"""Monotonic fuzzy sentence and chapter alignment for Synchrobook V1."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import defaultdict
from difflib import SequenceMatcher
import re

from .text import normalize_text


def similarity(left: str, right: str) -> float:
    a = normalize_text(left)
    b = normalize_text(right)
    if not a or not b:
        return 0.0
    sequence = SequenceMatcher(None, a, b, autojunk=False).ratio()
    a_tokens, b_tokens = set(a.split()), set(b.split())
    overlap = len(a_tokens & b_tokens) / max(1, len(a_tokens | b_tokens))
    containment = len(a_tokens & b_tokens) / max(1, min(len(a_tokens), len(b_tokens)))
    return min(1.0, 0.52 * sequence + 0.28 * overlap + 0.20 * containment)


def _token_similarity(left: list[str], right: list[str]) -> float:
    if not left or not right:
        return 0.0
    sequence = SequenceMatcher(None, left, right, autojunk=False).ratio()
    left_set, right_set = set(left), set(right)
    overlap = len(left_set & right_set) / max(1, len(left_set | right_set))
    containment = len(left_set & right_set) / max(1, min(len(left_set), len(right_set)))
    return min(1.0, 0.52 * sequence + 0.28 * overlap + 0.20 * containment)


def _generic_audio_chapter_title(value: str) -> bool:
    normalized = normalize_text(value)
    return bool(re.fullmatch(r"(?:(?:chapter|track|part)\s*)?\d+", normalized))


def _generic_audio_track_set(audio_chapters: list[dict]) -> bool:
    """Detect numbered file parts that are not semantic book chapters."""
    if not audio_chapters:
        return False
    if all(_generic_audio_chapter_title(row.get("title", "")) for row in audio_chapters):
        return True
    numbered_titles = [
        re.fullmatch(r"(.+?)\s+(\d+)", normalize_text(row.get("title", "")))
        for row in audio_chapters
    ]
    if not all(numbered_titles):
        return False
    prefixes = {match.group(1) for match in numbered_titles}
    numbers = [int(match.group(2)) for match in numbered_titles]
    return len(prefixes) == 1 and numbers == list(range(numbers[0], numbers[0] + len(numbers)))


def _explicit_chapter_number(value: str) -> int | None:
    normalized = normalize_text(value)
    matches = re.findall(r"\bchapter\s+(\d+)\b", normalized)
    return int(matches[-1]) if matches else None


def _epub_chapter_number(value: str) -> int | None:
    normalized = normalize_text(value)
    match = re.fullmatch(r"(?:chapter\s+)?(\d+)", normalized)
    return int(match.group(1)) if match else None


def _structural_section_title(value: str) -> bool:
    return bool(re.match(r"^(?:part|book)\s+", normalize_text(value)))


def _likely_supplementary_chapter(
    title: str, sentence_count: int, percentage: float, chapter_text: str = "",
) -> bool:
    normalized = normalize_text(title)
    normalized_text = normalize_text(chapter_text)
    if "project gutenberg" in normalized_text:
        return True
    if percentage >= 50:
        return False
    prefixes = (
        "about the author", "also by", "bibliography", "contents", "copyright",
        "further reading", "index", "introduction", "notes", "preface", "title",
        "the full project gutenberg",
        "translator s note", "acknowledg", "karta redakcyjna", "karta tytułowa",
        "okładka", "spis tresci",
    )
    return any(normalized.startswith(prefix) for prefix in prefixes)


def match_chapters(epub_chapters: list[dict], audio_chapters: list[dict]) -> list[dict]:
    """Order-preserving title matching that permits extra chapters on either side."""
    if _generic_audio_track_set(audio_chapters):
        return [
            {"epubChapterId": epub.get("id"), "audioChapterIndex": None, "confidence": 0.0}
            for epub in epub_chapters
        ]
    matches = []
    cursor = 0
    for epub in epub_chapters:
        best = None
        epub_title = epub.get("title", "")
        epub_normalized = normalize_text(epub_title)
        epub_number = _epub_chapter_number(epub_title)
        for index in range(cursor, len(audio_chapters)):
            audio = audio_chapters[index]
            if _generic_audio_chapter_title(audio.get("title", "")):
                continue
            audio_title = audio.get("title", "")
            audio_normalized = normalize_text(audio_title)
            audio_number = _explicit_chapter_number(audio_title)
            if epub_number is not None and audio_number == epub_number:
                score = 1.0
            elif _structural_section_title(epub_title) and audio_normalized != epub_normalized:
                # A marker such as "Part 1: Holston" is a container, not the
                # first spoken chapter "Part 1: Holston: Chapter 1".
                continue
            else:
                score = similarity(epub_title, audio_title)
            if best is None or score > best[0]:
                best = (score, index, audio)
            if score >= 0.94:
                break
        if best and best[0] >= 0.42:
            score, index, audio = best
            cursor = index + 1
            matches.append({
                "epubChapterId": epub.get("id"),
                "audioChapterIndex": index,
                "audioTitle": audio.get("title"),
                "start": audio.get("start"),
                "end": audio.get("end"),
                "confidence": round(score, 4),
            })
        else:
            matches.append({"epubChapterId": epub.get("id"), "audioChapterIndex": None, "confidence": 0.0})
    return matches


def _chapter_mapping_is_usable(
    chapter_mapping: list[dict], epub_chapters: list[dict], audio_chapters: list[dict],
) -> bool:
    """Reject sparse title matches caused by different chapter granularity."""
    matched = sum(row.get("audioChapterIndex") is not None for row in chapter_mapping)
    if not matched or not epub_chapters or not audio_chapters:
        return False
    epub_coverage = matched / len(epub_chapters)
    audio_coverage = matched / len(audio_chapters)
    return audio_coverage >= 0.80 or (epub_coverage >= 0.40 and audio_coverage >= 0.40)


_NON_CONTENT_MARKERS = {
    "after", "and", "ax", "axiom", "before", "by", "cf", "coroll", "d",
    "def", "deff", "e", "note", "of", "post", "proof", "prop", "q", "see",
    "the", "to",
}


def _alignment_content_sentence(row: dict) -> bool:
    """Return false for citation/structure fragments created by EPUB splitting."""
    words = normalize_text(row.get("originalText") or row.get("text", "")).split()
    if not words:
        return False
    return not all(
        word in _NON_CONTENT_MARKERS
        or word.isdigit()
        or bool(re.fullmatch(r"[ivxlcdm]+", word))
        for word in words
    )


def _timed_tokens(segments: list[dict]) -> list[dict]:
    tokens = []
    for segment_index, segment in enumerate(segments):
        words = normalize_text(segment.get("text", "")).split()
        if not words:
            continue
        start = max(0.0, float(segment.get("start") or 0.0))
        end = max(start, float(segment.get("end") or start))
        step = (end - start) / max(1, len(words))
        for word_index, word in enumerate(words):
            tokens.append({
                "text": word,
                "start": start + step * word_index,
                "end": start + step * (word_index + 1),
                "segment": segment_index,
            })
    return tokens


def align_sentences(sentences: list[dict], transcript_segments: list[dict], progress_callback=None) -> list[dict]:
    """Align in one direction only, using local fuzzy windows and anchor words.

    Unmatched EPUB sentences do not advance the transcript cursor, so omissions and
    footnotes cannot derail later sentences. Candidate windows never begin before
    the cursor, preventing repeated phrases from jumping backwards.
    """
    transcript = _timed_tokens(transcript_segments)
    positions: dict[str, list[int]] = defaultdict(list)
    for index, token in enumerate(transcript):
        positions[token["text"]].append(index)
    output = []
    cursor = 0
    max_forward = 5000
    total_sentences = len(sentences)
    for sentence_index, sentence in enumerate(sentences):
        if progress_callback and (sentence_index == 0 or sentence_index % 50 == 0):
            progress_callback(sentence_index, total_sentences)
        words = normalize_text(sentence.get("originalText") or sentence.get("text", "")).split()
        result = {"id": sentence.get("id"), "text": sentence.get("originalText") or sentence.get("text", "")}
        if not words or not transcript:
            output.append({**result, "start": None, "end": None, "confidence": 0.0})
            continue
        limit = min(len(transcript), cursor + max_forward)
        discriminators = sorted(set(words), key=lambda word: (len(positions.get(word, [])), -len(word)))
        candidate_starts = {cursor}
        selected_anchors = 0
        for word in discriminators:
            if len(word) < 3:
                continue
            word_positions = positions.get(word, [])
            left = bisect_left(word_positions, cursor)
            right = bisect_right(word_positions, limit - 1)
            local_positions = word_positions[left:right]
            if not local_positions or len(local_positions) > 30:
                continue
            target_offsets = [index for index, token in enumerate(words) if token == word][:3]
            for position in local_positions:
                for offset in target_offsets:
                    candidate_starts.add(max(cursor, position - offset))
            selected_anchors += 1
            if selected_anchors >= 3 or len(candidate_starts) >= 100:
                break
        # The immediate local window keeps alignment moving when an edition
        # difference removes all useful anchor words from one sentence.
        local_end = min(limit, cursor + max(24, len(words) * 2))
        candidate_starts.update(range(cursor, local_end, max(1, len(words) // 2)))
        if len(candidate_starts) > 100:
            candidate_starts = set(sorted(candidate_starts, key=lambda value: (value - cursor, value))[:100])
        best = (0.0, 0.0, cursor, cursor)
        lengths = sorted({max(1, round(len(words) * ratio)) for ratio in (0.76, 1.0, 1.28)})
        for start in sorted(candidate_starts):
            if start >= limit:
                continue
            distance = max(0, start - cursor)
            if distance > 600 or (len(words) <= 8 and distance > 40):
                continue
            distance_penalty = min(0.10, max(0, start - cursor) / max_forward * 0.10)
            for length in lengths:
                end = min(len(transcript), start + length)
                candidate = [token["text"] for token in transcript[start:end]]
                raw_score = _token_similarity(words, candidate)
                if distance > max(160, len(words) * 8) and raw_score < 0.78:
                    continue
                score = raw_score - distance_penalty
                if score > best[0]:
                    best = (score, raw_score, start, end)
        score, raw_score, start, end = best
        minimum = 0.55 if len(words) >= 5 else 0.68
        if score < minimum or end <= start:
            output.append({**result, "start": None, "end": None, "confidence": round(max(0.0, raw_score), 4)})
            continue
        confidence = min(0.99, max(0.0, raw_score))
        output.append({
            **result,
            "start": round(transcript[start]["start"], 3),
            "end": round(transcript[end - 1]["end"], 3),
            "confidence": round(confidence, 4),
        })
        cursor = max(cursor, end)
    if progress_callback:
        progress_callback(total_sentences, total_sentences)
    return output


def build_alignment(book_id: str, book: dict, transcript: dict, audio_chapters: list[dict], progress_callback=None) -> tuple[dict, dict]:
    epub_chapters = book.get("chapters", [])
    chapter_mapping = match_chapters(epub_chapters, audio_chapters)
    has_usable_chapter_map = _chapter_mapping_is_usable(
        chapter_mapping, epub_chapters, audio_chapters,
    )
    if not has_usable_chapter_map:
        chapter_mapping = [
            {"epubChapterId": chapter.get("id"), "audioChapterIndex": None, "confidence": 0.0}
            for chapter in epub_chapters
        ]
    mapping_by_id = {row["epubChapterId"]: row for row in chapter_mapping}
    all_epub_sentences = [
        sentence
        for chapter in epub_chapters
        for paragraph in chapter.get("paragraphs", [])
        for sentence in paragraph.get("sentences", [])
    ]
    total_to_process = len(all_epub_sentences)
    processed = 0
    aligned = []
    if has_usable_chapter_map:
        for chapter in epub_chapters:
            chapter_sentences = [
                sentence
                for paragraph in chapter.get("paragraphs", [])
                for sentence in paragraph.get("sentences", [])
            ]
            mapping = mapping_by_id.get(chapter.get("id")) or {}
            audio_index = mapping.get("audioChapterIndex")
            if audio_index is None:
                aligned.extend({
                    "id": sentence.get("id"),
                    "text": sentence.get("originalText") or sentence.get("text", ""),
                    "start": None, "end": None, "confidence": 0.0,
                } for sentence in chapter_sentences)
                processed += len(chapter_sentences)
                if progress_callback:
                    progress_callback(processed, total_to_process)
                continue
            audio_chapter = audio_chapters[audio_index]
            chapter_start = float(audio_chapter.get("start") or 0)
            chapter_end = float(audio_chapter.get("end") or float("inf"))
            local_segments = [
                segment for segment in transcript.get("segments", [])
                if float(segment.get("end") or 0) >= chapter_start
                and float(segment.get("start") or 0) <= chapter_end
            ]

            def local_progress(done: int, _total: int) -> None:
                if progress_callback:
                    progress_callback(processed + done, total_to_process)

            aligned.extend(align_sentences(
                chapter_sentences, local_segments, progress_callback=local_progress,
            ))
            processed += len(chapter_sentences)
    else:
        aligned = align_sentences(
            all_epub_sentences, transcript.get("segments", []), progress_callback=progress_callback,
        )
    lookup = {row["id"]: row for row in aligned}
    alignment_chapters = []
    report_chapters = []
    total_aligned = 0
    total_sentences = 0
    eligible_sentences = 0
    eligible_aligned = 0
    confidence_sum = 0.0
    for chapter in book.get("chapters", []):
        rows = [
            lookup[sentence["id"]]
            for paragraph in chapter.get("paragraphs", [])
            for sentence in paragraph.get("sentences", [])
        ]
        matched = [row for row in rows if row.get("start") is not None]
        content_rows = [row for row in rows if _alignment_content_sentence(row)]
        content_matched = [row for row in content_rows if row.get("start") is not None]
        average = (
            sum(row["confidence"] for row in content_matched) / len(content_matched)
            if content_matched else 0.0
        )
        percentage = 100 * len(content_matched) / len(content_rows) if content_rows else 0.0
        mapping = mapping_by_id.get(chapter.get("id")) or {}
        chapter_text = " ".join(row.get("text", "") for row in rows)
        in_audiobook = (
            mapping.get("audioChapterIndex") is not None
            if has_usable_chapter_map
            else not _likely_supplementary_chapter(
                chapter.get("title", ""), len(rows), percentage, chapter_text,
            )
        )
        if not in_audiobook:
            quality = "NOT_IN_AUDIO"
        elif percentage >= 97 and average >= 0.85:
            quality = "EXCELLENT"
        elif percentage >= 85 and average >= 0.72:
            quality = "GOOD"
        elif percentage >= 60:
            quality = "WARNING"
        else:
            quality = "PROBLEMATIC"
        alignment_chapters.append({"id": chapter["id"], "title": chapter["title"], "sentences": rows})
        report_chapters.append({
            "id": chapter["id"], "title": chapter["title"], "epubSentences": len(rows),
            "eligibleSentences": len(content_rows),
            "alignedSentences": len(matched), "unmatchedSentences": len(rows) - len(matched),
            "percentageAligned": round(percentage, 2), "averageConfidence": round(average, 4),
            "lowConfidenceMatches": sum(row["confidence"] < 0.60 for row in content_matched),
            "inAudiobook": in_audiobook, "audioChapterIndex": mapping.get("audioChapterIndex"),
            "quality": quality,
        })
        total_sentences += len(rows)
        total_aligned += len(matched)
        if in_audiobook:
            eligible_sentences += len(content_rows)
            eligible_aligned += len(content_matched)
            confidence_sum += sum(row["confidence"] for row in content_matched)
    alignment = {"bookId": book_id, "version": 1, "unit": "sentence", "chapters": alignment_chapters}
    report = {
        "bookId": book_id,
        "summary": {
            "epubSentences": total_sentences, "alignedSentences": total_aligned,
            "unmatchedSentences": total_sentences - total_aligned,
            "eligibleSentences": eligible_sentences,
            "percentageAligned": round(100 * eligible_aligned / eligible_sentences, 2) if eligible_sentences else 0.0,
            "averageConfidence": round(confidence_sum / eligible_aligned, 4) if eligible_aligned else 0.0,
        },
        "chapters": report_chapters,
        "chapterMapping": chapter_mapping,
    }
    return alignment, report
