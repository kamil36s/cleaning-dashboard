"""Conservative adapter for Jobbnorge's unauthenticated official Public API."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import re
import socket
import time
from typing import Any, Mapping
import urllib.error
import urllib.request
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit


JOBBNORGE_SOURCE_KEY = "jobbnorge"
JOBBNORGE_SOURCE_ID = "source_jobbnorge"
JOBBNORGE_ADAPTER_KEY = "jobbnorge-public-api"
JOBBNORGE_ADAPTER_VERSION = "jobbnorge-public-api-v1@1"
JOBBNORGE_BASE_URL = "https://publicapi.jobbnorge.no"
JOBBNORGE_JOBS_PATH = "/v1/Jobs"
JOBBNORGE_STRUCTURED_EXTRACTOR_VERSION = "jobbnorge_structured@1"
JOBBNORGE_DEFAULT_TIMEOUT_SECONDS = 20.0
JOBBNORGE_MAX_RESPONSE_BYTES = 1024 * 1024
JOBBNORGE_MAX_ITEMS = 100
JOBBNORGE_MAX_JSON_DEPTH = 12
JOBBNORGE_MAX_STRING_LENGTH = 100_000

_JOBS_PATH = re.compile(r"^/v1/Jobs$")
_QUERY_KEYS = frozenset({
    "county", "municipality", "category", "employer", "department", "term",
    "orderby", "period", "results", "page", "abroad", "language",
})


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


class JobbnorgeSourceError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        classification: str,
        retryable: bool = False,
        status_code: int | None = None,
        retry_after_seconds: float | None = None,
        request_path: str | None = None,
        duration_ms: float | None = None,
        response_bytes: int | None = None,
        etag: str | None = None,
        last_modified: str | None = None,
        raw: bytes | None = None,
    ) -> None:
        super().__init__(message)
        self.classification = classification
        self.retryable = bool(retryable)
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds
        self.request_path = request_path
        self.duration_ms = duration_ms
        self.response_bytes = response_bytes
        self.etag = etag
        self.last_modified = last_modified
        self.raw = raw


@dataclass(frozen=True)
class JobbnorgeResponse:
    operation: str
    request_path: str
    status_code: int
    items: list[dict[str, Any]]
    raw: bytes
    etag: str | None
    last_modified: str | None
    duration_ms: float

    @property
    def response_bytes(self) -> int:
        return len(self.raw)


def _header(headers: Any, name: str) -> str | None:
    value = headers.get(name) if headers is not None and hasattr(headers, "get") else None
    text = str(value or "").strip()
    return text[:1000] or None


def _retry_after(headers: Any) -> float | None:
    value = _header(headers, "Retry-After")
    if not value:
        return None
    try:
        return max(0.0, min(86400.0, float(value)))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return max(0.0, min(86400.0, (parsed - datetime.now(timezone.utc)).total_seconds()))
        except (TypeError, ValueError, OverflowError):
            return None


def _validate_shape(value: Any, depth: int = 0) -> None:
    if depth > JOBBNORGE_MAX_JSON_DEPTH:
        raise ValueError("JSON nesting exceeds the configured limit")
    if isinstance(value, str):
        if len(value) > JOBBNORGE_MAX_STRING_LENGTH:
            raise ValueError("JSON string exceeds the configured limit")
        return
    if isinstance(value, dict):
        if len(value) > 100:
            raise ValueError("JSON object contains too many fields")
        for key, child in value.items():
            if not isinstance(key, str) or len(key) > 200:
                raise ValueError("JSON object key is invalid")
            _validate_shape(child, depth + 1)
    elif isinstance(value, list):
        if len(value) > JOBBNORGE_MAX_ITEMS:
            raise ValueError("JSON array contains too many jobs")
        for child in value:
            _validate_shape(child, depth + 1)


class JobbnorgeSourceAdapter:
    key = JOBBNORGE_ADAPTER_KEY
    version = JOBBNORGE_ADAPTER_VERSION
    source_key = JOBBNORGE_SOURCE_KEY
    base_url = JOBBNORGE_BASE_URL
    auth_required = False

    def __init__(
        self,
        *,
        opener: Any | None = None,
        timeout_seconds: float = JOBBNORGE_DEFAULT_TIMEOUT_SECONDS,
        max_response_bytes: int = JOBBNORGE_MAX_RESPONSE_BYTES,
    ) -> None:
        self.opener = opener or urllib.request.build_opener(_NoRedirect())
        self.timeout_seconds = max(1.0, min(120.0, float(timeout_seconds)))
        self.max_response_bytes = max(1024, min(8 * 1024 * 1024, int(max_response_bytes)))

    @classmethod
    def validate_path(cls, value: str) -> str:
        text = str(value or "").strip()
        try:
            parsed = urlsplit(cls.base_url + text if text.startswith("/") else text)
            port = parsed.port
        except ValueError as exc:
            raise JobbnorgeSourceError(
                "Jobbnorge request URL is invalid", classification="validation"
            ) from exc
        decoded_path = unquote(parsed.path)
        if (
            parsed.scheme != "https"
            or (parsed.hostname or "").casefold() != "publicapi.jobbnorge.no"
            or port not in {None, 443}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or not _JOBS_PATH.fullmatch(parsed.path)
            or decoded_path != parsed.path
        ):
            raise JobbnorgeSourceError(
                "Jobbnorge request URL is outside the allowlist", classification="validation"
            )
        pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=False)
        if len(pairs) > 30 or any(key not in _QUERY_KEYS for key, _ in pairs):
            raise JobbnorgeSourceError(
                "Jobbnorge request query is outside the allowlist", classification="validation"
            )
        if len(parsed.query) > 2000:
            raise JobbnorgeSourceError(
                "Jobbnorge request query is too long", classification="validation"
            )
        return parsed.path + (f"?{parsed.query}" if parsed.query else "")

    @staticmethod
    def jobs_path(query: Mapping[str, Any], *, page: int, results: int) -> str:
        if page < 1 or page > 10_000 or results < 1 or results > JOBBNORGE_MAX_ITEMS:
            raise JobbnorgeSourceError(
                "Jobbnorge pagination is outside the configured bounds",
                classification="validation",
            )
        values: list[tuple[str, str]] = []
        for key in ("county", "municipality", "category", "employer", "department"):
            raw = query.get(key)
            if raw is None:
                continue
            for item in raw if isinstance(raw, list) else [raw]:
                values.append((key, str(int(item))))
        term = str(query.get("term") or "").strip()
        if term:
            values.append(("term", term[:200]))
        orderby = str(query.get("orderby") or "Published")
        period = str(query.get("period") or "All")
        if orderby not in {"Published", "Deadline", "Employer"} or period not in {"Day", "Week", "All"}:
            raise JobbnorgeSourceError("Jobbnorge query enum is invalid", classification="validation")
        values.extend((
            ("orderby", orderby), ("period", period),
            ("results", str(results)), ("page", str(page)),
        ))
        if query.get("abroad") is not None:
            values.append(("abroad", "true" if bool(query["abroad"]) else "false"))
        return JobbnorgeSourceAdapter.validate_path(JOBBNORGE_JOBS_PATH + "?" + urlencode(values))

    @staticmethod
    def _classification(status: int) -> tuple[str, bool]:
        if status == 401:
            return "authentication", False
        if status == 403:
            return "forbidden", False
        if status == 429:
            return "rate_limit", True
        if status in {408, 500, 502, 503, 504}:
            return "transient_server", True
        if 300 <= status < 400:
            return "unexpected_redirect", False
        return "validation", False

    def _open(self, request: urllib.request.Request):
        if hasattr(self.opener, "open"):
            return self.opener.open(request, timeout=self.timeout_seconds)
        return self.opener(request, timeout=self.timeout_seconds)

    def fetch_jobs(
        self, query: Mapping[str, Any], *, page: int, results: int
    ) -> JobbnorgeResponse:
        path = self.jobs_path(query, page=page, results=results)
        request = urllib.request.Request(
            self.base_url + path,
            headers={"Accept": "application/json", "User-Agent": "cleaning-dashboard-jobhunt/1"},
            method="GET",
        )
        started = time.perf_counter()
        response_headers: Any = None
        raw: bytes | None = None
        try:
            with self._open(request) as response:
                response_headers = response.headers
                status = int(getattr(response, "status", None) or response.getcode())
                raw = response.read(self.max_response_bytes + 1)
        except urllib.error.HTTPError as exc:
            duration = round((time.perf_counter() - started) * 1000, 3)
            response_headers = exc.headers
            try:
                raw = exc.read(self.max_response_bytes + 1)
            except Exception:
                raw = None
            classification, retryable = self._classification(int(exc.code))
            raise JobbnorgeSourceError(
                f"Jobbnorge request failed with HTTP {int(exc.code)}",
                classification=classification,
                retryable=retryable,
                status_code=int(exc.code),
                retry_after_seconds=_retry_after(response_headers),
                request_path=path,
                duration_ms=duration,
                response_bytes=None if raw is None else len(raw),
                etag=_header(response_headers, "ETag"),
                last_modified=_header(response_headers, "Last-Modified"),
                raw=raw if raw is not None and len(raw) <= self.max_response_bytes else None,
            ) from None
        except (TimeoutError, socket.timeout) as exc:
            raise JobbnorgeSourceError(
                "Jobbnorge request timed out", classification="timeout", retryable=True,
                request_path=path,
                duration_ms=round((time.perf_counter() - started) * 1000, 3),
            ) from exc
        except (urllib.error.URLError, OSError) as exc:
            raise JobbnorgeSourceError(
                "Jobbnorge network request failed", classification="network", retryable=True,
                request_path=path,
                duration_ms=round((time.perf_counter() - started) * 1000, 3),
            ) from exc
        duration = round((time.perf_counter() - started) * 1000, 3)
        if status != 200:
            classification, retryable = self._classification(status)
            raise JobbnorgeSourceError(
                f"Jobbnorge request failed with HTTP {status}", classification=classification,
                retryable=retryable, status_code=status, request_path=path,
                duration_ms=duration, response_bytes=len(raw or b""), raw=raw,
            )
        if raw is None or len(raw) > self.max_response_bytes:
            raise JobbnorgeSourceError(
                "Jobbnorge response exceeded the configured byte limit",
                classification="oversized_response", status_code=status,
                request_path=path, duration_ms=duration,
                response_bytes=0 if raw is None else len(raw),
            )
        try:
            payload = json.loads(raw.decode("utf-8"))
            _validate_shape(payload)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise JobbnorgeSourceError(
                "Jobbnorge returned malformed or out-of-bounds JSON",
                classification="malformed_response", status_code=status,
                request_path=path, duration_ms=duration, response_bytes=len(raw), raw=raw,
                etag=_header(response_headers, "ETag"),
                last_modified=_header(response_headers, "Last-Modified"),
            ) from exc
        if not isinstance(payload, list) or any(not isinstance(item, dict) for item in payload):
            raise JobbnorgeSourceError(
                "Jobbnorge Jobs response is not an array of objects",
                classification="malformed_response", status_code=status,
                request_path=path, duration_ms=duration, response_bytes=len(raw), raw=raw,
            )
        return JobbnorgeResponse(
            "jobs", path, status, payload, raw,
            _header(response_headers, "ETag"), _header(response_headers, "Last-Modified"), duration,
        )


__all__ = [
    "JOBBNORGE_ADAPTER_KEY", "JOBBNORGE_ADAPTER_VERSION", "JOBBNORGE_BASE_URL",
    "JOBBNORGE_JOBS_PATH", "JOBBNORGE_SOURCE_ID", "JOBBNORGE_STRUCTURED_EXTRACTOR_VERSION",
    "JobbnorgeResponse", "JobbnorgeSourceAdapter", "JobbnorgeSourceError",
]
