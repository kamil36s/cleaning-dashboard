"""SQLite persistence and validation for The Great Timeline."""

from __future__ import annotations

import calendar
import copy
import json
import re
import sqlite3
import threading
import uuid
from datetime import date, datetime, timezone
from pathlib import Path


SCHEMA_VERSION = 1
ENTITY_TABLES = {
    "timelineItems": "timeline_items",
    "people": "timeline_people",
    "categories": "timeline_categories",
    "sources": "timeline_sources",
    "itemLinks": "timeline_item_links",
    "reflections": "timeline_reflections",
}
ITEM_TYPES = {"point", "period", "phase"}
DATE_PRECISIONS = {
    "exact_day",
    "month",
    "year",
    "approximate_day",
    "approximate_month",
    "approximate_year",
    "date_range",
    "unknown",
}
DEFAULT_CATEGORIES = [
    ("relationships", "Relationships", "#b779a1", "heart"),
    ("people", "People", "#9b87bd", "people"),
    ("home", "Home", "#7f9b8e", "home"),
    ("work", "Work", "#7f98b8", "briefcase"),
    ("education", "Education", "#b49a67", "book"),
    ("health", "Health", "#8fae7a", "health"),
    ("family", "Family", "#b98b72", "family"),
    ("social", "Social", "#718fa0", "social"),
    ("travel", "Travel", "#8b9fbd", "travel"),
    ("projects", "Projects", "#a58b72", "project"),
    ("interests", "Interests", "#9b8e70", "star"),
    ("finance", "Finance", "#799b82", "finance"),
    ("external-events", "External events", "#858c96", "world"),
    ("other", "Other", "#858585", "dot"),
]


class TimelineError(Exception):
    def __init__(self, message: str, status: int = 400, code: str = "timeline_error", details=None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.details = details or []

    def as_payload(self):
        payload = {"error": str(self), "code": self.code}
        if self.details:
            payload["details"] = self.details
        return payload


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def safe_id(value, prefix="timeline"):
    candidate = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(value or "").strip()).strip("-.")
    return candidate[:120] if candidate else f"{prefix}-{uuid.uuid4().hex}"


def parse_date_value(value, precision, edge="start"):
    """Return a comparison date without changing the stored precision."""
    if precision == "unknown":
        return None
    if precision == "date_range":
        return None
    raw = str(value or "").strip()
    try:
        if precision in {"year", "approximate_year"}:
            year = int(raw)
            return date(year, 12 if edge == "end" else 1, 31 if edge == "end" else 1)
        if precision in {"month", "approximate_month"}:
            match = re.fullmatch(r"(\d{4})-(\d{2})", raw)
            if not match:
                return None
            year, month = map(int, match.groups())
            day = calendar.monthrange(year, month)[1] if edge == "end" else 1
            return date(year, month, day)
        return date.fromisoformat(raw)
    except (TypeError, ValueError):
        return None


def normalize_date_value(value, precision):
    raw = str(value or "").strip()
    if not raw:
        return None
    if precision in {"year", "approximate_year"}:
        return raw
    if precision in {"month", "approximate_month"}:
        display_match = re.fullmatch(r"(\d{2})/(\d{4})", raw)
        return f"{display_match.group(2)}-{display_match.group(1)}" if display_match else raw
    display_match = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", raw)
    return f"{display_match.group(3)}-{display_match.group(2)}-{display_match.group(1)}" if display_match else raw


def normalize_date_part(value, field_name, required=False):
    part = value if isinstance(value, dict) else {}
    precision = str(part.get("precision") or "exact_day").strip()
    if precision not in DATE_PRECISIONS:
        raise TimelineError(f"Invalid {field_name} precision", details=[field_name])
    normalized = {
        "date": normalize_date_value(part.get("date"), precision),
        "precision": precision,
        "earliest": normalize_date_value(part.get("earliest"), "exact_day"),
        "latest": normalize_date_value(part.get("latest"), "exact_day"),
    }
    if precision == "unknown":
        return normalized
    if precision == "date_range":
        earliest = parse_date_value(normalized["earliest"], "exact_day")
        latest = parse_date_value(normalized["latest"], "exact_day", "end")
        if not earliest or not latest or latest < earliest:
            raise TimelineError(f"{field_name} range requires valid earliest and latest dates", details=[field_name])
        return normalized
    parsed = parse_date_value(normalized["date"], precision)
    if required and not parsed:
        raise TimelineError(f"{field_name} is required", details=[field_name])
    if normalized["date"] and not parsed:
        raise TimelineError(f"Invalid {field_name}", details=[field_name])
    return normalized


