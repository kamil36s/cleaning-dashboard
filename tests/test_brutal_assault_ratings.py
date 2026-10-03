import unittest
import tempfile
from pathlib import Path

from brutal_assault_ratings import BrutalAssaultRatingEnricher, choose_release_group
from brutal_assault_store import BrutalAssaultStore


class BrutalAssaultRatingsTests(unittest.TestCase):
    def test_prefers_exact_artist_and_album_match(self):
        results = [
            {
                "id": "wrong",
                "title": "Dethalbum III",
                "score": 100,
                "artist-credit": [{"name": "Other Artist"}],
            },
            {
                "id": "correct",
                "title": "Dethalbum III",
                "score": 99,
                "artist-credit": [{"name": "Dethklok"}],
            },
        ]

        self.assertEqual(
            choose_release_group(results, "Dethklok", "Dethalbum III")["id"],
            "correct",
        )

    def test_rejects_weak_search_match(self):
        results = [{
            "id": "weak",
            "title": "Another Album",
            "score": 70,
            "artist-credit": [{"name": "Artist"}],
        }]
        self.assertIsNone(choose_release_group(results, "Artist", "Album"))

    def test_does_not_schedule_musicbrainz_for_album_with_manual_rym_rating(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = BrutalAssaultStore(Path(temp_dir) / "ba2027.sqlite")
            album = store.create({
                "artist": "Artist",
                "album": "Album",
                "rymRating": 4.12,
            })
            enricher = BrutalAssaultRatingEnricher(store)

            self.assertEqual(enricher.schedule([album], force=True), 0)


if __name__ == "__main__":
    unittest.main()
