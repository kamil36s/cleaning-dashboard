from __future__ import annotations

import importlib.util
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from language_learning.analysis.base import AnalyzerUnavailableError
from language_learning.analysis.norwegian_bokmal import NorwegianBokmalStanzaAnalyzer
from language_learning.analysis.registry import AnalyzerRegistry
from language_learning.errors import LanguageConflictError
from language_learning.jobs import LanguageJobManager
from language_learning.providers.frequency import WordfreqFrequencyProvider
from language_learning.service import LanguageService
from language_learning.store import LanguageStore
from language_learning.schemas import AnalyzerHealthState

from tests.language_phase2_fakes import (
    FakeAnalyzer,
    FakeFrequencyProvider,
    registry_for,
    wait_for_job,
)


class LanguageJobTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = LanguageStore(
            Path(self.temp.name) / "language.sqlite",
            backup_directory=Path(self.temp.name) / "backups",
        )
        self.analyzer = FakeAnalyzer()
        self.frequency = FakeFrequencyProvider()
        self.service = LanguageService(
            self.store,
            analyzer_registry=registry_for(self.analyzer),
            frequency_provider=self.frequency,
        )
        self.service.initialize()
        self.profile = self.service.ensure_bokmal_profile()["profile"]
        self.manager = LanguageJobManager(self.service, poll_interval=0.01)

    def tearDown(self) -> None:
        self.manager.stop()
        self.temp.cleanup()

    def draft(self, raw_text: str, title: str = "Phase 2") -> dict:
        return self.service.create_text_draft({
            "languageProfileId": self.profile["id"],
            "title": title,
            "rawText": raw_text,
        })["data"]["text"]

    def analyze(self, text_id: str) -> dict:
        queued = self.service.enqueue_analysis(text_id, {})["data"]["job"]
        return wait_for_job(self.service, queued["id"])

    def test_registry_is_lazy_and_reuses_one_analyzer_instance(self) -> None:
        created: list[FakeAnalyzer] = []
        registry = AnalyzerRegistry()
        registry.register(
            FakeAnalyzer.analyzer_id,
            FakeAnalyzer.implementation_version,
            lambda: created.append(FakeAnalyzer()) or created[-1],
        )
        self.assertFalse(registry.describe(FakeAnalyzer.analyzer_id)["loaded"])
        first = registry.get(FakeAnalyzer.analyzer_id)
        second = registry.get(FakeAnalyzer.analyzer_id)
        self.assertIs(first, second)
        self.assertEqual(len(created), 1)
        self.assertTrue(registry.describe(FakeAnalyzer.analyzer_id)["loaded"])

    def test_idle_worker_start_does_not_construct_analyzer(self) -> None:
        self.assertFalse(
            self.service.analyzer_registry.describe(FakeAnalyzer.analyzer_id)["loaded"]
        )
        self.manager.start()
        self.assertFalse(
            self.service.analyzer_registry.describe(FakeAnalyzer.analyzer_id)["loaded"]
        )

    def test_analysis_persists_exact_offsets_shared_lemmas_and_frequency_without_learning(self) -> None:
        raw = "jobb jobben jobber jobbene.\nÆrlig " + chr(0x1F60A)
        text = self.draft(raw)
        job = self.analyze(text["id"])
        self.assertEqual(job["state"], "COMPLETED")

        detail = self.service.get_text(text["id"])["data"]
        self.assertEqual(detail["document"]["rawText"], raw)
        self.assertEqual(detail["document"]["processingState"], "ANALYZED")
        for token in detail["tokens"]:
            self.assertEqual(
                token["surface"],
                raw[token["sourceStart"] : token["sourceEnd"]],
            )
        job_tokens = detail["tokens"][:4]
        self.assertEqual(len({row["selectedLemmaId"] for row in job_tokens}), 1)
        self.assertTrue(all(row["resolutionState"] == "MODEL_SELECTED" for row in job_tokens))
        self.assertEqual(detail["coverage"]["eligibleTokens"], 5)
        self.assertEqual(detail["coverage"]["unknownTokens"], 5)
        self.assertEqual(detail["coverage"]["nonLexicalTokens"], 2)
        self.assertEqual(detail["analysisRuns"][0]["analyzerId"], FakeAnalyzer.analyzer_id)
        self.assertEqual(detail["analysisRuns"][0]["frequencyProviderId"], "wordfreq")

        with self.store.connection() as connection:
            shared = connection.execute(
                "SELECT id FROM vocabulary_lemmas WHERE lemma_normalized='jobb' AND part_of_speech='NOUN'"
            ).fetchall()
            self.assertEqual(len(shared), 1)
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM lemma_knowledge WHERE lemma_id=?", (shared[0]["id"],)
            ).fetchone()[0], 1)
            frequency = connection.execute(
                "SELECT * FROM lemma_frequency WHERE lemma_id=?", (shared[0]["id"],)
            ).fetchone()
            self.assertNotIn("rank", frequency.keys())
            self.assertEqual(frequency["metric"], "ZIPF_FREQUENCY")
            self.assertEqual(frequency["provider_id"], "wordfreq")
            self.assertEqual(frequency["provider_version"], "3.1.1-test")
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM exposure_events").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM study_sessions").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM knowledge_events").fetchone()[0], 0)
            states = connection.execute(
                "SELECT DISTINCT knowledge_status,total_exposures FROM lemma_knowledge"
            ).fetchall()
            self.assertEqual({tuple(row) for row in states}, {("NEW", 0)})

    def test_unicode_code_point_offsets_and_unresolved_states_survive_persistence(self) -> None:
        raw = (
            chr(0x00C6) + "rlig " + chr(0x00F8) + "l p" + chr(0x00E5)
            + " " + chr(0x00AB) + "jobb" + chr(0x00BB) + " "
            + chr(0x1F60A) + " etter\n  tvetydig xyzzy"
        )
        text = self.draft(raw)
        self.assertEqual(self.analyze(text["id"])["state"], "COMPLETED")
        detail = self.service.get_text(text["id"])["data"]
        self.assertEqual(detail["document"]["rawText"], raw)
        for token in detail["tokens"]:
            self.assertEqual(token["offsetUnit"], "UNICODE_CODE_POINT")
            self.assertEqual(
                raw[token["sourceStart"] : token["sourceEnd"]], token["surface"]
            )
        ambiguous = next(row for row in detail["tokens"] if row["surface"] == "tvetydig")
        unresolved = next(row for row in detail["tokens"] if row["surface"] == "xyzzy")
        self.assertIsNone(ambiguous["selectedLemmaId"])
        self.assertEqual(ambiguous["resolutionState"], "AMBIGUOUS")
        self.assertIsNone(unresolved["selectedLemmaId"])
        self.assertEqual(unresolved["resolutionState"], "UNRESOLVED")
        self.assertEqual(detail["coverage"]["ambiguousTokens"], 2)
        with self.store.connection() as connection:
            candidates = connection.execute(
                "SELECT COUNT(*) FROM form_lemma_links WHERE form_id=?",
                (ambiguous["surfaceFormId"],),
            ).fetchone()[0]
        self.assertEqual(candidates, 2)

    def test_identical_completed_analysis_is_reused(self) -> None:
        text = self.draft("jobbene")
        first = self.analyze(text["id"])
        calls = self.analyzer.calls
        second = self.service.enqueue_analysis(text["id"], {})["data"]
        self.assertFalse(second["created"])
        self.assertTrue(second["reused"])
        self.assertEqual(second["job"]["id"], first["id"])
        self.assertEqual(second["job"]["state"], "COMPLETED")
        self.assertEqual(self.analyzer.calls, calls)

    def test_frequency_is_lemma_first_with_surface_fallback_and_never_has_rank(self) -> None:
        self.frequency.scores = {"jobb": 0.0, "jobbene": 4.25}
        analysis = self.analyzer.analyze("jobbene", language_code="nb")
        rows = self.service.frequency_rows_for_analysis(analysis)
        frequency = rows["jobb|NOUN"]
        self.assertEqual(self.frequency.calls, [("jobb", "nb"), ("jobbene", "nb")])
        self.assertEqual(frequency["match_kind"], "SURFACE")
        self.assertEqual(frequency["lookup_value"], "jobbene")
        self.assertEqual(frequency["score"], 4.25)

        real = WordfreqFrequencyProvider().lookup("jobb", language_code="nb")
        self.assertEqual(real.metric, "ZIPF_FREQUENCY")
        self.assertGreater(real.score, 0)
        self.assertIsNone(real.rank)
        self.assertEqual(real.source.source_id, "wordfreq")

    def test_running_cancellation_is_cooperative_and_never_commits(self) -> None:
        entered = threading.Event()
        release = threading.Event()
        self.analyzer.entered = entered
        self.analyzer.release = release
        text = self.draft("jobbene")
        queued = self.service.enqueue_analysis(text["id"], {})["data"]["job"]
        self.assertTrue(entered.wait(timeout=3))
        cancelling = self.service.cancel_analysis_job(queued["id"])["data"]["job"]
        self.assertTrue(cancelling["cancelRequested"])
        self.assertEqual(cancelling["stage"], "CANCELLING")
        release.set()
        terminal = wait_for_job(self.service, queued["id"])
        self.assertEqual(terminal["state"], "CANCELLED")
        detail = self.service.get_text(text["id"])["data"]
        self.assertEqual(detail["document"]["processingState"], "DRAFT")
        self.assertEqual(detail["tokens"], [])
        self.assertEqual(detail["analysisRuns"], [])

    def test_analyzer_unavailable_is_safe_and_leaves_draft_recoverable(self) -> None:
        self.analyzer.failure = AnalyzerUnavailableError(
            f"private model path: {self.temp.name}"
        )
        text = self.draft("jobbene")
        job = self.analyze(text["id"])
        self.assertEqual(job["state"], "FAILED")
        self.assertEqual(job["errorCode"], "canonical_analyzer_unavailable")
        self.assertNotIn(self.temp.name, job["errorMessage"])
        detail = self.service.get_text(text["id"])["data"]
        self.assertEqual(detail["document"]["rawText"], "jobbene")
        self.assertEqual(detail["document"]["processingState"], "ANALYSIS_FAILED")
        self.assertEqual(detail["tokens"], [])
        with self.store.connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM vocabulary_lemmas").fetchone()[0], 0)
        self.assertEqual(self.service.health()["data"]["status"], "READY")
        self.analyzer.failure = None
        retry = self.analyze(text["id"])
        self.assertEqual(retry["state"], "COMPLETED")
        self.assertNotEqual(retry["id"], job["id"])

    def test_queue_limit_wrong_profile_and_missing_document_are_rejected(self) -> None:
        first = self.draft("jobb", "first")
        second = self.draft("jobben", "second")
        first_values = self.service._analysis_job_values(first["id"], job_type="ANALYZE")
        second_values = self.service._analysis_job_values(second["id"], job_type="ANALYZE")
        self.store.create_analysis_job(first_values, max_pending=1)
        with self.assertRaisesRegex(LanguageConflictError, "queue is full"):
            self.store.create_analysis_job(second_values, max_pending=1)
        queued = self.store.create_analysis_job(first_values, max_pending=1)[0]
        cancelled = self.store.request_analysis_job_cancellation(queued["id"])
        self.assertEqual(cancelled["state"], "CANCELLED")

        other = self.service.create_profile({
            "languageCode": "sv", "locale": "sv-SE", "displayName": "Swedish"
        })["data"]["profile"]
        invalid = dict(second_values)
        invalid["language_profile_id"] = other["id"]
        with self.assertRaisesRegex(LanguageConflictError, "another language profile"):
            self.store.create_analysis_job(invalid)
        with self.assertRaisesRegex(Exception, "not found"):
            self.service.enqueue_analysis("0" * 32, {})

    def test_restart_recovery_requeues_cancels_and_bounds_retries(self) -> None:
        jobs: list[dict] = []
        for index in range(3):
            text = self.draft(f"jobb {index}", title=str(index))
            values = self.service._analysis_job_values(text["id"], job_type="ANALYZE")
            jobs.append(self.store.create_analysis_job(values)[0])
        first = self.store.claim_next_analysis_job()
        second = self.store.claim_next_analysis_job()
        third = self.store.claim_next_analysis_job()
        self.store.request_analysis_job_cancellation(second["id"])
        with self.store.connection() as connection:
            connection.execute(
                "UPDATE language_jobs SET attempt_count=3 WHERE id=?", (third["id"],)
            )

        recovered = self.manager.initialize()

        self.assertEqual(recovered, {"requeued": 1, "cancelled": 1, "failed": 1})
        self.assertEqual(self.store.get_analysis_job(first["id"])["state"], "QUEUED")
        self.assertEqual(self.store.get_analysis_job(second["id"])["state"], "CANCELLED")
        exhausted = self.store.get_analysis_job(third["id"])
        self.assertEqual(exhausted["state"], "FAILED")
        self.assertEqual(exhausted["error_code"], "language_job_recovery_exhausted")

    def test_worker_stop_leaves_running_job_for_restart_recovery(self) -> None:
        entered = threading.Event()
        release = threading.Event()
        self.analyzer.entered = entered
        self.analyzer.release = release
        text = self.draft("jobbene")
        job_id = self.service.enqueue_analysis(text["id"], {})["data"]["job"]["id"]
        self.assertTrue(entered.wait(timeout=3))
        self.manager.stop(timeout=0.01)
        release.set()
        self.manager.stop(timeout=3)
        self.assertEqual(self.store.get_analysis_job(job_id)["state"], "RUNNING")

        self.manager.start()
        terminal = wait_for_job(self.service, job_id)
        self.assertEqual(terminal["state"], "COMPLETED")
        self.assertEqual(terminal["attemptCount"], 2)

    def test_reanalysis_preview_is_non_mutating_and_commit_preserves_manual_lock(self) -> None:
        text = self.draft("jobbene")
        initial = self.analyze(text["id"])
        before = self.service.get_text(text["id"])["data"]
        form_id = before["tokens"][0]["surfaceFormId"]
        manual = self.service.upsert_lemma(
            self.profile["id"], "manuell", part_of_speech="VERB"
        )["lemma"]
        self.service.lock_form_lemma_mapping(
            self.profile["id"], form_id, manual["id"], source="USER_CORRECTION"
        )
        self.analyzer.variant = "changed"

        preview_job = self.service.enqueue_reanalysis_preview(text["id"], {})["data"]["job"]
        preview = wait_for_job(self.service, preview_job["id"])
        self.assertEqual(preview["state"], "COMPLETED")
        self.assertNotIn("analysisDocument", preview["result"])
        self.assertEqual(preview["result"]["summary"]["manualLockConflictsProtected"], 1)
        self.assertEqual(
            self.service.get_text(text["id"])["data"]["tokens"][0]["selectedLemmaId"],
            before["tokens"][0]["selectedLemmaId"],
        )
        calls_after_preview = self.analyzer.calls

        commit_job = self.service.enqueue_reanalysis_commit(
            text["id"], {"previewJobId": preview["id"]}
        )["data"]["job"]
        commit = wait_for_job(self.service, commit_job["id"])
        self.assertEqual(commit["state"], "COMPLETED")
        self.assertEqual(self.analyzer.calls, calls_after_preview)
        after = self.service.get_text(text["id"])["data"]
        token = after["tokens"][0]
        self.assertEqual(token["selectedLemmaId"], manual["id"])
        self.assertEqual(token["resolutionState"], "MODEL_SELECTED")
        self.assertEqual(token["partOfSpeech"], "VERB")
        self.assertIn("manual_lock_selected", token["provenance"])
        evidence = token["mappingEvidenceReference"]
        self.assertTrue(evidence["manualLockProtected"])
        self.assertTrue(evidence["analyzerDisagreed"])
        self.assertEqual(evidence["selectionProvenance"], "MANUAL_LOCK")
        self.assertEqual(evidence["effectiveResolution"], "MANUAL_SELECTED")
        self.assertEqual(len(after["analysisRuns"]), 2)
        self.assertEqual(after["analysisRuns"][0]["id"], initial["result"]["analysisRunId"])

    def test_stale_preview_is_rejected_after_manual_mapping_change(self) -> None:
        text = self.draft("jobbene")
        self.analyze(text["id"])
        preview_id = self.service.enqueue_reanalysis_preview(text["id"], {})["data"]["job"]["id"]
        preview = wait_for_job(self.service, preview_id)
        detail = self.service.get_text(text["id"])["data"]
        manual = self.service.upsert_lemma(
            self.profile["id"], "sen", part_of_speech="ADJ"
        )["lemma"]
        self.service.lock_form_lemma_mapping(
            self.profile["id"], detail["tokens"][0]["surfaceFormId"], manual["id"], source="USER"
        )
        with self.assertRaisesRegex(LanguageConflictError, "stale"):
            self.service.enqueue_reanalysis_commit(
                text["id"], {"previewJobId": preview["id"]}
            )

    def test_failed_reanalysis_commit_rolls_back_previous_analysis(self) -> None:
        text = self.draft("jobbene")
        self.analyze(text["id"])
        before = self.service.get_text(text["id"])["data"]
        before_token = dict(before["tokens"][0])
        self.analyzer.variant = "changed"
        preview_id = self.service.enqueue_reanalysis_preview(text["id"], {})["data"]["job"]["id"]
        preview = wait_for_job(self.service, preview_id)
        with self.store.connection() as connection:
            connection.execute(
                "CREATE TRIGGER fail_phase2_token_insert BEFORE INSERT ON text_tokens "
                "BEGIN SELECT RAISE(ABORT, 'synthetic phase2 failure'); END"
            )
        commit_id = self.service.enqueue_reanalysis_commit(
            text["id"], {"previewJobId": preview["id"]}
        )["data"]["job"]["id"]
        commit = wait_for_job(self.service, commit_id)
        self.assertEqual(commit["state"], "FAILED")
        after = self.service.get_text(text["id"])["data"]
        self.assertEqual(after["document"]["processingState"], "ANALYZED")
        self.assertEqual(after["tokens"][0]["id"], before_token["id"])
        self.assertEqual(after["tokens"][0]["selectedLemmaId"], before_token["selectedLemmaId"])
        self.assertEqual(len([run for run in after["analysisRuns"] if run["state"] == "COMPLETED"]), 1)
        with self.store.connection() as connection:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_failure_after_analyzer_output_persists_no_partial_lexical_rows(self) -> None:
        text = self.draft("jobbene")
        with mock.patch.object(
            self.frequency, "lookup", side_effect=RuntimeError("synthetic frequency failure")
        ):
            job = self.analyze(text["id"])
        self.assertEqual(job["state"], "FAILED")
        with self.store.connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM vocabulary_lemmas").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM surface_forms").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM text_tokens").fetchone()[0], 0)
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_failure_during_final_job_update_rolls_back_reanalysis(self) -> None:
        text = self.draft("jobbene")
        self.analyze(text["id"])
        before = self.service.get_text(text["id"])["data"]
        self.analyzer.variant = "changed"
        preview_id = self.service.enqueue_reanalysis_preview(text["id"], {})["data"]["job"]["id"]
        preview = wait_for_job(self.service, preview_id)
        with self.store.connection() as connection:
            connection.execute(
                "CREATE TRIGGER fail_phase2_final_job_update "
                "BEFORE UPDATE OF state ON language_jobs "
                "WHEN NEW.job_type='REANALYSIS_COMMIT' AND NEW.state='COMPLETED' "
                "BEGIN SELECT RAISE(ABORT, 'synthetic final update failure'); END"
            )
        commit_id = self.service.enqueue_reanalysis_commit(
            text["id"], {"previewJobId": preview["id"]}
        )["data"]["job"]["id"]
        failed = wait_for_job(self.service, commit_id)
        self.assertEqual(failed["state"], "FAILED")
        after = self.service.get_text(text["id"])["data"]
        self.assertEqual(after["tokens"][0]["id"], before["tokens"][0]["id"])
        self.assertEqual(after["tokens"][0]["selectedLemmaId"], before["tokens"][0]["selectedLemmaId"])
        self.assertEqual(len([row for row in after["analysisRuns"] if row["state"] == "COMPLETED"]), 1)


