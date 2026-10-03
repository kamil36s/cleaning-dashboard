"""EPUB metadata, cover, chapter, paragraph, and sentence extraction."""

from __future__ import annotations

import json
import mimetypes
import re
import unicodedata
import zipfile
from collections import Counter
from functools import lru_cache
from pathlib import Path, PurePosixPath
from urllib.parse import unquote
from xml.etree import ElementTree

from bs4 import BeautifulSoup

try:
    from wordfreq import zipf_frequency
except ImportError:  # Transcript-only repair remains available after a minimal install.
    zipf_frequency = None

from .text import normalize_text, split_sentences


class EpubError(ValueError):
    pass


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _safe_member(name: str) -> str:
    normalized = str(PurePosixPath(name))
    if normalized.startswith("/") or ".." in PurePosixPath(normalized).parts:
        raise EpubError("EPUB contains an unsafe path")
    return normalized


def _joined(base: str, href: str) -> str:
    return _safe_member(str(PurePosixPath(base).parent / PurePosixPath(href)))


BLOCK_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "blockquote", "li", "div", "section", "article"}
HEADING_CLASSES = {"ct", "cct", "fmht", "bmhT", "bmht", "fmh1", "aph1", "chapter", "chapter-title", "title"}


def _clean_text(value: str) -> str:
    # U+2010 and soft hyphens in PDF-derived EPUBs are line-break markers,
    # not semantic hyphens. Real compound-word hyphens remain untouched.
    value = str(value or "").replace("\ufffd", "'").replace("\u00ad", "").replace("\u2010", "")
    return " ".join(value.split())


def _useful_label(value: str) -> str | None:
    label = _clean_text(value).strip(". ,;:-–—")
    return label if any(character.isalnum() for character in label) else None


def _navigation_map(archive: zipfile.ZipFile, manifest: dict[str, dict], rootfile: str, names: set[str]) -> dict[str, dict]:
    """Map content files and anchors from EPUB3 nav or EPUB2 NCX documents."""
    output: dict[str, dict] = {}

    def add_entry(nav_member: str, href: str, label: str | None, parent_label: str | None = None) -> None:
        decoded = unquote(str(href or "")).replace("\\", "/")
        path, _, fragment = decoded.partition("#")
        if not path or re.match(r"^(?:[a-z]:|/)", path, re.I):
            return
        try:
            member = _joined(nav_member, path)
        except EpubError:
            return
        if member not in names:
            return
        record = output.setdefault(member, {"label": None, "parentLabel": None, "entries": []})
        useful = _useful_label(label)
        parent = _useful_label(parent_label)
        effective = useful or parent
        if effective:
            record["entries"].append({"fragment": fragment or None, "label": effective, "parentLabel": parent})
            if record["label"] is None or not fragment:
                record["label"], record["parentLabel"] = effective, parent

    navigation = next(
        (item for item in manifest.values() if "nav" in item.get("properties", "").split()), None
    )
    if navigation and navigation.get("href"):
        nav_member = _joined(rootfile, navigation["href"])
        if nav_member in names:
            soup = BeautifulSoup(archive.read(nav_member), "html.parser")
            toc = soup.find("nav", attrs={"epub:type": "toc"}) or soup.find("nav") or soup
            for link in toc.find_all("a", href=True):
                parent_label = None
                own_li = link.find_parent("li")
                parent_li = own_li.find_parent("li") if own_li else None
                if parent_li:
                    parent_link = parent_li.find("a", href=True, recursive=False)
                    if parent_link:
                        parent_label = parent_link.get_text(" ", strip=True)
                add_entry(nav_member, link.get("href"), link.get_text(" ", strip=True), parent_label)

    ncx = next(
        (item for item in manifest.values() if item.get("media-type") == "application/x-dtbncx+xml"), None
    )
    if ncx and ncx.get("href"):
        ncx_member = _joined(rootfile, ncx["href"])
        if ncx_member in names:
            soup = BeautifulSoup(archive.read(ncx_member), "xml")
            for point in soup.find_all("navPoint"):
                label_node = point.find("navLabel", recursive=False)
                content = point.find("content", recursive=False)
                parent_point = point.find_parent("navPoint")
                parent_node = parent_point.find("navLabel", recursive=False) if parent_point else None
                label = label_node.get_text(" ", strip=True) if label_node else None
                parent_label = parent_node.get_text(" ", strip=True) if parent_node else None
                if content and content.get("src"):
                    add_entry(ncx_member, content.get("src"), label, parent_label)
    return output


