"""Shared football snapshots, request control and lazy profile enrichment.

Kitchen owns score refresh; profiles reuse its controlled HTTP transport.
"""

import json
import os
import threading
import time
import unicodedata
import urllib.error
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlsplit


FOOTBALL_HOSTS = {
    "v3.football.api-sports.io": "API-Football",
    "site.web.api.espn.com": "ESPN",
    "site.api.espn.com": "ESPN",
    "www.thesportsdb.com": "TheSportsDB",
    "r2.thesportsdb.com": "TheSportsDB",
    "www.bbc.co.uk": "BBC Sport",
}
_history_lock = threading.Lock()


class FootballRequestControl:
    """Deduplicate equivalent requests and stop calls during a provider 429 cooldown."""

    PER_MINUTE = {"API-Football": 8, "ESPN": 20, "TheSportsDB": 30, "BBC Sport": 10}

    def __init__(self, clock=None):
        self.clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._request_locks = {}
        self._cache = {}
        self._cooldowns = {}
        self._calls = {}
        self._failures = {}

    def get(self, url, fetch):
        provider = FOOTBALL_HOSTS.get((urlsplit(url).hostname or "").lower())
        if not provider:
            return (*fetch(), False)
        with self._lock:
            request_lock = self._request_locks.setdefault(provider, threading.Lock())
        with request_lock:
            current = self.clock()
            with self._lock:
                cached = self._cache.get(url)
                if cached and current < cached[0]:
                    return cached[1], cached[2], True
                cooldown = self._cooldowns.get(provider, 0)
                if current < cooldown:
                    raise RuntimeError(f"{provider} cooldown: retry after {round(cooldown - current)}s")
                calls = [at for at in self._calls.get(provider, []) if current - at < 60]
                self._calls[provider] = calls
                if len(calls) >= self.PER_MINUTE.get(provider, 10):
                    self._cooldowns[provider] = calls[0] + 60
                    raise RuntimeError(f"{provider} cooldown: rolling-minute request limit")
                calls.append(current)
            try:
                payload, status = fetch()
            except urllib.error.HTTPError as exc:
                with self._lock:
                    self._failures[provider] = self._failures.get(provider, 0) + 1
                    if exc.code == 429:
                        try:
                            seconds = int(exc.headers.get("Retry-After") or 600)
                        except (TypeError, ValueError):
                            seconds = 600
                        self._cooldowns[provider] = self.clock() + min(3600, max(30, seconds))
                    elif self._failures[provider] >= 3:
                        self._cooldowns[provider] = self.clock() + 300
                raise
            except Exception:
                with self._lock:
                    self._failures[provider] = self._failures.get(provider, 0) + 1
                    if self._failures[provider] >= 3:
                        self._cooldowns[provider] = self.clock() + 300
                raise
            path = urlsplit(url).path.lower()
            ttl = 30 if "scoreboard" in path or "live" in path else 1800 if "standings" in path else 300
            with self._lock:
                self._cache[url] = (self.clock() + ttl, payload, status)
                self._failures[provider] = 0
                # Bound this in-memory cache independently of the JSON diagnostics history.
                if len(self._cache) > 300:
                    self._cache.pop(next(iter(self._cache)))
            return payload, status, False

    def cooldowns(self):
        with self._lock:
            current = self.clock()
            return {provider: round(until - current) for provider, until in self._cooldowns.items() if until > current}

    def usage(self):
        with self._lock:
            current = self.clock()
            return {provider: {"minute": len([at for at in self._calls.get(provider, []) if current - at < 60]),
                               "minuteLimit": limit, "consecutiveFailures": self._failures.get(provider, 0)}
                    for provider, limit in self.PER_MINUTE.items()}


def possible_duplicate_matches(matches):
    """Surface conservative same-day candidates without silently merging records."""
    groups = {}
    for row in matches:
        clubs = row.get("clubKeys") or []
        when = str(row.get("kickoffAt") or row.get("playedAt") or "")[:10]
        if len(clubs) < 2 or not clubs[0] or not clubs[1] or not when:
            continue
        key = (row.get("competitionKey") or "", when, clubs[0], clubs[1])
        groups.setdefault(key, []).append(row)
    return [{"competitionKey": key[0], "date": key[1], "homeKey": key[2], "awayKey": key[3],
             "sources": [{"provider": row.get("provider"), "id": row.get("id"), "category": row.get("category")} for row in rows]}
            for key, rows in groups.items() if len({(row.get("provider"), row.get("id")) for row in rows}) > 1][:100]


