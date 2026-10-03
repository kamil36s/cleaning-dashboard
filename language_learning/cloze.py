"""Deterministic Phase 9 Cloze practice over frozen shared and reference contexts."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any
import unicodedata

from .analysis.base import normalize_lookup
from .errors import LanguageConflictError, LanguageNotFoundError, LanguageValidationError
from .reference_core.schema import REFERENCE_SCHEMA_VERSION
from .store import LanguageStore, canonical_json, utc_now


FAST_TRACK_VERSION = "language.cloze-fast-track/v1"
TARGET_SELECTION_VERSION = "language.cloze-target-selection/v1"
SHARED_TARGET_SELECTION_VERSION = "language.cloze-target-selection/v2"
SENTENCE_SELECTION_VERSION = "language.cloze-sentence-selection/v2"
SHARED_CONTEXT_SELECTION_VERSION = "language.cloze-context-selection/v1"
DISTRACTOR_VERSION = "language.cloze-distractors/v1"
SHARED_DISTRACTOR_VERSION = "language.cloze-distractors/v2"
ITEM_VERSION = "language.cloze-item/v2"
SHARED_ITEM_VERSION = "language.cloze-item/v3"
EVIDENCE_VERSION = "language.cloze-evidence/v1"
OPTION_PRESENTATION_VERSION = "language.cloze-option-presentation/v1"
ANSWER_NORMALIZATION_VERSION = "language.cloze-answer-normalization/v1"
LEGACY_NORMALIZATION_VERSION = "language.cloze-answer-normalization/legacy-multiple-choice-v1"
KELLY_SOURCE_ID = "uio-norwegian-kelly-shu-wang"
MAX_TYPED_ANSWER_LENGTH = 200

FAST_TRACK_BANDS = {
    "FAST_TRACK_1": (1, 500),
    "FAST_TRACK_2": (501, 1000),
    "FAST_TRACK_3": (1001, 2000),
    "FAST_TRACK_4": (2001, 4000),
    "FAST_TRACK_5": (4001, 6000),
}


class ClosingReadConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def _hash_order(*parts: Any) -> str:
    return hashlib.sha256("\x1f".join(map(str, parts)).encode("utf-8")).hexdigest()


def _fingerprint(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _timestamp_sort(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def normalize_typed_answer(value: str) -> str:
    """Phase 9 exact-surface normalization: trim, NFC, then casefold only."""
    return unicodedata.normalize("NFC", str(value).strip()).casefold()


def _unsafe_context(value: str) -> bool:
    if not value or len(value) > 5000:
        return True
    if any(ord(char) < 32 and char not in "\t\n\r" for char in value):
        return True
    return bool(re.search(r"<\s*/?\s*(script|style|iframe|object|embed|img|svg)\b", value, re.IGNORECASE))


class ClozeReferenceStore:
    """Bounded read-only reference access owned by Cloze practice."""

    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path)

    def _connect(self) -> sqlite3.Connection:
        if not self.database_path.is_file():
            raise LanguageConflictError(
                "The Language reference database is unavailable", code="cloze_reference_unavailable"
            )
        connection = sqlite3.connect(
            f"file:{self.database_path.as_posix()}?mode=ro",
            uri=True,
            timeout=10,
            factory=ClosingReadConnection,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def health(self) -> dict[str, Any]:
        try:
            with self._connect() as connection:
                version = int(connection.execute(
                    "SELECT COALESCE(MAX(version),0) FROM reference_schema_migrations"
                ).fetchone()[0])
                sentences = int(connection.execute("SELECT COUNT(*) FROM reference_sentences").fetchone()[0])
            return {
                "status": ("READY" if version == REFERENCE_SCHEMA_VERSION else
                           "SCHEMA_TOO_OLD" if version < REFERENCE_SCHEMA_VERSION else
                           "UNSUPPORTED_SCHEMA"),
                "schemaVersion": version,
                "sentences": sentences,
            }
        except (sqlite3.Error, LanguageConflictError):
            return {"status": "UNAVAILABLE", "schemaVersion": None, "sentences": 0}

    def targets(self, minimum: int = 1, maximum: int = 6000) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT u.id,u.stable_key,u.canonical_form,u.normalized_form,u.part_of_speech,MIN(f.rank) rank "
                "FROM reference_frequency_observations f "
                "JOIN reference_lexical_units u ON u.id=f.lexical_unit_id "
                "WHERE f.source_id=? AND f.metric_type='SOURCE_LEARNER_RANK' "
                "AND f.rank BETWEEN ? AND ? AND u.unit_type='LEMMA' "
                "GROUP BY u.id,u.stable_key,u.canonical_form,u.normalized_form,u.part_of_speech "
                "ORDER BY rank,u.stable_key",
                (KELLY_SOURCE_ID, minimum, maximum),
            ).fetchall()
        return [dict(row) for row in rows]

    def playable_target_ids(self) -> set[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT DISTINCT lexical_unit_id FROM ("
                "SELECT o.lexical_unit_id,o.sentence_id FROM reference_sentence_occurrences o "
                "JOIN reference_sentences s ON s.id=o.sentence_id AND s.usable=1 "
                "WHERE o.resolution_status='MATCHED' AND o.lexical_unit_id IS NOT NULL "
                "AND EXISTS (SELECT 1 FROM reference_sentence_translations t "
                "WHERE t.sentence_id=o.sentence_id AND t.target_language_code='en') "
                "GROUP BY o.lexical_unit_id,o.sentence_id HAVING COUNT(*)=1)"
            ).fetchall()
        return {str(row[0]) for row in rows}

    def playable_targets(self, minimum: int = 1, maximum: int = 6000) -> list[dict[str, Any]]:
        playable = self.playable_target_ids()
        return [target for target in self.targets(minimum, maximum) if target["id"] in playable]

    def track_counts(self) -> dict[str, dict[str, int]]:
        targets = self.targets()
        playable = self.playable_target_ids()
        result: dict[str, dict[str, int]] = {}
        for key, (minimum, maximum) in FAST_TRACK_BANDS.items():
            band = [target for target in targets if minimum <= int(target["rank"]) <= maximum]
            result[key] = {
                "targets": len(band),
                "playableTargets": sum(1 for target in band if target["id"] in playable),
            }
        return result

    def sentence_candidates(self, lexical_unit_id: str, *, limit: int = 48) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT s.*,o.start_offset,o.end_offset,o.surface_form,o.normalized_form "
                "FROM reference_sentence_occurrences o JOIN reference_sentences s ON s.id=o.sentence_id "
                "WHERE o.lexical_unit_id=? AND o.resolution_status='MATCHED' AND s.usable=1 "
                "AND (SELECT COUNT(*) FROM reference_sentence_occurrences x "
                "WHERE x.sentence_id=o.sentence_id AND x.lexical_unit_id=o.lexical_unit_id "
                "AND x.resolution_status='MATCHED')=1 "
                "ORDER BY s.quality_score DESC,s.source_sentence_id,s.id LIMIT ?",
                (lexical_unit_id, max(1, min(int(limit), 100))),
            ).fetchall()
            items = [dict(row) for row in rows]
            if not items:
                return []
            ids = [item["id"] for item in items]
            placeholders = ",".join("?" for _ in ids)
            surrounding = connection.execute(
                "SELECT o.sentence_id,o.lexical_unit_id,u.stable_key,o.resolution_status "
                "FROM reference_sentence_occurrences o LEFT JOIN reference_lexical_units u "
                "ON u.id=o.lexical_unit_id "
                f"WHERE o.sentence_id IN ({placeholders}) ORDER BY o.sentence_id,o.occurrence_index",
                ids,
            ).fetchall()
            translations = connection.execute(
                "SELECT sentence_id,target_language_code,translation_sentence_id,translation_text,"
                "license_id,source_url FROM reference_sentence_translations "
                f"WHERE sentence_id IN ({placeholders}) AND target_language_code='en' "
                "ORDER BY sentence_id,CAST(translation_sentence_id AS INTEGER),translation_sentence_id",
                ids,
            ).fetchall()
        by_sentence: dict[str, list[dict[str, Any]]] = {item["id"]: [] for item in items}
        for row in surrounding:
            by_sentence[str(row["sentence_id"])].append(dict(row))
        translation_by_sentence: dict[str, dict[str, Any]] = {}
        for row in translations:
            translation_by_sentence.setdefault(str(row["sentence_id"]), dict(row))
        for item in items:
            item["surrounding"] = by_sentence[item["id"]]
            item["translation"] = translation_by_sentence.get(item["id"])
        return items

    def target_morphology(self, lexical_unit_id: str, normalized_form: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT fl.morphology_json,fl.form_type FROM reference_form_links fl "
                "JOIN reference_forms f ON f.id=fl.form_id WHERE fl.lexical_unit_id=? "
                "AND f.normalized_form=? ORDER BY fl.source_id,fl.source_local_id LIMIT 1",
                (lexical_unit_id, normalized_form),
            ).fetchone()
        if row is None:
            return {}
        try:
            morphology = json.loads(row["morphology_json"] or "{}")
        except json.JSONDecodeError:
            morphology = {}
        morphology["formType"] = row["form_type"]
        return morphology

    def sentence_translation(self, source_id: str, source_sentence_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT t.target_language_code,t.translation_sentence_id,t.translation_text,t.license_id,t.source_url "
                "FROM reference_sentences s JOIN reference_sentence_translations t ON t.sentence_id=s.id "
                "WHERE s.source_id=? AND s.source_sentence_id=? AND t.target_language_code='en' "
                "ORDER BY CAST(t.translation_sentence_id AS INTEGER),t.translation_sentence_id LIMIT 1",
                (source_id, source_sentence_id),
            ).fetchone()
        return dict(row) if row else None

    def distractor_rows(self, target: dict[str, Any], expected_normalized: str) -> list[dict[str, Any]]:
        pos = target.get("part_of_speech")
        if not pos:
            return []
        with self._connect() as connection:
            rows = connection.execute(
                "WITH ranked AS (SELECT lexical_unit_id,MIN(rank) rank FROM reference_frequency_observations "
                "WHERE source_id=? AND metric_type='SOURCE_LEARNER_RANK' GROUP BY lexical_unit_id) "
                "SELECT u.id,u.stable_key,u.canonical_form,u.part_of_speech,r.rank,f.display_form,"
                "f.normalized_form,fl.morphology_json,fl.form_type FROM ranked r "
                "JOIN reference_lexical_units u ON u.id=r.lexical_unit_id "
                "JOIN reference_form_links fl ON fl.lexical_unit_id=u.id "
                "JOIN reference_forms f ON f.id=fl.form_id "
                "WHERE u.part_of_speech=? AND u.id<>? AND f.normalized_form<>? "
                "AND r.rank BETWEEN ? AND ? ORDER BY ABS(r.rank-?),u.stable_key,f.normalized_form LIMIT 4000",
                (
                    KELLY_SOURCE_ID, pos, target["id"], expected_normalized,
                    max(1, int(target["rank"]) - 900), min(6000, int(target["rank"]) + 900),
                    int(target["rank"]),
                ),
            ).fetchall()
        return [dict(row) for row in rows]

    def targets_by_ids(self, lexical_unit_ids: list[str]) -> dict[str, dict[str, Any]]:
        ids = sorted({str(value) for value in lexical_unit_ids if value})[:1000]
        if not ids:
            return {}
        result: dict[str, dict[str, Any]] = {}
        with self._connect() as connection:
            for offset in range(0, len(ids), 300):
                batch = ids[offset:offset + 300]
                placeholders = ",".join("?" for _ in batch)
                rows = connection.execute(
                    "SELECT u.id,u.stable_key,u.canonical_form,u.normalized_form,u.part_of_speech,"
                    "MIN(CASE WHEN f.source_id=? AND f.metric_type='SOURCE_LEARNER_RANK' THEN f.rank END) rank "
                    "FROM reference_lexical_units u LEFT JOIN reference_frequency_observations f "
                    "ON f.lexical_unit_id=u.id WHERE u.id IN (" + placeholders + ") "
                    "GROUP BY u.id,u.stable_key,u.canonical_form,u.normalized_form,u.part_of_speech",
                    (KELLY_SOURCE_ID, *batch),
                ).fetchall()
                result.update((str(row["id"]), dict(row)) for row in rows)
        return result

    def sentence_candidates_batch(
        self, lexical_unit_ids: list[str], *, limit_per_target: int = 48,
    ) -> dict[str, list[dict[str, Any]]]:
        ids = sorted({str(value) for value in lexical_unit_ids if value})[:500]
        result: dict[str, list[dict[str, Any]]] = {value: [] for value in ids}
        if not ids:
            return result
        bounded = max(1, min(int(limit_per_target), 100))
        with self._connect() as connection:
            selected: list[dict[str, Any]] = []
            for offset in range(0, len(ids), 200):
                batch = ids[offset:offset + 200]
                placeholders = ",".join("?" for _ in batch)
                rows = connection.execute(
                    "WITH candidates AS (SELECT o.lexical_unit_id,s.*,o.start_offset,o.end_offset,"
                    "o.surface_form,o.normalized_form,ROW_NUMBER() OVER (PARTITION BY o.lexical_unit_id "
                    "ORDER BY s.quality_score DESC,s.source_sentence_id,s.id) AS candidate_order "
                    "FROM reference_sentence_occurrences o JOIN reference_sentences s ON s.id=o.sentence_id "
                    "WHERE o.lexical_unit_id IN (" + placeholders + ") AND o.resolution_status='MATCHED' "
                    "AND s.usable=1 AND (SELECT COUNT(*) FROM reference_sentence_occurrences x "
                    "WHERE x.sentence_id=o.sentence_id AND x.lexical_unit_id=o.lexical_unit_id "
                    "AND x.resolution_status='MATCHED')=1) "
                    "SELECT * FROM candidates WHERE candidate_order<=? "
                    "ORDER BY lexical_unit_id,candidate_order",
                    (*batch, bounded),
                ).fetchall()
                selected.extend(dict(row) for row in rows)
            if not selected:
                return result
            sentence_ids = sorted({str(row["id"]) for row in selected})
            surrounding_by_sentence: dict[str, list[dict[str, Any]]] = {value: [] for value in sentence_ids}
            translations_by_sentence: dict[str, dict[str, Any]] = {}
            for offset in range(0, len(sentence_ids), 300):
                batch = sentence_ids[offset:offset + 300]
                placeholders = ",".join("?" for _ in batch)
                surrounding = connection.execute(
                    "SELECT o.sentence_id,o.lexical_unit_id,u.stable_key,o.resolution_status "
                    "FROM reference_sentence_occurrences o LEFT JOIN reference_lexical_units u "
                    "ON u.id=o.lexical_unit_id WHERE o.sentence_id IN (" + placeholders + ") "
                    "ORDER BY o.sentence_id,o.occurrence_index",
                    batch,
                ).fetchall()
                for row in surrounding:
                    surrounding_by_sentence[str(row["sentence_id"])].append(dict(row))
                translations = connection.execute(
                    "SELECT sentence_id,target_language_code,translation_sentence_id,translation_text,"
                    "license_id,source_url FROM reference_sentence_translations "
                    "WHERE sentence_id IN (" + placeholders + ") AND target_language_code='en' "
                    "ORDER BY sentence_id,CAST(translation_sentence_id AS INTEGER),translation_sentence_id",
                    batch,
                ).fetchall()
                for row in translations:
                    translations_by_sentence.setdefault(str(row["sentence_id"]), dict(row))
        for row in selected:
            row["surrounding"] = surrounding_by_sentence.get(str(row["id"]), [])
            row["translation"] = translations_by_sentence.get(str(row["id"]))
            result.setdefault(str(row["lexical_unit_id"]), []).append(row)
        return result

    def target_morphology_batch(
        self, targets: list[tuple[str, str]],
    ) -> dict[tuple[str, str], dict[str, Any]]:
        pairs = sorted({(str(unit), str(form)) for unit, form in targets if unit and form})[:500]
        if not pairs:
            return {}
        clauses = " OR ".join("(fl.lexical_unit_id=? AND f.normalized_form=?)" for _ in pairs)
        parameters = [value for pair in pairs for value in pair]
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT fl.lexical_unit_id,f.normalized_form,fl.morphology_json,fl.form_type,"
                "ROW_NUMBER() OVER (PARTITION BY fl.lexical_unit_id,f.normalized_form "
                "ORDER BY fl.source_id,fl.source_local_id) AS rn "
                "FROM reference_form_links fl JOIN reference_forms f ON f.id=fl.form_id WHERE " + clauses,
                parameters,
            ).fetchall()
        result: dict[tuple[str, str], dict[str, Any]] = {}
        for row in rows:
            key = (str(row["lexical_unit_id"]), str(row["normalized_form"]))
            if key in result or int(row["rn"]) != 1:
                continue
            try:
                morphology = json.loads(row["morphology_json"] or "{}")
            except json.JSONDecodeError:
                morphology = {}
            morphology["formType"] = row["form_type"]
            result[key] = morphology
        return result

    def distractor_rows_batch(self, targets: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        """Fetch a bounded distractor pool once, then apply each v1 rank window in memory."""
        selected = [row for row in targets if row.get("part_of_speech") and row.get("rank")][:500]
        result: dict[str, list[dict[str, Any]]] = {str(row["id"]): [] for row in selected}
        if not selected:
            return result
        positions = sorted({str(row["part_of_speech"]) for row in selected})
        minimum = max(1, min(int(row["rank"]) for row in selected) - 900)
        maximum = min(6000, max(int(row["rank"]) for row in selected) + 900)
        placeholders = ",".join("?" for _ in positions)
        with self._connect() as connection:
            rows = connection.execute(
                "WITH ranked AS (SELECT lexical_unit_id,MIN(rank) rank FROM reference_frequency_observations "
                "WHERE source_id=? AND metric_type='SOURCE_LEARNER_RANK' GROUP BY lexical_unit_id) "
                "SELECT u.id,u.stable_key,u.canonical_form,u.part_of_speech,r.rank,f.display_form,"
                "f.normalized_form,fl.morphology_json,fl.form_type FROM ranked r "
                "JOIN reference_lexical_units u ON u.id=r.lexical_unit_id "
                "JOIN reference_form_links fl ON fl.lexical_unit_id=u.id "
                "JOIN reference_forms f ON f.id=fl.form_id "
                "WHERE u.part_of_speech IN (" + placeholders + ") AND r.rank BETWEEN ? AND ? "
                "ORDER BY u.part_of_speech,r.rank,u.stable_key,f.normalized_form LIMIT 30000",
                (KELLY_SOURCE_ID, *positions, minimum, maximum),
            ).fetchall()
        pool = [dict(row) for row in rows]
        for target in selected:
            target_id = str(target["id"])
            rank = int(target["rank"])
            result[target_id] = [row for row in pool if (
                str(row["part_of_speech"]) == str(target["part_of_speech"])
                and str(row["id"]) != target_id
                and max(1, rank - 900) <= int(row["rank"]) <= min(6000, rank + 900)
            )]
        return result


class ClozeService:
    def __init__(self, language_service: Any, reference_database_path: str | Path):
        self.language_service = language_service
        self.store: LanguageStore = language_service.store
        self.reference = ClozeReferenceStore(reference_database_path)

    @staticmethod
    def _track(track_key: Any) -> tuple[str, tuple[int, int]]:
        key = str(track_key or "FAST_TRACK_1").upper()
        if key not in FAST_TRACK_BANDS:
            raise LanguageValidationError("trackKey is invalid", details=["trackKey"])
        return key, FAST_TRACK_BANDS[key]

    def _evidence(self, profile_id: str) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for row in self.store.cloze_target_evidence(profile_id):
            key = str(row["reference_target_stable_key"])
            item = result.setdefault(key, {"attemptCount": 0})
            item.update({
                "lastOutcome": row["outcome"], "lastAttemptedAt": row["attempted_at"],
                "knowledgeStatus": row["knowledge_status"], "disposition": row["disposition"],
                "recognition": row["recognition"], "recall": row["recall"],
                "production": row["production"], "totalExposures": row["total_exposures"],
            })
            item["attemptCount"] += 1
        return result

    @staticmethod
    def _priority(target: dict[str, Any], evidence: dict[str, Any] | None) -> tuple[Any, ...]:
        if evidence is None:
            return (0, 1, 1, 1, 0, 0, int(target["rank"]), target["stable_key"])
        scores = [evidence.get(name) for name in ("recognition", "recall", "production")]
        weak = evidence.get("knowledgeStatus") == "LEARNING" or any(
            score is not None and int(score) <= 2 for score in scores
        )
        underexposed = evidence.get("knowledgeStatus") in {"LEARNING", "KNOWN"} and int(
            evidence.get("totalExposures") or 0
        ) < 3
        return (
            1 if evidence.get("lastOutcome") == "INCORRECT" else 2,
            0 if evidence.get("knowledgeStatus") == "LEARNING" else 1,
            0 if weak else 1,
            0 if underexposed else 1,
            int(evidence.get("totalExposures") or 0),
            int(evidence.get("attemptCount") or 0),
            int(target["rank"]),
            target["stable_key"],
        )

    def tracks(self, profile_id: str) -> dict[str, Any]:
        self.language_service.get_profile(profile_id)
        reference_health = self.reference.health()
        items = []
        if reference_health["status"] == "READY":
            counts = self.reference.track_counts()
            targets = self.reference.targets()
            rank_by_key = {row["stable_key"]: int(row["rank"]) for row in targets}
            evidence = self._evidence(profile_id)
            for key, (minimum, maximum) in FAST_TRACK_BANDS.items():
                encountered = sum(1 for stable_key in evidence if minimum <= rank_by_key.get(stable_key, -1) <= maximum)
                items.append({
                    "key": key, "label": key.replace("FAST_TRACK_", "Track "),
                    "rankMin": minimum, "rankMax": maximum, **counts[key], "encountered": encountered,
                    "rankLabel": "KELLY learner rank",
                })
        active = self.store.latest_cloze_session(profile_id)
        shared_targets = self.store.cloze_shared_targets(profile_id)
        shared_ids = [str(row["id"]) for row in shared_targets]
        reader_contexts = self.store.cloze_reader_contexts(profile_id, shared_ids)
        phrasebook_contexts = self.store.cloze_phrasebook_contexts(profile_id, shared_ids)
        available_shared = {
            str(row["selected_lemma_id"]) for row in reader_contexts
            if self._reader_context(row) is not None
        } | {
            str(row["target_lemma_id"]) for row in phrasebook_contexts
            if self._phrasebook_context(row) is not None
        }
        shared_source_targets: dict[str, set[str]] = {"READER": set(), "GENERATED": set(), "PHRASEBOOK": set()}
        for row in reader_contexts:
            context = self._reader_context(row)
            if context is not None:
                shared_source_targets[context["contextType"]].add(str(row["selected_lemma_id"]))
        for row in phrasebook_contexts:
            if self._phrasebook_context(row) is not None:
                shared_source_targets["PHRASEBOOK"].add(str(row["target_lemma_id"]))
        curriculum = self.language_service.curriculum_service.landing(profile_id)
        packs = [{
            "id": pack["id"], "version": pack["version"], "name": pack["name"],
            "fingerprint": pack["fingerprint"],
            "eligibleTargets": int(pack["progress"]["eligibleDenominator"]),
        } for pack in curriculum.get("packs", [])]
        summary = self.store.cloze_summary(profile_id)
        remediation = self.language_service.mistake_intelligence_service.remediation(profile_id)
        summary["mistakeTargets"] = len({
            str(item.get("targetLemmaId")) for item in remediation.get("items") or []
        })
        summary["remediationPolicyVersion"] = remediation.get("policyVersion")
        return {
            "status": "READY", "trackVersion": FAST_TRACK_VERSION, "rankMetric": "SOURCE_LEARNER_RANK",
            "rankLabel": "KELLY learner rank", "items": items,
            "fastTrackStatus": reference_health["status"],
            "summary": summary,
            "activeSessionId": active["id"] if active else None,
            "practiceModes": {
                "fastTrack": {"available": reference_health["status"] == "READY", "schedulerOwner": "DASHBOARD_PRACTICE"},
                "review": {"available": bool(available_shared), "targetCount": len(available_shared),
                           "selectionPolicyVersion": SHARED_TARGET_SELECTION_VERSION,
                           "sourceTargetCounts": {key: len(value) for key, value in shared_source_targets.items()}},
                "curriculum": {"available": bool(packs), "packs": packs},
            },
        }

    def _known_reference_keys(self, evidence: dict[str, dict[str, Any]]) -> set[str]:
        return {
            key for key, item in evidence.items()
            if item.get("knowledgeStatus") in {"KNOWN", "MASTERED"} or item.get("disposition") == "IGNORED"
        }

    def _sentence_from_candidates(
        self, target: dict[str, Any], profile_id: str, seed: str,
        evidence: dict[str, dict[str, Any]], source_candidates: list[dict[str, Any]],
        *, suppressed: set[tuple[str, str, str]] | None = None,
        known: set[str] | None = None,
    ) -> dict[str, Any] | None:
        if suppressed is None:
            suppressed = {
            (row["reference_target_stable_key"], row["reference_sentence_source"], row["reference_sentence_id"])
            for row in self.store.cloze_suppressions(profile_id)
            }
        if known is None:
            known = self._known_reference_keys(evidence)
        candidates = []
        for row in source_candidates:
            if not row.get("translation"):
                continue
            if (target["stable_key"], row["source_id"], row["source_sentence_id"]) in suppressed:
                continue
            surrounding = [item for item in row["surrounding"] if item.get("lexical_unit_id") != target["id"]]
            known_count = sum(1 for item in surrounding if item.get("stable_key") in known)
            unresolved = sum(1 for item in surrounding if item.get("resolution_status") != "MATCHED")
            unknown_resolved = sum(
                1 for item in surrounding
                if item.get("resolution_status") == "MATCHED" and item.get("stable_key") not in known
            )
            user_score = known_count * 3 - unresolved * 2 - unknown_resolved * 0.25
            candidates.append((
                -float(row["quality_score"]) - user_score,
                _hash_order(seed, target["stable_key"], row["source_sentence_id"]),
                str(row["id"]), row,
            ))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[:3])
        return candidates[0][3]

    def _sentence(self, target: dict[str, Any], profile_id: str, seed: str, evidence: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
        return self._sentence_from_candidates(
            target, profile_id, seed, evidence, self.reference.sentence_candidates(target["id"]),
        )

    @staticmethod
    def _present_options(sentence: dict[str, Any], options: list[str], expected: str) -> tuple[list[str], str]:
        prefix = str(sentence["sentence_text"])[:int(sentence["start_offset"])]
        sentence_initial = not any(char.isalpha() for char in prefix)
        expected_upper = bool(expected[:1] and expected[:1].isupper())
        uppercase = sentence_initial or expected_upper

        def present(value: str) -> str:
            if not value:
                return value
            first = value[:1].upper() if uppercase else value[:1].lower()
            return first + value[1:]

        return [present(option) for option in options], present(expected)

    def _distractors(
        self, target: dict[str, Any], expected: str, seed: str, *,
        morphology: dict[str, Any] | None = None, rows: list[dict[str, Any]] | None = None,
    ) -> list[str]:
        morphology = morphology if morphology is not None else self.reference.target_morphology(target["id"], normalize_lookup(expected))
        raw_tag = str(morphology.get("rawTag") or "")
        rows = rows if rows is not None else self.reference.distractor_rows(target, normalize_lookup(expected))
        candidates: list[tuple[Any, ...]] = []
        seen_units: set[str] = set()
        seen_forms = {normalize_lookup(expected)}
        for row in rows:
            unit_id = str(row["id"])
            normalized = str(row["normalized_form"])
            if unit_id in seen_units or normalized in seen_forms:
                continue
            try:
                candidate_morphology = json.loads(row["morphology_json"] or "{}")
            except json.JSONDecodeError:
                candidate_morphology = {}
            candidate_tag = str(candidate_morphology.get("rawTag") or "")
            compatibility = 0 if raw_tag and candidate_tag == raw_tag else 1 if raw_tag and candidate_tag.split(" ", 1)[0] == raw_tag.split(" ", 1)[0] else 2
            candidates.append((
                compatibility, abs(int(row["rank"]) - int(target["rank"])),
                _hash_order(seed, target["stable_key"], unit_id, normalized),
                unit_id, str(row["display_form"]), normalized,
            ))
        candidates.sort(key=lambda item: item[:4])
        selected: list[str] = []
        for item in candidates:
            if item[3] in seen_units or item[5] in seen_forms:
                continue
            seen_units.add(item[3]); seen_forms.add(item[5]); selected.append(item[4])
            if len(selected) == 3:
                break
        return selected

    def _ensure_user_lemma(self, profile_id: str, target: dict[str, Any], expected: str, morphology: dict[str, Any]) -> str:
        result = self.language_service.upsert_lemma(
            profile_id, target["canonical_form"], part_of_speech=target.get("part_of_speech"),
            source_kind="IMPORT", source_id=target["stable_key"], source_version=FAST_TRACK_VERSION,
        )
        lemma_id = result["lemma"]["id"]
        form = self.language_service.upsert_surface_form(profile_id, expected)["form"]
        self.language_service.upsert_form_lemma_mapping(
            profile_id, form["id"], lemma_id, provider_id="NORSK_ORDBANK_TATOEBA_CLOZE",
            provider_version=ITEM_VERSION, morphology=morphology, ambiguity_state="UNAMBIGUOUS",
            lexical_status="KNOWN", provenance="IMPORT",
        )
        return lemma_id

    def _item(
        self, target: dict[str, Any], profile_id: str, seed: str, item_index: int,
        evidence: dict[str, dict[str, Any]], *, sentence: dict[str, Any] | None = None,
        morphology: dict[str, Any] | None = None, distractor_rows: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        sentence = sentence or self._sentence(target, profile_id, seed, evidence)
        if sentence is None:
            return None
        expected = str(sentence["surface_form"])
        morphology = morphology if morphology is not None else self.reference.target_morphology(target["id"], normalize_lookup(expected))
        distractors = self._distractors(
            target, expected, f"{seed}:{item_index}", morphology=morphology, rows=distractor_rows,
        )
        if len(distractors) != 3:
            return None
        options = [expected, *distractors]
        options.sort(key=lambda value: (_hash_order(seed, item_index, target["stable_key"], normalize_lookup(value)), normalize_lookup(value)))
        correct_index = options.index(expected)
        display_options, display_expected = self._present_options(sentence, options, expected)
        lemma_id = self._ensure_user_lemma(profile_id, target, expected, morphology)
        snapshot = {
            "version": ITEM_VERSION,
            "targetLemmaId": lemma_id,
            "referenceTargetId": target["id"],
            "referenceTargetStableKey": target["stable_key"],
            "targetLemmaDisplay": target["canonical_form"],
            "partOfSpeech": target.get("part_of_speech"),
            "kellyLearnerRank": int(target["rank"]),
            "rankMetric": "SOURCE_LEARNER_RANK",
            "rankLabel": "KELLY learner rank",
            "sentenceText": sentence["sentence_text"],
            "blankStart": int(sentence["start_offset"]),
            "blankEnd": int(sentence["end_offset"]),
            "expectedSurfaceForm": expected,
            "options": options,
            "displayExpectedSurfaceForm": display_expected,
            "displayOptions": display_options,
            "correctIndex": correct_index,
            "source": {
                "provider": "Tatoeba", "sourceId": sentence["source_id"],
                "sentenceId": sentence["source_sentence_id"], "url": sentence["source_url"],
                "license": sentence["license_id"],
                "attribution": "Sentence from Tatoeba; source ID and license retained.",
            },
            "morphology": morphology,
            "translation": ({
                "languageCode": "en",
                "text": sentence["translation"]["translation_text"],
                "sentenceId": sentence["translation"]["translation_sentence_id"],
                "license": sentence["translation"]["license_id"],
                "url": sentence["translation"]["source_url"],
            } if sentence.get("translation") else None),
            "ruleVersions": {
                "track": FAST_TRACK_VERSION, "targetSelection": TARGET_SELECTION_VERSION,
                "sentenceSelection": SENTENCE_SELECTION_VERSION, "distractors": DISTRACTOR_VERSION,
                "item": ITEM_VERSION, "optionPresentation": OPTION_PRESENTATION_VERSION,
            },
        }
        snapshot["fingerprint"] = _fingerprint({
            key: value for key, value in snapshot.items() if key != "targetLemmaId"
        })
        return snapshot

    @staticmethod
    def _reader_context(row: dict[str, Any]) -> dict[str, Any] | None:
        sentence = str(row.get("sentence_text") or "")
        surface = str(row.get("surface") or "")
        if _unsafe_context(sentence) or not surface:
            return None
        if str(row.get("ambiguity_state") or "").upper() == "AMBIGUOUS":
            return None
        if str(row.get("resolution_state") or "").upper() in {"AMBIGUOUS", "UNRESOLVED"}:
            return None
        start = int(row.get("token_start") or 0) - int(row.get("sentence_start") or 0)
        end = int(row.get("token_end") or 0) - int(row.get("sentence_start") or 0)
        if start < 0 or end <= start or end > len(sentence) or sentence[start:end] != surface:
            return None
        generated = str(row.get("document_source_type") or "").startswith("GENERATED_")
        context_type = "GENERATED" if generated else "READER"
        try:
            morphology = json.loads(row.get("morphology_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            morphology = {}
        return {
            "contextType": context_type,
            "sentenceText": sentence,
            "blankStart": start,
            "blankEnd": end,
            "expectedSurfaceForm": surface,
            "targetLemmaId": str(row["selected_lemma_id"]),
            "partOfSpeech": row.get("lemma_part_of_speech") or row.get("part_of_speech"),
            "morphology": morphology,
            "quality": 0,
            "source": {
                "type": context_type,
                "provider": "Generated Reader" if generated else "Reader",
                "sourceId": context_type,
                "sourceEntityId": str(row["text_document_id"]),
                "sentenceId": str(row["sentence_id"]),
                "title": row.get("document_title"),
                "sourceReference": row.get("source_reference"),
                "license": None,
                "attribution": "Accepted analyzed generated Reader text." if generated else "Analyzed Reader text.",
                "provenance": {
                    "textDocumentId": str(row["text_document_id"]),
                    "sentenceId": str(row["sentence_id"]),
                    "tokenId": str(row["token_id"]),
                    "sentenceFingerprint": row.get("sentence_fingerprint"),
                    "contentFingerprint": row.get("content_fingerprint"),
                    "analyzerId": row.get("provider_id"),
                    "analyzerVersion": row.get("provider_version"),
                    "generationCandidateId": row.get("generation_candidate_id"),
                    "generationRequestId": row.get("generation_request_id"),
                },
            },
            "translation": None,
        }

    @staticmethod
    def _phrasebook_context(row: dict[str, Any]) -> dict[str, Any] | None:
        expression = unicodedata.normalize("NFC", str(row.get("expression_text") or "").strip())
        sentence = unicodedata.normalize("NFC", str(row.get("source_context") or "").strip())
        if not expression or not sentence or _unsafe_context(sentence) or len(expression.split()) != 1:
            return None
        matches = list(re.finditer(rf"(?<!\w){re.escape(expression)}(?!\w)", sentence, flags=re.IGNORECASE))
        if len(matches) != 1:
            return None
        match = matches[0]
        expected = sentence[match.start():match.end()]
        try:
            provenance = json.loads(row.get("source_provenance_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            provenance = {}
        return {
            "contextType": "PHRASEBOOK",
            "sentenceText": sentence,
            "blankStart": match.start(),
            "blankEnd": match.end(),
            "expectedSurfaceForm": expected,
            "targetLemmaId": str(row["target_lemma_id"]),
            "partOfSpeech": None,
            "morphology": {},
            "quality": 0,
            "source": {
                "type": "PHRASEBOOK", "provider": "Phrasebook", "sourceId": "PHRASEBOOK",
                "sourceEntityId": str(row["id"]), "sentenceId": str(row["id"]),
                "title": expression, "license": None,
                "attribution": "Exact saved Phrasebook context.", "provenance": provenance,
            },
            "translation": None,
        }

    @staticmethod
    def _shared_target_priority(target: dict[str, Any]) -> tuple[Any, ...]:
        scores = [target.get(name) for name in ("recognition", "recall", "production")]
        weak = any(value is not None and int(value) <= 2 for value in scores)
        underexposed = int(target.get("total_exposures") or 0) < 3
        last = str(target.get("last_outcome") or "")
        return (
            0 if last == "INCORRECT" else 1 if last == "REVEALED" else 2,
            0 if target.get("knowledge_status") == "LEARNING" else 1,
            0 if weak else 1,
            0 if underexposed else 1,
            -int(target.get("negative_count") or 0),
            int(target.get("attempt_count") or 0),
            str(target.get("lemma_normalized") or target.get("normalized_form") or ""),
            str(target.get("id") or target.get("stable_key") or ""),
        )

    @staticmethod
    def _target_key(target: dict[str, Any]) -> str:
        source_id = str(target.get("source_id") or "")
        if source_id.startswith("reference-key"):
            return source_id
        return str(target.get("stable_key") or f"user-lemma:{target.get('id')}")

    def _shared_context_index(
        self, profile_id: str, targets: list[dict[str, Any]], seed: str,
    ) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
        user_ids = [str(row["id"]) for row in targets if row.get("id")]
        contexts: dict[str, list[dict[str, Any]]] = {value: [] for value in user_ids}
        pool: list[dict[str, Any]] = []
        for row in self.store.cloze_reader_contexts(profile_id, user_ids):
            context = self._reader_context(row)
            if context is None:
                continue
            contexts.setdefault(str(row["selected_lemma_id"]), []).append(context)
            pool.append(context)
        for row in self.store.cloze_phrasebook_contexts(profile_id, user_ids):
            context = self._phrasebook_context(row)
            if context is None:
                continue
            target = next((item for item in targets if str(item.get("id")) == str(row["target_lemma_id"])), None)
            if target and not context.get("partOfSpeech"):
                context["partOfSpeech"] = target.get("part_of_speech")
            contexts.setdefault(str(row["target_lemma_id"]), []).append(context)
            pool.append(context)
        priority = {"READER": 0, "PHRASEBOOK": 1, "GENERATED": 2, "TATOEBA": 3}
        for target_id, values in contexts.items():
            values.sort(key=lambda item: (
                priority.get(str(item["contextType"]), 9),
                _hash_order(seed, target_id, item["contextType"], item["source"]["sentenceId"]),
                item["source"]["sentenceId"],
            ))
        return contexts, pool

    def _curriculum_targets(
        self, profile_id: str, pack_id: str, version: Any,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        detail = self.language_service.curriculum_service.detail(profile_id, pack_id, version)
        snapshot = {
            "packId": detail["id"], "version": detail["version"], "fingerprint": detail["fingerprint"],
            "name": detail["name"],
        }
        targets: list[dict[str, Any]] = []
        for item in detail["progress"].get("items", []):
            if item.get("reviewState") != "APPROVED" or item.get("mappingState") != "MAPPED":
                continue
            unit = item.get("referenceUnit") or {}
            targets.append({
                "id": item.get("user", {}).get("userLemmaId"),
                "reference_id": unit.get("id"), "stable_key": unit.get("stableKey"),
                "canonical_form": unit.get("canonicalForm") or item.get("displayTerm"),
                "normalized_form": unit.get("normalizedForm") or item.get("normalizedLookup"),
                "part_of_speech": unit.get("partOfSpeech"), "rank": None,
                "knowledge_status": item.get("user", {}).get("state"),
                "membership_id": item.get("membershipId"),
            })
        targets.sort(key=self._shared_target_priority)
        return targets, snapshot

    def _tatoeba_contexts_for_curriculum(
        self, targets: list[dict[str, Any]], seed: str,
    ) -> dict[str, list[dict[str, Any]]]:
        reference_ids = [str(row["reference_id"]) for row in targets if row.get("reference_id")]
        sentences = self.reference.sentence_candidates_batch(reference_ids)
        result: dict[str, list[dict[str, Any]]] = {}
        for target in targets:
            reference_id = str(target.get("reference_id") or "")
            values = []
            for sentence in sentences.get(reference_id, []):
                expected = str(sentence.get("surface_form") or "")
                text = str(sentence.get("sentence_text") or "")
                start, end = int(sentence.get("start_offset") or 0), int(sentence.get("end_offset") or 0)
                if _unsafe_context(text) or not expected or text[start:end] != expected:
                    continue
                translation = sentence.get("translation")
                values.append({
                    "contextType": "TATOEBA", "sentenceText": text, "blankStart": start, "blankEnd": end,
                    "expectedSurfaceForm": expected,
                    "targetLemmaId": target.get("id") or f"reference:{reference_id}",
                    "targetStableKey": target.get("stable_key"),
                    "partOfSpeech": target.get("part_of_speech"), "morphology": {},
                    "quality": float(sentence.get("quality_score") or 0),
                    "source": {
                        "type": "TATOEBA", "provider": "Tatoeba", "sourceId": sentence["source_id"],
                        "sourceEntityId": sentence["source_sentence_id"],
                        "sentenceId": sentence["source_sentence_id"], "url": sentence.get("source_url"),
                        "license": sentence.get("license_id"),
                        "attribution": "Sentence from Tatoeba; source ID and license retained.",
                        "provenance": {"referenceSentenceId": sentence.get("id")},
                    },
                    "translation": ({
                        "languageCode": "en", "text": translation["translation_text"],
                        "sentenceId": translation["translation_sentence_id"],
                        "license": translation["license_id"], "url": translation["source_url"],
                    } if translation else None),
                })
            values.sort(key=lambda item: (
                -item["quality"], _hash_order(seed, target.get("stable_key"), item["source"]["sentenceId"]),
            ))
            result[reference_id] = values
        return result

    def _ensure_shared_lemma(self, profile_id: str, target: dict[str, Any], context: dict[str, Any]) -> str:
        if target.get("id"):
            return str(target["id"])
        result = self.language_service.upsert_lemma(
            profile_id, str(target["canonical_form"]), part_of_speech=target.get("part_of_speech"),
            source_kind="IMPORT", source_id=str(target.get("stable_key") or "CURRICULUM"),
            source_version=SHARED_TARGET_SELECTION_VERSION,
        )
        lemma_id = str(result["lemma"]["id"])
        form = self.language_service.upsert_surface_form(profile_id, context["expectedSurfaceForm"])["form"]
        self.language_service.upsert_form_lemma_mapping(
            profile_id, form["id"], lemma_id, provider_id="PHASE9_SHARED_CONTEXT",
            provider_version=SHARED_ITEM_VERSION, morphology=context.get("morphology") or {},
            ambiguity_state="UNAMBIGUOUS", lexical_status="KNOWN", provenance="IMPORT",
        )
        target["id"] = lemma_id
        return lemma_id

    @staticmethod
    def _shared_distractors(
        target: dict[str, Any], context: dict[str, Any], pool: list[dict[str, Any]], seed: str,
    ) -> list[str]:
        expected_normalized = normalize_lookup(context["expectedSurfaceForm"])
        target_id = str(target.get("id") or (f"reference:{target.get('reference_id')}" if target.get("reference_id") else ""))
        target_stable_key = ClozeService._target_key(target)
        target_pos = target.get("part_of_speech") or context.get("partOfSpeech")
        target_tag = str((context.get("morphology") or {}).get("rawTag") or "")
        seen = {expected_normalized}
        candidates = []
        for item in pool:
            value = str(item.get("expectedSurfaceForm") or "")
            normalized = normalize_lookup(value)
            if not value or normalized in seen or str(item.get("targetLemmaId") or "") == target_id:
                continue
            if item.get("targetStableKey") and str(item.get("targetStableKey")) == target_stable_key:
                continue
            candidate_pos = item.get("partOfSpeech")
            if target_pos and candidate_pos and str(candidate_pos) != str(target_pos):
                continue
            candidate_tag = str((item.get("morphology") or {}).get("rawTag") or "")
            compatibility = 0 if target_tag and candidate_tag == target_tag else 1 if target_tag and candidate_tag.split(" ", 1)[0] == target_tag.split(" ", 1)[0] else 2
            candidates.append((compatibility, _hash_order(seed, target_id, normalized), normalized, value))
        candidates.sort()
        selected = []
        for _, _, normalized, value in candidates:
            if normalized in seen:
                continue
            seen.add(normalized); selected.append(value)
            if len(selected) == 3:
                break
        return selected

    def _shared_item(
        self, target: dict[str, Any], context: dict[str, Any], profile_id: str, seed: str,
        item_index: int, requested_question_type: str, pool: list[dict[str, Any]],
        curriculum_snapshot: dict[str, Any] | None,
    ) -> dict[str, Any]:
        lemma_id = self._ensure_shared_lemma(profile_id, target, context)
        expected = str(context["expectedSurfaceForm"])
        question_type = requested_question_type
        options: list[str] = []
        correct_index = None
        display_options: list[str] = []
        display_expected = expected
        if requested_question_type == "MULTIPLE_CHOICE":
            distractors = self._shared_distractors(target, context, pool, f"{seed}:{item_index}")
            if len(distractors) == 3:
                options = [expected, *distractors]
                options.sort(key=lambda value: (_hash_order(seed, item_index, self._target_key(target), normalize_lookup(value)), normalize_lookup(value)))
                correct_index = options.index(expected)
                display_options, display_expected = self._present_options(
                    {"sentence_text": context["sentenceText"], "start_offset": context["blankStart"]},
                    options, expected,
                )
            else:
                question_type = "TYPED"
        source = context["source"]
        snapshot = {
            "version": SHARED_ITEM_VERSION, "questionType": question_type,
            "sourceContextType": context["contextType"], "targetLemmaId": lemma_id,
            "referenceTargetId": target.get("reference_id"),
            "referenceTargetStableKey": self._target_key(target),
            "targetLemmaDisplay": target.get("lemma_display") or target.get("canonical_form"),
            "partOfSpeech": target.get("part_of_speech") or context.get("partOfSpeech"),
            "kellyLearnerRank": target.get("rank"), "rankMetric": None, "rankLabel": None,
            "sentenceText": context["sentenceText"], "blankStart": context["blankStart"],
            "blankEnd": context["blankEnd"], "expectedSurfaceForm": expected,
            "acceptedAnswers": [expected], "options": options, "displayOptions": display_options,
            "displayExpectedSurfaceForm": display_expected, "correctIndex": correct_index,
            "source": source, "morphology": context.get("morphology") or {},
            "translation": context.get("translation"), "curriculum": curriculum_snapshot,
            "ruleVersions": {
                "targetSelection": SHARED_TARGET_SELECTION_VERSION,
                "contextSelection": SHARED_CONTEXT_SELECTION_VERSION,
                "distractors": SHARED_DISTRACTOR_VERSION, "item": SHARED_ITEM_VERSION,
                "answerNormalization": ANSWER_NORMALIZATION_VERSION,
                "optionPresentation": OPTION_PRESENTATION_VERSION,
            },
        }
        snapshot["fingerprint"] = _fingerprint({key: value for key, value in snapshot.items() if key != "targetLemmaId"})
        return snapshot

    def _start_shared_session(
        self, profile_id: str, *, mode: str, requested: int, seed: str,
        question_type: str, pack_id: str | None, pack_version: Any,
        target_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        curriculum_snapshot = None
        if mode == "CURRICULUM":
            if not pack_id:
                raise LanguageValidationError("curriculumPackId is required", details=["curriculumPackId"])
            targets, curriculum_snapshot = self._curriculum_targets(profile_id, pack_id, pack_version)
        else:
            targets = self.store.cloze_shared_targets(profile_id)
            targets.sort(key=self._shared_target_priority)
            if target_ids:
                order = {str(value): index for index, value in enumerate(target_ids)}
                targets = [row for row in targets if str(row.get("id")) in order]
                targets.sort(key=lambda row: (order[str(row["id"])], self._shared_target_priority(row)))
        contexts, pool = self._shared_context_index(profile_id, targets, seed)
        if mode == "CURRICULUM":
            tatoeba = self._tatoeba_contexts_for_curriculum(targets, seed)
            for target in targets:
                reference_id = str(target.get("reference_id") or "")
                contexts.setdefault(str(target.get("id") or reference_id), []).extend(tatoeba.get(reference_id, []))
            pool.extend(item for values in tatoeba.values() for item in values)
        suppressed = {
            (str(row["reference_target_stable_key"]), str(row["reference_sentence_source"]), str(row["reference_sentence_id"]))
            for row in self.store.cloze_suppressions(profile_id)
        }
        items = []
        for target in targets:
            context_key = str(target.get("id") or target.get("reference_id") or "")
            candidates = [item for item in contexts.get(context_key, []) if (
                self._target_key(target), str(item["source"]["sourceId"]), str(item["source"]["sentenceId"])
            ) not in suppressed]
            if not candidates:
                continue
            item = self._shared_item(
                target, candidates[0], profile_id, seed, len(items), question_type, pool, curriculum_snapshot,
            )
            items.append(item)
            if len(items) >= requested:
                break
        if not items:
            raise LanguageConflictError("No safe shared-context Cloze items are available", code="cloze_no_playable_items")
        legacy_mode = "RECYCLE_MISTAKES" if mode in {"REVIEW", "REMEDIATION"} else "FAST_TRACK"
        track_key = (
            "SHARED_REMEDIATION" if mode == "REMEDIATION" else
            "SHARED_REVIEW" if mode == "REVIEW" else
            f"CURRICULUM:{curriculum_snapshot['packId']}"
        )
        session = self.store.create_cloze_session({
            "language_profile_id": profile_id, "mode": legacy_mode, "practice_mode": mode,
            "track_key": track_key, "track_version": SHARED_TARGET_SELECTION_VERSION,
            "requested_item_count": requested, "seed": seed, "items": items,
            "question_type": question_type, "selection_policy_version": SHARED_TARGET_SELECTION_VERSION,
            "source_policy_version": SHARED_CONTEXT_SELECTION_VERSION,
            "curriculum_snapshot": curriculum_snapshot,
        })
        return self._session_payload({"session": session, "attempts": []})

    def start_session(self, profile_id: str, payload: Any) -> dict[str, Any]:
        self.language_service.get_profile(profile_id)
        if not isinstance(payload, dict):
            raise LanguageValidationError("JSON payload must be an object", code="invalid_json_object")
        unknown = sorted(set(payload) - {
            "mode", "trackKey", "itemCount", "seed", "questionType",
            "curriculumPackId", "curriculumVersion",
        })
        if unknown:
            raise LanguageValidationError("Cloze session contains unsupported fields", details=unknown)
        mode = str(payload.get("mode") or "FAST_TRACK").upper()
        if mode not in {"FAST_TRACK", "RECYCLE_MISTAKES", "REVIEW", "CURRICULUM"}:
            raise LanguageValidationError("mode is invalid", details=["mode"])
        try:
            requested = int(payload.get("itemCount", 10))
        except (TypeError, ValueError) as exc:
            raise LanguageValidationError("itemCount is invalid", details=["itemCount"]) from exc
        if requested not in {10, 20, 50}:
            raise LanguageValidationError("itemCount must be 10, 20, or 50", details=["itemCount"])
        seed = str(payload.get("seed") or hashlib.sha256(f"{profile_id}:{utc_now()}".encode()).hexdigest()[:20])
        if len(seed) > 120:
            raise LanguageValidationError("seed is too long", details=["seed"])
        question_type = str(payload.get("questionType") or "MULTIPLE_CHOICE").upper()
        if question_type not in {"MULTIPLE_CHOICE", "TYPED"}:
            raise LanguageValidationError("questionType is invalid", details=["questionType"])
        if mode in {"REVIEW", "CURRICULUM"}:
            pack_id = str(payload.get("curriculumPackId") or "").strip() or None
            return self._start_shared_session(
                profile_id, mode=mode, requested=requested, seed=seed,
                question_type=question_type, pack_id=pack_id,
                pack_version=payload.get("curriculumVersion"),
            )
        if mode == "RECYCLE_MISTAKES":
            remediation = self.language_service.mistake_intelligence_service.remediation(
                profile_id, limit=requested,
            )
            target_ids = [str(item["targetLemmaId"]) for item in remediation.get("items") or []]
            if target_ids:
                try:
                    return self._start_shared_session(
                        profile_id, mode="REMEDIATION", requested=requested, seed=seed,
                        question_type=question_type, pack_id=None, pack_version=None,
                        target_ids=target_ids,
                    )
                except LanguageConflictError as exc:
                    if exc.code != "cloze_no_playable_items":
                        raise
        if question_type != "MULTIPLE_CHOICE":
            raise LanguageValidationError(
                "Fast Track keeps its Phase 9A multiple-choice contract", details=["questionType"],
            )
        track_key, bounds = self._track(payload.get("trackKey"))
        evidence = self._evidence(profile_id)
        suppressed = {
            (row["reference_target_stable_key"], row["reference_sentence_source"], row["reference_sentence_id"])
            for row in self.store.cloze_suppressions(profile_id)
        }
        known = self._known_reference_keys(evidence)
        targets = self.reference.playable_targets(*(bounds if mode == "FAST_TRACK" else (1, 6000)))
        if mode == "RECYCLE_MISTAKES":
            targets = [target for target in targets if evidence.get(target["stable_key"], {}).get("lastOutcome") == "INCORRECT"]
            targets.sort(key=lambda target: (
                -_timestamp_sort(evidence[target["stable_key"]].get("lastAttemptedAt")),
                int(target["rank"]), target["stable_key"],
            ))
        else:
            targets.sort(key=lambda target: self._priority(target, evidence.get(target["stable_key"])))
        items: list[dict[str, Any]] = []
        for offset in range(0, len(targets), 200):
            batch = targets[offset:offset + 200]
            sentence_rows = self.reference.sentence_candidates_batch([str(row["id"]) for row in batch])
            selected_sentences = {
                str(target["id"]): self._sentence_from_candidates(
                    target, profile_id, seed, evidence, sentence_rows.get(str(target["id"]), []),
                    suppressed=suppressed, known=known,
                )
                for target in batch
            }
            morphology = self.reference.target_morphology_batch([
                (str(target["id"]), normalize_lookup(str(selected_sentences[str(target["id"])]["surface_form"])))
                for target in batch if selected_sentences.get(str(target["id"])) is not None
            ])
            distractor_rows = self.reference.distractor_rows_batch(batch)
            for target in batch:
                sentence = selected_sentences.get(str(target["id"]))
                if sentence is None:
                    continue
                normalized = normalize_lookup(str(sentence["surface_form"]))
                item = self._item(
                    target, profile_id, seed, len(items), evidence, sentence=sentence,
                    morphology=morphology.get((str(target["id"]), normalized), {}),
                    distractor_rows=distractor_rows.get(str(target["id"]), []),
                )
                if item is not None:
                    items.append(item)
                if len(items) >= requested:
                    break
            if len(items) >= requested:
                break
        if not items:
            raise LanguageConflictError("No playable Cloze items are available for this selection", code="cloze_no_playable_items")
        session = self.store.create_cloze_session({
            "language_profile_id": profile_id, "mode": mode, "track_key": track_key,
            "track_version": FAST_TRACK_VERSION, "requested_item_count": requested,
            "seed": seed, "items": items, "practice_mode": mode,
            "question_type": "MULTIPLE_CHOICE", "selection_policy_version": TARGET_SELECTION_VERSION,
            "source_policy_version": SENTENCE_SELECTION_VERSION,
        })
        return self._session_payload({"session": session, "attempts": []})

    def _translation(self, item: dict[str, Any]) -> dict[str, Any] | None:
        if item.get("translation"):
            return item["translation"]
        source = item.get("source") or {}
        if item.get("sourceContextType", "TATOEBA") != "TATOEBA" and source.get("provider") != "Tatoeba":
            return None
        row = self.reference.sentence_translation(
            str(source.get("sourceId") or ""), str(source.get("sentenceId") or ""),
        )
        if not row:
            return None
        return {
            "languageCode": "en", "text": row["translation_text"],
            "sentenceId": row["translation_sentence_id"], "license": row["license_id"],
            "url": row["source_url"],
        }

    def _display_forms(self, item: dict[str, Any]) -> tuple[list[str], str]:
        if item.get("displayOptions") and item.get("displayExpectedSurfaceForm"):
            return item["displayOptions"], item["displayExpectedSurfaceForm"]
        return self._present_options(
            {"sentence_text": item["sentenceText"], "start_offset": item["blankStart"]},
            item["options"], item["expectedSurfaceForm"],
        )

    def _public_item(self, item: dict[str, Any], index: int) -> dict[str, Any]:
        display_options, _ = self._display_forms(item)
        return {
            "index": index, "fingerprint": item["fingerprint"], "sentenceText": item["sentenceText"],
            "blankStart": item["blankStart"], "blankEnd": item["blankEnd"],
            "options": display_options,
            "source": item["source"], "partOfSpeech": item.get("partOfSpeech"),
            "translation": self._translation(item),
            "questionType": item.get("questionType", "MULTIPLE_CHOICE"),
            "sourceContextType": item.get("sourceContextType", "TATOEBA"),
            "targetLemmaId": item.get("targetLemmaId"),
            "targetLemmaDisplay": item.get("targetLemmaDisplay"),
            "curriculum": item.get("curriculum"),
        }

    def _session_payload(self, detail: dict[str, Any]) -> dict[str, Any]:
        session = LanguageStore.api_row(detail["session"])
        items = session.pop("items")
        session["storageMode"] = session.get("mode")
        session["mode"] = session.get("practiceMode") or session.get("mode")
        attempts = [LanguageStore.api_row(row) for row in detail["attempts"]]
        answered = {int(row["itemIndex"]) for row in attempts}
        next_index = next((index for index in range(len(items)) if index not in answered), None)
        session["actualItemCount"] = len(items)
        session["answeredCount"] = len(answered)
        session["remainingCount"] = len(items) - len(answered)
        session["currentItem"] = self._public_item(items[next_index], next_index) if next_index is not None else None
        return {"session": session, "attempts": attempts}

    def get_session(self, session_id: str) -> dict[str, Any]:
        return self._session_payload(self.store.get_cloze_session(session_id))

    def submit_attempt(self, session_id: str, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise LanguageValidationError("JSON payload must be an object", code="invalid_json_object")
        unknown = sorted(set(payload) - {
            "itemIndex", "itemFingerprint", "action", "optionIndex", "answer",
            "responseMs", "idempotencyKey",
        })
        if unknown:
            raise LanguageValidationError("Cloze attempt contains unsupported fields", details=unknown)
        detail = self.store.get_cloze_session(session_id)
        session = LanguageStore.api_row(detail["session"])
        items = session["items"]
        try:
            item_index = int(payload.get("itemIndex"))
            response_ms = int(payload.get("responseMs", 0))
        except (TypeError, ValueError) as exc:
            raise LanguageValidationError("Cloze attempt indexes/timing are invalid") from exc
        if not 0 <= item_index < len(items) or not 0 <= response_ms <= 600000:
            raise LanguageValidationError("Cloze attempt indexes/timing are invalid")
        item = items[item_index]
        if payload.get("itemFingerprint") != item["fingerprint"]:
            raise LanguageConflictError("Cloze item fingerprint is stale", code="cloze_item_stale")
        action = str(payload.get("action") or "ANSWER").upper()
        chosen = None
        user_answer = None
        normalized_answer = None
        question_type = str(item.get("questionType") or "MULTIPLE_CHOICE")
        normalization_version = str(
            (item.get("ruleVersions") or {}).get("answerNormalization")
            or (LEGACY_NORMALIZATION_VERSION if question_type == "MULTIPLE_CHOICE" else ANSWER_NORMALIZATION_VERSION)
        )
        if action == "ANSWER":
            if question_type == "TYPED":
                answer = payload.get("answer")
                if not isinstance(answer, str) or not answer.strip():
                    raise LanguageValidationError("answer must not be empty", details=["answer"])
                if len(answer) > MAX_TYPED_ANSWER_LENGTH:
                    raise LanguageValidationError("answer is too long", details=["answer"])
                user_answer = answer
                normalized_answer = normalize_typed_answer(answer)
                accepted = item.get("acceptedAnswers") or [item["expectedSurfaceForm"]]
                accepted_normalized = {normalize_typed_answer(value) for value in accepted}
                outcome = "CORRECT" if normalized_answer in accepted_normalized else "INCORRECT"
            else:
                try:
                    option_index = int(payload.get("optionIndex"))
                except (TypeError, ValueError) as exc:
                    raise LanguageValidationError("optionIndex is invalid", details=["optionIndex"]) from exc
                if not 0 <= option_index < len(item.get("options") or []):
                    raise LanguageValidationError("optionIndex is invalid", details=["optionIndex"])
                chosen = item["options"][option_index]
                user_answer = chosen
                normalized_answer = normalize_typed_answer(chosen)
                outcome = "CORRECT" if option_index == int(item["correctIndex"]) else "INCORRECT"
        elif action == "REVEAL":
            outcome = "REVEALED"
        elif action == "SKIP":
            outcome = "SKIPPED"
        else:
            raise LanguageValidationError("action is invalid", details=["action"])
        key = str(payload.get("idempotencyKey") or "").strip()
        if not key or len(key) > 200:
            raise LanguageValidationError("idempotencyKey is invalid", details=["idempotencyKey"])
        attempt, updated_session, created = self.store.record_cloze_attempt({
            "session_id": session_id, "item_index": item_index, "target_lemma_id": item["targetLemmaId"],
            "reference_target_stable_key": item["referenceTargetStableKey"],
            "reference_sentence_source": item["source"]["sourceId"],
            "reference_sentence_id": item["source"]["sentenceId"], "item_snapshot": item,
            "item_fingerprint": item["fingerprint"], "expected_surface_form": item["expectedSurfaceForm"],
            "options": item["options"], "chosen_option": chosen, "outcome": outcome,
            "response_ms": response_ms, "idempotency_key": key, "attempted_at": utc_now(),
            "rule_versions": {**item["ruleVersions"], "evidence": EVIDENCE_VERSION},
            "question_type": question_type,
            "source_context_type": item.get("sourceContextType", "TATOEBA"),
            "normalization_version": normalization_version,
            "user_answer": user_answer, "normalized_answer": normalized_answer,
        })
        event = self.language_service.record_cloze_evidence(attempt)
        next_detail = self.store.get_cloze_session(session_id)
        chosen_index = item["options"].index(attempt["chosen_option"]) if attempt["chosen_option"] in item["options"] else None
        display_options, display_expected = self._display_forms(item)
        return {
            **self._session_payload(next_detail),
            "attempt": LanguageStore.api_row(attempt), "created": created, "evidence": event,
            "feedback": {
                "outcome": attempt["outcome"],
                "expectedSurfaceForm": display_expected,
                "chosenOption": display_options[chosen_index] if chosen_index is not None else None,
                "userAnswer": attempt.get("user_answer") or attempt.get("chosen_option"),
                "questionType": attempt.get("question_type") or question_type,
                "targetLemmaDisplay": item["targetLemmaDisplay"],
                "kellyLearnerRank": item["kellyLearnerRank"], "rankLabel": item["rankLabel"],
                "source": item["source"], "sourceContextType": item.get("sourceContextType", "TATOEBA"),
                "translation": self._translation(item),
            },
        }

    def report_item(self, session_id: str, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise LanguageValidationError("JSON payload must be an object", code="invalid_json_object")
        try:
            item_index = int(payload.get("itemIndex"))
        except (TypeError, ValueError) as exc:
            raise LanguageValidationError("itemIndex is invalid", details=["itemIndex"]) from exc
        reasons = {
            "WRONG_ANSWER", "AMBIGUOUS_ANSWER", "MULTIPLE_VALID_ANSWERS", "UNNATURAL_SENTENCE",
            "BAD_DISTRACTORS", "BAD_SENTENCE", "BAD_MAPPING", "UNNATURAL_GENERATED_CONTEXT", "OTHER",
        }
        reason = str(payload.get("reason") or "OTHER").upper()
        if reason not in reasons:
            raise LanguageValidationError("reason is invalid", details=["reason"])
        detail = self.store.get_cloze_session(session_id)
        session = LanguageStore.api_row(detail["session"])
        items = session["items"]
        if not 0 <= item_index < len(items):
            raise LanguageValidationError("itemIndex is invalid", details=["itemIndex"])
        item = items[item_index]
        row, created = self.store.report_cloze_item({
            "language_profile_id": session["languageProfileId"],
            "reference_target_stable_key": item["referenceTargetStableKey"],
            "reference_sentence_source": item["source"]["sourceId"],
            "reference_sentence_id": item["source"]["sentenceId"], "reason": reason,
            "source_context_type": item.get("sourceContextType", "TATOEBA"),
        })
        return {"suppression": LanguageStore.api_row(row), "created": created}

    def statistics(self, profile_id: str) -> dict[str, Any]:
        result = self.store.cloze_summary(profile_id)
        result["ruleVersion"] = EVIDENCE_VERSION
        return result


__all__ = [
    "ANSWER_NORMALIZATION_VERSION", "DISTRACTOR_VERSION", "EVIDENCE_VERSION", "FAST_TRACK_BANDS",
    "FAST_TRACK_VERSION", "ITEM_VERSION", "MAX_TYPED_ANSWER_LENGTH", "OPTION_PRESENTATION_VERSION",
    "SENTENCE_SELECTION_VERSION", "SHARED_CONTEXT_SELECTION_VERSION", "SHARED_DISTRACTOR_VERSION",
    "SHARED_ITEM_VERSION", "SHARED_TARGET_SELECTION_VERSION", "TARGET_SELECTION_VERSION",
    "ClozeReferenceStore", "ClozeService", "normalize_typed_answer",
]
