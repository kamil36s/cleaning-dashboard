import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

import server
from jobhunt_backend import JobhuntService


class JobhuntHttpTests(unittest.TestCase):
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

    def test_migration_crud_application_and_overview_routes(self):
        status, migrated = self.request("POST", "/api/jobhunt/migrations/local-storage", {
            "schemaVersion": 1,
            "idempotencyKey": "jobhunt-http-migration-0001",
            "offers": [{
                "id": "legacy-http",
                "company": "HTTP Co",
                "role": "QA",
                "source": {"url": "https://example.test/http"},
                "status": "to_review",
                "match": {"score": 70},
            }],
            "matchSettings": [],
        })
        self.assertEqual(status, 200)
        self.assertTrue(migrated["data"]["verified"])

        status, listed = self.request("GET", "/api/jobhunt/jobs")
        self.assertEqual(status, 200)
        job_id = listed["data"]["jobs"][0]["id"]

        status, updated = self.request("PATCH", f"/api/jobhunt/jobs/{job_id}", {"notes": "API note"})
        self.assertEqual(status, 200)
        self.assertEqual(updated["data"]["job"]["notes"], "API note")

        status, command = self.request(
            "POST", f"/api/jobhunt/applications/{job_id}/events", {"type": "applied"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(command["data"]["application"]["status"], "applied")

        status, overview = self.request("GET", "/api/jobhunt/overview")
        self.assertEqual(status, 200)
        self.assertEqual(overview["data"]["summary"]["total"], 1)
        self.assertNotIn("notes", overview["data"]["summary"]["bestMatch"])
        self.assertEqual(len(overview["data"]["home"]["recentOpportunities"]), 1)
        self.assertIsInstance(overview["data"]["home"]["attention"]["newJobs"], int)
        self.assertNotIn("score", overview["data"]["home"])
        self.assertNotIn("bestMatch", overview["data"]["home"])

        status, deleted = self.request("DELETE", f"/api/jobhunt/jobs/{job_id}")
        self.assertEqual(status, 200)
        self.assertTrue(deleted["data"]["soft"])
        self.assertEqual(self.request("GET", "/api/jobhunt/jobs")[1]["data"]["jobs"], [])

    def test_overview_exposes_a_bounded_first_run_home_model(self):
        status, overview = self.request("GET", "/api/jobhunt/overview")
        self.assertEqual(status, 200)
        home = overview["data"]["home"]
        self.assertTrue(home["firstRun"])
        self.assertTrue(home["profileEmpty"])
        self.assertEqual([item["order"] for item in home["onboarding"]], [1, 2, 3])
        self.assertEqual(home["recentOpportunities"], [])
        self.assertNotIn("score", home)

    def test_jobhunt_private_files_are_not_statically_served(self):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.request("GET", "/data/jobhunt/backups/private.json")
        response = connection.getresponse()
        response.read()
        connection.close()
        self.assertEqual(response.status, 404)


if __name__ == "__main__":
    unittest.main()
