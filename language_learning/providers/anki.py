"""Narrow, local-only AnkiConnect HTTP adapter.

This module knows the wire protocol and response validation only.  Domain ownership,
links, hashes, conflicts, and knowledge evidence belong to AnkiSyncService.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import socket
from typing import Any
import urllib.error
import urllib.parse
import urllib.request


DEFAULT_ENDPOINT = "http://127.0.0.1:8765"
MIN_API_VERSION = 6
READ_ACTIONS = frozenset({
    "version", "deckNames", "modelNames", "modelFieldNames", "findNotes",
    "notesInfo", "findCards", "cardsInfo", "canAddNotes", "getDeckStats",
    "getDeckConfig", "cardReviews",
})
WRITE_ACTIONS = frozenset({"addNote", "addNotes", "createDeck", "storeMediaFile",
                           "updateNoteFields", "addTags", "removeTags", "sync"})


class AnkiAdapterError(RuntimeError):
    def __init__(self, message: str, *, code: str, state: str = "HTTP_ERROR") -> None:
        super().__init__(message)
        self.code = code
        self.state = state


class AnkiUnavailableError(AnkiAdapterError):
    def __init__(self, message: str = "AnkiConnect is unavailable") -> None:
        super().__init__(message, code="anki_unavailable", state="UNAVAILABLE")


class AnkiTimeoutError(AnkiAdapterError):
    def __init__(self, message: str = "AnkiConnect timed out") -> None:
        super().__init__(message, code="anki_timeout", state="UNAVAILABLE")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def validate_local_endpoint(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Anki endpoint must be a non-empty local HTTP URL")
    parsed = urllib.parse.urlsplit(value.strip())
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "::1"}:
        raise ValueError("Anki endpoint must use HTTP on the loopback address")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Anki endpoint cannot contain credentials, query, or fragment")
    if parsed.path not in {"", "/"}:
        raise ValueError("Anki endpoint cannot contain a path")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Anki endpoint port is invalid") from exc
    if port is None or not 1 <= port <= 65535:
        raise ValueError("Anki endpoint requires a valid port")
    host = "[::1]" if parsed.hostname == "::1" else "127.0.0.1"
    return f"http://{host}:{port}"


@dataclass(frozen=True)
class AnkiCapabilities:
    version: int

    def api(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "minimumVersion": MIN_API_VERSION,
            "supported": self.version >= MIN_API_VERSION,
            "readActions": sorted(READ_ACTIONS),
            "writeActions": sorted(WRITE_ACTIONS),
            "reviewHistory": True,
        }


class AnkiAdapter:
    """Validated AnkiConnect calls to one allowlisted loopback endpoint."""

    def __init__(
        self,
        endpoint: str = DEFAULT_ENDPOINT,
        *,
        api_key: str | None = None,
        timeout_seconds: float = 3.0,
        opener: Any | None = None,
    ) -> None:
        self.endpoint = validate_local_endpoint(endpoint)
        self.api_key = api_key or None
        self.timeout_seconds = max(0.1, min(float(timeout_seconds), 30.0))
        self._opener = opener or urllib.request.build_opener(_NoRedirect())

    def invoke(self, action: str, params: dict[str, Any] | None = None) -> Any:
        if action not in READ_ACTIONS | WRITE_ACTIONS:
            raise AnkiAdapterError("Unsupported AnkiConnect action", code="anki_action_unsupported")
        payload: dict[str, Any] = {"action": action, "version": MIN_API_VERSION, "params": params or {}}
        if self.api_key:
            payload["key"] = self.api_key
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self._opener.open(request, timeout=self.timeout_seconds) as response:
                if int(getattr(response, "status", 200)) != 200:
                    raise AnkiAdapterError("AnkiConnect returned an HTTP error", code="anki_http_error")
                body = response.read(4 * 1024 * 1024 + 1)
        except urllib.error.HTTPError as exc:
            raise AnkiAdapterError(
                f"AnkiConnect returned HTTP {exc.code}", code="anki_http_error", state="HTTP_ERROR"
            ) from exc
        except (TimeoutError, socket.timeout) as exc:
            raise AnkiTimeoutError() from exc
        except (urllib.error.URLError, ConnectionError, OSError) as exc:
            raise AnkiUnavailableError() from exc
        if len(body) > 4 * 1024 * 1024:
            raise AnkiAdapterError("AnkiConnect response is too large", code="anki_response_too_large")
        try:
            envelope = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AnkiAdapterError("AnkiConnect returned invalid JSON", code="anki_invalid_response") from exc
        if not isinstance(envelope, dict) or "result" not in envelope or "error" not in envelope:
            raise AnkiAdapterError("AnkiConnect returned an invalid response", code="anki_invalid_response")
        if envelope["error"] is not None:
            message = str(envelope["error"])
            code = "anki_api_key_rejected" if "key" in message.casefold() else "anki_action_failed"
            raise AnkiAdapterError(message[:500], code=code)
        return envelope["result"]

    def capabilities(self) -> AnkiCapabilities:
        version = self.invoke("version")
        if isinstance(version, bool) or not isinstance(version, int):
            raise AnkiAdapterError("AnkiConnect version is invalid", code="anki_invalid_response")
        return AnkiCapabilities(version=version)

    def deck_names(self) -> list[str]:
        result = self.invoke("deckNames")
        if not isinstance(result, list) or any(not isinstance(item, str) for item in result):
            raise AnkiAdapterError("Anki deck list is invalid", code="anki_invalid_response")
        return result

    def deck_stats(self, deck_name: str) -> dict[str, int]:
        result = self.invoke("getDeckStats", {"decks": [deck_name]})
        if result == {}:
            return {"new": 0, "learn": 0, "due": 0}
        if not isinstance(result, dict) or len(result) != 1:
            raise AnkiAdapterError("Anki deck statistics are unavailable", code="anki_invalid_response")
        stats = next(iter(result.values()))
        if not isinstance(stats, dict):
            raise AnkiAdapterError("Anki deck statistics are invalid", code="anki_invalid_response")
        counts = {}
        for output_key, source_key in (("new", "new_count"), ("learn", "learn_count"), ("due", "review_count")):
            value = stats.get(source_key)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise AnkiAdapterError("Anki deck statistics are invalid", code="anki_invalid_response")
            counts[output_key] = value
        return counts

    def deck_config(self, deck_name: str) -> dict[str, Any]:
        result = self.invoke("getDeckConfig", {"deck": deck_name})
        if not isinstance(result, dict):
            raise AnkiAdapterError("Anki deck options are invalid", code="anki_invalid_response")
        return result

    def card_reviews(self, deck_name: str, start_id: int = 0) -> list[list[int]]:
        result = self.invoke("cardReviews", {"deck": deck_name, "startID": start_id})
        if not isinstance(result, list) or any(
            not isinstance(row, list) or len(row) != 9 or
            any(isinstance(value, bool) or not isinstance(value, int) for value in row)
            for row in result
        ):
            raise AnkiAdapterError("Anki review history is invalid", code="anki_invalid_response")
        return result

    def sync_web(self) -> None:
        result = self.invoke("sync")
        if result is not None:
            raise AnkiAdapterError("Anki sync returned an unexpected response", code="anki_invalid_response")

    def model_names(self) -> list[str]:
        result = self.invoke("modelNames")
        if not isinstance(result, list) or any(not isinstance(item, str) for item in result):
            raise AnkiAdapterError("Anki model list is invalid", code="anki_invalid_response")
        return result

    def model_field_names(self, model_name: str) -> list[str]:
        result = self.invoke("modelFieldNames", {"modelName": model_name})
        if not isinstance(result, list) or any(not isinstance(item, str) for item in result):
            raise AnkiAdapterError("Anki model field list is invalid", code="anki_invalid_response")
        return result

    def find_notes(self, query: str) -> list[int]:
        result = self.invoke("findNotes", {"query": query})
        if not isinstance(result, list) or any(isinstance(item, bool) or not isinstance(item, int) for item in result):
            raise AnkiAdapterError("Anki note search response is invalid", code="anki_invalid_response")
        return result

    def notes_info(self, note_ids: list[int]) -> list[dict[str, Any]]:
        result = self.invoke("notesInfo", {"notes": note_ids})
        if not isinstance(result, list) or any(not isinstance(item, dict) for item in result):
            raise AnkiAdapterError("Anki note response is invalid", code="anki_invalid_response")
        return result

    def find_cards(self, query: str) -> list[int]:
        result = self.invoke("findCards", {"query": query})
        if not isinstance(result, list) or any(isinstance(item, bool) or not isinstance(item, int) for item in result):
            raise AnkiAdapterError("Anki card search response is invalid", code="anki_invalid_response")
        return result

    def cards_info(self, card_ids: list[int]) -> list[dict[str, Any]]:
        result = self.invoke("cardsInfo", {"cards": card_ids})
        if not isinstance(result, list) or any(not isinstance(item, dict) for item in result):
            raise AnkiAdapterError("Anki card response is invalid", code="anki_invalid_response")
        return result

    def can_add_note(self, note: dict[str, Any]) -> bool:
        result = self.invoke("canAddNotes", {"notes": [note]})
        if not isinstance(result, list) or len(result) != 1 or not isinstance(result[0], bool):
            raise AnkiAdapterError("Anki duplicate preflight response is invalid", code="anki_invalid_response")
        return result[0]

    def add_note(self, note: dict[str, Any]) -> int:
        result = self.invoke("addNote", {"note": note})
        if isinstance(result, bool) or not isinstance(result, int):
            raise AnkiAdapterError("Anki note creation response is invalid", code="anki_invalid_response")
        return result

    def update_note_fields(self, note_id: int, fields: dict[str, str]) -> None:
        result = self.invoke("updateNoteFields", {"note": {"id": note_id, "fields": fields}})
        if result is not None:
            raise AnkiAdapterError("Anki note update response is invalid", code="anki_invalid_response")

    def add_tags(self, note_ids: list[int], tags: list[str]) -> None:
        result = self.invoke("addTags", {"notes": note_ids, "tags": " ".join(tags)})
        if result is not None:
            raise AnkiAdapterError("Anki tag update response is invalid", code="anki_invalid_response")

    def remove_tags(self, note_ids: list[int], tags: list[str]) -> None:
        result = self.invoke("removeTags", {"notes": note_ids, "tags": " ".join(tags)})
        if result is not None:
            raise AnkiAdapterError("Anki tag removal response is invalid", code="anki_invalid_response")

    def create_deck(self, name: str) -> int:
        result = self.invoke("createDeck", {"deck": name})
        if isinstance(result, bool) or not isinstance(result, int):
            raise AnkiAdapterError("Anki deck creation response is invalid", code="anki_invalid_response")
        return result

    def store_media_file(self, filename: str, data: str) -> str:
        result = self.invoke("storeMediaFile", {"filename": filename, "data": data})
        if not isinstance(result, str) or not result:
            raise AnkiAdapterError("Anki media response is invalid", code="anki_invalid_response")
        return result

    def can_add_notes(self, notes: list[dict[str, Any]]) -> list[bool]:
        result = self.invoke("canAddNotes", {"notes": notes})
        if not isinstance(result, list) or len(result) != len(notes) or any(not isinstance(item, bool) for item in result):
            raise AnkiAdapterError("Anki duplicate preflight response is invalid", code="anki_invalid_response")
        return result

    def add_notes(self, notes: list[dict[str, Any]]) -> list[int | None]:
        result = self.invoke("addNotes", {"notes": notes})
        if not isinstance(result, list) or len(result) != len(notes) or any(
            item is not None and (isinstance(item, bool) or not isinstance(item, int)) for item in result
        ):
            raise AnkiAdapterError("Anki note batch response is invalid", code="anki_invalid_response")
        return result


__all__ = [
    "AnkiAdapter", "AnkiAdapterError", "AnkiCapabilities", "AnkiTimeoutError",
    "AnkiUnavailableError", "DEFAULT_ENDPOINT", "MIN_API_VERSION", "validate_local_endpoint",
]
