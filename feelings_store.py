from __future__ import annotations

import csv
import colorsys
import hashlib
import io
import json
import os
import re
import sqlite3
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable


SEED_VERSION = "1"
SEED_EXPECTED_COUNT = 467
SEED_EXPECTED_OLDEST = "2024-07-16T10:26"
SEED_EXPECTED_NEWEST = "2026-07-06T12:13"
SCHEMA_VERSION = 1
QUADRANTS = {
    "high_unpleasant": {"color": "#ff4661", "energy": 0.72, "pleasantness": -0.72},
    "high_pleasant": {"color": "#ffc83d", "energy": 0.72, "pleasantness": 0.72},
    "low_unpleasant": {"color": "#6f91ff", "energy": -0.72, "pleasantness": -0.72},
    "low_pleasant": {"color": "#49dda0", "energy": -0.72, "pleasantness": 0.72},
}

METER_LAYOUT = (
    ("Enraged", "Terrified", "Panicked", "Shocked", "Impassioned", "Hyper", "Surprised", "Awe", "Exhilarated", "Thrilled", "Elated", "Ecstatic"),
    ("Livid", "Irate", "Overwhelmed", "Stressed", "Annoyed", "Pressured", "Excited", "Determined", "Successful", "Amazed", "Inspired", "Empowered"),
    ("Furious", "Frightened", "Anxious", "Apprehensive", "Irritated", "Restless", "Energized", "Eager", "Enthusiastic", "Joyful", "Productive", "Proud"),
    ("Jealous", "Scared", "Angry", "Jittery", "Fomo", "Confused", "Cheerful", "Curious", "Upbeat", "Happy", "Motivated", "Optimistic"),
    ("Envious", "Repulsed", "Frustrated", "Embarrassed", "Concerned", "Tense", "Pleasant", "Focused", "Alive", "Confident", "Engaged", "Challenged"),
    ("Contempt", "Troubled", "Worried", "Nervous", "Peeved", "Uneasy", "Pleased", "Playful", "Delighted", "Wishful", "Hopeful", "Accomplished"),
    ("Disgusted", "Trapped", "Insecure", "Disheartened", "Down", "Bored", "Calm", "At ease", "Understood", "Respected", "Fulfilled", "Blissful"),
    ("Humiliated", "Ashamed", "Lost", "Disappointed", "Meh", "Tired", "Good", "Thoughtful", "Appreciated", "Supported", "Loved", "Connected"),
    ("Pessimistic", "Vulnerable", "Disconnected", "Forlorn", "Sad", "Fatigued", "Relaxed", "Chill", "Compassionate", "Included", "Valued", "Grateful"),
    ("Guilty", "Numb", "Excluded", "Spent", "Discouraged", "Disengaged", "Sympathetic", "Comfortable", "Empathetic", "Content", "Accepted", "Moved"),
    ("Depressed", "Hopeless", "Alienated", "Nostalgic", "Lonely", "Apathetic", "Mellow", "Peaceful", "Balanced", "Safe", "Secure", "Blessed"),
    ("Miserable", "Despair", "Glum", "Burned out", "Exhausted", "Helpless", "Carefree", "Tranquil", "Thankful", "Relieved", "Satisfied", "Serene"),
)
METER_POSITIONS = {
    name: (row_index, column_index)
    for row_index, row in enumerate(METER_LAYOUT)
    for column_index, name in enumerate(row)
}


class FeelingsError(Exception):
    def __init__(self, message: str, *, status: int = 400, code: str = "feelings_error"):
        super().__init__(message)
        self.status = status
        self.code = code

    def as_payload(self) -> dict[str, Any]:
        return {"ok": False, "error": str(self), "code": self.code}


HIGH_UNPLEASANT = {
    "Agitated", "Alarmed", "Angry", "Annoyed", "Anxious", "Apprehensive", "Concerned",
    "Contempt", "Disgusted", "Enraged", "Frightened", "Frustrated", "Furious", "Horrified",
    "Irritated", "Jittery", "Mad", "Nervous", "Overwhelmed", "Panicked", "Peeved",
    "Pressured", "Repulsed", "Restless", "Scared", "Stressed", "Tense", "Terrified",
    "Terriﬁed", "Troubled", "Uneasy", "Worried",
}
HIGH_PLEASANT = {
    "Accomplished", "Alive", "Alert", "Amazed", "Cheerful", "Curious", "Determined",
    "Energized", "Enthusiastic", "Excited", "Focused", "Happy", "Hyper", "Inspired",
    "Motivated", "Optimistic", "Playful", "Productive", "Proud", "Surprised", "Thrilled",
    "Upbeat",
}
LOW_PLEASANT = {
    "Accepted", "Affectionate", "At ease", "Balanced", "Blessed", "Blissful", "Calm",
    "Carefree", "Chill", "Comfortable", "Connected", "Content", "Empathetic", "Fulfilled",
    "Fulﬁlled", "Good", "Loved", "Loving", "Moved", "Peaceful", "Pleasant", "Present",
    "Refreshed", "Relaxed", "Relieved", "Respected", "Satisfied", "Satisﬁed", "Thankful",
    "Thoughtful", "Tranquil", "Understood", "Valued", "Whole", "Zen",
}


