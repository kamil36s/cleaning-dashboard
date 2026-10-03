import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

import server


class EventCountdownBackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.events_path = Path(self.temp.name) / "events.json"
        self.settings_path = Path(self.temp.name) / "event-settings.json"
        self.events_path.write_text("[]", encoding="utf-8")
        self.events_patch = mock.patch.object(server, "EVENTS_JSON", self.events_path)
        self.settings_patch = mock.patch.object(server, "EVENT_COUNTDOWN_SETTINGS_JSON", self.settings_path)
        self.events_patch.start()
        self.settings_patch.start()

    def tearDown(self):
        self.events_patch.stop()
        self.settings_patch.stop()
        self.temp.cleanup()

    def test_creates_dashboard_only_event_with_required_category(self):
        result = server.upsert_local_dashboard_event({
            "event": {
                "title": "Severance S03E01",
                "date": "2026-09-01",
                "category": "new_episode",
                "countdown": True,
            },
        })

        stored = json.loads(self.events_path.read_text(encoding="utf-8"))
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]["id"], result["event"]["id"])
        self.assertEqual(stored[0]["category"], "new_episode")
        self.assertTrue(stored[0]["countdown"])
        self.assertEqual(stored[0]["source"], "local")

    def test_rejects_event_without_supported_category(self):
        with self.assertRaisesRegex(ValueError, "valid event category"):
            server.upsert_local_dashboard_event({
                "event": {
                    "title": "Uncategorized event",
                    "date": "2026-09-02",
                },
            })

    def test_adds_and_accepts_a_persistent_custom_category(self):
        category_result = server.save_event_countdown_category({"label": "Film premiere"})
        category = category_result["category"]
        event_result = server.upsert_local_dashboard_event({
            "event": {
                "title": "Nosferatu re-release",
                "date": "2026-09-18",
                "category": category["id"],
                "countdown": True,
            },
        })

        self.assertEqual(category, {"id": "film_premiere", "label": "Film premiere", "custom": True})
        self.assertEqual(event_result["event"]["category"], "film_premiere")
        stored_settings = json.loads(self.settings_path.read_text(encoding="utf-8"))
        self.assertEqual(stored_settings["countdownCategories"], [category])

    def test_past_mode_still_respects_the_requested_date_window(self):
        today = date.today()
        self.events_path.write_text(json.dumps([
            {"id": "old", "date": (today - timedelta(days=30)).isoformat(), "title": "Old"},
            {"id": "today", "date": today.isoformat(), "title": "Today"},
            {"id": "tomorrow", "date": (today + timedelta(days=1)).isoformat(), "title": "Tomorrow"},
            {"id": "later", "date": (today + timedelta(days=2)).isoformat(), "title": "Later"},
        ]), encoding="utf-8")

        payload = server.read_events_payload(
            include_local=True,
            include_google=False,
            include_past=True,
            window_days=1,
        )

        self.assertEqual([event["id"] for event in payload["events"]], ["today", "tomorrow"])

    def test_renames_builtin_and_custom_categories_without_changing_their_ids(self):
        custom = server.save_event_countdown_category({"label": "Film premiere"})["category"]
        builtin_result = server.save_event_countdown_category({"id": "match", "label": "Mecz piłkarski"})
        custom_result = server.save_event_countdown_category({"id": custom["id"], "label": "Premiera filmu"})

        self.assertEqual(builtin_result["category"]["id"], "match")
        self.assertEqual(builtin_result["category"]["label"], "Mecz piłkarski")
        self.assertEqual(custom_result["category"]["id"], "film_premiere")
        self.assertEqual(custom_result["category"]["label"], "Premiera filmu")
        settings = json.loads(self.settings_path.read_text(encoding="utf-8"))
        self.assertEqual(settings["countdownCategoryLabels"]["match"], "Mecz piłkarski")


if __name__ == "__main__":
    unittest.main()
