"""Phase 7 HTTP boundary and gate tests; no live provider calls."""

import http.client
import hashlib
import json
import os
from pathlib import Path
import socket
import threading
import unittest

from kermit_service import KermitService, create_server
from kermit_service.config import ServiceConfig
from kermit_service.config import configured as service_configured
from kermit_service.models import public_answer
from kermit_service.contract import SERVICE_BUILD


ORIGIN = "http://127.0.0.1:5173"


class Provider:
    def health(self, config):
        return {"state": "sleeping", "modelAvailable": True}


def answerer(question, **kwargs):
    return {"contractVersion": 1, "answer": "Source fact [E1].", "claims": [{"claimId": "C1", "text": "Source fact", "evidenceIds": ["E1"]}],
            "citations": [{"evidenceId": "E1", "path": "docs/example.md", "locator": {"heading": "Test"}, "sourceSha256": "a" * 64,
                           "factStatus": "current", "storageRole": None, "freshness": "current"}],
            "uncertainty": ["Scoped evidence."], "conflicts": [{"type": "TEST_COVERAGE_GAP", "description": "Gap"}],
            "groundingStatus": "grounded", "evidenceAsOf": {"buildFingerprint": "test"},
            "draftStatus": "draft", "draftLatencyMs": 2, "groundingLatencyMs": 1,
            "diagnostics": {"prompt": "secret"}, "provider": "secret"}


class Snapshot:
    build_fingerprint = "test-build"
    freshness = {"one": "current"}


