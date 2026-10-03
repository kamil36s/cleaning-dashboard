"""Read-only timestamps for the small dashboard runtime panel."""

import ctypes
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path


def system_boot_time():
    """Return the current OS boot time, or None when it cannot be determined."""
    try:
        if os.name == "nt":
            get_ticks = ctypes.WinDLL("kernel32", use_last_error=True).GetTickCount64
            get_ticks.restype = ctypes.c_ulonglong
            uptime_seconds = get_ticks() / 1000
        else:
            uptime_seconds = time.clock_gettime(time.CLOCK_BOOTTIME)
        return datetime.now(timezone.utc) - timedelta(seconds=uptime_seconds)
    except (AttributeError, OSError, OverflowError, ValueError):
        return None


def read_dashboard_runtime_status(root: Path):
    marker = root / "data" / "settings" / "dashboard-started-at.txt"
    dashboard_started_at = None
    boot = system_boot_time()
    try:
        recorded = datetime.fromisoformat(marker.read_text(encoding="utf-8").strip())
        if recorded.tzinfo and recorded <= datetime.now(timezone.utc) and (boot is None or recorded >= boot):
            dashboard_started_at = recorded.isoformat()
    except (OSError, ValueError):
        pass

    return {
        "dashboard_started_at": dashboard_started_at,
        "system_booted_at": boot.isoformat() if boot else None,
    }