def _is_heading(block) -> bool:
    if re.fullmatch(r"h[1-6]", block.name or ""):
        return True
    classes = {str(value).casefold() for value in block.get("class", [])}
    if classes & {value.casefold() for value in HEADING_CLASSES}:
        return True
    joined = " ".join(classes)
    return bool(re.search(r"(?:^|[-_])(chapter|heading|head|title)(?:$|[-_])", joined))


def _content_blocks(soup: BeautifulSoup) -> list[dict]:
    """Read leaf-level block elements, including publisher div-based paragraphs."""
    body = soup.body or soup
    paragraphs = []
    for block in body.find_all(BLOCK_TAGS):
        # A structural wrapper must not duplicate the text of its child blocks.
        if block.find(BLOCK_TAGS):
            continue
        for line_break in block.find_all("br"):
            line_break.replace_with(" ")
        # Preserve whitespace from text nodes. Inserting a separator between
        # inline spans corrupts words such as chcia<span>ł</span>oby.
        text = _clean_text(block.get_text("", strip=False))
        if not text:
            continue
        paragraphs.append({
            "heading": _is_heading(block), "text": text,
            "anchor": block.get("id") or block.get("name"),
        })
    if not paragraphs:
        fallback = _clean_text(body.get_text(" ", strip=True))
        if fallback:
            paragraphs.append({"heading": False, "text": fallback})
    return paragraphs


def _document_sections(member: str, navigation: dict, paragraphs: list[dict]) -> list[dict]:
    nav = navigation.get(member) or {}
    starts: list[tuple[int, dict]] = []
    used_indexes: set[int] = set()
    for entry in nav.get("entries") or []:
        fragment = entry.get("fragment")
        if fragment:
            index = next((i for i, row in enumerate(paragraphs) if row.get("anchor") == fragment), None)
            if index is None:
                continue
        else:
            index = 0
        if index in used_indexes:
            continue
        used_indexes.add(index)
        starts.append((index, entry))
    if not starts:
        title, parent = _document_title(member, navigation, paragraphs)
        return [{"title": title, "parentTitle": parent, "rawParagraphs": paragraphs, "hasNavigation": False}]
    starts.sort(key=lambda row: row[0])
    if starts[0][0] > 0:
        starts[0] = (0, starts[0][1])
    sections = []
    for position, (start, entry) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(paragraphs)
        rows = paragraphs[start:end]
        if rows:
            sections.append({
                "title": entry.get("label"), "parentTitle": entry.get("parentLabel"),
                "rawParagraphs": rows, "hasNavigation": True,
            })
    return sections


def _split_family(member: str) -> str | None:
    path = PurePosixPath(member)
    match = re.match(r"(.+?)[_-]split[_-]?(\d+)$", path.stem, re.I)
    return str(path.parent / match.group(1)).casefold() if match else None


def _document_title(member: str, navigation: dict, paragraphs: list[dict]) -> tuple[str, str | None]:
    nav = navigation.get(member) or {}
    label = _useful_label(nav.get("label"))
    parent = _useful_label(nav.get("parentLabel"))
    heading = next((_useful_label(row["text"]) for row in paragraphs if row["heading"]), None)
    first = _useful_label(paragraphs[0]["text"]) if paragraphs and len(normalize_text(paragraphs[0]["text"]).split()) <= 12 else None
    return label or parent or heading or first or PurePosixPath(member).stem.replace("_", " ").replace("-", " ").strip().title(), parent


