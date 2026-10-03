from __future__ import annotations

import csv
import hashlib
import html
import json
import re
import tempfile
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from threading import RLock
from zoneinfo import ZoneInfo


WARSAW = ZoneInfo("Europe/Warsaw")
REALISTIC_WEIGHT_MIN_KG = 30.0
REALISTIC_WEIGHT_MAX_KG = 300.0

SOURCE_DEFINITIONS = (
    {"id": "lastfm", "label": "Last.fm", "color": "#d92323", "private": True},
    {"id": "journal", "label": "Journal", "color": "#d9b36c", "private": True},
    {"id": "poems", "label": "Poems", "color": "#bd8fb3", "private": True},
    {"id": "cleaning", "label": "Cleaning", "color": "#6fc7b3", "private": False},
    {"id": "reading", "label": "Reading", "color": "#8ba7dc", "private": False},
    {"id": "habits", "label": "Habits", "color": "#c790d8", "private": True},
    {"id": "todos", "label": "Completed tasks", "color": "#db8c70", "private": True},
    {"id": "selfCare", "label": "Self-care", "color": "#df8faf", "private": True},
    {"id": "emotions", "label": "Emotions", "color": "#ef7d9b", "private": True},
    {"id": "health", "label": "Health & activity", "color": "#88c66e", "private": True},
    {"id": "culture", "label": "Culture & events", "color": "#9c94dd", "private": False},
)
SOURCE_IDS = {row["id"] for row in SOURCE_DEFINITIONS}


def _read_json(path: Path, fallback):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value
    except (OSError, ValueError, TypeError):
        return fallback


def _iso_day(value):
    raw = str(value or "").strip()
    if not raw:
        return None
    if len(raw) > 10:
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo:
                return parsed.astimezone(WARSAW).date().isoformat()
        except ValueError:
            pass
    candidate = raw[:10]
    try:
        return date.fromisoformat(candidate).isoformat()
    except ValueError:
        return None


def _epoch_day(value):
    try:
        number = float(value)
        if number > 10_000_000_000:
            number /= 1000
        return datetime.fromtimestamp(number, WARSAW).date().isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _number(value, default=0.0):
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return default


def _text(value, limit=500):
    return " ".join(str(value or "").split())[:limit]


def _content_text(value, content_format):
    raw = str(value or "")
    if str(content_format or "").lower() not in {"html", "rich_text", "rich-text"}:
        return raw
    with_breaks = re.sub(r"(?i)<\s*br\s*/?\s*>", "\n", raw)
    with_breaks = re.sub(r"(?i)</\s*(p|div|li|h[1-6])\s*>", "\n", with_breaks)
    without_comments = re.sub(r"<!--[\s\S]*?-->", "", with_breaks)
    return html.unescape(re.sub(r"<[^>]+>", "", without_comments)).replace("\xa0", " ").strip()


def _event(source, identifier, day, kind, title, *, occurred_at=None, summary="", details="", metrics=None, private=False):
    return {
        "id": f"{source}:{identifier}",
        "source": source,
        "day": day,
        "occurredAt": occurred_at or f"{day}T12:00:00",
        "kind": kind,
        "title": _text(title, 240),
        "summary": _text(summary, 800),
        "details": str(details or "")[:100_000],
        "metrics": metrics if isinstance(metrics, dict) else {},
        "private": bool(private),
    }