def date_bounds(part):
    precision = part.get("precision")
    if precision == "date_range":
        return (
            parse_date_value(part.get("earliest"), "exact_day"),
            parse_date_value(part.get("latest"), "exact_day", "end"),
        )
    return (
        parse_date_value(part.get("date"), precision, "start"),
        parse_date_value(part.get("date"), precision, "end"),
    )


def normalize_item(payload, existing=None):
    if not isinstance(payload, dict):
        raise TimelineError("Timeline item must be an object")
    base = copy.deepcopy(existing or {})
    base.update(copy.deepcopy(payload))
    item_type = str(base.get("type") or "").strip()
    title = str(base.get("title") or "").strip()
    category_id = str(base.get("categoryId") or "").strip()
    if item_type not in ITEM_TYPES:
        raise TimelineError("Type must be point, period, or phase", details=["type"])
    if not title:
        raise TimelineError("Title is required", details=["title"])
    if not category_id:
        raise TimelineError("Category is required", details=["categoryId"])
    start = normalize_date_part(base.get("start"), "start", required=True)
    ongoing = bool(base.get("ongoing")) if item_type != "point" else False
    end = None
    if item_type != "point" and not ongoing:
        end = normalize_date_part(base.get("end"), "end", required=True)
    if ongoing and base.get("end") and any(base["end"].get(key) for key in ("date", "earliest", "latest")):
        raise TimelineError("Ongoing entries cannot have an end date", details=["end", "ongoing"])
    if item_type == "point":
        end = None
    if end:
        start_low, _ = date_bounds(start)
        _, end_high = date_bounds(end)
        if start_low and end_high and end_high < start_low:
            raise TimelineError("End cannot be before start", details=["end"])
    try:
        importance = int(base.get("importance", 3))
    except (TypeError, ValueError):
        importance = 3
    if importance < 1 or importance > 5:
        raise TimelineError("Importance must be between 1 and 5", details=["importance"])
    now = utc_now()
    normalized = {
        "id": safe_id(base.get("id"), "item"),
        "type": item_type,
        "categoryId": category_id,
        "subcategory": str(base.get("subcategory") or "").strip(),
        "title": title,
        "start": start,
        "end": end,
        "ongoing": ongoing,
        "importance": importance,
        "description": str(base.get("description") or "").strip(),
        "location": str(base.get("location") or "").strip(),
        "peopleIds": list(dict.fromkeys(str(v).strip() for v in (base.get("peopleIds") or []) if str(v).strip())),
        "parentId": str(base.get("parentId") or "").strip() or None,
        "tagIds": list(dict.fromkeys(str(v).strip() for v in (base.get("tagIds") or []) if str(v).strip())),
        "sourceIds": list(dict.fromkeys(str(v).strip() for v in (base.get("sourceIds") or []) if str(v).strip())),
        "notes": str(base.get("notes") or "").strip(),
        "private": bool(base.get("private", False)),
        "createdAt": str((existing or {}).get("createdAt") or base.get("createdAt") or now),
        "updatedAt": now,
    }
    if normalized["parentId"] == normalized["id"]:
        raise TimelineError("An item cannot be its own parent", details=["parentId"])
    return normalized


def normalize_category(payload, existing=None):
    if not isinstance(payload, dict):
        raise TimelineError("Category must be an object")
    base = copy.deepcopy(existing or {})
    base.update(copy.deepcopy(payload))
    name = str(base.get("name") or "").strip()
    if not name:
        raise TimelineError("Category name is required", details=["name"])
    color = str(base.get("color") or "#858585").strip()
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        raise TimelineError("Category color must be a six-digit hex color", details=["color"])
    now = utc_now()
    return {
        "id": safe_id(base.get("id") or name.lower(), "category"),
        "name": name,
        "color": color,
        "icon": str(base.get("icon") or "dot").strip(),
        "order": int(base.get("order") or 0),
        "visible": base.get("visible") is not False,
        "archived": bool(base.get("archived", False)),
        "allowedTypes": [value for value in (base.get("allowedTypes") or []) if value in ITEM_TYPES],
        "subcategories": list(dict.fromkeys(str(v).strip() for v in (base.get("subcategories") or []) if str(v).strip())),
        "createdAt": str((existing or {}).get("createdAt") or base.get("createdAt") or now),
        "updatedAt": now,
    }


def normalize_simple_entity(entity, payload, existing=None):
    if not isinstance(payload, dict):
        raise TimelineError(f"{entity} record must be an object")
    base = copy.deepcopy(existing or {})
    base.update(copy.deepcopy(payload))
    now = utc_now()
    base["id"] = safe_id(base.get("id"), entity.rstrip("s"))
    base["createdAt"] = str((existing or {}).get("createdAt") or base.get("createdAt") or now)
    base["updatedAt"] = now
    return base


