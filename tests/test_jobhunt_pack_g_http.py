import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

import server
from jobhunt_backend import JobhuntService, JobhuntWorker
from tests.test_jobhunt_pack_g import FakeNavAdapter


class JobhuntPackGHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.service = JobhuntService(
            root / "jobhunt.sqlite", private_root=root / "private",
            environment={"JOBHUNT_NAV_TOKEN": "must-never-leak"},
            nav_adapter=FakeNavAdapter(),
        )
        self.service.initialize()
        self.worker = JobhuntWorker(self.service)
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
        self.worker.stop(timeout=1)
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

    def test_nav_and_worker_routes_enqueue_without_exposing_token(self):
        status, nav, raw = self.request("GET", "/api/jobhunt/sources/nav/status")
        self.assertEqual(status, 200)
        self.assertTrue(nav["data"]["tokenConfigured"])
        self.assertNotIn(b"must-never-leak", raw)

        status, enabled, raw = self.request("POST", "/api/jobhunt/sources/nav/enable", {})
        self.assertEqual(status, 200)
        job_id = enabled["data"]["scheduledJob"]["id"]
        self.assertNotIn(b"must-never-leak", raw)

        status, synced, _ = self.request("POST", "/api/jobhunt/sources/nav/sync", {})
        self.assertEqual(status, 202)
        self.assertEqual(synced["data"]["job"]["id"], job_id)
        self.assertTrue(synced["data"]["reused"])

        status, queue, _ = self.request("GET", "/api/jobhunt/worker/jobs?states=queued&limit=10")
        self.assertEqual(status, 200)
        self.assertEqual(queue["data"]["jobs"][0]["id"], job_id)
        status, detail, _ = self.request("GET", f"/api/jobhunt/worker/jobs/{job_id}")
        self.assertEqual(status, 200)
        self.assertTrue(detail["data"]["job"]["cancellable"])

        status, cancelled, _ = self.request("POST", f"/api/jobhunt/worker/jobs/{job_id}/cancel", {})
        self.assertEqual(status, 200)
        self.assertEqual(cancelled["data"]["job"]["state"], "cancelled")

        status, feed, _ = self.request("GET", "/api/jobhunt/sources/nav/feed-state")
        self.assertEqual(status, 200)
        self.assertIn("feedState", feed["data"])
        status, paused, _ = self.request("POST", "/api/jobhunt/sources/nav/pause", {})
        self.assertEqual(status, 200)
        self.assertFalse(paused["data"]["source"]["policy"]["enabled"])

    def test_enable_requires_configured_token(self):
        self.service.nav_adapter.token_configured = False
        status, body, _ = self.request("POST", "/api/jobhunt/sources/nav/enable", {})
        self.assertEqual(status, 409)
        self.assertEqual(body["code"], "nav_token_not_configured")


if __name__ == "__main__":
    unittest.main()
