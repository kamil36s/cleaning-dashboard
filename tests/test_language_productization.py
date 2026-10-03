import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from language_learning.service import LanguageService
from language_learning.errors import LanguageError
from language_learning.store import LanguageStore


class LanguageProductizationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = LanguageStore(Path(self.temp.name) / "language.sqlite")
        self.service = LanguageService(self.store)
        self.service.initialize()
        self.profile = self.service.ensure_bokmal_profile()["profile"]

    def tearDown(self):
        self.temp.cleanup()

    def counts(self):
        with self.store.connection() as connection:
            return {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    for table in ("knowledge_events", "exposure_events", "cloze_attempts", "gamification_awards")}

    def test_today_and_widget_are_read_only_and_never_probe_anki(self):
        lemma = self.service.upsert_lemma(self.profile["id"], "noen", part_of_speech="PRON")["lemma"]
        before = self.counts()
        original = self.service.anki_sync_service.status
        with mock.patch.object(self.service.anki_sync_service, "status", wraps=original) as status:
            today = self.service.today_summary(
                self.profile["id"], as_of=datetime(2026, 9, 25, 9, tzinfo=timezone.utc)
            )["data"]
            widget = self.service.widget_summary(self.profile["id"])["data"]
        self.assertEqual(today["policyVersion"], "language.today-summary/v1")
        self.assertEqual(today["trackedVocabulary"], 1)
        self.assertEqual(today["cloze"]["answeredToday"], 0)
        self.assertFalse(today["anki"]["configured"])
        self.assertEqual(widget["profileId"], self.profile["id"])
        self.assertEqual(status.call_count, 2)
        self.assertTrue(all(call.kwargs.get("probe") is False for call in status.call_args_list))
        self.assertEqual(self.counts(), before)

    def test_empty_history_has_a_start_here_state_without_learning_evidence(self):
        before = self.counts()
        summary = self.service.today_summary(self.profile["id"])["data"]
        self.assertTrue(summary["startHere"])
        self.assertIsNone(summary["reader"]["continue"])
        self.assertIsNone(summary["cloze"]["recommendedQuestionCount"])
        self.assertEqual(self.counts(), before)

    def test_today_counts_review_attempts_and_only_first_seen_new_sentences(self):
        lemma = self.service.upsert_lemma(self.profile["id"], "noen", part_of_speech="PRON")["lemma"]
        with self.store.connection() as connection:
            for session_id, mode, day in (("old", "FAST_TRACK", "24"),
                                          ("new", "FAST_TRACK", "25"),
                                          ("review", "RECYCLE_MISTAKES", "25")):
                at = f"2026-09-{day}T09:00:00+00:00"
                connection.execute(
                    "INSERT INTO cloze_sessions(id,language_profile_id,mode,track_key,track_version,"
                    "requested_item_count,seed,items_json,status,started_at,updated_at,practice_mode) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (session_id, self.profile["id"], mode, "TEST", "v1", 10, "seed", "[]",
                     "COMPLETED", at, at, mode),
                )
            for attempt_id, session_id, sentence_id, at in (
                ("a", "old", "repeated", "2026-09-24T09:00:00+00:00"),
                ("b", "new", "repeated", "2026-09-25T09:00:00+00:00"),
                ("c", "new", "fresh", "2026-09-25T09:01:00+00:00"),
                ("d", "review", "repeated", "2026-09-25T09:02:00+00:00"),
            ):
                connection.execute(
                    "INSERT INTO cloze_attempts(id,session_id,item_index,target_lemma_id,"
                    "reference_target_stable_key,reference_sentence_source,reference_sentence_id,"
                    "item_snapshot_json,item_fingerprint,expected_surface_form,options_json,"
                    "outcome,response_ms,idempotency_key,attempted_at,rule_versions_json) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (attempt_id, session_id, 0 if attempt_id != "c" else 1, lemma["id"], "target",
                     "TATOEBA", sentence_id, "{}", attempt_id, "noen", "[]", "CORRECT",
                     100, attempt_id, at, "{}"),
                )
        cloze = self.service.today_summary(
            self.profile["id"], as_of=datetime(2026, 9, 25, 12, tzinfo=timezone.utc)
        )["data"]["cloze"]
        self.assertEqual(cloze["answeredToday"], 3)
        self.assertEqual(cloze["reviewedToday"], 1)
        self.assertEqual(cloze["newSentencesToday"], 1)

    def test_hover_preview_is_local_and_does_not_create_learning_evidence(self):
        lemma = self.service.upsert_lemma(self.profile["id"], "noen", part_of_speech="PRON")["lemma"]
        self.service.upsert_lemma_translation(lemma["id"], {
            "targetLocale": "pl-PL", "translation": "ktoś"
        })
        before = self.counts()
        with mock.patch.object(self.service.dictionary_provider, "lookup_lemma", side_effect=AssertionError("provider called")):
            preview = self.service.get_lemma_preview(lemma["id"])["data"]
        self.assertEqual(preview["lemmaDisplay"], "noen")
        self.assertEqual(preview["translations"]["user"][0]["translationText"], "ktoś")
        self.assertEqual(self.counts(), before)

    def test_untracked_surface_lookup_is_read_only(self):
        before = self.counts()
        with mock.patch.object(self.service.dictionary_provider, "lookup_lemma", side_effect=AssertionError("provider called")):
            preview = self.service.lookup_surface_preview(self.profile["id"], "ukjent")["data"]
        self.assertIsNone(preview["lemmaId"])
        self.assertEqual(preview["lemmaDisplay"], "ukjent")
        with self.store.connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM vocabulary_lemmas").fetchone()[0], 0)
        self.assertEqual(self.counts(), before)

    def test_missing_word_meanings_use_bounded_translation_fallbacks(self):
        before = self.counts()
        with mock.patch("language_learning.service.GooglePublicTranslationProvider.translate",
                        side_effect=lambda word, locale, **kwargs: {"en": "through", "pl": "przez"}[locale]) as translate:
            meanings = self.service.lookup_surface_meanings(self.profile["id"], "gjennom")["data"]
        self.assertEqual({row["targetLocale"]: row["value"] for row in meanings["translations"]["machine"]},
                         {"en": "through", "pl": "przez"})
        self.assertEqual(translate.call_count, 2)
        self.assertEqual(self.counts(), before)

    def test_word_meaning_tries_second_source_when_first_fails(self):
        with mock.patch("language_learning.service.GooglePublicTranslationProvider.translate",
                        side_effect=LanguageError("Unavailable", code="translation_unavailable", status=502)), \
             mock.patch("language_learning.service.MyMemoryTranslationProvider.translate", return_value="przez"):
            meaning = self.service._translate_surface_word("gjennom", "pl")
        self.assertEqual(meaning["value"], "przez")
        self.assertEqual(meaning["source"], "MYMEMORY_PUBLIC")


if __name__ == "__main__":
    unittest.main()
