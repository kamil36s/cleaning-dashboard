"""Bounded server-side generation providers for Language Phase 8."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
import socket
import time
from typing import Any, Mapping, Protocol
import urllib.error
import urllib.request


GEMINI_PROVIDER_ID = "GEMINI"
GEMINI_ADAPTER_VERSION = "google-gemini-generate-content/v1"
GEMINI_MODEL_ID = "gemini-3.8-flash"
GEMINI_PROVIDER_POLICY = "FREE_ONLY"
GEMINI_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL_ID}:generateContent"
)
MAX_PROVIDER_RESPONSE_BYTES = 512 * 1024
MAX_PROVIDER_PROMPT_BYTES = 128 * 1024
MAX_TRANSPORT_ATTEMPTS = 2
_RETRYABLE_HTTP = {408, 500, 502, 503, 504}


class GenerationProviderError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "generation_provider_error",
        state: str = "PROVIDER_ERROR",
        retryable: bool = False,
        status: int = 502,
        transport_attempts: int = 1,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.state = state
        self.retryable = retryable
        self.status = status
        self.transport_attempts = transport_attempts


@dataclass(frozen=True)
class ProviderResult:
    provider_id: str
    adapter_version: str
    model_id: str
    text: str
    structured: dict[str, Any]
    request_id: str | None = None
    model_version: str | None = None
    finish_reason: str | None = None
    usage_metadata: dict[str, int] = field(default_factory=dict)
    latency_ms: float = 0.0
    status: str = "SUCCESS"
    transport_attempts: int = 1


class GenerationProvider(Protocol):
    provider_id: str
    adapter_version: str
    model_id: str
    policy: str

    def health(self) -> dict[str, Any]: ...
    def generate(self, *, prompt: str, max_output_tokens: int) -> ProviderResult: ...


class GeminiGenerationProvider:
    """Direct fixed-endpoint adapter with explicit FREE_ONLY configuration."""

    provider_id = GEMINI_PROVIDER_ID
    adapter_version = GEMINI_ADAPTER_VERSION
    model_id = GEMINI_MODEL_ID
    policy = GEMINI_PROVIDER_POLICY

    def __init__(
        self,
        *,
        environment: Mapping[str, str] | None = None,
        opener: Any | None = None,
        timeout_seconds: float = 45.0,
    ) -> None:
        self.environment = environment if environment is not None else os.environ
        self.opener = opener or urllib.request.build_opener()
        self.timeout_seconds = max(1.0, min(120.0, float(timeout_seconds)))
        self._runtime_state: str | None = None

    @staticmethod
    def _enabled(value: Any) -> bool:
        return str(value or "").strip().casefold() in {"1", "true", "yes", "on"}

    def _configuration_state(self) -> tuple[str, str | None]:
        if not self._enabled(self.environment.get("LANGUAGE_GEMINI_ENABLED")):
            return "NOT_CONFIGURED", "AUTOMATIC_PROVIDER_DISABLED"
        if str(self.environment.get("LANGUAGE_GEMINI_MODE") or GEMINI_PROVIDER_POLICY).strip().upper() != GEMINI_PROVIDER_POLICY:
            return "PROVIDER_ERROR", "FREE_ONLY_MODE_REQUIRED"
        configured_model = str(self.environment.get("LANGUAGE_GEMINI_MODEL") or GEMINI_MODEL_ID).strip()
        if configured_model != GEMINI_MODEL_ID:
            return "MODEL_UNAVAILABLE", "MODEL_NOT_ALLOWLISTED"
        if not str(self.environment.get("GEMINI_API_KEY") or "").strip():
            return "NOT_CONFIGURED", "API_KEY_MISSING"
        return "CONFIGURED", None

    def health(self) -> dict[str, Any]:
        state, reason = self._configuration_state()
        if state == "CONFIGURED" and self._runtime_state:
            state = self._runtime_state
        return {
            "providerId": self.provider_id,
            "adapterVersion": self.adapter_version,
            "modelId": self.model_id,
            "policy": self.policy,
            "state": state,
            "configured": state not in {"NOT_CONFIGURED", "PROVIDER_ERROR", "MODEL_UNAVAILABLE"},
            "reason": reason,
            "healthCheckNetworkCall": False,
            "automaticFallback": False,
            "paidFallback": False,
        }

    def _require_configured(self) -> str:
        state, reason = self._configuration_state()
        if state != "CONFIGURED":
            raise GenerationProviderError(
                "Gemini automatic generation is not configured for FREE_ONLY use",
                code="gemini_not_configured",
                state=state,
                status=503,
            )
        return str(self.environment.get("GEMINI_API_KEY") or "").strip()

    @staticmethod
    def _safe_usage(value: Any) -> dict[str, int]:
        if not isinstance(value, dict):
            return {}
        allowed = {
            "promptTokenCount", "candidatesTokenCount", "totalTokenCount",
            "cachedContentTokenCount", "thoughtsTokenCount", "toolUsePromptTokenCount",
        }
        return {
            key: int(item)
            for key, item in value.items()
            if key in allowed and isinstance(item, int) and not isinstance(item, bool) and item >= 0
        }

    @staticmethod
    def _http_error(status: int, body: bytes) -> GenerationProviderError:
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = {}
        error = payload.get("error") if isinstance(payload, dict) else {}
        code = str((error or {}).get("status") or (error or {}).get("code") or "").upper()
        message = str((error or {}).get("message") or "")[:1000]
        lowered = f"{code} {message}".casefold()
        if status in {401, 403}:
            return GenerationProviderError("Gemini authentication failed", code="gemini_auth_error", state="AUTH_ERROR", status=503)
        if status == 404:
            return GenerationProviderError("The configured Gemini model is unavailable", code="gemini_model_unavailable", state="MODEL_UNAVAILABLE", status=503)
        if status == 429:
            if any(marker in lowered for marker in ("rate limit", "rate_limit", "rpm", "tpm", "too many")) and not any(marker in lowered for marker in ("daily", "quota", "rpd")):
                return GenerationProviderError("Gemini Free Tier rate limit reached", code="gemini_rate_limited", state="RATE_LIMITED", status=429)
            return GenerationProviderError("Gemini Free Tier quota is exhausted", code="gemini_free_quota_exhausted", state="FREE_QUOTA_EXHAUSTED", status=429)
        if status in _RETRYABLE_HTTP:
            return GenerationProviderError("Gemini is temporarily unavailable", code="gemini_provider_unavailable", state="NETWORK_ERROR", retryable=True, status=502)
        return GenerationProviderError("Gemini rejected the generation request", code="gemini_provider_error", state="PROVIDER_ERROR", status=502)

    def _request_once(self, api_key: str, prompt: str, max_output_tokens: int) -> tuple[dict[str, Any], float]:
        body = json.dumps({
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "maxOutputTokens": max_output_tokens,
                "responseMimeType": "application/json",
                "responseJsonSchema": {
                    "type": "object",
                    "properties": {"title": {"type": "string"}, "text": {"type": "string"}},
                    "required": ["title", "text"],
                    "additionalProperties": False,
                },
            },
        }, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            GEMINI_ENDPOINT,
            data=body,
            headers={"Content-Type": "application/json", "Accept": "application/json", "x-goog-api-key": api_key},
            method="POST",
        )
        started = time.perf_counter()
        try:
            with self.opener.open(request, timeout=self.timeout_seconds) as response:
                raw = response.read(MAX_PROVIDER_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            raw = exc.read(MAX_PROVIDER_RESPONSE_BYTES + 1)
            raise self._http_error(int(exc.code), raw) from None
        except (TimeoutError, socket.timeout) as exc:
            raise GenerationProviderError("Gemini request timed out", code="gemini_timeout", state="NETWORK_ERROR", retryable=True, status=504) from exc
        except (urllib.error.URLError, OSError) as exc:
            raise GenerationProviderError("Gemini network request failed", code="gemini_network_error", state="NETWORK_ERROR", retryable=True, status=502) from exc
        latency_ms = round((time.perf_counter() - started) * 1000, 3)
        if len(raw) > MAX_PROVIDER_RESPONSE_BYTES:
            raise GenerationProviderError("Gemini response exceeded the configured limit", code="gemini_response_too_large", state="PROVIDER_ERROR", status=502)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GenerationProviderError("Gemini returned malformed JSON", code="gemini_malformed_response", state="PROVIDER_ERROR", status=502) from exc
        if not isinstance(payload, dict):
            raise GenerationProviderError("Gemini returned an invalid response", code="gemini_malformed_response", state="PROVIDER_ERROR", status=502)
        return payload, latency_ms

    def generate(self, *, prompt: str, max_output_tokens: int) -> ProviderResult:
        api_key = self._require_configured()
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt.encode("utf-8")) > MAX_PROVIDER_PROMPT_BYTES:
            raise GenerationProviderError("Generation prompt is invalid or too large", code="generation_prompt_too_large", state="PROVIDER_ERROR", status=400)
        max_output_tokens = max(256, min(8192, int(max_output_tokens)))
        payload: dict[str, Any] | None = None
        latency_ms = 0.0
        last_error: GenerationProviderError | None = None
        for transport_attempt in range(1, MAX_TRANSPORT_ATTEMPTS + 1):
            try:
                payload, latency = self._request_once(api_key, prompt, max_output_tokens)
                latency_ms += latency
                break
            except GenerationProviderError as exc:
                last_error = exc
                if not exc.retryable or transport_attempt >= MAX_TRANSPORT_ATTEMPTS:
                    exc.transport_attempts = transport_attempt
                    self._runtime_state = exc.state
                    raise
                time.sleep(0.2 * transport_attempt)
        if payload is None:
            assert last_error is not None
            raise last_error

        candidates = payload.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            self._runtime_state = "PROVIDER_ERROR"
            raise GenerationProviderError("Gemini refused the request", code="gemini_provider_refusal", state="PROVIDER_ERROR", status=422)
        candidate = candidates[0] if isinstance(candidates[0], dict) else {}
        finish_reason = str(candidate.get("finishReason") or "") or None
        if finish_reason not in {None, "STOP"}:
            self._runtime_state = "PROVIDER_ERROR"
            raise GenerationProviderError("Gemini did not return a usable completion", code="gemini_provider_refusal", state="PROVIDER_ERROR", status=422)
        parts = ((candidate.get("content") or {}).get("parts") or []) if isinstance(candidate, dict) else []
        text = "".join(str(part.get("text") or "") for part in parts if isinstance(part, dict)).strip()
        try:
            structured = json.loads(text)
        except json.JSONDecodeError as exc:
            raise GenerationProviderError("Gemini returned malformed structured output", code="gemini_malformed_output", state="PROVIDER_ERROR", status=422) from exc
        if not isinstance(structured, dict) or not isinstance(structured.get("title"), str) or not isinstance(structured.get("text"), str):
            raise GenerationProviderError("Gemini returned malformed structured output", code="gemini_malformed_output", state="PROVIDER_ERROR", status=422)
        self._runtime_state = "AVAILABLE"
        return ProviderResult(
            provider_id=self.provider_id,
            adapter_version=self.adapter_version,
            model_id=self.model_id,
            text=text,
            structured=structured,
            request_id=str(payload.get("responseId") or "") or None,
            model_version=str(payload.get("modelVersion") or "") or None,
            finish_reason=finish_reason,
            usage_metadata=self._safe_usage(payload.get("usageMetadata")),
            latency_ms=latency_ms,
            transport_attempts=transport_attempt,
        )


class FakeGenerationProvider:
    """Deterministic scripted provider used by tests and isolated browser fixtures."""

    provider_id = "FAKE"
    adapter_version = "deterministic-fake/v1"
    model_id = "fake-bokmal"
    policy = GEMINI_PROVIDER_POLICY

    def __init__(self, outcomes: list[Any], *, health_state: str = "AVAILABLE") -> None:
        self.outcomes = list(outcomes)
        self.health_state = health_state
        self.calls: list[dict[str, Any]] = []

    def health(self) -> dict[str, Any]:
        return {
            "providerId": self.provider_id, "adapterVersion": self.adapter_version,
            "modelId": self.model_id, "policy": self.policy, "state": self.health_state,
            "configured": self.health_state in {"CONFIGURED", "AVAILABLE"},
            "healthCheckNetworkCall": False, "automaticFallback": False, "paidFallback": False,
        }

    def generate(self, *, prompt: str, max_output_tokens: int) -> ProviderResult:
        self.calls.append({"prompt": prompt, "maxOutputTokens": max_output_tokens})
        if not self.outcomes:
            raise GenerationProviderError("Fake provider has no scripted outcome", code="fake_exhausted", state="PROVIDER_ERROR")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        if isinstance(outcome, ProviderResult):
            return outcome
        if not isinstance(outcome, dict):
            raise GenerationProviderError("Fake provider returned malformed output", code="gemini_malformed_output", state="PROVIDER_ERROR", status=422)
        structured = dict(outcome)
        raw = json.dumps(structured, ensure_ascii=False)
        return ProviderResult(
            provider_id=self.provider_id, adapter_version=self.adapter_version,
            model_id=self.model_id, text=raw, structured=structured,
            request_id=f"fake-{len(self.calls)}", model_version=self.model_id,
            finish_reason="STOP", usage_metadata={"totalTokenCount": len(raw.split())},
            latency_ms=0.0, transport_attempts=1,
        )


__all__ = [
    "GEMINI_ADAPTER_VERSION", "GEMINI_ENDPOINT", "GEMINI_MODEL_ID",
    "GEMINI_PROVIDER_ID", "GEMINI_PROVIDER_POLICY", "MAX_PROVIDER_PROMPT_BYTES",
    "MAX_PROVIDER_RESPONSE_BYTES", "MAX_TRANSPORT_ATTEMPTS", "FakeGenerationProvider",
    "GenerationProvider", "GenerationProviderError", "GeminiGenerationProvider", "ProviderResult",
]
