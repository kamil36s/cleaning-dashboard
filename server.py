import csv
import json
import os
import re
import sqlite3
import time
import urllib.parse
import urllib.request
from datetime import date, datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "watchlist.sqlite"
SEED_JS = ROOT / "js" / "oscars-seed.js"
SEED_JS_2025 = ROOT / "js" / "oscars-seed-2025.js"
SEED_JS_2024 = ROOT / "js" / "oscars-seed-2024.js"
SEED_JS_2023 = ROOT / "js" / "oscars-seed-2023.js"
SEED_JS_2022 = ROOT / "js" / "oscars-seed-2022.js"
SEED_JS_1929 = ROOT / "js" / "oscars-seed-1929.js"
LOG_PATH = ROOT / "server.log"
LAST_UPDATE = {"empty": True}
ENV_FILES = [ROOT / ".env.development", ROOT / ".env.production"]
TMDB_CONFIG = {}
WIKI_UA = "cleaning-dashboard/1.0"
POSTERS_DIR = ROOT / "public" / "posters"
POSTER_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
OSCARS_DATA_DIR = ROOT / "data" / "oscars"
WINNERS_CSV_URL = "https://huggingface.co/datasets/ceyyyh/oscar_award_winners/resolve/main/oscars_1929_2025.csv"
WINNERS_CACHE = OSCARS_DATA_DIR / "oscars_1929_2025.csv"
WINNERS_CACHE_TTL = 60 * 60 * 24 * 30


def enable_ansi():
    if os.name != "nt":
        return True
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)) == 0:
            return False
        mode.value |= 0x0004  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        if kernel32.SetConsoleMode(handle, mode) == 0:
            return False
        return True
    except Exception:
        return False


ANSI_ENABLED = enable_ansi()


def color(txt: str, code: str) -> str:
    if not ANSI_ENABLED:
        return txt
    return f"\x1b[{code}m{txt}\x1b[0m"


def fmt_time(short: bool = True) -> str:
    return datetime.now().strftime("%H:%M:%S" if short else "%Y-%m-%d %H:%M:%S")


def normalize_poster_key(value: str) -> str:
    if not value:
        return ""
    s = str(value).lower()
    s = s.replace("&", "and")
    s = s.replace("’", "").replace("'", "").replace("`", "")
    s = re.sub(r"[^a-z0-9]+", "", s)
    return s


def build_local_poster_index():
    if not POSTERS_DIR.exists():
        return {}, []
    exact = {}
    fuzzy = []
    try:
        for item in POSTERS_DIR.iterdir():
            if not item.is_file():
                continue
            if item.suffix.lower() not in POSTER_EXTS:
                continue
            key = normalize_poster_key(item.stem)
            if not key:
                continue
            if key not in exact:
                exact[key] = item.name
            fuzzy.append((key, item.name))
    except Exception:
        return {}, []
    return exact, fuzzy


def local_poster_for_title(title: str, index):
    if not title:
        return None
    exact, fuzzy = index
    if not exact and not fuzzy:
        return None
    key = normalize_poster_key(title)
    if not key:
        return None
    if key in exact:
        return exact[key]
    best = None
    for fkey, name in fuzzy:
        if key in fkey or fkey in key:
            score = abs(len(fkey) - len(key))
            if best is None or score < best[0] or (score == best[0] and len(fkey) < best[1]):
                best = (score, len(fkey), name)
    return best[2] if best else None


def local_poster_url(title: str, index):
    name = local_poster_for_title(title, index)
    if not name:
        return None
    return f"/posters/{urllib.parse.quote(name)}"

COLUMNS = [
    ("watched", "INTEGER"),
    ("watched_date", "TEXT"),
    ("title", "TEXT"),
    ("type", "TEXT"),
    ("runtime_helper", "TEXT"),
    ("runtime_helper_2", "TEXT"),
    ("runtime", "TEXT"),
    ("rating_1_10", "REAL"),
    ("director_s", "TEXT"),
    ("country", "TEXT"),
    ("nominations_number", "INTEGER"),
    ("nominated_categories", "TEXT"),
    ("won_categories", "TEXT"),
    ("wikipedia_link", "TEXT"),
    ("imdb_link", "TEXT"),
    ("where_to_watch", "TEXT"),
    ("notes", "TEXT"),
    ("wikipedia_url", "TEXT"),
    ("imdb_url", "TEXT"),
    ("poster_url", "TEXT"),
    ("poster_source", "TEXT"),
    ("oscars_year", "INTEGER"),
]

UPDATE_FIELDS = {
    "watched",
    "watched_date",
    "rating_1_10",
    "where_to_watch",
    "notes",
    "won_categories",
    "poster_url",
    "poster_source",
}


def today_iso() -> str:
    return date.today().isoformat()


def parse_year(value):
    try:
        year = int(value)
    except (TypeError, ValueError):
        return None
    return year if 1900 <= year <= 2100 else None

def log_line(msg: str, tag: str = "api", level: str = "info"):
    ts_file = fmt_time(short=False)
    line = f"[{ts_file}] [{tag}] {msg}"
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    try:
        ts_console = fmt_time(short=True)
        tag_text = f"[{tag}]"
        tag_color = "35" if tag == "api" else "36" if tag == "http" else "33"
        msg_color = {
            "info": "37",
            "success": "32",
            "warn": "33",
            "error": "31",
            "dim": "90",
        }.get(level, "37")
        out = f"{color(ts_console, '90')} {color(tag_text, tag_color)} {color(msg, msg_color)}"
        print(out, flush=True)
    except Exception:
        pass


