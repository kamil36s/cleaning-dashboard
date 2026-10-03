import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from language_learning.errors import LanguageConflictError
from language_learning.gamification import (
    ACHIEVEMENT_POLICY_VERSION,
    GamificationService,
    XP_POLICY_VERSION,
    level_floor,
    level_from_xp,
)
from language_learning.service import LanguageService
from language_learning.store import LanguageStore


def stable_id(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


class FakeClozeReference:
    def targets(self, minimum=1, maximum=6000):
        rows = [{"id": "one", "stable_key": "kelly:1", "rank": 1},
                {"id": "two", "stable_key": "kelly:2", "rank": 2}]
        return [row for row in rows if minimum <= row["rank"] <= maximum]

    def playable_target_ids(self):
        return {"one"}

    def playable_targets(self, minimum, maximum):
        return [row for row in self.targets(minimum, maximum) if row["id"] in self.playable_target_ids()]


class FakeClozeService:
    def __init__(self):
        self.reference = FakeClozeReference()


class LanguageGamificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = LanguageStore(Path(self.temp.name) / "language.sqlite")
        self.service = LanguageService(self.store)
        self.service.initialize()
        self.profile = self.service.ensure_bokmal_profile()["profile"]
        self.lemma = self.service.upsert_lemma(
            self.profile["id"], "jobb", part_of_speech="NOUN"
        )["lemma"]

    def tearDown(self):
        self.temp.cleanup()

    def add_reader_evidence(self, *, exposure_events=25, active_seconds=125, completed=True):
        text_id = stable_id("text")
        session_id = stable_id("reader-session")
        with self.store.connection() as connection:
            connection.execute(
                "INSERT INTO text_documents(id,language_profile_id,title,raw_text,source_type,"
                "content_fingerprint,processing_state,offset_unit,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (text_id, self.profile["id"], "Reader", "jobb", "PASTED", "sha256:test", "ANALYZED",
                 "UNICODE_CODE_POINT", "2026-09-15T08:00:00Z", "2026-09-15T08:00:00Z"),
            )
            connection.execute(
                "INSERT INTO study_sessions(id,language_profile_id,text_document_id,session_type,status,"
                "started_at,ended_at,active_seconds,created_at,updated_at,activity_state) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (session_id, self.profile["id"], text_id, "READER", "COMPLETED",
                 "2026-09-15T08:00:00Z", "2026-09-15T08:03:00Z", active_seconds,
                 "2026-09-15T08:00:00Z", "2026-09-15T08:03:00Z", "PAUSED"),
            )
            for index in range(exposure_events):
                event_id = stable_id(f"exposure-{index}")
                connection.execute(
                    "INSERT INTO exposure_events(id,idempotency_key,language_profile_id,lemma_id,"
                    "text_document_id,study_session_id,source_type,occurrence_count,occurred_at,created_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (event_id, f"exposure-{index}", self.profile["id"], self.lemma["id"], text_id,
                     session_id, "READER", 1, f"2026-09-15T08:{index:02d}:00Z", f"2026-09-15T08:{index:02d}:00Z"),
                )
            if completed:
                connection.execute(
                    "INSERT INTO text_reading_progress(text_document_id,language_profile_id,status,"
                    "progress_source_offset,last_read_at,completed_at,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (text_id, self.profile["id"], "COMPLETED", 4, "2026-09-15T08:04:00Z",
                     "2026-09-15T08:04:00Z", "2026-09-15T08:04:00Z", "2026-09-15T08:04:00Z"),
                )
        return text_id, session_id

    def add_cloze_attempts(self, outcomes, *, target="kelly:1", dates=None):
        session_id = stable_id(f"cloze-{target}-{len(outcomes)}")
        with self.store.connection() as connection:
            connection.execute(
                "INSERT INTO cloze_sessions(id,language_profile_id,mode,track_key,track_version,"
                "requested_item_count,seed,items_json,status,started_at,completed_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (session_id, self.profile["id"], "FAST_TRACK", "FAST_TRACK_1",
                 "language.cloze-fast-track/v1", 10, "seed", "[]", "COMPLETED",
                 "2026-09-15T09:00:00Z", "2026-09-16T09:10:00Z", "2026-09-16T09:10:00Z"),
            )
            for index, outcome in enumerate(outcomes):
                attempted_at = (dates or [None] * len(outcomes))[index] or f"2026-09-15T09:{index:02d}:00Z"
                attempt_id = stable_id(f"attempt-{target}-{index}")
                connection.execute(
                    "INSERT INTO cloze_attempts(id,session_id,item_index,target_lemma_id,"
                    "reference_target_stable_key,reference_sentence_source,reference_sentence_id,"
                    "item_snapshot_json,item_fingerprint,expected_surface_form,options_json,chosen_option,"
                    "outcome,response_ms,idempotency_key,attempted_at,rule_versions_json) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (attempt_id, session_id, index, self.lemma["id"], target, "tatoeba", str(index),
                     "{}", f"fingerprint-{index}", "jobb", "[]", "jobb" if outcome in {"CORRECT", "INCORRECT"} else None,
                     outcome, 500, f"attempt-{target}-{index}", attempted_at, "{}"),
                )
        return session_id

    def test_level_curve_boundaries_and_monotonicity(self):
        self.assertEqual(level_floor(1), 0)
        self.assertEqual(level_floor(2), 50)
        self.assertEqual(level_floor(3), 150)
        self.assertEqual(level_from_xp(0)["level"], 1)
        self.assertEqual(level_from_xp(49)["level"], 1)
        self.assertEqual(level_from_xp(50)["level"], 2)
        self.assertEqual(level_from_xp(149)["level"], 2)
        self.assertEqual(level_from_xp(150)["level"], 3)
        levels = [level_from_xp(value)["level"] for value in range(0, 100000, 137)]
        self.assertEqual(levels, sorted(levels))
        self.assertEqual(level_from_xp(50000)["ruleVersion"], "language.gamification-levels/v1")

    def test_reconciliation_has_exact_xp_is_idempotent_and_bounded(self):
        self.add_reader_evidence()
        self.add_cloze_attempts([
            "CORRECT", "INCORRECT", "REVEALED", "SKIPPED", "CORRECT", "CORRECT", "CORRECT",
        ])
        first = self.service.gamification_service.reconcile_profile(
            self.profile["id"], as_of="2026-09-17T10:00:00Z"
        )
        # Reader: 2 minutes * 2 + completion 20 + first 20 exposure events = 44.
        # Cloze: first three scored target/day attempts 5 + 2 + 5, plus one recovery bonus 3 = 15.
        self.assertEqual(first["lifetimeXp"], 59)
        self.assertEqual(first["xpAwarded"], 59)
        second = self.service.gamification_service.reconcile_profile(
            self.profile["id"], as_of="2026-09-17T10:00:00Z"
        )
        self.assertEqual(second["xpAwarded"], 0)
        self.assertEqual(second["lifetimeXp"], 59)
        ledger = self.store.gamification_ledger(self.profile["id"], recent_limit=50)
        self.assertTrue(all(item["xpAmount"] > 0 for item in ledger["recent"]))
        self.assertTrue(all(item["ruleVersion"] == XP_POLICY_VERSION for item in ledger["recent"]))

    def test_page_reads_do_not_award_xp_and_quests_are_deterministic(self):
        before = self.store.gamification_ledger(self.profile["id"])["lifetimeXp"]
        first = self.service.quests(self.profile["id"], as_of="2026-10-25T00:30:00Z")["data"]
        second = self.service.quests(self.profile["id"], as_of="2026-10-25T20:30:00Z")["data"]
        next_day = self.service.quests(self.profile["id"], as_of="2026-10-25T23:30:00Z")["data"]
        self.assertEqual(first["snapshotId"], second["snapshotId"])
        self.assertEqual(first["items"], second["items"])
        self.assertEqual(len(first["items"]), 3)
        self.assertNotEqual(first["localStudyDate"], next_day["localStudyDate"])
        self.service.gamification(self.profile["id"], as_of="2026-10-25T20:30:00Z")
        self.assertEqual(self.store.gamification_ledger(self.profile["id"])["lifetimeXp"], before)

    def test_achievement_unlock_is_idempotent_and_preserves_original_time(self):
        self.add_reader_evidence(exposure_events=1, active_seconds=60, completed=True)
        result = self.service.gamification_service.reconcile_profile(
            self.profile["id"], as_of="2026-09-17T10:00:00Z"
        )
        self.assertGreaterEqual(result["achievementsUnlocked"], 2)
        first = self.service.achievements(self.profile["id"])["data"]
        completion = next(item for item in first["items"] if item["key"] == "READER_FIRST_COMPLETION")
        self.assertEqual(completion["state"], "UNLOCKED")
        self.assertEqual(completion["unlockedAt"], "2026-09-15T08:04:00Z")
        self.service.gamification_service.reconcile_profile(
            self.profile["id"], as_of="2027-01-01T00:00:00Z"
        )
        again = next(
            item for item in self.service.achievements(self.profile["id"])["data"]["items"]
            if item["key"] == "READER_FIRST_COMPLETION"
        )
        self.assertEqual(again["unlockedAt"], completion["unlockedAt"])
        self.assertEqual(again["definitionVersion"], ACHIEVEMENT_POLICY_VERSION)

    def test_fast_track_collection_discloses_playable_denominator_and_reliable_rule(self):
        dates = ["2026-09-15T09:00:00Z", "2026-09-15T09:01:00Z", "2026-09-16T09:00:00Z"]
        self.add_cloze_attempts(["CORRECT", "CORRECT", "CORRECT"], dates=dates)
        self.service.gamification_service.attach_cloze_service(FakeClozeService())
        collection = self.service.collections(self.profile["id"])["data"]["items"][0]
        self.assertEqual(collection["collectionKey"], "FAST_TRACK_1")
        self.assertEqual(collection["allRankedTargets"], 2)
        self.assertEqual(collection["totalEligible"], 1)
        self.assertEqual(collection["unresolved"], 1)
        self.assertEqual(collection["stateCounts"]["RELIABLE"], 1)
        self.assertEqual(collection["progressPercent"], 100)
        self.assertIn("Reveal/Skip", collection["completionStateRule"])

    def test_campaigns_are_generic_multidimensional_and_future_packs_are_unavailable(self):
        future = self.service.create_campaign(self.profile["id"], {
            "name": "Norway Spring 2027", "targetDate": "2027-05-01",
            "milestones": [
                {"type": "READER_TEXTS_COMPLETED", "target": 5},
                {"type": "CLOZE_ATTEMPTS", "target": 100},
            ],
        })["data"]["campaign"]
        self.assertIsNone(future["universalReadinessPercent"])
        self.assertEqual(len(future["milestones"]), 2)
        updated = self.service.update_campaign(future["id"], {
            "name": "Norway Autumn 2027", "targetDate": "2020-01-01", "enabled": False,
        })["data"]["campaign"]
        self.assertEqual(updated["name"], "Norway Autumn 2027")
        self.assertFalse(updated["enabled"])
        self.assertEqual(updated["dateState"], "PAST")
        with self.assertRaises(LanguageConflictError):
            self.service.create_campaign(self.profile["id"], {
                "name": "Fake pack", "targetDate": "2027-01-01",
                "milestones": [{"type": "WAREHOUSE", "target": 75}],
            })

    def test_gamification_operations_do_not_mutate_canonical_learning_truth(self):
        self.add_reader_evidence(exposure_events=2, active_seconds=60)
        self.add_cloze_attempts(["INCORRECT", "REVEALED", "SKIPPED"])
        canonical_tables = [
            "vocabulary_lemmas", "lemma_knowledge", "knowledge_events", "exposure_events",
            "cloze_attempts", "anki_card_snapshots", "topics", "topic_lemmas",
        ]
        with self.store.connection() as connection:
            before = {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in canonical_tables}
        self.service.gamification_service.reconcile_profile(self.profile["id"])
        self.service.achievements(self.profile["id"])
        self.service.collections(self.profile["id"])
        self.service.quests(self.profile["id"], as_of="2026-09-17T10:00:00Z")
        self.service.create_campaign(self.profile["id"], {
            "name": "Norway", "targetDate": "2027-01-01",
            "milestones": [{"type": "CLOZE_ATTEMPTS", "target": 10}],
        })
        with self.store.connection() as connection:
            after = {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in canonical_tables}
        self.assertEqual(after, before)

    def test_export_contains_only_durable_gamification_facts(self):
        self.service.gamification_service.reconcile_profile(self.profile["id"])
        self.service.quests(self.profile["id"], as_of="2026-09-17T10:00:00Z")
        export = self.store.export_data()
        self.assertEqual(export["exportVersion"], "language-learning-export/v16")
        self.assertIn("gamificationAwards", export["data"])
        self.assertIn("achievementUnlocks", export["data"])
        self.assertIn("gamificationQuestSnapshots", export["data"])
        self.assertIn("campaignDefinitions", export["data"])
        self.assertNotIn("lifetimeXp", export["data"])


if __name__ == "__main__":
    unittest.main()
