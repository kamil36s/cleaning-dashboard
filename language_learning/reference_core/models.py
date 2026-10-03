"""Source-neutral identities and resolver contracts for reference data."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import unicodedata
from urllib.parse import quote


UNIT_TYPES = frozenset({"LEMMA", "PHRASE", "IDIOM", "COLLOCATION", "FORMULA"})


def normalize_reference_lookup(value: str) -> str:
    """NFC + casefold only; display spelling, diacritics and boundaries stay stored."""

    return unicodedata.normalize("NFC", str(value or "").strip()).casefold()


def make_stable_key(
    *,
    language_code: str,
    unit_type: str,
    normalized_form: str,
    part_of_speech: str | None = None,
    identity_qualifier: str | None = None,
) -> str:
    language = normalize_reference_lookup(language_code)
    kind = str(unit_type or "").strip().upper()
    normalized = normalize_reference_lookup(normalized_form)
    pos = str(part_of_speech or "").strip().upper()
    qualifier = normalize_reference_lookup(identity_qualifier or "")
    if not language or not normalized or kind not in UNIT_TYPES:
        raise ValueError("language, supported unit type and normalized form are required")
    components = ("reference-key/v1", language, kind, normalized, pos, qualifier)
    return "|".join(quote(item, safe="-._~") for item in components)


def deterministic_id(namespace: str, *parts: str) -> str:
    payload = "\x1f".join((namespace, *map(str, parts))).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:32]


@dataclass(frozen=True)
class ReferenceSourceRecord:
    source_id: str
    canonical_name: str
    provider: str
    resource_type: str
    language_code: str
    version: str
    landing_url: str
    license_id: str | None
    license_url: str | None
    attribution_text: str | None = None


@dataclass(frozen=True)
class ReferenceLexicalUnit:
    id: str
    stable_key: str
    language_code: str
    unit_type: str
    canonical_form: str
    normalized_form: str
    part_of_speech: str | None
    subtype: str | None
    identity_qualifier: str | None


@dataclass(frozen=True)
class VocabularyLemmaIdentity:
    language_code: str
    normalized_lemma: str
    part_of_speech: str | None
    lemma_id: str | None = None


class ResolverStatus(str, Enum):
    MATCHED = "MATCHED"
    AMBIGUOUS = "AMBIGUOUS"
    UNMATCHED = "UNMATCHED"


@dataclass(frozen=True)
class ResolverCandidate:
    lexical_unit: ReferenceLexicalUnit
    match_basis: str


@dataclass(frozen=True)
class ResolverResult:
    status: ResolverStatus
    candidates: tuple[ResolverCandidate, ...]
    rule_version: str = "reference-resolver/v1"


__all__ = [
    "UNIT_TYPES",
    "ReferenceLexicalUnit",
    "ReferenceSourceRecord",
    "ResolverCandidate",
    "ResolverResult",
    "ResolverStatus",
    "VocabularyLemmaIdentity",
    "deterministic_id",
    "make_stable_key",
    "normalize_reference_lookup",
]
