"""On-demand lifecycle controller for the local Journal HTR Docker stack."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable


class JournalHtrRuntimeController:
    def __init__(
        self,
        root: Path,
        *,
        on_started: Callable[[], None] | None = None,
        on_stopped: Callable[[], None] | None = None,
    ):
        self.root = Path(root).resolve()
        self.bootstrap_path = self.root / "scripts" / "journal_htr_bootstrap.py"
        self._on_started = on_started
        self._on_stopped = on_stopped
        self._lock = threading.Lock()
        self._state = "stopped"
        self._detail = ""
        self._service_active = False

    def _probe(self, timeout: float = 0.75) -> bool:
        base_url = os.environ.get(
            "ESCRIPTORIUM_BASE_URL", "http://127.0.0.1:8081"
        ).rstrip("/")
        request = urllib.request.Request(
            f"{base_url}/api/",
            method="GET",
            headers={"Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout):
                return True
        except urllib.error.HTTPError:
            # 401/403 still proves that nginx and Django are reachable.
            return True
        except (urllib.error.URLError, TimeoutError, OSError):
            return False

    def _activate_service(self):
        with self._lock:
            if self._service_active:
                return
            if self._on_started:
                self._on_started()
            self._service_active = True

    def _deactivate_service(self):
        with self._lock:
            if not self._service_active:
                return
            if self._on_stopped:
                self._on_stopped()
            self._service_active = False

    def snapshot(self, *, probe: bool = True) -> dict:
        with self._lock:
            state = self._state
        if probe and state not in {"starting", "stopping"}:
            reachable = self._probe()
            next_state = "online" if reachable else (
                "error" if state == "error" else "stopped"
            )
            with self._lock:
                self._state = next_state
                if next_state == "online":
                    self._detail = ""
                state = self._state
            if reachable:
                self._activate_service()
            else:
                self._deactivate_service()
        with self._lock:
            return {
                "state": self._state,
                "detail": self._detail,
                "canStart": self._state in {"stopped", "error"},
                "canStop": self._state == "online",
            }

    def start(self) -> dict:
        current = self.snapshot()
        if current["state"] in {"online", "starting", "stopping"}:
            return current
        with self._lock:
            self._state = "starting"
            self._detail = "Uruchamiam eScriptorium i workery Kraken…"
        threading.Thread(
            target=self._run_action,
            args=("start",),
            name="journal-htr-runtime-start",
            daemon=True,
        ).start()
        return self.snapshot(probe=False)

    def stop(self) -> dict:
        current = self.snapshot()
        if current["state"] in {"stopped", "stopping", "starting"}:
            return current
        with self._lock:
            self._state = "stopping"
            self._detail = "Zatrzymuję kontenery OCR…"
        threading.Thread(
            target=self._run_action,
            args=("stop",),
            name="journal-htr-runtime-stop",
            daemon=True,
        ).start()
        return self.snapshot(probe=False)

    def _run_action(self, action: str):
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            completed = subprocess.run(
                [sys.executable, str(self.bootstrap_path), f"--{action}"],
                cwd=self.root,
                text=True,
                capture_output=True,
                timeout=3600 if action == "start" else 600,
                creationflags=creationflags,
            )
            output = "\n".join(
                part.strip()
                for part in (completed.stdout, completed.stderr)
                if part and part.strip()
            )
            detail = output.splitlines()[-1][:500] if output else ""
            if completed.returncode != 0:
                raise RuntimeError(detail or f"Polecenie OCR zakończyło się kodem {completed.returncode}")
            if action == "start":
                if not self._probe(timeout=2):
                    raise RuntimeError("Kontenery wystartowały, ale API eScriptorium nie odpowiada.")
                self._activate_service()
                with self._lock:
                    self._state = "online"
                    self._detail = ""
            else:
                self._deactivate_service()
                with self._lock:
                    self._state = "stopped"
                    self._detail = ""
        except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
            with self._lock:
                self._state = "error"
                self._detail = str(exc)[:500]
