"""Read-only runtime boundary for source-backed Language reference facts."""

from __future__ import annotations

import hashlib
import json
import copy
from pathlib import Path
import sqlite3
from typing import Any, Iterable

from .models import (
    ReferenceLexicalUnit,
    ResolverResult,
    VocabularyLemmaIdentity,
    normalize_reference_lookup,
)
from .resolver import ReferenceResolver
from .store import ClosingReferenceConnection, ReferenceStore, canonical_json


REFERENCE_SERVICE_VERSION = "language.reference-lexicon-service/v1"
EXPRESSION_DETECTOR_VERSION = "language.reference-expression-detection/v1"
REFERENCE_PROFILE_VERSION = "language.reference-text-profile/v1"
SUPPORTED_SCHEMA_VERSIONS = frozenset({1, 2, 3})
MAX_CANDIDATES = 20
MAX_EVIDENCE = 80
KELLY_SOURCE_ID = "uio-norwegian-kelly-shu-wang"


def _json(value: Any, fallback: Any) -> Any:
    try:
        return json.loads(value) if value else fallback
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback


def _unit_payload(unit: ReferenceLexicalUnit) -> dict[str, Any]:
    return {
        "id": unit.id,
        "stableKey": unit.stable_key,
        "languageCode": unit.language_code,
        "unitType": unit.unit_type,
        "canonicalForm": unit.canonical_form,
        "normalizedForm": unit.normalized_form,
        "partOfSpeech": unit.part_of_speech,
        "subtype": unit.subtype,
        "identityQualifier": unit.identity_qualifier,
    }


