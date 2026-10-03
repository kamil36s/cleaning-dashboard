"""Deterministic, evidence-backed career hypotheses and experiment templates."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any, Callable
import unicodedata

from .analytics import JobhuntAnalyticsReadModel, _dt, _fingerprint, _loads


CAREER_ADJACENCY_VERSION = "career-adjacency@1"
CAREER_INTELLIGENCE_VERSION = "career-intelligence@1"
MINIMUM_ADJACENT_JOBS = 3
ROLE_STOPWORDS = {
    "senior", "junior", "mid", "middle", "lead", "principal", "staff", "intern",
    "trainee", "specialist", "worker", "employee", "position", "job", "remote",
    "hybrid", "part", "full", "time",
}

EXPERIMENT_TEMPLATES = (
    {
        "id": "playwright-mini-test@1",
        "title": "Playwright mini-test",
        "hypothesis": "A small browser-automation task will clarify whether test automation is energising enough to explore further.",
        "taskDefinition": "Automate one realistic web flow with assertions, one failure case, and a short README.",
        "taskDefinitionVersion": "playwright-mini-test@1",
        "plannedMinutes": 90,
        "record": ["interest", "difficulty", "frustration", "desire to continue"],
    },
    {
        "id": "sql-analysis@1",
        "title": "SQL analysis sprint",
        "hypothesis": "A bounded data-analysis task will test interest in SQL-heavy work.",
        "taskDefinition": "Answer three practical questions from a small local dataset using documented SQL queries and a short conclusion.",
        "taskDefinitionVersion": "sql-analysis@1",
        "plannedMinutes": 90,
        "record": ["interest", "difficulty", "frustration", "desire to continue"],
    },
    {
        "id": "requirements-spec@1",
        "title": "Requirements specification trial",
        "hypothesis": "Writing a concise specification will test interest in analysis and coordination work.",
        "taskDefinition": "Choose one familiar workflow and write scope, actors, acceptance criteria, edge cases, and open questions.",
        "taskDefinitionVersion": "requirements-spec@1",
        "plannedMinutes": 75,
        "record": ["interest", "difficulty", "frustration", "desire to continue"],
    },
    {
        "id": "norwegian-workplace-language@1",
        "title": "Norwegian workplace-language task",
        "hypothesis": "A realistic language task will clarify the current cost of working in Norwegian.",
        "taskDefinition": "Read a short workplace instruction, extract actions and risks, then write a brief Norwegian response.",
        "taskDefinitionVersion": "norwegian-workplace-language@1",
        "plannedMinutes": 60,
        "record": ["interest", "difficulty", "frustration", "desire to continue"],
    },
    {
        "id": "physical-work-trial@1",
        "title": "Physical-work trial",
        "hypothesis": "A safe, self-chosen physical task will provide direct evidence about energy, strain, and desire to continue.",
        "taskDefinition": "Complete one safe representative session. Record the task, duration, conditions, energy before/after, discomfort, and recovery. Stop if unsafe.",
        "taskDefinitionVersion": "physical-work-trial@1",
        "plannedMinutes": 90,
        "record": ["interest", "difficulty", "frustration", "desire to continue"],
    },
)


def _normalize(value: Any) -> str:
    folded = unicodedata.normalize("NFKD", str(value or ""))
    return " ".join(re.findall(r"[a-z0-9]+", folded.casefold()))


def _role_family(value: Any) -> tuple[str, str]:
    tokens = [token for token in _normalize(value).split() if token not in ROLE_STOPWORDS]
    if not tokens:
        return "", ""
    key = " ".join(tokens[:5])
    display = " ".join(token.upper() if token in {"qa", "sql", "ui", "ux", "it"} else token.title() for token in tokens[:5])
    return key, display


class CareerIntelligenceReadModel:
    """Career hypotheses derived from observed jobs; never a decision or ranking."""

    def __init__(
        self,
        store: Any,
        analytics: JobhuntAnalyticsReadModel,
        *,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self.store = store
        self.analytics = analytics
        self.now_provider = now_provider or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def templates() -> list[dict[str, Any]]:
        return [dict(item) for item in EXPERIMENT_TEMPLATES]

    @staticmethod
    def template(template_id: str) -> dict[str, Any] | None:
        return next((dict(item) for item in EXPERIMENT_TEMPLATES if item["id"] == template_id), None)

    @staticmethod
    def _profile_terms(profile: dict[str, Any]) -> tuple[set[str], dict[str, dict[str, Any]]]:
        terms = set()
        evidence = {}
        for row in profile.get("skills", []):
            for value in (row.get("normalized_key"), row.get("display_name")):
                normalized = _normalize(value)
                if normalized:
                    terms.add(normalized)
                    evidence[normalized] = {
                        "recordId": row.get("id"), "displayName": row.get("display_name"),
                        "level": row.get("level"), "confidence": row.get("confidence"),
                        "origin": row.get("origin"),
                    }
        for row in profile.get("languages", []):
            normalized = _normalize(row.get("language_name"))
            if normalized:
                terms.add(normalized)
                evidence[normalized] = {
                    "recordId": row.get("id"), "displayName": row.get("language_name"),
                    "level": row.get("proficiency"), "confidence": row.get("confidence"),
                    "origin": row.get("origin"),
                }
        for row in profile.get("certifications", []):
            normalized = _normalize(row.get("name"))
            if normalized:
                terms.add(normalized)
                evidence[normalized] = {
                    "recordId": row.get("id"), "displayName": row.get("name"),
                    "origin": row.get("origin"),
                }
        return terms, evidence

    @staticmethod
    def _concept_rows(connection: Any, job_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        result: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
        for index in range(0, len(job_ids), 300):
            chunk = job_ids[index:index + 300]
            placeholders = ",".join("?" for _ in chunk)
            rows = connection.execute(
                f"""SELECT l.canonical_job_id AS job_id,f.id AS fact_id,f.fact_type,
                            f.requirement_preference,f.source_wording,c.concept_type,
                            c.concept_key,c.display_label,n.rule_version,n.mapping_origin
                       FROM source_listings l
                       JOIN raw_captures rc ON rc.id=(
                         SELECT rc2.id FROM raw_captures rc2 WHERE rc2.listing_id=l.id
                          ORDER BY rc2.captured_at DESC,rc2.rowid DESC LIMIT 1
                       )
                       JOIN extracted_facts f ON f.capture_id=rc.id
                       JOIN fact_normalizations n ON n.fact_id=f.id AND n.state='active'
                       JOIN normalization_concepts c ON c.id=n.concept_id AND c.active=1
                      WHERE l.canonical_job_id IN ({placeholders})
                        AND f.fact_type IN ('skill','tool','language','certification')
                        AND f.validation_state='valid' AND f.state!='explicit_negative'
                      ORDER BY n.is_manual DESC,n.created_at DESC,n.id""",
                chunk,
            ).fetchall()
            for row in rows:
                item = dict(row)
                reference = f"{item['concept_type']}:{item['concept_key']}"
                result[str(item["job_id"])].setdefault(reference, item)
        return {job_id: list(values.values()) for job_id, values in result.items()}

    @staticmethod
    def _track_context(connection: Any, job_ids: list[str]) -> tuple[dict[str, set[str]], dict[str, str]]:
        by_job: dict[str, set[str]] = defaultdict(set)
        names = {row["id"]: row["name"] for row in connection.execute("SELECT id,name FROM career_tracks")}
        for index in range(0, len(job_ids), 300):
            chunk = job_ids[index:index + 300]
            placeholders = ",".join("?" for _ in chunk)
            for row in connection.execute(
                f"""SELECT job_id,track_id FROM track_job_assignments
                     WHERE active=1 AND job_id IN ({placeholders})""", chunk
            ):
                by_job[str(row["job_id"])].add(str(row["track_id"]))
            for row in connection.execute(
                f"""SELECT l.canonical_job_id AS job_id,x.track_id FROM source_listings l
                     JOIN source_listing_tracks x ON x.listing_id=l.id
                     WHERE l.canonical_job_id IN ({placeholders})""", chunk
            ):
                by_job[str(row["job_id"])].add(str(row["track_id"]))
        return by_job, names

    @staticmethod
    def _evaluation_findings(connection: Any, job_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        result: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for index in range(0, len(job_ids), 300):
            chunk = job_ids[index:index + 300]
            placeholders = ",".join("?" for _ in chunk)
            for row in connection.execute(
                f"""SELECT c.job_id,c.track_id,f.status,f.requirement_class,
                            f.concept_key,f.display_params_json
                       FROM evaluation_current c JOIN evaluations e ON e.id=c.evaluation_id
                       JOIN evaluation_findings f ON f.evaluation_id=e.id
                      WHERE c.job_id IN ({placeholders}) AND e.status='completed'
                        AND f.status IN ('gap','blocker','unknown')""", chunk
            ):
                item = dict(row)
                item["display"] = _loads(item.pop("display_params_json"), {})
                result[str(row["job_id"])].append(item)
        return result

    @staticmethod
    def _is_existing_direction(family_key: str, texts: list[str]) -> bool:
        family = set(family_key.split())
        if not family:
            return True
        for text in texts:
            tokens = set(_normalize(text).split())
            if family <= tokens or len(family & tokens) / len(family) >= .67:
                return True
        return False

    def adjacent(self) -> dict[str, Any]:
        now = self.now_provider()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        now = now.astimezone(timezone.utc)
        profile = self.store.get_profile()
        profile_terms, profile_evidence = self._profile_terms(profile)
        with self.store.read_connection() as connection:
            jobs = self.analytics._current(self.analytics._population(connection), now)
            job_ids = [str(row["id"]) for row in jobs]
            concepts = self._concept_rows(connection, job_ids)
            sources = self.analytics._source_rows(connection, job_ids)
            track_context, track_names = self._track_context(connection, job_ids)
            findings = self._evaluation_findings(connection, job_ids)
            existing_texts = []
            for row in connection.execute("SELECT name,purpose FROM career_tracks WHERE status!='archived'"):
                existing_texts.extend([row["name"], row["purpose"]])
            for row in connection.execute(
                "SELECT name,role_intent,include_keywords_json FROM track_search_profiles WHERE status!='archived'"
            ):
                existing_texts.extend([row["name"], row["role_intent"] or "", " ".join(_loads(row["include_keywords_json"], []))])
            preferences = [dict(row) for row in connection.execute(
                "SELECT dimension_key,value_json,importance,confidence,origin FROM career_preferences ORDER BY dimension_key"
            )]
            assessment_rows = [dict(row) for row in connection.execute(
                """SELECT r.instrument_id,r.instrument_version,r.completed_at,s.dimension,s.normalized_score
                     FROM assessment_runs r JOIN assessment_scores s ON s.run_id=r.id
                    WHERE r.status='completed' AND r.completed_at=(
                      SELECT MAX(r2.completed_at) FROM assessment_runs r2
                       WHERE r2.instrument_id=r.instrument_id AND r2.status='completed')
                    ORDER BY r.instrument_id,s.dimension"""
            )]

        families: dict[str, dict[str, Any]] = {}
        for job in jobs:
            key, display = _role_family(job.get("role_title"))
            if not key:
                continue
            family = families.setdefault(key, {
                "key": key, "display": display, "jobs": [], "conceptJobs": defaultdict(set),
                "concepts": {}, "countries": Counter(), "workModels": Counter(),
                "sources": set(), "tracks": set(), "gaps": Counter(), "unknowns": Counter(),
            })
            job_id = str(job["id"])
            family["jobs"].append(job)
            country = str(job.get("location_country") or "Unknown")
            family["countries"][country if country.strip().casefold() not in {"", "unknown"} else "Unknown"] += 1
            work_model = str(job.get("work_mode") or "Unknown")
            family["workModels"][work_model if work_model.strip().casefold() not in {"", "unknown"} else "Unknown"] += 1
            family["sources"].update(item["source_key"] for item in sources.get(job_id, []))
            family["tracks"].update(track_context.get(job_id, set()))
            for concept in concepts.get(job_id, []):
                normalized = _normalize(concept["concept_key"])
                reference = f"{concept['concept_type']}:{concept['concept_key']}"
                family["conceptJobs"][reference].add(job_id)
                family["concepts"][reference] = {**concept, "normalized": normalized}
            for finding in findings.get(job_id, []):
                label = finding.get("concept_key") or finding["display"].get("label") or finding["display"].get("requirement") or "Unspecified requirement"
                if finding["status"] in {"gap", "blocker"}:
                    family["gaps"][str(label)] += 1
                elif finding["status"] == "unknown":
                    family["unknowns"][str(label)] += 1

        suggestions = []
        proposals = []
        decisions = {item["proposalKey"]: item for item in self.store.list_track_proposals()}
        for family in families.values():
            observed = len(family["jobs"])
            if observed < MINIMUM_ADJACENT_JOBS:
                continue
            recurring = sorted(
                ((reference, len(ids)) for reference, ids in family["conceptJobs"].items()),
                key=lambda item: (-item[1], item[0]),
            )
            shared = []
            for reference, count in recurring:
                concept = family["concepts"][reference]
                candidates = {_normalize(concept["concept_key"]), _normalize(concept["display_label"])}
                match = next((term for term in candidates if term in profile_terms), None)
                if match:
                    shared.append({
                        "reference": reference, "displayLabel": concept["display_label"],
                        "observedJobs": count, "profileEvidence": profile_evidence[match],
                    })
            if not shared:
                continue
            evidence_types = ["observed_job_supply", "profile_skill_overlap"]
            if family["gaps"]:
                evidence_types.append("current_evaluation_findings")
            if family["countries"]:
                evidence_types.append("geography")
            if len(family["sources"]) > 1:
                evidence_types.append("cross_source_recurrence")
            confidence = "limited evidence"
            if observed >= 5 and len(shared) >= 2:
                confidence = "emerging pattern"
            if observed >= 10 and len(shared) >= 3 and len(family["sources"]) >= 2:
                confidence = "established pattern"
            existing = self._is_existing_direction(family["key"], existing_texts)
            examples = [{
                "id": row["id"], "role": row["role_title"], "company": row["company"],
                "country": row.get("location_country"), "workModel": row.get("work_mode"),
            } for row in family["jobs"][:5]]
            suggestion = {
                "roleFamily": family["display"],
                "roleFamilyKey": family["key"],
                "observedJobCount": observed,
                "population": {"entity": "CanonicalJob", "denominator": len(jobs), "scope": "current active observed market"},
                "sourcePopulation": sorted(family["sources"]),
                "trackPopulation": [{"id": item, "name": track_names.get(item, item)} for item in sorted(family["tracks"])],
                "sharedStrengths": shared[:10],
                "recurringSkills": [{
                    "reference": reference,
                    "displayLabel": family["concepts"][reference]["display_label"],
                    "jobCount": count,
                } for reference, count in recurring[:10]],
                "explicitGaps": [{"label": key, "jobs": value} for key, value in family["gaps"].most_common(8)],
                "unknowns": [{"label": key, "jobs": value} for key, value in family["unknowns"].most_common(8)],
                "geography": [{"value": key, "jobs": value} for key, value in family["countries"].most_common()],
                "workModels": [{"value": key, "jobs": value} for key, value in family["workModels"].most_common()],
                "examples": examples,
                "whySuggested": [
                    f"{observed} recurring active Canonical Jobs share this normalized title family.",
                    f"{len(shared)} recurring concepts have explicit Career Profile evidence.",
                    "Current Pack J gaps and unknowns are shown separately where available.",
                ],
                "confidenceCategory": confidence,
                "evidenceTypes": evidence_types,
                "existingTrackDirection": existing,
            }
            suggestions.append(suggestion)
            if not existing and len(evidence_types) >= 3:
                dominant_country = family["countries"].most_common(1)[0][0] if family["countries"] else "Unknown"
                name = family["display"] if dominant_country == "Unknown" else f"{family['display']} - {dominant_country}"
                proposal_key = "proposal_" + hashlib.sha256(
                    f"{CAREER_INTELLIGENCE_VERSION}|{family['key']}|{dominant_country}".encode("utf-8")
                ).hexdigest()[:24]
                evidence = {
                    "adjacency": suggestion,
                    "proposedGeography": [] if dominant_country == "Unknown" else [dominant_country],
                    "methodVersion": CAREER_INTELLIGENCE_VERSION,
                }
                decision = decisions.get(proposal_key)
                proposals.append({
                    "proposalKey": proposal_key,
                    "proposedName": name,
                    "roleFamily": family["display"],
                    "state": decision["state"] if decision else "suggested",
                    "acceptedTrackId": decision.get("acceptedTrackId") if decision else None,
                    "evidence": evidence,
                    "evidenceFingerprint": _fingerprint(evidence),
                    "automaticCreation": False,
                })

        suggestions.sort(key=lambda item: (-item["observedJobCount"], item["roleFamily"].casefold()))
        proposals.sort(key=lambda item: (-item["evidence"]["adjacency"]["observedJobCount"], item["proposedName"].casefold()))
        assessment_context = [{
            "instrumentId": row["instrument_id"], "instrumentVersion": row["instrument_version"],
            "dimension": row["dimension"], "normalizedScore": row["normalized_score"],
            "completedAt": row["completed_at"],
        } for row in assessment_rows]
        preference_context = [{
            "dimensionKey": row["dimension_key"], "value": _loads(row["value_json"], None),
            "importance": row["importance"], "confidence": row["confidence"], "origin": row["origin"],
        } for row in preferences]
        return {
            "versions": {
                "careerAdjacency": CAREER_ADJACENCY_VERSION,
                "careerIntelligence": CAREER_INTELLIGENCE_VERSION,
            },
            "population": {
                "entity": "CanonicalJob", "denominator": len(jobs),
                "semantics": "Current active, non-expired, deduplicated Canonical Jobs.",
            },
            "minimumSample": MINIMUM_ADJACENT_JOBS,
            "method": {
                "components": ["normalized title family", "shared normalized concepts", "Profile evidence", "current Evaluation findings", "geography", "source recurrence"],
                "embeddings": False,
                "personalityGeneratesSuggestions": False,
            },
            "suggestions": suggestions,
            "trackProposals": proposals,
            "supportingContext": {
                "preferences": preference_context,
                "assessments": assessment_context,
                "use": "Supporting context only. Assessments and preferences do not create, score, or rank suggestions.",
            },
            "fingerprint": _fingerprint({
                "version": CAREER_INTELLIGENCE_VERSION,
                "profile": profile.get("fingerprint"),
                "jobs": [(row["id"], row.get("updated_at")) for row in jobs],
                "suggestions": [(row["roleFamilyKey"], row["observedJobCount"]) for row in suggestions],
            }),
            "generatedAt": now.isoformat(timespec="seconds"),
            "semantics": "Suggestions are hypotheses for user review, not career decisions.",
        }
