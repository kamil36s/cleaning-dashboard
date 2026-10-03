import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.parse import quote

import server
from jobhunt_backend import JobhuntService


class JobhuntPackKHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.service = JobhuntService(
            root / "jobhunt.sqlite", private_root=root / "private", environment={}
        )
        self.service.initialize()
        self.track_id = "track_seed_qa_poland"
        imported = self.service.manual_import({
            "sourceKey": "manual", "externalListingId": "pack-k-http",
            "inputMode": "json", "contentType": "application/json",
            "content": json.dumps({
                "title": "QA Engineer", "company": "HTTP <unsafe>",
                "skills": ["SQL"], "datePosted": "2026-09-23",
            }),
        })["data"]
        extracted = self.service.extract_capture(imported["capture"]["id"])["data"]
        self.job_id = extracted["projection"]["canonicalJobId"]
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

    def request(self, path):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.request("GET", path)
        response = connection.getresponse()
        raw = response.read()
        connection.close()
        return response.status, json.loads(raw.decode())

    def test_intelligence_detail_unmapped_and_meta_routes(self):
        base = f"/api/jobhunt/tracks/{self.track_id}/skills"
        status, intelligence = self.request(
            f"{base}/intelligence?population=current&window=90d&sort=demand&minimumDemand=1"
        )
        self.assertEqual(status, 200)
        self.assertEqual(intelligence["data"]["track"]["id"], self.track_id)
        self.assertEqual(intelligence["data"]["skills"][0]["reference"], "skill:SQL")
        self.assertEqual(intelligence["data"]["population"]["canonicalJobDenominator"], 1)

        status, detail = self.request(f"{base}/{quote('skill:SQL')}")
        self.assertEqual(status, 200)
        self.assertEqual(detail["data"]["skill"]["conceptKey"], "SQL")
        self.assertEqual(detail["data"]["skill"]["demandJobs"][0]["id"], self.job_id)

        status, unmapped = self.request(f"{base}/unmapped")
        self.assertEqual(status, 200)
        self.assertIn("unmapped", unmapped["data"])

        status, meta = self.request(f"{base}/meta?population=historical&window=30d")
        self.assertEqual(status, 200)
        self.assertEqual(meta["data"]["population"]["mode"], "historical")
        self.assertEqual(meta["data"]["materialization"]["strategy"], "bounded_live_query")

    def test_query_validation_is_bounded(self):
        base = f"/api/jobhunt/tracks/{self.track_id}/skills/intelligence"
        status, body = self.request(f"{base}?window=all-time")
        self.assertEqual(status, 400)
        self.assertEqual(body["code"], "invalid_skill_window")
        status, body = self.request(f"{base}?sort=DROP%20TABLE")
        self.assertEqual(status, 400)
        self.assertEqual(body["code"], "invalid_skill_sort")


if __name__ == "__main__":
    unittest.main()
