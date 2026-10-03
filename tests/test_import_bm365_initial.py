import unittest

from bm365_store import _identity_key
from scripts.import_bm365_initial import merge_rows


class Bm365ImportIdentityTests(unittest.TestCase):
    def test_description_follows_album_when_row_ids_are_swapped(self):
        first = {"year": 1998, "description": "Cradle description", "identity": _identity_key("Cradle of Filth", "Cruelty and the Beast")}
        second = {"year": 2007, "description": "Lunar description", "identity": _identity_key("Lunar Aurora", "Andacht")}
        rows = [
            {"rowId": 205, "artist": "Cradle of Filth", "album": "Cruelty and the Beast"},
            {"rowId": 237, "artist": "Lunar Aurora", "album": "Andacht"},
        ]

        merged = merge_rows(
            rows,
            {205: second, 237: first},
            {first["identity"]: first, second["identity"]: second},
            [],
        )

        self.assertEqual(merged[0]["description"], "Cradle description")
        self.assertEqual(merged[1]["description"], "Lunar description")
        self.assertEqual(merged[0]["year"], 1998)

    def test_duplicate_album_keeps_description_for_its_own_row(self):
        identity = _identity_key("Bekëth Nexëhmü", "De fördolda klangorna")
        first = {"description": "First entry", "identity": identity}
        second = {"description": "Second entry", "identity": identity}

        merged = merge_rows(
            [{"rowId": 27, "artist": "Bekëth Nexëhmü", "album": "De fördolda klangorna"}],
            {27: first, 93: second},
            {identity: second},
            [],
        )

        self.assertEqual(merged[0]["description"], "First entry")


if __name__ == "__main__":
    unittest.main()