def _read(path, default):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        return value if isinstance(value, type(default)) else default
    except (OSError, ValueError):
        return default


def _key(name):
    folded = unicodedata.normalize("NFKD", str(name or "")).casefold()
    return "".join(char for char in folded if char.isalnum())


def _crest_key(name):
    folded = unicodedata.normalize("NFKD", str(name or "")).casefold()
    words = "".join(char if char.isalnum() and ord(char) < 128 else " " for char in folded).split()
    return " ".join(word for word in words if word not in {"fc", "ks", "tsk", "sa"})


def _timestamp(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def record_request(path, url, status, elapsed_ms, received=None, error=""):
    """Store bounded, credential-free metadata about a football provider request."""
    parsed = urlsplit(url)
    provider = FOOTBALL_HOSTS.get((parsed.hostname or "").lower())
    if not provider:
        return
    row = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "provider": provider,
        "endpoint": parsed.path[:120],
        "status": status,
        "durationMs": round(elapsed_ms),
        "received": received,
        "error": str(error)[:120],
    }
    with _history_lock:
        data = _read(path, {"requests": [], "runs": []})
        data["requests"] = ([row] + data.get("requests", []))[:200]
        _write(path, data)


def record_sync(path, payload, input_count, error=""):
    row = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": "error" if error else "success",
        "receivedNormalized": input_count,
        "storedMatches": len(payload.get("matches") or []),
        "duplicates": max(0, input_count - len(payload.get("matches") or [])),
        "upcoming": len(payload.get("nextMatches") or []),
        "sourceErrors": list(payload.get("sourceErrors") or [])[:10],
        "error": str(error)[:160],
    }
    with _history_lock:
        data = _read(path, {"requests": [], "runs": []})
        data["runs"] = ([row] + data.get("runs", []))[:50]
        _write(path, data)


def _write(path, data):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, target)


