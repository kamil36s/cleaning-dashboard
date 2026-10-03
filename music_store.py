"""Canonical relational store for the dashboard Music application."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import threading
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

from music_importers import PARSER_VERSION, normalize_text, parse_rym_html, slug_from_genre_url
from music_legacy_adapters import find_legacy_matches, legacy_catalog_rows, project_summaries


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class MusicError(RuntimeError):
    def __init__(self, message, *, status=400, code="music_error"):
        super().__init__(message)
        self.status = status
        self.code = code

    def as_payload(self):
        return {"ok": False, "error": str(self), "code": self.code}


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


SCHEMA = r"""
CREATE TABLE IF NOT EXISTS music_schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS music_artists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS music_releases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    normalized_title TEXT NOT NULL,
    artist_credit TEXT NOT NULL,
    normalized_artist_credit TEXT NOT NULL,
    release_type TEXT NOT NULL DEFAULT 'Album',
    release_date TEXT,
    release_year INTEGER,
    cover_local TEXT,
    cover_remote TEXT,
    recorded_text TEXT,
    label TEXT,
    catalog_number TEXT,
    issues_text TEXT,
    description TEXT,
    duration_seconds INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_music_releases_identity
    ON music_releases(normalized_artist_credit, normalized_title, release_year, release_type);
