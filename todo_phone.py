"""Small, atomic phone operations on the dashboard's existing todo JSON."""

import json
import time
import uuid


VISIBLE_BUCKETS = {"now", "shopping"}


def active_items(items):
    if not isinstance(items, list):
        return []
    return [
        {"id": item["id"], "title": item["title"], "bucket": item["bucket"], "due": item.get("due")}
        for item in items
        if isinstance(item, dict)
        and item.get("bucket") in VISIBLE_BUCKETS
        and not item.get("done")
        and isinstance(item.get("id"), str)
        and isinstance(item.get("title"), str)
    ]


def apply_action(items, payload):
    if not isinstance(items, list) or not isinstance(payload, dict):
        raise ValueError("Invalid todo data")
    action = payload.get("action")
    if action == "add":
        bucket = payload.get("bucket")
        title = payload.get("title")
        if bucket not in VISIBLE_BUCKETS or not isinstance(title, str) or not 0 < len(title.strip()) <= 120:
            raise ValueError("Invalid title or list")
        now = int(time.time() * 1000)
        return items + [{
            "id": str(uuid.uuid4()), "title": title.strip(), "bucket": bucket,
            "due": None, "done": False, "completedAt": None,
            "createdAt": now, "updatedAt": now,
        }]
    if action == "complete":
        item_id = payload.get("id")
        for item in items:
            if isinstance(item, dict) and item.get("id") == item_id and item.get("bucket") in VISIBLE_BUCKETS and not item.get("done"):
                now = int(time.time() * 1000)
                return [
                    {**entry, "done": True, "completedAt": now, "updatedAt": now} if entry is item else entry
                    for entry in items
                ]
        raise ValueError("Active item not found")
    raise ValueError("Unknown todo action")


def update_file(path, payload, lock, temp_path, replace_file):
    path.parent.mkdir(parents=True, exist_ok=True)
    with lock(path):
        items = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        result = apply_action(items, payload)
        temporary = temp_path(path)
        try:
            temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            replace_file(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    return active_items(result)
