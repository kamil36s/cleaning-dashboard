"""Jobbnorge Public API discovery, matching, evidence, and pagination orchestration."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import re
from typing import Any, Callable, Mapping
import unicodedata
from urllib.parse import urlsplit

from .archive import RawArchive, StoredBlob
from ..extraction import ExtractionBatch, FactCandidate
from ..sources.jobbnorge import (
    JOBBNORGE_ADAPTER_VERSION,
    JOBBNORGE_BASE_URL,
    JOBBNORGE_SOURCE_ID,
    JOBBNORGE_STRUCTURED_EXTRACTOR_VERSION,
    JobbnorgeResponse,
    JobbnorgeSourceAdapter,
    JobbnorgeSourceError,
)


JOBBNORGE_MATCHER_VERSION = "jobbnorge-discovery-matcher@1"
JOBBNORGE_DEFAULT_POLL_SECONDS = 1800
JOBBNORGE_DEFAULT_PAGE_SIZE = 50
JOBBNORGE_DEFAULT_MAX_PAGES = 3
JOBBNORGE_DEFAULT_REQUEST_BUDGET = 12
JOBBNORGE_DEFAULT_JOB_BUDGET = 300
JOBBNORGE_DEFAULT_CYCLE_BYTES = 4 * 1024 * 1024


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


def _fingerprint(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _deadline(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    for pattern in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, pattern).date().isoformat()
        except ValueError:
            continue
    return None


def _public_url(value: Any) -> str | None:
    text = str(value or "").strip()[:2048]
    if not text:
        return None
    try:
        parsed = urlsplit(text)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or (parsed.hostname or "").casefold() not in {"jobbnorge.no", "www.jobbnorge.no"}
        or port not in {None, 443}
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    return text


def jobbnorge_extraction_batch(
    raw: bytes, capture: Mapping[str, Any], listing: Mapping[str, Any]
) -> ExtractionBatch:
    """Map one explicitly derived JobResultV1 item without inventing absent fields."""
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Jobbnorge derived listing capture must be a JSON object")
    metadata = capture.get("safe_metadata") or {}
    expected_id = str(metadata.get("sourceJobId") or listing.get("external_id") or "")
    observed_id = str(data.get("id") or "")
    if not observed_id or observed_id != expected_id:
        raise ValueError("Jobbnorge derived listing identity does not match its evidence link")
    collection_pointer = str(metadata.get("jsonPointer") or "/0")
    facts: list[FactCandidate] = []

    def add(
        fact_type: str,
        field: str,
        value: Any,
        *,
        namespace: str = "job",
        label: str | None = None,
        value_override: str | None = None,
    ) -> None:
        if value in (None, "", [], {}):
            return
        wording = (
            value if isinstance(value, str)
            else json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )
        text = str(value_override if value_override is not None else value)
        facts.append(FactCandidate(
            namespace=namespace,
            fact_type=fact_type,
            source_field=field,
            source_wording=str(wording)[:8000],
            value_type="text",
            value_text=text[:8000],
            label=label,
            confidence=0.995,
            evidence_locator={
                "kind": "collection_json_pointer",
                "collectionCaptureId": metadata.get("collectionCaptureId"),
                "collectionBlobSha256": metadata.get("collectionBlobSha256"),
                "itemIndex": int(metadata.get("itemIndex") or 0),
                "jsonPointer": f"{collection_pointer}/{field}",
                "sourceJobId": observed_id,
                "derivedCaptureId": capture["id"],
                "derivedRepresentation": True,
                "exactSourceBytes": False,
            },
        ))

    add("title", "title", data.get("title"))
    add("company", "employer", data.get("employer"))
    add("location_text", "location", data.get("location"))
    add("description", "summary", data.get("summary"))
    add("employment_fraction", "jobScope", data.get("jobScope"))
    add("contract_type", "jobDuration", data.get("jobDuration"))
    deadline = str(data.get("deadline") or "").strip()
    if deadline:
        normalized_deadline = deadline
        try:
            normalized_deadline = datetime.strptime(deadline, "%d.%m.%Y").date().isoformat()
        except ValueError:
            pass
        add("valid_through", "deadline", deadline, value_override=normalized_deadline)
    for field, label in (
        ("id", "Jobbnorge job id"),
        ("link", "Public listing URL"),
        ("postCode", "Post code"),
        ("positionCount", "Position count"),
        ("isJobListing", "Job listing flag"),
        ("promoted", "Promoted flag"),
        ("isInternal", "Internal listing flag"),
        ("logo", "Employer logo URL"),
    ):
        add("other", field, data.get(field), namespace="source", label=label)
    return ExtractionBatch(
        "json_structured", JOBBNORGE_STRUCTURED_EXTRACTOR_VERSION, tuple(facts)
    )


class JobbnorgeDiscoveryMatcher:
    version = JOBBNORGE_MATCHER_VERSION

    @staticmethod
    def profile_match(item: Mapping[str, Any], profile: Mapping[str, Any]) -> bool:
        title = str(item.get("title") or "")
        employer = str(item.get("employer") or "")
        location = str(item.get("location") or "")
        summary = str(item.get("summary") or "")
        scope = str(item.get("jobScope") or "")
        duration = str(item.get("jobDuration") or "")
        corpus = _fold(" ".join((title, employer, location, summary, scope, duration)))
        if any(_contains(corpus, term) for term in profile.get("exclude_keywords") or []):
            return False
        include = profile.get("include_keywords") or []
        role_terms = [
            term for term in re.split(r"[/,;|]", str(profile.get("role_intent") or ""))
            if len(_fold(term)) >= 3
        ]
        discovery_terms = [*include, *role_terms]
        if discovery_terms and title and summary and not any(
            _contains(corpus, term) for term in discovery_terms
        ):
            return False
        regions = profile.get("regions_cities") or []
        if regions and location and not any(_contains(location, term) for term in regions):
            return False
        # JobResultV1 has no country field. Country criteria therefore remain
        # uncertain and cannot safely reject an otherwise matching vacancy.
        for criterion, available in (
            ("work_models", ""),
            ("contract_hints", duration),
            ("schedule_hints", " ".join((scope, summary))),
            ("language_hints", summary),
            ("seniority_hints", " ".join((title, summary))),
        ):
            expected = profile.get(criterion) or []
            folded_available = _fold(available)
            if expected and folded_available and not any(
                _contains(folded_available, term) for term in expected
            ):
                return False
        return True

    def match(self, item: Mapping[str, Any], profiles: list[Mapping[str, Any]]) -> list[str]:
        return [
            str(profile["id"]) for profile in profiles if self.profile_match(item, profile)
        ]

    @staticmethod
    def query_plan(profiles: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
        plans: list[dict[str, Any]] = []
        seen: set[str] = set()
        for profile in profiles:
            include = [str(item).strip() for item in profile.get("include_keywords") or [] if str(item).strip()]
            role = str(profile.get("role_intent") or "").strip()
            term = (include[0] if include else re.split(r"[/,;|]", role)[0].strip())[:200]
            key = _fold(term)
            if key in seen:
                continue
            seen.add(key)
            plans.append({
                "term": term or None,
                "orderby": "Published",
                "period": "All",
                "abroad": False,
            })
        return plans or [{"term": None, "orderby": "Published", "period": "All", "abroad": False}]


class JobbnorgeCollectionCoordinator:
    def __init__(
        self,
        *,
        store: Any,
        archive: RawArchive,
        adapter: JobbnorgeSourceAdapter,
        matcher: JobbnorgeDiscoveryMatcher | None = None,
        page_size: int = JOBBNORGE_DEFAULT_PAGE_SIZE,
        max_pages: int = JOBBNORGE_DEFAULT_MAX_PAGES,
        job_budget: int = JOBBNORGE_DEFAULT_JOB_BUDGET,
        cycle_byte_budget: int = JOBBNORGE_DEFAULT_CYCLE_BYTES,
    ) -> None:
        self.store = store
        self.archive = archive
        self.adapter = adapter
        self.matcher = matcher or JobbnorgeDiscoveryMatcher()
        self.page_size = max(1, min(100, int(page_size)))
        self.max_pages = max(1, min(20, int(max_pages)))
        self.job_budget = max(1, min(2000, int(job_budget)))
        self.cycle_byte_budget = max(1024, min(32 * 1024 * 1024, int(cycle_byte_budget)))

    def _policy(self) -> dict[str, Any]:
        source = self.store.get_source(JOBBNORGE_SOURCE_ID)
        if not source:
            raise JobbnorgeSourceError("Jobbnorge source definition is missing", classification="internal")
        if not source.get("enabled") or source.get("operational_state") == "paused":
            raise JobbnorgeSourceError("Jobbnorge collection is paused", classification="policy_stop")
        backoff = source.get("backoff_until")
        if backoff and str(backoff) > _now():
            error = JobbnorgeSourceError(
                "Jobbnorge source is in persisted backoff", classification="rate_limit", retryable=True
            )
            try:
                target = datetime.fromisoformat(str(backoff).replace("Z", "+00:00"))
                error.retry_after_seconds = max(1.0, (target - datetime.now(timezone.utc)).total_seconds())
            except ValueError:
                pass
            raise error
        return source

    @staticmethod
    def _listing_values(item: Mapping[str, Any], *, observed_at: str) -> dict[str, Any]:
        external_id = str(item.get("id") or "").strip()
        if not external_id or not external_id.isdigit():
            raise JobbnorgeSourceError(
                "Jobbnorge result has no stable numeric id", classification="malformed_response"
            )
        deadline = _deadline(item.get("deadline"))
        expired = bool(deadline and deadline < date.today().isoformat())
        url = _public_url(item.get("link"))
        return {
            "source_id": JOBBNORGE_SOURCE_ID,
            "identity_key": "external:" + hashlib.sha256(external_id.encode("utf-8")).hexdigest(),
            "external_id": external_id,
            "canonical_url": url,
            "observed_url": url,
            "title_hint": str(item.get("title") or "").strip()[:500] or None,
            "company_hint": str(item.get("employer") or "").strip()[:500] or None,
            "location_hint": str(item.get("location") or "").strip()[:500] or None,
            "lifecycle_state": "expired" if expired else "active",
            "source_ended_at": observed_at if expired else None,
            "notes": (
                f"Observed via {JOBBNORGE_ADAPTER_VERSION}; matched by "
                f"{JOBBNORGE_MATCHER_VERSION}."
            ),
        }

    def _blob(self, raw: bytes) -> StoredBlob:
        digest = hashlib.sha256(raw).hexdigest()
        existing = self.store.get_raw_blob(digest)
        if existing:
            self.archive.read_verified(
                relative_path=existing["relative_path"], expected_hash=existing["sha256"],
                expected_size=int(existing["byte_size"]),
            )
            return StoredBlob(
                sha256=existing["sha256"], byte_size=int(existing["byte_size"]),
                mime_type=existing["mime_type"], file_extension=existing["file_extension"],
                relative_path=existing["relative_path"], created=False,
            )
        return self.archive.store(raw, mime_type="application/json", extension=".json")

    def _save_collection(
        self,
        response: JobbnorgeResponse | None,
        *,
        raw: bytes,
        request_path: str,
        query_fingerprint: str,
        page: int,
        observed_at: str,
        valid: bool,
        status_code: int | None,
        duration_ms: float | None,
        etag: str | None,
        last_modified: str | None,
    ) -> dict[str, Any]:
        blob = self._blob(raw)
        return self.store.save_collection_capture(
            source_id=JOBBNORGE_SOURCE_ID,
            blob={
                "sha256": blob.sha256, "byte_size": blob.byte_size,
                "mime_type": blob.mime_type, "file_extension": blob.file_extension,
                "relative_path": blob.relative_path,
            },
            capture={
                "operation_type": "jobs", "request_path": request_path,
                "query_fingerprint": query_fingerprint, "page_number": page,
                "http_status": status_code, "mime_type": "application/json",
                "response_bytes": len(raw), "duration_ms": duration_ms,
                "etag": etag, "last_modified": last_modified,
                "safe_metadata": {
                    "source": "jobbnorge", "adapterKey": self.adapter.key,
                    "adapterVersion": self.adapter.version, "exactHttpBody": True,
                    "responseValidated": valid,
                    "singleListingEndpointAvailable": False,
                },
            },
            captured_at=observed_at,
        )

    def _observe(
        self, *, request_path: str, started_at: str, status_code: int | None,
        duration_ms: float | None, response_bytes: int | None,
        classification: str | None, etag: str | None, last_modified: str | None,
    ) -> None:
        self.store.record_source_request({
            "source_id": JOBBNORGE_SOURCE_ID, "operation_type": "jobs",
            "request_path": request_path, "status_code": status_code,
            "started_at": started_at, "completed_at": _now(),
            "duration_ms": duration_ms, "response_bytes": response_bytes,
            "retry_classification": classification, "etag": etag,
            "last_modified": last_modified,
        })

    @staticmethod
    def _followup(
        *, cycle_id: str, query_index: int, page: int, delay: int,
        query_fingerprint: str,
    ) -> dict[str, Any]:
        return {
            "job_type": "jobbnorge_poll",
            "payload": {
                "source": "jobbnorge", "cycleId": cycle_id,
                "queryIndex": query_index, "page": page,
                "queryFingerprint": query_fingerprint,
            },
            "idempotency_key": f"jobbnorge-poll:{cycle_id}:{query_index}:{page}"[:500],
            "priority": 0, "max_attempts": 6, "next_attempt_at": _after(delay),
        }

    def poll(
        self,
        payload: Mapping[str, Any],
        *,
        cancelled: Callable[[], bool],
        progress: Callable[[str, float | None], None],
    ) -> dict[str, Any]:
        policy = self._policy()
        now = _now()
        profiles = self.store.enabled_source_profiles(JOBBNORGE_SOURCE_ID)
        plans = self.matcher.query_plan(profiles)
        query_fingerprint = _fingerprint({"plans": plans, "pageSize": self.page_size})
        cycle_id = str(payload.get("cycleId") or "cycle-" + hashlib.sha256(now.encode()).hexdigest()[:20])
        try:
            query_index = int(0 if payload.get("queryIndex") is None else payload.get("queryIndex"))
            page = int(1 if payload.get("page") is None else payload.get("page"))
        except (TypeError, ValueError) as exc:
            raise JobbnorgeSourceError(
                "Jobbnorge pagination state is invalid", classification="validation"
            ) from exc
        if query_index < 0 or query_index > len(plans) or page < 1 or page > self.max_pages:
            raise JobbnorgeSourceError(
                "Jobbnorge pagination state is outside the configured bounds",
                classification="validation",
            )
        payload_fingerprint = str(payload.get("queryFingerprint") or "")
        if payload_fingerprint and payload_fingerprint != query_fingerprint:
            # A Search Profile changed after this page was queued. Its page
            # cursor belongs to the old query plan, so restart conservatively.
            query_index, page = 0, 1
        state = self.store.get_query_sync_state(JOBBNORGE_SOURCE_ID) or {}
        new_cycle = state.get("cycle_id") != cycle_id or state.get("query_fingerprint") != query_fingerprint
        if new_cycle:
            state = self.store.update_query_sync_state(JOBBNORGE_SOURCE_ID, {
                "cycle_id": cycle_id, "query_fingerprint": query_fingerprint,
                "current_query_index": query_index, "current_page": page,
                "pages_fetched": 0, "requests_made": 0,
                "jobs_observed_cycle": 0, "response_bytes_cycle": 0,
                "query_count": len(plans), "cycle_started_at": now,
                "cycle_completed_at": None, "last_error_class": None,
                "last_error_message": None,
            }, now=now)
        elif (
            int(state.get("current_query_index") or 0) > query_index
            or (
                int(state.get("current_query_index") or 0) == query_index
                and int(state.get("current_page") or 1) > page
            )
        ):
            progress("query_checkpoint_already_advanced", 0.95)
            return {"staleCheckpoint": True, "followups": [self._followup(
                cycle_id=cycle_id,
                query_index=int(state.get("current_query_index") or 0),
                page=int(state.get("current_page") or 1), delay=0,
                query_fingerprint=query_fingerprint,
            )]}

        request_budget = min(
            JOBBNORGE_DEFAULT_REQUEST_BUDGET,
            max(1, int(policy.get("maximum_request_budget") or JOBBNORGE_DEFAULT_REQUEST_BUDGET)),
        )
        if query_index >= len(plans) or int(state.get("requests_made") or 0) >= request_budget:
            return self._complete_cycle(
                cycle_id, query_fingerprint, policy, state, now,
                reason="request_budget" if query_index < len(plans) else "queries_complete",
            )
        query = plans[query_index]
        request_path = self.adapter.jobs_path(query, page=page, results=self.page_size)
        started = now
        self.store.record_source_attempt(JOBBNORGE_SOURCE_ID, now=now)
        progress("polling_jobbnorge", 0.1)
        try:
            response = self.adapter.fetch_jobs(query, page=page, results=self.page_size)
        except Exception as exc:
            raw = getattr(exc, "raw", None)
            if isinstance(raw, bytes):
                self._save_collection(
                    None, raw=raw, request_path=str(getattr(exc, "request_path", request_path)),
                    query_fingerprint=query_fingerprint, page=page, observed_at=now,
                    valid=False, status_code=getattr(exc, "status_code", None),
                    duration_ms=getattr(exc, "duration_ms", None),
                    etag=getattr(exc, "etag", None),
                    last_modified=getattr(exc, "last_modified", None),
                )
            self._observe(
                request_path=str(getattr(exc, "request_path", request_path)), started_at=started,
                status_code=getattr(exc, "status_code", None),
                duration_ms=getattr(exc, "duration_ms", None),
                response_bytes=getattr(exc, "response_bytes", None),
                classification=str(getattr(exc, "classification", "internal")),
                etag=getattr(exc, "etag", None), last_modified=getattr(exc, "last_modified", None),
            )
            raise
        self._observe(
            request_path=response.request_path, started_at=started,
            status_code=response.status_code, duration_ms=response.duration_ms,
            response_bytes=response.response_bytes, classification=None,
            etag=response.etag, last_modified=response.last_modified,
        )
        collection = self._save_collection(
            response, raw=response.raw, request_path=response.request_path,
            query_fingerprint=query_fingerprint, page=page, observed_at=now,
            valid=True, status_code=response.status_code, duration_ms=response.duration_ms,
            etag=response.etag, last_modified=response.last_modified,
        )
        if cancelled():
            raise JobbnorgeSourceError("Jobbnorge job was cancelled", classification="cancelled")

        matched = 0
        derived_created = 0
        extraction_followups: list[dict[str, Any]] = []
        jobs_before = int(state.get("jobs_observed_cycle") or 0)
        for index, item in enumerate(response.items):
            if cancelled():
                raise JobbnorgeSourceError("Jobbnorge job was cancelled", classification="cancelled")
            if jobs_before + index >= self.job_budget:
                break
            listing_values = self._listing_values(item, observed_at=now)
            matched_ids = self.matcher.match(item, profiles)
            matched += int(bool(matched_ids))
            listing_result = self.store.upsert_source_listing(
                listing=listing_values, search_profile_ids=matched_ids, observed_at=now,
            )
            derived_capture_id = None
            if matched_ids:
                derived = json.dumps(
                    item, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                ).encode("utf-8")
                blob = self._blob(derived)
                capture_result = self.store.save_source_capture(
                    listing_id=listing_result["listing_id"],
                    blob={
                        "sha256": blob.sha256, "byte_size": blob.byte_size,
                        "mime_type": blob.mime_type, "file_extension": blob.file_extension,
                        "relative_path": blob.relative_path,
                    },
                    capture={
                        "input_method": "jobbnorge_api_derived",
                        "mime_type": "application/json", "file_extension": ".json",
                        "source_url": JOBBNORGE_BASE_URL + response.request_path,
                        "http_status": response.status_code,
                        "safe_metadata": {
                            "source": "jobbnorge", "adapterKey": self.adapter.key,
                            "adapterVersion": self.adapter.version,
                            "derivedRepresentation": True, "exactHttpBody": False,
                            "collectionCaptureId": collection["id"],
                            "collectionBlobSha256": collection["blob_sha256"],
                            "itemIndex": index, "jsonPointer": f"/{index}",
                            "sourceJobId": listing_values["external_id"],
                            "matcherVersion": self.matcher.version,
                        },
                    },
                    search_profile_ids=matched_ids, observed_at=now,
                )
                derived_capture_id = capture_result["capture"]["id"]
                if not capture_result["capture_reused"]:
                    derived_created += 1
                    extraction_followups.append({
                        "job_type": "extract_capture",
                        "payload": {"source": "jobbnorge", "captureId": derived_capture_id},
                        "idempotency_key": (
                            f"extract:{derived_capture_id}:{JOBBNORGE_STRUCTURED_EXTRACTOR_VERSION}"
                        ),
                        "priority": 5, "max_attempts": 3, "next_attempt_at": now,
                    })
            self.store.link_listing_collection_evidence(
                listing_id=listing_result["listing_id"],
                collection_capture_id=collection["id"], item_index=index,
                json_pointer=f"/{index}", external_id=listing_values["external_id"],
                derived_capture_id=derived_capture_id, linked_at=now,
            )
            progress("filtering_jobbnorge", min(0.8, 0.2 + ((index + 1) / max(1, len(response.items))) * 0.6))

        processed = min(len(response.items), max(0, self.job_budget - jobs_before))
        requests_made = int(state.get("requests_made") or 0) + 1
        pages_fetched = int(state.get("pages_fetched") or 0) + 1
        jobs_observed = jobs_before + processed
        byte_count = int(state.get("response_bytes_cycle") or 0) + response.response_bytes
        page_has_more = len(response.items) == self.page_size and page < self.max_pages
        bounded = (
            requests_made >= request_budget
            or jobs_observed >= self.job_budget
            or byte_count >= self.cycle_byte_budget
        )
        if page_has_more and not bounded:
            next_query, next_page = query_index, page + 1
        elif query_index + 1 < len(plans) and not bounded:
            next_query, next_page = query_index + 1, 1
        else:
            next_query, next_page = len(plans), 1
        stats = self.store.source_stats(JOBBNORGE_SOURCE_ID)
        previous_total = int(state.get("listings_observed") or 0)
        state = self.store.update_query_sync_state(JOBBNORGE_SOURCE_ID, {
            "current_query_index": next_query, "current_page": next_page,
            "pages_fetched": pages_fetched, "requests_made": requests_made,
            "jobs_observed_cycle": jobs_observed, "response_bytes_cycle": byte_count,
            "last_request_path": response.request_path,
            "last_collection_capture_id": collection["id"],
            "last_poll_at": now, "last_success_at": now,
            "last_error_class": None, "last_error_message": None,
            "listings_observed": previous_total + processed,
            "matched_listings": stats["matched"], "captures_created": stats["captures"],
        }, now=now)
        self.store.record_source_success(JOBBNORGE_SOURCE_ID, now=now)
        followups = extraction_followups
        if next_query < len(plans):
            followups.append(self._followup(
                cycle_id=cycle_id, query_index=next_query, page=next_page, delay=0,
                query_fingerprint=query_fingerprint,
            ))
        else:
            completion = self._complete_cycle(
                cycle_id, query_fingerprint, policy, state, now,
                reason="bounded" if bounded else "queries_complete",
            )
            followups.extend(completion.pop("followups"))
        progress("jobbnorge_page_complete", 0.95)
        return {
            "cycleId": cycle_id, "queryIndex": query_index, "page": page,
            "observed": processed, "matched": matched,
            "collectionCaptureId": collection["id"],
            "derivedCapturesCreated": derived_created,
            "nextQueryIndex": next_query, "nextPage": next_page,
            "bounded": bounded, "followups": followups,
        }

    def _complete_cycle(
        self, cycle_id: str, query_fingerprint: str, policy: Mapping[str, Any],
        state: Mapping[str, Any], now: str, *, reason: str,
    ) -> dict[str, Any]:
        self.store.update_query_sync_state(JOBBNORGE_SOURCE_ID, {
            "cycle_completed_at": now, "last_success_at": now,
            "last_error_class": None, "last_error_message": None,
        }, now=now)
        cadence = int(policy.get("polling_cadence_seconds") or JOBBNORGE_DEFAULT_POLL_SECONDS)
        next_cycle = "cycle-" + hashlib.sha256(f"{cycle_id}:{now}".encode()).hexdigest()[:20]
        return {
            "cycleId": cycle_id, "completed": True, "reason": reason,
            "requestsMade": int(state.get("requests_made") or 0),
            "jobsObserved": int(state.get("jobs_observed_cycle") or 0),
            "followups": [self._followup(
                cycle_id=next_cycle, query_index=0, page=1, delay=cadence,
                query_fingerprint=query_fingerprint,
            )],
        }


__all__ = [
    "JOBBNORGE_MATCHER_VERSION", "JobbnorgeCollectionCoordinator",
    "JobbnorgeDiscoveryMatcher", "jobbnorge_extraction_batch",
]
