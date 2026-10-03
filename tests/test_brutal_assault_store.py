import tempfile
import unittest
from pathlib import Path

from brutal_assault_store import BrutalAssaultError, BrutalAssaultStore


class BrutalAssaultStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = BrutalAssaultStore(Path(self.temp_dir.name) / "ba2027.sqlite")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_create_and_list_album(self):
        created = self.store.create(
            {
                "artist": "Test Artist",
                "album": "Test Album",
                "year": 2026,
                "date": "2026-08-10",
                "minutes": 43,
            }
        )

        self.assertEqual(created["rowId"], 1)
        self.assertEqual(created["listened"], "")
        self.assertEqual(created["year"], "2026")
        self.assertEqual(self.store.snapshot()["rows"], [created])

    def test_rating_marks_album_as_listened(self):
        created = self.store.create({"artist": "Artist", "album": "Album"})
        updated = self.store.update(created["rowId"], {"rating": 4.5})

        self.assertEqual(updated["rating"], 4.5)
        self.assertEqual(updated["listened"], "TAK")

    def test_updates_album_metadata(self):
        created = self.store.create(
            {"artist": "Old Artist", "album": "Old Album", "minutes": 551}
        )

        updated = self.store.update(
            created["rowId"],
            {
                "artist": "New Artist",
                "album": "New Album",
                "year": 2012,
                "minutes": 51,
                "date": "2026-08-11",
                "description": "Pierwsze zdanie. Drugie zdanie.",
            },
        )

        self.assertEqual(updated["artist"], "New Artist")
        self.assertEqual(updated["album"], "New Album")
        self.assertEqual(updated["year"], "2012")
        self.assertEqual(updated["minutes"], 51)
        self.assertEqual(updated["date"], "2026-08-11")
        self.assertEqual(updated["description"], "Pierwsze zdanie. Drugie zdanie.")

    def test_rejects_description_longer_than_ten_sentences(self):
        created = self.store.create({"artist": "Artist", "album": "Album"})

        with self.assertRaises(BrutalAssaultError) as raised:
            self.store.update(created["rowId"], {"description": "Zdanie. " * 11})

        self.assertEqual(raised.exception.code, "invalid_description")

    def test_bulk_imports_descriptions_and_does_not_overwrite_existing_text(self):
        first = self.store.create({"artist": "First", "album": "One"})
        second = self.store.create(
            {"artist": "Second", "album": "Two", "description": "Existing text."}
        )

        result = self.store.bulk_update_descriptions({
            str(first["rowId"]): "[W SKRÓCIE]\nFresh description.",
            str(second["rowId"]): "Replacement text.",
        })

        self.assertEqual(result["updatedCount"], 1)
        self.assertEqual(result["skippedIds"], [second["rowId"]])
        self.assertEqual(self.store.get(first["rowId"])["description"], "[W SKRÓCIE]\nFresh description.")
        self.assertEqual(self.store.get(second["rowId"])["description"], "Existing text.")

    def test_bulk_import_accepts_more_than_ten_sentences(self):
        album = self.store.create({"artist": "Artist", "album": "Album"})
        description = "Zdanie. " * 11

        result = self.store.bulk_update_descriptions({str(album["rowId"]): description})

        self.assertEqual(result["updatedCount"], 1)
        self.assertEqual(self.store.get(album["rowId"])["description"], description.strip())

    def test_stores_community_rating_and_clears_it_after_identity_change(self):
        created = self.store.create({"artist": "Artist", "album": "Album"})
        enriched = self.store.update_community_rating(
            created["rowId"],
            rating=4.25,
            votes=12,
            source="MusicBrainz",
            url="https://musicbrainz.org/release-group/example",
        )

        self.assertEqual(enriched["communityRating"], 4.25)
        self.assertEqual(enriched["communityVotes"], 12)
        self.assertIsNotNone(enriched["communityCheckedAt"])

        renamed = self.store.update(created["rowId"], {"album": "Renamed Album"})
        self.assertIsNone(renamed["communityRating"])
        self.assertIsNone(renamed["communityCheckedAt"])

    def test_manual_rym_rating_has_full_decimal_precision_and_clears_musicbrainz(self):
        created = self.store.create({"artist": "Artist", "album": "Album"})
        self.store.update_community_rating(
            created["rowId"],
            rating=4.5,
            votes=100,
            source="MusicBrainz",
            url="https://musicbrainz.org/release-group/example",
        )

        updated = self.store.update(created["rowId"], {"rymRating": "3,87"})

        self.assertEqual(updated["rymRating"], 3.87)
        self.assertIsNone(updated["communityRating"])
        self.assertIsNone(updated["communityVotes"])
        self.assertIsNone(updated["communitySource"])
        self.assertIsNone(updated["communityCheckedAt"])

        after_late_musicbrainz = self.store.update_community_rating(
            created["rowId"],
            rating=4.9,
            votes=999,
            source="MusicBrainz",
            url="https://musicbrainz.org/release-group/late",
        )
        self.assertEqual(after_late_musicbrainz["rymRating"], 3.87)
        self.assertIsNone(after_late_musicbrainz["communityRating"])

    def test_validates_manual_rym_rating_range(self):
        created = self.store.create({"artist": "Artist", "album": "Album"})

        for invalid in (0.49, 5.01, "not-a-number"):
            with self.subTest(invalid=invalid), self.assertRaises(BrutalAssaultError) as raised:
                self.store.update(created["rowId"], {"rymRating": invalid})
            self.assertEqual(raised.exception.code, "invalid_rym_rating")

    def test_can_ignore_an_album_until_a_rym_rating_exists(self):
        created = self.store.create({"artist": "Artist", "album": "Unreleased"})

        ignored = self.store.update(created["rowId"], {"rymRatingIgnored": True})
        self.assertTrue(ignored["rymRatingIgnored"])

        rated = self.store.update(created["rowId"], {"rymRating": 3.91})
        self.assertFalse(rated["rymRatingIgnored"])

    def test_assigns_the_day_after_the_latest_album_when_date_is_omitted(self):
        self.store.create(
            {"artist": "First Artist", "album": "First Album", "date": "2026-08-10"}
        )

        second = self.store.create({"artist": "Second Artist", "album": "Second Album"})

        self.assertEqual(second["date"], "2026-08-11")

    def test_rejects_duplicate_album_case_insensitively(self):
        self.store.create({"artist": "Artist", "album": "Album"})

        with self.assertRaises(BrutalAssaultError) as raised:
            self.store.create({"artist": "artist", "album": "album"})

        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(raised.exception.code, "duplicate_album")

    def test_validates_rating_step(self):
        created = self.store.create({"artist": "Artist", "album": "Album"})

        with self.assertRaises(BrutalAssaultError):
            self.store.update(created["rowId"], {"rating": 4.2})


if __name__ == "__main__":
    unittest.main()
