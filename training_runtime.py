#!/usr/bin/env python3
"""Independent, durable runtime for active Live Workout sessions.

This process intentionally has no dependency on ``server.py``. Dashboard and Vite
may restart while this service keeps the workout clock, telemetry ingest, SSE and
active-session persistence alive.
"""

import hmac
import json
import os
import queue
import re
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from live_workout_plan import LiveWorkoutPlan
from live_workout_store import HeartRateWearDetector, LiveWorkoutStore
from journey_postcards import JourneyPostcardStore
from santiago_journey import SantiagoJourney


ROOT = Path(__file__).resolve().parent
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8766
MAX_BODY_BYTES = 25 * 1024 * 1024
MAX_TELEMETRY_SAMPLES = 250_000
SESSION_ID_RE = re.compile(r"[a-zA-Z0-9-]+")


def load_env_files(root=ROOT):
    """Load the repository's optional local env files without another dependency."""
    for path in (Path(root) / ".env", Path(root) / ".env.local"):
        if not path.exists():
            continue
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key and key not in os.environ:
                os.environ[key] = value.strip().strip('"').strip("'")


def normalize_telemetry(payload):
    if not isinstance(payload, dict):
        raise ValueError("JSON payload must be an object")
    timestamp = payload.get("timestamp")
    heart_rate = payload.get("heart_rate")
    status = str(payload.get("status") or "").strip().lower()
    if isinstance(timestamp, bool) or not isinstance(timestamp, int) or timestamp <= 0:
        raise ValueError("timestamp must be a positive integer")
    if isinstance(heart_rate, bool) or not isinstance(heart_rate, int) or not 30 <= heart_rate <= 240:
        raise ValueError("heart_rate must be an integer between 30 and 240")
    if status not in {"ready", "running", "paused", "finished"}:
        raise ValueError("status must be ready, running, paused or finished")
    normalized = {"timestamp": timestamp, "heart_rate": heart_rate, "status": status}
    cadence = payload.get("cadence_rpm")
    if cadence is not None:
        if isinstance(cadence, bool) or not isinstance(cadence, (int, float)) or not 0 <= cadence <= 250:
            raise ValueError("cadence_rpm must be a number between 0 and 250")
        normalized["cadence_rpm"] = round(float(cadence), 1)
    speed = payload.get("speed_kmh")
    if speed is not None:
        if isinstance(speed, bool) or not isinstance(speed, (int, float)) or not 0 <= speed <= 120:
            raise ValueError("speed_kmh must be a number between 0 and 120")
        normalized["speed_kmh"] = round(float(speed), 2)
    return normalized


def normalize_telemetry_payload(payload):
    if isinstance(payload, list):
        if not payload:
            raise ValueError("telemetry batch must contain at least one sample")
        if len(payload) > MAX_TELEMETRY_SAMPLES:
            raise ValueError(f"telemetry batch cannot exceed {MAX_TELEMETRY_SAMPLES} samples")
        return [normalize_telemetry(item) for item in payload], True
    return [normalize_telemetry(payload)], False


def session_summary(payload):
    return {
        "duration_seconds": payload.get("elapsed_seconds"),
        "zones": payload.get("zone_seconds"),
        "interval_progress_seconds": payload.get("interval_progress_seconds"),
        "plan_completed_at_elapsed": payload.get("plan_completed_at_elapsed"),
        "plan_completed": payload.get("plan_completed"),
        "active_calories": payload.get("active_calories"),
        "active_calories_keytel_raw": payload.get("active_calories_keytel_raw"),
        "calorie_method": payload.get("calorie_method"),
        "calorie_calibration_factor": payload.get("calorie_calibration_factor"),
        "training_load": payload.get("training_load"),
        "virtual_walk_active_seconds": payload.get("virtual_walk_active_seconds"),
        "virtual_walk_outside_seconds": payload.get("virtual_walk_outside_seconds"),
        "virtual_steps": payload.get("virtual_steps"),
        "cadence_rpm_avg": payload.get("cadence_rpm_avg"),
        "distance_km": payload.get("distance_km"),
        "strength_data": payload.get("strength_data"),
        "runtime_state": payload.get("runtime_state"),
        "session_rpe": payload.get("session_rpe"),
        "notes": payload.get("notes"),
    }