def build_snapshot(scores, settings, catalog, crest_cache, history, now=None, api_key_configured=False, cooldowns=None, preferred_crests=None, request_usage=None):
    """Return only locally stored data. Missing capabilities are explicit."""
    now = now or time.time()
    sports = settings.get("sports") or {}
    leagues = [item for item in catalog if item.get("sport", "Soccer") == "Soccer" and item.get("espn_sport", "soccer") == "soccer"]
    excluded_keys = {item["key"] for item in catalog if item not in leagues}
    competitions = [item for item in leagues if item.get("type") == "competition"]
    teams = [item for item in leagues if item.get("type") == "team" or (not item.get("type") and item.get("thesportsdb_team_id"))]
    followed_teams = set(sports.get("enabledTeamKeys") or [])
    followed_leagues = set(sports.get("enabledLeagueKeys") or [])
    crest_rows = crest_cache.get("teams") or {}
    preferred_crests = preferred_crests or {}
    aliases = {}
    clubs = {}

    for team in teams:
        key = team["key"]
        if key in clubs:
            continue
        aliases[_key(team.get("name"))] = key
        for alias in team.get("espn_team_names") or []:
            aliases[_key(alias)] = key
        clubs[key] = {
            "key": key, "name": team.get("name"), "followed": key in followed_teams,
            "providerIds": {k: team[k] for k in ("thesportsdb_team_id",) if team.get(k)},
            "names": [team.get("name")], "crest": preferred_crests.get(key) or team.get("crest") or "",
            "crestSource": "manual override" if preferred_crests.get(key) else "catalog" if team.get("crest") else "",
        }

    def resolve_club(name):
        normalized = _key(name)
        if normalized in aliases:
            return aliases[normalized]
        for suffix in ("fc", "afc", "sc", "jk"):
            if normalized.endswith(suffix) and normalized[:-len(suffix)] in aliases:
                return aliases[normalized[:-len(suffix)]]
        return "name-" + normalized

    matches = []
    seen = set()
    for category in ("liveMatches", "matches", "nextMatches"):
        for original in scores.get(category) or []:
            if not isinstance(original, dict):
                continue
            if (original.get("leagueKey") or original.get("teamKey")) in excluded_keys:
                continue
            item = dict(original)
            item["category"] = {"liveMatches": "live", "matches": "result", "nextMatches": "upcoming"}[category]
            item["competitionKey"] = item.get("leagueKey") or item.get("teamKey") or ""
            item["sourceUpdatedAt"] = scores.get("nextMatchesUpdatedAt") if category == "nextMatches" else scores.get("updatedAt")
            club_keys = []
            for side in ("home", "away"):
                side_data = item.get(side) or {}
                name = side_data.get("name") or ""
                if not name:
                    club_keys.append("")
                    continue
                key = resolve_club(name)
                club = clubs.setdefault(key, {
                    "key": key, "name": name, "followed": False, "providerIds": {},
                    "names": [], "crest": "", "crestSource": "",
                })
                if name not in club["names"]:
                    club["names"].append(name)
                crest_record = crest_rows.get(_crest_key(name)) or {}
                if crest_record.get("crest") and club["crestSource"] != "manual override":
                    club["crest"] = crest_record["crest"]
                    club["crestSource"] = crest_record.get("source") or "crest cache"
                elif not club["crest"] and side_data.get("crest"):
                    club["crest"] = side_data["crest"]
                    club["crestSource"] = item.get("provider") or "provider"
                club_keys.append(key)
            item["clubKeys"] = club_keys
            identity = (item.get("id"), item["category"])
            if identity in seen:
                continue
            seen.add(identity)
            matches.append(item)

    for item in matches:
        for side, key in zip(("home", "away"), item["clubKeys"]):
            if not key:
                continue
            club = clubs[key]
            item[side] = {**(item.get(side) or {}), "crest": club["crest"], "crestSource": club["crestSource"]}
    for club in clubs.values():
        club["matchCount"] = sum(club["key"] in row["clubKeys"] for row in matches)
    competition_rows = []
    for league in competitions:
        key = league["key"]
        competition_rows.append({
            "key": key, "name": league.get("name"), "country": league.get("country") or "",
            "followed": key in followed_leagues,
            "providers": [name for field, name in (("api_football_id", "API-Football"), ("espn_league", "ESPN"), ("thesportsdb_id", "TheSportsDB")) if league.get(field)],
            "providerIds": {field: league[field] for field in ("api_football_id", "espn_league", "thesportsdb_id") if league.get(field)},
            "matchCount": sum(row["competitionKey"] == key for row in matches),
            "standings": (scores.get("standings") or {}).get(key),
        })

    updated = scores.get("updatedAt")
    age = now - _timestamp(updated) if _timestamp(updated) is not None else None
    score_cache = {
        "key": "kitchen-scores", "type": "results and slides", "updatedAt": updated,
        "ttlSeconds": 1800, "ageSeconds": round(age) if age is not None else None,
        "status": "missing" if age is None else "fresh" if age < 1800 else "stale",
        "recordCount": len(scores.get("matches") or []),
    }
    for item in matches:
        if item["category"] == "live":
            live_at = _timestamp(scores.get("liveUpdatedAt"))
            item["sourceUpdatedAt"] = scores.get("liveUpdatedAt") or item["sourceUpdatedAt"]
            item["liveUnverified"] = bool(scores.get("liveError")) or live_at is None or now - live_at > 120
    next_age = now - _timestamp(scores.get("nextMatchesUpdatedAt")) if _timestamp(scores.get("nextMatchesUpdatedAt")) is not None else None
    next_cache = {
        "key": "kitchen-next-matches", "type": "fixtures", "updatedAt": scores.get("nextMatchesUpdatedAt"),
        "ttlSeconds": 7200, "ageSeconds": round(next_age) if next_age is not None else None,
        "status": "missing" if next_age is None else "fresh" if next_age < 7200 else "stale",
        "recordCount": len(scores.get("nextMatches") or []),
    }
    provider_counts = Counter(item.get("provider") or "unknown" for item in matches)
    requests = history.get("requests") or []
    providers = []
    cooldowns = cooldowns or {}
    request_usage = request_usage or {}
    for name, kind, features in (
        ("API-Football", "REST API", ["results", "fixtures", "standings", "crests"]),
        ("ESPN", "REST API", ["results", "fixtures", "live", "standings", "crests"]),
        ("TheSportsDB", "REST API", ["results", "fixtures", "live", "standings", "crests"]),
        ("BBC Sport", "HTML table", ["standings", "crests"]),
        ("Wikipedia", "wikitext", ["CONIFA results"]),
        ("Manual", "static", ["supplemental results", "assets"]),
    ):
        recent = next((row for row in requests if row.get("provider") == name), None)
        last_success = next((row.get("at") for row in requests if row.get("provider") == name and not row.get("error") and row.get("status") == 200), None)
        last_failure = next((row.get("at") for row in requests if row.get("provider") == name and (row.get("error") or (row.get("status") or 0) >= 400)), None)
        configured = name != "API-Football" or api_key_configured
        providers.append({"name": name, "type": kind, "features": features, "configured": configured,
                          "lastRequest": recent, "cachedRecords": provider_counts.get(name.casefold(), 0),
                          "lastSuccess": last_success, "lastFailure": last_failure,
                          "usage": request_usage.get(name),
                          "cooldownSeconds": cooldowns.get(name, 0),
                          "health": "disabled" if not configured else "cooldown" if cooldowns.get(name, 0) else "unknown" if not recent else "rate limited" if recent.get("status") == 429 else "error" if recent.get("error") else "last request succeeded"})

    return {
        "ok": True, "updatedAt": updated, "cache": [score_cache, next_cache],
        "stale": score_cache["status"] != "fresh" or bool(scores.get("stale")),
        "sourceErrors": list(scores.get("sourceErrors") or []) + ([scores["liveError"]] if scores.get("liveError") else []),
        "fallback": {"scores": bool(scores.get("cachedScoreFallback")), "fixtures": bool(scores.get("cachedNextFallback"))},
        "matches": matches, "clubs": sorted(clubs.values(), key=lambda club: (not club["followed"], club["name"] or "")),
        "competitions": sorted(competition_rows, key=lambda row: (not row["followed"], row["name"] or "")),
        "following": {"teams": sorted(followed_teams), "competitions": sorted(followed_leagues), "standings": sports.get("standingsLeagueKeys") or [], "windowHours": sports.get("windowHours") or 24},
        "providers": providers, "requests": requests[:100], "runs": (history.get("runs") or [])[:30],
        "stored": {"matches": len(scores.get("matches") or []), "fixtures": len(scores.get("nextMatches") or []), "standings": len(scores.get("standings") or {}), "clubsInSnapshot": len(clubs), "competitionsInCatalog": len(competition_rows), "news": 0},
        "leaderboards": scores.get("leaderboards") or {},
        "news": [], "newsStatus": "No licensed football news feed is configured.",
        "storageNote": "The Kitchen JSON cache is the current local snapshot. Historical records and provider mappings are not yet persisted in a football database.",
    }

