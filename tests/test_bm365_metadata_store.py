import tempfile
import unittest
from pathlib import Path

from bm365_metadata_store import Bm365MetadataStore


class Bm365MetadataStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = Bm365MetadataStore(Path(self.temp_dir.name) / "bm365.sqlite")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_saves_description(self):
        saved = self.store.update(
            2,
            {
                "description": "[W SKRÓCIE]\nSurowy klasyk. Warto posłuchać.",
            },
            artist="Darkthrone",
            album="A Blaze in the Northern Sky",
        )

        self.assertEqual(saved["rowId"], 2)
        self.assertIn("Surowy klasyk", saved["description"])
        self.assertEqual(self.store.snapshot()["metadata"], [saved])

    def test_bulk_import_skips_existing_descriptions(self):
        albums = {
            2: {"artist": "Darkthrone", "album": "A Blaze in the Northern Sky"},
            3: {"artist": "Emperor", "album": "In the Nightside Eclipse"},
        }
        self.store.update(
            2,
            {"description": "Istniejący opis."},
            artist=albums[2]["artist"],
            album=albums[2]["album"],
        )

        result = self.store.bulk_update_descriptions(
            {"2": "Nowy opis.", "3": "Świeży opis."}, albums
        )

        self.assertEqual(result["updatedCount"], 1)
        self.assertEqual(result["skippedIds"], [2])
        descriptions = {
            row["rowId"]: row["description"] for row in self.store.list()
        }
        self.assertEqual(descriptions[2], "Istniejący opis.")
        self.assertEqual(descriptions[3], "Świeży opis.")


if __name__ == "__main__":
    unittest.main()
