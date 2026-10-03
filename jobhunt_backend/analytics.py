"""Bounded, reproducible Pack M analytics over durable Job Hunt records."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
from statistics import median
from typing import Any, Callable, Iterable

from .models import JobhuntError


MARKET_ANALYTICS_VERSION = "market-analytics@1"
SOURCE_ANALYTICS_VERSION = "source-analytics@1"
APPLICATION_ANALYTICS_VERSION = "application-analytics@1"
TRACK_ANALYTICS_VERSION = "track-analytics@1"
TRADEOFF_VERSION = "track-tradeoff@1"
SALARY_POLICY_VERSION = "salary-analytics@1"
WINDOWS = {"30d": 30, "90d": 90, "180d": 180, "365d": 365, "all": None}
MINIMUM_SALARY_SAMPLE = 3
MINIMUM_APPLICATION_RATE_SAMPLE = 5
MAX_CANONICAL_JOBS = 5000
MAX_SOURCE_LISTINGS = 10000
UNKNOWN_VALUES = {"", "unknown", "not specified", "n/a", "none"}


def _loads(value: Any, fallback: Any) -> Any:
    try:
        return json.loads(value) if value not in (None, "") else fallback
    except (TypeError, json.JSONDecodeError):
        return fallback


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _fingerprint(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.combine(date.fromisoformat(str(value)[:10]), datetime.min.time())
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _known(value: Any) -> bool:
    return value is not None and str(value).strip().casefold() not in UNKNOWN_VALUES


def _percent(numerator: int, denominator: int) -> float | None:
    return round(numerator * 100 / denominator, 1) if denominator else None


def _ratio(numerator: int, denominator: int, *, minimum_sample: int | None = None) -> dict[str, Any]:
    return {
        "numerator": int(numerator),
        "denominator": int(denominator),
        "percent": _percent(numerator, denominator),
        "lowSample": bool(minimum_sample and denominator < minimum_sample),
        "minimumSample": minimum_sample,
    }


def _quantile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _chunks(values: list[str], size: int = 300) -> Iterable[list[str]]:
    for index in range(0, len(values), size):
        yield values[index:index + size]


def _fact_value(fact: dict[str, Any]) -> Any:
    kind = fact.get("value_type")
    if kind == "number":
        return fact.get("value_number")
    if kind == "boolean":
        value = fact.get("value_boolean")
        return None if value is None else bool(value)
    if kind == "json":
        return _loads(fact.get("value_json"), None)
    return fact.get("value_text")


class JobhuntAnalyticsReadModel:
    """Live read models. No analytics metric is persisted or treated as canonical truth."""

    def __init__(self, store: Any, *, now_provider: Callable[[], datetime] | None = None) -> None:
        self.store = store
        self.now_provider = now_provider or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def validate_window(value: Any) -> str:
        window = str(value or "90d")
        if window not in WINDOWS:
            raise JobhuntError(
                "window must be 30d, 90d, 180d, 365d, or all",
                code="invalid_analytics_window",
            )
        return window

    def _window(self, value: Any) -> tuple[str, datetime | None, datetime]:
        window = self.validate_window(value)
        now = self.now_provider()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        now = now.astimezone(timezone.utc)
        days = WINDOWS[window]
        return window, now - timedelta(days=days) if days else None, now

    @staticmethod
    def _track_clause(track_id: str | None, parameters: list[Any]) -> str:
        if not track_id:
            return ""
        parameters.extend([track_id, track_id, track_id])
        return """
          AND (
            EXISTS(SELECT 1 FROM track_job_assignments a
                    WHERE a.job_id=j.id AND a.track_id=? AND a.active=1)
            OR EXISTS(SELECT 1 FROM source_listings l
                      JOIN source_listing_tracks x ON x.listing_id=l.id
                     WHERE l.canonical_job_id=j.id AND x.track_id=?)
            OR EXISTS(SELECT 1 FROM source_listings l
                      JOIN source_listing_search_profiles x ON x.listing_id=l.id
                      JOIN track_search_profiles p ON p.id=x.search_profile_id
                     WHERE l.canonical_job_id=j.id AND p.track_id=?)
          )
        """

    def _population(
        self,
        connection: Any,
        *,
        track_id: str | None = None,
        source_key: str | None = None,
        geography: str | None = None,
    ) -> list[dict[str, Any]]:
        if track_id and not connection.execute("SELECT 1 FROM career_tracks WHERE id=?", (track_id,)).fetchone():
            raise JobhuntError("Track not found", status=404, code="track_not_found")
        parameters: list[Any] = []
        clauses = self._track_clause(track_id, parameters)
        if source_key:
            source = connection.execute(
                "SELECT id FROM source_definitions WHERE source_key=? COLLATE NOCASE",
                (str(source_key),),
            ).fetchone()
            if not source:
                raise JobhuntError("Source not found", status=404, code="source_not_found")
            clauses += " AND EXISTS(SELECT 1 FROM source_listings l WHERE l.canonical_job_id=j.id AND l.source_id=?)"
            parameters.append(source["id"])
        rows = connection.execute(
            f"""
            SELECT j.*,a.id AS application_id,a.current_status,a.source_expired,
                   a.date_applied,a.follow_up_date,a.next_action,
                   COALESCE(k.publication_at,
                     (SELECT MIN(l.first_seen_at) FROM source_listings l WHERE l.canonical_job_id=j.id),
                     j.created_at) AS anchor_at,
                   CASE WHEN k.publication_at IS NOT NULL THEN 'publication_fact'
                        WHEN EXISTS(SELECT 1 FROM source_listings l WHERE l.canonical_job_id=j.id)
                        THEN 'first_source_observation' ELSE 'canonical_job_created' END AS anchor_kind
              FROM canonical_jobs j
              JOIN applications a ON a.job_id=j.id
              LEFT JOIN dedupe_job_keys k ON k.job_id=j.id
             WHERE j.deleted_at IS NULL AND j.merged_into_job_id IS NULL {clauses}
             ORDER BY anchor_at DESC,j.id LIMIT ?
            """,
            (*parameters, MAX_CANONICAL_JOBS + 1),
        ).fetchall()
        if len(rows) > MAX_CANONICAL_JOBS:
            raise JobhuntError(
                "Analytics population exceeds the bounded live-query limit; choose a Track or source filter",
                status=422,
                code="analytics_population_too_large",
            )
        result = [dict(row) for row in rows]
        location = str(geography or "").strip().casefold()
        if location:
            result = [
                row for row in result
                if location in " ".join((str(row.get("location_city") or ""), str(row.get("location_country") or ""))).casefold()
            ]
        return result

    @staticmethod
    def _current(rows: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
        today = now.date()
        result = []
        for row in rows:
            expires = _dt(row.get("expires_at"))
            if row.get("archived_at") or bool(row.get("source_expired")):
                continue
            if expires and expires.date() < today:
                continue
            result.append(row)
        return result

    @staticmethod
    def _observed(rows: list[dict[str, Any]], start: datetime | None, end: datetime) -> list[dict[str, Any]]:
        if start is None:
            return rows
        return [row for row in rows if (anchor := _dt(row.get("anchor_at"))) and start <= anchor <= end]

    @staticmethod
    def _source_rows(connection: Any, job_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        result: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for chunk in _chunks(job_ids):
            placeholders = ",".join("?" for _ in chunk)
            for row in connection.execute(
                f"""SELECT l.*,d.source_key,d.display_name
                       FROM source_listings l JOIN source_definitions d ON d.id=l.source_id
                      WHERE l.canonical_job_id IN ({placeholders}) ORDER BY l.first_seen_at,l.id""",
                chunk,
            ):
                result[str(row["canonical_job_id"])].append(dict(row))
        return result

    @staticmethod
    def _facts(connection: Any, job_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, dict[tuple[str, str, str], dict[str, Any]]] = defaultdict(dict)
        for chunk in _chunks(job_ids):
            placeholders = ",".join("?" for _ in chunk)
            rows = connection.execute(
                f"""SELECT l.canonical_job_id AS job_id,d.source_key,f.*,r.extractor_version
                       FROM source_listings l
                       JOIN source_definitions d ON d.id=l.source_id
                       JOIN raw_captures c ON c.id=(
                         SELECT c2.id FROM raw_captures c2 WHERE c2.listing_id=l.id
                          ORDER BY c2.captured_at DESC,c2.rowid DESC LIMIT 1
                       )
                       JOIN extraction_runs r ON r.capture_id=c.id
                       JOIN extracted_facts f ON f.extraction_run_id=r.id
                      WHERE l.canonical_job_id IN ({placeholders})
                        AND r.status IN ('completed','completed_with_warnings')
                        AND f.validation_state='valid'
                      ORDER BY f.created_at DESC,f.id""",
                chunk,
            ).fetchall()
            for row in rows:
                item = dict(row)
                key = (
                    str(item.get("fact_type") or ""),
                    str(item.get("source_wording") or "").strip().casefold(),
                    str(item.get("state") or ""),
                )
                grouped[str(item["job_id"])].setdefault(key, item)
        return {job_id: list(values.values()) for job_id, values in grouped.items()}

    @staticmethod
    def _coverage(known_jobs: set[str], denominator: int, label: str) -> dict[str, Any]:
        return {
            "label": label,
            "known": len(known_jobs),
            "unknown": max(0, denominator - len(known_jobs)),
            "denominator": denominator,
            "knownPercent": _percent(len(known_jobs), denominator),
        }

    @staticmethod
    def _salary_group_key(row: dict[str, Any]) -> tuple[str, str, str] | None:
        if not bool(row.get("salary_is_known")):
            return None
        currency = str(row.get("salary_currency") or "").strip().upper()
        period = str(row.get("salary_period") or "").strip().casefold()
        period = {"monthly": "month", "yearly": "year", "annual": "year", "hourly": "hour"}.get(period, period)
        tax_type = str(row.get("salary_tax_type") or "unknown").strip().casefold()
        if not currency or currency.casefold() in UNKNOWN_VALUES or period in UNKNOWN_VALUES:
            return None
        if row.get("salary_min") is None and row.get("salary_max") is None:
            return None
        return currency, period, tax_type if tax_type not in {""} else "unknown"

    @classmethod
    def _salary(cls, rows: list[dict[str, Any]], denominator: int) -> dict[str, Any]:
        groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            key = cls._salary_group_key(row)
            if key:
                groups[key].append(row)
        values = []
        for (currency, period, tax_type), members in sorted(groups.items()):
            lowers = [float(row["salary_min"]) for row in members if row.get("salary_min") is not None]
            uppers = [float(row["salary_max"]) for row in members if row.get("salary_max") is not None]
            midpoints = [
                (float(row.get("salary_min") if row.get("salary_min") is not None else row["salary_max"]) +
                 float(row.get("salary_max") if row.get("salary_max") is not None else row["salary_min"])) / 2
                for row in members
            ]
            enough = len(members) >= MINIMUM_SALARY_SAMPLE
            quartiles = len(members) >= 5
            values.append({
                "currency": currency,
                "period": period,
                "taxType": tax_type,
                "count": len(members),
                "denominator": denominator,
                "coveragePercent": _percent(len(members), denominator),
                "minimumSample": MINIMUM_SALARY_SAMPLE,
                "status": "sufficient" if enough else "insufficient_salary_evidence",
                "medianLower": median(lowers) if enough and lowers else None,
                "medianUpper": median(uppers) if enough and uppers else None,
                "medianMidpoint": median(midpoints) if enough else None,
                "quartileLower": _quantile(midpoints, .25) if quartiles else None,
                "quartileUpper": _quantile(midpoints, .75) if quartiles else None,
                "minimumObserved": min(midpoints) if members else None,
                "maximumObserved": max(midpoints) if members else None,
                "observations": [{
                    "jobId": row["id"], "lower": row.get("salary_min"), "upper": row.get("salary_max")
                } for row in members[:100]],
                "outlierPolicy": "No observations are removed.",
            })
        known = sum(len(items) for items in groups.values())
        return {
            "policyVersion": SALARY_POLICY_VERSION,
            "comparableBy": ["currency", "period", "taxType"],
            "knownJobs": known,
            "unknownJobs": max(0, denominator - known),
            "denominator": denominator,
            "minimumSample": MINIMUM_SALARY_SAMPLE,
            "groups": values,
        }

    @staticmethod
    def _distribution(rows: list[dict[str, Any]], field: str, *, unknown: str = "Unknown") -> list[dict[str, Any]]:
        counts = Counter(str(row.get(field) or "").strip() if _known(row.get(field)) else unknown for row in rows)
        denominator = len(rows)
        return [
            {"value": value, "count": count, "denominator": denominator, "percent": _percent(count, denominator)}
            for value, count in sorted(counts.items(), key=lambda item: (-item[1], item[0].casefold()))
        ]

    @staticmethod
    def _trend(rows: list[dict[str, Any]], window: str) -> list[dict[str, Any]]:
        buckets: Counter[str] = Counter()
        for row in rows:
            anchor = _dt(row.get("anchor_at"))
            if not anchor:
                continue
            if window in {"30d", "90d"}:
                monday = anchor.date() - timedelta(days=anchor.weekday())
                key = monday.isoformat()
                granularity = "week"
            else:
                key = anchor.strftime("%Y-%m")
                granularity = "month"
            buckets[key] += 1
        return [{"period": key, "count": buckets[key], "granularity": granularity} for key in sorted(buckets)]

    def market(
        self,
        *,
        window: Any = "90d",
        track_id: Any = None,
        source: Any = None,
        geography: Any = None,
    ) -> dict[str, Any]:
        selected_window, start, end = self._window(window)
        safe_track = str(track_id or "").strip() or None
        safe_source = str(source or "").strip() or None
        safe_geography = str(geography or "").strip()[:120] or None
        with self.store.read_connection() as connection:
            rows = self._population(
                connection, track_id=safe_track, source_key=safe_source, geography=safe_geography,
            )
            observed = self._observed(rows, start, end)
            current = self._current(rows, end)
            current_ids = {str(row["id"]) for row in current}
            all_ids = sorted({str(row["id"]) for row in observed + current})
            sources = self._source_rows(connection, all_ids)
            facts = self._facts(connection, all_ids)

        denominator = len(observed)
        fact_types: dict[str, set[str]] = defaultdict(set)
        requirement_values: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
        requirement_samples: dict[tuple[str, str], list[str]] = defaultdict(list)
        for job_id, items in facts.items():
            for fact in items:
                if fact.get("state") == "explicit_negative":
                    continue
                fact_type = str(fact.get("fact_type") or "other")
                fact_types[fact_type].add(job_id)
                value = str(_fact_value(fact) or fact.get("source_wording") or "").strip()
                if value:
                    normalized = value.casefold()
                    requirement_values[fact_type][normalized].add(job_id)
                    key = (fact_type, normalized)
                    if len(requirement_samples[key]) < 3 and value not in requirement_samples[key]:
                        requirement_samples[key].append(value)

        coverage_types = {
            "languageRequirement": {"language"},
            "experienceRequirement": {"experience"},
            "certificationRequirement": {"certification"},
            "educationRequirement": {"education"},
            "schedule": {"schedule", "shift_work"},
            "drivingLicence": {"driving_licence"},
        }
        coverage = {
            "salary": self._coverage(
                {str(row["id"]) for row in observed if self._salary_group_key(row)}, denominator, "Salary"
            ),
            "workModel": self._coverage(
                {str(row["id"]) for row in observed if _known(row.get("work_mode"))}, denominator, "Work model"
            ),
            "location": self._coverage(
                {str(row["id"]) for row in observed if _known(row.get("location_city")) or _known(row.get("location_country"))}, denominator, "Location"
            ),
        }
        for key, types in coverage_types.items():
            coverage[key] = self._coverage(set().union(*(fact_types[item] for item in types)), denominator, key)

        requirement_rows = []
        for fact_type in sorted(requirement_values):
            if fact_type in {"skill", "tool"}:
                continue
            values = []
            for normalized, job_ids in requirement_values[fact_type].items():
                values.append({
                    "value": requirement_samples[(fact_type, normalized)][0],
                    "jobCount": len(job_ids),
                    "denominator": denominator,
                    "percent": _percent(len(job_ids), denominator),
                    "sourceWordingSamples": requirement_samples[(fact_type, normalized)],
                })
            values.sort(key=lambda item: (-item["jobCount"], item["value"].casefold()))
            requirement_rows.append({
                "type": fact_type,
                "jobsWithEvidence": len(fact_types[fact_type] & {str(row["id"]) for row in observed}),
                "denominator": denominator,
                "values": values[:30],
            })

        company_counts = Counter(
            str(row.get("company") or "").strip() if _known(row.get("company")) else "Unknown"
            for row in observed
        )
        companies = [{
            "company": name, "jobs": count, "denominator": denominator,
            "percent": _percent(count, denominator),
            "currentlyActive": sum(
                1 for row in observed if str(row.get("company") or "").strip() == name and str(row["id"]) in current_ids
            ),
        } for name, count in sorted(company_counts.items(), key=lambda item: (-item[1], item[0].casefold()))]

        lifetimes = []
        for listing_rows in sources.values():
            for listing in listing_rows:
                first = _dt(listing.get("first_seen_at"))
                last = _dt(listing.get("source_ended_at") or listing.get("last_seen_at"))
                if first and last and listing.get("lifecycle_state") != "active" and last >= first:
                    lifetimes.append((last - first).total_seconds() / 86400)

        recent_cutoff = end - timedelta(days=7)
        inactive = [row for row in observed if str(row["id"]) not in current_ids]
        source_mix = Counter()
        for row in observed:
            keys = {item["source_key"] for item in sources.get(str(row["id"]), [])}
            for key in keys or {row.get("source_name") or "unknown"}:
                source_mix[str(key)] += 1
        population_rows = [
            (row["id"], row.get("anchor_at"), row.get("updated_at"), tuple(
                (item["id"], item["lifecycle_state"], item["last_seen_at"])
                for item in sources.get(str(row["id"]), [])
            )) for row in observed
        ]
        return {
            "versions": {
                "marketAnalytics": MARKET_ANALYTICS_VERSION,
                "salaryAnalytics": SALARY_POLICY_VERSION,
            },
            "filters": {
                "window": selected_window, "trackId": safe_track,
                "source": safe_source, "geography": safe_geography,
            },
            "populations": {
                "observed": {
                    "entity": "CanonicalJob", "denominator": denominator,
                    "startAt": start.isoformat(timespec="seconds") if start else None,
                    "endAt": end.isoformat(timespec="seconds"),
                    "semantics": "Deduplicated Canonical Jobs first observed inside the selected window.",
                },
                "current": {
                    "entity": "CanonicalJob", "denominator": len(current),
                    "asOf": end.isoformat(timespec="seconds"),
                    "semantics": "Active, non-archived, non-expired deduplicated Canonical Jobs at the current snapshot.",
                },
            },
            "flow": {
                "observedUniqueJobs": denominator,
                "currentlyActiveJobs": len(current),
                "newLast7Days": sum(
                    bool((anchor := _dt(row.get("anchor_at"))) and recent_cutoff <= anchor <= end) for row in rows
                ),
                "expiredOrInactiveObservedJobs": len(inactive),
                "medianObservedLifetimeDays": round(median(lifetimes), 1) if lifetimes else None,
                "lifetimeSample": len(lifetimes),
                "trend": self._trend(observed, selected_window),
            },
            "companies": {
                "distinctKnown": len([name for name in company_counts if name != "Unknown"]),
                "unknownJobs": company_counts.get("Unknown", 0),
                "topFiveConcentration": _ratio(sum(item["jobs"] for item in companies[:5]), denominator),
                "items": companies[:100],
                "interpretation": "Listing frequency is not a company-quality rating.",
            },
            "geography": {
                "countries": self._distribution(observed, "location_country"),
                "cities": self._distribution(observed, "location_city"),
            },
            "workModels": self._distribution(observed, "work_mode"),
            "contractTypes": self._distribution(observed, "contract_type"),
            "coverage": coverage,
            "requirements": requirement_rows,
            "skillIntelligence": {
                "href": f"/api/jobhunt/tracks/{safe_track}/skills/intelligence" if safe_track else "/jobhunt.html#skills",
                "semantics": "Detailed skill/tool demand remains owned by Pack K and is not duplicated here.",
            },
            "salary": self._salary(observed, denominator),
            "sourceMix": [
                {"source": key, "jobs": value, "denominator": denominator}
                for key, value in sorted(source_mix.items(), key=lambda item: (-item[1], item[0]))
            ],
            "fingerprint": _fingerprint({
                "version": MARKET_ANALYTICS_VERSION, "filters": [selected_window, safe_track, safe_source, safe_geography],
                "population": population_rows,
            }),
            "generatedAt": end.isoformat(timespec="seconds"),
            "materialization": {"strategy": "bounded_live_query", "durableSnapshot": False},
        }

    def sources(self, *, window: Any = "90d") -> dict[str, Any]:
        selected_window, start, end = self._window(window)
        start_text = start.isoformat(timespec="seconds") if start else "0001-01-01T00:00:00+00:00"
        with self.store.read_connection() as connection:
            definitions = [dict(row) for row in connection.execute(
                """SELECT d.*,p.enabled,p.operational_state,p.last_attempt_at,p.last_success_at,
                          p.failure_count,p.last_error_class,p.updated_at AS policy_updated_at
                     FROM source_definitions d JOIN source_policies p ON p.source_id=d.id
                    WHERE d.adapter_implemented=1 AND d.definition_state='active'
                    ORDER BY d.display_name"""
            )]
            total_listings = int(connection.execute(
                "SELECT COUNT(*) FROM source_listings WHERE first_seen_at>=? AND first_seen_at<=?",
                (start_text, end.isoformat(timespec="seconds")),
            ).fetchone()[0])
            if total_listings > MAX_SOURCE_LISTINGS:
                raise JobhuntError(
                    "Source analytics population exceeds the bounded live-query limit; choose a shorter window",
                    status=422, code="source_analytics_population_too_large",
                )
            rows = []
            for source in definitions:
                source_id = source["id"]
                listings = [dict(row) for row in connection.execute(
                    """SELECT l.* FROM source_listings l
                        WHERE l.source_id=? AND l.first_seen_at>=? AND l.first_seen_at<=?
                        ORDER BY l.first_seen_at,l.id""",
                    (source_id, start_text, end.isoformat(timespec="seconds")),
                )]
                listing_ids = {item["id"] for item in listings}
                job_ids = {str(item["canonical_job_id"]) for item in listings if item.get("canonical_job_id")}
                unique_jobs = set()
                overlapping_jobs = set()
                for job_id in job_ids:
                    contributor_count = int(connection.execute(
                        "SELECT COUNT(DISTINCT source_id) FROM source_listings WHERE canonical_job_id=?",
                        (job_id,),
                    ).fetchone()[0])
                    (unique_jobs if contributor_count == 1 else overlapping_jobs).add(job_id)
                requests = [dict(row) for row in connection.execute(
                    """SELECT * FROM source_request_observations
                        WHERE source_id=? AND created_at>=? AND created_at<=?""",
                    (source_id, start_text, end.isoformat(timespec="seconds")),
                )]
                successes = sum(
                    item.get("retry_classification") in (None, "success", "not_modified")
                    and (item.get("status_code") is None or int(item["status_code"]) < 400)
                    for item in requests
                )
                failures = len(requests) - successes
                extraction_failures = int(connection.execute(
                    """SELECT COUNT(DISTINCT r.id) FROM extraction_runs r
                        JOIN raw_captures c ON c.id=r.capture_id
                        JOIN source_listings l ON l.id=c.listing_id
                        WHERE l.source_id=? AND r.status='failed' AND r.created_at>=? AND r.created_at<=?""",
                    (source_id, start_text, end.isoformat(timespec="seconds")),
                ).fetchone()[0])
                capture_count = int(connection.execute(
                    """SELECT COUNT(*) FROM raw_captures c JOIN source_listings l ON l.id=c.listing_id
                        WHERE l.source_id=? AND c.created_at>=? AND c.created_at<=?""",
                    (source_id, start_text, end.isoformat(timespec="seconds")),
                ).fetchone()[0])
                review_count = 0
                duplicate_count = 0
                if listing_ids or job_ids:
                    review_count = int(connection.execute(
                        """SELECT COUNT(*) FROM review_items r
                            WHERE r.created_at>=? AND r.created_at<=? AND (
                              (r.entity_type='listing' AND r.entity_id IN (SELECT id FROM source_listings WHERE source_id=?))
                              OR (r.entity_type='capture' AND r.entity_id IN (
                                SELECT c.id FROM raw_captures c JOIN source_listings l ON l.id=c.listing_id WHERE l.source_id=?
                              ))
                              OR (r.entity_type='job' AND r.entity_id IN (
                                SELECT canonical_job_id FROM source_listings WHERE source_id=? AND canonical_job_id IS NOT NULL
                              ))
                            )""",
                        (start_text, end.isoformat(timespec="seconds"), source_id, source_id, source_id),
                    ).fetchone()[0])
                    duplicate_count = int(connection.execute(
                        """SELECT COUNT(DISTINCT d.id) FROM duplicate_candidates d
                            WHERE d.generated_at>=? AND d.generated_at<=? AND (
                              d.left_job_id IN (SELECT canonical_job_id FROM source_listings WHERE source_id=?)
                              OR d.right_job_id IN (SELECT canonical_job_id FROM source_listings WHERE source_id=?))""",
                        (start_text, end.isoformat(timespec="seconds"), source_id, source_id),
                    ).fetchone()[0])
                latency = connection.execute(
                    """SELECT AVG((julianday(r.completed_at)-julianday(c.captured_at))*86400000.0)
                         FROM extraction_runs r JOIN raw_captures c ON c.id=r.capture_id
                         JOIN source_listings l ON l.id=c.listing_id
                        WHERE l.source_id=? AND r.completed_at IS NOT NULL
                          AND r.created_at>=? AND r.created_at<=?""",
                    (source_id, start_text, end.isoformat(timespec="seconds")),
                ).fetchone()[0]
                listing_count = len(listings)
                linked_listing_count = sum(bool(item.get("canonical_job_id")) for item in listings)
                inactive_count = sum(item["lifecycle_state"] != "active" for item in listings)
                rows.append({
                    "sourceId": source_id,
                    "sourceKey": source["source_key"],
                    "displayName": source["display_name"],
                    "population": {"entity": "SourceListing", "denominator": listing_count},
                    "listingsDiscovered": listing_count,
                    "canonicalJobsContributed": len(job_ids),
                    "unlinkedListings": listing_count - linked_listing_count,
                    "duplicateRate": _ratio(
                        max(0, linked_listing_count - len(job_ids)), linked_listing_count,
                    ),
                    "uniqueContribution": len(unique_jobs),
                    "overlappingCanonicalJobs": len(overlapping_jobs),
                    "duplicateOverlap": _ratio(len(overlapping_jobs), len(job_ids)),
                    "currentActiveListings": sum(item["lifecycle_state"] == "active" for item in listings),
                    "staleOrExpired": _ratio(inactive_count, listing_count),
                    "capturesCreated": capture_count,
                    "requests": {"total": len(requests), "succeeded": successes, "failed": failures},
                    "extractionFailures": extraction_failures,
                    "reviewBurden": {
                        "reviewItems": review_count,
                        "duplicateCandidates": duplicate_count,
                        "per100Listings": round(review_count * 100 / listing_count, 1) if listing_count else None,
                        "denominator": listing_count,
                    },
                    "averageProcessingLatencyMs": round(float(latency), 1) if latency is not None else None,
                    "health": {
                        "enabled": bool(source["enabled"]),
                        "operationalState": source["operational_state"],
                        "lastAttemptAt": source.get("last_attempt_at"),
                        "lastSuccessAt": source.get("last_success_at"),
                        "failureCount": int(source.get("failure_count") or 0),
                        "lastErrorClass": source.get("last_error_class"),
                        "degradedSince": source.get("policy_updated_at") if source["operational_state"] == "degraded" else None,
                    },
                    "interpretation": "Overlap can provide corroborating evidence; it is not automatically wasted collection.",
                })
        return {
            "version": SOURCE_ANALYTICS_VERSION,
            "window": {"id": selected_window, "startAt": start.isoformat(timespec="seconds") if start else None, "endAt": end.isoformat(timespec="seconds")},
            "population": {"entity": "SourceListing", "denominator": total_listings},
            "sources": rows,
            "fingerprint": _fingerprint({"version": SOURCE_ANALYTICS_VERSION, "window": selected_window, "sources": rows}),
            "generatedAt": end.isoformat(timespec="seconds"),
            "materialization": {"strategy": "bounded_live_query", "durableSnapshot": False},
        }

    @staticmethod
    def _application_event_stage(event: dict[str, Any]) -> str | None:
        event_type = str(event.get("event_type") or "").casefold()
        payload = _loads(event.get("payload_json"), {})
        target = str(payload.get("to") or payload.get("status") or "").casefold()
        values = {event_type, target}
        if "applied" in values or event_type == "application_sent":
            return "applied"
        for stage, aliases in (
            ("screening", {"screening", "screened", "recruiter_response", "screen_response"}),
            ("interview", {"interview", "interview_scheduled", "interview_completed"}),
            ("final", {"final", "final_interview"}),
            ("offer", {"offer", "offer_received"}),
            ("rejected", {"rejected", "rejection_received"}),
            ("withdrawn", {"withdrawn", "withdrawal"}),
        ):
            if values & aliases:
                return stage
        return None

    def applications(
        self, *, window: Any = "180d", track_id: Any = None, source: Any = None,
    ) -> dict[str, Any]:
        selected_window, start, end = self._window(window)
        safe_track = str(track_id or "").strip() or None
        safe_source = str(source or "").strip() or None
        with self.store.read_connection() as connection:
            if safe_track and not connection.execute("SELECT 1 FROM career_tracks WHERE id=?", (safe_track,)).fetchone():
                raise JobhuntError("Track not found", status=404, code="track_not_found")
            source_row = None
            if safe_source:
                source_row = connection.execute(
                    "SELECT id,source_key FROM source_definitions WHERE source_key=? COLLATE NOCASE OR id=?",
                    (safe_source, safe_source),
                ).fetchone()
                if not source_row:
                    raise JobhuntError("Source not found", status=404, code="source_not_found")
            applications = [dict(row) for row in connection.execute(
                """SELECT a.*,j.company,j.role_title,j.source_name
                     FROM applications a JOIN canonical_jobs j ON j.id=a.job_id
                    WHERE j.deleted_at IS NULL AND j.merged_into_job_id IS NULL
                    ORDER BY a.created_at,a.id"""
            )]
            events_by_app: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for row in connection.execute(
                "SELECT * FROM application_events ORDER BY occurred_at,id"
            ):
                events_by_app[str(row["application_id"])].append(dict(row))
            attributions = {
                row["application_id"]: dict(row) for row in connection.execute(
                    "SELECT * FROM application_attributions"
                )
            }
            track_names = {row["id"]: row["name"] for row in connection.execute("SELECT id,name FROM career_tracks")}
            source_names = {row["id"]: row["source_key"] for row in connection.execute("SELECT id,source_key FROM source_definitions")}
            assignment_rows = [dict(row) for row in connection.execute(
                """SELECT a.*,t.name FROM track_job_assignments a JOIN career_tracks t ON t.id=a.track_id
                    WHERE a.active=1 ORDER BY CASE a.origin WHEN 'manual' THEN 0 ELSE 1 END,a.created_at,a.track_id"""
            )]
            assignments: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for row in assignment_rows:
                assignments[str(row["job_id"])].append(row)
            discovery_rows = [dict(row) for row in connection.execute(
                """SELECT l.canonical_job_id,l.source_id,d.source_key,l.first_seen_at
                     FROM source_listings l JOIN source_definitions d ON d.id=l.source_id
                    WHERE l.canonical_job_id IS NOT NULL ORDER BY l.first_seen_at,l.id"""
            )]
            discovery: dict[str, dict[str, Any]] = {}
            contributors: dict[str, set[str]] = defaultdict(set)
            for row in discovery_rows:
                discovery.setdefault(str(row["canonical_job_id"]), row)
                contributors[str(row["canonical_job_id"])].add(str(row["source_key"]))

        included = []
        for application in applications:
            events = events_by_app[str(application["id"])]
            stages: dict[str, datetime] = {}
            structured_reasons = []
            for event in events:
                stage = self._application_event_stage(event)
                occurred = _dt(event.get("occurred_at"))
                if stage and occurred and stage not in stages:
                    stages[stage] = occurred
                payload = _loads(event.get("payload_json"), {})
                reason = payload.get("reasonCode") or payload.get("outcomeReason")
                if reason and stage in {"rejected", "withdrawn"}:
                    structured_reasons.append(str(reason))
            submitted = stages.get("applied") or _dt(application.get("date_applied"))
            if not submitted or (start and submitted < start) or submitted > end:
                continue
            attribution = attributions.get(str(application["id"]), {})
            track = attribution.get("track_id")
            basis = attribution.get("attribution_basis")
            if not track:
                candidates = assignments.get(str(application["job_id"]), [])
                track = candidates[0]["track_id"] if candidates else None
                basis = "multiple_current_tracks" if len(candidates) > 1 else ("fallback_current_assignment" if candidates else "unattributed")
            source_id = attribution.get("discovery_source_id")
            if source_id:
                source_key = source_names.get(source_id)
            else:
                origin = discovery.get(str(application["job_id"]))
                source_id = origin.get("source_id") if origin else None
                source_key = origin.get("source_key") if origin else str(application.get("source_name") or "unknown")
            if safe_track and track != safe_track:
                continue
            if source_row and source_id != source_row["id"] and source_key != source_row["source_key"]:
                continue
            response_candidates = [stages[key] for key in ("screening", "interview", "final", "offer", "rejected") if key in stages and stages[key] >= submitted]
            first_response = min(response_candidates) if response_candidates else None
            outcome_candidates = [stages[key] for key in ("offer", "rejected", "withdrawn") if key in stages and stages[key] >= submitted]
            first_outcome = min(outcome_candidates) if outcome_candidates else None
            included.append({
                "application": application, "events": events, "stages": stages,
                "submitted": submitted, "firstResponse": first_response, "firstOutcome": first_outcome,
                "trackId": track, "trackName": track_names.get(track, "Unattributed"),
                "attributionBasis": basis, "sourceId": source_id, "sourceKey": source_key,
                "contributingSources": sorted(contributors.get(str(application["job_id"]), {source_key})),
                "structuredReasons": structured_reasons,
            })

        denominator = len(included)
        stage_counts = {
            stage: sum(stage in item["stages"] for item in included)
            for stage in ("screening", "interview", "final", "offer", "rejected", "withdrawn")
        }
        responded = sum(item["firstResponse"] is not None for item in included)
        response_days = [
            (item["firstResponse"] - item["submitted"]).total_seconds() / 86400
            for item in included if item["firstResponse"]
        ]
        interview_days = [
            (item["stages"]["interview"] - item["submitted"]).total_seconds() / 86400
            for item in included if "interview" in item["stages"] and item["stages"]["interview"] >= item["submitted"]
        ]
        outcome_days = [
            (item["firstOutcome"] - item["submitted"]).total_seconds() / 86400
            for item in included if item["firstOutcome"]
        ]

        def grouped(field: str, label: str) -> list[dict[str, Any]]:
            groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for item in included:
                groups[str(item.get(field) or "Unattributed")].append(item)
            values = []
            for key, items in groups.items():
                values.append({
                    label: key,
                    "applications": len(items),
                    "responses": sum(item["firstResponse"] is not None for item in items),
                    "interviews": sum("interview" in item["stages"] for item in items),
                    "offers": sum("offer" in item["stages"] for item in items),
                    "withdrawals": sum("withdrawn" in item["stages"] for item in items),
                    "responseRate": _ratio(
                        sum(item["firstResponse"] is not None for item in items), len(items),
                        minimum_sample=MINIMUM_APPLICATION_RATE_SAMPLE,
                    ),
                })
            return sorted(values, key=lambda item: (-item["applications"], str(item[label]).casefold()))

        reasons = Counter(reason for item in included for reason in item["structuredReasons"])
        event_fingerprint = [
            (item["application"]["id"], item["submitted"].isoformat(),
             tuple((event["id"], event["event_type"], event["occurred_at"], event["payload_json"]) for event in item["events"]))
            for item in included
        ]
        return {
            "version": APPLICATION_ANALYTICS_VERSION,
            "filters": {"window": selected_window, "trackId": safe_track, "source": safe_source},
            "population": {
                "entity": "Application", "denominator": denominator,
                "startAt": start.isoformat(timespec="seconds") if start else None,
                "endAt": end.isoformat(timespec="seconds"),
                "semantics": "Applications with a documented applied event/date inside the selected window.",
            },
            "definitions": {
                "response": "First documented recruiter/screening/interview/offer/rejection event after submission.",
                "trackAttribution": "Captured Track at application time when present; otherwise one disclosed current-assignment fallback. An Application is counted once.",
                "sourceAttribution": "Captured discovery source when present; otherwise the earliest contributing Source Listing. Other contributors remain listed separately.",
                "missingResponse": "Censored/unknown; no response is inferred.",
            },
            "funnel": {"applied": denominator, **stage_counts},
            "rates": {
                "response": _ratio(responded, denominator, minimum_sample=MINIMUM_APPLICATION_RATE_SAMPLE),
                "screening": _ratio(stage_counts["screening"], denominator, minimum_sample=MINIMUM_APPLICATION_RATE_SAMPLE),
                "interview": _ratio(stage_counts["interview"], denominator, minimum_sample=MINIMUM_APPLICATION_RATE_SAMPLE),
                "offer": _ratio(stage_counts["offer"], denominator, minimum_sample=MINIMUM_APPLICATION_RATE_SAMPLE),
                "rejection": _ratio(stage_counts["rejected"], denominator, minimum_sample=MINIMUM_APPLICATION_RATE_SAMPLE),
                "withdrawal": _ratio(stage_counts["withdrawn"], denominator, minimum_sample=MINIMUM_APPLICATION_RATE_SAMPLE),
            },
            "timing": {
                "timeToFirstResponseDays": {"median": round(median(response_days), 1) if response_days else None, "sample": len(response_days), "censored": denominator - len(response_days)},
                "timeToInterviewDays": {"median": round(median(interview_days), 1) if interview_days else None, "sample": len(interview_days), "censored": denominator - len(interview_days)},
                "timeToOutcomeDays": {"median": round(median(outcome_days), 1) if outcome_days else None, "sample": len(outcome_days), "censored": denominator - len(outcome_days)},
            },
            "activePipeline": dict(Counter(
                item["application"]["current_status"] for item in included
                if item["application"]["current_status"] not in {"offer", "rejected", "archived"}
            )),
            "followUpCompletion": {
                "completed": sum(any(event["event_type"] == "follow_up_sent" for event in item["events"]) for item in included),
                "scheduled": sum(any(event["event_type"] == "follow_up_scheduled" for event in item["events"]) for item in included),
            },
            "byTrack": grouped("trackId", "trackId"),
            "byDiscoverySource": grouped("sourceKey", "source"),
            "outcomeReasons": [{"reason": key, "count": value} for key, value in reasons.most_common()],
            "fingerprint": _fingerprint({"version": APPLICATION_ANALYTICS_VERSION, "events": event_fingerprint}),
            "generatedAt": end.isoformat(timespec="seconds"),
            "materialization": {"strategy": "bounded_live_query", "durableSnapshot": False},
        }

    def track(self, track_id: str, *, window: Any = "90d") -> dict[str, Any]:
        market = self.market(window=window, track_id=track_id)
        applications = self.applications(window=window, track_id=track_id)
        with self.store.read_connection() as connection:
            rows = [dict(row) for row in connection.execute(
                """SELECT e.* FROM evaluation_current c JOIN evaluations e ON e.id=c.evaluation_id
                    JOIN canonical_jobs j ON j.id=c.job_id JOIN applications a ON a.job_id=j.id
                    WHERE c.track_id=? AND e.status='completed' AND j.deleted_at IS NULL
                      AND j.merged_into_job_id IS NULL AND j.archived_at IS NULL AND a.source_expired=0""",
                (track_id,),
            )]
            dimensions = [dict(row) for row in connection.execute(
                """SELECT d.dimension,d.state,COUNT(*) AS count FROM evaluation_current c
                    JOIN evaluations e ON e.id=c.evaluation_id
                    JOIN evaluation_dimensions d ON d.evaluation_id=e.id
                    JOIN canonical_jobs j ON j.id=c.job_id JOIN applications a ON a.job_id=j.id
                    WHERE c.track_id=? AND e.status='completed' AND j.deleted_at IS NULL
                      AND j.merged_into_job_id IS NULL AND j.archived_at IS NULL AND a.source_expired=0
                    GROUP BY d.dimension,d.state ORDER BY d.dimension,d.state""",
                (track_id,),
            )]
            findings = [dict(row) for row in connection.execute(
                """SELECT f.status,f.requirement_class,COUNT(*) AS count FROM evaluation_current c
                    JOIN evaluations e ON e.id=c.evaluation_id
                    JOIN evaluation_findings f ON f.evaluation_id=e.id
                    JOIN canonical_jobs j ON j.id=c.job_id JOIN applications a ON a.job_id=j.id
                    WHERE c.track_id=? AND e.status='completed' AND j.deleted_at IS NULL
                      AND j.merged_into_job_id IS NULL AND j.archived_at IS NULL AND a.source_expired=0
                    GROUP BY f.status,f.requirement_class ORDER BY f.status,f.requirement_class""",
                (track_id,),
            )]
        denominator = market["populations"]["current"]["denominator"]
        evaluated = len(rows)
        return {
            "version": TRACK_ANALYTICS_VERSION,
            "trackId": track_id,
            "window": market["filters"]["window"],
            "market": market,
            "evaluations": {
                "population": {"entity": "CanonicalJob", "denominator": denominator},
                "evaluatedJobs": evaluated,
                "coverage": _ratio(evaluated, denominator),
                "blockerFreeJobs": sum(int(row.get("blocker_count") or 0) == 0 for row in rows),
                "jobsWithBlockers": sum(int(row.get("blocker_count") or 0) > 0 for row in rows),
                "jobsWithUnknowns": sum(int(row.get("unknown_count") or 0) > 0 for row in rows),
                "requiredGaps": sum(int(row.get("required_gap_count") or 0) for row in rows),
                "unknownFindings": sum(int(row.get("unknown_count") or 0) for row in rows),
                "dimensions": dimensions,
                "findings": findings,
                "semantics": "Current Pack J Evaluations only; historical Evaluations are not mixed into this snapshot.",
            },
            "applications": applications,
            "skillIntelligence": {
                "version": "skill-intelligence@1",
                "href": f"/api/jobhunt/tracks/{track_id}/skills/intelligence",
                "semantics": "Detailed skill demand remains owned by Pack K and is linked rather than duplicated.",
            },
            "fingerprint": _fingerprint({
                "version": TRACK_ANALYTICS_VERSION, "market": market["fingerprint"],
                "applications": applications["fingerprint"],
                "evaluations": [(row["id"], row["input_fingerprint"]) for row in rows],
            }),
            "generatedAt": market["generatedAt"],
        }

    def tradeoff(self, track_ids: Iterable[Any], *, window: Any = "90d") -> dict[str, Any]:
        ids = [str(item).strip() for item in track_ids if str(item).strip()]
        ids = list(dict.fromkeys(ids))
        if len(ids) < 2 or len(ids) > 5:
            raise JobhuntError("Choose between 2 and 5 Tracks", code="invalid_tradeoff_tracks")
        selected_window = self.validate_window(window)
        items = []
        for track_id in ids:
            analytics = self.track(track_id, window=selected_window)
            track = self.store.get_track(track_id)
            if not track:
                raise JobhuntError("Track not found", status=404, code="track_not_found")
            scenario = self.store.get_current_economic_scenario(track_id)
            assumptions = scenario.get("assumptions", {}) if scenario else {}
            costs = assumptions.get("monthlyCosts") if isinstance(assumptions.get("monthlyCosts"), dict) else {}
            required_costs = ("housing", "utilities", "food", "transport", "other")
            cost_values = [
                value.get("value") if isinstance((value := costs.get(key)), dict) else value
                for key in required_costs
            ]
            complete_costs = all(isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 for value in cost_values)
            total_costs = sum(float(value) for value in cost_values) if complete_costs else None
            net = assumptions.get("netMonthlyEstimate") if isinstance(assumptions.get("netMonthlyEstimate"), dict) else {}
            net_amount = net.get("amount") if isinstance(net.get("amount"), (int, float)) and not isinstance(net.get("amount"), bool) else None
            remainder = float(net_amount) - total_costs if net_amount is not None and total_costs is not None else None
            fx = assumptions.get("fx") if isinstance(assumptions.get("fx"), dict) else {}
            fx_rate = fx.get("rateToBase") if isinstance(fx.get("rateToBase"), (int, float)) and fx.get("rateToBase", 0) > 0 else None
            currency = str(track.get("primary_currency") or (scenario or {}).get("currency") or "unknown")
            salary_group = next((
                group for group in analytics["market"]["salary"]["groups"]
                if group["currency"] == currency.upper() and group["period"] == "month" and group["taxType"] == "gross"
            ), None)
            unknowns = []
            if not salary_group or salary_group["status"] != "sufficient":
                unknowns.append("insufficient comparable gross monthly salary evidence")
            if net_amount is None:
                unknowns.append("net estimate unavailable")
            if not complete_costs:
                unknowns.append("living-cost assumptions incomplete")
            if not fx_rate:
                unknowns.append("manual FX assumption unavailable")
            language_requirement = analytics["market"]["coverage"].get("languageRequirement", {})
            language_rows = next((
                item for item in analytics["market"].get("requirements", []) if item.get("type") == "language"
            ), {"values": []})
            evaluated_jobs = int(analytics["evaluations"].get("evaluatedJobs") or 0)
            jobs_with_unknowns = int(analytics["evaluations"].get("jobsWithUnknowns") or 0)
            items.append({
                "track": {"id": track_id, "name": track["name"], "status": track["status"], "currency": currency},
                "currentJobs": analytics["market"]["populations"]["current"]["denominator"],
                "observedJobs": analytics["market"]["populations"]["observed"]["denominator"],
                "salaryEvidence": salary_group,
                "estimatedNetMonthly": net_amount,
                "netEstimate": net or None,
                "monthlyLivingCosts": total_costs,
                "costAssumptions": costs,
                "estimatedMonthlyRemainder": remainder,
                "remainderLabel": "scenario estimate" if remainder is not None else None,
                "commonCurrency": fx.get("baseCurrency") if fx_rate else None,
                "estimatedRemainderInBaseCurrency": remainder * fx_rate if remainder is not None and fx_rate else None,
                "fxAssumption": fx or None,
                "relocationRequired": None if track.get("relocation_relevant") is None else bool(track["relocation_relevant"]),
                "requiredSkillGaps": analytics["evaluations"]["requiredGaps"],
                "evaluationUnknowns": analytics["evaluations"]["unknownFindings"],
                "evaluationUnknownRate": _ratio(jobs_with_unknowns, evaluated_jobs),
                "languageRequirements": language_rows.get("values", [])[:5],
                "languageRequirementCoverage": language_requirement,
                "applicationFunnel": analytics["applications"]["funnel"],
                "economicScenario": scenario,
                "uncertainty": unknowns,
            })
        return {
            "version": TRADEOFF_VERSION,
            "window": selected_window,
            "tracks": items,
            "winner": None,
            "semantics": "Factual and scenario rows are shown side by side. No winner or aggregate career score is calculated.",
            "fingerprint": _fingerprint({
                "version": TRADEOFF_VERSION, "window": selected_window,
                "tracks": [(item["track"]["id"], item["economicScenario"].get("fingerprint") if item["economicScenario"] else None) for item in items],
            }),
            "generatedAt": self._window(selected_window)[2].isoformat(timespec="seconds"),
        }
