from __future__ import annotations

import json
import os
import queue
import re
import shutil
import sqlite3
import ssl
import subprocess
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path


POLL_INTERVAL_SECONDS = 60
STALE_AFTER_SECONDS = 5 * 60
CODEX_INACTIVITY_SECONDS = 15 * 60
ANTIGRAVITY_INACTIVITY_SECONDS = 20 * 60
RETRY_BACKOFF_SECONDS = (60, 120, 300, 600)
AVERAGE_WEEKS_PER_MONTH = 4.345

# This is a notional share of the subscription, never API/token cost.
AI_USAGE_CONFIG = {
    "codexPlanName": "ChatGPT Pro 5X",
    "quotaMultiplier": 5,
    "codexBaseMonthlyUsd": 100.0,
    "vatRate": 0.23,
    "usdPlnRate": 488.44 / 123.0,
    "grossMonthlyPln": 488.44,
    "planActivatedAt": "2026-09-16T10:10:54.914025Z",
}

PREVIOUS_CODEX_PLAN_CONFIG = {
    "codexPlanName": "ChatGPT Plus",
    "quotaMultiplier": 1,
    "codexBaseMonthlyUsd": 20.0,
    "vatRate": 0.23,
    "usdPlnRate": 3.73,
}

GROUPS = (
    ("codex", "main", "Codex"),
    ("antigravity", "gemini", "Gemini"),
    ("antigravity", "claude_gpt", "Claude / GPT"),
)


def find_codex_executable(path_value=None, home=None):
    """Find Codex both on PATH and inside supported editor extensions."""
    configured = os.environ.get("CODEX_EXECUTABLE")
    if configured and Path(configured).is_file():
        return configured

    executable = shutil.which("codex", path=path_value)
    if executable:
        return executable

    if os.name != "nt":
        return None

    user_home = Path(home) if home is not None else Path.home()
    extension_roots = (
        user_home / ".vscode" / "extensions",
        user_home / ".vscode-insiders" / "extensions",
        user_home / ".cursor" / "extensions",
    )
    candidates = []
    for extension_root in extension_roots:
        if not extension_root.is_dir():
            continue
        candidates.extend(
            candidate
            for candidate in extension_root.glob("openai.chatgpt-*/bin/windows-x86_64/codex.exe")
            if candidate.is_file()
        )
    if not candidates:
        return None
    return str(max(candidates, key=lambda candidate: candidate.stat().st_mtime))


def utc_now():
    return datetime.now(timezone.utc)


