from __future__ import annotations

import json
import importlib.util
import socket
import sqlite3
import tempfile
import time
import unittest
from contextlib import closing
from unittest import mock
from pathlib import Path

from language_learning.errors import LanguageNotFoundError, LanguageValidationError
from language_learning.jobs import LanguageJobManager
from language_learning.analysis.norwegian_bokmal import NorwegianBokmalStanzaAnalyzer
from language_learning.schemas import AnalyzerHealthState
from language_learning.service import LanguageService
from language_learning.store import LanguageStore
from language_learning.reference_core import ReferenceStore
from language_learning.reference_core.fixture_importer import import_fixture
from language_learning.reference_core.service import ReferenceLexiconService
from tests.language_phase2_fakes import FakeAnalyzer, FakeFrequencyProvider, registry_for


class LanguageGenerationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = LanguageStore(Path(self.temp.name) / "language.sqlite")
        self.analyzer = FakeAnalyzer()
        self.service = LanguageService(
            self.store,
            analyzer_registry=registry_for(self.analyzer),
            frequency_provider=FakeFrequencyProvider(),
        )
        self.service.initialize()
        self.profile = self.service.ensure_bokmal_profile()["profile"]
        self.manager = LanguageJobManager(self.service, poll_interval=0.01)
        self.job = self.service.upsert_lemma(self.profile["id"], "jobb", part_of_speech="NOUN")["lemma"]
        self.service.update_knowledge(self.job["id"], {"knowledgeStatus": "KNOWN"})
        self.weak = self.service.upsert_lemma(self.profile["id"], "svak", part_of_speech="ADJ")["lemma"]
        self.service.update_knowledge(self.weak["id"], {"knowledgeStatus": "LEARNING", "recognition": 1})

    def tearDown(self):
        self.manager.stop()
        self.temp.cleanup()

    def request(self, **overrides):
        payload = {"length": 200, "difficultyPreset": "BALANCED", "explicitTargetLemmaIds": [self.job["id"]]}
        payload.update(overrides)
        return self.service.create_generation_request(self.profile["id"], payload)["data"]

    def candidate(self, request_id, text="jobb jobben"):
        raw = json.dumps({"title": "Arbeid", "text": text}, ensure_ascii=False)
        return self.service.import_generation_candidate(request_id, {"response": raw, "providerLabel": "manual"})["data"]["candidate"]

    def wait_candidate(self, candidate_id):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            row = self.service.get_generation_candidate(candidate_id)["data"]["candidate"]
            if row["status"] not in {"QUEUED", "ANALYZING"}:
                return row
            time.sleep(0.01)
        self.fail("candidate analysis did not finish")

    def wait_job(self, job_id):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            row = self.service.get_analysis_job(job_id)["data"]["job"]
            if row["state"] not in {"QUEUED", "RUNNING"}:
                return row
            time.sleep(0.01)
        self.fail("accepted analysis job did not finish")

    def test_context_pack_is_versioned_deterministic_bounded_and_private(self):
        first = self.request()
        second = self.request()
        self.assertEqual(first["request"]["promptFingerprint"], second["request"]["promptFingerprint"])
        files = first["contextPack"]["files"]
        self.assertEqual(set(files), {"prompt.md", "generation-spec.json", "known-vocabulary.txt", "focus-vocabulary.json", "metadata.json"})
        self.assertEqual(first["contextPack"]["formatVersion"], "language-generation-context/v1")
        self.assertEqual(files["generation-spec.json"]["newLexicalItemBudget"], 10)
        self.assertEqual(files["focus-vocabulary.json"]["items"][0]["category"], "EXPLICIT")
        self.assertIn("jobb", files["prompt.md"])
        self.assertIn("Known vocabulary guidance", files["prompt.md"])
        serialized = json.dumps(first)
        for forbidden in ("apiKey", ".sqlite", "filesystem", "session history"):
            self.assertNotIn(forbidden, serialized)

    def test_reference_aware_v2_freezes_bounded_fingerprint_and_preserves_v1(self):
        reference_path = Path(self.temp.name) / "reference.sqlite"
        reference_store = ReferenceStore(reference_path)
        import_fixture(
            reference_store,
            Path(__file__).parent / "fixtures" / "language" / "reference" / "reference_v1.json",
        )
        reference_job = reference_store.upsert_lexical_unit(
            language_code="nb", unit_type="LEMMA", canonical_form="jobb", part_of_speech="NOUN",
            identity_qualifier="generation-test",
        )
        reference_store.link_source(
            reference_job.id, source_id="fixture-newspaper", source_local_id="generation-jobb"
        )
        reference_store.add_frequency(
            reference_job.id, source_id="fixture-newspaper", metric_type="SOURCE_LEARNER_RANK",
            observation_key="generation-kelly", rank=250,
        )
        self.service.attach_reference_lexicon_service(ReferenceLexiconService(reference_path))

        legacy = self.request(referenceEnrichment=False)
        first = self.request(referenceEnrichment=True)
        second = self.request(referenceEnrichment=True)
        self.assertEqual(legacy["contextPack"]["formatVersion"], "language-generation-context/v1")
        self.assertEqual(legacy["request"]["promptVersion"], "language-generation-prompt/v1")
        self.assertNotIn("reference-facts.json", legacy["contextPack"]["files"])
        self.assertEqual(first["contextPack"]["formatVersion"], "language-generation-context/v2")
        self.assertEqual(first["request"]["selectionRuleVersion"], "language-generation-targets/v2")
        self.assertEqual(first["request"]["promptVersion"], "language-generation-prompt/v2")
        self.assertEqual(first["request"]["promptFingerprint"], second["request"]["promptFingerprint"])
        reference = first["contextPack"]["files"]["reference-facts.json"]
        self.assertEqual(reference["formatVersion"], "language-generation-reference-facts/v1")
        self.assertLessEqual(len(reference["items"]), 12)
        matched_item = next(item for item in reference["items"] if item["userLemmaId"] == self.job["id"])
        self.assertEqual(matched_item["resolution"]["status"], "MATCHED")
        learner_rank = next(
            item for item in matched_item["frequencyEvidence"]
            if item["metricType"] == "SOURCE_LEARNER_RANK"
        )
        self.assertEqual(learner_rank["label"], "Learner rank")
        self.assertLess(len(json.dumps(reference)), 40_000)
        self.assertNotIn(str(reference_path), json.dumps(first))

        with closing(sqlite3.connect(reference_path)) as connection:
            connection.execute(
                "UPDATE reference_sources SET version='2' WHERE source_id='fixture-newspaper'"
            )
            connection.commit()
        changed = self.request(referenceEnrichment=True)
        self.assertNotEqual(
            first["contextPack"]["files"]["metadata.json"]["referenceEnrichment"]["referenceFingerprint"],
            changed["contextPack"]["files"]["metadata.json"]["referenceEnrichment"]["referenceFingerprint"],
        )
        self.assertNotEqual(first["request"]["promptFingerprint"], changed["request"]["promptFingerprint"])

    def test_presets_budget_validation_and_empty_profile(self):
        for preset, expected in (("VERY_EASY", 99), ("EASY", 97), ("BALANCED", 95), ("CHALLENGING", 90)):
            result = self.request(difficultyPreset=preset, explicitTargetLemmaIds=[])
            spec = result["contextPack"]["files"]["generation-spec.json"]
            self.assertEqual(spec["targetTokenCoveragePercent"], expected)
        empty = self.service.create_profile({"languageCode": "nn", "locale": "nn-NO", "displayName": "Nynorsk"})["data"]["profile"]
        result = self.service.create_generation_request(empty["id"], {"length": 100, "difficultyPreset": "EASY"})["data"]
        self.assertEqual(result["request"]["targetSnapshot"]["items"], [])
        with self.assertRaises(LanguageValidationError):
            self.request(length=10)

    def test_import_validation_plain_fallback_unicode_and_history(self):
        request_id = self.request()["request"]["id"]
        first = self.candidate(request_id, "Ærlig jobb")
        self.assertEqual(first["attemptNumber"], 1)
        plain = self.service.import_generation_candidate(request_id, {"response": "<script>ikke html</script> Ærlig", "treatAsPlainText": True})["data"]["candidate"]
        self.assertEqual(plain["importFormat"], "PLAIN_TEXT")
        self.assertIn("<script>", plain["extractedText"])
        self.assertEqual(plain["attemptNumber"], 2)
        self.assertEqual(len(self.service.list_generation_candidates(request_id)["data"]["items"]), 2)
        for raw in ('{"title":', "ordinary text"):
            with self.assertRaises(LanguageValidationError):
                self.service.import_generation_candidate(request_id, {"response": raw})
        with self.assertRaises(LanguageValidationError):
            self.service.import_generation_candidate(request_id, {"response": "x" * (256 * 1024 + 1), "treatAsPlainText": True})

    def test_analysis_uses_frozen_snapshot_and_does_not_mutate_learning(self):
        request_id = self.request()["request"]["id"]
        # Later knowledge changes must not rewrite generation-time semantics.
        self.service.update_knowledge(self.job["id"], {"knowledgeStatus": "NEW"})
        candidate = self.candidate(request_id, "jobb jobben xyzzy")
        with self.store.connection() as connection:
            before = tuple(connection.execute("SELECT COUNT(*) FROM vocabulary_lemmas").fetchone())
        self.service.analyze_generation_candidate(candidate["id"], {})
        result = self.wait_candidate(candidate["id"])
        self.assertIn(result["status"], {"IN_TOLERANCE", "OUT_OF_TOLERANCE"})
        report = result["analysis"]
        self.assertEqual(report["snapshotBasis"], "FROZEN_AT_REQUEST_CREATION")
        self.assertEqual(report["coverage"]["coveredTokens"], 2)
        self.assertGreater(report["coverage"]["uniqueEligibleLemmas"], 1)
        self.assertEqual(report["targetUsage"][0]["count"], 2)
        with self.store.connection() as connection:
            self.assertEqual(tuple(connection.execute("SELECT COUNT(*) FROM vocabulary_lemmas").fetchone()), before)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM exposure_events").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM study_sessions").fetchone()[0], 0)

    def test_revision_is_manual_and_acceptance_is_idempotent_reader_flow(self):
        request_id = self.request()["request"]["id"]
        candidate = self.candidate(request_id, "jobb xyzzy")
        self.service.analyze_generation_candidate(candidate["id"], {})
        analyzed = self.wait_candidate(candidate["id"])
        calls = self.analyzer.calls
        revision = self.service.generation_revision_prompt(candidate["id"])["data"]
        self.assertIn("manual revision request", revision["prompt"])
        self.assertEqual(self.analyzer.calls, calls)
        accepted = self.service.accept_generation_candidate(candidate["id"], {})["data"]
        duplicate = self.service.accept_generation_candidate(candidate["id"], {})["data"]
        self.assertTrue(accepted["created"])
        self.assertFalse(duplicate["created"])
        self.assertEqual(accepted["document"]["id"], duplicate["document"]["id"])
        self.assertEqual(accepted["document"]["sourceType"], "GENERATED_MANUAL_LLM")
        job = self.wait_job(accepted["job"]["id"])
        self.assertEqual(job["state"], "COMPLETED")
        self.assertEqual(self.analyzer.calls, calls, "accepted Reader commit reuses candidate analysis")
        detail = self.service.get_text(accepted["document"]["id"])["data"]
        self.assertEqual(detail["document"]["processingState"], "ANALYZED")
        with self.store.connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM exposure_events").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM study_sessions").fetchone()[0], 0)

    def test_series_continuation_uses_frozen_previous_episode_and_saves_next_episode(self):
        profile_id = self.profile["id"]
        series = self.service.create_reading_series(profile_id, {
            "title": "Lørdag i byen", "premise": "Maja investigates a missing letter.",
            "continuityNotes": "Maja knows Erik. They meet at the harbor.",
        })["data"]["series"]
        first = self.service.create_text_draft({
            "languageProfileId": profile_id, "title": "Det første brevet",
            "rawText": "Maja fant et brev ved havnen. Erik så en ukjent båt.",
        })["data"]["text"]
        self.service.assign_text_to_series(first["id"], {"seriesId": series["id"]})
        request = self.request(
            storyMode="CONTINUE", seriesId=series["id"], previousTextId=first["id"],
            episodeDirection="Maja follows the boat", avoidRepeating="Do not find another letter",
            pacing="TENSE", ending="CLIFFHANGER",
        )
        prompt = request["contextPack"]["files"]["prompt.md"]
        self.assertIn("language-generation-context/v3", request["contextPack"]["formatVersion"])
        for expected in ("Maja fant et brev", "Maja knows Erik", "Maja follows the boat",
                         "Do not find another letter", "Do not retell", "Familiar vocabulary may recur"):
            self.assertIn(expected, prompt)
        self.service.update_reading_series(series["id"], {"continuityNotes": "Later notes"})
        frozen = self.service.get_generation_context(request["request"]["id"])["data"]["contextPack"]["files"]["prompt.md"]
        self.assertEqual(frozen, prompt)
        self.assertEqual(request["contextPack"]["files"]["generation-spec.json"]["story"]["previousTextId"], first["id"])
        candidate = self.candidate(request["request"]["id"], "Maja og Erik fulgte båten. De fant et spor.")
        self.service.analyze_generation_candidate(candidate["id"], {})
        self.wait_candidate(candidate["id"])
        revision = self.service.generation_revision_prompt(candidate["id"])["data"]["prompt"]
        self.assertIn("Maja fant et brev", revision)
        self.assertIn("Do not restart or retell", revision)
        accepted = self.service.accept_generation_candidate(candidate["id"], {})["data"]
        episodes = self.service.list_reading_series(profile_id)["data"]["items"][0]["episodes"]
        self.assertEqual([episode["episodeNumber"] for episode in episodes], [1, 2])
        self.assertEqual(episodes[1]["textDocumentId"], accepted["document"]["id"])
        listed = self.service.list_texts(profile_id)["data"]["items"]
        self.assertEqual(next(item for item in listed if item["id"] == accepted["document"]["id"])["seriesId"], series["id"])
        with self.assertRaises(LanguageValidationError):
            self.request(storyMode="CONTINUE", seriesId=series["id"], previousTextId=None)

    def test_new_series_request_saves_first_episode_after_acceptance(self):
        series = self.service.create_reading_series(self.profile["id"], {
            "title": "Harbor", "premise": "Maja searches for her brother",
        })["data"]["series"]
        request = self.request(storyMode="NEW", seriesId=series["id"], episodeDirection="Introduce Maja")
        self.assertIn("Write the first episode", request["contextPack"]["files"]["prompt.md"])
        candidate = self.candidate(request["request"]["id"], "Maja kom til havnen. Hun så Erik.")
        self.service.analyze_generation_candidate(candidate["id"], {})
        self.wait_candidate(candidate["id"])
        result = self.service.accept_generation_candidate(candidate["id"], {})["data"]
        detail = self.service.get_text(result["document"]["id"])["data"]["document"]
        self.assertEqual(detail["seriesId"], series["id"])
        self.assertEqual(detail["episodeNumber"], 1)

    def test_series_ownership_and_previous_episode_are_validated(self):
        other = self.service.create_profile({"languageCode": "nn", "locale": "nn-NO", "displayName": "Other"})["data"]["profile"]
        foreign = self.service.create_reading_series(other["id"], {"title": "Private"})["data"]["series"]
        with self.assertRaises(LanguageNotFoundError):
            self.request(storyMode="NEW", seriesId=foreign["id"])
        local = self.service.create_reading_series(self.profile["id"], {"title": "Local"})["data"]["series"]
        unrelated = self.service.create_text_draft({"languageProfileId": self.profile["id"], "title": "Unrelated", "rawText": "Hei."})["data"]["text"]
        with self.assertRaises(LanguageNotFoundError):
            self.request(storyMode="CONTINUE", seriesId=local["id"], previousTextId=unrelated["id"])

    def test_worker_recovers_candidate_without_second_worker(self):
        request_id = self.request()["request"]["id"]
        candidate = self.candidate(request_id)
        with self.store.connection() as connection:
            connection.execute("UPDATE generation_candidates SET status='ANALYZING',analysis_attempt_count=1 WHERE id=?", (candidate["id"],))
        recovery = self.manager.initialize()
        self.assertEqual(recovery["generationRequeued"], 1)
        self.assertEqual(self.manager.status()["workerCount"], 1)