DEFINITIONS = {
    "Anxious": "uneasy or worried about what may happen",
    "Angry": "feeling strong displeasure or hostility",
    "Annoyed": "slightly angry or bothered",
    "Burned out": "feeling exhausted from ongoing stress",
    "Calm": "feeling free of stress, agitation, and worry",
    "Chill": "feeling relaxed and easygoing",
    "Discouraged": "feeling a loss of confidence and enthusiasm",
    "Disengaged": "feeling unable to focus or interested",
    "Frightened": "afraid or fearful",
    "Good": "feeling positive and generally well",
    "Hopeless": "feeling completely defeated and in despair about the future",
    "Jittery": "feeling nervous, restless, or unable to settle",
    "Lonely": "feeling sad because you are alone or disconnected",
    "Loved": "feeling like someone cares deeply for you",
    "Meh": "feeling uninspired or blah",
    "Miserable": "feeling absolutely awful",
    "Moved": "emotionally touched by something meaningful",
    "Nervous": "worried or uneasy about something",
    "Overwhelmed": "feeling that there is too much to handle",
    "Peaceful": "feeling quiet, settled, and free from disturbance",
    "Pressured": "feeling as if an important outcome depends on you",
    "Productive": "feeling like you are accomplishing your tasks or goals",
    "Relaxed": "feeling at ease and free from tension",
    "Sad": "feeling unhappy or sorrowful",
    "Tense": "feeling unable to relax because of worry or strain",
    "Tired": "feeling in need of rest or sleep",
    "Worried": "troubled about actual or potential problems",
}


REFERENCE_EMOTIONS = [
    ("Abandoned", "feeling left behind and not considered, wanted, or cared about", "low_unpleasant"),
    ("Absorbed", "fully focused and interested", "high_pleasant"),
    ("Abused", "experiencing cruel or unjust treatment", "low_unpleasant"),
    ("Accepted", "feeling acknowledged and seen", "low_pleasant"),
    ("Adoring", "feeling a deep love or respect for someone", "high_pleasant"),
    ("Affectionate", "feeling or showing fondness", "low_pleasant"),
    ("Afraid", "experiencing fear or threat", "high_unpleasant"),
    ("Agitated", "very troubled and restless", "high_unpleasant"),
    ("Alarmed", "a sense of urgent fear or concern", "high_unpleasant"),
    ("Alert", "feeling awake and focused", "high_pleasant"),
    ("Alienated", "feeling made a stranger to others", "low_unpleasant"),
    ("Alive", "filled with energy and vitality", "high_pleasant"),
    ("Amazed", "feeling lost in wonder about an event", "high_pleasant"),
    ("Ambivalent", "having contradictory feelings about something", "high_unpleasant"),
    ("Amused", "finding something funny or entertaining", "high_pleasant"),
    ("Carefree", "feeling free of worry and lighthearted", "low_pleasant"),
    ("Challenged", "feeling pushed to reach a higher goal", "high_pleasant"),
    ("Chatty", "feeling like talking in a friendly, informal way", "high_pleasant"),
    ("Hesitant", "unsure or slow in thinking, acting, or speaking", "low_unpleasant"),
    ("Hollow", "feeling that something is missing", "low_unpleasant"),
    ("Homesick", "longing for the familiarity of home when away", "low_unpleasant"),
    ("Hopeful", "optimistic that something good will happen", "high_pleasant"),
    ("Horrified", "experiencing intense fear or disgust", "high_unpleasant"),
    ("Hurting", "experiencing physical or emotional pain", "low_unpleasant"),
    ("Longing", "a strong desire for something distant or unattainable", "low_unpleasant"),
    ("Loving", "feeling love toward someone", "low_pleasant"),
    ("Mad", "feeling intensely angry", "high_unpleasant"),
    ("Present", "fully aware of the moment and free of internal noise", "low_pleasant"),
    ("Protective", "feeling the need to keep someone or something safe", "low_pleasant"),
    ("Refreshed", "feeling rested and restored", "low_pleasant"),
    ("Weary", "tired and lacking strength to push forward", "low_unpleasant"),
    ("Whole", "inner fullness and a sense of wellbeing", "low_pleasant"),
    ("Wishful", "having or showing a wish or longing", "high_pleasant"),
    ("Wistful", "desire with a trace of sadness", "low_unpleasant"),
    ("Worthless", "feeling you have no real value", "low_unpleasant"),
    ("Zen", "fully present and calm", "low_pleasant"),
]


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _slug(value: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-") or "emotion"
    return base[:48]


def _stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:8]
    return f"{prefix}-{_slug(value)}-{digest}"


def _meter_quadrant(row: int, column: int) -> str:
    if row < 6:
        return "high_unpleasant" if column < 6 else "high_pleasant"
    return "low_unpleasant" if column < 6 else "low_pleasant"


def _hsl_hex(hue: float, saturation: float, lightness: float) -> str:
    red, green, blue = colorsys.hls_to_rgb((hue % 360) / 360, lightness, saturation)
    return f"#{round(red * 255):02x}{round(green * 255):02x}{round(blue * 255):02x}"