def _same_title(left: str | None, right: str | None) -> bool:
    return bool(left and right and normalize_text(left) == normalize_text(right))


def extract_epub(source: Path, output_dir: Path) -> dict:
    try:
        archive = zipfile.ZipFile(source)
    except (OSError, zipfile.BadZipFile) as exc:
        raise EpubError("The selected file is not a valid EPUB archive") from exc
    with archive:
        expanded_size = sum(item.file_size for item in archive.infolist())
        if expanded_size > 1024 * 1024 * 1024:
            raise EpubError("EPUB expands beyond the 1 GB safety limit")
        names = set(archive.namelist())
        if "META-INF/container.xml" not in names:
            raise EpubError("EPUB container.xml is missing")
        try:
            container = ElementTree.fromstring(archive.read("META-INF/container.xml"))
            rootfile = next(
                node.attrib["full-path"] for node in container.iter()
                if _local_name(node.tag) == "rootfile" and node.attrib.get("full-path")
            )
            rootfile = _safe_member(rootfile)
            package = ElementTree.fromstring(archive.read(rootfile))
        except (KeyError, StopIteration, ElementTree.ParseError) as exc:
            raise EpubError("EPUB package metadata is malformed") from exc

        metadata = next((node for node in package if _local_name(node.tag) == "metadata"), None)
        title = "Unknown title"
        author = "Unknown author"
        language = ""
        cover_id = None
        if metadata is not None:
            for node in metadata.iter():
                name = _local_name(node.tag)
                value = " ".join((node.text or "").split())
                if name == "title" and value and title == "Unknown title":
                    title = value
                elif name == "creator" and value and author == "Unknown author":
                    author = value
                elif name == "language" and value and not language:
                    language = value
                elif name == "meta" and node.attrib.get("name") == "cover":
                    cover_id = node.attrib.get("content")

        manifest: dict[str, dict] = {}
        for node in package.iter():
            if _local_name(node.tag) != "item" or not node.attrib.get("id"):
                continue
            manifest[node.attrib["id"]] = dict(node.attrib)
        spine_ids = [
            node.attrib.get("idref") for node in package.iter()
            if _local_name(node.tag) == "itemref" and node.attrib.get("idref")
        ]
        navigation = _navigation_map(archive, manifest, rootfile, names)

        cover_item = manifest.get(cover_id or "")
        if not cover_item:
            cover_item = next(
                (item for item in manifest.values() if "cover-image" in item.get("properties", "").split()),
                None,
            )
        cover_file = None
        if cover_item and cover_item.get("href"):
            member = _joined(rootfile, cover_item["href"])
            if member in names:
                mime = cover_item.get("media-type") or mimetypes.guess_type(member)[0] or "image/jpeg"
                extension = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}.get(mime)
                if extension:
                    cover_file = f"cover{extension}"
                    output_dir.mkdir(parents=True, exist_ok=True)
                    (output_dir / cover_file).write_bytes(archive.read(member))

        raw_documents: list[dict] = []
        for item_id in spine_ids:
            item = manifest.get(item_id) or {}
            if item.get("media-type") not in {"application/xhtml+xml", "text/html"}:
                continue
            properties = item.get("properties", "").split()
            lowered_href = str(item.get("href") or "").casefold()
            if "nav" in properties or item_id.casefold() in {"cover", "toc", "nav", "navdoc"} or "next-reads" in lowered_href:
                continue
            member = _joined(rootfile, item.get("href", ""))
            if member not in names:
                continue
            if archive.getinfo(member).file_size > 64 * 1024 * 1024:
                raise EpubError("An EPUB content document exceeds the 64 MB safety limit")
            soup = BeautifulSoup(archive.read(member), "html.parser")
            for unwanted in soup.select("script, style, nav, noscript, [hidden], [aria-hidden='true']"):
                unwanted.decompose()
            raw_paragraphs = _content_blocks(soup)
            if not raw_paragraphs:
                continue
            for section in _document_sections(member, navigation, raw_paragraphs):
                word_count = sum(len(normalize_text(row["text"]).split()) for row in section["rawParagraphs"])
                raw_documents.append({
                    **section, "sourceHrefs": [member], "wordCount": word_count,
                    "splitFamily": _split_family(member),
                })

        # Calibre may split one logical chapter into *_split_000 and
        # *_split_001 files while listing only the first part in the TOC.
        continued_documents: list[dict] = []
        for document in raw_documents:
            previous = continued_documents[-1] if continued_documents else None
            if (
                previous and document.get("splitFamily")
                and document.get("splitFamily") == previous.get("splitFamily")
                and not document.get("hasNavigation")
            ):
                previous["sourceHrefs"].extend(document["sourceHrefs"])
                previous["rawParagraphs"].extend(document["rawParagraphs"])
                previous["wordCount"] += document["wordCount"]
            else:
                continued_documents.append(document)

        documents: list[dict] = []
        pending_short: dict | None = None
        for document in continued_documents:
            if document["wordCount"] < 8:
                if pending_short:
                    documents.append(pending_short)
                pending_short = document
                continue
            if pending_short:
                if _same_title(pending_short["title"], document["title"]) or _same_title(pending_short["title"], document.get("parentTitle")):
                    document["title"] = pending_short["title"]
                    document["sourceHrefs"] = pending_short["sourceHrefs"] + document["sourceHrefs"]
                    document["rawParagraphs"] = pending_short["rawParagraphs"] + document["rawParagraphs"]
                    document["wordCount"] += pending_short["wordCount"]
                else:
                    documents.append(pending_short)
                pending_short = None
            documents.append(document)
        if pending_short:
            documents.append(pending_short)

        chapters: list[dict] = []
        all_sentences: list[dict] = []
        for document in documents:
            chapter_id = f"ch{len(chapters) + 1:02d}"
            paragraphs = []
            for raw in document["rawParagraphs"]:
                originals = split_sentences(raw["text"])
                if not originals:
                    continue
                paragraph_id = f"{chapter_id}-p{len(paragraphs) + 1:03d}"
                rows = []
                for sentence_index, original in enumerate(originals, 1):
                    sentence_id = f"{paragraph_id}-s{sentence_index:03d}"
                    row = {
                        "id": sentence_id, "text": original, "originalText": original,
                        "normalizedText": normalize_text(original), "heading": raw["heading"],
                    }
                    rows.append(row)
                    all_sentences.append({**row, "chapterId": chapter_id})
                paragraphs.append({"id": paragraph_id, "heading": raw["heading"], "sentences": rows})
            if paragraphs:
                chapters.append({
                    "id": chapter_id, "title": document["title"],
                    "sourceHref": document["sourceHrefs"][0],
                    "sourceHrefs": document["sourceHrefs"], "paragraphs": paragraphs,
                })
        if not chapters or not all_sentences:
            raise EpubError("No readable prose was found in the EPUB")

    payload = {
        "extractionVersion": 4,
        "title": title,
        "author": author,
        "language": language,
        "coverFile": cover_file,
        "chapters": chapters,
    }
    _write_extracted_book(payload, output_dir)
    return payload


