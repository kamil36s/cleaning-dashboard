import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path

from phone_tracker import PhoneTrackerStore, notification_attribution, reconstruct, time_window, location_breakdown, battery_exposure
from phone_tracker_rules import evaluate_expression


def event(kind, at, package=None, event_id=None):
    return {
        "event_id": event_id or str(uuid.uuid4()), "timestamp": at,
        "event_type": kind, "package_name": package, "app_name": package,
        "metadata": {},
    }


class PhoneTrackerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = PhoneTrackerStore(Path(self.temp.name) / "phone.sqlite")
        self.pairing = self.store.pair("Redmi")

    def tearDown(self):
        self.temp.cleanup()

    def sync(self, events, batch_id=None):
        return self.store.ingest({
            "schema_version": 1, "device_id": self.pairing["device_id"],
            "batch_id": batch_id or str(uuid.uuid4()), "sent_at": "2026-09-26T12:00:00Z",
            "events": events,
        })

    def test_duplicate_batch_and_crash_retry_with_new_batch(self):
        one = event("unlock", "2026-09-26T10:00:00Z")
        batch = str(uuid.uuid4())
        first = self.sync([one], batch)
        self.assertEqual(first["accepted"], [one["event_id"]])
        self.assertEqual(self.sync([one], batch), first)
        self.assertEqual(self.sync([one])["duplicates"], [one["event_id"]])
        self.assertEqual(len(self.store.events()), 1)

    def test_bad_events_are_rejected_without_losing_good_events(self):
        good = event("unlock", "2026-09-26T10:00:00Z")
        bad = event("unknown", "2026-09-26T10:01:00Z")
        result = self.sync([bad, good])
        self.assertEqual(result["accepted"], [good["event_id"]])
        self.assertEqual(result["rejected"][0]["event_id"], bad["event_id"])
        self.assertEqual(len(self.store.events()), 1)

    def test_session_reconstruction_closes_on_switch_and_screen_off(self):
        events = [event("unlock", "2026-09-26T10:00:00Z"),
                  event("app_foreground", "2026-09-26T10:01:00Z", "a"),
                  event("app_foreground", "2026-09-26T10:06:00Z", "b"),
                  event("screen_off", "2026-09-26T10:08:00Z")]
        apps, phones = reconstruct(events)
        self.assertEqual([a["seconds"] for a in apps], [300, 120])
        self.assertEqual(phones[0]["seconds"], 480)

    def test_notification_attribution_uses_nearest_unused_same_package(self):
        notification = event("notification_posted", "2026-09-26T10:00:00Z", "a")
        other = event("notification_posted", "2026-09-26T10:00:10Z", "b")
        open_a = event("app_foreground", "2026-09-26T10:00:37Z", "a")
        second_open = event("app_foreground", "2026-09-26T10:00:50Z", "a")
        matches = notification_attribution([notification,other,open_a,second_open],120)
        self.assertEqual(len(matches),1)
        self.assertEqual(matches[0]["latency_seconds"],37)

    def test_local_day_window_respects_dst_and_clips_cross_midnight_session(self):
        begin, end = time_window("today", "Europe/Warsaw", now=datetime(2026,3,29,12,tzinfo=timezone.utc))
        self.assertEqual(begin,"2026-03-28T23:00:00.000Z")
        self.assertEqual(end,"2026-03-29T22:00:00.000Z")
        events = [event("app_foreground","2026-03-28T22:55:00Z","a"),
                  event("app_background","2026-03-28T23:05:00Z","a")]
        self.sync(events)
        summary = self.store.summary("custom","Europe/Warsaw",start="2026-03-29",end="2026-03-29")
        self.assertEqual(summary["screen_time_seconds"],300)
        self.assertEqual(summary["hourly_usage_seconds"][0],300)

    def test_sample_data_remains_separate(self):
        self.store.generate_sample(1,"Europe/Warsaw")
        self.assertEqual(self.store.summary("today","Europe/Warsaw")["screen_time_seconds"],0)
        self.assertGreater(self.store.summary("today","Europe/Warsaw",sample=True)["screen_time_seconds"],0)
        self.assertEqual(self.store.clear_sample()["deleted"],20)

    def test_rules_are_declarative_and_config_sent_to_phone(self):
        definition = {"name":"Instagram limit","target":"com.instagram.android","action":"block",
                      "when":{"all":[{"metric":"app_usage_today","operator":">=","value":45,"unit":"minutes"},
                                     {"not":{"metric":"external:bike_done","operator":"==","value":True}}]}}
        rule = self.store.save_rule(self.pairing["device_id"],definition)
        self.store.set_external_condition(self.pairing["device_id"],"bike_done",False)
        self.assertTrue(evaluate_expression(rule["when"],{"app_usage_today":50,"external:bike_done":False}))
        self.assertFalse(evaluate_expression(rule["when"],{"app_usage_today":50,"external:bike_done":True}))
        config = self.store.config(self.pairing["device_id"])
        self.assertEqual(config["rules"][0]["rule_id"],rule["rule_id"])
        self.assertFalse(config["external_conditions"]["bike_done"])

    def test_cleaning_goal_condition_carries_its_day_for_phone_expiry(self):
        device_id = self.pairing["device_id"]
        self.store.set_external_condition(device_id,"cleaning_done_today",True)
        config = self.store.config(device_id)
        self.assertTrue(config["external_conditions"]["cleaning_done_today"])
        self.assertRegex(config["external_condition_dates"]["cleaning_done_today"],r"^\d{4}-\d{2}-\d{2}$")

    def test_override_policy_hashes_pin_and_reaches_phone_config(self):
        device_id = self.pairing["device_id"]
        policy = self.store.set_override_policy(device_id, {"mode":"pin","duration_minutes":7,
                                                            "cooldown_minutes":0,"pin":"1234"})
        self.assertEqual(policy, {"mode":"pin","duration_minutes":7,"cooldown_minutes":0})
        config_policy = self.store.config(device_id)["override_policy"]
        self.assertEqual(config_policy["mode"],"pin")
        self.assertEqual(config_policy["duration_minutes"],7)
        self.assertNotIn("1234",str(config_policy))
        self.assertEqual(len(config_policy["pin_hash"]),64)
        with self.assertRaises(ValueError):
            self.store.set_override_policy(device_id, {"mode":"pin","pin":"12"})

    def test_retention_scrubs_notification_content_and_keeps_event(self):
        old = event("notification_posted","2026-01-01T10:00:00Z","a")
        old["metadata"] = {"title":"private","text":"message","notification_key":"key"}
        self.sync([old])
        self.store.prune_retention(force=True)
        stored = self.store.events(start="2026-01-01T00:00:00Z",end="2026-01-02T00:00:00Z")
        self.assertEqual(len(stored),1)
        self.assertNotIn("text",stored[0]["metadata"])
        self.assertEqual(stored[0]["metadata"]["notification_key"],"key")

    def test_location_dwell_is_lower_bound_from_same_cell_only(self):
        points = [event("location","2026-09-26T10:00:00Z"),event("location","2026-09-26T10:30:00Z")]
        for point in points:
            point["metadata"] = {"latitude":52.23,"longitude":21.01,"accuracy_m":80}
        sessions = [{"start":"2026-09-26T10:10:00Z","end":"2026-09-26T10:20:00Z","seconds":600}]
        place = location_breakdown(points,sessions)[0]
        self.assertEqual(place["dwell_seconds_lower_bound"],1800)
        self.assertEqual(place["screen_time_seconds_estimate"],600)

    def test_revocation_keeps_history_but_disables_token(self):
        self.sync([event("unlock","2026-09-26T10:00:00Z")])
        self.assertTrue(self.store.authenticate(self.pairing["device_id"],self.pairing["token"]))
        self.store.revoke(self.pairing["device_id"])
        self.assertFalse(self.store.authenticate(self.pairing["device_id"],self.pairing["token"]))
        self.assertEqual(len(self.store.events()),1)

    def test_battery_exposure_is_time_weighted_estimate(self):
        first = event("battery","2026-09-26T10:00:00Z")
        second = event("battery","2026-09-26T11:00:00Z")
        first["metadata"] = {"percent":80,"charging":False}
        second["metadata"] = {"percent":78,"charging":False}
        sessions = [{"start":"2026-09-26T10:00:00Z","end":"2026-09-26T10:30:00Z",
                     "package_name":"a","device_id":None}]
        estimate = battery_exposure([first,second],sessions)
        self.assertEqual(estimate["observed_drop_percent"],2)
        self.assertEqual(estimate["estimated_exposure_percent_by_package"]["a"],1)

    def test_delete_all_removes_pairing_and_history(self):
        self.sync([event("unlock","2026-09-26T10:00:00Z")])
        result = self.store.delete_all()
        self.assertEqual(result["deleted_events"],1)
        self.assertFalse(self.store.authenticate(self.pairing["device_id"],self.pairing["token"]))
        self.assertEqual(self.store.events(),[])


if __name__ == "__main__":
    unittest.main()
