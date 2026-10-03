"""Streaming Tatoeba Bokmal sentence import and exact Ordbank-form mapping."""

from __future__ import annotations

import bz2
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import unicodedata
from typing import Any, Iterable, Iterator

from .models import ReferenceSourceRecord, deterministic_id, normalize_reference_lookup
from .store import ReferenceStore, canonical_json, utc_now


TATOEBA_IMPORTER_ID = "tatoeba-nob-sentences"
TATOEBA_IMPORTER_VERSION = "1.0.0"
TATOEBA_TRANSLATION_IMPORTER_ID = "tatoeba-nob-eng-translations"
TATOEBA_TRANSLATION_IMPORTER_VERSION = "1.0.0"
SENTENCE_MAPPING_VERSION = "language.reference-sentence-mapping/v1"
SENTENCE_QUALITY_VERSION = "language.cloze-sentence-quality/v1"
ORDBANK_SOURCE_ID = "nb-norsk-ordbank-nob-2022-02-01"
TOKEN_RE = re.compile(r"[^\W\d_]+(?:[-'’][^\W\d_]+)*", re.UNICODE)
URL_RE = re.compile(r"(?:https?://|www\.)", re.IGNORECASE)


@dataclass(frozen=True)
class TatoebaArtifact:
    source_id: str
    title: str
    version: str
    path: Path
    download_url: str
    landing_url: str
    license_id: str
    license_url: str
    attribution: str
    retrieved_at: str
    http_metadata: dict[str, str]


@dataclass(frozen=True)
class TatoebaTranslationArtifacts:
    source_id: str
    title: str
    version: str
    links_path: Path
    english_sentences_path: Path
    links_url: str
    english_sentences_url: str
    landing_url: str
    license_id: str
    license_url: str
    attribution: str
    retrieved_at: str
    artifacts_metadata: dict[str, dict[str, str]]


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_tatoeba_rows(path: str | Path) -> Iterator[tuple[str, str, str]]:
    with bz2.open(path, "rt", encoding="utf-8", newline="") as handle:
        for line_number, line in enumerate(handle, start=1):
            parts = line.rstrip("\r\n").split("\t", 2)
            if len(parts) != 3 or not parts[0].strip() or not parts[1].strip():
                yield f"INVALID:{line_number}", "", ""
                continue
            yield parts[0].strip(), parts[1].strip(), unicodedata.normalize("NFC", parts[2])


def iter_tatoeba_links(path: str | Path) -> Iterator[tuple[str, str]]:
    with bz2.open(path, "rt", encoding="utf-8", newline="") as handle:
        for line in handle:
            parts = line.rstrip("\r\n").split("\t", 1)
            if len(parts) == 2 and parts[0].strip() and parts[1].strip():
                yield parts[0].strip(), parts[1].strip()


def tokenize_sentence(text: str) -> list[dict[str, Any]]:
    return [
        {
            "surface": match.group(0),
            "normalized": normalize_reference_lookup(match.group(0)),
            "start": match.start(),
            "end": match.end(),
        }
        for match in TOKEN_RE.finditer(text)
    ]


def sentence_quality(text: str, tokens: list[dict[str, Any]], resolution_counts: dict[str, int]) -> dict[str, Any]:
    flags: list[str] = []
    token_count = len(tokens)
    score = 100.0
    if token_count < 5:
        score -= (5 - token_count) * 12
        flags.append("SHORT")
    elif token_count > 18:
        score -= min(45, (token_count - 18) * 3)
        flags.append("LONG")
    if len(text) > 500:
        score -= 80
        flags.append("TOO_LONG")
    if URL_RE.search(text):
        score -= 80
        flags.append("URL")
    if any(unicodedata.category(char) == "Cc" and char not in "\t\r\n" for char in text):
        score -= 80
        flags.append("CONTROL_CHARACTER")
    punctuation = sum(1 for char in text if unicodedata.category(char).startswith("P"))
    if text and punctuation / len(text) > 0.25:
        score -= 35
        flags.append("EXCESSIVE_PUNCTUATION")
    if "<" in text and ">" in text:
        score -= 8
        flags.append("HTML_LIKE_TEXT")
    unresolved = resolution_counts.get("AMBIGUOUS", 0) + resolution_counts.get("UNMATCHED", 0)
    if token_count:
        score -= 35 * unresolved / token_count
    usable = bool(
        3 <= token_count <= 30
        and len(text) <= 500
        and not URL_RE.search(text)
        and "CONTROL_CHARACTER" not in flags
        and "EXCESSIVE_PUNCTUATION" not in flags
    )
    return {"score": round(max(0.0, score), 3), "usable": usable, "flags": flags}


