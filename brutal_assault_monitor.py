"""Official Brutal Assault lineup/news monitor, independent of the album store."""

import json
import os
import re
import tempfile
import threading
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path


BASE = "https://brutalassault.cz"
LINEUP_URL = f"{BASE}/en/line-up"
NEWS_URL = f"{BASE}/en/c/news"
CHECK_SECONDS = 6 * 60 * 60
NEWS_MAX_AGE_DAYS = 30
USER_AGENT = "cleaning-dashboard/1.0 (local personal dashboard)"


class _Node:
    def __init__(self, tag="", attrs=()):
        self.tag = tag
        self.attrs = dict(attrs)
        self.children = []
        self.text = ""

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()

    def content(self):
        return self.text + " ".join(child.content() for child in self.children)

    def has_class(self, name):
        return name in self.attrs.get("class", "").split()


class _Tree(HTMLParser):
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = _Node()
        self.stack = [self.root]
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data):
        self.stack[-1].text += data + " "


def _clean(value):
    return " ".join(str(value or "").split())


def _official_url(href, pattern):
    url = urllib.parse.urljoin(BASE, href or "")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.netloc != "brutalassault.cz":
        return None
    if not re.fullmatch(pattern, parsed.path):
        return None
    return f"{BASE}{parsed.path}"


def parse_lineup(html):
    tree = _Tree(html).root
    headings = [node.content() for node in tree.walk() if node.tag in {"h1", "h2", "h3"}]
    match = next((re.search(r"\b(\d{1,3})\s*%\s*CONFIRMED\b", heading, re.I) for heading in headings if re.search(r"\b\d{1,3}\s*%\s*CONFIRMED\b", heading, re.I)), None)
    if not match:
        raise ValueError("Official lineup percentage heading is missing")
    percent = int(match.group(1))
    if not 0 < percent <= 100:
        raise ValueError("Invalid official lineup percentage")
    bands = {}
    for node in tree.walk():
        if node.tag != "a":
            continue
        url = _official_url(node.attrs.get("href"), r"/en/band/[^/]+")
        if not url:
            continue
        titles = [_clean(child.content()) for child in node.walk() if child.has_class("band_lineup_title")]
        name = next((title for title in titles if title), "")
        if name:
            slug = url.rsplit("/", 1)[-1]
            bands[slug] = {"name": name, "slug": slug, "url": url}
    if not bands:
        raise ValueError("Official lineup contains no band links with titles")
    return {"confirmedPercent": percent, "bands": list(bands.values())}


def parse_news(html):
    tree = _Tree(html).root
    articles = {}
    for preview in (node for node in tree.walk() if node.has_class("article_preview")):
        links = []
        for node in preview.walk():
            if node.tag == "a":
                url = _official_url(node.attrs.get("href"), r"/en/a/\d+/[^/]+")
                if url:
                    links.append(url)
        if not links:
            continue
        url = links[0]
        article_id = url.split("/")[5]
        titles = [_clean(node.content()) for node in preview.walk() if node.has_class("article_title")]
        dates = [_clean(node.content()) for node in preview.walk() if node.has_class("article_date")]
        if not titles or not titles[0] or not dates or not re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", dates[0]):
            raise ValueError("Official news article is missing title or date")
        excerpts = [_clean(node.content()) for node in preview.walk() if node.tag == "p" and not any(child.has_class("article_date") for child in node.walk())]
        articles[article_id] = {"id": article_id, "title": titles[0], "date": dates[0], "url": url, "excerpt": next((s for s in excerpts if s), "")[:500]}
    if not articles:
        raise ValueError("Official news page contains no articles")
    return list(articles.values())


def estimate(count, percent):
    if not count or not percent:
        return None
    total = round(count * 100 / percent)
    lower = round(count * 100 / min(100, percent + 0.5))
    upper = round(count * 100 / max(0.5, percent - 0.5))
    return {"estimatedTotal": total, "estimatedTotalRange": [lower, upper], "estimatedRemaining": total - count, "estimatedRemainingRange": [lower - count, upper - count]}


def lineup_difference(old, new):
    before = {band["slug"]: band for band in old}
    after = {band["slug"]: band for band in new}
    return ([band for slug, band in after.items() if slug not in before],
            [band for slug, band in before.items() if slug not in after])


def recent_news(article, today=None):
    today = today or datetime.now(timezone.utc).date()
    try:
        published = datetime.strptime(article["date"], "%d.%m.%Y").date()
    except (KeyError, TypeError, ValueError):
        return False
    return 0 <= (today - published).days <= NEWS_MAX_AGE_DAYS


def recent_event(event, today):
    if event.get("type") != "news":
        return True
    if event.get("newsDate"):
        return recent_news({"date": event["newsDate"]}, today)
    try:
        return 0 <= (today - date.fromisoformat(event["detectedAt"][:10])).days <= NEWS_MAX_AGE_DAYS
    except (KeyError, TypeError, ValueError):
        return False


