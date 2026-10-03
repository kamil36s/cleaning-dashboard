import tempfile
import unittest
from pathlib import Path

from language_learning.errors import LanguageConflictError, LanguageValidationError
from language_learning.gamification import LISTENING_XP_POLICY_VERSION
from language_learning.schemas import text_fingerprint
from language_learning.service import LanguageService
from language_learning.store import LanguageStore


class LanguageListeningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = LanguageStore(Path(self.temp.name) / "language.sqlite")
        self.service = LanguageService(self.store)
        self.service.initialize()
        self.profile = self.service.ensure_bokmal_profile()["profile"]
        self.text, self.sentences, self.lemmas = self._analyzed_text()

    def tearDown(self):
        self.temp.cleanup()

    def _analyzed_text(self):
        raw = "jobb ukjent. bok."
        text = self.service.create_text_draft({
            "languageProfileId": self.profile["id"], "title": "Lyttetekst", "rawText": raw,
        })["data"]["text"]
        job = self.service.upsert_lemma(self.profile["id"], "jobb", part_of_speech="NOUN")["lemma"]
        book = self.service.upsert_lemma(self.profile["id"], "bok", part_of_speech="NOUN")["lemma"]
        job_form = self.service.upsert_surface_form(self.profile["id"], "jobb")["form"]
        book_form = self.service.upsert_surface_form(self.profile["id"], "bok")["form"]
        unknown_form = self.service.upsert_surface_form(self.profile["id"], "ukjent")["form"]
        self.service.upsert_form_lemma_mapping(self.profile["id"], job_form["id"], job["id"])
        self.service.upsert_form_lemma_mapping(self.profile["id"], book_form["id"], book["id"])
        first = "1" * 32
        second = "2" * 32
        self.store.insert_text_structure(
            text["id"],
            sentences=[
                {"id": first, "sentence_order": 0, "source_start": 0, "source_end": 12,
                 "exact_text": "jobb ukjent.", "fingerprint": text_fingerprint("jobb ukjent.")},
                {"id": second, "sentence_order": 1, "source_start": 13, "source_end": 17,
                 "exact_text": "bok.", "fingerprint": text_fingerprint("bok.")},
            ],
            tokens=[
                {"id": "3" * 32, "sentence_id": first, "token_order": 0, "surface": "jobb",
                 "source_start": 0, "source_end": 4, "token_kind": "WORD", "normalized_lookup": "jobb",
                 "surface_form_id": job_form["id"], "selected_lemma_id": job["id"]},
                {"id": "4" * 32, "sentence_id": first, "token_order": 1, "surface": "ukjent",
                 "source_start": 5, "source_end": 11, "token_kind": "WORD", "normalized_lookup": "ukjent",
                 "surface_form_id": unknown_form["id"], "selected_lemma_id": None},
                {"id": "5" * 32, "sentence_id": second, "token_order": 2, "surface": "bok",
                 "source_start": 13, "source_end": 16, "token_kind": "WORD", "normalized_lookup": "bok",
                 "surface_form_id": book_form["id"], "selected_lemma_id": book["id"]},
            ],
            analysis_run={
                "id": "f" * 32, "analyzer_id": "synthetic", "analyzer_version": "1",
                "contract_version": "language.analysis/v1", "state": "COMPLETED",
            },
        )
        with self.store.connection() as connection:
            connection.execute(
                "UPDATE text_documents SET processing_state='ANALYZED' WHERE id=?", (text["id"],)
            )
        return text, [first, second], [job, book]

    def _start(self, key="listen-one", mode="READ_LISTEN"):
        return self.service.start_listening_session(self.text["id"], {
            "languageProfileId": self.profile["id"], "clientSessionId": key, "mode": mode,
        })["data"]

    def _event(self, session_id, sentence_id, key, *, active=48_000, duration=60_000,
               outcome="ENDED", source="BROWSER_TTS", metadata=None):
        return self.service.record_listening_sentence_event(session_id, {
            "textDocumentId": self.text["id"], "sentenceId": sentence_id,
            "idempotencyKey": key, "outcome": outcome, "playbackSource": source,
            "activeMs": active, "durationMs": duration,
            "metadata": metadata or {"mode": "READ_LISTEN"},
        })["data"]

    def test_session_is_lazy_contract_idempotent_and_material_is_listed(self):
        materials = self.service.listening_materials(self.profile["id"])["data"]
        self.assertEqual(materials["total"], 1)
        self.assertEqual(materials["items"][0]["listeningStatus"], "NOT_STARTED")
        first = self._start()
        repeated = self._start()
        self.assertTrue(first["created"])
        self.assertTrue(repeated["reused"])
        self.assertEqual(first["session"]["id"], repeated["session"]["id"])
        with self.assertRaises(LanguageConflictError):
            self._start(mode="LISTENING_ONLY")

    def test_partial_cancel_error_and_source_spoof_do_not_create_exposure(self):
        session = self._start()["session"]
        with self.assertRaises(LanguageValidationError):
            self.service.record_exposure({
                "idempotencyKey": "forged-listening", "languageProfileId": self.profile["id"],
                "lemmaId": self.lemmas[0]["id"], "studySessionId": session["id"],
                "sourceType": "LISTENING", "occurrenceCount": 99,
            })
        partial = self._event(session["id"], self.sentences[0], "partial", active=47_999)
        self.assertFalse(partial["event"]["qualified"])
        self.assertFalse(partial["event"]["exposureAwarded"])
        cancelled = self._event(
            session["id"], self.sentences[0], "cancel", active=10_000,
            duration=None, outcome="CANCELLED",
        )
        self.assertFalse(cancelled["event"]["qualified"])
        self.assertEqual(cancelled["exposures"], [])
        failed = self._event(
            session["id"], self.sentences[0], "error", active=0,
            duration=None, outcome="ERROR",
        )
        self.assertFalse(failed["event"]["qualified"])
        self.assertEqual(failed["exposures"], [])
        with self.assertRaises(LanguageConflictError):
            self._event(session["id"], self.sentences[0], "spoof", source="CLOUD_TTS")
        with self.assertRaises(LanguageValidationError):
            self._event(session["id"], self.sentences[0], "oversize", active=600_001)

    def test_qualification_replay_bound_completion_and_reader_separation(self):
        session = self._start()["session"]
        first = self._event(session["id"], self.sentences[0], "first")
        self.assertTrue(first["event"]["qualified"])
        self.assertTrue(first["event"]["exposureAwarded"])
        self.assertEqual(len(first["exposures"]), 1)
        duplicate = self._event(session["id"], self.sentences[0], "first")
        self.assertTrue(duplicate["duplicate"])
        replay = self._event(session["id"], self.sentences[0], "replay")
        self.assertTrue(replay["event"]["qualified"])
        self.assertFalse(replay["event"]["exposureAwarded"])
        self.assertEqual(replay["exposures"], [])
        with self.assertRaises(LanguageConflictError):
            self._event(session["id"], self.sentences[1], "first")
        completed = self._event(session["id"], self.sentences[1], "second")
        self.assertEqual(completed["progress"]["status"], "COMPLETED")
        self.assertEqual(completed["progress"]["completedSentenceCount"], 2)
        self.assertEqual(completed["progress"]["completionPercent"], 100.0)

        with self.store.connection() as connection:
            overlap_time = completed["event"]["occurredAt"]
            totals = {
                row["lemma_id"]: row["total_exposures"]
                for row in connection.execute(
                    "SELECT lemma_id,total_exposures FROM lemma_knowledge ORDER BY lemma_id"
                )
            }
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM exposure_events WHERE source_type='LISTENING'"
            ).fetchone()[0], 2)
            connection.execute(
                "INSERT INTO study_sessions(id,language_profile_id,text_document_id,session_type,status,"
                "started_at,ended_at,active_seconds,created_at,updated_at,activity_state) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    "a" * 32, self.profile["id"], self.text["id"], "READER", "COMPLETED",
                    overlap_time, overlap_time, 60,
                    overlap_time, overlap_time, "PAUSED",
                ),
            )
        self.assertEqual(totals[self.lemmas[0]["id"]], 1)
        self.assertEqual(totals[self.lemmas[1]["id"]], 1)

        stats = self.service.statistics(self.profile["id"], range_name="7d")["data"]
        self.assertEqual(stats["exposures"]["totalReaderOccurrences"], 0)
        self.assertEqual(stats["reading"]["activeSeconds"], 60)
        self.assertEqual(stats["listening"]["sentencesListened"], 2)
        self.assertEqual(stats["listening"]["textsCompleted"], 1)
        self.assertEqual(stats["listening"]["comprehensionClaim"], "NONE")
        self.assertEqual(stats["listening"]["byPlaybackSource"]["BROWSER_TTS"]["events"], 3)
        self.assertFalse(stats["studyTime"]["aggregateIsUniqueWallClock"])
        self.assertEqual(
            stats["studyTime"]["modalitySumSeconds"],
            stats["studyTime"]["readingActiveSeconds"] + stats["studyTime"]["listeningActiveSeconds"],
        )
        exported = self.service.export_data()["data"]
        self.assertEqual(exported["exportVersion"], "language-learning-export/v16")
        self.assertEqual(len(exported["data"]["listeningSessions"]), 1)
        self.assertEqual(len(exported["data"]["listeningSentenceEvents"]), 3)
        self.assertEqual(exported["data"]["listeningProgress"][0]["status"], "COMPLETED")

    def test_listening_goals_and_bounded_xp_use_canonical_events(self):
        session = self._start()["session"]
        for index in range(25):
            self._event(session["id"], self.sentences[0], f"minute-{index}", active=60_000)
        with self.store.connection() as connection:
            awards = connection.execute(
                "SELECT xp_amount FROM gamification_awards WHERE rule_version=? ORDER BY source_id",
                (LISTENING_XP_POLICY_VERSION,),
            ).fetchall()
        self.assertEqual(len(awards), 20)
        self.assertEqual(sum(int(row["xp_amount"]) for row in awards), 40)

        for metric, unit, expected in (
            ("LISTENING_ACTIVE_MINUTES", "MINUTES", 25.0),
            ("LISTENING_SESSIONS", "SESSIONS", 1),
            ("LISTENING_TEXTS_COMPLETED", "TEXTS", 0),
        ):
            goal = self.service.create_goal(self.profile["id"], {
                "metric": metric, "targetValue": 30, "unit": unit,
            })["data"]["goal"]
            item = next(
                row for row in self.service.list_goals(self.profile["id"])["data"]["items"]
                if row["goal"]["id"] == goal["id"]
            )
            self.assertEqual(item["current"], expected)


if __name__ == "__main__":
    unittest.main()
