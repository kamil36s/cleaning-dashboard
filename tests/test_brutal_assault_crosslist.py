import tempfile
import unittest
from pathlib import Path
from unittest import mock

import server
from brutal_assault_store import BrutalAssaultStore


class BrutalAssaultCrossListTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = BrutalAssaultStore(Path(self.temp_dir.name) / "ba2027.sqlite")
        self.store_patch = mock.patch.object(
            server, "BRUTAL_ASSAULT_2027_STORE", self.store
        )
        self.store_patch.start()

    def tearDown(self):
        self.store_patch.stop()
        self.temp_dir.cleanup()

    def test_album_identity_ignores_accents_ampersands_and_punctuation(self):
        self.assertEqual(
            server.album_identity_key("Mgła & Friends", "Album: One!"),
            server.album_identity_key("Mgla and Friends", "album one"),
        )

    def test_existing_bm365_rating_is_copied_to_local_album(self):
        created = self.store.create(
            {"artist": "Emperor", "album": "In the Nightside Eclipse"}
        )
        bm_rows = [{
            "rowId": 3,
            "date": "2026-01-02",
            "artist": "Emperor",
            "album": "In the Nightside Eclipse",
            "rating": 4,
        }]

        with mock.patch.object(server, "bm365_fetch_rows", return_value=bm_rows):
            matches = server.brutal_assault_2027_cross_sync()

        updated = self.store.list()[0]
        self.assertEqual(updated["rowId"], created["rowId"])
        self.assertEqual(updated["rating"], 4)
        self.assertEqual(updated["listened"], "TAK")
        self.assertEqual(matches[0]["bmRowId"], 3)

    def test_local_rating_is_written_to_unrated_bm365_match(self):
        self.store.create({
            "artist": "Emperor",
            "album": "IX Equilibrium",
            "rating": 3.5,
        })
        bm_row = {
            "rowId": 99,
            "date": "2026-01-03",
            "artist": "Emperor",
            "album": "IX Equilibrium",
            "rating": None,
        }

        with (
            mock.patch.object(server, "bm365_fetch_rows", return_value=[bm_row]),
            mock.patch.object(server, "bm365_rate_remote") as rate_remote,
        ):
            server.brutal_assault_2027_cross_sync()

        rate_remote.assert_called_once_with(bm_row, 3.5)


if __name__ == "__main__":
    unittest.main()
