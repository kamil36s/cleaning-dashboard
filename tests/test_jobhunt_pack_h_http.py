import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

import server
from jobhunt_backend import JobhuntService


class JobhuntPackHHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.service = JobhuntService(root / "jobhunt.sqlite", private_root=root / "private", environment={})
        self.service.initialize()
        for external_id, company in (("a", "Example AS"), ("b", "Example")):
            imported = self.service.manual_import({
                "sourceKey": "manual", "externalListingId": external_id,
                "inputMode": "json", "contentType": "application/json",
                "content": json.dumps({
                    "title": "QA Engineer", "company": company, "city": "Oslo",
                    "country": "Norway", "datePosted": "2026-09-20",
                    "description": "Test APIs and web applications",
                }),
            })["data"]
            self.service.extract_capture(imported["capture"]["id"])
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
        body = json.dumps(payload).encode() if payload is not None else None
        headers = {"Content-Type": "application/json"} if body is not None else {}
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        raw = response.read()
        connection.close()
        return response.status, json.loads(raw.decode()) if raw else None, raw

    def test_duplicate_review_merge_history_unmerge_and_summary_routes(self):
        status, listed, raw = self.request("GET", "/api/jobhunt/duplicates")
        self.assertEqual(status, 200)
        self.assertNotIn(b"Test APIs and web applications", raw)
        candidate = listed["data"]["items"][0]
        status, detail, _ = self.request("GET", f"/api/jobhunt/duplicates/{candidate['id']}")
        self.assertEqual(status, 200)
        self.assertTrue(detail["data"]["safety"]["safe"])
        status, merged, _ = self.request("POST", f"/api/jobhunt/duplicates/{candidate['id']}/merge", {
            "confirm": True, "survivorJobId": detail["data"]["safety"]["survivorJobId"],
        })
        self.assertEqual(status, 200)
        merge_id = merged["data"]["merge"]["id"]
        status, history, _ = self.request("GET", "/api/jobhunt/dedupe/merges")
        self.assertEqual(status, 200)
        self.assertEqual(history["data"]["items"][0]["state"], "active")
        status, reverted, _ = self.request("POST", f"/api/jobhunt/dedupe/merges/{merge_id}/unmerge", {})
        self.assertEqual(status, 200)
        self.assertEqual(reverted["data"]["merge"]["state"], "reverted")
        status, summary, _ = self.request("GET", "/api/jobhunt/dedupe/summary")
        self.assertEqual(status, 200)
        self.assertEqual(summary["data"]["summary"]["canonicalJobs"], 2)
        self.assertIn("sourceListings", summary["data"]["denominators"])

    def test_automatic_policy_cannot_be_forced_from_frontend(self):
        candidate = self.service.list_duplicates()["data"]["items"][0]
        status, body, _ = self.request("POST", f"/api/jobhunt/duplicates/{candidate['id']}/merge", {
            "confirm": True, "auto": True,
        })
        self.assertEqual(status, 400)
        self.assertEqual(body["code"], "invalid_duplicate_merge")


if __name__ == "__main__":
    unittest.main()
