import tempfile
import unittest
from pathlib import Path
from unittest import mock

import server
from brutal_assault_store import BrutalAssaultStore
from rym_polish_black_metal_store import RymPolishBlackMetalStore


class RymPolishBlackMetalCrossListTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        temp_root = Path(self.temp_dir.name)
        project_root = Path(__file__).resolve().parents[1]
        self.rym_store = RymPolishBlackMetalStore(
            temp_root / "rym.sqlite",
            project_root / "data" / "rym-polish-black-metal-top-100.json",
        )
        self.ba_store = BrutalAssaultStore(temp_root / "ba.sqlite")
        self.ba_store.create({
            "artist": "Azarath",
            "album": "Diabolic Impious Evil",
        })

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_snapshot_marks_matches_from_both_other_album_lists(self):
        bm_rows = [{
            "rowId": 17,
            "date": "2026-01-17",
            "artist": "Azarath",
            "album": "Diabolic Impious Evil",
            "rating": None,
        }]
        with (
            mock.patch.object(server, "RYM_POLISH_BLACK_METAL_STORE", self.rym_store),
            mock.patch.object(server, "BRUTAL_ASSAULT_2027_STORE", self.ba_store),
            mock.patch.object(server, "bm365_fetch_rows", return_value=bm_rows),
        ):
            snapshot = server.rym_polish_black_metal_snapshot_with_cross_lists()

        first = snapshot["rows"][0]
        self.assertEqual(first["sourceRank"], 1)
        self.assertEqual(
            [item["label"] for item in first["crossLists"]],
            ["Black Metal 365", "Brutal Assault 2027"],
        )

    def test_bm365_rating_is_copied_to_both_local_lists(self):
        bm_rows = [{
            "rowId": 17,
            "date": "2026-01-17",
            "artist": "Azarath",
            "album": "Diabolic Impious Evil",
            "rating": 4.5,
        }]
        with (
            mock.patch.object(server, "RYM_POLISH_BLACK_METAL_STORE", self.rym_store),
            mock.patch.object(server, "BRUTAL_ASSAULT_2027_STORE", self.ba_store),
            mock.patch.object(server, "bm365_fetch_rows", return_value=bm_rows),
        ):
            result = server.sync_bm_rating_to_ba({
                "artist": "Azarath",
                "album": "Diabolic Impious Evil",
                "rating": 4.5,
            })

        self.assertTrue(result["matched"])
        self.assertEqual(self.ba_store.list()[0]["rating"], 4.5)
        self.assertEqual(self.rym_store.list()[0]["rating"], 4.5)

    def test_rym_rating_is_copied_to_brutal_and_bm365(self):
        rym_album = self.rym_store.list()[0]
        rym_album = self.rym_store.update(rym_album["rowId"], {"rating": 3.5})
        bm_row = {
            "rowId": 17,
            "date": "2026-01-17",
            "artist": "Azarath",
            "album": "Diabolic Impious Evil",
            "rating": None,
        }
        with (
            mock.patch.object(server, "RYM_POLISH_BLACK_METAL_STORE", self.rym_store),
            mock.patch.object(server, "BRUTAL_ASSAULT_2027_STORE", self.ba_store),
            mock.patch.object(server, "bm365_fetch_rows", return_value=[bm_row]),
            mock.patch.object(server, "bm365_rate_remote") as rate_remote,
        ):
            server.sync_album_rating_across_lists(
                rym_album,
                source="rym-polish-black-metal-top-100",
                rym_row=rym_album,
            )

        self.assertEqual(self.ba_store.list()[0]["rating"], 3.5)
        rate_remote.assert_called_once_with(bm_row, 3.5)

    def test_bm365_rate_remote_writes_local_store_and_wakes_background_sync(self):
        local_store = mock.Mock()
        local_store.rate_album.return_value = {"rowId": 17, "rating": 3.5}
        with (
            mock.patch.object(server, "BM365_STORE", local_store),
            mock.patch.object(server.BM365_SHEETS_SYNCER, "notify") as notify,
        ):
            result = server.bm365_rate_remote({"rowId": 17}, 3.5)

        local_store.rate_album.assert_called_once_with(
            {"rowId": 17, "date": None}, 3.5, propagate=False
        )
        notify.assert_called_once_with()
        self.assertTrue(result["ok"])


if __name__ == "__main__":
    unittest.main()
