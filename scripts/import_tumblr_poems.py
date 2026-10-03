"""Import authored poems from a public Tumblr blog into the local journal.

The default mode is read-only. Pass --apply to create a consistent SQLite backup
and atomically upsert the selected posts.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from journal_store import JournalStore  # noqa: E402


DEFAULT_BLOG = "https://burntashyroses.tumblr.com"
DEFAULT_DATABASE = ROOT / "data" / "journal.sqlite"
EXPECTED_POSTS_TOTAL = 127
EXPECTED_POEM_CANDIDATES = 121
POEM_TAGS = {"poem", "poems", "poetry", "poezja", "wiersz", "wiersze", "poema", "poesia"}
MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}
USER_AGENT = "cleaning-dashboard-tumblr-poem-import/1.0"
JSONP_PREFIX = re.compile(r"^\s*var\s+tumblr_api_read\s*=\s*")
LEADING_H1 = re.compile(r"^\s*<h1\b[^>]*>([\s\S]*?)</h1>\s*", re.IGNORECASE)
HTML_TAG = re.compile(r"<[^>]+>")


def request_bytes(url: str, *, max_bytes: int | None = None) -> tuple[bytes, str]:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=30) as response:
        data = response.read((max_bytes + 1) if max_bytes else -1)
        if max_bytes and len(data) > max_bytes:
            raise ValueError(f"Remote asset exceeds {max_bytes} bytes: {url}")
        return data, str(response.headers.get_content_type() or "application/octet-stream")


def fetch_batch(blog_url: str, start: int, count: int = 50) -> dict:
    query = urlencode({"start": start, "num": count})
    payload, _ = request_bytes(f"{blog_url.rstrip('/')}/api/read/json?{query}")
    source = payload.decode("utf-8-sig")
    source = JSONP_PREFIX.sub("", source, count=1).strip()
    if source.endswith(";"):
        source = source[:-1]
    return json.loads(source)


def fetch_all_posts(blog_url: str) -> tuple[list[dict], int]:
    posts: list[dict] = []
    total = None
    start = 0
    while total is None or start < total:
        batch = fetch_batch(blog_url, start)
        total = int(batch.get("posts-total") or 0)
        rows = batch.get("posts") or []
        if not rows:
            break
        posts.extend(rows)
        start += len(rows)
    unique = {str(post.get("id")): post for post in posts if post.get("id") is not None}
    return list(unique.values()), int(total or 0)


def plain_text(value) -> str:
    text = HTML_TAG.sub(" ", str(value or ""))
    return " ".join(html.unescape(text).replace("\xa0", " ").split())


def tumblr_local_iso(value) -> str:
    match = re.fullmatch(
        r"[A-Za-z]{3},\s+(\d{2})\s+([A-Za-z]{3})\s+(\d{4})\s+(\d{2}):(\d{2}):(\d{2})",
        str(value or "").strip(),
    )
    if not match or match.group(2) not in MONTHS:
        raise ValueError(f"Unsupported Tumblr local date: {value!r}")
    day, month_name, year, hour, minute, second = match.groups()
    return (
        f"{year}-{MONTHS[month_name]:02d}-{int(day):02d}"
        f"T{int(hour):02d}:{int(minute):02d}:{int(second):02d}"
    )


def published_at_utc(post: dict) -> str:
    timestamp = int(post.get("unix-timestamp"))
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def title_and_body(post: dict) -> tuple[str, str, str]:
    body = str(post.get("regular-body") or post.get("photo-caption") or "").strip()
    title = plain_text(post.get("regular-title"))
    title_source = "regular-title" if title else "none"
    if not title:
        match = LEADING_H1.match(body)
        if match:
            heading = plain_text(match.group(1))
            if heading:
                title = heading
                title_source = "leading-h1"
                body = body[match.end():].strip()
    return title[:160], body, title_source


def has_poem_tag(post: dict) -> bool:
    return bool({str(tag).strip().casefold() for tag in post.get("tags") or []} & POEM_TAGS)


def candidate_reason(post: dict) -> str | None:
    post_type = str(post.get("type") or "")
    if post_type == "regular":
        return "explicit-poem-tag" if has_poem_tag(post) else "original-regular-untagged"
    if post_type == "photo" and has_poem_tag(post):
        return "tagged-photo-poem"
    return None


def photo_data_url(post: dict) -> tuple[str, str]:
    urls = [post.get("photo-url-1280"), post.get("photo-url-500")]
    last_error = None
    for url in dict.fromkeys(str(value or "") for value in urls if value):
        try:
            data, content_type = request_bytes(url, max_bytes=2 * 1024 * 1024)
            if content_type not in {"image/jpeg", "image/png", "image/webp", "image/gif"}:
                raise ValueError(f"Unsupported Tumblr image type: {content_type}")
            return f"data:{content_type};base64,{base64.b64encode(data).decode('ascii')}", url
        except (OSError, ValueError) as exc:
            last_error = exc
    raise ValueError(f"Could not download Tumblr poem image: {last_error}")


def source_metadata(post: dict, *, blog_url: str, reason: str, title_source: str, content: str) -> dict:
    ignored = {"regular-body", "photo-caption", "like-button", "reblog-button"}
    raw_metadata = {key: value for key, value in post.items() if key not in ignored}
    local_iso = tumblr_local_iso(post.get("date"))
    return {
        "tumblr": {
            "blogUrl": blog_url.rstrip("/"),
            "postId": str(post.get("id")),
            "url": str(post.get("url-with-slug") or post.get("url") or ""),
            "publishedOriginal": str(post.get("date") or ""),
            "publishedGmtOriginal": str(post.get("date-gmt") or ""),
            "publishedLocal": local_iso,
            "publishedAtUtc": published_at_utc(post),
            "classification": reason,
            "titleSource": title_source,
            "contentSha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "rawMetadata": raw_metadata,
        }
    }


def build_payloads(posts: list[dict], blog_url: str, *, download_images: bool) -> tuple[list[dict], list[dict]]:
    payloads = []
    excluded = []
    for post in sorted(posts, key=lambda row: int(row.get("unix-timestamp") or 0)):
        reason = candidate_reason(post)
        if not reason:
            excluded.append(post)
            continue
        title, content, title_source = title_and_body(post)
        illustration = ""
        illustration_alt = ""
        downloaded_url = ""
        if post.get("type") == "photo" and download_images:
            illustration, downloaded_url = photo_data_url(post)
            illustration_alt = title or "Wiersz graficzny z Tumblra"
        metadata = source_metadata(
            post, blog_url=blog_url, reason=reason, title_source=title_source, content=content
        )
        if downloaded_url:
            metadata["tumblr"]["downloadedImageUrl"] = downloaded_url
        payloads.append({
            "title": title,
            "content": content,
            "contentFormat": "html",
            "entryDate": metadata["tumblr"]["publishedLocal"][:10],
            "entryKind": "poem",
            "tags": [str(tag) for tag in post.get("tags") or []],
            "illustration": illustration,
            "illustrationAlt": illustration_alt,
            "sourceType": "tumblr",
            "sourceExternalId": str(post.get("id")),
            "sourceMetadata": metadata,
        })
    return payloads, excluded


def backup_database(database: Path) -> Path | None:
    if not database.exists():
        return None
    backup_dir = database.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    destination = backup_dir / f"journal.pre-tumblr-{stamp}.sqlite"
    with sqlite3.connect(database) as source, sqlite3.connect(destination) as target:
        source.backup(target)
    return destination


def summary(payloads: list[dict], excluded: list[dict], total: int) -> dict:
    untagged = [row for row in payloads if row["sourceMetadata"]["tumblr"]["classification"] == "original-regular-untagged"]
    return {
        "tumblrPosts": total,
        "poemCandidates": len(payloads),
        "explicitlyTagged": len(payloads) - len(untagged),
        "untaggedRegular": len(untagged),
        "excluded": len(excluded),
        "excludedByType": {
            kind: sum(1 for post in excluded if post.get("type") == kind)
            for kind in sorted({str(post.get("type") or "unknown") for post in excluded})
        },
        "dateRange": [payloads[0]["entryDate"], payloads[-1]["entryDate"]] if payloads else [],
        "untaggedCandidates": [
            {"id": row["sourceExternalId"], "date": row["entryDate"], "title": row["title"]}
            for row in untagged
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blog-url", default=DEFAULT_BLOG)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--apply", action="store_true", help="Back up the database and apply the import")
    parser.add_argument("--allow-count-change", action="store_true")
    args = parser.parse_args()

    posts, total = fetch_all_posts(args.blog_url)
    payloads, excluded = build_payloads(posts, args.blog_url, download_images=args.apply)
    report = summary(payloads, excluded, total)
    if not args.allow_count_change and (
        total != EXPECTED_POSTS_TOTAL or len(payloads) != EXPECTED_POEM_CANDIDATES
    ):
        raise SystemExit(
            f"Tumblr changed since review: expected {EXPECTED_POSTS_TOTAL}/{EXPECTED_POEM_CANDIDATES}, "
            f"received {total}/{len(payloads)}. Re-run with --allow-count-change only after review."
        )

    if args.apply:
        database = args.database.resolve()
        backup = backup_database(database)
        store = JournalStore(database)
        imported = store.import_external_entries(payloads)
        report.update({
            "mode": "applied",
            "database": str(database),
            "backup": str(backup) if backup else None,
            "stored": len(imported),
        })
    else:
        report["mode"] = "dry-run"

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
