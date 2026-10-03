"""Deterministic, explainable duplicate-candidate policy for Job Hunt Pack H."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
import re
from typing import Any
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


DEDUPE_RULE_VERSION = "dedupe@1"
DEDUPE_NORMALIZATION_VERSION = "dedupe-normalization@1"
PUBLICATION_WINDOW_DAYS = 60
MAX_COMPANY_BLOCK_CANDIDATES = 150
MAX_URL_BLOCK_CANDIDATES = 50
MAX_DESCRIPTION_CHARS = 20_000
MAX_DESCRIPTION_TOKENS = 2_000

_UNKNOWN = {"", "unknown", "n/a", "none", "null", "-"}
_COMPANY_SUFFIXES = (
    ("sp", "z", "o", "o"),
    ("a", "s"),
    ("as",),
    ("ltd",),
    ("limited",),
    ("inc",),
)
_TRACKING_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid"}
_TOKEN_RE = re.compile(r"[\w+#.]+", re.UNICODE)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = re.sub(r"[^\w+#.]+", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def known(value: Any) -> bool:
    return normalize_text(value) not in _UNKNOWN


def normalize_company(value: Any) -> str:
    tokens = normalize_text(value).replace(".", " ").split()
    while tokens:
        removed = False
        for suffix in _COMPANY_SUFFIXES:
            if len(tokens) > len(suffix) and tuple(tokens[-len(suffix):]) == suffix:
                del tokens[-len(suffix):]
                removed = True
                break
        if not removed:
            break
    return " ".join(tokens)


def normalize_title(value: Any) -> str:
    return normalize_text(value)


def normalize_location(value: Any) -> str:
    return normalize_text(value)


def normalize_url(value: Any) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return None
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
        return None
    scheme = parsed.scheme.casefold()
    host = parsed.hostname.casefold()
    port = parsed.port
    netloc = host
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = f"{host}:{port}"
    params = []
    for key, item in parse_qsl(parsed.query, keep_blank_values=True):
        lowered = key.casefold()
        if lowered.startswith("utm_") or lowered in _TRACKING_PARAMS:
            continue
        params.append((key, item))
    query = urlencode(sorted(params), doseq=True)
    path = parsed.path or "/"
    return urlunsplit((scheme, netloc, path, query, ""))


def lexical_tokens(value: Any, *, maximum: int = MAX_DESCRIPTION_TOKENS) -> tuple[str, ...]:
    text = unicodedata.normalize("NFKC", str(value or ""))[:MAX_DESCRIPTION_CHARS].casefold()
    tokens = [token for token in _TOKEN_RE.findall(text) if len(token) > 1]
    return tuple(tokens[:maximum])


def token_similarity(left: Any, right: Any) -> float | None:
    left_tokens = set(lexical_tokens(left))
    right_tokens = set(lexical_tokens(right))
    if not left_tokens or not right_tokens:
        return None
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _date(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            return datetime.fromisoformat(raw[:10])
        except ValueError:
            return None


def delta_days(left: Any, right: Any) -> int | None:
    left_date, right_date = _date(left), _date(right)
    if not left_date or not right_date:
        return None
    if left_date.tzinfo is None:
        left_date = left_date.replace(tzinfo=right_date.tzinfo)
    if right_date.tzinfo is None:
        right_date = right_date.replace(tzinfo=left_date.tzinfo)
    return abs((left_date - right_date).days)


def salary_compatible(left: dict[str, Any], right: dict[str, Any]) -> bool | None:
    left_min, left_max = left.get("salary_min"), left.get("salary_max")
    right_min, right_max = right.get("salary_min"), right.get("salary_max")
    if all(value is None for value in (left_min, left_max)) or all(
        value is None for value in (right_min, right_max)
    ):
        return None
    left_currency = normalize_text(left.get("salary_currency"))
    right_currency = normalize_text(right.get("salary_currency"))
    if left_currency and right_currency and left_currency != right_currency:
        return False
    l_min = float(left_min if left_min is not None else left_max)
    l_max = float(left_max if left_max is not None else left_min)
    r_min = float(right_min if right_min is not None else right_max)
    r_max = float(right_max if right_max is not None else right_min)
    return max(l_min, r_min) <= min(l_max, r_max)


def build_job_key(context: dict[str, Any]) -> dict[str, Any]:
    job = context["job"]
    publication_at = context.get("publication_at") or job.get("source_captured_at") or job.get("created_at")
    values = {
        "company_key": normalize_company(job.get("company")),
        "title_key": normalize_title(job.get("role_title")),
        "title_tokens": sorted(set(lexical_tokens(job.get("role_title"), maximum=40))),
        "city_key": normalize_location(job.get("location_city")),
        "country_key": normalize_location(job.get("location_country")),
        "publication_at": publication_at,
        "expiration_at": context.get("expiration_at") or job.get("expires_at"),
        "urls": sorted({
            normalized
            for item in context.get("urls", [])
            if (normalized := normalize_url(item.get("url")))
        }),
        "source_identities": sorted(
            (str(item.get("source_key") or ""), str(item.get("external_id") or ""))
            for item in context.get("listings", []) if item.get("external_id")
        ),
    }
    values["identity_fingerprint"] = fingerprint(values)
    return values


def compare_jobs(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any] | None:
    left_job, right_job = left["job"], right["job"]
    left_key, right_key = left["dedupe_key"], right["dedupe_key"]
    shared_urls = sorted(set(left_key["urls"]) & set(right_key["urls"]))
    shared_url_kinds = sorted({
        item.get("kind")
        for item in left.get("urls", []) + right.get("urls", [])
        if normalize_url(item.get("url")) in shared_urls
    })
    same_company = None
    if left_key["company_key"] and right_key["company_key"]:
        same_company = left_key["company_key"] == right_key["company_key"]
    title_similarity = token_similarity(left_job.get("role_title"), right_job.get("role_title"))
    same_city = None
    if left_key["city_key"] and right_key["city_key"]:
        same_city = left_key["city_key"] == right_key["city_key"]
    same_country = None
    if left_key["country_key"] and right_key["country_key"]:
        same_country = left_key["country_key"] == right_key["country_key"]
    publication_delta = delta_days(left_key.get("publication_at"), right_key.get("publication_at"))
    expiration_delta = delta_days(left_key.get("expiration_at"), right_key.get("expiration_at"))
    description_similarity = token_similarity(left.get("description"), right.get("description"))
    salary_match = salary_compatible(left_job, right_job)

    contradictions: list[str] = []
    if same_company is False:
        contradictions.append("different_employers")
    if same_country is False and normalize_text(left_job.get("work_mode")) != "remote" \
            and normalize_text(right_job.get("work_mode")) != "remote":
        contradictions.append("incompatible_countries")
    authoritative_left = {
        (source, external) for source, external in left_key["source_identities"]
        if source not in {"", "manual"}
    }
    authoritative_right = {
        (source, external) for source, external in right_key["source_identities"]
        if source not in {"", "manual"}
    }
    if any(source_a == source_b and external_a != external_b
           for source_a, external_a in authoritative_left
           for source_b, external_b in authoritative_right):
        contradictions.append("different_authoritative_source_ids")
    if publication_delta is not None and publication_delta > PUBLICATION_WINDOW_DAYS:
        contradictions.append("publication_window_mismatch")
    if same_company is True and title_similarity is not None and title_similarity < 0.25:
        contradictions.append("materially_different_titles")

    exact = bool(shared_urls)
    strong_fingerprint = (
        same_company is True
        and title_similarity is not None and title_similarity >= 0.75
        and same_country is not False and same_city is not False
        and (publication_delta is None or publication_delta <= PUBLICATION_WINDOW_DAYS)
    )
    description_support = description_similarity is not None and description_similarity >= 0.65
    if not exact and not strong_fingerprint and not (
        same_company is True and title_similarity is not None and title_similarity >= 0.55
        and description_support
    ):
        return None

    if exact:
        confidence_class = "exact"
    elif strong_fingerprint and description_support:
        confidence_class = "strong"
    elif strong_fingerprint:
        confidence_class = "review"
    else:
        confidence_class = "weak"
    reasons = []
    if exact:
        reasons.append("shared_normalized_url")
    if strong_fingerprint:
        reasons.append("company_title_location_time")
    if description_support:
        reasons.append("description_lexical_support")
    if salary_match is True:
        reasons.append("salary_compatible")

    components = {
        "sameCompany": same_company,
        "titleSimilarity": None if title_similarity is None else round(title_similarity, 4),
        "exactTitle": bool(left_key["title_key"] and left_key["title_key"] == right_key["title_key"]),
        "sameCity": same_city,
        "sameCountry": same_country,
        "publicationDeltaDays": publication_delta,
        "expirationDeltaDays": expiration_delta,
        "salaryCompatible": salary_match,
        "descriptionSimilarity": None if description_similarity is None else round(description_similarity, 4),
        "exactSharedUrl": exact,
        "sharedUrls": shared_urls[:10],
        "sharedUrlKinds": shared_url_kinds,
        "hardContradictions": contradictions,
        "normalizationVersion": DEDUPE_NORMALIZATION_VERSION,
        "bounds": {
            "publicationWindowDays": PUBLICATION_WINDOW_DAYS,
            "descriptionChars": MAX_DESCRIPTION_CHARS,
            "descriptionTokens": MAX_DESCRIPTION_TOKENS,
        },
    }
    evidence_fingerprint = fingerprint({
        "ruleVersion": DEDUPE_RULE_VERSION,
        "identityPair": sorted((
            left_key["identity_fingerprint"], right_key["identity_fingerprint"],
        )),
        "reasons": reasons,
        "components": components,
    })
    return {
        "rule_version": DEDUPE_RULE_VERSION,
        "evidence_fingerprint": evidence_fingerprint,
        "left_identity_fingerprint": left_key["identity_fingerprint"],
        "right_identity_fingerprint": right_key["identity_fingerprint"],
        "confidence_class": confidence_class,
        "reason_codes": reasons,
        "evidence": components,
        "hard_contradictions": contradictions,
        "auto_merge_eligible": exact and not contradictions,
    }


__all__ = [
    "DEDUPE_NORMALIZATION_VERSION",
    "DEDUPE_RULE_VERSION",
    "MAX_COMPANY_BLOCK_CANDIDATES",
    "MAX_URL_BLOCK_CANDIDATES",
    "PUBLICATION_WINDOW_DAYS",
    "build_job_key",
    "canonical_json",
    "compare_jobs",
    "fingerprint",
    "normalize_company",
    "normalize_location",
    "normalize_text",
    "normalize_title",
    "normalize_url",
    "token_similarity",
]