class TimelineStore:
    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.RLock()

    def connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def initialize(self):
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.connect() as conn:
                for table in ENTITY_TABLES.values():
                    conn.execute(
                        f"CREATE TABLE IF NOT EXISTS {table} ("
                        "id TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
                    )
                count = conn.execute("SELECT COUNT(*) FROM timeline_categories").fetchone()[0]
                if not count:
                    for order, (category_id, name, color, icon) in enumerate(DEFAULT_CATEGORIES, 1):
                        category = normalize_category({
                            "id": category_id,
                            "name": name,
                            "color": color,
                            "icon": icon,
                            "order": order,
                        })
                        self._write(conn, "timeline_categories", category)

    def _write(self, conn, table, record):
        conn.execute(
            f"INSERT INTO {table} (id, payload, created_at, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at",
            (record["id"], json.dumps(record, ensure_ascii=False), record["createdAt"], record["updatedAt"]),
        )

    def _read_all(self, conn, table):
        return [json.loads(row["payload"]) for row in conn.execute(f"SELECT payload FROM {table} ORDER BY updated_at DESC")]

    def _get(self, conn, table, record_id):
        row = conn.execute(f"SELECT payload FROM {table} WHERE id = ?", (record_id,)).fetchone()
        return json.loads(row["payload"]) if row else None

    def snapshot(self):
        self.initialize()
        with self._lock, self.connect() as conn:
            result = {"schemaVersion": SCHEMA_VERSION}
            for entity, table in ENTITY_TABLES.items():
                result[entity] = self._read_all(conn, table)
            return result

    def summary(self):
        snapshot = self.snapshot()
        items = snapshot["timelineItems"]
        items.sort(key=lambda item: item.get("updatedAt", ""), reverse=True)
        return {
            "total": len(items),
            "active": sum(1 for item in items if item.get("ongoing")),
            "updatedAt": items[0].get("updatedAt") if items else None,
            "recent": [{"id": item["id"], "title": item["title"], "type": item["type"]} for item in items[:3]],
        }

    def _ensure_category(self, conn, category_id):
        if not self._get(conn, "timeline_categories", category_id):
            raise TimelineError("Selected category does not exist", details=["categoryId"])

    def create_item(self, payload):
        self.initialize()
        item = normalize_item(payload)
        with self._lock, self.connect() as conn:
            self._ensure_category(conn, item["categoryId"])
            if self._get(conn, "timeline_items", item["id"]):
                raise TimelineError("An item with this ID already exists", status=409, code="duplicate_id")
            self._write(conn, "timeline_items", item)
        return item

    def update_item(self, item_id, patch):
        self.initialize()
        with self._lock, self.connect() as conn:
            existing = self._get(conn, "timeline_items", item_id)
            if not existing:
                raise TimelineError("Timeline item not found", status=404, code="not_found")
            item = normalize_item({**patch, "id": item_id}, existing)
            self._ensure_category(conn, item["categoryId"])
            self._write(conn, "timeline_items", item)
        return item

    def delete_item(self, item_id):
        self.initialize()
        with self._lock, self.connect() as conn:
            if not self._get(conn, "timeline_items", item_id):
                raise TimelineError("Timeline item not found", status=404, code="not_found")
            linked = []
            for link in self._read_all(conn, "timeline_item_links"):
                if item_id in {link.get("fromItemId"), link.get("toItemId")}:
                    linked.append(link["id"])
            reflection_ids = [r["id"] for r in self._read_all(conn, "timeline_reflections") if r.get("itemId") == item_id]
            children = 0
            for child in self._read_all(conn, "timeline_items"):
                if child.get("parentId") == item_id:
                    child["parentId"] = None
                    child["updatedAt"] = utc_now()
                    self._write(conn, "timeline_items", child)
                    children += 1
            conn.execute("DELETE FROM timeline_items WHERE id = ?", (item_id,))
            conn.executemany("DELETE FROM timeline_item_links WHERE id = ?", [(value,) for value in linked])
            conn.executemany("DELETE FROM timeline_reflections WHERE id = ?", [(value,) for value in reflection_ids])
        return {"ok": True, "id": item_id, "removedLinks": len(linked), "removedReflections": len(reflection_ids), "detachedChildren": children}

    def create_category(self, payload):
        self.initialize()
        category = normalize_category(payload)
        with self._lock, self.connect() as conn:
            if self._get(conn, "timeline_categories", category["id"]):
                raise TimelineError("A category with this ID already exists", status=409, code="duplicate_id")
            self._write(conn, "timeline_categories", category)
        return category

    def update_category(self, category_id, patch):
        self.initialize()
        with self._lock, self.connect() as conn:
            existing = self._get(conn, "timeline_categories", category_id)
            if not existing:
                raise TimelineError("Category not found", status=404, code="not_found")
            category = normalize_category({**patch, "id": category_id}, existing)
            self._write(conn, "timeline_categories", category)
        return category

    def delete_category(self, category_id, move_to=None):
        self.initialize()
        with self._lock, self.connect() as conn:
            if not self._get(conn, "timeline_categories", category_id):
                raise TimelineError("Category not found", status=404, code="not_found")
            used = [item for item in self._read_all(conn, "timeline_items") if item.get("categoryId") == category_id]
            if used and not move_to:
                raise TimelineError("Category is used by timeline items", status=409, code="category_in_use", details=[item["id"] for item in used])
            if move_to:
                if move_to == category_id:
                    raise TimelineError("Choose a different destination category")
                self._ensure_category(conn, move_to)
                for item in used:
                    item["categoryId"] = move_to
                    item["updatedAt"] = utc_now()
                    self._write(conn, "timeline_items", item)
            conn.execute("DELETE FROM timeline_categories WHERE id = ?", (category_id,))
        return {"ok": True, "id": category_id, "movedItems": len(used)}

    def _normalize_snapshot(self, snapshot, existing_category_ids=None):
        if not isinstance(snapshot, dict):
            raise TimelineError("Import must be a JSON object", code="invalid_import")
        if int(snapshot.get("schemaVersion", 0)) != SCHEMA_VERSION:
            raise TimelineError(f"Unsupported schemaVersion; expected {SCHEMA_VERSION}", code="invalid_schema")
        normalized = {"schemaVersion": SCHEMA_VERSION}
        errors = []
        for entity in ENTITY_TABLES:
            rows = snapshot.get(entity, [])
            if not isinstance(rows, list):
                errors.append(f"{entity} must be an array")
                continue
            normalized[entity] = []
            seen = set()
            for index, row in enumerate(rows):
                try:
                    if entity == "timelineItems":
                        value = normalize_item(row)
                        value["createdAt"] = str(row.get("createdAt") or value["createdAt"])
                        value["updatedAt"] = str(row.get("updatedAt") or value["updatedAt"])
                    elif entity == "categories":
                        value = normalize_category(row)
                    else:
                        value = normalize_simple_entity(entity, row)
                    value["createdAt"] = str(row.get("createdAt") or value["createdAt"])
                    value["updatedAt"] = str(row.get("updatedAt") or value["updatedAt"])
                    if value["id"] in seen:
                        raise TimelineError("duplicate ID in import")
                    seen.add(value["id"])
                    normalized[entity].append(value)
                except (TimelineError, TypeError, ValueError) as exc:
                    errors.append(f"{entity}[{index}]: {exc}")
        category_ids = {
            *(str(value) for value in (existing_category_ids or [])),
            *(row["id"] for row in normalized.get("categories", [])),
        }
        for index, item in enumerate(normalized.get("timelineItems", [])):
            if item["categoryId"] not in category_ids:
                errors.append(f"timelineItems[{index}]: unknown categoryId {item['categoryId']}")
        if errors:
            raise TimelineError("Import validation failed", code="invalid_import", details=errors[:100])
        return normalized

    def import_snapshot(self, snapshot, mode="merge", conflict="overwrite", dry_run=False):
        if mode not in {"merge", "replace"}:
            raise TimelineError("Import mode must be merge or replace")
        if conflict not in {"overwrite", "skip"}:
            raise TimelineError("Conflict strategy must be overwrite or skip")
        self.initialize()
        with self._lock, self.connect() as conn:
            existing = {entity: {row["id"] for row in self._read_all(conn, table)} for entity, table in ENTITY_TABLES.items()}
            normalized = self._normalize_snapshot(
                snapshot,
                existing_category_ids=existing["categories"] if mode == "merge" else [],
            )
            report = {"new": 0, "changed": 0, "conflicts": 0, "skipped": 0, "byEntity": {}}
            for entity, table in ENTITY_TABLES.items():
                counts = {"new": 0, "changed": 0, "conflicts": 0, "skipped": 0}
                for row in normalized.get(entity, []):
                    if row["id"] in existing[entity]:
                        counts["conflicts"] += 1
                        if conflict == "skip" and mode == "merge":
                            counts["skipped"] += 1
                        else:
                            counts["changed"] += 1
                    else:
                        counts["new"] += 1
                report["byEntity"][entity] = counts
                for key in ("new", "changed", "conflicts", "skipped"):
                    report[key] += counts[key]
            if dry_run:
                return report
            if mode == "replace":
                for table in ENTITY_TABLES.values():
                    conn.execute(f"DELETE FROM {table}")
            for entity, table in ENTITY_TABLES.items():
                for row in normalized.get(entity, []):
                    if mode == "merge" and conflict == "skip" and row["id"] in existing[entity]:
                        continue
                    self._write(conn, table, row)
        return report


TIMELINE_STORE = TimelineStore(Path(__file__).resolve().parent / "data" / "timeline.sqlite")
