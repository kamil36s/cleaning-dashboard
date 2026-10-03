import tempfile
import unittest
from pathlib import Path

from timeline_store import TimelineError, TimelineStore


def date_part(value, precision="exact_day"):
    return {"date": value, "precision": precision, "earliest": None, "latest": None}


def item(item_id="item-1", item_type="point", **overrides):
    value = {
        "id": item_id,
        "title": "Example trip",
        "type": item_type,
        "categoryId": "travel",
        "start": date_part("2024-05-10"),
        "end": None,
        "ongoing": False,
        "importance": 3,
    }
    value.update(overrides)
    return value


class TimelineStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = TimelineStore(Path(self.temp.name) / "timeline.sqlite")
        self.store.initialize()

    def tearDown(self):
        self.temp.cleanup()

    def test_create_edit_and_delete_item(self):
        created = self.store.create_item(item())
        self.assertEqual(created["type"], "point")
        updated = self.store.update_item(created["id"], {"title": "Edited example trip"})
        self.assertEqual(updated["title"], "Edited example trip")
        result = self.store.delete_item(created["id"])
        self.assertTrue(result["ok"])
        self.assertEqual(self.store.summary()["total"], 0)

    def test_create_period_and_ongoing_period(self):
        period = self.store.create_item(item("period-1", "period", end=date_part("2025-04", "month")))
        ongoing = self.store.create_item(item("period-2", "period", ongoing=True))
        self.assertEqual(period["end"]["date"], "2025-04")
        self.assertTrue(ongoing["ongoing"])
        self.assertIsNone(ongoing["end"])

    def test_accepts_european_dates_and_normalizes_storage(self):
        created = self.store.create_item(item("display-date", start=date_part("10/05/2024")))
        monthly = self.store.create_item(item(
            "display-month",
            "period",
            start=date_part("10/2022", "month"),
            end=date_part("02/2024", "month"),
        ))
        self.assertEqual(created["start"]["date"], "2024-05-10")
        self.assertEqual(monthly["start"]["date"], "2022-10")
        self.assertEqual(monthly["end"]["date"], "2024-02")

    def test_end_before_start_is_rejected(self):
        with self.assertRaises(TimelineError):
            self.store.create_item(item("bad-period", "period", end=date_part("2020-01-01")))

    def test_valid_import_roundtrip_and_invalid_import_is_atomic(self):
        self.store.create_item(item())
        exported = self.store.snapshot()
        fresh = TimelineStore(Path(self.temp.name) / "fresh.sqlite")
        report = fresh.import_snapshot(exported, mode="replace")
        self.assertGreater(report["new"], 0)
        self.assertEqual(fresh.snapshot()["timelineItems"][0]["title"], "Example trip")
        invalid = dict(exported)
        invalid["timelineItems"] = [item("invalid", categoryId="missing")]
        before = fresh.snapshot()
        with self.assertRaises(TimelineError):
            fresh.import_snapshot(invalid, mode="replace")
        self.assertEqual(fresh.snapshot(), before)

    def test_merge_accepts_categories_already_in_database_but_replace_does_not(self):
        payload = {
            "schemaVersion": 1,
            "timelineItems": [item("merge-existing-category")],
            "people": [],
            "categories": [],
            "sources": [],
            "itemLinks": [],
            "reflections": [],
        }
        report = self.store.import_snapshot(payload, mode="merge")
        self.assertEqual(report["new"], 1)
        with self.assertRaises(TimelineError) as context:
            self.store.import_snapshot(payload, mode="replace")
        self.assertEqual(context.exception.code, "invalid_import")

    def test_category_in_use_requires_reassignment(self):
        self.store.create_item(item())
        with self.assertRaises(TimelineError) as context:
            self.store.delete_category("travel")
        self.assertEqual(context.exception.code, "category_in_use")
        result = self.store.delete_category("travel", move_to="other")
        self.assertEqual(result["movedItems"], 1)
        self.assertEqual(self.store.snapshot()["timelineItems"][0]["categoryId"], "other")


if __name__ == "__main__":
    unittest.main()
