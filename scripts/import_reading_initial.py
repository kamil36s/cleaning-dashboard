#!/usr/bin/env python3
"""One-time, lossless import of the legacy reading sources into SQLite."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reading_store import ReadingError, ReadingStore  # noqa: E402


PRIMARY_URL = (
    "https://script.google.com/macros/s/"
    "AKfycbxHsr6z0XaqmWoJf6B2MuVtcnHVa9OFzha9mVAEH4p7yAoTPqi2hSp2SrwxZpO_Hq35/exec?type=reading"
)
STATE_URL = (
    "https://script.google.com/macros/s/"
    "AKfycbwTd7tWUscysF4ROYe2NmV4TK9ymxiStCbQFNoxxl-hiPQP3pMAs9kOUog8IwDOW18T/exec?action=state"
)


def read_json(path: Path, *, required: bool = True):
    if not path.exists():
        if required:
            raise FileNotFoundError(path)
        return {}
    with path.open("r", encoding="utf-8-sig") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def fetch_json(url: str, label: str):
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "cleaning-dashboard-reading-import/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            raw = response.read()
    except (OSError, urllib.error.URLError) as exc:
        raise RuntimeError(f"Could not fetch {label}: {exc}") from exc
    try:
        value = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{label} did not return valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{label} did not return a JSON object")
    return value


def backup_database(db_path: Path) -> Path | None:
    if not db_path.exists() or db_path.stat().st_size == 0:
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = db_path.with_name(f"{db_path.stem}.before-import-{stamp}{db_path.suffix}.bak")
    shutil.copy2(db_path, backup_path)
    return backup_path


def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Import Google reading books/state and the existing local reading history/settings "
            "into data/reading.sqlite. Existing populated databases are never overwritten."
        ),
    )
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "reading.sqlite")
    parser.add_argument("--history", type=Path, default=ROOT / "data" / "settings" / "reading-history.json")
    parser.add_argument("--settings", type=Path, default=ROOT / "data" / "settings" / "reading.json")
    parser.add_argument("--primary-url", default=PRIMARY_URL)
    parser.add_argument("--state-url", default=STATE_URL)
    parser.add_argument("--primary-file", type=Path, help="Read the primary Google snapshot from a JSON file")
    parser.add_argument("--state-file", type=Path, help="Read the Apps Script state snapshot from a JSON file")
    parser.add_argument("--dry-run", action="store_true", help="Validate and import into a temporary database only")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    primary = read_json(args.primary_file) if args.primary_file else fetch_json(args.primary_url, "primary reading feed")
    remote_state = read_json(args.state_file) if args.state_file else fetch_json(args.state_url, "reading state feed")
    history = read_json(args.history)
    settings = read_json(args.settings)

    primary_count = len(primary.get("books") or [])
    remote_count = len(remote_state.get("activeBooks") or [])
    history_days = len(history.get("log") or {})
    history_pages = sum(int(entry.get("total") or 0) for entry in (history.get("log") or {}).values())
    print(
        f"Validated sources: primary_books={primary_count}, state_books={remote_count}, "
        f"history_days={history_days}, history_pages={history_pages}"
    )
    if primary_count == 0 or remote_count == 0:
        raise RuntimeError("Remote reading sources are empty; refusing to create an incomplete database")
    if history_days == 0:
        raise RuntimeError("Local reading history is empty; refusing to lose the existing history")

    temporary = tempfile.TemporaryDirectory() if args.dry_run else None
    db_path = Path(temporary.name) / "reading.sqlite" if temporary else args.db.resolve()
    db_existed_before = db_path.exists()
    store = ReadingStore(db_path)
    store.initialize()
    if store.count_books() or store.history()["log"]:
        raise ReadingError(
            f"{db_path} already contains reading data; no changes were made",
            status=409,
            code="database_not_empty",
        )

    backup_path = backup_database(db_path) if db_existed_before and not args.dry_run else None
    result = store.import_initial(primary, remote_state, history, settings)
    state = store.state()
    if result["historyPages"] != history_pages:
        raise RuntimeError(
            f"History verification failed: source={history_pages}, sqlite={result['historyPages']}"
        )
    if len(state["books"]) < primary_count:
        raise RuntimeError(
            f"Book verification failed: source={primary_count}, sqlite={len(state['books'])}"
        )

    mode = "DRY RUN" if args.dry_run else "IMPORTED"
    print(
        f"{mode}: db={db_path}, books={result['books']}, active_books={result['activeBooks']}, "
        f"history_days={result['historyDays']}, history_pages={result['historyPages']}"
    )
    if backup_path:
        print(f"Pre-import database backup: {backup_path}")
    if temporary:
        temporary.cleanup()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, ReadingError, RuntimeError, ValueError) as exc:
        print(f"Import failed safely: {exc}", file=sys.stderr)
        raise SystemExit(1)
