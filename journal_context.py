"""Context snapshots for written-journal entries from The Great Timeline."""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from timeline_activity import SOURCE_DEFINITIONS
from timeline_store import date_bounds


CONTEXT_CATEGORY_IDS = (
    "relationships",
    "home",
    "work",
    "education",
    "health",
    "family",
    "travel",
    "interests",
    "external-events",
    "other",
)
CONTEXT_ACTIVITY_SOURCE_IDS = (
    "lastfm",
    "cleaning",
    "reading",
    "habits",
    "todos",
    "selfCare",
    "emotions",
    "health",
    "culture",
)
MAX_CONTEXT_DATES = 1000


def normalize_context_dates(values) -> list[str]:
    if not isinstance(values, list):
        raise ValueError("dates must be an array")
    normalized = []
    for value in values:
        try:
            day = date.fromisoformat(str(value or "").strip()).isoformat()
        except ValueError as exc:
            raise ValueError(f"Invalid journal context date: {value}") from exc
        if day not in normalized:
            normalized.append(day)
        if len(normalized) > MAX_CONTEXT_DATES:
            raise ValueError(f"At most {MAX_CONTEXT_DATES} context dates are allowed")
    return sorted(normalized)


def item_is_active_on(item: dict, day: str, today: str) -> bool:
    start_low, start_high = date_bounds(item.get("start") or {})
    if not start_low:
        return False
    if item.get("type") == "point":
        return start_low.isoformat() <= day <= (start_high or start_low).isoformat()
    if item.get("ongoing"):
        end_high = date.fromisoformat(today)
    else:
        _, end_high = date_bounds(item.get("end") or {})
    return bool(end_high and start_low.isoformat() <= day <= end_high.isoformat())


class JournalContextService:
    def __init__(self, timeline_store, activity_service):
        self.timeline_store = timeline_store
        self.activity_service = activity_service

    def query(self, values) -> dict:
        dates = normalize_context_dates(values)
        if not dates:
            return {"contexts": {}}

        snapshot = self.timeline_store.snapshot()
        categories = {row.get("id"): row for row in snapshot.get("categories", [])}
        people = {
            row.get("id"): str(row.get("name") or row.get("title") or "").strip()
            for row in snapshot.get("people", [])
        }
        today = date.today().isoformat()
        contexts = {
            day: {"timelineGroups": [], "activityGroups": []}
            for day in dates
        }

        items_by_date = {day: defaultdict(list) for day in dates}
        for item in snapshot.get("timelineItems", []):
            category_id = str(item.get("categoryId") or "")
            if category_id not in CONTEXT_CATEGORY_IDS:
                continue
            category = categories.get(category_id) or {}
            for day in dates:
                if not item_is_active_on(item, day, today):
                    continue
                item_people = [people.get(person_id, "") for person_id in item.get("peopleIds") or []]
                items_by_date[day][category_id].append({
                    "id": item.get("id"),
                    "type": item.get("type"),
                    "title": str(item.get("title") or ""),
                    "subcategory": str(item.get("subcategory") or ""),
                    "location": str(item.get("location") or ""),
                    "people": [name for name in item_people if name],
                    "ongoing": bool(item.get("ongoing")),
                    "private": bool(item.get("private")),
                })

        for day in dates:
            for category_id in CONTEXT_CATEGORY_IDS:
                items = items_by_date[day].get(category_id) or []
                if not items:
                    continue
                category = categories.get(category_id) or {}
                items.sort(key=lambda row: (row["type"] == "point", row["title"].casefold()))
                contexts[day]["timelineGroups"].append({
                    "id": category_id,
                    "label": str(category.get("name") or category_id),
                    "color": str(category.get("color") or "#858585"),
                    "items": items,
                })

        activity = self.activity_service.query(
            dates[0], dates[-1], CONTEXT_ACTIVITY_SOURCE_IDS, "metadata"
        )
        source_definitions = {row["id"]: row for row in SOURCE_DEFINITIONS}
        activity_by_date = {day: defaultdict(list) for day in dates}
        requested = set(dates)
        for row in activity.get("days", []):
            day = str(row.get("date") or "")
            if day not in requested:
                continue
            for event in row.get("events", []):
                source = str(event.get("source") or "")
                if source not in CONTEXT_ACTIVITY_SOURCE_IDS:
                    continue
                if source == "lastfm" and event.get("metrics", {}).get("granularity") != "day":
                    continue
                activity_by_date[day][source].append({
                    "id": event.get("id"),
                    "kind": event.get("kind"),
                    "title": str(event.get("title") or ""),
                    "summary": str(event.get("summary") or ""),
                    "occurredAt": event.get("occurredAt"),
                    "metrics": event.get("metrics") if isinstance(event.get("metrics"), dict) else {},
                    "private": bool(event.get("private")),
                })

        for day in dates:
            for source_id in CONTEXT_ACTIVITY_SOURCE_IDS:
                events = activity_by_date[day].get(source_id) or []
                if not events:
                    continue
                definition = source_definitions.get(source_id) or {}
                contexts[day]["activityGroups"].append({
                    "id": source_id,
                    "label": str(definition.get("label") or source_id),
                    "color": str(definition.get("color") or "#858585"),
                    "events": events,
                })

        return {
            "contexts": contexts,
            "range": {"from": dates[0], "to": dates[-1]},
            "requestedDates": len(dates),
        }


__all__ = [
    "CONTEXT_ACTIVITY_SOURCE_IDS",
    "CONTEXT_CATEGORY_IDS",
    "JournalContextService",
    "item_is_active_on",
    "normalize_context_dates",
]