def _chunks(rows: Iterable[tuple[str, str, str]], size: int = 400) -> Iterator[list[tuple[str, str, str]]]:
    batch: list[tuple[str, str, str]] = []
    for row in rows:
        batch.append(row)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def _candidate_map(connection, normalized_forms: set[str]) -> dict[str, list[str]]:
    result: dict[str, set[str]] = {value: set() for value in normalized_forms}
    values = sorted(normalized_forms)
    for offset in range(0, len(values), 500):
        chunk = values[offset:offset + 500]
        placeholders = ",".join("?" for _ in chunk)
        rows = connection.execute(
            "SELECT f.normalized_form,fl.lexical_unit_id FROM reference_forms f "
            "JOIN reference_form_links fl ON fl.form_id=f.id "
            f"WHERE fl.source_id=? AND f.normalized_form IN ({placeholders}) "
            "GROUP BY f.normalized_form,fl.lexical_unit_id",
            (ORDBANK_SOURCE_ID, *chunk),
        ).fetchall()
        for row in rows:
            result.setdefault(str(row[0]), set()).add(str(row[1]))
    return {key: sorted(value) for key, value in result.items()}


def _register_source_and_artifact(store: ReferenceStore, artifact: TatoebaArtifact, sha256: str) -> None:
    size = artifact.path.stat().st_size
    store.register_source(
        ReferenceSourceRecord(
            source_id=artifact.source_id,
            canonical_name=artifact.title,
            provider="Tatoeba Association",
            resource_type="BOKMAL_SENTENCE_EXPORT",
            language_code="nb",
            version=artifact.version,
            landing_url=artifact.landing_url,
            license_id=artifact.license_id,
            license_url=artifact.license_url,
            attribution_text=artifact.attribution,
        ),
        release_date=artifact.http_metadata.get("lastModified"),
        download_url=artifact.download_url,
        expected_filename=artifact.path.name,
        declared_size_bytes=size,
        format="BZip2 TSV: sentence id, ISO 639-3 language, sentence text",
        corpus_description="Norwegian Bokmal sentences from the official Tatoeba weekly export.",
        notes=f"Imported by {TATOEBA_IMPORTER_ID}/{TATOEBA_IMPORTER_VERSION}",
    )
    with store.transaction() as connection:
        connection.execute(
            "INSERT INTO reference_source_artifacts(source_id,filename,download_url,size_bytes,sha256,"
            "required,parser_id,parser_version,retrieved_at,http_metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(source_id,filename) DO UPDATE SET download_url=excluded.download_url,"
            "size_bytes=excluded.size_bytes,sha256=excluded.sha256,retrieved_at=excluded.retrieved_at,"
            "http_metadata_json=excluded.http_metadata_json",
            (
                artifact.source_id, artifact.path.name, artifact.download_url, size, f"sha256:{sha256}", 1,
                TATOEBA_IMPORTER_ID, TATOEBA_IMPORTER_VERSION, artifact.retrieved_at,
                canonical_json(artifact.http_metadata),
            ),
        )


