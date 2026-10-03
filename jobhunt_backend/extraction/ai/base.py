"""Provider-neutral contracts for synchronous Job Hunt AI extraction."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol


@dataclass(frozen=True)
class AIExtractionRequest:
    system_prompt: str
    user_prompt: str
    response_schema: dict[str, Any]
    max_output_tokens: int


@dataclass(frozen=True)
class AIExtractionResponse:
    provider_key: str
    adapter_version: str
    model_id: str
    structured: dict[str, Any]
    raw_response: str
    request_id: str | None = None
    model_version: str | None = None
    finish_reason: str | None = None
    usage: dict[str, int] = field(default_factory=dict)
    latency_ms: float = 0.0


class AIProviderError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "ai_provider_error",
        classification: str = "provider_error",
        retryable: bool = False,
        status: int = 502,
        raw_response: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.classification = classification
        self.retryable = retryable
        self.status = status
        self.raw_response = raw_response


class AIExtractionProvider(Protocol):
    provider_key: str
    adapter_version: str
    model_id: str

    def health(self) -> dict[str, Any]: ...

    def extract_facts(self, request: AIExtractionRequest) -> AIExtractionResponse: ...


class UnavailableAIProvider:
    """Explicit disabled/invalid provider state; it never makes a network call."""

    adapter_version = "unavailable/v1"

    def __init__(
        self,
        *,
        provider_key: str = "none",
        model_id: str = "",
        reason: str = "provider_not_configured",
    ) -> None:
        self.provider_key = provider_key
        self.model_id = model_id
        self.reason = reason

    def health(self) -> dict[str, Any]:
        return {
            "provider": self.provider_key,
            "adapterVersion": self.adapter_version,
            "model": self.model_id or None,
            "state": "NOT_CONFIGURED",
            "configured": False,
            "reason": self.reason,
            "networkCheckPerformed": False,
            "automaticFallback": False,
        }

    def extract_facts(self, request: AIExtractionRequest) -> AIExtractionResponse:
        del request
        raise AIProviderError(
            "AI extraction provider is not configured",
            code="ai_provider_not_configured",
            classification="not_configured",
            status=503,
        )


def enabled(value: Any) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "yes", "on"}


def integer_setting(
    environment: Mapping[str, str],
    key: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    try:
        value = int(str(environment.get(key, default)).strip())
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def float_setting(
    environment: Mapping[str, str],
    key: str,
    default: float,
    *,
    minimum: float,
    maximum: float,
) -> float:
    try:
        value = float(str(environment.get(key, default)).strip())
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))

