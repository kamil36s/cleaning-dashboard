import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from brutal_assault_monitor import (
    LINEUP_URL, NEWS_URL, BrutalAssaultMonitor, estimate,
    lineup_difference, parse_lineup, parse_news, recent_news,
)


def lineup(*names, percent=28):
    links = "".join(
        f'<a href="/en/band/{slug}"><strong class="band_lineup_title">{name}</strong>'
        '<span class="band_lineup_genre">DEATH METAL</span></a>'
        for slug, name in names
    )
    return f"<h1>{percent}% CONFIRMED!</h1>{links}"


def news(*ids, published=None):
    published = published or datetime.now(timezone.utc).strftime("%d.%m.%Y")
    return "".join(
        '<div class="article_preview">'
        f'<a href="/en/a/{number}/story-{number}"><h3 class="article_title">News {number}</h3></a>'
        f'<span class="article_date">{published}</span><p>Preview</p></div>'
        for number in ids
    )


class BrutalAssaultMonitorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.pages = {
            LINEUP_URL: lineup(("a", "A &amp; B"), ("b", "Band B")),
            NEWS_URL: news(805, 803),
        }
        self.monitor = BrutalAssaultMonitor(
            Path(self.temp.name) / "monitor.json", fetch=lambda url: self.pages[url]
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_parse_lineup_and_estimate(self):
        parsed = parse_lineup(lineup(("a", "A &amp; B"), ("a", "A &amp; B"), ("b", "B")))
        self.assertEqual(parsed["confirmedPercent"], 28)
        self.assertEqual(parsed["bands"], [
            {"name": "A & B", "slug": "a", "url": "https://brutalassault.cz/en/band/a"},
            {"name": "B", "slug": "b", "url": "https://brutalassault.cz/en/band/b"},
        ])
        self.assertEqual(estimate(37, 28)["estimatedTotal"], 132)
        self.assertEqual(estimate(37, 28)["estimatedRemaining"], 95)
        with self.assertRaises(ValueError):
            parse_lineup("<html>temporarily unavailable</html>")

    def test_difference_and_news_parser(self):
        old = parse_lineup(lineup(("a", "A"), ("b", "B"), ("c", "C")))["bands"]
        current = parse_lineup(lineup(("a", "A"), ("b", "B"), ("c", "C"), ("d", "D"), ("e", "E")))["bands"]
        added, removed = lineup_difference(old, current)
        self.assertEqual([band["name"] for band in added], ["D", "E"])
        self.assertEqual(removed, [])
        self.assertEqual([article["id"] for article in parse_news(news(805, 803))], ["805", "803"])

    def test_first_run_baselines_then_deduplicates(self):
        first = self.monitor.check()
        self.assertEqual(first["events"], [])
        self.assertEqual(first["announcedCount"], 2)
        self.pages[LINEUP_URL] = lineup(("a", "A &amp; B"), ("b", "Band B"), ("c", "Band C"))
        self.pages[NEWS_URL] = news(806, 805, 803)
        second = self.monitor.check()
        self.assertEqual(len(second["events"]), 2)
        self.assertEqual(second["newBands"][0]["name"], "Band C")
        self.assertEqual(second["latestNews"][1]["firstSeenAt"], first["lastCheckAt"])
        again = self.monitor.check()
        self.assertEqual(len(again["events"]), 2)

    def test_invalid_fetch_preserves_snapshots_and_events(self):
        before = self.monitor.check()
        self.pages[LINEUP_URL] = "<h1>28% CONFIRMED!</h1>"
        self.pages[NEWS_URL] = "<html>Unavailable</html>"
        failed = self.monitor.check()
        self.assertEqual(failed["bands"], before["bands"])
        self.assertEqual(failed["latestNews"], before["latestNews"])
        self.assertEqual(failed["events"], [])
        self.assertEqual(failed["status"], "error")
        self.assertEqual(failed["lastSuccessfulCheckAt"], before["lastSuccessfulCheckAt"])

    def test_news_older_than_30_days_is_not_kept_or_notified(self):
        self.monitor.check()
        old_date = (datetime.now(timezone.utc) - timedelta(days=31)).strftime("%d.%m.%Y")
        self.assertFalse(recent_news({"date": old_date}))
        self.pages[NEWS_URL] = news(806) + news(700, published=old_date)
        result = self.monitor.check()
        self.assertEqual([article["id"] for article in result["latestNews"]], ["806"])
        self.assertEqual([event["articleId"] for event in result["events"]], ["806"])
        self.assertIn("700", self.monitor._read()["seenNewsIds"])
        self.assertNotIn("700", self.monitor._read()["knownNews"])


if __name__ == "__main__":
    unittest.main()