def log_json(title: str, payload, tag: str = "api", level: str = "dim"):
    log_line(title, tag=tag, level=level)
    try:
        pretty = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    except Exception:
        pretty = str(payload)
    for line in pretty.splitlines():
        log_line(f"  {line}", tag=tag, level=level)


def set_last_update(payload):
    global LAST_UPDATE
    LAST_UPDATE = payload


def normalize_bool(val) -> int:
    if isinstance(val, bool):
        return 1 if val else 0
    if val is None:
        return 0
    s = str(val).strip().upper()
    return 1 if s in {"1", "TRUE", "YES", "TAK"} else 0


def normalize_float(val):
    if val is None or val == "":
        return None
    try:
        return float(str(val).replace(",", "."))
    except ValueError:
        return None


def normalize_int(val):
    n = normalize_float(val)
    return int(n) if n is not None else None


def normalize_date_input(val):
    if val is None:
        return None
    s = str(val).strip()
    if not s:
        return None
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return s
    m = re.match(r"^(\d{1,2})[./-](\d{1,2})[./-](\d{4})$", s)
    if not m:
        return None
    day = int(m.group(1))
    month = int(m.group(2))
    year = int(m.group(3))
    try:
        date(year, month, day)
    except ValueError:
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def load_env_files():
    for path in ENV_FILES:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            raw = line.strip()
            if not raw or raw.startswith("#") or "=" not in raw:
                continue
            key, value = raw.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def poster_providers():
    disable_tmdb = str(os.environ.get("DISABLE_TMDB", "")).strip().lower() in {"1", "true", "yes", "on"}
    tmdb = None
    if not disable_tmdb:
        tmdb = os.environ.get("TMDB_API_KEY") or os.environ.get("VITE_TMDB_API_KEY")
    omdb = os.environ.get("OMDB_API_KEY") or os.environ.get("VITE_OMDB_API_KEY")
    return tmdb, omdb


def http_get_json(url, headers=None, timeout=10):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read().decode("utf-8")
    if not data:
        return {}
    return json.loads(data)


def imdb_id_from_url(url):
    if not url:
        return None
    match = re.search(r"(tt\d{6,})", str(url))
    return match.group(1) if match else None


def get_tmdb_config(api_key):
    if not api_key:
        return None
    cached = TMDB_CONFIG.get(api_key)
    if cached:
        return cached
    params = urllib.parse.urlencode({"api_key": api_key})
    url = f"https://api.themoviedb.org/3/configuration?{params}"
    data = http_get_json(url, headers={"Accept": "application/json"})
    images = data.get("images") or {}
    base_url = images.get("secure_base_url") or images.get("base_url")
    sizes = images.get("poster_sizes") or []
    size = "w185" if "w185" in sizes else "w154" if "w154" in sizes else ("original" if sizes else None)
    if not base_url or not size:
        return None
    config = {"base_url": base_url, "size": size}
    TMDB_CONFIG[api_key] = config
    return config


def tmdb_poster(title, api_key):
    if not api_key or not title:
        return None
    config = get_tmdb_config(api_key)
    if not config:
        return None
    params = urllib.parse.urlencode({
        "api_key": api_key,
        "query": title,
        "include_adult": "false",
    })
    url = f"https://api.themoviedb.org/3/search/movie?{params}"
    data = http_get_json(url, headers={"Accept": "application/json"})
    for item in data.get("results") or []:
        poster_path = item.get("poster_path")
        if poster_path:
            return f"{config['base_url']}{config['size']}{poster_path}"
    return None


def omdb_poster(title, imdb_url, api_key):
    if not api_key or not title:
        return None
    imdb_id = imdb_id_from_url(imdb_url)
    params = {"apikey": api_key}
    if imdb_id:
        params["i"] = imdb_id
    else:
        params["t"] = title
    url = f"https://www.omdbapi.com/?{urllib.parse.urlencode(params)}"
    data = http_get_json(url, headers={"Accept": "application/json"})
    if data.get("Response") == "True":
        poster = data.get("Poster")
        if poster and poster != "N/A":
            return poster
    if imdb_id:
        return None
    params = {"apikey": api_key, "s": title}
    url = f"https://www.omdbapi.com/?{urllib.parse.urlencode(params)}"
    data = http_get_json(url, headers={"Accept": "application/json"})
    for item in data.get("Search") or []:
        poster = item.get("Poster")
        if poster and poster != "N/A":
            return poster
    return None


def wiki_poster(title):
    if not title:
        return None
    headers = {"User-Agent": WIKI_UA}
    search_params = {
        "action": "query",
        "list": "search",
        "srsearch": title,
        "format": "json",
        "srlimit": 1,
    }
    search_url = f"https://en.wikipedia.org/w/api.php?{urllib.parse.urlencode(search_params)}"
    data = http_get_json(search_url, headers=headers)
    results = (data.get("query") or {}).get("search") or []
    if not results:
        return None
    page_title = results[0].get("title")
    if not page_title:
        return None
    img_params = {
        "action": "query",
        "prop": "pageimages",
        "titles": page_title,
        "format": "json",
        "piprop": "thumbnail",
        "pithumbsize": 300,
    }
    img_url = f"https://en.wikipedia.org/w/api.php?{urllib.parse.urlencode(img_params)}"
    data = http_get_json(img_url, headers=headers)
    pages = (data.get("query") or {}).get("pages") or {}
    for page in pages.values():
        thumb = page.get("thumbnail")
        if thumb and thumb.get("source"):
            return thumb["source"]
    return None