class TimelineActivityService:
    """Read-only adapters over dashboard stores, with a fingerprinted daily cache."""

    def __init__(self, root: Path, journal_store=None, lastfm_store=None, reading_store=None, cleaning_store=None):
        self.root = Path(root)
        self.journal_store = journal_store
        self.lastfm_store = lastfm_store
        self.reading_store = reading_store
        self.cleaning_store = cleaning_store
        self._cache = {}
        self._lock = RLock()

    @property
    def data(self):
        return self.root / "data"

    def _source_paths(self, source):
        paths = {
            "lastfm": [self.data / "lastfm.sqlite"],
            "journal": [self.data / "journal.sqlite", self.data / "journal.sqlite-wal", self.data / "journal.sqlite-shm"],
            "poems": [self.data / "journal.sqlite", self.data / "journal.sqlite-wal", self.data / "journal.sqlite-shm"],
            "cleaning": (
                [
                    Path(self.cleaning_store.db_path),
                    Path(f"{self.cleaning_store.db_path}-wal"),
                    Path(f"{self.cleaning_store.db_path}-shm"),
                ]
                if self.cleaning_store is not None
                else list((self.data / "settings").glob("cleaning-history-*.json"))
            ),
            "reading": (
                [
                    Path(self.reading_store.db_path),
                    Path(f"{self.reading_store.db_path}-wal"),
                    Path(f"{self.reading_store.db_path}-shm"),
                ]
                if self.reading_store is not None
                else [self.data / "settings" / "reading-history.json"]
            ),
            "habits": [self.data / "habit-data.json"],
            "todos": [self.data / "settings" / "todo.json"],
            "selfCare": [self.data / "timeline-activity" / "self-care.jsonl"],
            "emotions": [self.data / "timeline-activity" / "emotions.json"],
            "health": [
                self.data / "scale" / "steps.json",
                self.data / "scale" / "scale_measurements.jsonl",
                self.data / "scale" / "scale_measurements.csv",
                self.data / "diet" / "diet.json",
                self.data / "health-connect" / "snapshots.jsonl",
                self.data / "health-connect" / "latest.json",
            ],
            "culture": [self.data / "events.json", self.data / "films" / "library.json"],
        }
        return paths.get(source, [])

    def _fingerprint(self, sources):
        rows = []
        for source in sorted(sources):
            for path in self._source_paths(source):
                try:
                    stat = path.stat()
                    rows.append((str(path), stat.st_mtime_ns, stat.st_size))
                except OSError:
                    rows.append((str(path), 0, 0))
        return hashlib.sha256(json.dumps(rows).encode("utf-8")).hexdigest()

    def query(self, from_day, to_day, sources=None, journal_content="full"):
        start = date.fromisoformat(str(from_day))
        end = date.fromisoformat(str(to_day))
        if end < start:
            raise ValueError("The end date must not be earlier than the start date")
        if (end - start).days > 36525:
            raise ValueError("Date range is too large")
        enabled = set(SOURCE_IDS if sources is None else sources) & SOURCE_IDS
        content_mode = journal_content if journal_content in {"full", "summary", "metadata"} else "full"
        fingerprint = self._fingerprint(enabled)
        key = (start.isoformat(), end.isoformat(), tuple(sorted(enabled)), content_mode, fingerprint)
        with self._lock:
            cached = self._cache.get(key)
            if cached:
                return {**cached, "cache": {"hit": True, "fingerprint": fingerprint}}

        events = []
        statuses = []
        adapters = {
            "lastfm": lambda: self._lastfm(start, end),
            "journal": lambda: self._journal(start, end, content_mode, "journal"),
            "poems": lambda: self._journal(start, end, content_mode, "poem"),
            "cleaning": lambda: self._cleaning(start, end),
            "reading": lambda: self._reading(start, end),
            "habits": lambda: self._habits(start, end),
            "todos": lambda: self._todos(start, end),
            "selfCare": lambda: self._self_care(start, end),
            "emotions": lambda: self._emotions(start, end),
            "health": lambda: self._health(start, end),
            "culture": lambda: self._culture(start, end),
        }
        definitions = {row["id"]: row for row in SOURCE_DEFINITIONS}
        for source in sorted(enabled):
            try:
                source_events = adapters[source]()
                events.extend(source_events)
                statuses.append({**definitions[source], "available": True, "count": len(source_events)})
            except Exception as exc:
                statuses.append({**definitions[source], "available": False, "count": 0, "error": str(exc)[:300]})

        events.sort(key=lambda row: (row["day"], row.get("occurredAt") or "", row["id"]))
        by_day = defaultdict(list)
        for row in events:
            by_day[row["day"]].append(row)
        days = []
        for day, rows in sorted(by_day.items()):
            counts = Counter(row["source"] for row in rows)
            days.append({"date": day, "total": len(rows), "sourceCounts": dict(counts), "events": rows})

        result = {
            "schemaVersion": 1,
            "from": start.isoformat(),
            "to": end.isoformat(),
            "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "sources": statuses,
            "days": days,
            "totals": {"days": len(days), "events": len(events), "bySource": dict(Counter(row["source"] for row in events))},
            "cache": {"hit": False, "fingerprint": fingerprint},
        }
        with self._lock:
            if len(self._cache) > 24:
                self._cache.clear()
            self._cache[key] = result
        return result

    def _in_range(self, day, start, end):
        return bool(day and start.isoformat() <= day <= end.isoformat())

    def _lastfm(self, start, end):
        if not self.lastfm_store:
            return []
        events = []
        for row in self.lastfm_store.timeline_charts(start, end):
            granularity = row["granularity"]
            period = row["period"]
            if granularity in {"day", "week"}:
                day = period
            elif granularity == "month":
                day = f"{period}-01"
            else:
                day = f"{period}-01-01"
            artist = row.get("topArtist") or {}
            album = row.get("topAlbum") or {}
            track = row.get("topTrack") or {}
            parts = []
            if artist.get("name"):
                parts.append(f"Artist: {artist['name']} ({artist.get('scrobbles', 0)})")
            if album.get("name"):
                album_artist = album.get("artist") or artist.get("name")
                album_name = f"{album['name']} by {album_artist}" if album_artist else album["name"]
                parts.append(f"Album: {album_name} ({album.get('scrobbles', 0)})")
            if track.get("name"):
                track_artist = track.get("artist") or artist.get("name")
                track_name = f"{track['name']} by {track_artist}" if track_artist else track["name"]
                parts.append(f"Track: {track_name} ({track.get('scrobbles', 0)})")
            event = _event(
                "lastfm",
                f"{granularity}:{period}",
                day,
                "listening_chart",
                f"{row.get('scrobbles', 0):,} scrobbles",
                metrics=row,
                private=True,
            )
            event["summary"] = "\n".join(parts)
            events.append(event)
        return events

    def _journal(self, start, end, content_mode, entry_kind="journal"):
        if not self.journal_store:
            return []
        rows = self.journal_store.list(limit=10000)
        events = []
        for row in rows:
            row_kind = row.get("entryKind") or "journal"
            if row_kind != entry_kind:
                continue
            day = _iso_day(row.get("entryDate"))
            if not self._in_range(day, start, end):
                continue
            content = _content_text(row.get("content"), row.get("contentFormat"))
            if content_mode == "metadata":
                details = ""
                summary = "Poem" if entry_kind == "poem" else "Journal entry"
            elif content_mode == "summary":
                details = ""
                summary = _text(content, 260)
            else:
                details = content
                summary = _text(content, 260)
            events.append(_event(
                "poems" if entry_kind == "poem" else "journal",
                row.get("id"), day, "poem" if entry_kind == "poem" else "journal_entry",
                row.get("title") or ("Untitled poem" if entry_kind == "poem" else "Journal entry"),
                occurred_at=row.get("entryDate"), summary=summary, details=details,
                metrics={
                    "tags": row.get("tags") or [],
                    "contentFormat": row.get("contentFormat") or "plain_text",
                    "entryKind": row_kind,
                    "sourceType": row.get("sourceType") or "manual",
                },
                private=True,
            ))
        return events

    def _cleaning(self, start, end):
        events = []
        if self.cleaning_store is not None:
            for apartment in self.cleaning_store.list_apartments():
                apartment_id = apartment.get("id")
                if not apartment_id:
                    continue
                payload = self.cleaning_store.get_history(apartment_id, range_name="all")
                for index, row in enumerate(payload.get("actions") or []):
                    if not isinstance(row, dict):
                        continue
                    day = _iso_day(row.get("doneAt") or row.get("at"))
                    if not self._in_range(day, start, end):
                        continue
                    task = row.get("taskName") or row.get("task") or "Cleaning task"
                    place = " · ".join(filter(None, [_text(row.get("room"), 100), _text(row.get("category"), 100)]))
                    action_id = row.get("actionId") or row.get("id") or index
                    events.append(_event(
                        "cleaning", f"{apartment_id}:{action_id}", day, "cleaning_action", task,
                        occurred_at=row.get("doneAt") or row.get("at"), summary=place,
                        metrics={
                            "room": row.get("room"),
                            "category": row.get("category"),
                            "statusAfter": row.get("status"),
                            "apartment": apartment_id,
                        },
                    ))
            return events

        for path in (self.data / "settings").glob("cleaning-history-*.json"):
            rows = _read_json(path, [])
            if not isinstance(rows, list):
                continue
            apartment = path.stem.removeprefix("cleaning-history-")
            for index, row in enumerate(rows):
                if not isinstance(row, dict):
                    continue
                day = _iso_day(row.get("at"))
                if not self._in_range(day, start, end):
                    continue
                task = row.get("task") or "Cleaning task"
                place = " · ".join(filter(None, [_text(row.get("room"), 100), _text(row.get("category"), 100)]))
                events.append(_event(
                    "cleaning", f"{apartment}:{index}:{row.get('at')}", day, "cleaning_action", task,
                    occurred_at=row.get("at"), summary=place,
                    metrics={"room": row.get("room"), "category": row.get("category"), "statusAfter": row.get("status"), "apartment": apartment},
                ))
        return events

    def _reading(self, start, end):
        payload = (
            self.reading_store.history()
            if self.reading_store is not None
            else _read_json(self.data / "settings" / "reading-history.json", {})
        )
        log = payload.get("log", {}) if isinstance(payload, dict) else {}
        events = []
        for day, row in log.items():
            if not self._in_range(_iso_day(day), start, end) or not isinstance(row, dict):
                continue
            total = int(_number(row.get("total"), 0))
            if total <= 0:
                continue
            books = row.get("books") if isinstance(row.get("books"), dict) else {}
            details = []
            for title, value in books.items():
                if isinstance(value, dict):
                    pages = value.get("pages", value.get("count", value.get("total", "")))
                else:
                    pages = value
                details.append(f"{title}: {pages} pages" if pages not in (None, "") else str(title))
            events.append(_event(
                "reading", day, day, "reading", f"{total} pages read",
                summary=f"{len(books)} book(s)" if books else "", details="\n".join(details),
                metrics={"pages": total, "books": books, "progress": row.get("progress") or {}},
            ))
        return events

    def _habits(self, start, end):
        payload = _read_json(self.data / "habit-data.json", {})
        habits = payload.get("habits", []) if isinstance(payload, dict) else []
        events = []
        for habit in habits:
            if not isinstance(habit, dict):
                continue
            habit_type = int(_number(habit.get("type"), 0))
            for index, point in enumerate(habit.get("points") or []):
                if not isinstance(point, list) or len(point) < 2:
                    continue
                day = _epoch_day(point[0])
                value = _number(point[1], 0)
                if not self._in_range(day, start, end) or value <= 0:
                    continue
                if habit_type == 0:
                    display = "done"
                    metric_value = True
                else:
                    scaled = value / 1000
                    display_number = int(scaled) if scaled.is_integer() else round(scaled, 3)
                    display = f"{display_number}{(' ' + str(habit.get('unit'))) if habit.get('unit') else ''}"
                    metric_value = display_number
                events.append(_event(
                    "habits", f"{habit.get('id')}:{point[0]}:{index}", day, "habit", habit.get("name") or "Habit",
                    summary=display, metrics={"value": metric_value, "unit": habit.get("unit") or "", "habitType": habit_type}, private=True,
                ))
        return events

    def _todos(self, start, end):
        rows = _read_json(self.data / "settings" / "todo.json", [])
        events = []
        for index, row in enumerate(rows if isinstance(rows, list) else []):
            if not isinstance(row, dict) or not row.get("done"):
                continue
            day = _epoch_day(row.get("completedAt")) or _iso_day(row.get("completedAt"))
            if not self._in_range(day, start, end):
                continue
            events.append(_event(
                "todos", row.get("id") or index, day, "todo_completed", row.get("title") or "Completed task",
                occurred_at=datetime.fromtimestamp(float(row["completedAt"]) / 1000, timezone.utc).isoformat() if isinstance(row.get("completedAt"), (int, float)) else row.get("completedAt"),
                summary=_text(row.get("bucket"), 120), metrics={"bucket": row.get("bucket"), "due": row.get("due")}, private=True,
            ))
        return events

    def _self_care(self, start, end):
        path = self.data / "timeline-activity" / "self-care.jsonl"
        events = []
        if not path.exists():
            return events
        for index, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
            try:
                row = json.loads(line)
            except ValueError:
                continue
            day = _iso_day(row.get("occurredAt"))
            if self._in_range(day, start, end):
                events.append(_event("selfCare", row.get("id") or index, day, "self_care", row.get("title") or "Self-care", occurred_at=row.get("occurredAt"), summary=row.get("category") or "", private=True))
        return events

    def _emotions(self, start, end):
        payload = _read_json(self.data / "timeline-activity" / "emotions.json", {})
        events = []
        for row in payload.get("checkIns", []) if isinstance(payload, dict) else []:
            if not isinstance(row, dict):
                continue
            day = _iso_day(row.get("occurredAt"))
            if not self._in_range(day, start, end):
                continue
            mood = _text(row.get("mood") or str(row.get("moodKey") or "").replace("_", " "), 120)
            tags = row.get("tags") if isinstance(row.get("tags"), dict) else {}
            tag_parts = []
            for label, key in (("With", "people"), ("At", "places"), ("Events", "events")):
                values = tags.get(key) if isinstance(tags.get(key), list) else []
                if values:
                    tag_parts.append(f"{label}: {', '.join(map(str, values))}")
            detail_parts = []
            if row.get("notes"):
                detail_parts.append(str(row["notes"]))
            for label, key in (("Reflection", "reflections"), ("Takeaway", "takeaways")):
                values = row.get(key) if isinstance(row.get(key), list) else []
                for value in values:
                    if isinstance(value, dict):
                        text_value = str(value.get("text") or "").strip()
                        role = str(value.get("role") or "").strip()
                        if text_value:
                            detail_parts.append(f"{label}{f' ({role})' if role else ''}: {text_value}")
                    elif str(value or "").strip():
                        detail_parts.append(f"{label}: {value}")
            events.append(_event(
                "emotions", row.get("id"), day, "emotion_check_in", f"Feeling {mood}" if mood else "Emotion check-in",
                occurred_at=row.get("occurredAt"), summary=" · ".join(tag_parts), details="\n".join(detail_parts),
                metrics={"moodKey": row.get("moodKey"), "mood": mood, "tags": tags, "context": row.get("context") or {}},
                private=True,
            ))
        return events

    def import_emotions_csv(self, raw, filename="Check-in_data.csv"):
        if not isinstance(raw, (bytes, bytearray)) or not raw:
            raise ValueError("Uploaded emotions CSV is empty")
        text = None
        for encoding in ("utf-8-sig", "utf-8", "cp1250", "latin-1"):
            try:
                text = bytes(raw).decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            raise ValueError("Could not decode emotions CSV")
        rows = list(csv.DictReader(text.splitlines()))
        headers = set(rows[0].keys()) if rows else set()
        if "Date" not in headers or not ({"Mood Keys", "Mood"} & headers):
            raise ValueError("This is not a How We Feel check-in export (Date and Mood columns are required)")

        def split_tags(value):
            return [part.strip() for part in str(value or "").split(";") if part.strip()]

        def json_list(value):
            try:
                parsed = json.loads(str(value or "[]"))
                return parsed if isinstance(parsed, list) else []
            except ValueError:
                return []

        def optional_number(value):
            raw_value = str(value or "").strip()
            if not raw_value:
                return None
            try:
                number = float(raw_value.replace(",", "."))
                return int(number) if number.is_integer() else number
            except ValueError:
                return None

        check_ins = []
        skipped = []
        for line_number, row in enumerate(rows, 2):
            raw_date = str(row.get("Date") or "").strip()
            parsed_date = None
            for date_format in ("%Y %a %b %d %I:%M %p", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
                try:
                    parsed_date = datetime.strptime(raw_date, date_format).replace(tzinfo=WARSAW)
                    break
                except ValueError:
                    continue
            if parsed_date is None:
                skipped.append({"line": line_number, "reason": "invalid date"})
                continue
            mood_key = _text(row.get("Mood Keys") or row.get("Mood"), 120).lower().replace(" ", "_")
            mood = _text(row.get("Mood") or mood_key.replace("_", " "), 120)
            if not mood_key:
                skipped.append({"line": line_number, "reason": "missing mood"})
                continue
            occurred_at = parsed_date.isoformat(timespec="minutes")
            check_id = hashlib.sha256(f"{occurred_at}\0{mood_key}".encode("utf-8")).hexdigest()[:24]
            check_ins.append({
                "id": check_id,
                "occurredAt": occurred_at,
                "locale": _text(row.get("Locale"), 12),
                "moodKey": mood_key,
                "mood": mood,
                "tags": {
                    "people": split_tags(row.get("Tags (People)")),
                    "places": split_tags(row.get("Tags (Places)")),
                    "events": split_tags(row.get("Tags (Events)")),
                },
                "context": {
                    "exercise": optional_number(row.get("Exercise")),
                    "sleep": optional_number(row.get("Sleep")),
                    "menstrual": _text(row.get("Menstrual"), 120) or None,
                    "steps": optional_number(row.get("Steps")),
                    "meditation": optional_number(row.get("Meditation")),
                    "weather": _text(row.get("Weather"), 120) or None,
                    "temperatureF": optional_number(row.get("Temperature (F)")),
                    "waterCups": optional_number(row.get("Water (cups)")),
                    "caffeineMg": optional_number(row.get("Caffeine (mg)")),
                    "alcoholicDrinks": optional_number(row.get("Alcoholic Drinks")),
                },
                "notes": str(row.get("Notes") or "").strip(),
                "reflections": json_list(row.get("Reflections")),
                "takeaways": json_list(row.get("Takeaways")),
            })

        if not check_ins:
            raise ValueError("No valid emotion check-ins were found")
        destination = self.data / "timeline-activity" / "emotions.json"
        existing = _read_json(destination, {})
        existing_rows = existing.get("checkIns", []) if isinstance(existing, dict) else []
        by_id = {row.get("id"): row for row in existing_rows if isinstance(row, dict) and row.get("id")}
        imported = updated = duplicates = 0
        for row in check_ins:
            previous = by_id.get(row["id"])
            if previous is None:
                imported += 1
            elif previous == row:
                duplicates += 1
            else:
                updated += 1
            by_id[row["id"]] = row
        merged = sorted(by_id.values(), key=lambda row: (row.get("occurredAt") or "", row.get("id") or ""))
        output = {
            "schemaVersion": 1,
            "updatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "lastImportFile": Path(str(filename or "Check-in_data.csv")).name,
            "checkIns": merged,
        }
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=destination.parent, delete=False, suffix=".tmp") as handle:
            json.dump(output, handle, ensure_ascii=False, separators=(",", ":"))
            temporary_path = Path(handle.name)
        temporary_path.replace(destination)
        with self._lock:
            self._cache.clear()
        return {
            "ok": True,
            "file": Path(str(filename or "Check-in_data.csv")).name,
            "rows": len(rows),
            "valid": len(check_ins),
            "imported": imported,
            "updated": updated,
            "duplicates": duplicates,
            "skipped": len(skipped),
            "skippedDetails": skipped[:20],
            "total": len(merged),
            "range": {"from": merged[0]["occurredAt"][:10], "to": merged[-1]["occurredAt"][:10]},
        }

    def record_self_care(self, payload):
        candidates = (payload or {}).get("events") if isinstance((payload or {}).get("events"), list) else [payload or {}]
        path = self.data / "timeline-activity" / "self-care.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        existing_ids = set()
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    existing_ids.add(json.loads(line).get("id"))
                except ValueError:
                    pass
        rows = []
        for candidate in candidates[:500]:
            title = _text(candidate.get("title"), 240)
            if not title:
                continue
            occurred_at = str(candidate.get("occurredAt") or datetime.now(WARSAW).isoformat(timespec="seconds"))
            if not _iso_day(occurred_at):
                continue
            row = {
                "id": hashlib.sha256(f"{_iso_day(occurred_at)}\0{title}".encode("utf-8")).hexdigest()[:24],
                "occurredAt": occurred_at,
                "title": title,
                "category": _text(candidate.get("category"), 120),
            }
            if row["id"] not in existing_ids:
                existing_ids.add(row["id"])
                rows.append(row)
        if not rows and len(candidates) == 1 and not _text(candidates[0].get("title"), 240):
            raise ValueError("Missing self-care task title")
        with self._lock, path.open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
            self._cache.clear()
        return {"ok": True, "imported": len(rows), "duplicates": len(candidates) - len(rows), "events": rows}

    def _health(self, start, end):
        events = []
        steps_payload = _read_json(self.data / "scale" / "steps.json", {})
        for day, row in (steps_payload.get("days", {}) if isinstance(steps_payload, dict) else {}).items():
            if not self._in_range(_iso_day(day), start, end):
                continue
            steps = int(_number(row.get("steps") if isinstance(row, dict) else row, 0))
            if steps > 0:
                events.append(_event("health", f"steps:{day}", day, "steps", f"{steps:,} steps", metrics={"steps": steps}, private=True))

        weight_rows = []
        jsonl = self.data / "scale" / "scale_measurements.jsonl"
        csv_path = self.data / "scale" / "scale_measurements.csv"
        if jsonl.exists():
            for line in jsonl.read_text(encoding="utf-8").splitlines():
                try:
                    weight_rows.append(json.loads(line))
                except ValueError:
                    pass
        elif csv_path.exists():
            with csv_path.open("r", encoding="utf-8", newline="") as handle:
                weight_rows.extend(csv.DictReader(handle))
        weights = defaultdict(list)
        seen_weight_rows = set()
        for row in weight_rows:
            day = _iso_day(row.get("timestamp")) if isinstance(row, dict) else None
            value = _number(row.get("weight_kg"), -1) if isinstance(row, dict) else -1
            dedupe_key = (
                str(row.get("timestamp") or ""),
                round(value, 3),
                row.get("type"),
                row.get("raw_hex"),
            ) if isinstance(row, dict) else None
            if dedupe_key in seen_weight_rows:
                continue
            seen_weight_rows.add(dedupe_key)
            if self._in_range(day, start, end) and REALISTIC_WEIGHT_MIN_KG <= value <= REALISTIC_WEIGHT_MAX_KG:
                weights[day].append(value)
        for day, values in weights.items():
            average = round(sum(values) / len(values), 2)
            events.append(_event("health", f"weight:{day}", day, "weight", f"Weight: {average:g} kg", metrics={"averageKg": average, "measurements": len(values)}, private=True))

        diet = _read_json(self.data / "diet" / "diet.json", {})
        default_goal = int(_number(diet.get("goal_kcal"), 0)) if isinstance(diet, dict) else 0
        for day, row in (diet.get("days", {}) if isinstance(diet, dict) else {}).items():
            if not self._in_range(_iso_day(day), start, end) or not isinstance(row, dict):
                continue
            meals = row.get("meals") if isinstance(row.get("meals"), list) else []
            calories = sum(int(_number(meal.get("kcal"), 0)) for meal in meals if isinstance(meal, dict))
            if not meals and row.get("estimated_kcal"):
                calories = int(_number(row.get("estimated_kcal"), 0))
            if calories or meals:
                details = "\n".join(f"{meal.get('name')}: {int(_number(meal.get('kcal'), 0))} kcal" for meal in meals if isinstance(meal, dict))
                events.append(_event("health", f"diet:{day}", day, "diet", f"{calories} kcal", summary=f"{len(meals)} meal(s)", details=details, metrics={"kcal": calories, "goalKcal": int(_number(row.get("goal_kcal"), default_goal)), "mealCount": len(meals)}, private=True))

        snapshots_path = self.data / "health-connect" / "snapshots.jsonl"
        snapshot_rows = []
        if snapshots_path.exists():
            for line in snapshots_path.read_text(encoding="utf-8").splitlines():
                try:
                    snapshot_rows.append(json.loads(line))
                except ValueError:
                    pass
        else:
            latest = _read_json(self.data / "health-connect" / "latest.json", {})
            if latest:
                snapshot_rows.append(latest)
        seen_snapshots = set()
        for index, wrapper in enumerate(snapshot_rows):
            payload = wrapper.get("payload", wrapper) if isinstance(wrapper, dict) else {}
            day = _iso_day(wrapper.get("day") if isinstance(wrapper, dict) else None) or _iso_day(payload.get("day"))
            if not self._in_range(day, start, end) or day in seen_snapshots:
                continue
            seen_snapshots.add(day)
            metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
            sleep = payload.get("sleep") if isinstance(payload.get("sleep"), dict) else {}
            exercise = payload.get("exercise") if isinstance(payload.get("exercise"), dict) else {}
            active = _number(metrics.get("active_calories_kcal"), 0)
            sleep_count = int(_number(sleep.get("session_count"), len(sleep.get("sessions") or [])))
            exercise_count = int(_number(exercise.get("session_count"), len(exercise.get("sessions") or [])))
            if active or sleep_count or exercise_count:
                parts = []
                if active:
                    parts.append(f"{round(active):g} active kcal")
                if sleep_count:
                    parts.append(f"{sleep_count} sleep session(s)")
                if exercise_count:
                    parts.append(f"{exercise_count} exercise session(s)")
                events.append(_event("health", f"health-connect:{day}:{index}", day, "health_connect", "Health Connect", summary=" · ".join(parts), metrics={"activeCaloriesKcal": active, "sleepSessions": sleep_count, "exerciseSessions": exercise_count}, private=True))
        return events

    def _culture(self, start, end):
        events = []
        payload = _read_json(self.data / "films" / "library.json", {})
        for row in payload.get("items", []) if isinstance(payload, dict) else []:
            if not isinstance(row, dict) or not row.get("watched"):
                continue
            day = _iso_day(row.get("watched_date"))
            if self._in_range(day, start, end):
                meta = " · ".join(filter(None, [str(row.get("release_year") or ""), str(row.get("director") or "")]))
                events.append(_event("culture", f"film:{row.get('id')}", day, "film_watched", row.get("title") or "Film watched", summary=meta, metrics={"rating": row.get("rating_1_10"), "type": row.get("type")}, private=False))
        calendar = _read_json(self.data / "events.json", [])
        for index, row in enumerate(calendar if isinstance(calendar, list) else []):
            if not isinstance(row, dict):
                continue
            day = _iso_day(row.get("date"))
            if self._in_range(day, start, end):
                events.append(_event("culture", f"event:{row.get('id') or index}", day, "calendar_event", row.get("title") or "Event", summary=row.get("type") or row.get("source") or "", metrics={"type": row.get("type"), "source": row.get("source")}, private=False))
        return events
