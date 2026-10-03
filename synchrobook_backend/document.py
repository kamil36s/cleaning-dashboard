"""Book extraction dispatch for EPUB, text PDFs, and unencrypted MOBI files."""

from __future__ import annotations

import re
import statistics
from pathlib import Path

from .epub import _write_extracted_book, extract_epub
from .text import normalize_text, split_sentences


class DocumentError(ValueError):
    pass


def _pymupdf():
    try:
        import pymupdf
        return pymupdf
    except ImportError:
        try:
            import fitz as pymupdf
            return pymupdf
        except ImportError as exc:
            raise DocumentError(
                "PDF/MOBI import requires PyMuPDF. Run: pip install -r requirements-synchrobook.txt"
            ) from exc


def _clean_block_text(value: str) -> str:
    value = str(value or "").replace("\u00ad", "")
    value = re.sub(r"(?<=\w)[\u2010-\u2011-]\s*\n\s*(?=[a-ząćęłńóśźż])", "", value)
    return " ".join(value.replace("\r", "\n").split())


def _page_blocks(page) -> list[dict]:
    rows = []
    payload = page.get_text("dict", sort=True)
    for block in payload.get("blocks", []):
        if block.get("type") != 0:
            continue
        lines = []
        sizes = []
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            lines.append("".join(str(span.get("text") or "") for span in spans))
            sizes.extend(float(span.get("size") or 0) for span in spans if span.get("text"))
        text = _clean_block_text("\n".join(lines))
        if not text or (text.isdigit() and len(text) <= 5):
            continue
        rows.append({
            "text": text,
            "size": max(sizes, default=0),
            "y": float((block.get("bbox") or [0, 0, 0, 0])[1]),
        })
    return rows


def _chapter_boundaries(document, pages: list[list[dict]], body_size: float, fallback_title: str) -> list[tuple[int, str]]:
    by_page: dict[int, tuple[int, str]] = {}
    try:
        toc = document.get_toc(simple=True) or []
    except Exception:
        toc = []
    for entry in toc:
        if len(entry) < 3:
            continue
        level, title, page_number = int(entry[0]), _clean_block_text(entry[1]), int(entry[2]) - 1
        if title and 0 <= page_number < len(pages):
            previous = by_page.get(page_number)
            # Prefer the broad chapter/part title when a PDF outline contains
            # several nested entries pointing at the same first page.
            if previous is None or level < previous[0]:
                by_page[page_number] = (level, title)
    if by_page:
        boundaries = sorted((page, value[1]) for page, value in by_page.items())
        if boundaries[0][0] > 0:
            boundaries.insert(0, (0, "Początek"))
        return boundaries

    boundaries = [(0, fallback_title or "Książka")]
    seen = {normalize_text(boundaries[0][1])}
    for page_index, blocks in enumerate(pages[1:], 1):
        if not blocks:
            continue
        candidate = blocks[0]
        words = candidate["text"].split()
        key = normalize_text(candidate["text"])
        if (
            candidate["y"] < 320
            and 1 <= len(words) <= 14
            and len(candidate["text"]) <= 120
            and candidate["size"] >= body_size * 1.28
            and key not in seen
        ):
            boundaries.append((page_index, candidate["text"]))
            seen.add(key)
    return boundaries


def extract_pdf_or_mobi(source: Path, output_dir: Path) -> dict:
    pymupdf = _pymupdf()
    try:
        document = pymupdf.open(str(source))
    except Exception as exc:
        raise DocumentError(f"Nie udało się otworzyć pliku {source.suffix.upper()}: {exc}") from exc
    try:
        if getattr(document, "needs_pass", False):
            raise DocumentError("Zabezpieczone hasłem lub DRM książki nie są obsługiwane")
        if getattr(document, "is_reflowable", False):
            document.layout(width=720, height=960, fontsize=12)
        metadata = document.metadata or {}
        title = _clean_block_text(metadata.get("title")) or source.stem
        author = _clean_block_text(metadata.get("author")) or "Unknown author"
        language = _clean_block_text(metadata.get("language"))
        pages = [_page_blocks(page) for page in document]
        sizes = [row["size"] for page in pages for row in page if row["size"] > 0 and len(row["text"].split()) >= 5]
        body_size = statistics.median(sizes) if sizes else 11.0
        if not any(pages):
            raise DocumentError(
                "Dokument nie zawiera tekstu do odczytu. Skanowany PDF trzeba najpierw przepuścić przez OCR."
            )
        boundaries = _chapter_boundaries(document, pages, body_size, title)
        chapters = []
        for boundary_index, (start_page, chapter_title) in enumerate(boundaries):
            end_page = boundaries[boundary_index + 1][0] if boundary_index + 1 < len(boundaries) else len(pages)
            chapter_id = f"ch{len(chapters) + 1:02d}"
            paragraphs = []
            for page_index in range(start_page, end_page):
                for block in pages[page_index]:
                    if page_index == start_page and normalize_text(block["text"]) == normalize_text(chapter_title):
                        continue
                    originals = split_sentences(block["text"])
                    if not originals:
                        continue
                    paragraph_id = f"{chapter_id}-p{len(paragraphs) + 1:03d}"
                    heading = block["size"] >= body_size * 1.22 and len(block["text"].split()) <= 18
                    sentences = []
                    for sentence_index, original in enumerate(originals, 1):
                        sentence_id = f"{paragraph_id}-s{sentence_index:03d}"
                        sentences.append({
                            "id": sentence_id,
                            "text": original,
                            "originalText": original,
                            "normalizedText": normalize_text(original),
                            "heading": heading,
                        })
                    paragraphs.append({"id": paragraph_id, "heading": heading, "sentences": sentences})
            if paragraphs:
                chapters.append({
                    "id": chapter_id,
                    "title": chapter_title or f"Rozdział {len(chapters) + 1}",
                    "sourceHref": f"{source.name}#page={start_page + 1}",
                    "sourceHrefs": [f"{source.name}#pages={start_page + 1}-{end_page}"],
                    "paragraphs": paragraphs,
                })
        if not chapters:
            raise DocumentError("Nie znaleziono czytelnej treści książki")

        cover_file = None
        try:
            pixmap = document[0].get_pixmap(matrix=pymupdf.Matrix(1.2, 1.2), alpha=False)
            output_dir.mkdir(parents=True, exist_ok=True)
            cover_file = "cover.png"
            pixmap.save(str(output_dir / cover_file))
        except Exception:
            cover_file = None
        payload = {
            "extractionVersion": 5,
            "sourceFormat": source.suffix.lower().lstrip("."),
            "title": title,
            "author": author,
            "language": language,
            "coverFile": cover_file,
            "chapters": chapters,
        }
        _write_extracted_book(payload, output_dir)
        return payload
    finally:
        document.close()


def extract_book(source: Path, output_dir: Path) -> dict:
    extension = source.suffix.lower()
    if extension == ".epub":
        return extract_epub(source, output_dir)
    if extension in {".pdf", ".mobi"}:
        return extract_pdf_or_mobi(source, output_dir)
    raise DocumentError(f"Nieobsługiwany format książki: {extension or 'brak rozszerzenia'}")
