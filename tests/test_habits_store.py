import json
import tempfile
import unittest
from pathlib import Path

from habits_store import HabitsStore, SCHEMA_VERSION, SERVICE_NAME


class HabitsStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        seed = root / "seed.json"
        seed.write_text(json.dumps({"habits": [{
            "id": 7, "name": "Meditation", "type": 0, "unit": "",
            "points": [[1_777_507_200_000, 2]],
        }]}), encoding="utf-8")
        self.store = HabitsStore(root / "habits.sqlite")
        self.store.initialize(seed)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_health_and_seed_snapshot(self):
        self.assertEqual(self.store.health()["service"], SERVICE_NAME)
        snapshot = self.store.snapshot()
        self.assertEqual(snapshot["schemaVersion"], SCHEMA_VERSION)
        self.assertEqual(len(snapshot["habits"]), 1)
        self.assertEqual(snapshot["habits"][0]["category"], "HABIT")
        self.assertEqual(snapshot["entries"][0]["status"], "DONE")

    def test_ack_idempotency_pull_and_conflict(self):
        snapshot = self.store.snapshot()
        habit = snapshot["habits"][0]
        mutation = {
            "mutationId": "m-1", "entityType": "ENTRY",
            "entityId": f"{habit['id']}:2026-08-26", "operation": "UPSERT",
            "baseRevision": None, "clientUpdatedAt": "2026-08-26T12:00:00Z",
            "payload": {"habitId": habit["id"], "date": "2026-08-26", "status": "DONE"},
        }
        request = {"schemaVersion": 1, "deviceId": "phone", "lastPulledCursor": snapshot["cursor"], "mutations": [mutation], "limit": 200}
        first = self.store.sync(request)
        self.assertEqual(first["acknowledgedMutationIds"], ["m-1"])
        self.assertEqual(first["changes"][0]["entity"]["revision"], 1)

        replay = self.store.sync({**request, "lastPulledCursor": first["nextCursor"]})
        self.assertEqual(replay["acknowledgedMutationIds"], ["m-1"])
        self.assertEqual(replay["changes"][0]["entity"]["revision"], 1)

        stale = {**mutation, "mutationId": "m-2", "baseRevision": 0,
                 "payload": {**mutation["payload"], "status": "MISSED"}}
        conflict = self.store.sync({**request, "lastPulledCursor": first["nextCursor"], "mutations": [stale]})
        self.assertEqual(conflict["acknowledgedMutationIds"], [])
        self.assertEqual(conflict["conflicts"][0]["reason"], "REVISION_MISMATCH")
        self.assertEqual(conflict["conflicts"][0]["serverEntity"]["status"], "DONE")

    def test_zero_numeric_value_after_deleting_absent_entry_keeps_phone_revision(self):
        habit = self.store.snapshot()["habits"][0]
        entity_id = f"{habit['id']}:2026-09-26"
        base = {"schemaVersion": 1, "deviceId": "phone", "lastPulledCursor": None, "limit": 200}
        deleted = self.store.sync({**base, "mutations": [{
            "mutationId": "delete-absent", "entityType": "ENTRY", "entityId": entity_id,
            "operation": "DELETE", "baseRevision": None,
            "payload": {"habitId": habit["id"], "date": "2026-09-26"},
        }]})
        self.assertEqual(deleted["acknowledgedMutationIds"], ["delete-absent"])
        self.assertFalse(any(entry["id"] == entity_id for entry in self.store.snapshot()["entries"]))
        zero = self.store.sync({**base, "mutations": [{
            "mutationId": "record-zero", "entityType": "ENTRY", "entityId": entity_id,
            "operation": "UPSERT", "baseRevision": 1,
            "payload": {"habitId": habit["id"], "date": "2026-09-26", "valueMilli": 0},
        }]})
        self.assertEqual(zero["conflicts"], [])
        entry = next(entry for entry in self.store.snapshot()["entries"] if entry["id"] == entity_id)
        self.assertEqual(entry["valueMilli"], 0)
        self.assertEqual(entry["revision"], 2)

    def test_old_delete_without_saved_tombstone_can_accept_followup_zero(self):
        habit = self.store.snapshot()["habits"][0]
        entity_id = f"{habit['id']}:2026-09-27"
        base = {"schemaVersion": 1, "deviceId": "phone", "lastPulledCursor": None, "limit": 200}
        self.store.sync({**base, "mutations": [{
            "mutationId": "old-delete", "entityType": "ENTRY", "entityId": entity_id,
            "operation": "DELETE", "baseRevision": None,
            "payload": {"habitId": habit["id"], "date": "2026-09-27"},
        }]})
        with self.store._connect() as connection:
            connection.execute("DELETE FROM entries WHERE id=?", (entity_id,))
        result = self.store.sync({**base, "mutations": [{
            "mutationId": "late-zero", "entityType": "ENTRY", "entityId": entity_id,
            "operation": "UPSERT", "baseRevision": 1,
            "payload": {"habitId": habit["id"], "date": "2026-09-27", "valueMilli": 0},
        }]})
        self.assertEqual(result["conflicts"], [])
        entry = next(entry for entry in self.store.snapshot()["entries"] if entry["id"] == entity_id)
        self.assertEqual(entry["valueMilli"], 0)

    def test_archiving_and_restoring_habit_preserves_history_and_metadata(self):
        before = self.store.snapshot()
        habit = before["habits"][0]
        entries_before = before["entries"]

        archived = self.store.sync({
            "schemaVersion": 1,
            "deviceId": "dashboard",
            "lastPulledCursor": before["cursor"],
            "mutations": [{
                "mutationId": "archive-1",
                "entityType": "HABIT",
                "entityId": habit["id"],
                "operation": "UPSERT",
                "baseRevision": habit["revision"],
                "clientUpdatedAt": "2026-08-26T12:00:00Z",
                "payload": {"archived": True},
            }],
            "limit": 200,
        })

        self.assertEqual(archived["acknowledgedMutationIds"], ["archive-1"])
        archived_habit = archived["changes"][0]["entity"]
        self.assertTrue(archived_habit["archived"])
        self.assertEqual(archived_habit["name"], habit["name"])
        self.assertEqual(archived_habit["category"], habit["category"])
        self.assertEqual(archived_habit["colorHex"], habit["colorHex"])

        after_archive = self.store.snapshot()
        self.assertTrue(after_archive["habits"][0]["archived"])
        self.assertEqual(after_archive["entries"], entries_before)

        restored = self.store.sync({
            "schemaVersion": 1,
            "deviceId": "phone",
            "lastPulledCursor": archived["nextCursor"],
            "mutations": [{
                "mutationId": "restore-1",
                "entityType": "HABIT",
                "entityId": habit["id"],
                "operation": "UPSERT",
                "baseRevision": archived_habit["revision"],
                "clientUpdatedAt": "2026-08-26T12:01:00Z",
                "payload": {"archived": False},
            }],
            "limit": 200,
        })

        self.assertEqual(restored["acknowledgedMutationIds"], ["restore-1"])
        self.assertFalse(restored["changes"][0]["entity"]["archived"])
        after_restore = self.store.snapshot()
        self.assertFalse(after_restore["habits"][0]["archived"])
        self.assertEqual(after_restore["entries"], entries_before)

    def test_reminder_config_groups_and_occurrence_claims_are_durable(self):
        snapshot = self.store.snapshot()
        habit = snapshot["habits"][0]
        self.assertFalse(habit["reminderConfig"]["enabled"])
        self.assertEqual(snapshot["reminderTimeGroups"][0]["id"], "morning")

        response = self.store.sync({
            "schemaVersion": 1,
            "deviceId": "dashboard",
            "lastPulledCursor": snapshot["cursor"],
            "mutations": [{
                "mutationId": "reminder-config-1",
                "entityType": "HABIT",
                "entityId": habit["id"],
                "operation": "UPSERT",
                "baseRevision": habit["revision"],
                "payload": {
                    "name": habit["name"],
                    "reminderConfig": {
                        "enabled": True,
                        "scheduleType": "interval_days",
                        "selectedWeekdays": [],
                        "intervalDays": 2,
                        "intervalAnchorDate": "2026-09-23",
                        "timeGroupIds": ["evening"],
                        "customTimes": [],
                        "snoozeMinutes": 30,
                        "skipIfCompleted": True,
                        "completionPolicy": "day",
                    },
                },
            }],
            "limit": 200,
        })
        self.assertEqual(response["acknowledgedMutationIds"], ["reminder-config-1"])
        saved = self.store.snapshot()["habits"][0]["reminderConfig"]
        self.assertEqual(saved["intervalDays"], 2)
        self.assertEqual(saved["timeGroupIds"], ["evening"])

        occurrence = {
            "action": "claim",
            "occurrenceKey": f"{habit['id']}|2026-09-23|group:evening",
            "habitId": habit["id"],
            "localDate": "2026-09-23",
            "sourceKey": "group:evening",
            "scheduledLocalTime": "21:00",
        }
        self.assertTrue(self.store.reminder_action(occurrence)["claimed"])
        self.assertFalse(self.store.reminder_action(occurrence)["claimed"])
        snoozed = self.store.reminder_action({
            "action": "snooze",
            "occurrenceKey": occurrence["occurrenceKey"],
            "snoozedUntil": "2099-09-23T21:10:00.000Z",
        })
        self.assertEqual(snoozed["state"]["status"], "snoozed")
        self.assertFalse(self.store.reminder_action(occurrence)["claimed"])

    def test_deleting_referenced_time_group_requires_resolution(self):
        snapshot = self.store.snapshot()
        habit = snapshot["habits"][0]
        self.store.sync({
            "schemaVersion": 1, "deviceId": "dashboard", "lastPulledCursor": snapshot["cursor"],
            "mutations": [{
                "mutationId": "reminder-config-2", "entityType": "HABIT", "entityId": habit["id"],
                "operation": "UPSERT", "baseRevision": habit["revision"],
                "payload": {"name": habit["name"], "reminderConfig": {
                    "enabled": True, "scheduleType": "daily", "selectedWeekdays": [],
                    "intervalDays": 2, "intervalAnchorDate": None, "timeGroupIds": ["evening"],
                    "customTimes": [], "snoozeMinutes": 10, "skipIfCompleted": True,
                    "completionPolicy": "day",
                }},
            }], "limit": 200,
        })
        remaining = [group for group in self.store.snapshot()["reminderTimeGroups"] if group["id"] != "evening"]
        with self.assertRaisesRegex(Exception, "still referenced"):
            self.store.save_reminder_settings({"timeGroups": remaining, "browserNotificationsEnabled": False})

        self.store.save_reminder_settings({
            "timeGroups": remaining,
            "browserNotificationsEnabled": False,
            "deletedGroupResolutions": {"evening": "morning"},
        })
        config = self.store.snapshot()["habits"][0]["reminderConfig"]
        self.assertEqual(config["timeGroupIds"], ["morning"])

    def test_invalid_reminder_schedule_is_rejected(self):
        snapshot = self.store.snapshot()
        habit = snapshot["habits"][0]
        request = {
            "schemaVersion": 1, "deviceId": "dashboard", "lastPulledCursor": snapshot["cursor"],
            "mutations": [{
                "mutationId": "invalid-reminder", "entityType": "HABIT", "entityId": habit["id"],
                "operation": "UPSERT", "baseRevision": habit["revision"],
                "payload": {"name": habit["name"], "reminderConfig": {
                    "enabled": True, "scheduleType": "interval_days", "intervalDays": 0,
                    "intervalAnchorDate": "", "timeGroupIds": [], "customTimes": [], "snoozeMinutes": 5,
                }},
            }], "limit": 200,
        }
        with self.assertRaisesRegex(Exception, "interval"):
            self.store.sync(request)

    def test_deleting_all_unreferenced_groups_survives_restart(self):
        self.store.save_reminder_settings({
            "timeGroups": [],
            "browserNotificationsEnabled": False,
            "deletedGroupResolutions": {},
        })
        self.store.initialize()
        self.assertEqual(self.store.snapshot()["reminderTimeGroups"], [])


if __name__ == "__main__":
    unittest.main()