def import_tatoeba_artifact(store: ReferenceStore, artifact: TatoebaArtifact) -> dict[str, Any]:
    """Import one official export. Existing sentence IDs are retained (CC0 is imported first)."""

    sha256 = file_sha256(artifact.path)
    _register_source_and_artifact(store, artifact, sha256)
    run_id = store.begin_import_run(
        artifact.source_id,
        importer_id=TATOEBA_IMPORTER_ID,
        importer_version=TATOEBA_IMPORTER_VERSION,
        source_checksum=f"sha256:{sha256}",
    )
    counters = {
        "rowsRead": 0, "rowsAccepted": 0, "rowsRejected": 0, "duplicates": 0,
        "usableRows": 0, "occurrences": 0, "matched": 0, "ambiguous": 0, "unmatched": 0,
    }
    try:
        for batch in _chunks(iter_tatoeba_rows(artifact.path)):
            parsed: list[dict[str, Any]] = []
            normalized_forms: set[str] = set()
            for source_sentence_id, language, text in batch:
                counters["rowsRead"] += 1
                if source_sentence_id.startswith("INVALID:") or language != "nob" or not text.strip():
                    counters["rowsRejected"] += 1
                    continue
                tokens = tokenize_sentence(text)
                normalized_forms.update(token["normalized"] for token in tokens)
                parsed.append({
                    "sourceSentenceId": source_sentence_id,
                    "text": text,
                    "tokens": tokens,
                })
            with store.transaction() as connection:
                candidates = _candidate_map(connection, normalized_forms)
                for item in parsed:
                    sentence_id = deterministic_id("tatoeba-sentence", item["sourceSentenceId"])
                    existing = connection.execute(
                        "SELECT license_id FROM reference_sentences WHERE id=?", (sentence_id,)
                    ).fetchone()
                    if existing is not None:
                        counters["duplicates"] += 1
                        continue
                    occurrence_rows: list[tuple[Any, ...]] = []
                    resolution_counts = {"MATCHED": 0, "AMBIGUOUS": 0, "UNMATCHED": 0}
                    for occurrence_index, token in enumerate(item["tokens"]):
                        candidate_ids = candidates.get(token["normalized"], [])
                        status = "MATCHED" if len(candidate_ids) == 1 else "AMBIGUOUS" if candidate_ids else "UNMATCHED"
                        resolution_counts[status] += 1
                        occurrence_rows.append((
                            sentence_id, occurrence_index, candidate_ids[0] if status == "MATCHED" else None,
                            token["start"], token["end"], token["surface"], token["normalized"], status,
                            SENTENCE_MAPPING_VERSION, len(candidate_ids), canonical_json(candidate_ids[:64]),
                        ))
                    quality = sentence_quality(item["text"], item["tokens"], resolution_counts)
                    source_url = f"https://tatoeba.org/en/sentences/show/{item['sourceSentenceId']}"
                    connection.execute(
                        "INSERT INTO reference_sentences(id,source_id,import_run_id,source_sentence_id,"
                        "language_code,sentence_text,normalized_text,license_id,source_url,lexical_token_count,"
                        "matched_token_count,ambiguous_token_count,unmatched_token_count,quality_score,usable,"
                        "quality_flags_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            sentence_id, artifact.source_id, run_id, item["sourceSentenceId"], "nb",
                            item["text"], normalize_reference_lookup(item["text"]), artifact.license_id,
                            source_url, len(item["tokens"]), resolution_counts["MATCHED"],
                            resolution_counts["AMBIGUOUS"], resolution_counts["UNMATCHED"],
                            quality["score"], 1 if quality["usable"] else 0,
                            canonical_json(quality["flags"]), utc_now(),
                        ),
                    )
                    connection.executemany(
                        "INSERT INTO reference_sentence_occurrences(sentence_id,occurrence_index,lexical_unit_id,"
                        "start_offset,end_offset,surface_form,normalized_form,resolution_status,resolution_basis,"
                        "candidate_count,candidate_unit_ids_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        occurrence_rows,
                    )
                    counters["rowsAccepted"] += 1
                    counters["usableRows"] += int(quality["usable"])
                    counters["occurrences"] += len(occurrence_rows)
                    for status in resolution_counts:
                        counters[status.casefold()] += resolution_counts[status]
        store.complete_import_run(
            run_id,
            rows_read=counters["rowsRead"],
            rows_accepted=counters["rowsAccepted"],
            rows_rejected=counters["rowsRejected"],
            warnings=[f"duplicate sentence IDs retained from earlier preferred-license import: {counters['duplicates']}"]
            if counters["duplicates"] else [],
        )
    except Exception as exc:
        store.complete_import_run(
            run_id, rows_read=counters["rowsRead"], rows_accepted=counters["rowsAccepted"],
            rows_rejected=counters["rowsRejected"], errors=[f"{type(exc).__name__}: {exc}"],
        )
        raise
    return {
        **counters,
        "sourceId": artifact.source_id,
        "artifact": artifact.path.name,
        "bytes": artifact.path.stat().st_size,
        "sha256": sha256,
        "license": artifact.license_id,
        "importRunId": run_id,
        "mappingVersion": SENTENCE_MAPPING_VERSION,
        "qualityVersion": SENTENCE_QUALITY_VERSION,
    }


