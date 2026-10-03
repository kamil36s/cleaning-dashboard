"""Bounded production importers for the authorized Phase 7.5B sources."""

from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import sqlite3
import tarfile
import time
from typing import Any, Callable, Iterable, Iterator
import zipfile

from .artifacts import VerifiedArtifact
from .manifest import SourceManifest
from .models import deterministic_id, make_stable_key, normalize_reference_lookup
from .pos_mapping import (
    KELLY_POS_MAPPING_VERSION,
    ORDBANK_POS_MAPPING_VERSION,
    map_kelly_pos,
    map_ordbank_family,
    ordbank_tag_family,
)
from .schema import REFERENCE_SCHEMA_VERSION
from .store import canonical_json, utc_now


ORDBANK_ID = "nb-norsk-ordbank-nob-2022-02-01"
KELLY_ID = "uio-norwegian-kelly-shu-wang"
CLARINO_ID = "clarino-norsk-aviskorpus-nob-frequency-2025-08-25"
IDIOM_ID = "nb-norwegian-idioms-2024-10-10"
UNIGRAM_ID = "nb-bokmal-ngram-2012"
ORDBANK_EXPECTED_LEMMAS = 154_824
ORDBANK_EXPECTED_FORMS = 1_143_887
CLARINO_EXPECTED_ROWS = 9_999
IDIOM_EXPECTED_FREQUENCY = {"nob": 3455, "nno": 88, "both": 6}
IDIOM_EXPECTED_PROMPTS = 3245
IDIOM_EXPECTED_MULTI_COMPLETION = 156
BATCH_SIZE = 10_000
NONLEXICAL_MARKERS = {"<s>", "</s>"}


def _unit_identity(
    canonical_form: str,
    *,
    unit_type: str,
    pos: str | None,
    qualifier: str | None,
) -> tuple[str, str, str]:
    normalized = normalize_reference_lookup(canonical_form)
    stable_key = make_stable_key(
        language_code="nb",
        unit_type=unit_type,
        normalized_form=normalized,
        part_of_speech=pos,
        identity_qualifier=qualifier,
    )
    return deterministic_id("reference-unit", stable_key), stable_key, normalized


def _form_identity(display_form: str) -> tuple[str, str]:
    normalized = normalize_reference_lookup(display_form)
    return deterministic_id("reference-form", "nb", display_form, normalized), normalized


def _observation_id(source_id: str, metric_type: str, source_local_id: str) -> str:
    return deterministic_id("reference-raw-observation", source_id, metric_type, source_local_id)


def _is_nonlexical(value: str) -> bool:
    stripped = str(value or "").strip()
    return stripped in NONLEXICAL_MARKERS or not any(char.isalpha() for char in stripped)


def _chunked(iterator: Iterable[Any], size: int = BATCH_SIZE) -> Iterator[list[Any]]:
    batch: list[Any] = []
    for item in iterator:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


