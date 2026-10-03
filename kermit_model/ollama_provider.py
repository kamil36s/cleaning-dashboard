"""Fixed-endpoint Ollama adapter. No redirects, proxies or model-selected URLs."""

import http.client
import json
import socket
import time
from urllib.parse import urlsplit

from .provider import ModelResult, ProviderFailure
from .answer import MAX_ANSWER_CHARS, MAX_UNCERTAINTY


CONNECT_TIMEOUT = 3
GENERATION_TIMEOUT = 90
HEALTH_TIMEOUT = 3
MAX_RESPONSE_BYTES = 16000
MAX_HEALTH_BYTES = 32000
MAX_RETRIES = 1

DRAFT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "answer": {"type": "string", "minLength": 1, "maxLength": MAX_ANSWER_CHARS},
        "citedEvidenceIds": {"type": "array", "items": {"type": "string"}, "maxItems": 12, "uniqueItems": True},
        "uncertainty": {"type": "array", "items": {"type": "string", "maxLength": 500}, "maxItems": MAX_UNCERTAINTY},
        "conflictsMentioned": {"type": "array", "items": {"type": "string"}, "maxItems": 8, "uniqueItems": True},
    },
    "required": ["answer", "citedEvidenceIds", "uncertainty", "conflictsMentioned"],
}


class OllamaProvider:
    def _request(self, config, path, payload=None, *, health=False):
        parsed = urlsplit(config.base_url)
        connection_type = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
        connection = connection_type(parsed.hostname, parsed.port, timeout=CONNECT_TIMEOUT)
        started = time.monotonic()
        try:
            connection.connect()
            connection.sock.settimeout(HEALTH_TIMEOUT if health else GENERATION_TIMEOUT)
            body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
            connection.request("GET" if body is None else "POST", path, body=body,
                               headers={"Content-Type": "application/json", "Accept": "application/json", "Connection": "close"})
            active_socket = connection.sock
            response = connection.getresponse()
            limit = MAX_HEALTH_BYTES if health else MAX_RESPONSE_BYTES
            deadline = time.monotonic() + (HEALTH_TIMEOUT if health else GENERATION_TIMEOUT)
            parts = []
            size = 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ProviderFailure("provider response deadline exceeded", "provider_timeout")
                active_socket.settimeout(remaining)
                chunk = response.read1(min(4096, limit + 1 - size))
                if not chunk:
                    break
                parts.append(chunk)
                size += len(chunk)
                if size > limit:
                    raise ProviderFailure("provider response exceeded byte limit", "oversized_response")
            raw = b"".join(parts)
            if response.status in (429, 502, 503, 504):
                raise ProviderFailure("transient provider failure")
            if response.status != 200:
                raise ProviderFailure(f"provider HTTP {response.status}")
            try:
                data = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ProviderFailure("invalid provider JSON", "malformed_json") from exc
            if not isinstance(data, dict):
                raise ProviderFailure("invalid provider response shape")
            return data, int((time.monotonic() - started) * 1000)
        except (OSError, socket.timeout, http.client.HTTPException) as exc:
            category = "provider_timeout" if isinstance(exc, socket.timeout) else "transport_failure"
            raise ProviderFailure("provider connection or timeout failure", category) from exc
        finally:
            connection.close()

    def generate(self, messages, config):
        payload = {"model": config.model, "messages": list(messages), "stream": False,
                   "format": DRAFT_SCHEMA, "keep_alive": config.keep_alive,
                   "options": {"num_predict": config.max_output_tokens, "temperature": config.temperature}}
        if config.think is not None:
            payload["think"] = config.think
        for attempt in range(MAX_RETRIES + 1):
            try:
                data, latency = self._request(config, "/api/chat", payload)
                break
            except ProviderFailure as exc:
                if attempt >= MAX_RETRIES or (str(exc) != "transient provider failure" and exc.category != "transport_failure"):
                    raise
        content = data.get("message", {}).get("content") if isinstance(data.get("message"), dict) else None
        if not isinstance(content, str):
            raise ProviderFailure("provider omitted response text")
        usage = {key: data[key] for key in ("prompt_eval_count", "eval_count", "load_duration", "eval_duration") if isinstance(data.get(key), int)}
        return ModelResult(content, "ollama", config.model, latency,
                           "stop" if data.get("done_reason") == "stop" else str(data.get("done_reason", "unknown"))[:40], usage)

    def health(self, config):
        started = time.monotonic()
        try:
            tags, _ = self._request(config, "/api/tags", health=True)
            models = tags.get("models", [])
            if not isinstance(models, list):
                raise ProviderFailure("invalid model list")
            available = any(isinstance(m, dict) and config.model in (m.get("name"), m.get("model")) for m in models)
            if not available:
                return {"provider": "ollama", "state": "unavailable", "reachable": True,
                        "modelAvailable": False, "latencyMs": int((time.monotonic() - started) * 1000)}
            try:
                running, _ = self._request(config, "/api/ps", health=True)
            except ProviderFailure:
                running = {"models": []}
            loaded = any(isinstance(m, dict) and config.model in (m.get("name"), m.get("model")) for m in running.get("models", []))
            return {"provider": "ollama", "state": "ready" if loaded else "sleeping", "reachable": True,
                    "modelAvailable": True, "latencyMs": int((time.monotonic() - started) * 1000)}
        except ProviderFailure:
            return {"provider": "ollama", "state": "unavailable", "reachable": False,
                    "modelAvailable": False, "latencyMs": int((time.monotonic() - started) * 1000)}
