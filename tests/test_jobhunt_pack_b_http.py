import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

import server
from jobhunt_backend import JobhuntService


class JobhuntPackBHttpTests(unittest.TestCase):
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

    def test_profile_and_assessment_routes(self):
        status, profile = self.request("GET", "/api/jobhunt/profile")
        self.assertEqual(status, 200)
        self.assertIsNone(profile["data"]["profile"]["headline"])

        status, profile = self.request("PATCH", "/api/jobhunt/profile", {"headline": "Quality specialist"})
        self.assertEqual(status, 200)
        self.assertEqual(profile["data"]["profile"]["headline"], "Quality specialist")

        status, created = self.request("POST", "/api/jobhunt/profile/skills", {
            "displayName": "SQL", "level": 3, "confidence": 4, "developmentInterest": 5,
        })
        self.assertEqual(status, 201)
        skill_id = created["data"]["record"]["id"]
        status, changed = self.request(
            "PATCH", f"/api/jobhunt/profile/skills/{skill_id}", {"level": 4}
        )
        self.assertEqual(status, 200)
        self.assertEqual(changed["data"]["record"]["level"], 4)

        status, instruments = self.request("GET", "/api/jobhunt/assessments")
        self.assertEqual(status, 200)
        self.assertEqual(len(instruments["data"]["instruments"]), 3)
        status, started = self.request("POST", "/api/jobhunt/assessment-runs", {
            "instrumentId": "career-work-preferences",
        })
        self.assertEqual(status, 201)
        run_id = started["data"]["run"]["id"]
        answers = {item["id"]: 3 for item in started["data"]["instrument"]["items"]}
        status, saved = self.request(
            "POST", f"/api/jobhunt/assessment-runs/{run_id}/responses", {"responses": answers}
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(saved["data"]["run"]["responses"]), 31)
        status, completed = self.request(
            "POST", f"/api/jobhunt/assessment-runs/{run_id}/complete", {}
        )
        self.assertEqual(status, 200)
        self.assertEqual(completed["data"]["run"]["status"], "completed")
        status, immutable = self.request(
            "POST", f"/api/jobhunt/assessment-runs/{run_id}/responses", {
                "responses": {"cwp-01": 1},
            }
        )
        self.assertEqual(status, 409)
        self.assertEqual(immutable["code"], "assessment_run_immutable")

        status, deleted = self.request("DELETE", f"/api/jobhunt/profile/skills/{skill_id}")
        self.assertEqual(status, 200)
        self.assertEqual(deleted["data"]["profile"]["skills"], [])


if __name__ == "__main__":
    unittest.main()
