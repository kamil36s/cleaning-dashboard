"""Read-only adapters between Music and the protected legacy projects."""

from bm365_store import BM365_STORE
from brutal_assault_store import BRUTAL_ASSAULT_2027_STORE
from rym_polish_black_metal_store import RYM_POLISH_BLACK_METAL_STORE

from music_importers import normalize_text


PROJECTS = (
    ("black_metal_365", "Black Metal 365", "./bm365.html"),
    ("brutal_assault_2027", "Brutal Assault 2027", "./brutal-assault-2027.html"),
    ("rym_polish_bm", "Top 100 RYM Polish BM", "./rym-polish-black-metal-top-100.html"),
)


def _rows():
    yield "black_metal_365", BM365_STORE.get_albums()
    yield "brutal_assault_2027", BRUTAL_ASSAULT_2027_STORE.list()
    yield "rym_polish_bm", RYM_POLISH_BLACK_METAL_STORE.list()


def legacy_catalog_rows():
    """Return copies of legacy album rows without mutating their stores."""
    return [
        {"legacyModule": module, **dict(row)}
        for module, rows in _rows()
        for row in rows
    ]


def find_legacy_matches(artist, title, year=None):
    artist_key = normalize_text(artist)
    title_key = normalize_text(title)
    matches = []
    for module, rows in _rows():
        for row in rows:
            if normalize_text(row.get("artist")) != artist_key:
                continue
            if normalize_text(row.get("album")) != title_key:
                continue
            row_year = row.get("releaseYear", row.get("year"))
            year_matches = not year or not row_year or str(row_year) == str(year)
            if not year_matches:
                continue
            matches.append({
                "legacyModule": module,
                "legacyEntityType": "album",
                "legacyEntityId": str(row.get("rowId")),
                "artist": row.get("artist"),
                "title": row.get("album"),
                "year": int(row_year) if str(row_year or "").isdigit() else None,
                "rating": row.get("rating"),
                "confidence": 1.0 if year and row_year and str(row_year) == str(year) else 0.96,
            })
    return matches


def project_summaries():
    by_key = {key: {"key": key, "title": title, "href": href} for key, title, href in PROJECTS}
    bm = BM365_STORE.get_summary()
    stats = bm.get("stats") or {}
    by_key["black_metal_365"].update({
        "total": int(stats.get("total") or 0),
        "done": int(stats.get("done") or 0),
        "averageRating": stats.get("avgRating"),
        "next": next(
            (
                {"artist": row.get("artist"), "title": row.get("album"), "date": row.get("date")}
                for row in bm.get("rows") or []
                if str(row.get("listened") or "").upper() not in {"TAK", "YES", "TRUE", "1"}
            ),
            None,
        ),
    })
    for module, store in (
        ("brutal_assault_2027", BRUTAL_ASSAULT_2027_STORE),
        ("rym_polish_bm", RYM_POLISH_BLACK_METAL_STORE),
    ):
        rows = store.list()
        done = [row for row in rows if str(row.get("listened") or "").upper() in {"TAK", "YES", "TRUE", "1"}]
        ratings = [float(row["rating"]) for row in rows if row.get("rating") is not None]
        next_row = next((row for row in rows if row not in done), None)
        by_key[module].update({
            "total": len(rows),
            "done": len(done),
            "averageRating": sum(ratings) / len(ratings) if ratings else None,
            "next": (
                {"artist": next_row.get("artist"), "title": next_row.get("album"), "date": next_row.get("date")}
                if next_row else None
            ),
        })
    return [by_key[key] for key, _title, _href in PROJECTS]
