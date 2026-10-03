import json
import tempfile
import unittest
from pathlib import Path

from timeline_activity import TimelineActivityService


class FakeJournalStore:
    def list(self, limit=10000):
        return [{
            "id": "journal-1",
            "title": "Entry",
            "content": "Complete private text",
            "entryDate": "2026-07-22T10:00:00+02:00",
            "tags": ["day"],
            "entryKind": "journal",
        }, {
            "id": "poem-1",
            "title": "Ararat",
            "content": "<p>Poem body</p>",
            "contentFormat": "html",
            "entryDate": "2026-07-22",
            "tags": ["poem"],
            "entryKind": "poem",
            "sourceType": "tumblr",
        }]


class FakeCleaningStore:
    db_path = "cleaning.sqlite"

    def list_apartments(self):
        return [{"id": "flat", "label": "Flat"}]

    def get_history(self, apartment_id, range_name="month", offset=0):
        return {"actions": [{
            "actionId": 31,
            "taskName": "Vacuum",
            "room": "Living room",
            "category": "Floors",
            "status": "DUE",
            "doneAt": "2026-09-10T18:30:00+02:00",
        }]}


class TimelineActivityServiceTests(unittest.TestCase):
    def test_reads_current_cleaning_actions_from_sqlite_store(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cleaning_store = FakeCleaningStore()
            cleaning_store.db_path = root / "data" / "cleaning.sqlite"
            result = TimelineActivityService(root, cleaning_store=cleaning_store).query(
                "2026-09-01", "2026-09-30", {"cleaning"}
            )

            self.assertEqual(result["totals"]["bySource"], {"cleaning": 1})
            event = result["days"][0]["events"][0]
            self.assertEqual(event["title"], "Vacuum")
            self.assertEqual(event["summary"], "Living room · Floors")
            self.assertEqual(event["metrics"]["apartment"], "flat")

    def test_aggregates_adapters_and_reuses_fingerprinted_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "data/settings").mkdir(parents=True)
            (root / "data").mkdir(exist_ok=True)
            (root / "data/settings/reading-history.json").write_text(json.dumps({
                "log": {"2026-07-22": {"total": 12, "books": {"Book": 12}, "progress": {}}}
            }), encoding="utf-8")
            (root / "data/settings/todo.json").write_text("[]", encoding="utf-8")
            (root / "data/habit-data.json").write_text(json.dumps({"habits": []}), encoding="utf-8")

            service = TimelineActivityService(root, FakeJournalStore())
            first = service.query("2026-07-22", "2026-07-22", {"journal", "reading"}, "full")
            second = service.query("2026-07-22", "2026-07-22", {"journal", "reading"}, "full")

            self.assertEqual(first["totals"]["events"], 2)
            self.assertEqual(first["days"][0]["sourceCounts"], {"journal": 1, "reading": 1})
            journal = next(event for event in first["days"][0]["events"] if event["source"] == "journal")
            self.assertEqual(journal["details"], "Complete private text")
            self.assertTrue(journal["private"])
            self.assertFalse(first["cache"]["hit"])
            self.assertTrue(second["cache"]["hit"])

    def test_separates_poems_from_journal_counts(self):
        with tempfile.TemporaryDirectory() as folder:
            service = TimelineActivityService(Path(folder), FakeJournalStore())
            result = service.query("2026-07-22", "2026-07-22", {"journal", "poems"}, "full")

            self.assertEqual(result["days"][0]["sourceCounts"], {"journal": 1, "poems": 1})
            poem = next(event for event in result["days"][0]["events"] if event["source"] == "poems")
            self.assertEqual(poem["kind"], "poem")
            self.assertEqual(poem["title"], "Ararat")
            self.assertEqual(poem["details"], "Poem body")
            self.assertEqual(poem["metrics"]["sourceType"], "tumblr")

    def test_self_care_batch_is_deduplicated_per_task_and_day(self):
        with tempfile.TemporaryDirectory() as folder:
            service = TimelineActivityService(Path(folder))
            payload = {"events": [
                {"title": "Rest", "category": "recovery", "occurredAt": "2026-07-22T08:00:00+02:00"},
                {"title": "Rest", "category": "recovery", "occurredAt": "2026-07-22T20:00:00+02:00"},
            ]}
            first = service.record_self_care(payload)
            second = service.record_self_care(payload)
            result = service.query("2026-07-22", "2026-07-22", {"selfCare"})

            self.assertEqual(first["imported"], 1)
            self.assertEqual(second["imported"], 0)
            self.assertEqual(result["totals"]["events"], 1)

    def test_how_we_feel_csv_import_is_private_and_idempotent(self):
        csv_data = (
            "Date,Locale,Mood Keys,Mood,Tags (People),Tags (Places),Tags (Events),Notes,Reflections,Takeaways\n"
            '2026 Wed Jul 22 11:36 PM,en,down,down,By Myself,Home,Resting,"A full note","[]","[]"\n'
            '2026 Wed Jul 22 08:15 AM,en,calm,calm,Friend,Outside,Walking,,"[]","[]"\n'
        ).encode("utf-8")
        with tempfile.TemporaryDirectory() as folder:
            service = TimelineActivityService(Path(folder))
            first = service.import_emotions_csv(csv_data, "Check-in_data.csv")
            second = service.import_emotions_csv(csv_data, "Check-in_data.csv")
            result = service.query("2026-07-22", "2026-07-22", {"emotions"})

            self.assertEqual(first["imported"], 2)
            self.assertEqual(second["duplicates"], 2)
            self.assertEqual(result["totals"]["events"], 2)
            event = next(row for row in result["days"][0]["events"] if row["metrics"]["moodKey"] == "down")
            self.assertTrue(event["private"])
            self.assertEqual(event["details"], "A full note")

    def test_health_ignores_impossible_and_duplicate_weight_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            scale = root / "data/scale"
            scale.mkdir(parents=True)
            rows = [
                {"timestamp": "2026-07-24T10:05:07.156", "weight_kg": 92.5, "type": "181D", "raw_hex": "valid"},
                {"timestamp": "2026-07-24T10:05:07.156", "weight_kg": 92.5, "type": "181D", "raw_hex": "valid"},
                {"timestamp": "2026-07-24T14:59:39.155", "weight_kg": 14.05, "type": "181D", "raw_hex": "invalid"},
            ]
            (scale / "scale_measurements.jsonl").write_text(
                "\n".join(json.dumps(row) for row in rows) + "\n",
                encoding="utf-8",
            )

            result = TimelineActivityService(root).query("2026-07-24", "2026-07-24", {"health"})
            weight = next(event for event in result["days"][0]["events"] if event["kind"] == "weight")

            self.assertEqual(weight["metrics"], {"averageKg": 92.5, "measurements": 1})


if __name__ == "__main__":
    unittest.main()