def _meter_color(row: int, column: int) -> str:
    quadrant = _meter_quadrant(row, column)
    vertical = (row % 6) / 5
    horizontal = (column % 6) / 5
    if quadrant == "high_unpleasant":
        return _hsl_hex(344 + 22 * horizontal, .92, .55 + .07 * (horizontal + vertical) / 2)
    if quadrant == "high_pleasant":
        return _hsl_hex(38 + 14 * vertical + 3 * horizontal, .95, .55 + .09 * vertical)
    if quadrant == "low_unpleasant":
        return _hsl_hex(225 - 24 * horizontal - 8 * vertical, .90, .64 - .08 * vertical)
    return _hsl_hex(143 + 11 * horizontal + 18 * vertical, .80, .67 - .13 * (horizontal + vertical) / 2)


def _quadrant_for(name: str) -> str:
    meter_position = METER_POSITIONS.get(name)
    if meter_position:
        return _meter_quadrant(*meter_position)
    if name in HIGH_UNPLEASANT:
        return "high_unpleasant"
    if name in HIGH_PLEASANT:
        return "high_pleasant"
    if name in LOW_PLEASANT:
        return "low_pleasant"
    return "low_unpleasant"


def _tag_category(name: str) -> str | None:
    place = {"Home", "Work (home office)", "Office", "Outside", "Park", "Jessy's place", "Supermarket"}
    people = {"By Myself", "Friends", "Co-Workers", "Jess", "Margo", "Wera", "Therapist"}
    body = {"Hungry", "Sick/getting sick", "Hangover", "Resting"}
    substance = {"Caffeine", "Alcohol", "Smoking", "Pregabalin"}
    if name in place:
        return "place"
    if name in people:
        return "people"
    if name in body:
        return "body/state"
    if name in substance:
        return "substance/context"
    return "activity"


