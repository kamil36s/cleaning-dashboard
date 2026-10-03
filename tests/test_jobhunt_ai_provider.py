import io
import json
import socket
import unittest
import urllib.error

from jobhunt_backend.extraction.ai import (
    AIExtractionRequest,
    AIProviderError,
    AI_RESPONSE_JSON_SCHEMA,
    GeminiAIExtractionProvider,
)


class _Response:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit):
        return self.payload[:limit]


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


def request():
    return AIExtractionRequest(
        system_prompt="System boundary", user_prompt="Untrusted advertisement",
        response_schema=AI_RESPONSE_JSON_SCHEMA, max_output_tokens=500,
    )


class JobhuntGeminiProviderTests(unittest.TestCase):
    def environment(self, **updates):
        result = {
            "JOBHUNT_AI_ENABLED": "true", "JOBHUNT_AI_PROVIDER": "gemini",
            "JOBHUNT_AI_MODEL": "gemini-3.8-flash", "GEMINI_API_KEY": "secret-test-key",
        }
        result.update(updates)
        return result

    def test_fixed_model_request_schema_usage_and_no_key_in_body(self):
        structured = {"facts": [], "openFacts": [], "warnings": []}
        opener = _Opener([{
            "responseId": "response-1", "modelVersion": "model-version-1",
            "candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(structured)}]}}],
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 4, "totalTokenCount": 14, "cachedContentTokenCount": 2},
        }])
        provider = GeminiAIExtractionProvider(environment=self.environment(), opener=opener)
        result = provider.extract_facts(request())
        http_request, timeout = opener.requests[0]
        body = json.loads(http_request.data.decode("utf-8"))
        self.assertEqual(timeout, 45.0)
        self.assertIn("gemini-3.8-flash:generateContent", http_request.full_url)
        self.assertEqual(body["systemInstruction"]["parts"][0]["text"], "System boundary")
        self.assertFalse(body["generationConfig"]["responseJsonSchema"]["additionalProperties"])
        self.assertNotIn("secret-test-key", http_request.data.decode("utf-8"))
        self.assertEqual(result.usage["total_tokens"], 14)

    def test_timeout_429_and_auth_are_classified_without_adapter_retry(self):
        provider = GeminiAIExtractionProvider(environment=self.environment(), opener=_Opener([socket.timeout()]))
        with self.assertRaises(AIProviderError) as timeout:
            provider.extract_facts(request())
        self.assertTrue(timeout.exception.retryable)
        self.assertEqual(timeout.exception.classification, "timeout")

        error_429 = urllib.error.HTTPError("url", 429, "rate", {}, io.BytesIO(b'{"error":{"message":"rate limit"}}'))
        provider = GeminiAIExtractionProvider(environment=self.environment(), opener=_Opener([error_429]))
        with self.assertRaises(AIProviderError) as limited:
            provider.extract_facts(request())
        self.assertTrue(limited.exception.retryable)

        error_503 = urllib.error.HTTPError("url", 503, "down", {}, io.BytesIO(b"{}"))
        provider = GeminiAIExtractionProvider(environment=self.environment(), opener=_Opener([error_503]))
        with self.assertRaises(AIProviderError) as unavailable:
            provider.extract_facts(request())
        self.assertTrue(unavailable.exception.retryable)
        self.assertEqual(unavailable.exception.classification, "transient")

        error_401 = urllib.error.HTTPError("url", 401, "auth", {}, io.BytesIO(b"{}"))
        provider = GeminiAIExtractionProvider(environment=self.environment(), opener=_Opener([error_401]))
        with self.assertRaises(AIProviderError) as auth:
            provider.extract_facts(request())
        self.assertFalse(auth.exception.retryable)
        self.assertEqual(auth.exception.classification, "authentication")

    def test_disabled_missing_key_and_non_allowlisted_model_never_call_network(self):
        cases = [
            self.environment(JOBHUNT_AI_ENABLED="false"),
            self.environment(GEMINI_API_KEY=""),
            self.environment(JOBHUNT_AI_MODEL="arbitrary-expensive-model"),
        ]
        for environment in cases:
            opener = _Opener([])
            provider = GeminiAIExtractionProvider(environment=environment, opener=opener)
            self.assertFalse(provider.health()["configured"])
            with self.assertRaises(AIProviderError):
                provider.extract_facts(request())
            self.assertEqual(opener.requests, [])

    def test_malformed_and_incomplete_response_are_permanent(self):
        opener = _Opener([{"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "not-json"}]}}]}])
        provider = GeminiAIExtractionProvider(environment=self.environment(), opener=opener)
        with self.assertRaises(AIProviderError) as malformed:
            provider.extract_facts(request())
        self.assertFalse(malformed.exception.retryable)
        self.assertEqual(malformed.exception.classification, "malformed_response")

        opener = _Opener([{"candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": [{"text": "{}"}]}}]}])
        provider = GeminiAIExtractionProvider(environment=self.environment(), opener=opener)
        with self.assertRaises(AIProviderError) as incomplete:
            provider.extract_facts(request())
        self.assertEqual(incomplete.exception.classification, "incomplete")


if __name__ == "__main__":
    unittest.main()
