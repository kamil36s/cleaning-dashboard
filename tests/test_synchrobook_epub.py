import tempfile
import unittest
import zipfile
from pathlib import Path

from synchrobook_backend.epub import extract_epub, repair_fragmented_words


CONTAINER = """<?xml version="1.0"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>"""

PACKAGE = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Test Book</dc:title><dc:creator>Test Author</dc:creator><dc:language>en</dc:language>
  </metadata>
  <manifest><item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/></manifest>
  <spine><itemref idref="chapter"/></spine>
</package>"""

CHAPTER = """<html xmlns="http://www.w3.org/1999/xhtml"><body>
<h1>Chapter One</h1><p>Dr. Smith waited. “No, I couldn't,” he said.</p>
<nav><p>This duplicated navigation must be excluded.</p></nav>
</body></html>"""

DIV_PACKAGE = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Div Book</dc:title><dc:creator>Author</dc:creator></metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="part" href="part.xhtml" media-type="application/xhtml+xml"/>
    <item id="body" href="body.xhtml" media-type="application/xhtml+xml"/>
    <item id="next-reads.xhtml" href="next-reads.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine><itemref idref="part"/><itemref idref="body"/><itemref idref="next-reads.xhtml"/></spine>
</package>"""

DIV_NAV = """<html xmlns="http://www.w3.org/1999/xhtml"><body><nav epub:type="toc" xmlns:epub="http://www.idpf.org/2007/ops"><ol>
<li><a href="part.xhtml">PART ONE</a><ol><li><a href="body.xhtml">.</a></li></ol></li>
</ol></nav></body></html>"""

NCX_PACKAGE = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Polish Book</dc:title><dc:creator>Author</dc:creator><dc:language>pl</dc:language></metadata>
  <manifest>
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
    <item id="first" href="text/chapter_split_000.html" media-type="application/xhtml+xml"/>
    <item id="continued" href="text/chapter_split_001.html" media-type="application/xhtml+xml"/>
  </manifest>
  <spine toc="ncx"><itemref idref="first"/><itemref idref="continued"/></spine>
</package>"""

NCX_TOC = """<?xml version="1.0" encoding="UTF-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/"><navMap>
  <navPoint><navLabel><text>O czym to bę dzie</text></navLabel><content src="text/chapter_split_000.html#one"/></navPoint>
  <navPoint><navLabel><text>Ki bol sie dzi na ka sie</text></navLabel><content src="text/chapter_split_000.html#two"/></navPoint>
