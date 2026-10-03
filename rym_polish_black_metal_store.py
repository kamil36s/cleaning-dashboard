import json
import sqlite3
import threading
from datetime import date, timedelta
from pathlib import Path

from brutal_assault_store import BrutalAssaultStore


class RymPolishBlackMetalStore(BrutalAssaultStore):
    """Separate rating state for the fixed RYM Polish black-metal Top 100."""

    def __init__(self, db_path=None, seed_path=None):
        root = Path(__file__).resolve().parent
        super().__init__(db_path or root / "data" / "rym-polish-black-metal-top-100.sqlite")
        self.seed_path = Path(
            seed_path or root / "data" / "rym-polish-black-metal-top-100.json"
        )
        self._seed_lock = threading.Lock()
        self._seed_initialized = False

    def initialize(self):
        super().initialize()
        if self._seed_initialized:
            return
        with self._seed_lock:
            if self._seed_initialized:
                return
            with self._connect() as connection:
                columns = {
                    row["name"]
                    for row in connection.execute("PRAGMA table_info(albums)").fetchall()
                }
                if "source_rank" not in columns:
                    connection.execute("ALTER TABLE albums ADD COLUMN source_rank INTEGER")
                connection.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_rym_polish_bm_source_rank "
                    "ON albums(source_rank) WHERE source_rank IS NOT NULL"
                )
                count = connection.execute("SELECT COUNT(*) FROM albums").fetchone()[0]
                if count == 0:
                    self._seed(connection)
            self._seed_initialized = True

    def _seed(self, connection):
        payload = json.loads(self.seed_path.read_text(encoding="utf-8"))
        albums = payload.get("albums") if isinstance(payload, dict) else None
        if not isinstance(albums, list) or len(albums) != 100:
            raise ValueError("RYM Polish black-metal seed must contain exactly 100 albums")

        now = "2000-01-01T00:00:00+00:00"
        order_start = date(2000, 1, 1)
        for expected_rank, album in enumerate(albums, 1):
            source_rank = int(album.get("rank") or 0)
            if source_rank != expected_rank:
                raise ValueError("RYM Polish black-metal ranks must be consecutive from 1 to 100")
            connection.execute(
                """
                INSERT INTO albums (
                    artist, album, release_year, planned_date, listened, rating, minutes,
                    community_rating, community_votes, community_source, community_url,
                    community_checked_at, description, created_at, updated_at, source_rank
                ) VALUES (?, ?, ?, ?, 0, NULL, NULL, ?, ?, ?, ?, ?, '', ?, ?, ?)
                """,
                (
                    str(album.get("artist") or "").strip(),
                    str(album.get("album") or "").strip(),
                    album.get("year"),
                    (order_start + timedelta(days=source_rank - 1)).isoformat(),
                    album.get("rymRating"),
                    album.get("rymVotes"),
                    "Rate Your Music",
                    str(album.get("rymUrl") or "").strip(),
                    now,
                    now,
                    now,
                    source_rank,
                ),
            )

    @staticmethod
    def _row_payload(row):
        payload = BrutalAssaultStore._row_payload(row)
        payload["sourceRank"] = row["source_rank"]
        return payload

    def list(self):
        self.initialize()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM albums ORDER BY source_rank ASC, id ASC"
            ).fetchall()
        return [self._row_payload(row) for row in rows]


RYM_POLISH_BLACK_METAL_STORE = RymPolishBlackMetalStore()
