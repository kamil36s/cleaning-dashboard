"""Conservative adapter for NAV's authenticated ``pam-stilling-feed`` API."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import os
import re
import socket
import time
from typing import Any, Mapping
import urllib.error
import urllib.request
from urllib.parse import unquote, urljoin, urlsplit


NAV_SOURCE_KEY = "nav"
NAV_SOURCE_ID = "source_nav"
NAV_ADAPTER_KEY = "nav-pam-stilling-feed"
NAV_ADAPTER_VERSION = "pam-stilling-feed@1"
NAV_BASE_URL = "https://pam-stilling-feed.nav.no"
NAV_INITIAL_FEED_PATH = "/api/v1/feed"
NAV_DEFAULT_TIMEOUT_SECONDS = 20.0
NAV_MAX_FEED_BYTES = 2 * 1024 * 1024
NAV_MAX_DETAIL_BYTES = 2 * 1024 * 1024
NAV_MAX_FEED_ITEMS = 2000
NAV_MAX_JSON_DEPTH = 32

_FEED_PATH = re.compile(r"^/api/v1/feed(?:/[A-Za-z0-9._~%-]+)?$")
_DETAIL_PATH = re.compile(r"^/api/v1/feedentry/[A-Za-z0-9._~%-]+$")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


class NavSourceError(RuntimeError):
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


@dataclass(frozen=True)
class NavResponse:
    operation: str
    request_path: str
    status_code: int
    payload: dict[str, Any] | None
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


def _json_depth(value: Any, depth: int = 0) -> int:
    if depth > NAV_MAX_JSON_DEPTH:
        return depth
    if isinstance(value, dict):
        return max([depth, *(_json_depth(item, depth + 1) for item in value.values())])
    if isinstance(value, list):
        return max([depth, *(_json_depth(item, depth + 1) for item in value)])
    return depth


class NavSourceAdapter:
    key = NAV_ADAPTER_KEY
    version = NAV_ADAPTER_VERSION
    source_key = NAV_SOURCE_KEY
    base_url = NAV_BASE_URL

    def __init__(
        self,
        *,
        environment: Mapping[str, str] | None = None,
        opener: Any | None = None,
        timeout_seconds: float = NAV_DEFAULT_TIMEOUT_SECONDS,
        max_feed_bytes: int = NAV_MAX_FEED_BYTES,
        max_detail_bytes: int = NAV_MAX_DETAIL_BYTES,
    ) -> None:
        self.environment = environment if environment is not None else os.environ
        self.opener = opener or urllib.request.build_opener(_NoRedirect())
        self.timeout_seconds = max(1.0, min(120.0, float(timeout_seconds)))
        self.max_feed_bytes = max(1024, min(8 * 1024 * 1024, int(max_feed_bytes)))
        self.max_detail_bytes = max(1024, min(8 * 1024 * 1024, int(max_detail_bytes)))

    @property
    def token_configured(self) -> bool:
        return bool(str(self.environment.get("JOBHUNT_NAV_TOKEN") or "").strip())

    def _token(self) -> str:
        token = str(self.environment.get("JOBHUNT_NAV_TOKEN") or "").strip()
        if not token:
            raise NavSourceError(
                "NAV token is not configured",
                classification="authentication",
                request_path=NAV_INITIAL_FEED_PATH,
            )
        return token

    @classmethod
    def validate_path(cls, value: str, *, operation: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise NavSourceError("NAV request path is missing", classification="validation")
        absolute = urljoin(cls.base_url + "/", text)
        try:
            parsed = urlsplit(absolute)
            port = parsed.port
        except ValueError as exc:
            raise NavSourceError("NAV request URL is invalid", classification="validation") from exc
        if (
            parsed.scheme != "https"
            or (parsed.hostname or "").casefold() != "pam-stilling-feed.nav.no"
            or port not in {None, 443}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise NavSourceError("NAV request URL is outside the allowlist", classification="validation")
        expected = _FEED_PATH if operation == "feed" else _DETAIL_PATH
        decoded_path = unquote(parsed.path)
        if (
            not expected.fullmatch(parsed.path)
            or not expected.fullmatch(decoded_path)
            or decoded_path != parsed.path
            or len(parsed.query) > 1000
        ):
            raise NavSourceError("NAV request path is outside the allowlist", classification="validation")
        return parsed.path + (f"?{parsed.query}" if parsed.query else "")

    @staticmethod
    def _classification(status: int) -> tuple[str, bool]:
        if status == 401:
            return "authentication", False
        if status == 403:
            return "forbidden", False
        if status == 404:
            return "permanent_not_found", False
        if status == 429:
            return "rate_limit", True
        if status in {408, 500, 502, 503, 504}:
            return "transient_server", True
        if 300 <= status < 400:
            return "validation", False
        return "validation", False

    def _open(self, request: urllib.request.Request):
        if hasattr(self.opener, "open"):
            return self.opener.open(request, timeout=self.timeout_seconds)
        return self.opener(request, timeout=self.timeout_seconds)

    def _request_json(
        self,
        path: str,
        *,
        operation: str,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> NavResponse:
        safe_path = self.validate_path(path, operation=operation)
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._token()}",
        }
        if etag:
            headers["If-None-Match"] = str(etag)[:1000]
        if last_modified:
            headers["If-Modified-Since"] = str(last_modified)[:1000]
        request = urllib.request.Request(self.base_url + safe_path, headers=headers, method="GET")
        limit = self.max_feed_bytes if operation == "feed" else self.max_detail_bytes
        started = time.perf_counter()
        response_headers: Any = None
        try:
            with self._open(request) as response:
                response_headers = response.headers
                status = int(getattr(response, "status", None) or response.getcode())
                raw = response.read(limit + 1)
        except urllib.error.HTTPError as exc:
            duration = round((time.perf_counter() - started) * 1000, 3)
            response_headers = exc.headers
            if int(exc.code) == 304:
                return NavResponse(
                    operation, safe_path, 304, None, b"", _header(response_headers, "ETag"),
                    _header(response_headers, "Last-Modified"), duration,
                )
            classification, retryable = self._classification(int(exc.code))
            raise NavSourceError(
                f"NAV request failed with HTTP {int(exc.code)}",
                classification=classification,
                retryable=retryable,
                status_code=int(exc.code),
                retry_after_seconds=_retry_after(response_headers),
                request_path=safe_path,
                duration_ms=duration,
                response_bytes=None,
                etag=_header(response_headers, "ETag"),
                last_modified=_header(response_headers, "Last-Modified"),
            ) from None
        except (TimeoutError, socket.timeout) as exc:
            raise NavSourceError(
                "NAV request timed out", classification="timeout", retryable=True,
                request_path=safe_path,
                duration_ms=round((time.perf_counter() - started) * 1000, 3),
            ) from exc
        except (urllib.error.URLError, OSError) as exc:
            raise NavSourceError(
                "NAV network request failed", classification="network", retryable=True,
                request_path=safe_path,
                duration_ms=round((time.perf_counter() - started) * 1000, 3),
            ) from exc
        duration = round((time.perf_counter() - started) * 1000, 3)
        if status != 200:
            classification, retryable = self._classification(status)
            raise NavSourceError(
                f"NAV request failed with HTTP {status}", classification=classification,
                retryable=retryable, status_code=status, request_path=safe_path,
                duration_ms=duration, response_bytes=len(raw),
                etag=_header(response_headers, "ETag"),
                last_modified=_header(response_headers, "Last-Modified"),
            )
        if len(raw) > limit:
            raise NavSourceError(
                "NAV response exceeded the configured byte limit",
                classification="validation", status_code=status, request_path=safe_path,
                duration_ms=duration, response_bytes=len(raw),
            )
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise NavSourceError(
                "NAV returned malformed JSON", classification="malformed_response",
                status_code=status, request_path=safe_path, duration_ms=duration,
                response_bytes=len(raw),
            ) from exc
        if not isinstance(payload, dict) or _json_depth(payload) > NAV_MAX_JSON_DEPTH:
            raise NavSourceError(
                "NAV returned an invalid or over-nested JSON object",
                classification="malformed_response", status_code=status,
                request_path=safe_path, duration_ms=duration, response_bytes=len(raw),
            )
        return NavResponse(
            operation, safe_path, status, payload, raw, _header(response_headers, "ETag"),
            _header(response_headers, "Last-Modified"), duration,
        )

    def poll_feed(self, state: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, Any]:
        del policy
        path = str(state.get("feed_path") or NAV_INITIAL_FEED_PATH)
        response = self._request_json(
            path,
            operation="feed",
            etag=state.get("etag"),
            last_modified=state.get("last_modified") or state.get("bootstrap_if_modified_since"),
        )
        if response.status_code == 304:
            return {"not_modified": True, "response": response, "items": [], "next_path": None}
        payload = response.payload or {}
        items = payload.get("items")
        if not isinstance(items, list) or len(items) > NAV_MAX_FEED_ITEMS:
            raise NavSourceError(
                "NAV feed items are missing or exceed the configured limit",
                classification="malformed_response", status_code=200,
                request_path=response.request_path, duration_ms=response.duration_ms,
                response_bytes=response.response_bytes,
            )
        if any(not isinstance(item, dict) for item in items):
            raise NavSourceError(
                "NAV feed contains an invalid item", classification="malformed_response",
                status_code=200, request_path=response.request_path,
                duration_ms=response.duration_ms, response_bytes=response.response_bytes,
            )
        next_value = payload.get("next_url")
        next_path = self.validate_path(next_value, operation="feed") if next_value else None
        return {
            "not_modified": False,
            "response": response,
            "items": items,
            "next_path": next_path,
            "page_id": str(payload.get("id") or "") or None,
            "next_id": str(payload.get("next_id") or "") or None,
            "feed_version": str(payload.get("version") or "")[:200] or None,
        }

    def fetch_listing(self, identity: Mapping[str, Any], policy: Mapping[str, Any]) -> NavResponse:
        del policy
        path = str(identity.get("detail_path") or identity.get("url") or "")
        response = self._request_json(path, operation="detail")
        if response.payload is None:
            raise NavSourceError(
                "NAV listing detail was not returned", classification="malformed_response",
                request_path=response.request_path,
            )
        return response

    @staticmethod
    def feed_header(item: Mapping[str, Any]) -> dict[str, Any]:
        entry = item.get("_feed_entry")
        if not isinstance(entry, dict):
            raise NavSourceError("NAV feed entry metadata is missing", classification="malformed_response")
        external_id = str(entry.get("uuid") or "").strip()
        status = str(entry.get("status") or "").strip().upper()
        entry_id = str(item.get("id") or "").strip()
        detail_path = str(item.get("url") or "").strip()
        if not external_id or not entry_id or status not in {"ACTIVE", "INACTIVE"}:
            raise NavSourceError("NAV feed entry identity or status is invalid", classification="malformed_response")
        safe_detail_path = NavSourceAdapter.validate_path(detail_path, operation="detail")
        return {
            "entry_id": entry_id,
            "external_id": external_id,
            "status": status,
            "title": str(entry.get("title") or item.get("title") or "").strip()[:500] or None,
            "company": str(entry.get("businessName") or "").strip()[:500] or None,
            "municipality": str(entry.get("municipal") or "").strip()[:500] or None,
            "modified_at": str(entry.get("sistEndret") or item.get("date_modified") or "").strip()[:100] or None,
            "detail_path": safe_detail_path,
        }


__all__ = [
    "NAV_ADAPTER_KEY",
    "NAV_ADAPTER_VERSION",
    "NAV_BASE_URL",
    "NAV_INITIAL_FEED_PATH",
    "NAV_SOURCE_ID",
    "NavResponse",
    "NavSourceAdapter",
    "NavSourceError",
]
