"""Pack K Track-specific, reproducible Skill Intelligence read model."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
from typing import Any, Callable, Iterable
import unicodedata

from .evaluation import (
    EVALUATOR_VERSION,
    fingerprint as evaluation_fingerprint,
    input_fingerprint as evaluation_input_fingerprint,
    track_context,
)
from .models import JobhuntError


SKILL_INTELLIGENCE_VERSION = "skill-intelligence@1"
SUPPORTED_FACT_TYPES = frozenset({"skill", "tool", "language", "certification"})
POPULATION_MODES = frozenset({"current", "historical"})
WINDOWS = {"30d": 30, "90d": 90, "180d": 180}
REQUIREMENT_CLASSES = frozenset({"all", "required", "preferred", "optional", "unknown", "ambiguous"})
USER_STATES = frozenset({"all", "supported", "partial", "gap", "unknown", "mixed"})
SORTS = frozenset({"required", "demand", "gaps", "unlocked", "unknown", "alphabetical", "priority"})
MAX_POPULATION = 2000
MAX_DETAIL_JOBS = 100
MAX_UNMAPPED_TERMS = 200
MINIMUM_POPULATION = 5
MINIMUM_SKILL_EVIDENCE_COVERAGE = 0.40
MINIMUM_EVALUATION_COVERAGE = 0.40

PRIORITY_POLICY = {
    "version": SKILL_INTELLIGENCE_VERSION,
    "minimumPopulation": MINIMUM_POPULATION,
    "minimumSkillEvidenceCoverage": MINIMUM_SKILL_EVIDENCE_COVERAGE,
    "minimumEvaluationCoverage": MINIMUM_EVALUATION_COVERAGE,
    "high": {
        "requiredGapsMinimum": 2,
        "strictUnlockedMinimum": 2,
        "requiredDemandMinimum": 5,
        "repeatedRequiredGapsMinimum": 3,
    },
    "medium": {"requiredDemandMinimum": 2, "explicitGapOrBlockerMinimum": 1},
    "description": (
        "HIGH requires sufficient coverage, repeated required gaps, and either at least two strict "
        "single-skill unlocks or at least five required-demand jobs with three required gaps. "
        "MEDIUM requires recurring required demand plus an explicit gap/blocker, or an unlock. "
        "LOW is evidence-backed but weaker or mainly preferred demand. MONITOR covers limited demand "
        "or established strengths."
    ),
}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _loads(value: Any, fallback: Any) -> Any:
    try:
        return json.loads(value) if value not in (None, "") else fallback
    except (TypeError, json.JSONDecodeError):
        return fallback


def _fingerprint(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).casefold()
    text = "".join(character for character in text if not unicodedata.combining(character))
    return " ".join(re.findall(r"[a-z0-9+#.]+", text))


def _percent(numerator: int, denominator: int) -> float | None:
    return round(numerator * 100 / denominator, 1) if denominator else None


def _chunks(values: list[str], size: int = 300) -> Iterable[list[str]]:
    for index in range(0, len(values), size):
        yield values[index:index + size]


def _as_utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _requirement_class(values: Iterable[str]) -> str:
    classes = {str(value or "unknown") for value in values}
    known = classes.intersection({"required", "preferred", "optional"})
    if len(known) > 1:
        return "ambiguous"
    if known:
        return next(iter(known))
    return "unknown"


def _finding_state(findings: list[dict[str, Any]]) -> str:
    states = {item["status"] for item in findings}
    for state in ("blocker", "gap", "partial", "unknown", "supported"):
        if state in states:
            return state
    return "unknown"


def _public_user_state(counts: dict[str, int]) -> str:
    active = [state for state in ("supported", "partial", "gap", "unknown") if counts.get(state, 0)]
    if counts.get("blocker", 0) and "gap" not in active:
        active.append("gap")
    if len(active) > 1:
        return "mixed"
    return active[0] if active else "unknown"


def _priority(skill: dict[str, Any], coverage: dict[str, Any]) -> dict[str, Any]:
    demand = skill["demand"]
    user = skill["user"]
    unlock = skill["opportunity"]
    insufficient_reasons = []
    if coverage["totalJobs"] < MINIMUM_POPULATION:
        insufficient_reasons.append(
            f"Track population {coverage['totalJobs']} is below the minimum {MINIMUM_POPULATION}."
        )
    if coverage["skillEvidenceRate"] < MINIMUM_SKILL_EVIDENCE_COVERAGE:
        insufficient_reasons.append(
            f"Skill-evidence coverage {coverage['skillEvidenceRate']:.0%} is below the 40% minimum."
        )
    if coverage["evaluationRate"] < MINIMUM_EVALUATION_COVERAGE:
        insufficient_reasons.append(
            f"Current-Evaluation coverage {coverage['evaluationRate']:.0%} is below the 40% minimum."
        )
    components = {
        "requiredDemand": demand["requiredJobs"],
        "preferredDemand": demand["preferredJobs"],
        "requiredGaps": user["requiredGaps"],
        "blockers": user["blockers"],
        "strictJobsUnlocked": unlock["strictJobsUnlocked"],
        "potentialJobsUnlocked": unlock["potentialJobsUnlocked"],
        "profileEvidenceExists": bool(skill["profileEvidence"]["exists"]),
        "profileLevel": skill["profileEvidence"].get("level"),
        "developmentInterest": skill["profileEvidence"].get("developmentInterest"),
        "totalJobs": coverage["totalJobs"],
        "jobsWithSkillEvidence": coverage["jobsWithSkillEvidence"],
        "jobsWithCurrentEvaluations": coverage["jobsWithCurrentEvaluations"],
        "evaluationUnknownRate": user["unknownRate"],
    }
    if insufficient_reasons:
        return {"classification": "insufficient_evidence", "components": components, "reasons": insufficient_reasons}

    high = (
        user["requiredGaps"] >= 2
        and (
            unlock["strictJobsUnlocked"] >= 2
            or (demand["requiredJobs"] >= 5 and user["requiredGaps"] >= 3)
        )
    )
    medium = (
        (demand["requiredJobs"] >= 2 and user["requiredGaps"] + user["blockers"] >= 1)
        or unlock["strictJobsUnlocked"] + unlock["potentialJobsUnlocked"] >= 1
    )
    low = user["requiredGaps"] + user["blockers"] > 0 or (
        demand["preferredJobs"] >= 2 and user["preferredGaps"] > 0
    )
    if high:
        classification = "high"
    elif medium:
        classification = "medium"
    elif low:
        classification = "low"
    else:
        classification = "monitor"

    reasons = []
    if demand["requiredJobs"]:
        reasons.append(f"{demand['requiredJobs']} Track jobs explicitly require this concept.")
    elif demand["preferredJobs"]:
        reasons.append(f"{demand['preferredJobs']} Track jobs list it as preferred.")
    if user["requiredGaps"]:
        reasons.append(f"Pack J reports a required gap in {user['requiredGaps']} current jobs.")
    if user["blockers"]:
        reasons.append(f"Pack J reports an explicit blocker in {user['blockers']} current jobs.")
    if unlock["strictJobsUnlocked"]:
        reasons.append(
            f"Resolving it alone removes the final known required gap in {unlock['strictJobsUnlocked']} jobs."
        )
    if unlock["potentialJobsUnlocked"]:
        reasons.append(
            f"Another {unlock['potentialJobsUnlocked']} jobs retain required UNKNOWN evidence."
        )
    if not reasons:
        reasons.append("Observed demand or explicit user-gap evidence is currently limited.")
    if skill["profileEvidence"]["exists"] and user["requiredGaps"] == 0 and user["blockers"] == 0:
        reasons.append("Current Profile and Pack J evidence indicate an established market strength.")
    return {"classification": classification, "components": components, "reasons": reasons}


class SkillIntelligenceReadModel:
    """Bounded live aggregation over canonical Job Hunt state; no durable cache."""

    def __init__(self, store: Any, *, now_provider: Callable[[], datetime] | None = None) -> None:
        self.store = store
        self.now_provider = now_provider or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def _fallback_projection(job: dict[str, Any]) -> dict[str, Any]:
        fields = (
            "company", "role_title", "seniority", "location_city", "location_country",
            "work_mode", "contract_type", "salary_min", "salary_max", "salary_currency",
            "salary_period", "salary_tax_type", "salary_is_known", "requirements_json",
        )
        return {key: job.get(key) for key in fields}

    @staticmethod
    def _validate_query(population: Any, window: Any) -> tuple[str, str]:
        mode = str(population or "current")
        selected_window = str(window or "90d")
        if mode not in POPULATION_MODES:
            raise JobhuntError("population must be current or historical", code="invalid_skill_population")
        if selected_window not in WINDOWS:
            raise JobhuntError("window must be 30d, 90d, or 180d", code="invalid_skill_window")
        return mode, selected_window

    def _population(
        self, connection: Any, track_id: str, *, mode: str, window: str, now: datetime,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], str | None, str]:
        track_row = connection.execute("SELECT * FROM career_tracks WHERE id=?", (track_id,)).fetchone()
        if not track_row:
            raise JobhuntError("Track not found", status=404, code="track_not_found")
        track = dict(track_row)
        track["countries"] = _loads(track.pop("countries_json", "[]"), [])
        track["regions_cities"] = _loads(track.pop("regions_cities_json", "[]"), [])
        end = now.isoformat(timespec="seconds")
        start = (now - timedelta(days=WINDOWS[window])).isoformat(timespec="seconds") if mode == "historical" else None
        active_clause = ""
        parameters: list[Any] = [track_id, track_id, track_id]
        if mode == "current":
            active_clause = (
                " AND j.archived_at IS NULL AND a.source_expired=0 "
                "AND (j.expires_at IS NULL OR substr(j.expires_at,1,10)>=substr(?,1,10))"
            )
            parameters.append(end)
        else:
            active_clause = " AND anchor_at>=? AND anchor_at<=?"
            parameters.extend([start, end])
        rows = connection.execute(
            f"""
            WITH relevant AS (
                SELECT a.job_id FROM track_job_assignments a
                 WHERE a.track_id=? AND a.active=1
                UNION
                SELECT l.canonical_job_id FROM source_listings l
                 JOIN source_listing_tracks x ON x.listing_id=l.id
                 WHERE x.track_id=? AND l.canonical_job_id IS NOT NULL
                UNION
                SELECT l.canonical_job_id FROM source_listings l
                 JOIN source_listing_search_profiles x ON x.listing_id=l.id
                 JOIN track_search_profiles p ON p.id=x.search_profile_id
                 WHERE p.track_id=? AND l.canonical_job_id IS NOT NULL
            ), population AS (
                SELECT j.*,a.source_expired,
                       COALESCE(k.publication_at,
                           (SELECT MIN(l.first_seen_at) FROM source_listings l WHERE l.canonical_job_id=j.id),
                           j.created_at) AS anchor_at,
                       CASE WHEN k.publication_at IS NOT NULL THEN 'publication_fact'
                            WHEN EXISTS(SELECT 1 FROM source_listings l WHERE l.canonical_job_id=j.id)
                            THEN 'first_source_observation' ELSE 'canonical_job_created' END AS anchor_kind,
                       p.id AS latest_projection_id,p.snapshot_fingerprint AS latest_projection_fingerprint
                  FROM relevant r
                  JOIN canonical_jobs j ON j.id=r.job_id
                  JOIN applications a ON a.job_id=j.id
                  LEFT JOIN dedupe_job_keys k ON k.job_id=j.id
                  LEFT JOIN canonical_job_projections p ON p.id=(
                      SELECT p2.id FROM canonical_job_projections p2
                       WHERE p2.job_id=j.id ORDER BY p2.projection_version DESC LIMIT 1
                  )
                 WHERE j.deleted_at IS NULL AND j.merged_into_job_id IS NULL
            )
            SELECT * FROM population j JOIN applications a ON a.job_id=j.id
             WHERE 1=1 {active_clause}
             ORDER BY anchor_at DESC,j.id LIMIT ?
            """,
            (*parameters, MAX_POPULATION + 1),
        ).fetchall()
        if len(rows) > MAX_POPULATION:
            raise JobhuntError(
                "Track population exceeds the bounded Skill Intelligence limit; choose a shorter historical window",
                status=422, code="skill_intelligence_population_too_large",
            )
        return track, [dict(row) for row in rows], start, end

    @staticmethod
    def _mapping_state(connection: Any) -> tuple[str, list[str]]:
        digest = hashlib.sha256()
        versions: set[str] = set()
        for row in connection.execute(
            """SELECT id,concept_type,concept_key,display_label,aliases_json,updated_at
                 FROM normalization_concepts WHERE active=1 ORDER BY id"""
        ):
            digest.update(_json(dict(row)).encode("utf-8"))
        for row in connection.execute(
            """SELECT n.fact_id,n.concept_id,n.rule_version,n.confidence,n.mapping_origin,
                      n.is_manual,n.created_at
                 FROM fact_normalizations n
                 JOIN normalization_concepts c ON c.id=n.concept_id AND c.active=1
                WHERE n.state='active' ORDER BY n.fact_id,n.is_manual DESC,n.created_at,n.id"""
        ):
            versions.add(str(row["rule_version"]))
            digest.update(_json(dict(row)).encode("utf-8"))
        return "sha256:" + digest.hexdigest(), sorted(versions)

    @staticmethod
    def _load_sources_and_captures(
        connection: Any, job_ids: list[str],
    ) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]]]:
        by_job: dict[str, list[dict[str, Any]]] = defaultdict(list)
        by_capture: dict[str, dict[str, Any]] = {}
        for chunk in _chunks(job_ids):
            placeholders = ",".join("?" for _ in chunk)
            rows = connection.execute(
                f"""SELECT l.canonical_job_id AS job_id,l.id AS listing_id,l.lifecycle_state,
                            l.first_seen_at,l.last_seen_at,d.source_key,d.display_name,
                            c.id AS capture_id,c.captured_at
                       FROM source_listings l
                       JOIN source_definitions d ON d.id=l.source_id
                       LEFT JOIN raw_captures c ON c.id=(
                           SELECT c2.id FROM raw_captures c2 WHERE c2.listing_id=l.id
                            ORDER BY c2.captured_at DESC,c2.rowid DESC LIMIT 1
                       )
                      WHERE l.canonical_job_id IN ({placeholders}) ORDER BY l.id""",
                chunk,
            ).fetchall()
            for row in rows:
                item = dict(row)
                by_job[str(row["job_id"])].append(item)
                if row["capture_id"]:
                    by_capture[str(row["capture_id"])] = item
        return by_job, by_capture

    @staticmethod
    def _load_facts(connection: Any, by_capture: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        grouped: dict[str, dict[str, Any]] = {}
        capture_ids = sorted(by_capture)
        for chunk in _chunks(capture_ids):
            placeholders = ",".join("?" for _ in chunk)
            rows = connection.execute(
                f"""SELECT f.*,r.extractor_kind,r.extractor_version,
                            n.id AS mapping_id,n.rule_version AS mapping_rule_version,
                            n.confidence AS mapping_confidence,n.mapping_origin,
                            n.is_manual AS mapping_is_manual,n.created_at AS mapping_created_at,
                            c.id AS concept_id,c.concept_type,c.concept_key,c.display_label,c.aliases_json
                       FROM extracted_facts f
                       JOIN extraction_runs r ON r.id=f.extraction_run_id
                       LEFT JOIN fact_normalizations n ON n.fact_id=f.id AND n.state='active'
                       LEFT JOIN normalization_concepts c ON c.id=n.concept_id AND c.active=1
                      WHERE f.capture_id IN ({placeholders})
                        AND f.fact_type IN ('skill','tool','language','certification')
                        AND f.validation_state='valid' AND f.state!='explicit_negative'
                        AND r.status IN ('completed','completed_with_warnings')
                      ORDER BY f.created_at,f.id,n.is_manual DESC,n.created_at DESC,n.id""",
                chunk,
            ).fetchall()
            for row in rows:
                fact_id = str(row["id"])
                if fact_id not in grouped:
                    fact = dict(row)
                    fact["job_id"] = by_capture[str(row["capture_id"])]["job_id"]
                    fact["listing_id"] = by_capture[str(row["capture_id"])]["listing_id"]
                    fact["source_key"] = by_capture[str(row["capture_id"])]["source_key"]
                    fact["mappings"] = []
                    grouped[fact_id] = fact
                if row["concept_id"]:
                    grouped[fact_id]["mappings"].append({
                        "conceptId": row["concept_id"], "conceptType": row["concept_type"],
                        "conceptKey": row["concept_key"], "displayLabel": row["display_label"],
                        "aliases": _loads(row["aliases_json"], []),
                        "ruleVersion": row["mapping_rule_version"],
                        "confidence": row["mapping_confidence"],
                        "origin": row["mapping_origin"], "isManual": bool(row["mapping_is_manual"]),
                    })
        result = []
        for fact in grouped.values():
            mappings = fact.pop("mappings")
            preferred = [item for item in mappings if item["isManual"]] or mappings
            unique = {item["conceptId"]: item for item in preferred}
            fact["mapping"] = next(iter(unique.values())) if len(unique) == 1 else None
            fact["mapping_status"] = "mapped" if len(unique) == 1 else ("ambiguous" if unique else "unmapped")
            result.append(fact)
        return result

    @staticmethod
    def _legacy_facts(job: dict[str, Any]) -> list[dict[str, Any]]:
        requirements = _loads(job.get("requirements_json"), {})
        result = []
        groups = (("mustHave", "skill", "required"), ("niceToHave", "skill", "preferred"), ("tools", "tool", "unknown"))
        for field, fact_type, preference in groups:
            values = requirements.get(field) if isinstance(requirements, dict) else []
            for index, value in enumerate(values if isinstance(values, list) else []):
                wording = str(value or "").strip()
                if wording:
                    result.append({
                        "id": f"canonical:{job['id']}:{field}:{index}", "job_id": job["id"],
                        "listing_id": None, "source_key": job.get("source_name") or "legacy",
                        "fact_type": fact_type, "source_wording": wording,
                        "requirement_preference": preference, "confidence": 1.0,
                        "extractor_kind": "canonical_legacy", "mapping": None,
                        "mapping_status": "unmapped", "evidence_locator_json": "{}",
                    })
        return result

    @staticmethod
    def _profile_match(concept: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
        terms = {
            _normalize(concept["conceptKey"]), _normalize(concept["displayLabel"]),
            *(_normalize(item) for item in concept.get("aliases", [])),
        }
        terms.discard("")
        concept_type = concept["conceptType"]
        if concept_type in {"skill", "tool", "programming_language"}:
            collection = "skills"
            matches = [
                item for item in profile.get("skills", [])
                if _normalize(item.get("normalized_key")) in terms or _normalize(item.get("display_name")) in terms
            ]
            primary_fields = {"level": "level", "confidence": "confidence", "developmentInterest": "development_interest"}
        elif concept_type == "spoken_language":
            collection = "languages"
            matches = [item for item in profile.get("languages", []) if _normalize(item.get("language_name")) in terms]
            primary_fields = {"level": "proficiency", "confidence": "confidence"}
        elif concept_type == "certification":
            collection = "certifications"
            matches = [item for item in profile.get("certifications", []) if _normalize(item.get("name")) in terms]
            primary_fields = {}
        else:
            collection, matches, primary_fields = "skills", [], {}
        primary = matches[0] if matches else {}
        evidence = [
            {
                "id": row.get("id"), "fieldName": row.get("field_name"),
                "origin": row.get("origin"), "sourceReference": row.get("source_reference"),
                "notes": row.get("notes"),
            }
            for row in profile.get("evidence", [])
            if row.get("target_type") == collection and row.get("target_id") in {None, primary.get("id")}
        ] if primary else []
        result = {
            "exists": bool(matches), "collection": collection,
            "recordId": primary.get("id"),
            "displayName": primary.get("display_name") or primary.get("language_name") or primary.get("name"),
            "origin": primary.get("origin"), "evidenceReferences": evidence,
        }
        for public, source in primary_fields.items():
            result[public] = primary.get(source)
        return result

    @staticmethod
    def _source_mix(jobs: list[dict[str, Any]], sources: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
        result = {"nav": 0, "pracuj": 0, "manual": 0, "other": 0, "multiSource": 0}
        for job in jobs:
            keys = {item["source_key"] for item in sources.get(job["id"], [])}
            if not keys:
                raw = _normalize(job.get("source_name"))
                keys = {"manual" if raw == "manual" else "other"}
            if len(keys) > 1:
                result["multiSource"] += 1
            for key in keys:
                result[key if key in {"nav", "pracuj", "manual"} else "other"] += 1
        return result

    @staticmethod
    def _serialize_job(job: dict[str, Any], sources: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "id": job["id"], "company": job.get("company"), "role": job.get("role_title"),
            "location": {"city": job.get("location_city"), "country": job.get("location_country")},
            "timeAnchor": job.get("anchor_at"), "timeAnchorKind": job.get("anchor_kind"),
            "sources": sorted({item["source_key"] for item in sources}) or [job.get("source_name") or "unknown"],
        }

    def build(self, track_id: str, *, population: Any = "current", window: Any = "90d") -> dict[str, Any]:
        mode, selected_window = self._validate_query(population, window)
        now = _as_utc(self.now_provider())
        profile = self.store.get_profile()
        policy = self.store.get_track_evaluation_policy(track_id)
        with self.store.read_connection() as connection:
            track, jobs, start, end = self._population(
                connection, track_id, mode=mode, window=selected_window, now=now,
            )
            job_ids = [str(job["id"]) for job in jobs]
            job_lookup = {str(job["id"]): job for job in jobs}
            source_rows, by_capture = self._load_sources_and_captures(connection, job_ids)
            facts = self._load_facts(connection, by_capture)
            mapped_job_facts = defaultdict(list)
            for fact in facts:
                mapped_job_facts[str(fact["job_id"])].append(fact)
            for job in jobs:
                if not mapped_job_facts[str(job["id"])]:
                    fallback = self._legacy_facts(job)
                    facts.extend(fallback)
                    mapped_job_facts[str(job["id"])].extend(fallback)
            mapping_fingerprint, mapping_versions = self._mapping_state(connection)

            concepts: dict[str, dict[str, Any]] = {}
            unmapped: dict[tuple[str, str], dict[str, Any]] = {}
            fact_concepts: dict[str, str] = {}
            evidence_jobs: set[str] = set()
            for fact in facts:
                job_id = str(fact["job_id"])
                evidence_jobs.add(job_id)
                mapping = fact.get("mapping")
                wording = str(fact.get("source_wording") or "").strip()
                if mapping:
                    reference = f"{mapping['conceptType']}:{mapping['conceptKey']}"
                    fact_concepts[str(fact["id"])] = reference
                    concept = concepts.setdefault(reference, {
                        "reference": reference, **mapping, "jobFacts": defaultdict(list),
                        "termJobs": defaultdict(set), "termObservations": defaultdict(int),
                    })
                    concept["jobFacts"][job_id].append(fact)
                    concept["termJobs"][wording].add(job_id)
                    concept["termObservations"][wording] += 1
                else:
                    key = (str(fact["fact_type"]), _normalize(wording))
                    term = unmapped.setdefault(key, {
                        "term": wording, "factType": fact["fact_type"],
                        "normalizationStatus": fact.get("mapping_status") or "unmapped",
                        "jobIds": set(), "observations": 0, "samples": [],
                    })
                    term["jobIds"].add(job_id)
                    term["observations"] += 1
                    if len(term["samples"]) < 3:
                        term["samples"].append({
                            "jobId": job_id, "sourceWording": wording,
                            "source": fact.get("source_key"), "factId": fact.get("id"),
                        })

            current_policy = policy or {}
            track_value = {
                "id": track["id"], "countries": track["countries"],
                "regions_cities": track["regions_cities"],
                "remote_allowed": None if track.get("remote_allowed") is None else bool(track["remote_allowed"]),
                "relocation_relevant": None if track.get("relocation_relevant") is None else bool(track["relocation_relevant"]),
                "primary_currency": track.get("primary_currency"),
            }
            context_fingerprint = evaluation_fingerprint(track_context(track_value))
            current_evaluations: dict[str, dict[str, Any]] = {}
            stale_evaluations = 0
            if job_ids and current_policy:
                for chunk in _chunks(job_ids):
                    placeholders = ",".join("?" for _ in chunk)
                    rows = connection.execute(
                        f"""SELECT c.job_id,e.* FROM evaluation_current c
                               JOIN evaluations e ON e.id=c.evaluation_id
                              WHERE c.track_id=? AND c.job_id IN ({placeholders})""",
                        (track_id, *chunk),
                    ).fetchall()
                    for row in rows:
                        item = dict(row)
                        job = job_lookup[str(item["job_id"])]
                        projection_fingerprint = job.get("latest_projection_fingerprint") or evaluation_fingerprint({
                            "schemaVersion": "canonical-job-row@1", "job": self._fallback_projection(job),
                        })
                        expected = evaluation_input_fingerprint(
                            profile_fingerprint=str(profile["fingerprint"]),
                            projection_fingerprint=projection_fingerprint,
                            policy_fingerprint=str(current_policy["fingerprint"]),
                            track_context_fingerprint=context_fingerprint,
                        )
                        if item.get("status") == "completed" and item.get("input_fingerprint") == expected:
                            current_evaluations[str(item["job_id"])] = item
                        else:
                            stale_evaluations += 1

            findings_by_job: dict[str, list[dict[str, Any]]] = defaultdict(list)
            evaluation_ids = [item["id"] for item in current_evaluations.values()]
            evaluation_job_by_id = {item["id"]: job_id for job_id, item in current_evaluations.items()}
            for chunk in _chunks(evaluation_ids):
                placeholders = ",".join("?" for _ in chunk)
                for row in connection.execute(
                    f"SELECT * FROM evaluation_findings WHERE evaluation_id IN ({placeholders}) ORDER BY evaluation_id,rowid",
                    chunk,
                ):
                    item = dict(row)
                    item["job_fact_ids"] = _loads(item.pop("job_fact_ids_json"), [])
                    item["display"] = _loads(item.pop("display_params_json"), {})
                    item["job_evidence"] = _loads(item.pop("job_evidence_json"), [])
                    item["concept_references"] = sorted({
                        fact_concepts[fact_id] for fact_id in item["job_fact_ids"] if fact_id in fact_concepts
                    })
                    findings_by_job[evaluation_job_by_id[item["evaluation_id"]]].append(item)

            total_jobs = len(jobs)
            evaluated_jobs = len(current_evaluations)
            coverage = {
                "totalJobs": total_jobs,
                "jobsWithSkillEvidence": len(evidence_jobs),
                "jobsWithoutSkillEvidence": total_jobs - len(evidence_jobs),
                "jobsWithCurrentEvaluations": evaluated_jobs,
                "jobsMissingCurrentEvaluations": total_jobs - evaluated_jobs,
                "staleEvaluationPointers": stale_evaluations,
                "skillEvidenceRate": len(evidence_jobs) / total_jobs if total_jobs else 0.0,
                "evaluationRate": evaluated_jobs / total_jobs if total_jobs else 0.0,
            }
            skill_rows = []
            for reference, concept in concepts.items():
                demand_jobs = set(concept["jobFacts"])
                class_jobs: dict[str, set[str]] = defaultdict(set)
                demand_evidence = []
                for job_id, job_facts in concept["jobFacts"].items():
                    requirement = _requirement_class(
                        fact.get("requirement_preference") for fact in job_facts
                    )
                    class_jobs[requirement].add(job_id)
                    demand_evidence.append({
                        **self._serialize_job(job_lookup[job_id], source_rows.get(job_id, [])),
                        "requirementClass": requirement,
                        "sourceTerms": sorted({str(item.get("source_wording") or "") for item in job_facts}),
                        "factIds": sorted({str(item["id"]) for item in job_facts}),
                    })

                state_jobs: dict[str, set[str]] = defaultdict(set)
                requirement_gap_jobs: dict[str, set[str]] = defaultdict(set)
                evaluated_mentions = set()
                missing_finding_jobs = set()
                finding_jobs = []
                for job_id in sorted(demand_jobs):
                    if job_id not in current_evaluations:
                        continue
                    matches = [
                        item for item in findings_by_job.get(job_id, [])
                        if reference in item["concept_references"]
                    ]
                    if not matches:
                        missing_finding_jobs.add(job_id)
                        continue
                    evaluated_mentions.add(job_id)
                    state = _finding_state(matches)
                    state_jobs[state].add(job_id)
                    finding_jobs.append({
                        **self._serialize_job(job_lookup[job_id], source_rows.get(job_id, [])),
                        "state": state,
                        "findings": [
                            {
                                "status": item["status"],
                                "requirementClass": item["requirement_class"],
                                "label": item["display"].get("label"),
                                "jobFactIds": item["job_fact_ids"],
                            }
                            for item in matches
                        ],
                    })
                    for item in matches:
                        if item["status"] == "gap":
                            requirement_gap_jobs[item["requirement_class"]].add(job_id)

                strict_jobs, potential_jobs, multi_gap_jobs = [], [], []
                for job_id in sorted(demand_jobs):
                    if job_id not in current_evaluations:
                        continue
                    all_findings = findings_by_job.get(job_id, [])
                    candidate = [
                        item for item in all_findings
                        if reference in item["concept_references"]
                        and item["status"] == "gap" and item["requirement_class"] == "required"
                    ]
                    if not candidate:
                        continue
                    unrelated_blockers = [
                        item for item in all_findings
                        if item["status"] == "blocker" and reference not in item["concept_references"]
                    ]
                    other_required_gaps = [
                        item for item in all_findings
                        if item["status"] == "gap" and item["requirement_class"] == "required"
                        and reference not in item["concept_references"]
                    ]
                    remaining_unknowns = [
                        item for item in all_findings
                        if item["status"] == "unknown" and item["requirement_class"] == "required"
                        and reference not in item["concept_references"]
                    ]
                    job_value = self._serialize_job(job_lookup[job_id], source_rows.get(job_id, []))
                    if unrelated_blockers:
                        continue
                    if other_required_gaps:
                        multi_gap_jobs.append({
                            **job_value, "reason": "Another required GAP remains.",
                            "remainingGapLabels": [item["display"].get("label") for item in other_required_gaps],
                        })
                    elif remaining_unknowns:
                        potential_jobs.append({
                            **job_value, "reason": "This is the only known required GAP, but required UNKNOWN evidence remains.",
                            "remainingUnknownLabels": [item["display"].get("label") for item in remaining_unknowns],
                        })
                    else:
                        strict_jobs.append({
                            **job_value, "reason": "This is the only remaining required GAP and no unrelated blocker remains.",
                        })

                user_counts = {
                    state: len(state_jobs[state])
                    for state in ("supported", "partial", "gap", "blocker", "unknown")
                }
                profile_evidence = self._profile_match(concept, profile)
                row = {
                    "reference": reference, "conceptId": concept["conceptId"],
                    "conceptType": concept["conceptType"], "conceptKey": concept["conceptKey"],
                    "displayLabel": concept["displayLabel"],
                    "normalization": {
                        "ruleVersions": sorted({
                            item.get("mapping", {}).get("ruleVersion")
                            for job_facts in concept["jobFacts"].values() for item in job_facts
                            if item.get("mapping", {}).get("ruleVersion")
                        }),
                        "manualMappingUsed": any(
                            item.get("mapping", {}).get("isManual")
                            for job_facts in concept["jobFacts"].values() for item in job_facts
                        ),
                    },
                    "sourceTerms": [
                        {
                            "term": term, "jobCount": len(concept["termJobs"][term]),
                            "observationCount": concept["termObservations"][term],
                            "jobIds": sorted(concept["termJobs"][term]),
                        }
                        for term in sorted(concept["termJobs"], key=lambda value: (-len(concept["termJobs"][value]), value.casefold()))
                    ],
                    "demand": {
                        "jobsMentioning": len(demand_jobs),
                        "requiredJobs": len(class_jobs["required"]),
                        "preferredJobs": len(class_jobs["preferred"]),
                        "optionalJobs": len(class_jobs["optional"]),
                        "unknownRequirementJobs": len(class_jobs["unknown"]),
                        "ambiguousRequirementJobs": len(class_jobs["ambiguous"]),
                        "notMentionedJobs": total_jobs - len(demand_jobs),
                        "totalTrackJobs": total_jobs,
                        "jobsWithSkillEvidence": len(evidence_jobs),
                        "percentAllTrackJobs": _percent(len(demand_jobs), total_jobs),
                        "percentSkillBearingJobs": _percent(len(demand_jobs), len(evidence_jobs)),
                    },
                    "profileEvidence": profile_evidence,
                    "user": {
                        **user_counts, "blockers": user_counts["blocker"],
                        "state": _public_user_state(user_counts),
                        "requiredGaps": len(requirement_gap_jobs["required"]),
                        "preferredGaps": len(requirement_gap_jobs["preferred"]),
                        "optionalGaps": len(requirement_gap_jobs["optional"]),
                        "unknownRequirementGaps": len(requirement_gap_jobs["unknown"]),
                        "evaluatedJobsMentioning": len(evaluated_mentions),
                        "evaluatedJobsMissingConceptFinding": len(missing_finding_jobs),
                        "unknownRate": (
                            len(state_jobs["unknown"]) / len(evaluated_mentions)
                            if evaluated_mentions else None
                        ),
                    },
                    "opportunity": {
                        "strictJobsUnlocked": len(strict_jobs),
                        "potentialJobsUnlocked": len(potential_jobs),
                        "multiGapOpportunities": len(multi_gap_jobs),
                    },
                    "_detail": {
                        "demandJobs": demand_evidence[:MAX_DETAIL_JOBS],
                        "findingJobs": finding_jobs[:MAX_DETAIL_JOBS],
                        "strictUnlockJobs": strict_jobs[:MAX_DETAIL_JOBS],
                        "potentialUnlockJobs": potential_jobs[:MAX_DETAIL_JOBS],
                        "multiGapJobs": multi_gap_jobs[:MAX_DETAIL_JOBS],
                    },
                }
                row["priority"] = _priority(row, coverage)
                skill_rows.append(row)

            priority_order = {"high": 0, "medium": 1, "low": 2, "monitor": 3, "insufficient_evidence": 4}
            skill_rows.sort(key=lambda item: (
                priority_order[item["priority"]["classification"]],
                -item["demand"]["requiredJobs"], -item["demand"]["jobsMentioning"],
                item["displayLabel"].casefold(),
            ))
            unmapped_rows = [
                {
                    "term": value["term"], "factType": value["factType"],
                    "jobCount": len(value["jobIds"]), "observationCount": value["observations"],
                    "normalizationStatus": value["normalizationStatus"],
                    "sampleEvidence": value["samples"],
                }
                for value in unmapped.values() if value["term"]
            ]
            unmapped_rows.sort(key=lambda item: (-item["jobCount"], item["term"].casefold()))
            source_fingerprint_rows = [
                (job["id"], job.get("latest_projection_fingerprint"), job.get("anchor_at"),
                 tuple((item["listing_id"], item["lifecycle_state"], item.get("capture_id")) for item in source_rows.get(job["id"], [])))
                for job in jobs
            ]
            population_fingerprint = _fingerprint({
                "track": {"id": track["id"], "status": track["status"], "updatedAt": track["updated_at"]},
                "mode": mode, "window": selected_window, "jobs": source_fingerprint_rows,
            })
            evaluation_fingerprint_value = _fingerprint(sorted(
                (job_id, item["id"], item["input_fingerprint"]) for job_id, item in current_evaluations.items()
            ))
            strengths = [
                {"reference": item["reference"], "displayLabel": item["displayLabel"],
                 "jobsMentioning": item["demand"]["jobsMentioning"], "requiredJobs": item["demand"]["requiredJobs"],
                 "supportedJobs": item["user"]["supported"]}
                for item in skill_rows
                if item["user"]["supported"] > 0 and item["user"]["requiredGaps"] == 0 and item["user"]["blockers"] == 0
            ][:10]
            unknown_areas = [
                {"reference": item["reference"], "displayLabel": item["displayLabel"],
                 "jobsMentioning": item["demand"]["jobsMentioning"], "requiredJobs": item["demand"]["requiredJobs"],
                 "unknownJobs": item["user"]["unknown"]}
                for item in skill_rows
                if not item["profileEvidence"]["exists"] and item["user"]["unknown"] > 0
            ][:10]
            return {
                "track": {"id": track["id"], "name": track["name"], "status": track["status"]},
                "population": {
                    "mode": mode, "window": "current" if mode == "current" else selected_window,
                    "startAt": start, "endAt": end, "canonicalJobDenominator": total_jobs,
                    "semantics": (
                        "Active, non-archived, non-expired deduplicated Canonical Jobs relevant to this Track."
                        if mode == "current" else
                        "Deduplicated Canonical Jobs anchored inside the selected window; inactive and archived jobs remain historical evidence."
                    ),
                    "timeAnchorHierarchy": ["source publication/date-posted fact", "first source observation", "Canonical Job created timestamp"],
                    "fingerprint": population_fingerprint,
                },
                "coverage": coverage,
                "sourceMix": self._source_mix(jobs, source_rows),
                "versions": {
                    "skillIntelligence": SKILL_INTELLIGENCE_VERSION,
                    "mappingFingerprint": mapping_fingerprint,
                    "mappingRuleVersions": mapping_versions,
                    "profileFingerprint": profile["fingerprint"],
                    "evaluationFingerprint": evaluation_fingerprint_value,
                    "evaluatorVersion": EVALUATOR_VERSION if current_evaluations else None,
                },
                "priorityPolicy": PRIORITY_POLICY,
                "skills": skill_rows,
                "strengths": strengths,
                "unknownProfileAreas": unknown_areas,
                "unmapped": {"termCount": len(unmapped_rows), "terms": unmapped_rows[:MAX_UNMAPPED_TERMS]},
                "generatedAt": end,
                "materialization": {"strategy": "bounded_live_query", "durableSnapshot": False},
            }

    @staticmethod
    def _filter_and_sort(
        result: dict[str, Any], *, requirement_class: Any = "all", user_state: Any = "all",
        minimum_demand: Any = 0, sort: Any = "priority",
    ) -> dict[str, Any]:
        requirement = str(requirement_class or "all")
        state = str(user_state or "all")
        sort_value = str(sort or "priority")
        if requirement not in REQUIREMENT_CLASSES:
            raise JobhuntError("Invalid requirementClass filter", code="invalid_skill_requirement_class")
        if state not in USER_STATES:
            raise JobhuntError("Invalid userState filter", code="invalid_skill_user_state")
        if sort_value not in SORTS:
            raise JobhuntError("Invalid Skill Intelligence sort", code="invalid_skill_sort")
        try:
            minimum = int(minimum_demand or 0)
        except (TypeError, ValueError) as exc:
            raise JobhuntError("minimumDemand must be an integer", code="invalid_skill_minimum_demand") from exc
        if not 0 <= minimum <= MAX_POPULATION:
            raise JobhuntError("minimumDemand is out of range", code="invalid_skill_minimum_demand")
        key_by_requirement = {
            "required": "requiredJobs", "preferred": "preferredJobs", "optional": "optionalJobs",
            "unknown": "unknownRequirementJobs", "ambiguous": "ambiguousRequirementJobs",
        }
        rows = [item for item in result["skills"] if item["demand"]["jobsMentioning"] >= minimum]
        if requirement != "all":
            rows = [item for item in rows if item["demand"][key_by_requirement[requirement]] > 0]
        if state != "all":
            rows = [item for item in rows if item["user"]["state"] == state]
        sorters = {
            "required": lambda item: (-item["demand"]["requiredJobs"], -item["demand"]["jobsMentioning"], item["displayLabel"].casefold()),
            "demand": lambda item: (-item["demand"]["jobsMentioning"], -item["demand"]["requiredJobs"], item["displayLabel"].casefold()),
            "gaps": lambda item: (-item["user"]["requiredGaps"], -item["user"]["blockers"], item["displayLabel"].casefold()),
            "unlocked": lambda item: (-item["opportunity"]["strictJobsUnlocked"], -item["opportunity"]["potentialJobsUnlocked"], item["displayLabel"].casefold()),
            "unknown": lambda item: (-(item["user"]["unknownRate"] or 0), -item["user"]["unknown"], item["displayLabel"].casefold()),
            "alphabetical": lambda item: (item["displayLabel"].casefold(),),
            "priority": lambda item: ({"high": 0, "medium": 1, "low": 2, "monitor": 3, "insufficient_evidence": 4}[item["priority"]["classification"]], -item["demand"]["requiredJobs"], item["displayLabel"].casefold()),
        }
        rows.sort(key=sorters[sort_value])
        result["skills"] = rows
        result["filters"] = {
            "requirementClass": requirement, "userState": state,
            "minimumDemand": minimum, "sort": sort_value,
        }
        return result

    def intelligence(self, track_id: str, **query: Any) -> dict[str, Any]:
        result = self.build(track_id, population=query.get("population"), window=query.get("window"))
        result = self._filter_and_sort(
            result, requirement_class=query.get("requirement_class"),
            user_state=query.get("user_state"), minimum_demand=query.get("minimum_demand"),
            sort=query.get("sort"),
        )
        for row in result["skills"]:
            row.pop("_detail", None)
        return result

    def detail(self, track_id: str, concept_reference: str, **query: Any) -> dict[str, Any]:
        reference = str(concept_reference or "")
        if not reference or len(reference) > 240 or not re.fullmatch(r"[A-Za-z0-9_+.#:-]+", reference):
            raise JobhuntError("Invalid concept key", code="invalid_skill_concept")
        result = self.build(track_id, population=query.get("population"), window=query.get("window"))
        skill = next((item for item in result["skills"] if item["reference"] == reference), None)
        if not skill:
            raise JobhuntError("Skill concept not found in this population", status=404, code="skill_concept_not_found")
        detail = skill.pop("_detail")
        skill.update(detail)
        return {
            "track": result["track"], "population": result["population"],
            "coverage": result["coverage"], "versions": result["versions"],
            "priorityPolicy": result["priorityPolicy"], "skill": skill,
            "generatedAt": result["generatedAt"],
        }

    def unmapped(self, track_id: str, **query: Any) -> dict[str, Any]:
        result = self.build(track_id, population=query.get("population"), window=query.get("window"))
        return {
            "track": result["track"], "population": result["population"],
            "coverage": result["coverage"], "versions": result["versions"],
            "unmapped": result["unmapped"], "generatedAt": result["generatedAt"],
        }

    def meta(self, track_id: str, **query: Any) -> dict[str, Any]:
        result = self.build(track_id, population=query.get("population"), window=query.get("window"))
        return {
            key: result[key] for key in (
                "track", "population", "coverage", "sourceMix", "versions",
                "priorityPolicy", "generatedAt", "materialization",
            )
        }


__all__ = [
    "MAX_POPULATION", "PRIORITY_POLICY", "SKILL_INTELLIGENCE_VERSION",
    "SkillIntelligenceReadModel",
]
