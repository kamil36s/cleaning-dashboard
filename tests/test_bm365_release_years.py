import unittest
from unittest import mock

import server


class Bm365ReleaseYearTests(unittest.TestCase):
    def setUp(self):
        server.BM365_RELEASE_YEARS_CACHE["rows"] = None
        server.BM365_RELEASE_YEARS_CACHE["fetched_at"] = 0.0

    def tearDown(self):
        server.BM365_RELEASE_YEARS_CACHE["rows"] = None
        server.BM365_RELEASE_YEARS_CACHE["fetched_at"] = 0.0

    def test_reads_release_years_using_physical_sheet_row_ids(self):
        values = [
            ["1 Jan 2026", "1", "Darkthrone", "A Blaze in the Northern Sky", "1992"],
            [],
            ["3 Jan 2026", "3", "Emperor", "In the Nightside Eclipse", "1994"],
        ]
        with mock.patch.object(
            server,
            "google_sheets_api_request",
            return_value={"values": values},
        ) as request:
            rows = server.bm365_release_year_rows(force=True)

        self.assertEqual(
            rows,
            [
                {
                    "rowId": 2,
                    "artist": "Darkthrone",
                    "album": "A Blaze in the Northern Sky",
                    "year": "1992",
                },
                {
                    "rowId": 4,
                    "artist": "Emperor",
                    "album": "In the Nightside Eclipse",
                    "year": "1994",
                },
            ],
        )
        self.assertIn("A2%3AE", request.call_args.args[1])

    def test_metadata_snapshot_merges_year_with_saved_description(self):
        stored = {
            "ok": True,
            "metadata": [{
                "rowId": 2,
                "artist": "Darkthrone",
                "album": "A Blaze in the Northern Sky",
                "description": "Surowy klasyk.",
            }],
            "count": 1,
            "storedPath": "example.sqlite",
        }
        release_rows = [{
            "rowId": 2,
            "artist": "Darkthrone",
            "album": "A Blaze in the Northern Sky",
            "year": "1992",
        }]
        with (
            mock.patch.object(server.BM365_METADATA_STORE, "snapshot", return_value=stored),
            mock.patch.object(server, "bm365_release_year_rows", return_value=release_rows),
        ):
            result = server.bm365_metadata_snapshot()

        self.assertEqual(result["releaseYearsCount"], 1)
        self.assertEqual(result["metadata"][0]["year"], "1992")
        self.assertEqual(result["metadata"][0]["description"], "Surowy klasyk.")


if __name__ == "__main__":
    unittest.main()
