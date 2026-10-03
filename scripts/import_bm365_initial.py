#!/usr/bin/env python3
import argparse
import json
import os
import sqlite3
import sys
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bm365_store import Bm365Store, _identity_key


DEFAULT_API_BASE = (
    "https://script.google.com/macros/s/"
    "AKfycbzcvpZ78Zw6yZdt7owKjEkiZvpqHPf_I2JKqRV5M1Ny2_702SpGrUTMAmm_DL7Av_rX/exec"
)


def fetch_rows(api_base):
    parsed = urllib.parse.urlsplit(api_base)
    query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    query["action"] = "bm365_get"
    url = urllib.parse.urlunsplit((
        parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(query), parsed.fragment
    ))
    request = urllib.request.Request(url, headers={"User-Agent": "cleaning-dashboard/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload if isinstance(payload, list) else payload.get("rows") or []


def load_snapshot(path):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return payload if isinstance(payload, list) else payload.get("rows") or []


def load_metadata(path):
    path = Path(path)
    if not path.exists():
        return {}, {}
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    columns = {row[1] for row in connection.execute("PRAGMA table_info(album_metadata)")}
    rows = connection.execute("SELECT * FROM album_metadata").fetchall()
    connection.close()
    by_id = {}
    by_key = {}
    for row in rows:
        item = dict(row)
        release_value = item.get("release_date") or item.get("release_year") or ""
        year = str(release_value)[:4] if str(release_value)[:4].isdigit() else None
        metadata = {
            "year": int(year) if year else None,
            "description": str(item.get("description") or "").strip(),
            "identity": _identity_key(item.get("artist"), item.get("album")),
        }
        by_id[int(item["row_id"])] = metadata
        by_key[_identity_key(item.get("artist"), item.get("album"))] = metadata
    return by_id, by_key


def load_related_albums(path):
    path = Path(path)
    if not path.exists():
        return {}
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            "SELECT artist, album, release_year, minutes, description FROM albums"
        ).fetchall()
    except sqlite3.DatabaseError:
        rows = []
    finally:
        connection.close()
    return {_identity_key(row["artist"], row["album"]): dict(row) for row in rows}


def load_google_release_years():
    try:
        import server

        server.load_env_files()
        rows = server.bm365_release_year_rows(force=True)
    except Exception as exc:
        print(f"Warning: Google Sheet release years are unavailable: {exc}", file=sys.stderr)
        return {}, {}
    by_id = {}
    by_key = {}
    for row in rows:
        raw_year = str(row.get("year") or "").strip()
        if not raw_year.isdigit():
            continue
        metadata = {"year": int(raw_year), "description": ""}
        if str(row.get("rowId") or "").isdigit():
            by_id[int(row["rowId"])] = metadata
        by_key[_identity_key(row.get("artist"), row.get("album"))] = metadata
    return by_id, by_key


def merge_rows(rows, metadata_by_id, metadata_by_key, related_sources):
    merged = []
    for row in rows:
        item = dict(row)
        key = _identity_key(item.get("artist"), item.get("album"))
        id_metadata = metadata_by_id.get(int(item.get("rowId") or 0)) or {}
        metadata = (
            id_metadata if id_metadata.get("identity") == key
            else metadata_by_key.get(key) or {}
        )
        related = next((source[key] for source in related_sources if key in source), {})
        item["year"] = metadata.get("year") or related.get("release_year")
        item["description"] = metadata.get("description") or str(related.get("description") or "").strip()
        if item.get("minutes") in (None, "") and related.get("minutes") is not None:
            item["minutes"] = related["minutes"]
        merged.append(item)
    return merged


def main(argv=None):
    parser = argparse.ArgumentParser(description="Import the BM365 Google Sheet into local SQLite.")
    parser.add_argument("--api-base", default=os.environ.get("BM365_API_BASE", DEFAULT_API_BASE))
    parser.add_argument("--snapshot", help="Read source rows from a local JSON snapshot instead of Google.")
    parser.add_argument("--database", default=ROOT / "data" / "bm365.sqlite", type=Path)
    parser.add_argument("--metadata-database", default=ROOT / "data" / "bm365-metadata.sqlite", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    rows = load_snapshot(args.snapshot) if args.snapshot else fetch_rows(args.api_base)
    if len(rows) != 365:
        raise SystemExit(f"Expected exactly 365 BM365 albums, got {len(rows)}.")
    metadata_by_id, metadata_by_key = load_metadata(args.metadata_database)
    release_years_by_id, release_years_by_key = load_google_release_years()
    related = [
        load_related_albums(ROOT / "data" / "brutal-assault-2027.sqlite"),
        load_related_albums(ROOT / "data" / "rym-polish-black-metal-top-100.sqlite"),
    ]
    merged = merge_rows(rows, metadata_by_id, metadata_by_key, related)
    for item in merged:
        if item.get("year") is not None:
            continue
        release_metadata = (
            release_years_by_id.get(int(item.get("rowId") or 0))
            or release_years_by_key.get(_identity_key(item.get("artist"), item.get("album")))
            or {}
        )
        item["year"] = release_metadata.get("year")
    descriptions = sum(bool(str(row.get("description") or "").strip()) for row in merged)
    years = sum(row.get("year") is not None for row in merged)
    listened = sum(str(row.get("listened") or "").strip().upper() == "TAK" for row in merged)
    rated = sum(row.get("rating") not in (None, "") for row in merged)

    if not args.dry_run:
        store = Bm365Store(args.database)
        try:
            imported = store.replace_all(merged, expected_count=365)
        finally:
            store.close()
    else:
        imported = len(merged)
    mode = "Dry run verified" if args.dry_run else "Imported"
    print(
        f"{mode} {imported} albums: {listened} listened, {rated} rated, "
        f"{years} release years, {descriptions} descriptions."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
