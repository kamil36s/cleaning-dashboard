import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from live_workout_store import LiveWorkoutStore
from live_workout_tcx import parse_tcx


SUMMARY_TCX = b"""<?xml version="1.0" encoding="UTF-8"?>
<TrainingCenterDatabase creator="Mi Fitness" xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">
  <Activities><Activity Sport=""><Id>2026-08-22T09:06:21.000Z</Id><Calories>376</Calories>
    <Lap><TotalTimeSeconds>2513</TotalTimeSeconds><Calories>301</Calories><HeartRateBpm>126</HeartRateBpm></Lap>
  </Activity></Activities>
</TrainingCenterDatabase>"""


TRACKPOINT_TCX = b"""<?xml version="1.0" encoding="UTF-8"?>
<TrainingCenterDatabase creator="Mi Fitness" xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">
  <Activities><Activity Sport=""><Id>2027-01-02T10:00:00.000Z</Id><Calories>100</Calories>
    <Lap><TotalTimeSeconds>2</TotalTimeSeconds><Calories>80</Calories>
      <AverageHeartRateBpm><Value>130</Value></AverageHeartRateBpm>
      <MaximumHeartRateBpm><Value>150</Value></MaximumHeartRateBpm>
      <Track><Trackpoint><Time>2027-01-02T10:00:00.000Z</Time><HeartRateBpm><Value>100</Value></HeartRateBpm></Trackpoint>
      <Trackpoint><Time>2027-01-02T10:00:01.000Z</Time><HeartRateBpm><Value>120</Value></HeartRateBpm></Trackpoint>
      <Trackpoint><Time>2027-01-02T10:00:02.000Z</Time><HeartRateBpm><Value>150</Value></HeartRateBpm></Trackpoint></Track>
    </Lap>
  </Activity></Activities>
</TrainingCenterDatabase>"""


class LiveWorkoutTcxTests(unittest.TestCase):
    def test_reads_mi_fitness_summary_and_treats_exported_z_as_local_time(self):
        workout = parse_tcx(SUMMARY_TCX, "20260822Indoor cycling.tcx")
        expected = int(datetime.fromisoformat("2026-08-22T09:06:21+02:00").timestamp() * 1000)

        self.assertEqual(workout["started_at"], expected)
        self.assertEqual(workout["duration_seconds"], 2513)
        self.assertEqual(workout["active_calories"], 301)
        self.assertEqual(workout["total_calories"], 376)
        self.assertEqual(workout["avg_hr"], 126)
        self.assertIsNone(workout["max_hr"])
        self.assertEqual(workout["samples"], [])

    def test_tcx_summary_enriches_seed_without_losing_screenshot_only_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = LiveWorkoutStore(Path(temp_dir) / "history.sqlite")
            saved = store.import_summary(
                parse_tcx(SUMMARY_TCX, "20260822Indoor cycling.tcx")
            )

            self.assertEqual(saved["id"], "mi-fitness-2026-08-22-0906")
            self.assertEqual(saved["max_hr"], 185)
            self.assertEqual(saved["zones"]["intensive"], 1258)
            self.assertEqual(saved["data_quality"]["summary"], "tcx")
            self.assertEqual(saved["data_quality"]["max_hr"], "screenshot")
            self.assertEqual(saved["sample_count"], 0)

    def test_imports_trackpoints_when_a_future_tcx_contains_them(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = LiveWorkoutStore(Path(temp_dir) / "history.sqlite")
            saved = store.import_summary(parse_tcx(TRACKPOINT_TCX, "full.tcx"))
            detail = store.session(saved["id"])

            self.assertEqual(saved["sample_count"], 3)
            self.assertEqual(saved["max_hr"], 150)
            self.assertEqual(saved["zones"]["light"], 1)
            self.assertEqual(saved["zones"]["intensive"], 1)
            self.assertEqual(len(detail["samples"]), 3)


if __name__ == "__main__":
    unittest.main()
