import tempfile
import unittest
from pathlib import Path

from rym_polish_black_metal_store import RymPolishBlackMetalStore


class RymPolishBlackMetalStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(__file__).resolve().parents[1]
        self.store = RymPolishBlackMetalStore(
            Path(self.temp_dir.name) / "rym.sqlite",
            root / "data" / "rym-polish-black-metal-top-100.json",
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_seeds_exactly_one_hundred_albums_in_new_chart_order(self):
        rows = self.store.list()

        self.assertEqual(len(rows), 100)
        self.assertEqual(rows[0]["sourceRank"], 1)
        self.assertEqual(rows[0]["artist"], "Azarath")
        self.assertEqual(rows[0]["album"], "Diabolic Impious Evil")
        self.assertEqual(rows[-1]["sourceRank"], 100)

    def test_rating_is_local_and_marks_album_as_listened(self):
        first = self.store.list()[0]

        updated = self.store.update(first["rowId"], {"rating": 4.5})

        self.assertEqual(updated["rating"], 4.5)
        self.assertEqual(updated["listened"], "TAK")
        self.assertEqual(updated["communitySource"], "Rate Your Music")

    def test_description_can_be_edited_and_imported_in_batches(self):
        first, second = self.store.list()[:2]

        updated = self.store.update(
            first["rowId"],
            {"description": "[W SKRÓCIE]\nPierwszy opis."},
        )
        imported = self.store.bulk_update_descriptions({
            str(first["rowId"]): "Nie nadpisuj istniejącego.",
            str(second["rowId"]): "[W SKRÓCIE]\nDrugi opis.",
        })

        rows = self.store.list()
        self.assertEqual(updated["description"], "[W SKRÓCIE]\nPierwszy opis.")
        self.assertEqual(imported["updatedCount"], 1)
        self.assertIn(first["rowId"], imported["skippedIds"])
        self.assertEqual(rows[1]["description"], "[W SKRÓCIE]\nDrugi opis.")


if __name__ == "__main__":
    unittest.main()