def import_tatoeba_translations(
    store: ReferenceStore, artifacts: TatoebaTranslationArtifacts,
) -> dict[str, Any]:
    """Import direct Bokmal-English Tatoeba links without retaining the full English export."""

    links_sha = file_sha256(artifacts.links_path)
    english_sha = file_sha256(artifacts.english_sentences_path)
    store.register_source(
        ReferenceSourceRecord(
            source_id=artifacts.source_id,
            canonical_name=artifacts.title,
            provider="Tatoeba Association",
            resource_type="SENTENCE_TRANSLATION_LINKS",
            language_code="nb-en",
            version=artifacts.version,
            landing_url=artifacts.landing_url,
            license_id=artifacts.license_id,
            license_url=artifacts.license_url,
            attribution_text=artifacts.attribution,
        ),
        download_url=artifacts.links_url,
        expected_filename=artifacts.links_path.name,
        declared_size_bytes=artifacts.links_path.stat().st_size,
        format="BZip2 TSV direct sentence links plus English sentence export",
        corpus_description="Direct Norwegian Bokmal to English sentence translations from Tatoeba.",
        notes=f"Imported by {TATOEBA_TRANSLATION_IMPORTER_ID}/{TATOEBA_TRANSLATION_IMPORTER_VERSION}",
    )
    with store.transaction() as connection:
        for path, url, sha in (
            (artifacts.links_path, artifacts.links_url, links_sha),
            (artifacts.english_sentences_path, artifacts.english_sentences_url, english_sha),
        ):
            connection.execute(
                "INSERT INTO reference_source_artifacts(source_id,filename,download_url,size_bytes,sha256,"
                "required,parser_id,parser_version,retrieved_at,http_metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(source_id,filename) DO UPDATE SET download_url=excluded.download_url,"
                "size_bytes=excluded.size_bytes,sha256=excluded.sha256,retrieved_at=excluded.retrieved_at,"
                "http_metadata_json=excluded.http_metadata_json",
                (
                    artifacts.source_id, path.name, url, path.stat().st_size, f"sha256:{sha}", 1,
                    TATOEBA_TRANSLATION_IMPORTER_ID, TATOEBA_TRANSLATION_IMPORTER_VERSION,
                    artifacts.retrieved_at,
                    canonical_json(artifacts.artifacts_metadata.get(path.name) or {}),
                ),
            )
    run_id = store.begin_import_run(
        artifacts.source_id,
        importer_id=TATOEBA_TRANSLATION_IMPORTER_ID,
        importer_version=TATOEBA_TRANSLATION_IMPORTER_VERSION,
        source_checksum=f"sha256:{links_sha}+sha256:{english_sha}",
    )
    counters = {
        "linksRead": 0, "eligibleLinks": 0, "englishRowsRead": 0,
        "englishRowsMatched": 0, "missingTranslations": 0,
        "translationsCreated": 0, "duplicates": 0,
    }
    try:
        with store._connect() as connection:
            norwegian = {
                str(row[0]): str(row[1])
                for row in connection.execute(
                    "SELECT source_sentence_id,id FROM reference_sentences WHERE language_code='nb'"
                )
            }
        pairs: list[tuple[str, str]] = []
        wanted_english: set[str] = set()
        for norwegian_id, english_id in iter_tatoeba_links(artifacts.links_path):
            counters["linksRead"] += 1
            sentence_id = norwegian.get(norwegian_id)
            if sentence_id is None:
                continue
            counters["eligibleLinks"] += 1
            pairs.append((sentence_id, english_id))
            wanted_english.add(english_id)
        english: dict[str, str] = {}
        for sentence_id, language, text in iter_tatoeba_rows(artifacts.english_sentences_path):
            counters["englishRowsRead"] += 1
            if language == "eng" and sentence_id in wanted_english:
                english[sentence_id] = text
                counters["englishRowsMatched"] += 1
                if len(english) >= len(wanted_english):
                    break
        counters["missingTranslations"] = sum(1 for _, english_id in pairs if english_id not in english)
        created_at = utc_now()
        for offset in range(0, len(pairs), 500):
            with store.transaction() as connection:
                for sentence_id, english_id in pairs[offset:offset + 500]:
                    text = english.get(english_id)
                    if not text:
                        continue
                    cursor = connection.execute(
                        "INSERT OR IGNORE INTO reference_sentence_translations("
                        "sentence_id,target_language_code,translation_sentence_id,translation_text,"
                        "normalized_text,source_id,import_run_id,license_id,source_url,created_at) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (
                            sentence_id, "en", english_id, text, normalize_reference_lookup(text),
                            artifacts.source_id, run_id, artifacts.license_id,
                            f"https://tatoeba.org/en/sentences/show/{english_id}", created_at,
                        ),
                    )
                    if cursor.rowcount:
                        counters["translationsCreated"] += 1
                    else:
                        counters["duplicates"] += 1
        store.complete_import_run(
            run_id,
            rows_read=counters["linksRead"] + counters["englishRowsRead"],
            rows_accepted=counters["translationsCreated"],
            rows_rejected=counters["missingTranslations"],
        )
    except Exception as exc:
        store.complete_import_run(
            run_id, rows_read=counters["linksRead"] + counters["englishRowsRead"],
            rows_accepted=counters["translationsCreated"], rows_rejected=0,
            errors=[f"{type(exc).__name__}: {exc}"],
        )
        raise
    return {
        **counters,
        "sourceId": artifacts.source_id,
        "linksArtifact": artifacts.links_path.name,
        "linksSha256": links_sha,
        "englishArtifact": artifacts.english_sentences_path.name,
        "englishSha256": english_sha,
        "license": artifacts.license_id,
        "importRunId": run_id,
    }


