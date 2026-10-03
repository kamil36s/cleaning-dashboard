import unittest
import server


class CalendarEventTests(unittest.TestCase):
    def test_google_interval_is_preserved_for_multiday_rendering(self):
        start = {"date": "2026-09-28"}
        end = {"date": "2026-10-03"}
        result = server.google_event_to_dashboard_event({
            "id": "calendar-test", "summary": "Leave", "start": start, "end": end,
        }, "test-calendar", calendar_meta={"summary": "Test", "accessRole": "reader"})
        self.assertEqual(result["external"]["start"], start)
        self.assertEqual(result["external"]["end"], end)
        self.assertIsNone(result["startTime"])

    def test_google_timed_interval_keeps_timezone_offset(self):
        start = {"dateTime": "2026-10-01T23:00:00+02:00"}
        end = {"dateTime": "2026-10-02T01:30:00+02:00"}
        result = server.google_event_to_dashboard_event({
            "id": "calendar-test", "summary": "Night", "start": start, "end": end,
        }, "test-calendar")
        self.assertEqual(result["external"]["start"], start)
        self.assertEqual(result["external"]["end"], end)


if __name__ == '__main__':
    unittest.main()
