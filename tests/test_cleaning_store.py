import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from cleaning_store import CleaningError, CleaningStore


WARSAW = ZoneInfo("Europe/Warsaw")


class CleaningStoreTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.store = CleaningStore(Path(self.tempdir.name) / "cleaning.sqlite")

    def tearDown(self):
        self.tempdir.cleanup()

    def add_task(self, **overrides):
        payload = {
            "room": "Kuchnia",
            "category": "Blaty",
            "task": "Umyj blat",
            "freq": 7,
            "articles": "Ściereczka, spray",
            "notes": "",
        }
        payload.update(overrides)
        return self.store.add_task("aleja-pokoju6", payload)

    def test_database_uses_wal_and_foreign_keys(self):
        with self.store._connect() as conn:
            self.assertEqual(conn.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")
            self.assertEqual(conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        self.assertEqual(self.store.integrity_check(), "ok")

    def test_state_keeps_existing_status_and_kpi_contract(self):
        old_day = (datetime.now(WARSAW) - timedelta(days=20)).date().isoformat()
        task = self.add_task(lastDone=old_day, freq=7)
        state = self.store.get_state("aleja-pokoju6")
        self.assertEqual(task["status"], "DEAD")
        self.assertEqual(state["kpi"]["total"], 1)
        self.assertEqual(state["kpi"]["overdue"], 1)
        self.assertGreater(state["kpi"]["avgDelay"], 7)

    def test_mark_done_and_undo_are_atomic_and_auditable(self):
        old_day = (datetime.now(WARSAW) - timedelta(days=10)).date().isoformat()
        task = self.add_task(lastDone=old_day)
        done = self.store.mark_done(task["id"], "aleja-pokoju6", source="cleaning-page")
        self.assertEqual(done["task"]["status"], "FRESH")
        history = self.store.get_history("aleja-pokoju6", "all")
        self.assertEqual(len(history["actions"]), 1)

        reverted = self.store.revert_last_action(done["action"]["id"])
        restored_day = datetime.fromisoformat(reverted["task"]["lastDone"].replace("Z", "+00:00")).astimezone(WARSAW).date()
        self.assertEqual(restored_day.isoformat(), old_day)
        self.assertEqual(self.store.get_history("aleja-pokoju6", "all")["actions"], [])
        self.assertEqual(self.store.counts()["actions"], 1)

    def test_phone_goal_counts_only_actions_after_six_am_and_excludes_undo(self):
        first = self.add_task(task="Before six")
        second = self.add_task(task="After six")
        self.store.mark_done(first["id"],"aleja-pokoju6",done_at="2026-09-26T05:30:00+02:00")
        action = self.store.mark_done(second["id"],"aleja-pokoju6",done_at="2026-09-26T06:30:00+02:00")
        self.assertEqual(self.store.count_actions_for_day("aleja-pokoju6","2026-09-26"),1)
        self.store.revert_last_action(action["action"]["id"])
        self.assertEqual(self.store.count_actions_for_day("aleja-pokoju6","2026-09-26"),0)

    def test_removing_one_duplicate_action_restores_previous_completion(self):
        old_day = (datetime.now(WARSAW) - timedelta(days=10)).date().isoformat()
        task = self.add_task(lastDone=old_day)
        first_at = (datetime.now(WARSAW) - timedelta(minutes=2)).isoformat()
        second_at = datetime.now(WARSAW).isoformat()
        first = self.store.mark_done(task["id"], "aleja-pokoju6", done_at=first_at)
        second = self.store.mark_done(task["id"], "aleja-pokoju6", done_at=second_at)

        removed = self.store.remove_action(second["action"]["id"], "aleja-pokoju6")

        self.assertTrue(removed["softDeleted"])
        self.assertEqual(removed["task"]["lastDone"], first["action"]["doneAt"])
        active = self.store.get_history("aleja-pokoju6", "all")["actions"]
        self.assertEqual([entry["id"] for entry in active], [first["action"]["id"]])
        self.assertEqual(self.store.counts()["actions"], 2)

    def test_removing_older_action_does_not_change_current_completion(self):
        task = self.add_task()
        first = self.store.mark_done(
            task["id"], "aleja-pokoju6", done_at=(datetime.now(WARSAW) - timedelta(minutes=2)).isoformat()
        )
        second = self.store.mark_done(task["id"], "aleja-pokoju6", done_at=datetime.now(WARSAW).isoformat())

        removed = self.store.remove_action(first["action"]["id"], "aleja-pokoju6")

        self.assertEqual(removed["task"]["lastDone"], second["action"]["doneAt"])

    def test_soft_delete_hides_task_without_deleting_history(self):
        task = self.add_task()
        self.store.mark_done(task["id"], "aleja-pokoju6", source="android")
        deleted = self.store.delete_task(task["id"])
        self.assertTrue(deleted["softDeleted"])
        self.assertEqual(self.store.get_tasks("aleja-pokoju6"), [])
        self.assertEqual(len(self.store.get_history("aleja-pokoju6", "all")["actions"]), 1)
        with self.assertRaises(CleaningError):
            self.store.delete_task(task["id"], soft_delete=False)

    def test_import_is_idempotent_and_maps_legacy_rows(self):
        tasks = {
            "aleja-pokoju6": [{
                "row": 24,
                "room": "Kuchnia",
                "category": "Śmieci",
                "task": "Wynieś śmieci",
                "freq": 2,
                "lastDone": "2026-08-25",
                "items": "Worki",
            }]
        }
        history = {
            "aleja-pokoju6": [{
                "row": 24,
                "at": "2026-08-25T09:27:12.790Z",
                "task": "Wynieś śmieci",
                "room": "Kuchnia",
                "category": "Śmieci",
                "status": "FRESH",
                "source": "cleaning-page",
            }]
        }
        first = self.store.import_initial(tasks, history, {"activeApartmentId": "aleja-pokoju6"})
        second = self.store.import_initial(tasks, history, {"activeApartmentId": "aleja-pokoju6"})
        self.assertEqual(first["insertedTasks"], 1)
        self.assertEqual(first["insertedActions"], 1)
        self.assertEqual(second["insertedTasks"], 0)
        self.assertEqual(second["insertedActions"], 0)
        action = self.store.get_history("aleja-pokoju6", "all")["actions"][0]
        self.assertEqual(action["taskId"], self.store.get_tasks("aleja-pokoju6")[0]["id"])


if __name__ == "__main__":
    unittest.main()