# Profile enrichment is part of the existing service, using the same HTTP budget
# controller as Kitchen. No provider requests are made during snapshot/search.
PROFILE_TTLS = {"catalog": 86400, "club": 86400, "squad": 21600,
                "statistics": 3600, "transfers": 21600, "coach": 21600, "standings": 21600}
ESPN_PROFILE_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"


def entity_key(kind, provider, external_id):
    return f"{kind}-" + uuid.uuid5(uuid.NAMESPACE_URL, f"football/{kind}/{provider}/{external_id}").hex


def match_identity(row):
    provider = str(row.get("provider") or "")
    external = str(row.get("eventId") or row.get("id") or "")
    if provider == "espn":
        external = external.rsplit(":", 1)[-1]
    return provider, external


def merge_match_history(current, history):
    result, seen = [], set()
    for rows in (current, history):
        for row in sorted(rows, key=lambda r: {"result": 0, "live": 1, "upcoming": 2}.get(r.get("category"), 3)):
            identity = match_identity(row)
            if identity not in seen:
                seen.add(identity)
                result.append(row)
    return result


def final_matches(matches):
    """Only played finals; count the same club/date pairing once across providers."""
    finals = {"ft", "full time", "full-time", "final", "aet", "after extra time", "pen", "after penalties"}
    seen, result = set(), []
    for row in sorted(matches, key=lambda r: str(r.get("playedAt") or r.get("kickoffAt") or ""), reverse=True):
        if str(row.get("status") or "").strip().lower() not in finals:
            continue
        score = row.get("score") or {}
        if any(not isinstance(score.get(side), (int, float)) or isinstance(score.get(side), bool) for side in ("home", "away")):
            continue
        clubs = row.get("clubKeys") or []
        day = str(row.get("playedAt") or row.get("kickoffAt") or "")[:10]
        if len(clubs) != 2 or not all(clubs) or not day:
            continue
        identity = (tuple(clubs), day)
        if identity not in seen:
            seen.add(identity)
            result.append(row)
    return result


def club_statistics(matches, key):
    games = final_matches([r for r in matches if key in (r.get("clubKeys") or [])])
    stats = dict(played=0, wins=0, draws=0, losses=0, goalsFor=0, goalsAgainst=0, goalDifference=0, cleanSheets=0)
    form = []
    for row in games:
        home = row["clubKeys"][0] == key
        gf, ga = row["score"]["home" if home else "away"], row["score"]["away" if home else "home"]
        outcome = "W" if gf > ga else "L" if gf < ga else "D"
        stats["played"] += 1
        stats[{"W": "wins", "D": "draws", "L": "losses"}[outcome]] += 1
        stats["goalsFor"] += gf
        stats["goalsAgainst"] += ga
        stats["cleanSheets"] += ga == 0
        form.append({"result": outcome, "match": row})
    stats["goalDifference"] = stats["goalsFor"] - stats["goalsAgainst"]
    return {"statistics": stats, "form": form[:10], "scope": "Zapisane zakończone mecze — nie pełny sezon. Wynik po grze, bez rozstrzygnięcia serii karnych."}


