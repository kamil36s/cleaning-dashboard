"""Deterministic scripted AI provider for tests and local diagnostics."""

from __future__ import annotations

import json
from typing import Any

from .base import AIExtractionRequest, AIExtractionResponse, AIProviderError


class FakeAIExtractionProvider:
    provider_key = "fake"
    adapter_version = "deterministic-fake/v1"
    model_id = "fake-job-facts"

    def __init__(self, outcomes: list[Any] | None = None, *, configured: bool = True) -> None:
        self.outcomes = list(outcomes or [])
        self.configured = configured
        self.calls: list[AIExtractionRequest] = []

    def health(self) -> dict[str, Any]:
        return {
            "provider": self.provider_key, "adapterVersion": self.adapter_version,
            "model": self.model_id, "state": "AVAILABLE" if self.configured else "NOT_CONFIGURED",
            "configured": self.configured, "reason": None if self.configured else "fake_disabled",
            "networkCheckPerformed": False, "automaticFallback": False,
        }

    def extract_facts(self, request: AIExtractionRequest) -> AIExtractionResponse:
        self.calls.append(request)
        if not self.configured:
            raise AIProviderError("Fake provider is disabled", code="fake_not_configured", classification="not_configured", status=503)
        if not self.outcomes:
            raise AIProviderError("Fake provider has no scripted outcome", code="fake_exhausted", classification="permanent")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        if isinstance(outcome, str):
            raise AIProviderError(
                "Fake provider returned malformed JSON", code="fake_malformed_json",
                classification="malformed_response", status=422, raw_response=outcome,
            )
        if not isinstance(outcome, dict):
            raise AIProviderError("Fake provider returned an invalid response", code="fake_invalid_response", classification="malformed_response", status=422)
        raw = json.dumps(outcome, ensure_ascii=False, sort_keys=True)
        words = len(request.user_prompt.split())
        output_words = len(raw.split())
        return AIExtractionResponse(
            provider_key=self.provider_key, adapter_version=self.adapter_version,
            model_id=self.model_id, structured=outcome, raw_response=raw,
            request_id=f"fake-{len(self.calls)}", model_version=self.model_id,
            finish_reason="STOP", usage={
                "input_tokens": words, "output_tokens": output_words,
                "total_tokens": words + output_words, "cached_tokens": 0,
            }, latency_ms=0.0,
        )

