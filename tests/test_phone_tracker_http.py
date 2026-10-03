import tempfile
import json
import threading
import unittest
import urllib.request
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from unittest import mock
from http.server import ThreadingHTTPServer

import server
from phone_tracker import PhoneTrackerStore


class PhoneTrackerHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = PhoneTrackerStore(Path(self.temp.name) / "phone.sqlite")
        self.pairing = self.store.pair("Redmi")
        self.patch = mock.patch.object(server, "PHONE_TRACKER", self.store)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def handler(self, token=None, ip="192.168.1.8"):
        handler = object.__new__(server.Handler)
        handler.headers = {"X-Phone-Device-ID": self.pairing["device_id"],
                           "Authorization": f"Bearer {token}" if token else ""}
        handler.client_address = (ip, 1234)
        handler.send_json = mock.Mock()
        handler._cors_origin = None
        return handler

    def test_remote_sync_needs_paired_token(self):
        self.assertFalse(self.handler().authorize_api_request("/api/phone-tracker/sync",True))
        self.assertTrue(self.handler(self.pairing["token"]).authorize_api_request("/api/phone-tracker/sync",True))
        self.assertFalse(self.handler(self.pairing["token"],"8.8.8.8").authorize_api_request("/api/phone-tracker/sync",True))

    def test_remote_raw_read_requires_dashboard_origin_and_config_requires_phone_token(self):
        raw = self.handler()
        self.assertFalse(raw.authorize_api_request("/api/phone-tracker/events",True))
        self.assertEqual(raw.send_json.call_args.kwargs["status"],403)
        config = self.handler()
        self.assertFalse(config.authorize_api_request("/api/phone-tracker/config",True))
        self.assertEqual(config.send_json.call_args.kwargs["status"],401)

    def test_sync_route_acknowledges_events(self):
        handler = self.handler(self.pairing["token"])
        event_id = str(uuid.uuid4())
        handler.read_json_body = mock.Mock(return_value={
            "schema_version": 1,"device_id":self.pairing["device_id"],
            "batch_id":str(uuid.uuid4()),"sent_at":"2026-09-26T10:00:00Z",
            "events":[{"event_id":event_id,"timestamp":"2026-09-26T10:00:00Z","event_type":"unlock"}],
        })
        self.assertTrue(handler.dispatch_phone_tracker_post("/api/phone-tracker/sync"))
        self.assertEqual(handler.send_json.call_args.args[0]["accepted"],[event_id])

    def test_plan_action_route_uses_local_admin_and_existing_store(self):
        handler = self.handler()
        handler.phone_tracker_local_admin = mock.Mock(return_value=True)
        handler.read_json_body = mock.Mock(return_value={
            "device_id":self.pairing["device_id"],"target":"com.instagram.android","action":"pause"})
        with mock.patch.object(server.PHONE_ACCESS,"plan_action",return_value={"paused":True}) as action:
            self.assertTrue(handler.dispatch_phone_tracker_post("/api/phone-tracker/access/plan"))
        action.assert_called_once_with(self.pairing["device_id"],"com.instagram.android","pause")
        self.assertEqual(handler.send_json.call_args.args[0],{"paused":True})

    def test_end_to_end_http_event_to_summary(self):
        httpd = ThreadingHTTPServer(("127.0.0.1",0),server.Handler)
        thread = threading.Thread(target=httpd.serve_forever,daemon=True)
        thread.start()
        root = f"http://127.0.0.1:{httpd.server_port}"
        try:
            def post(path, body, headers=None):
                request = urllib.request.Request(root+path,data=json.dumps(body).encode(),
                    headers={"Content-Type":"application/json",**(headers or {})},method="POST")
                with urllib.request.urlopen(request,timeout=5) as response:
                    return json.load(response)
            pairing = post("/api/phone-tracker/pair",{"label":"HTTP test"})
            event_id = str(uuid.uuid4())
            result = post("/api/phone-tracker/sync",{
                "schema_version":1,"device_id":pairing["device_id"],
                "batch_id":str(uuid.uuid4()),"sent_at":"2026-09-26T10:00:00Z",
                "events":[{"event_id":event_id,"timestamp":"2026-09-26T10:00:00Z","event_type":"unlock"}],
            },{"Authorization":f"Bearer {pairing['token']}","X-Phone-Device-ID":pairing["device_id"]})
            self.assertEqual(result["accepted"],[event_id])
            with urllib.request.urlopen(root+"/api/phone-tracker/summary?range=custom&tz=UTC&start=2026-09-26&end=2026-09-26",timeout=5) as response:
                summary = json.load(response)
            self.assertEqual(summary["unlocks"],1)
            policy = post("/api/phone-tracker/override-policy",{
                "device_id":pairing["device_id"],"mode":"pin","duration_minutes":7,
                "cooldown_minutes":0,"pin":"1234"})
            self.assertEqual(policy["mode"],"pin")
            with urllib.request.urlopen(root+"/api/phone-tracker/override-policy?device_id="+pairing["device_id"],timeout=5) as response:
                public_policy = json.load(response)
            self.assertNotIn("pin_hash",public_policy)
            config_request = urllib.request.Request(root+"/api/phone-tracker/config",headers={
                "Authorization":f"Bearer {pairing['token']}","X-Phone-Device-ID":pairing["device_id"]})
            with urllib.request.urlopen(config_request,timeout=5) as response:
                config = json.load(response)
            self.assertEqual(config["override_policy"]["duration_minutes"],7)
            self.assertEqual(len(config["override_policy"]["pin_hash"]),64)
            day = (datetime.now(ZoneInfo("Europe/Warsaw")) - timedelta(hours=6)).date().isoformat()
            with mock.patch.object(server.CLEANING_STORE,"count_actions_for_day",return_value=3):
                gate = post("/api/cleaning/phone-goal",{"apartmentId":"aleja-pokoju6","day":day,"target":3,"done":3})
            self.assertTrue(gate["complete"])
            self.assertTrue(self.store.config(pairing["device_id"])["external_conditions"]["cleaning_done_today"])
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