class ReferenceLexiconService:
    """Optional, operation-scoped, read-only access to the reference database."""

    service_version = REFERENCE_SERVICE_VERSION
    detector_version = EXPRESSION_DETECTOR_VERSION
    profile_version = REFERENCE_PROFILE_VERSION

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.store = ReferenceStore(self.database_path, read_only=True)
        self.resolver = ReferenceResolver(self.store)
        self._health_cache_signature: tuple[Any, ...] | None = None
        self._health_cache_value: dict[str, Any] | None = None

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.database_path.resolve().as_uri() + "?mode=ro",
            uri=True,
            timeout=15,
            factory=ClosingReferenceConnection,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=15000")
        return connection

    @staticmethod
    def _exists(connection: sqlite3.Connection, sql: str, parameters: tuple[Any, ...] = ()) -> bool:
        return connection.execute(sql, parameters).fetchone() is not None

    def health(self) -> dict[str, Any]:
        try:
            stat = self.database_path.stat()
            signature: tuple[Any, ...] = (True, stat.st_size, stat.st_mtime_ns)
        except OSError:
            signature = (False,)
        if signature == self._health_cache_signature and self._health_cache_value is not None:
            return copy.deepcopy(self._health_cache_value)

        def finish(payload: dict[str, Any]) -> dict[str, Any]:
            self._health_cache_signature = signature
            self._health_cache_value = copy.deepcopy(payload)
            return payload

        base = {
            "serviceVersion": self.service_version,
            "configured": True,
            "available": False,
            "schemaVersion": None,
            "referenceFingerprint": None,
            "sourceSnapshot": [],
            "lexicalUnitsAvailable": 0,
            "frequencyAvailable": False,
            "learnerRankAvailable": False,
            "idiomsAvailable": False,
            "mweAvailable": False,
            "sentenceBankAvailable": False,
            "cefrAvailable": False,
            "tier3Available": False,
        }
        if not self.database_path.is_file():
            return finish({**base, "reason": "REFERENCE_DATABASE_MISSING"})
        try:
            with self._connect() as connection:
                schema_version = int(connection.execute(
                    "SELECT COALESCE(MAX(version),0) FROM reference_schema_migrations"
                ).fetchone()[0])
                if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
                    return finish({**base, "schemaVersion": schema_version, "reason": "UNSUPPORTED_REFERENCE_SCHEMA"})
                sources = [dict(row) for row in connection.execute(
                    "SELECT s.source_id,s.canonical_name,s.provider,s.version,s.license_id,"
                    "MAX(r.importer_version) AS importer_version,MAX(r.source_checksum) AS source_checksum "
                    "FROM reference_sources s LEFT JOIN reference_import_runs r "
                    "ON r.source_id=s.source_id AND r.status='COMPLETED' "
                    "GROUP BY s.source_id,s.canonical_name,s.provider,s.version,s.license_id "
                    "ORDER BY s.source_id LIMIT 20"
                ).fetchall()]
                fingerprint_payload = {
                    "schemaVersion": schema_version,
                    "sources": [
                        {
                            "sourceId": row["source_id"],
                            "version": row["version"],
                            "importerVersion": row["importer_version"],
                            "sourceChecksum": row["source_checksum"],
                        }
                        for row in sources
                    ],
                }
                fingerprint = "sha256:" + hashlib.sha256(
                    canonical_json(fingerprint_payload).encode("utf-8")
                ).hexdigest()
                units = int(connection.execute("SELECT COUNT(*) FROM reference_lexical_units").fetchone()[0])
                return finish({
                    **base,
                    "available": True,
                    "schemaVersion": schema_version,
                    "referenceFingerprint": fingerprint,
                    "sourceSnapshot": [
                        {
                            "sourceId": row["source_id"],
                            "name": row["canonical_name"],
                            "provider": row["provider"],
                            "version": row["version"],
                            "license": row["license_id"],
                            "importerVersion": row["importer_version"],
                        }
                        for row in sources
                    ],
                    "lexicalUnitsAvailable": units,
                    "frequencyAvailable": self._exists(connection, "SELECT 1 FROM reference_frequency_observations LIMIT 1"),
                    "learnerRankAvailable": self._exists(connection, "SELECT 1 FROM reference_frequency_observations WHERE metric_type='SOURCE_LEARNER_RANK' LIMIT 1"),
                    "idiomsAvailable": self._exists(connection, "SELECT 1 FROM reference_lexical_units WHERE unit_type='IDIOM' LIMIT 1"),
                    "mweAvailable": self._exists(connection, "SELECT 1 FROM reference_mwe_components LIMIT 1"),
                    "sentenceBankAvailable": schema_version >= 2 and self._exists(connection, "SELECT 1 FROM reference_sentences LIMIT 1"),
                    "cefrAvailable": self._exists(connection, "SELECT 1 FROM reference_cefr_evidence LIMIT 1"),
                    "tier3Available": self._exists(connection, "SELECT 1 FROM reference_association_evidence LIMIT 1"),
                })
        except (sqlite3.Error, OSError) as exc:
            return finish({**base, "reason": "REFERENCE_DATABASE_UNAVAILABLE", "error": type(exc).__name__})

    def _available(self) -> bool:
        return bool(self.health().get("available"))

    @staticmethod
    def _resolution_payload(result: ResolverResult) -> dict[str, Any]:
        return {
            "status": result.status.value,
            "ruleVersion": result.rule_version,
            "candidates": [
                {**_unit_payload(candidate.lexical_unit), "matchBasis": candidate.match_basis}
                for candidate in result.candidates[:MAX_CANDIDATES]
            ],
        }

    def resolve_user_lemma(self, lemma: VocabularyLemmaIdentity) -> dict[str, Any]:
        if not self._available():
            return {"status": "UNAVAILABLE", "ruleVersion": self.resolver.rule_version, "candidates": []}
        return self._resolution_payload(self.resolver.resolve(lemma))

    def resolve_user_lemmas(self, lemmas: Iterable[VocabularyLemmaIdentity]) -> list[dict[str, Any]]:
        items = list(lemmas)
        if not items:
            return []
        if not self._available():
            return [
                {"status": "UNAVAILABLE", "ruleVersion": self.resolver.rule_version, "candidates": []}
                for _ in items
            ]
        return [self._resolution_payload(item) for item in self.resolver.resolve_many(items)]

    def _sources_for_units(self, connection: sqlite3.Connection, unit_ids: list[str]) -> list[dict[str, Any]]:
        if not unit_ids:
            return []
        rows = []
        for offset in range(0, len(unit_ids), 300):
            batch = unit_ids[offset:offset + 300]
            placeholders = ",".join("?" for _ in batch)
            rows.extend(connection.execute(
                "SELECT DISTINCT s.source_id,s.canonical_name,s.provider,s.version,s.license_id,s.license_url,"
                "s.attribution_text,l.lexical_unit_id FROM reference_source_links l "
                "JOIN reference_sources s ON s.source_id=l.source_id "
                f"WHERE l.lexical_unit_id IN ({placeholders}) ORDER BY s.source_id LIMIT ?",
                (*batch, MAX_EVIDENCE - len(rows)),
            ).fetchall())
            if len(rows) >= MAX_EVIDENCE:
                break
        return [
            {
                "sourceId": row["source_id"], "name": row["canonical_name"],
                "provider": row["provider"], "version": row["version"],
                "license": row["license_id"], "licenseUrl": row["license_url"],
                "attribution": row["attribution_text"], "lexicalUnitId": row["lexical_unit_id"],
            }
            for row in rows
        ]

    @staticmethod
    def _frequency_row(row: sqlite3.Row, *, raw_surface: bool = False) -> dict[str, Any]:
        metric = str(row["metric_type"])
        labels = {
            "SOURCE_LEARNER_RANK": "Learner rank",
            "SOURCE_FORM_RANK": "Source form rank",
            "SOURCE_NGRAM_FREQUENCY": "Raw corpus count",
            "DERIVED_LEMMA_FREQUENCY": "Derived lemma frequency",
            "DERIVED_LEMMA_RANK": "Derived lemma rank",
            "ZIPF_FREQUENCY": "Zipf estimate",
        }
        return {
            "lexicalUnitId": row["matched_lexical_unit_id"] if raw_surface else row["lexical_unit_id"],
            "metricType": metric,
            "label": labels.get(metric, metric.replace("_", " ").title()),
            "evidenceKind": "RAW_SOURCE" if raw_surface else row["evidence_kind"],
            "sourceId": row["source_id"],
            "sourceName": row["canonical_name"],
            "provider": row["provider"],
            "sourceVersion": row["source_version"],
            "rank": row["rank"],
            "rawCount": row["raw_count"],
            "frequencyPerMillion": None if raw_surface else row["frequency_per_million"],
            "zipfScore": None if raw_surface else row["zipf_score"],
            "method": None if raw_surface else row["method"],
            "methodVersion": None if raw_surface else row["method_version"],
            "scope": "SOURCE_SURFACE_FORM" if metric == "SOURCE_FORM_RANK" else (
                "DERIVED_LEMMA" if metric.startswith("DERIVED_LEMMA") else "REFERENCE_UNIT"
            ),
            "surfaceForm": row["raw_form"] if raw_surface else None,
        }

    def _frequency_for_units(self, connection: sqlite3.Connection, unit_ids: list[str]) -> list[dict[str, Any]]:
        if not unit_ids:
            return []
        rows, raw_rows = [], []
        for offset in range(0, len(unit_ids), 300):
            batch = unit_ids[offset:offset + 300]
            placeholders = ",".join("?" for _ in batch)
            if len(rows) < MAX_EVIDENCE:
                rows.extend(connection.execute(
                    "SELECT f.*,s.canonical_name,s.provider,s.version AS source_version "
                    "FROM reference_frequency_observations f JOIN reference_sources s ON s.source_id=f.source_id "
                    f"WHERE f.lexical_unit_id IN ({placeholders}) "
                    "ORDER BY f.lexical_unit_id,f.source_id,f.metric_type,f.rank LIMIT ?",
                    (*batch, MAX_EVIDENCE - len(rows)),
                ).fetchall())
            if len(raw_rows) < MAX_EVIDENCE:
                raw_rows.extend(connection.execute(
                    "SELECT r.metric_type,r.source_id,r.raw_form,r.raw_count,r.rank,r.matched_lexical_unit_id,"
                    "s.canonical_name,s.provider,s.version AS source_version,NULL AS evidence_kind,"
                    "NULL AS frequency_per_million,NULL AS zipf_score,NULL AS method,NULL AS method_version "
                    "FROM reference_raw_observations r JOIN reference_sources s ON s.source_id=r.source_id "
                    f"WHERE r.matched_lexical_unit_id IN ({placeholders}) AND r.metric_type='SOURCE_FORM_RANK' "
                    "ORDER BY r.rank LIMIT ?",
                    (*batch, MAX_EVIDENCE - len(raw_rows)),
                ).fetchall())
            if len(rows) >= MAX_EVIDENCE and len(raw_rows) >= MAX_EVIDENCE:
                break
        return ([self._frequency_row(row) for row in rows] + [
            self._frequency_row(row, raw_surface=True) for row in raw_rows
        ])[:MAX_EVIDENCE]

    def _forms_for_unit(self, connection: sqlite3.Connection, unit_id: str) -> list[dict[str, Any]]:
        rows = connection.execute(
            "SELECT f.display_form,f.normalized_form,l.form_type,l.orthographic_status,l.morphology_json,"
            "l.source_id,s.canonical_name,s.version FROM reference_form_links l "
            "JOIN reference_forms f ON f.id=l.form_id JOIN reference_sources s ON s.source_id=l.source_id "
            "WHERE l.lexical_unit_id=? ORDER BY f.normalized_form,f.display_form LIMIT 40",
            (unit_id,),
        ).fetchall()
        return [
            {
                "displayForm": row["display_form"], "normalizedForm": row["normalized_form"],
                "formType": row["form_type"], "orthographicStatus": row["orthographic_status"],
                "morphology": _json(row["morphology_json"], {}), "sourceId": row["source_id"],
                "sourceName": row["canonical_name"], "sourceVersion": row["version"],
            }
            for row in rows
        ]

    def _expressions_for_lemma(self, connection: sqlite3.Connection, normalized: str) -> list[dict[str, Any]]:
        rows = connection.execute(
            "SELECT DISTINCT u.id,u.stable_key,u.unit_type,u.canonical_form,u.part_of_speech "
            "FROM reference_mwe_components c JOIN reference_lexical_units u ON u.id=c.lexical_unit_id "
            "WHERE c.lemma_constraint=? OR c.normalized_form=? "
            "ORDER BY u.unit_type,u.normalized_form LIMIT 30",
            (normalized, normalized),
        ).fetchall()
        return [
            {"id": row["id"], "stableKey": row["stable_key"], "unitType": row["unit_type"],
             "canonicalForm": row["canonical_form"], "partOfSpeech": row["part_of_speech"]}
            for row in rows
        ]

    def get_reference_profile(self, lemma: VocabularyLemmaIdentity) -> dict[str, Any]:
        health = self.health()
        if not health.get("available"):
            return {
                "reference": {"available": False, "health": health},
                "resolution": {"status": "UNAVAILABLE", "ruleVersion": self.resolver.rule_version, "candidates": []},
            }
        resolution_result = self.resolver.resolve(lemma)
        resolution = self._resolution_payload(resolution_result)
        unit_ids = [item.lexical_unit.id for item in resolution_result.candidates]
        reference: dict[str, Any] = {
            "available": True,
            "serviceVersion": self.service_version,
            "unit": _unit_payload(resolution_result.candidates[0].lexical_unit)
            if resolution_result.status.value == "MATCHED" else None,
            "forms": [], "frequencyEvidence": [], "cefrEvidence": [],
            "expressions": [], "sources": [],
        }
        with self._connect() as connection:
            reference["frequencyEvidence"] = self._frequency_for_units(connection, unit_ids)
            reference["sources"] = self._sources_for_units(connection, unit_ids)
            if resolution_result.status.value == "MATCHED":
                unit = resolution_result.candidates[0].lexical_unit
                reference["forms"] = self._forms_for_unit(connection, unit.id)
                reference["expressions"] = self._expressions_for_lemma(connection, unit.normalized_form)
                cefr_rows = connection.execute(
                    "SELECT e.*,s.canonical_name,s.provider,s.version AS source_version "
                    "FROM reference_cefr_evidence e JOIN reference_sources s ON s.source_id=e.source_id "
                    "WHERE e.lexical_unit_id=? ORDER BY e.evidence_type,e.source_id LIMIT 20",
                    (unit.id,),
                ).fetchall()
                reference["cefrEvidence"] = [
                    {
                        "evidenceType": row["evidence_type"], "bestLevel": row["best_level"],
                        "confidence": row["confidence"], "sourceId": row["source_id"],
                        "sourceName": row["canonical_name"], "provider": row["provider"],
                        "sourceVersion": row["source_version"], "method": row["method"],
                        "methodVersion": row["method_version"],
                    }
                    for row in cefr_rows
                ]
        reference["cefrAvailable"] = bool(reference["cefrEvidence"])
        return {"reference": reference, "resolution": resolution}

    def get_learner_glosses(
        self, *, language_code: str, lemma_normalized: str,
        part_of_speech: str | None, user_lemma_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return KELLY's bounded learner gloss evidence without treating it as a sense."""
        if not self._available():
            return []
        identity = VocabularyLemmaIdentity(
            language_code, lemma_normalized, part_of_speech, user_lemma_id,
        )
        resolution = self.resolver.resolve(identity)
        unit_ids = [candidate.lexical_unit.id for candidate in resolution.candidates[:MAX_CANDIDATES]]
        if not unit_ids:
            return []
        placeholders = ",".join("?" for _ in unit_ids)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT r.raw_evidence_json,r.source_local_id,r.matched_lexical_unit_id,"
                "s.source_id,s.canonical_name,s.provider,s.version,s.license_id,s.license_url,"
                "s.attribution_text FROM reference_raw_observations r "
                "JOIN reference_sources s ON s.source_id=r.source_id "
                f"WHERE r.matched_lexical_unit_id IN ({placeholders}) "
                "AND r.source_id=? AND r.metric_type='SOURCE_LEARNER_RANK' "
                "ORDER BY r.rank,r.id LIMIT 8",
                (*unit_ids, KELLY_SOURCE_ID),
            ).fetchall()
        result = []
        seen = set()
        for row in rows:
            evidence = _json(row["raw_evidence_json"], {})
            value = str(evidence.get("englishGloss") or "").strip()
            if not value or value.casefold() in seen:
                continue
            seen.add(value.casefold())
            result.append({
                "targetLocale": "en",
                "value": value,
                "type": "SOURCE_GLOSS",
                "method": "SOURCE_GLOSS",
                "scope": "LEMMA_LEVEL",
                "role": evidence.get("englishGlossRole") or "KELLY_TRANSLATION_NOT_DICTIONARY_SENSE",
                "sourceLocalId": row["source_local_id"],
                "lexicalUnitId": row["matched_lexical_unit_id"],
                "source": {
                    "id": row["source_id"], "name": row["canonical_name"],
                    "provider": row["provider"], "version": row["version"],
                    "license": row["license_id"], "licenseUrl": row["license_url"],
                    "attribution": row["attribution_text"],
                },
            })
        return result

    def generation_facts(
        self, lemmas: Iterable[VocabularyLemmaIdentity], *, limit: int = 12
    ) -> dict[str, Any]:
        """Return a bounded batch for generator context; never returns user history."""
        items = list(lemmas)[:max(0, min(int(limit), 20))]
        health = self.health()
        if not health.get("available"):
            return {"available": False, "health": health, "items": []}
        resolutions = self.resolver.resolve_many(items)
        matched_ids = [
            result.candidates[0].lexical_unit.id
            for result in resolutions if result.status.value == "MATCHED"
        ]
        with self._connect() as connection:
            evidence = self._frequency_for_units(connection, matched_ids)
        by_unit: dict[str, list[dict[str, Any]]] = {}
        for row in evidence:
            by_unit.setdefault(str(row["lexicalUnitId"]), []).append(row)
        result_items = []
        for identity, resolution in zip(items, resolutions):
            public_resolution = self._resolution_payload(resolution)
            unit_id = (
                resolution.candidates[0].lexical_unit.id
                if resolution.status.value == "MATCHED" else None
            )
            result_items.append({
                "userLemmaId": identity.lemma_id,
                "resolution": public_resolution,
                "unit": _unit_payload(resolution.candidates[0].lexical_unit)
                if unit_id else None,
                "frequencyEvidence": by_unit.get(str(unit_id), [])[:12] if unit_id else [],
            })
        return {
            "available": True,
            "schemaVersion": health.get("schemaVersion"),
            "referenceFingerprint": health.get("referenceFingerprint"),
            "serviceVersion": self.service_version,
            "resolverRuleVersion": self.resolver.rule_version,
            "items": result_items,
        }

    def _expression_candidates(
        self, connection: sqlite3.Connection, first_components: list[str]
    ) -> list[dict[str, Any]]:
        if not first_components:
            return []
        unit_map: dict[str, sqlite3.Row] = {}
        for offset in range(0, len(first_components), 300):
            batch = first_components[offset:offset + 300]
            placeholders = ",".join("?" for _ in batch)
            for row in connection.execute(
                "SELECT DISTINCT u.id,u.stable_key,u.unit_type,u.canonical_form,u.part_of_speech "
                "FROM reference_mwe_components first JOIN reference_lexical_units u ON u.id=first.lexical_unit_id "
                f"WHERE first.position=0 AND first.normalized_form IN ({placeholders}) "
                "ORDER BY u.id LIMIT 2000",
                tuple(batch),
            ).fetchall():
                unit_map[str(row["id"])] = row
                if len(unit_map) >= 2000:
                    break
            if len(unit_map) >= 2000:
                break
        unit_rows = list(unit_map.values())
        if not unit_rows:
            return []
        units = {row["id"]: dict(row) for row in unit_rows}
        ids = list(units)
        for offset in range(0, len(ids), 300):
            batch = ids[offset:offset + 300]
            placeholders = ",".join("?" for _ in batch)
            for row in connection.execute(
                "SELECT * FROM reference_mwe_components "
                f"WHERE lexical_unit_id IN ({placeholders}) ORDER BY lexical_unit_id,position",
                tuple(batch),
            ).fetchall():
                units[row["lexical_unit_id"]].setdefault("components", []).append(dict(row))
        sources = self._sources_for_units(connection, ids)
        by_unit: dict[str, list[dict[str, Any]]] = {}
        for source in sources:
            by_unit.setdefault(source.pop("lexicalUnitId"), []).append(source)
        for unit_id, unit in units.items():
            unit["sources"] = by_unit.get(unit_id, [])
        return list(units.values())

    @staticmethod
    def _component_match(component: dict[str, Any], token: dict[str, Any]) -> str | None:
        if token.get("tokenKind") != "WORD":
            return None
        token_surface = normalize_reference_lookup(token.get("surface") or token.get("normalizedLookup") or "")
        token_lemma = normalize_reference_lookup(token.get("selectedLemmaNormalized") or "")
        surface_match = token_surface == component["normalized_form"]
        lemma_constraint = normalize_reference_lookup(component.get("lemma_constraint") or "")
        lemma_match = bool(lemma_constraint and token_lemma == lemma_constraint)
        pos_constraint = str(component.get("pos_constraint") or "").upper()
        if pos_constraint and str(token.get("partOfSpeech") or token.get("selectedLemmaPos") or "").upper() != pos_constraint:
            return None
        if lemma_match:
            return "LEMMA_CONSTRAINT"
        if surface_match:
            return "SURFACE_CONSTRAINT"
        return None

    def _match_components(
        self, components: list[dict[str, Any]], tokens: list[dict[str, Any]], start: int
    ) -> tuple[int, list[str]] | None:
        def walk(component_index: int, token_index: int, bases: list[str]) -> tuple[int, list[str]] | None:
            if component_index >= len(components):
                return token_index, bases
            component = components[component_index]
            if component.get("optional"):
                skipped = walk(component_index + 1, token_index, bases + ["OPTIONAL_SKIPPED"])
                matched_basis = self._component_match(component, tokens[token_index]) if token_index < len(tokens) else None
                consumed = walk(component_index + 1, token_index + 1, bases + [matched_basis]) if matched_basis else None
                candidates = [item for item in (skipped, consumed) if item]
                return max(candidates, key=lambda item: item[0]) if candidates else None
            if token_index >= len(tokens):
                return None
            basis = self._component_match(component, tokens[token_index])
            return walk(component_index + 1, token_index + 1, bases + [basis]) if basis else None

        return walk(0, start, [])

    def detect_expressions(
        self, *, raw_text: str, sentences: list[dict[str, Any]], tokens: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        if not self._available():
            return []
        lexical_first = sorted({
            normalize_reference_lookup(token.get("surface") or token.get("normalizedLookup") or "")
            for token in tokens if token.get("tokenKind") == "WORD"
        })
        with self._connect() as connection:
            candidates = self._expression_candidates(connection, lexical_first)
        candidates_by_first: dict[str, list[dict[str, Any]]] = {}
        for candidate in candidates:
            components = candidate.get("components") or []
            if components:
                candidates_by_first.setdefault(components[0]["normalized_form"], []).append(candidate)
        tokens_by_sentence: dict[str, list[dict[str, Any]]] = {}
        for token in sorted(tokens, key=lambda item: (item.get("tokenOrder", 0), item.get("id", ""))):
            tokens_by_sentence.setdefault(str(token.get("sentenceId") or ""), []).append(token)
        occurrences: list[dict[str, Any]] = []
        for sentence in sentences:
            sentence_id = str(sentence.get("id") or "")
            sentence_tokens = tokens_by_sentence.get(sentence_id, [])
            for start, token in enumerate(sentence_tokens):
                first = normalize_reference_lookup(token.get("surface") or token.get("normalizedLookup") or "")
                for candidate in candidates_by_first.get(first, []):
                    match = self._match_components(candidate["components"], sentence_tokens, start)
                    if not match or match[0] <= start:
                        continue
                    end_exclusive, bases = match
                    matched_tokens = sentence_tokens[start:end_exclusive]
                    start_offset = int(matched_tokens[0]["sourceStart"])
                    end_offset = int(matched_tokens[-1]["sourceEnd"])
                    occurrences.append({
                        "referenceLexicalUnitKey": candidate["stable_key"],
                        "referenceLexicalUnitId": candidate["id"],
                        "canonicalForm": candidate["canonical_form"],
                        "unitType": candidate["unit_type"],
                        "sentenceId": sentence_id,
                        "startToken": matched_tokens[0].get("id"),
                        "endToken": matched_tokens[-1].get("id"),
                        "startTokenOrder": matched_tokens[0].get("tokenOrder"),
                        "endTokenOrder": matched_tokens[-1].get("tokenOrder"),
                        "exactSourceSpan": {"start": start_offset, "end": end_offset, "offsetUnit": "UNICODE_CODE_POINT"},
                        "surfaceText": raw_text[start_offset:end_offset],
                        "matchBasis": bases,
                        "ambiguous": any(token.get("ambiguityState") == "AMBIGUOUS" for token in matched_tokens),
                        "detectorVersion": self.detector_version,
                        "sourceProvenance": candidate.get("sources", []),
                        "selectionState": "SOURCE_SUPPORTED",
                    })
        span_groups: dict[tuple[str, Any, Any], list[dict[str, Any]]] = {}
        for occurrence in occurrences:
            span_groups.setdefault((occurrence["sentenceId"], occurrence["startToken"], occurrence["endToken"]), []).append(occurrence)
        for group in span_groups.values():
            if len(group) > 1:
                for occurrence in group:
                    occurrence["ambiguous"] = True
        for occurrence in occurrences:
            overlaps = [
                other for other in occurrences
                if other["sentenceId"] == occurrence["sentenceId"]
                and other is not occurrence
                and other["exactSourceSpan"]["start"] < occurrence["exactSourceSpan"]["end"]
                and occurrence["exactSourceSpan"]["start"] < other["exactSourceSpan"]["end"]
            ]
            own_length = occurrence["exactSourceSpan"]["end"] - occurrence["exactSourceSpan"]["start"]
            occurrence["selectionState"] = "LONGEST_PREFERRED" if not any(
                other["exactSourceSpan"]["end"] - other["exactSourceSpan"]["start"] > own_length
                for other in overlaps
            ) else "OVERLAP_RETAINED"
        return sorted(occurrences, key=lambda item: (item["sentenceId"], item["startTokenOrder"], -item["endTokenOrder"], item["referenceLexicalUnitKey"]))

    def text_reference_profile(
        self, *, language_code: str, raw_text: str,
        sentences: list[dict[str, Any]], tokens: list[dict[str, Any]],
    ) -> dict[str, Any]:
        health = self.health()
        if not health.get("available"):
            return {"available": False, "profileVersion": self.profile_version, "health": health,
                    "resolutionSummary": {"matched": 0, "ambiguous": 0, "unmatched": 0},
                    "frequencyProfile": {"learnerRankAvailable": False, "items": []}, "expressions": []}
        unique: dict[str, VocabularyLemmaIdentity] = {}
        for token in tokens:
            lemma_id = token.get("selectedLemmaId")
            normalized = token.get("selectedLemmaNormalized")
            if lemma_id and normalized:
                unique[str(lemma_id)] = VocabularyLemmaIdentity(
                    language_code, str(normalized), token.get("selectedLemmaPos") or token.get("partOfSpeech"), str(lemma_id)
                )
        identities = list(unique.values())
        resolutions = self.resolver.resolve_many(identities)
        resolution_payloads = [self._resolution_payload(item) for item in resolutions]
        matched_ids = [
            result.candidates[0].lexical_unit.id
            for result in resolutions if result.status.value == "MATCHED"
        ]
        with self._connect() as connection:
            frequency = self._frequency_for_units(connection, matched_ids)
        expressions = self.detect_expressions(raw_text=raw_text, sentences=sentences, tokens=tokens)
        learner_ranks = [item for item in frequency if item["metricType"] == "SOURCE_LEARNER_RANK" and item["rank"]]
        bands = {"1-500": 0, "501-1000": 0, "1001-2000": 0, "2001-4000": 0, "4001-6000": 0}
        for item in learner_ranks:
            rank = int(item["rank"])
            for label, low, high in (("1-500",1,500),("501-1000",501,1000),("1001-2000",1001,2000),("2001-4000",2001,4000),("4001-6000",4001,6000)):
                if low <= rank <= high:
                    bands[label] += 1
                    break
        return {
            "available": True,
            "profileVersion": self.profile_version,
            "resolverRuleVersion": self.resolver.rule_version,
            "detectorVersion": self.detector_version,
            "referenceFingerprint": health.get("referenceFingerprint"),
            "schemaVersion": health.get("schemaVersion"),
            "resolutionSummary": {
                "matched": sum(item["status"] == "MATCHED" for item in resolution_payloads),
                "ambiguous": sum(item["status"] == "AMBIGUOUS" for item in resolution_payloads),
                "unmatched": sum(item["status"] == "UNMATCHED" for item in resolution_payloads),
                "uniqueUserLemmas": len(identities),
            },
            "resolutions": [
                {"userLemmaId": identity.lemma_id, **payload}
                for identity, payload in zip(identities, resolution_payloads)
            ],
            "frequencyProfile": {
                "learnerRankAvailable": bool(learner_ranks),
                "learnerRankDistribution": bands,
                "items": frequency[:MAX_EVIDENCE],
                "label": "Reference learner-rank and source-frequency profile (not user coverage)",
            },
            "expressions": expressions,
            "idiomOccurrences": sum(item["unitType"] == "IDIOM" for item in expressions),
            "mweOccurrences": len(expressions),
            "cefr": {"available": bool(health.get("cefrAvailable")), "value": None if not health.get("cefrAvailable") else "SOURCE_EVIDENCE_AVAILABLE"},
        }


__all__ = [
    "EXPRESSION_DETECTOR_VERSION",
    "REFERENCE_PROFILE_VERSION",
    "REFERENCE_SERVICE_VERSION",
    "ReferenceLexiconService",
]