CREATE INDEX IF NOT EXISTS idx_music_releases_year ON music_releases(release_year);
CREATE INDEX IF NOT EXISTS idx_music_releases_title ON music_releases(normalized_title);
CREATE TABLE IF NOT EXISTS music_release_artists (
    release_id INTEGER NOT NULL REFERENCES music_releases(id) ON DELETE CASCADE,
    artist_id INTEGER NOT NULL REFERENCES music_artists(id) ON DELETE CASCADE,
    credit_order INTEGER NOT NULL DEFAULT 0,
    credit_role TEXT NOT NULL DEFAULT 'PRIMARY',
    display_credit TEXT,
    PRIMARY KEY (release_id, artist_id, credit_order)
);
CREATE TABLE IF NOT EXISTS music_tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    release_id INTEGER NOT NULL REFERENCES music_releases(id) ON DELETE CASCADE,
    position TEXT NOT NULL,
    disc_number INTEGER,
    title TEXT NOT NULL,
    normalized_title TEXT NOT NULL,
    duration_seconds INTEGER,
    source TEXT NOT NULL,
    UNIQUE (release_id, position, normalized_title)
);
CREATE INDEX IF NOT EXISTS idx_music_tracks_release ON music_tracks(release_id);
CREATE TABLE IF NOT EXISTS music_genres (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    slug TEXT,
    source TEXT NOT NULL DEFAULT 'RYM',
    source_url TEXT,
    description TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (source, normalized_name)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_music_genres_source_slug
    ON music_genres(source, slug) WHERE slug IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_music_genres_name ON music_genres(normalized_name);
CREATE TABLE IF NOT EXISTS music_genre_relations (
    parent_genre_id INTEGER NOT NULL REFERENCES music_genres(id) ON DELETE CASCADE,
    child_genre_id INTEGER NOT NULL REFERENCES music_genres(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    relation_type TEXT NOT NULL DEFAULT 'SUBGENRE',
    PRIMARY KEY (parent_genre_id, child_genre_id, source, relation_type),
    CHECK (parent_genre_id <> child_genre_id)
);
CREATE INDEX IF NOT EXISTS idx_music_genre_rel_parent ON music_genre_relations(parent_genre_id);
CREATE INDEX IF NOT EXISTS idx_music_genre_rel_child ON music_genre_relations(child_genre_id);
CREATE TABLE IF NOT EXISTS music_release_genres (
    release_id INTEGER NOT NULL REFERENCES music_releases(id) ON DELETE CASCADE,
    genre_id INTEGER NOT NULL REFERENCES music_genres(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    source TEXT NOT NULL,
    source_record_id INTEGER,
    PRIMARY KEY (release_id, genre_id, role, source)
);
CREATE INDEX IF NOT EXISTS idx_music_release_genres_genre ON music_release_genres(genre_id, release_id);
CREATE TABLE IF NOT EXISTS music_descriptors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS music_release_descriptors (
    release_id INTEGER NOT NULL REFERENCES music_releases(id) ON DELETE CASCADE,
    descriptor_id INTEGER NOT NULL REFERENCES music_descriptors(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    source_record_id INTEGER,
    PRIMARY KEY (release_id, descriptor_id, source)
);
CREATE TABLE IF NOT EXISTS music_external_ids (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    source TEXT NOT NULL,
    external_type TEXT NOT NULL,
    external_value TEXT NOT NULL,
    external_url TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (source, external_type, external_value)
);
CREATE INDEX IF NOT EXISTS idx_music_external_entity ON music_external_ids(entity_type, entity_id);
CREATE TABLE IF NOT EXISTS music_import_batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    page_type TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    file_hash_sha256 TEXT NOT NULL UNIQUE,
    source_url TEXT,
    parser_version TEXT NOT NULL,
    captured_at TEXT,
    imported_at TEXT NOT NULL,
    committed_at TEXT,
    status TEXT NOT NULL,
    raw_file_path TEXT,
    title TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    parsed_count INTEGER NOT NULL DEFAULT 0,
    new_count INTEGER NOT NULL DEFAULT 0,
    matched_count INTEGER NOT NULL DEFAULT 0,
    ambiguous_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS music_import_rows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL REFERENCES music_import_batches(id) ON DELETE CASCADE,
    row_index INTEGER NOT NULL,
    source_position INTEGER,
    parsed_json TEXT NOT NULL,
    match_status TEXT NOT NULL,
    matched_release_id INTEGER REFERENCES music_releases(id),
    candidates_json TEXT NOT NULL DEFAULT '[]',
    error_text TEXT,
    resolution_json TEXT,
    UNIQUE (batch_id, row_index)
);
CREATE INDEX IF NOT EXISTS idx_music_import_rows_batch ON music_import_rows(batch_id, row_index);
CREATE TABLE IF NOT EXISTS music_source_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL REFERENCES music_import_batches(id) ON DELETE CASCADE,
    import_row_id INTEGER REFERENCES music_import_rows(id),
    entity_type TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    source_url TEXT,
    observed_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    UNIQUE (batch_id, import_row_id, entity_type, entity_id)
);
CREATE TABLE IF NOT EXISTS music_rankings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    source TEXT NOT NULL,
    source_key TEXT NOT NULL,
    genre_id INTEGER REFERENCES music_genres(id),
    include_descendants INTEGER NOT NULL DEFAULT 0,
    filters_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (source, source_key)
);
CREATE TABLE IF NOT EXISTS music_ranking_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ranking_id INTEGER NOT NULL REFERENCES music_rankings(id) ON DELETE CASCADE,
    import_batch_id INTEGER REFERENCES music_import_batches(id),
    captured_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    is_current INTEGER NOT NULL DEFAULT 0,
    UNIQUE (import_batch_id)
);
CREATE INDEX IF NOT EXISTS idx_music_ranking_snapshots_rank ON music_ranking_snapshots(ranking_id, captured_at DESC);
CREATE TABLE IF NOT EXISTS music_ranking_entries (
    snapshot_id INTEGER NOT NULL REFERENCES music_ranking_snapshots(id) ON DELETE CASCADE,
    release_id INTEGER NOT NULL REFERENCES music_releases(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    source_position INTEGER,
    created_at TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, release_id),
    UNIQUE (snapshot_id, position)
);
CREATE INDEX IF NOT EXISTS idx_music_ranking_entries_release ON music_ranking_entries(release_id);
CREATE TABLE IF NOT EXISTS music_user_ratings (
    release_id INTEGER PRIMARY KEY REFERENCES music_releases(id) ON DELETE CASCADE,
    rating REAL NOT NULL CHECK (rating >= 0.5 AND rating <= 5.0),
    rated_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS music_lists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS music_list_entries (
    list_id INTEGER NOT NULL REFERENCES music_lists(id) ON DELETE CASCADE,
    release_id INTEGER NOT NULL REFERENCES music_releases(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    note TEXT,
    added_at TEXT NOT NULL,
    PRIMARY KEY (list_id, release_id),
    UNIQUE (list_id, position)
);
CREATE TABLE IF NOT EXISTS music_release_metric_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    release_id INTEGER NOT NULL REFERENCES music_releases(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    rating REAL,
    rating_display TEXT,
    rating_count INTEGER,
    rating_count_display TEXT,
    review_count INTEGER,
    review_count_display TEXT,
    ranking_text TEXT,
    import_batch_id INTEGER REFERENCES music_import_batches(id),
    UNIQUE (release_id, source, import_batch_id)
);
CREATE INDEX IF NOT EXISTS idx_music_metrics_release ON music_release_metric_snapshots(release_id, captured_at DESC);
CREATE TABLE IF NOT EXISTS music_release_credits (
    release_id INTEGER NOT NULL REFERENCES music_releases(id) ON DELETE CASCADE,
    person_name TEXT NOT NULL,
    normalized_person_name TEXT NOT NULL,
    role TEXT NOT NULL,
    source TEXT NOT NULL,
    PRIMARY KEY (release_id, normalized_person_name, role, source)
);
CREATE TABLE IF NOT EXISTS music_legacy_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    legacy_module TEXT NOT NULL,
    legacy_entity_type TEXT NOT NULL,
    legacy_entity_id TEXT NOT NULL,
    music_release_id INTEGER NOT NULL REFERENCES music_releases(id) ON DELETE CASCADE,
    match_method TEXT NOT NULL,
    confidence REAL,
    created_at TEXT NOT NULL,
    UNIQUE (legacy_module, legacy_entity_type, legacy_entity_id)
);
CREATE INDEX IF NOT EXISTS idx_music_legacy_release ON music_legacy_links(music_release_id);
CREATE TABLE IF NOT EXISTS music_legacy_release_state (
    legacy_link_id INTEGER PRIMARY KEY REFERENCES music_legacy_links(id) ON DELETE CASCADE,
    planned_date TEXT,
    listened INTEGER NOT NULL DEFAULT 0,
    rating REAL,
    minutes INTEGER,
    description TEXT,
    rym_rating REAL,
    rym_rating_ignored INTEGER NOT NULL DEFAULT 0,
    community_rating REAL,
    community_votes INTEGER,
    community_source TEXT,
    community_url TEXT,
    community_checked_at TEXT,
    source_rank INTEGER,
    source_updated_at TEXT,
    observed_at TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_music_legacy_state_listened ON music_legacy_release_state(listened);
CREATE TABLE IF NOT EXISTS music_lastfm_scrobbles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lastfm_scrobble_id INTEGER NOT NULL UNIQUE,
    release_id INTEGER REFERENCES music_releases(id),
    track_id INTEGER REFERENCES music_tracks(id),
    matched_at TEXT,
    match_method TEXT
);
CREATE TABLE IF NOT EXISTS music_lastfm_sync_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS music_metadata_values (
    entity_type TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    field_name TEXT NOT NULL,
    provider TEXT NOT NULL,
    provider_entity_id TEXT,
    value_json TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 1,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (entity_type, entity_id, field_name, provider)
);
CREATE TABLE IF NOT EXISTS music_metadata_checks (
    entity_type TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    field_name TEXT NOT NULL,
    provider TEXT NOT NULL,
    status TEXT NOT NULL,
    checked_at TEXT NOT NULL,
    error_text TEXT,
    PRIMARY KEY (entity_type, entity_id, field_name, provider)
);
CREATE TABLE IF NOT EXISTS music_provider_payloads (
    entity_type TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    provider TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (entity_type, entity_id, action, provider)
);
CREATE TABLE IF NOT EXISTS music_enrichment_jobs (
    release_id INTEGER PRIMARY KEY REFERENCES music_releases(id) ON DELETE CASCADE,
    priority INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    match_method TEXT,
    match_confidence REAL,
    error_text TEXT,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_music_enrichment_jobs_status ON music_enrichment_jobs(status, priority, updated_at);
CREATE TABLE IF NOT EXISTS music_artwork_cache (
    sha256 TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    source_url TEXT NOT NULL,
    local_path TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    width INTEGER,
    height INTEGER,
    artwork_type TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_music_artwork_source ON music_artwork_cache(source_url);
"""


class MusicStore:
    def __init__(self, root=None):
        self.root = Path(root or Path(__file__).resolve().parent)
        self.path = self.root / "data" / "music.sqlite"
        self.import_dir = self.root / "data" / "music-imports"
        self._lock = threading.RLock()

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30, factory=ClosingConnection)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection

    def initialize(self):
        with self._connect() as connection:
            connection.executescript(SCHEMA)
            release_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(music_releases)")
            }
            if "description" not in release_columns:
                connection.execute("ALTER TABLE music_releases ADD COLUMN description TEXT")
            if "duration_seconds" not in release_columns:
                connection.execute("ALTER TABLE music_releases ADD COLUMN duration_seconds INTEGER")
            connection.execute(
                "INSERT OR IGNORE INTO music_schema_migrations(version, applied_at) VALUES(1, ?)",
                (utc_now(),),
            )
            connection.execute(
                "INSERT OR IGNORE INTO music_schema_migrations(version, applied_at) VALUES(2, ?)",
                (utc_now(),),
            )
            connection.execute(
                "INSERT OR IGNORE INTO music_schema_migrations(version, applied_at) VALUES(3, ?)",
                (utc_now(),),
            )
            if not connection.execute("SELECT 1 FROM music_schema_migrations WHERE version=4").fetchone():
                # Provider tags were accidentally promoted into the user's RYM genre tree.
                connection.execute("DELETE FROM music_genres WHERE source IN ('MusicBrainz','Discogs') "
                                   "AND id NOT IN (SELECT genre_id FROM music_rankings WHERE genre_id IS NOT NULL)")
                connection.execute("INSERT INTO music_schema_migrations(version, applied_at) VALUES(4, ?)", (utc_now(),))

    @staticmethod
    def _json(value):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _year_predicate(filters, column="r.release_year"):
        mode = str(filters.get("yearMode") or "").strip().lower()
        if not mode:
            mode = ("year" if filters.get("year") else "decade" if filters.get("decade")
                    else "range" if filters.get("yearFrom") or filters.get("yearTo") else "all")
        if mode == "all":
            return None, []
        def checked(value):
            try:
                year = int(value)
            except (TypeError, ValueError):
                raise MusicError("Podaj poprawny rok wydania", code="invalid_release_year")
            if not 1000 <= year <= 2100:
                raise MusicError("Rok wydania musi być w zakresie 1000–2100", code="invalid_release_year")
            return year
        if mode == "year":
            return f"{column}=?", [checked(filters.get("year"))]
        if mode == "decade":
            decade = checked(filters.get("decade"))
            if decade % 10:
                raise MusicError("Początek dekady musi kończyć się zerem", code="invalid_release_year")
            return f"{column} BETWEEN ? AND ?", [decade, decade + 9]
        if mode == "range":
            first, last = checked(filters.get("yearFrom")), checked(filters.get("yearTo"))
            if first > last:
                raise MusicError("Początek zakresu jest późniejszy niż koniec", code="invalid_release_year")
            return f"{column} BETWEEN ? AND ?", [first, last]
        raise MusicError("Nieznany tryb wyboru roku", code="invalid_release_year_mode")

    @staticmethod
    def _row_dict(row):
        return dict(row) if row else None

    def _artist_id(self, connection, name):
        name = str(name or "Unknown Artist").strip() or "Unknown Artist"
        key = normalize_text(name)
        now = utc_now()
        connection.execute(
            "INSERT INTO music_artists(name, normalized_name, created_at, updated_at) VALUES(?,?,?,?) "
            "ON CONFLICT(normalized_name) DO UPDATE SET updated_at=excluded.updated_at",
            (name, key, now, now),
        )
        return int(connection.execute("SELECT id FROM music_artists WHERE normalized_name=?", (key,)).fetchone()[0])

    def _genre_id(self, connection, genre):
        name = str((genre or {}).get("name") or "").strip()
        if not name:
            return None
        source = str((genre or {}).get("source") or "RYM").upper()
        slug = (genre or {}).get("slug") or slug_from_genre_url((genre or {}).get("url"))
        key = normalize_text(name)
        row = None
        if slug:
            row = connection.execute(
                "SELECT id,slug FROM music_genres WHERE source=? AND slug=?", (source, slug)
            ).fetchone()
        if not row:
            row = connection.execute(
                "SELECT id,slug FROM music_genres WHERE source=? AND normalized_name=?", (source, key)
            ).fetchone()
            if row and slug and row["slug"] and row["slug"] != slug:
                key = f"{key} {slug}"
                row = connection.execute(
                    "SELECT id,slug FROM music_genres WHERE source=? AND normalized_name=?", (source, key)
                ).fetchone()
        now = utc_now()
        if row:
            genre_id = int(row[0])
            connection.execute(
                "UPDATE music_genres SET name=?, slug=COALESCE(slug,?), source_url=COALESCE(?,source_url), "
                "description=CASE WHEN ?<>'' THEN ? ELSE description END, updated_at=? WHERE id=?",
                (name, slug, (genre or {}).get("url"), str((genre or {}).get("description") or ""),
                 (genre or {}).get("description"), now, genre_id),
            )
            return genre_id
        cursor = connection.execute(
            "INSERT INTO music_genres(name,normalized_name,slug,source,source_url,description,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (name, key, slug, source, (genre or {}).get("url"), (genre or {}).get("description"), now, now),
        )
        return int(cursor.lastrowid)

    def _external_match(self, connection, row):
        checks = []
        if row.get("rymReleaseId"):
            checks.append(("rym", "release_id", str(row["rymReleaseId"])))
        if row.get("releaseUrl"):
            checks.append(("rym", "release_url", str(row["releaseUrl"])))
        for source, kind, value in checks:
            match = connection.execute(
                "SELECT entity_id FROM music_external_ids WHERE entity_type='release' AND source=? "
                "AND external_type=? AND external_value=?",
                (source, kind, value),
            ).fetchone()
            if match:
                return int(match[0])
        return None

    def _candidate_payload(self, connection, release_ids):
        if not release_ids:
            return []
        placeholders = ",".join("?" for _ in release_ids)
        rows = connection.execute(
            f"SELECT id,title,artist_credit,release_year,release_type FROM music_releases WHERE id IN ({placeholders})",
            tuple(release_ids),
        ).fetchall()
        return [dict(row) for row in rows]

    def _match_import_row(self, connection, row):
        release_id = self._external_match(connection, row)
        if release_id:
            return {"status": "EXACT_MATCH", "releaseId": release_id, "candidates": self._candidate_payload(connection, [release_id])}

        artist_key = normalize_text(row.get("artistCredit"))
        title_key = normalize_text(row.get("title"))
        year = row.get("releaseYear")
        release_type = normalize_text(row.get("releaseType") or "Album")
        matches = connection.execute(
            "SELECT id FROM music_releases WHERE normalized_artist_credit=? AND normalized_title=? "
            "AND (? IS NULL OR release_year IS NULL OR release_year=?) "
            "AND lower(release_type)=lower(?)",
            (artist_key, title_key, year, year, row.get("releaseType") or "Album"),
        ).fetchall()
        if len(matches) == 1:
            release_id = int(matches[0][0])
            return {"status": "LIKELY_MATCH", "releaseId": release_id, "candidates": self._candidate_payload(connection, [release_id])}
        if len(matches) > 1:
            ids = [int(match[0]) for match in matches]
            return {"status": "AMBIGUOUS", "releaseId": None, "candidates": self._candidate_payload(connection, ids)}

        legacy = find_legacy_matches(row.get("artistCredit"), row.get("title"), year)
        linked = []
        for candidate in legacy:
            existing = connection.execute(
                "SELECT music_release_id FROM music_legacy_links WHERE legacy_module=? AND legacy_entity_type=? AND legacy_entity_id=?",
                (candidate["legacyModule"], candidate["legacyEntityType"], candidate["legacyEntityId"]),
            ).fetchone()
            if existing:
                linked.append(int(existing[0]))
        if linked:
            ids = sorted(set(linked))
            if len(ids) == 1:
                return {"status": "LEGACY_MATCH", "releaseId": ids[0], "candidates": self._candidate_payload(connection, ids), "legacy": legacy[0]}
            return {"status": "AMBIGUOUS", "releaseId": None, "candidates": self._candidate_payload(connection, ids), "legacy": legacy}
        if len(legacy) == 1:
            return {"status": "LEGACY_MATCH", "releaseId": None, "candidates": [], "legacy": legacy[0]}
        if len(legacy) > 1:
            return {"status": "AMBIGUOUS", "releaseId": None, "candidates": [], "legacy": legacy}

        possible = []
        for candidate in connection.execute(
            "SELECT id,title,normalized_title,artist_credit,normalized_artist_credit,release_year,release_type "
            "FROM music_releases WHERE normalized_title LIKE ? OR normalized_artist_credit LIKE ? LIMIT 30",
            (f"%{title_key[:24]}%", f"%{artist_key[:24]}%"),
        ).fetchall():
            left = f"{artist_key} {title_key}"
            right = f"{candidate['normalized_artist_credit']} {candidate['normalized_title']}"
            score = SequenceMatcher(None, left, right).ratio()
            if score >= 0.86:
                payload = dict(candidate)
                payload["confidence"] = round(score, 3)
                possible.append(payload)
        if possible:
            possible.sort(key=lambda item: item["confidence"], reverse=True)
            return {"status": "AMBIGUOUS", "releaseId": None, "candidates": possible[:5]}
        return {"status": "NEW", "releaseId": None, "candidates": []}

    def preview_import(self, *, filename, html, captured_at=None, reparse=False):
        if not str(filename or "").lower().endswith((".html", ".htm")):
            raise MusicError("Wybierz zapisany plik HTML", code="invalid_file_type")
        raw = str(html or "")
        if not raw.strip():
            raise MusicError("Plik HTML jest pusty", code="empty_import")
        if len(raw.encode("utf-8")) > 12 * 1024 * 1024:
            raise MusicError("Plik HTML przekracza limit 12 MB", status=413, code="import_too_large")
        parsed = parse_rym_html(raw)
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        self.initialize()
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT id,status FROM music_import_batches WHERE file_hash_sha256=?", (digest,)
            ).fetchone()
            if existing and not reparse:
                result = self.get_import(int(existing["id"]))
                result["alreadyImported"] = True
                return result

        self.import_dir.mkdir(parents=True, exist_ok=True)
        raw_path = self.import_dir / f"{digest}.html"
        if not raw_path.exists() or reparse:
            raw_path.write_text(raw, encoding="utf-8")
        now = utc_now()
        with self._lock, self._connect() as connection:
            if existing:
                batch_id = int(existing["id"])
                connection.execute("DELETE FROM music_import_rows WHERE batch_id=?", (batch_id,))
                connection.execute(
                    "UPDATE music_import_batches SET source=?,page_type=?,original_filename=?,source_url=?,parser_version=?,"
                    "captured_at=?,imported_at=?,committed_at=NULL,status='PREVIEW',raw_file_path=?,title=?,metadata_json=? WHERE id=?",
                    (parsed["source"], parsed["pageType"], filename, parsed.get("sourceUrl"), PARSER_VERSION,
                     captured_at, now, str(raw_path.relative_to(self.root)).replace("\\", "/"), parsed.get("title"),
                     self._json({key: value for key, value in parsed.items() if key not in {"rows", "genres"}}), batch_id),
                )
            else:
                cursor = connection.execute(
                    "INSERT INTO music_import_batches(source,page_type,original_filename,file_hash_sha256,source_url,parser_version,"
                    "captured_at,imported_at,status,raw_file_path,title,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (parsed["source"], parsed["pageType"], filename, digest, parsed.get("sourceUrl"), PARSER_VERSION,
                     captured_at, now, "PREVIEW", str(raw_path.relative_to(self.root)).replace("\\", "/"), parsed.get("title"),
                     self._json({key: value for key, value in parsed.items() if key not in {"rows", "genres"}})),
                )
                batch_id = int(cursor.lastrowid)

            counts = {"NEW": 0, "MATCHED": 0, "AMBIGUOUS": 0, "ERROR": 0}
            for index, row in enumerate(parsed.get("rows") or [], 1):
                try:
                    match = ({"status": "NEW", "releaseId": None, "candidates": []}
                             if parsed["pageType"] == "RYM_GENRE_INDEX" else self._match_import_row(connection, row))
                    if match.get("legacy"):
                        row["_legacyMatch"] = match["legacy"]
                    status = match["status"]
                    counts["AMBIGUOUS" if status == "AMBIGUOUS" else ("NEW" if status == "NEW" else "MATCHED")] += 1
                    connection.execute(
                        "INSERT INTO music_import_rows(batch_id,row_index,source_position,parsed_json,match_status,matched_release_id,candidates_json) "
                        "VALUES(?,?,?,?,?,?,?)",
                        (batch_id, index, row.get("position"), self._json(row), status, match.get("releaseId"), self._json(match.get("candidates") or [])),
                    )
                except Exception as exc:
                    counts["ERROR"] += 1
                    connection.execute(
                        "INSERT INTO music_import_rows(batch_id,row_index,source_position,parsed_json,match_status,error_text) VALUES(?,?,?,?,?,?)",
                        (batch_id, index, row.get("position"), self._json(row), "ERROR", str(exc)[:1000]),
                    )
            connection.execute(
                "UPDATE music_import_batches SET parsed_count=?,new_count=?,matched_count=?,ambiguous_count=?,error_count=? WHERE id=?",
                (len(parsed.get("rows") or []), counts["NEW"], counts["MATCHED"], counts["AMBIGUOUS"], counts["ERROR"], batch_id),
            )
        return self.get_import(batch_id)

    def get_import(self, batch_id):
        self.initialize()
        with self._connect() as connection:
            batch = connection.execute("SELECT * FROM music_import_batches WHERE id=?", (int(batch_id),)).fetchone()
            if not batch:
                raise MusicError("Import nie istnieje", status=404, code="import_not_found")
            rows = connection.execute(
                "SELECT * FROM music_import_rows WHERE batch_id=? ORDER BY row_index", (int(batch_id),)
            ).fetchall()
        payload = dict(batch)
        payload["metadata"] = json.loads(payload.pop("metadata_json") or "{}")
        payload["rows"] = []
        for row in rows:
            item = dict(row)
            item["parsed"] = json.loads(item.pop("parsed_json"))
            item["candidates"] = json.loads(item.pop("candidates_json") or "[]")
            item["resolution"] = json.loads(item.pop("resolution_json") or "null")
            payload["rows"].append(item)
        return {"ok": True, "batch": payload}

    def _upsert_external_id(self, connection, release_id, source, kind, value, url=None):
        if value is None or str(value).strip() == "":
            return
        connection.execute(
            "INSERT OR IGNORE INTO music_external_ids(entity_type,entity_id,source,external_type,external_value,external_url,created_at) "
            "VALUES('release',?,?,?,?,?,?)",
            (release_id, str(source).lower(), str(kind).lower(), str(value), url, utc_now()),
        )

    def _create_release(self, connection, row):
        now = utc_now()
        cursor = connection.execute(
            "INSERT INTO music_releases(title,normalized_title,artist_credit,normalized_artist_credit,release_type,release_date,"
            "release_year,cover_local,cover_remote,recorded_text,label,catalog_number,issues_text,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (row.get("title"), normalize_text(row.get("title")), row.get("artistCredit") or "Unknown Artist",
             normalize_text(row.get("artistCredit") or "Unknown Artist"), row.get("releaseType") or "Album",
             row.get("releaseDate"), row.get("releaseYear"), row.get("coverLocal"), row.get("coverRemote"),
             row.get("recordedText"), row.get("label"), row.get("catalogNumber"), row.get("issuesText"), now, now),
        )
        return int(cursor.lastrowid)

    def _enrich_release(self, connection, release_id, row):
        connection.execute(
            "UPDATE music_releases SET release_date=COALESCE(?,release_date),release_year=COALESCE(?,release_year),"
            "cover_local=COALESCE(cover_local,?),cover_remote=COALESCE(?,cover_remote),recorded_text=COALESCE(?,recorded_text),"
            "label=COALESCE(?,label),catalog_number=COALESCE(?,catalog_number),issues_text=COALESCE(?,issues_text),"
            "description=CASE WHEN COALESCE(description,'')='' AND COALESCE(?,'')<>'' THEN ? ELSE description END,"
            "duration_seconds=COALESCE(duration_seconds,?),updated_at=? WHERE id=?",
            (row.get("releaseDate"), row.get("releaseYear"), row.get("coverLocal"), row.get("coverRemote"),
             row.get("recordedText"), row.get("label"), row.get("catalogNumber"), row.get("issuesText"),
             row.get("description"), row.get("description"), row.get("durationSeconds"), utc_now(), release_id),
        )
        for order, name in enumerate(row.get("artists") or [row.get("artistCredit") or "Unknown Artist"]):
            artist_id = self._artist_id(connection, name)
            connection.execute(
                "INSERT OR IGNORE INTO music_release_artists(release_id,artist_id,credit_order,credit_role,display_credit) VALUES(?,?,?,?,?)",
                (release_id, artist_id, order, "PRIMARY", name),
            )
        self._upsert_external_id(connection, release_id, "rym", "release_id", row.get("rymReleaseId"), row.get("releaseUrl"))
        self._upsert_external_id(connection, release_id, "rym", "release_url", row.get("releaseUrl"), row.get("releaseUrl"))
        for external in row.get("externalIds") or []:
            self._upsert_external_id(connection, release_id, external.get("source"), external.get("type"), external.get("value"), external.get("url"))

    def _attach_release_data(self, connection, release_id, row, batch_id, import_row_id, captured_at):
        for role, key in (("PRIMARY", "primaryGenres"), ("SECONDARY", "secondaryGenres")):
            for genre in row.get(key) or []:
                genre_id = self._genre_id(connection, {**genre, "source": "RYM"})
                if genre_id:
                    connection.execute(
                        "INSERT OR IGNORE INTO music_release_genres(release_id,genre_id,role,source,source_record_id) VALUES(?,?,?,?,?)",
                        (release_id, genre_id, role, "RYM", import_row_id),
                    )
        for descriptor in row.get("descriptors") or []:
            key = normalize_text(descriptor)
            if not key:
                continue
            connection.execute("INSERT OR IGNORE INTO music_descriptors(name,normalized_name) VALUES(?,?)", (descriptor, key))
            descriptor_id = int(connection.execute("SELECT id FROM music_descriptors WHERE normalized_name=?", (key,)).fetchone()[0])
            connection.execute(
                "INSERT OR IGNORE INTO music_release_descriptors(release_id,descriptor_id,source,source_record_id) VALUES(?,?,?,?)",
                (release_id, descriptor_id, "RYM", import_row_id),
            )
        for track in row.get("tracks") or []:
            connection.execute(
                "INSERT INTO music_tracks(release_id,position,disc_number,title,normalized_title,duration_seconds,source) VALUES(?,?,?,?,?,?,?) "
                "ON CONFLICT(release_id,position,normalized_title) DO UPDATE SET duration_seconds=COALESCE(excluded.duration_seconds,duration_seconds)",
                (release_id, str(track.get("position") or ""), track.get("discNumber"), track.get("title"),
                 normalize_text(track.get("title")), track.get("durationSeconds"), track.get("source") or "RYM"),
            )
        for credit in row.get("credits") or []:
            for role in credit.get("roles") or ["credit"]:
                connection.execute(
                    "INSERT OR IGNORE INTO music_release_credits(release_id,person_name,normalized_person_name,role,source) VALUES(?,?,?,?,?)",
                    (release_id, credit.get("name"), normalize_text(credit.get("name")), role, "RYM"),
                )
        if any(row.get(key) is not None for key in ("rymRating", "rymRatingsDisplay", "rymReviews", "rankingText")):
            connection.execute(
                "INSERT OR IGNORE INTO music_release_metric_snapshots(release_id,source,captured_at,rating,rating_display,rating_count,"
                "rating_count_display,review_count,review_count_display,ranking_text,import_batch_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (release_id, "RYM", captured_at, row.get("rymRating"), row.get("rymRatingDisplay"), row.get("rymRatingsApprox"),
                 row.get("rymRatingsDisplay"), row.get("rymReviews"), row.get("rymReviewsDisplay"), row.get("rankingText"), batch_id),
            )
        connection.execute(
            "INSERT OR IGNORE INTO music_source_records(batch_id,import_row_id,entity_type,entity_id,source_url,observed_at,payload_json) "
            "VALUES(?,?,?,?,?,?,?)",
            (batch_id, import_row_id, "release", release_id, row.get("releaseUrl"), captured_at, self._json(row)),
        )
        legacy = row.get("_legacyMatch")
        if isinstance(legacy, dict):
            connection.execute(
                "INSERT OR IGNORE INTO music_legacy_links(legacy_module,legacy_entity_type,legacy_entity_id,music_release_id,match_method,confidence,created_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (legacy.get("legacyModule"), legacy.get("legacyEntityType") or "album", legacy.get("legacyEntityId"),
                 release_id, "normalized_artist_title_year", legacy.get("confidence"), utc_now()),
            )

    @staticmethod
    def _cover_slug(artist, title):
        replacements = str.maketrans({
            "ł": "l", "Ł": "l", "đ": "d", "Đ": "d", "ð": "d", "Ð": "d",
            "þ": "th", "Þ": "th", "æ": "ae", "Æ": "ae", "œ": "oe", "Œ": "oe",
            "ø": "o", "Ø": "o", "&": "and",
        })

        def slug_part(value):
            value = str(value or "").translate(replacements)
            value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii").lower()
            return re.sub(r"[^a-z0-9]+", "-", value).strip("-")

        return "--".join(part for part in (slug_part(artist), slug_part(title)) if part) or "unknown"

    def _legacy_cover_path(self, artist, title):
        slug = self._cover_slug(artist, title)
        for candidate_slug in (slug, slug.replace("--", "-")):
            for extension in ("jpg", "jpeg", "png", "webp"):
                candidate = self.root / "covers" / f"{candidate_slug}.{extension}"
                if candidate.is_file():
                    return f"/covers/{candidate.name}"
        return None

    def set_cover(self, release_id, url):
        value = str(url or "").strip() or None
        self.initialize()
        with self._connect() as connection:
            if not connection.execute("SELECT 1 FROM music_releases WHERE id=?", (int(release_id),)).fetchone():
                raise MusicError("Album nie istnieje", status=404, code="release_not_found")
            connection.execute(
                "UPDATE music_releases SET cover_local=?,updated_at=? WHERE id=?",
                (value, utc_now(), int(release_id)),
            )
        return {"ok": True, "releaseId": int(release_id), "url": value}

    def missing_covers(self, limit=25):
        self.initialize()
        size = max(1, min(int(limit), 100))
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id,artist_credit,title FROM music_releases "
                "WHERE COALESCE(cover_local,'')='' AND COALESCE(cover_remote,'')='' "
                "ORDER BY normalized_artist_credit,normalized_title LIMIT ?",
                (size,),
            ).fetchall()
        return [dict(row) for row in rows]

    def sync_local_covers(self):
        """Attach canonical covers and copy imported sidecar images into /covers."""
        self.initialize()
        cover_dir = self.root / "covers"
        cover_dir.mkdir(parents=True, exist_ok=True)
        report = {"ok": True, "matched": 0, "copied": 0, "missing": 0}
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT id,artist_credit,title,cover_local FROM music_releases ORDER BY id"
            ).fetchall()
            for row in rows:
                current = str(row["cover_local"] or "")
                generated = current.startswith('/covers/music-') and (self.root / current.lstrip('/')).is_file()
                canonical = current if generated else self._legacy_cover_path(row["artist_credit"], row["title"])
                copied = False
                if not canonical:
                    raw_path = str(row["cover_local"] or "").strip()
                    if raw_path.startswith("data:image/"):
                        connection.execute(
                            "UPDATE music_releases SET cover_local=NULL,updated_at=? WHERE id=?",
                            (utc_now(), int(row["id"])),
                        )
                        raw_path = ""
                    if raw_path and not re.match(r"^(?:https?:)?//", raw_path, re.I):
                        normalized = raw_path.replace("\\", "/").lstrip("./")
                        if normalized.startswith("covers/"):
                            existing = (self.root / normalized).resolve()
                            if existing.is_file():
                                canonical = f"/covers/{existing.name}"
                        else:
                            for base in (self.root, self.root.parent):
                                candidate = (base / normalized).resolve()
                                try:
                                    candidate.relative_to(base.resolve())
                                except ValueError:
                                    continue
                                if not candidate.is_file() or candidate.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
                                    continue
                                extension = ".jpg" if candidate.suffix.lower() == ".jpeg" else candidate.suffix.lower()
                                destination = cover_dir / f"{self._cover_slug(row['artist_credit'], row['title'])}{extension}"
                                shutil.copy2(candidate, destination)
                                canonical = f"/covers/{destination.name}"
                                copied = True
                                break
                if canonical:
                    if canonical != row["cover_local"]:
                        connection.execute(
                            "UPDATE music_releases SET cover_local=?,updated_at=? WHERE id=?",
                            (canonical, utc_now(), int(row["id"])),
                        )
                    report["matched"] += 1
                    report["copied"] += int(copied)
                else:
                    report["missing"] += 1
        return report

    def refresh_imported_metadata(self):
        """Repair parser-derived metadata in committed imports without re-importing user data."""
        self.initialize()
        report = {"ok": True, "batches": 0, "updated": 0, "errors": 0}
        with self._lock, self._connect() as connection:
            batches = connection.execute(
                "SELECT id,raw_file_path FROM music_import_batches "
                "WHERE status='COMMITTED' AND page_type IN ('RYM_CHART','RYM_RELEASE')"
            ).fetchall()
            for batch in batches:
                try:
                    raw_path = (self.root / str(batch["raw_file_path"] or "")).resolve()
                    raw_path.relative_to(self.root.resolve())
                    if not raw_path.is_file():
                        continue
                    parsed = parse_rym_html(raw_path.read_text(encoding="utf-8"))
                    report["batches"] += 1
                    for item in parsed.get("rows") or []:
                        release_id = self._external_match(connection, item)
                        if not release_id:
                            match = connection.execute(
                                "SELECT id FROM music_releases WHERE normalized_artist_credit=? AND normalized_title=? LIMIT 2",
                                (normalize_text(item.get("artistCredit")), normalize_text(item.get("title"))),
                            ).fetchall()
                            if len(match) == 1:
                                release_id = int(match[0]["id"])
                        if not release_id:
                            continue
                        connection.execute(
                            "UPDATE music_releases SET release_year=COALESCE(?,release_year),"
                            "release_date=COALESCE(?,release_date),"
                            "cover_local=CASE WHEN ? IS NOT NULL THEN ? WHEN cover_local LIKE 'data:image/%' THEN NULL ELSE cover_local END,"
                            "cover_remote=COALESCE(?,cover_remote),updated_at=? WHERE id=?",
                            (item.get("releaseYear"), item.get("releaseDate"), item.get("coverLocal"), item.get("coverLocal"),
                             item.get("coverRemote"), utc_now(), release_id),
                        )
                        report["updated"] += 1
                except (OSError, ValueError, MusicError):
                    report["errors"] += 1
        return report

    @staticmethod
    def _legacy_year(row):
        value = row.get("releaseYear", row.get("year"))
        try:
            value = int(value)
        except (TypeError, ValueError):
            return None
        return value if 1000 <= value <= 3000 else None

    @staticmethod
    def _legacy_listened(value):
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        return str(value or "").strip().casefold() in {"1", "true", "yes", "tak"}

    def sync_legacy_catalog(self, rows=None):
        """Mirror legacy identities and state without writing legacy stores."""
        source_rows = list(legacy_catalog_rows() if rows is None else rows)
        self.initialize()
        report = {"rows": len(source_rows), "created": 0, "matched": 0, "linked": 0, "ambiguous": 0}
        with self._lock, self._connect() as connection:
            for source_row in source_rows:
                row = dict(source_row)
                module = str(row.get("legacyModule") or "").strip()
                legacy_id = str(row.get("rowId") or "").strip()
                artist = str(row.get("artist") or "").strip()
                title = str(row.get("album") or "").strip()
                if not module or not legacy_id or not artist or not title:
                    report["ambiguous"] += 1
                    continue

                existing_link = connection.execute(
                    "SELECT id,music_release_id FROM music_legacy_links WHERE legacy_module=? "
                    "AND legacy_entity_type='album' AND legacy_entity_id=?",
                    (module, legacy_id),
                ).fetchone()
                release_id = int(existing_link["music_release_id"]) if existing_link else None
                method = "LEGACY_EXISTING_LINK"
                year = self._legacy_year(row)
                community_url = str(row.get("communityUrl") or "").strip() or None
                is_rym_url = bool(community_url and "rateyourmusic.com/" in community_url.casefold())

                if release_id is None and is_rym_url:
                    release_id = self._external_match(connection, {"releaseUrl": community_url})
                    if release_id:
                        method = "LEGACY_RYM_URL"

                if release_id is None:
                    candidates = connection.execute(
                        "SELECT id,release_year FROM music_releases "
                        "WHERE normalized_artist_credit=? AND normalized_title=?",
                        (normalize_text(artist), normalize_text(title)),
                    ).fetchall()
                    if len(candidates) == 1:
                        release_id = int(candidates[0]["id"])
                        method = "LEGACY_EXACT_IDENTITY"
                        if year and candidates[0]["release_year"] and year != int(candidates[0]["release_year"]):
                            method = "LEGACY_EXACT_IDENTITY_YEAR_CONFLICT"
                    elif len(candidates) > 1:
                        same_year = [candidate for candidate in candidates if year and candidate["release_year"] == year]
                        if len(same_year) == 1:
                            release_id = int(same_year[0]["id"])
                            method = "LEGACY_EXACT_IDENTITY_YEAR"
                        else:
                            report["ambiguous"] += 1
                            continue

                payload = {
                    "title": title,
                    "artistCredit": artist,
                    "artists": [artist],
                    "releaseType": "Album",
                    "releaseYear": year,
                    "coverLocal": self._legacy_cover_path(artist, title),
                    "description": str(row.get("description") or "").strip() or None,
                    "durationSeconds": int(row["minutes"]) * 60 if row.get("minutes") not in (None, "") else None,
                    "releaseUrl": community_url if is_rym_url else None,
                }
                if release_id is None:
                    release_id = self._create_release(connection, payload)
                    method = "LEGACY_CREATED"
                    report["created"] += 1
                else:
                    report["matched"] += 1
                self._enrich_release(connection, release_id, payload)
                self._upsert_external_id(connection, release_id, module, "album_id", legacy_id)
                if community_url and not is_rym_url:
                    self._upsert_external_id(
                        connection, release_id, "legacy_community", "release_url", community_url, community_url
                    )

                if existing_link:
                    link_id = int(existing_link["id"])
                else:
                    cursor = connection.execute(
                        "INSERT INTO music_legacy_links(legacy_module,legacy_entity_type,legacy_entity_id,music_release_id,"
                        "match_method,confidence,created_at) VALUES(?,'album',?,?,?,?,?)",
                        (module, legacy_id, release_id, method, 1.0, utc_now()),
                    )
                    link_id = int(cursor.lastrowid)
                    report["linked"] += 1

                state_values = (
                    link_id, row.get("date"), int(self._legacy_listened(row.get("listened"))), row.get("rating"),
                    row.get("minutes"), str(row.get("description") or "").strip() or None, row.get("rymRating"),
                    int(bool(row.get("rymRatingIgnored"))), row.get("communityRating"), row.get("communityVotes"),
                    row.get("communitySource"), community_url, row.get("communityCheckedAt"), row.get("sourceRank"),
                    row.get("updatedAt"), utc_now(), self._json(row),
                )
                connection.execute(
                    "INSERT INTO music_legacy_release_state(legacy_link_id,planned_date,listened,rating,minutes,description,"
                    "rym_rating,rym_rating_ignored,community_rating,community_votes,community_source,community_url,"
                    "community_checked_at,source_rank,source_updated_at,observed_at,payload_json) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(legacy_link_id) DO UPDATE SET "
                    "planned_date=excluded.planned_date,listened=excluded.listened,rating=excluded.rating,"
                    "minutes=excluded.minutes,description=excluded.description,rym_rating=excluded.rym_rating,"
                    "rym_rating_ignored=excluded.rym_rating_ignored,community_rating=excluded.community_rating,"
                    "community_votes=excluded.community_votes,community_source=excluded.community_source,"
                    "community_url=excluded.community_url,community_checked_at=excluded.community_checked_at,"
                    "source_rank=excluded.source_rank,source_updated_at=excluded.source_updated_at,"
                    "observed_at=excluded.observed_at,payload_json=excluded.payload_json",
                    state_values,
                )
        return {"ok": True, **report}

    def _commit_genres(self, connection, rows):
        by_url = {}
        for import_row in rows:
            genre = json.loads(import_row["parsed_json"])
            genre_id = self._genre_id(connection, genre)
            if genre.get("url"):
                by_url[genre["url"]] = genre_id
        relations = 0
        for import_row in rows:
            genre = json.loads(import_row["parsed_json"])
            child_id = by_url.get(genre.get("url"))
            for parent_url in genre.get("parentUrls") or []:
                parent_id = by_url.get(parent_url)
                if parent_id and child_id and parent_id != child_id:
                    before = connection.total_changes
                    connection.execute(
                        "INSERT OR IGNORE INTO music_genre_relations(parent_genre_id,child_genre_id,source,relation_type) VALUES(?,?,?,?)",
                        (parent_id, child_id, "RYM", "SUBGENRE"),
                    )
                    relations += connection.total_changes - before
        return {"genres": len(by_url), "relations": relations}

    def sync_genre_hierarchy(self, parsed):
        """Replace derived RYM hierarchy edges with a complete canonical DAG."""
        rows = list((parsed or {}).get("rows") or [])
        relations = list((parsed or {}).get("relations") or [])
        if not rows:
            raise MusicError("Dokument nie zawiera gatunków RYM", code="empty_genre_hierarchy")
        self.initialize()
        by_url = {}
        with self._lock, self._connect() as connection:
            for row in rows:
                genre_id = self._genre_id(connection, {**row, "source": "RYM"})
                url = str(row.get("url") or "").strip()
                if genre_id and url:
                    by_url[url] = genre_id
            connection.execute("DELETE FROM music_genre_relations WHERE source='RYM'")
            inserted = missing = 0
            for relation in relations:
                parent_id = by_url.get(str(relation.get("parentUrl") or "").strip())
                child_id = by_url.get(str(relation.get("childUrl") or "").strip())
                if not parent_id or not child_id or parent_id == child_id:
                    missing += 1
                    continue
                before = connection.total_changes
                connection.execute(
                    "INSERT OR IGNORE INTO music_genre_relations(parent_genre_id,child_genre_id,source,relation_type) "
                    "VALUES(?,?,?,?)",
                    (parent_id, child_id, "RYM", "SUBGENRE"),
                )
                inserted += connection.total_changes - before
        return {
            "ok": True,
            "genres": len(by_url),
            "relations": inserted,
            "missingRelations": missing,
            "occurrences": int((parsed or {}).get("occurrenceCount") or len(rows)),
            "anomalies": int((parsed or {}).get("anomalyCount") or 0),
        }

    def commit_import(self, batch_id, resolutions=None, *, fail_after=None):
        self.initialize()
        resolutions = {str(key): value for key, value in (resolutions or {}).items()}
        with self._lock, self._connect() as connection:
            batch = connection.execute("SELECT * FROM music_import_batches WHERE id=?", (int(batch_id),)).fetchone()
            if not batch:
                raise MusicError("Import nie istnieje", status=404, code="import_not_found")
            if batch["status"] == "COMMITTED":
                return {"ok": True, "alreadyCommitted": True, "batchId": int(batch_id)}
            rows = connection.execute("SELECT * FROM music_import_rows WHERE batch_id=? ORDER BY row_index", (int(batch_id),)).fetchall()
            captured_at = batch["captured_at"] or batch["imported_at"] or utc_now()
            if batch["page_type"] == "RYM_GENRE_INDEX":
                result = self._commit_genres(connection, rows)
                connection.execute("UPDATE music_import_batches SET status='COMMITTED',committed_at=? WHERE id=?", (utc_now(), int(batch_id)))
                return {"ok": True, "batchId": int(batch_id), **result}

            snapshot_id = ranking_id = None
            if batch["page_type"] == "RYM_CHART":
                metadata = json.loads(batch["metadata_json"] or "{}")
                source_key = metadata.get("rankingKey") or batch["source_url"] or normalize_text(batch["title"])
                now = utc_now()
                connection.execute(
                    "INSERT INTO music_rankings(name,kind,source,source_key,filters_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?) "
                    "ON CONFLICT(source,source_key) DO UPDATE SET name=excluded.name,filters_json=excluded.filters_json,updated_at=excluded.updated_at",
                    (batch["title"] or "Ranking RYM", "SOURCE", "RYM", source_key, self._json(metadata.get("filters") or {}), now, now),
                )
                ranking_id = int(connection.execute("SELECT id FROM music_rankings WHERE source='RYM' AND source_key=?", (source_key,)).fetchone()[0])
                connection.execute("UPDATE music_ranking_snapshots SET is_current=0 WHERE ranking_id=?", (ranking_id,))
                cursor = connection.execute(
                    "INSERT INTO music_ranking_snapshots(ranking_id,import_batch_id,captured_at,created_at,is_current) VALUES(?,?,?,?,1)",
                    (ranking_id, int(batch_id), captured_at, now),
                )
                snapshot_id = int(cursor.lastrowid)

            report = {"created": 0, "matched": 0, "skipped": 0, "errors": 0, "releases": [],
                      "ratingsAdded": 0, "ratingsAlreadyPresent": 0, "ratingConflicts": []}
            for count, import_row in enumerate(rows, 1):
                if fail_after is not None and count > int(fail_after):
                    raise MusicError("Wymuszony błąd testowy", status=500, code="forced_commit_failure")
                row = json.loads(import_row["parsed_json"])
                resolution = resolutions.get(str(import_row["id"])) or resolutions.get(str(import_row["row_index"])) or {}
                action = str(resolution.get("action") or "").lower()
                release_id = resolution.get("releaseId") or import_row["matched_release_id"]
                status = import_row["match_status"]
                if not action:
                    action = "skip" if status in {"AMBIGUOUS", "ERROR", "SKIPPED"} else ("match" if release_id else "create")
                if action == "skip":
                    report["skipped"] += 1
                    connection.execute("UPDATE music_import_rows SET resolution_json=? WHERE id=?", (self._json({"action": "skip"}), import_row["id"]))
                    continue
                if action == "match":
                    if not release_id or not connection.execute("SELECT 1 FROM music_releases WHERE id=?", (int(release_id),)).fetchone():
                        raise MusicError(f"Nieprawidłowe dopasowanie w wierszu {import_row['row_index']}", code="invalid_resolution")
                    release_id = int(release_id)
                    report["matched"] += 1
                elif action == "create":
                    exact = self._external_match(connection, row)
                    if exact:
                        release_id = exact
                        report["matched"] += 1
                    else:
                        strong = connection.execute(
                            "SELECT id FROM music_releases WHERE normalized_artist_credit=? AND normalized_title=? "
                            "AND (? IS NULL OR release_year IS NULL OR release_year=?) AND lower(release_type)=lower(?) LIMIT 2",
                            (normalize_text(row.get("artistCredit")), normalize_text(row.get("title")), row.get("releaseYear"),
                             row.get("releaseYear"), row.get("releaseType") or "Album"),
                        ).fetchall()
                        if len(strong) == 1:
                            release_id = int(strong[0][0])
                            report["matched"] += 1
                        else:
                            release_id = self._create_release(connection, row)
                            report["created"] += 1
                else:
                    raise MusicError(f"Nieznana akcja importu: {action}", code="invalid_resolution")
                self._enrich_release(connection, release_id, row)
                self._attach_release_data(connection, release_id, row, int(batch_id), int(import_row["id"]), captured_at)
                if batch["page_type"] == "RYM_COLLECTION":
                    existing_rating = connection.execute(
                        "SELECT rating FROM music_user_ratings WHERE release_id=?", (release_id,)
                    ).fetchone()
                    if existing_rating is None:
                        existing_rating = connection.execute(
                            "SELECT ls.rating FROM music_legacy_release_state ls "
                            "JOIN music_legacy_links ll ON ll.id=ls.legacy_link_id "
                            "WHERE ll.music_release_id=? AND ls.rating IS NOT NULL "
                            "ORDER BY COALESCE(ls.source_updated_at,ls.observed_at) DESC LIMIT 1", (release_id,)
                        ).fetchone()
                    if existing_rating is not None:
                        report["ratingsAlreadyPresent"] += 1
                        if float(existing_rating["rating"]) != float(row["userRating"]):
                            report["ratingConflicts"].append({"releaseId": release_id, "artist": row["artistCredit"],
                                                               "title": row["title"], "existing": existing_rating["rating"],
                                                               "rym": row["userRating"]})
                    else:
                        rated_at = row.get("ratedAt") or captured_at
                        connection.execute(
                            "INSERT INTO music_user_ratings(release_id,rating,rated_at,updated_at) VALUES(?,?,?,?)",
                            (release_id, row["userRating"], rated_at, utc_now()),
                        )
                        report["ratingsAdded"] += 1
                if snapshot_id is not None:
                    connection.execute(
                        "INSERT INTO music_ranking_entries(snapshot_id,release_id,position,source_position,created_at) VALUES(?,?,?,?,?)",
                        (snapshot_id, release_id, int(row.get("position") or count), row.get("position"), utc_now()),
                    )
                resolution_value = {"action": action, "releaseId": release_id}
                connection.execute(
                    "UPDATE music_import_rows SET matched_release_id=?,resolution_json=? WHERE id=?",
                    (release_id, self._json(resolution_value), import_row["id"]),
                )
                report["releases"].append(release_id)
            if ranking_id is not None:
                filters = json.loads(batch["metadata_json"] or "{}").get("filters") or {}
                for genre_name in filters.get("genres") or []:
                    genre = connection.execute(
                        "SELECT id FROM music_genres WHERE normalized_name=? ORDER BY source='RYM' DESC,id LIMIT 1",
                        (normalize_text(genre_name),),
                    ).fetchone()
                    if genre:
                        connection.execute(
                            "UPDATE music_rankings SET genre_id=? WHERE id=?",
                            (int(genre["id"]), ranking_id),
                        )
                        break
            connection.execute("UPDATE music_import_batches SET status='COMMITTED',committed_at=? WHERE id=?", (utc_now(), int(batch_id)))
            return {"ok": True, "batchId": int(batch_id), "rankingId": ranking_id, "snapshotId": snapshot_id, **report}

    @staticmethod
    def _release_select():
        return """
            SELECT r.*,
              (SELECT group_concat(g.name, ' · ') FROM music_release_genres rg JOIN music_genres g ON g.id=rg.genre_id
               WHERE rg.release_id=r.id AND rg.role='PRIMARY') AS primary_genres,
              (SELECT rating FROM music_user_ratings ur WHERE ur.release_id=r.id) AS user_rating,
              (SELECT ls.rating FROM music_legacy_release_state ls
               JOIN music_legacy_links ll ON ll.id=ls.legacy_link_id
               WHERE ll.music_release_id=r.id AND ls.rating IS NOT NULL
               ORDER BY COALESCE(ls.source_updated_at,ls.observed_at) DESC LIMIT 1) AS legacy_rating,
              (SELECT MAX(ls.listened) FROM music_legacy_release_state ls
               JOIN music_legacy_links ll ON ll.id=ls.legacy_link_id
               WHERE ll.music_release_id=r.id) AS legacy_listened,
              (SELECT group_concat(DISTINCT ll.legacy_module) FROM music_legacy_links ll
               WHERE ll.music_release_id=r.id) AS legacy_sources,
              COALESCE(
                (SELECT rating FROM music_release_metric_snapshots ms WHERE ms.release_id=r.id AND ms.source='RYM'
                 ORDER BY ms.captured_at DESC, ms.id DESC LIMIT 1),
                (SELECT COALESCE(ls.rym_rating,ls.community_rating) FROM music_legacy_release_state ls
                 JOIN music_legacy_links ll ON ll.id=ls.legacy_link_id
                 WHERE ll.music_release_id=r.id AND ls.rym_rating_ignored=0
                   AND (ls.rym_rating IS NOT NULL OR
                     (lower(COALESCE(ls.community_source,'')) LIKE '%rate your music%' AND ls.community_rating IS NOT NULL))
                 ORDER BY COALESCE(ls.community_checked_at,ls.source_updated_at,ls.observed_at) DESC LIMIT 1)
              ) AS rym_rating,
              (SELECT rating_count_display FROM music_release_metric_snapshots ms WHERE ms.release_id=r.id AND ms.source='RYM'
               ORDER BY ms.captured_at DESC, ms.id DESC LIMIT 1) AS rym_rating_count
            FROM music_releases r
        """

    def list_releases(self, filters=None):
        self.initialize()
        filters = filters or {}
        where = []
        values = []
        q = normalize_text(filters.get("q"))
        if q and not filters.get("ids"):
            where.append("(r.normalized_title LIKE ? OR r.normalized_artist_credit LIKE ?)")
            values.extend((f"%{q}%", f"%{q}%"))
        if filters.get("ids"):
            ids = [part for part in str(filters["ids"]).split(",") if part]
            if not ids or len(ids) > 200 or any(not part.isdecimal() for part in ids):
                raise MusicError("Nieprawidłowa lista wydań", code="invalid_release_ids")
            where.append(f"r.id IN ({','.join('?' for _ in ids)})")
            values.extend(int(part) for part in ids)
        year_clause, year_values = self._year_predicate(filters)
        if year_clause:
            where.append(year_clause)
            values.extend(year_values)
        if filters.get("type"):
            where.append("lower(r.release_type)=lower(?)")
            values.append(filters["type"])
        if filters.get("rating"):
            where.append("COALESCE((SELECT ur.rating FROM music_user_ratings ur WHERE ur.release_id=r.id), "
                         "(SELECT ls.rating FROM music_legacy_release_state ls JOIN music_legacy_links ll "
                         "ON ll.id=ls.legacy_link_id WHERE ll.music_release_id=r.id AND ls.rating IS NOT NULL "
                         "ORDER BY COALESCE(ls.source_updated_at,ls.observed_at) DESC LIMIT 1))>=?")
            values.append(float(filters["rating"]))
        show_rated = str(filters.get("showRated", "1")).lower() not in {"0", "false", "no"}
        show_unrated = str(filters.get("showUnrated", "1")).lower() not in {"0", "false", "no"}
        rated_clause = "(EXISTS(SELECT 1 FROM music_user_ratings ur WHERE ur.release_id=r.id) OR EXISTS(" \
                       "SELECT 1 FROM music_legacy_links ll JOIN music_legacy_release_state ls ON ls.legacy_link_id=ll.id " \
                       "WHERE ll.music_release_id=r.id AND ls.rating IS NOT NULL))"
        if show_rated and not show_unrated:
            where.append(rated_clause)
        elif show_unrated and not show_rated:
            where.append(f"NOT {rated_clause}")
        elif not show_rated and not show_unrated:
            where.append("0")
        if filters.get("source"):
            if filters["source"] == "rym_import":
                where.append("(EXISTS(SELECT 1 FROM music_external_ids ei WHERE ei.entity_type='release' "
                             "AND ei.entity_id=r.id AND ei.source='rym') OR EXISTS("
                             "SELECT 1 FROM music_source_records sr WHERE sr.entity_type='release' AND sr.entity_id=r.id))")
            else:
                where.append("EXISTS(SELECT 1 FROM music_legacy_links ll WHERE ll.music_release_id=r.id AND ll.legacy_module=?)")
                values.append(str(filters["source"]))
        if filters.get("listened") in {"yes", "no"}:
            listened_clause = "EXISTS(SELECT 1 FROM music_legacy_links ll JOIN music_legacy_release_state ls " \
                              "ON ls.legacy_link_id=ll.id WHERE ll.music_release_id=r.id AND ls.listened=1)"
            if filters["listened"] == "yes":
                where.append(listened_clause)
            else:
                where.append("EXISTS(SELECT 1 FROM music_legacy_links ll JOIN music_legacy_release_state ls "
                             "ON ls.legacy_link_id=ll.id WHERE ll.music_release_id=r.id) AND NOT " + listened_clause)
        if filters.get("genre"):
            where.append("EXISTS(SELECT 1 FROM music_release_genres rg JOIN music_genres g ON g.id=rg.genre_id WHERE rg.release_id=r.id AND (g.id=? OR g.slug=?))")
            values.extend((filters["genre"], str(filters["genre"])))
        limit = max(1, min(int(filters.get("limit") or 50), 200))
        offset = max(0, int(filters.get("offset") or 0))
        sort = str(filters.get("sort") or "my_desc")
        sort_options = {
            "my_desc": "COALESCE(user_rating,legacy_rating) IS NULL, COALESCE(user_rating,legacy_rating) DESC",
            "my_asc": "COALESCE(user_rating,legacy_rating) IS NULL, COALESCE(user_rating,legacy_rating) ASC",
            "rym_desc": "rym_rating IS NULL, rym_rating DESC",
            "rym_asc": "rym_rating IS NULL, rym_rating ASC",
            "year_desc": "r.release_year IS NULL, r.release_year DESC",
            "year_asc": "r.release_year IS NULL, r.release_year ASC",
            "artist_asc": "r.normalized_artist_credit ASC",
            "title_asc": "r.normalized_title ASC",
        }
        if sort not in sort_options:
            raise MusicError("Nieznany sposób sortowania biblioteki", code="invalid_library_sort")
        clause = f" WHERE {' AND '.join(where)}" if where else ""
        with self._connect() as connection:
            total = int(connection.execute(f"SELECT COUNT(*) FROM music_releases r{clause}", values).fetchone()[0])
            rows = connection.execute(
                self._release_select() + clause + f" ORDER BY {sort_options[sort]},r.normalized_artist_credit,r.release_year,r.normalized_title,r.id LIMIT ? OFFSET ?",
                (*values, limit, offset),
            ).fetchall()
        return {"ok": True, "rows": [dict(row) for row in rows], "total": total, "limit": limit, "offset": offset}

    def missing_metadata(self, filters=None):
        """Return a live enrichment queue derived from the canonical release rows."""
        self.initialize()
        filters = filters or {}
        limit = max(1, min(int(filters.get("limit") or 50), 200))
        offset = max(0, int(filters.get("offset") or 0))
        wanted = str(filters.get("field") or "").strip().lower()
        with self._connect() as connection:
            source_rows = connection.execute(
                """SELECT base.*,
                   (SELECT COUNT(*) FROM music_tracks mt WHERE mt.release_id=base.id) AS track_count,
                   (SELECT COUNT(*) FROM music_release_genres mrg WHERE mrg.release_id=base.id) AS genre_count,
                   (SELECT MAX(length(value_json)) FROM music_metadata_values mv WHERE mv.entity_type='release'
                    AND mv.entity_id=base.id AND mv.field_name='release_date') AS enriched_date_length
                FROM (""" + self._release_select() + """) base
                ORDER BY base.normalized_artist_credit,base.release_year,base.normalized_title"""
            ).fetchall()
        labels = {
            "cover": "okładka",
            "date": "pełna data wydania",
            "year": "rok wydania",
            "genres": "gatunki",
            "tracklist": "tracklista",
            "description": "opis",
        }
        rows = []
        counts = {key: 0 for key in labels}
        for source_row in source_rows:
            row = dict(source_row)
            missing = []
            if not (row.get("cover_local") or row.get("cover_remote")):
                missing.append("cover")
            if not row.get("release_year"):
                missing.append("year")
            elif len(str(row.get("release_date") or "")) <= 4 and int(row.get("enriched_date_length") or 0) <= 6:
                missing.append("date")
            if not int(row.get("genre_count") or 0):
                missing.append("genres")
            if not int(row.get("track_count") or 0):
                missing.append("tracklist")
            if not str(row.get("description") or "").strip():
                missing.append("description")
            for key in missing:
                counts[key] += 1
            if missing and (not wanted or wanted in missing):
                row["missing"] = missing
                row["missing_labels"] = [labels[key] for key in missing]
                rows.append(row)
        rows.sort(key=lambda row: (-len(row["missing"]), normalize_text(row.get("artist_credit")), normalize_text(row.get("title"))))
        total = len(rows)
        return {"ok": True, "rows": rows[offset:offset + limit], "total": total, "limit": limit, "offset": offset, "counts": counts, "labels": labels}

    def release_detail(self, release_id):
        self.initialize()
        with self._connect() as connection:
            release = connection.execute(self._release_select() + " WHERE r.id=?", (int(release_id),)).fetchone()
            if not release:
                raise MusicError("Album nie istnieje", status=404, code="release_not_found")
            result = dict(release)
            result["artists"] = [dict(row) for row in connection.execute(
                "SELECT a.id,a.name,ra.credit_order,ra.credit_role,ra.display_credit FROM music_release_artists ra "
                "JOIN music_artists a ON a.id=ra.artist_id WHERE ra.release_id=? ORDER BY ra.credit_order", (int(release_id),)
            )]
            result["metadata"] = {}
            for value in connection.execute(
                "SELECT field_name,value_json,provider FROM music_metadata_values WHERE entity_type='release' AND entity_id=? "
                "ORDER BY CASE provider WHEN 'musicbrainz' THEN 0 WHEN 'cover_art_archive' THEN 1 WHEN 'discogs' THEN 2 "
                "WHEN 'theaudiodb' THEN 3 WHEN 'apple' THEN 4 ELSE 5 END", (int(release_id),)
            ):
                result["metadata"].setdefault(value["field_name"], json.loads(value["value_json"]))
            full_date = connection.execute(
                "SELECT value_json FROM music_metadata_values WHERE entity_type='release' AND entity_id=? AND field_name='release_date' "
                "ORDER BY length(value_json) DESC LIMIT 1", (int(release_id),)
            ).fetchone()
            result["effective_release_date"] = (result.get("release_date") if len(str(result.get("release_date") or "")) > 4
                                                else json.loads(full_date["value_json"]) if full_date and len(full_date["value_json"]) > 6
                                                else result.get("release_date"))
            for artist in result["artists"]:
                artist["metadata"] = {}
                for value in connection.execute(
                    "SELECT field_name,value_json FROM music_metadata_values WHERE entity_type='artist' AND entity_id=? "
                    "ORDER BY CASE provider WHEN 'musicbrainz' THEN 0 WHEN 'wikimedia' THEN 1 WHEN 'wikidata' THEN 2 ELSE 3 END",
                    (artist["id"],)
                ):
                    artist["metadata"].setdefault(value["field_name"], json.loads(value["value_json"]))
            result["genres"] = [dict(row) for row in connection.execute(
                "SELECT g.id,g.name,g.slug,g.description,rg.role,rg.source FROM music_release_genres rg JOIN music_genres g ON g.id=rg.genre_id "
                "WHERE rg.release_id=? ORDER BY CASE rg.role WHEN 'PRIMARY' THEN 0 ELSE 1 END,g.name", (int(release_id),)
            )]
            result["descriptors"] = [row[0] for row in connection.execute(
                "SELECT d.name FROM music_release_descriptors rd JOIN music_descriptors d ON d.id=rd.descriptor_id WHERE rd.release_id=? ORDER BY d.name", (int(release_id),)
            )]
            result["tracks"] = [dict(row) for row in connection.execute(
                "SELECT id,position,disc_number,title,duration_seconds,source FROM music_tracks WHERE release_id=? ORDER BY id", (int(release_id),)
            )]
            result["credits"] = [dict(row) for row in connection.execute(
                "SELECT person_name,role,source FROM music_release_credits WHERE release_id=? ORDER BY person_name,role", (int(release_id),)
            )]
            result["externalIds"] = [dict(row) for row in connection.execute(
                "SELECT source,external_type,external_value,external_url FROM music_external_ids WHERE entity_type='release' AND entity_id=? ORDER BY source", (int(release_id),)
            )]
            result["metrics"] = [dict(row) for row in connection.execute(
                "SELECT source,captured_at,rating,rating_display,rating_count,rating_count_display,review_count,review_count_display,ranking_text "
                "FROM music_release_metric_snapshots WHERE release_id=? ORDER BY captured_at DESC,id DESC LIMIT 25", (int(release_id),)
            )]
            result["rankings"] = [dict(row) for row in connection.execute(
                "SELECT rk.id,rk.name,rk.kind,re.position,rs.captured_at FROM music_ranking_entries re "
                "JOIN music_ranking_snapshots rs ON rs.id=re.snapshot_id JOIN music_rankings rk ON rk.id=rs.ranking_id "
                "WHERE re.release_id=? AND rs.is_current=1 ORDER BY rk.kind,re.position", (int(release_id),)
            )]
            result["lists"] = [dict(row) for row in connection.execute(
                "SELECT l.id,l.name,le.position,le.note FROM music_list_entries le JOIN music_lists l ON l.id=le.list_id WHERE le.release_id=?", (int(release_id),)
            )]
            result["legacyLinks"] = [dict(row) for row in connection.execute(
                "SELECT ll.legacy_module,ll.legacy_entity_type,ll.legacy_entity_id,ll.match_method,ll.confidence,"
                "ls.planned_date,ls.listened,ls.rating,ls.minutes,ls.description,ls.rym_rating,"
                "ls.rym_rating_ignored,ls.community_rating,ls.community_votes,ls.community_source,"
                "ls.community_url,ls.community_checked_at,ls.source_rank,ls.source_updated_at "
                "FROM music_legacy_links ll LEFT JOIN music_legacy_release_state ls ON ls.legacy_link_id=ll.id "
                "WHERE ll.music_release_id=? ORDER BY ll.legacy_module,ll.legacy_entity_id", (int(release_id),)
            )]
        return {"ok": True, "release": result}

    def set_rating(self, release_id, rating):
        value = float(rating)
        if value < 0.5 or value > 5 or round(value * 2) != value * 2:
            raise MusicError("Ocena musi mieć wartość 0,5–5,0 co 0,5", code="invalid_rating")
        self.initialize()
        now = utc_now()
        with self._connect() as connection:
            if not connection.execute("SELECT 1 FROM music_releases WHERE id=?", (int(release_id),)).fetchone():
                raise MusicError("Album nie istnieje", status=404, code="release_not_found")
            connection.execute(
                "INSERT INTO music_user_ratings(release_id,rating,rated_at,updated_at) VALUES(?,?,?,?) "
                "ON CONFLICT(release_id) DO UPDATE SET rating=excluded.rating,updated_at=excluded.updated_at",
                (int(release_id), value, now, now),
            )
        return {"ok": True, "releaseId": int(release_id), "rating": value}

    def genres(self, filters=None):
        self.initialize()
        filters = filters or {}
        q = normalize_text(filters.get("q"))
        limit = max(1, min(int(filters.get("limit") or 100), 500))
        offset = max(0, int(filters.get("offset") or 0))
        where = "WHERE g.normalized_name LIKE ?" if q else ""
        values = [f"%{q}%"] if q else []
        sql = f"""SELECT g.*,
          (SELECT COUNT(*) FROM music_release_genres rg WHERE rg.genre_id=g.id) AS release_count,
          (SELECT COUNT(*) FROM music_genre_relations rel WHERE rel.parent_genre_id=g.id) AS child_count,
          (SELECT COUNT(*) FROM music_genre_relations rel WHERE rel.child_genre_id=g.id) AS parent_count
          FROM music_genres g {where} ORDER BY g.normalized_name LIMIT ? OFFSET ?"""
        with self._connect() as connection:
            total = int(connection.execute(f"SELECT COUNT(*) FROM music_genres g {where}", values).fetchone()[0])
            rows = [dict(row) for row in connection.execute(sql, (*values, limit, offset))]
        return {"ok": True, "rows": rows, "total": total, "limit": limit, "offset": offset}

    def genre_tree(self):
        self.initialize()
        with self._connect() as connection:
            genres = [dict(row) for row in connection.execute("""
                SELECT g.*,
                  (SELECT COUNT(*) FROM music_release_genres rg WHERE rg.genre_id=g.id) AS release_count,
                  (SELECT COUNT(*) FROM music_genre_relations rel WHERE rel.parent_genre_id=g.id) AS child_count,
                  (SELECT COUNT(*) FROM music_genre_relations rel WHERE rel.child_genre_id=g.id) AS parent_count
                FROM music_genres g ORDER BY g.normalized_name
            """)]
            relations = [dict(row) for row in connection.execute(
                "SELECT parent_genre_id AS parentId,child_genre_id AS childId "
                "FROM music_genre_relations ORDER BY parent_genre_id,child_genre_id"
            )]
        return {"ok": True, "genres": genres, "relations": relations, "total": len(genres)}

    def decorate_history_media(self, payload):
        """Use canonical local artwork in Last.fm history and artist summaries."""
        if not isinstance(payload, dict):
            return payload
        self.initialize()
        album_media = {}
        artist_media = {}
        with self._connect() as connection:
            for row in connection.execute(
                "SELECT normalized_artist_credit,normalized_title,cover_local,cover_remote "
                "FROM music_releases WHERE COALESCE(cover_local,cover_remote) IS NOT NULL "
                "ORDER BY CASE WHEN COALESCE(cover_local,'')<>'' THEN 0 ELSE 1 END,id"
            ):
                media = row["cover_local"] or row["cover_remote"]
                album_media.setdefault((row["normalized_artist_credit"], row["normalized_title"]), media)
            for row in connection.execute("""SELECT a.normalized_name,m.value_json FROM music_artists a
                JOIN music_metadata_values m ON m.entity_type='artist' AND m.entity_id=a.id
                WHERE m.field_name='image_url' ORDER BY CASE m.provider WHEN 'wikimedia' THEN 0 ELSE 1 END"""):
                artist_media.setdefault(row["normalized_name"], json.loads(row["value_json"]))

        for row in payload.get("topAlbums") or []:
            row["cover"] = album_media.get((normalize_text(row.get("artist")), normalize_text(row.get("album")))) or row.get("cover")
        for row in payload.get("rows") or []:
            row["cover"] = album_media.get((normalize_text(row.get("artist")), normalize_text(row.get("album")))) or row.get("cover")
            row["artistImage"] = artist_media.get(normalize_text(row.get("artist")))
        for row in payload.get("topArtists") or []:
            row["image"] = artist_media.get(normalize_text(row.get("artist")))
        return payload

    def genre_detail(self, genre_id):
        self.initialize()
        with self._connect() as connection:
            genre = connection.execute("SELECT * FROM music_genres WHERE id=?", (int(genre_id),)).fetchone()
            if not genre:
                raise MusicError("Gatunek nie istnieje", status=404, code="genre_not_found")
            result = dict(genre)
            result["parents"] = [dict(row) for row in connection.execute(
                "SELECT g.id,g.name,g.slug FROM music_genre_relations rel JOIN music_genres g ON g.id=rel.parent_genre_id WHERE rel.child_genre_id=? ORDER BY g.name", (int(genre_id),)
            )]
            result["children"] = [dict(row) for row in connection.execute(
                "SELECT g.id,g.name,g.slug,g.description FROM music_genre_relations rel JOIN music_genres g ON g.id=rel.child_genre_id WHERE rel.parent_genre_id=? ORDER BY g.name", (int(genre_id),)
            )]
            result["rankings"] = [dict(row) for row in connection.execute(
                "SELECT id,name,kind,source FROM music_rankings WHERE genre_id=? ORDER BY kind,name", (int(genre_id),)
            )]
        releases = self.list_releases({"genre": int(genre_id), "limit": 100})
        result["releases"] = releases["rows"]
        result["releaseCount"] = releases["total"]
        return {"ok": True, "genre": result}

    def rankings(self):
        self.initialize()
        with self._connect() as connection:
            rows = connection.execute("""
                SELECT rk.*,g.name AS genre_name,
                  (SELECT rs.id FROM music_ranking_snapshots rs WHERE rs.ranking_id=rk.id ORDER BY rs.is_current DESC,rs.captured_at DESC,rs.id DESC LIMIT 1) AS snapshot_id,
                  (SELECT rs.captured_at FROM music_ranking_snapshots rs WHERE rs.ranking_id=rk.id ORDER BY rs.is_current DESC,rs.captured_at DESC,rs.id DESC LIMIT 1) AS latest_snapshot_at,
                  (SELECT COUNT(*) FROM music_ranking_entries re JOIN music_ranking_snapshots rs ON rs.id=re.snapshot_id WHERE rs.ranking_id=rk.id AND rs.is_current=1) AS entry_count,
                  (SELECT COUNT(*) FROM music_ranking_snapshots rs WHERE rs.ranking_id=rk.id) AS snapshot_count
                FROM music_rankings rk LEFT JOIN music_genres g ON g.id=rk.genre_id ORDER BY rk.kind,rk.updated_at DESC
            """).fetchall()
        return {"ok": True, "rows": [dict(row) for row in rows]}

    def artist_ranking(self, *, min_ratings=3, limit=100, offset=0, sort="weighted", period=None):
        """Rank RYM artist identities with BM365's three-album prior."""
        self.initialize()
        minimum = max(1, min(int(min_ratings), 100))
        limit = max(1, min(int(limit), 200))
        offset = max(0, int(offset))
        if sort not in {"weighted", "average"}:
            raise MusicError("Nieznana kolejność rankingu artystów", code="invalid_artist_sort")
        identities = defaultdict(set)
        names = defaultdict(Counter)
        aliases = defaultdict(set)
        year_clause, year_values = self._year_predicate(period or {})
        rating_sql = """
            SELECT r.id, COALESCE(ur.rating, (
              SELECT ls.rating FROM music_legacy_release_state ls
              JOIN music_legacy_links ll ON ll.id=ls.legacy_link_id
              WHERE ll.music_release_id=r.id AND ls.rating IS NOT NULL
              ORDER BY COALESCE(ls.source_updated_at,ls.observed_at) DESC LIMIT 1
            )) AS rating
            FROM music_releases r LEFT JOIN music_user_ratings ur ON ur.release_id=r.id
            WHERE lower(r.release_type)='album'
        """ + (f" AND {year_clause}" if year_clause else "")
        with self._connect() as connection:
            ratings = {int(row["id"]): float(row["rating"]) for row in connection.execute(rating_sql, year_values)
                       if row["rating"] is not None}
            artist_images = {}
            for image in connection.execute("""SELECT a.normalized_name,m.value_json FROM music_artists a
                JOIN music_metadata_values m ON m.entity_type='artist' AND m.entity_id=a.id
                WHERE m.field_name='image_url' ORDER BY CASE m.provider WHEN 'wikimedia' THEN 0 ELSE 1 END"""):
                artist_images.setdefault(image["normalized_name"], json.loads(image["value_json"]))
            for record in connection.execute("""
                SELECT sr.entity_id,sr.payload_json FROM music_source_records sr
                JOIN music_import_batches b ON b.id=sr.batch_id
                WHERE b.page_type='RYM_COLLECTION' AND b.status='COMMITTED'
            """):
                release_id = int(record["entity_id"])
                if release_id not in ratings:
                    continue
                source = json.loads(record["payload_json"])
                for name, rym_id in zip(source.get("artists") or [], source.get("rymArtistIds") or []):
                    key = ("rym", str(rym_id)) if rym_id else ("name", normalize_text(name))
                    identities[release_id].add(key)
                    names[key][name] += 1
                    if rym_id:
                        aliases[normalize_text(name)].add(key)
            for record in connection.execute("""
                SELECT ra.release_id,a.name FROM music_release_artists ra
                JOIN music_artists a ON a.id=ra.artist_id
                WHERE ra.credit_role='PRIMARY'
            """):
                release_id = int(record["release_id"])
                if release_id not in ratings or release_id in identities:
                    continue
                name = record["name"]
                options = aliases.get(normalize_text(name), set())
                key = next(iter(options)) if len(options) == 1 else ("name", normalize_text(name))
                identities[release_id].add(key)
                names[key][name] += 1
        scores = defaultdict(dict)
        for release_id, keys in identities.items():
            for key in keys:
                scores[key][release_id] = ratings[release_id]
        global_average = sum(ratings.values()) / len(ratings) if ratings else 0.0
        prior = 3  # Same prior as ARTIST_WEIGHT_PRIOR in js/bm365-page-v2.js.
        rows = []
        for key, release_ratings in scores.items():
            if len(release_ratings) < minimum:
                continue
            values = list(release_ratings.values())
            label = names[key].most_common(1)[0][0]
            average = sum(values) / len(values)
            weighted = (sum(values) + global_average * prior) / (len(values) + prior)
            rows.append({"id": f"{key[0]}:{key[1]}", "name": label,
                         "image": artist_images.get(normalize_text(label)),
                         "rated_count": len(values), "average_rating": round(average, 3),
                         "weighted_rating": round(weighted, 3),
                         "five_star_count": sum(value == 5 for value in values),
                         "release_ids": sorted(release_ratings),
                         "_average_sort": average, "_weighted_sort": weighted})
        primary = "_weighted_sort" if sort == "weighted" else "_average_sort"
        secondary = "_average_sort" if sort == "weighted" else "_weighted_sort"
        rows.sort(key=lambda row: (-row[primary], -row["rated_count"], -row[secondary], row["name"].casefold()))
        for row in rows:
            del row["_average_sort"], row["_weighted_sort"]
        return {"ok": True, "rows": rows[offset:offset + limit], "total": len(rows),
                "minRatings": minimum, "limit": limit, "offset": offset,
                "sort": sort, "globalAverage": round(global_average, 3), "weightPrior": prior}

    def ranking_detail(self, ranking_id):
        self.initialize()
        with self._connect() as connection:
            ranking = connection.execute("SELECT * FROM music_rankings WHERE id=?", (int(ranking_id),)).fetchone()
            if not ranking:
                raise MusicError("Ranking nie istnieje", status=404, code="ranking_not_found")
            snapshots = connection.execute(
                "SELECT * FROM music_ranking_snapshots WHERE ranking_id=? ORDER BY is_current DESC,captured_at DESC,id DESC LIMIT 2", (int(ranking_id),)
            ).fetchall()
            if not snapshots:
                entries = []
            else:
                current_id = int(snapshots[0]["id"])
                previous_id = int(snapshots[1]["id"]) if len(snapshots) > 1 else None
                entries = connection.execute(
                    self._release_select().replace("FROM music_releases r", "FROM music_ranking_entries re JOIN music_releases r ON r.id=re.release_id")
                    + " WHERE re.snapshot_id=? ORDER BY re.position",
                    (current_id,),
                ).fetchall()
                positions = {}
                if previous_id:
                    positions = {int(row["release_id"]): int(row["position"]) for row in connection.execute(
                        "SELECT release_id,position FROM music_ranking_entries WHERE snapshot_id=?", (previous_id,)
                    )}
                payload = []
                for item in entries:
                    data = dict(item)
                    position = int(connection.execute(
                        "SELECT position FROM music_ranking_entries WHERE snapshot_id=? AND release_id=?", (current_id, data["id"])
                    ).fetchone()[0])
                    previous = positions.get(data["id"])
                    data.update({"position": position, "previousPosition": previous, "movement": (previous - position) if previous else None})
                    payload.append(data)
                entries = payload
        return {"ok": True, "ranking": dict(ranking), "snapshots": [dict(row) for row in snapshots], "entries": entries}

    def create_personal_ranking(self, name, *, genre_id=None, include_descendants=False, filters=None):
        title = str(name or "").strip()
        if not title:
            raise MusicError("Nazwa rankingu jest wymagana", code="missing_name")
        self.initialize()
        now = utc_now()
        source_key = f"personal:{hashlib.sha256((title + now).encode()).hexdigest()[:16]}"
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO music_rankings(name,kind,source,source_key,genre_id,include_descendants,filters_json,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (title, "PERSONAL", "USER", source_key, int(genre_id) if genre_id else None, int(bool(include_descendants)), self._json(filters or {}), now, now),
            )
            ranking_id = int(cursor.lastrowid)
            connection.execute(
                "INSERT INTO music_ranking_snapshots(ranking_id,captured_at,created_at,is_current) VALUES(?,?,?,1)",
                (ranking_id, now, now),
            )
        return self.ranking_detail(ranking_id)

    def update_personal_ranking(self, ranking_id, *, action, release_id=None, position=None):
        self.initialize()
        with self._lock, self._connect() as connection:
            ranking = connection.execute("SELECT kind FROM music_rankings WHERE id=?", (int(ranking_id),)).fetchone()
            if not ranking or ranking["kind"] != "PERSONAL":
                raise MusicError("Ranking osobisty nie istnieje", status=404, code="ranking_not_found")
            snapshot = connection.execute(
                "SELECT id FROM music_ranking_snapshots WHERE ranking_id=? AND is_current=1 ORDER BY id DESC LIMIT 1", (int(ranking_id),)
            ).fetchone()
            snapshot_id = int(snapshot[0])
            ids = [int(row[0]) for row in connection.execute(
                "SELECT release_id FROM music_ranking_entries WHERE snapshot_id=? ORDER BY position", (snapshot_id,)
            )]
            release_id = int(release_id) if release_id is not None else None
            if action == "add":
                if not release_id or not connection.execute("SELECT 1 FROM music_releases WHERE id=?", (release_id,)).fetchone():
                    raise MusicError("Album nie istnieje", status=404, code="release_not_found")
                if release_id not in ids:
                    at = max(0, min(int(position or len(ids) + 1) - 1, len(ids)))
                    ids.insert(at, release_id)
            elif action == "move":
                if release_id not in ids:
                    raise MusicError("Album nie należy do rankingu", status=404, code="ranking_entry_not_found")
                ids.remove(release_id)
                at = max(0, min(int(position or 1) - 1, len(ids)))
                ids.insert(at, release_id)
            elif action == "remove":
                if release_id in ids:
                    ids.remove(release_id)
            else:
                raise MusicError("Nieznana operacja rankingu", code="invalid_ranking_action")
            connection.execute("DELETE FROM music_ranking_entries WHERE snapshot_id=?", (snapshot_id,))
            connection.executemany(
                "INSERT INTO music_ranking_entries(snapshot_id,release_id,position,source_position,created_at) VALUES(?,?,?,?,?)",
                [(snapshot_id, item, index, None, utc_now()) for index, item in enumerate(ids, 1)],
            )
            connection.execute("UPDATE music_rankings SET updated_at=? WHERE id=?", (utc_now(), int(ranking_id)))
        return self.ranking_detail(ranking_id)

    def lists(self):
        self.initialize()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT l.*,COUNT(le.release_id) AS entry_count FROM music_lists l LEFT JOIN music_list_entries le ON le.list_id=l.id GROUP BY l.id ORDER BY l.updated_at DESC"
            ).fetchall()
        return {"ok": True, "rows": [dict(row) for row in rows]}

    def create_list(self, name, description=None):
        title = str(name or "").strip()
        if not title:
            raise MusicError("Nazwa listy jest wymagana", code="missing_name")
        self.initialize()
        now = utc_now()
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO music_lists(name,description,created_at,updated_at) VALUES(?,?,?,?)", (title, description, now, now)
            )
        return {"ok": True, "id": int(cursor.lastrowid), "name": title}

    def update_list_entry(self, list_id, *, action, release_id, note=None):
        self.initialize()
        with self._connect() as connection:
            if action == "remove":
                connection.execute("DELETE FROM music_list_entries WHERE list_id=? AND release_id=?", (int(list_id), int(release_id)))
            elif action == "add":
                position = int(connection.execute("SELECT COALESCE(MAX(position),0)+1 FROM music_list_entries WHERE list_id=?", (int(list_id),)).fetchone()[0])
                connection.execute(
                    "INSERT INTO music_list_entries(list_id,release_id,position,note,added_at) VALUES(?,?,?,?,?) "
                    "ON CONFLICT(list_id,release_id) DO UPDATE SET note=excluded.note",
                    (int(list_id), int(release_id), position, note, utc_now()),
                )
            else:
                raise MusicError("Nieznana operacja listy", code="invalid_list_action")
            connection.execute("UPDATE music_lists SET updated_at=? WHERE id=?", (utc_now(), int(list_id)))
        return {"ok": True}

    def search(self, query, limit=8):
        self.initialize()
        q = normalize_text(query)
        if not q:
            return {"ok": True, "artists": [], "releases": [], "genres": [], "rankings": [], "lists": []}
        pattern = f"%{q}%"
        limit = max(1, min(int(limit), 25))
        with self._connect() as connection:
            artists = [dict(row) for row in connection.execute(
                "SELECT id,name FROM music_artists WHERE normalized_name LIKE ? ORDER BY normalized_name LIMIT ?", (pattern, limit)
            )]
            releases = [dict(row) for row in connection.execute(
                "SELECT id,title,artist_credit,release_year,cover_remote,cover_local FROM music_releases WHERE normalized_title LIKE ? OR normalized_artist_credit LIKE ? "
                "ORDER BY normalized_artist_credit,normalized_title LIMIT ?", (pattern, pattern, limit)
            )]
            genres = [dict(row) for row in connection.execute(
                "SELECT id,name,slug FROM music_genres WHERE normalized_name LIKE ? ORDER BY normalized_name LIMIT ?", (pattern, limit)
            )]
            rankings = [dict(row) for row in connection.execute(
                "SELECT id,name,kind,source FROM music_rankings WHERE lower(name) LIKE ? ORDER BY updated_at DESC LIMIT ?", (pattern, limit)
            )]
            lists = [dict(row) for row in connection.execute(
                "SELECT id,name,description FROM music_lists WHERE lower(name) LIKE ? ORDER BY updated_at DESC LIMIT ?", (pattern, limit)
            )]
        return {"ok": True, "artists": artists, "releases": releases, "genres": genres, "rankings": rankings, "lists": lists}

    def overview(self):
        self.initialize()
        with self._connect() as connection:
            stats = {
                "releases": int(connection.execute("SELECT COUNT(*) FROM music_releases").fetchone()[0]),
                "artists": int(connection.execute("SELECT COUNT(*) FROM music_artists").fetchone()[0]),
                "genres": int(connection.execute("SELECT COUNT(*) FROM music_genres").fetchone()[0]),
                "ratings": int(connection.execute(
                    "SELECT COUNT(*) FROM music_releases r WHERE EXISTS("
                    "SELECT 1 FROM music_user_ratings ur WHERE ur.release_id=r.id) OR EXISTS("
                    "SELECT 1 FROM music_legacy_links ll JOIN music_legacy_release_state ls ON ls.legacy_link_id=ll.id "
                    "WHERE ll.music_release_id=r.id AND ls.rating IS NOT NULL)"
                ).fetchone()[0]),
            }
            imports = [dict(row) for row in connection.execute(
                "SELECT id,title,page_type,status,parsed_count,new_count,matched_count,ambiguous_count,imported_at,committed_at FROM music_import_batches ORDER BY id DESC LIMIT 6"
            )]
        rankings = self.rankings()["rows"][:6]
        return {"ok": True, "stats": stats, "projects": project_summaries(), "recentImports": imports, "recentRankings": rankings}


MUSIC_STORE = MusicStore()
