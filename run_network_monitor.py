from __future__ import annotations

import atexit
import logging
import os
from pathlib import Path

from network_monitor.api import create_app
from network_monitor.persistence import NetworkStore
from network_monitor.scanning import LanScanner, NetworkMonitorService


ROOT = Path(__file__).resolve().parent


def env_int(name: str, default: int, minimum: int = 1) -> int:
    raw = str(os.environ.get(name, "")).strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, value)


def resolve_path(name: str, default_path: Path) -> Path:
    raw = str(os.environ.get(name, "")).strip()
    if not raw:
        return default_path
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def main() -> None:
    port = env_int("NETWORK_MONITOR_PORT", 8765, minimum=1)
    interval = env_int("NETWORK_MONITOR_SCAN_INTERVAL", 30, minimum=5)
    ping_timeout_ms = env_int("NETWORK_MONITOR_PING_TIMEOUT_MS", 400, minimum=100)
    max_hosts_per_network = env_int("NETWORK_MONITOR_MAX_HOSTS", 256, minimum=16)
    max_workers = env_int("NETWORK_MONITOR_MAX_WORKERS", 16, minimum=4)
    db_path = resolve_path("NETWORK_MONITOR_DB_PATH", ROOT / "data" / "network-monitor.sqlite")
    names_path = resolve_path(
        "NETWORK_MONITOR_NAMES_PATH",
        ROOT / "data" / "network-known-devices.json",
    )

    store = NetworkStore(db_path, names_path=names_path)
    scanner = LanScanner(
        names_path=names_path,
        scan_interval_seconds=interval,
        ping_timeout_ms=ping_timeout_ms,
        max_hosts_per_network=max_hosts_per_network,
        max_workers=max_workers,
    )
    service = NetworkMonitorService(scanner=scanner, store=store, scan_interval_seconds=interval)
    service.start()
    atexit.register(service.stop)

    app = create_app(store)
    http_log_mode = str(os.environ.get("DASHBOARD_HTTP_LOG", "compact") or "compact").strip().lower()
    if http_log_mode not in {"all", "full", "verbose", "1", "true", "yes", "on"}:
        logging.getLogger("werkzeug").setLevel(logging.WARNING)
    print(f"Network monitor API: http://127.0.0.1:{port}")
    print(f"Database: {db_path}")
    print(f"Names file: {names_path}")
    print(f"Scan interval: {interval}s")
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False, threaded=True)


if __name__ == "__main__":
    main()
