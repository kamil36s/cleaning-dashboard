import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from cinema_city_repertoire import apply_repertoire_filters, normalize_repertoire_payload


class CinemaCityRepertoireTests(unittest.TestCase):
    def test_normalizes_only_future_available_screenings(self):
        payload = {
            "body": {
                "films": [
                    {
                        "id": "film-1",
                        "name": "  Film testowy  ",
                        "length": 120,
                        "attributeIds": ["2d", "thriller", "dubbed", "subbed"],
                    }
                ],
                "events": [
                    {
                        "id": "past",
                        "filmId": "film-1",
                        "eventDateTime": "2026-08-01T10:00:00",
                        "soldOut": False,
                    },
                    {
                        "id": "sold-out",
                        "filmId": "film-1",
                        "eventDateTime": "2026-08-01T20:00:00",
                        "soldOut": True,
                    },
                    {
                        "id": "future",
                        "filmId": "film-1",
                        "eventDateTime": "2026-08-01T18:30:00",
                        "soldOut": False,
                        "attributeIds": ["subbed", "laser-barco"],
                        "bookingLink": "https://example.test/tickets",
                    },
                    {
                        "id": "dubbed",
                        "filmId": "film-1",
                        "eventDateTime": "2026-08-01T21:00:00",
                        "soldOut": False,
                        "attributeIds": ["2d", "dubbed-lang-uk"],
                    },
                ],
            }
        }
        now = datetime(2026, 8, 1, 12, 0, tzinfo=ZoneInfo("Europe/Warsaw"))

        events = normalize_repertoire_payload("2026-08-01", payload, now=now)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["id"], "cinema-city:future")
        self.assertEqual(events[0]["title"], "Film testowy")
        self.assertEqual(events[0]["startTime"], "18:30")
        self.assertEqual(events[0]["endTime"], "20:30")
        self.assertIn("AUTO_CINEMA_CITY", events[0]["notes"])
        self.assertEqual(events[0]["external"]["calendarSummary"], "Cinema City Galeria Kazimierz")

    def test_applies_watched_never_watch_and_kids_filters(self):
        titles = [
            "Obsesja",
            "Backrooms. Bez wyjścia - wersja rozszerzona",
            "Supergirl",
            "Psi patrol i dinozaury",
            "Film dla mnie",
            "Film abonamentowy",
        ]
        payload = {"events": [{"id": str(index), "title": title} for index, title in enumerate(titles)]}
        filters = {
            "watched": ["Obsesja", "Backrooms. Bez wyjścia"],
            "neverWatch": ["Supergirl"],
            "kidsKeywords": ["psi patrol"],
            "watchedSubscription": ["Film abonamentowy"],
        }

        result = apply_repertoire_filters(payload, filters)

        self.assertEqual([event["title"] for event in result["events"]], ["Film dla mnie"])
        self.assertEqual(result["filtering"]["hiddenEvents"], 5)
        self.assertEqual(result["filtering"]["hiddenMovies"], 5)


if __name__ == "__main__":
    unittest.main()
