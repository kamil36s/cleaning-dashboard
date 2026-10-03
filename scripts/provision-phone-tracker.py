"""Pair a debug Phone Tracker install over ADB without printing the bearer token.

The token crosses ADB stdin into a private one-time file. On app launch,
TrackerConfig encrypts it with Android Keystore and deletes the file.
"""

import argparse
import json
import subprocess
import urllib.request


PACKAGE = "com.cleaningdashboard.phonetracker"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--serial", required=True)
    parser.add_argument("--server", required=True, help="PC LAN URL, e.g. http://192.168.0.2:8000")
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--label", default="Redmi Phone Tracker")
    args = parser.parse_args()

    request = urllib.request.Request(
        args.api.rstrip("/") + "/api/phone-tracker/pair",
        data=json.dumps({"label": args.label}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        paired = json.load(response)
    payload = json.dumps({"server": args.server.rstrip("/"),
                          "device_id": paired["device_id"], "token": paired["token"]}).encode("utf-8")
    base = [args.adb, "-s", args.serial, "shell", "run-as", PACKAGE]
    subprocess.run(base + ["mkdir", "-p", "files"], capture_output=True, check=True, timeout=20)
    result = subprocess.run(base + ["dd", "of=files/pairing-once.json"],
                            input=payload, capture_output=True, check=False, timeout=20)
    if result.returncode:
        revoke = urllib.request.Request(args.api.rstrip("/") + "/api/phone-tracker/devices/" +
                                        paired["device_id"], method="DELETE")
        try:
            urllib.request.urlopen(revoke, timeout=10).close()
        except Exception:
            pass
        raise RuntimeError("ADB private provisioning failed: " +
                           result.stderr.decode("utf-8", errors="replace")[:300])
    subprocess.run([args.adb, "-s", args.serial, "shell", "am", "force-stop", PACKAGE],
                   check=True, capture_output=True, timeout=20)
    subprocess.run([args.adb, "-s", args.serial, "shell", "am", "start", "-n",
                    PACKAGE + "/.MainActivity"], check=True, capture_output=True, timeout=20)
    print("Pairing installed on phone; one-time token was not printed.")
    print("Device ID:", paired["device_id"])


if __name__ == "__main__":
    main()
