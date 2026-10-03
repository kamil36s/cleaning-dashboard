import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from live_workout_store import LiveWorkoutStore
from training_runtime import TrainingRuntime, create_server


ROOT = Path(__file__).resolve().parents[1]


class RuntimeHarness:
    def __init__(self, database_path):
        self.server = create_server(
            host="127.0.0.1",
            port=0,
            database_path=database_path,
            plan_path=ROOT / "data" / "live-workout-plan.json",
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}/api/live-workout"

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def request(self, path, method="GET", payload=None):
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            f"{self.base}{path}",
            data=data,
            headers={"Content-Type": "application/json"} if data is not None else {},
            method=method,
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))


class TrainingRuntimeLifecycleTests(unittest.TestCase):
    def test_csc_measurements_and_distance_checkpoints_survive_finish(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = RuntimeHarness(Path(temp_dir) / "runtime.sqlite")
            base = int(time.time() * 1000)
            try:
                _, started = runtime.request("/session", "POST", {
                    "action": "start", "request_id": "sensor-history", "timestamp": base,
                    "workout_type": "indoor_cycling",
                })
                session_id = started["session"]["id"]
                event = {
                    "id": "csc-1", "timestamp": base + 1000, "kind": "measurement",
                    "status": "connected", "mode": "CADENCE", "stale": False,
                    "rpm": 82, "speed_kmh": None, "distance_km": 0.02,
                    "distance_source": "cadence_virtual_distance_v1", "heart_rate": 130,
                }
                checkpoint = {
                    "action": "checkpoint", "session_id": session_id, "timestamp": base + 2000,
                    "distance_km": 0.02, "sensor_samples": [event],
                }
                runtime.request("/session", "POST", checkpoint)
                runtime.request("/session", "POST", checkpoint)
                runtime.request("/session", "POST", {
                    "action": "finish", "session_id": session_id, "timestamp": base + 3000,
                    "distance_km": 0.02, "sensor_samples": [{
                        **event, "id": "csc-2", "timestamp": base + 3000,
                        "kind": "distance", "status": "reconnecting", "stale": True,
                        "rpm": 0, "distance_source": "heart_rate_virtual_distance_v1",
                    }],
                })
                _, history = runtime.request(f"/history/{session_id}/sensors")
                self.assertEqual(len(history["samples"]), 2)
                self.assertEqual(history["samples"][0]["cadence_rpm"], 82)
                self.assertEqual(history["samples"][1]["csc_status"], "reconnecting")
                self.assertEqual(history["samples"][1]["distance_km"], 0.02)
            finally:
                runtime.close()

    def test_calorie_ranking_endpoint_returns_daily_totals(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = RuntimeHarness(Path(temp_dir) / "runtime.sqlite")
            try:
                status, payload = runtime.request("/calorie-ranking")
                self.assertEqual(status, 200)
                self.assertEqual(payload["total_days"], 3)
                self.assertEqual(payload["days"][0]["date"], "2026-08-20")
                self.assertEqual(payload["days"][0]["active_calories"], 713)
                self.assertEqual(payload["days"][0]["cycling_calories"], 713)
                self.assertEqual(payload["days"][0]["walking_calories"], 0)
                self.assertEqual(payload["days"][0]["duration_seconds"], 4294)
            finally:
                runtime.close()

    def test_start_pause_resume_finish_and_cancel_matrix(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = RuntimeHarness(Path(temp_dir) / "runtime.sqlite")
            base = int(time.time() * 1000)
            try:
                _, started = runtime.request("/session", "POST", {
                    "action": "start", "request_id": "matrix-finish", "timestamp": base,
                    "workout_type": "indoor_cycling",
                })
                session_id = started["session"]["id"]

                _, paused = runtime.request("/session", "POST", {
                    "action": "pause", "session_id": session_id, "timestamp": base + 10_000,
                })
                self.assertEqual(paused["session"]["status"], "paused")
                paused_duration = paused["session"]["duration_seconds"]
                _, still_paused = runtime.request("/session")
                self.assertEqual(still_paused["session"]["duration_seconds"], paused_duration)

                runtime.request("/telemetry", "POST", {
                    "timestamp": base + 20_000, "heart_rate": 111, "status": "running",
                })
                _, paused_detail = runtime.request(f"/history/{session_id}")
                self.assertEqual(paused_detail["sample_count"], 0)

                _, resumed = runtime.request("/session", "POST", {
                    "action": "resume", "session_id": session_id, "timestamp": base + 30_000,
                })
                self.assertEqual(resumed["session"]["status"], "running")
                runtime.request("/telemetry", "POST", {
                    "timestamp": base + 31_000, "heart_rate": 135, "status": "running",
                })
                _, finished = runtime.request("/session", "POST", {
                    "action": "finish", "session_id": session_id, "timestamp": base + 40_000,
                })
                self.assertEqual(finished["session"]["status"], "finished")
                self.assertEqual(finished["session"]["sample_count"], 1)

                _, second = runtime.request("/session", "POST", {
                    "action": "start", "request_id": "matrix-cancel", "timestamp": base + 50_000,
                    "workout_type": "indoor_cycling",
                })
                cancelled_id = second["session"]["id"]
                runtime.request("/telemetry", "POST", {
                    "timestamp": base + 51_000, "heart_rate": 140, "status": "running",
                })
                _, cancelled = runtime.request("/session", "POST", {
                    "action": "cancel", "session_id": cancelled_id, "timestamp": base + 52_000,
                })
                self.assertEqual(cancelled["session"]["id"], cancelled_id)
                _, active = runtime.request("/session")
                self.assertIsNone(active["session"])
                _, history = runtime.request("/history?limit=200")
                self.assertFalse(any(item["id"] == cancelled_id for item in history["sessions"]))
                self.assertTrue(any(item["id"] == session_id for item in history["sessions"]))

                # Workout cancellation removes only the workout record/samples.
                # Every accepted watch transmission must remain in global HR history,
                # including telemetry received while paused and during a cancelled run.
                _, heart_rate_history = runtime.request(
                    f"/heart-rate-history?limit=100&from={base}&to={base + 60_000}"
                )
                self.assertEqual(
                    [sample["heart_rate"] for sample in heart_rate_history["samples"]],
                    [140, 135, 111],
                )
                self.assertTrue(all(
                    sample["source"] == "smartwatch"
                    for sample in heart_rate_history["samples"]
                ))
            finally:
                runtime.close()

    def test_legacy_dashboard_ingest_is_visible_to_the_runtime(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "runtime.sqlite"
            runtime = RuntimeHarness(database)
            legacy_store = LiveWorkoutStore(database)
            base = int(time.time() * 1000)
            try:
                _, started = runtime.request("/session", "POST", {
                    "action": "start", "request_id": "legacy-watch", "timestamp": base,
                    "workout_type": "indoor_cycling",
                })
                # This is the same store call used by the retained :8000 telemetry
                # endpoint. It proves old watch senders remain visible to :8766.
                legacy_telemetry = {
                    "timestamp": base + 1_000,
                    "heart_rate": 147,
                    "status": "running",
                    "cadence_rpm": 82,
                    "speed_kmh": 24.5,
                }
                legacy_store.archive_heart_rate(legacy_telemetry)
                legacy_store.ingest_dashboard(legacy_telemetry)

                _, latest = runtime.request("/latest")
                self.assertEqual(latest["telemetry"]["heart_rate"], 147)
                self.assertEqual(latest["telemetry"]["cadence_rpm"], 82)
                _, detail = runtime.request(f"/history/{started['session']['id']}")
                self.assertEqual(detail["sample_count"], 1)
                self.assertEqual(detail["samples"][0]["heart_rate"], 147)
                _, heart_rate_history = runtime.request(
                    f"/heart-rate-history?limit=10&from={base}&to={base + 2_000}"
                )
                self.assertEqual(len(heart_rate_history["samples"]), 1)
                self.assertEqual(heart_rate_history["samples"][0]["heart_rate"], 147)
                self.assertEqual(heart_rate_history["samples"][0]["payload"]["cadence_rpm"], 82)
            finally:
                runtime.close()

    def test_virtual_walk_finish_is_queued_for_dashboard_step_sync(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = TrainingRuntime(
                database_path=Path(temp_dir) / "runtime.sqlite",
                plan_path=ROOT / "data" / "live-workout-plan.json",
            )
            base = int(time.time() * 1000)
            started = runtime.control_session({
                "action": "start",
                "request_id": "walk-1",
                "timestamp": base,
                "workout_type": "virtual_walk",
            })
            runtime.control_session({
                "action": "finish",
                "session_id": started["id"],
                "timestamp": base + 60_000,
                "elapsed_seconds": 60,
                "virtual_steps": 105,
            })

            pending = runtime.store.pending_outbox()
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0]["event_type"], "virtual_walk_steps")
            self.assertEqual(pending[0]["payload"]["steps"], 105)

    def test_session_survives_dashboard_restarts_reconnect_and_runtime_recovery(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "live-workout.sqlite"
            runtime = RuntimeHarness(database)
            base = int(time.time() * 1000)
            try:
                start_payload = {
                    "action": "start",
                    "request_id": "browser-start-1",
                    "timestamp": base,
                    "title": "Integration ride",
                    "workout_type": "indoor_cycling",
                }
                _, first = runtime.request("/session", "POST", start_payload)
                _, duplicate = runtime.request("/session", "POST", start_payload)
                session_id = first["session"]["id"]
                self.assertEqual(duplicate["session"]["id"], session_id)

                for offset, heart_rate in ((1000, 101), (2000, 112), (3000, 123)):
                    runtime.request("/telemetry", "POST", {
                        "timestamp": base + offset,
                        "heart_rate": heart_rate,
                        "status": "running",
                    })
                runtime.request("/session", "POST", {
                    "action": "checkpoint",
                    "session_id": session_id,
                    "timestamp": base + 3500,
                    "elapsed_seconds": 3.5,
                    "active_calories": 2.25,
                    "zone_seconds": {"light": 1, "intensive": 2.5},
                })

                # A dashboard/Vite process has no ownership relationship with this
                # server. Multiple new clients represent dashboard restarts/reopens.
                for _restart in range(3):
                    _, rehydrated = runtime.request("/session")
                    self.assertEqual(rehydrated["session"]["id"], session_id)
                    self.assertGreaterEqual(rehydrated["session"]["duration_seconds"], 3.5)

                for offset, heart_rate in ((4000, 134), (5000, 145)):
                    runtime.request("/telemetry", "POST", {
                        "timestamp": base + offset,
                        "heart_rate": heart_rate,
                        "status": "running",
                    })
                _, latest = runtime.request("/latest")
                self.assertEqual(latest["telemetry"]["heart_rate"], 145)
            finally:
                runtime.close()

            # Runtime crash/restart recovery uses only the persisted SQLite file.
            recovered = RuntimeHarness(database)
            try:
                _, active = recovered.request("/session")
                self.assertEqual(active["session"]["id"], session_id)
                self.assertEqual(active["session"]["sample_count"], 5)
                _, latest = recovered.request("/latest")
                self.assertEqual(latest["telemetry"]["heart_rate"], 145)

                finish = {
                    "action": "finish",
                    "session_id": session_id,
                    "timestamp": base + 6000,
                    "elapsed_seconds": 6,
                    "active_calories": 4.5,
                    "zone_seconds": {"light": 1, "intensive": 5},
                }
                _, finished = recovered.request("/session", "POST", finish)
                _, duplicate_stop = recovered.request("/session", "POST", finish)
                self.assertEqual(finished["session"]["id"], session_id)
                self.assertEqual(duplicate_stop["session"]["id"], session_id)

                _, history = recovered.request("/history?limit=200")
                matches = [item for item in history["sessions"] if item["id"] == session_id]
                self.assertEqual(len(matches), 1)
                self.assertEqual(matches[0]["status"], "finished")
                _, detail = recovered.request(f"/history/{session_id}")
                self.assertEqual(len(detail["samples"]), 5)
                self.assertEqual([item["heart_rate"] for item in detail["samples"]], [101, 112, 123, 134, 145])
            finally:
                recovered.close()

    def test_runtime_process_outlives_restarted_dashboard_process(self):
        def free_port():
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                return sock.getsockname()[1]

        def wait_for(url, timeout=10):
            deadline = time.time() + timeout
            while time.time() < deadline:
                try:
                    with urllib.request.urlopen(url, timeout=1) as response:
                        if response.status == 200:
                            return
                except (OSError, urllib.error.URLError):
                    time.sleep(0.05)
            self.fail(f"Service did not become ready: {url}")

        def stop(process):
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)

        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_port = free_port()
            dashboard_port = free_port()
            env = {
                **os.environ,
                "TRAINING_RUNTIME_HOST": "127.0.0.1",
                "TRAINING_RUNTIME_PORT": str(runtime_port),
                "TRAINING_RUNTIME_DB": str(Path(temp_dir) / "runtime.sqlite"),
                "TRAINING_RUNTIME_PLAN": str(ROOT / "data" / "live-workout-plan.json"),
            }
            runtime_process = subprocess.Popen(
                [sys.executable, "-u", "training_runtime.py"],
                cwd=ROOT,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            dashboard_process = None
            try:
                runtime_base = f"http://127.0.0.1:{runtime_port}/api/live-workout"
                wait_for(f"{runtime_base}/health")

                dashboard_command = [
                    sys.executable, "-m", "http.server", str(dashboard_port),
                    "--bind", "127.0.0.1", "--directory", str(ROOT),
                ]
                dashboard_process = subprocess.Popen(
                    dashboard_command,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                wait_for(f"http://127.0.0.1:{dashboard_port}/")

                def runtime_request(path, payload=None):
                    data = json.dumps(payload).encode("utf-8") if payload else None
                    request = urllib.request.Request(
                        f"{runtime_base}{path}", data=data,
                        headers={"Content-Type": "application/json"} if data else {},
                        method="POST" if data else "GET",
                    )
                    with urllib.request.urlopen(request, timeout=5) as response:
                        return json.loads(response.read().decode("utf-8"))

                base = int(time.time() * 1000)
                started = runtime_request("/session", {
                    "action": "start", "request_id": "process-test", "timestamp": base,
                    "workout_type": "indoor_cycling",
                })["session"]
                runtime_request("/telemetry", {"timestamp": base + 1000, "heart_rate": 120, "status": "running"})

                for heart_rate, offset in ((130, 2000), (140, 3000)):
                    stop(dashboard_process)
                    dashboard_process = subprocess.Popen(
                        dashboard_command,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    wait_for(f"http://127.0.0.1:{dashboard_port}/")
                    runtime_request("/telemetry", {"timestamp": base + offset, "heart_rate": heart_rate, "status": "running"})
                    active = runtime_request("/session")["session"]
                    self.assertEqual(active["id"], started["id"])

                runtime_request("/session", {
                    "action": "finish", "session_id": started["id"],
                    "timestamp": base + 4000, "elapsed_seconds": 4,
                })
                detail = runtime_request(f"/history/{started['id']}")
                self.assertEqual([sample["heart_rate"] for sample in detail["samples"]], [120, 130, 140])
            finally:
                stop(dashboard_process)
                stop(runtime_process)


if __name__ == "__main__":
    unittest.main()
