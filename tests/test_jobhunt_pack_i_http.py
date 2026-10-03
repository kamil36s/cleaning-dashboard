import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

import server
from jobhunt_backend import JobhuntService, JobhuntWorker
from tests.test_jobhunt_pack_i import FakeMailboxTransport, FIXTURES


class JobhuntPackIHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.transport = FakeMailboxTransport({
            21: (FIXTURES / "pack-i-plain.eml").read_bytes(),
        })
        self.service = JobhuntService(
            root / "jobhunt.sqlite",
            private_root=root / "private",
            environment={"JOBHUNT_PRACUJ_IMAP_PASSWORD": "must-never-leak"},
            mail_transport=self.transport,
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

    def test_status_bindings_and_commands_are_narrow_and_secret_free(self):
        status, body, raw = self.request("GET", "/api/jobhunt/sources/pracuj/status")
        self.assertEqual(status, 200)
        self.assertEqual(body["data"]["source"]["policy"]["accessMethod"], "official_email_alert")
        self.assertNotIn(b"must-never-leak", raw)

        track = self.service.get_track("track_seed_norway_qa")["data"]["track"]
        profile = self.service.create_search_profile(track["id"], {
            "name": "Pracuj HTTP",
            "includeKeywords": ["QA"],
            "countries": ["Poland"],
            "regionsCities": ["Krakow"],
            "plannedSourceKeys": ["pracuj"],
        })["data"]["searchProfile"]
        status, created, _ = self.request("POST", "/api/jobhunt/sources/pracuj/bindings", {
            "subjectMatcher": "QA Krakow", "searchProfileId": profile["id"], "enabled": True,
        })
        self.assertEqual(status, 201)
        binding_id = created["data"]["binding"]["id"]
        status, updated, _ = self.request(
            "PATCH", f"/api/jobhunt/sources/pracuj/bindings/{binding_id}", {"enabled": False}
        )
        self.assertEqual(status, 200)
        self.assertFalse(updated["data"]["binding"]["enabled"])

        status, enabled, _ = self.request("POST", "/api/jobhunt/sources/pracuj/enable", {})
        self.assertEqual(status, 200)
        poll_id = enabled["data"]["scheduledJob"]["id"]
        status, synced, _ = self.request("POST", "/api/jobhunt/sources/pracuj/sync", {})
        self.assertEqual(status, 202)
        self.assertEqual(synced["data"]["job"]["id"], poll_id)
        status, state, _ = self.request("GET", "/api/jobhunt/sources/pracuj/mail-state")
        self.assertEqual(status, 200)
        self.assertEqual(state["data"]["mailState"]["mailbox"], "Job Hunt/Pracuj")
        status, paused, _ = self.request("POST", "/api/jobhunt/sources/pracuj/pause", {})
        self.assertEqual(status, 200)
        self.assertFalse(paused["data"]["source"]["policy"]["enabled"])


if __name__ == "__main__":
    unittest.main()