class ProductionImporter:
    def __init__(
        self,
        connection: sqlite3.Connection,
        manifests: Iterable[SourceManifest],
        artifacts: dict[str, tuple[VerifiedArtifact, ...]],
        *,
        progress: Callable[[str], None] | None = None,
    ) -> None:
        self.connection = connection
        self.manifests = {item.source_id: item for item in manifests}
        self.artifacts = artifacts
        self.progress = progress or (lambda _message: None)
        self.quality: dict[str, dict[str, Any]] = {}

    def _log(self, message: str) -> None:
        self.progress(message)

    def _data_artifact(self, source_id: str, *suffixes: str) -> Path:
        matches = [
            item.path for item in self.artifacts[source_id]
            if item.path.name.lower().endswith(tuple(value.lower() for value in suffixes))
        ]
        if len(matches) != 1:
            raise RuntimeError(f"expected one data artifact for {source_id} and {suffixes}, found {matches}")
        return matches[0]

    def register_sources(self) -> None:
        now = utc_now()
        for source_id, manifest in self.manifests.items():
            payload = manifest.payload
            primary = manifest.required_artifacts[0]
            self.connection.execute(
                "INSERT INTO reference_sources(source_id,canonical_name,provider,resource_type,language_code,"
                "version,release_date,landing_url,license_id,license_url,attribution_text,download_url,"
                "expected_filename,declared_size_bytes,format,corpus_description,notes,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    source_id, payload["title"], payload["provider"], payload["resourceType"], payload["language"],
                    payload["version"], payload.get("releaseDate"), payload["landingUrl"],
                    payload["license"]["id"], payload["license"]["url"], payload.get("attribution"),
                    primary.url, primary.name, primary.size_bytes, primary.format,
                    None, canonical_json(payload.get("notes") or []), now, now,
                ),
            )
            manifest_artifacts = {item.name: item for item in manifest.artifacts}
            for artifact in self.artifacts[source_id]:
                declared = manifest_artifacts[artifact.path.name]
                self.connection.execute(
                    "INSERT INTO reference_source_artifacts(source_id,filename,download_url,size_bytes,sha256,"
                    "required,parser_id,parser_version,retrieved_at,http_metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        source_id, artifact.path.name, declared.url, artifact.size_bytes,
                        f"sha256:{artifact.sha256}", 1 if declared.required else 0,
                        manifest.parser_id, manifest.parser_version, artifact.retrieved_at,
                        canonical_json(artifact.http_metadata),
                    ),
                )
        self.connection.commit()

    def _start_run(self, source_id: str) -> str:
        manifest = self.manifests[source_id]
        checksum = manifest.source_checksum()
        run_id = deterministic_id(
            "reference-import-run/v1", source_id, manifest.parser_id,
            manifest.parser_version, checksum,
        )
        self.connection.execute(
            "INSERT INTO reference_import_runs(id,source_id,importer_id,importer_version,reference_schema_version,"
            "status,source_checksum,started_at) VALUES(?,?,?,?,?,'RUNNING',?,?)",
            (
                run_id, source_id, manifest.parser_id, manifest.parser_version,
                REFERENCE_SCHEMA_VERSION, checksum, utc_now(),
            ),
        )
        self.connection.commit()
        return run_id

    def _finish_run(
        self,
        run_id: str,
        *,
        rows_read: int,
        rows_accepted: int,
        rows_rejected: int,
        warnings: list[str] | None = None,
        errors: list[str] | None = None,
    ) -> None:
        errors = errors or []
        self.connection.execute(
            "UPDATE reference_import_runs SET status=?,rows_read=?,rows_accepted=?,rows_rejected=?,"
            "warnings_json=?,errors_json=?,completed_at=? WHERE id=?",
            (
                "FAILED" if errors else "COMPLETED", rows_read, rows_accepted, rows_rejected,
                canonical_json((warnings or [])[:100]), canonical_json(errors[:100]), utc_now(), run_id,
            ),
        )
        self.connection.commit()

    def import_all(self) -> dict[str, dict[str, Any]]:
        ordered = (ORDBANK_ID, KELLY_ID, CLARINO_ID, IDIOM_ID, UNIGRAM_ID)
        methods = {
            ORDBANK_ID: self.import_ordbank,
            KELLY_ID: self.import_kelly,
            CLARINO_ID: self.import_clarino,
            IDIOM_ID: self.import_idioms,
            UNIGRAM_ID: self.import_unigrams,
        }
        for source_id in ordered:
            if source_id not in self.manifests:
                continue
            started = time.monotonic()
            self._log(f"import {source_id}: started")
            try:
                methods[source_id]()
            except Exception as exc:
                self.connection.rollback()
                running = self.connection.execute(
                    "SELECT id FROM reference_import_runs WHERE source_id=? AND status='RUNNING' ORDER BY started_at DESC LIMIT 1",
                    (source_id,),
                ).fetchone()
                if running:
                    self._finish_run(
                        running[0], rows_read=0, rows_accepted=0, rows_rejected=0,
                        errors=[f"{type(exc).__name__}: {exc}"],
                    )
                raise
            self._log(f"import {source_id}: completed in {time.monotonic()-started:.1f}s")
        return self.quality

    @contextmanager
    def _tar_text(self, archive: tarfile.TarFile, name: str, encoding: str) -> Iterator[io.TextIOWrapper]:
        member = next((item for item in archive.getmembers() if Path(item.name).name == name), None)
        if member is None:
            raise RuntimeError(f"Ordbank archive is missing {name}")
        raw = archive.extractfile(member)
        if raw is None:
            raise RuntimeError(f"cannot open Ordbank member {name}")
        wrapper = io.TextIOWrapper(raw, encoding=encoding, newline="")
        try:
            yield wrapper
        finally:
            wrapper.close()

    def import_ordbank(self) -> None:
        source_id = ORDBANK_ID
        run_id = self._start_run(source_id)
        archive_path = self._data_artifact(source_id, ".tar.gz")
        self.connection.executescript(
            """
            CREATE TEMP TABLE _ordbank_lemma(
                lemma_id TEXT PRIMARY KEY, canonical_form TEXT NOT NULL, dictionary_flag TEXT, source_row INTEGER NOT NULL
            ) WITHOUT ROWID;
            CREATE TEMP TABLE _ordbank_tag_count(
                lemma_id TEXT NOT NULL, family TEXT NOT NULL, row_count INTEGER NOT NULL,
                PRIMARY KEY(lemma_id,family)
            ) WITHOUT ROWID;
            CREATE TEMP TABLE _ordbank_unit_map(
                lemma_id TEXT PRIMARY KEY, lexical_unit_id TEXT NOT NULL, normalized_pos TEXT, raw_family TEXT
            ) WITHOUT ROWID;
            CREATE TEMP TABLE _ordbank_form_batch(
                source_local_id TEXT PRIMARY KEY, lemma_id TEXT NOT NULL, form_id TEXT NOT NULL,
                display_form TEXT NOT NULL, normalized_form TEXT NOT NULL, form_type TEXT NOT NULL,
                orthographic_status TEXT, morphology_json TEXT NOT NULL
            ) WITHOUT ROWID;
            """
        )
        lemma_rows = 0
        malformed_lemmas = 0
        with tarfile.open(archive_path, "r:gz") as archive:
            with self._tar_text(archive, "lemma.txt", "latin-1") as stream:
                reader = csv.DictReader(stream, delimiter="\t")
                batch: list[tuple[Any, ...]] = []
                for item in reader:
                    lemma_rows += 1
                    lemma_id = str(item.get("LEMMA_ID") or "").strip()
                    canonical = str(item.get("GRUNNFORM") or "").strip()
                    if not lemma_id or not canonical:
                        malformed_lemmas += 1
                        continue
                    batch.append((lemma_id, canonical, item.get("'BM_ORDBOK'"), lemma_rows))
                    if len(batch) >= BATCH_SIZE:
                        self.connection.executemany(
                            "INSERT INTO _ordbank_lemma VALUES(?,?,?,?)", batch
                        )
                        batch = []
                if batch:
                    self.connection.executemany("INSERT INTO _ordbank_lemma VALUES(?,?,?,?)", batch)

            form_rows = 0
            malformed_forms_first_pass = 0
            with self._tar_text(archive, "fullformsliste.txt", "latin-1") as stream:
                reader = csv.DictReader(stream, delimiter="\t")
                counts: Counter[tuple[str, str]] = Counter()
                for item in reader:
                    form_rows += 1
                    lemma_id = str(item.get("LEMMA_ID") or "").strip()
                    family = ordbank_tag_family(str(item.get("TAG") or ""))
                    if not lemma_id:
                        malformed_forms_first_pass += 1
                    else:
                        counts[(lemma_id, family)] += 1
                    if len(counts) >= BATCH_SIZE:
                        self.connection.executemany(
                            "INSERT INTO _ordbank_tag_count VALUES(?,?,?) "
                            "ON CONFLICT(lemma_id,family) DO UPDATE SET row_count=row_count+excluded.row_count",
                            [(key[0], key[1], count) for key, count in counts.items()],
                        )
                        self.connection.commit()
                        counts.clear()
                    if form_rows % 250_000 == 0:
                        self._log(f"import {source_id}: scanned {form_rows} form rows")
                if counts:
                    self.connection.executemany(
                        "INSERT INTO _ordbank_tag_count VALUES(?,?,?) "
                        "ON CONFLICT(lemma_id,family) DO UPDATE SET row_count=row_count+excluded.row_count",
                        [(key[0], key[1], count) for key, count in counts.items()],
                    )
                    self.connection.commit()

            self.connection.execute(
                "CREATE TEMP VIEW _ordbank_pos_choice AS "
                "SELECT lemma_id,family,row_count FROM ("
                "SELECT lemma_id,family,row_count,ROW_NUMBER() OVER "
                "(PARTITION BY lemma_id ORDER BY row_count DESC,family) AS choice FROM _ordbank_tag_count"
                ") WHERE choice=1"
            )
            now = utc_now()
            unit_rows: list[tuple[Any, ...]] = []
            link_rows: list[tuple[Any, ...]] = []
            map_rows: list[tuple[Any, ...]] = []
            unknown_families: Counter[str] = Counter()
            missing_pos = 0
            query = self.connection.execute(
                "SELECT l.lemma_id,l.canonical_form,l.dictionary_flag,l.source_row,p.family,p.row_count "
                "FROM _ordbank_lemma l LEFT JOIN _ordbank_pos_choice p ON p.lemma_id=l.lemma_id "
                "ORDER BY l.source_row"
            )
            for row in query:
                lemma_id, canonical, dictionary_flag, source_row, family, family_rows = row
                pos = map_ordbank_family(family or "")
                if family is None:
                    missing_pos += 1
                elif pos is None:
                    unknown_families[str(family)] += 1
                qualifier = f"{source_id}:{lemma_id}"
                unit_id, stable_key, normalized = _unit_identity(
                    canonical, unit_type="LEMMA", pos=pos, qualifier=qualifier
                )
                unit_rows.append(
                    (unit_id, stable_key, "nb", "LEMMA", canonical, normalized, pos, None, qualifier, now, now)
                )
                source_entry = {
                    "lemmaId": lemma_id,
                    "sourceRow": source_row,
                    "dictionaryFlag": dictionary_flag,
                    "dominantTagFamily": family,
                    "dominantTagRows": family_rows,
                    "normalizedPos": pos,
                    "posMappingVersion": ORDBANK_POS_MAPPING_VERSION,
                }
                link_rows.append((unit_id, source_id, lemma_id, run_id, canonical_json(source_entry)))
                map_rows.append((lemma_id, unit_id, pos, family))
                if len(unit_rows) >= BATCH_SIZE:
                    self._insert_ordbank_units(unit_rows, link_rows, map_rows)
                    unit_rows, link_rows, map_rows = [], [], []
            if unit_rows:
                self._insert_ordbank_units(unit_rows, link_rows, map_rows)

            accepted_form_rows = 0
            rejected_orphan_forms = 0
            malformed_forms = 0
            with self._tar_text(archive, "fullformsliste.txt", "latin-1") as stream:
                reader = csv.DictReader(stream, delimiter="\t")
                batch: list[tuple[Any, ...]] = []
                for source_row, item in enumerate(reader, 1):
                    local_id = str(item.get("LOEPENR") or source_row).strip()
                    lemma_id = str(item.get("LEMMA_ID") or "").strip()
                    display = str(item.get("OPPSLAG") or "").strip()
                    if not local_id or not lemma_id or not display:
                        malformed_forms += 1
                        continue
                    form_id, normalized = _form_identity(display)
                    morphology = {
                        "rawTag": item.get("TAG"),
                        "paradigmId": item.get("PARADIGME_ID"),
                        "inflectionNumber": item.get("BOY_NUMMER"),
                        "validFrom": item.get("FRADATO"),
                        "validTo": item.get("TILDATO"),
                        "normering": item.get("NORMERING"),
                        "posMappingVersion": ORDBANK_POS_MAPPING_VERSION,
                    }
                    batch.append(
                        (
                            local_id, lemma_id, form_id, display, normalized, "INFLECTED",
                            item.get("NORMERING"), canonical_json(morphology),
                        )
                    )
                    if len(batch) >= BATCH_SIZE:
                        accepted, rejected = self._insert_ordbank_forms(batch, source_id, run_id, now)
                        accepted_form_rows += accepted
                        rejected_orphan_forms += rejected
                        batch = []
                    if source_row % 250_000 == 0:
                        self._log(f"import {source_id}: stored {source_row} form rows")
                if batch:
                    accepted, rejected = self._insert_ordbank_forms(batch, source_id, run_id, now)
                    accepted_form_rows += accepted
                    rejected_orphan_forms += rejected

            compound_rows, compound_accepted, compound_rejected = self._import_ordbank_compounds(
                archive, source_id, run_id
            )

        if lemma_rows != ORDBANK_EXPECTED_LEMMAS or form_rows != ORDBANK_EXPECTED_FORMS:
            raise RuntimeError(
                f"Ordbank source count deviation: lemmas={lemma_rows}, forms={form_rows}; "
                f"expected {ORDBANK_EXPECTED_LEMMAS}/{ORDBANK_EXPECTED_FORMS}"
            )
        unit_count = self.connection.execute(
            "SELECT COUNT(*) FROM reference_source_links WHERE source_id=?", (source_id,)
        ).fetchone()[0]
        form_count = self.connection.execute(
            "SELECT COUNT(*) FROM reference_forms"
        ).fetchone()[0]
        form_link_count = self.connection.execute(
            "SELECT COUNT(*) FROM reference_form_links WHERE source_id=?", (source_id,)
        ).fetchone()[0]
        homographs = self.connection.execute(
            "SELECT COUNT(*) FROM (SELECT normalized_form FROM reference_lexical_units "
            "WHERE unit_type='LEMMA' GROUP BY normalized_form HAVING COUNT(*)>1)"
        ).fetchone()[0]
        multiword = self.connection.execute(
            "SELECT COUNT(*) FROM reference_lexical_units WHERE unit_type='LEMMA' AND canonical_form GLOB '* *'"
        ).fetchone()[0]
        rejected = malformed_lemmas + malformed_forms_first_pass + malformed_forms + rejected_orphan_forms + compound_rejected
        warnings = [
            f"{missing_pos} lemma rows have no full-form POS evidence",
            f"{rejected_orphan_forms} full-form rows reference lemma IDs absent from lemma.txt",
        ]
        if unknown_families:
            warnings.append(f"unmapped dominant POS families: {dict(sorted(unknown_families.items()))}")
        rows_read = lemma_rows + form_rows + compound_rows
        accepted = unit_count + accepted_form_rows + compound_accepted
        self._finish_run(
            run_id, rows_read=rows_read, rows_accepted=accepted, rows_rejected=rejected,
            warnings=warnings,
        )
        mapped_pos = self.connection.execute(
            "SELECT COUNT(*) FROM _ordbank_unit_map WHERE normalized_pos IS NOT NULL"
        ).fetchone()[0]
        self.quality[source_id] = {
            "rowsRead": rows_read,
            "rowsAccepted": accepted,
            "rowsRejected": rejected,
            "lemmaRows": lemma_rows,
            "lexicalUnitsCreated": unit_count,
            "formRows": form_rows,
            "formRowsAccepted": accepted_form_rows,
            "formsCreated": form_count,
            "formLinks": form_link_count,
            "orphanFormRows": rejected_orphan_forms,
            "compoundRows": compound_rows,
            "compoundRowsAccepted": compound_accepted,
            "homographSpellings": homographs,
            "multiwordLemmas": multiword,
            "posMapped": mapped_pos,
            "posUnmapped": unit_count - mapped_pos,
            "posMappingVersion": ORDBANK_POS_MAPPING_VERSION,
            "unknownDominantFamilies": dict(sorted(unknown_families.items())),
            "warnings": warnings,
        }
        self.connection.commit()

    def _insert_ordbank_units(
        self,
        units: list[tuple[Any, ...]],
        links: list[tuple[Any, ...]],
        mappings: list[tuple[Any, ...]],
    ) -> None:
        self.connection.executemany(
            "INSERT INTO reference_lexical_units(id,stable_key,language_code,unit_type,canonical_form,"
            "normalized_form,part_of_speech,subtype,identity_qualifier,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)", units,
        )
        self.connection.executemany(
            "INSERT INTO reference_source_links(lexical_unit_id,source_id,source_local_id,import_run_id,"
            "source_entry_json) VALUES(?,?,?,?,?)", links,
        )
        self.connection.executemany("INSERT INTO _ordbank_unit_map VALUES(?,?,?,?)", mappings)
        self.connection.commit()

    def _insert_ordbank_forms(
        self,
        rows: list[tuple[Any, ...]],
        source_id: str,
        run_id: str,
        now: str,
    ) -> tuple[int, int]:
        self.connection.execute("DELETE FROM _ordbank_form_batch")
        self.connection.executemany("INSERT INTO _ordbank_form_batch VALUES(?,?,?,?,?,?,?,?)", rows)
        accepted = self.connection.execute(
            "SELECT COUNT(*) FROM _ordbank_form_batch b JOIN _ordbank_unit_map m ON m.lemma_id=b.lemma_id"
        ).fetchone()[0]
        self.connection.execute(
            "INSERT OR IGNORE INTO reference_forms(id,language_code,display_form,normalized_form,created_at) "
            "SELECT b.form_id,'nb',b.display_form,b.normalized_form,? FROM _ordbank_form_batch b "
            "JOIN _ordbank_unit_map m ON m.lemma_id=b.lemma_id", (now,)
        )
        self.connection.execute(
            "INSERT INTO reference_form_links(form_id,lexical_unit_id,source_id,import_run_id,source_local_id,"
            "form_type,orthographic_status,morphology_json) "
            "SELECT b.form_id,m.lexical_unit_id,?,?,b.source_local_id,b.form_type,b.orthographic_status,b.morphology_json "
            "FROM _ordbank_form_batch b JOIN _ordbank_unit_map m ON m.lemma_id=b.lemma_id",
            (source_id, run_id),
        )
        self.connection.commit()
        return int(accepted), len(rows) - int(accepted)

    def _import_ordbank_compounds(
        self, archive: tarfile.TarFile, source_id: str, run_id: str
    ) -> tuple[int, int, int]:
        rows_read = accepted = rejected = 0
        with self._tar_text(archive, "leddanalyse.txt", "latin-1") as stream:
            reader = csv.DictReader(stream, delimiter="\t")
            batch: list[tuple[Any, ...]] = []
            for source_row, item in enumerate(reader, 1):
                rows_read += 1
                local = str(item.get("LOEPENR") or source_row)
                lemma_id = str(item.get("LEMMA_ID") or "").strip()
                evidence_id = deterministic_id("reference-compound", source_id, local)
                batch.append(
                    (
                        evidence_id, lemma_id, source_id, run_id, local,
                        item.get("LEDDANALYSE"), item.get("FORLEDD"), item.get("FORLEDD_GRAM"),
                        item.get("FUGE"), item.get("ETTERLEDD"), item.get("ETTERLEDD_GRAM"),
                        canonical_json(item),
                    )
                )
                if len(batch) >= BATCH_SIZE:
                    a, r = self._insert_compound_batch(batch)
                    accepted += a; rejected += r; batch = []
            if batch:
                a, r = self._insert_compound_batch(batch)
                accepted += a; rejected += r
        return rows_read, accepted, rejected

    def _insert_compound_batch(self, rows: list[tuple[Any, ...]]) -> tuple[int, int]:
        self.connection.execute(
            "CREATE TEMP TABLE IF NOT EXISTS _ordbank_compound_batch("
            "id TEXT,lemma_id TEXT,source_id TEXT,run_id TEXT,source_local_id TEXT,analysis_text TEXT,"
            "first_component TEXT,first_grammar TEXT,joiner TEXT,final_component TEXT,final_grammar TEXT,raw_json TEXT)"
        )
        self.connection.execute("DELETE FROM _ordbank_compound_batch")
        self.connection.executemany(
            "INSERT INTO _ordbank_compound_batch VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", rows
        )
        accepted = self.connection.execute(
            "SELECT COUNT(*) FROM _ordbank_compound_batch b JOIN _ordbank_unit_map m ON m.lemma_id=b.lemma_id"
        ).fetchone()[0]
        self.connection.execute(
            "INSERT INTO reference_compound_analyses(id,lexical_unit_id,source_id,import_run_id,source_local_id,"
            "analysis_text,first_component,first_component_grammar,joiner,final_component,final_component_grammar,"
            "raw_evidence_json) SELECT b.id,m.lexical_unit_id,b.source_id,b.run_id,b.source_local_id,b.analysis_text,"
            "b.first_component,b.first_grammar,b.joiner,b.final_component,b.final_grammar,b.raw_json "
            "FROM _ordbank_compound_batch b JOIN _ordbank_unit_map m ON m.lemma_id=b.lemma_id"
        )
        return int(accepted), len(rows) - int(accepted)

    def import_kelly(self) -> None:
        source_id = KELLY_ID
        run_id = self._start_run(source_id)
        path = self._data_artifact(source_id, ".json")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise RuntimeError("KELLY artifact is not a JSON array")
        now = utc_now()
        raw_rows: list[tuple[Any, ...]] = []
        pos_rows: list[tuple[str, str]] = []
        rejected = 0
        reject_samples: list[str] = []
        self.connection.execute(
            "CREATE TEMP TABLE _kelly_pos(observation_id TEXT NOT NULL,normalized_pos TEXT NOT NULL,"
            "PRIMARY KEY(observation_id,normalized_pos)) WITHOUT ROWID"
        )
        for source_row, item in enumerate(payload, 1):
            try:
                word = str(item["word"]).strip()
                rank = int(item["rank"])
                raw_pos = str(item.get("pos") or "")
                if not word or rank <= 0:
                    raise ValueError("missing word/rank")
            except (KeyError, TypeError, ValueError) as exc:
                rejected += 1
                if len(reject_samples) < 20:
                    reject_samples.append(f"row {source_row}: {exc}")
                continue
            local = str(source_row)
            observation_id = _observation_id(source_id, "SOURCE_LEARNER_RANK", local)
            mapped_pos = map_kelly_pos(raw_pos)
            raw_rows.append(
                (
                    observation_id, source_id, run_id, local, "SOURCE_LEARNER_RANK", word,
                    normalize_reference_lookup(word), None, rank, "nb", None, "PENDING", None, 0,
                    canonical_json({
                        "word": word, "rank": rank, "rawPos": raw_pos,
                        "normalizedPosCandidates": mapped_pos,
                        "posMappingVersion": KELLY_POS_MAPPING_VERSION,
                        "englishGloss": item.get("english"),
                        "englishGlossRole": "KELLY_TRANSLATION_NOT_DICTIONARY_SENSE",
                    }), now,
                )
            )
            pos_rows.extend((observation_id, pos) for pos in mapped_pos)
        self.connection.executemany(
            "INSERT INTO reference_raw_observations(id,source_id,import_run_id,source_local_id,metric_type,raw_form,"
            "normalized_form,raw_count,rank,language_label,normalized_pos,resolution_status,matched_lexical_unit_id,"
            "candidate_count,raw_evidence_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", raw_rows,
        )
        self.connection.executemany("INSERT INTO _kelly_pos VALUES(?,?)", pos_rows)
        self.connection.execute(
            "INSERT OR IGNORE INTO reference_observation_candidates(observation_id,lexical_unit_id,match_basis) "
            "SELECT o.id,u.id,'NORMALIZED_LEMMA_POS' FROM reference_raw_observations o "
            "JOIN _kelly_pos p ON p.observation_id=o.id "
            "JOIN reference_lexical_units u ON u.language_code='nb' AND u.unit_type='LEMMA' "
            "AND u.normalized_form=o.normalized_form AND u.part_of_speech=p.normalized_pos "
            "WHERE o.source_id=? AND o.metric_type='SOURCE_LEARNER_RANK'", (source_id,)
        )
        self._finalize_resolution(source_id, "SOURCE_LEARNER_RANK")
        matched_rows = self.connection.execute(
            "SELECT id,matched_lexical_unit_id,source_local_id,rank,raw_evidence_json FROM reference_raw_observations "
            "WHERE source_id=? AND metric_type='SOURCE_LEARNER_RANK' AND resolution_status='MATCHED' ORDER BY rank,id",
            (source_id,),
        )
        link_rows: list[tuple[Any, ...]] = []
        frequency_rows: list[tuple[Any, ...]] = []
        for observation_id, unit_id, local, rank, raw_json in matched_rows:
            link_rows.append((unit_id, source_id, f"kelly:{local}", run_id, raw_json))
            frequency_rows.append(
                (
                    deterministic_id("reference-frequency", unit_id, source_id, "SOURCE_LEARNER_RANK", local),
                    unit_id, source_id, run_id, local, "RAW_SOURCE", "SOURCE_LEARNER_RANK",
                    None, rank, None, None, None, None, None, "learner-oriented KELLY", None, None,
                    None, None, raw_json, now,
                )
            )
        self.connection.executemany(
            "INSERT INTO reference_source_links(lexical_unit_id,source_id,source_local_id,import_run_id,"
            "source_entry_json) VALUES(?,?,?,?,?)", link_rows,
        )
        self._insert_frequency_rows(frequency_rows)
        counts = self._resolution_counts(source_id, "SOURCE_LEARNER_RANK")
        warnings = reject_samples + [f"KELLY POS mapping version: {KELLY_POS_MAPPING_VERSION}"]
        self._finish_run(
            run_id, rows_read=len(payload), rows_accepted=len(raw_rows), rows_rejected=rejected,
            warnings=warnings,
        )
        self.quality[source_id] = {
            "rowsRead": len(payload), "rowsAccepted": len(raw_rows), "rowsRejected": rejected,
            "sourceLinks": len(link_rows), "mapping": counts,
            "rankMin": min((row[8] for row in raw_rows), default=None),
            "rankMax": max((row[8] for row in raw_rows), default=None),
            "posMappingVersion": KELLY_POS_MAPPING_VERSION,
            "cefrRowsCreated": 0, "rejectSamples": reject_samples,
        }
        self.connection.commit()

    def import_clarino(self) -> None:
        source_id = CLARINO_ID
        run_id = self._start_run(source_id)
        path = self._data_artifact(source_id, ".tsv")
        rows: list[tuple[Any, ...]] = []
        rejected = 0
        reject_samples: list[str] = []
        previous_count: int | None = None
        now = utc_now()
        header = ""
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            for line_number, line in enumerate(stream, 1):
                line = line.rstrip("\r\n")
                if line.startswith("#"):
                    header = line
                    continue
                if not line:
                    continue
                try:
                    count_text, token = line.split("\t", 1)
                    count = int(count_text)
                    if count < 0 or not token:
                        raise ValueError("invalid count/token")
                    if previous_count is not None and count > previous_count:
                        raise ValueError("source counts are not descending")
                    previous_count = count
                except ValueError as exc:
                    rejected += 1
                    if len(reject_samples) < 20:
                        reject_samples.append(f"line {line_number}: {exc}")
                    continue
                rank = len(rows) + 1
                local = str(rank)
                status = "EXCLUDED_NONLEXICAL" if _is_nonlexical(token) else "PENDING"
                rows.append(
                    (
                        _observation_id(source_id, "SOURCE_FORM_RANK", local), source_id, run_id, local,
                        "SOURCE_FORM_RANK", token, normalize_reference_lookup(token), count, rank, "nb", None,
                        status, None, 0, canonical_json({"header": header, "sourceLine": line_number}), now,
                    )
                )
        if len(rows) != CLARINO_EXPECTED_ROWS:
            raise RuntimeError(f"CLARINO source count deviation: {len(rows)} rows; expected {CLARINO_EXPECTED_ROWS}")
        self._insert_raw_rows(rows)
        self._resolve_surface(source_id, "SOURCE_FORM_RANK")
        derived = self._derive_lemma_frequency(
            source_id, "SOURCE_FORM_RANK", run_id,
            method_id="clarino-derived-lemma-frequency", method_version="v1",
        )
        counts = self._resolution_counts(source_id, "SOURCE_FORM_RANK")
        self._finish_run(
            run_id, rows_read=len(rows) + rejected, rows_accepted=len(rows), rows_rejected=rejected,
            warnings=reject_samples,
        )
        self.quality[source_id] = {
            "rowsRead": len(rows) + rejected, "rowsAccepted": len(rows), "rowsRejected": rejected,
            "mapping": counts, "frequencyMass": self._mass_counts(source_id, "SOURCE_FORM_RANK"),
            "derived": derived, "rawMetric": "SOURCE_FORM_RANK", "rejectSamples": reject_samples,
        }
        self.connection.commit()

    def import_idioms(self) -> None:
        source_id = IDIOM_ID
        run_id = self._start_run(source_id)
        path = self._data_artifact(source_id, ".zip")
        now = utc_now()
        rows_read = rows_accepted = rows_rejected = 0
        units_created: set[str] = set()
        imported_by_display: dict[str, str] = {}
        language_frequency_counts: Counter[str] = Counter()
        prompt_language_counts: Counter[str] = Counter()
        completion_variants = 0
        multi_completion_prompts = 0
        reject_samples: list[str] = []
        with zipfile.ZipFile(path) as archive:
            members = {Path(name).name: name for name in archive.namelist() if not name.endswith("/")}
            frequency_members = (
                ("nob", "nob_idioms_freq.json"),
                ("nno", "nno_idioms_freq.json"),
                ("both", "both_freqs.json"),
            )
            for language, filename in frequency_members:
                if filename not in members:
                    raise RuntimeError(f"idiom archive is missing {filename}")
                data = json.loads(archive.read(members[filename]).decode("utf-8"))
                for index, (expression, raw_count) in enumerate(data.items(), 1):
                    rows_read += 1
                    language_frequency_counts[language] += 1
                    try:
                        expression = str(expression).strip()
                        count = int(raw_count)
                        if not expression or count < 0:
                            raise ValueError("invalid expression/count")
                    except (TypeError, ValueError) as exc:
                        rows_rejected += 1
                        if len(reject_samples) < 20:
                            reject_samples.append(f"{filename}:{index}: {exc}")
                        continue
                    local = f"frequency:{language}:{index}"
                    if language == "nno":
                        self._insert_raw_rows([(
                            _observation_id(source_id, "SOURCE_IDIOM_FREQUENCY", local), source_id, run_id,
                            local, "SOURCE_IDIOM_FREQUENCY", expression, normalize_reference_lookup(expression),
                            count, None, "nno", None, "EXCLUDED_LANGUAGE", None, 0,
                            canonical_json({"language": language, "sourceFile": filename}), now,
                        )])
                        rows_accepted += 1
                        continue
                    unit_id = self._insert_idiom_unit(
                        expression, qualifier=f"{source_id}:{local}", source_id=source_id,
                        source_local_id=local, run_id=run_id, source_entry={"language": language, "count": count},
                        now=now,
                    )
                    units_created.add(unit_id)
                    imported_by_display.setdefault(expression, unit_id)
                    observation_id = _observation_id(source_id, "SOURCE_IDIOM_FREQUENCY", local)
                    self._insert_raw_rows([(
                        observation_id, source_id, run_id, local, "SOURCE_IDIOM_FREQUENCY", expression,
                        normalize_reference_lookup(expression), count, None, language, None, "MATCHED", unit_id, 1,
                        canonical_json({"language": language, "sourceFile": filename}), now,
                    )])
                    self.connection.execute(
                        "INSERT INTO reference_frequency_observations(id,lexical_unit_id,source_id,import_run_id,"
                        "observation_key,evidence_kind,metric_type,raw_count,raw_evidence_json,created_at) "
                        "VALUES(?,?,?,?,?,'RAW_SOURCE','SOURCE_IDIOM_FREQUENCY',?,?,?)",
                        (
                            deterministic_id("reference-frequency", unit_id, source_id, "SOURCE_IDIOM_FREQUENCY", local),
                            unit_id, source_id, run_id, local, count,
                            canonical_json({"language": language, "sourceFile": filename}), now,
                        ),
                    )
                    rows_accepted += 1

            data_member = members.get("data.jsonl")
            if not data_member:
                raise RuntimeError("idiom archive is missing data.jsonl")
            with archive.open(data_member) as raw_stream:
                stream = io.TextIOWrapper(raw_stream, encoding="utf-8", newline="")
                for prompt_index, line in enumerate(stream, 1):
                    rows_read += 1
                    try:
                        item = json.loads(line)
                        start = str(item["idiom_start"]).strip()
                        completions = item["accepted_completions"]
                        language = str(item["language"]).strip()
                        if not start or not isinstance(completions, list) or not completions:
                            raise ValueError("invalid prompt/completions")
                    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                        rows_rejected += 1
                        if len(reject_samples) < 20:
                            reject_samples.append(f"data.jsonl:{prompt_index}: {exc}")
                        continue
                    prompt_language_counts[language] += 1
                    if len(completions) > 1:
                        multi_completion_prompts += 1
                    rows_accepted += 1
                    for completion_index, completion_value in enumerate(completions, 1):
                        completion = str(completion_value).strip()
                        full = f"{start} {completion}".strip()
                        local = f"prompt:{prompt_index}:{completion_index}"
                        if language == "nno":
                            self._insert_raw_rows([(
                                _observation_id(source_id, "SOURCE_IDIOM_VARIANT", local), source_id, run_id,
                                local, "SOURCE_IDIOM_VARIANT", full, normalize_reference_lookup(full), None, None,
                                "nno", None, "EXCLUDED_LANGUAGE", None, 0,
                                canonical_json({"prompt": start, "completion": completion}), now,
                            )])
                            continue
                        unit_id = imported_by_display.get(full)
                        if unit_id is None:
                            unit_id = self._insert_idiom_unit(
                                full, qualifier=f"{source_id}:{local}", source_id=source_id,
                                source_local_id=local, run_id=run_id,
                                source_entry={"language": language, "prompt": start, "completion": completion},
                                now=now,
                            )
                            imported_by_display[full] = unit_id
                            units_created.add(unit_id)
                        else:
                            self.connection.execute(
                                "INSERT OR IGNORE INTO reference_source_links(lexical_unit_id,source_id,source_local_id,"
                                "import_run_id,source_entry_json) VALUES(?,?,?,?,?)",
                                (
                                    unit_id, source_id, local, run_id,
                                    canonical_json({"language": language, "prompt": start, "completion": completion}),
                                ),
                            )
                        variant_id = deterministic_id("reference-expression-variant", source_id, local, full)
                        self.connection.execute(
                            "INSERT INTO reference_expression_variants(id,lexical_unit_id,source_id,import_run_id,"
                            "source_local_id,display_form,normalized_form,variant_type,metadata_json) "
                            "VALUES(?,?,?,?,?,?,?,?,?)",
                            (
                                variant_id, unit_id, source_id, run_id, local, full,
                                normalize_reference_lookup(full), "COMPLETION",
                                canonical_json({"prompt": start, "completion": completion, "language": language}),
                            ),
                        )
                        completion_variants += 1
        expected_frequency = IDIOM_EXPECTED_FREQUENCY
        if dict(language_frequency_counts) != expected_frequency:
            raise RuntimeError(
                f"idiom source frequency deviation: {dict(language_frequency_counts)}; expected {expected_frequency}"
            )
        if (
            sum(prompt_language_counts.values()) != IDIOM_EXPECTED_PROMPTS
            or multi_completion_prompts != IDIOM_EXPECTED_MULTI_COMPLETION
        ):
            raise RuntimeError(
                f"idiom prompt deviation: prompts={sum(prompt_language_counts.values())}, "
                f"multiCompletion={multi_completion_prompts}"
            )
        self._finish_run(
            run_id, rows_read=rows_read, rows_accepted=rows_accepted, rows_rejected=rows_rejected,
            warnings=reject_samples,
        )
        self.quality[source_id] = {
            "rowsRead": rows_read, "rowsAccepted": rows_accepted, "rowsRejected": rows_rejected,
            "frequencyLanguageCounts": dict(language_frequency_counts),
            "promptLanguageCounts": dict(prompt_language_counts),
            "referenceUnitsCreated": len(units_created), "completionVariants": completion_variants,
            "multiCompletionPrompts": multi_completion_prompts,
            "nynorskOnlyImportedAsBokmal": 0, "definitionsCreated": 0,
            "rejectSamples": reject_samples,
        }
        self.connection.commit()

    def _insert_idiom_unit(
        self,
        expression: str,
        *,
        qualifier: str,
        source_id: str,
        source_local_id: str,
        run_id: str,
        source_entry: dict[str, Any],
        now: str,
    ) -> str:
        unit_id, stable_key, normalized = _unit_identity(
            expression, unit_type="IDIOM", pos=None, qualifier=qualifier
        )
        self.connection.execute(
            "INSERT INTO reference_lexical_units(id,stable_key,language_code,unit_type,canonical_form,"
            "normalized_form,part_of_speech,subtype,identity_qualifier,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (unit_id, stable_key, "nb", "IDIOM", expression, normalized, None, None, qualifier, now, now),
        )
        self.connection.execute(
            "INSERT INTO reference_source_links(lexical_unit_id,source_id,source_local_id,import_run_id,"
            "source_entry_json) VALUES(?,?,?,?,?)",
            (unit_id, source_id, source_local_id, run_id, canonical_json(source_entry)),
        )
        self.connection.executemany(
            "INSERT INTO reference_mwe_components(lexical_unit_id,position,component_text,normalized_form,"
            "optional,variant_metadata_json) VALUES(?,?,?,?,0,'{}')",
            [
                (unit_id, position, token, normalize_reference_lookup(token))
                for position, token in enumerate(expression.split())
            ],
        )
        return unit_id

    def import_unigrams(self) -> None:
        source_id = UNIGRAM_ID
        run_id = self._start_run(source_id)
        path = self._data_artifact(source_id, ".zip")
        now = utc_now()
        rows_read = rows_accepted = rows_rejected = 0
        reject_samples: list[str] = []
        pattern = re.compile(r"^\s*(\d+)\s+(.+?)\s*$")
        with zipfile.ZipFile(path) as archive:
            members = [
                item for item in archive.infolist()
                if not item.is_dir() and item.filename.lower().endswith((".txt", ".frk"))
            ]
            if len(members) != 1:
                raise RuntimeError(f"unigram archive must contain exactly one text member; found {len(members)}")
            with archive.open(members[0]) as raw_stream:
                stream = io.TextIOWrapper(raw_stream, encoding="latin-1", newline="")
                batch: list[tuple[Any, ...]] = []
                previous_count: int | None = None
                for line_number, line in enumerate(stream, 1):
                    rows_read += 1
                    match = pattern.match(line.rstrip("\r\n"))
                    if not match:
                        rows_rejected += 1
                        if len(reject_samples) < 20:
                            reject_samples.append(f"line {line_number}: malformed unigram row")
                        continue
                    count = int(match.group(1))
                    token = match.group(2)
                    if previous_count is not None and count > previous_count:
                        raise RuntimeError(f"unigram source is not frequency sorted at line {line_number}")
                    previous_count = count
                    rows_accepted += 1
                    local = str(rows_accepted)
                    status = "EXCLUDED_NONLEXICAL" if _is_nonlexical(token) else "PENDING"
                    batch.append(
                        (
                            _observation_id(source_id, "SOURCE_NGRAM_FREQUENCY", local), source_id, run_id, local,
                            "SOURCE_NGRAM_FREQUENCY", token, normalize_reference_lookup(token), count,
                            rows_accepted, "nb", None, status, None, 0,
                            canonical_json({"sourceLine": line_number, "archiveMember": members[0].filename}), now,
                        )
                    )
                    if len(batch) >= BATCH_SIZE:
                        self._insert_raw_rows(batch)
                        self.connection.commit()
                        batch = []
                    if rows_read % 250_000 == 0:
                        self._log(f"import {source_id}: stored {rows_read} unigram rows")
                if batch:
                    self._insert_raw_rows(batch)
        self._resolve_surface(source_id, "SOURCE_NGRAM_FREQUENCY")
        derived = self._derive_lemma_frequency(
            source_id, "SOURCE_NGRAM_FREQUENCY", run_id,
            method_id="bokmal-unigram-derived-lemma-frequency", method_version="v1",
        )
        counts = self._resolution_counts(source_id, "SOURCE_NGRAM_FREQUENCY")
        self._finish_run(
            run_id, rows_read=rows_read, rows_accepted=rows_accepted, rows_rejected=rows_rejected,
            warnings=reject_samples,
        )
        self.quality[source_id] = {
            "rowsRead": rows_read, "rowsAccepted": rows_accepted, "rowsRejected": rows_rejected,
            "mapping": counts, "frequencyMass": self._mass_counts(source_id, "SOURCE_NGRAM_FREQUENCY"),
            "derived": derived, "tier3Rows": 0, "rejectSamples": reject_samples,
        }
        self.connection.commit()

    def _insert_raw_rows(self, rows: list[tuple[Any, ...]]) -> None:
        self.connection.executemany(
            "INSERT INTO reference_raw_observations(id,source_id,import_run_id,source_local_id,metric_type,raw_form,"
            "normalized_form,raw_count,rank,language_label,normalized_pos,resolution_status,matched_lexical_unit_id,"
            "candidate_count,raw_evidence_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows,
        )

    def _resolve_surface(self, source_id: str, metric_type: str) -> None:
        self.connection.execute(
            "INSERT OR IGNORE INTO reference_observation_candidates(observation_id,lexical_unit_id,match_basis) "
            "SELECT DISTINCT o.id,l.lexical_unit_id,'NORMALIZED_ORDBANK_FORM' "
            "FROM reference_raw_observations o JOIN reference_forms f "
            "ON f.language_code='nb' AND f.normalized_form=o.normalized_form "
            "JOIN reference_form_links l ON l.form_id=f.id AND l.source_id=? "
            "WHERE o.source_id=? AND o.metric_type=? AND o.resolution_status='PENDING'",
            (ORDBANK_ID, source_id, metric_type),
        )
        self._finalize_resolution(source_id, metric_type)

    def _finalize_resolution(self, source_id: str, metric_type: str) -> None:
        self.connection.execute(
            "UPDATE reference_raw_observations SET candidate_count=(SELECT COUNT(*) FROM "
            "reference_observation_candidates c WHERE c.observation_id=reference_raw_observations.id) "
            "WHERE source_id=? AND metric_type=? AND resolution_status='PENDING'",
            (source_id, metric_type),
        )
        self.connection.execute(
            "UPDATE reference_raw_observations SET resolution_status=CASE candidate_count "
            "WHEN 0 THEN 'UNMATCHED' WHEN 1 THEN 'MATCHED' ELSE 'AMBIGUOUS' END,"
            "matched_lexical_unit_id=CASE WHEN candidate_count=1 THEN (SELECT c.lexical_unit_id FROM "
            "reference_observation_candidates c WHERE c.observation_id=reference_raw_observations.id LIMIT 1) "
            "ELSE NULL END WHERE source_id=? AND metric_type=? AND resolution_status='PENDING'",
            (source_id, metric_type),
        )

    def _resolution_counts(self, source_id: str, metric_type: str) -> dict[str, int]:
        rows = self.connection.execute(
            "SELECT resolution_status,COUNT(*) FROM reference_raw_observations "
            "WHERE source_id=? AND metric_type=? GROUP BY resolution_status ORDER BY resolution_status",
            (source_id, metric_type),
        )
        return {str(status): int(count) for status, count in rows}

    def _mass_counts(self, source_id: str, metric_type: str) -> dict[str, int | float]:
        rows = self.connection.execute(
            "SELECT resolution_status,COALESCE(SUM(raw_count),0) FROM reference_raw_observations "
            "WHERE source_id=? AND metric_type=? GROUP BY resolution_status ORDER BY resolution_status",
            (source_id, metric_type),
        )
        result = {str(status): int(count) for status, count in rows}
        total = sum(result.values())
        result["TOTAL"] = total
        result["MAPPED_PERCENT"] = round(100 * result.get("MATCHED", 0) / total, 6) if total else 0.0
        return result

    def _derive_lemma_frequency(
        self,
        source_id: str,
        raw_metric: str,
        run_id: str,
        *,
        method_id: str,
        method_version: str,
    ) -> dict[str, Any]:
        policy = {
            "inputMetric": raw_metric,
            "qualification": "resolution_status=MATCHED and exactly one Ordbank form candidate",
            "case": "NFC casefold lookup; original source case retained",
            "punctuation": "rows without a Unicode letter and sentence-boundary markers excluded",
            "properNouns": "not guessed or excluded; casefold mapping may match, ambiguity remains unresolved",
            "oneToMany": "ambiguous mass excluded",
            "aggregation": "sum raw counts by matched Ordbank lexical-unit identity",
            "unmapped": "retained as raw evidence and excluded from derived totals",
            "ties": "SQL RANK semantics; equal counts share rank and gaps follow",
            "direction": "larger count is more frequent; rank 1 is largest",
            "failure": "raw observations remain authoritative; derived stage aborts transaction on error",
        }
        checksum = "sha256:" + hashlib.sha256(canonical_json(policy).encode("utf-8")).hexdigest()
        self.connection.execute(
            "INSERT INTO reference_derived_methods(method_id,method_version,policy_checksum,policy_json,created_at) "
            "VALUES(?,?,?,?,?)",
            (method_id, method_version, checksum, canonical_json(policy), utc_now()),
        )
        self.connection.execute("DROP TABLE IF EXISTS temp._derived_totals")
        self.connection.execute(
            "CREATE TEMP TABLE _derived_totals AS SELECT matched_lexical_unit_id AS lexical_unit_id,"
            "SUM(raw_count) AS total_count FROM reference_raw_observations WHERE source_id=? AND metric_type=? "
            "AND resolution_status='MATCHED' GROUP BY matched_lexical_unit_id",
            (source_id, raw_metric),
        )
        self.connection.execute(
            "CREATE INDEX _idx_derived_totals_count ON _derived_totals(total_count DESC,lexical_unit_id)"
        )
        now = utc_now()
        rows: list[tuple[Any, ...]] = []
        previous_count: int | None = None
        current_rank = 0
        ordinal = 0
        for unit_id, total_count in self.connection.execute(
            "SELECT lexical_unit_id,total_count FROM _derived_totals ORDER BY total_count DESC,lexical_unit_id"
        ):
            ordinal += 1
            if previous_count != total_count:
                current_rank = ordinal
                previous_count = total_count
            evidence = canonical_json({"inputMetric": raw_metric, "policyChecksum": checksum})
            rows.extend([
                (
                    deterministic_id("reference-frequency", unit_id, source_id, "DERIVED_LEMMA_FREQUENCY", method_version),
                    unit_id, source_id, run_id, f"{method_id}/{method_version}", "DERIVED",
                    "DERIVED_LEMMA_FREQUENCY", int(total_count), None, None, None, None, None, None,
                    None, None, None, method_id, method_version, evidence, now,
                ),
                (
                    deterministic_id("reference-frequency", unit_id, source_id, "DERIVED_LEMMA_RANK", method_version),
                    unit_id, source_id, run_id, f"{method_id}/{method_version}", "DERIVED",
                    "DERIVED_LEMMA_RANK", None, current_rank, None, None, None, None, None,
                    None, None, None, method_id, method_version, evidence, now,
                ),
            ])
            if len(rows) >= BATCH_SIZE:
                self._insert_frequency_rows(rows)
                rows = []
        if rows:
            self._insert_frequency_rows(rows)
        return {
            "method": method_id, "version": method_version, "policyChecksum": checksum,
            "lemmaCount": ordinal, "observationCount": ordinal * 2,
        }

    def _insert_frequency_rows(self, rows: list[tuple[Any, ...]]) -> None:
        self.connection.executemany(
            "INSERT INTO reference_frequency_observations(id,lexical_unit_id,source_id,import_run_id,"
            "observation_key,evidence_kind,metric_type,raw_count,rank,frequency_per_million,zipf_score,"
            "document_frequency,dispersion,corpus_token_count,genre,period_start,period_end,method,method_version,"
            "raw_evidence_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows,
        )
        self.connection.commit()


__all__ = [
    "BATCH_SIZE",
    "CLARINO_ID",
    "IDIOM_ID",
    "KELLY_ID",
    "ORDBANK_ID",
    "ProductionImporter",
    "UNIGRAM_ID",
]
