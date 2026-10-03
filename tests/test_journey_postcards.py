import base64
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from journey_postcards import JourneyPostcardStore
from training_runtime import create_server


ROOT = Path(__file__).resolve().parents[1]
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class JourneyPostcardTests(unittest.TestCase):
    def test_store_persists_and_replaces_a_valid_image(self):
        with tempfile.TemporaryDirectory() as directory:
            store = JourneyPostcardStore(Path(directory), ["santiago-001"])
            saved = store.save(
                "santiago-001", "krakow.png", "image/png", base64.b64encode(PNG_1X1).decode("ascii")
            )
            self.assertEqual(saved["checkpointId"], "santiago-001")
            self.assertEqual(store.image("santiago-001")[0].read_bytes(), PNG_1X1)
            self.assertEqual(len(store.list()), 1)

    def test_runtime_accepts_reached_postcard_and_serves_binary(self):
        with tempfile.TemporaryDirectory() as directory:
            server = create_server(
                "127.0.0.1",
                0,
                database_path=Path(directory) / "live-workout.sqlite",
                plan_path=ROOT / "data" / "live-workout-plan.json",
                postcard_dir=Path(directory) / "postcards",
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            host, port = server.server_address
            base = f"http://{host}:{port}/api/live-workout/journey/postcards"
            try:
                preflight = urllib.request.Request(base, method="OPTIONS", headers={
                    "Origin": "http://localhost:5173",
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Private-Network": "true",
                })
                with urllib.request.urlopen(preflight, timeout=5) as response:
                    self.assertEqual(response.status, 204)
                    self.assertEqual(response.headers.get("Access-Control-Allow-Origin"), "http://localhost:5173")
                    self.assertEqual(response.headers.get("Access-Control-Allow-Private-Network"), "true")

                body = json.dumps({
                    "checkpointId": "santiago-001",
                    "filename": "krakow.png",
                    "mimeType": "image/png",
                    "dataBase64": base64.b64encode(PNG_1X1).decode("ascii"),
                }).encode("utf-8")
                request = urllib.request.Request(
                    base, data=body, headers={"Content-Type": "text/plain;charset=UTF-8", "Origin": "http://localhost:5173"}, method="POST"
                )
                with urllib.request.urlopen(request, timeout=5) as response:
                    uploaded = json.load(response)
                    self.assertEqual(response.headers.get("Access-Control-Allow-Origin"), "http://localhost:5173")
                self.assertTrue(uploaded["ok"])

                with urllib.request.urlopen(base, timeout=5) as response:
                    listing = json.load(response)
                self.assertEqual(listing["postcards"][0]["checkpointId"], "santiago-001")

                with urllib.request.urlopen(f"{base}/santiago-001/image", timeout=5) as response:
                    self.assertEqual(response.headers.get_content_type(), "image/png")
                    self.assertEqual(response.read(), PNG_1X1)

                locked_body = json.dumps({
                    "checkpointId": "santiago-365",
                    "filename": "future.png",
                    "mimeType": "image/png",
                    "dataBase64": base64.b64encode(PNG_1X1).decode("ascii"),
                }).encode("utf-8")
                locked_request = urllib.request.Request(
                    base, data=locked_body, headers={"Content-Type": "application/json"}, method="POST"
                )
                with urllib.request.urlopen(locked_request, timeout=5) as response:
                    locked_upload = json.load(response)
                self.assertTrue(locked_upload["ok"])
                self.assertEqual(locked_upload["postcard"]["checkpointId"], "santiago-365")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
