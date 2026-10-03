"""Loopback HTTP service. Only Phase 6's final answer crosses this boundary."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
import os
import threading
import time
from uuid import uuid4

from kermit_grounding import ask_grounded
from kermit_model.config import configured as model_configured
from kermit_model.fake_provider import FakeProvider
from kermit_model.ollama_provider import OllamaProvider
from kermit_model.resources import preflight
from kermit_retrieval.service import RetrievalError, Snapshot

from .config import configured as service_configured
from .contract import CAPABILITIES, SERVICE_BUILD
from .conversation import generate as generate_conversation
from .models import MAX_BODY_BYTES, CHAT_BODY_BYTES, parse_ask, parse_chat, public_answer, public_resource
from .routing import CLARIFY, GENERAL, PROJECT, route


class KermitService:
    def __init__(self, config=None, *, answerer=ask_grounded, provider=None,
                 preflight_check=preflight, snapshot_factory=Snapshot):
        self.config = config or service_configured()
        self.answerer = answerer
        self.provider = provider or (OllamaProvider() if self.config.provider == "ollama" else FakeProvider())
        self.preflight_check = preflight_check
        self.snapshot_factory = snapshot_factory
        self._slot = threading.Lock()
        self._state_lock = threading.Lock()
        self._active_state = None
        self._pending_confirmation = None
        self.instance_id = str(uuid4())

    def _set_state(self, state):
        with self._state_lock:
            self._active_state = state

    def _index_status(self):
        try:
            snapshot = self.snapshot_factory()
            counts = {state: list(snapshot.freshness.values()).count(state)
                      for state in ("current", "stale", "missing_or_unsafe")}
            return {"state": "current" if not counts["stale"] and not counts["missing_or_unsafe"] else "stale",
                    "buildId": snapshot.build_fingerprint, "sourceCounts": counts}
        except (RetrievalError, OSError, ValueError):
            return {"state": "unavailable", "buildId": None, "sourceCounts": None}

    def status(self):
        config = model_configured("normal", self.config.provider)
        if self.config.provider == "ollama":
            resource = self.preflight_check(config, self.provider)
            state = resource["modelState"]
            provider_available = resource["providerState"] != "unavailable"
        else:
            health = self.provider.health(config)
            provider_available = bool(health.get("modelAvailable"))
            resource = {"state": "green", "modelResident": True}
            state = "ready" if provider_available else "unavailable"
        with self._state_lock:
            if self._active_state == "loading" and resource.get("modelResident"):
                self._active_state = "generating"
            state = self._active_state or state
        return {"contractVersion": 1, "status": "ok", "serviceAvailable": True,
                "serviceBuild": SERVICE_BUILD, "capabilities": list(CAPABILITIES),
                "instanceId": self.instance_id, "processId": os.getpid(),
                "providerAvailable": provider_available, "model": config.model,
                "profile": "normal", "profiles": list(self.config.profiles),
                "modelState": state, "resourceGate": resource["state"],
                "resource": public_resource(resource), "index": self._index_status()}

    def ask(self, payload):
        question, profile, override = parse_ask(payload, self.config.profiles)
        return self._execute(question, profile, override)

    def chat(self, payload):
        question, profile, override, history, previous = parse_chat(payload, self.config.profiles)
        decision = route(question, history, previous)
        if decision["reason"] == "habit_mutation_request":
            return 200, {"contractVersion": 1, "status": "ok",
                         "answer": "I can't mark a habit done or change your dashboard data. You can record it in Habits App yourself.",
                         "claims": [], "citations": [], "uncertainty": [], "conflicts": [],
                         "groundingStatus": "not_required", "evidenceAsOf": None,
                         "route": PROJECT, "topic": "habits-app",
                         "timing": {"routingMs": decision["routingMs"], "classifierCalls": 0, "totalMs": 0}}
        if decision["reason"] == "private_runtime_request":
            return 200, {"contractVersion": 1, "status": "ok",
                         "answer": "I don't have an authorized reader for your live private dashboard data, so I can't verify that value.",
                         "claims": [], "citations": [], "uncertainty": ["No private runtime adapter is available."],
                         "conflicts": [], "groundingStatus": "insufficient_evidence", "evidenceAsOf": None,
                         "route": PROJECT, "topic": decision["topic"],
                         "timing": {"routingMs": decision["routingMs"], "classifierCalls": 0, "totalMs": 0}}
        if decision["route"] == CLARIFY:
            return 200, {"contractVersion": 1, "status": "ok", "answer": "What are you referring to?",
                         "claims": [], "citations": [], "uncertainty": [], "conflicts": [],
                         "groundingStatus": "not_required", "evidenceAsOf": None,
                         "route": CLARIFY, "topic": None,
                         "timing": {"routingMs": decision["routingMs"], "classifierCalls": 0, "totalMs": 0}}
        code, body = self._execute(decision["query"], profile, override, decision=decision, history=history)
        body["route"] = decision["route"]
        body["topic"] = decision["topic"]
        body.setdefault("timing", {})["routingMs"] = decision["routingMs"]
        body["timing"]["classifierCalls"] = 0
        return code, body

    def _execute(self, question, profile, override, *, decision=None, history=()):
        if not self._slot.acquire(blocking=False):
            return 409, {"contractVersion": 1, "status": "busy", "modelState": "generating",
                         "message": "Kermit is answering another question."}
        try:
            config = model_configured(profile, self.config.provider)
            confirmation = (hashlib.sha256(question.encode("utf-8")).hexdigest(), profile,
                            decision["route"] if decision else PROJECT)
            resource = None
            if self.config.provider == "ollama":
                resource = self.preflight_check(config, self.provider)
                if resource["state"] == "red":
                    self._pending_confirmation = None
                    status = "unavailable" if resource["reason"] == "model_unavailable" else "waiting_for_memory"
                    self._set_state(status)
                    return 503, {"contractVersion": 1, "status": status, "modelState": resource["modelState"],
                                 "message": resource["message"], "resource": public_resource(resource)}
                if resource["state"] == "yellow" and (not override or self._pending_confirmation != confirmation):
                    self._pending_confirmation = confirmation
                    self._set_state("resource_pressure")
                    return 409, {"contractVersion": 1, "status": "confirmation_required",
                                 "modelState": "resource_pressure", "message": resource["message"],
                                 "resource": public_resource(resource)}
            self._pending_confirmation = None
            self._set_state("generating" if resource and resource["modelResident"] else "loading")
            started = time.monotonic()
            if decision and decision["route"] == GENERAL:
                result = generate_conversation(question, history, provider=self.provider, config=config,
                                               topic=decision["topic"],
                                               hypothetical=decision["reason"] == "hypothetical_project")
                result["timing"]["totalMs"] = int((time.monotonic() - started) * 1000)
                return 200, result
            result = self.answerer(question, profile=profile, provider=self.config.provider,
                                   allow_memory_pressure=override)
            if result.get("draftStatus") == "confirmation_required":
                self._pending_confirmation = confirmation
            return 200, public_answer(result, profile, config.model, int((time.monotonic() - started) * 1000))
        finally:
            self._set_state(None)
            self._slot.release()


def create_server(config=None, *, service=None):
    service = service or KermitService(config)
    config = service.config

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            # Do not log questions, URLs, origin headers, or private response text.
            pass

        def _headers(self, code, origin=None):
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            if origin in config.origins:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
            self.end_headers()

        def _reply(self, code, body, origin=None):
            raw = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            if origin in config.origins:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
            self.end_headers()
            self.wfile.write(raw)

        def _permitted(self, *, require_origin=False):
            host = self.headers.get("Host", "")
            origin = self.headers.get("Origin")
            allowed_hosts = {f"{name}:{config.port}" for name in ("127.0.0.1", "localhost")}
            return host in allowed_hosts and (origin in config.origins if require_origin else origin is None or origin in config.origins)

        def do_OPTIONS(self):
            origin = self.headers.get("Origin")
            if self.path not in ("/api/kermit/v1/ask", "/api/kermit/v1/chat") or not self._permitted(require_origin=True):
                self._reply(403, {"status": "forbidden"})
                return
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "POST")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Max-Age", "600")
            self.send_header("Vary", "Origin")
            self.end_headers()

        def do_GET(self):
            if not self._permitted():
                self._reply(403, {"status": "forbidden"})
            elif self.path == "/api/kermit/v1/status":
                try:
                    self._reply(200, service.status(), self.headers.get("Origin"))
                except Exception:
                    self._reply(503, {"contractVersion": 1, "status": "unavailable"}, self.headers.get("Origin"))
            else:
                self._reply(404, {"status": "not_found"}, self.headers.get("Origin"))

        def do_POST(self):
            origin = self.headers.get("Origin")
            if not self._permitted(require_origin=True):
                self._reply(403, {"status": "forbidden"})
                return
            if self.path not in ("/api/kermit/v1/ask", "/api/kermit/v1/chat"):
                self._reply(404, {"status": "not_found"}, origin)
                return
            if self.headers.get("Content-Type", "").lower() != "application/json":
                self._reply(415, {"status": "invalid_request", "message": "JSON content type required."}, origin)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 1 or length > (CHAT_BODY_BYTES if self.path.endswith("/chat") else MAX_BODY_BYTES):
                    raise ValueError("request is too large or empty")
                raw = self.rfile.read(length)
                def unique_pairs(pairs):
                    value = {}
                    for key, item in pairs:
                        if key in value:
                            raise ValueError("duplicate JSON field")
                        value[key] = item
                    return value
                payload = json.loads(raw.decode("utf-8", "strict"), object_pairs_hook=unique_pairs)
                code, body = service.chat(payload) if self.path.endswith("/chat") else service.ask(payload)
            except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
                code, body = 400, {"contractVersion": 1, "status": "invalid_request", "message": str(exc)[:120]}
            except Exception:
                code, body = 503, {"contractVersion": 1, "status": "unavailable", "message": "Kermit could not complete the request."}
            self._reply(code, body, origin)

    return ThreadingHTTPServer((config.host, config.port), Handler)
