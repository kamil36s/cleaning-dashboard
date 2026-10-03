# Local process lifecycle

## Identity and verification

- Stable ID: `process-lifecycle`; development Vite, central API, network monitor, BLE scale collector and independent training runtime. Reviewed 2026-10-03 against B5 source.
- A healthy UI or static pack is not evidence that any local process is currently running.

## Launch and restart ownership

`start-all.ps1` ensures `training_runtime.py` on port 8766, then runs `start-dashboard.ps1`. The latter sets `SKIP_TRAINING_RUNTIME=1` and invokes `start-dev.cmd`. `start-training-runtime.ps1` probes `/api/live-workout/health`; an already-ready runtime is left running, an occupied unrelated port fails, otherwise it starts a hidden Python process and waits for health. This detached runtime owns active-session continuity and is outside ordinary dashboard cleanup.

`start-dev.cmd` ensures the runtime unless explicitly skipped, invokes project-scoped `scripts/stop-dev-services.ps1`, optionally starts Kermit, then launches `scripts/dev-service.js` instances for API (`server.py`, port 8000), Network Monitor (`run_network_monitor.py`, port 8765), BLE scale/sensor collector (`scripts/scan_ble.py`) and foreground Vite. `scripts/wait-dev-services.ps1` checks backend readiness. When Vite exits, the batch script cleans ordinary project services. `scripts/dev-service.js` automatically restarts only the central API after 1.5 seconds; network, BLE and Vite exit without automatic restart. It records Vite start time under ignored `data/settings/`, used by `dashboard_runtime_status.py` and the Settings Status tab. That status is informational, not a restart control.

The central API owns ring collector startup/shutdown within its process. The independent training runtime continues through API/Vite restarts and recovers its SQLite clock/checkpoints after its own restart; a runtime outage still interrupts telemetry ingest. Network monitor and BLE collector have their own process lifetimes. Kermit is optional at startup; a Kermit outage does not prevent dashboard startup. This pack concerns process ownership, not Git backup scheduling or live process observation.

## Privacy and evidence

Local logs, PID/port observations, device addresses in `scripts/scan_ble.py`, runtime databases and private settings are excluded. The scanner source was reviewed as a dependency but remains unadmitted due to embedded device identifiers. `tests/test_training_runtime.py::test_runtime_process_outlives_restarted_dashboard_process` tests the isolation; `tests/test_server_startup.py` and service tests cover narrower startup paths. These tests do not establish today's service status.

## Checked implementation references

| Admitted source | Checked marker |
| --- | --- |
| `scripts/dev-service.js` | `const autoRestart = serviceName === 'api'` |
| `training_runtime.py` | `class TrainingRuntime` |
| `dashboard_runtime_status.py` | `def read_dashboard_runtime_status` |
