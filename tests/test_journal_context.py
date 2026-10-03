import unittest

from journal_context import JournalContextService, item_is_active_on, normalize_context_dates


def exact(value):
    return {"date": value, "precision": "exact_day", "earliest": None, "latest": None}


class FakeTimelineStore:
    def snapshot(self):
        return {
            "categories": [
                {"id": "relationships", "name": "Relationships", "color": "#c86b7b"},
                {"id": "home", "name": "Home", "color": "#b98f65"},
                {"id": "social", "name": "Social", "color": "#999999"},
            ],
            "people": [{"id": "person-1", "name": "Ala"}],
            "timelineItems": [
                {
                    "id": "relationship-1", "type": "period", "categoryId": "relationships",
                    "title": "Ala", "start": exact("2020-01-01"), "end": exact("2021-01-01"),
                    "ongoing": False, "subcategory": "", "location": "", "peopleIds": ["person-1"],
                },
                {
                    "id": "home-1", "type": "period", "categoryId": "home",
                    "title": "Kraków", "start": exact("2019-01-01"), "end": None,
                    "ongoing": True, "subcategory": "mieszkanie", "location": "Kraków", "peopleIds": [],
                },
                {
                    "id": "social-1", "type": "period", "categoryId": "social",
                    "title": "Ignored", "start": exact("2020-01-01"), "end": exact("2021-01-01"),
                    "ongoing": False, "peopleIds": [],
                },
            ],
        }


class FakeActivityService:
    def query(self, from_day, to_day, sources, journal_content):
        return {
            "days": [{
                "date": "2020-06-15",
                "events": [
                    {"id": "lastfm:day", "source": "lastfm", "kind": "listening_chart", "title": "30 scrobbles", "summary": "Artist: Test", "metrics": {"granularity": "day"}},
                    {"id": "lastfm:month", "source": "lastfm", "kind": "listening_chart", "title": "500 scrobbles", "summary": "", "metrics": {"granularity": "month"}},
                    {"id": "health:weight", "source": "health", "kind": "weight", "title": "Weight: 80 kg", "summary": "", "metrics": {"averageKg": 80}},
                ],
            }],
        }


class JournalContextTests(unittest.TestCase):
    def test_validates_and_deduplicates_dates(self):
        self.assertEqual(normalize_context_dates(["2020-06-15", "2020-06-15"]), ["2020-06-15"])
        with self.assertRaises(ValueError):
            normalize_context_dates(["15/06/2020"])

    def test_matches_points_and_periods_to_the_requested_day(self):
        period = {"type": "period", "start": exact("2020-01-01"), "end": exact("2020-12-31"), "ongoing": False}
        point = {"type": "point", "start": exact("2020-06-15"), "end": None, "ongoing": False}
        self.assertTrue(item_is_active_on(period, "2020-06-15", "2026-01-01"))
        self.assertTrue(item_is_active_on(point, "2020-06-15", "2026-01-01"))
        self.assertFalse(item_is_active_on(point, "2020-06-16", "2026-01-01"))

    def test_builds_life_context_and_daily_signals_without_monthly_lastfm_duplicates(self):
        service = JournalContextService(FakeTimelineStore(), FakeActivityService())

        result = service.query(["2020-06-15"])
        context = result["contexts"]["2020-06-15"]

        self.assertEqual([group["id"] for group in context["timelineGroups"]], ["relationships", "home"])
        self.assertEqual(context["timelineGroups"][0]["items"][0]["people"], ["Ala"])
        self.assertEqual([group["id"] for group in context["activityGroups"]], ["lastfm", "health"])
        self.assertEqual(len(context["activityGroups"][0]["events"]), 1)
        self.assertEqual(context["activityGroups"][0]["events"][0]["title"], "30 scrobbles")


if __name__ == "__main__":
    unittest.main()
