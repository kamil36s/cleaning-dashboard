import json
import os
import threading
import time
import unicodedata
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


CINEMA_CITY_API_ROOT = "https://www.cinema-city.pl/pl/data-api-service/v1/quickbook/10103"
CINEMA_CITY_CALENDAR_NAME = "Cinema City Galeria Kazimierz"
CINEMA_CITY_AUTO_TAG = "AUTO_CINEMA_CITY"
CINEMA_CITY_TIMEZONE = ZoneInfo("Europe/Warsaw")
CINEMA_CITY_USER_AGENT = "cleaning-dashboard/1.0"
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
EXCLUDED_EVENT_ATTRIBUTE_PREFIXES = ("dubbed",)

_CACHE = {"expires_at": 0.0, "payload": None}
_CACHE_LOCK = threading.Lock()


class CinemaCityRepertoireError(RuntimeError):
    pass


def _config():
    raw_days = os.environ.get("CINEMA_CITY_REPERTOIRE_DAYS", "8")
    raw_ttl = os.environ.get("CINEMA_CITY_REPERTOIRE_CACHE_SECONDS", "600")
    try:
        days = max(1, min(14, int(raw_days)))
    except (TypeError, ValueError):
        days = 8
    try:
        cache_seconds = max(60, min(3600, int(raw_ttl)))
    except (TypeError, ValueError):
        cache_seconds = 600
    return {
        "api_root": os.environ.get("CINEMA_CITY_REPERTOIRE_API_ROOT", CINEMA_CITY_API_ROOT).rstrip("/"),
        "cinema_id": os.environ.get("CINEMA_CITY_CINEMA_ID", "1076").strip() or "1076",
        "days": days,
        "cache_seconds": cache_seconds,
    }


def _read_json(url):
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Referer": "https://www.cinema-city.pl/kina/kazimierz/1076",
            "User-Agent": CINEMA_CITY_USER_AGENT,
        },
    )
    with urllib.request.urlopen(request, timeout=12) as response:
        body = response.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise CinemaCityRepertoireError("Cinema City response is too large")
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CinemaCityRepertoireError("Cinema City returned invalid JSON") from exc


def _api_url(config, path):
    return f"{config['api_root']}{path}"


def _fetch_available_dates(config, today):
    until = today + timedelta(days=config["days"] - 1)
    url = _api_url(
        config,
        f"/dates/in-cinema/{urllib.parse.quote(config['cinema_id'], safe='')}/until/{until.isoformat()}?attr=",
    )
    payload = _read_json(url)
    dates = payload.get("body", {}).get("dates", [])
    return [
        value
        for value in dates
        if isinstance(value, str) and today.isoformat() <= value <= until.isoformat()
    ]


def _fetch_date(config, value):
    url = _api_url(
        config,
        f"/film-events/in-cinema/{urllib.parse.quote(config['cinema_id'], safe='')}/at-date/{value}?attr=",
    )
    return value, _read_json(url)


def _clean_text(value):
    return " ".join(str(value or "").split()).strip()


def _has_excluded_event_attribute(attributes):
    normalized = (_clean_text(attribute).casefold() for attribute in attributes or [])
    return any(
        attribute == prefix or attribute.startswith(f"{prefix}-")
        for attribute in normalized
        for prefix in EXCLUDED_EVENT_ATTRIBUTE_PREFIXES
    )


def normalize_filter_text(value):
    text = unicodedata.normalize("NFKD", _clean_text(value).casefold())
    text = "".join(character for character in text if not unicodedata.combining(character))
    return re_sub_non_word(text)


def re_sub_non_word(value):
    normalized = "".join(character if character.isalnum() else " " for character in value)
    return " ".join(normalized.split())


def _matches_excluded_title(title, excluded_titles):
    normalized_title = normalize_filter_text(title)
    if not normalized_title:
        return False
    for excluded in excluded_titles:
        normalized_excluded = normalize_filter_text(excluded)
        if not normalized_excluded:
            continue
        if normalized_title == normalized_excluded:
            return True
        for suffix in (" wersja ", " ukrainski dubbing", " dubbing ukrainski"):
            if normalized_title.startswith(f"{normalized_excluded}{suffix}"):
                return True
    return False


def repertoire_filter_reason(title, filters):
    watched = [
        *(filters.get("watched") or []),
        *(filters.get("watchedSubscription") or []),
    ]
    if _matches_excluded_title(title, watched):
        return "watched"
    if _matches_excluded_title(title, filters.get("neverWatch") or []):
        return "never_watch"
    normalized_title = normalize_filter_text(title)
    if any(
        normalize_filter_text(keyword) in normalized_title
        for keyword in (filters.get("kidsKeywords") or [])
        if normalize_filter_text(keyword)
    ):
        return "kids_keyword"
    return ""


