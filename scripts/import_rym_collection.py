"""Import numbered, locally saved RYM collection pages into Music.

No network requests are made. Existing personal and legacy ratings take priority.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path

from music_importers import parse_rym_html
from music_store import MusicStore


ROOT = Path(__file__).resolve().parents[1]


def numbered_pages(folder: Path, expected_pages: int):
    pages = [folder / f"{number}.html" for number in range(1, expected_pages + 1)]
    missing = [page.name for page in pages if not page.is_file()]
    if missing:
        raise ValueError(f"Brak stron: {', '.join(missing)}")
    seen = set()
    total = 0
    for number, page in enumerate(pages, 1):
        parsed = parse_rym_html(page.read_text(encoding="utf-8"))
        if parsed["pageType"] != "RYM_COLLECTION":
            raise ValueError(f"{page.name}: plik nie jest stroną kolekcji RYM")
        source = parsed.get("sourceUrl") or ""
        if not re.search(rf"/collection/[^/]+/{number}/$", source):
            raise ValueError(f"{page.name}: adres strony nie odpowiada numerowi pliku: {source}")
        for row in parsed["rows"]:
            release_id = row["rymReleaseId"]
            if release_id in seen:
                raise ValueError(f"Powtórzony identyfikator wydania RYM: {release_id}")
            seen.add(release_id)
            total += 1
    return pages, total


def backup_database(source: Path, target: Path):
    if target.exists():
        raise FileExistsError(f"Kopia już istnieje: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source) as original, sqlite3.connect(target) as backup:
        original.backup(backup)


def import_pages(store: MusicStore, pages, manual_matches=None):
    manual_matches = manual_matches or {}
    report = {"pages": len(pages), "sourceRows": 0, "created": 0, "matched": 0,
              "skipped": 0, "ratingsAdded": 0, "ratingsAlreadyPresent": 0,
              "ratingConflicts": [], "ambiguousRows": [], "resolvedRows": [], "errors": [], "alreadyImportedPages": 0}
    for page in pages:
        preview = store.preview_import(filename=page.name, html=page.read_text(encoding="utf-8"))
        batch = preview["batch"]
        report["sourceRows"] += batch["parsed_count"]
        resolutions = {}
        if batch["ambiguous_count"] or batch["error_count"]:
            for row in batch["rows"]:
                if row["match_status"] in ("AMBIGUOUS", "ERROR"):
                    entry = {"page": page.name, "artist": row["parsed"].get("artistCredit"),
                             "title": row["parsed"].get("title"), "rymReleaseId": row["parsed"].get("rymReleaseId"),
                             "status": row["match_status"], "candidates": row["candidates"]}
                    chosen = manual_matches.get(entry["rymReleaseId"])
                    if row["match_status"] == "AMBIGUOUS" and chosen is not None:
                        if chosen not in {candidate["id"] for candidate in row["candidates"]}:
                            raise ValueError(f"{page.name}: ręczne dopasowanie {chosen} nie jest kandydatem")
                        resolutions[str(row["id"])] = {"action": "match", "releaseId": chosen}
                        report["resolvedRows"].append(entry)
                    else:
                        report["ambiguousRows" if row["match_status"] == "AMBIGUOUS" else "errors"].append(entry)
        if batch["status"] == "COMMITTED":
            report["alreadyImportedPages"] += 1
            continue
        result = store.commit_import(batch["id"], resolutions)
        for key in ("created", "matched", "skipped", "ratingsAdded", "ratingsAlreadyPresent"):
            report[key] += result[key]
        report["ratingConflicts"].extend({"page": page.name, **conflict} for conflict in result["ratingConflicts"])
    return report


def attach_saved_covers(store: MusicStore, folder: Path, pages):
    """Use saved 75px thumbnails only where Music has no local cover."""
    folder = folder.resolve()
    cover_dir = store.root / "covers"
    cover_dir.mkdir(parents=True, exist_ok=True)
    result = {"coversAdded": 0, "coverFilesMissing": 0, "coversAlreadyPresent": 0}
    with store._lock, store._connect() as connection:
        release_by_rym_id = {row["external_value"]: int(row["entity_id"]) for row in connection.execute(
            "SELECT external_value,entity_id FROM music_external_ids "
            "WHERE entity_type='release' AND source='rym' AND external_type='release_id'"
        )}
        local_covers = {int(row["id"]): row["cover_local"] for row in connection.execute(
            "SELECT id,cover_local FROM music_releases"
        )}
        for page in pages:
            parsed = parse_rym_html(page.read_text(encoding="utf-8"))
            for row in parsed["rows"]:
                release_id = release_by_rym_id.get(row["rymReleaseId"])
                if release_id is None:
                    continue
                if local_covers.get(release_id):
                    result["coversAlreadyPresent"] += 1
                    continue
                relative = row.get("coverSavedPath")
                if not relative:
                    result["coverFilesMissing"] += 1
                    continue
                source = (folder / relative).resolve()
                try:
                    source.relative_to(folder)
                except ValueError:
                    result["coverFilesMissing"] += 1
                    continue
                if not source.is_file():
                    result["coverFilesMissing"] += 1
                    continue
                header = source.read_bytes()[:12]
                if header[:4] != b"RIFF" or header[8:12] != b"WEBP":
                    result["coverFilesMissing"] += 1
                    continue
                destination = cover_dir / f"rym-collection-{row['rymReleaseId']}.webp"
                shutil.copyfile(source, destination)
                url = f"/covers/{destination.name}"
                connection.execute("UPDATE music_releases SET cover_local=? WHERE id=? AND cover_local IS NULL",
                                   (url, release_id))
                local_covers[release_id] = url
                result["coversAdded"] += 1
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--expected-pages", type=int, default=94)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--covers-only", action="store_true")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--match", action="append", default=[], metavar="RYM_ID:RELEASE_ID",
                        help="Resolve a reviewed ambiguous row to an existing Music release")
    args = parser.parse_args()
    manual_matches = {}
    for pair in args.match:
        source_id, release_id = pair.split(":", 1)
        manual_matches[source_id] = int(release_id)
    pages, total = numbered_pages(args.folder, args.expected_pages)
    source_db = ROOT / "data" / "music.sqlite"
    if not source_db.is_file():
        raise FileNotFoundError(source_db)
    if args.covers_only:
        store = MusicStore(ROOT)
        report_path = args.report or ROOT / "data" / "music-imports" / "rym-collection-report.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report.update(attach_saved_covers(store, args.folder, pages))
    elif args.dry_run:
        with tempfile.TemporaryDirectory(prefix="rym-collection-") as temporary:
            trial_root = Path(temporary)
            backup_database(source_db, trial_root / "data" / "music.sqlite")
            report = import_pages(MusicStore(trial_root), pages, manual_matches)
    else:
        backup = ROOT / "data" / f"music.sqlite.backup-before-rym-collection-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}"
        backup_database(source_db, backup)
        report = import_pages(MusicStore(ROOT), pages, manual_matches)
        report.update(attach_saved_covers(MusicStore(ROOT), args.folder, pages))
        report["backupFile"] = str(backup)
    if not args.covers_only and report["sourceRows"] != total:
        raise ValueError("Liczba zaimportowanych wierszy różni się od sprawdzonych plików")
    if not args.covers_only:
        report["dryRun"] = args.dry_run
    output = args.report or ROOT / "data" / "music-imports" / ("rym-collection-dry-run.json" if args.dry_run else "rym-collection-report.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: len(value) if isinstance(value, list) else value for key, value in report.items()}, ensure_ascii=False))
    print(output)


if __name__ == "__main__":
    main()