def fast_track_coverage(store: ReferenceStore) -> dict[str, Any]:
    bands = {
        "FAST_TRACK_1": (1, 500), "FAST_TRACK_2": (501, 1000),
        "FAST_TRACK_3": (1001, 2000), "FAST_TRACK_4": (2001, 4000),
        "FAST_TRACK_5": (4001, 6000),
    }
    with store._connect() as connection:  # bounded aggregate over indexed production facts
        mapping_count = int(connection.execute("SELECT COUNT(*) FROM reference_sentence_occurrences").fetchone()[0])
        sentence_count = int(connection.execute("SELECT COUNT(*) FROM reference_sentences").fetchone()[0])
        usable_count = int(connection.execute("SELECT COUNT(*) FROM reference_sentences WHERE usable=1").fetchone()[0])
        unique_units = int(connection.execute(
            "SELECT COUNT(DISTINCT lexical_unit_id) FROM reference_sentence_occurrences "
            "WHERE resolution_status='MATCHED'"
        ).fetchone()[0])
        coverage: dict[str, Any] = {}
        for key, (minimum, maximum) in bands.items():
            row = connection.execute(
                "WITH targets AS (SELECT DISTINCT lexical_unit_id FROM reference_frequency_observations "
                "WHERE metric_type='SOURCE_LEARNER_RANK' AND rank BETWEEN ? AND ?), candidates AS ("
                "SELECT o.lexical_unit_id,o.sentence_id FROM reference_sentence_occurrences o "
                "JOIN reference_sentences s ON s.id=o.sentence_id AND s.usable=1 "
                "WHERE o.resolution_status='MATCHED' GROUP BY o.lexical_unit_id,o.sentence_id "
                "HAVING COUNT(*)=1), counts AS (SELECT lexical_unit_id,COUNT(*) n FROM candidates GROUP BY lexical_unit_id) "
                "SELECT (SELECT COUNT(*) FROM targets),"
                "(SELECT COUNT(*) FROM targets t JOIN counts c ON c.lexical_unit_id=t.lexical_unit_id),"
                "(SELECT COUNT(*) FROM targets t JOIN counts c ON c.lexical_unit_id=t.lexical_unit_id WHERE c.n>=3)",
                (minimum, maximum),
            ).fetchone()
            targets, one, three = map(int, row)
            coverage[key] = {
                "rankMin": minimum, "rankMax": maximum, "targets": targets,
                "withAtLeastOne": one, "withAtLeastThree": three,
                "coveragePercent": round(one * 100 / targets, 2) if targets else 0.0,
            }
    return {
        "trackVersion": "language.cloze-fast-track/v1",
        "sentenceRows": sentence_count,
        "usableRows": usable_count,
        "occurrenceMappings": mapping_count,
        "uniqueReferenceUnitsWithSentences": unique_units,
        "bands": coverage,
    }


__all__ = [
    "SENTENCE_MAPPING_VERSION", "SENTENCE_QUALITY_VERSION", "TATOEBA_IMPORTER_ID",
    "TATOEBA_IMPORTER_VERSION", "TATOEBA_TRANSLATION_IMPORTER_ID",
    "TATOEBA_TRANSLATION_IMPORTER_VERSION", "TatoebaArtifact", "TatoebaTranslationArtifacts",
    "fast_track_coverage", "file_sha256", "import_tatoeba_artifact",
    "import_tatoeba_translations", "iter_tatoeba_links", "iter_tatoeba_rows", "sentence_quality",
    "tokenize_sentence",
]