def iso_utc(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        value = datetime.fromtimestamp(value, timezone.utc)
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_iso(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def clamp_percent(value):
    try:
        number = min(100.0, max(0.0, float(value)))
    except (TypeError, ValueError):
        return None
    return round(number, 1)


def quota_window(remaining=None, reset_at=None):
    remaining = clamp_percent(remaining)
    if remaining is None:
        return None
    return {"remaining": remaining, "resetAt": iso_utc(reset_at)}


def _codex_limits(payload):
    result = payload.get("result", payload) if isinstance(payload, dict) else {}
    by_id = result.get("rateLimitsByLimitId") if isinstance(result, dict) else None
    if isinstance(by_id, dict) and isinstance(by_id.get("codex"), dict):
        return by_id["codex"]
    limits = result.get("rateLimits") if isinstance(result, dict) else None
    if isinstance(limits, dict) and str(limits.get("limitId", "")).lower() == "codex":
        return limits
    return None


def parse_codex_rate_limits(payload, observed_at=None):
    limits = _codex_limits(payload)
    if limits is None:
        raise ValueError("Codex rate limit payload is unavailable or ambiguous")
    windows = {300: None, 10080: None}
    for key in ("primary", "secondary"):
        item = limits.get(key)
        if not isinstance(item, dict):
            continue
        try:
            duration = int(item.get("windowDurationMins"))
        except (TypeError, ValueError):
            continue
        if duration not in windows:
            continue
        used = clamp_percent(item.get("usedPercent"))
        if used is None:
            continue
        windows[duration] = quota_window(100.0 - used, item.get("resetsAt"))
    return {
        "provider": "codex",
        "group": "main",
        "fiveHour": windows[300],
        "weekly": windows[10080],
        "status": "connected",
        "updatedAt": iso_utc(observed_at or utc_now()),
    }


def _find_reset(bucket):
    candidates = [
        bucket.get("resetTime"),
        bucket.get("resetAt"),
        (bucket.get("remaining") or {}).get("resetTime") if isinstance(bucket.get("remaining"), dict) else None,
        (bucket.get("remaining") or {}).get("resetAt") if isinstance(bucket.get("remaining"), dict) else None,
    ]
    metadata = bucket.get("metadata")
    if isinstance(metadata, dict):
        candidates.extend((metadata.get("resetTime"), metadata.get("resetAt"), metadata.get("resetDescription")))
    return next((iso_utc(value) for value in candidates if value), None)


def _antigravity_group(name):
    normalized = str(name or "").lower()
    if "gemini" in normalized:
        return "gemini"
    if "claude" in normalized or "gpt" in normalized or "third" in normalized or "3p" in normalized:
        return "claude_gpt"
    return None


def _antigravity_window(bucket):
    text = " ".join(str(bucket.get(key) or "") for key in ("window", "displayName", "bucketId")).lower()
    if re.search(r"(^|\W)(5h|five[ -]?hour|300)(\W|$)", text):
        return "fiveHour"
    if "week" in text or "10080" in text or "7d" in text:
        return "weekly"
    return None


def parse_antigravity_quota(payload, observed_at=None):
    root = payload.get("response", payload) if isinstance(payload, dict) else {}
    groups = root.get("groups") if isinstance(root, dict) else None
    if not isinstance(groups, list):
        raise ValueError("Antigravity quota groups are unavailable")
    result = {}
    for group_data in groups:
        if not isinstance(group_data, dict):
            continue
        group = _antigravity_group(group_data.get("displayName") or group_data.get("groupName"))
        if group is None:
            continue
        row = result.setdefault(group, {
            "provider": "antigravity",
            "group": group,
            "fiveHour": None,
            "weekly": None,
            "status": "connected",
            "updatedAt": iso_utc(observed_at or utc_now()),
        })
        for bucket in group_data.get("buckets") or []:
            if not isinstance(bucket, dict):
                continue
            window = _antigravity_window(bucket)
            if window is None:
                continue
            remaining_data = bucket.get("remaining")
            fraction = remaining_data.get("remainingFraction") if isinstance(remaining_data, dict) else bucket.get("remainingFraction")
            try:
                remaining = float(fraction) * 100.0
            except (TypeError, ValueError):
                continue
            row[window] = quota_window(remaining, _find_reset(bucket))
    if not result:
        raise ValueError("Antigravity response contains no confirmed quota fractions")
    return list(result.values())


def calculate_burn(previous, current, reset_changed=False):
    previous = clamp_percent(previous)
    current = clamp_percent(current)
    if previous is None or current is None or reset_changed or current >= previous:
        return 0.0
    return round(previous - current, 1)


def subscription_values(config=None):
    config = config or AI_USAGE_CONFIG
    base = float(config["codexBaseMonthlyUsd"])
    gross = base * (1.0 + float(config["vatRate"]))
    weekly = gross / AVERAGE_WEEKS_PER_MONTH
    gross_pln = float(config.get("grossMonthlyPln", gross * float(config["usdPlnRate"])))
    return {
        "planName": config["codexPlanName"],
        "quotaMultiplier": int(config.get("quotaMultiplier", 1)),
        "grossMonthlyUsd": round(gross, 2),
        "grossMonthlyPln": round(gross_pln, 2),
        "weeklyQuotaUsd": round(weekly, 2),
        "weeklyQuotaPln": round(gross_pln / AVERAGE_WEEKS_PER_MONTH, 2),
        "usdPlnRate": float(config["usdPlnRate"]),
    }


def quota_value_for_burn(burn_pp, config=None):
    values = subscription_values(config)
    fraction = max(0.0, float(burn_pp or 0)) / 100.0
    return {
        "usd": round(values["weeklyQuotaUsd"] * fraction, 2),
        "pln": round(values["weeklyQuotaPln"] * fraction, 2),
    }


def codex_plan_config_for(timestamp):
    activated_at = parse_iso(AI_USAGE_CONFIG.get("planActivatedAt"))
    observed_at = parse_iso(timestamp)
    if activated_at and observed_at and observed_at < activated_at:
        return PREVIOUS_CODEX_PLAN_CONFIG
    return AI_USAGE_CONFIG


def codex_plan_changes():
    activated_at = AI_USAGE_CONFIG.get("planActivatedAt")
    if not activated_at:
        return []
    return [{
        "provider": "codex",
        "group": "main",
        "activatedAt": activated_at,
        "fromPlanName": PREVIOUS_CODEX_PLAN_CONFIG["codexPlanName"],
        "toPlanName": AI_USAGE_CONFIG["codexPlanName"],
        "quotaMultiplier": int(AI_USAGE_CONFIG.get("quotaMultiplier", 1)),
    }]


class CodexAppServer:
    def __init__(self, timeout=15):
        self.timeout = timeout
        self.process = None
        self._reader = None
        self._responses = {}
        self._responses_lock = threading.Lock()
        self._request_lock = threading.Lock()
        self._next_id = 1

    def _read_stdout(self):
        try:
            for line in self.process.stdout:
                try:
                    message = json.loads(line)
                except (TypeError, ValueError):
                    continue
                request_id = message.get("id")
                if request_id is None:
                    continue
                with self._responses_lock:
                    target = self._responses.get(request_id)
                if target is not None:
                    target.put(message)
        except Exception:
            pass

    @staticmethod
    def _drain(stream):
        try:
            for _line in stream:
                pass
        except Exception:
            pass

    def _send(self, message):
        if self.process is None or self.process.poll() is not None:
            raise RuntimeError("Codex app-server is not running")
        self.process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
        self.process.stdin.flush()

    def _request(self, method, params=None):
        with self._request_lock:
            request_id = self._next_id
            self._next_id += 1
            response_queue = queue.Queue(maxsize=1)
            with self._responses_lock:
                self._responses[request_id] = response_queue
            request = {"id": request_id, "method": method}
            if params is not None:
                request["params"] = params
            try:
                self._send(request)
                response = response_queue.get(timeout=self.timeout)
            except queue.Empty as exc:
                raise TimeoutError(f"Codex app-server timed out on {method}") from exc
            finally:
                with self._responses_lock:
                    self._responses.pop(request_id, None)
            if response.get("error"):
                message = response["error"].get("message") if isinstance(response["error"], dict) else response["error"]
                raise RuntimeError(str(message or "Codex JSON-RPC error"))
            return response

    def start(self):
        if self.process is not None and self.process.poll() is None:
            return
        self.stop()
        executable = find_codex_executable()
        if not executable:
            raise FileNotFoundError("codex executable was not found")
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        child_env = os.environ.copy()
        child_env.pop("FORCE_COLOR", None)
        child_env["NO_COLOR"] = "1"
        self.process = subprocess.Popen(
            [executable, "app-server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=child_env,
            creationflags=creation_flags,
        )
        self._reader = threading.Thread(target=self._read_stdout, name="codex-app-server-reader", daemon=True)
        self._reader.start()
        threading.Thread(target=self._drain, args=(self.process.stderr,), name="codex-app-server-stderr", daemon=True).start()
        self._request("initialize", {
            "clientInfo": {"name": "dashboard-ai-usage", "title": "Dashboard AI Usage", "version": "1.0.0"},
            "capabilities": {"experimentalApi": True},
        })
        self._send({"method": "initialized"})

    def read_quota(self):
        self.start()
        return parse_codex_rate_limits(self._request("account/rateLimits/read"))

    def stop(self):
        process = self.process
        self.process = None
        if process is None:
            return
        try:
            process.terminate()
            process.wait(timeout=3)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass


def _powershell_json(script, timeout=12):
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=creation_flags,
        check=False,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        return []
    try:
        data = json.loads(completed.stdout)
    except ValueError:
        return []
    return data if isinstance(data, list) else [data]


def _command_arg(command_line, flag):
    pattern = rf"(?:^|\s){re.escape(flag)}(?:=|\s+)(?:\"([^\"]+)\"|'([^']+)'|([^\s]+))"
    match = re.search(pattern, str(command_line or ""), re.IGNORECASE)
    return next((part for part in match.groups() if part is not None), None) if match else None


class AntigravityClient:
    PROCESS_SCRIPT = r"""
$items = Get-CimInstance Win32_Process | Where-Object {
  $_.Name -eq 'agy.exe' -or ($_.Name -eq 'language_server.exe' -and [string]$_.CommandLine -match 'antigravity')
} | Select-Object Name, ProcessId, CommandLine
$items | ConvertTo-Json -Compress
"""

    def __init__(self, timeout=5):
        self.timeout = timeout
        self.connection = None

    def _listeners(self, pid):
        script = (
            f"Get-NetTCPConnection -State Listen -OwningProcess {int(pid)} -ErrorAction SilentlyContinue | "
            "Where-Object { $_.LocalAddress -eq '127.0.0.1' -or $_.LocalAddress -eq '::1' } | "
            "Select-Object LocalAddress, LocalPort | ConvertTo-Json -Compress"
        )
        return _powershell_json(script)

    def _fetch_hub_csrf(self, host, hub_port):
        """Fetch the ephemeral CSRF token from the agy hub's HTTP UI page.

        The token is embedded in ``window.__APP_CONFIG__`` in the root HTML
        response served on the plain-HTTP hub port.  It is held in memory only
        and never persisted or logged.
        """
        if host not in {"127.0.0.1", "::1"}:
            return None
        try:
            url = f"http://{host}:{hub_port}/"
            request = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                html = response.read(16384).decode("utf-8", errors="replace")
            match = re.search(r"window\.__APP_CONFIG__\s*=\s*(\{[^;]+\})", html)
            if not match:
                return None
            config = json.loads(match.group(1))
            return config.get("csrfToken") or None
        except Exception:
            return None

    def _request(self, connection, method):
        host = connection["host"]
        if host not in {"127.0.0.1", "::1"}:
            raise ValueError("Antigravity host must be loopback")
        display_host = f"[{host}]" if ":" in host else host
        url = f"https://{display_host}:{connection['port']}/exa.language_server_pb.LanguageServerService/{method}"
        headers = {"Content-Type": "application/json", "Connect-Protocol-Version": "1"}
        if connection.get("csrf"):
            headers["X-Codeium-Csrf-Token"] = connection["csrf"]
        body = json.dumps({"metadata": {
            "ideName": "antigravity", "extensionName": "antigravity", "ideVersion": "unknown", "locale": "en",
        }}).encode("utf-8")
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        context = ssl._create_unverified_context()  # Only used for validated loopback hosts above.
        with urllib.request.urlopen(request, context=context, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def _try_agy_hub(self, process):
        """Try the agy --hub path: fetch CSRF from HTTP UI, probe HTTPS RPC port.

        agy --hub exposes two loopback ports for a given PID:
          - HTTP port (from --hub-port): serves the UI with CSRF in __APP_CONFIG__
          - HTTPS port: the Connect-RPC endpoint requiring that CSRF token

        Returns a valid connection dict or None.
        """
        command_line = process.get("CommandLine") or ""
        pid = process.get("ProcessId")
        if not pid:
            return None
        # Only process agy.exe processes running with --hub
        if str(process.get("Name") or "").lower() != "agy.exe":
            return None
        if "--hub" not in command_line.lower():
            return None

        hub_port_str = _command_arg(command_line, "--hub-port")
        try:
            hub_port = int(hub_port_str) if hub_port_str else None
        except ValueError:
            hub_port = None

        host = "127.0.0.1"

        # Collect all loopback listener ports for this PID
        all_ports = []
        for listener in self._listeners(pid):
            lhost = listener.get("LocalAddress")
            lport = listener.get("LocalPort")
            if lhost in {"127.0.0.1", "::1"} and lport:
                all_ports.append((lhost, int(lport)))

        # Ensure hub_port is known; add it if missing from listener list
        if hub_port:
            hub_entry = (host, hub_port)
            if hub_entry not in all_ports:
                all_ports.append(hub_entry)

        # Fetch CSRF from the HTTP UI port. Newer agy builds can run the hub
        # without the web UI, so allow an explicitly configured loopback token
        # from the local process command line as a compatibility fallback.
        csrf = None
        if hub_port:
            csrf = self._fetch_hub_csrf(host, hub_port)
        if not csrf:
            csrf = (
                _command_arg(command_line, "--csrf_token")
                or _command_arg(command_line, "--extension_server_csrf_token")
            )

        if not csrf:
            return None

        # Probe non-hub-port loopback ports as HTTPS RPC candidates
        rpc_candidates = [(h, p) for h, p in all_ports if p != hub_port]
        # Also try hub_port itself as a last resort
        if hub_port:
            rpc_candidates.append((host, hub_port))

        for rpc_host, rpc_port in rpc_candidates:
            connection = {
                "host": rpc_host,
                "port": rpc_port,
                "pid": int(pid),
                "csrf": csrf,
            }
            try:
                self._request(connection, "GetUnleashData")
                return connection
            except Exception:
                continue
        return None

    def discover(self):
        processes = _powershell_json(self.PROCESS_SCRIPT)

        # PRIMARY: agy --hub path (fetches CSRF from HTTP UI page)
        for process in processes:
            connection = self._try_agy_hub(process)
            if connection is not None:
                self.connection = connection
                return connection

        # LEGACY FALLBACK: language_server.exe or agy without --hub
        for process in processes:
            command_line = process.get("CommandLine") or ""
            process_name = str(process.get("Name") or "").lower()
            # Skip agy --hub processes already tried above
            if process_name == "agy.exe" and "--hub" in command_line.lower():
                continue
            csrf = _command_arg(command_line, "--csrf_token") or _command_arg(command_line, "--extension_server_csrf_token")
            explicit = _command_arg(command_line, "--extension_server_port")
            candidates = []
            for listener in self._listeners(process.get("ProcessId")):
                lhost = listener.get("LocalAddress")
                lport = listener.get("LocalPort")
                if lhost in {"127.0.0.1", "::1"} and lport:
                    candidates.append((lhost, int(lport)))
            if explicit:
                try:
                    fallback = ("127.0.0.1", int(explicit))
                    if fallback not in candidates:
                        candidates.append(fallback)
                except ValueError:
                    pass
            for host, port in candidates:
                connection = {
                    "host": host,
                    "port": port,
                    "pid": int(process.get("ProcessId")),
                    "csrf": csrf if process_name == "language_server.exe" or csrf else None,
                }
                try:
                    self._request(connection, "GetUnleashData")
                except Exception:
                    continue
                self.connection = connection
                return connection

        self.connection = None
        raise RuntimeError("No responsive Antigravity quota endpoint was found")

    def read_quota(self):
        connection = self.connection or self.discover()
        try:
            payload = self._request(connection, "RetrieveUserQuotaSummary")
            return parse_antigravity_quota(payload)
        except Exception as preferred_error:
            for method in ("GetUserStatus", "GetCommandModelConfigs"):
                try:
                    parsed = parse_antigravity_quota(self._request(connection, method))
                    if parsed:
                        return parsed
                except Exception:
                    continue
            self.connection = None
            raise preferred_error


class AIUsageService:
    def __init__(self, database_path):
        self.database_path = Path(database_path)
        self.codex = CodexAppServer()
        self.antigravity = AntigravityClient()
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread = None
        self._current = {}
        self._retry = {"codex": 0, "antigravity": 0}
        self._next_poll = {"codex": 0.0, "antigravity": 0.0}

    def _connect(self):
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self, start_worker=True):
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    group_name TEXT NOT NULL,
                    five_hour_remaining REAL,
                    five_hour_reset_at TEXT,
                    weekly_remaining REAL,
                    weekly_reset_at TEXT,
                    status TEXT NOT NULL,
                    updated_at TEXT,
                    five_hour_burn REAL NOT NULL DEFAULT 0,
                    weekly_burn REAL NOT NULL DEFAULT 0,
                    five_hour_reset INTEGER NOT NULL DEFAULT 0,
                    weekly_reset INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_ai_usage_snapshots_group_time
                    ON snapshots(provider, group_name, timestamp DESC);
                CREATE TABLE IF NOT EXISTS reset_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    group_name TEXT NOT NULL,
                    window_name TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_start TEXT NOT NULL,
                    session_end TEXT,
                    last_burn_at TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    group_name TEXT NOT NULL,
                    start_5h_remaining REAL,
                    end_5h_remaining REAL,
                    start_weekly_remaining REAL,
                    end_weekly_remaining REAL,
                    five_hour_burn REAL NOT NULL DEFAULT 0,
                    weekly_burn REAL NOT NULL DEFAULT 0,
                    duration_seconds INTEGER NOT NULL DEFAULT 60,
                    status TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_ai_usage_sessions_group_time
                    ON sessions(provider, group_name, session_start DESC);
            """)
            for provider, group, _label in GROUPS:
                row = connection.execute(
                    "SELECT * FROM snapshots WHERE provider=? AND group_name=? ORDER BY id DESC LIMIT 1",
                    (provider, group),
                ).fetchone()
                if row:
                    self._current[(provider, group)] = self._row_to_current(row)
        self._close_inactive(utc_now())
        if start_worker:
            self.start()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="ai-usage-poller", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        self.codex.stop()
        self.antigravity.connection = None

    def _run(self):
        while not self._stop_event.is_set():
            now_mono = time.monotonic()
            self._close_inactive(utc_now())
            for provider in ("codex", "antigravity"):
                if now_mono < self._next_poll[provider]:
                    continue
                self._poll_provider(provider)
            self._stop_event.wait(1)

    def _poll_provider(self, provider):
        observed_at = utc_now()
        try:
            rows = [self.codex.read_quota()] if provider == "codex" else self.antigravity.read_quota()
            found_groups = set()
            for row in rows:
                found_groups.add(row["group"])
                self._ingest(row, observed_at)
            if provider == "antigravity":
                for missing in {"gemini", "claude_gpt"} - found_groups:
                    self._record_failure(provider, missing, "unavailable", observed_at)
            self._retry[provider] = 0
            self._next_poll[provider] = time.monotonic() + POLL_INTERVAL_SECONDS
        except Exception as exc:
            message = str(exc).lower()
            status = "not_logged_in" if "login" in message or "auth" in message else "unavailable" if "not found" in message or "no responsive" in message else "error"
            groups = ("main",) if provider == "codex" else ("gemini", "claude_gpt")
            for group in groups:
                self._record_failure(provider, group, status, observed_at)
            if provider == "codex":
                self.codex.stop()
            else:
                self.antigravity.connection = None
            index = min(self._retry[provider], len(RETRY_BACKOFF_SECONDS) - 1)
            self._next_poll[provider] = time.monotonic() + RETRY_BACKOFF_SECONDS[index]
            self._retry[provider] += 1

    @staticmethod
    def _window_values(row, key):
        value = row.get(key) if isinstance(row, dict) else None
        return (
            value.get("remaining") if isinstance(value, dict) else None,
            value.get("resetAt") if isinstance(value, dict) else None,
        )

    def _record_failure(self, provider, group, status, observed_at):
        previous = self._current.get((provider, group))
        row = {
            "provider": provider,
            "group": group,
            "fiveHour": previous.get("fiveHour") if previous else None,
            "weekly": previous.get("weekly") if previous else None,
            "status": status,
            "updatedAt": previous.get("updatedAt") if previous else None,
        }
        self._ingest(row, observed_at)

    def _ingest(self, row, observed_at=None):
        observed_at = observed_at or utc_now()
        timestamp = iso_utc(observed_at)
        provider, group = row["provider"], row["group"]
        with self._lock, self._connect() as connection:
            previous_db = connection.execute(
                "SELECT * FROM snapshots WHERE provider=? AND group_name=? ORDER BY id DESC LIMIT 1",
                (provider, group),
            ).fetchone()
            previous = self._row_to_current(previous_db) if previous_db else None
            five_remaining, five_reset_at = self._window_values(row, "fiveHour")
            week_remaining, week_reset_at = self._window_values(row, "weekly")
            five_reset = self._is_reset(previous.get("fiveHour") if previous else None, row.get("fiveHour"))
            week_reset = self._is_reset(previous.get("weekly") if previous else None, row.get("weekly"))
            five_burn = calculate_burn(
                previous.get("fiveHour", {}).get("remaining") if previous and previous.get("fiveHour") else None,
                five_remaining,
                five_reset,
            )
            week_burn = calculate_burn(
                previous.get("weekly", {}).get("remaining") if previous and previous.get("weekly") else None,
                week_remaining,
                week_reset,
            )
            changed = previous is None or any((
                previous.get("fiveHour") != row.get("fiveHour"),
                previous.get("weekly") != row.get("weekly"),
                previous.get("status") != row.get("status"),
            ))
            current = {**row, "checkedAt": timestamp}
            self._current[(provider, group)] = current
            if not changed:
                return False
            connection.execute("""
                INSERT INTO snapshots (
                    timestamp, provider, group_name, five_hour_remaining, five_hour_reset_at,
                    weekly_remaining, weekly_reset_at, status, updated_at,
                    five_hour_burn, weekly_burn, five_hour_reset, weekly_reset
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                timestamp, provider, group, five_remaining, five_reset_at, week_remaining, week_reset_at,
                row.get("status") or "error", row.get("updatedAt"), five_burn, week_burn,
                int(five_reset), int(week_reset),
            ))
            for window_name, did_reset in (("5h", five_reset), ("weekly", week_reset)):
                if did_reset:
                    connection.execute(
                        "INSERT INTO reset_events(timestamp, provider, group_name, window_name) VALUES (?, ?, ?, ?)",
                        (timestamp, provider, group, window_name),
                    )
            if five_burn > 0 or week_burn > 0:
                self._apply_session_burn(connection, row, previous, timestamp, five_burn, week_burn)
            return True

    @staticmethod
    def _is_reset(previous, current):
        if not isinstance(previous, dict) or not isinstance(current, dict):
            return False
        previous_remaining = clamp_percent(previous.get("remaining"))
        current_remaining = clamp_percent(current.get("remaining"))
        increased = previous_remaining is not None and current_remaining is not None and current_remaining > previous_remaining
        reset_changed = bool(previous.get("resetAt") and current.get("resetAt") and previous.get("resetAt") != current.get("resetAt"))
        large_jump = previous_remaining is not None and current_remaining is not None and current_remaining - previous_remaining >= 15
        return increased and (reset_changed or large_jump)

    def _apply_session_burn(self, connection, row, previous, timestamp, five_burn, week_burn):
        provider, group = row["provider"], row["group"]
        active = connection.execute(
            "SELECT * FROM sessions WHERE provider=? AND group_name=? AND status='active' ORDER BY id DESC LIMIT 1",
            (provider, group),
        ).fetchone()
        if active:
            last_burn = parse_iso(active["last_burn_at"])
            timeout = CODEX_INACTIVITY_SECONDS if provider == "codex" else ANTIGRAVITY_INACTIVITY_SECONDS
            if last_burn and (parse_iso(timestamp) - last_burn).total_seconds() >= timeout:
                self._close_session(connection, active)
                active = None
        current_five = row.get("fiveHour", {}).get("remaining") if row.get("fiveHour") else None
        current_week = row.get("weekly", {}).get("remaining") if row.get("weekly") else None
        if not active:
            previous_five = previous.get("fiveHour", {}).get("remaining") if previous and previous.get("fiveHour") else current_five
            previous_week = previous.get("weekly", {}).get("remaining") if previous and previous.get("weekly") else current_week
            connection.execute("""
                INSERT INTO sessions (
                    session_start, session_end, last_burn_at, provider, group_name,
                    start_5h_remaining, end_5h_remaining, start_weekly_remaining, end_weekly_remaining,
                    five_hour_burn, weekly_burn, duration_seconds, status
                ) VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
            """, (
                timestamp, timestamp, provider, group, previous_five, current_five, previous_week, current_week,
                five_burn, week_burn, POLL_INTERVAL_SECONDS,
            ))
            return
        started = parse_iso(active["session_start"])
        ended = parse_iso(timestamp) + timedelta(seconds=POLL_INTERVAL_SECONDS)
        duration = max(POLL_INTERVAL_SECONDS, int((ended - started).total_seconds()))
        connection.execute("""
            UPDATE sessions SET last_burn_at=?, end_5h_remaining=?, end_weekly_remaining=?,
                five_hour_burn=five_hour_burn+?, weekly_burn=weekly_burn+?, duration_seconds=?
            WHERE id=?
        """, (timestamp, current_five, current_week, five_burn, week_burn, duration, active["id"]))

    @staticmethod
    def _close_session(connection, session):
        started = parse_iso(session["session_start"])
        last_burn = parse_iso(session["last_burn_at"])
        ended = last_burn + timedelta(seconds=POLL_INTERVAL_SECONDS)
        duration = max(POLL_INTERVAL_SECONDS, int((ended - started).total_seconds()))
        connection.execute(
            "UPDATE sessions SET session_end=?, duration_seconds=?, status='closed' WHERE id=?",
            (iso_utc(ended), duration, session["id"]),
        )

    def _close_inactive(self, now):
        with self._lock, self._connect() as connection:
            active = connection.execute("SELECT * FROM sessions WHERE status='active'").fetchall()
            for session in active:
                last_burn = parse_iso(session["last_burn_at"])
                timeout = CODEX_INACTIVITY_SECONDS if session["provider"] == "codex" else ANTIGRAVITY_INACTIVITY_SECONDS
                if last_burn and (now - last_burn).total_seconds() >= timeout:
                    self._close_session(connection, session)

    @staticmethod
    def _row_to_current(row):
        if row is None:
            return None
        return {
            "provider": row["provider"],
            "group": row["group_name"],
            "fiveHour": quota_window(row["five_hour_remaining"], row["five_hour_reset_at"]),
            "weekly": quota_window(row["weekly_remaining"], row["weekly_reset_at"]),
            "status": row["status"],
            "updatedAt": row["updated_at"],
            "checkedAt": row["timestamp"],
        }

    @staticmethod
    def _period_start(kind, now):
        local = now.astimezone()
        if kind == "today":
            start = local.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            start = (local - timedelta(days=local.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        return iso_utc(start)

    def _burn_since(self, connection, provider, group, since):
        row = connection.execute("""
            SELECT COALESCE(SUM(five_hour_burn), 0) AS five, COALESCE(SUM(weekly_burn), 0) AS week
            FROM snapshots WHERE provider=? AND group_name=? AND timestamp>=?
        """, (provider, group, since)).fetchone()
        return {"fiveHour": round(row["five"], 1), "weekly": round(row["week"], 1)}

    def _session_stats(self, connection, provider, group, since):
        row = connection.execute("""
            SELECT COUNT(*) AS count, COALESCE(SUM(duration_seconds), 0) AS duration
            FROM sessions WHERE provider=? AND group_name=? AND session_start>=?
        """, (provider, group, since)).fetchone()
        return {"activeSeconds": int(row["duration"]), "sessions": int(row["count"])}

    def get_dashboard(self, history_hours=None, session_limit=20):
        now = utc_now()
        self._close_inactive(now)
        today_start = self._period_start("today", now)
        week_start = self._period_start("week", now)
        groups = []
        values = subscription_values()
        with self._lock, self._connect() as connection:
            for provider, group, label in GROUPS:
                current = dict(self._current.get((provider, group)) or {
                    "provider": provider, "group": group, "fiveHour": None, "weekly": None,
                    "status": "unavailable", "updatedAt": None, "checkedAt": None,
                })
                updated = parse_iso(current.get("updatedAt"))
                if updated and (now - updated).total_seconds() > STALE_AFTER_SECONDS:
                    current["status"] = "stale"
                today_since = today_start
                week_since = week_start
                if provider == "codex":
                    activated_at = parse_iso(AI_USAGE_CONFIG.get("planActivatedAt"))
                    if activated_at and activated_at > parse_iso(today_since):
                        today_since = iso_utc(activated_at)
                    if activated_at and activated_at > parse_iso(week_since):
                        week_since = iso_utc(activated_at)
                today_burn = self._burn_since(connection, provider, group, today_since)
                week_burn = self._burn_since(connection, provider, group, week_since)
                last_hour = self._burn_since(connection, provider, group, iso_utc(now - timedelta(hours=1)))
                five_since = today_start
                weekly_since = week_start
                if current.get("fiveHour") and current["fiveHour"].get("resetAt"):
                    reset = parse_iso(current["fiveHour"]["resetAt"])
                    if reset:
                        five_since = iso_utc(reset - timedelta(minutes=300))
                if current.get("weekly") and current["weekly"].get("resetAt"):
                    reset = parse_iso(current["weekly"]["resetAt"])
                    if reset:
                        weekly_since = iso_utc(reset - timedelta(minutes=10080))
                current_burn = {
                    "fiveHour": self._burn_since(connection, provider, group, five_since)["fiveHour"],
                    "weekly": self._burn_since(connection, provider, group, weekly_since)["weekly"],
                }
                today_stats = {**self._session_stats(connection, provider, group, today_since), **today_burn}
                week_stats = {**self._session_stats(connection, provider, group, week_since), "weekly": week_burn["weekly"]}
                current.update({
                    "label": label,
                    "burn": {"lastHour": last_hour, "today": today_burn, "currentWindow": current_burn},
                    "stats": {"today": today_stats, "thisWeek": week_stats},
                })
                if provider == "codex":
                    remaining = current.get("weekly", {}).get("remaining") if current.get("weekly") else None
                    used_fraction = (100.0 - remaining) / 100.0 if remaining is not None else None
                    current["quotaValue"] = {
                        **values,
                        "usedUsd": round(values["weeklyQuotaUsd"] * used_fraction, 2) if used_fraction is not None else None,
                        "remainingUsd": round(values["weeklyQuotaUsd"] * (1.0 - used_fraction), 2) if used_fraction is not None else None,
                        "today": quota_value_for_burn(today_burn["weekly"]),
                    }
                groups.append(current)
            safe_session_limit = max(1, min(100, int(session_limit or 20)))
            session_rows = connection.execute(
                "SELECT * FROM sessions ORDER BY session_start DESC LIMIT ?",
                (safe_session_limit,),
            ).fetchall()
            sessions = []
            for row in session_rows:
                item = dict(row)
                item["group"] = item.pop("group_name")
                item["quotaValue"] = quota_value_for_burn(
                    item["weekly_burn"], codex_plan_config_for(item["session_start"])
                ) if item["provider"] == "codex" else None
                sessions.append(item)
            if history_hours is None:
                history_rows = connection.execute(
                    "SELECT * FROM snapshots ORDER BY timestamp DESC LIMIT 40"
                ).fetchall()
            else:
                safe_history_hours = max(1.0, min(24.0 * 30, float(history_hours)))
                history_since = iso_utc(now - timedelta(hours=safe_history_hours))
                history_rows = connection.execute(
                    "SELECT * FROM snapshots WHERE timestamp>=? ORDER BY timestamp DESC LIMIT 10000",
                    (history_since,),
                ).fetchall()
            history = []
            for row in history_rows:
                item = self._row_to_current(row)
                item["fiveHourBurn"] = row["five_hour_burn"]
                item["weeklyBurn"] = row["weekly_burn"]
                history.append(item)
        return {
            "providers": groups,
            "sessions": sessions,
            "history": history,
            "config": {
                **values,
                "vatRate": AI_USAGE_CONFIG["vatRate"],
                "codexBaseMonthlyUsd": AI_USAGE_CONFIG["codexBaseMonthlyUsd"],
                "planActivatedAt": AI_USAGE_CONFIG["planActivatedAt"],
                "planChanges": codex_plan_changes(),
                "pollIntervalSeconds": POLL_INTERVAL_SECONDS,
                "codexInactivitySeconds": CODEX_INACTIVITY_SECONDS,
                "antigravityInactivitySeconds": ANTIGRAVITY_INACTIVITY_SECONDS,
            },
            "generatedAt": iso_utc(now),
        }
