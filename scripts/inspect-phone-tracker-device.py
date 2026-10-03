"""Print aggregate Phone Tracker diagnostics from a debug install over ADB.

Copies SQLite files into a temporary directory; never prints notification text
or pairing credentials. The temporary copy is removed on exit.
"""

import argparse
from contextlib import closing
import sqlite3
import subprocess
import tempfile
from pathlib import Path


PACKAGE = "com.cleaningdashboard.phonetracker"


def copy_database(adb, serial, remote, target):
    target.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        result = subprocess.run([adb, "-s", serial, "exec-out", "run-as", PACKAGE,
                                 "cat", remote + suffix], capture_output=True, timeout=20)
        if result.returncode == 0:
            (target / (Path(remote).name + suffix)).write_bytes(result.stdout)
    return target / Path(remote).name


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--serial", required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="phone-tracker-check-") as directory:
        root = Path(directory)
        events_db = copy_database(args.adb, args.serial, "databases/phone-tracker.sqlite", root / "events")
        with closing(sqlite3.connect(events_db)) as db:
            print("Phone events:")
            for event_type, count, first, last in db.execute(
                "SELECT eventType,COUNT(*) AS n,MIN(timestamp),MAX(timestamp) FROM events GROUP BY eventType ORDER BY n DESC"):
                print(f"  {event_type}: {count} ({first} to {last})")
            print("Pending:", db.execute("SELECT COUNT(*) FROM events WHERE syncedAt IS NULL AND rejectedReason IS NULL").fetchone()[0])
            print("Rejected:", db.execute("SELECT COUNT(*) FROM events WHERE rejectedReason IS NOT NULL").fetchone()[0])
        work_db = copy_database(args.adb, args.serial, "no_backup/androidx.work.workdb", root / "work")
        with closing(sqlite3.connect(work_db)) as db:
            print("WorkManager jobs:")
            for worker, state, job_id in db.execute(
                "SELECT w.worker_class_name,w.state,s.system_id FROM WorkSpec w "
                "LEFT JOIN SystemIdInfo s ON s.work_spec_id=w.id ORDER BY w.worker_class_name,w.state"):
                print(f"  {worker.rsplit('.',1)[-1]} state={state} job={job_id}")


if __name__ == "__main__":
    main()
