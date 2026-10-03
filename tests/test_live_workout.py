import json
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest import mock

import server
from live_workout_store import (
    HeartRateWearDetector,
    LiveWorkoutStore,
    estimate_training_metrics,
    filter_unworn_heart_rate_samples,
)


class LiveWorkoutPlanTests(unittest.TestCase):
    def test_plan_durations_are_consistent(self):
        plan = server.LIVE_WORKOUT_PLAN_SERVICE.response("2026-08-22")
        interval_minutes = sum(item["duration_minutes"] for item in plan["intervals"])
        zone_minutes = sum(plan["target_zones"].values())

        self.assertEqual(interval_minutes, plan["total_duration_minutes"])
        self.assertEqual(zone_minutes, plan["total_duration_minutes"])
        self.assertEqual(len(plan["schedule"]), 44)
        self.assertEqual(plan["summary"]["planned_minutes"], 2022)
        self.assertEqual(
            [week["planned_minutes"] for week in plan["weeks"]],
            [282, 315, 335, 275, 0, 410, 405],
        )
        for workout in plan["schedule"]:
            selected = server.LIVE_WORKOUT_PLAN_SERVICE.response(workout["date"])
            self.assertEqual(sum(selected["target_zones"].values()), selected["total_duration_minutes"])
            self.assertEqual(
                sum(interval["duration_minutes"] for interval in selected["intervals"]),
                selected["total_duration_minutes"],
            )
        self.assertEqual(
            set(plan["target_zones"]),
            {"light", "intensive", "aerobic", "anaerobic", "vo2max"},
            )

    def test_extended_cardio_block_has_expected_dates_and_no_duplicates(self):
        plan = server.LIVE_WORKOUT_PLAN_SERVICE.response("2026-09-18")
        schedule = plan["schedule"]
        by_date = {workout["date"]: workout for workout in schedule}

        self.assertEqual(len(by_date), len(schedule))
        self.assertEqual(schedule[0]["date"], "2026-08-22")
        self.assertEqual(schedule[-1]["date"], "2026-10-04")
        self.assertEqual(by_date["2026-09-18"]["duration"], 50)
        for day in ("2026-09-19", "2026-09-20"):
            self.assertEqual(by_date[day]["type"], "rest")
            self.assertEqual(by_date[day]["duration"], 0)
        self.assertEqual(
            sum(by_date[day]["duration"] for day in by_date if "2026-09-21" <= day <= "2026-09-27"),
            410,
        )
        self.assertEqual(
            sum(by_date[day]["duration"] for day in by_date if "2026-09-28" <= day <= "2026-10-04"),
            405,
        )
        for workout in schedule:
            self.assertEqual(sum(workout["zones"].values()), workout["duration"])


class HeartRateArchiveSourceTests(unittest.TestCase):
    def test_smartwatch_and_health_connect_reference_win_minute_by_minute(self):
        base = 1_788_343_200_000
        watch = [{
            "id": 1,
            "timestamp": base + 35_000,
            "received_at": base + 36_000,
            "heart_rate": 75,
            "status": "ready",
            "payload": {},
        }]
        ring_archive = {
            "heartRate": [
                {"id": 10, "timestampUtc": "2026-09-02T10:00:00Z", "bpm": 70},
                {"id": 11, "timestampUtc": "2026-09-02T10:01:00Z", "bpm": 71},
                {"id": 12, "timestampUtc": "2026-09-02T10:02:00Z", "bpm": 72},
                {"id": 13, "timestampUtc": "2026-09-02T10:02:40Z", "bpm": 73},
            ],
            "watchHeartRateReference": [
                {"timestampUtc": "2026-09-02T10:01:20Z", "bpm": 76},
            ],
        }

        merged = server.merge_heart_rate_archive_sources(watch, ring_archive)

        self.assertEqual(
            [sample["source"] for sample in merged],
            ["smart_ring", "smartwatch", "smartwatch"],
        )
        self.assertEqual([sample["heart_rate"] for sample in merged], [73, 76, 75])
        self.assertEqual(merged[1]["source_label"], "Smartwatch · Health Connect")


class LiveWorkoutConsoleSummaryTests(unittest.TestCase):
    def reset_stats(self):
        server.LIVE_WORKOUT_CONSOLE_STATS.update({
            "started_at": None,
            "requests": 0,
            "successes": 0,
            "failures": 0,
            "samples": 0,
            "sse_clients": 0,
        })

    def setUp(self):
        self.reset_stats()

    def tearDown(self):
        self.reset_stats()

    def test_results_are_silent_until_five_minute_summary(self):
        with mock.patch.object(server, "log_line") as log_line:
            self.assertIsNone(server.record_live_workout_console_result(True, samples=1, sse_clients=1, now=100))
            self.assertIsNone(server.record_live_workout_console_result(True, samples=2, sse_clients=1, now=399))
            message = server.record_live_workout_console_result(False, now=400)

        self.assertIn("requests=3", message)
        self.assertIn("success=66.7%", message)
        self.assertIn("samples=3", message)
        self.assertIn("errors=1", message)
        log_line.assert_called_once_with(message, tag="live-workout", level="warn")