def _write_extracted_book(book: dict, output_dir: Path) -> None:
    all_sentences = [
        {**sentence, "chapterId": chapter["id"]}
        for chapter in book.get("chapters", [])
        for paragraph in chapter.get("paragraphs", [])
        for sentence in paragraph.get("sentences", [])
    ]
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "book.json").write_text(json.dumps(book, ensure_ascii=False), encoding="utf-8")
    (output_dir / "sentences.json").write_text(
        json.dumps({"sentences": all_sentences}, ensure_ascii=False), encoding="utf-8"
    )


@lru_cache(maxsize=32768)
def _word_key(value: str) -> str:
    return "".join(character for character in normalize_text(value) if character.isalnum())


@lru_cache(maxsize=32768)
def _polish_frequency(value: str) -> float:
    return float(zipf_frequency(value, "pl")) if zipf_frequency else 0.0


def _dictionary_key(value: str) -> str:
    return "".join(
        character for character in unicodedata.normalize("NFKC", str(value or "")).casefold()
        if character.isalnum()
    )


POLISH_FUNCTION_WORDS = {"do", "od", "po", "na", "za", "we", "ze", "w", "z", "i", "o", "u", "a"}


def _starts_with_separate_function_word(component_keys: list[str], full_frequency: float) -> bool:
    if len(component_keys) < 2 or component_keys[0] not in POLISH_FUNCTION_WORDS:
        return False
    if len(component_keys[0]) == 1:
        return len(component_keys[1]) > 1
    remainder_frequency = _polish_frequency("".join(component_keys[1:]))
    return remainder_frequency >= 1.5 and remainder_frequency >= full_frequency - 0.2