def _validate_timestamp(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise FeelingsError("Timestamp is required", code="invalid_timestamp")
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FeelingsError("Invalid timestamp", code="invalid_timestamp") from exc
    return text


class FeelingsService:
    def __init__(self, database_path: str | Path, seed_paths: Iterable[str | Path] = ()):
        self.database_path = Path(database_path)
        self.seed_paths = [Path(path) for path in seed_paths if path]

    def _connect(self) -> sqlite3.Connection:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def initialize(self) -> dict[str, Any]:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS feelings_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS feelings_emotions (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    description TEXT NOT NULL DEFAULT '',
                    quadrant TEXT NOT NULL,
                    energy REAL NOT NULL,
                    pleasantness REAL NOT NULL,
                    color TEXT NOT NULL,
                    x REAL,
                    y REAL,
                    shape TEXT NOT NULL DEFAULT 'circle',
                    is_custom INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS feelings_checkins (
                    id TEXT PRIMARY KEY,
                    occurred_at TEXT NOT NULL,
                    timezone TEXT NOT NULL,
                    note TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL,
                    source_device TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    sync_id TEXT UNIQUE,
                    deleted_at TEXT,
                    schema_version INTEGER NOT NULL DEFAULT 1,
                    source_date_text TEXT,
                    source_block_text TEXT,
                    source_payload TEXT
                );
                CREATE TABLE IF NOT EXISTS feelings_checkin_emotions (
                    checkin_id TEXT NOT NULL REFERENCES feelings_checkins(id) ON DELETE CASCADE,
                    emotion_id TEXT NOT NULL REFERENCES feelings_emotions(id),
                    position INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (checkin_id, emotion_id)
                );
                CREATE TABLE IF NOT EXISTS feelings_tags (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    category TEXT,
                    is_custom INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS feelings_checkin_tags (
                    checkin_id TEXT NOT NULL REFERENCES feelings_checkins(id) ON DELETE CASCADE,
                    tag_id TEXT NOT NULL REFERENCES feelings_tags(id),
                    PRIMARY KEY (checkin_id, tag_id)
                );
                CREATE INDEX IF NOT EXISTS feelings_checkins_occurred_idx
                    ON feelings_checkins(occurred_at DESC);
                CREATE INDEX IF NOT EXISTS feelings_checkins_deleted_idx
                    ON feelings_checkins(deleted_at);
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO feelings_metadata(key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            self._seed_reference_catalog(connection)
        imported = self.import_seed_if_needed()
        return {"ok": True, "database": str(self.database_path), **imported}

    def _seed_reference_catalog(self, connection: sqlite3.Connection) -> None:
        entries: dict[str, tuple[str, str]] = {
            name: (description, quadrant) for name, description, quadrant in REFERENCE_EMOTIONS
        }
        for name, (row, column) in METER_POSITIONS.items():
            entries.setdefault(name, (DEFINITIONS.get(name, f"feeling {name.casefold()}"), _meter_quadrant(row, column)))
        for name in HIGH_UNPLEASANT | HIGH_PLEASANT | LOW_PLEASANT:
            entries.setdefault(name, (DEFINITIONS.get(name, f"feeling {name.casefold()}"), _quadrant_for(name)))
        seed = self._find_seed_path()
        if seed:
            try:
                payload = json.loads(seed.read_text(encoding="utf-8"))
                for row in payload.get("checkins", []):
                    name = str(row.get("emotion") or "").strip()
                    if name:
                        entries.setdefault(name, (DEFINITIONS.get(name, f"feeling {name.casefold()}"), _quadrant_for(name)))
            except (OSError, json.JSONDecodeError):
                pass
        for name in sorted(entries, key=str.casefold):
            description, quadrant = entries[name]
            self._ensure_emotion(connection, name, description=description, quadrant=quadrant, is_custom=False)
        self._sync_meter_catalog(connection)

    def _sync_meter_catalog(self, connection: sqlite3.Connection) -> None:
        updated = _now()
        for name, (row, column) in METER_POSITIONS.items():
            quadrant = _meter_quadrant(row, column)
            energy = round((5.5 - row) / 5.5, 4)
            pleasantness = round((column - 5.5) / 5.5, 4)
            connection.execute(
                """UPDATE feelings_emotions
                   SET quadrant = ?, energy = ?, pleasantness = ?, color = ?, x = ?, y = ?, updated_at = ?
                   WHERE name = ? COLLATE NOCASE""",
                (quadrant, energy, pleasantness, _meter_color(row, column), column, row, updated, name),
            )

    def _find_seed_path(self) -> Path | None:
        env_path = os.environ.get("FEELINGS_SEED_PATH")
        candidates = ([Path(env_path)] if env_path else []) + self.seed_paths
        return next((path for path in candidates if path.is_file()), None)

    def import_seed_if_needed(self) -> dict[str, Any]:
        with self._connect() as connection:
            marker = connection.execute(
                "SELECT value FROM feelings_metadata WHERE key = 'feelings_seed_version'"
            ).fetchone()
            if marker and marker["value"] == SEED_VERSION:
                count = connection.execute(
                    "SELECT COUNT(*) AS count FROM feelings_checkins WHERE source = 'legacy How We Feel import'"
                ).fetchone()["count"]
                return {"seedStatus": "already_imported", "legacyCount": count}

        seed_path = self._find_seed_path()
        if not seed_path:
            return {"seedStatus": "not_found", "legacyCount": 0}
        try:
            payload = json.loads(seed_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise FeelingsError("The feelings seed file is malformed", status=500, code="malformed_seed") from exc
        records = payload.get("checkins")
        if not isinstance(records, list):
            raise FeelingsError("The feelings seed has no checkins array", status=500, code="malformed_seed")
        timestamps = sorted(str(row.get("timestamp_local") or "") for row in records)
        if len(records) != SEED_EXPECTED_COUNT or not timestamps or timestamps[0] != SEED_EXPECTED_OLDEST or timestamps[-1] != SEED_EXPECTED_NEWEST:
            raise FeelingsError(
                "Feelings seed validation failed; expected 467 records from 2024-07-16T10:26 to 2026-07-06T12:13",
                status=500,
                code="seed_validation_failed",
            )
        now = _now()
        with self._connect() as connection:
            for row in records:
                checkin_id = str(row.get("id") or "").strip()
                if not checkin_id:
                    raise FeelingsError("Legacy check-in is missing an id", status=500, code="malformed_seed")
                emotion_name = str(row.get("emotion") or "").strip()
                if not emotion_name:
                    raise FeelingsError(f"Legacy check-in {checkin_id} has no emotion", status=500, code="missing_emotion")
                emotion_id = self._ensure_emotion(
                    connection,
                    emotion_name,
                    description=DEFINITIONS.get(emotion_name, f"feeling {emotion_name.casefold()}"),
                    quadrant=_quadrant_for(emotion_name),
                    is_custom=False,
                )
                occurred_at = _validate_timestamp(row.get("timestamp_local"))
                connection.execute(
                    """
                    INSERT OR IGNORE INTO feelings_checkins(
                        id, occurred_at, timezone, note, source, source_device, created_at, updated_at,
                        sync_id, schema_version, source_date_text, source_block_text, source_payload
                    ) VALUES (?, ?, ?, ?, 'legacy How We Feel import', 'legacy-pdf', ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        checkin_id, occurred_at, str(row.get("timezone") or "Europe/Warsaw"),
                        str(row.get("note_or_reflection") or ""), now, now, checkin_id,
                        SCHEMA_VERSION, str(row.get("source_date_text") or ""),
                        str(row.get("source_block_text") or ""), json.dumps(row, ensure_ascii=False),
                    ),
                )
                connection.execute(
                    "INSERT OR IGNORE INTO feelings_checkin_emotions(checkin_id, emotion_id, position) VALUES (?, ?, 0)",
                    (checkin_id, emotion_id),
                )
                for tag_name in row.get("tags") or []:
                    tag_id = self._ensure_tag(connection, str(tag_name), is_custom=False)
                    connection.execute(
                        "INSERT OR IGNORE INTO feelings_checkin_tags(checkin_id, tag_id) VALUES (?, ?)",
                        (checkin_id, tag_id),
                    )
            legacy = connection.execute(
                """SELECT COUNT(*) AS count, MIN(occurred_at) AS oldest, MAX(occurred_at) AS newest
                   FROM feelings_checkins WHERE source = 'legacy How We Feel import'"""
            ).fetchone()
            if legacy["count"] != SEED_EXPECTED_COUNT or legacy["oldest"] != SEED_EXPECTED_OLDEST or legacy["newest"] != SEED_EXPECTED_NEWEST:
                raise FeelingsError("Imported feelings history failed validation", status=500, code="seed_validation_failed")
            connection.execute(
                "INSERT OR REPLACE INTO feelings_metadata(key, value) VALUES ('feelings_seed_version', ?)",
                (SEED_VERSION,),
            )
        return {"seedStatus": "imported", "legacyCount": SEED_EXPECTED_COUNT}

    def _ensure_emotion(
        self,
        connection: sqlite3.Connection,
        name: str,
        *,
        description: str = "",
        quadrant: str | None = None,
        is_custom: bool = False,
        color: str | None = None,
    ) -> str:
        clean_name = str(name or "").strip()
        if not clean_name:
            raise FeelingsError("Emotion name is required", code="emotion_name_required")
        found = connection.execute("SELECT id FROM feelings_emotions WHERE name = ? COLLATE NOCASE", (clean_name,)).fetchone()
        if found:
            return found["id"]
        clean_quadrant = quadrant or _quadrant_for(clean_name)
        if clean_quadrant not in QUADRANTS:
            raise FeelingsError("Invalid emotion quadrant", code="invalid_quadrant")
        family = QUADRANTS[clean_quadrant]
        count = connection.execute("SELECT COUNT(*) AS count FROM feelings_emotions WHERE quadrant = ?", (clean_quadrant,)).fetchone()["count"]
        emotion_id = _stable_id("emotion", clean_name)
        created = _now()
        shapes = ("circle", "soft-square", "petal", "arch", "notched")
        connection.execute(
            """INSERT INTO feelings_emotions(
                   id, name, description, quadrant, energy, pleasantness, color, x, y, shape,
                   is_custom, created_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                emotion_id, clean_name, str(description or f"feeling {clean_name.casefold()}"), clean_quadrant,
                family["energy"], family["pleasantness"], color or family["color"],
                90 + (count % 5) * 176 + ((count * 29) % 31),
                80 + (count // 5) * 150 + ((count * 17) % 27), shapes[count % len(shapes)],
                1 if is_custom else 0, created, created,
            ),
        )
        return emotion_id

    def _ensure_tag(self, connection: sqlite3.Connection, name: str, *, is_custom: bool) -> str:
        clean_name = str(name or "").strip()
        if not clean_name:
            raise FeelingsError("Tag name is required", code="tag_name_required")
        found = connection.execute("SELECT id FROM feelings_tags WHERE name = ? COLLATE NOCASE", (clean_name,)).fetchone()
        if found:
            return found["id"]
        tag_id = _stable_id("tag", clean_name)
        connection.execute(
            "INSERT INTO feelings_tags(id, name, category, is_custom, created_at) VALUES (?, ?, ?, ?, ?)",
            (tag_id, clean_name, _tag_category(clean_name), 1 if is_custom else 0, _now()),
        )
        return tag_id

    def list_emotions(self) -> dict[str, Any]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM feelings_emotions ORDER BY name COLLATE NOCASE"
            ).fetchall()
        return {"ok": True, "emotions": [self._emotion_dict(row) for row in rows]}

    @staticmethod
    def _emotion_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"], "name": row["name"], "description": row["description"],
            "quadrant": row["quadrant"], "energy": row["energy"],
            "pleasantness": row["pleasantness"], "color": row["color"],
            "x": row["x"], "y": row["y"], "shape": row["shape"],
            "custom": bool(row["is_custom"]), "meter": row["name"] in METER_POSITIONS,
        }

    def create_emotion(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._connect() as connection:
            emotion_id = self._ensure_emotion(
                connection, payload.get("name"), description=str(payload.get("description") or ""),
                quadrant=str(payload.get("quadrant") or ""), is_custom=True,
            )
            row = connection.execute("SELECT * FROM feelings_emotions WHERE id = ?", (emotion_id,)).fetchone()
        return {"ok": True, "emotion": self._emotion_dict(row)}

    def list_tags(self) -> dict[str, Any]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT t.*, COUNT(c.id) AS usage_count
                   FROM feelings_tags t LEFT JOIN feelings_checkin_tags ct ON ct.tag_id = t.id
                   LEFT JOIN feelings_checkins c ON c.id = ct.checkin_id AND c.deleted_at IS NULL
                   GROUP BY t.id ORDER BY usage_count DESC, t.name COLLATE NOCASE"""
            ).fetchall()
        return {"ok": True, "tags": [
            {"id": row["id"], "name": row["name"], "category": row["category"],
             "custom": bool(row["is_custom"]), "usageCount": row["usage_count"]}
            for row in rows
        ]}

    def create_tag(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._connect() as connection:
            tag_id = self._ensure_tag(connection, payload.get("name"), is_custom=True)
            row = connection.execute("SELECT * FROM feelings_tags WHERE id = ?", (tag_id,)).fetchone()
        return {"ok": True, "tag": {"id": row["id"], "name": row["name"], "category": row["category"], "custom": bool(row["is_custom"]), "usageCount": 0}}

    def create_checkin(self, payload: dict[str, Any], *, imported: bool = False) -> dict[str, Any]:
        emotion_values = payload.get("emotionIds") or payload.get("emotions") or ([payload.get("emotionId")] if payload.get("emotionId") else [])
        if not isinstance(emotion_values, list) or not emotion_values:
            raise FeelingsError("Select at least one emotion", code="emotion_required")
        occurred_at = _validate_timestamp(payload.get("occurredAt") or payload.get("occurred_at"))
        timezone_name = str(payload.get("timezone") or "Europe/Warsaw").strip() or "Europe/Warsaw"
        checkin_id = str(payload.get("id") or uuid.uuid4().hex)
        created = _now()
        with self._connect() as connection:
            if connection.execute("SELECT 1 FROM feelings_checkins WHERE id = ?", (checkin_id,)).fetchone():
                if imported:
                    return {"ok": True, "skipped": True, "id": checkin_id}
                raise FeelingsError("A check-in with this id already exists", status=409, code="duplicate_checkin")
            resolved: list[str] = []
            for value in emotion_values:
                raw = value if isinstance(value, str) else value.get("id") or value.get("name")
                row = connection.execute(
                    "SELECT id FROM feelings_emotions WHERE id = ? OR name = ? COLLATE NOCASE", (raw, raw)
                ).fetchone()
                if not row:
                    raise FeelingsError(f"Unknown emotion: {raw}", code="missing_emotion_mapping")
                resolved.append(row["id"])
            connection.execute(
                """INSERT INTO feelings_checkins(
                       id, occurred_at, timezone, note, source, source_device, created_at, updated_at,
                       sync_id, schema_version
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    checkin_id, occurred_at, timezone_name, str(payload.get("note") or ""),
                    str(payload.get("source") or "dashboard"), str(payload.get("sourceDevice") or "desktop-dashboard"),
                    str(payload.get("createdAt") or created), created, str(payload.get("syncId") or checkin_id),
                    int(payload.get("schemaVersion") or SCHEMA_VERSION),
                ),
            )
            for position, emotion_id in enumerate(resolved):
                connection.execute(
                    "INSERT INTO feelings_checkin_emotions(checkin_id, emotion_id, position) VALUES (?, ?, ?)",
                    (checkin_id, emotion_id, position),
                )
            for value in payload.get("tags") or payload.get("tagNames") or []:
                raw = value if isinstance(value, str) else value.get("name") or value.get("id")
                tag_row = connection.execute(
                    "SELECT id FROM feelings_tags WHERE id = ? OR name = ? COLLATE NOCASE", (raw, raw)
                ).fetchone()
                tag_id = tag_row["id"] if tag_row else self._ensure_tag(connection, raw, is_custom=True)
                connection.execute("INSERT OR IGNORE INTO feelings_checkin_tags(checkin_id, tag_id) VALUES (?, ?)", (checkin_id, tag_id))
        return {"ok": True, "checkin": self.get_checkin(checkin_id)}

    def _base_rows(self, where: str = "", params: tuple[Any, ...] = (), *, limit: int = 1000, offset: int = 0) -> list[sqlite3.Row]:
        clause = f" AND {where}" if where else ""
        with self._connect() as connection:
            return connection.execute(
                f"""SELECT c.*, e.id AS emotion_id, e.name AS emotion_name, e.description AS emotion_description,
                            e.quadrant, e.energy, e.pleasantness, e.color, e.shape
                     FROM feelings_checkins c
                     JOIN feelings_checkin_emotions ce ON ce.checkin_id = c.id AND ce.position = 0
                     JOIN feelings_emotions e ON e.id = ce.emotion_id
                     WHERE c.deleted_at IS NULL {clause}
                     ORDER BY c.occurred_at DESC, c.id DESC LIMIT ? OFFSET ?""",
                (*params, max(1, min(int(limit), 5000)), max(0, int(offset))),
            ).fetchall()

    def _hydrate(self, rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
        if not rows:
            return []
        ids = [row["id"] for row in rows]
        placeholders = ",".join("?" for _ in ids)
        with self._connect() as connection:
            emotion_rows = connection.execute(
                f"""SELECT ce.checkin_id, e.* FROM feelings_checkin_emotions ce
                     JOIN feelings_emotions e ON e.id = ce.emotion_id
                     WHERE ce.checkin_id IN ({placeholders}) ORDER BY ce.position""", ids,
            ).fetchall()
            tag_rows = connection.execute(
                f"""SELECT ct.checkin_id, t.* FROM feelings_checkin_tags ct
                     JOIN feelings_tags t ON t.id = ct.tag_id
                     WHERE ct.checkin_id IN ({placeholders}) ORDER BY t.name COLLATE NOCASE""", ids,
            ).fetchall()
        emotions: dict[str, list[dict[str, Any]]] = defaultdict(list)
        tags: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in emotion_rows:
            emotions[row["checkin_id"]].append(self._emotion_dict(row))
        for row in tag_rows:
            tags[row["checkin_id"]].append({"id": row["id"], "name": row["name"], "category": row["category"]})
        return [{
            "id": row["id"], "occurredAt": row["occurred_at"], "timezone": row["timezone"],
            "note": row["note"], "source": row["source"], "sourceDevice": row["source_device"],
            "createdAt": row["created_at"], "updatedAt": row["updated_at"], "syncId": row["sync_id"],
            "schemaVersion": row["schema_version"], "emotions": emotions[row["id"]],
            "emotion": emotions[row["id"]][0] if emotions[row["id"]] else None,
            "tags": tags[row["id"]],
        } for row in rows]

    def get_checkin(self, checkin_id: str) -> dict[str, Any]:
        rows = self._base_rows("c.id = ?", (checkin_id,), limit=1)
        if not rows:
            raise FeelingsError("Check-in not found", status=404, code="not_found")
        return self._hydrate(rows)[0]

    def list_checkins(self, query: dict[str, list[str]]) -> dict[str, Any]:
        where: list[str] = []
        params: list[Any] = []
        mapping = (("from", "c.occurred_at >= ?"), ("to", "c.occurred_at <= ?"))
        for key, clause in mapping:
            value = (query.get(key) or [""])[0]
            if value:
                where.append(clause)
                params.append(value + ("T23:59:59" if key == "to" and "T" not in value else ""))
        quadrant = (query.get("quadrant") or [""])[0]
        if quadrant:
            where.append("e.quadrant = ?")
            params.append(quadrant)
        emotion = (query.get("emotion") or [""])[0]
        if emotion:
            where.append("(e.id = ? OR e.name = ? COLLATE NOCASE)")
            params.extend((emotion, emotion))
        tag = (query.get("tag") or [""])[0]
        if tag:
            where.append("EXISTS (SELECT 1 FROM feelings_checkin_tags fct JOIN feelings_tags ft ON ft.id=fct.tag_id WHERE fct.checkin_id=c.id AND (ft.id=? OR ft.name=? COLLATE NOCASE))")
            params.extend((tag, tag))
        search = (query.get("q") or [""])[0].strip()
        if search:
            where.append("(c.note LIKE ? OR e.name LIKE ? OR EXISTS (SELECT 1 FROM feelings_checkin_tags sct JOIN feelings_tags st ON st.id=sct.tag_id WHERE sct.checkin_id=c.id AND st.name LIKE ?))")
            pattern = f"%{search}%"
            params.extend((pattern, pattern, pattern))
        limit = int((query.get("limit") or [1000])[0])
        offset = int((query.get("offset") or [0])[0])
        rows = self._base_rows(" AND ".join(where), tuple(params), limit=limit, offset=offset)
        return {"ok": True, "checkins": self._hydrate(rows), "count": len(rows)}

    def update_checkin(self, checkin_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.get_checkin(checkin_id)
        with self._connect() as connection:
            occurred = _validate_timestamp(payload.get("occurredAt", current["occurredAt"]))
            connection.execute(
                "UPDATE feelings_checkins SET occurred_at=?, timezone=?, note=?, updated_at=? WHERE id=? AND deleted_at IS NULL",
                (occurred, str(payload.get("timezone", current["timezone"])), str(payload.get("note", current["note"])), _now(), checkin_id),
            )
            if "emotionIds" in payload or "emotionId" in payload:
                values = payload.get("emotionIds") or [payload.get("emotionId")]
                connection.execute("DELETE FROM feelings_checkin_emotions WHERE checkin_id = ?", (checkin_id,))
                for position, value in enumerate(values):
                    row = connection.execute("SELECT id FROM feelings_emotions WHERE id=? OR name=? COLLATE NOCASE", (value, value)).fetchone()
                    if not row:
                        raise FeelingsError(f"Unknown emotion: {value}", code="missing_emotion_mapping")
                    connection.execute("INSERT INTO feelings_checkin_emotions VALUES (?, ?, ?)", (checkin_id, row["id"], position))
            if "tags" in payload or "tagNames" in payload:
                connection.execute("DELETE FROM feelings_checkin_tags WHERE checkin_id = ?", (checkin_id,))
                for value in payload.get("tags") or payload.get("tagNames") or []:
                    raw = value if isinstance(value, str) else value.get("name") or value.get("id")
                    row = connection.execute("SELECT id FROM feelings_tags WHERE id=? OR name=? COLLATE NOCASE", (raw, raw)).fetchone()
                    tag_id = row["id"] if row else self._ensure_tag(connection, raw, is_custom=True)
                    connection.execute("INSERT INTO feelings_checkin_tags VALUES (?, ?)", (checkin_id, tag_id))
        return {"ok": True, "checkin": self.get_checkin(checkin_id)}

    def delete_checkin(self, checkin_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            result = connection.execute(
                "UPDATE feelings_checkins SET deleted_at=?, updated_at=? WHERE id=? AND deleted_at IS NULL",
                (_now(), _now(), checkin_id),
            )
        if not result.rowcount:
            raise FeelingsError("Check-in not found", status=404, code="not_found")
        return {"ok": True, "deleted": checkin_id}

    def insights(self, days: int | None = None) -> dict[str, Any]:
        query: dict[str, list[str]] = {"limit": ["5000"]}
        if days and days > 0:
            query["from"] = [(datetime.now() - timedelta(days=days - 1)).date().isoformat()]
        checkins = self.list_checkins(query)["checkins"]
        total = len(checkins)
        quadrants = Counter(item["emotion"]["quadrant"] for item in checkins)
        emotion_counts = Counter(item["emotion"]["name"] for item in checkins)
        by_day = Counter(item["occurredAt"][:10] for item in checkins)
        by_week = Counter()
        by_month = Counter()
        time_of_day = Counter()
        weekdays = Counter()
        tag_items: dict[str, list[dict[str, Any]]] = defaultdict(list)
        emotion_items: dict[str, list[dict[str, Any]]] = defaultdict(list)
        daily_values: dict[str, list[tuple[float, float]]] = defaultdict(list)
        for item in checkins:
            parsed = datetime.fromisoformat(item["occurredAt"].replace("Z", "+00:00"))
            iso_year, iso_week, _ = parsed.isocalendar()
            by_week[f"{iso_year}-W{iso_week:02d}"] += 1
            by_month[item["occurredAt"][:7]] += 1
            hour = parsed.hour
            bucket = "morning" if 5 <= hour < 12 else "afternoon" if 12 <= hour < 17 else "evening" if 17 <= hour < 22 else "night"
            time_of_day[bucket] += 1
            weekdays[parsed.strftime("%a")] += 1
            emotion_items[item["emotion"]["name"]].append(item)
            daily_values[item["occurredAt"][:10]].append((item["emotion"]["energy"], item["emotion"]["pleasantness"]))
            for tag in item["tags"]:
                tag_items[tag["name"]].append(item)
        tag_associations = []
        for name, items in sorted(tag_items.items(), key=lambda pair: (-len(pair[1]), pair[0].casefold())):
            tag_associations.append({
                "tag": name, "count": len(items),
                "emotions": Counter(item["emotion"]["name"] for item in items).most_common(8),
                "quadrants": dict(Counter(item["emotion"]["quadrant"] for item in items)),
            })
        emotion_associations = []
        for name, items in sorted(emotion_items.items(), key=lambda pair: (-len(pair[1]), pair[0].casefold())):
            tags = Counter(tag["name"] for item in items for tag in item["tags"])
            buckets = Counter()
            for item in items:
                hour = datetime.fromisoformat(item["occurredAt"].replace("Z", "+00:00")).hour
                buckets["morning" if 5 <= hour < 12 else "afternoon" if 12 <= hour < 17 else "evening" if 17 <= hour < 22 else "night"] += 1
            emotion_associations.append({"emotion": name, "count": len(items), "tags": tags.most_common(8), "timeOfDay": dict(buckets), "recent": [item["occurredAt"] for item in items[:5]]})
        trend = [{
            "date": day, "count": len(values),
            "energy": round(sum(v[0] for v in values) / len(values), 3),
            "pleasantness": round(sum(v[1] for v in values) / len(values), 3),
        } for day, values in sorted(daily_values.items())]
        return {
            "ok": True, "total": total,
            "quadrants": [{"quadrant": key, "count": quadrants[key], "percentage": round(quadrants[key] * 100 / total, 1) if total else 0} for key in QUADRANTS],
            "emotions": [{"emotion": name, "count": count} for name, count in emotion_counts.most_common()],
            "frequency": {
                "byDay": [{"date": day, "count": count} for day, count in sorted(by_day.items())],
                "byWeek": [{"week": week, "count": count} for week, count in sorted(by_week.items())],
                "byMonth": [{"month": month, "count": count} for month, count in sorted(by_month.items())],
            },
            "timeOfDay": dict(time_of_day), "dayOfWeek": {day: weekdays[day] for day in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")},
            "heatmap": [{"date": day, "count": count} for day, count in sorted(by_day.items())],
            "trend": trend, "tagAssociations": tag_associations, "emotionAssociations": emotion_associations,
            "todayCount": by_day[datetime.now().date().isoformat()],
        }

    def export_data(self) -> dict[str, Any]:
        return {
            "format": "feelings-export", "version": 1, "exportedAt": _now(),
            "emotions": self.list_emotions()["emotions"], "tags": self.list_tags()["tags"],
            "checkins": self.list_checkins({"limit": ["5000"]})["checkins"],
        }

    def export_csv(self) -> str:
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer)
        writer.writerow(("timestamp", "emotions", "quadrant", "tags", "note", "source"))
        for item in reversed(self.list_checkins({"limit": ["5000"]})["checkins"]):
            writer.writerow((item["occurredAt"], "; ".join(e["name"] for e in item["emotions"]), item["emotion"]["quadrant"], "; ".join(t["name"] for t in item["tags"]), item["note"], item["source"]))
        return buffer.getvalue()

    def import_export(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("format") != "feelings-export" or not isinstance(payload.get("checkins"), list):
            raise FeelingsError("Unsupported feelings import format", code="invalid_import")
        with self._connect() as connection:
            for emotion in payload.get("emotions") or []:
                self._ensure_emotion(
                    connection,
                    emotion.get("name"),
                    description=str(emotion.get("description") or ""),
                    quadrant=str(emotion.get("quadrant") or ""),
                    is_custom=bool(emotion.get("custom")),
                    color=str(emotion.get("color") or "") or None,
                )
        imported = skipped = 0
        for item in payload["checkins"]:
            normalized = {
                **item,
                "emotionIds": [e.get("id") or e.get("name") for e in item.get("emotions") or []],
                "tags": [t.get("name") or t.get("id") for t in item.get("tags") or []],
            }
            result = self.create_checkin(normalized, imported=True)
            if result.get("skipped"):
                skipped += 1
            else:
                imported += 1
        return {"ok": True, "imported": imported, "skipped": skipped}


def default_feelings_service(project_root: str | Path) -> FeelingsService:
    root = Path(project_root)
    return FeelingsService(
        root / "data" / "feelings.sqlite",
        seed_paths=(root / "data" / "feelings" / "how_we_feel_seed.json", root.parent / "how_we_feel_seed.json"),
    )
