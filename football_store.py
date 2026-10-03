"""Small local history of the normalized football snapshot, independent of Kitchen JSON."""

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


class FootballStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS entity_cache (
                    cache_key TEXT PRIMARY KEY, payload TEXT NOT NULL, fetched_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS entities (
                    kind TEXT NOT NULL, key TEXT NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY(kind,key)
                );
                CREATE TABLE IF NOT EXISTS clubs (
                    key TEXT PRIMARY KEY, name TEXT NOT NULL, crest TEXT NOT NULL DEFAULT '',
                    crest_source TEXT NOT NULL DEFAULT '', first_seen TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS competitions (
                    key TEXT PRIMARY KEY, name TEXT NOT NULL, country TEXT NOT NULL DEFAULT '',
                    first_seen TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS matches (
                    source_key TEXT PRIMARY KEY, provider TEXT NOT NULL, external_id TEXT NOT NULL,
                    competition_key TEXT NOT NULL DEFAULT '', home_key TEXT NOT NULL DEFAULT '',
                    away_key TEXT NOT NULL DEFAULT '', match_time TEXT NOT NULL DEFAULT '',
                    category TEXT NOT NULL, payload TEXT NOT NULL,
                    first_seen TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_football_matches_time ON matches(match_time);
                CREATE INDEX IF NOT EXISTS idx_football_matches_clubs ON matches(home_key, away_key);
                CREATE TABLE IF NOT EXISTS provider_mappings (
                    entity_type TEXT NOT NULL, provider TEXT NOT NULL, external_id TEXT NOT NULL,
                    entity_key TEXT NOT NULL, observed_name TEXT NOT NULL DEFAULT '',
                    first_seen TEXT NOT NULL, updated_at TEXT NOT NULL,
                    PRIMARY KEY (entity_type, provider, external_id)
                );
                CREATE TABLE IF NOT EXISTS mapping_conflicts (
                    entity_type TEXT NOT NULL, provider TEXT NOT NULL, external_id TEXT NOT NULL,
                    existing_key TEXT NOT NULL, proposed_key TEXT NOT NULL,
                    first_seen TEXT NOT NULL, updated_at TEXT NOT NULL,
                    PRIMARY KEY (entity_type, provider, external_id, proposed_key)
                );
                PRAGMA user_version = 2;
            """)

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def ingest(self, snapshot):
        """Idempotently retain results/fixtures seen in a new Kitchen cache snapshot."""
        rows = [row for row in snapshot.get("matches") or [] if row.get("category") in {"result", "upcoming"}]
        fingerprint = hashlib.sha256(json.dumps({"matches": rows, "clubs": snapshot.get("clubs") or [],
                                                  "competitions": snapshot.get("competitions") or []},
                                                 sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._connect() as connection:
            previous = connection.execute("SELECT value FROM metadata WHERE key='snapshot_hash'").fetchone()
            if previous and previous[0] == fingerprint:
                return False
            for club in snapshot.get("clubs") or []:
                connection.execute("""INSERT INTO clubs(key,name,crest,crest_source,first_seen,updated_at)
                    VALUES(?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET
                    name=excluded.name, crest=CASE WHEN excluded.crest!='' THEN excluded.crest ELSE clubs.crest END,
                    crest_source=CASE WHEN excluded.crest!='' THEN excluded.crest_source ELSE clubs.crest_source END,
                    updated_at=excluded.updated_at""",
                    (club["key"], club.get("name") or club["key"], club.get("crest") or "",
                     club.get("crestSource") or "", now, now))
                for field, external_id in (club.get("providerIds") or {}).items():
                    provider = "TheSportsDB" if field == "thesportsdb_team_id" else field
                    self._mapping(connection, "club", provider, external_id, club["key"], club.get("name") or "", now)
            for competition in snapshot.get("competitions") or []:
                connection.execute("""INSERT INTO competitions(key,name,country,first_seen,updated_at)
                    VALUES(?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET
                    name=excluded.name, country=excluded.country, updated_at=excluded.updated_at""",
                    (competition["key"], competition.get("name") or competition["key"], competition.get("country") or "", now, now))
                for field, external_id in (competition.get("providerIds") or {}).items():
                    provider = {"api_football_id": "API-Football", "espn_league": "ESPN", "thesportsdb_id": "TheSportsDB"}.get(field, field)
                    self._mapping(connection, "competition", provider, external_id, competition["key"], competition.get("name") or "", now)
            for row in rows:
                external_id = str(row.get("id") or "")
                provider = str(row.get("provider") or "unknown")
                if not external_id:
                    continue
                source_key = f"{provider}:{external_id}"
                keys = row.get("clubKeys") or []
                match_time = str(row.get("kickoffAt") or row.get("playedAt") or "")
                connection.execute("""INSERT INTO matches(source_key,provider,external_id,competition_key,home_key,away_key,match_time,category,payload,first_seen,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(source_key) DO UPDATE SET
                    competition_key=excluded.competition_key, home_key=excluded.home_key,
                    away_key=excluded.away_key, match_time=excluded.match_time,
                    category=excluded.category, payload=excluded.payload, updated_at=excluded.updated_at""",
                    (source_key, provider, external_id, row.get("competitionKey") or "",
                     keys[0] if len(keys) > 0 else "", keys[1] if len(keys) > 1 else "",
                     match_time, row["category"], json.dumps(row, ensure_ascii=False), now, now))
                self._mapping(connection, "match", provider, external_id, source_key, "", now)
            connection.execute("INSERT INTO metadata(key,value) VALUES('snapshot_hash',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (fingerprint,))
        return True

    @staticmethod
    def _mapping(connection, entity_type, provider, external_id, entity_key, name, now):
        existing = connection.execute("SELECT entity_key FROM provider_mappings WHERE entity_type=? AND provider=? AND external_id=?",
                                      (entity_type, provider, str(external_id))).fetchone()
        if existing and existing[0] != entity_key:
            connection.execute("""INSERT INTO mapping_conflicts(entity_type,provider,external_id,existing_key,proposed_key,first_seen,updated_at)
                VALUES(?,?,?,?,?,?,?) ON CONFLICT(entity_type,provider,external_id,proposed_key) DO UPDATE SET updated_at=excluded.updated_at""",
                (entity_type, provider, str(external_id), existing[0], entity_key, now, now))
            return
        connection.execute("""INSERT INTO provider_mappings(entity_type,provider,external_id,entity_key,observed_name,first_seen,updated_at)
            VALUES(?,?,?,?,?,?,?) ON CONFLICT(entity_type,provider,external_id) DO UPDATE SET
            entity_key=excluded.entity_key, observed_name=excluded.observed_name, updated_at=excluded.updated_at""",
            (entity_type, provider, str(external_id), entity_key, name, now, now))

    def matches(self, limit=3000):
        with self._connect() as connection:
            rows = connection.execute("SELECT payload, first_seen, updated_at FROM matches ORDER BY match_time DESC LIMIT ?", (min(max(int(limit), 1), 10000),)).fetchall()
        return [{**json.loads(row["payload"]), "firstSeenAt": row["first_seen"], "lastStoredAt": row["updated_at"]} for row in rows]

    def cached(self, key):
        with self._connect() as connection:
            row = connection.execute("SELECT payload,fetched_at FROM entity_cache WHERE cache_key=?", (key,)).fetchone()
        return {"data": json.loads(row[0]), "fetchedAt": row[1]} if row else None

    def cache(self, key, payload, fetched_at):
        with self._connect() as connection:
            connection.execute("INSERT INTO entity_cache VALUES(?,?,?) ON CONFLICT(cache_key) DO UPDATE SET payload=excluded.payload,fetched_at=excluded.fetched_at",
                               (key, json.dumps(payload, ensure_ascii=False), fetched_at))

    def put_entity(self, kind, entity):
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._connect() as connection:
            connection.execute("INSERT INTO entities VALUES(?,?,?) ON CONFLICT(kind,key) DO UPDATE SET payload=excluded.payload",
                               (kind, entity["key"], json.dumps(entity, ensure_ascii=False)))
            for provider, provider_id in (entity.get("providerIds") or {}).items():
                self._mapping(connection, kind, provider, provider_id, entity["key"], entity.get("name") or "", now)

    def entity(self, kind, key):
        with self._connect() as connection:
            row = connection.execute("SELECT payload FROM entities WHERE kind=? AND key=?", (kind, key)).fetchone()
        return json.loads(row[0]) if row else None

    def entities(self, kind):
        with self._connect() as connection:
            rows = connection.execute("SELECT payload FROM entities WHERE kind=? ORDER BY key", (kind,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def counts(self):
        with self._connect() as connection:
            return {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    for table in ("clubs", "competitions", "matches", "provider_mappings", "mapping_conflicts")}

    def mappings(self, limit=300):
        with self._connect() as connection:
            rows = connection.execute("SELECT entity_type,provider,external_id,entity_key,observed_name,updated_at FROM provider_mappings ORDER BY updated_at DESC LIMIT ?", (min(max(int(limit), 1), 1000),)).fetchall()
        return [dict(row) for row in rows]

    def mapping_conflicts(self, limit=100):
        with self._connect() as connection:
            rows = connection.execute("SELECT entity_type,provider,external_id,existing_key,proposed_key,updated_at FROM mapping_conflicts ORDER BY updated_at DESC LIMIT ?", (min(max(int(limit), 1), 1000),)).fetchall()
        return [dict(row) for row in rows]