def _repair_glued_boundaries(value: str) -> tuple[str, int]:
    """Restore a missing space after a one-letter Polish conjunction/preposition."""
    repaired, changes = re.subn(
        r"(?<!\w)([aiouwz])(?=[A-ZĄĆĘŁŃÓŚŹŻ])",
        r"\1 ",
        str(value or ""),
    )
    prefixes = ("przed", "przez", "bez", "nad", "pod", "dla", "do", "od", "po", "na", "za", "we", "ze", "w", "z", "i", "o", "u", "a")

    def split_known_preposition(match: re.Match) -> str:
        nonlocal changes
        word = match.group(0)
        key = _dictionary_key(word)
        if _polish_frequency(key) >= 1.0:
            return word
        for prefix in prefixes:
            if not key.startswith(prefix) or len(key) - len(prefix) < 3:
                continue
            remainder = word[len(prefix):]
            if _polish_frequency(_dictionary_key(remainder)) >= 3.0:
                changes += 1
                return f"{word[:len(prefix)]} {remainder}"
        return word

    repaired = re.sub(r"(?<!\w)[A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż]{4,}(?!\w)", split_known_preposition, repaired)

    def split_two_known_words(match: re.Match) -> str:
        nonlocal changes
        word = match.group(0)
        if _polish_frequency(_dictionary_key(word)) >= 1.0:
            return word
        best: tuple[float, int] | None = None
        for position in range(2, len(word) - 1):
            left_frequency = _polish_frequency(_dictionary_key(word[:position]))
            right_frequency = _polish_frequency(_dictionary_key(word[position:]))
            if min(left_frequency, right_frequency) < 3.5:
                continue
            score = left_frequency + right_frequency
            if best is None or score > best[0]:
                best = (score, position)
        if best is None:
            return word
        changes += 1
        position = best[1]
        return f"{word[:position]} {word[position:]}"

    repaired = re.sub(r"(?<!\w)[A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż]{5,}(?!\w)", split_two_known_words, repaired)
    return repaired, changes


