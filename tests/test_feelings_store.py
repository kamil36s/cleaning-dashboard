import json
import tempfile
import unittest
from pathlib import Path

from feelings_store import FeelingsService


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SEED_PATH = PROJECT_ROOT.parent / "how_we_feel_seed.json"


class FeelingsCatalogTests(unittest.TestCase):
    def test_reference_meter_has_exact_four_quadrant_coordinates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = FeelingsService(Path(temp_dir) / "feelings.sqlite")
            service.initialize()
            emotions = service.list_emotions()["emotions"]
            meter = [emotion for emotion in emotions if emotion["meter"]]
            self.assertEqual(len(meter), 144)
            self.assertEqual(len({(emotion["x"], emotion["y"]) for emotion in meter}), 144)
            by_name = {emotion["name"]: emotion for emotion in meter}
            self.assertEqual((by_name["Enraged"]["x"], by_name["Enraged"]["y"], by_name["Enraged"]["quadrant"]), (0, 0, "high_unpleasant"))
            self.assertEqual((by_name["Concerned"]["x"], by_name["Concerned"]["y"]), (4, 4))
            self.assertEqual((by_name["Calm"]["x"], by_name["Calm"]["y"], by_name["Calm"]["quadrant"]), (6, 6, "low_pleasant"))
            self.assertEqual((by_name["Serene"]["x"], by_name["Serene"]["y"]), (11, 11))


@unittest.skipUnless(SEED_PATH.is_file(), "provided How We Feel seed is not available")
class FeelingsStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "feelings.sqlite"
        self.service = FeelingsService(self.database, (SEED_PATH,))
        self.initialized = self.service.initialize()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_seed_imports_exact_history_and_is_idempotent(self):
        self.assertEqual(self.initialized["legacyCount"], 467)
        self.assertEqual(self.initialized["seedStatus"], "imported")
        second = self.service.initialize()
        self.assertEqual(second["seedStatus"], "already_imported")
        self.assertEqual(second["legacyCount"], 467)
        rows = self.service.list_checkins({"limit": ["1000"]})["checkins"]
        self.assertEqual(len(rows), 467)
        self.assertEqual(rows[0]["occurredAt"], "2026-07-06T12:13")
        self.assertEqual(rows[-1]["occurredAt"], "2024-07-16T10:26")
        self.assertEqual(len({row["id"] for row in rows}), 467)

    def test_new_checkin_tags_and_note_line_breaks_survive_reload(self):
        emotion = self.service.list_emotions()["emotions"][0]
        result = self.service.create_checkin({
            "emotionIds": [emotion["id"]],
            "occurredAt": "2026-09-23T18:45",
            "timezone": "Europe/Warsaw",
            "tags": ["Home", "A brand new context"],
            "note": "First line\nSecond line",
        })
        reloaded = FeelingsService(self.database, (SEED_PATH,))
        reloaded.initialize()
        item = reloaded.get_checkin(result["checkin"]["id"])
        self.assertEqual(item["note"], "First line\nSecond line")
        self.assertEqual({tag["name"] for tag in item["tags"]}, {"Home", "A brand new context"})

    def test_custom_emotion_and_tag_can_be_created(self):
        emotion = self.service.create_emotion({
            "name": "Quietly electric",
            "description": "calm with a current of anticipation",
            "quadrant": "high_pleasant",
        })["emotion"]
        tag = self.service.create_tag({"name": "Late-night coding"})["tag"]
        self.assertTrue(emotion["custom"])
        self.assertEqual(emotion["quadrant"], "high_pleasant")
        self.assertTrue(tag["custom"])

    def test_filters_delete_and_insights_recalculate(self):
        emotion = next(item for item in self.service.list_emotions()["emotions"] if item["name"] == "Calm")
        before = self.service.insights()["total"]
        created = self.service.create_checkin({
            "emotionId": emotion["id"], "occurredAt": "2026-09-23T19:05",
            "tags": ["Test context"], "note": "filter needle",
        })["checkin"]
        result = self.service.list_checkins({"q": ["needle"], "tag": ["Test context"]})
        self.assertEqual([item["id"] for item in result["checkins"]], [created["id"]])
        self.assertEqual(self.service.insights()["total"], before + 1)
        self.service.delete_checkin(created["id"])
        self.assertEqual(self.service.list_checkins({"q": ["needle"]})["count"], 0)
        self.assertEqual(self.service.insights()["total"], before)

    def test_export_import_skips_existing_ids_without_overwrite(self):
        exported = self.service.export_data()
        self.assertEqual(exported["format"], "feelings-export")
        result = self.service.import_export(json.loads(json.dumps(exported)))
        self.assertEqual(result["imported"], 0)
        self.assertEqual(result["skipped"], 467)
        fresh = FeelingsService(Path(self.temp_dir.name) / "fresh.sqlite")
        fresh.initialize()
        restored = fresh.import_export(json.loads(json.dumps(exported)))
        self.assertEqual(restored["imported"], 467)
        self.assertEqual(restored["skipped"], 0)
        self.assertEqual(fresh.list_checkins({"limit": ["1000"]})["count"], 467)


if __name__ == "__main__":
    unittest.main()