class LiveWorkoutTelemetryTests(unittest.TestCase):
    def test_normalizes_valid_telemetry(self):
        payload = {"timestamp": 1_777_000_000_000, "heart_rate": 154, "status": "RUNNING"}
        self.assertEqual(
            server.normalize_live_workout_telemetry(payload),
            {"timestamp": payload["timestamp"], "heart_rate": 154, "status": "running"},
        )

    def test_rejects_invalid_heart_rate_and_timestamp(self):
        for payload in (
            {"timestamp": True, "heart_rate": 120, "status": "running"},
            {"timestamp": 123, "heart_rate": 241, "status": "running"},
            {"timestamp": 123, "heart_rate": 120, "status": "unknown"},
        ):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                server.normalize_live_workout_telemetry(payload)

    def test_normalizes_buffered_telemetry_before_processing(self):
        payload = [
            {"timestamp": 1_777_000_000_000, "heart_rate": 141, "status": "RUNNING"},
            {"timestamp": 1_777_000_001_000, "heart_rate": 143, "status": "running"},
        ]

        normalized, is_batch = server.normalize_live_workout_telemetry_payload(payload)

        self.assertTrue(is_batch)
        self.assertEqual(
            normalized,
            [
                {"timestamp": 1_777_000_000_000, "heart_rate": 141, "status": "running"},
                {"timestamp": 1_777_000_001_000, "heart_rate": 143, "status": "running"},
            ],
        )

    def test_rejects_entire_buffer_when_one_sample_is_invalid(self):
        payload = [
            {"timestamp": 1_777_000_000_000, "heart_rate": 141, "status": "running"},
            {"timestamp": 1_777_000_001_000, "heart_rate": 999, "status": "running"},
        ]

        with self.assertRaisesRegex(ValueError, r"telemetry\[1\].*heart_rate"):
            server.normalize_live_workout_telemetry_payload(payload)

    def test_broadcast_reaches_subscriber_and_becomes_latest_snapshot(self):
        previous_latest = server.LIVE_WORKOUT_LATEST
        subscriber = server.subscribe_live_workout()
        try:
            while not subscriber.empty():
                subscriber.get_nowait()
            payload = {"timestamp": 123, "heart_rate": 140, "status": "running"}
            server.broadcast_live_workout(payload)
            self.assertEqual(subscriber.get_nowait(), payload)
            self.assertEqual(server.LIVE_WORKOUT_LATEST, payload)
            self.assertEqual(server.latest_live_workout_telemetry(), payload)
        finally:
            server.unsubscribe_live_workout(subscriber)
            server.LIVE_WORKOUT_LATEST = previous_latest

    def test_post_endpoint_accepts_and_broadcasts_telemetry(self):
        payload = {"timestamp": 1_777_000_000_000, "heart_rate": 147, "status": "running"}
        raw = json.dumps(payload).encode("utf-8")
        handler = object.__new__(server.Handler)
        handler.path = "/api/live-workout/telemetry"
        handler.headers = {"Content-Length": str(len(raw)), "Content-Type": "application/json"}
        handler.client_address = ("127.0.0.1", 54321)
        handler.rfile = BytesIO(raw)
        handler._cors_origin = None
        handler.authorize_api_request = mock.Mock(return_value=True)
        handler.send_json = mock.Mock()

        with (
            mock.patch.object(server, "broadcast_live_workout", return_value=2) as broadcast,
            mock.patch.object(server.LIVE_WORKOUT_STORE, "archive_heart_rate") as archive,
            mock.patch.object(server.LIVE_WORKOUT_STORE, "ingest_dashboard", return_value={"id": "session-1"}) as ingest,
            mock.patch.object(server, "log_line") as log_line,
        ):
            handler.do_POST()

        archive.assert_called_once_with(payload)
        ingest.assert_called_once_with(payload)
        broadcast.assert_called_once_with(payload)
        handler.send_json.assert_called_once_with(
            {
                "ok": True,
                "telemetry": payload,
                "session_id": "session-1",
                "wear_state": "worn",
            },
            status=202,
        )
        messages = [call.args[0] for call in log_line.call_args_list]
        self.assertTrue(any("POST arrived" in message for message in messages))
        self.assertTrue(any('"heart_rate": 147' in message for message in messages))
        self.assertTrue(any("telemetry 202" in message and "SSE=2" in message for message in messages))

    def test_post_endpoint_accepts_buffered_telemetry_batch(self):
        payload = [
            {"timestamp": 1_777_000_000_000, "heart_rate": 147, "status": "running"},
            {"timestamp": 1_777_000_001_000, "heart_rate": 149, "status": "paused"},
        ]
        raw = json.dumps(payload).encode("utf-8")
        handler = object.__new__(server.Handler)
        handler.path = "/api/live-workout/telemetry"
        handler.headers = {"Content-Length": str(len(raw)), "Content-Type": "application/json"}
        handler.client_address = ("127.0.0.1", 54321)
        handler.rfile = BytesIO(raw)
        handler._cors_origin = None
        handler.authorize_api_request = mock.Mock(return_value=True)
        handler.send_json = mock.Mock()

        with (
            mock.patch.object(server, "broadcast_live_workout", return_value=1) as broadcast,
            mock.patch.object(server.LIVE_WORKOUT_STORE, "archive_heart_rates") as archive,
            mock.patch.object(
                server.LIVE_WORKOUT_STORE,
                "ingest_dashboard",
                side_effect=[{"id": "session-1"}, {"id": "session-1"}],
            ) as ingest,
            mock.patch.object(server, "log_line") as log_line,
        ):
            handler.do_POST()

        archive.assert_called_once_with(payload)
        self.assertEqual(ingest.call_args_list, [mock.call(payload[0]), mock.call(payload[1])])
        self.assertEqual(broadcast.call_args_list, [mock.call(payload[0]), mock.call(payload[1])])
        handler.send_json.assert_called_once_with(
            {
                "ok": True,
                "telemetry": payload[-1],
                "session_id": "session-1",
                "wear_state": "worn",
                "accepted": 2,
            },
            status=202,
        )
        messages = [call.args[0] for call in log_line.call_args_list]
        self.assertTrue(any("payload batch samples=2" in message for message in messages))
        self.assertTrue(any("telemetry 202" in message and "samples=2" in message for message in messages))

    def test_post_endpoint_suspends_flatline_storage_but_keeps_live_bpm_stream(self):
        payload = {"timestamp": 1_777_000_300_000, "heart_rate": 78, "status": "running"}
        raw = json.dumps(payload).encode("utf-8")
        handler = object.__new__(server.Handler)
        handler.path = "/api/live-workout/telemetry"
        handler.headers = {"Content-Length": str(len(raw)), "Content-Type": "application/json"}
        handler.client_address = ("127.0.0.1", 54321)
        handler.rfile = BytesIO(raw)
        handler._cors_origin = None
        handler.authorize_api_request = mock.Mock(return_value=True)
        handler.send_json = mock.Mock()
        wear = {
            "wear_state": "off_wrist",
            "became_off_wrist": True,
            "became_worn": False,
            "flatline_start": 1_777_000_000_000,
            "flatline_heart_rates": (78,),
            "timestamp": payload["timestamp"],
            "heart_rate": 78,
        }

        with (
            mock.patch.object(server.LIVE_WORKOUT_WEAR_DETECTOR, "observe", return_value=wear),
            mock.patch.object(server.LIVE_WORKOUT_STORE, "archive_heart_rate") as archive_one,
            mock.patch.object(server.LIVE_WORKOUT_STORE, "archive_heart_rates") as archive_many,
            mock.patch.object(server.LIVE_WORKOUT_STORE, "discard_heart_rate_flatline", return_value=301) as discard,
            mock.patch.object(server.LIVE_WORKOUT_STORE, "ingest_dashboard") as ingest,
            mock.patch.object(server, "broadcast_live_workout", return_value=1) as broadcast,
            mock.patch.object(server, "log_line"),
        ):
            handler.do_POST()

        archive_one.assert_not_called()
        archive_many.assert_not_called()
        ingest.assert_not_called()
        discard.assert_called_once_with(1_777_000_000_000, payload["timestamp"], (78,))
        broadcast.assert_called_once_with(payload)
        handler.send_json.assert_called_once_with({
            "ok": True,
            "telemetry": payload,
            "session_id": None,
            "wear_state": "off_wrist",
        }, status=202)

    def test_post_endpoint_rejects_batch_before_writing_any_invalid_sample(self):
        payload = [
            {"timestamp": 1_777_000_000_000, "heart_rate": 147, "status": "running"},
            {"timestamp": 1_777_000_001_000, "heart_rate": 999, "status": "running"},
        ]
        raw = json.dumps(payload).encode("utf-8")
        handler = object.__new__(server.Handler)
        handler.path = "/api/live-workout/telemetry"
        handler.headers = {"Content-Length": str(len(raw)), "Content-Type": "application/json"}
        handler.client_address = ("127.0.0.1", 54321)
        handler.rfile = BytesIO(raw)
        handler._cors_origin = None
        handler.authorize_api_request = mock.Mock(return_value=True)
        handler.send_json = mock.Mock()

        with (
            mock.patch.object(server, "broadcast_live_workout") as broadcast,
            mock.patch.object(server.LIVE_WORKOUT_STORE, "archive_heart_rate") as archive,
            mock.patch.object(server.LIVE_WORKOUT_STORE, "ingest_dashboard") as ingest,
            mock.patch.object(server, "log_line"),
        ):
            handler.do_POST()

        archive.assert_not_called()
        ingest.assert_not_called()
        broadcast.assert_not_called()
        handler.send_json.assert_called_once_with(
            {"error": "telemetry[1]: heart_rate must be an integer between 30 and 240", "code": "invalid_telemetry"},
            status=400,
        )

    def test_remote_watch_route_supports_existing_bearer_token_auth(self):
        handler = object.__new__(server.Handler)
        handler.headers = {"Authorization": "Bearer watch-token"}
        handler.client_address = ("192.168.0.50", 12345)
        handler._cors_origin = None
        handler.send_json = mock.Mock()

        with mock.patch.dict(server.os.environ, {"DASHBOARD_WRITE_TOKEN": "watch-token"}):
            allowed = handler.authorize_api_request(
                "/api/live-workout/telemetry",
                require_origin=True,
            )

        self.assertTrue(allowed)
        self.assertIsNone(handler._cors_origin)
        handler.send_json.assert_not_called()

    def test_remote_watch_gets_explicit_401_for_wrong_token(self):
        handler = object.__new__(server.Handler)
        handler.headers = {"Authorization": "Bearer wrong-token"}
        handler.client_address = ("192.168.0.46", 12345)
        handler._cors_origin = None
        handler.send_json = mock.Mock()

        with (
            mock.patch.object(server, "configured_live_workout_tokens", return_value={"correct-token"}),
            mock.patch.object(server, "log_line") as log_line,
        ):
            allowed = handler.authorize_api_request(
                "/api/live-workout/telemetry",
                require_origin=True,
            )

        self.assertFalse(allowed)
        handler.send_json.assert_called_once_with(
            {"error": "Invalid Live Workout bearer token", "code": "invalid_bearer_token"},
            status=401,
        )
        diagnostic = log_line.call_args.args[0]
        self.assertIn("supplied_fp=", diagnostic)
        self.assertIn("expected_fp=", diagnostic)
        self.assertNotIn("wrong-token", diagnostic)
        self.assertNotIn("correct-token", diagnostic)

    def test_remote_watch_gets_503_when_server_token_is_missing(self):
        handler = object.__new__(server.Handler)
        handler.headers = {"Authorization": "Bearer any-token"}
        handler.client_address = ("192.168.0.46", 12345)
        handler._cors_origin = None
        handler.send_json = mock.Mock()

        with (
            mock.patch.object(server, "configured_live_workout_tokens", return_value=set()),
            mock.patch.object(server, "log_line"),
        ):
            allowed = handler.authorize_api_request(
                "/api/live-workout/telemetry",
                require_origin=True,
            )

        self.assertFalse(allowed)
        handler.send_json.assert_called_once_with(
            {
                "error": "Live Workout bearer token is not configured on the server",
                "code": "live_workout_auth_not_configured",
            },
            status=503,
        )

    def test_dashboard_session_control_accepts_same_lan_host_origin(self):
        handler = object.__new__(server.Handler)
        handler.headers = {
            "Origin": "http://192.168.0.136:8000",
            "Host": "192.168.0.136:8000",
        }
        handler.client_address = ("192.168.0.136", 54321)
        handler._cors_origin = None
        handler.send_json = mock.Mock()

        allowed = handler.authorize_api_request("/api/live-workout/session", require_origin=True)

        self.assertTrue(allowed)
        self.assertEqual(handler._cors_origin, "http://192.168.0.136:8000")
        handler.send_json.assert_not_called()

    def test_history_endpoint_returns_persisted_sessions(self):
        handler = object.__new__(server.Handler)
        handler.path = "/api/live-workout/history?limit=6"
        handler.headers = {}
        handler._cors_origin = None
        handler.authorize_api_request = mock.Mock(return_value=True)
        handler.authorize_static_request = mock.Mock(return_value=True)
        handler.send_json = mock.Mock()
        sessions = [{"id": "workout-1"}]

        with mock.patch.object(server.LIVE_WORKOUT_STORE, "history", return_value=sessions) as history:
            handler.do_GET()

        history.assert_called_once_with(limit=6)
        handler.send_json.assert_called_once_with({"sessions": sessions})

    def test_heart_rate_history_endpoint_supports_time_filters(self):
        handler = object.__new__(server.Handler)
        handler.path = (
            "/api/live-workout/heart-rate-history"
            "?limit=250&from=1777000000000&to=1777003600000"
        )
        handler.headers = {}
        handler._cors_origin = None
        handler.authorize_api_request = mock.Mock(return_value=True)
        handler.authorize_static_request = mock.Mock(return_value=True)
        handler.send_json = mock.Mock()
        samples = [{"timestamp": 1_777_000_000_000, "heart_rate": 147}]

        with (
            mock.patch.object(
                server.LIVE_WORKOUT_STORE,
                "heart_rate_history",
                return_value=samples,
            ) as history,
            mock.patch.object(
                server.RING_COLLECTOR.store,
                "heart_rate_archive",
                return_value={"heartRate": [], "watchHeartRateReference": []},
            ) as ring_history,
        ):
            handler.do_GET()

        history.assert_called_once_with(
            limit=250,
            from_timestamp=1_777_000_000_000,
            to_timestamp=1_777_003_600_000,
        )
        ring_history.assert_called_once_with(
            limit=250,
            from_timestamp=1_777_000_000_000,
            to_timestamp=1_777_003_600_000,
        )
        handler.send_json.assert_called_once_with({
            "samples": [{**samples[0], "source": "smartwatch", "source_label": "Smartwatch"}],
            "sources": {"smartwatch": 1, "smartRing": 0},
        })

    def test_delete_endpoint_requires_confirmation_and_removes_virtual_steps(self):
        handler = object.__new__(server.Handler)
        handler.path = "/api/live-workout/session/dashboard-walk-1?confirm=delete"
        handler.headers = {}
        handler._cors_origin = None
        handler.authorize_api_request = mock.Mock(return_value=True)
        handler.send_json = mock.Mock()
        deleted = {"id": "dashboard-walk-1", "workout_type": "virtual_walk"}

        with (
            mock.patch.object(server.LIVE_WORKOUT_STORE, "delete_session", return_value=deleted) as delete_session,
            mock.patch.object(server, "remove_virtual_walk_steps", return_value=1050) as remove_steps,
            mock.patch.object(server, "log_line"),
        ):
            handler.do_DELETE()

        delete_session.assert_called_once_with("dashboard-walk-1")
        remove_steps.assert_called_once_with("dashboard-walk-1")
        handler.send_json.assert_called_once_with({
            "ok": True,
            "deleted": "dashboard-walk-1",
            "virtual_steps_removed": 1050,
        })


