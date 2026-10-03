"""Deterministic, evidence-backed Career Profile x Job x Track evaluation."""

from __future__ import annotations

from datetime import date
import hashlib
import json
import re
from typing import Any, Iterable
import unicodedata


EVALUATOR_VERSION = "evaluator@1"
EVALUATION_SCHEMA_VERSION = "jobhunt-evaluation@1"
POLICY_SCHEMA_VERSION = "track-evaluation-policy@1"
DIMENSIONS = ("skills", "experience", "compensation", "geography", "preferences")
IMPORTANCE = frozenset({"primary", "secondary", "informational"})
BLOCKER_KEYS = (
    "compensation", "trackGeography", "workModel", "contract", "schedule",
    "relocation", "language",
)
CEFR = {"A1": 1, "A2": 2, "B1": 3, "B2": 4, "C1": 5, "C2": 6}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fingerprint(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def default_policy() -> dict[str, Any]:
    return {
        "schemaVersion": POLICY_SCHEMA_VERSION,
        "dimensions": {
            "skills": {"enabled": True, "importance": "primary"},
            "experience": {"enabled": True, "importance": "primary"},
            "compensation": {"enabled": True, "importance": "secondary"},
            "geography": {"enabled": True, "importance": "primary"},
            "preferences": {"enabled": True, "importance": "secondary"},
        },
        "blockers": {
            "compensation": True,
            "trackGeography": True,
            "workModel": True,
            "contract": True,
            "schedule": True,
            "relocation": True,
            "language": False,
        },
        "skillThresholds": {"partialMin": 1, "supportedMin": 3},
        "unknownHandling": "preserve",
        "aggregate": "none",
    }


def validate_policy(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Evaluation Policy must be an object")
    allowed = {"schemaVersion", "dimensions", "blockers", "skillThresholds", "unknownHandling", "aggregate"}
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError("Unsupported Evaluation Policy fields: " + ", ".join(unknown))
    if value.get("schemaVersion") != POLICY_SCHEMA_VERSION:
        raise ValueError(f"schemaVersion must be {POLICY_SCHEMA_VERSION}")
    if value.get("unknownHandling") != "preserve":
        raise ValueError("unknownHandling must be preserve")
    if value.get("aggregate") != "none":
        raise ValueError("aggregate must be none")

    raw_dimensions = value.get("dimensions")
    if not isinstance(raw_dimensions, dict) or set(raw_dimensions) != set(DIMENSIONS):
        raise ValueError("dimensions must contain exactly the known Pack J dimensions")
    dimensions: dict[str, Any] = {}
    for key in DIMENSIONS:
        entry = raw_dimensions.get(key)
        if not isinstance(entry, dict) or set(entry) != {"enabled", "importance"}:
            raise ValueError(f"dimensions.{key} has unsupported fields")
        if not isinstance(entry.get("enabled"), bool):
            raise ValueError(f"dimensions.{key}.enabled must be boolean")
        importance = entry.get("importance")
        if importance not in IMPORTANCE:
            raise ValueError(f"dimensions.{key}.importance is invalid")
        dimensions[key] = {"enabled": entry["enabled"], "importance": importance}

    raw_blockers = value.get("blockers")
    if not isinstance(raw_blockers, dict) or set(raw_blockers) != set(BLOCKER_KEYS):
        raise ValueError("blockers must contain exactly the known blocker categories")
    blockers = {}
    for key in BLOCKER_KEYS:
        if not isinstance(raw_blockers.get(key), bool):
            raise ValueError(f"blockers.{key} must be boolean")
        blockers[key] = raw_blockers[key]

    thresholds = value.get("skillThresholds")
    if not isinstance(thresholds, dict) or set(thresholds) != {"partialMin", "supportedMin"}:
        raise ValueError("skillThresholds must contain partialMin and supportedMin")
    partial = thresholds.get("partialMin")
    supported = thresholds.get("supportedMin")
    if isinstance(partial, bool) or isinstance(supported, bool):
        raise ValueError("Skill thresholds must be integers")
    if not isinstance(partial, int) or not isinstance(supported, int):
        raise ValueError("Skill thresholds must be integers")
    if not (0 <= partial < supported <= 5):
        raise ValueError("Skill thresholds must satisfy 0 <= partialMin < supportedMin <= 5")
    return {
        "schemaVersion": POLICY_SCHEMA_VERSION,
        "dimensions": dimensions,
        "blockers": blockers,
        "skillThresholds": {"partialMin": partial, "supportedMin": supported},
        "unknownHandling": "preserve",
        "aggregate": "none",
    }


def track_context(track: dict[str, Any]) -> dict[str, Any]:
    return {
        "trackId": track.get("id"),
        "countries": sorted(str(item).upper() for item in (track.get("countries") or [])),
        "regionsCities": sorted(str(item) for item in (track.get("regions_cities") or [])),
        "remoteAllowed": track.get("remote_allowed"),
        "relocationRelevant": track.get("relocation_relevant"),
        "primaryCurrency": str(track.get("primary_currency") or "").upper() or None,
    }


def input_fingerprint(
    *, profile_fingerprint: str, projection_fingerprint: str,
    policy_fingerprint: str, track_context_fingerprint: str,
) -> str:
    return fingerprint({
        "profileFingerprint": profile_fingerprint,
        "projectionFingerprint": projection_fingerprint,
        "policyFingerprint": policy_fingerprint,
        "trackContextFingerprint": track_context_fingerprint,
        "evaluatorVersion": EVALUATOR_VERSION,
        "evaluationSchemaVersion": EVALUATION_SCHEMA_VERSION,
    })


def normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).casefold()
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9+#.]+", text))


def _known(value: Any) -> bool:
    return value not in (None, "", "unknown", "UNKNOWN", "not specified", "n/a")


def _fact_value(fact: dict[str, Any]) -> Any:
    return {
        "text": fact.get("value_text"),
        "number": fact.get("value_number"),
        "boolean": fact.get("value_boolean"),
        "json": fact.get("value_json"),
    }.get(fact.get("value_type"))


def _job_evidence(fact: dict[str, Any] | None, context: dict[str, Any], field: str) -> tuple[list[str], list[dict[str, Any]]]:
    projection = context.get("projection") or {}
    if fact:
        return [str(fact["id"])], [{
            "type": "extracted_fact", "id": fact["id"], "field": field,
            "sourceWording": fact.get("source_wording"),
            "extractor": fact.get("extractor_kind"),
            "evidenceLocator": fact.get("evidence_locator") or {},
        }]
    return [], [{
        "type": "canonical_projection" if projection else "canonical_job",
        "id": projection.get("id") or context["job"].get("id"),
        "field": field,
        "projectionFingerprint": context["projection_fingerprint"],
    }]


def _profile_evidence(context: dict[str, Any], kind: str, item: dict[str, Any] | None, field: str) -> list[dict[str, Any]]:
    if not item:
        return []
    evidence = []
    for row in context["profile"].get("evidence", []):
        if row.get("target_type") == kind and row.get("target_id") in (None, item.get("id")):
            evidence.append(row.get("id"))
    return [{
        "type": kind, "id": item.get("id"), "field": field,
        "origin": item.get("origin"), "evidenceIds": evidence,
    }]


def _policy_evidence(context: dict[str, Any], path: str) -> dict[str, Any]:
    policy = context["policy_record"]
    return {
        "policyId": policy["id"], "policyVersion": policy["policy_version"],
        "policyFingerprint": policy["fingerprint"], "path": path,
    }


def _finding(
    context: dict[str, Any], dimension: str, status: str, requirement: str,
    explanation_code: str, *, label: str, job_value: Any = None,
    profile_value: Any = None, concept_key: str | None = None,
    fact: dict[str, Any] | None = None, field: str = "",
    profile_kind: str = "profile", profile_item: dict[str, Any] | None = None,
    policy_path: str | None = None, summary: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fact_ids, job_evidence = _job_evidence(fact, context, field or dimension)
    finding_type = {
        "supported": "support", "partial": "partial", "gap": "gap",
        "blocker": "blocker", "unknown": "unknown_requirement",
        "not_applicable": "informational",
    }[status]
    params = {
        "label": label, "jobValue": job_value, "profileValue": profile_value,
        "summary": summary or explanation_code.replace("_", " ").capitalize(),
    }
    params.update(extra or {})
    return {
        "dimension": dimension,
        "finding_type": finding_type,
        "status": status,
        "importance": context["policy"]["dimensions"][dimension]["importance"],
        "requirement_class": requirement if requirement in {"required", "preferred", "optional", "unknown"} else "not_applicable",
        "concept_key": concept_key,
        "job_fact_ids": fact_ids,
        "job_evidence": job_evidence,
        "profile_evidence": _profile_evidence(context, profile_kind, profile_item, field),
        "policy_evidence": _policy_evidence(context, policy_path or f"dimensions.{dimension}"),
        "explanation_code": explanation_code,
        "display_params": params,
    }


def _fact_for(context: dict[str, Any], *types: str) -> dict[str, Any] | None:
    return next((fact for fact in context["facts"] if fact.get("fact_type") in types), None)


def _requirements(context: dict[str, Any], types: set[str]) -> list[dict[str, Any]]:
    facts = [
        fact for fact in context["facts"]
        if fact.get("fact_type") in types and fact.get("validation_state", "valid") == "valid"
    ]
    if facts:
        return facts
    if not types.intersection({"skill", "tool"}):
        return []
    raw = context["job"].get("requirements_json") or "{}"
    try:
        requirements = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, json.JSONDecodeError):
        requirements = {}
    result = []
    for key, requirement in (("mustHave", "required"), ("niceToHave", "preferred"), ("tools", "unknown")):
        for index, item in enumerate(requirements.get(key) or []):
            result.append({
                "id": f"canonical:{context['job']['id']}:{key}:{index}",
                "fact_type": "tool" if key == "tools" else "skill",
                "source_wording": str(item), "value_type": "text", "value_text": str(item),
                "requirement_preference": requirement, "state": "explicit_positive",
                "validation_state": "valid", "concept_key": None, "display_label": None,
            })
    return result


def _aggregate(findings: list[dict[str, Any]]) -> str:
    states = {item["status"] for item in findings}
    if "blocker" in states:
        return "blocker"
    if "gap" in states:
        return "gap"
    if "partial" in states or ("supported" in states and "unknown" in states):
        return "partial"
    if "unknown" in states:
        return "unknown"
    if "supported" in states:
        return "supported"
    return "not_applicable"


def _evaluate_skills(context: dict[str, Any]) -> list[dict[str, Any]]:
    thresholds = context["policy"]["skillThresholds"]
    profiles = context["profile"].get("skills", [])
    findings = []
    for fact in _requirements(context, {"skill", "tool"}):
        if fact.get("state") == "explicit_negative":
            continue
        value = str(_fact_value(fact) or fact.get("source_wording") or "").strip()
        concept = str(fact.get("concept_key") or "").strip()
        exact = normalize_text(fact.get("display_label") or value)
        match = None
        for skill in profiles:
            profile_key = str(skill.get("normalized_key") or "").strip()
            if concept and profile_key and normalize_text(profile_key) == normalize_text(concept):
                match = skill
                break
            if normalize_text(skill.get("display_name")) == exact:
                match = skill
                break
        requirement = fact.get("requirement_preference") or "unknown"
        if not match:
            findings.append(_finding(
                context, "skills", "unknown", requirement, "skill_profile_evidence_missing",
                label=value or "Skill", job_value=value, concept_key=concept or exact,
                fact=fact, field="skill", policy_path="skillThresholds",
                summary=f"{value or 'Skill'} is requested, but the Career Profile has no matching skill evidence.",
            ))
            continue
        level = match.get("level")
        if level is None:
            status, code = "unknown", "skill_level_unknown"
            summary = f"{match.get('display_name')} is recorded, but its level is unknown."
        elif int(level) >= int(thresholds["supportedMin"]):
            status, code = "supported", "skill_level_supported"
            summary = f"Profile level {level} meets the policy supported threshold {thresholds['supportedMin']}."
        elif int(level) >= int(thresholds["partialMin"]):
            status, code = "partial", "skill_level_partial"
            summary = f"Profile level {level} is below the policy supported threshold {thresholds['supportedMin']}."
        else:
            status, code = "gap", "skill_level_gap"
            summary = f"Profile level {level} is below the policy partial threshold {thresholds['partialMin']}."
        findings.append(_finding(
            context, "skills", status, requirement, code, label=value or "Skill",
            job_value=value, profile_value={"name": match.get("display_name"), "level": level},
            concept_key=concept or exact, fact=fact, field="level", profile_kind="skills",
            profile_item=match, policy_path="skillThresholds", summary=summary,
            extra={"partialMin": thresholds["partialMin"], "supportedMin": thresholds["supportedMin"]},
        ))
    return findings


def _cefr(value: Any) -> str | None:
    match = re.search(r"\b([ABC][12])\b", str(value or "").upper())
    return match.group(1) if match else None


def _language_name(fact: dict[str, Any]) -> str:
    if fact.get("display_label"):
        return str(fact["display_label"])
    text = re.sub(r"\b[ABC][12]\b", "", str(_fact_value(fact) or fact.get("source_wording") or ""), flags=re.I)
    text = re.sub(r"\b(required|preferred|optional|minimum|fluent|level)\b", "", text, flags=re.I)
    return " ".join(text.split()).strip(" -:,")


def _evaluate_languages(context: dict[str, Any]) -> list[dict[str, Any]]:
    findings = []
    profiles = context["profile"].get("languages", [])
    for fact in _requirements(context, {"language"}):
        name = _language_name(fact) or str(_fact_value(fact) or "Language")
        requirement = fact.get("requirement_preference") or "unknown"
        if fact.get("state") == "explicit_negative":
            findings.append(_finding(
                context, "preferences", "supported", "not_applicable", "language_explicitly_not_required",
                label=name, job_value=fact.get("source_wording"), fact=fact, field="language",
                summary=f"The advertisement explicitly says {name} is not required.",
            ))
            continue
        concept = normalize_text(fact.get("concept_key") or name)
        match = next((item for item in profiles if normalize_text(item.get("language_name")) in {concept, normalize_text(name)}), None)
        required_level = _cefr(_fact_value(fact)) or _cefr(fact.get("source_wording"))
        if not match:
            findings.append(_finding(
                context, "preferences", "unknown", requirement, "language_profile_evidence_missing",
                label=name, job_value=fact.get("source_wording"), concept_key=concept,
                fact=fact, field="language", policy_path="blockers.language",
                summary=f"{name} is requested, but the Career Profile has no matching language evidence.",
            ))
            continue
        profile_level = _cefr(match.get("proficiency"))
        if required_level and not profile_level:
            status, code = "unknown", "language_profile_level_unknown"
            summary = f"{name} is recorded, but no comparable CEFR level is available."
        elif required_level and profile_level and CEFR[profile_level] < CEFR[required_level]:
            hard = bool(context["policy"]["blockers"]["language"] and requirement == "required")
            status, code = ("blocker", "language_level_blocker") if hard else ("gap", "language_level_gap")
            summary = f"Job level {required_level} exceeds Profile level {profile_level}."
        else:
            status, code = "supported", "language_supported"
            summary = (
                f"Profile level {profile_level} meets job level {required_level}."
                if required_level else f"The Career Profile records {name}; the job does not state a comparable CEFR level."
            )
        findings.append(_finding(
            context, "preferences", status, requirement, code, label=name,
            job_value=fact.get("source_wording"), profile_value=match.get("proficiency"),
            concept_key=concept, fact=fact, field="proficiency", profile_kind="languages",
            profile_item=match, policy_path="blockers.language", summary=summary,
        ))
    return findings


def _years_requirement(value: Any) -> float | None:
    match = re.search(r"\b(\d+(?:[.,]\d+)?)\s*\+?\s*(?:years?|yrs?|years? of|ar|år)\b", str(value or ""), re.I)
    return float(match.group(1).replace(",", ".")) if match else None


def _date_value(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def _experience_years(records: Iterable[dict[str, Any]], as_of: date) -> float | None:
    intervals = []
    for item in records:
        start = _date_value(item.get("start_date"))
        end = as_of if item.get("is_current") else _date_value(item.get("end_date"))
        if not start or not end or end < start:
            return None
        intervals.append((start, end))
    if not intervals:
        return None
    intervals.sort()
    merged: list[list[date]] = []
    for start, end in intervals:
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        elif end > merged[-1][1]:
            merged[-1][1] = end
    return round(sum((end - start).days for start, end in merged) / 365.2425, 2)


def _evaluate_experience(context: dict[str, Any]) -> list[dict[str, Any]]:
    findings = []
    records = context["profile"].get("experience", [])
    stop = {"experience", "years", "year", "required", "minimum", "with", "and", "the", "of", "in"}
    job_role_tokens = set(normalize_text(context["job"].get("role_title")).split()) - stop
    changed = _date_value(context.get("profile_changed_at")) or date(1970, 1, 1)
    for fact in _requirements(context, {"experience"}):
        if fact.get("state") == "explicit_negative":
            continue
        wording = str(_fact_value(fact) or fact.get("source_wording") or "")
        required = _years_requirement(wording)
        tokens = set(normalize_text(wording).split()) - stop
        tokens = {token for token in tokens if not token.replace(".", "").isdigit()}
        relevant = []
        for item in records:
            profile_tokens = set(normalize_text(item.get("job_title")).split())
            for domain in item.get("domains_json") or []:
                profile_tokens.update(normalize_text(domain).split())
            target = tokens or job_role_tokens
            if target and target.intersection(profile_tokens):
                relevant.append(item)
        requirement = fact.get("requirement_preference") or "unknown"
        if not relevant:
            findings.append(_finding(
                context, "experience", "unknown", requirement, "experience_not_comparable",
                label="Experience", job_value=wording, fact=fact, field="experience",
                summary="The job experience requirement cannot be mapped safely to a structured Profile experience record.",
            ))
            continue
        if required is None:
            findings.append(_finding(
                context, "experience", "supported", requirement, "experience_relevant_record_supported",
                label="Experience", job_value=wording,
                profile_value=[item.get("job_title") for item in relevant], fact=fact,
                field="job_title", profile_kind="experience", profile_item=relevant[0],
                summary="A directly relevant structured Profile experience record exists; the job states no comparable duration.",
            ))
            continue
        years = _experience_years(relevant, changed)
        if years is None:
            status, code = "unknown", "experience_duration_unknown"
            summary = "Relevant Profile experience exists, but its structured dates are insufficient for a safe duration comparison."
        elif years >= required:
            status, code = "supported", "experience_years_supported"
            summary = f"{years:g} derived years meet the explicit {required:g}-year requirement."
        else:
            status, code = "gap", "experience_years_gap"
            summary = f"{years:g} derived years are below the explicit {required:g}-year requirement."
        finding = _finding(
            context, "experience", status, requirement, code, label="Experience",
            job_value={"wording": wording, "requiredYears": required},
            profile_value={"derivedYears": years, "asOf": changed.isoformat()}, fact=fact,
            field="dates", profile_kind="experience", profile_item=relevant[0],
            summary=summary, extra={"profileRecordIds": [item.get("id") for item in relevant]},
        )
        finding["profile_evidence"] = [
            evidence
            for item in relevant
            for evidence in _profile_evidence(context, "experience", item, "dates")
        ]
        findings.append(finding)
    return findings


def _value_set(value: Any) -> set[str]:
    if isinstance(value, dict):
        for key in (
            "allowed", "values", "types", "value", "preferred", "prohibited",
            "countries",
        ):
            if key in value:
                return _value_set(value[key])
        return set()
    if isinstance(value, (list, tuple, set)):
        return {normalize_text(item) for item in value if _known(item)}
    return {normalize_text(value)} if _known(value) else set()


def _salary_floor(context: dict[str, Any]) -> dict[str, Any] | None:
    for item in context["profile"].get("constraints", []):
        if normalize_text(item.get("constraint_key")).replace(" ", "_") in {
            "minimum_salary", "salary_floor", "minimum_compensation",
        }:
            value = item.get("value_json")
            if isinstance(value, (int, float)):
                value = {"amount": value}
            if isinstance(value, dict) and isinstance(value.get("amount"), (int, float)):
                return {**value, "record": item}
    return None


def _evaluate_compensation(context: dict[str, Any]) -> list[dict[str, Any]]:
    floor = _salary_floor(context)
    salary_fact = _fact_for(context, "salary_min", "salary_max", "salary_exact")
    if not floor:
        return [_finding(
            context, "compensation", "unknown", "not_applicable", "salary_constraint_missing",
            label="Compensation", job_value=None, fact=salary_fact, field="salary",
            summary="No explicit Career Profile salary floor exists, so compensation alignment is unknown.",
        )]
    job = context["job"]
    minimum, maximum = job.get("salary_min"), job.get("salary_max")
    currency = str(job.get("salary_currency") or "").upper() if _known(job.get("salary_currency")) else ""
    period = normalize_text(job.get("salary_period")) if _known(job.get("salary_period")) else ""
    tax = normalize_text(job.get("salary_tax_type")) if _known(job.get("salary_tax_type")) else ""
    record = floor["record"]
    profile_value = {key: value for key, value in floor.items() if key != "record"}
    job_value = {"min": minimum, "max": maximum, "currency": currency, "period": period or None, "taxType": tax or None}
    if minimum is None and maximum is None:
        status, code, summary = "unknown", "salary_job_value_missing", "The job has no explicit salary range."
    else:
        floor_currency = str(floor.get("currency") or "").upper()
        floor_period = normalize_text(floor.get("period"))
        floor_tax = normalize_text(floor.get("taxType") or floor.get("grossNet"))
        unsafe = (
            not floor_currency or not currency or floor_currency != currency
            or not floor_period or not period or floor_period != period
            or bool(floor_tax) != bool(tax) or (floor_tax and tax and floor_tax != tax)
        )
        if unsafe:
            status, code, summary = "unknown", "salary_not_comparable", "Salary currency, period, or gross/net state is not safely comparable."
        elif maximum is not None and float(maximum) < float(floor["amount"]):
            hard = bool(record.get("is_hard")) and context["policy"]["blockers"]["compensation"]
            status, code = ("blocker", "salary_floor_blocker") if hard else ("gap", "salary_floor_gap")
            summary = f"The job maximum {maximum:g} {currency} is below the explicit floor {floor['amount']:g} {currency}."
        elif maximum is None and minimum is not None and float(minimum) < float(floor["amount"]):
            status, code = "unknown", "salary_upper_bound_missing"
            summary = "The stated salary minimum is below the floor, but no maximum exists to prove the whole range is below it."
        else:
            status, code, summary = "supported", "salary_floor_supported", "The explicit job range reaches or exceeds the Career Profile salary floor."
    return [_finding(
        context, "compensation", status, "not_applicable", code, label="Compensation",
        job_value=job_value, profile_value=profile_value, fact=salary_fact,
        field="salary", profile_kind="constraints", profile_item=record,
        policy_path="blockers.compensation", summary=summary,
    )]


COUNTRIES = {"poland": "PL", "pl": "PL", "norway": "NO", "no": "NO", "iceland": "IS", "is": "IS"}


def _country(value: Any) -> str:
    normalized = normalize_text(value)
    return COUNTRIES.get(normalized, normalized.upper())


def _constraint(context: dict[str, Any], *keys: str) -> dict[str, Any] | None:
    wanted = {normalize_text(key).replace(" ", "_") for key in keys}
    return next((item for item in context["profile"].get("constraints", []) if normalize_text(item.get("constraint_key")).replace(" ", "_") in wanted), None)


def _evaluate_geography(context: dict[str, Any]) -> list[dict[str, Any]]:
    fact = _fact_for(context, "country", "location_text")
    job_country = _country(context["job"].get("location_country")) if _known(context["job"].get("location_country")) else ""
    countries = {_country(item) for item in context["track"].get("countries") or []}
    work_model = normalize_text(context["job"].get("work_mode"))
    if not job_country:
        status, code, summary = "unknown", "job_geography_missing", "The job has no explicit comparable country."
    elif job_country in countries or (work_model == "remote" and context["track"].get("remote_allowed") is True):
        status, code, summary = "supported", "track_geography_supported", "The job geography is compatible with the Track context."
    elif countries:
        hard = context["policy"]["blockers"]["trackGeography"]
        status, code = ("blocker", "track_geography_blocker") if hard else ("gap", "track_geography_gap")
        summary = f"Job country {job_country} conflicts with Track countries {', '.join(sorted(countries))}."
    else:
        status, code, summary = "unknown", "track_geography_missing", "The Track has no explicit country context."
    findings = [_finding(
        context, "geography", status, "not_applicable", code, label="Geography",
        job_value=job_country or None, profile_value={"trackCountries": sorted(countries)},
        fact=fact, field="location_country", policy_path="blockers.trackGeography", summary=summary,
    )]
    profile_geography = _constraint(
        context, "country", "allowed_countries", "prohibited_countries",
        "geography", "geography_countries",
    )
    if profile_geography:
        key = normalize_text(profile_geography.get("constraint_key")).replace(" ", "_")
        profile_countries = {
            _country(item) for item in _value_set(profile_geography.get("value_json"))
        }
        prohibited = key.startswith(("prohibited_", "forbidden_", "excluded_", "disallowed_"))
        if not job_country:
            profile_status, profile_code = "unknown", "profile_geography_job_value_missing"
            profile_summary = "The Career Profile has a geography constraint, but the job country is unknown."
        elif not profile_countries:
            profile_status, profile_code = "unknown", "profile_geography_constraint_unstructured"
            profile_summary = "The Career Profile geography constraint has no comparable country values."
        else:
            compatible = (
                job_country not in profile_countries if prohibited
                else job_country in profile_countries
            )
            if compatible:
                profile_status, profile_code = "supported", "profile_geography_supported"
                profile_summary = "The job country is compatible with the explicit Career Profile geography constraint."
            else:
                hard = bool(
                    profile_geography.get("is_hard")
                    and context["policy"]["blockers"]["trackGeography"]
                )
                profile_status, profile_code = (
                    ("blocker", "profile_geography_blocker")
                    if hard else ("gap", "profile_geography_gap")
                )
                profile_summary = "The job country conflicts with the explicit Career Profile geography constraint."
        findings.append(_finding(
            context, "geography", profile_status, "not_applicable", profile_code,
            label="Career Profile geography", job_value=job_country or None,
            profile_value=sorted(profile_countries), fact=fact, field="location_country",
            profile_kind="constraints", profile_item=profile_geography,
            policy_path="blockers.trackGeography", summary=profile_summary,
        ))
    relocation = _constraint(context, "relocation", "relocation_allowed")
    if context["track"].get("relocation_relevant") is True and relocation and relocation.get("value_json") is False:
        hard = bool(relocation.get("is_hard")) and context["policy"]["blockers"]["relocation"]
        status = "blocker" if hard else "gap"
        findings.append(_finding(
            context, "geography", status, "not_applicable", "relocation_conflict",
            label="Relocation", job_value={"trackRelocationRelevant": True}, profile_value=False,
            fact=fact, field="relocation", profile_kind="constraints", profile_item=relocation,
            policy_path="blockers.relocation",
            summary="This Track requires relocation relevance, while the Career Profile explicitly rejects relocation.",
        ))
    return findings


def _preference(context: dict[str, Any], *keys: str) -> dict[str, Any] | None:
    wanted = {normalize_text(key).replace(" ", "_") for key in keys}
    return next((item for item in context["profile"].get("preferences", []) if normalize_text(item.get("dimension_key")).replace(" ", "_") in wanted), None)


def _condition_finding(
    context: dict[str, Any], *, label: str, axis: str, job_value: Any,
    fact: dict[str, Any] | None, constraint_keys: tuple[str, ...],
    preference_keys: tuple[str, ...],
) -> dict[str, Any] | None:
    constraint = _constraint(context, *constraint_keys)
    preference = _preference(context, *preference_keys)
    evidence = constraint or preference
    if not evidence and not _known(job_value):
        return None
    if not _known(job_value):
        return _finding(
            context, "preferences", "unknown", "not_applicable", f"{axis}_job_value_missing",
            label=label, job_value=None, profile_value=(evidence or {}).get("value_json"),
            fact=fact, field=axis, profile_kind="constraints" if constraint else "preferences",
            profile_item=evidence, policy_path=f"blockers.{axis}",
            summary=f"The Career Profile records a {label.lower()} condition, but the job does not state one.",
        )
    if not evidence:
        return _finding(
            context, "preferences", "unknown", "not_applicable", f"{axis}_profile_evidence_missing",
            label=label, job_value=job_value, fact=fact, field=axis,
            policy_path=f"blockers.{axis}",
            summary=f"The job states {label.lower()} evidence, but the Career Profile has no comparable preference or constraint.",
        )
    profile_value = evidence.get("value_json")
    job_key = normalize_text(job_value)
    values = _value_set(profile_value)
    key = normalize_text(evidence.get("constraint_key") or evidence.get("dimension_key")).replace(" ", "_")
    prohibited = key.startswith(("prohibited_", "forbidden_", "excluded_", "disallowed_"))
    if isinstance(profile_value, bool):
        if key == "remote_work":
            comparable_bool = job_key == "remote"
        elif isinstance(job_value, bool):
            comparable_bool = job_value
        else:
            comparable_bool = job_key in {"true", "yes", "required", "allowed"}
        compatible = comparable_bool is profile_value
    else:
        compatible = (job_key not in values) if prohibited else (job_key in values)
    if compatible:
        status, code, summary = "supported", f"{axis}_supported", f"The explicit job {label.lower()} is compatible with the Career Profile evidence."
    else:
        hard = bool(constraint and constraint.get("is_hard") and context["policy"]["blockers"][axis])
        status, code = ("blocker", f"{axis}_blocker") if hard else ("gap", f"{axis}_preference_gap")
        summary = f"The explicit job {label.lower()} conflicts with the Career Profile {'constraint' if constraint else 'preference'}."
    return _finding(
        context, "preferences", status, "not_applicable", code, label=label,
        job_value=job_value, profile_value=profile_value, fact=fact, field=axis,
        profile_kind="constraints" if constraint else "preferences", profile_item=evidence,
        policy_path=f"blockers.{axis}", summary=summary,
    )


def _evaluate_preferences(context: dict[str, Any]) -> list[dict[str, Any]]:
    findings = _evaluate_languages(context)
    work_fact = _fact_for(context, "work_model")
    contract_fact = _fact_for(context, "contract_type")
    schedule_fact = _fact_for(context, "schedule", "shift_work", "employment_fraction")
    work_value = context["job"].get("work_mode")
    contract_value = context["job"].get("contract_type")
    schedule_value = _fact_value(schedule_fact) if schedule_fact else None
    candidates = (
        _condition_finding(
            context, label="Work model", axis="workModel", job_value=work_value,
            fact=work_fact, constraint_keys=("work_model", "allowed_work_models", "prohibited_work_models"),
            preference_keys=("work_model", "preferred_work_models", "remote_work"),
        ),
        _condition_finding(
            context, label="Contract", axis="contract", job_value=contract_value,
            fact=contract_fact, constraint_keys=("contract_type", "allowed_contract_types", "prohibited_contract_types"),
            preference_keys=("contract_type", "preferred_contract_types"),
        ),
        _condition_finding(
            context, label="Schedule", axis="schedule", job_value=schedule_value,
            fact=schedule_fact, constraint_keys=("schedule", "allowed_schedules", "forbidden_schedule"),
            preference_keys=("schedule", "preferred_schedule"),
        ),
    )
    findings.extend(item for item in candidates if item)
    return findings


def evaluate(context: dict[str, Any]) -> dict[str, Any]:
    policy = validate_policy(context["policy"])
    context = {**context, "policy": policy}
    builders = {
        "skills": _evaluate_skills,
        "experience": _evaluate_experience,
        "compensation": _evaluate_compensation,
        "geography": _evaluate_geography,
        "preferences": _evaluate_preferences,
    }
    findings: list[dict[str, Any]] = []
    dimensions = []
    for dimension in DIMENSIONS:
        rule = policy["dimensions"][dimension]
        current = builders[dimension](context) if rule["enabled"] else []
        state = _aggregate(current) if rule["enabled"] else "not_applicable"
        findings.extend(current)
        dimensions.append({
            "dimension": dimension, "state": state, "importance": rule["importance"],
            "finding_count": len(current),
            "explanation_code": "dimension_disabled" if not rule["enabled"] else f"dimension_{state}",
            "display_params": {"enabled": rule["enabled"]},
        })
    counts = {
        "blocker_count": sum(item["status"] == "blocker" for item in findings),
        "gap_count": sum(item["status"] == "gap" for item in findings),
        "unknown_count": sum(item["status"] == "unknown" for item in findings),
        "required_gap_count": sum(item["status"] == "gap" and item["requirement_class"] == "required" for item in findings),
        "supported_required_count": sum(item["status"] == "supported" and item["requirement_class"] == "required" for item in findings),
    }
    return {"dimensions": dimensions, "findings": findings, "counts": counts}


__all__ = [
    "BLOCKER_KEYS", "DIMENSIONS", "EVALUATION_SCHEMA_VERSION", "EVALUATOR_VERSION",
    "POLICY_SCHEMA_VERSION", "default_policy", "evaluate", "fingerprint",
    "input_fingerprint", "track_context", "validate_policy",
]