class BrutalAssaultMonitor:
    def __init__(self, path=None, *, fetch=None, logger=None):
        self.path = Path(path or Path(__file__).resolve().parent / "data" / "brutal-assault-2027-monitor.json")
        self.fetch = fetch or self._fetch
        self.logger = logger or (lambda message: None)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None

    @staticmethod
    def _fetch(url):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.read(2_000_000).decode("utf-8")

    def _read(self):
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}

    def _write(self, state):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temp_path = tempfile.mkstemp(prefix=".ba-monitor-", suffix=".json", dir=self.path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(state, output, ensure_ascii=False, indent=2)
            os.replace(temp_path, self.path)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def snapshot(self):
        with self._lock:
            state = self._read()
        lineup = state.get("lineup") or {}
        bands = lineup.get("bands") or []
        percent = lineup.get("confirmedPercent")
        today = datetime.now(timezone.utc).date()
        return {
            "source": LINEUP_URL,
            "lastCheckAt": state.get("lastCheckAt"),
            "lastSuccessfulCheckAt": state.get("lastSuccessfulCheckAt"),
            "lastError": state.get("lastError"),
            "status": "error" if state.get("lastError") else ("ok" if lineup else "pending"),
            "confirmedPercent": percent,
            "announcedCount": len(bands) if lineup else None,
            "bands": bands,
            "newBands": state.get("newBands") or [],
            "latestNews": [article for article in state.get("latestNews") or [] if recent_news(article, today)][:5],
            "events": [event for event in state.get("events") or [] if recent_event(event, today)][:50],
            **(estimate(len(bands), percent) or {}),
        }

    def check(self):
        with self._lock:
            state = self._read()
            now_dt = datetime.now(timezone.utc)
            now = now_dt.isoformat()
            today = now_dt.date()
            state["lastCheckAt"] = now
            state["knownNews"] = {
                article_id: article for article_id, article in (state.get("knownNews") or {}).items()
                if recent_news(article, today)
            }
            state["latestNews"] = [
                article for article in state.get("latestNews") or [] if recent_news(article, today)
            ]
            state["events"] = [
                event for event in state.get("events") or [] if recent_event(event, today)
            ][:50]
            errors = []
            successful = False
            try:
                lineup = parse_lineup(self.fetch(LINEUP_URL))
                old = state.get("lineup")
                if old and len(old.get("bands") or []) >= 20 and len(lineup["bands"]) < len(old["bands"]) // 2:
                    raise ValueError("Official lineup shrank unexpectedly; keeping the previous snapshot")
                added, removed = lineup_difference(old["bands"], lineup["bands"]) if old else ([], [])
                if old and (added or removed or old["confirmedPercent"] != lineup["confirmedPercent"]):
                    event = {"id": f"ba-lineup:{now}", "type": "lineup_change", "detectedAt": now,
                             "officialPercentBefore": old["confirmedPercent"], "officialPercentAfter": lineup["confirmedPercent"],
                             "addedBands": added, "removedBands": removed}
                    state["events"] = ([event] + state.get("events", []))[:50]
                state["lineup"] = lineup
                if old and (added or removed or old["confirmedPercent"] != lineup["confirmedPercent"]):
                    state["newBands"] = added
                successful = True
            except Exception as exc:
                errors.append(f"Lineup: {exc}")
                self.logger(f"BA2027 lineup monitor failed: {exc}")
            try:
                news = parse_news(self.fetch(NEWS_URL))
                fresh_news = [article for article in news if recent_news(article, today)]
                seen = set(state.get("seenNewsIds") or [])
                known_news = state.get("knownNews") or {}
                if "seenNewsIds" in state:
                    events = [{"id": f"ba-news:{article['id']}", "type": "news", "detectedAt": now,
                               "articleId": article["id"], "title": article["title"], "url": article["url"],
                               "newsDate": article["date"]}
                              for article in fresh_news if article["id"] not in seen]
                    state["events"] = (events + state.get("events", []))[:50]
                state["seenNewsIds"] = sorted(seen.union(article["id"] for article in news))
                for article in fresh_news:
                    known_news.setdefault(article["id"], {**article, "firstSeenAt": now})
                state["knownNews"] = known_news
                state["latestNews"] = [known_news[article["id"]] for article in fresh_news]
                successful = True
            except Exception as exc:
                errors.append(f"News: {exc}")
                self.logger(f"BA2027 news monitor failed: {exc}")
            state["lastError"] = "; ".join(errors) or None
            if successful:
                state["lastSuccessfulCheckAt"] = now
            self._write(state)
        return self.snapshot()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="ba2027-monitor", daemon=True)
        self._thread.start()

    def _run(self):
        while not self._stop.is_set():
            try:
                self.check()
            except Exception as exc:
                self.logger(f"BA2027 monitor cycle failed: {exc}")
            self._stop.wait(CHECK_SECONDS)

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)