class LiveWorkoutStoreTests(unittest.TestCase):
    def test_calorie_ranking_sums_completed_cycling_sessions_by_day(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = LiveWorkoutStore(Path(temp_dir) / "workouts.sqlite")

            ranking = store.calorie_ranking()

            self.assertEqual(ranking[0]["date"], "2026-08-20")
            self.assertEqual(ranking[0]["active_calories"], 713)
            self.assertEqual(ranking[0]["session_count"], 3)
            self.assertEqual(ranking[0]["cycling_calories"], 713)
            self.assertEqual(ranking[0]["walking_calories"], 0)
            self.assertEqual(ranking[0]["position"], 1)
            august_21 = next(day for day in ranking if day["date"] == "2026-08-21")
            self.assertEqual(august_21["active_calories"], 619)
            self.assertEqual(august_21["session_count"], 2)

    def test_calorie_ranking_includes_virtual_walks_and_keeps_breakdown(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = LiveWorkoutStore(Path(temp_dir) / "workouts.sqlite")
            store.import_summary({
                "id": "ranking-cycle",
                "started_at": 1_800_000_000_000,
                "duration_seconds": 600,
                "active_calories": 80,
                "workout_type": "indoor_cycling",
            })
            store.import_summary({
                "id": "ranking-walk",
                "started_at": 1_800_000_180_000,
                "duration_seconds": 600,
                "active_calories": 20,
                "workout_type": "virtual_walk",
            })

            day = next(item for item in store.calorie_ranking() if item["active_calories"] == 100)
            self.assertEqual(day["cycling_calories"], 80)
            self.assertEqual(day["walking_calories"], 20)
            self.assertEqual(day["duration_seconds"], 1200)
            self.assertEqual(day["cycling_session_count"], 1)
            self.assertEqual(day["walking_session_count"], 1)

    def test_detects_off_wrist_flatline_and_resumes_on_human_hr_change(self):
        detector = HeartRateWearDetector(
            minimum_duration_ms=5000,
            minimum_samples=6,
            maximum_gap_ms=1500,
        )
        start = 1_777_000_000_000

        states = [
            detector.observe({"timestamp": start + offset * 1000, "heart_rate": 78})
            for offset in range(6)
        ]
        resumed = detector.observe({"timestamp": start + 6000, "heart_rate": 79})

        self.assertEqual(states[-1]["wear_state"], "off_wrist")
        self.assertTrue(states[-1]["became_off_wrist"])
        self.assertEqual(states[-1]["flatline_start"], start)
        self.assertEqual(resumed["wear_state"], "worn")
        self.assertTrue(resumed["became_worn"])

    def test_live_detector_accepts_small_jitter_but_rejects_human_variability(self):
        detector = HeartRateWearDetector(
            minimum_duration_ms=10_000,
            minimum_samples=100,
            maximum_gap_ms=1500,
        )
        start = 1_777_000_000_000
        states = [
            detector.observe({
                "timestamp": start + offset * 100,
                "heart_rate": 79 if offset == 50 else 78,
            })
            for offset in range(101)
        ]
        resumed = detector.observe({"timestamp": start + 10_100, "heart_rate": 84})

        self.assertEqual(states[-1]["wear_state"], "off_wrist")
        self.assertEqual(states[-1]["flatline_heart_rates"], (78, 79))
        self.assertEqual(resumed["wear_state"], "worn")

    def test_filters_confirmed_flatline_from_history(self):
        start = 1_777_000_000_000
        flatline = [
            {"timestamp": start + offset * 1000, "heart_rate": 78}
            for offset in range(6)
        ]
        natural = [
            {"timestamp": start + 10_000 + offset * 1000, "heart_rate": 78 + offset % 2}
            for offset in range(6)
        ]

        filtered = filter_unworn_heart_rate_samples(
            natural + flatline,
            minimum_duration_ms=5000,
            minimum_samples=6,
            maximum_gap_ms=1500,
        )

        self.assertEqual(filtered, natural)

    def test_filters_sparse_near_flatline_but_preserves_jagged_human_signal(self):
        start = 1_777_000_000_000
        sparse_flatline = [
            {
                "timestamp": start + offset * 10_000,
                "heart_rate": 79 if offset == 45 else 78,
            }
            for offset in range(91)
        ]
        human = [
            {
                "timestamp": start + 20 * 60_000 + offset * 1000,
                "heart_rate": 68 + (offset * 7) % 19,
            }
            for offset in range(600)
        ]

        filtered = filter_unworn_heart_rate_samples(sparse_flatline + human)

        self.assertEqual(filtered, human)

    def test_archives_all_heart_rate_transmissions_without_a_workout_session(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "workouts.sqlite"
            store = LiveWorkoutStore(path)
            payload = {
                "timestamp": 1_777_000_000,
                "heart_rate": 147,
                "status": "RUNNING",
                "cadence_rpm": 83.5,
                "watch_battery": 72,
            }

            first = store.archive_heart_rate(payload, received_at=1_777_000_001_234)
            second = store.archive_heart_rate(payload, received_at=1_777_000_002_345)

            self.assertNotEqual(first["id"], second["id"])
            reopened = LiveWorkoutStore(path)
            history = reopened.heart_rate_history(limit=10)
            self.assertEqual(len(history), 2)
            self.assertEqual(history[0]["timestamp"], 1_777_000_000_000)
            self.assertEqual(history[0]["received_at"], 1_777_000_002_345)
            self.assertEqual(history[0]["heart_rate"], 147)
            self.assertEqual(history[0]["payload"], payload)

    def test_archives_batch_with_each_watch_timestamp_and_status(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = LiveWorkoutStore(Path(temp_dir) / "workouts.sqlite")
            payload = [
                {"timestamp": 1_777_000_000, "heart_rate": 147, "status": "RUNNING"},
                {"timestamp": 1_777_000_001, "heart_rate": 149, "status": "paused"},
                {"timestamp": 1_777_000_002, "heart_rate": 145, "status": "finished"},
            ]

            archived = store.archive_heart_rates(payload, received_at=1_777_000_010_000)
            history = store.heart_rate_history(limit=10)

            self.assertEqual(len(archived), 3)
            self.assertEqual(
                [(sample["timestamp"], sample["status"]) for sample in history],
                [
                    (1_777_000_002_000, "finished"),
                    (1_777_000_001_000, "paused"),
                    (1_777_000_000_000, "running"),
                ],
            )

    def test_filters_heart_rate_history_by_recorded_timestamp(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = LiveWorkoutStore(Path(temp_dir) / "workouts.sqlite")
            for offset in range(3):
                store.archive_heart_rate(
                    {
                        "timestamp": 1_777_000_000_000 + offset * 1000,
                        "heart_rate": 120 + offset,
                        "status": "running",
                    },
                    received_at=1_777_000_010_000 + offset,
                )

            history = store.heart_rate_history(
                limit=10,
                from_timestamp=1_777_000_001_000,
                to_timestamp=1_777_000_002_000,
            )

            self.assertEqual([sample["heart_rate"] for sample in history], [122, 121])

    def test_estimates_training_effect_and_recovery_from_actual_zones(self):
        metrics = estimate_training_metrics(
            {"light": 360, "intensive": 900, "aerobic": 1320, "anaerobic": 60, "vo2max": 0},
            duration_seconds=2640,
            training_load=102,
        )

        self.assertGreaterEqual(metrics["training_effect"]["aerobic"], 2)
        self.assertLess(metrics["training_effect"]["anaerobic"], 1)
        self.assertGreaterEqual(metrics["recovery_hours"], 12)
        self.assertTrue(metrics["training_effect"]["estimated"])

    def test_dashboard_session_controls_when_telemetry_is_recorded(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = LiveWorkoutStore(Path(temp_dir) / "workouts.sqlite")
            timestamp = 1_777_000_000_000

            self.assertIsNone(store.ingest_dashboard({"timestamp": timestamp, "heart_rate": 120, "status": "running"}))
            started = store.start_dashboard_session({"plan_date": "2026-08-22"}, timestamp=timestamp)
            first = store.ingest_dashboard({"timestamp": timestamp, "heart_rate": 120, "status": "running"})
            store.control_dashboard_session("pause", timestamp=timestamp + 1000)
            self.assertIsNone(store.ingest_dashboard({"timestamp": timestamp + 1000, "heart_rate": 130, "status": "running"}))
            store.control_dashboard_session("resume", timestamp=timestamp + 2000)
            store.ingest_dashboard({"timestamp": timestamp + 2000, "heart_rate": 130, "status": "running"})
            finished = store.control_dashboard_session(
                "finish",
                timestamp=timestamp + 3000,
                summary={
                    "active_calories": 8.79,
                    "active_calories_keytel_raw": 12.34,
                    "calorie_method": "indoor_cycling_mi_calibrated_v1",
                    "calorie_calibration_factor": .712,
                    "training_load": 4.5,
                    "interval_progress_seconds": [60, 120],
                    "plan_completed_at_elapsed": 180,
                    "plan_completed": True,
                },
            )

            self.assertEqual(first["id"], started["id"])
            self.assertEqual(finished["status"], "finished")
            self.assertEqual(finished["active_calories"], 8.79)
            self.assertEqual(finished["active_calories_keytel_raw"], 12.34)
            self.assertEqual(finished["calorie_method"], "indoor_cycling_mi_calibrated_v1")
            self.assertEqual(finished["calorie_calibration_factor"], .712)
            self.assertEqual(finished["interval_progress_seconds"], [60, 120])
            self.assertTrue(finished["plan_completed"])
            self.assertEqual(finished["training_load"], 4.5)
            self.assertIsNotNone(finished["training_effect"])
            self.assertIsNotNone(finished["recovery_hours"])
            self.assertEqual(store.session(started["id"])["sample_count"], 2)

    def test_virtual_walk_is_saved_with_symbolic_load_and_no_recovery_debt(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = LiveWorkoutStore(Path(temp_dir) / "workouts.sqlite")
            timestamp = 1_777_000_000_000
            started = store.start_dashboard_session(
                {"plan_id": "virtual-walk", "workout_type": "virtual_walk", "sub_type": "liss"},
                timestamp=timestamp,
            )
            finished = store.control_dashboard_session(
                "finish",
                timestamp=timestamp + 1_200_000,
                summary={
                    "duration_seconds": 1200,
                    "virtual_walk_active_seconds": 900,
                    "virtual_walk_outside_seconds": 300,
                    "virtual_steps": 1575,
                    "cadence_rpm_avg": 84.2,
                    "distance_km": 1.18125,
                },
            )

            self.assertEqual(finished["id"], started["id"])
            self.assertEqual(finished["workout_type"], "virtual_walk")
            self.assertEqual(finished["sub_type"], "liss")
            self.assertEqual(finished["virtual_steps"], 1575)
            self.assertEqual(finished["cadence_rpm_avg"], 84.2)
            self.assertAlmostEqual(store.journey_progress()["committed_distance_km"], 1.18125)
            self.assertEqual(finished["training_load"], 5.0)
            self.assertEqual(finished["recovery_hours"], 0)
            self.assertEqual(finished["training_effect"]["anaerobic"], 0.0)

    def test_rejects_second_start_and_invalid_session_transitions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = LiveWorkoutStore(Path(temp_dir) / "workouts.sqlite")
            started = store.start_dashboard_session(
                {"workout_type": "virtual_walk"},
                timestamp=1_777_000_000_000,
            )

            with self.assertRaisesRegex(ValueError, "already active"):
                store.start_dashboard_session({"workout_type": "strength"})
            with self.assertRaisesRegex(ValueError, "Cannot resume"):
                store.control_dashboard_session("resume", session_id=started["id"])
            with self.assertRaisesRegex(ValueError, "does not match"):
                store.control_dashboard_session("pause", session_id="stale-session")

            paused = store.control_dashboard_session("pause", session_id=started["id"])
            self.assertEqual(paused["status"], "paused")
            with self.assertRaisesRegex(ValueError, "Cannot pause"):
                store.control_dashboard_session("pause", session_id=started["id"])
            resumed = store.control_dashboard_session("resume", session_id=started["id"])
            self.assertEqual(resumed["status"], "running")

    def test_cancel_rejects_a_stale_session_id(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = LiveWorkoutStore(Path(temp_dir) / "workouts.sqlite")
            started = store.start_dashboard_session({}, timestamp=1_777_000_000_000)

            with self.assertRaisesRegex(ValueError, "does not match"):
                store.cancel_dashboard_session(session_id="stale-session")

            self.assertEqual(store.active_dashboard_session()["id"], started["id"])

    def test_strength_session_uses_existing_store_and_preserves_structured_execution(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = LiveWorkoutStore(Path(temp_dir) / "workouts.sqlite")
            timestamp = 1_777_000_000_000
            started = store.start_dashboard_session(
                {
                    "title": "Workout A",
                    "workout_type": "strength",
                    "sub_type": "a",
                    "plan_id": "strength-adaptation-2026-09",
                    "plan_date": "2026-09-05",
                    "strength_data": {"schemaVersion": 1, "workoutId": "A", "exercises": []},
                },
                timestamp=timestamp,
            )
            strength_data = {
                "schemaVersion": 1,
                "workoutId": "A",
                "timers": {"totalElapsed": 3120, "restTime": 780, "equipmentTransitionTime": 420},
                "exercises": [
                    {
                        "exerciseId": "dumbbell-floor-press",
                        "plannedSets": 2,
                        "completedSets": 2,
                        "sets": [
                            {"setNumber": 1, "actualWeightPerDumbbellKg": 7.5, "dumbbellCount": 2, "actualReps": 10, "actualRir": 3},
                            {"setNumber": 2, "actualWeightPerDumbbellKg": 7.5, "dumbbellCount": 2, "actualReps": 9, "actualRir": 2},
                        ],
                    }
                ],
            }
            finished = store.control_dashboard_session(
                "finish",
                timestamp=timestamp + 3_120_000,
                summary={
                    "duration_seconds": 3120,
                    "strength_data": strength_data,
                    "session_rpe": 7,
                    "notes": "Dobra technika.",
                    "plan_completed": True,
                },
            )

            self.assertEqual(started["workout_type"], "strength")
            self.assertEqual(finished["strength_data"], strength_data)
            self.assertEqual(finished["session_rpe"], 7)
            self.assertEqual(finished["notes"], "Dobra technika.")
            self.assertEqual(store.session(started["id"])["strength_data"]["exercises"][0]["sets"][0]["dumbbellCount"], 2)

    def test_cancel_removes_active_session_and_its_hr_samples(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = LiveWorkoutStore(Path(temp_dir) / "workouts.sqlite")
            timestamp = 1_777_000_000_000
            started = store.start_dashboard_session({"plan_id": "virtual-walk"}, timestamp=timestamp)
            store.ingest_dashboard({"timestamp": timestamp + 1000, "heart_rate": 105, "status": "running"})

            cancelled = store.cancel_dashboard_session()

            self.assertEqual(cancelled["id"], started["id"])
            self.assertIsNone(store.active_dashboard_session())
            self.assertIsNone(store.session(started["id"]))
            self.assertFalse(any(item["id"] == started["id"] for item in store.history(limit=100)))

    def test_backup_import_preserves_summary_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = LiveWorkoutStore(Path(temp_dir) / "workouts.sqlite")
            imported = store.import_summary(
                {
                    "id": "backup-workout-1",
                    "started_at": 1_777_000_000_000,
                    "duration_seconds": 120,
                    "active_calories": 20.5,
                    "training_load": 7.2,
                    "zones": {"light": 60, "intensive": 60, "aerobic": 0, "anaerobic": 0, "vo2max": 0},
                    "samples": [{"timestamp": 1_777_000_000_000, "heart_rate": 120}],
                }
            )

            self.assertEqual(imported["active_calories"], 20.5)
            self.assertEqual(imported["training_load"], 7.2)
            self.assertEqual(store.session(imported["id"])["sample_count"], 1)

    def test_seeds_screenshot_history_and_keeps_new_samples(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "workouts.sqlite"
            store = LiveWorkoutStore(path)
            history = store.history()

            self.assertEqual(len(history), 6)
            self.assertEqual(history[0]["active_calories"], 301)
            self.assertEqual(history[0]["zones"]["intensive"], 1258)

            started_at = 1_777_000_000_000
            first = store.ingest({"timestamp": started_at, "heart_rate": 100, "status": "running"})
            store.ingest({"timestamp": started_at + 1000, "heart_rate": 120, "status": "running"})
            finished = store.ingest({"timestamp": started_at + 2000, "heart_rate": 130, "status": "finished"})

            self.assertEqual(finished["id"], first["id"])
            self.assertEqual(finished["status"], "finished")
            self.assertEqual(finished["duration_seconds"], 2)
            self.assertEqual(finished["avg_hr"], 117)
            self.assertEqual(finished["max_hr"], 130)
            self.assertEqual(finished["zones"]["light"], 1)
            self.assertEqual(finished["zones"]["intensive"], 1)
            self.assertEqual(len(store.session(first["id"])["samples"]), 3)

            reopened = LiveWorkoutStore(path)
            self.assertIn(first["id"], {session["id"] for session in reopened.history()})

    def test_finished_status_can_close_the_last_sample_without_a_new_timestamp(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = LiveWorkoutStore(Path(temp_dir) / "workouts.sqlite")
            timestamp = 1_800_000_000_000
            running = store.ingest({"timestamp": timestamp, "heart_rate": 145, "status": "running"})
            finished = store.ingest({"timestamp": timestamp, "heart_rate": 145, "status": "finished"})

            self.assertEqual(finished["id"], running["id"])
            self.assertEqual(finished["status"], "finished")
            self.assertEqual(len(store.session(running["id"])["samples"]), 1)


if __name__ == "__main__":
    unittest.main()
