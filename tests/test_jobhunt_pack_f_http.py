import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

import server
from jobhunt_backend import JobhuntService
from jobhunt_backend.extraction.ai import FakeAIExtractionProvider


class JobhuntPackFHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        output = {
            "facts": [{
                "namespace": "job", "type": "skill", "state": "explicit_positive",
                "requirementPreference": "required", "valueType": "text", "valueText": "SQL",
                "sourceWording": "SQL is required", "evidenceQuote": "SQL is required", "confidence": 0.9,
            }],
            "openFacts": [], "warnings": [],
        }
        self.service = JobhuntService(
            root / "jobhunt.sqlite", private_root=root / "private",
            ai_provider=FakeAIExtractionProvider([output]),
            environment={"JOBHUNT_AI_MAX_RETRIES": "0"},
        )
        self.service.initialize()
        self.previous_service = server.JOBHUNT_SERVICE
        server.JOBHUNT_SERVICE = self.service
        self.httpd = server.DashboardHTTPServer(("127.0.0.1", 0), server.Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.httpd.server_address[1]

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)
        server.JOBHUNT_SERVICE = self.previous_service
        self.temp.cleanup()

    def request(self, method, path, payload=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Content-Type": "application/json"} if body is not None else {}
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        raw = response.read()
        connection.close()
        return response.status, json.loads(raw.decode("utf-8")) if raw else None

    def import_text(self):
        status, imported = self.request("POST", "/api/jobhunt/manual-import", {
            "sourceKey": "manual", "externalListingId": "pack-f-http",
            "titleHint": "QA Engineer", "inputMode": "text", "contentType": "text/plain",
            "content": "QA Engineer. SQL is required.",
        })
        self.assertEqual(status, 201)
        return imported["data"]

    def test_safe_status_ai_extract_run_detail_and_fact_routes(self):
        status, config = self.request("GET", "/api/jobhunt/ai/config-summary")
        self.assertEqual(status, 200)
        self.assertTrue(config["data"]["configured"])
        self.assertNotIn("apiKey", json.dumps(config))
        imported = self.import_text()
        capture_id = imported["capture"]["id"]
        status, extracted = self.request("POST", f"/api/jobhunt/captures/{capture_id}/ai-extract", {"force": False})
        self.assertEqual(status, 200)
        run = extracted["data"]["run"]
        self.assertEqual(run["extractorKind"], "ai")
        self.assertEqual(run["ai"]["model"], "fake-job-facts")
        status, detail = self.request("GET", f"/api/jobhunt/extraction-runs/{run['id']}")
        self.assertEqual(status, 200)
        self.assertEqual(len(detail["data"]["attempts"]), 1)
        status, facts = self.request("GET", f"/api/jobhunt/extraction-runs/{run['id']}/facts")
        self.assertEqual(status, 200)
        self.assertEqual(facts["data"]["facts"][0]["extractor"]["provider"], "fake")

    def test_browser_cannot_override_provider_model_or_url(self):
        imported = self.import_text()
        capture_id = imported["capture"]["id"]
        status, body = self.request("POST", f"/api/jobhunt/captures/{capture_id}/ai-extract", {
            "force": False, "model": "arbitrary", "providerUrl": "https://example.test",
        })
        self.assertEqual(status, 400)
        self.assertEqual(body["code"], "unknown_ai_extraction_fields")

    def test_unconfigured_status_and_route_do_not_break_deterministic_route(self):
        root = Path(self.temp.name)
        disabled = JobhuntService(
            root / "disabled.sqlite", private_root=root / "disabled-private",
            environment={"JOBHUNT_AI_ENABLED": "false"},
        )
        disabled.initialize()
        server.JOBHUNT_SERVICE = disabled
        status, config = self.request("GET", "/api/jobhunt/ai/status")
        self.assertEqual(status, 200)
        self.assertFalse(config["data"]["configured"])
        imported = self.import_text()
        capture_id = imported["capture"]["id"]
        status, deterministic = self.request("POST", f"/api/jobhunt/captures/{capture_id}/extract", {})
        self.assertEqual(status, 200)
        self.assertEqual(deterministic["data"]["projection"]["outcome"], "created")
        status, unavailable = self.request("POST", f"/api/jobhunt/captures/{capture_id}/ai-extract", {"force": False})
        self.assertEqual(status, 503)
        self.assertEqual(unavailable["code"], "ai_provider_not_configured")


if __name__ == "__main__":
    unittest.main()