def _repair_dictionary_spacing(value: str) -> tuple[str, int]:
    if not zipf_frequency:
        return value, 0
    tokens = str(value or "").split()
    if len(tokens) < 2:
        return value, 0
    output = []
    changes = 0
    index = 0
    while index < len(tokens):
        size = 1
        maximum = min(8, len(tokens) - index)
        for candidate_size in range(maximum, 1, -1):
            group = tokens[index:index + candidate_size]
            if any(re.search(r"[.!?,;:][\"'”’»)]*$", token) for token in group[:-1]):
                continue
            component_keys = [_dictionary_key(token) for token in group]
            if not all(component_keys):
                continue
            key = "".join(component_keys)
            component_frequencies = [_polish_frequency(component) for component in component_keys]
            frequency = _polish_frequency(key)
            all_components_are_words = all(value >= 4.0 for value in component_frequencies)
            starts_with_function_word = _starts_with_separate_function_word(component_keys, frequency)
            likely_broken_pair = candidate_size == 2 and (
                component_keys[1] in {"cie", "scie", "jąc", "jac", "nia", "bym", "bys", "by"}
                or component_keys[1].startswith("nastolet")
                or (len(component_keys[0]) >= 4 and group[0][:1].isupper() and not group[1][:1].isupper())
            )
            long_fragmented_word = (
                candidate_size >= 3
                and len(key) >= 7
                and frequency >= 1.0
                and (sum(len(component) <= 3 for component in component_keys) >= 2 or max(map(len, component_keys)) <= 5)
            )
            inflected_fragment = (
                candidate_size >= 2
                and len(key) >= 7
                and len(component_keys[0]) <= 4
                and all(len(component) <= 7 for component in component_keys[1:])
                and all(token[:1].islower() for token in group[1:])
                and not starts_with_function_word
                and (
                    min(component_frequencies, default=0) < 2.0
                    or (candidate_size >= 4 and all(len(component) <= 3 for component in component_keys))
                )
                and key.endswith((
                    "skiego", "skiej", "skich", "skim", "ckiego", "ckiej", "ckim",
                    "towi", "owej", "owych", "owaniu", "ywania", "wania", "aniu", "eniu",
                    "jącej", "jacej", "jących", "jacych", "jący", "jacy",
                ))
            )
            previous_token = re.sub(r"^[^\w]+|[^\w]+$", "", tokens[index - 1]) if index > 0 else ""
            fragmented_proper_name = (
                index > 0
                and 2 <= len(component_keys[0]) <= 4
                and 6 <= len(key) <= 18
                and candidate_size <= 3
                and group[0].isalpha()
                and group[0][:1].isupper()
                and group[0][1:].islower()
                and all(token[:1].islower() and len(component) >= 2 for token, component in zip(group[1:], component_keys[1:]))
                and all(len(component) <= 4 for component in component_keys)
                and previous_token.istitle()
                and component_frequencies[0] < 2.0
                and not re.search(r"[.!?…][\"'”’»)]*$", tokens[index - 1])
            )
            if not starts_with_function_word and (not all_components_are_words or frequency >= 3.0) and (long_fragmented_word or inflected_fragment or fragmented_proper_name or (
                frequency >= 1.3
                and (
                    min(component_frequencies, default=0) < 1.0
                    or frequency >= min(component_frequencies, default=0) + 0.5
                    or likely_broken_pair
                )
            )):
                size = candidate_size
                break
        if size == 1:
            # Extremely rare inflections and proper names can be absent from
            # both corpora. Join only a long run of short PDF syllables.
            for candidate_size in range(maximum, 3, -1):
                group = tokens[index:index + candidate_size]
                keys = [_dictionary_key(token) for token in group]
                frequencies = [_polish_frequency(key) for key in keys]
                if (
                    all(2 <= len(key) <= 4 for key in keys)
                    and sum(frequency == 0 for frequency in frequencies) >= 1
                    and sum(frequencies) / len(frequencies) < 4.0
                    and len("".join(keys)) >= 10
                    and not any(re.search(r"[.!?,;:][\"'”’»)]*$", token) for token in group[:-1])
                ):
                    size = candidate_size
                    break
        output.append("".join(tokens[index:index + size]) if size > 1 else tokens[index])
        changes += size - 1
        index += size
    return " ".join(output), changes


