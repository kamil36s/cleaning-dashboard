"""Strict local contract and evidence validation for untrusted AI output."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any

from ..deterministic import FactCandidate, MAX_VALUE_TEXT


MAX_AI_FACTS = 200
MAX_AI_WARNINGS = 50
MAX_EVIDENCE_QUOTE = 1200
MAX_AI_SOURCE_WORDING = 2000
MAX_RAW_AI_RESPONSE_BYTES = 256 * 1024

FACT_TYPES = frozenset({
    "title", "company", "industry", "description", "city", "region", "country",
    "location_text", "applicant_city", "applicant_region", "applicant_country",
    "applicant_location_text", "work_model", "salary_min", "salary_max",
    "salary_exact", "salary_currency", "salary_period", "salary_tax_type", "bonus",
    "contract_type", "employment_fraction", "schedule", "shift_work", "start_date",
    "date_posted", "valid_through", "skill", "tool", "language", "education",
    "experience", "certification", "driving_licence", "responsibility", "benefit",
    "recruitment_process", "requirement_other",
})

_TOP_KEYS = frozenset({"facts", "openFacts", "warnings"})
_FACT_KEYS = frozenset({
    "namespace", "type", "label", "state", "requirementPreference", "valueType",
    "valueText", "valueNumber", "valueBoolean", "valueJson", "unit", "currency",
    "period", "sourceWording", "evidenceQuote", "evidenceStart", "evidenceEnd",
    "confidence", "notes",
})
_VALUE_KEYS = {
    "text": "valueText", "number": "valueNumber",
    "boolean": "valueBoolean", "json": "valueJson",
}


AI_RESPONSE_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "facts": {"type": "array", "maxItems": MAX_AI_FACTS, "items": {"$ref": "#/$defs/fact"}},
        "openFacts": {"type": "array", "maxItems": MAX_AI_FACTS, "items": {"$ref": "#/$defs/openFact"}},
        "warnings": {"type": "array", "maxItems": MAX_AI_WARNINGS, "items": {"type": "string", "maxLength": 1000}},
    },
    "required": ["facts", "openFacts", "warnings"],
    "$defs": {
        "fact": {
            "type": "object", "additionalProperties": False,
            "properties": {
                "namespace": {"type": "string"}, "type": {"type": "string"},
                "label": {"type": "string"},
                "state": {"type": "string", "enum": ["explicit_positive", "explicit_negative"]},
                "requirementPreference": {"type": "string", "enum": ["required", "preferred", "optional", "unknown"]},
                "valueType": {"type": "string", "enum": ["text", "number", "boolean", "json"]},
                "valueText": {"type": "string"}, "valueNumber": {"type": "number"},
                "valueBoolean": {"type": "boolean"}, "valueJson": {},
                "unit": {"type": "string"}, "currency": {"type": "string"}, "period": {"type": "string"},
                "sourceWording": {"type": "string"}, "evidenceQuote": {"type": "string"},
                "evidenceStart": {"type": "integer", "minimum": 0}, "evidenceEnd": {"type": "integer", "minimum": 0},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1}, "notes": {"type": "string"},
            },
            "required": ["namespace", "type", "state", "requirementPreference", "valueType", "sourceWording", "evidenceQuote", "confidence"],
        },
        "openFact": {
            "type": "object", "additionalProperties": False,
            "properties": {
                "namespace": {"type": "string"}, "type": {"type": "string"}, "label": {"type": "string"},
                "state": {"type": "string", "enum": ["explicit_positive", "explicit_negative"]},
                "requirementPreference": {"type": "string", "enum": ["required", "preferred", "optional", "unknown"]},
                "valueType": {"type": "string", "enum": ["text", "number", "boolean", "json"]},
                "valueText": {"type": "string"}, "valueNumber": {"type": "number"},
                "valueBoolean": {"type": "boolean"}, "valueJson": {},
                "unit": {"type": "string"}, "currency": {"type": "string"}, "period": {"type": "string"},
                "sourceWording": {"type": "string"}, "evidenceQuote": {"type": "string"},
                "evidenceStart": {"type": "integer", "minimum": 0}, "evidenceEnd": {"type": "integer", "minimum": 0},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1}, "notes": {"type": "string"},
            },
            "required": ["namespace", "type", "label", "state", "requirementPreference", "valueType", "sourceWording", "evidenceQuote", "confidence"],
        },
    },
}


@dataclass(frozen=True)
class RejectedFact:
    reason: str
    message: str
    candidate: dict[str, Any]


@dataclass(frozen=True)
class ValidatedAIOutput:
    facts: tuple[FactCandidate, ...]
    warnings: tuple[str, ...]
    rejected: tuple[RejectedFact, ...]


class AISchemaError(ValueError):
    pass


def _bounded_text(value: Any, name: str, limit: int, *, required: bool = False) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{name} must be text")
    if required and not value:
        raise ValueError(f"{name} is required")
    if len(value) > limit:
        raise ValueError(f"{name} exceeds {limit} characters")
    return value or None


def _value_supported(value_type: str, value: Any, wording: str, quote: str, state: str) -> bool:
    support = f"{wording}\n{quote}".casefold()
    if value_type == "text":
        token = " ".join(str(value).casefold().split())
        source = " ".join(support.split())
        return bool(token) and token in source
    if value_type == "number":
        expected = format(float(value), "g")
        expected_digits = re.sub(r"\D", "", expected)
        source_digits = re.sub(r"\D", "", support)
        return bool(expected_digits) and expected_digits in source_digits
    if value_type == "boolean" and value is False:
        if state != "explicit_negative":
            return False
        return any(marker in support for marker in (" not ", "no ", "without", "ikke", "ingen", "nie ", "bez "))
    return True


def _candidate(item: dict[str, Any], *, source_text: str, open_fact: bool) -> FactCandidate:
    unknown = sorted(set(item) - _FACT_KEYS)
    if unknown:
        raise ValueError("unsupported keys: " + ", ".join(unknown))
    namespace = _bounded_text(item.get("namespace"), "namespace", 80, required=True)
    raw_type = _bounded_text(item.get("type"), "type", 100, required=True)
    if not re.fullmatch(r"[a-z][a-z0-9_.-]{0,99}", namespace or ""):
        raise ValueError("namespace is invalid")
    if not re.fullmatch(r"[a-z][a-z0-9_.-]{0,99}", raw_type or ""):
        raise ValueError("type is invalid")
    if not open_fact and raw_type not in FACT_TYPES:
        raise ValueError("typed fact type is unsupported")
    label = _bounded_text(item.get("label"), "label", 200, required=open_fact)
    state = item.get("state")
    if state not in {"explicit_positive", "explicit_negative"}:
        raise ValueError("state is invalid")
    preference = item.get("requirementPreference")
    if preference not in {"required", "preferred", "optional", "unknown"}:
        raise ValueError("requirementPreference is invalid")
    value_type = item.get("valueType")
    value_key = _VALUE_KEYS.get(value_type)
    if not value_key:
        raise ValueError("valueType is invalid")
    present = [key for key in _VALUE_KEYS.values() if key in item]
    if present != [value_key]:
        raise ValueError(f"exactly {value_key} must be supplied")
    value = item[value_key]
    if value_type == "text":
        value = _bounded_text(value, value_key, MAX_VALUE_TEXT, required=True)
        if str(value).strip().casefold() in {"unknown", "not specified", "n/a", "none"}:
            raise ValueError("missing information must not be emitted as a fact")
    elif value_type == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value or value in (float("inf"), float("-inf")):
            raise ValueError("valueNumber must be finite")
        value = float(value)
        if raw_type.startswith("salary_") and value < 0:
            raise ValueError("salary cannot be negative")
    elif value_type == "boolean":
        if not isinstance(value, bool):
            raise ValueError("valueBoolean must be boolean")
    else:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > 16 * 1024:
            raise ValueError("valueJson is too large")
    wording = _bounded_text(item.get("sourceWording"), "sourceWording", MAX_AI_SOURCE_WORDING, required=True) or ""
    quote = _bounded_text(item.get("evidenceQuote"), "evidenceQuote", MAX_EVIDENCE_QUOTE, required=True) or ""
    quote_start = source_text.find(quote)
    if quote_start < 0:
        raise ValueError("evidence quote was not found in the prepared advertisement")
    if source_text.find(wording) < 0:
        raise ValueError("source wording was not found in the prepared advertisement")
    if not _value_supported(value_type, value, wording, quote, state):
        raise ValueError("the claimed value is not supported by its evidence")
    confidence = item.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
        raise ValueError("confidence is invalid")
    currency = _bounded_text(item.get("currency"), "currency", 12)
    if currency and not re.fullmatch(r"[A-Z]{3}", currency):
        raise ValueError("currency must be a three-letter uppercase code")
    evidence = {
        "kind": "ai_text_span", "start": quote_start, "end": quote_start + len(quote),
        "quote": quote, "claimedStart": item.get("evidenceStart"), "claimedEnd": item.get("evidenceEnd"),
    }
    final_confidence = min(float(confidence), 0.95)
    values = {"value_text": None, "value_number": None, "value_boolean": None, "value_json": None}
    values[{"text": "value_text", "number": "value_number", "boolean": "value_boolean", "json": "value_json"}[value_type]] = value
    return FactCandidate(
        namespace=namespace or "job", fact_type="other" if open_fact else (raw_type or "other"),
        source_field=f"ai:{raw_type}", label=(label or raw_type) if open_fact else label,
        source_wording=wording, value_type=value_type, **values,
        unit=_bounded_text(item.get("unit"), "unit", 80), currency=currency,
        period=_bounded_text(item.get("period"), "period", 80),
        requirement_preference=preference, state=state, confidence=final_confidence,
        evidence_locator=evidence, validation_state="valid", validation_message=None,
    )


def validate_ai_output(structured: Any, *, source_text: str) -> ValidatedAIOutput:
    if not isinstance(structured, dict):
        raise AISchemaError("AI response must be an object")
    unknown = sorted(set(structured) - _TOP_KEYS)
    if unknown or set(structured) != _TOP_KEYS:
        raise AISchemaError("AI response must contain only facts, openFacts, and warnings")
    if not all(isinstance(structured[key], list) for key in _TOP_KEYS):
        raise AISchemaError("AI response collections must be arrays")
    if len(structured["facts"]) > MAX_AI_FACTS or len(structured["openFacts"]) > MAX_AI_FACTS:
        raise AISchemaError("AI response contains too many facts")
    if len(structured["warnings"]) > MAX_AI_WARNINGS:
        raise AISchemaError("AI response contains too many warnings")
    warnings: list[str] = []
    for warning in structured["warnings"]:
        if not isinstance(warning, str) or len(warning) > 1000:
            raise AISchemaError("AI warning is invalid")
        warnings.append(warning)
    accepted: list[FactCandidate] = []
    rejected: list[RejectedFact] = []
    for open_fact, collection in ((False, structured["facts"]), (True, structured["openFacts"])):
        for raw in collection:
            if not isinstance(raw, dict):
                rejected.append(RejectedFact("invalid_schema", "fact must be an object", {"value": str(raw)[:500]}))
                continue
            try:
                accepted.append(_candidate(raw, source_text=source_text, open_fact=open_fact))
            except (TypeError, ValueError) as exc:
                reason = "evidence_not_found" if "not found" in str(exc) or "not supported" in str(exc) else "invalid_schema"
                rejected.append(RejectedFact(reason, str(exc), dict(raw)))
    return ValidatedAIOutput(tuple(accepted), tuple(warnings), tuple(rejected))

