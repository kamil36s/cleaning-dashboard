import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "import_tumblr_poems.py"
SPEC = importlib.util.spec_from_file_location("import_tumblr_poems", MODULE_PATH)
IMPORTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(IMPORTER)


class TumblrPoemImportTests(unittest.TestCase):
    def test_extracts_missing_title_from_leading_h1(self):
        title, body, source = IMPORTER.title_and_body({
            "regular-title": "",
            "regular-body": "<h1>quando ver venit meum?</h1><p>first line<br/>second line</p>",
        })

        self.assertEqual(title, "quando ver venit meum?")
        self.assertEqual(body, "<p>first line<br/>second line</p>")
        self.assertEqual(source, "leading-h1")

    def test_selects_original_regular_posts_and_tagged_photo_poems(self):
        self.assertEqual(IMPORTER.candidate_reason({"type": "regular", "tags": []}), "original-regular-untagged")
        self.assertEqual(IMPORTER.candidate_reason({"type": "regular", "tags": ["poem"]}), "explicit-poem-tag")
        self.assertEqual(IMPORTER.candidate_reason({"type": "photo", "tags": ["poetry"]}), "tagged-photo-poem")
        self.assertIsNone(IMPORTER.candidate_reason({"type": "quote", "tags": []}))

    def test_preserves_tumblr_calendar_day_without_timezone_shift(self):
        self.assertEqual(
            IMPORTER.tumblr_local_iso("Thu, 07 Mar 2024 18:43:16"),
            "2024-03-07T18:43:16",
        )


if __name__ == "__main__":
    unittest.main()
