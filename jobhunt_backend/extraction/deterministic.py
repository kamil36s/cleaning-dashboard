"""Bounded deterministic extraction from Pack D captures.

The parser never executes HTML, follows links, performs network access, or
interprets arbitrary advertisement prose. Only explicit structured values,
JSON-LD JobPosting objects, inert HTML metadata, and submitted listing hints
become facts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from html.parser import HTMLParser
import json
import re
from typing import Any, Iterable


OUTPUT_SCHEMA_VERSION = "jobhunt-facts@1"
EXTRACTOR_VERSIONS = {
    "json_structured": "json_structured@1",
    "nav_structured": "nav_structured@1",
    "json_ld_jobposting": "json_ld_jobposting@1",
    "html_metadata": "html_metadata@1",
    "manual_hints": "manual_hints@1",
}

MAX_JSON_DEPTH = 20
MAX_JSON_LD_BLOCKS = 32
MAX_JSON_LD_BYTES = 256 * 1024
MAX_FACTS_PER_RUN = 500
MAX_LIST_ITEMS = 100
MAX_SOURCE_WORDING = 8000
MAX_VALUE_TEXT = 8000


@dataclass(frozen=True)
class FactCandidate:
    namespace: str
    fact_type: str
    source_field: str
    source_wording: str
    value_type: str
    value_text: str | None = None
    value_number: float | None = None
    value_boolean: bool | None = None
    value_json: Any | None = None
    label: str | None = None
    unit: str | None = None
    currency: str | None = None
    period: str | None = None
    requirement_preference: str = "unknown"
    state: str = "explicit_positive"
    confidence: float = 0.99
    evidence_locator: dict[str, Any] = field(default_factory=dict)
    validation_state: str = "valid"
    validation_message: str | None = None


@dataclass(frozen=True)
class ExtractionBatch:
    kind: str
    version: str
    facts: tuple[FactCandidate, ...]
    warnings: tuple[str, ...] = ()


def _compact(value: Any, *, limit: int = MAX_SOURCE_WORDING) -> str:
    if isinstance(value, str):
        result = value
    else:
        result = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return result[:limit]


def _pointer_part(value: Any) -> str:
    return str(value).replace("~", "~0").replace("/", "~1")


def _pointer(base: str, *parts: Any) -> str:
    suffix = "/".join(_pointer_part(part) for part in parts)
    return f"{base.rstrip('/')}/{suffix}" if suffix else (base or "/")


def _text(value: Any, *, limit: int = MAX_VALUE_TEXT) -> str | None:
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        return None
    result = str(value).strip()
    return result[:limit] if result else None


def _number(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result and result not in (float("inf"), float("-inf")) else None


def _date_value(value: Any) -> tuple[str | None, str | None]:
    raw = _text(value, limit=100)
    if not raw:
        return None, "date is empty"
    try:
        if len(raw) == 10:
            return date.fromisoformat(raw).isoformat(), None
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed.isoformat(), None
    except ValueError:
        return raw, "date is not ISO-8601"


def _period(value: Any) -> str | None:
    token = re.sub(r"[^a-z]", "", str(value or "").casefold())
    return {
        "hour": "hour", "hourly": "hour", "hr": "hour",
        "day": "day", "daily": "day",
        "week": "week", "weekly": "week",
        "month": "month", "monthly": "month",
        "year": "year", "yearly": "year", "annual": "year", "annually": "year",
    }.get(token)


def _fact(
    fact_type: str,
    raw: Any,
    *,
    source_field: str,
    pointer: str,
    locator_kind: str = "json_pointer",
    namespace: str = "job",
    label: str | None = None,
    confidence: float = 0.99,
    preference: str = "unknown",
    state: str | None = None,
    unit: str | None = None,
    currency: str | None = None,
    period: str | None = None,
    script_index: int | None = None,
    value_override: Any = None,
) -> FactCandidate | None:
    value = raw if value_override is None else value_override
    evidence = {"kind": locator_kind, "pointer": pointer}
    if script_index is not None:
        evidence["scriptIndex"] = script_index
    source_wording = _compact(raw)
    validation_state = "valid"
    validation_message = None
    if isinstance(value, bool):
        value_type, value_boolean = "boolean", value
        value_text = value_number = value_json = None
        resolved_state = state or ("explicit_positive" if value else "explicit_negative")
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        value_type, value_number = "number", _number(value)
        value_text = value_boolean = value_json = None
        resolved_state = state or "explicit_positive"
        if value_number is None:
            validation_state, validation_message = "invalid", "number is not finite"
    elif isinstance(value, str):
        value_type, value_text = "text", value.strip()[:MAX_VALUE_TEXT]
        value_number = value_boolean = value_json = None
        resolved_state = state or "explicit_positive"
        if not value_text:
            return None
        if len(value) > MAX_VALUE_TEXT:
            validation_state, validation_message = "warning", "text was bounded"
    elif isinstance(value, (dict, list)):
        value_type, value_json = "json", value
        value_text = value_number = value_boolean = None
        resolved_state = state or "explicit_positive"
    else:
        return None
    if fact_type.startswith("salary_") and value_type == "number" and value_number is not None and value_number < 0:
        validation_state, validation_message = "invalid", "salary cannot be negative"
    if currency and not re.fullmatch(r"[A-Z]{3}", currency):
        validation_state, validation_message = "warning", "currency is not a three-letter code"
    return FactCandidate(
        namespace=namespace,
        fact_type=fact_type,
        source_field=source_field[:200],
        label=(label or None),
        source_wording=source_wording,
        value_type=value_type,
        value_text=value_text,
        value_number=value_number,
        value_boolean=value_boolean,
        value_json=value_json,
        unit=(unit[:80] if unit else None),
        currency=(currency[:12] if currency else None),
        period=period,
        requirement_preference=preference,
        state=resolved_state,
        confidence=max(0.0, min(1.0, confidence)),
        evidence_locator=evidence,
        validation_state=validation_state,
        validation_message=validation_message,
    )


def _first(mapping: dict[str, Any], *keys: str) -> tuple[str | None, Any]:
    for key in keys:
        if key in mapping and mapping[key] not in (None, "", [], {}):
            return key, mapping[key]
    return None, None


def _items(value: Any) -> list[Any]:
    return list(value[:MAX_LIST_ITEMS]) if isinstance(value, list) else ([value] if value not in (None, "") else [])


def _name(value: Any) -> Any:
    return value.get("name") if isinstance(value, dict) and value.get("name") else value


def _emit_list(
    facts: list[FactCandidate], fact_type: str, value: Any, *, source_field: str,
    pointer: str, locator_kind: str, script_index: int | None, preference: str = "unknown",
    confidence: float = 0.99,
) -> None:
    for index, item in enumerate(_items(value)):
        raw_item = item
        item_preference = preference
        item_state = None
        if isinstance(item, dict):
            named = item.get("name") or item.get("value") or item.get("label")
            if named is None:
                continue
            required = item.get("required")
            preferred = item.get("preferred")
            if required is False:
                item_state, item_preference = "explicit_negative", "required"
            elif required is True:
                item_preference = "required"
            elif preferred is True:
                item_preference = "preferred"
            raw_item, item = item, named
        candidate = _fact(
            fact_type, raw_item, source_field=source_field,
            pointer=_pointer(pointer, index) if isinstance(value, list) else pointer,
            locator_kind=locator_kind, script_index=script_index,
            preference=item_preference, confidence=confidence, state=item_state,
            value_override=item,
        )
        if candidate:
            facts.append(candidate)


def _extract_location(
    facts: list[FactCandidate], value: Any, *, pointer: str, locator_kind: str,
    script_index: int | None, confidence: float, fact_prefix: str = "",
) -> None:
    for index, place in enumerate(_items(value)):
        place_pointer = _pointer(pointer, index) if isinstance(value, list) else pointer
        if isinstance(place, str):
            candidate = _fact(f"{fact_prefix}location_text", place, source_field="location", pointer=place_pointer,
                              locator_kind=locator_kind, script_index=script_index, confidence=confidence)
            if candidate:
                facts.append(candidate)
            continue
        if not isinstance(place, dict):
            continue
        address = place.get("address") if isinstance(place.get("address"), dict) else place
        fields = (
            ("city", ("addressLocality", "city")),
            ("region", ("addressRegion", "region")),
            ("country", ("addressCountry", "country")),
        )
        for fact_type, keys in fields:
            key, raw = _first(address, *keys)
            if raw is not None:
                raw = _name(raw)
                candidate = _fact(f"{fact_prefix}{fact_type}", raw, source_field=key or fact_type,
                                  pointer=_pointer(place_pointer, "address", key) if place.get("address") is address else _pointer(place_pointer, key),
                                  locator_kind=locator_kind, script_index=script_index, confidence=confidence)
                if candidate:
                    facts.append(candidate)
        label = place.get("name")
        if label:
            candidate = _fact(f"{fact_prefix}location_text", label, source_field="name", pointer=_pointer(place_pointer, "name"),
                              locator_kind=locator_kind, script_index=script_index, confidence=confidence)
            if candidate:
                facts.append(candidate)


def _extract_salary(
    facts: list[FactCandidate], value: Any, *, pointer: str, locator_kind: str,
    script_index: int | None, confidence: float, fallback_currency: Any = None,
) -> None:
    if value in (None, ""):
        return
    if not isinstance(value, dict):
        amount = _number(value)
        if amount is not None:
            candidate = _fact("salary_exact", value, source_field="salary", pointer=pointer,
                              locator_kind=locator_kind, script_index=script_index, confidence=confidence,
                              currency=_text(fallback_currency, limit=12), value_override=amount)
            if candidate:
                facts.append(candidate)
        return
    currency = _text(value.get("currency") or value.get("salaryCurrency") or fallback_currency, limit=12)
    currency = currency.upper() if currency else None
    unit_text = value.get("unitText") or value.get("period")
    nested = value.get("value", value)
    nested_pointer = _pointer(pointer, "value") if value.get("value") is nested else pointer
    if isinstance(nested, dict):
        unit_text = nested.get("unitText") or nested.get("period") or unit_text
        for fact_type, keys in (
            ("salary_min", ("minValue", "min", "minimum")),
            ("salary_max", ("maxValue", "max", "maximum")),
            ("salary_exact", ("value", "amount")),
        ):
            key, raw = _first(nested, *keys)
            amount = _number(raw)
            if key and amount is not None:
                candidate = _fact(fact_type, raw, source_field=key, pointer=_pointer(nested_pointer, key),
                                  locator_kind=locator_kind, script_index=script_index, confidence=confidence,
                                  unit=_text(unit_text, limit=80), currency=currency, period=_period(unit_text),
                                  value_override=amount)
                if candidate:
                    facts.append(candidate)
    else:
        amount = _number(nested)
        if amount is not None:
            candidate = _fact("salary_exact", nested, source_field="value", pointer=nested_pointer,
                              locator_kind=locator_kind, script_index=script_index, confidence=confidence,
                              unit=_text(unit_text, limit=80), currency=currency, period=_period(unit_text),
                              value_override=amount)
            if candidate:
                facts.append(candidate)
    if currency:
        candidate = _fact("salary_currency", currency, source_field="currency",
                          pointer=_pointer(pointer, "currency"), locator_kind=locator_kind,
                          script_index=script_index, confidence=confidence, value_override=currency)
        if candidate:
            facts.append(candidate)
    if unit_text:
        normalized = _period(unit_text)
        candidate = _fact("salary_period", unit_text, source_field="unitText",
                          pointer=_pointer(nested_pointer, "unitText"), locator_kind=locator_kind,
                          script_index=script_index, confidence=confidence,
                          value_override=normalized or str(unit_text))
        if candidate:
            facts.append(candidate)
    tax_key, tax_type = _first(value, "taxType", "grossNet")
    if tax_type:
        candidate = _fact("salary_tax_type", tax_type, source_field=tax_key or "taxType",
                          pointer=_pointer(pointer, tax_key or "taxType"), locator_kind=locator_kind,
                          script_index=script_index, confidence=confidence)
        if candidate:
            facts.append(candidate)


def _extract_job_object(
    obj: dict[str, Any], *, base_pointer: str, locator_kind: str,
    script_index: int | None = None, confidence: float = 0.99,
    preserve_unknown: bool = True,
) -> tuple[list[FactCandidate], list[str]]:
    facts: list[FactCandidate] = []
    warnings: list[str] = []
    recognized: set[str] = set()

    def scalar(fact_type: str, keys: tuple[str, ...], *, transform=None, confidence_override=None):
        key, raw = _first(obj, *keys)
        if key is None:
            return
        recognized.add(key)
        value = _name(raw)
        if transform:
            value = transform(value)
        candidate = _fact(fact_type, raw, source_field=key, pointer=_pointer(base_pointer, key),
                          locator_kind=locator_kind, script_index=script_index,
                          confidence=confidence_override or confidence, value_override=value)
        if candidate:
            facts.append(candidate)

    scalar("title", ("title", "jobTitle", "jobtitle", "role", "positionTitle"))
    company_key, company_value = _first(obj, "hiringOrganization", "company", "organization", "employer")
    if company_key:
        recognized.add(company_key)
        value = _name(company_value)
        candidate = _fact("company", company_value, source_field=company_key,
                          pointer=_pointer(base_pointer, company_key, "name") if isinstance(company_value, dict) else _pointer(base_pointer, company_key),
                          locator_kind=locator_kind, script_index=script_index, confidence=confidence,
                          value_override=value)
        if candidate:
            facts.append(candidate)
    scalar("industry", ("industry", "domain"))
    scalar("description", ("description",), confidence_override=min(confidence, 0.98))

    location_key, location = _first(obj, "jobLocation", "workLocations", "location", "locations")
    if location_key:
        recognized.add(location_key)
        _extract_location(facts, location, pointer=_pointer(base_pointer, location_key),
                          locator_kind=locator_kind, script_index=script_index, confidence=confidence)
    applicant_key, applicant_location = _first(obj, "applicantLocationRequirements")
    if applicant_key:
        recognized.add(applicant_key)
        _extract_location(facts, applicant_location, pointer=_pointer(base_pointer, applicant_key),
                          locator_kind=locator_kind, script_index=script_index, confidence=confidence,
                          fact_prefix="applicant_")
    for direct_key, fact_type in (("city", "city"), ("country", "country"), ("region", "region")):
        if direct_key in obj and obj[direct_key] not in (None, ""):
            recognized.add(direct_key)
            candidate = _fact(fact_type, obj[direct_key], source_field=direct_key,
                              pointer=_pointer(base_pointer, direct_key), locator_kind=locator_kind,
                              script_index=script_index, confidence=confidence)
            if candidate:
                facts.append(candidate)

    work_key, work_value = _first(obj, "jobLocationType", "workModel", "workMode", "remoteType")
    if work_key:
        recognized.add(work_key)
        token = str(work_value).casefold().replace("_", " ").replace("-", " ")
        normalized = "remote" if any(term in token for term in ("telecommute", "remote")) else (
            "hybrid" if "hybrid" in token else "on-site" if any(term in token for term in ("onsite", "on site")) else str(work_value)
        )
        candidate = _fact("work_model", work_value, source_field=work_key,
                          pointer=_pointer(base_pointer, work_key), locator_kind=locator_kind,
                          script_index=script_index, confidence=confidence, value_override=normalized)
        if candidate:
            facts.append(candidate)

    currency_key, fallback_currency = _first(obj, "salaryCurrency", "currency")
    if currency_key:
        recognized.add(currency_key)
    salary_key, salary = _first(obj, "baseSalary", "salary", "compensation")
    if salary_key:
        recognized.add(salary_key)
        _extract_salary(facts, salary, pointer=_pointer(base_pointer, salary_key),
                        locator_kind=locator_kind, script_index=script_index,
                        confidence=confidence, fallback_currency=fallback_currency)
    elif fallback_currency:
        candidate = _fact("salary_currency", fallback_currency, source_field=currency_key or "currency",
                          pointer=_pointer(base_pointer, currency_key or "currency"), locator_kind=locator_kind,
                          script_index=script_index, confidence=0.85,
                          value_override=str(fallback_currency).upper())
        if candidate:
            facts.append(candidate)
    bonus_key, bonus = _first(obj, "bonus", "variableCompensation")
    if bonus_key:
        recognized.add(bonus_key)
        candidate = _fact("bonus", bonus, source_field=bonus_key,
                          pointer=_pointer(base_pointer, bonus_key), locator_kind=locator_kind,
                          script_index=script_index, confidence=confidence)
        if candidate:
            facts.append(candidate)

    employment_key, employment = _first(
        obj, "employmentType", "engagementtype", "contractType", "contract"
    )
    if employment_key:
        recognized.add(employment_key)
        _emit_list(facts, "contract_type", employment, source_field=employment_key,
                   pointer=_pointer(base_pointer, employment_key), locator_kind=locator_kind,
                   script_index=script_index, confidence=confidence)

    for fact_type, keys in (
        ("employment_fraction", ("employmentFraction", "extent", "workHours")),
        ("schedule", ("workSchedule", "schedule")),
        ("shift_work", ("shiftWork",)),
        ("start_date", ("startDate", "starttime")),
        ("date_posted", ("datePosted", "published")),
        ("valid_through", ("validThrough", "applicationDue", "expires", "expirationDate", "expiresAt")),
    ):
        key, raw = _first(obj, *keys)
        if key is None and fact_type == "shift_work" and "shiftWork" in obj:
            key, raw = "shiftWork", obj["shiftWork"]
        if key is None:
            continue
        recognized.add(key)
        value, message = _date_value(raw) if fact_type.endswith("date") or fact_type in {"date_posted", "valid_through"} else (raw, None)
        candidate = _fact(fact_type, raw, source_field=key, pointer=_pointer(base_pointer, key),
                          locator_kind=locator_kind, script_index=script_index, confidence=confidence,
                          value_override=value)
        if candidate:
            if message:
                candidate = FactCandidate(**{**candidate.__dict__, "validation_state": "warning", "validation_message": message})
            facts.append(candidate)

    list_fields = (
        ("skill", ("skills", "skillRequirements"), "unknown"),
        ("tool", ("tools",), "unknown"),
        ("language", ("languages", "languageRequirements"), "unknown"),
        ("education", ("educationRequirements", "education"), "unknown"),
        ("experience", ("experienceRequirements", "experience"), "unknown"),
        ("certification", ("certifications", "certificationRequirements"), "unknown"),
        ("driving_licence", ("drivingLicence", "driversLicense"), "unknown"),
        ("responsibility", ("responsibilities",), "unknown"),
        ("benefit", ("jobBenefits", "benefits"), "unknown"),
        ("recruitment_process", ("recruitmentProcess",), "unknown"),
        ("requirement_other", ("qualifications",), "unknown"),
    )
    for fact_type, keys, preference in list_fields:
        key, raw = _first(obj, *keys)
        if key:
            recognized.add(key)
            _emit_list(facts, fact_type, raw, source_field=key, pointer=_pointer(base_pointer, key),
                       locator_kind=locator_kind, script_index=script_index,
                       preference=preference, confidence=confidence)

    requirements = obj.get("requirements")
    if isinstance(requirements, dict):
        recognized.add("requirements")
        groups = (("required", "required"), ("mustHave", "required"),
                  ("preferred", "preferred"), ("niceToHave", "preferred"),
                  ("optional", "optional"))
        for key, preference in groups:
            if key in requirements:
                _emit_list(facts, "requirement_other", requirements[key], source_field=f"requirements.{key}",
                           pointer=_pointer(base_pointer, "requirements", key), locator_kind=locator_kind,
                           script_index=script_index, preference=preference, confidence=confidence)
        for key, fact_type in (("skills", "skill"), ("tools", "tool"), ("languages", "language"),
                               ("education", "education"), ("experience", "experience")):
            if key in requirements:
                _emit_list(facts, fact_type, requirements[key], source_field=f"requirements.{key}",
                           pointer=_pointer(base_pointer, "requirements", key), locator_kind=locator_kind,
                           script_index=script_index, preference="unknown", confidence=confidence)

    ignored = {"@context", "@type", "id", "externalId", "url", "identifier", "sameAs", "image", "logo"}
    if preserve_unknown:
        for key, raw in list(obj.items())[:100]:
            if key in recognized or key in ignored or not re.fullmatch(r"[A-Za-z0-9_.:@-]{1,100}", str(key)):
                continue
            if isinstance(raw, (str, int, float, bool)) or (
                isinstance(raw, list) and len(raw) <= 20 and all(isinstance(item, (str, int, float, bool)) for item in raw)
            ):
                candidate = _fact("other", raw, source_field=str(key), label=str(key).replace("_", " ")[:200],
                                  pointer=_pointer(base_pointer, key), locator_kind=locator_kind,
                                  script_index=script_index, confidence=0.97, namespace="source")
                if candidate:
                    facts.append(candidate)

    if len(facts) > MAX_FACTS_PER_RUN:
        warnings.append(f"Fact output was bounded to {MAX_FACTS_PER_RUN} records.")
        facts = facts[:MAX_FACTS_PER_RUN]
    return facts, warnings


def _is_jobposting(value: Any) -> bool:
    kinds = value.get("@type") if isinstance(value, dict) else None
    return "JobPosting" in _items(kinds)


def _jobposting_nodes(value: Any, pointer: str = "", depth: int = 0) -> Iterable[tuple[dict[str, Any], str]]:
    if depth > MAX_JSON_DEPTH:
        return
    if isinstance(value, dict):
        if _is_jobposting(value):
            yield value, pointer or "/"
        for key, child in list(value.items())[:200]:
            if isinstance(child, (dict, list)):
                yield from _jobposting_nodes(child, _pointer(pointer, key), depth + 1)
    elif isinstance(value, list):
        for index, child in enumerate(value[:MAX_LIST_ITEMS]):
            if isinstance(child, (dict, list)):
                yield from _jobposting_nodes(child, _pointer(pointer, index), depth + 1)


class _MetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: list[dict[str, str]] = []
        self.scripts: list[str] = []
        self.script_types: list[str] = []
        self.title_parts: list[str] = []
        self._in_json_ld = False
        self._in_title = False
        self._buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {str(key).casefold(): str(value or "") for key, value in attrs}
        if tag.casefold() == "meta":
            self.meta.append(values)
        elif tag.casefold() == "script" and values.get("type", "").split(";", 1)[0].strip().casefold() == "application/ld+json":
            self._in_json_ld = True
            self._buffer = []
            self.script_types.append(values.get("type", ""))
        elif tag.casefold() == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "script" and self._in_json_ld:
            self.scripts.append("".join(self._buffer))
            self._in_json_ld = False
            self._buffer = []
        elif tag.casefold() == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_json_ld:
            self._buffer.append(data)
        elif self._in_title:
            self.title_parts.append(data)


def _manual_hints(listing: dict[str, Any]) -> ExtractionBatch:
    facts: list[FactCandidate] = []
    for column, fact_type in (("title_hint", "title"), ("company_hint", "company"), ("location_hint", "location_text")):
        raw = listing.get(column)
        if raw:
            candidate = _fact(fact_type, raw, source_field=column, pointer=f"source_listings.{column}",
                              locator_kind="submitted_field", confidence=0.96)
            if candidate:
                facts.append(candidate)
    return ExtractionBatch("manual_hints", EXTRACTOR_VERSIONS["manual_hints"], tuple(facts))


def _json_batches(content: str) -> list[ExtractionBatch]:
    data = json.loads(content)
    if isinstance(data, dict):
        nav_key = next(
            (key for key in ("json", "ad_content", "adContent") if isinstance(data.get(key), dict)),
            None,
        )
        if nav_key is not None and (data.get("uuid") or data[nav_key].get("uuid")):
            nav_content = data[nav_key]
            facts, warnings = _extract_job_object(
                nav_content,
                base_pointer=_pointer("", nav_key),
                locator_kind="json_pointer",
                confidence=0.995,
            )
            emitted_open: set[tuple[str, str]] = set()
            for owner, prefix in ((data, ""), (nav_content, _pointer("", nav_key))):
                for key, label in (
                    ("uuid", "NAV vacancy UUID"),
                    ("status", "NAV listing status"),
                    ("applicationDue", "Application due"),
                    ("sourceurl", "Source URL"),
                    ("applicationUrl", "Application URL"),
                    ("positioncount", "Position count"),
                    ("sector", "Sector"),
                    ("occupationCategories", "Occupation categories"),
                    ("categoryList", "Categories"),
                ):
                    if owner.get(key) in (None, "", [], {}):
                        continue
                    signature = (key, _compact(owner[key]))
                    if signature in emitted_open:
                        continue
                    emitted_open.add(signature)
                    candidate = _fact(
                        "other",
                        owner[key],
                        source_field=key,
                        label=label,
                        pointer=_pointer(prefix, key),
                        locator_kind="json_pointer",
                        confidence=0.995,
                        namespace="source",
                    )
                    if candidate:
                        facts.append(candidate)
            return [ExtractionBatch(
                "json_structured",
                EXTRACTOR_VERSIONS["nav_structured"],
                tuple(facts[:MAX_FACTS_PER_RUN]),
                tuple(warnings),
            )]
    nodes = list(_jobposting_nodes(data))
    if nodes:
        facts: list[FactCandidate] = []
        warnings: list[str] = []
        for node, pointer in nodes[:MAX_JSON_LD_BLOCKS]:
            node_facts, node_warnings = _extract_job_object(
                node, base_pointer=pointer, locator_kind="json_pointer", confidence=0.995,
            )
            facts.extend(node_facts)
            warnings.extend(node_warnings)
        if len(nodes) > MAX_JSON_LD_BLOCKS:
            warnings.append(f"JobPosting objects were bounded to {MAX_JSON_LD_BLOCKS}.")
        return [ExtractionBatch("json_ld_jobposting", EXTRACTOR_VERSIONS["json_ld_jobposting"], tuple(facts[:MAX_FACTS_PER_RUN]), tuple(warnings))]
    candidates = data if isinstance(data, list) else [data]
    facts = []
    warnings = []
    for index, obj in enumerate(candidates[:MAX_LIST_ITEMS]):
        if not isinstance(obj, dict):
            continue
        child, child_warnings = _extract_job_object(
            obj, base_pointer=f"/{index}" if isinstance(data, list) else "", locator_kind="json_pointer",
            confidence=0.99,
        )
        facts.extend(child)
        warnings.extend(child_warnings)
    return [ExtractionBatch("json_structured", EXTRACTOR_VERSIONS["json_structured"], tuple(facts[:MAX_FACTS_PER_RUN]), tuple(warnings))]


def _html_batches(content: str) -> list[ExtractionBatch]:
    parser = _MetadataParser()
    parser.feed(content)
    batches: list[ExtractionBatch] = []
    json_facts: list[FactCandidate] = []
    json_warnings: list[str] = []
    for index, script in enumerate(parser.scripts[:MAX_JSON_LD_BLOCKS]):
        if len(script.encode("utf-8")) > MAX_JSON_LD_BYTES:
            json_warnings.append(f"JSON-LD script {index} exceeded the parser limit.")
            continue
        try:
            data = json.loads(script)
        except json.JSONDecodeError:
            json_warnings.append(f"JSON-LD script {index} is malformed and was ignored.")
            continue
        for node, pointer in _jobposting_nodes(data):
            facts, warnings = _extract_job_object(
                node, base_pointer=pointer, locator_kind="json_ld_pointer",
                script_index=index, confidence=0.995,
            )
            json_facts.extend(facts)
            json_warnings.extend(warnings)
    if parser.scripts:
        if len(parser.scripts) > MAX_JSON_LD_BLOCKS:
            json_warnings.append(f"JSON-LD blocks were bounded to {MAX_JSON_LD_BLOCKS}.")
        batches.append(ExtractionBatch(
            "json_ld_jobposting", EXTRACTOR_VERSIONS["json_ld_jobposting"],
            tuple(json_facts[:MAX_FACTS_PER_RUN]), tuple(json_warnings),
        ))

    meta_facts: list[FactCandidate] = []
    meta_map = {
        "og:title": ("title", 0.88), "twitter:title": ("title", 0.86),
        "job:title": ("title", 0.95), "job:company": ("company", 0.95),
        "job:location": ("location_text", 0.92), "job:employment_type": ("contract_type", 0.92),
        "title": ("title", 0.92), "hiringorganization": ("company", 0.90),
        "joblocation": ("location_text", 0.90),
    }
    for index, attrs in enumerate(parser.meta[:200]):
        key = (attrs.get("property") or attrs.get("name") or attrs.get("itemprop") or "").casefold()
        raw = attrs.get("content")
        mapped = meta_map.get(key)
        if mapped and raw:
            candidate = _fact(mapped[0], raw, source_field=key, pointer=f"meta[{index}]@content",
                              locator_kind="html_selector", confidence=mapped[1])
            if candidate:
                meta_facts.append(candidate)
    title = "".join(parser.title_parts).strip()
    if title and not any(fact.fact_type == "title" for fact in meta_facts):
        candidate = _fact("title", title, source_field="title", pointer="head > title",
                          locator_kind="html_selector", confidence=0.75)
        if candidate:
            meta_facts.append(candidate)
    batches.append(ExtractionBatch(
        "html_metadata", EXTRACTOR_VERSIONS["html_metadata"], tuple(meta_facts[:MAX_FACTS_PER_RUN]),
    ))
    return batches


def extract_batches(
    content: str,
    *,
    mime_type: str,
    listing: dict[str, Any],
) -> list[ExtractionBatch]:
    """Return deterministic batches in precedence order for one verified capture."""
    batches = [_manual_hints(listing)]
    if mime_type == "application/json":
        batches.extend(_json_batches(content))
    elif mime_type == "text/html":
        batches.extend(_html_batches(content))
    return batches
