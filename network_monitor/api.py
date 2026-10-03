from __future__ import annotations

from urllib.parse import urlparse

from flask import Flask, jsonify, request


LOCAL_HOSTS = {"127.0.0.1", "localhost"}


def is_local_origin(origin: str | None) -> bool:
    if not origin:
        return False
    try:
        parsed = urlparse(origin)
    except Exception:
        return False
    return parsed.hostname in LOCAL_HOSTS


def create_app(store) -> Flask:
    app = Flask(__name__)

    @app.after_request
    def add_default_headers(response):
        response.headers["Cache-Control"] = "no-store, max-age=0"
        origin = request.headers.get("Origin")
        if is_local_origin(origin):
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        return response

    @app.route("/api/network/device-names", methods=["OPTIONS"])
    def device_names_options():
        return ("", 204)

    @app.route("/api/network/device-profiles", methods=["OPTIONS"])
    def device_profiles_options():
        return ("", 204)

    @app.get("/api/network/devices")
    def get_devices():
        return jsonify(store.list_devices())

    @app.get("/api/network/summary")
    def get_summary():
        return jsonify(store.summary())

    @app.get("/api/network/history")
    def get_history():
        scope = str(request.args.get("scope") or "").strip().lower()
        device_key = str(request.args.get("device_key") or "").strip()
        day = str(request.args.get("day") or "").strip() or None
        if scope == "all":
            device = store.get_global_history_snapshot(day=day)
            if not device:
                return jsonify({"error": "No devices found."}), 404
            return jsonify({"device": device})
        if device_key:
            device = store.get_device_history_snapshot(device_key, day=day)
            if not device:
                return jsonify({"error": "Device not found."}), 404
            return jsonify({"device": device})
        return jsonify({"devices": store.list_device_history()})

    @app.get("/api/network/device-names")
    def get_device_names():
        return jsonify({"names": store.get_custom_names()})

    @app.get("/api/network/device-profiles")
    def get_device_profiles():
        return jsonify({"profiles": store.get_device_profiles()})

    @app.post("/api/network/device-names")
    def save_device_name():
        payload = request.get_json(silent=True) or {}
        mac = payload.get("mac")
        name = payload.get("name")
        try:
            names = store.save_custom_name(mac=mac, name=name)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except RuntimeError as exc:
            return jsonify({"error": str(exc)}), 500
        return jsonify(
            {
                "ok": True,
                "mac": mac,
                "name": (str(name or "").strip() or None),
                "names": names,
            }
        )

    @app.post("/api/network/device-profiles")
    def save_device_profile():
        payload = request.get_json(silent=True) or {}
        mac = payload.get("mac")
        name = payload.get("name")
        category = payload.get("category")
        owner = payload.get("owner")
        try:
            profiles = store.save_device_profile(
                mac=mac,
                name=name,
                category=category,
                owner=owner,
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except RuntimeError as exc:
            return jsonify({"error": str(exc)}), 500
        return jsonify(
            {
                "ok": True,
                "mac": mac,
                "name": (str(name or "").strip() or None),
                "category": (str(category or "").strip() or None),
                "owner": (str(owner or "").strip() or None),
                "profiles": profiles,
            }
        )

    return app