def apply_repertoire_filters(payload, filters):
    source_events = payload.get("events", []) if isinstance(payload, dict) else []
    reasons_by_title = {}
    filtered_events = []
    for event in source_events:
        title = _clean_text(event.get("title")) if isinstance(event, dict) else ""
        reason = reasons_by_title.setdefault(title, repertoire_filter_reason(title, filters))
        if not reason:
            filtered_events.append(event)

    result = dict(payload)
    result["events"] = filtered_events
    result["filtering"] = {
        "source": "google_sheets",
        "keptEvents": len(filtered_events),
        "hiddenEvents": len(source_events) - len(filtered_events),
        "hiddenMovies": sum(1 for reason in reasons_by_title.values() if reason),
        "rules": {
            "watched": len(filters.get("watched") or []),
            "neverWatch": len(filters.get("neverWatch") or []),
            "kidsKeywords": len(filters.get("kidsKeywords") or []),
            "watchedSubscription": len(filters.get("watchedSubscription") or []),
        },
    }
    return result


def normalize_repertoire_payload(value, payload, now=None):
    now = now or datetime.now(CINEMA_CITY_TIMEZONE)
    if now.tzinfo is None:
        now = now.replace(tzinfo=CINEMA_CITY_TIMEZONE)
    body = payload.get("body", {}) if isinstance(payload, dict) else {}
    films = {
        str(item.get("id")): item
        for item in body.get("films", [])
        if isinstance(item, dict) and item.get("id")
    }
    normalized = []
    for item in body.get("events", []):
        if not isinstance(item, dict) or item.get("soldOut") is True:
            continue
        event_attribute_ids = item.get("attributeIds", [])
        if _has_excluded_event_attribute(event_attribute_ids):
            continue
        film = films.get(str(item.get("filmId")))
        title = _clean_text((film or {}).get("name"))
        raw_start = _clean_text(item.get("eventDateTime"))
        if not title or not raw_start:
            continue
        try:
            start = datetime.fromisoformat(raw_start)
        except ValueError:
            continue
        if start.tzinfo is None:
            start = start.replace(tzinfo=CINEMA_CITY_TIMEZONE)
        if start <= now:
            continue

        length = (film or {}).get("length")
        try:
            length = int(length)
        except (TypeError, ValueError):
            length = 0
        end = start + timedelta(minutes=max(0, length)) if length else None
        film_attributes = " ".join(
            _clean_text(attribute) for attribute in (film or {}).get("attributeIds", []) if _clean_text(attribute)
        )
        event_attributes = " ".join(
            _clean_text(attribute) for attribute in event_attribute_ids if _clean_text(attribute)
        )
        event_id = _clean_text(item.get("id")) or f"{item.get('filmId')}:{raw_start}"
        normalized.append({
            "id": f"cinema-city:{event_id}",
            "date": start.date().isoformat(),
            "title": title,
            "startTime": start.strftime("%H:%M"),
            "endTime": end.strftime("%H:%M") if end else "",
            "notes": "\n".join([
                CINEMA_CITY_AUTO_TAG,
                f"Film: {title}",
                f"Film attributes: {film_attributes}",
                f"Event attributes: {event_attributes}",
                f"Link: {_clean_text(item.get('bookingRouterLaunchLink') or item.get('bookingLink'))}",
            ]),
            "source": "cinema_city",
            "external": {
                "provider": "cinema_city",
                "calendarId": "cinema-city-live",
                "calendarSummary": CINEMA_CITY_CALENDAR_NAME,
                "eventId": event_id,
            },
        })
    return normalized


def _fetch_repertoire(config, now):
    dates = _fetch_available_dates(config, now.date())
    events = []
    failures = []
    if dates:
        with ThreadPoolExecutor(max_workers=min(4, len(dates))) as executor:
            futures = {executor.submit(_fetch_date, config, value): value for value in dates}
            for future in as_completed(futures):
                value = futures[future]
                try:
                    date_value, payload = future.result()
                    events.extend(normalize_repertoire_payload(date_value, payload, now=now))
                except Exception as exc:
                    failures.append({"date": value, "error": str(exc)})
    if dates and len(failures) == len(dates):
        raise CinemaCityRepertoireError("Could not load Cinema City screenings")
    events.sort(key=lambda item: (item["date"], item["startTime"], item["title"]))
    return {
        "ok": True,
        "source": "cinema_city",
        "cinemaId": config["cinema_id"],
        "cinemaName": CINEMA_CITY_CALENDAR_NAME,
        "fetchedAt": now.isoformat(timespec="seconds"),
        "dates": dates,
        "events": events,
        "partialErrors": failures,
    }


def read_cinema_city_repertoire(force=False):
    now_epoch = time.time()
    with _CACHE_LOCK:
        cached = _CACHE.get("payload")
        if not force and cached is not None and now_epoch < _CACHE.get("expires_at", 0):
            return cached

        config = _config()
        try:
            payload = _fetch_repertoire(config, datetime.now(CINEMA_CITY_TIMEZONE))
        except Exception as exc:
            if cached is not None:
                stale = dict(cached)
                stale["stale"] = True
                stale["refreshError"] = str(exc)
                return stale
            if isinstance(exc, CinemaCityRepertoireError):
                raise
            raise CinemaCityRepertoireError(str(exc)) from exc

        _CACHE["payload"] = payload
        _CACHE["expires_at"] = now_epoch + config["cache_seconds"]
        return payload
