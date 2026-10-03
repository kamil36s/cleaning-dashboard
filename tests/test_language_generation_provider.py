from __future__ import annotations

import io
import json
import socket
import tempfile
import time
import unittest
import urllib.error
from pathlib import Path

from language_learning.providers.generation import (
    GEMINI_ENDPOINT,
    FakeGenerationProvider,
    GenerationProviderError,
    GeminiGenerationProvider,
)
from language_learning.jobs import LanguageJobManager
from language_learning.service import LanguageService
from language_learning.store import LanguageStore
from tests.language_phase2_fakes import FakeAnalyzer, FakeFrequencyProvider, registry_for


class _Response:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size=-1):
        return self.payload[:size] if size >= 0 else self.payload


class _Opener:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return _Response(outcome)


def _gemini_payload(title="Arbeid", text="jobb"):
    return {
        "candidates": [{
            "finishReason": "STOP",
            "content": {"parts": [{"text": json.dumps({"title": title, "text": text})}]},
        }],
        "responseId": "response-safe-id",
        "modelVersion": "gemini-3.8-flash-001",
        "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 3, "totalTokenCount": 13},
    }


class GeminiGenerationProviderTests(unittest.TestCase):
    def environment(self):
        return {
            "LANGUAGE_GEMINI_ENABLED": "true",
            "LANGUAGE_GEMINI_MODE": "FREE_ONLY",
            "LANGUAGE_GEMINI_MODEL": "gemini-3.8-flash",
            "GEMINI_API_KEY": "test-secret-never-return",
        }

    def test_fixed_endpoint_structured_payload_and_redacted_health(self):
        opener = _Opener([_gemini_payload()])
        provider = GeminiGenerationProvider(environment=self.environment(), opener=opener)
        result = provider.generate(prompt="Skriv naturlig Bokmål", max_output_tokens=900)
        request, timeout = opener.requests[0]
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(request.full_url, GEMINI_ENDPOINT)
        self.assertEqual(request.headers["X-goog-api-key"], "test-secret-never-return")
        self.assertEqual(body["generationConfig"]["responseMimeType"], "application/json")
        self.assertEqual(body["generationConfig"]["responseJsonSchema"]["required"], ["title", "text"])
        self.assertNotIn("temperature", body["generationConfig"])
        self.assertEqual(result.structured, {"title": "Arbeid", "text": "jobb"})
        self.assertEqual(result.usage_metadata["totalTokenCount"], 13)
        self.assertNotIn("test-secret", json.dumps(provider.health()))
        self.assertEqual(timeout, 45.0)

    def test_free_only_and_model_allowlist_are_fail_closed(self):
        cases = [
            ({**self.environment(), "LANGUAGE_GEMINI_MODE": "PAID"}, "PROVIDER_ERROR"),
            ({**self.environment(), "LANGUAGE_GEMINI_MODEL": "gemini-other"}, "MODEL_UNAVAILABLE"),
            ({**self.environment(), "GEMINI_API_KEY": ""}, "NOT_CONFIGURED"),
        ]
        for environment, state in cases:
            with self.subTest(state=state):
                provider = GeminiGenerationProvider(environment=environment, opener=_Opener([]))
                self.assertEqual(provider.health()["state"], state)
                with self.assertRaises(GenerationProviderError):
                    provider.generate(prompt="valid", max_output_tokens=256)

    def test_429_quota_and_rate_states_are_not_retried(self):
        for message, expected in (
            ("Daily RPD quota exceeded", "FREE_QUOTA_EXHAUSTED"),
            ("Rate limit RPM exceeded", "RATE_LIMITED"),
        ):
            body = json.dumps({"error": {"status": "RESOURCE_EXHAUSTED", "message": message}}).encode()
            error = urllib.error.HTTPError(GEMINI_ENDPOINT, 429, "limited", {}, io.BytesIO(body))
            opener = _Opener([error])
            with self.subTest(expected=expected), self.assertRaises(GenerationProviderError) as caught:
                GeminiGenerationProvider(environment=self.environment(), opener=opener).generate(
                    prompt="valid", max_output_tokens=256,
                )
            self.assertEqual(caught.exception.state, expected)
            self.assertEqual(len(opener.requests), 1)

    def test_timeout_retries_once_then_stops(self):
        opener = _Opener([socket.timeout(), socket.timeout()])
        with self.assertRaises(GenerationProviderError) as caught:
            GeminiGenerationProvider(environment=self.environment(), opener=opener).generate(
                prompt="valid", max_output_tokens=256,
            )
        self.assertEqual(caught.exception.code, "gemini_timeout")
        self.assertEqual(caught.exception.transport_attempts, 2)
        self.assertEqual(len(opener.requests), 2)

    def test_refusal_and_malformed_output_are_explicit(self):
        for payload, code in (
            ({"candidates": []}, "gemini_provider_refusal"),
            ({"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "not-json"}]}}]}, "gemini_malformed_output"),
        ):
            with self.subTest(code=code), self.assertRaises(GenerationProviderError) as caught:
                GeminiGenerationProvider(environment=self.environment(), opener=_Opener([payload])).generate(
                    prompt="valid", max_output_tokens=256,
                )
            self.assertEqual(caught.exception.code, code)


class AutomaticGenerationLoopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp.cleanup()

    def service_with(self, outcomes):
        provider = FakeGenerationProvider(outcomes)
        service = LanguageService(
            LanguageStore(Path(self.temp.name) / "language.sqlite"),
            analyzer_registry=registry_for(FakeAnalyzer()),
            frequency_provider=FakeFrequencyProvider(),
            generation_provider=provider,
        )
        service.initialize()
        profile = service.ensure_bokmal_profile()["profile"]
        known = service.upsert_lemma(profile["id"], "jobb", part_of_speech="NOUN")["lemma"]
        service.update_knowledge(known["id"], {"knowledgeStatus": "KNOWN"})
        weak = service.upsert_lemma(profile["id"], "svak", part_of_speech="ADJ")["lemma"]
        service.update_knowledge(weak["id"], {"knowledgeStatus": "LEARNING", "recognition": 1})
        request = service.create_generation_request(profile["id"], {
            "generationMode": "AUTOMATIC", "length": 200, "difficultyPreset": "BALANCED",
            "explicitTargetLemmaIds": [known["id"]],
        })["data"]["request"]
        return service, provider, request

    @staticmethod
    def passing_text():
        return ("jobb " * 19) + "svak"

    def test_first_attempt_passes_locally_and_is_not_autoaccepted(self):
        service, provider, request = self.service_with([{"title": "Arbeid", "text": self.passing_text(), "coverage": 1}])
        service.generation_service.run_automatic(request["id"])
        saved = service.get_generation_request(request["id"])["data"]["request"]
        candidates = service.list_generation_candidates(request["id"])["data"]["items"]
        self.assertEqual(saved["automaticStatus"], "READY")
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(candidates[0]["analysis"]["actualTokenCoveragePercent"], 95.0)
        self.assertEqual(candidates[0]["status"], "IN_TOLERANCE")
        self.assertIsNone(candidates[0]["acceptedTextDocumentId"])

    def test_explicit_acceptance_creates_generated_gemini_reader_text_only_then(self):
        service, _provider, request = self.service_with([{"title": "Arbeid", "text": self.passing_text()}])
        service.generation_service.run_automatic(request["id"])
        candidate = service.list_generation_candidates(request["id"])["data"]["items"][0]
        manager = LanguageJobManager(service, poll_interval=0.01)
        try:
            accepted = service.accept_generation_candidate(candidate["id"], {})["data"]
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                job = service.get_analysis_job(accepted["job"]["id"])["data"]["job"]
                if job["state"] not in {"QUEUED", "RUNNING"}:
                    break
                time.sleep(0.01)
            self.assertTrue(accepted["created"])
            self.assertEqual(accepted["document"]["sourceType"], "GENERATED_GEMINI")
            self.assertEqual(job["state"], "COMPLETED")
            with service.store.connection() as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM exposure_events").fetchone()[0], 0)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM gamification_awards").fetchone()[0], 0)
        finally:
            manager.stop()

    def test_miss_then_revision_pass_uses_measured_issues(self):
        service, provider, request = self.service_with([
            {"title": "Svakt", "text": "svak ukjent"},
            {"title": "Arbeid", "text": self.passing_text()},
        ])
        service.generation_service.run_automatic(request["id"])
        candidates = service.list_generation_candidates(request["id"])["data"]["items"]
        self.assertEqual(len(provider.calls), 2)
        self.assertIn("Measured locally", provider.calls[1]["prompt"])
        self.assertIn("Missing required targets", provider.calls[1]["prompt"])
        self.assertEqual(candidates[0]["status"], "IN_TOLERANCE")
        self.assertEqual(service.get_generation_request(request["id"])["data"]["request"]["automaticStatus"], "READY")

    def test_three_misses_stop_and_choose_deterministic_best(self):
        service, provider, request = self.service_with([
            {"title": "One", "text": "svak ukjent"},
            {"title": "Two", "text": ("jobb " * 8) + "svak ukjent"},
            {"title": "Three", "text": ("jobb " * 3) + "svak ukjent"},
        ])
        service.generation_service.run_automatic(request["id"])
        saved = service.get_generation_request(request["id"])["data"]["request"]
        candidates = service.list_generation_candidates(request["id"])["data"]["items"]
        best = next(item for item in candidates if item["isBestCandidate"])
        self.assertEqual(len(provider.calls), 3)
        self.assertEqual(saved["automaticStatus"], "OUT_OF_TOLERANCE")
        self.assertEqual(best["title"], "Two")
        self.assertEqual(best["status"], "OUT_OF_TOLERANCE")

    def test_missing_required_target_cannot_pass_on_coverage_alone(self):
        service, _provider, request = self.service_with([{"title": "Only known", "text": "jobb " * 20}] * 3)
        service.generation_service.run_automatic(request["id"])
        candidate = service.list_generation_candidates(request["id"])["data"]["items"][-1]
        self.assertEqual(candidate["analysis"]["actualTokenCoveragePercent"], 100.0)
        self.assertFalse(candidate["analysis"]["targetsSatisfied"])
        self.assertEqual(candidate["status"], "OUT_OF_TOLERANCE")

    def test_auth_error_stops_without_fallback_or_secret_leak(self):
        error = GenerationProviderError("Authentication failed", code="gemini_auth_error", state="AUTH_ERROR")
        service, provider, request = self.service_with([error, {"title": "unused", "text": self.passing_text()}])
        service.generation_service.run_automatic(request["id"])
        saved = service.get_generation_request(request["id"])["data"]["request"]
        self.assertEqual(saved["automaticStatus"], "FAILED")
        self.assertEqual(saved["automaticStage"], "AUTH_ERROR")
        self.assertEqual(len(provider.calls), 1)
        self.assertNotIn("GEMINI_API_KEY", json.dumps(saved))

    def test_malformed_output_consumes_at_most_three_total_attempts(self):
        service, provider, request = self.service_with([{}, {}, {}, {"title": "unused", "text": self.passing_text()}])
        service.generation_service.run_automatic(request["id"])
        candidates = service.list_generation_candidates(request["id"])["data"]["items"]
        self.assertEqual(len(provider.calls), 3)
        self.assertEqual(len(candidates), 3)
        self.assertTrue(all(item["status"] == "FAILED" for item in candidates))

    def test_queued_cancellation_prevents_provider_call(self):
        service, provider, request = self.service_with([{"title": "unused", "text": self.passing_text()}])
        service.store.queue_automatic_generation(request["id"])
        service.store.cancel_automatic_generation(request["id"])
        service.generation_service.run_automatic(request["id"])
        self.assertEqual(provider.calls, [])
        self.assertEqual(service.get_generation_request(request["id"])["data"]["request"]["automaticStatus"], "CANCELLED")


if __name__ == "__main__":
    unittest.main()
