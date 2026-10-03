"""NAV-specific discovery matching and Pack G collection orchestration."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
import hashlib
import json
import re
from typing import Any, Callable, Mapping
import unicodedata

from .archive import RawArchive, StoredBlob
from ..sources.nav import (
    NAV_ADAPTER_VERSION,
    NAV_BASE_URL,
    NAV_INITIAL_FEED_PATH,
    NAV_SOURCE_ID,
    NavResponse,
    NavSourceAdapter,
    NavSourceError,
)


NAV_MATCHER_VERSION = "nav-discovery-matcher@1"
NAV_STRUCTURED_EXTRACTOR_VERSION = "nav_structured@1"
NAV_DEFAULT_POLL_SECONDS = 120
NAV_DEFAULT_BOOTSTRAP_DAYS = 185
NAV_DEFAULT_DETAIL_BUDGET = 100


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _after(seconds: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=max(0.0, float(seconds)))).isoformat(
        timespec="seconds"
    )


def _fold(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9+#./-]+", " ", text.casefold())).strip()


def _contains(corpus: str, value: Any) -> bool:
    term = _fold(value)
    return bool(term and term in corpus)


def _strings(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item not in (None, "")]
    if value in (None, ""):
        return []
    return [str(value)]


def _nav_content(payload: Mapping[str, Any]) -> dict[str, Any]:
    for key in ("json", "ad_content", "adContent", "content"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return dict(payload)


def _location_values(content: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    countries: list[str] = []
    places: list[str] = []
    locations = content.get("workLocations") or content.get("jobLocation") or content.get("locations")
    if not isinstance(locations, list):
        locations = [locations] if isinstance(locations, dict) else []
    for location in locations[:100]:
        if not isinstance(location, dict):
            continue
        country = location.get("country") or location.get("addressCountry")
        if isinstance(country, dict):
            country = country.get("name")
        if country:
            countries.append(str(country))
        for key in ("municipal", "city", "county", "region", "address"):
            value = location.get(key)
            if value and not isinstance(value, (dict, list)):
                places.append(str(value))
    return countries, places


def _country_key(value: Any) -> str:
    token = _fold(value).replace(" ", "")
    aliases = {
        "no": "no", "nor": "no", "norway": "no", "norge": "no", "noreg": "no",
        "pl": "pl", "pol": "pl", "poland": "pl", "polska": "pl",
        "is": "is", "isl": "is", "iceland": "is", "island": "is",
    }
    return aliases.get(token, token)


class NavDiscoveryMatcher:
    version = NAV_MATCHER_VERSION

    @staticmethod
    def _profile_header_match(header: Mapping[str, Any], profile: Mapping[str, Any]) -> bool:
        corpus = _fold(" ".join(str(header.get(key) or "") for key in ("title", "company", "municipality")))
        if any(_contains(corpus, term) for term in profile.get("exclude_keywords") or []):
            return False
        regions = profile.get("regions_cities") or []
        municipality = _fold(header.get("municipality"))
        if regions and municipality and not any(_contains(municipality, value) for value in regions):
            return False
        include = profile.get("include_keywords") or []
        if not include:
            return True
        if any(_contains(corpus, term) for term in include):
            return True
        role_terms = [term for term in re.split(r"[/,;|]", str(profile.get("role_intent") or "")) if len(_fold(term)) >= 3]
        if any(_contains(corpus, term) for term in role_terms):
            return True
        # A missing title cannot support a safe negative decision. A complete,
        # non-matching title is rejected using ANY-keyword semantics, never all-keyword semantics.
        return not bool(_fold(header.get("title")))

    def prefilter(
        self, header: Mapping[str, Any], profiles: list[Mapping[str, Any]]
    ) -> list[str]:
        return [
            str(profile["id"])
            for profile in profiles
            if self._profile_header_match(header, profile)
        ]

    @staticmethod
    def _profile_detail_match(content: Mapping[str, Any], profile: Mapping[str, Any]) -> bool:
        employer = content.get("employer")
        employer_name = employer.get("name") if isinstance(employer, dict) else employer
        countries, places = _location_values(content)
        searchable = [
            content.get("title"), content.get("jobtitle"), content.get("description"),
            employer_name, content.get("engagementtype"), content.get("extent"),
            content.get("sector"), *places,
        ]
        for category in content.get("occupationCategories") or []:
            if isinstance(category, dict):
                searchable.extend(category.values())
        corpus = _fold(" ".join(str(value) for value in searchable if value not in (None, "")))
        if any(_contains(corpus, term) for term in profile.get("exclude_keywords") or []):
            return False
        include = profile.get("include_keywords") or []
        if include and not any(_contains(corpus, term) for term in include):
            return False
        allowed_countries = {_country_key(value) for value in profile.get("countries") or []}
        observed_countries = {_country_key(value) for value in countries if _country_key(value)}
        if allowed_countries and observed_countries and allowed_countries.isdisjoint(observed_countries):
            return False
        regions = profile.get("regions_cities") or []
        if regions and places:
            location_corpus = _fold(" ".join(places))
            if not any(_contains(location_corpus, value) for value in regions):
                return False
        explicit_fields = (
            ("work_models", (content.get("workModel"), content.get("workMode"), content.get("remoteType"))),
            ("contract_hints", (content.get("engagementtype"), content.get("employmentType"))),
            ("schedule_hints", (content.get("extent"), content.get("workSchedule"), content.get("description"))),
            ("language_hints", (content.get("languages"), content.get("languageRequirements"), content.get("description"))),
            ("seniority_hints", (content.get("title"), content.get("jobtitle"), content.get("description"))),
        )
        for criterion, values in explicit_fields:
            expected = profile.get(criterion) or []
            available = _fold(" ".join(str(value) for value in values if value not in (None, "")))
            if expected and available and not any(_contains(available, value) for value in expected):
                return False
        return True

    def full_match(
        self, payload: Mapping[str, Any], profiles: list[Mapping[str, Any]]
    ) -> list[str]:
        content = _nav_content(payload)
        return [
            str(profile["id"])
            for profile in profiles
            if self._profile_detail_match(content, profile)
        ]


class NavCollectionCoordinator:
    def __init__(
        self,
        *,
        store: Any,
        archive: RawArchive,
        adapter: NavSourceAdapter,
        matcher: NavDiscoveryMatcher | None = None,
        detail_budget: int = NAV_DEFAULT_DETAIL_BUDGET,
        bootstrap_days: int = NAV_DEFAULT_BOOTSTRAP_DAYS,
    ) -> None:
        self.store = store
        self.archive = archive
        self.adapter = adapter
        self.matcher = matcher or NavDiscoveryMatcher()
        self.detail_budget = max(1, min(500, int(detail_budget)))
        self.bootstrap_days = max(1, min(366, int(bootstrap_days)))

    def _policy(self) -> dict[str, Any]:
        source = self.store.get_source(NAV_SOURCE_ID)
        if not source:
            raise NavSourceError("NAV source definition is missing", classification="internal")
        if not source.get("enabled") or source.get("operational_state") == "paused":
            raise NavSourceError("NAV collection is paused", classification="policy_stop")
        if not self.adapter.token_configured:
            raise NavSourceError("NAV token is not configured", classification="authentication")
        backoff = source.get("backoff_until")
        if backoff and str(backoff) > _now():
            error = NavSourceError("NAV source is in persisted backoff", classification="rate_limit", retryable=True)
            try:
                target = datetime.fromisoformat(str(backoff).replace("Z", "+00:00"))
                error.retry_after_seconds = max(1.0, (target - datetime.now(timezone.utc)).total_seconds())
            except ValueError:
                pass
            raise error
        return source

    @staticmethod
    def _listing_values(header: Mapping[str, Any], *, lifecycle: str, observed_at: str) -> dict[str, Any]:
        external_id = str(header["external_id"])
        detail_path = str(header["detail_path"])
        return {
            "source_id": NAV_SOURCE_ID,
            "identity_key": "external:" + hashlib.sha256(external_id.encode("utf-8")).hexdigest(),
            "external_id": external_id,
            "canonical_url": NAV_BASE_URL + detail_path,
            "observed_url": NAV_BASE_URL + detail_path,
            "title_hint": header.get("title"),
            "company_hint": header.get("company"),
            "location_hint": header.get("municipality"),
            "lifecycle_state": lifecycle,
            "source_ended_at": observed_at if lifecycle in {"expired", "removed"} else None,
            "notes": f"Observed by {NAV_ADAPTER_VERSION}; matched by {NAV_MATCHER_VERSION}.",
        }

    def _observe_success(self, response: NavResponse, *, started_at: str) -> None:
        completed = _now()
        self.store.record_source_request({
            "source_id": NAV_SOURCE_ID,
            "operation_type": response.operation,
            "request_path": response.request_path,
            "status_code": response.status_code,
            "started_at": started_at,
            "completed_at": completed,
            "duration_ms": response.duration_ms,
            "response_bytes": response.response_bytes,
            "retry_classification": None,
            "etag": response.etag,
            "last_modified": response.last_modified,
        })

    def observe_failure(self, error: Exception, *, operation: str, started_at: str) -> None:
        self.store.record_source_request({
            "source_id": NAV_SOURCE_ID,
            "operation_type": operation,
            "request_path": str(getattr(error, "request_path", None) or "unknown")[:2048],
            "status_code": getattr(error, "status_code", None),
            "started_at": started_at,
            "completed_at": _now(),
            "duration_ms": getattr(error, "duration_ms", None),
            "response_bytes": getattr(error, "response_bytes", None),
            "retry_classification": str(getattr(error, "classification", "internal"))[:100],
            "etag": getattr(error, "etag", None),
            "last_modified": getattr(error, "last_modified", None),
        })

    @staticmethod
    def _poll_followup(path: str, *, delay: int) -> dict[str, Any]:
        key_hash = hashlib.sha256(path.encode("utf-8")).hexdigest()[:24]
        return {
            "job_type": "nav_feed_poll",
            "payload": {"source": "nav", "feedPath": path},
            "idempotency_key": f"nav-poll:{key_hash}",
            "priority": 0,
            "max_attempts": 8,
            "next_attempt_at": _after(delay),
        }

    def poll_feed(
        self,
        payload: Mapping[str, Any],
        *,
        cancelled: Callable[[], bool],
        progress: Callable[[str, float | None], None],
    ) -> dict[str, Any]:
        policy = self._policy()
        state = self.store.get_source_sync_state(NAV_SOURCE_ID) or {}
        now = _now()
        requested_path = self.adapter.validate_path(
            str(payload.get("feedPath") or state.get("feed_path") or NAV_INITIAL_FEED_PATH),
            operation="feed",
        )
        persisted_path = state.get("feed_path")
        if (
            payload.get("feedPath")
            and persisted_path
            and requested_path != persisted_path
            and state.get("conditional_feed_path") == requested_path
        ):
            progress("feed_checkpoint_already_advanced", 0.95)
            return {
                "staleCheckpoint": True,
                "observed": 0,
                "followups": [self._poll_followup(str(persisted_path), delay=0)],
            }
        state = {**state, "feed_path": requested_path}
        if not state.get("bootstrap_started_at"):
            horizon = int(state.get("bootstrap_horizon_days") or self.bootstrap_days)
            state["bootstrap_if_modified_since"] = format_datetime(
                datetime.now(timezone.utc) - timedelta(days=horizon), usegmt=True
            )
            self.store.update_source_sync_state(
                NAV_SOURCE_ID,
                {
                    "bootstrap_started_at": now,
                    "bootstrap_horizon_days": horizon,
                    "bootstrap_if_modified_since": state["bootstrap_if_modified_since"],
                },
                now=now,
            )
        request_state = dict(state)
        if state.get("conditional_feed_path") != requested_path:
            request_state["etag"] = None
            request_state["last_modified"] = None
            if not (
                requested_path == NAV_INITIAL_FEED_PATH
                and not state.get("conditional_feed_path")
                and not state.get("bootstrap_completed_at")
            ):
                request_state["bootstrap_if_modified_since"] = None
        self.store.record_source_attempt(NAV_SOURCE_ID, now=now)
        progress("polling_feed", 0.1)
        started = now
        try:
            result = self.adapter.poll_feed(request_state, policy)
        except Exception as exc:
            self.observe_failure(exc, operation="feed", started_at=started)
            raise
        response: NavResponse = result["response"]
        self._observe_success(response, started_at=started)
        if cancelled():
            raise NavSourceError("NAV feed job was cancelled", classification="cancelled")
        cadence = int(policy.get("polling_cadence_seconds") or NAV_DEFAULT_POLL_SECONDS)
        if result["not_modified"]:
            stats = self.store.source_stats(NAV_SOURCE_ID)
            changes = {
                "feed_path": requested_path,
                "conditional_feed_path": requested_path,
                "etag": response.etag or state.get("etag"),
                "last_modified": response.last_modified or state.get("last_modified"),
                "last_poll_at": now,
                "last_success_at": now,
                "last_error_class": None,
                "last_error_message": None,
                "active_listings": stats["active"],
                "matched_listings": stats["matched"],
                "captures_created": stats["captures"],
            }
            if not state.get("bootstrap_completed_at"):
                changes["bootstrap_completed_at"] = now
            self.store.update_source_sync_state(NAV_SOURCE_ID, changes, now=now)
            self.store.record_source_success(NAV_SOURCE_ID, now=now)
            progress("feed_unchanged", 0.95)
            return {
                "notModified": True,
                "observed": 0,
                "followups": [self._poll_followup(requested_path, delay=cadence)],
            }

        profiles = self.store.enabled_source_profiles(NAV_SOURCE_ID)
        followups: list[dict[str, Any]] = []
        observed = 0
        active = 0
        inactive = 0
        scheduled = 0
        last_event = state.get("last_feed_event_at")
        budget = min(
            self.detail_budget,
            int(policy.get("maximum_request_budget") or self.detail_budget),
        )
        items = result["items"]
        for index, item in enumerate(items):
            if cancelled():
                raise NavSourceError("NAV feed job was cancelled", classification="cancelled")
            header = self.adapter.feed_header(item)
            observed += 1
            modified = header.get("modified_at")
            if modified and (not last_event or str(modified) > str(last_event)):
                last_event = modified
            known = self.store.source_listing_by_external_id(NAV_SOURCE_ID, header["external_id"])
            if header["status"] == "INACTIVE":
                inactive += 1
                if known:
                    self.store.upsert_source_listing(
                        listing=self._listing_values(header, lifecycle="removed", observed_at=now),
                        search_profile_ids=[], observed_at=now,
                    )
                continue
            active += 1
            candidate_ids = self.matcher.prefilter(header, profiles)
            if not candidate_ids or scheduled >= budget:
                continue
            listing_result = self.store.upsert_source_listing(
                listing=self._listing_values(header, lifecycle="active", observed_at=now),
                search_profile_ids=[], observed_at=now,
            )
            fetch_key = f"nav-fetch:{header['external_id']}:{header.get('modified_at') or header['entry_id']}"
            followups.append({
                "job_type": "nav_fetch_listing",
                "payload": {
                    "source": "nav",
                    "listingId": listing_result["listing_id"],
                    "sourceUuid": header["external_id"],
                    "feedEntryId": header["entry_id"],
                    "detailPath": header["detail_path"],
                    "modifiedAt": header.get("modified_at"),
                    "candidateProfileIds": candidate_ids,
                    "header": {
                        "title": header.get("title"),
                        "company": header.get("company"),
                        "municipality": header.get("municipality"),
                    },
                },
                "idempotency_key": fetch_key[:500],
                "priority": 10,
                "max_attempts": 6,
                "next_attempt_at": now,
            })
            scheduled += 1
            progress("filtering_feed", min(0.8, 0.15 + (index + 1) / max(1, len(items)) * 0.65))

        next_path = result.get("next_path") or requested_path
        tail = result.get("next_path") is None
        followups.append(self._poll_followup(next_path, delay=cadence if tail else 0))
        previous_observed = state.get("listings_observed")
        stats = self.store.source_stats(NAV_SOURCE_ID)
        changes = {
            "feed_path": next_path,
            "current_feed_page_id": result.get("page_id"),
            "next_feed_page_id": result.get("next_id"),
            "etag": response.etag or state.get("etag"),
            "last_modified": response.last_modified or state.get("last_modified"),
            "conditional_feed_path": requested_path,
            "last_feed_event_at": last_event,
            "last_poll_at": now,
            "last_success_at": now,
            "last_error_class": None,
            "last_error_message": None,
            "feed_version": result.get("feed_version") or state.get("feed_version"),
            "listings_observed": int(previous_observed or 0) + observed,
            "active_listings": stats["active"],
            "matched_listings": stats["matched"],
            "captures_created": stats["captures"],
        }
        if tail and not state.get("bootstrap_completed_at"):
            changes["bootstrap_completed_at"] = now
        self.store.update_source_sync_state(NAV_SOURCE_ID, changes, now=now)
        self.store.record_source_success(NAV_SOURCE_ID, now=now)
        progress("feed_page_complete", 0.95)
        return {
            "notModified": False,
            "observed": observed,
            "activeEvents": active,
            "inactiveEvents": inactive,
            "detailJobsScheduled": scheduled,
            "tail": tail,
            "followups": followups,
        }

    def fetch_listing(
        self,
        payload: Mapping[str, Any],
        *,
        cancelled: Callable[[], bool],
        progress: Callable[[str, float | None], None],
    ) -> dict[str, Any]:
        policy = self._policy()
        now = _now()
        progress("fetching_listing", 0.15)
        started = now
        try:
            response = self.adapter.fetch_listing(
                {"detail_path": payload.get("detailPath")}, policy
            )
        except Exception as exc:
            self.observe_failure(exc, operation="detail", started_at=started)
            raise
        self._observe_success(response, started_at=started)
        if cancelled():
            raise NavSourceError("NAV listing job was cancelled", classification="cancelled")
        detail = response.payload or {}
        content = _nav_content(detail)
        external_id = str(detail.get("uuid") or content.get("uuid") or "").strip()
        expected_id = str(payload.get("sourceUuid") or "").strip()
        if not external_id or external_id != expected_id:
            raise NavSourceError(
                "NAV detail identity does not match the feed entry",
                classification="validation", request_path=response.request_path,
            )
        status = str(detail.get("status") or content.get("status") or "ACTIVE").strip().upper()
        header_values = payload.get("header") if isinstance(payload.get("header"), dict) else {}
        header = {
            "external_id": external_id,
            "detail_path": response.request_path,
            "title": content.get("title") or header_values.get("title"),
            "company": ((content.get("employer") or {}).get("name")
                        if isinstance(content.get("employer"), dict) else header_values.get("company")),
            "municipality": header_values.get("municipality"),
        }
        if status == "INACTIVE":
            self.store.upsert_source_listing(
                listing=self._listing_values(header, lifecycle="removed", observed_at=now),
                search_profile_ids=[], observed_at=now,
            )
            self.store.record_source_success(NAV_SOURCE_ID, now=now)
            return {"sourceUuid": external_id, "inactive": True, "captureCreated": False}
        if status != "ACTIVE":
            raise NavSourceError("NAV detail status is invalid", classification="malformed_response")
        candidates = set(str(item) for item in payload.get("candidateProfileIds") or [])
        profiles = [
            profile for profile in self.store.enabled_source_profiles(NAV_SOURCE_ID)
            if profile["id"] in candidates
        ]
        matched_ids = self.matcher.full_match(detail, profiles)
        listing_result = self.store.upsert_source_listing(
            listing=self._listing_values(header, lifecycle="active", observed_at=now),
            search_profile_ids=matched_ids, observed_at=now,
        )
        if not matched_ids:
            self.store.record_source_success(NAV_SOURCE_ID, now=now)
            return {"sourceUuid": external_id, "matched": False, "captureCreated": False}
        progress("archiving_listing", 0.45)
        existing = self.store.get_raw_blob(hashlib.sha256(response.raw).hexdigest())
        if existing:
            self.archive.read_verified(
                relative_path=existing["relative_path"],
                expected_hash=existing["sha256"],
                expected_size=int(existing["byte_size"]),
            )
            blob = StoredBlob(
                sha256=existing["sha256"], byte_size=int(existing["byte_size"]),
                mime_type=existing["mime_type"], file_extension=existing["file_extension"],
                relative_path=existing["relative_path"], created=False,
            )
        else:
            blob = self.archive.store(response.raw, mime_type="application/json", extension=".json")
        capture_result = self.store.save_source_capture(
            listing_id=listing_result["listing_id"],
            blob={
                "sha256": blob.sha256, "byte_size": blob.byte_size,
                "mime_type": blob.mime_type, "file_extension": blob.file_extension,
                "relative_path": blob.relative_path,
            },
            capture={
                "mime_type": "application/json", "file_extension": ".json",
                "source_url": NAV_BASE_URL + response.request_path,
                "http_status": response.status_code,
                "safe_metadata": {
                    "adapterKey": self.adapter.key,
                    "adapterVersion": self.adapter.version,
                    "source": "nav",
                    "feedEntryId": payload.get("feedEntryId"),
                    "sourceUuid": external_id,
                    "sourceModifiedAt": payload.get("modifiedAt"),
                    "observedAt": now,
                    "etag": response.etag,
                    "lastModified": response.last_modified,
                    "requestPath": response.request_path,
                    "matcherVersion": self.matcher.version,
                },
            },
            search_profile_ids=matched_ids,
            observed_at=now,
        )
        stats = self.store.source_stats(NAV_SOURCE_ID)
        self.store.update_source_sync_state(
            NAV_SOURCE_ID,
            {
                "active_listings": stats["active"],
                "matched_listings": stats["matched"],
                "captures_created": stats["captures"],
                "last_success_at": now,
                "last_error_class": None,
                "last_error_message": None,
            },
            now=now,
        )
        self.store.record_source_success(NAV_SOURCE_ID, now=now)
        progress("listing_archived", 0.8)
        followups: list[dict[str, Any]] = []
        if not capture_result["capture_reused"]:
            capture_id = capture_result["capture"]["id"]
            followups.append({
                "job_type": "extract_capture",
                "payload": {"source": "nav", "captureId": capture_id},
                "idempotency_key": f"extract:{capture_id}:{NAV_STRUCTURED_EXTRACTOR_VERSION}",
                "priority": 5,
                "max_attempts": 3,
                "next_attempt_at": now,
            })
        return {
            "sourceUuid": external_id,
            "matched": True,
            "matchedProfileIds": matched_ids,
            "captureId": capture_result["capture"]["id"],
            "captureCreated": not capture_result["capture_reused"],
            "unchanged": capture_result["capture_reused"],
            "followups": followups,
        }


__all__ = [
    "NAV_MATCHER_VERSION",
    "NAV_STRUCTURED_EXTRACTOR_VERSION",
    "NavCollectionCoordinator",
    "NavDiscoveryMatcher",
]
