import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from phone_tracker import PhoneTrackerStore
from phone_tracker_access import (PhoneAccessStore, default_policy, reward_progress,
                                  reduced_baseline, extra_reading_bonus)


class Reading:
    def __init__(self):
        self.read = 0
        self.target = 20

    def state(self):
        return {"dailyStats": {"todayRead": self.read, "todayTarget": self.target}}


class Cleaning:
    def __init__(self):
        self.done = 0
        self.previous_day_actions = 0

    def get_settings(self):
        return {"activeApartmentId": "home"}

    def get_state(self, apartment_id):
        return {}

    def count_actions_for_day(self, apartment_id, day):
        if day == (datetime.now(ZoneInfo("Europe/Warsaw")).date()-timedelta(days=1)).isoformat():
            return self.previous_day_actions
        return self.done


class PhoneAccessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.tracker = PhoneTrackerStore(Path(self.temp.name) / "phone.sqlite")
        self.device = self.tracker.pair("Test phone")["device_id"]
        self.reading = Reading()
        self.cleaning = Cleaning()
        self.access = PhoneAccessStore(self.tracker, self.reading, self.cleaning)
        self.access.set_cleaning_target("home", self.access.day(), 10)
        policy = default_policy()
        policy["baseline"]["mode"] = "manual"
        policy["baseline"]["manual_minutes"] = 100
        policy["reduction"]["enabled"] = False
        self.access.save_policy(self.device, policy)

    def tearDown(self):
        self.temp.cleanup()

    def test_minimum_progress_and_rollback_do_not_reset_usage(self):
        policy = self.access.policies(self.device)[0]
        self.assertEqual(self.access.state(self.device,policy)["unlocked_minutes"],0)
        self.reading.read = 10
        self.cleaning.done = 5
        self.assertEqual(self.access.state(self.device,policy)["unlocked_minutes"],50)
        self.cleaning.done = 2
        self.assertEqual(self.access.state(self.device,policy)["unlocked_minutes"],20)
        self.assertEqual(self.access.state(self.device,policy)["highest_unlocked_minutes"],50)

    def test_recovery_day_uses_one_cleaning_task_despite_stale_target(self):
        self.cleaning.previous_day_actions = 15
        self.cleaning.done = 1
        self.reading.read = 20
        policy = self.access.policies(self.device)[0]
        state = self.access.state(self.device,policy)
        self.assertEqual(self.access.cleaning_target(self.access.day()),1)
        self.assertEqual(state["sources"]["cleaning"]["target_value"],1)
        self.assertEqual(state["sources"]["cleaning"]["progress"],1)
        self.assertEqual(state["normal_unlocked_minutes"],100)

    def test_no_plan_behavior_and_weighted_formula(self):
        self.assertEqual(reward_progress([(0.5,75),(1,25)],"weighted"),0.625)
        self.assertEqual(reward_progress([(0.5,50),(1,50)],"minimum"),0.5)
        self.reading.target = 0
        self.cleaning.done = 5
        policy = self.access.policies(self.device)[0]
        self.assertEqual(self.access.state(self.device,policy)["unlocked_minutes"],50)
        policy["sources"]["reading"]["no_plan"] = "zero"
        self.assertEqual(self.access.state(self.device,policy)["unlocked_minutes"],0)

    def test_progress_matrix_and_remaining_usage(self):
        policy = self.access.policies(self.device)[0]
        for read, clean, expected in [(0,0,0),(20,0,0),(0,10,0),(10,5,50),
                                      (16,2,20),(20,10,100)]:
            self.reading.read, self.cleaning.done = read, clean
            self.assertEqual(self.access.state(self.device,policy)["unlocked_minutes"],expected)

    def test_baseline_snapshot_and_manual_update(self):
        policy = self.access.policies(self.device)[0]
        self.assertEqual(self.access.state(self.device,policy)["baseline_minutes"],100)
        policy["baseline"]["manual_minutes"] = 45
        saved = self.access.save_policy(self.device,policy)
        self.assertEqual(saved["version"],2)
        self.assertEqual(self.access.state(self.device,saved)["baseline_minutes"],45)
        self.assertEqual(self.access.config(self.device)["version"],2)

    def test_automatic_baseline_uses_seven_completed_days(self):
        policy = default_policy("com.example.video")
        events = []
        today = datetime.now(ZoneInfo("Europe/Warsaw")).date()
        for days_ago in range(1,8):
            day = today - timedelta(days=days_ago)
            start = datetime.combine(day,time(12,0),ZoneInfo("Europe/Warsaw")).astimezone(timezone.utc)
            for kind, at in [("app_foreground",start),("app_background",start+timedelta(minutes=10))]:
                events.append({"event_id":str(uuid.uuid4()),"timestamp":at.isoformat().replace("+00:00","Z"),
                               "event_type":kind,"package_name":"com.example.video",
                               "app_name":"Video","metadata":{}})
        self.tracker.ingest({"schema_version":1,"device_id":self.device,"batch_id":str(uuid.uuid4()),
                             "sent_at":datetime.now(timezone.utc).isoformat(),"events":events})
        baseline, source = self.access._baseline(self.device,policy,today.isoformat())
        self.assertEqual(baseline,10)
        self.assertEqual(source,"7-day average")

    def test_compound_decay_floor_fixed_and_extra_page_thresholds(self):
        self.assertAlmostEqual(reduced_baseline(118,0,"compound_percentage",10,5,15),118)
        self.assertAlmostEqual(reduced_baseline(118,1,"compound_percentage",10,5,15),106.2)
        self.assertAlmostEqual(reduced_baseline(118,2,"compound_percentage",10,5,15),95.58)
        self.assertEqual(reduced_baseline(118,100,"compound_percentage",10,5,15),15)
        self.assertEqual(reduced_baseline(60,3,"fixed_minutes",10,5,15),45)
        self.assertEqual(reduced_baseline(60,50,"fixed_minutes",10,5,15),15)
        settings = default_policy()["extra_reading"]
        for read, expected in ((29,0),(30,0),(39,0),(40,2),(50,4),(80,10),(100,10)):
            self.assertEqual(extra_reading_bonus(read,30,settings)[1],expected)
        self.assertEqual(extra_reading_bonus(100,None,settings),(0,0))
        settings["partial_rewards"] = True
        self.assertEqual(extra_reading_bonus(35,30,settings),(5,1.0))

    def _start_plan(self, days_ago=0, mode="compound_percentage"):
        policy = self.access.policies(self.device)[0]
        policy["reduction"].update({"enabled":True,"start_source":"manual",
                                    "manual_start_minutes":118,"type":mode})
        saved = self.access.save_policy(self.device,policy)
        start = (datetime.now(ZoneInfo("Europe/Warsaw")).date()-timedelta(days=days_ago)).isoformat()
        with self.tracker._connect() as db:
            db.execute("UPDATE app_access_reduction_plans SET start_date=? WHERE device_id=? AND target=?",
                       (start,self.device,saved["target"]))
        return saved

    def test_day_seven_reduction_reading_bonus_and_cleaning_gate(self):
        policy = self._start_plan(7)
        self.reading.target,self.reading.read = 30,50
        self.cleaning.done = 3
        self.access.set_cleaning_target("home",self.access.day(),4)
        from unittest import mock
        with mock.patch.object(self.access,"_used_minutes",return_value=31):
            state = self.access.state(self.device,policy)
        self.assertAlmostEqual(state["effective_base_cap_exact_minutes"],56.4390,places=2)
        self.assertEqual(state["effective_base_cap_minutes"],56)
        self.assertEqual(state["normal_unlocked_minutes"],42)
        self.assertEqual(state["extra_reading_pages"],20)
        self.assertEqual(state["extra_reading_bonus_minutes"],4)
        self.assertEqual(state["total_unlocked_minutes"],46)
        self.assertEqual(state["remaining_minutes"],15)
        self.assertEqual(state["reduction_plan"]["day"],7)

    def test_pause_resume_freezes_reduction_days(self):
        policy = self._start_plan(4)
        paused = self.access.plan_action(self.device,policy["target"],"pause")
        day4 = paused["effective_base_cap_minutes"]
        today = datetime.now(ZoneInfo("Europe/Warsaw")).date()
        self.access.day = lambda: (today+timedelta(days=3)).isoformat()
        paused_later = self.access.state(self.device,policy)
        self.assertEqual(paused_later["effective_base_cap_minutes"],day4)
        resumed = self.access.plan_action(self.device,policy["target"],"resume")
        self.assertEqual(resumed["effective_base_cap_minutes"],day4)
        self.access.day = lambda: (today+timedelta(days=4)).isoformat()
        next_day = self.access.state(self.device,policy)
        self.assertLess(next_day["effective_base_cap_minutes"],day4)
        self.assertGreater(self.access.config(self.device)["version"],policy["version"])

    def test_pause_keeps_cap_when_rate_is_edited(self):
        policy = self._start_plan(4)
        frozen = self.access.plan_action(self.device,policy["target"],"pause")["effective_base_cap_minutes"]
        policy["reduction"]["percentage_per_day"] = 20
        saved = self.access.save_policy(self.device,policy)
        self.assertEqual(self.access.state(self.device,saved)["effective_base_cap_minutes"],frozen)

    def test_reward_event_idempotency_and_rollback_reconciliation(self):
        policy = self._start_plan()
        self.reading.target,self.reading.read = 30,50
        self.cleaning.done = 10
        first = self.access.state(self.device,policy)
        self.access.state(self.device,policy)
        with self.tracker._connect() as db:
            count = db.execute("SELECT COUNT(*) FROM app_access_reward_events").fetchone()[0]
        self.assertEqual(count,2)
        self.reading.read = 40
        from unittest import mock
        with mock.patch.object(self.access,"_used_minutes",return_value=first["total_unlocked_minutes"]):
            rolled_back = self.access.state(self.device,policy)
        self.assertEqual(rolled_back["extra_reading_bonus_minutes"],2)
        self.assertEqual(rolled_back["effective_unlocked_minutes"],first["total_unlocked_minutes"])
        self.assertEqual(rolled_back["remaining_minutes"],0)
        with self.tracker._connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM app_access_reward_events").fetchone()[0],2)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM app_access_day_corrections WHERE kind='bonus_rollback'").fetchone()[0],1)

    def test_no_reading_plan_needs_explicit_standalone_target(self):
        policy = self._start_plan()
        self.reading.target,self.reading.read = 0,20
        self.cleaning.done = 10
        self.assertEqual(self.access.state(self.device,policy)["extra_reading_bonus_minutes"],0)
        policy["extra_reading"]["standalone_target_pages"] = 10
        self.assertEqual(self.access.state(self.device,policy)["extra_reading_bonus_minutes"],2)

    def test_legacy_policy_migrates_without_losing_day_history(self):
        policy = self.access.policies(self.device)[0]
        self.access.state(self.device,policy)
        old_version = policy["version"]
        import json
        with self.tracker._connect() as db:
            raw = json.loads(db.execute("SELECT config_json FROM app_access_policies").fetchone()[0])
            raw.pop("reduction"); raw.pop("extra_reading")
            db.execute("UPDATE app_access_policies SET config_json=?",(json.dumps(raw),))
        migrated = self.access.policies(self.device)[0]
        self.assertEqual(migrated["version"],old_version+1)
        self.assertTrue(migrated["reduction"]["enabled"])
        self.assertTrue(self.access.history(self.device,migrated["target"]))

    def test_config_version_and_history_breakdown(self):
        policy = self._start_plan()
        self.reading.target,self.reading.read = 30,40
        self.cleaning.done = 10
        before = self.access.config(self.device)
        policy["reduction"]["percentage_per_day"] = 12
        policy["extra_reading"]["daily_bonus_cap"] = 8
        saved = self.access.save_policy(self.device,policy)
        after = self.access.config(self.device)
        self.assertEqual(after["version"],before["version"]+1)
        self.assertEqual(after["policies"][0]["extra_reading"]["daily_bonus_cap"],8)
        self.assertEqual(after["policies"][0]["reduction"]["percentage_per_day"],12)
        self.assertEqual(saved["version"],after["version"])
        history = self.access.history(self.device,policy["target"])[0]
        self.assertIn("normal_unlocked_minutes",history)
        self.assertIn("extra_reading_bonus_minutes",history)
        self.assertEqual(history["reward_events"][0]["threshold"],10)


if __name__ == "__main__":
    unittest.main()
