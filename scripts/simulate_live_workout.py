#!/usr/bin/env python3
"""Send synthetic heart-rate telemetry to the local Live Workout API."""

import argparse
import json
import math
import os
import random
import time
import urllib.error
import urllib.request


DEFAULT_URL = "http://127.0.0.1:8766/api/live-workout/telemetry"


def simulated_heart_rate(elapsed_seconds, minimum, maximum):
    cycle_seconds = 12 * 60
    phase = (elapsed_seconds % cycle_seconds) / cycle_seconds
    if phase < 0.18:
        effort = phase / 0.18 * 0.38
    elif phase < 0.48:
        effort = 0.38 + ((phase - 0.18) / 0.30) * 0.34
    elif phase < 0.64:
        effort = 0.72 - ((phase - 0.48) / 0.16) * 0.27
    elif phase < 0.83:
        effort = 0.45 + ((phase - 0.64) / 0.19) * 0.5
    else:
        effort = 0.95 - ((phase - 0.83) / 0.17) * 0.65
    wave = math.sin(elapsed_seconds / 7) * 2.5
    noise = random.uniform(-2.2, 2.2)
    return round(minimum + (maximum - minimum) * effort + wave + noise)


def send(url, token, heart_rate, status="running"):
    payload = json.dumps(
        {
            "timestamp": int(time.time() * 1000),
            "heart_rate": int(heart_rate),
            "status": status,
        }
    ).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL, help="Telemetry endpoint URL")
    parser.add_argument("--token", default=os.environ.get("DASHBOARD_LIVE_WORKOUT_TOKEN", os.environ.get("DASHBOARD_WRITE_TOKEN", "")), help="Bearer token for LAN writes")
    parser.add_argument("--duration", type=int, default=0, help="Run time in seconds; 0 means until Ctrl+C")
    parser.add_argument("--min-hr", type=int, default=82, help="Minimum simulated heart rate")
    parser.add_argument("--max-hr", type=int, default=181, help="Maximum simulated heart rate")
    args = parser.parse_args()
    if not 30 <= args.min_hr < args.max_hr <= 240:
        parser.error("expected 30 <= --min-hr < --max-hr <= 240")

    started = time.monotonic()
    sent_count = 0
    last_heart_rate = None
    print(f"Sending telemetry once per second to {args.url}. Press Ctrl+C to stop.")
    try:
        while args.duration <= 0 or time.monotonic() - started < args.duration:
            loop_started = time.monotonic()
            elapsed = loop_started - started
            heart_rate = simulated_heart_rate(elapsed, args.min_hr, args.max_hr)
            last_heart_rate = heart_rate
            try:
                status = send(args.url, args.token, heart_rate)
                sent_count += 1
                print(f"\r#{sent_count:05d}  {heart_rate:3d} BPM  HTTP {status}", end="", flush=True)
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                print(f"\nHTTP {exc.code}: {detail}")
            except urllib.error.URLError as exc:
                print(f"\nConnection error: {exc.reason}")
            time.sleep(max(0, 1 - (time.monotonic() - loop_started)))
    except KeyboardInterrupt:
        pass
    if last_heart_rate is not None:
        try:
            send(args.url, args.token, last_heart_rate, status="finished")
        except (urllib.error.HTTPError, urllib.error.URLError):
            pass
    print(f"\nStopped after {sent_count} samples.")


if __name__ == "__main__":
    main()