class TrainingRuntime:
    def __init__(self, database_path=None, plan_path=None, postcard_dir=None):
        self.store = LiveWorkoutStore(database_path or ROOT / "data" / "live-workout.sqlite")
        self.plan = LiveWorkoutPlan(plan_path or ROOT / "data" / "live-workout-plan.json")
        self.journey = None
        self.journey_error = None
        try:
            self.journey = SantiagoJourney(ROOT / "data" / "journeys" / "santiago")
        except Exception as exc:
            self.journey_error = f"{type(exc).__name__}: {exc}"
        self.postcards = JourneyPostcardStore(
            postcard_dir or ROOT / "data" / "journeys" / "santiago" / "postcards",
            [item["id"] for item in self.journey.checkpoints] if self.journey else [],
        )
        self.wear_detector = HeartRateWearDetector()
        self._subscribers = set()
        self._subscribers_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._outbox_thread = None

    def initialize(self):
        self.store.initialize()
        if not self._outbox_thread or not self._outbox_thread.is_alive():
            self._stop_event.clear()
            self._outbox_thread = threading.Thread(target=self._deliver_outbox, daemon=True, name="training-outbox")
            self._outbox_thread.start()

    def stop(self):
        self._stop_event.set()
        if self._outbox_thread:
            self._outbox_thread.join(timeout=3)
            self._outbox_thread = None

    def _deliver_outbox(self):
        dashboard_base = os.environ.get("DASHBOARD_API_BASE", "http://127.0.0.1:8000").rstrip("/")
        while not self._stop_event.is_set():
            for event in self.store.pending_outbox():
                if event["event_type"] != "virtual_walk_steps":
                    continue
                try:
                    body = json.dumps(event["payload"]).encode("utf-8")
                    request = urllib.request.Request(
                        f"{dashboard_base}/api/steps/events/upsert",
                        data=body,
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(request, timeout=3) as response:
                        if not 200 <= response.status < 300:
                            raise OSError(f"HTTP {response.status}")
                    self.store.mark_outbox(event["event_id"], True)
                except Exception as exc:
                    self.store.mark_outbox(event["event_id"], False, exc)
            self._stop_event.wait(10)

    def subscribe(self):
        subscriber = queue.Queue(maxsize=60)
        with self._subscribers_lock:
            self._subscribers.add(subscriber)
        latest = self.store.latest_heart_rate()
        if latest:
            subscriber.put_nowait(latest)
        return subscriber

    def unsubscribe(self, subscriber):
        with self._subscribers_lock:
            self._subscribers.discard(subscriber)

    def broadcast(self, payload):
        with self._subscribers_lock:
            subscribers = list(self._subscribers)
        for subscriber in subscribers:
            try:
                subscriber.put_nowait(dict(payload))
            except queue.Full:
                try:
                    subscriber.get_nowait()
                    subscriber.put_nowait(dict(payload))
                except queue.Empty:
                    pass
        return len(subscribers)

    def control_session(self, payload):
        action = str(payload.get("action") or "").strip().lower()
        if action == "start":
            return self.store.start_dashboard_session(
                {
                    "title": payload.get("title"),
                    "plan_id": payload.get("plan_id"),
                    "plan_date": payload.get("plan_date"),
                    "planned_duration_minutes": payload.get("planned_duration_minutes"),
                    "target_zones": payload.get("target_zones"),
                    "workout_type": payload.get("workout_type"),
                    "sub_type": payload.get("sub_type"),
                    "strength_data": payload.get("strength_data"),
                },
                timestamp=payload.get("timestamp"),
                request_id=payload.get("request_id"),
            )
        if action == "checkpoint":
            return self.store.checkpoint_dashboard_session(
                timestamp=payload.get("timestamp"),
                session_id=payload.get("session_id"),
                summary=session_summary(payload),
                sensor_samples=payload.get("sensor_samples"),
            )
        if action == "cancel":
            return self.store.cancel_dashboard_session(session_id=payload.get("session_id"))
        session = self.store.control_dashboard_session(
            action,
            timestamp=payload.get("timestamp"),
            session_id=payload.get("session_id"),
            summary=session_summary(payload),
            sensor_samples=payload.get("sensor_samples"),
        )
        if session is None and action == "finish" and payload.get("session_id"):
            previous = self.store.session(payload["session_id"])
            if previous and previous.get("status") == "finished":
                return previous
        if session and action == "finish" and session.get("workout_type") == "virtual_walk":
            started_at = int(session.get("started_at") or time.time() * 1000)
            self.store.enqueue_outbox(
                f"virtual-walk-finished:{session['id']}",
                "virtual_walk_steps",
                {
                    "day": time.strftime("%Y-%m-%d", time.localtime(started_at / 1000)),
                    "steps": session.get("virtual_steps") or 0,
                    "source": "virtual_walk",
                    "session_id": session["id"],
                    "duration_seconds": session.get("duration_seconds") or 0,
                },
                created_at=session.get("ended_at"),
            )
        return session

    def journey_snapshot(self, include_checkpoints=False):
        if not self.journey:
            raise RuntimeError(self.journey_error or "Santiago journey data is unavailable")
        progress = self.store.journey_progress() or {}
        active = self.store.active_dashboard_session()
        live_distance = 0
        if active and active.get("workout_type") in {"indoor_cycling", "virtual_walk"}:
            live_distance = active.get("distance_km") or 0
        payload = self.journey.snapshot(
            progress.get("committed_distance_km") or 0,
            live_distance,
            include_checkpoints=include_checkpoints,
        )
        payload["committedSessionCount"] = progress.get("committed_session_count") or 0
        payload["updatedAt"] = progress.get("updated_at")
        payload["activeSessionId"] = active.get("id") if active else None
        return payload

    def save_postcard(self, payload):
        if not isinstance(payload, dict):
            raise ValueError("JSON payload must be an object")
        if not self.journey:
            raise RuntimeError(self.journey_error or "Santiago journey data is unavailable")
        checkpoint_id = str(payload.get("checkpointId") or "").strip()
        checkpoint = next((item for item in self.journey.checkpoints if item.get("id") == checkpoint_id), None)
        if not checkpoint:
            raise ValueError("Unknown journey checkpoint")
        return self.postcards.save(
            checkpoint_id,
            payload.get("filename"),
            payload.get("mimeType"),
            payload.get("dataBase64"),
        )

    def ingest_telemetry(self, raw_payload):
        telemetries, is_batch = normalize_telemetry_payload(raw_payload)
        raw_samples = raw_payload if is_batch else [raw_payload]
        accepted = []
        streams = []
        deletions = []
        latest_wear_state = "worn"
        for raw, telemetry in zip(raw_samples, telemetries):
            wear = self.wear_detector.observe(telemetry)
            latest_wear_state = wear["wear_state"]
            if wear["became_off_wrist"]:
                start = wear["flatline_start"]
                deletions.append((start, wear["timestamp"], wear["flatline_heart_rates"]))
                accepted = [item for item in accepted if not (
                    start <= item[2] <= wear["timestamp"] and item[1]["heart_rate"] in wear["flatline_heart_rates"]
                )]
            if wear["wear_state"] == "worn":
                accepted.append((raw, telemetry, wear["timestamp"]))
            streams.append(telemetry)
        for start, end, heart_rates in deletions:
            self.store.discard_heart_rate_flatline(start, end, heart_rates)
        accepted_raw = [item[0] for item in accepted]
        if accepted_raw:
            self.store.archive_heart_rates(accepted_raw)
        session = None
        subscriber_count = 0
        accepted_keys = {(item[1]["timestamp"], item[1]["heart_rate"]) for item in accepted}
        for telemetry in streams:
            if (telemetry["timestamp"], telemetry["heart_rate"]) in accepted_keys:
                ingested = self.store.ingest_dashboard(telemetry)
                if ingested:
                    session = ingested
            subscriber_count = self.broadcast(telemetry)
        response = {
            "ok": True,
            "telemetry": telemetries[-1],
            "session_id": session.get("id") if session else None,
            "wear_state": latest_wear_state,
            "sse_clients": subscriber_count,
        }
        if is_batch:
            response["accepted"] = len(telemetries)
        return response


class TrainingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, server_address, handler_class, runtime):
        self.runtime = runtime
        super().__init__(server_address, handler_class)

    def server_close(self):
        self.runtime.stop()
        super().server_close()


