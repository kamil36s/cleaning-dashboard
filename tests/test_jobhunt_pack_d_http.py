import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

import server
from jobhunt_backend import JobhuntService


class JobhuntPackDHttpTests(unittest.TestCase):
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

    def test_source_import_listing_capture_and_health_routes(self):
        status, sources = self.request("GET", "/api/jobhunt/sources")
        self.assertEqual(status, 200)
        self.assertEqual(len(sources["data"]["sources"]), 10)

        status, imported = self.request("POST", "/api/jobhunt/manual-import", {
            "sourceKey": "manual", "externalListingId": "http-1",
            "inputMode": "html", "contentType": "text/html",
            "content": "<h1>synthetic</h1>", "titleHint": "Synthetic role",
        })
        self.assertEqual(status, 201)
        listing_id = imported["data"]["listing"]["id"]
        capture_id = imported["data"]["capture"]["id"]
        self.assertFalse(imported["data"]["parsingPerformed"])

        status, listings = self.request("GET", "/api/jobhunt/listings?sourceId=manual")
        self.assertEqual(status, 200)
        self.assertEqual(listings["data"]["listings"][0]["id"], listing_id)
        status, detail = self.request("GET", f"/api/jobhunt/listings/{listing_id}")
        self.assertEqual(status, 200)
        self.assertEqual(detail["data"]["captures"][0]["id"], capture_id)
        status, history = self.request("GET", f"/api/jobhunt/listings/{listing_id}/captures")
        self.assertEqual(status, 200)
        self.assertEqual(history["data"]["captures"][0]["id"], capture_id)
        status, capture = self.request("GET", f"/api/jobhunt/captures/{capture_id}")
        self.assertEqual(status, 200)
        self.assertEqual(capture["data"]["content"], "<h1>synthetic</h1>")
        self.assertEqual(capture["data"]["rendering"], "inert_text_only")
        status, health = self.request("GET", "/api/jobhunt/ingestion/storage-health")
        self.assertEqual(status, 200)
        self.assertTrue(health["data"]["healthy"])

    def test_raw_archive_cannot_be_read_as_a_static_file(self):
        result = self.service.manual_import({
            "sourceKey": "manual", "inputMode": "text", "contentType": "text/plain",
            "content": "private raw advertisement",
        })["data"]
        digest = result["capture"]["sha256"]
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.request("GET", f"/data/jobhunt/raw/sha256/{digest[:2]}/{digest[2:4]}/{digest}.txt")
        response = connection.getresponse()
        response.read()
        connection.close()
        self.assertEqual(response.status, 404)


if __name__ == "__main__":
    unittest.main()
