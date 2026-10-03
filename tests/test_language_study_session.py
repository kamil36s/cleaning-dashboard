import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

from language_learning.errors import LanguageValidationError
from language_learning.service import LanguageService
from language_learning.store import LanguageStore
from language_learning.study_session import _candidate, compose, StudySessionBuilder


class StudySessionPolicyTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            _candidate("ANKI_DUE", "due", "Due", "Stored due cards", "#reviews"),
            _candidate("CLOZE_MISTAKES", "mistakes", "Mistakes", "Current remediation", "#cloze"),
            _candidate("CONTINUE_READING", "read", "Read", "Unfinished text", "#reader/text/abc"),
            _candidate("CONTINUE_LISTENING", "listen", "Listen", "Unfinished text", "#listening/text/abc"),
            *[_candidate("CURRICULUM_GAP", str(i), str(i), "Eligible gap", "#curriculum") for i in range(30)],
        ]

    def test_determinism_budget_bounds_and_priority(self):
        for minutes, bound in ((10, 3), (20, 4), (30, 5)):
            first = compose("profile", minutes, "2026-09-24", self.rows)
            self.assertEqual(first, compose("profile", minutes, "2026-09-24", list(reversed(self.rows))))
            self.assertLessEqual(first["plannedMinutes"], minutes)
            self.assertLessEqual(first["segmentCount"], bound)
            self.assertEqual(first["segments"][0]["segmentType"], "ANKI_DUE")
            self.assertEqual(len(first["snapshotFingerprint"]), 64)
            self.assertTrue(all(row["reason"] and row["destinationRoute"] and row["sourceOwner"]
                                for row in first["segments"]))

    def test_diversity_does_not_displace_urgent_work(self):
        plan = compose("profile", 20, "2026-09-24", self.rows)
        kinds = [row["segmentType"] for row in plan["segments"]]
        self.assertEqual(kinds[:2], ["ANKI_DUE", "CLOZE_MISTAKES"])
        self.assertTrue({"CONTINUE_READING", "CONTINUE_LISTENING"} & set(kinds))

    def test_empty_partial_and_invalid_duration(self):
        self.assertEqual(compose("p", 10, "2026-09-24", [])["plannedMinutes"], 0)
        partial = compose("p", 20, "2026-09-24", [self.rows[0]], unavailable=["Listening"])
        self.assertEqual(partial["plannedMinutes"], 5)
        self.assertEqual(partial["unavailableSources"], ["Listening"])
        for minutes in (0, 11, 1000, True, "20"):
            with self.assertRaises(LanguageValidationError):
                compose("p", minutes, "2026-09-24", [])


class StudySessionIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = LanguageStore(Path(self.temp.name) / "language.sqlite")
        self.service = LanguageService(self.store)
        self.profile = self.service.create_profile({
            "languageCode": "nb", "locale": "nb-NO", "displayName": "Test"
        })["data"]["profile"]["id"]

    def tearDown(self):
        self.temp.cleanup()

    def test_empty_profile_zero_mutation_and_same_day_snapshot(self):
        exported_before = self.store.export_data()["data"]
        with self.store.connection() as connection:
            before = {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                      for table in ("study_sessions", "exposure_events", "cloze_attempts", "benchmark_runs",
                                    "gamification_awards", "goal_definitions", "grammar_occurrences")}
        builder = StudySessionBuilder(self.service)
        morning = builder.build(self.profile, 20, as_of=datetime(2026, 9, 24, 6, tzinfo=timezone.utc))
        evening = builder.build(self.profile, 20, as_of=datetime(2026, 9, 24, 18, tzinfo=timezone.utc))
        self.assertEqual(morning, evening)
        self.assertEqual(morning["segments"], [])
        self.assertEqual(morning["sourceAvailability"]["LearningPlan"], "AVAILABLE")
        self.assertEqual(morning["sourceAvailability"]["Anki"], "UNAVAILABLE")
        with self.store.connection() as connection:
            after = {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                     for table in before}
        self.assertEqual(before, after)
        self.assertEqual(exported_before, self.store.export_data()["data"])

    def test_owner_outputs_partial_failure_and_benchmark_tie_break(self):
        self.service.anki_sync_service.status = Mock(return_value={"configured": False})
        self.service.learning_plan_service.build = Mock(return_value={"items": [
            {"id": "continue:reader", "kind": "CONTINUE_READING", "title": "Continue Reader",
             "detail": "Unfinished Reader text", "href": "#reader/text/reader"},
            {"id": "continue-listening:listen", "kind": "CONTINUE_LISTENING", "title": "Continue Listening",
             "detail": "Unfinished Listening text", "href": "#listening/text/listen"},
            {"id": "cloze:mistakes", "kind": "CLOZE_MISTAKES", "title": "Mistakes",
             "detail": "Remediation", "href": "#cloze"},
        ], "cloze": {"remediation": [{"targetLemmaId": "lemma"}]}})
        self.store.list_texts = Mock(return_value={"items": []})
        self.store.list_listening_materials = Mock(side_effect=RuntimeError("unavailable"))
        self.service.curriculum_service.landing = Mock(return_value={"packs": [{
            "id": "nb.test", "version": 1, "name": "Test pack",
            "progress": {"eligibleDenominator": 10, "completed": 2},
        }]})
        self.service.grammar.summary = Mock(return_value={"items": [{
            "patternId": "V2", "name": "V2", "state": "ENCOUNTERED", "authoritativeCount": 2,
        }]})
        self.service.assessment.list_runs = Mock(return_value={"runs": [{
            "status": "COMPLETED", "scores": {
                "READING": {"percent": 70}, "LISTENING": {"percent": 50},
            },
        }]})
        result = StudySessionBuilder(self.service).build(
            self.profile, 30, as_of=datetime(2026, 9, 24, 12, tzinfo=timezone.utc))
        self.assertIn("Listening", result["unavailableSources"])
        self.assertIn("Mistake Intelligence", {row["sourceOwner"] for row in result["segments"]})
        self.assertLessEqual(result["plannedMinutes"], 30)
        self.service.anki_sync_service.status.assert_called_once_with(self.profile, probe=False)
        self.assertTrue(any("completed benchmark" in row["reason"] for row in result["segments"]
                            if row["segmentType"] == "CONTINUE_LISTENING"))
        self.service.assessment.list_runs.return_value["runs"][0]["scores"] = {
            "READING": {"percent": 40}, "LISTENING": {"percent": 70},
        }
        self.service.assessment.list_runs.return_value["runs"][0]["comparison"] = {
            "state": "REPEAT_INFLUENCED",
        }
        reading_result = StudySessionBuilder(self.service).build(
            self.profile, 30, as_of=datetime(2026, 9, 24, 12, tzinfo=timezone.utc))
        self.assertTrue(any("completed benchmark" in row["reason"] for row in reading_result["segments"]
                            if row["segmentType"] == "CONTINUE_READING"))
        self.assertTrue(any("may reflect familiarity" in row["reason"] for row in reading_result["segments"]
                            if row["segmentType"] == "CONTINUE_READING"))

    def test_same_day_completed_anki_sync_is_used_without_live_probe(self):
        self.service.anki_sync_service.status = Mock(return_value={
            "configured": True, "dueCount": 5,
            "lastSync": {"status": "COMPLETED", "startedAt": "2026-09-24T08:00:00Z"},
        })
        result = StudySessionBuilder(self.service).build(
            self.profile, 10, as_of=datetime(2026, 9, 24, 12, tzinfo=timezone.utc))
        self.assertEqual(result["segments"][0]["segmentType"], "ANKI_DUE")
        self.assertEqual(result["plannedMinutes"], 5)
        self.assertIn("stored Anki sync", result["segments"][0]["reason"])
        self.service.anki_sync_service.status.assert_called_once_with(self.profile, probe=False)

    def test_completed_work_discovered_grammar_and_unstarted_pack_do_not_fill(self):
        self.service.anki_sync_service.status = Mock(return_value={"configured": False})
        self.service.learning_plan_service.build = Mock(return_value={"items": [
            {"id": "read:text", "kind": "READ_TEXT", "title": "Read again",
             "detail": "An old text", "href": "#reader/text/text"},
        ], "cloze": {"remediation": []}})
        self.store.list_texts = Mock(return_value={"items": [{
            "id": "text", "processing_state": "ANALYZED", "reading_status": "COMPLETED",
        }]})
        self.store.list_listening_materials = Mock(return_value={"items": [{
            "text_document_id": "text", "title": "Finished listening", "listening_status": "COMPLETED",
            "eligible_sentence_count": 3,
        }]})
        self.service.curriculum_service.landing = Mock(return_value={"packs": [{
            "id": "nb.test", "version": 1, "name": "Test pack",
            "progress": {"eligibleDenominator": 10, "completed": 0},
        }]})
        self.service.grammar.summary = Mock(return_value={"items": [{
            "patternId": "V2", "name": "V2", "state": "DISCOVERED", "authoritativeCount": 2,
        }]})
        self.service.assessment.list_runs = Mock(return_value={"runs": []})
        builder = StudySessionBuilder(self.service)
        empty = builder.build(self.profile, 20, as_of=datetime(2026, 9, 24, 12, tzinfo=timezone.utc))
        self.assertEqual(empty["segments"], [])
        self.service.grammar.summary.return_value["items"][0]["state"] = "ENCOUNTERED"
        grammar = builder.build(self.profile, 20, as_of=datetime(2026, 9, 24, 12, tzinfo=timezone.utc))
        self.assertEqual([row["segmentType"] for row in grammar["segments"]], ["CORE_GRAMMAR"])
        self.assertNotIn("weak", grammar["segments"][0]["reason"].lower())
