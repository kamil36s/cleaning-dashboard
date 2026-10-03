import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from language_learning.errors import LanguageConflictError, LanguageValidationError
from language_learning.service import LanguageService
from language_learning.statistics import classify_lemma, week_bounds
from language_learning.store import LanguageStore


AS_OF = "2026-03-29T10:00:00Z"


class LanguageStatisticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = LanguageStore(Path(self.temp.name) / "language.sqlite")
        self.service = LanguageService(self.store)
        self.service.initialize()
        self.profile = self.service.ensure_bokmal_profile()["profile"]

    def tearDown(self):
        self.temp.cleanup()

    def lemma(self, name):
        return self.service.upsert_lemma(
            self.profile["id"], name, part_of_speech="NOUN"
        )["lemma"]

    def set_knowledge(self, lemma, status, *, recognition=None, recall=None, production=None,
                      exposures=0, event_at="2026-03-23T08:00:00Z"):
        payload = {
            "before": {"knowledge_status": "NEW", "disposition": "TRACKED"},
            "applied": {"knowledge_status": status},
        }
        with self.store.connection() as connection:
            connection.execute(
                "UPDATE vocabulary_lemmas SET created_at='2026-03-20T08:00:00Z' WHERE id=?",
                (lemma["id"],),
            )
            connection.execute(
                "UPDATE lemma_knowledge SET knowledge_status=?,recognition=?,recall=?,production=?,"
                "total_exposures=?,first_seen_at=?,last_seen_at=?,updated_at=? WHERE lemma_id=?",
                (status, recognition, recall, production, exposures, event_at, event_at, event_at, lemma["id"]),
            )
            connection.execute(
                "INSERT INTO knowledge_events(id,lemma_id,event_type,source,payload_json,created_at) "
                "VALUES(?,?,?,?,?,?)",
                (name_id(f"event-{lemma['id']}"), lemma["id"], "MANUAL_KNOWLEDGE_UPDATE", "TEST", json.dumps(payload), event_at),
            )

    def test_classifier_policy_is_deterministic_and_conservative(self):
        active = classify_lemma({
            "knowledge_status": "KNOWN", "disposition": "TRACKED", "recognition": 5,
            "recall": 4, "production": 2, "total_exposures": 5,
            "first_advanced_at": "2026-03-20T00:00:00Z",
        }, as_of=AS_OF)
        passive = classify_lemma({
            "knowledge_status": "KNOWN", "disposition": "TRACKED", "recognition": 4,
            "recall": 3, "production": 2, "total_exposures": 2,
            "first_advanced_at": "2026-03-01T00:00:00Z",
        }, as_of=AS_OF)
        mastered = classify_lemma({
            "knowledge_status": "MASTERED", "disposition": "TRACKED", "total_exposures": 100,
        }, as_of=AS_OF)
        exposure_only = classify_lemma({
            "knowledge_status": "NEW", "disposition": "TRACKED", "total_exposures": 100,
        }, as_of=AS_OF)
        self.assertTrue(active["active"])
        self.assertFalse(active["passive"])
        self.assertTrue(passive["passive"])
        self.assertTrue(passive["underexposed"])
        self.assertTrue(mastered["mastered"])
        self.assertFalse(exposure_only["mastered"])

    def test_recent_and_underexposed_boundaries(self):
        inside = classify_lemma({
            "knowledge_status": "LEARNING", "disposition": "TRACKED", "total_exposures": 2,
            "first_advanced_at": "2026-03-15T10:00:01Z",
        }, as_of=AS_OF)
        boundary = classify_lemma({
            "knowledge_status": "LEARNING", "disposition": "TRACKED", "total_exposures": 3,
            "first_advanced_at": "2026-03-15T10:00:00Z",
        }, as_of=AS_OF)
        self.assertTrue(inside["recent"])
        self.assertTrue(inside["underexposed"])
        self.assertFalse(boundary["recent"])
        self.assertFalse(boundary["underexposed"])

    def test_week_bounds_handle_warsaw_dst_forward_and_backward(self):
        spring_start, spring_end = week_bounds("2026-03-29T10:00:00Z")
        autumn_start, autumn_end = week_bounds("2026-10-25T10:00:00Z")
        self.assertEqual(spring_start.isoformat(), "2026-03-22T23:00:00+00:00")
        self.assertEqual(spring_end.isoformat(), "2026-03-29T22:00:00+00:00")
        self.assertEqual((spring_end - spring_start).total_seconds(), 167 * 3600)
        self.assertEqual(autumn_start.isoformat(), "2026-10-18T22:00:00+00:00")
        self.assertEqual(autumn_end.isoformat(), "2026-10-25T23:00:00+00:00")
        self.assertEqual((autumn_end - autumn_start).total_seconds(), 169 * 3600)

    def test_week_bounds_use_warsaw_local_midnight(self):
        start, end = week_bounds("2026-06-15T00:30:00Z")
        self.assertEqual(start.isoformat(), "2026-06-14T22:00:00+00:00")
        self.assertEqual(end.isoformat(), "2026-06-21T22:00:00+00:00")

    def test_statistics_use_events_exposures_active_seconds_and_frozen_coverage(self):
        learning = self.lemma("jobb")
        known = self.lemma("bok")
        mastered = self.lemma("hus")
        self.set_knowledge(learning, "LEARNING", recognition=3, exposures=2)
        self.set_knowledge(known, "KNOWN", recognition=5, recall=4, exposures=5, event_at="2026-03-24T08:00:00Z")
        self.set_knowledge(mastered, "MASTERED", exposures=7, event_at="2026-03-25T08:00:00Z")
        text_id = name_id("text")
        session_id = name_id("session")
        with self.store.connection() as connection:
            connection.execute(
                "INSERT INTO text_documents(id,language_profile_id,title,raw_text,source_type,content_fingerprint,"
                "processing_state,offset_unit,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (text_id, self.profile["id"], "Fixture", "jobb bok", "PASTED", "sha256:test", "ANALYZED", "UNICODE_CODE_POINT", "2026-03-20T00:00:00Z", "2026-03-28T00:00:00Z"),
            )
            connection.execute(
                "INSERT INTO study_sessions(id,language_profile_id,text_document_id,session_type,status,started_at,"
                "ended_at,active_seconds,created_at,updated_at,activity_state) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (session_id, self.profile["id"], text_id, "READER", "COMPLETED", "2026-03-28T10:00:00Z", "2026-03-28T10:10:00Z", 600, "2026-03-28T10:00:00Z", "2026-03-28T10:10:00Z", "PAUSED"),
            )
            connection.execute(
                "INSERT INTO exposure_events(id,idempotency_key,language_profile_id,lemma_id,text_document_id,"
                "study_session_id,source_type,occurrence_count,occurred_at,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (name_id("exposure"), "batch:jobb", self.profile["id"], learning["id"], text_id, session_id, "READER", 4, "2026-03-29T08:00:00Z", "2026-03-29T08:00:00Z"),
            )
            connection.execute(
                "INSERT INTO text_reading_progress(text_document_id,language_profile_id,status,progress_source_offset,"
                "last_read_at,completed_at,coverage_snapshot_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (text_id, self.profile["id"], "COMPLETED", 8, "2026-03-29T09:00:00Z", "2026-03-29T09:00:00Z", json.dumps({"policyVersion": "language.coverage-policy/v1", "tokenCoveragePercent": 75, "uniqueLemmaCoveragePercent": 50}), "2026-03-29T09:00:00Z", "2026-03-29T09:00:00Z"),
            )
        result = self.service.statistics(self.profile["id"], range_name="7d", as_of=AS_OF)["data"]
        self.assertEqual(result["vocabulary"]["newlyAdvanced"], 3)
        self.assertEqual(len(result["vocabulary"]["series"]), 7)
        self.assertEqual(result["vocabulary"]["series"][-1]["learning"], 1)
        self.assertEqual(result["vocabulary"]["series"][-1]["known"], 1)
        self.assertEqual(result["vocabulary"]["series"][-1]["mastered"], 1)
        self.assertEqual(result["vocabulary"]["classifierCounts"]["active"], 1)
        self.assertEqual(result["exposures"]["totalReaderOccurrences"], 4)
        self.assertEqual(result["exposures"]["highExposure"][0], {
            "lemmaId": learning["id"], "lemma": "jobb", "occurrenceCount": 4,
        })
        self.assertEqual(result["reading"]["activeSeconds"], 600)
        self.assertEqual(result["reading"]["textsCompleted"], 1)
        self.assertEqual(result["streak"]["currentDays"], 2)
        self.assertEqual(result["coverage"]["completedTextAveragePercent"], 75)
        self.assertFalse(result["coverage"]["historicalSnapshotsRescored"])
        self.assertFalse(result["frequencyCoverage"]["configured"])

    def test_topic_crud_manual_membership_and_weighted_mastery(self):
        new = self.lemma("ny")
        known = self.lemma("kjent")
        mastered = self.lemma("mester")
        self.set_knowledge(known, "KNOWN", recall=4)
        self.set_knowledge(mastered, "MASTERED")
        topic = self.service.create_topic(self.profile["id"], {
            "displayName": "Work", "description": "Manual scope",
        })["data"]["topic"]
        for lemma, weight in ((new, 1), (known, 2), (mastered, 1)):
            self.service.assign_topic_lemma(topic["id"], {"lemmaId": lemma["id"], "weight": weight})
        detail = self.service.get_topic(topic["id"], as_of=AS_OF)["data"]
        self.assertEqual(detail["mastery"]["weightedMasteryPercent"], 62.5)
        self.assertEqual(detail["mastery"]["denominatorQuality"]["scope"], "USER_MAPPED_LEMMAS_ONLY")
        self.assertFalse(detail["mastery"]["denominatorQuality"]["completeTopicDomain"])
        self.assertTrue(all(item["provenance"] == "MANUAL" for item in detail["lemmas"]))
        self.service.update_topic(topic["id"], {"displayName": "Work & tools", "archived": True})
        self.service.remove_topic_lemma(topic["id"], new["id"])
        updated = self.service.get_topic(topic["id"])["data"]
        self.assertEqual(updated["topic"]["displayName"], "Work & tools")
        self.assertTrue(updated["topic"]["archived"])
        self.assertEqual(len(updated["lemmas"]), 2)

    def test_topic_assignment_rejects_cross_profile_and_unreviewed_import(self):
        lemma = self.lemma("jobb")
        other = self.service.create_profile({
            "languageCode": "nn", "locale": "nn-NO", "displayName": "Nynorsk",
        })["data"]["profile"]
        topic = self.service.create_topic(other["id"], {"displayName": "Work"})["data"]["topic"]
        with self.assertRaises(LanguageConflictError):
            self.service.assign_topic_lemma(topic["id"], {"lemmaId": lemma["id"]})
        with self.assertRaises(LanguageValidationError):
            self.service.assign_topic_lemma(topic["id"], {
                "lemmaId": lemma["id"], "provenance": "IMPORT", "membershipState": "IMPORTED",
            })

    def test_goal_progress_is_derived_and_validated(self):
        lemma = self.lemma("jobb")
        self.set_knowledge(lemma, "LEARNING", event_at="2026-03-23T08:00:00Z")
        goal = self.service.create_goal(self.profile["id"], {
            "metric": "NEW_WORDS", "targetValue": 2, "unit": "WORDS",
        })["data"]["goal"]
        item = self.service.list_goals(self.profile["id"], as_of=AS_OF)["data"]["items"][0]
        self.assertEqual(item["current"], 1)
        self.assertEqual(item["remaining"], 1)
        self.assertEqual(item["percentage"], 50)
        self.assertTrue(item["activeNow"])
        completed_goal = self.service.create_goal(self.profile["id"], {
            "metric": "NEW_WORDS", "targetValue": 1, "unit": "WORDS",
        })["data"]["goal"]
        completed = next(
            candidate for candidate in self.service.list_goals(self.profile["id"], as_of=AS_OF)["data"]["items"]
            if candidate["goal"]["id"] == completed_goal["id"]
        )
        self.assertTrue(completed["completed"])
        self.assertEqual(completed["remaining"], 0)
        self.assertEqual(completed["percentage"], 100)
        disabled = self.service.update_goal(goal["id"], {"enabled": False})["data"]
        self.assertFalse(disabled["goal"]["enabled"])
        with self.assertRaises(LanguageValidationError):
            self.service.create_goal(self.profile["id"], {"metric": "NEW_WORDS", "targetValue": 0})
        with self.assertRaises(LanguageValidationError):
            self.service.create_goal(self.profile["id"], {
                "metric": "NEW_WORDS", "targetValue": 3, "unit": "MINUTES",
            })
        with self.assertRaises(LanguageValidationError):
            self.service.create_goal(self.profile["id"], {
                "metric": "NEW_WORDS", "targetValue": 3,
                "activeFrom": "2026-04-01", "activeUntil": "2026-03-01",
            })

    def test_learning_plan_is_deterministic_bounded_and_contains_no_anki_work(self):
        lemma = self.lemma("jobb")
        self.set_knowledge(lemma, "LEARNING", exposures=1)
        first = self.service.learning_plan(self.profile["id"], as_of=AS_OF)["data"]
        second = self.service.learning_plan(self.profile["id"], as_of=AS_OF)["data"]
        self.assertEqual(first, second)
        self.assertLessEqual(len(first["items"]), 5)
        self.assertTrue(any(item["kind"] == "REVIEW_WEAK" for item in first["items"]))
        self.assertTrue(first["wordsToRecycle"]["items"][0]["reasons"])
        self.assertEqual(first["anki"], {"status": "NOT_CONFIGURED", "recommendations": 0})
        self.assertFalse(any("ANKI" in item["kind"] for item in first["items"]))

    def test_learning_plan_prioritizes_unfinished_goal_and_weak_work(self):
        lemma = self.lemma("jobb")
        self.set_knowledge(lemma, "LEARNING", exposures=1)
        self.service.create_goal(self.profile["id"], {
            "metric": "ACTIVE_READING_MINUTES", "targetValue": 30, "unit": "MINUTES",
        })
        text_id = name_id("unfinished-plan-text")
        with self.store.connection() as connection:
            connection.execute(
                "INSERT INTO text_documents(id,language_profile_id,title,raw_text,source_type,content_fingerprint,"
                "processing_state,offset_unit,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (text_id, self.profile["id"], "Continue me", "jobb", "PASTED", "sha256:plan", "ANALYZED", "UNICODE_CODE_POINT", "2026-03-20T00:00:00Z", "2026-03-28T00:00:00Z"),
            )
            connection.execute(
                "INSERT INTO text_reading_progress(text_document_id,language_profile_id,status,progress_source_offset,"
                "last_read_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                (text_id, self.profile["id"], "IN_PROGRESS", 2, "2026-03-28T09:00:00Z", "2026-03-28T09:00:00Z", "2026-03-28T09:00:00Z"),
            )
        plan = self.service.learning_plan(self.profile["id"], as_of=AS_OF)["data"]
        kinds = [item["kind"] for item in plan["items"]]
        self.assertEqual(kinds[:4], ["CONTINUE_READING", "GOAL_GAP", "REVIEW_WEAK", "RECYCLE_WORDS"])
        self.assertLessEqual(len(kinds), 5)

    def test_empty_profile_plan_is_truthful_and_bounded(self):
        other = self.service.create_profile({
            "languageCode": "sv", "locale": "sv-SE", "displayName": "Swedish",
        })["data"]["profile"]
        plan = self.service.learning_plan(other["id"], as_of=AS_OF)["data"]
        self.assertEqual([item["kind"] for item in plan["items"]], ["ADD_TEXT"])
        self.assertEqual(plan["wordsToRecycle"]["items"], [])
        self.assertEqual(plan["anki"]["status"], "NOT_CONFIGURED")

    def test_streak_splits_activity_at_warsaw_midnight(self):
        text_id = name_id("midnight-text")
        with self.store.connection() as connection:
            connection.execute(
                "INSERT INTO text_documents(id,language_profile_id,title,raw_text,source_type,content_fingerprint,"
                "processing_state,offset_unit,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (text_id, self.profile["id"], "Midnight", "jobb", "PASTED", "sha256:midnight", "DRAFT", "UNICODE_CODE_POINT", "2026-06-14T00:00:00Z", "2026-06-15T00:00:00Z"),
            )
            for suffix, started in (("sun", "2026-06-14T21:30:00Z"), ("mon", "2026-06-14T22:30:00Z")):
                connection.execute(
                    "INSERT INTO study_sessions(id,language_profile_id,text_document_id,session_type,status,started_at,"
                    "ended_at,active_seconds,created_at,updated_at,activity_state) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (name_id(suffix), self.profile["id"], text_id, "READER", "COMPLETED", started, started, 60, started, started, "PAUSED"),
                )
        result = self.service.statistics(
            self.profile["id"], range_name="7d", as_of="2026-06-15T10:00:00Z"
        )["data"]
        self.assertEqual(result["streak"]["currentDays"], 2)


def name_id(value):
    import hashlib
    return hashlib.md5(value.encode("utf-8"), usedforsecurity=False).hexdigest()


if __name__ == "__main__":
    unittest.main()