def find_poster(item, tmdb_key, omdb_key):
    title = item.get("title")
    imdb_url = item.get("imdb_url")
    poster = tmdb_poster(title, tmdb_key) if tmdb_key else None
    if poster:
        return poster, "tmdb"
    poster = omdb_poster(title, imdb_url, omdb_key) if omdb_key else None
    if poster:
        return poster, "omdb"
    poster = wiki_poster(title)
    if poster:
        return poster, "wikipedia"
    return None, None


def clean_text(value):
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if s.upper() in {"N/A", "NONE", "NULL", "-"}:
        return None
    return s


def normalize_country_list(value):
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    aliases = {
        "united states": "USA",
        "united states of america": "USA",
        "u.s.": "USA",
        "u.s.a.": "USA",
        "us": "USA",
        "usa": "USA",
        "u s": "USA",
        "u s a": "USA",
    }
    parts = [p.strip() for p in re.split(r"[;,/]", raw) if p.strip()]
    out = []
    seen = set()
    for part in parts:
        key = re.sub(r"\s+", " ", part.lower().replace(".", " ")).strip()
        mapped = aliases.get(key, part.strip())
        if mapped and mapped not in seen:
            seen.add(mapped)
            out.append(mapped)
    return ", ".join(out) if out else None


CANONICAL_CATEGORIES = [
    "Best Picture",
    "Directing",
    "Actor in a Leading Role",
    "Actress in a Leading Role",
    "Actor in a Supporting Role",
    "Actress in a Supporting Role",
    "Writing (Original Screenplay)",
    "Writing (Adapted Screenplay)",
    "Cinematography",
    "Production Design",
    "Costume Design",
    "Film Editing",
    "Sound",
    "Visual Effects",
    "Music (Original Score)",
    "Music (Original Song)",
    "Makeup and Hairstyling",
    "Animated Feature Film",
    "Animated Short Film",
    "Documentary Feature Film",
    "Documentary Short Film",
    "International Feature Film",
    "Live Action Short Film",
    "Casting",
    "Special Award",
]

CATEGORY_ALIASES = {
    "actor": "Actor in a Leading Role",
    "actress": "Actress in a Leading Role",
    "directing (dramatic picture)": "Directing",
    "directing (comedy picture)": "Directing",
    "writing (adaptation)": "Writing (Adapted Screenplay)",
    "writing (original story)": "Writing (Original Screenplay)",
    "writing (title writing)": "Writing (Original Screenplay)",
    "outstanding picture": "Best Picture",
    "unique and artistic picture": "Best Picture",
    "engineering effects": "Visual Effects",
    "art direction": "Production Design",
}

CANONICAL_BY_KEY = {c.lower(): c for c in CANONICAL_CATEGORIES}
CANONICAL_ORDER = {c: i for i, c in enumerate(CANONICAL_CATEGORIES)}


def normalize_category(value):
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    key = " ".join(raw.lower().split())
    if key in CATEGORY_ALIASES:
        return CATEGORY_ALIASES[key]
    if key in CANONICAL_BY_KEY:
        return CANONICAL_BY_KEY[key]
    return None


def split_categories(value):
    if not value:
        return []
    parts = [p.strip() for p in str(value).split(";") if p.strip()]
    out = []
    seen = set()
    for part in parts:
        normalized = normalize_category(part) or part
        if normalized not in seen:
            seen.add(normalized)
            out.append(normalized)
    return out


def tmdb_details(title, api_key):
    if not api_key or not title:
        return {}
    params = urllib.parse.urlencode({
        "api_key": api_key,
        "query": title,
        "include_adult": "false",
    })
    url = f"https://api.themoviedb.org/3/search/movie?{params}"
    data = http_get_json(url, headers={"Accept": "application/json"})
    results = data.get("results") or []
    if not results:
        return {}
    movie_id = results[0].get("id")
    if not movie_id:
        return {}
    details_url = f"https://api.themoviedb.org/3/movie/{movie_id}?{urllib.parse.urlencode({'api_key': api_key})}"
    details = http_get_json(details_url, headers={"Accept": "application/json"})
    runtime = details.get("runtime")
    runtime_str = f"{runtime} min" if isinstance(runtime, int) and runtime > 0 else None
    countries = details.get("production_countries") or []
    country_names = [c.get("name") for c in countries if c.get("name")]
    country_str = ", ".join(country_names) if country_names else None
    out = {}
    if runtime_str:
        out["runtime"] = runtime_str
    if country_str:
        out["country"] = country_str
    return out


