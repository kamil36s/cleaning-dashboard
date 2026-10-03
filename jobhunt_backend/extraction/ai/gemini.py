"""Fixed-endpoint Gemini adapter for schema-constrained Job Hunt extraction."""

from __future__ import annotations

import json
import os
import socket
import time
from typing import Any, Mapping
import urllib.error
import urllib.request

from .base import AIExtractionRequest, AIExtractionResponse, AIProviderError, enabled


GEMINI_PROVIDER_KEY = "gemini"
GEMINI_ADAPTER_VERSION = "google-gemini-generate-content/v1"
GEMINI_DEFAULT_MODEL = "gemini-3.8-flash"
GEMINI_ALLOWED_MODELS = frozenset({GEMINI_DEFAULT_MODEL})
MAX_PROVIDER_RESPONSE_BYTES = 512 * 1024
MAX_PROVIDER_PROMPT_BYTES = 128 * 1024


class GeminiAIExtractionProvider:
    provider_key = GEMINI_PROVIDER_KEY
    adapter_version = GEMINI_ADAPTER_VERSION

    def __init__(
        self,
        *,
        environment: Mapping[str, str] | None = None,
        opener: Any | None = None,
        timeout_seconds: float = 45.0,
    ) -> None:
        self.environment = environment if environment is not None else os.environ
        self.model_id = str(self.environment.get("JOBHUNT_AI_MODEL") or GEMINI_DEFAULT_MODEL).strip()
        self.opener = opener or urllib.request.build_opener()
        self.timeout_seconds = max(1.0, min(120.0, float(timeout_seconds)))

    @property
    def endpoint(self) -> str:
        return f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_id}:generateContent"

    def _state(self) -> tuple[str, str | None]:
        if not enabled(self.environment.get("JOBHUNT_AI_ENABLED")):
            return "NOT_CONFIGURED", "AI_DISABLED"
        if str(self.environment.get("JOBHUNT_AI_PROVIDER") or GEMINI_PROVIDER_KEY).strip().casefold() != GEMINI_PROVIDER_KEY:
            return "NOT_CONFIGURED", "PROVIDER_NOT_SUPPORTED"
        if self.model_id not in GEMINI_ALLOWED_MODELS:
            return "MODEL_UNAVAILABLE", "MODEL_NOT_ALLOWLISTED"
        if not str(self.environment.get("GEMINI_API_KEY") or "").strip():
            return "NOT_CONFIGURED", "API_KEY_MISSING"
        return "CONFIGURED", None

    def health(self) -> dict[str, Any]:
        state, reason = self._state()
        return {
            "provider": self.provider_key, "adapterVersion": self.adapter_version,
            "model": self.model_id, "state": state,
            "configured": state == "CONFIGURED", "reason": reason,
            "networkCheckPerformed": False, "automaticFallback": False,
        }

    def _api_key(self) -> str:
        state, _reason = self._state()
        if state != "CONFIGURED":
            raise AIProviderError(
                "Gemini AI extraction is not configured", code="ai_provider_not_configured",
                classification="not_configured", status=503,
            )
        return str(self.environment.get("GEMINI_API_KEY") or "").strip()

    @staticmethod
    def _usage(value: Any) -> dict[str, int]:
        value = value if isinstance(value, dict) else {}
        mapping = {
            "promptTokenCount": "input_tokens", "candidatesTokenCount": "output_tokens",
            "totalTokenCount": "total_tokens", "cachedContentTokenCount": "cached_tokens",
        }
        return {
            target: int(value[source])
            for source, target in mapping.items()
            if isinstance(value.get(source), int) and not isinstance(value[source], bool) and value[source] >= 0
        }

    @staticmethod
    def _http_error(status: int, raw: bytes) -> AIProviderError:
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = {}
        error = payload.get("error") if isinstance(payload, dict) else {}
        message = str((error or {}).get("message") or "")[:500]
        if status in {401, 403}:
            return AIProviderError("Gemini authentication failed", code="gemini_auth_error", classification="authentication", status=503)
        if status == 404:
            return AIProviderError("Configured Gemini model is unavailable", code="gemini_model_unavailable", classification="unsupported_model", status=503)
        if status == 429:
            return AIProviderError("Gemini rate limit or quota was reached", code="gemini_rate_limited", classification="rate_limit", retryable=True, status=429)
        if status in {408, 500, 502, 503, 504}:
            return AIProviderError("Gemini is temporarily unavailable", code="gemini_unavailable", classification="transient", retryable=True, status=502)
        return AIProviderError(
            "Gemini rejected the extraction request" + (f": {message}" if message else ""),
            code="gemini_provider_error", classification="permanent", status=502,
        )

    def extract_facts(self, request: AIExtractionRequest) -> AIExtractionResponse:
        api_key = self._api_key()
        prompt_bytes = len(request.system_prompt.encode("utf-8")) + len(request.user_prompt.encode("utf-8"))
        if prompt_bytes > MAX_PROVIDER_PROMPT_BYTES:
            raise AIProviderError("AI prompt exceeds the provider limit", code="ai_prompt_too_large", classification="input_too_large", status=413)
        body = json.dumps({
            "systemInstruction": {"parts": [{"text": request.system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": request.user_prompt}]}],
            "generationConfig": {
                "maxOutputTokens": max(256, min(8192, int(request.max_output_tokens))),
                "responseMimeType": "application/json",
                "responseJsonSchema": request.response_schema,
            },
        }, ensure_ascii=False).encode("utf-8")
        http_request = urllib.request.Request(
            self.endpoint, data=body,
            headers={"Content-Type": "application/json", "Accept": "application/json", "x-goog-api-key": api_key},
            method="POST",
        )
        started = time.perf_counter()
        try:
            with self.opener.open(http_request, timeout=self.timeout_seconds) as response:
                raw = response.read(MAX_PROVIDER_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            raise self._http_error(int(exc.code), exc.read(MAX_PROVIDER_RESPONSE_BYTES + 1)) from None
        except (TimeoutError, socket.timeout) as exc:
            raise AIProviderError("Gemini request timed out", code="gemini_timeout", classification="timeout", retryable=True, status=504) from exc
        except (urllib.error.URLError, OSError) as exc:
            raise AIProviderError("Gemini network request failed", code="gemini_network_error", classification="network", retryable=True, status=502) from exc
        latency_ms = round((time.perf_counter() - started) * 1000, 3)
        if len(raw) > MAX_PROVIDER_RESPONSE_BYTES:
            raise AIProviderError("Gemini response exceeded the configured limit", code="gemini_response_too_large", classification="response_too_large")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AIProviderError("Gemini returned malformed JSON", code="gemini_malformed_response", classification="malformed_response", raw_response=raw[:4096].decode("utf-8", "replace")) from exc
        candidates = payload.get("candidates") if isinstance(payload, dict) else None
        candidate = candidates[0] if isinstance(candidates, list) and candidates and isinstance(candidates[0], dict) else None
        if not candidate:
            raise AIProviderError("Gemini returned no candidate", code="gemini_incomplete", classification="incomplete", status=422, raw_response=json.dumps(payload, ensure_ascii=False)[:4096])
        finish_reason = str(candidate.get("finishReason") or "") or None
        parts = ((candidate.get("content") or {}).get("parts") or [])
        text = "".join(str(part.get("text") or "") for part in parts if isinstance(part, dict)).strip()
        if finish_reason not in {None, "STOP"}:
            raise AIProviderError("Gemini completion was incomplete", code="gemini_incomplete", classification="incomplete", status=422, raw_response=text[:4096])
        try:
            structured = json.loads(text)
        except json.JSONDecodeError as exc:
            raise AIProviderError("Gemini returned malformed structured output", code="gemini_malformed_output", classification="malformed_response", status=422, raw_response=text[:4096]) from exc
        if not isinstance(structured, dict):
            raise AIProviderError("Gemini returned an invalid structured output", code="gemini_malformed_output", classification="malformed_response", status=422, raw_response=text[:4096])
        return AIExtractionResponse(
            provider_key=self.provider_key, adapter_version=self.adapter_version,
            model_id=self.model_id, structured=structured, raw_response=text,
            request_id=str(payload.get("responseId") or "") or None,
            model_version=str(payload.get("modelVersion") or "") or None,
            finish_reason=finish_reason, usage=self._usage(payload.get("usageMetadata")),
            latency_ms=latency_ms,
        )

