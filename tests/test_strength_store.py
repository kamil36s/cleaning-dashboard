import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from strength_store import StrengthStore


class StrengthStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "strength.sqlite"
        self.store = StrengthStore(self.database_path)
        self.store.initialize()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def save_bodyweight_set(self, set_id, session_id, exercise_id, reps, completed_at, set_type="quality"):
        exercise = next(item for item in self.store.exercises() if item["id"] == exercise_id)
        return self.store.save_set({
            "id": set_id, "sessionId": session_id, "exerciseId": exercise_id,
            "techniqueVariantId": exercise["techniqueVariantId"], "reps": reps,
            "completedAt": completed_at, "loadStatus": "bodyweight", "loadLabel": "Bodyweight",
            "setType": set_type, "rir": 2,
        })

    def test_individual_set_survives_interrupted_session(self):
        session = self.store.start_session({"id": "interrupted", "mode": "freestyle"})
        self.save_bodyweight_set("durable-set", session["id"], "push-up-v2", 9, 1_789_000_000_000)
        reopened = StrengthStore(self.database_path)
        saved = next(item for item in reopened.history() if item["id"] == "durable-set")
        self.assertEqual(saved["reps"], 9)
        self.assertEqual(saved["session_id"], "interrupted")

    def test_weekly_volume_counts_quality_primary_sets_only_and_resets_view(self):
        session = self.store.start_session({"id": "weekly", "mode": "freestyle"})
        first_week = int(datetime(2026, 9, 10, 12).timestamp() * 1000)
        second_week = int(datetime(2026, 9, 17, 12).timestamp() * 1000)
        self.save_bodyweight_set("quality-one", session["id"], "push-up-v2", 10, first_week)
        self.save_bodyweight_set("warmup", session["id"], "push-up-v2", 8, first_week + 60_000, "warmup")
        self.save_bodyweight_set("quality-next-week", session["id"], "push-up-v2", 11, second_week)
        first = next(item for item in self.store.weekly_scoreboard("2026-09-10")["groups"] if item["muscle_group"] == "chest")
        second = next(item for item in self.store.weekly_scoreboard("2026-09-17")["groups"] if item["muscle_group"] == "chest")
        self.assertEqual(first["sets"], 1)
        self.assertEqual(second["sets"], 1)
        self.assertEqual(len([item for item in self.store.history() if item["exercise_id"] == "push-up-v2"]), 3)

    def test_higher_total_reps_at_same_load_and_technique_creates_total_rep_pr(self):
        for session_id, reps, start in (("previous", [10, 10], 1_788_900_000_000), ("current", [11, 10], 1_789_000_000_000)):
            self.store.start_session({"id": session_id, "mode": "freestyle", "startedAt": start})
            for index, count in enumerate(reps):
                self.store.save_set({
                    "id": f"{session_id}-{index}", "sessionId": session_id,
                    "exerciseId": "standing-alternating-dumbbell-curl",
                    "techniqueVariantId": "curl-continuous-alternating", "reps": count,
                    "rir": 2, "completedAt": start + index * 60_000, "platesWeightKg": 5,
                    "loadStatus": "partial", "loadLabel": "5 kg plates + uncalibrated hardware",
                })
        with sqlite3.connect(self.database_path) as connection:
            records = connection.execute("SELECT record_type, value FROM strength_personal_records WHERE set_id='current-1'").fetchall()
        self.assertIn(("total_rep_pr", 21.0), records)

    def test_different_technique_variant_does_not_compare_against_baseline(self):
        session = self.store.start_session({"id": "new-technique", "mode": "freestyle"})
        result = self.store.save_set({
            "id": "full-rep", "sessionId": session["id"],
            "exerciseId": "standing-alternating-dumbbell-curl",
            "techniqueVariantId": "curl-full-rep-alternating", "reps": 20, "rir": 1,
            "platesWeightKg": 7.5, "loadStatus": "partial",
            "loadLabel": "7.5 kg plates + uncalibrated hardware",
        })
        self.assertEqual(result["records"], [])

    def test_set_xp_is_idempotent(self):
        session = self.store.start_session({"id": "xp", "mode": "freestyle"})
        payload = {
            "id": "same-set", "sessionId": session["id"], "exerciseId": "push-up-v2",
            "techniqueVariantId": "push-up-standard", "reps": 10, "rir": 2,
            "loadStatus": "bodyweight", "loadLabel": "Bodyweight",
        }
        first = self.store.save_set(payload)
        duplicate = self.store.save_set(payload)
        self.assertEqual(first["xpAwarded"], 10)
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(self.store.dashboard()["xp"]["total"], 10)

    def test_recovery_is_advisory_and_never_blocks_manual_selection(self):
        self.store.report_recovery({"muscleGroup": "back", "soreness": 5})
        recovery = next(item for item in self.store.dashboard()["recovery"] if item["muscleGroup"] == "back")
        self.assertEqual(recovery["status"], "red")
        self.assertTrue(recovery["manualSelectionAllowed"])

    def test_migrates_legacy_fbw_sets_idempotently_without_false_exact_load(self):
        legacy = [{
            "id": "dashboard-old", "workout_type": "strength", "status": "finished",
            "started_at": 1_788_800_000_000, "duration_seconds": 300,
            "strength_data": {"exercises": [{
                "exerciseId": "dumbbell-floor-press", "plannedSets": 2,
                "sets": [
                    {"setNumber": 1, "actualWeightPerDumbbellKg": 7.5, "actualReps": 10, "actualRir": 2},
                    {"setNumber": 2, "actualWeightPerDumbbellKg": 7.5, "actualReps": 9, "actualRir": 1},
                ],
            }]},
        }]
        first = self.store.migrate_live_workout_history(legacy)
        second = self.store.migrate_live_workout_history(legacy)
        migrated = [item for item in self.store.history() if item["session_id"] == "legacy-dashboard-old"]
        self.assertEqual(first, {"sessions": 1, "sets": 2})
        self.assertEqual(second, {"sessions": 0, "sets": 0})
        self.assertEqual(len(migrated), 2)
        self.assertTrue(all(item["load_status"] == "partial" and item["load_kg"] is None for item in migrated))

    def test_strength_backup_round_trip_preserves_sets(self):
        session = self.store.start_session({"id": "backup-session", "mode": "freestyle"})
        self.save_bodyweight_set("backup-set", session["id"], "push-up-v2", 12, 1_789_000_000_000)
        backup = self.store.export_data()
        other = StrengthStore(Path(self.temporary_directory.name) / "restored.sqlite")
        merged = other.import_data(backup)
        self.assertGreaterEqual(merged["sets"], 1)
        self.assertTrue(any(item["id"] == "backup-set" for item in other.history()))


if __name__ == "__main__":
    unittest.main()