def omdb_details(title, imdb_url, api_key):
    if not api_key or not title:
        return {}
    imdb_id = imdb_id_from_url(imdb_url)
    params = {"apikey": api_key}
    if imdb_id:
        params["i"] = imdb_id
    else:
        params["t"] = title
    url = f"https://www.omdbapi.com/?{urllib.parse.urlencode(params)}"
    data = http_get_json(url, headers={"Accept": "application/json"})
    if data.get("Response") != "True":
        return {}
    runtime = clean_text(data.get("Runtime"))
    country = clean_text(data.get("Country"))
    out = {}
    if runtime:
        out["runtime"] = runtime
    if country:
        out["country"] = country
    return out


def wiki_page_title(title):
    if not title:
        return None
    headers = {"User-Agent": WIKI_UA}
    search_params = {
        "action": "query",
        "list": "search",
        "srsearch": title,
        "format": "json",
        "srlimit": 1,
    }
    search_url = f"https://en.wikipedia.org/w/api.php?{urllib.parse.urlencode(search_params)}"
    data = http_get_json(search_url, headers=headers)
    results = (data.get("query") or {}).get("search") or []
    if not results:
        return None
    return results[0].get("title")


def wikidata_qid_from_title(title):
    page_title = wiki_page_title(title)
    if not page_title:
        return None
    headers = {"User-Agent": WIKI_UA}
    params = {
        "action": "query",
        "prop": "pageprops",
        "ppprop": "wikibase_item",
        "titles": page_title,
        "format": "json",
    }
    url = f"https://en.wikipedia.org/w/api.php?{urllib.parse.urlencode(params)}"
    data = http_get_json(url, headers=headers)
    pages = (data.get("query") or {}).get("pages") or {}
    for page in pages.values():
        qid = (page.get("pageprops") or {}).get("wikibase_item")
        if qid:
            return qid
    return None


def wikidata_labels(qids):
    if not qids:
        return {}
    headers = {"User-Agent": WIKI_UA}
    params = {
        "action": "wbgetentities",
        "ids": "|".join(qids),
        "props": "labels",
        "languages": "en",
        "format": "json",
    }
    url = f"https://www.wikidata.org/w/api.php?{urllib.parse.urlencode(params)}"
    data = http_get_json(url, headers=headers)
    entities = data.get("entities") or {}
    out = {}
    for qid, payload in entities.items():
        label = (payload.get("labels") or {}).get("en") or {}
        value = label.get("value")
        if value:
            out[qid] = value
    return out