</navMap></ncx>"""


class SynchrobookEpubTests(unittest.TestCase):
    def test_repairs_long_fragmented_words_names_and_glued_polish_prepositions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            broken = (
                "Marek Zień czuk i Marcin Ki czyń skiego. Każda zi den ty fi ko wana osoba "
                "wkracza jąc zostanie wy eli mi no wana. Pomagał w wy ga sza niu sporu wOżarowie. "
                "Wrzeczywistości Wam udało się to zrobić, ale odpowiada za to nie on. "
                "Na pierwszy rzut okanie ma nic dziwnego. Z wi ślac kiej bojówki."
            )
            book = {
                "language": "pl",
                "chapters": [{
                    "id": "ch01", "title": "Rozdział", "paragraphs": [{
                        "id": "ch01-p001", "heading": False, "sentences": [{
                            "id": "ch01-p001-s001", "text": broken, "originalText": broken,
                        }],
                    }],
                }],
            }
            transcript = {"language": "pl", "segments": [{
                "text": "Marek Zieńczuk i Marcin Kiecińskiego. Każda zidentyfikowana osoba "
                        "wkraczając zostanie wyeliminowana. Pomagał w wygaszeniu sporu w Ożarowie."
            }]}

            repaired = repair_fragmented_words(book, transcript, root / "text")
            text = repaired["chapters"][0]["paragraphs"][0]["sentences"][0]["originalText"]

            self.assertIn("Marek Zieńczuk", text)
            self.assertIn("Marcin Kiczyńskiego", text)
            self.assertIn("zidentyfikowana", text)
            self.assertIn("wkraczając", text)
            self.assertIn("wyeliminowana", text)
            self.assertIn("wygaszaniu", text)
            self.assertIn("w Ożarowie", text)
            self.assertIn("W rzeczywistości Wam udało się to zrobić", text)
            self.assertIn("odpowiada za to nie on", text)
            self.assertIn("Na pierwszy rzut oka nie ma nic dziwnego", text)
            self.assertIn("Z wiślackiej bojówki", text)
            self.assertEqual(repaired["wordRepairVersion"], 3)

    def test_extracts_metadata_structure_original_text_and_stable_ids(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "book.epub"
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("mimetype", "application/epub+zip")
                archive.writestr("META-INF/container.xml", CONTAINER)
                archive.writestr("OEBPS/content.opf", PACKAGE)
                archive.writestr("OEBPS/chapter.xhtml", CHAPTER)
            result = extract_epub(source, root / "text")
            self.assertEqual(result["title"], "Test Book")
            self.assertEqual(result["author"], "Test Author")
            rows = result["chapters"][0]["paragraphs"][1]["sentences"]
            self.assertEqual(rows[0]["id"], "ch01-p002-s001")
            self.assertEqual(rows[0]["originalText"], "Dr. Smith waited.")
            self.assertEqual(rows[1]["normalizedText"], "no i could not he said")
            self.assertNotIn("navigation", (root / "text" / "book.json").read_text(encoding="utf-8"))

    def test_reads_div_paragraphs_and_merges_separate_part_heading(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "book.epub"
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("META-INF/container.xml", CONTAINER)
                archive.writestr("OEBPS/content.opf", DIV_PACKAGE)
                archive.writestr("OEBPS/nav.xhtml", DIV_NAV)
                archive.writestr("OEBPS/part.xhtml", "<html><body><div class='ct'>PART ONE</div></body></html>")
                archive.writestr("OEBPS/body.xhtml", "<html><body><div><div class='tx1'>The novel begins here.</div><div class='tx'>This is the complete first paragraph of prose.</div></div></body></html>")
                archive.writestr("OEBPS/next-reads.xhtml", "<html><body><div>What is next on your reading list?</div></body></html>")
            result = extract_epub(source, root / "text")
            self.assertEqual(len(result["chapters"]), 1)
            self.assertEqual(result["chapters"][0]["title"], "PART ONE")
            rendered = " ".join(
                sentence["originalText"]
                for paragraph in result["chapters"][0]["paragraphs"]
                for sentence in paragraph["sentences"]
            )
            self.assertIn("The novel begins here.", rendered)
            self.assertNotIn("reading list", rendered)

    def test_reads_epub2_ncx_anchors_repairs_inline_spans_and_merges_split_continuation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "book.epub"
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("META-INF/container.xml", CONTAINER)
                archive.writestr("OEBPS/content.opf", NCX_PACKAGE)
                archive.writestr("OEBPS/toc.ncx", NCX_TOC)
                archive.writestr("OEBPS/text/chapter_split_000.html", """<html><body>
                  <p id='one'>Chcia<span>ł</span>oby wi dzieć ki boli jako pro stych ban dy tów.</p>
                  <p id='two'>Ki bol sie dzi na ka sie.</p>
                </body></html>""")
                archive.writestr("OEBPS/text/chapter_split_001.html", "<html><body><p>Dalszy tekst tego samego rozdziału.</p></body></html>")
            result = extract_epub(source, root / "text")
            self.assertEqual([chapter["title"] for chapter in result["chapters"]], ["O czym to bę dzie", "Ki bol sie dzi na ka sie"])
            self.assertEqual(result["chapters"][0]["paragraphs"][0]["sentences"][0]["originalText"], "Chciałoby wi dzieć ki boli jako pro stych ban dy tów.")
            self.assertIn("Dalszy tekst", result["chapters"][1]["paragraphs"][-1]["sentences"][0]["originalText"])
            repaired = repair_fragmented_words(result, {"language": "pl", "segments": [
                {"text": "O czym to będzie. Chciałoby widzieć kiboli jako prostych bandytów."},
                {"text": "Kibol siedzi na kasie. Dalszy tekst tego samego rozdziału."},
            ]}, root / "text")
            self.assertEqual(repaired["chapters"][0]["title"], "O czym to będzie")
            self.assertEqual(repaired["chapters"][1]["title"], "Kibol siedzi na kasie")
            self.assertIn("Chciałoby widzieć kiboli jako prostych bandytów.", (root / "text" / "book.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
