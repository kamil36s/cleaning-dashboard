import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

import server
from jobhunt_backend import JobhuntService


class JobhuntPackCHttpTests(unittest.TestCase):
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

    def test_track_search_profile_and_assignment_routes(self):
        status, listed = self.request("GET", "/api/jobhunt/tracks")
        self.assertEqual(status, 200)
        self.assertEqual(len(listed["data"]["tracks"]), 5)

        status, created = self.request("POST", "/api/jobhunt/tracks", {
            "name": "QA Abroad", "purpose": "Explore relocation", "status": "exploring",
            "geography": {"countries": ["NO"], "remoteAllowed": None},
        })
        self.assertEqual(status, 201)
        track_id = created["data"]["track"]["id"]

        status, changed = self.request("PATCH", f"/api/jobhunt/tracks/{track_id}", {"status": "active"})
        self.assertEqual(status, 200)
        self.assertEqual(changed["data"]["track"]["status"], "active")

        status, profile = self.request("POST", f"/api/jobhunt/tracks/{track_id}/search-profiles", {
            "name": "Norway test roles", "includeKeywords": ["tester"],
            "excludeKeywords": ["manager"], "plannedSourceKeys": ["nav", "finn"],
        })
        self.assertEqual(status, 201)
        profile_id = profile["data"]["searchProfile"]["id"]
        status, paused = self.request("PATCH", f"/api/jobhunt/search-profiles/{profile_id}", {"status": "paused"})
        self.assertEqual(status, 200)
        self.assertEqual(paused["data"]["searchProfile"]["status"], "paused")

        job = self.service.create_job({
            "company": "ACME", "role": "Tester", "location": {}, "contract": {},
            "salary": {"isKnown": False}, "source": {"name": "manual"},
            "status": "to_review", "priority": "P2", "nextAction": "analyze",
        })["data"]["job"]
        status, assignments = self.request("POST", f"/api/jobhunt/jobs/{job['id']}/tracks", {
            "trackIds": [track_id], "origin": "manual", "note": "Relevant relocation option",
        })
        self.assertEqual(status, 200)
        self.assertTrue(next(item for item in assignments["data"]["tracks"] if item["trackId"] == track_id)["assigned"])
        status, fetched = self.request("GET", f"/api/jobhunt/jobs/{job['id']}/tracks")
        self.assertEqual(status, 200)
        self.assertIn("not a fit", fetched["data"]["assignmentMeaning"])


if __name__ == "__main__":
    unittest.main()