def parse_transfers(rows, team_id, season=""):
    result = []
    for item in rows:
        player = item.get("player") or {}
        for transfer in item.get("transfers") or []:
            teams = transfer.get("teams") or {}
            incoming, outgoing = teams.get("in") or {}, teams.get("out") or {}
            if str(team_id) not in {str(incoming.get("id")), str(outgoing.get("id"))}:
                continue
            date = str(transfer.get("date") or "")
            # Explicit July–June transfer window convention; not a claim about
            # a provider competition season (calendar-year leagues differ).
            if season:
                if "-" in season:
                    start, end = season.split("-", 1)
                    if not (f"{start}-07-01" <= date < f"{end}-07-01"):
                        continue
                elif not date.startswith(str(season)):
                    continue
            result.append({"key": entity_key("transfer", "API-Football", f"{player.get('id')}/{date}/{outgoing.get('id')}/{incoming.get('id')}"),
                           "providerIds": {"API-Football": f"{player.get('id')}/{date}/{outgoing.get('id')}/{incoming.get('id')}"},
                           "player": player.get("name"), "from": outgoing.get("name"), "to": incoming.get("name"),
                           "date": date, "type": transfer.get("type"),
                           "direction": "IN" if str(incoming.get("id")) == str(team_id) else "OUT",
                           "provider": "API-Football"})
    return sorted(result, key=lambda r: r["date"], reverse=True)


