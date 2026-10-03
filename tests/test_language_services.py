import tempfile
import unittest
from pathlib import Path
from unittest import mock

from language_learning.errors import LanguageConflictError, LanguageValidationError
from language_learning.service import MAX_ANALYSIS_TEXT_BYTES, LanguageService
from language_learning.store import EXPORT_VERSION, LanguageStore
from language_learning.schemas import text_fingerprint


class LanguageServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = LanguageStore(Path(self.temp.name) / "language.sqlite")
        self.service = LanguageService(self.store)
        self.service.initialize()
        self.profile = self.service.ensure_bokmal_profile()["profile"]

    def tearDown(self):
        self.temp.cleanup()

    def analyzed_reader_text(self):
        lemma = self.service.upsert_lemma(
            self.profile["id"], "jobb", part_of_speech="NOUN"
        )["lemma"]
        raw = "jobb jobben jobb"
        text = self.service.create_text_draft({
            "languageProfileId": self.profile["id"], "title": "Reader", "rawText": raw
        })["data"]["text"]
        sentence_id = "1" * 32
        tokens = []
        for index, (surface, start, end) in enumerate((
            ("jobb", 0, 4), ("jobben", 5, 11), ("jobb", 12, 16)
        )):
            form = self.service.upsert_surface_form(self.profile["id"], surface)["form"]
            self.service.upsert_form_lemma_mapping(
                self.profile["id"], form["id"], lemma["id"]
            )
            tokens.append({
                "id": f"{index + 2:032x}", "sentence_id": sentence_id,
                "token_order": index, "surface": surface, "source_start": start,
                "source_end": end, "token_kind": "WORD", "normalized_lookup": surface,
                "surface_form_id": form["id"], "selected_lemma_id": lemma["id"],
            })
        self.store.insert_text_structure(
            text["id"],
            sentences=[{
                "id": sentence_id, "sentence_order": 0, "source_start": 0,
                "source_end": len(raw), "exact_text": raw,
                "fingerprint": text_fingerprint(raw),
            }],
            tokens=tokens,
            analysis_run={
                "id": "f" * 32, "analyzer_id": "synthetic", "analyzer_version": "1",
                "contract_version": "language.analysis/v1", "state": "COMPLETED",
            },
        )
        with self.store.connection() as connection:
            connection.execute(
                "UPDATE text_documents SET processing_state='ANALYZED' WHERE id=?",
                (text["id"],),
            )
        return text, sentence_id, lemma

    def test_bokmal_seed_is_idempotent_and_explicit(self):
        second = self.service.ensure_bokmal_profile()
        self.assertFalse(second["created"])
        self.assertEqual(second["profile"]["id"], self.profile["id"])
        self.assertEqual(second["profile"]["analyzerId"], "stanza-nb-bokmaal")
        self.assertEqual(len(self.service.list_profiles()["data"]["items"]), 1)

    def test_four_forms_share_one_lemma_and_one_knowledge_snapshot(self):
        lemma = self.service.upsert_lemma(self.profile["id"], "jobb", part_of_speech="NOUN")["lemma"]
        for display in ("jobb", "jobben", "jobber", "jobbene"):
            form = self.service.upsert_surface_form(self.profile["id"], display)["form"]
            self.service.upsert_form_lemma_mapping(
                self.profile["id"], form["id"], lemma["id"],
                provider_id="stanza-nb-bokmaal", provider_version="1.0.0",
            )
        detail = self.service.get_lemma(lemma["id"])["data"]
        self.assertEqual({item["formDisplay"] for item in detail["forms"]}, {"jobb", "jobben", "jobber", "jobbene"})
        with self.store.connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM vocabulary_lemmas").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM lemma_knowledge").fetchone()[0], 1)

    def test_ambiguous_candidates_and_manual_mapping_lock_survive_refresh(self):
        noun = self.service.upsert_lemma(self.profile["id"], "jobb", part_of_speech="NOUN")["lemma"]
        verb = self.service.upsert_lemma(self.profile["id"], "jobbe", part_of_speech="VERB")["lemma"]
        form = self.service.upsert_surface_form(self.profile["id"], "jobber")["form"]
        self.service.upsert_form_lemma_mapping(self.profile["id"], form["id"], verb["id"], ambiguity_state="AMBIGUOUS")
        locked = self.service.lock_form_lemma_mapping(self.profile["id"], form["id"], noun["id"], source="USER_CORRECTION")
        refreshed = self.service.upsert_form_lemma_mapping(
            self.profile["id"], form["id"], noun["id"],
            provider_id="new-analyzer", provider_version="2", morphology={"Gender": "Neut"},
        )
        self.assertTrue(locked["mapping"]["manualLocked"])
        self.assertTrue(refreshed["protected"])
        self.assertEqual(refreshed["mapping"]["manualProvenance"], "USER_CORRECTION")
        with self.store.connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM form_lemma_links WHERE form_id=?", (form["id"],)).fetchone()[0], 2)

    def test_manual_status_and_scores_are_protected_from_automation(self):
        lemma = self.service.upsert_lemma(self.profile["id"], "jobb", part_of_speech="NOUN")["lemma"]
        self.service.update_knowledge(lemma["id"], {"knowledgeStatus": "MASTERED", "recognition": 5})
        automated = self.service.apply_automated_knowledge(
            lemma["id"], {"knowledgeStatus": "LEARNING", "recognition": 1}, source="RULE_V2"
        )["knowledge"]
        self.assertEqual(automated["knowledgeStatus"], "MASTERED")
        self.assertEqual(automated["recognition"], 5)
        self.assertTrue(automated["protected"])

    def test_scores_and_relationships_are_validated(self):
        lemma = self.service.upsert_lemma(self.profile["id"], "jobb", part_of_speech="NOUN")["lemma"]
        for value in (-1, 6, 2.5, True):
            with self.subTest(value=value), self.assertRaises(LanguageValidationError):
                self.service.update_knowledge(lemma["id"], {"recall": value})
        other = self.service.create_profile({
            "languageCode": "sv", "locale": "sv-SE", "displayName": "Swedish"
        })["data"]["profile"]
        form = self.service.upsert_surface_form(other["id"], "jobb")["form"]
        with self.assertRaises(LanguageConflictError):
            self.service.upsert_form_lemma_mapping(other["id"], form["id"], lemma["id"])
        own_form = self.service.upsert_surface_form(self.profile["id"], "jobben")["form"]
        self.service.upsert_form_lemma_mapping(self.profile["id"], own_form["id"], lemma["id"])
        with self.assertRaises(LanguageConflictError):
            self.service.upsert_form_lemma_mapping(other["id"], own_form["id"], lemma["id"])

    def test_merge_rules_reject_self_cross_profile_and_preserve_redirect(self):
        first = self.service.upsert_lemma(self.profile["id"], "arbeider", part_of_speech="NOUN")["lemma"]
        target = self.service.upsert_lemma(self.profile["id"], "arbeid", part_of_speech="NOUN")["lemma"]
        with self.assertRaises(LanguageConflictError):
            self.service.merge_lemmas({"sourceLemmaId": first["id"], "targetLemmaId": first["id"]})
        other = self.service.create_profile({
            "languageCode": "sv", "locale": "sv-SE", "displayName": "Swedish"
        })["data"]["profile"]
        foreign = self.service.upsert_lemma(other["id"], "arbete", part_of_speech="NOUN")["lemma"]
        with self.assertRaises(LanguageConflictError):
            self.service.merge_lemmas({"sourceLemmaId": first["id"], "targetLemmaId": foreign["id"]})
        result = self.service.merge_lemmas({"sourceLemmaId": first["id"], "targetLemmaId": target["id"]})
        self.assertEqual(result["data"]["targetLemmaId"], target["id"])
        self.assertEqual(self.service.get_lemma(first["id"])["data"]["lemma"]["mergedIntoId"], target["id"])

    def test_exposure_idempotency_and_export_round_trip_semantics(self):
        lemma = self.service.upsert_lemma(self.profile["id"], "jobb", part_of_speech="NOUN")["lemma"]
        forms = []
        for display in ("jobb", "jobben", "jobber", "jobbene"):
            form = self.service.upsert_surface_form(self.profile["id"], display)["form"]
            forms.append(form)
            self.service.upsert_form_lemma_mapping(self.profile["id"], form["id"], lemma["id"])
        raw = "Blåbær 😊 jobbene"
        text = self.service.create_text_draft({
            "languageProfileId": self.profile["id"], "title": "Ærlig tekst", "rawText": raw
        })["data"]["text"]
        session = self.service.create_study_session({
            "languageProfileId": self.profile["id"], "sessionType": "MANUAL", "clientSessionId": "one"
        })["data"]["session"]
        command = {
            "languageProfileId": self.profile["id"], "lemmaId": lemma["id"],
            "studySessionId": session["id"], "sourceType": "MANUAL",
            "occurrenceCount": 3, "idempotencyKey": "same-command",
        }
        self.service.record_exposure(command)
        self.service.record_exposure(command)
        exported = self.service.export_data()["data"]
        data = exported["data"]
        self.assertEqual(exported["exportVersion"], EXPORT_VERSION)
        self.assertEqual(exported["offsetUnit"], "UNICODE_CODE_POINT")
        self.assertEqual(data["textDocuments"][0]["rawText"], raw)
        self.assertEqual(len(data["surfaceForms"]), 4)
        self.assertEqual({row["lemmaId"] for row in data["formLemmaLinks"]}, {lemma["id"]})
        self.assertEqual(len(data["lemmaKnowledge"]), 1)
        self.assertEqual(data["lemmaKnowledge"][0]["totalExposures"], 3)
        self.assertEqual(len(data["exposureEvents"]), 1)
        self.assertEqual(data["exposureEvents"][0]["idempotencyKey"], "same-command")
        self.assertEqual(data["textDocuments"][0]["id"], text["id"])

    def test_text_draft_does_not_import_or_instantiate_stanza(self):
        with unittest.mock.patch(
            "language_learning.analysis.norwegian_bokmal.NorwegianBokmalStanzaAnalyzer.__init__",
            side_effect=AssertionError("Stanza must not be instantiated"),
        ):
            created = self.service.create_text_draft({
                "languageProfileId": self.profile["id"], "title": "Draft", "rawText": "jobb"
            })
            loaded = self.service.get_text(created["data"]["text"]["id"])
            health = self.service.health()
        self.assertEqual(loaded["data"]["document"]["rawText"], "jobb")
        self.assertEqual(health["data"]["canonicalAnalyzer"]["runtimeState"], "LAZY_NOT_CREATED")

    def test_text_input_limits_and_whitespace_analysis_error_are_stable(self):
        with self.assertRaisesRegex(LanguageValidationError, "non-empty"):
            self.service.create_text_draft({
                "languageProfileId": self.profile["id"], "title": "Empty", "rawText": ""
            })
        with self.assertRaisesRegex(LanguageValidationError, "too large"):
            self.service.create_text_draft({
                "languageProfileId": self.profile["id"],
                "title": "Large",
                "rawText": "x" * (MAX_ANALYSIS_TEXT_BYTES + 1),
            })
        whitespace = self.service.create_text_draft({
            "languageProfileId": self.profile["id"],
            "title": "Whitespace",
            "rawText": " \n  ",
        })["data"]["text"]
        with self.assertRaisesRegex(LanguageValidationError, "non-whitespace"):
            self.service._analysis_job_values(whitespace["id"], job_type="ANALYZE")

    def test_reader_exposure_batch_is_validated_atomic_and_idempotent(self):
        text, sentence_id, lemma = self.analyzed_reader_text()
        session = self.service.start_reader_session({
            "languageProfileId": self.profile["id"],
            "textDocumentId": text["id"],
            "clientSessionId": "reader-one",
        })["data"]["session"]
        retried_session = self.service.start_reader_session({
            "languageProfileId": self.profile["id"],
            "textDocumentId": text["id"],
            "clientSessionId": "reader-one",
        })["data"]
        self.assertTrue(retried_session["reused"])
        self.assertEqual(retried_session["session"]["id"], session["id"])
        command = {
            "textDocumentId": text["id"],
            "sentenceId": sentence_id,
            "idempotencyKey": "reader-one:sentence-one",
            "occurrences": [{"lemmaId": lemma["id"], "occurrenceCount": 3}],
        }
        first = self.service.record_reader_exposure_batch(session["id"], command)["data"]
        second = self.service.record_reader_exposure_batch(session["id"], command)["data"]
        self.assertTrue(first["created"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(len(first["events"]), 1)
        self.assertEqual(
            self.service.get_lemma(lemma["id"])["data"]["knowledge"]["totalExposures"], 3
        )
        invalid = {**command, "idempotencyKey": "inflated", "occurrences": [
            {"lemmaId": lemma["id"], "occurrenceCount": 500}
        ]}
        with self.assertRaisesRegex(LanguageConflictError, "do not match"):
            self.service.record_reader_exposure_batch(session["id"], invalid)
        self.assertEqual(
            self.service.get_lemma(lemma["id"])["data"]["knowledge"]["totalExposures"], 3
        )

    def test_reader_active_time_excludes_hidden_gap_pause_and_command_retry(self):
        text, _, _ = self.analyzed_reader_text()
        session = self.service.start_reader_session({
            "languageProfileId": self.profile["id"],
            "textDocumentId": text["id"],
            "clientSessionId": "active-time",
        })["data"]["session"]
        with self.store.connection() as connection:
            connection.execute(
                "UPDATE study_sessions SET last_heartbeat_at='2026-09-16T00:00:00.000Z' WHERE id=?",
                (session["id"],),
            )
        times = [
            "2026-09-16T00:00:30.000Z",
            "2026-09-16T00:00:30.000Z",
            "2026-09-16T00:01:30.000Z",
            "2026-09-16T00:01:50.000Z",
            "2026-09-16T00:02:50.000Z",
        ]
        with mock.patch("language_learning.store.utc_now", side_effect=times):
            self.service.update_reader_session(session["id"], {"action": "HEARTBEAT", "commandId": "h1"})
            self.service.update_reader_session(session["id"], {"action": "PAUSE", "commandId": "p1"})
            self.service.update_reader_session(session["id"], {"action": "RESUME", "commandId": "r1"})
            paused = self.service.update_reader_session(session["id"], {"action": "PAUSE", "commandId": "p2"})["data"]
            duplicate = self.service.update_reader_session(session["id"], {"action": "PAUSE", "commandId": "p2"})["data"]
        self.assertEqual(paused["session"]["activeSeconds"], 50)
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(duplicate["session"]["activeSeconds"], 50)

    def test_reading_progress_completion_history_and_reanalysis_safety(self):
        text, sentence_id, _ = self.analyzed_reader_text()
        progress = self.service.update_reading_progress(text["id"], {
            "languageProfileId": self.profile["id"],
            "progressSourceOffset": 11,
            "progressSentenceId": sentence_id,
            "status": "IN_PROGRESS",
        })["data"]["readingProgress"]
        self.assertEqual(progress["status"], "IN_PROGRESS")
        completed = self.service.update_reading_progress(text["id"], {
            "languageProfileId": self.profile["id"],
            "progressSourceOffset": 16,
            "progressSentenceId": sentence_id,
            "status": "COMPLETED",
        })["data"]["readingProgress"]
        self.assertEqual(completed["status"], "COMPLETED")
        self.assertIsNotNone(completed["coverageSnapshot"])
        loaded = self.service.get_text(text["id"])["data"]
        self.assertEqual(loaded["readingProgress"]["progressSourceOffset"], 16)
        history = self.service.list_texts(self.profile["id"])["data"]["items"][0]
        self.assertEqual(history["readingStatus"], "COMPLETED")
        self.assertIsNotNone(history["coverageSnapshot"])
        with self.assertRaises(LanguageConflictError) as blocked:
            self.service.enqueue_reanalysis_commit(
                text["id"], {"previewJobId": "a" * 32}
            )
        self.assertEqual(blocked.exception.code, "studied_text_reanalysis_blocked")


if __name__ == "__main__":
    unittest.main()
