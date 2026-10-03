import copy
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

import server
from jobhunt_backend import JobhuntService


class JobhuntPackJHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.service = JobhuntService(
            root / "jobhunt.sqlite", private_root=root / "private", environment={}
        )
        self.service.initialize()
        self.track_id = "track_seed_qa_poland"
        job = self.service.create_job({
            "company": "Pack J HTTP",
            "role": "QA Engineer",
            "location": {"city": "Krakow", "country": "Poland", "workMode": "hybrid"},
            "requirements": {"mustHave": ["SQL"], "niceToHave": [], "tools": []},
            "match": {"score": 77, "summary": "Legacy imported-like compatibility data"},
        })["data"]["job"]
        self.job_id = job["id"]
        self.service.set_job_tracks(self.job_id, {"trackIds": [self.track_id]})

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
        return response.status, json.loads(raw.decode()) if raw else None

    def test_policy_evaluation_history_and_lists_are_exposed(self):
        status, current = self.request(
            "GET", f"/api/jobhunt/tracks/{self.track_id}/evaluation-policy"
        )
        self.assertEqual(status, 200)
        self.assertEqual(current["data"]["policy"]["version"], 1)
        self.assertEqual(current["data"]["policy"]["policy"]["aggregate"], "none")

        changed = copy.deepcopy(current["data"]["policy"]["policy"])
        changed["skillThresholds"] = {"partialMin": 2, "supportedMin": 4}
        status, created = self.request(
            "POST",
            f"/api/jobhunt/tracks/{self.track_id}/evaluation-policy",
            {"policy": changed},
        )
        self.assertEqual(status, 201)
        self.assertEqual(created["data"]["policy"]["version"], 2)

        status, evaluated = self.request(
            "POST",
            f"/api/jobhunt/jobs/{self.job_id}/tracks/{self.track_id}/evaluate",
            {},
        )
        self.assertEqual(status, 200)
        evaluation = evaluated["data"]["evaluation"]
        self.assertNotIn("score", evaluation)
        self.assertEqual(evaluation["policyVersion"], 2)
        self.assertTrue(evaluation["findings"][0]["policyEvidence"])

        status, detail = self.request(
            "GET", f"/api/jobhunt/evaluations/{evaluation['id']}"
        )
        self.assertEqual(status, 200)
        self.assertEqual(detail["data"]["evaluation"]["id"], evaluation["id"])

        status, job_values = self.request(
            "GET", f"/api/jobhunt/jobs/{self.job_id}/evaluations"
        )
        self.assertEqual(status, 200)
        self.assertEqual(job_values["data"]["targets"][0]["evaluation"]["state"], "current")
        self.assertIn("legacy", job_values["data"]["legacySeparation"])

        status, track_values = self.request(
            "GET", f"/api/jobhunt/tracks/{self.track_id}/evaluations"
        )
        self.assertEqual(status, 200)
        self.assertEqual(track_values["data"]["items"][0]["jobId"], self.job_id)

        status, history = self.request(
            "GET", f"/api/jobhunt/tracks/{self.track_id}/evaluation-policy/history"
        )
        self.assertEqual(status, 200)
        self.assertEqual([item["version"] for item in history["data"]["items"]], [2, 1])

    def test_safe_policy_writes_reject_unknown_fields_and_bad_shapes(self):
        current = self.service.get_track_evaluation_policy(self.track_id)["data"]["policy"]["policy"]
        unsafe = copy.deepcopy(current)
        unsafe["run"] = "arbitrary expression"
        status, body = self.request(
            "POST",
            f"/api/jobhunt/tracks/{self.track_id}/evaluation-policy",
            {"policy": unsafe},
        )
        self.assertEqual(status, 400)
        self.assertEqual(body["code"], "invalid_evaluation_policy")

        status, body = self.request(
            "POST",
            f"/api/jobhunt/tracks/{self.track_id}/evaluation-policy",
            {"policy": current, "overwrite": True},
        )
        self.assertEqual(status, 400)
        self.assertEqual(body["code"], "invalid_evaluation_policy")


if __name__ == "__main__":
    unittest.main()