@unittest.skipUnless(importlib.util.find_spec("stanza"), "Stanza package is explicitly provisioned")
class RealStanzaPhase2IntegrationTests(unittest.TestCase):
    def test_persisted_jobs_reuse_one_offline_pipeline(self) -> None:
        probe = NorwegianBokmalStanzaAnalyzer()
        if probe.health().state is not AnalyzerHealthState.AVAILABLE:
            self.skipTest("The explicit Bokmal Stanza model is not provisioned")
        with tempfile.TemporaryDirectory() as directory:
            store = LanguageStore(Path(directory) / "language.sqlite")
            service = LanguageService(store)
            service.initialize()
            profile = service.ensure_bokmal_profile()["profile"]
            manager = LanguageJobManager(service, poll_interval=0.01)
            try:
                first = service.create_text_draft({
                    "languageProfileId": profile["id"],
                    "title": "Frozen forms",
                    "rawText": (
                        "Jeg har en jobb. Jobben er ny. Hun har to jobber. "
                        "Jobbene er viktige."
                    ),
                })["data"]["text"]
                second = service.create_text_draft({
                    "languageProfileId": profile["id"],
                    "title": "Reuse",
                    "rawText": "Jeg har en jobb, og jobbene er viktige.",
                })["data"]["text"]
                with mock.patch(
                    "stanza.download", side_effect=AssertionError("download attempted")
                ), mock.patch(
                    "stanza.pipeline.core.download_resources_json",
                    side_effect=AssertionError("resource download attempted"),
                ), mock.patch(
                    "stanza.pipeline.core.download_models",
                    side_effect=AssertionError("model download attempted"),
                ), mock.patch(
                    "socket.create_connection", side_effect=AssertionError("network attempted")
                ):
                    first_id = service.enqueue_analysis(first["id"], {})["data"]["job"]["id"]
                    self.assertEqual(wait_for_job(service, first_id, timeout=30)["state"], "COMPLETED")
                    analyzer = service.analyzer_registry.get("stanza-nb-bokmaal")
                    pipeline = analyzer._pipeline
                    self.assertIsNotNone(pipeline)
                    second_id = service.enqueue_analysis(second["id"], {})["data"]["job"]["id"]
                    self.assertEqual(wait_for_job(service, second_id, timeout=30)["state"], "COMPLETED")
                    self.assertIs(analyzer._pipeline, pipeline)

                detail = service.get_text(first["id"])["data"]
                word_tokens = [
                    row
                    for row in detail["tokens"]
                    if row["normalizedLookup"] in {"jobb", "jobben", "jobber", "jobbene"}
                ]
                self.assertEqual(len(word_tokens), 4)
                self.assertEqual(len({row["selectedLemmaId"] for row in word_tokens}), 1)
                with store.connection() as connection:
                    lemma = connection.execute(
                        "SELECT lemma_normalized,part_of_speech FROM vocabulary_lemmas "
                        "WHERE id=?", (word_tokens[0]["selectedLemmaId"],)
                    ).fetchone()
                self.assertEqual(tuple(lemma), ("jobb", "NOUN"))
            finally:
                manager.stop()


if __name__ == "__main__":
    unittest.main()