class FootballHub:
    def __init__(self, store, fetch, catalog, sportsdb_base, api_key="", clock=None, standings_fetch=None):
        self.store, self.fetch, self.catalog = store, fetch, catalog
        self.sportsdb_base, self.api_key = sportsdb_base, api_key
        self.clock = clock or time.time
        self.standings_fetch = standings_fetch
        self.lock = threading.RLock()
        self.failures = {}
        self.trace = []  # accessed only inside lock

    def cached(self, kind, identity, fetch):
        key = f"{kind}:{identity}"
        old = self.store.cached(key)
        now = self.clock()
        if old and now - old["fetchedAt"] < PROFILE_TTLS[kind]:
            self.trace.append({"key": key, "state": "fresh", "fetchedAt": old["fetchedAt"]})
            return old["data"]
        failure = self.failures.get(key)
        try:
            if failure and now < failure[0]:
                raise RuntimeError(failure[1])
            value = fetch()
            fetched_at = (_timestamp(value.get("updatedAt")) if kind == "standings" and isinstance(value, dict) else None) or now
            self.store.cache(key, value, fetched_at)
            self.failures.pop(key, None)
            self.trace.append({"key": key, "state": "fresh", "fetchedAt": fetched_at})
            return value
        except Exception as exc:
            limited = getattr(exc, "code", None) == 429 or "cooldown" in str(exc) or str(exc) == "rate-limited"
            reason = "rate-limited" if limited else "provider-unavailable"
            self.failures[key] = failure if failure and now < failure[0] else (now + 120, reason)
            if len(self.failures) > 300:
                self.failures.pop(next(iter(self.failures)))
            self.trace.append({"key": key, "state": "stale" if old else reason,
                               "fetchedAt": old["fetchedAt"] if old else None, "error": reason})
            return old["data"] if old else None

    def _club(self, key, snapshot):
        base = next((dict(c) for c in snapshot["clubs"] if c["key"] == key), None)
        saved = self.store.entity("club", key)
        if not base and not saved:
            raise ValueError("Nieznany klub")
        return {**(base or {}), **(saved or {}), "followed": key in snapshot["following"]["teams"]}

    def _register_teams(self, league, snapshot):
        code = (league.get("providerIds") or {}).get("espn_league") or league.get("espn_league")
        if not code:
            return []
        payload = self.cached("catalog", code, lambda: self.fetch(f"{ESPN_PROFILE_BASE}/{code}/teams?limit=100"))
        if payload is None:
            return []
        teams = [row.get("team") or {} for sport in payload.get("sports") or []
                 for group in sport.get("leagues") or [] for row in group.get("teams") or []]
        result = []
        for team in teams:
            if not team.get("id") or not team.get("displayName"):
                continue
            names = {_key(team.get(field)) for field in ("displayName", "name", "shortDisplayName")}
            candidates = [c for c in snapshot["clubs"] if names.intersection({_key(c.get("name"))} | {_key(n) for n in c.get("names") or []})]
            base = candidates[0] if len(candidates) == 1 else {}
            key = base.get("key") or entity_key("club", "ESPN", team["id"])
            saved = self.store.entity("club", key) or {}
            club = {**base, **saved, "key": key,
                    "name": base.get("name") or team["displayName"], "espnLeague": code,
                    "competitionKey": league.get("key"), "country": league.get("country"),
                    "providerIds": {**saved.get("providerIds", {}), **base.get("providerIds", {}), "ESPN": str(team["id"])},
                    "crest": base.get("crest") or next((l.get("href") for l in team.get("logos") or []), ""),
                    "names": base.get("names") or [team["displayName"]]}
            self.store.put_entity("club", club)
            result.append(club)
        return result

    def _resolve_club(self, club, snapshot):
        if (club.get("providerIds") or {}).get("ESPN"):
            return club
        if not club.get("espnLeague"):
            club = self._metadata(club)
        sources = ([{"key": club.get("competitionKey"), "espn_league": club["espnLeague"]}] if club.get("espnLeague") else [])
        sources += [s for s in self.catalog if s.get("key") == club["key"] and s.get("espn_league")]
        sources += [c for c in snapshot["competitions"] if any(
            club["key"] in (m.get("clubKeys") or []) and m.get("competitionKey") == c["key"] for m in snapshot["matches"])]
        for source in sources[:2]:
            self._register_teams(source, snapshot)
            found = self.store.entity("club", club["key"])
            if found and found.get("providerIds", {}).get("ESPN"):
                return {**club, **found}
        return club

    def _metadata(self, club):
        team_id = club.get("providerIds", {}).get("thesportsdb_team_id")
        if not team_id:
            return club
        def fetch():
            payload = self.fetch(f"{self.sportsdb_base}/lookupteam.php?id={team_id}")
            team = next((t for t in payload.get("teams") or [] if str(t.get("idTeam")) == str(team_id) and t.get("strSport") == "Soccer"), None)
            if not team:
                raise ValueError("Provider returned no matching football team")
            return team
        team = self.cached("club", str(team_id), fetch)
        if not team:
            return club
        club = {**club, "country": team.get("strCountry") or club.get("country"),
                "founded": team.get("intFormedYear"), "city": team.get("strLocation"),
                "metadataSource": "TheSportsDB", "sourceUrl": f"https://www.thesportsdb.com/team/{team_id}"}
        league = next((c for c in self.catalog if str(c.get("thesportsdb_id")) == str(team.get("idLeague")) and c.get("espn_league")), None)
        if league:
            club["espnLeague"], club["competitionKey"] = league["espn_league"], league["key"]
        if team.get("strStadium"):
            stadium = {"key": entity_key("stadium", "TheSportsDB", team.get("idVenue") or f"team/{team_id}"),
                       "providerIds": {"TheSportsDB": str(team.get("idVenue") or f"team/{team_id}")},
                       "name": team["strStadium"], "clubKey": club["key"], "clubName": club["name"],
                       "city": team.get("strLocation"), "capacity": team.get("intStadiumCapacity"),
                       "image": team.get("strStadiumThumb"), "address": team.get("strStadiumLocation"),
                       "provider": "TheSportsDB", "sourceUrl": club["sourceUrl"]}
            self.store.put_entity("stadium", stadium)
            club["stadium"] = stadium
        self.store.put_entity("club", club)
        return club

    def _squad(self, club):
        provider_id = club.get("providerIds", {}).get("ESPN")
        code = club.get("espnLeague")
        if not provider_id or not code:
            return {"players": [], "availability": "Brak zweryfikowanego mapowania składu ESPN dla tego klubu."}
        def fetch():
            payload = self.fetch(f"{ESPN_PROFILE_BASE}/{code}/teams/{provider_id}/roster")
            if str((payload.get("team") or {}).get("id")) != str(provider_id) or not isinstance(payload.get("athletes"), list):
                raise ValueError("Roster identity mismatch")
            return payload
        payload = self.cached("squad", f"{code}/{provider_id}", fetch)
        if payload is None:
            return {"players": [], "availability": "Skład chwilowo niedostępny."}
        result = []
        for row in payload.get("athletes") or []:
            if not row.get("id"):
                continue
            player = {"key": entity_key("player", "ESPN", row["id"]), "providerIds": {"ESPN": str(row["id"])},
                      "name": row.get("displayName"), "fullName": row.get("fullName"),
                      "photo": (row.get("headshot") or {}).get("href"), "nationality": row.get("citizenship"),
                      "dateOfBirth": row.get("dateOfBirth"), "position": (row.get("position") or {}).get("displayName"),
                      "number": row.get("jersey"), "clubKey": club["key"], "clubName": club["name"],
                      "espnLeague": code, "season": payload.get("season"), "provider": "ESPN",
                      "sourceUrl": f"https://www.espn.com/soccer/player/_/id/{row['id']}"}
            self.store.put_entity("player", player)
            result.append(player)
        season = dict(payload.get("season") or {})
        if season.get("year"):
            season_id = f"{code}/{season['year']}"
            season.update(key=entity_key("season", "ESPN", season_id), providerIds={"ESPN": season_id})
            self.store.put_entity("season", season)
        squad = {"key": entity_key("squad", "ESPN", f"{code}/{provider_id}/{season.get('year', 'current')}"),
                 "providerIds": {"ESPN": f"{code}/{provider_id}/{season.get('year', 'current')}"},
                 "clubKey": club["key"], "players": result, "season": season,
                 "availability": "Dane składu ESPN; data pobrania nie potwierdza rejestracji zawodnika."}
        self.store.put_entity("squad", squad)
        return squad

    def _api_team_id(self, club):
        team_id = club.get("providerIds", {}).get("API-Football")
        if team_id or not self.api_key:
            return team_id
        # Search is only used after explicit navigation to transfers/coaches.
        def fetch():
            payload = self.fetch("https://v3.football.api-sports.io/teams?" + urlencode({"search": club["name"]}),
                                 headers={"x-apisports-key": self.api_key})
            if payload.get("errors"):
                raise ValueError("Provider rejected request")
            return payload
        payload = self.cached("catalog", "api-team/" + club["key"], fetch)
        candidates = [r["team"] for r in (payload or {}).get("response") or []
                      if _key((r.get("team") or {}).get("name")) == _key(club["name"])]
        if len(candidates) != 1:
            return None
        team_id = candidates[0]["id"]
        club["providerIds"] = {**club.get("providerIds", {}), "API-Football": team_id}
        self.store.put_entity("club", club)
        return team_id

    def _api_section(self, club, section, year):
        team_id = self._api_team_id(club)
        if not self.api_key or not team_id:
            return {"rows": [], "availability": "Brak skonfigurowanego dostępu API-Football lub zweryfikowanego ID klubu."}
        endpoint = "transfers" if section == "transfers" else "coachs"
        def fetch():
            payload = self.fetch(f"https://v3.football.api-sports.io/{endpoint}?team={team_id}", headers={"x-apisports-key": self.api_key})
            if payload.get("errors") or not isinstance(payload.get("response"), list):
                raise ValueError("Provider rejected request")
            return payload["response"]
        rows = self.cached("transfers" if section == "transfers" else "coach", str(team_id), fetch)
        if section == "transfers":
            transfers = parse_transfers(rows or [], team_id, year)
            for transfer in transfers:
                self.store.put_entity("transfer", transfer)
            return {"rows": transfers, "availability": "Transfery według API-Football; sezon transferowy obejmuje 1 lipca–30 czerwca."}
        result = []
        for coach in rows or []:
            current = next((c for c in coach.get("career") or [] if str((c.get("team") or {}).get("id")) == str(team_id) and c.get("start") and c["start"] <= datetime.now(timezone.utc).date().isoformat() and not c.get("end")), None)
            if not current:
                continue
            result.append({"key": entity_key("coach", "API-Football", coach["id"]), "name": coach.get("name"),
                           "providerIds": {"API-Football": coach["id"]},
                           "photo": coach.get("photo"), "nationality": coach.get("nationality"), "appointed": current["start"], "provider": "API-Football"})
            self.store.put_entity("coach", result[-1])
        return {"rows": result, "availability": "Tylko nominacje z datą rozpoczęcia i bez daty zakończenia w źródle."}

    def _table(self, competition):
        table = competition.get("standings") or {}
        stamp = _timestamp(table.get("updatedAt"))
        if self.standings_fetch and (not table.get("rows") or not stamp or self.clock() - stamp > PROFILE_TTLS["standings"]):
            table = self.cached("standings", competition["key"], lambda: self.standings_fetch(competition["key"])) or table
        return {**competition, "standings": table}

    def search(self, snapshot, query, kind_filter=""):

        query = _key(query)[:100]
        result = []
        for kind, rows in (("club", snapshot["clubs"] + self.store.entities("club")),
                           ("competition", snapshot["competitions"]), ("player", self.store.entities("player")),
                           ("stadium", self.store.entities("stadium"))):
            if kind_filter and kind != kind_filter:
                continue
            seen = set()
            for row in rows:
                if row["key"] in seen:
                    continue
                seen.add(row["key"])
                if not query or query in _key(row.get("name")):
                    result.append({"kind": kind, "key": row["key"], "name": row.get("name"), "followed": row.get("followed", False)})
        return sorted(result, key=lambda r: (not r["followed"], r["name"] or ""))[:100]

    def detail(self, kind, key, section, snapshot, year=""):
        with self.lock:
            self.trace = []
            if kind == "club":
                club = self._club(key, snapshot)
                matches = [r for r in snapshot["matches"] if key in (r.get("clubKeys") or [])]
                result = {"club": club, "matches": matches, **club_statistics(matches, key)}
                if section in {"overview", "squad", "history", "stadium"}:
                    club = self._resolve_club(club, snapshot)
                    if section != "squad":
                        club = self._metadata(club)
                    result["club"] = club
                if section == "squad":
                    result.update(self._squad(club))
                if section in {"transfers", "coach"}:
                    result.update(self._api_section(club, section, year))
                competitions = [self._table(c) if c["key"] == club.get("competitionKey") and section in {"overview", "form"} else c for c in snapshot["competitions"]]
                result["tables"] = [{**c, "standings": {**c["standings"], "rows": [r for r in c["standings"].get("rows", []) if _key(r.get("name")) in {_key(club["name"]), *(_key(n) for n in club.get("names") or [])}]}}
                                    for c in competitions if c.get("standings")]
            elif kind == "competition":
                competition = next((r for r in snapshot["competitions"] if r["key"] == key), None)
                if not competition:
                    raise ValueError("Nieznane rozgrywki")
                competition = self._table(competition)
                league_id = competition.get("providerIds", {}).get("thesportsdb_id")
                if league_id:
                    def metadata():
                        payload = self.fetch(f"{self.sportsdb_base}/lookupleague.php?id={league_id}")
                        row = next((r for r in payload.get("leagues") or [] if str(r.get("idLeague")) == str(league_id) and r.get("strSport") == "Soccer"), None)
                        if not row:
                            raise ValueError("Competition identity mismatch")
                        return row
                    info = self.cached("catalog", "league/" + str(league_id), metadata)
                    if info:
                        competition.update(logo=info.get("strBadge"), season=info.get("strCurrentSeason"), country=info.get("strCountry") or competition.get("country"))
                result = {"competition": competition, "clubs": self._register_teams(competition, snapshot),
                          "matches": [r for r in snapshot["matches"] if r.get("competitionKey") == key]}
            elif kind == "player":
                player = self.store.entity("player", key)
                if not player:
                    raise ValueError("Nieznany zawodnik — otwórz najpierw skład klubu")
                club = self.store.entity("club", player["clubKey"])
                roster = self._squad(club) if club else {"players": []}
                current = next((p for p in roster["players"] if p["key"] == key), None)
                player = current or player
                code, provider_id = player["espnLeague"], player["providerIds"]["ESPN"]
                payload = self.cached("statistics", f"{code}/{provider_id}", lambda: self.fetch(
                    f"https://site.web.api.espn.com/apis/common/v3/sports/soccer/{code}/athletes/{provider_id}/overview"))
                result = {"player": player, "inCurrentSquad": bool(current), "statistics": (payload or {}).get("statistics") or {}}
                squad_cache = self.store.cached(f"squad:{code}/{(self.store.entity('club', player['clubKey']) or {}).get('providerIds', {}).get('ESPN')}")
                if squad_cache:
                    self.trace.append({"key": "player-profile", "state": "fresh" if self.clock() - squad_cache["fetchedAt"] < PROFILE_TTLS["squad"] else "stale", "fetchedAt": squad_cache["fetchedAt"]})
            elif kind == "stadium":
                stadium = self.store.entity("stadium", key)
                if not stadium:
                    raise ValueError("Nieznany stadion")
                club = self._metadata(self._club(stadium["clubKey"], snapshot))
                result = {"stadium": club.get("stadium") or stadium}
            else:
                raise ValueError("Nieznany typ encji")
            return {"ok": True, **result, "cache": list(self.trace), "stale": any(t["state"] == "stale" for t in self.trace),
                    "sourceErrors": [t for t in self.trace if t.get("error")]}
