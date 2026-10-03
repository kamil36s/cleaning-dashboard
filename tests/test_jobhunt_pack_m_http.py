import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.parse import quote

import server
from jobhunt_backend import JobhuntService


class JobhuntPackMHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.service = JobhuntService(
            root / "jobhunt.sqlite", private_root=root / "private", environment={}
        )
        self.service.initialize()
        self.previous_service = server.JOBHUNT_SERVICE
        server.JOBHUNT_SERVICE = self.service
        self.httpd = server.DashboardHTTPServer(("127.0.0.1", 0), server.Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.httpd.server_address[1]
        self.track_id = "track_seed_qa_poland"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)
        server.JOBHUNT_SERVICE = self.previous_service
        self.temp.cleanup()

    def request(self, method, path, payload=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=8)
        body = json.dumps(payload).encode() if payload is not None else None
        headers = {"Content-Type": "application/json"} if body is not None else {}
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        raw = response.read()
        connection.close()
        return response.status, json.loads(raw.decode()) if raw else None

    def test_analytics_track_tradeoff_and_scenario_routes(self):
        for path in (
            "/api/jobhunt/analytics/market?window=30d",
            "/api/jobhunt/analytics/sources?window=90d",
            "/api/jobhunt/analytics/applications?window=180d",
            f"/api/jobhunt/tracks/{self.track_id}/analytics?window=90d",
        ):
            status, body = self.request("GET", path)
            self.assertEqual(status, 200, path)
            self.assertTrue(body["ok"])

        scenario = {
            "name": "HTTP partial scenario", "currency": "PLN",
            "assumptions": {"monthlyCosts": {
                "housing": {"value": 2500, "source": "manual", "updatedAt": "2026-09-24"},
            }},
        }
        status, body = self.request(
            "POST", f"/api/jobhunt/tracks/{self.track_id}/economic-scenarios", scenario
        )
        self.assertEqual(status, 201)
        self.assertEqual(body["data"]["scenario"]["version"], 1)
        status, body = self.request(
            "GET", f"/api/jobhunt/economic-scenarios?trackId={self.track_id}"
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(body["data"]["items"]), 1)
        status, body = self.request(
            "GET", "/api/jobhunt/analytics/tradeoffs?window=90d&trackIds="
            f"{self.track_id},track_seed_norway_qa"
        )
        self.assertEqual(status, 200)
        self.assertIsNone(body["data"]["winner"])

        status, body = self.request("GET", "/api/jobhunt/analytics/market?window=DROP%20TABLE")
        self.assertEqual(status, 400)
        self.assertEqual(body["code"], "invalid_analytics_window")

    def test_career_intelligence_and_experiment_crud_routes(self):
        for path in (
            "/api/jobhunt/career-intelligence",
            "/api/jobhunt/career-intelligence/adjacent",
            "/api/jobhunt/career-intelligence/track-proposals",
            "/api/jobhunt/experiments/templates",
            "/api/jobhunt/experiments",
        ):
            status, body = self.request("GET", path)
            self.assertEqual(status, 200, path)
            self.assertTrue(body["ok"])

        status, created = self.request("POST", "/api/jobhunt/experiments", {
            "templateId": "sql-analysis@1", "trackId": self.track_id,
        })
        self.assertEqual(status, 201)
        experiment_id = created["data"]["experiment"]["id"]
        encoded = quote(experiment_id)
        status, patched = self.request(
            "PATCH", f"/api/jobhunt/experiments/{encoded}", {"plannedMinutes": 100}
        )
        self.assertEqual(status, 200)
        self.assertEqual(patched["data"]["experiment"]["plannedMinutes"], 100)
        self.assertEqual(self.request(
            "POST", f"/api/jobhunt/experiments/{encoded}/start", {}
        )[0], 200)
        status, completed = self.request(
            "POST", f"/api/jobhunt/experiments/{encoded}/complete", {
                "actualMinutes": 90, "interestRating": 4, "difficultyRating": 3,
                "frustrationRating": 2, "confidenceChangeRating": 1,
                "desireToContinue": True, "notes": "HTTP evidence",
            }
        )
        self.assertEqual(status, 200)
        self.assertEqual(completed["data"]["experiment"]["status"], "completed")
        status, noted = self.request(
            "POST", f"/api/jobhunt/experiments/{encoded}/notes", {"note": "Append-only note"}
        )
        self.assertEqual(status, 200)
        self.assertTrue(any(
            item["type"] == "note_added"
            for item in noted["data"]["experiment"]["events"]
        ))
        status, immutable = self.request(
            "PATCH", f"/api/jobhunt/experiments/{encoded}", {"notes": "overwrite"}
        )
        self.assertEqual(status, 409)
        self.assertEqual(immutable["code"], "experiment_immutable")
        status, applied = self.request(
            "POST", f"/api/jobhunt/experiments/{encoded}/apply-insight", {
                "confirm": True, "collection": "skills",
                "record": {"displayName": "SQL", "normalizedKey": "SQL", "level": 2,
                           "confidence": 3},
            }
        )
        self.assertEqual(status, 200)
        self.assertEqual(applied["data"]["profileRecord"]["origin"], "career_experiment")


if __name__ == "__main__":
    unittest.main()
