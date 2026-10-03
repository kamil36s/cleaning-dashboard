#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
SETTINGS_DIR = DATA_DIR / "settings"
DEFAULT_DB = DATA_DIR / "cleaning.sqlite"
GAS_URL = "https://script.google.com/macros/s/AKfycbwZXHkLhl9HlcTHHzJjcMzAzDMRYhboDs3_kR8oAq9SdeKgBOp9JbWFS6P2OaiczpmXkg/exec"
APARTMENTS = {
    "aleja-pokoju6": "sprzatanie_tracker_detailed_aleja_pokoju6",
    "classic": "sprzatanie_tracker_detailed",
}


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def read_json(path: Path) -> tuple[Any, str]:
    raw = path.read_bytes()
    return json.loads(raw.decode("utf-8-sig")), sha256_bytes(raw)


def fetch_tasks(apartment_id: str, sheet_name: str, *, offline: bool) -> tuple[list[dict], str, str]:
    cache_path = SETTINGS_DIR / f"cleaning-tasks-{apartment_id}.json"
    if not offline:
        query = urllib.parse.urlencode({"apartment": apartment_id, "sheet": sheet_name})
        try:
            with urllib.request.urlopen(f"{GAS_URL}?{query}", timeout=30) as response:
                raw = response.read()
            payload = json.loads(raw.decode("utf-8-sig"))
            tasks = payload.get("tasks") if isinstance(payload, dict) else None
            if not isinstance(tasks, list):
                raise ValueError("response does not contain a tasks array")
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return tasks, sha256_bytes(raw), "google-apps-script"
        except Exception as exc:
            if not cache_path.exists():
                raise RuntimeError(f"Could not fetch {apartment_id} and no local cache exists: {exc}") from exc
            print(f"Warning: remote fetch failed for {apartment_id}; using {cache_path.relative_to(ROOT)}", file=sys.stderr)
    if not cache_path.exists():
        raise FileNotFoundError(f"Missing local task cache: {cache_path}")
    payload, checksum = read_json(cache_path)
    tasks = payload.get("tasks") if isinstance(payload, dict) else payload
    if not isinstance(tasks, list):
        raise ValueError(f"Invalid task cache: {cache_path}")
    return tasks, checksum, str(cache_path.relative_to(ROOT))


def load_history_sets() -> tuple[dict[str, list[dict]], list[dict[str, Any]]]:
    result: dict[str, list[dict]] = {}
    manifests: list[dict[str, Any]] = []
    for path in sorted(SETTINGS_DIR.glob("cleaning-history-*.json")):
        apartment_id = path.stem.removeprefix("cleaning-history-")
        payload, checksum = read_json(path)
        if not isinstance(payload, list):
            raise ValueError(f"History must be an array: {path}")
        result.setdefault(apartment_id, []).extend(payload)
        manifests.append({
            "path": str(path.relative_to(ROOT)),
            "apartment": apartment_id,
            "records": len(payload),
            "sha256": checksum,
        })
    return result, manifests


def load_settings() -> tuple[dict[str, Any], dict[str, Any] | None]:
    path = SETTINGS_DIR / "cleaning.json"
    if not path.exists():
        return {}, None
    payload, checksum = read_json(path)
    if not isinstance(payload, dict):
        raise ValueError(f"Settings must be an object: {path}")
    return payload, {
        "path": str(path.relative_to(ROOT)),
        "records": len(payload),
        "sha256": checksum,
    }


def backup_existing_database(db_path: Path) -> Path | None:
    if not db_path.exists() or db_path.stat().st_size == 0:
        return None
    backup_dir = DATA_DIR / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = backup_dir / f"cleaning.before-import-{stamp}.sqlite.bak"
    shutil.copy2(db_path, target)
    return target


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import the legacy cleaning module into local SQLite.")
    parser.add_argument("--dry-run", action="store_true", help="validate all data in a temporary database")
    parser.add_argument("--offline", action="store_true", help="use local cleaning-tasks-*.json caches only")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="target SQLite database")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    task_sets: dict[str, list[dict]] = {}
    task_manifest: list[dict[str, Any]] = []
    for apartment_id, sheet_name in APARTMENTS.items():
        tasks, checksum, source = fetch_tasks(apartment_id, sheet_name, offline=args.offline)
        task_sets[apartment_id] = tasks
        task_manifest.append({
            "source": source,
            "apartment": apartment_id,
            "records": len(tasks),
            "sha256": checksum,
        })
    history_sets, history_manifest = load_history_sets()
    settings, settings_manifest = load_settings()

    temporary: tempfile.TemporaryDirectory[str] | None = None
    target = args.db.resolve()
    backup = None
    if args.dry_run:
        temporary = tempfile.TemporaryDirectory(prefix="cleaning-import-")
        target = Path(temporary.name) / "cleaning.sqlite"
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        backup = backup_existing_database(target)

    os.environ["CLEANING_DB_PATH"] = str(target)
    sys.path.insert(0, str(ROOT))
    from cleaning_store import CleaningStore  # imported after CLEANING_DB_PATH is selected

    store = CleaningStore(target)
    result = store.import_initial(task_sets, history_sets, settings)
    expected_tasks = sum(len(tasks) for tasks in task_sets.values())
    expected_actions = sum(len(actions) for actions in history_sets.values())
    if result["counts"]["activeTasks"] < expected_tasks:
        raise RuntimeError(
            f"Task verification failed: expected at least {expected_tasks}, got {result['counts']['activeTasks']}"
        )
    if result["counts"]["actions"] < expected_actions:
        raise RuntimeError(
            f"History verification failed: expected at least {expected_actions}, got {result['counts']['actions']}"
        )
    if result["integrityCheck"].lower() != "ok":
        raise RuntimeError(f"SQLite integrity check failed: {result['integrityCheck']}")

    report = {
        "mode": "dry-run" if args.dry_run else "import",
        "database": str(args.db.resolve()),
        "backup": str(backup) if backup else None,
        "sources": {
            "tasks": task_manifest,
            "history": history_manifest,
            "settings": settings_manifest,
        },
        "expected": {"tasks": expected_tasks, "actions": expected_actions},
        "result": result,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if temporary is not None:
        temporary.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
