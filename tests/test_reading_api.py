import http.client
import json
import tempfile
import threading
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import server
from reading_store import ReadingStore


class ReadingApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = ReadingStore(Path(self.temp_dir.name) / "reading.sqlite")
        self.store.initialize()
        self.previous_store = server.READING_STORE
        server.READING_STORE = self.store
        self.httpd = server.DashboardHTTPServer(("127.0.0.1", 0), server.Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.httpd.server_address[1]

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)
        server.READING_STORE = self.previous_store
        self.temp_dir.cleanup()

    def request(self, method, path, payload=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Content-Type": "application/json"} if body is not None else {}
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        data = json.loads(response.read().decode("utf-8"))
        connection.close()
        return response.status, data

    def test_reading_routes_cover_state_create_progress_history_and_settings(self):
        status, created = self.request("POST", "/api/reading/books", {
            "title": "Lokalna książka",
            "author": "Ada Autorka",
            "pagesRead": 5,
            "pagesTotal": 100,
            "source": "owned",
        })
        self.assertEqual(status, 201)
        book_id = created["book_id"]

        status, progress = self.request(
            "PATCH",
            f"/api/reading/books/{book_id}/progress",
            {"pageCurrent": 12, "recordHistory": False},
        )
        self.assertEqual(status, 200)
        self.assertEqual(progress["page_current"], 12)

        status, updated = self.request(
            "PATCH",
            f"/api/reading/books/{book_id}",
            {
                "title": "Lokalna książka po edycji",
                "author": "Ada Autorka",
                "pagesRead": 12,
                "pagesTotal": 120,
                "source": "library",
                "returnDate": "2026-09-30",
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(updated["book"]["title"], "Lokalna książka po edycji")
        self.assertEqual(updated["book"]["pagesTotal"], 120)
        self.assertEqual(updated["book"]["returnDate"], "2026-09-30")

        status, returned = self.request(
            "PATCH",
            f"/api/reading/books/{book_id}",
            {"returnDate": None},
        )
        self.assertEqual(status, 200)
        self.assertEqual(returned["book"]["source"], "library")
        self.assertIsNone(returned["book"]["returnDate"])

        today_key = date.today().isoformat()
        history = {
            "log": {today_key: {"total": 7, "books": {"Lokalna książka - Ada Autorka": 7}, "progress": {}}},
            "startKey": today_key,
            "forecastPlan": None,
        }
        status, saved_history = self.request("POST", "/api/reading/history", history)
        self.assertEqual(status, 200)
        self.assertEqual(saved_history["log"][today_key]["total"], 7)

        settings = {"activeMap": {f"remote:{book_id}": True}, "updatedAt": 1}
        status, saved_settings = self.request("POST", "/api/reading/settings", settings)
        self.assertEqual(status, 200)
        self.assertTrue(saved_settings["activeMap"][f"remote:{book_id}"])

        status, state = self.request("GET", "/api/reading/state")
        self.assertEqual(status, 200)
        self.assertEqual(len(state["books"]), 1)
        self.assertEqual(state["books"][0]["pagesRead"], 12)
        self.assertEqual(state["dailyStats"]["todayRead"], 7)

    def test_remote_cover_lookup_keeps_an_existing_shared_cover(self):
        covers_dir = Path(self.temp_dir.name) / "covers"
        covers_dir.mkdir()
        existing = covers_dir / "reading--wool--hugh-howey.jpg"
        existing.write_bytes(b"shared-cover")

        with (
            mock.patch.object(server, "COVERS_DIR", covers_dir),
            mock.patch.object(server, "download_cover_bytes") as download,
        ):
            result = server.save_reading_cover({
                "title": "Wool",
                "author": "Hugh Howey",
                "sourceUrl": "https://example.test/another-edition.jpg",
            })

        self.assertTrue(result["cached"])
        self.assertEqual(result["url"], "./covers/reading--wool--hugh-howey.jpg")
        self.assertEqual(existing.read_bytes(), b"shared-cover")
        download.assert_not_called()

    def test_static_head_requests_work_for_direct_and_prefixed_lan_urls(self):
        for path in ("/index.html", "/cleaning-dashboard/index.html"):
            connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
            connection.request("HEAD", path)
            response = connection.getresponse()
            response.read()
            connection.close()

            self.assertEqual(response.status, 200)
            self.assertEqual(response.getheader("X-Content-Type-Options"), "nosniff")


if __name__ == "__main__":
    unittest.main()