class TrainingHandler(BaseHTTPRequestHandler):
    server_version = "CleaningDashboardTrainingRuntime/1.0"

    @property
    def runtime(self):
        return self.server.runtime

    def log_message(self, format_string, *args):
        print(f"{time.strftime('%H:%M:%S')} [TRAIN] {self.address_string()} {format_string % args}", flush=True)

    def _allowed_origin(self):
        origin = self.headers.get("Origin")
        if not origin or origin == "null":
            return None
        try:
            parsed = urllib.parse.urlparse(origin)
            request_host = (self.headers.get("Host") or "").split(":", 1)[0].strip("[]").lower()
            origin_host = (parsed.hostname or "").lower()
        except ValueError:
            return None
        loopbacks = {"localhost", "127.0.0.1", "::1"}
        configured = {item.strip() for item in os.environ.get("TRAINING_RUNTIME_ALLOWED_ORIGINS", "").split(",") if item.strip()}
        if origin in configured or (origin_host in loopbacks and request_host in loopbacks) or origin_host == request_host:
            return origin
        return None

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        allowed = self._allowed_origin()
        if allowed:
            self.send_header("Access-Control-Allow-Origin", allowed)
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Dashboard-Token")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
            if self.headers.get("Access-Control-Request-Private-Network") == "true":
                self.send_header("Access-Control-Allow-Private-Network", "true")
            self.send_header("Vary", "Origin")
        super().end_headers()

    def send_json(self, payload, status=200):
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def send_bytes(self, payload, mime_type, status=200):
        self.send_response(status)
        self.send_header("Content-Type", mime_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def read_json(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError as exc:
            raise ValueError("Invalid Content-Length") from exc
        if length <= 0 or length > MAX_BODY_BYTES:
            raise ValueError("Invalid request body size")
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Request body must be valid JSON") from exc

    def _is_local_client(self):
        return self.client_address[0] in {"127.0.0.1", "::1", "localhost"}

    def _valid_token(self):
        supplied = self.headers.get("Authorization", "")
        if supplied.lower().startswith("bearer "):
            supplied = supplied[7:].strip()
        else:
            supplied = self.headers.get("X-Dashboard-Token", "").strip()
        expected = {
            value.strip() for value in (
                os.environ.get("DASHBOARD_WRITE_TOKEN", ""),
                os.environ.get("DASHBOARD_LIVE_WORKOUT_TOKEN", ""),
            ) if value.strip()
        }
        return bool(supplied) and any(hmac.compare_digest(supplied, item) for item in expected)

    def _authorize(self, telemetry=False):
        origin = self.headers.get("Origin")
        if origin and origin != "null" and not self._allowed_origin():
            self.send_json({"error": "Origin not allowed"}, status=403)
            return False
        if telemetry and not self._is_local_client() and not self._valid_token():
            status = 503 if not any((os.environ.get("DASHBOARD_WRITE_TOKEN"), os.environ.get("DASHBOARD_LIVE_WORKOUT_TOKEN"))) else 401
            self.send_json({"error": "A valid Live Workout bearer token is required"}, status=status)
            return False
        return True

    def do_OPTIONS(self):
        if self.headers.get("Origin") and not self._allowed_origin():
            self.send_json({"error": "Origin not allowed"}, status=403)
            return
        self.send_response(204)
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if not self._authorize():
            return
        if path in {"/health", "/api/live-workout/health"}:
            active = self.runtime.store.active_dashboard_session()
            self.send_json({"ok": True, "service": "training-runtime", "active_session_id": active.get("id") if active else None})
            return
        if path == "/api/live-workout/plan":
            query = urllib.parse.parse_qs(parsed.query)
            self.send_json(self.runtime.plan.response(query.get("date", [None])[0]))
            return
        if path == "/api/live-workout/session":
            self.send_json({"session": self.runtime.store.active_dashboard_session()})
            return
        if path == "/api/live-workout/history":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                limit = max(1, min(200, int(query.get("limit", [30])[0] or 30)))
                self.send_json({"sessions": self.runtime.store.history(limit)})
            except (TypeError, ValueError):
                self.send_json({"error": "Invalid history limit"}, status=400)
            return
        if path == "/api/live-workout/calorie-ranking":
            days = self.runtime.store.calorie_ranking()
            self.send_json({"days": days, "total_days": len(days)})
            return
        if path == "/api/live-workout/journey/santiago":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                include_checkpoints = (query.get("checkpoints") or [""])[0] in {"1", "true", "yes"}
                self.send_json(self.runtime.journey_snapshot(include_checkpoints=include_checkpoints))
            except RuntimeError as exc:
                self.send_json({"error": "Journey unavailable", "detail": str(exc)}, status=503)
            return
        if path == "/api/live-workout/journey/postcards":
            self.send_json({"postcards": self.runtime.postcards.list()})
            return
        postcard_match = re.fullmatch(r"/api/live-workout/journey/postcards/([a-zA-Z0-9-]+)/image", path)
        if postcard_match:
            image = self.runtime.postcards.image(postcard_match.group(1))
            if not image:
                self.send_json({"error": "Postcard not found"}, status=404)
                return
            image_path, mime_type = image
            self.send_bytes(image_path.read_bytes(), mime_type)
            return
        if path == "/api/live-workout/latest":
            self.send_json({"telemetry": self.runtime.store.latest_heart_rate()})
            return
        if path == "/api/live-workout/heart-rate-history":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                limit = max(1, min(100000, int(query.get("limit", [1000])[0] or 1000)))
                start = query.get("from", [None])[0]
                end = query.get("to", [None])[0]
                samples = self.runtime.store.heart_rate_history(
                    limit, int(start) if start is not None else None, int(end) if end is not None else None
                )
                samples = [{**sample, "source": "smartwatch", "source_label": "Smartwatch"} for sample in samples]
                self.send_json({"samples": samples, "sources": {"smartwatch": len(samples), "smartRing": 0}})
            except (TypeError, ValueError):
                self.send_json({"error": "Invalid heart-rate history query"}, status=400)
            return
        sensor_match = re.fullmatch(r"/api/live-workout/history/([a-zA-Z0-9-]+)/sensors", path)
        if sensor_match:
            session = self.runtime.store.session(sensor_match.group(1))
            if not session:
                self.send_json({"error": "Workout session not found"}, status=404)
            else:
                self.send_json({"samples": self.runtime.store.sensor_history(session["id"])})
            return
        match = re.fullmatch(r"/api/live-workout/history/([a-zA-Z0-9-]+)", path)
        if match:
            session = self.runtime.store.session(match.group(1))
            self.send_json(session if session else {"error": "Workout session not found"}, status=200 if session else 404)
            return
        if path == "/api/live-workout/stream":
            self.send_stream()
            return
        self.send_json({"error": "Not found"}, status=404)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path.rstrip("/")
        telemetry = path == "/api/live-workout/telemetry"
        if not self._authorize(telemetry=telemetry):
            return
        try:
            payload = self.read_json()
            if path == "/api/live-workout/session":
                if not isinstance(payload, dict):
                    raise ValueError("JSON payload must be an object")
                session = self.runtime.control_session(payload)
                if not session:
                    self.send_json({"error": "No active workout session"}, status=409)
                else:
                    self.send_json({"ok": True, "session": session})
                return
            if telemetry:
                self.send_json(self.runtime.ingest_telemetry(payload), status=202)
                return
            if path == "/api/live-workout/journey/postcards":
                self.send_json({"ok": True, "postcard": self.runtime.save_postcard(payload)}, status=201)
                return
            self.send_json({"error": "Not found"}, status=404)
        except ValueError as exc:
            self.send_json({"error": str(exc), "code": "invalid_request"}, status=400)
        except Exception as exc:
            print(f"{time.strftime('%H:%M:%S')} [TRAIN] error: {type(exc).__name__}: {exc}", flush=True)
            self.send_json({"error": "Training runtime request failed"}, status=500)

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        if not self._authorize():
            return
        match = re.fullmatch(r"/api/live-workout/session/([a-zA-Z0-9-]+)", parsed.path.rstrip("/"))
        if not match:
            self.send_json({"error": "Not found"}, status=404)
            return
        query = urllib.parse.parse_qs(parsed.query)
        if (query.get("confirm") or [""])[0] != "delete":
            self.send_json({"error": "Permanent deletion requires confirm=delete", "code": "confirmation_required"}, status=409)
            return
        deleted = self.runtime.store.delete_session(match.group(1))
        if not deleted:
            self.send_json({"error": "Workout session not found"}, status=404)
            return
        self.send_json({"ok": True, "deleted": match.group(1), "virtual_steps_removed": 0})

    def send_stream(self):
        subscriber = self.runtime.subscribe()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            while True:
                try:
                    payload = subscriber.get(timeout=20)
                    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
                    self.wfile.write(f"event: telemetry\ndata: {encoded}\n\n".encode("utf-8"))
                except queue.Empty:
                    self.wfile.write(b": keep-alive\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.runtime.unsubscribe(subscriber)


def create_server(host=DEFAULT_HOST, port=DEFAULT_PORT, database_path=None, plan_path=None, postcard_dir=None):
    runtime = TrainingRuntime(database_path=database_path, plan_path=plan_path, postcard_dir=postcard_dir)
    runtime.initialize()
    return TrainingHTTPServer((host, int(port)), TrainingHandler, runtime)


def run():
    load_env_files()
    host = os.environ.get("TRAINING_RUNTIME_HOST") or os.environ.get("DASHBOARD_HOST") or DEFAULT_HOST
    port = int(os.environ.get("TRAINING_RUNTIME_PORT", str(DEFAULT_PORT)))
    database_path = os.environ.get("TRAINING_RUNTIME_DB") or None
    plan_path = os.environ.get("TRAINING_RUNTIME_PLAN") or None
    server = create_server(
        host=host.strip() or DEFAULT_HOST,
        port=port,
        database_path=database_path,
        plan_path=plan_path,
    )
    visible_host = "127.0.0.1" if host in {"", "0.0.0.0"} else host
    print(f"{time.strftime('%H:%M:%S')} [TRAIN] runtime ready at http://{visible_host}:{port}", flush=True)
    active = server.runtime.store.active_dashboard_session()
    if active:
        print(f"{time.strftime('%H:%M:%S')} [TRAIN] recovered {active['id']} ({active['status']})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    run()
