import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

import server
from jobhunt_backend import JobhuntService


class JobhuntPackEHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.service = JobhuntService(root / "jobhunt.sqlite", private_root=root / "private")
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

    def import_json(self, payload, external_id="http-pack-e"):
        status, imported = self.request("POST", "/api/jobhunt/manual-import", {
            "sourceKey": "manual", "externalListingId": external_id,
            "inputMode": "json", "contentType": "application/json",
            "content": json.dumps(payload),
        })
        self.assertEqual(status, 201)
        return imported["data"]

    def test_extraction_fact_provenance_and_review_routes(self):
        imported = self.import_json({
            "title": "QA Engineer", "company": "Synthetic HTTP AS",
            "salary": {"min": 50000, "max": 60000, "currency": "NOK", "period": "month"},
            "skills": ["SQL"], "unexpectedField": "preserved",
        })
        capture_id = imported["capture"]["id"]
        status, extracted = self.request("POST", f"/api/jobhunt/captures/{capture_id}/extract", {})
        self.assertEqual(status, 200)
        self.assertEqual(extracted["data"]["projection"]["outcome"], "created")
        job_id = extracted["data"]["projection"]["canonicalJobId"]

        status, runs = self.request("GET", f"/api/jobhunt/captures/{capture_id}/extraction-runs")
        self.assertEqual(status, 200)
        structured = next(item for item in runs["data"]["runs"] if item["extractorKind"] == "json_structured")
        status, run = self.request("GET", f"/api/jobhunt/extraction-runs/{structured['id']}")
        self.assertEqual(status, 200)
        self.assertEqual(run["data"]["run"]["extractorVersion"], "json_structured@1")
        status, facts = self.request("GET", f"/api/jobhunt/extraction-runs/{structured['id']}/facts")
        self.assertEqual(status, 200)
        self.assertTrue(all(item["evidence"] for item in facts["data"]["facts"]))
        status, job_facts = self.request("GET", f"/api/jobhunt/jobs/{job_id}/facts")
        self.assertEqual(status, 200)
        self.assertEqual(job_facts["data"]["projection"]["ruleVersion"], "projection@1")

        status, reviews = self.request("GET", "/api/jobhunt/review?state=open")
        self.assertEqual(status, 200)
        open_fact_review = next(item for item in reviews["data"]["items"] if item["reason"] == "unsupported_unexpected_fact")
        status, detail = self.request("GET", f"/api/jobhunt/review/{open_fact_review['id']}")
        self.assertEqual(status, 200)
        self.assertTrue(detail["data"]["facts"])
        status, dismissed = self.request("POST", f"/api/jobhunt/review/{open_fact_review['id']}/dismiss", {
            "resolution": "Source-specific information retained",
        })
        self.assertEqual(status, 200)
        self.assertEqual(dismissed["data"]["item"]["state"], "dismissed")

    def test_human_override_route_takes_precedence_without_rewriting_facts(self):
        first = self.import_json({"title": "Worker", "salary": {"min": 50000, "currency": "NOK", "period": "month"}}, "override-http")
        status, extracted = self.request("POST", f"/api/jobhunt/captures/{first['capture']['id']}/extract", {})
        self.assertEqual(status, 200)
        job_id = extracted["data"]["projection"]["canonicalJobId"]
        second = self.import_json({"title": "Worker", "salary": {"min": 60000, "currency": "NOK", "period": "month"}}, "override-http")
        self.request("POST", f"/api/jobhunt/captures/{second['capture']['id']}/extract", {})

        status, overridden = self.request("POST", f"/api/jobhunt/jobs/{job_id}/overrides", {
            "field": "salary_min", "value": 55000, "reason": "Confirmed locally",
        })
        self.assertEqual(status, 201)
        self.assertEqual(overridden["data"]["override"]["replacementValue"], 55000.0)
        status, job = self.request("GET", f"/api/jobhunt/jobs/{job_id}")
        self.assertEqual(status, 200)
        self.assertEqual(job["data"]["job"]["salary"]["min"], 55000.0)
        status, facts = self.request("GET", f"/api/jobhunt/jobs/{job_id}/facts")
        source_values = {item["value"] for item in facts["data"]["facts"] if item["type"] == "salary_min"}
        self.assertEqual(source_values, {50000.0, 60000.0})


if __name__ == "__main__":
    unittest.main()