@unittest.skipUnless(importlib.util.find_spec("stanza"), "Stanza package is explicitly provisioned")
class RealStanzaPhase7IntegrationTests(unittest.TestCase):
    def test_persisted_candidates_reuse_one_offline_pipeline(self):
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
                request_id = service.create_generation_request(profile["id"], {"length": 100, "difficultyPreset": "BALANCED"})["data"]["request"]["id"]
                candidates = []
                for title, text in (("Første", "Jeg har en jobb. Jobben er viktig."), ("Andre", "Hun jobber hjemme og leser en bok.")):
                    candidates.append(service.import_generation_candidate(request_id, {"response": json.dumps({"title": title, "text": text}, ensure_ascii=False)})["data"]["candidate"])
                with mock.patch("stanza.download", side_effect=AssertionError("download attempted")), \
                     mock.patch("stanza.pipeline.core.download_resources_json", side_effect=AssertionError("resource download attempted")), \
                     mock.patch("stanza.pipeline.core.download_models", side_effect=AssertionError("model download attempted")), \
                     mock.patch("socket.create_connection", side_effect=AssertionError("network attempted")):
                    service.analyze_generation_candidate(candidates[0]["id"], {})
                    first = self._wait(service, candidates[0]["id"])
                    self.assertIn(first["status"], {"IN_TOLERANCE", "OUT_OF_TOLERANCE"})
                    analyzer = service.analyzer_registry.get("stanza-nb-bokmaal")
                    pipeline = analyzer._pipeline
                    service.analyze_generation_candidate(candidates[1]["id"], {})
                    second = self._wait(service, candidates[1]["id"])
                    self.assertIn(second["status"], {"IN_TOLERANCE", "OUT_OF_TOLERANCE"})
                    self.assertIs(analyzer._pipeline, pipeline)
                with store.connection() as connection:
                    self.assertEqual(connection.execute("SELECT COUNT(*) FROM exposure_events").fetchone()[0], 0)
                    self.assertEqual(connection.execute("SELECT COUNT(*) FROM knowledge_events").fetchone()[0], 0)
            finally:
                manager.stop()

    @staticmethod
    def _wait(service, candidate_id):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            row = service.get_generation_candidate(candidate_id)["data"]["candidate"]
            if row["status"] not in {"QUEUED", "ANALYZING"}:
                return row
            time.sleep(0.02)
        raise AssertionError("real Stanza candidate did not finish")


if __name__ == "__main__":
    unittest.main()
