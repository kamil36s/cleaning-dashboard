import unittest
from datetime import date

from phone_tracker_insights import conditional_comparison, daily_facts, streaks_for_rules


def e(kind, at, package=None):
    return {"event_id":f"{kind}:{at}:{package}","device_id":"phone","timestamp":at,
            "event_type":kind,"package_name":package}


class PhoneTrackerInsightTests(unittest.TestCase):
    def test_daily_usage_is_clipped_to_local_midnight(self):
        events = [e("app_foreground","2026-03-28T22:55:00Z","instagram"),
                  e("app_background","2026-03-28T23:05:00Z","instagram"),
                  e("screen_off","2026-03-28T23:06:00Z")]
        days = daily_facts(events,"Europe/Warsaw")
        self.assertEqual(days["2026-03-28"]["app_seconds"]["instagram"],300)
        self.assertEqual(days["2026-03-29"]["app_seconds"]["instagram"],300)

    def test_streak_stops_on_unknown_day_instead_of_inventing_success(self):
        rules = [{"rule_id":"r1","name":"Instagram under 30m","target":"instagram","enabled":True,
                  "when":{"metric":"app_usage_today","operator":">=","value":30,"unit":"minutes"}}]
        daily = {"2026-09-25":{"usage_signal":True,"app_seconds":{"instagram":600},"app_launches":{}},
                 "2026-09-24":{"usage_signal":False,"app_seconds":{},"app_launches":{}}}
        result = streaks_for_rules(rules,daily,"Europe/Warsaw",today=date(2026,9,26))
        self.assertEqual(result[0]["days"],1)
        self.assertEqual(result[0]["stop_reason"],"no_coverage")

    def test_conditional_comparison_reports_both_denominators(self):
        rows = {
            "a":{"usage_signal":True,"notifications":120,"unlocks":5,"screen_time_seconds":3600,
                 "app_seconds":{},"app_launches":{}},
            "b":{"usage_signal":True,"notifications":20,"unlocks":2,"screen_time_seconds":1800,
                 "app_seconds":{},"app_launches":{}},
            "c":{"usage_signal":False,"notifications":200,"unlocks":0,"screen_time_seconds":0,
                 "app_seconds":{},"app_launches":{}},
        }
        result = conditional_comparison(rows,"notifications",">=",100,"screen_time")
        self.assertEqual(result["selected_days"],1)
        self.assertEqual(result["other_days"],1)
        self.assertEqual(result["selected_mean"],60)
        self.assertEqual(result["other_mean"],30)


if __name__ == "__main__":
    unittest.main()
