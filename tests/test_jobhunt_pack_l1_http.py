import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

import server
from jobhunt_backend import JobhuntService, JobhuntWorker
from tests.test_jobhunt_pack_l1 import FakeJobbnorgeAdapter


class JobhuntPackL1HttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.adapter = FakeJobbnorgeAdapter([])
        self.service = JobhuntService(
            root / "jobhunt.sqlite", private_root=root / "private",
            environment={}, jobbnorge_adapter=self.adapter,
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

    def test_status_sync_state_and_commands_are_narrow_and_offline(self):
        status, body, raw = self.request("GET", "/api/jobhunt/sources/jobbnorge/status")
        self.assertEqual(status, 200)
        self.assertFalse(body["data"]["auth"]["required"])
        self.assertEqual(body["data"]["api"]["route"], "/v1/Jobs")
        self.assertNotIn(b"Authorization", raw)

        status, enabled, _ = self.request("POST", "/api/jobhunt/sources/jobbnorge/enable", {})
        self.assertEqual(status, 200)
        job_id = enabled["data"]["scheduledJob"]["id"]
        self.assertEqual(len(self.adapter.calls), 0)

        status, sync, _ = self.request("POST", "/api/jobhunt/sources/jobbnorge/sync", {})
        self.assertEqual(status, 202)
        self.assertEqual(sync["data"]["job"]["type"], "jobbnorge_poll")
        self.assertEqual(len(self.adapter.calls), 0)

        status, state, _ = self.request("GET", "/api/jobhunt/sources/jobbnorge/sync-state")
        self.assertEqual(status, 200)
        self.assertIn("queryState", state["data"])

        status, paused, _ = self.request("POST", "/api/jobhunt/sources/jobbnorge/pause", {})
        self.assertEqual(status, 200)
        self.assertFalse(paused["data"]["source"]["policy"]["enabled"])
        self.assertGreaterEqual(paused["data"]["cancelledJobs"], 1)
        self.assertIsNotNone(job_id)

    def test_sync_requires_explicit_enablement_and_commands_require_empty_body(self):
        status, body, _ = self.request("POST", "/api/jobhunt/sources/jobbnorge/sync", {})
        self.assertEqual(status, 409)
        self.assertEqual(body["code"], "jobbnorge_source_paused")
        status, body, _ = self.request("POST", "/api/jobhunt/sources/jobbnorge/enable", {"token": "no"})
        self.assertEqual(status, 400)
        self.assertEqual(body["code"], "invalid_command_payload")


if __name__ == "__main__":
    unittest.main()