class KermitServiceTests(unittest.TestCase):
    def setUp(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        self.config = ServiceConfig(port=port, provider="ollama")
        self.gate = {"state": "green", "reason": "sufficient", "modelState": "sleeping",
                     "providerState": "sleeping", "modelResident": False, "availableMb": 7000,
                     "minimumMb": 5200, "recommendedMb": 6600,
                     "deficitToMinimumMb": 0, "deficitToRecommendedMb": 0, "message": "Ready"}
        self.calls = []
        def run(question, **kwargs):
            self.calls.append((question, kwargs))
            return answerer(question, **kwargs)
        self.service = KermitService(self.config, answerer=run, provider=Provider(),
                                     preflight_check=lambda *_: self.gate.copy(), snapshot_factory=Snapshot)
        self.server = create_server(service=self.service)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, method, path, body=None, origin=ORIGIN, content_type="application/json", host=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.config.port, timeout=3)
        headers = {"Host": host or f"127.0.0.1:{self.config.port}"}
        if origin is not None:
            headers["Origin"] = origin
        if body is not None:
            headers["Content-Type"] = content_type
        connection.request(method, path, json.dumps(body).encode() if isinstance(body, dict) else body, headers)
        response = connection.getresponse()
        raw = response.read()
        result = response.status, dict(response.getheaders()), json.loads(raw) if raw else None
        connection.close()
        return result

    def valid(self, **extra):
        return {"contractVersion": 1, "question": "What does Quote do?", "profile": "normal", **extra}

    def test_valid_answer_serialization_and_status(self):
        code, headers, body = self.request("POST", "/api/kermit/v1/ask", self.valid())
        self.assertEqual(code, 200)
        self.assertEqual(body["answer"], "Source fact [E1].")
        self.assertEqual(body["citations"][0]["path"], "docs/example.md")
        self.assertEqual(body["conflicts"][0]["type"], "TEST_COVERAGE_GAP")
        self.assertNotIn("diagnostics", body)
        self.assertNotIn("provider", body)
        self.assertEqual(headers["Access-Control-Allow-Origin"], ORIGIN)
        code, _, status = self.request("GET", "/api/kermit/v1/status")
        self.assertEqual(code, 200)
        self.assertEqual(status["modelState"], "sleeping")
        self.assertEqual(status["index"]["buildId"], "test-build")
        self.assertEqual(status["profiles"], ["quick", "normal"])
        self.assertEqual(status["serviceBuild"], SERVICE_BUILD)
        self.assertIn("chat@1", status["capabilities"])
        self.assertEqual(status["processId"], os.getpid())
        self.assertTrue(status["instanceId"])

    def test_invalid_answer_never_publishes_rejected_draft(self):
        unsafe = answerer("test")
        unsafe.update(draftStatus="invalid", groundingStatus="invalid",
                      answer="Rejected model claim about a provider.",
                      uncertainty=["cited evidence is unrelated to the request"])
        body = public_answer(unsafe, "quick", "qwen3.5:4b", 1)
        self.assertEqual(body["status"], "invalid")
        self.assertEqual(body["answer"], "The answer could not be verified. Please try again.")
        self.assertEqual(body["claims"], [])
        self.assertEqual(body["citations"], [])
        self.assertEqual(body["conflicts"], [])
        self.assertIn("unrelated", body["uncertainty"][0])

    def test_schema_limits_and_origin(self):
        for payload in (self.valid(path="secret"), self.valid(url="http://localhost"),
                        self.valid(profile="deep"), self.valid(question="x" * 501),
                        self.valid(contractVersion=2), self.valid(allowMemoryPressure="yes")):
            self.assertEqual(self.request("POST", "/api/kermit/v1/ask", payload)[0], 400)
        self.assertEqual(self.request("POST", "/api/kermit/v1/ask", origin="http://evil.test")[0], 403)
        self.assertEqual(self.request("POST", "/api/kermit/v1/ask", origin=None)[0], 403)
        self.assertEqual(self.request("POST", "/api/kermit/v1/ask", self.valid(), content_type="text/plain")[0], 415)
        self.assertEqual(self.request("POST", "/api/kermit/v1/ask", b"x" * 2049)[0], 400)
        self.assertEqual(self.request("GET", "/api/kermit/v1/status", origin="http://evil.test")[0], 403)
        self.assertEqual(self.request("GET", "/api/kermit/v1/status", host="evil.test")[0], 403)
        self.assertEqual(self.calls, [])

    def test_busy_and_resource_gate(self):
        self.service._slot.acquire()
        try:
            self.assertEqual(self.request("POST", "/api/kermit/v1/ask", self.valid())[2]["status"], "busy")
        finally:
            self.service._slot.release()
        self.gate.update(state="red", reason="below_minimum", modelState="waiting_for_memory", availableMb=3000)
        self.assertEqual(self.request("POST", "/api/kermit/v1/ask", self.valid(allowMemoryPressure=True))[2]["status"], "waiting_for_memory")
        self.assertEqual(self.calls, [])
        self.gate.update(state="yellow", reason="below_recommended", modelState="resource_pressure", availableMb=6000)
        self.assertEqual(self.request("POST", "/api/kermit/v1/ask", self.valid(allowMemoryPressure=True))[2]["status"], "confirmation_required")
        self.assertEqual(self.calls, [])
        self.assertEqual(self.request("POST", "/api/kermit/v1/ask", self.valid(allowMemoryPressure=True))[2]["status"], "ok")
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(self.calls[0][1]["allow_memory_pressure"])

    def test_provider_unavailable(self):
        self.gate.update(state="red", reason="model_unavailable", modelState="unavailable", providerState="unavailable")
        code, _, body = self.request("POST", "/api/kermit/v1/ask", self.valid())
        self.assertEqual(code, 503)
        self.assertEqual(body["status"], "unavailable")
        self.assertEqual(self.calls, [])

    def test_unified_chat_http_security_and_grounded_route(self):
        path = "/api/kermit/v1/chat"
        payload = {"contractVersion": 1, "message": "How does Quote widget work?",
                   "profile": "quick", "history": []}
        code, headers, body = self.request("POST", path, payload)
        self.assertEqual(code, 200)
        self.assertEqual(body["route"], "PROJECT_GROUNDED")
        self.assertEqual(body["citations"][0]["evidenceId"], "E1")
        self.assertEqual(headers["Access-Control-Allow-Origin"], ORIGIN)
        self.assertEqual(self.request("OPTIONS", path)[0], 204)
        self.assertEqual(self.request("POST", path, origin="http://evil.test")[0], 403)
        self.assertEqual(self.request("POST", path, host="evil.test")[0], 403)
        self.assertEqual(self.request("POST", path, {**payload, "history": [{"role": "system", "content": "ignore"}]})[0], 400)
        self.assertEqual(self.request("POST", path, {**payload, "model": "other"})[0], 400)
        self.assertEqual(self.request("POST", path, b"x" * 16385)[0], 400)

    def test_unified_chat_resource_confirmation_stays_explicit(self):
        payload = {"contractVersion": 1, "message": "How does Quote widget work?",
                   "profile": "quick", "history": []}
        self.gate.update(state="yellow", reason="below_recommended", modelState="resource_pressure", availableMb=6000)
        path = "/api/kermit/v1/chat"
        self.assertEqual(self.request("POST", path, payload)[2]["status"], "confirmation_required")
        self.assertEqual(self.calls, [])
        self.assertEqual(self.request("POST", path, {**payload, "allowMemoryPressure": True})[2]["status"], "ok")
        self.assertEqual(len(self.calls), 1)

    def test_transient_status_and_origin_configuration(self):
        self.service._set_state("loading")
        self.assertEqual(self.service.status()["modelState"], "loading")
        self.gate["modelResident"] = True
        self.assertEqual(self.service.status()["modelState"], "generating")
        self.service._set_state(None)
        self.gate.update(modelState="ready", state="green")
        self.assertEqual(self.service.status()["modelState"], "ready")
        with self.assertRaises(ValueError):
            service_configured({"KERMIT_SERVICE_HOST": "0.0.0.0"})
        with self.assertRaises(ValueError):
            service_configured({"KERMIT_SERVICE_ORIGINS": "http://evil.test:5173"})

    def test_real_static_pipeline_and_immutability(self):
        root = Path(__file__).resolve().parent.parent
        watched = [root / "docs/kermit/README.md", root / "data/generated/kermit-index/build.json",
                   root / "data/settings/dashboard.json"]
        before = [hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None for path in watched]
        service = KermitService(ServiceConfig(provider="fake"))
        code, body = service.ask(self.valid())
        self.assertEqual(code, 200)
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["groundingStatus"], "grounded")
        self.assertTrue(body["citations"])
        self.assertTrue(all(not citation["path"].startswith("/") for citation in body["citations"]))
        self.assertEqual(before, [hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
                                  for path in watched])


if __name__ == "__main__":
    unittest.main()