def parse_wikidata_duration(claims):
    if not claims:
        return None
    for claim in claims:
        val = ((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value")
        if not isinstance(val, dict):
            continue
        amount = val.get("amount")
        unit = val.get("unit")
        if amount is None or not unit:
            continue
        try:
            num = float(str(amount).replace("+", ""))
        except ValueError:
            continue
        unit_id = str(unit).split("/")[-1]
        if unit_id == "Q7727":  # minutes
            minutes = num
        elif unit_id == "Q25235":  # hours
            minutes = num * 60
        elif unit_id == "Q11574":  # seconds
            minutes = num / 60
        else:
            continue
        if minutes and minutes > 0:
            return f"{int(round(minutes))} min"
    return None


def wikidata_details(title):
    qid = wikidata_qid_from_title(title)
    if not qid:
        return {}
    headers = {"User-Agent": WIKI_UA}
    url = f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"
    data = http_get_json(url, headers=headers)
    entity = (data.get("entities") or {}).get(qid) or {}
    claims = entity.get("claims") or {}
    runtime = parse_wikidata_duration(claims.get("P2047"))
    country_ids = []
    for claim in claims.get("P495") or []:
        val = ((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value")
        if isinstance(val, dict):
            q = val.get("id")
            if q:
                country_ids.append(q)
    country = None
    if country_ids:
        labels = wikidata_labels(country_ids)
        names = [labels.get(q) for q in country_ids if labels.get(q)]
        if names:
            country = ", ".join(dict.fromkeys(names))
    out = {}
    if runtime:
        out["runtime"] = runtime
    if country:
        out["country"] = country
    return out


def find_details(item, tmdb_key, omdb_key):
    runtime = clean_text(item.get("runtime"))
    country = clean_text(item.get("country"))
    providers = set()
    title = item.get("title")
    imdb_url = item.get("imdb_url")

    if (not runtime or not country) and tmdb_key:
        data = tmdb_details(title, tmdb_key)
        if data.get("runtime") and not runtime:
            runtime = data["runtime"]
            providers.add("tmdb")
        if data.get("country") and not country:
            country = data["country"]
            providers.add("tmdb")

    if (not runtime or not country) and omdb_key:
        data = omdb_details(title, imdb_url, omdb_key)
        if data.get("runtime") and not runtime:
            runtime = data["runtime"]
            providers.add("omdb")
        if data.get("country") and not country:
            country = data["country"]
            providers.add("omdb")

    if not runtime or not country:
        data = wikidata_details(title)
        if data.get("runtime") and not runtime:
            runtime = data["runtime"]
            providers.add("wikidata")
        if data.get("country") and not country:
            country = data["country"]
            providers.add("wikidata")

    country = normalize_country_list(country)
    return runtime, country, providers


def winners_cache_fresh(path):
    try:
        if not path.exists():
            return False
        age = time.time() - path.stat().st_mtime
        return age < WINNERS_CACHE_TTL
    except Exception:
        return False


def download_winners_csv(force=False):
    if not force and winners_cache_fresh(WINNERS_CACHE):
        return WINNERS_CACHE
    try:
        raw = urllib.request.urlopen(WINNERS_CSV_URL, timeout=20).read()
        WINNERS_CACHE.parent.mkdir(parents=True, exist_ok=True)
        WINNERS_CACHE.write_bytes(raw)
        return WINNERS_CACHE
    except Exception as exc:
        raise RuntimeError(f"Failed to download winners CSV: {exc}") from exc


def normalize_title_key(value):
    if not value:
        return ""
    s = str(value).lower()
    s = s.replace("&", "and")
    s = re.sub(r"[^a-z0-9]+", "", s)
    return s


def split_winner_entries(text):
    if not text:
        return []
    if text.count(" - ") <= 1:
        return [text]
    return re.split(r",\s+(?=[^,]*\s-\s)", text)


def clean_film_title(value):
    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None
    s = re.sub(r"\s*\(.*?\)\s*$", "", s).strip()
    s = re.split(r"\s+as\s+", s, flags=re.IGNORECASE)[0].strip()
    return s or None


def extract_films_from_winners(winners_text, category):
    if not winners_text:
        return []
    text = str(winners_text).strip()
    if not text:
        return []

    if category == "Music (Original Song)":
        m = re.search(r"from\s+([^;,(]+)", text, flags=re.IGNORECASE)
        if m:
            film = clean_film_title(m.group(1))
            return [film] if film else []

    films = []
    for entry in split_winner_entries(text):
        if " - " not in entry:
            continue
        film = entry.split(" - ")[-1].strip()
        film = clean_film_title(film)
        if film:
            films.append(film)
    return list(dict.fromkeys(films))


def parse_winners_rows(path):
    rows = []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def build_winners_map(rows, year=None):
    winners = {}
    for row in rows:
        try:
            y = int(row.get("year") or 0)
        except (TypeError, ValueError):
            continue
        if year and y != year:
            continue
        category = normalize_category(row.get("category"))
        if not category:
            continue
        films = extract_films_from_winners(row.get("winners"), category)
        if not films:
            continue
        year_map = winners.setdefault(y, {})
        for film in films:
            key = normalize_title_key(film)
            if not key:
                continue
            year_map.setdefault(key, set()).add(category)
    return winners


def merge_categories(existing, extra):
    base = []
    seen = set()
    for item in existing or []:
        if item and item not in seen:
            seen.add(item)
            base.append(item)
    for item in extra or []:
        if item and item not in seen:
            seen.add(item)
            base.append(item)
    base.sort(key=lambda c: CANONICAL_ORDER.get(c, 999))
    return base


def update_winners_data(year=None, force=False):
    csv_path = download_winners_csv(force=force)
    rows = parse_winners_rows(csv_path)
    winners_map = build_winners_map(rows, year=year)

    updated_files = 0
    updated_rows = 0
    matched_rows = 0

    # Update JSON seeds
    if OSCARS_DATA_DIR.exists():
        for path in sorted(OSCARS_DATA_DIR.glob("*.json")):
            if path.name.lower() == "years.json":
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if not isinstance(data, dict):
                continue
            rows_list = data.get("rows")
            if not isinstance(rows_list, list):
                continue
            try:
                data_year = int(data.get("year") or 0)
            except (TypeError, ValueError):
                data_year = None
            if year and data_year != year:
                continue
            winners_for_year = winners_map.get(data_year or 0, {})
            if not winners_for_year:
                continue

            changed = False
            for item in rows_list:
                title = item.get("title")
                key = normalize_title_key(title)
                if not key or key not in winners_for_year:
                    continue
                matched_rows += 1
                existing = split_categories(item.get("won_categories"))
                merged = merge_categories(existing, winners_for_year[key])
                if merged:
                    value = "; ".join(merged)
                    if value != item.get("won_categories"):
                        item["won_categories"] = value
                        changed = True
            if changed:
                path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                updated_files += 1

    # Update DB
    if DB_PATH.exists():
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(watchlist);")
        existing_cols = {row[1] for row in cur.fetchall()}
        if "won_categories" not in existing_cols:
            cur.execute("ALTER TABLE watchlist ADD COLUMN won_categories TEXT;")
        conn.commit()

        if year:
            db_rows = cur.execute(
                "SELECT rowid, title, oscars_year, won_categories FROM watchlist WHERE oscars_year = ?;",
                (year,),
            ).fetchall()
        else:
            db_rows = cur.execute(
                "SELECT rowid, title, oscars_year, won_categories FROM watchlist;"
            ).fetchall()

        for rowid, title, oscars_year, won_categories in db_rows:
            try:
                y = int(oscars_year or 0)
            except (TypeError, ValueError):
                continue
            winners_for_year = winners_map.get(y, {})
            if not winners_for_year:
                continue
            key = normalize_title_key(title)
            if not key or key not in winners_for_year:
                continue
            matched_rows += 1
            existing = split_categories(won_categories)
            merged = merge_categories(existing, winners_for_year[key])
            if merged:
                value = "; ".join(merged)
                if value != won_categories:
                    cur.execute(
                        "UPDATE watchlist SET won_categories = ? WHERE rowid = ?;",
                        (value, rowid),
                    )
                    updated_rows += 1
        conn.commit()
        conn.close()

    return {
        "ok": True,
        "year": year,
        "updated_files": updated_files,
        "updated_rows": updated_rows,
        "matched_rows": matched_rows,
        "source": "oscars_1929_2025.csv",
    }

def update_posters(limit=25, force=False, year=None):
    tmdb_key, omdb_key = poster_providers()
    local_index = build_local_poster_index()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    year = parse_year(year)
    if year:
        all_rows = cur.execute(
            "SELECT rowid AS id, * FROM watchlist WHERE oscars_year = ?;",
            (year,),
        ).fetchall()
    else:
        all_rows = cur.execute("SELECT rowid AS id, * FROM watchlist;").fetchall()

    local_updates = 0
    if local_index != ({}, []):
        for row in all_rows:
            item = dict(row)
            local_url = local_poster_url(item.get("title"), local_index)
            if not local_url:
                continue
            current = str(item.get("poster_url") or "")
            if current == local_url and (item.get("poster_source") == "local"):
                continue
            cur.execute(
                "UPDATE watchlist SET poster_url = ?, poster_source = ? WHERE rowid = ?;",
                (local_url, "local", item["id"]),
            )
            local_updates += 1
        conn.commit()

    if force:
        if year:
            rows = cur.execute(
                "SELECT rowid AS id, * FROM watchlist WHERE oscars_year = ?;",
                (year,),
            ).fetchall()
        else:
            rows = cur.execute("SELECT rowid AS id, * FROM watchlist;").fetchall()
    else:
        if year:
            rows = cur.execute(
                "SELECT rowid AS id, * FROM watchlist WHERE oscars_year = ? AND (poster_url IS NULL OR poster_url = '');",
                (year,),
            ).fetchall()
        else:
            rows = cur.execute(
                "SELECT rowid AS id, * FROM watchlist WHERE poster_url IS NULL OR poster_url = '';"
            ).fetchall()

    updated = 0
    missing = 0
    errors = 0
    limit_n = max(0, int(limit))
    for row in rows[:limit_n]:
        item = dict(row)
        try:
            current = str(item.get("poster_url") or "")
            if current.startswith("/posters/"):
                name = urllib.parse.unquote(current[len("/posters/"):])
                if name and (POSTERS_DIR / name).exists():
                    continue
            poster_url, source = find_poster(item, tmdb_key, omdb_key)
            if poster_url:
                cur.execute(
                    "UPDATE watchlist SET poster_url = ?, poster_source = ? WHERE rowid = ?;",
                    (poster_url, source, item["id"]),
                )
                updated += 1
                log_line(f"poster ok: {item.get('title', '-') } [{source}]", tag="api", level="success")
            else:
                missing += 1
        except Exception as exc:
            errors += 1
            log_line(f"poster error: {item.get('title', '-')}: {exc}", tag="api", level="warn")
        time.sleep(0.1)

    conn.commit()
    conn.close()
    attempted = min(len(rows), limit_n)
    return {
        "attempted": attempted,
        "updated": updated,
        "local_updated": local_updates,
        "missing": missing,
        "errors": errors,
        "providers": {"tmdb": bool(tmdb_key), "omdb": bool(omdb_key), "wikipedia": True},
    }


def update_details(limit=25, force=False, year=None):
    tmdb_key, omdb_key = poster_providers()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    year = parse_year(year)
    if year:
        all_rows = cur.execute(
            "SELECT rowid AS id, * FROM watchlist WHERE oscars_year = ?;",
            (year,),
        ).fetchall()
    else:
        all_rows = cur.execute("SELECT rowid AS id, * FROM watchlist;").fetchall()

    if force:
        rows = all_rows
    else:
        rows = []
        for row in all_rows:
            item = dict(row)
            if not clean_text(item.get("runtime")) or not clean_text(item.get("country")):
                rows.append(row)

    updated = 0
    updated_runtime = 0
    updated_country = 0
    missing = 0
    errors = 0
    limit_n = max(0, int(limit))
    for row in rows[:limit_n]:
        item = dict(row)
        try:
            before_runtime = clean_text(item.get("runtime"))
            before_country = clean_text(item.get("country"))
            runtime, country, providers = find_details(item, tmdb_key, omdb_key)
            if runtime or country:
                cur.execute(
                    "UPDATE watchlist SET runtime = ?, country = ? WHERE rowid = ?;",
                    (runtime or before_runtime, country or before_country, item["id"]),
                )
                if runtime and runtime != before_runtime:
                    updated_runtime += 1
                if country and country != before_country:
                    updated_country += 1
                if (runtime and runtime != before_runtime) or (country and country != before_country):
                    updated += 1
                    sources = ",".join(sorted(providers)) if providers else "unknown"
                    log_line(f"details ok: {item.get('title', '-') } [{sources}]", tag="api", level="success")
            else:
                missing += 1
        except Exception as exc:
            errors += 1
            log_line(f"details error: {item.get('title', '-')}: {exc}", tag="api", level="warn")
        time.sleep(0.1)

    conn.commit()
    conn.close()
    attempted = min(len(rows), limit_n)
    return {
        "attempted": attempted,
        "updated": updated,
        "updated_runtime": updated_runtime,
        "updated_country": updated_country,
        "missing": missing,
        "errors": errors,
        "providers": {"tmdb": bool(tmdb_key), "omdb": bool(omdb_key), "wikidata": True},
    }

def load_seed_rows(path=SEED_JS):
    if not path.exists():
        return []
    raw = path.read_text(encoding="utf-8")
    if "=" not in raw:
        return []
    json_text = raw.split("=", 1)[1].strip()
    if json_text.endswith(";"):
        json_text = json_text[:-1]
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        data = data.get("rows", [])
    return data if isinstance(data, list) else []


def load_seed_rows_json(year):
    if year is None:
        return []
    try:
        year_int = int(year)
    except (TypeError, ValueError):
        return []
    path = OSCARS_DATA_DIR / f"{year_int}.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        data = data.get("rows", [])
    return data if isinstance(data, list) else []


def list_seed_years():
    years = set()
    if OSCARS_DATA_DIR.exists():
        for item in OSCARS_DATA_DIR.glob("*.json"):
            if item.name.lower() == "years.json":
                continue
            name = item.stem
            if name.isdigit():
                years.add(int(name))
    return sorted(years, reverse=True)


def list_db_years():
    if not DB_PATH.exists():
        return []
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        cur.execute("SELECT DISTINCT oscars_year FROM watchlist WHERE oscars_year IS NOT NULL;")
        years = [row[0] for row in cur.fetchall() if row and row[0] is not None]
    except sqlite3.Error:
        years = []
    conn.close()
    return years


def available_years():
    years = set(list_seed_years())
    years.update(list_db_years())
    return sorted(years, reverse=True)


def ensure_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cols_sql = ", ".join(f"{name} {ctype}" for name, ctype in COLUMNS)
    cur.execute(f"CREATE TABLE IF NOT EXISTS watchlist ({cols_sql});")
    conn.commit()

    cur.execute("PRAGMA table_info(watchlist);")
    existing = {row[1] for row in cur.fetchall()}
    for name, ctype in COLUMNS:
        if name not in existing:
            cur.execute(f"ALTER TABLE watchlist ADD COLUMN {name} {ctype};")
    conn.commit()

    cur.execute("UPDATE watchlist SET oscars_year = ? WHERE oscars_year IS NULL;", (2026,))
    conn.commit()

    years = list_seed_years()
    cur.execute("SELECT COUNT(1) FROM watchlist;")
    count = cur.fetchone()[0]
    if count == 0:
        for year in years:
            rows = load_seed_rows_json(year)
            if rows:
                insert_seed(conn, rows, default_year=year)
    else:
        for year in years:
            cur.execute("SELECT COUNT(1) FROM watchlist WHERE oscars_year = ?;", (year,))
            has_year = cur.fetchone()[0]
            if has_year == 0:
                rows = load_seed_rows_json(year)
                if rows:
                    insert_seed(conn, rows, default_year=year)
    conn.close()

def insert_seed(conn, seed_rows, default_year=None):
    cols = [name for name, _ in COLUMNS]
    placeholders = ",".join("?" for _ in cols)
    rows = []
    for item in seed_rows:
        row = []
        for col in cols:
            val = item.get(col)
            if val == "":
                val = None
            if col == "watched":
                val = normalize_bool(val)
            elif col == "rating_1_10":
                val = normalize_float(val)
            elif col == "nominations_number":
                val = normalize_int(val)
            elif col == "oscars_year":
                val = normalize_int(val)
                if val is None and default_year is not None:
                    val = int(default_year)
            row.append(val)
        rows.append(row)

    cur = conn.cursor()
    cur.executemany(
        f"INSERT INTO watchlist ({','.join(cols)}) VALUES ({placeholders});",
        rows,
    )
    conn.commit()

def fetch_all(year=None):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    if year:
        rows = cur.execute(
            "SELECT rowid AS id, * FROM watchlist WHERE oscars_year = ?;",
            (year,),
        ).fetchall()
    else:
        rows = cur.execute("SELECT rowid AS id, * FROM watchlist;").fetchall()
    conn.close()
    result = [dict(r) for r in rows]
    index = build_local_poster_index()
    if index != ({}, []):
        for row in result:
            current = str(row.get("poster_url") or "")
            if current.startswith("/posters/"):
                name = urllib.parse.unquote(current[len("/posters/"):])
                if name and (POSTERS_DIR / name).exists():
                    row["poster_source"] = row.get("poster_source") or "local"
                    continue
            local_url = local_poster_url(row.get("title"), index)
            if local_url:
                row["poster_url"] = local_url
                row["poster_source"] = "local"
    return result

def normalize_patch(patch: dict):
    out = {}
    if "watched" in patch:
        watched = normalize_bool(patch.get("watched"))
        out["watched"] = watched
        if watched == 1 and not patch.get("watched_date"):
            out["watched_date"] = today_iso()
        if watched == 0:
            out["watched_date"] = None

    if "watched_date" in patch:
        wd = patch.get("watched_date")
        if wd in (None, ""):
            out["watched_date"] = None
        else:
            normalized = normalize_date_input(wd)
            if normalized:
                out["watched_date"] = normalized

    if "rating_1_10" in patch:
        n = normalize_float(patch.get("rating_1_10"))
        if n is None:
            out["rating_1_10"] = None
        else:
            out["rating_1_10"] = max(0, min(10, n))

    if "where_to_watch" in patch:
        val = patch.get("where_to_watch")
        out["where_to_watch"] = None if val in (None, "") else str(val)

    if "notes" in patch:
        val = patch.get("notes")
        out["notes"] = None if val in (None, "") else str(val)

    if "won_categories" in patch:
        val = patch.get("won_categories")
        out["won_categories"] = None if val in (None, "") else str(val)

    if "poster_url" in patch:
        val = patch.get("poster_url")
        if val in (None, ""):
            out["poster_url"] = None
            out["poster_source"] = None
        else:
            out["poster_url"] = str(val)
            out["poster_source"] = "manual"

    return out


def update_row(row_id, patch):
    if row_id is None:
        return None
    fields = {k: v for k, v in patch.items() if k in UPDATE_FIELDS}
    if not fields:
        return None

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    assignments = ", ".join(f"{k} = ?" for k in fields.keys())
    values = list(fields.values()) + [row_id]
    cur.execute(f"UPDATE watchlist SET {assignments} WHERE rowid = ?;", values)
    conn.commit()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    row = cur.execute(
        "SELECT rowid AS id, * FROM watchlist WHERE rowid = ?;",
        (row_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, format, *args):
        try:
            if len(args) >= 2 and isinstance(args[0], str):
                request_line = args[0]
                status = int(args[1])
                method = request_line.split(" ", 1)[0]
                path = request_line.split(" ")[1] if " " in request_line else request_line
                level = "success" if 200 <= status < 300 else "warn" if 300 <= status < 400 else "error"
                log_line(f"{status} {method} {path}", tag="http", level=level)
                return
        except Exception:
            pass
        super().log_message(format, *args)

    def send_json(self, payload, status=200):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path.startswith("/posters/"):
            self.path = f"/public{path}"
            super().do_GET()
            return
        if path == "/api/oscars/years":
            try:
                years = available_years()
                self.send_json({"years": years})
            except Exception as exc:
                self.send_json({"error": str(exc)}, status=500)
            return
        if path == "/api/oscars":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                year = parse_year(query.get("year", [None])[0])
                rows = fetch_all(year)
                self.send_json({"rows": rows})
            except Exception as exc:
                self.send_json({"error": str(exc)}, status=500)
            return
        if path == "/api/oscars/debug":
            info = dict(LAST_UPDATE)
            info["db_path"] = str(DB_PATH)
            self.send_json(info)
            return
        super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        if path not in {
            "/api/oscars/update",
            "/api/oscars/reset",
            "/api/oscars/posters",
            "/api/oscars/details",
            "/api/oscars/winners",
        }:
            self.send_json({"error": "Not found"}, status=404)
            return

        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except json.JSONDecodeError:
            self.send_json({"error": "Invalid JSON"}, status=400)
            return

        try:
            if path == "/api/oscars/posters":
                limit = int(payload.get("limit") or 25)
                force = bool(payload.get("force"))
                year = parse_year(payload.get("year"))
                result = update_posters(limit=limit, force=force, year=year)
                self.send_json({"ok": True, **result})
                return

            if path == "/api/oscars/details":
                limit = int(payload.get("limit") or 25)
                force = bool(payload.get("force"))
                year = parse_year(payload.get("year"))
                result = update_details(limit=limit, force=force, year=year)
                self.send_json({"ok": True, **result})
                return

            if path == "/api/oscars/winners":
                force = bool(payload.get("force"))
                year = parse_year(payload.get("year"))
                result = update_winners_data(year=year, force=force)
                self.send_json(result)
                return

            if path == "/api/oscars/reset":
                year = parse_year(payload.get("year"))
                count = reset_db(year=year)
                self.send_json({"ok": True, "count": count})
                return

            row_id = payload.get("id")
            patch = payload.get("patch") or {}
            log_line(f"UPDATE request id={row_id}", tag="api", level="info")
            log_json("patch:", patch, tag="api", level="dim")
            normalized = normalize_patch(patch)
            log_json("normalized:", normalized, tag="api", level="dim")
            updated = update_row(row_id, normalized)
            log_json("result:", updated, tag="api", level="dim")
            set_last_update(
                {
                    "id": row_id,
                    "patch": patch,
                    "normalized": normalized,
                    "row": updated,
                }
            )
            if not updated:
                self.send_json({"error": "Update failed"}, status=400)
                return
            self.send_json({"ok": True, "row": updated})
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=500)


def reset_db(year=None):
    year = parse_year(year)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    if year:
        cur.execute("DELETE FROM watchlist WHERE oscars_year = ?;", (year,))
        rows = load_seed_rows_json(year)
        if rows:
            insert_seed(conn, rows, default_year=year)
        conn.commit()
        conn.close()
        return len(rows)

    cur.execute("DELETE FROM watchlist;")
    total = 0
    years = list_seed_years()
    for seed_year in years:
        rows = load_seed_rows_json(seed_year)
        if rows:
            insert_seed(conn, rows, default_year=seed_year)
            total += len(rows)
    conn.commit()
    conn.close()
    return total

def run():
    log_line("Server starting...", tag="api", level="info")
    load_env_files()
    ensure_db()
    port = 8000
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    log_line(f"Server running: http://127.0.0.1:{port}", tag="api", level="success")
    server.serve_forever()


if __name__ == "__main__":
    run()
