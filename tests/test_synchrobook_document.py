import tempfile
import unittest
from pathlib import Path

import pymupdf

from synchrobook_backend.document import DocumentError, extract_book


class SynchrobookDocumentTests(unittest.TestCase):
    def test_extracts_pdf_metadata_toc_chapters_and_complete_text(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "book.pdf"
            document = pymupdf.open()
            first = document.new_page()
            first.insert_text((72, 80), "Chapter One", fontsize=20)
            first.insert_text((72, 130), "This is the complete opening paragraph. It has two sentences.", fontsize=11)
            second = document.new_page()
            second.insert_text((72, 80), "Chapter Two", fontsize=20)
            second.insert_text((72, 130), "The second chapter is also present in full.", fontsize=11)
            document.set_metadata({"title": "PDF Book", "author": "PDF Author"})
            document.set_toc([[1, "Chapter One", 1], [1, "Chapter Two", 2]])
            document.save(source)
            document.close()

            result = extract_book(source, root / "text")

            self.assertEqual(result["sourceFormat"], "pdf")
            self.assertEqual(result["title"], "PDF Book")
            self.assertEqual(result["author"], "PDF Author")
            self.assertEqual([row["title"] for row in result["chapters"]], ["Chapter One", "Chapter Two"])
            rendered = " ".join(
                sentence["originalText"]
                for chapter in result["chapters"]
                for paragraph in chapter["paragraphs"]
                for sentence in paragraph["sentences"]
            )
            self.assertIn("complete opening paragraph", rendered)
            self.assertIn("second chapter", rendered)
            self.assertTrue((root / "text" / "cover.png").is_file())

    def test_rejects_pdf_without_a_text_layer_with_an_ocr_hint(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "scan.pdf"
            document = pymupdf.open()
            document.new_page()
            document.save(source)
            document.close()
            with self.assertRaisesRegex(DocumentError, "OCR"):
                extract_book(source, root / "text")


if __name__ == "__main__":
    unittest.main()