def _repair_word_spacing(
    value: str,
    vocabulary: Counter,
    bigrams: Counter,
) -> tuple[str, int]:
    value, boundary_changes = _repair_glued_boundaries(value)
    tokens = str(value or "").split()

    def recognized(group: list[str]) -> str | None:
        keys = [_word_key(token) for token in group]
        if not all(keys):
            return None
        candidate = "".join(keys)
        if len(group) == 1 and candidate in vocabulary:
            return candidate
        if len(candidate) < 4:
            return None
        dictionary_keys = [_dictionary_key(token) for token in group]
        dictionary_candidate = "".join(dictionary_keys)
        dictionary_frequency = _polish_frequency(dictionary_candidate)
        component_frequencies = [_polish_frequency(key) for key in dictionary_keys]
        has_single_letter_fragment = any(len(key) == 1 for key in dictionary_keys)
        credible_fragment = (
            dictionary_frequency >= 1.0
            or (not has_single_letter_fragment and min(component_frequencies, default=0) < 1.3)
        ) and not _starts_with_separate_function_word(dictionary_keys, dictionary_frequency)
        if candidate in vocabulary and credible_fragment:
            return candidate
        if "-" in group[0]:
            tail = _word_key(group[0].rsplit("-", 1)[-1]) + "".join(keys[1:])
            if tail in vocabulary:
                return tail
        if len(candidate) >= 7 and credible_fragment:
            # Whisper occasionally omits one initial or final consonant.
            for position in (0, len(candidate) - 1):
                if (position == 0 and len(keys[0]) == 1) or (position == len(candidate) - 1 and len(keys[-1]) == 1):
                    continue
                near = candidate[:position] + candidate[position + 1:]
                if near in vocabulary:
                    return near
        return None

    output: list[str] = []
    changes = 0
    index = 0
    while index < len(tokens):
        selected = 1
        for size in range(min(6, len(tokens) - index), 1, -1):
            group = tokens[index:index + size]
            if any(re.search(r"[.!?,;:][\"'”’»)]*$", token) for token in group[:-1]):
                continue
            combined = recognized(group)
            if not combined:
                continue
            partition_strength = 0
            for boundary in range(1, size):
                left = recognized(group[:boundary])
                right = recognized(group[boundary:])
                if left and right:
                    partition_strength = max(partition_strength, bigrams.get((left, right), 0))
            if partition_strength >= vocabulary.get(combined, 0):
                continue
            selected = size
            break
        if selected > 1:
            output.append("".join(tokens[index:index + selected]))
            changes += selected - 1
        else:
            output.append(tokens[index])
        index += selected
    repaired = " ".join(output)
    repaired = re.sub(r"([„«(\[])\s+", r"\1", repaired)
    repaired = re.sub(r"\s+([,.;:!?…”)\]»])", r"\1", repaired)
    repaired, dictionary_changes = _repair_dictionary_spacing(repaired)
    return repaired, boundary_changes + changes + dictionary_changes


def repair_fragmented_words(book: dict, transcript: dict, output_dir: Path) -> dict:
    """Repair PDF-style syllable spacing using words confirmed by the audiobook transcript."""
    if int(book.get("wordRepairVersion") or 0) >= 3:
        return book
    language = str(book.get("language") or transcript.get("language") or "").casefold().split("-", 1)[0]
    if language not in {"pl", "pol"}:
        return book
    transcript_words = [
        word
        for segment in transcript.get("segments", [])
        for word in normalize_text(segment.get("text", "")).split()
    ]
    vocabulary = Counter(transcript_words)
    bigrams = Counter(zip(transcript_words, transcript_words[1:]))
    if not vocabulary:
        return book
    changes = 0
    for chapter in book.get("chapters", []):
        chapter["title"], count = _repair_word_spacing(chapter.get("title", ""), vocabulary, bigrams)
        changes += count
        for paragraph in chapter.get("paragraphs", []):
            for sentence in paragraph.get("sentences", []):
                original, count = _repair_word_spacing(
                    sentence.get("originalText") or sentence.get("text", ""), vocabulary, bigrams,
                )
                sentence["text"] = original
                sentence["originalText"] = original
                sentence["normalizedText"] = normalize_text(original)
                changes += count
    book["wordRepairVersion"] = 3
    book["wordRepairChanges"] = changes
    _write_extracted_book(book, output_dir)
    return book
