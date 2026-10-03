import tempfile
import unittest
from datetime import date
from pathlib import Path

from lastfm_store import LastFmStore, normalize_name
from timeline_activity import TimelineActivityService


class LastFmStoreTests(unittest.TestCase):
    def test_clean_row_accepts_extended_recent_tracks_artist_shape(self):
        cleaned = LastFmStore._clean_row({
            "date": {"uts": "1786746744"},
            "artist": {"name": "Chelsea Wolfe", "mbid": ""},
            "album": {"#text": "The Dark", "mbid": ""},
            "name": "The Dark",
        })

        self.assertIsNotNone(cleaned)
        self.assertEqual(cleaned[5], "Chelsea Wolfe")
        self.assertEqual(cleaned[7], "The Dark")
        self.assertEqual(cleaned[9], "The Dark")

    def test_import_matches_edition_names_and_builds_exact_period_charts(self):
        csv_text = (
            "uts,utc_time,artist,artist_mbid,album,album_mbid,track,track_mbid\n"
            "1767265200,,Mgła,,Exercises in Futility,,I,\n"
            "1767265500,,Mgła,,Exercises in Futility (Remastered),,II,\n"
            "1767351600,,Mgła,,Age of Excuse,,I,\n"
            "1767351900,,Cultes des Ghoules,,Häxan,,The Voice of Satan,\n"
            "1767351900,,Cultes des Ghoules,,Häxan,,The Voice of Satan,\n"
        )
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "recent.csv"
            source.write_text(csv_text, encoding="utf-8")
            store = LastFmStore(root)

            result = store.import_csv(source)
            matched = store.match_albums([{"artist": "Mgla", "album": "Exercises in Futility — Deluxe"}])
            charts = store.timeline_charts(date(2026, 1, 1), date(2026, 12, 31))

            self.assertEqual(result["processed"], 5)
            self.assertEqual(result["inserted"], 4)
            self.assertEqual(result["duplicates"], 1)
            self.assertEqual(matched["albums"][0]["albumScrobbles"], 2)
            year = next(row for row in charts if row["granularity"] == "year")
            self.assertEqual(year["scrobbles"], 4)
            self.assertEqual(year["topArtist"], {"name": "Mgła", "scrobbles": 3})

    def test_timeline_adapter_exposes_all_four_granularities(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "recent.csv"
            source.write_text(
                "uts,utc_time,artist,artist_mbid,album,album_mbid,track,track_mbid\n"
                "1767265200,,Artist,,Album,,Song,\n",
                encoding="utf-8",
            )
            store = LastFmStore(root)
            store.import_csv(source)
            service = TimelineActivityService(root, lastfm_store=store)

            result = service.query("2026-01-01", "2026-12-31", {"lastfm"})
            events = [event for day in result["days"] for event in day["events"]]

            self.assertEqual({event["metrics"]["granularity"] for event in events}, {"day", "week", "month", "year"})
            self.assertTrue(all(event["private"] for event in events))
            self.assertTrue(all(len(event["day"]) == 10 for event in events))
            year = next(event for event in events if event["metrics"]["granularity"] == "year")
            self.assertEqual(year["day"], "2026-01-01")
            expected_summary = "Artist: Artist (1)\nAlbum: Album by Artist (1)\nTrack: Song by Artist (1)"
            self.assertTrue(all(event["summary"] == expected_summary for event in events))

    def test_incremental_update_advances_album_and_period_totals(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "recent.csv"
            source.write_text(
                "uts,utc_time,artist,artist_mbid,album,album_mbid,track,track_mbid\n"
                "1767265200,,Artist,,Album,,Song one,\n",
                encoding="utf-8",
            )
            store = LastFmStore(root)
            store.import_csv(source)
            next_row = store._clean_row({
                "uts": "1767268800", "artist": "Artist", "album": "Album", "track": "Song two",
            })
            with store._connect() as connection:
                connection.execute(store._insert_sql(), next_row)

            store.apply_incremental_updates(1767265200)
            matched = store.match_albums([{"artist": "Artist", "album": "Album"}])["albums"][0]
            year = next(row for row in store.timeline_charts(date(2026, 1, 1), date(2026, 12, 31)) if row["granularity"] == "year")

            self.assertEqual(matched["albumScrobbles"], 2)
            self.assertEqual(matched["uniqueTracks"], 2)
            self.assertEqual(year["scrobbles"], 2)

    def test_normalization_keeps_artist_and_album_matching_stable(self):
        self.assertEqual(normalize_name("Mgła"), "mgla")
        self.assertEqual(normalize_name("Don't Break the Oath (2024 Remastered)", album=True), "don t break the oath")
        self.assertEqual(normalize_name("шумные и угрожающие выходки"), "шумные и угрожающие выходки")
        self.assertNotEqual(normalize_name("Океан Ельзи"), normalize_name("Путь"))
        self.assertNotEqual(normalize_name("!!!"), normalize_name("†††"))
        self.assertNotEqual(normalize_name("★"), normalize_name("•"))

    def test_import_preserves_full_history_and_keeps_unicode_artists_distinct(self):
        csv_text = (
            "uts,utc_time,artist,artist_mbid,album,album_mbid,track,track_mbid\n"
            "1262304000,,Океан Ельзи,,Альбом,,Пісня,\n"
            "1767265200,,Путь,,Песни смерти,,Эпитафия,\n"
            "1767265500,,Michael Kiwanuka,,KIWANUKA,,Hero,\n"
            "1767265800,,Michael Kiwanuka,,KIWANUKA,,Hero,\n"
        )
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "recent.csv"
            source.write_text(csv_text, encoding="utf-8")
            store = LastFmStore(root)

            result = store.import_csv(source)
            chart = next(row for row in store.timeline_charts(date(2026, 1, 1), date(2026, 12, 31)) if row["granularity"] == "year")

            self.assertEqual(result["status"]["totalScrobbles"], 4)
            self.assertEqual(chart["topArtist"], {"name": "Michael Kiwanuka", "scrobbles": 2})


if __name__ == "__main__":
    unittest.main()
