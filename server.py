import base64
import csv
import hashlib
import html
import hmac
import io
import ipaddress
import json
import math
import os
import queue
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import urllib.parse
import urllib.error
import urllib.request
import uuid
import zipfile
from todo_phone import active_items as phone_todo_active_items, update_file as update_phone_todo_file
from datetime import date, datetime, timedelta, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo
from football_service import merge_match_history, FootballHub, FootballRequestControl, build_snapshot as build_football_snapshot, possible_duplicate_matches, record_request as record_football_request, record_sync as record_football_sync
from football_store import FootballStore

from voice_journal import (
    MAX_MULTIPART_BYTES as VOICE_JOURNAL_MAX_MULTIPART_BYTES,
    VoiceJournalError,
    transcribe_multipart as transcribe_voice_journal_multipart,
    voice_journal_health,
)
from voice_journal_store import (
    VOICE_JOURNAL_STORE,
    parse_create_entry_request,
)
from voice_journal_jobs import VOICE_JOURNAL_JOBS
from journal_store import JOURNAL_STORE, JournalError
from dashboard_sync.core import SyncError
from dashboard_sync.http import authorize as authorize_sync, dispatch as dispatch_sync
from journal_context import JournalContextService
from timeline_store import TIMELINE_STORE, TimelineError
from reading_store import READING_STORE, ReadingError
from cleaning_store import CLEANING_STORE, CleaningError
from timeline_activity import TimelineActivityService
from journal_htr_service import (
    JournalHtrError,
    get_journal_htr_service,
)
from journal_htr_runtime import JournalHtrRuntimeController
from cinema_city_repertoire import (
    CinemaCityRepertoireError,
    apply_repertoire_filters,
    normalize_filter_text,
    read_cinema_city_repertoire,
)
from brutal_assault_store import BRUTAL_ASSAULT_2027_STORE, BrutalAssaultError
from brutal_assault_ratings import BrutalAssaultRatingEnricher
from brutal_assault_monitor import BrutalAssaultMonitor
from bm365_store import BM365_STORE, Bm365Error
from bm365_sheets_syncer import Bm365SheetsSyncer
from bm365_metadata_store import BM365_METADATA_STORE, Bm365MetadataError
from rym_polish_black_metal_store import RYM_POLISH_BLACK_METAL_STORE
from lastfm_store import LASTFM_STORE, LastFmError
from music_store import MUSIC_STORE, MusicError
from music_enrichment import MusicEnrichment
MUSIC_ENRICHMENT = MusicEnrichment(MUSIC_STORE)
from live_workout_plan import LiveWorkoutPlan
from live_workout_store import HeartRateWearDetector, LiveWorkoutStore
from strength_store import StrengthError, StrengthStore
from habits_store import HABITS_STORE, HabitsError
from supplements_store import SupplementsStore
SUPPLEMENTS_STORE = SupplementsStore(HABITS_STORE)
from ring_collector import RingError, create_ring_collector
from ring_phone_bridge import RingPhoneBridge, RingPhoneBridgeError
from synchrobook_backend import READING_GUIDE, SYNCHROBOOK, ReadingGuideError, SynchrobookError
from ai_usage import AIUsageService
from feelings_store import FeelingsError, default_feelings_service
from language_learning import LanguageJobManager, LanguageService, LanguageStore
from language_learning.cloze import ClozeService
from language_learning.cloze_audio import ClozeAudioService
from language_learning.generated_audio import GeneratedTextAudioService
from language_learning.word_audio import WordAudioService
from language_learning.errors import LanguageError
from language_learning.content_inbox import MAX_MEDIA_BYTES
from language_learning.reference_core.config import resolve_reference_paths
from language_learning.reference_core.service import ReferenceLexiconService
from finance_repository import FinanceError, FinanceNotFoundError
from finance_service import FinanceService, FinanceValidationError
from jobhunt_backend import JobhuntError, JobhuntService, JobhuntWorker
from mental_health_store import MENTAL_HEALTH_STORE, MentalHealthError
from phone_tracker import PhoneTrackerStore, PhoneTrackerError
from phone_tracker_access import PhoneAccessStore
from dashboard_runtime_status import read_dashboard_runtime_status

JOURNAL_MAX_PAYLOAD_BYTES = 5 * 1024 * 1024
LIVE_WORKOUT_TELEMETRY_MAX_BYTES = 25 * 1024 * 1024
LIVE_WORKOUT_TELEMETRY_MAX_SAMPLES = 250_000
LIVE_WORKOUT_CONSOLE_SUMMARY_INTERVAL_SEC = 5 * 60
LIVE_WORKOUT_CONSOLE_STATS_LOCK = threading.Lock()
LIVE_WORKOUT_CONSOLE_STATS = {
    "started_at": None,
    "requests": 0,
    "successes": 0,
    "failures": 0,
    "samples": 0,
    "sse_clients": 0,
}

HEART_RATE_SOURCE_MINUTE_MS = 60 * 1000


def _iso_timestamp_ms(value):
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return round(parsed.astimezone(timezone.utc).timestamp() * 1000)


def merge_heart_rate_archive_sources(watch_samples, ring_archive, limit=100000):
    """Merge HR minute-by-minute; any smartwatch sample suppresses ring fallback."""
    safe_limit = max(1, min(100000, int(limit)))
    smartwatch = []
    occupied_minutes = set()
    for sample in watch_samples or []:
        timestamp = sample.get("timestamp") if isinstance(sample, dict) else None
        try:
            timestamp = int(timestamp)
        except (TypeError, ValueError):
            continue
        occupied_minutes.add(timestamp // HEART_RATE_SOURCE_MINUTE_MS)
        smartwatch.append({
            **sample,
            "source": "smartwatch",
            "source_label": "Smartwatch",
        })

    references = sorted(
        (ring_archive or {}).get("watchHeartRateReference") or [],
        key=lambda sample: _iso_timestamp_ms(sample.get("timestampUtc")) or 0,
        reverse=True,
    )
    for reference in references:
        timestamp = _iso_timestamp_ms(reference.get("timestampUtc"))
        if timestamp is None:
            continue
        minute = timestamp // HEART_RATE_SOURCE_MINUTE_MS
        if minute in occupied_minutes:
            continue
        try:
            bpm = int(reference.get("bpm"))
        except (TypeError, ValueError):
            continue
        if not 30 <= bpm <= 240:
            continue
        occupied_minutes.add(minute)
        smartwatch.append({
            "id": f"watch-reference-{reference.get('id')}",
            "timestamp": timestamp,
            "received_at": _iso_timestamp_ms(reference.get("createdAt")) or timestamp,
            "heart_rate": bpm,
            "status": "ready",
            "source": "smartwatch",
            "source_label": "Smartwatch · Health Connect",
            "payload": {
                "heart_rate": bpm,
                "source": "health-connect",
                "data_origin": reference.get("dataOrigin"),
                "device_type": reference.get("deviceType"),
                "manufacturer": reference.get("manufacturer"),
                "model": reference.get("model"),
            },
        })

    ring_fallback = []
    ring_minutes = set()
    ring_samples = sorted(
        (ring_archive or {}).get("heartRate") or [],
        key=lambda sample: _iso_timestamp_ms(sample.get("timestampUtc")) or 0,
        reverse=True,
    )
    for sample in ring_samples:
        timestamp = _iso_timestamp_ms(sample.get("timestampUtc"))
        try:
            bpm = int(sample.get("bpm"))
        except (TypeError, ValueError):
            continue
        if timestamp is None or not 30 <= bpm <= 220:
            continue
        minute = timestamp // HEART_RATE_SOURCE_MINUTE_MS if timestamp is not None else None
        if minute in occupied_minutes or minute in ring_minutes:
            continue
        ring_minutes.add(minute)
        received_at = _iso_timestamp_ms(sample.get("createdAt")) or timestamp
        ring_fallback.append({
            "id": f"ring-{sample.get('id')}",
            "timestamp": timestamp,
            "received_at": received_at,
            "heart_rate": bpm,
            "status": "ready",
            "source": "smart_ring",
            "source_label": "COLMI Ring",
            "payload": {
                "heart_rate": bpm,
                "source": "colmi-ring",
                "source_mode": sample.get("sourceMode"),
                "collector_source": sample.get("source"),
                "parser": sample.get("parser"),
                "protocol_confidence": sample.get("protocolConfidence"),
            },
        })

    merged = smartwatch + ring_fallback
    merged.sort(
        key=lambda sample: (
            int(sample.get("timestamp") or 0),
            int(sample.get("received_at") or 0),
            str(sample.get("id") or ""),
        ),
        reverse=True,
    )
    return merged[:safe_limit]

ROOT = Path(__file__).resolve().parent
PHONE_TRACKER = PhoneTrackerStore(ROOT / "data" / "phone-tracker.sqlite")
PHONE_ACCESS = PhoneAccessStore(PHONE_TRACKER, READING_STORE, CLEANING_STORE)
LANGUAGE_STORE = LanguageStore(ROOT / "data" / "language-learning.sqlite")
LANGUAGE_SERVICE = LanguageService(LANGUAGE_STORE)
LANGUAGE_REFERENCE_PATHS = resolve_reference_paths(project_root=ROOT)
LANGUAGE_SERVICE.attach_reference_lexicon_service(
    ReferenceLexiconService(LANGUAGE_REFERENCE_PATHS.database)
)
LANGUAGE_SERVICE.attach_cloze_service(ClozeService(LANGUAGE_SERVICE, LANGUAGE_REFERENCE_PATHS.database))
LANGUAGE_SENTENCE_AUDIO = ClozeAudioService(
    LANGUAGE_STORE, ROOT / "data" / "audio" / "language-learning",
)
LANGUAGE_SERVICE.attach_cloze_audio_service(LANGUAGE_SENTENCE_AUDIO)
LANGUAGE_SERVICE.attach_generated_audio_service(
    GeneratedTextAudioService(LANGUAGE_STORE, LANGUAGE_SENTENCE_AUDIO)
)
LANGUAGE_SERVICE.attach_word_audio_service(
    WordAudioService(LANGUAGE_STORE, LANGUAGE_SENTENCE_AUDIO)
)
LANGUAGE_JOBS = LanguageJobManager(LANGUAGE_SERVICE)
AI_USAGE_SERVICE = AIUsageService(ROOT / "data" / "ai-usage.sqlite")
FEELINGS_SERVICE = default_feelings_service(ROOT)
RING_COLLECTOR = create_ring_collector(ROOT)
RING_PHONE_BRIDGE = RingPhoneBridge(
    RING_COLLECTOR.store,
    RING_COLLECTOR.phone_bridge_heartbeat,
    RING_COLLECTOR.phone_bridge_profile,
)
LIVE_WORKOUT_STORE = LiveWorkoutStore(ROOT / "data" / "live-workout.sqlite")
STRENGTH_STORE = StrengthStore(ROOT / "data" / "strength.sqlite")
LIVE_WORKOUT_WEAR_DETECTOR = HeartRateWearDetector()
LIVE_WORKOUT_PLAN_SERVICE = LiveWorkoutPlan(ROOT / "data" / "live-workout-plan.json")
JOURNAL_HTR = get_journal_htr_service(ROOT)
JOURNAL_HTR_RUNTIME = JournalHtrRuntimeController(
    ROOT,
    on_started=JOURNAL_HTR.start_runtime,
    on_stopped=JOURNAL_HTR.stop_runtime,
)
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
COMMONS_API_URL = "https://commons.wikimedia.org/w/api.php"
POSTERS_DIR = ROOT / "public" / "posters"
POSTER_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
COVERS_DIR = ROOT / "covers"
COVER_MIME_EXT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
COVER_FILE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
COVER_MAX_BYTES = 8 * 1024 * 1024
BM365_API_BASE = os.environ.get(
    "BM365_API_BASE",
    "https://script.google.com/macros/s/AKfycbzcvpZ78Zw6yZdt7owKjEkiZvpqHPf_I2JKqRV5M1Ny2_702SpGrUTMAmm_DL7Av_rX/exec",
)
BM365_SHEETS_SYNCER = Bm365SheetsSyncer(BM365_STORE, BM365_API_BASE)
BM365_ITUNES_URL = "https://itunes.apple.com/search"
BM365_MB_URL = "https://musicbrainz.org/ws/2/release/"
BM365_CAA_URL = "https://coverartarchive.org/release/"
BM365_MB_MIN_DELAY = 1.1
BM365_MB_LAST_CALL = 0.0
BM365_DEFAULT_SHEET_ID = "1pHhF5Wh4Bj-akpOoolOnbhf6z577Gae9G4mRb8HBpoM"
BM365_DEFAULT_SHEET_NAME = "main"
BM365_RELEASE_YEARS_CACHE_TTL = 300
BM365_RELEASE_YEARS_CACHE = {"rows": None, "fetched_at": 0.0}
BM365_RELEASE_YEARS_CACHE_LOCK = threading.Lock()
BRUTAL_ASSAULT_2027_RATINGS = BrutalAssaultRatingEnricher(BRUTAL_ASSAULT_2027_STORE)
BRUTAL_ASSAULT_2027_MONITOR = BrutalAssaultMonitor(logger=lambda message: log_line(message, tag="api", level="warn"))
OSCARS_DATA_DIR = ROOT / "data" / "oscars"
FILMS_DATA_DIR = ROOT / "data" / "films"
FILMS_SNAPSHOT_PATH = FILMS_DATA_DIR / "library.json"
CLASSICAL_DATA_DIR = ROOT / "data" / "classical-library"
CLASSICAL_COMPOSERS_DIR = CLASSICAL_DATA_DIR / "composers"
CLASSICAL_COMPOSER_INDEX = CLASSICAL_COMPOSERS_DIR / "index.json"
CLASSICAL_PROGRESS_PATH = CLASSICAL_DATA_DIR / "progress" / "progress.json"
CLASSICAL_KNOWN_COMPOSERS_PATH = CLASSICAL_DATA_DIR / "known-composers.json"
CLASSICAL_PUBLIC_ASSETS_DIR = ROOT / "public" / "assets" / "composers"
CLASSICAL_ASSETS_DIR = ROOT / "assets" / "composers"
CLASSICAL_RYM_UPLOADS_DIR = CLASSICAL_DATA_DIR / "raw" / "rym" / "uploads"
CLASSICAL_IMAGE_MAX_BYTES = 8 * 1024 * 1024
CLASSICAL_RYM_HTML_MAX_BYTES = 15 * 1024 * 1024
CLASSICAL_IMAGE_MIME_EXT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/svg+xml": ".svg",
}
WINNERS_CSV_URL = "https://huggingface.co/datasets/ceyyyh/oscar_award_winners/resolve/main/oscars_1929_2025.csv"
WINNERS_CACHE = OSCARS_DATA_DIR / "oscars_1929_2025.csv"
WINNERS_CACHE_TTL = 60 * 60 * 24 * 30
WIKIPEDIA_API_URL = "https://en.wikipedia.org/w/api.php"
PL_WIKIPEDIA_API_URL = "https://pl.wikipedia.org/w/api.php"
HABIT_UPLOAD_MAX_BYTES = 64 * 1024 * 1024
HABIT_DB_DIR = ROOT / "data" / "raw" / "db"
HABIT_CSV_DIR = ROOT / "data" / "raw" / "csv" / "uploads"
HABIT_BUILD_SCRIPT = ROOT / "scripts" / "build-habits.py"
HABIT_DATA_JS = ROOT / "js" / "habit-data.js"
HABIT_DATA_JSON = ROOT / "data" / "habit-data.json"
HABIT_CONFLICTS_JSON = ROOT / "data" / "conflicts.json"
HABIT_REPORT_JSON = ROOT / "data" / "report.json"
HABIT_REPORT_HTML = ROOT / "data" / "report.html"
TIMELINE_ACTIVITY = TimelineActivityService(
    ROOT,
    JOURNAL_STORE,
    LASTFM_STORE,
    READING_STORE,
    CLEANING_STORE,
)
JOURNAL_CONTEXT = JournalContextService(TIMELINE_STORE, TIMELINE_ACTIVITY)
SCALE_DATA_DIR = ROOT / "data" / "scale"
SCALE_LATEST_JSON = SCALE_DATA_DIR / "latest.json"
SCALE_SIGNAL_JSON = SCALE_DATA_DIR / "signal.json"
SCALE_MEASUREMENTS_CSV = SCALE_DATA_DIR / "scale_measurements.csv"
REALISTIC_WEIGHT_MIN_KG = 30.0
REALISTIC_WEIGHT_MAX_KG = 300.0
STEPS_JSON = SCALE_DATA_DIR / "steps.json"
SENSOR_DATA_DIR = ROOT / "data" / "sensor"
SENSOR_LATEST_JSON = SENSOR_DATA_DIR / "latest.json"
SENSOR_READINGS_JSONL = SENSOR_DATA_DIR / "readings.jsonl"
HEALTH_DATA_DIR = ROOT / "data" / "health-connect"
HEALTH_LATEST_JSON = HEALTH_DATA_DIR / "latest.json"
HEALTH_SNAPSHOTS_JSONL = HEALTH_DATA_DIR / "snapshots.jsonl"
DIET_DATA_DIR = ROOT / "data" / "diet"
DIET_JSON = DIET_DATA_DIR / "diet.json"
DIET_DEFAULT_GOAL_KCAL = 2200
BUDGET_JSON = ROOT / "data" / "budget.json"
BUDGET_DB = ROOT / "data" / "finance.sqlite"
BUDGET_IMPORT_MAX_BYTES = 12 * 1024 * 1024
# JSON/base64 overhead for the 24 MiB decoded receipt bundle limit.
RECEIPT_IMPORT_MAX_BYTES = 34 * 1024 * 1024
FINANCE_SERVICE = FinanceService(
    BUDGET_DB,
    legacy_json_path=BUDGET_JSON,
    backup_directory=ROOT / "data" / "budget-backups",
)
JOBHUNT_SERVICE = JobhuntService(
    ROOT / "data" / "jobhunt.sqlite",
    private_root=ROOT / "data" / "jobhunt",
)
JOBHUNT_WORKER = JobhuntWorker(JOBHUNT_SERVICE)
SETTINGS_DATA_DIR = ROOT / "data" / "settings"
SETTINGS_ALLOWED_NAMES = {
    "bills",
    "dashboard",
    "live-workout-plan",
    "todo",
    "reading",
    "reading-history",
    "cleaning",
    "events",
    "network",
}
ARTIST_FACTS_DIR = ROOT / "data" / "spotify" / "artist-facts"
ARTIST_MEDIA_CACHE_DIR = ROOT / "data" / "spotify" / "artist-media-cache"
ARTIST_MEDIA_CACHE_TTL = 60 * 60 * 24 * 7
ARTIST_MEDIA_MAX_BYTES = 8 * 1024 * 1024
EVENTS_JSON = ROOT / "data" / "events.json"
EVENT_COUNTDOWN_SETTINGS_JSON = SETTINGS_DATA_DIR / "events.json"
EVENT_COUNTDOWN_CATEGORY_LABELS = {
    "album_release": "Album release",
    "match": "Match",
    "hockey_match": "Mecz hokejowy",
    "stadium_match": "Match (going to the stadium)",
    "concert": "Concert",
    "new_episode": "New episode",
    "phases_of_the_moon": "Phases of the Moon",
}
EVENT_COUNTDOWN_CATEGORIES = set(EVENT_COUNTDOWN_CATEGORY_LABELS)
EVENT_PUBLIC_COVERS_DIR = ROOT / "public" / "assets" / "events"
EVENT_COVERS_DIR = ROOT / "assets" / "events"
KITCHEN_SCORES_JSON = ROOT / "data" / "kitchen-scores.json"
KITCHEN_SETTINGS_JSON = ROOT / "data" / "kitchen-settings.json"
KITCHEN_LEAGUES_CATALOG_JSON = ROOT / "data" / "kitchen-leagues.json"
KITCHEN_TEAM_CRESTS_JSON = ROOT / "data" / "kitchen-team-crests.json"
FOOTBALL_DIAGNOSTICS_JSON = ROOT / "data" / "football-diagnostics.json"
FOOTBALL_SETTINGS_JSON = ROOT / "data" / "football-settings.json"
FOOTBALL_REQUEST_CONTROL = FootballRequestControl()
_FOOTBALL_STORE = None
_FOOTBALL_STORE_LOCK = threading.Lock()
KITCHEN_SCORES_SCHEMA_VERSION = 19
KITCHEN_LEAGUES_CATALOG_SCHEMA_VERSION = 7
KITCHEN_SCORES_CACHE_TTL = 30 * 60
KITCHEN_LEAGUES_CACHE_TTL = 60 * 60 * 24
KITCHEN_STANDINGS_CACHE_TTL = 6 * 60 * 60
KITCHEN_NEXT_MATCHES_CACHE_TTL = 2 * 60 * 60
KITCHEN_LEAGUE_BADGE_CACHE = {}
KITCHEN_LEAGUE_BADGES = {
    "nhl": "https://r2.thesportsdb.com/images/media/league/badge/4cem2k1619616539.png",
    "champions-league": "https://r2.thesportsdb.com/images/media/league/badge/facv1u1742998896.png",
    "conference-league": "https://r2.thesportsdb.com/images/media/league/badge/ymfo5j1718775759.png",
    "ekstraklasa": "https://r2.thesportsdb.com/images/media/league/badge/l3jovw1516960585.png",
    "polish-i-liga": "https://r2.thesportsdb.com/images/media/league/badge/kf2y521760289353.png",
    "polish-ii-liga": "https://r2.thesportsdb.com/images/media/league/badge/ck3xnx1760289040.png",
    "europa-league": "https://r2.thesportsdb.com/images/media/league/badge/mlsr7d1718774547.png",
    "fa-cup": "https://r2.thesportsdb.com/images/media/league/badge/vk7isd1598802862.png",
    "premier-league": "https://r2.thesportsdb.com/images/media/league/badge/gasy9d1737743125.png",
    "world-cup": "https://r2.thesportsdb.com/images/media/league/badge/e7er5g1696521789.png",
}
KITCHEN_TEAM_CRESTS = {
    "besiktas": "https://upload.wikimedia.org/wikipedia/commons/d/da/BesiktasJK-Logo.svg",
    "hearts": "https://r2.thesportsdb.com/images/media/team/badge/twqvyt1447597939.png",
    "liverpool": "https://r2.thesportsdb.com/images/media/team/badge/kfaher1737969724.png",
    "montreal-canadiens": "https://a.espncdn.com/i/teamlogos/nhl/500/mtl.png",
    "poland": "https://a.espncdn.com/i/teamlogos/countries/500/pol.png",
    "wieczysta-krakow": "https://r2.thesportsdb.com/images/media/team/badge/sjv7bd1750699486.png",
    "hutnik-krakow": "https://r2.thesportsdb.com/images/media/team/badge/zxp6oq1760232608.png",
}
NATIONAL_TOURNAMENT_BADGES = {
    "uefa-euro": "https://upload.wikimedia.org/wikipedia/commons/b/b5/UEFA_logo.svg",
    "copa-america": "https://upload.wikimedia.org/wikipedia/commons/5/55/Copa_America_wordmark.svg",
    "afcon": "https://upload.wikimedia.org/wikipedia/en/c/cf/Africa_Cup_of_Nation_official_logo.png",
    "afc-asian-cup": "https://upload.wikimedia.org/wikipedia/en/4/4d/AFC_Asian_Cup.png",
    "concacaf-gold-cup": "https://upload.wikimedia.org/wikipedia/commons/b/b5/Concacaf_Gold_Cup_2021.svg",
    "ofc-nations-cup": "https://upload.wikimedia.org/wikipedia/commons/c/c5/OFC_Nations_Cup_%282012%29.svg",
    "uefa-nations-league": "https://upload.wikimedia.org/wikipedia/en/8/80/UEFA_Nations_League.svg",
    "concacaf-nations-league": "https://upload.wikimedia.org/wikipedia/commons/e/ec/Concacaf_Nations_League_logo.svg",
    "cafa-nations-cup": "https://upload.wikimedia.org/wikipedia/commons/b/be/Central_Asian_Football_Association_%282025%29.png",
    "uefa-euro-qualifiers": "https://upload.wikimedia.org/wikipedia/commons/b/b5/UEFA_logo.svg",
    "fifa-world-cup-qualifiers": "https://upload.wikimedia.org/wikipedia/commons/a/aa/FIFA_logo_without_slogan.svg",
    "afcon-qualifiers": "https://upload.wikimedia.org/wikipedia/commons/3/3f/Caf_llogo.svg",
    "fifa-u20-world-cup": "https://upload.wikimedia.org/wikipedia/commons/c/c4/FIFA_U-20_World_Cup.svg",
    "fifa-u17-world-cup": "https://upload.wikimedia.org/wikipedia/commons/1/15/Trophy_U17.png",
    "uefa-u21-championship": "https://upload.wikimedia.org/wikipedia/en/9/92/UEFA_European_Under-21_Championship_logo.svg",
    "uefa-u19-championship": "https://upload.wikimedia.org/wikipedia/en/6/6c/UEFA_European_Under-19_Football_Championship_logo.svg",
    "uefa-u17-championship": "https://upload.wikimedia.org/wikipedia/en/3/31/UEFA_European_Under-17_Championship_logo.svg",
    "eaff-e1": "https://upload.wikimedia.org/wikipedia/en/7/73/2017_EAFF_E-1_Football_Championship.png",
    "saff-championship": "https://upload.wikimedia.org/wikipedia/commons/b/b1/Logo_of_South_Asian_Football_Federation.svg",
    "waff-championship": "https://upload.wikimedia.org/wikipedia/commons/9/98/West_Asian_Football_Federation_logo_2023.svg",
    "asean-championship": "https://upload.wikimedia.org/wikipedia/commons/b/b4/ASEAN_Football_Championship_Cup.svg",
    "conifa-world-football-cup": "https://upload.wikimedia.org/wikipedia/commons/7/76/CONIFA_logotype.png",
    "conifa-european-football-cup": "https://upload.wikimedia.org/wikipedia/commons/7/76/CONIFA_logotype.png",
    "conifa-africa-football-cup": "https://upload.wikimedia.org/wikipedia/commons/7/76/CONIFA_logotype.png",
    "conifa-asia-football-cup": "https://upload.wikimedia.org/wikipedia/commons/7/76/CONIFA_logotype.png",
    "conifa-south-america-football-cup": "https://upload.wikimedia.org/wikipedia/commons/7/76/CONIFA_logotype.png",
    "island-games": "https://upload.wikimedia.org/wikipedia/commons/1/18/2027_Island_Games_logo.svg",
}
THESPORTSDB_API_BASE = "https://www.thesportsdb.com/api/v1/json/123"
API_FOOTBALL_BASE = "https://v3.football.api-sports.io"
ESPN_SCOREBOARD_BASE = "https://site.web.api.espn.com/apis/site/v2/sports"
ESPN_WEB_BASE = "https://site.web.api.espn.com/apis/v2/sports"
BBC_FOOTBALL_TABLE_SLUGS = {
    "ekstraklasa": "polish-ekstraklasa",
}
FIFA_WORLD_CUP_2026 = {
    "key": "fifa-world-cup-2030",
    "leagueKey": "world-cup",
    "leagueName": "FIFA World Cup 2030",
    "eyebrow": "FIFA World Cup 2030",
    "title": "Nastepny mundial",
    "matchupTitle": "Otwarcie: 13-14 czerwca 2030",
    "kickoffAt": "2030-06-13T00:00:00+02:00",
    "displayDate": "13-14 czerwca 2030",
    "venue": "Morocco / Portugal / Spain",
    "city": "plus mecze stulecia w Argentina / Paraguay / Uruguay",
    "image": "https://upload.wikimedia.org/wikipedia/commons/a/aa/FIFA_logo_without_slogan.svg",
    "lockupImage": "https://upload.wikimedia.org/wikipedia/commons/a/aa/FIFA_logo_without_slogan.svg",
    "home": {},
    "away": {},
}
FIFA_WORLD_CUP_2026_NEXT_WINDOW_HOURS = 24
CONIFA_EURO_2026_KEY = "conifa-european-football-cup"
CONIFA_EURO_2026_WIKI_PAGE = "2026_CONIFA_European_Football_Cup"
CONIFA_EURO_2026_NEXT_WINDOW_HOURS = 24
CONIFA_EURO_2026_TEAM_CRESTS = {
    "rouet-provence": "https://www.conifa.org/en/wp-content/uploads/2026/04/rouet.png",
    "ff rouet provence": "https://www.conifa.org/en/wp-content/uploads/2026/04/rouet.png",
    "canton ticino": "https://www.conifa.org/en/wp-content/uploads/2022/09/Canton-Ticino.png",
    "raetia": "https://www.conifa.org/en/wp-content/uploads/2021/05/members-raetia-logo-259x259-1.png",
    "padania": "https://www.conifa.org/en/wp-content/uploads/2021/05/members-padania-logo.png",
    "greenland": "https://www.conifa.org/en/wp-content/uploads/2025/10/Greenland_Football_Association.svg.png",
    "greenland fa": "https://www.conifa.org/en/wp-content/uploads/2025/10/Greenland_Football_Association.svg.png",
    "northern cyprus": "https://www.conifa.org/en/wp-content/uploads/2021/05/members-northern-cyprus-logo.png",
    "north cyprus": "https://www.conifa.org/en/wp-content/uploads/2021/05/members-northern-cyprus-logo.png",
}
OPEN_METEO_KITCHEN_URL = (
    "https://api.open-meteo.com/v1/forecast"
    f"?latitude={os.environ.get('WEATHER_LATITUDE', '50.0614')}"
    f"&longitude={os.environ.get('WEATHER_LONGITUDE', '19.9366')}"
    "&current=temperature_2m,relative_humidity_2m,apparent_temperature,"
    "precipitation,cloud_cover,weather_code,wind_speed_10m,wind_gusts_10m"
    "&timezone=Europe%2FWarsaw"
)
GIOS_AQI_PATH = "pjp-api/v1/rest/aqindex/getIndex/400"
GIOS_AQI_URLS = [
    f"https://gios.kamil36s.workers.dev/gios/{GIOS_AQI_PATH}",
    f"https://api.gios.gov.pl/{GIOS_AQI_PATH}",
]
KITCHEN_DEFAULT_CLOZEMASTER_URL = "https://www.clozemaster.com/l/ita-eng/collections/travel-essentials/play?skill=vocabulary&mode=multiple_choice&count=50"
KITCHEN_RECIPE_MAX_LENGTH = 100_000
KITCHEN_WINDOW_HOUR_OPTIONS = [24, 48, 72, 96, 168]
KITCHEN_DEFAULT_WINDOW_HOURS = 24
KITCHEN_TIMEZONE = ZoneInfo("Europe/Warsaw")
COUNTRY_PL_NAMES = {
    "england": "Anglia",
    "germany": "Niemcy",
    "italy": "Włochy",
    "spain": "Hiszpania",
    "france": "Francja",
    "greece": "Grecja",
    "netherlands": "Holandia",
    "the netherlands": "Holandia",
    "holland": "Holandia",
    "belgium": "Belgia",
    "poland": "Polska",
    "turkey": "Turcja",
    "turkiye": "Turcja",
    "türkiye": "Turcja",
    "saudi arabia": "Arabia Saudyjska",
    "brazil": "Brazylia",
    "portugal": "Portugalia",
    "czech republic": "Czechy",
    "czechia": "Czechy",
    "mexico": "Meksyk",
    "denmark": "Dania",
    "sweden": "Szwecja",
    "norway": "Norwegia",
    "finland": "Finlandia",
    "switzerland": "Szwajcaria",
    "serbia": "Serbia",
    "croatia": "Chorwacja",
    "austria": "Austria",
    "ukraine": "Ukraina",
    "azerbaijan": "Azerbejdżan",
    "bulgaria": "Bułgaria",
    "slovenia": "Słowenia",
    "hungary": "Węgry",
    "iceland": "Islandia",
    "slovakia": "Słowacja",
    "scotland": "Szkocja",
    "usa": "USA",
    "united states": "USA",
    "canada": "Kanada",
    "world": "Świat",
    "international": "Świat",
}
NHL_TEAM_FACTS = {
    "canadiens": "Montreal Canadiens to najbardziej utytulowany klub NHL: 24 Puchary Stanleya.",
    "maple leafs": "Toronto Maple Leafs maja jedna z najstarszych i najbardziej wymagajacych fanbaz w lidze.",
    "bruins": "Boston Bruins byli pierwsza amerykanska druzyna w NHL.",
    "rangers": "New York Rangers sa czescia Original Six, czyli klasycznej szostki najstarszych marek NHL.",
    "red wings": "Detroit Red Wings przez dekady slyneli z europejskiego stylu gry i swietnego skautingu.",
    "blackhawks": "Chicago Blackhawks to Original Six i klub z jedna z najbardziej rozpoznawalnych koszulek w hokeju.",
    "oilers": "Edmonton Oilers to klub Wayne'a Gretzky'ego i Connor McDavida: szybki, ofensywny hokej.",
    "penguins": "Pittsburgh Penguins kojarza sie z Mario Lemieux i Sidneyem Crosbym, dwoma ikonami centrow.",
    "avalanche": "Colorado Avalanche zwykle graja bardzo szybki hokej oparty na mobilnych obroncach.",
    "golden knights": "Vegas Golden Knights wygrali Puchar Stanleya juz w szostym sezonie istnienia.",
    "kraken": "Seattle Kraken to mloda marka NHL, nazwana od morskiego mitu z Pacyfiku.",
}
NHL_GENERIC_FACTS = [
    "W NHL zmiany sa krotkie: jedna zmiana napastnika czesto trwa tylko okolo 40-50 sekund.",
    "Power play oznacza gre w przewadze po karze rywala; penalty kill to bronienie oslabienia.",
    "Hat trick w hokeju to trzy gole jednego zawodnika w meczu, a kibice tradycyjnie rzucaja czapki na lod.",
    "Bramkarz moze zostac zdjety pod koniec meczu, zeby druzyna miala dodatkowego gracza w polu.",
]
KITCHEN_LEAGUES = [
    {
        "key": "premier-league",
        "name": "Premier League",
        "type": "competition",
        "sport": "Soccer",
        "standing": {"provider": "espn", "sport": "soccer", "league": "eng.1"},
        "espn_sport": "soccer",
        "espn_league": "eng.1",
        "api_football_id": 39,
        "thesportsdb_id": 4328,
    },
    {
        "key": "ekstraklasa",
        "name": "Ekstraklasa",
        "type": "competition",
        "sport": "Soccer",
        "standing": {"provider": "thesportsdb"},
        "api_football_id": 106,
        "thesportsdb_id": 4422,
    },
    {
        "key": "polish-i-liga",
        "name": "Polska I liga",
        "type": "competition",
        "sport": "Soccer",
        "standing": {"provider": "thesportsdb"},
        "thesportsdb_id": 4661,
    },
    {
        "key": "polish-ii-liga",
        "name": "Polska II liga",
        "type": "competition",
        "sport": "Soccer",
        "standing": {"provider": "thesportsdb"},
        "thesportsdb_id": 5709,
    },
    {
        "key": "besiktas",
        "name": "Beşiktaş",
        "type": "team",
        "sport": "Soccer",
        "thesportsdb_team_id": 133794,
    },
    {
        "key": "hearts",
        "name": "Hearts",
        "type": "team",
        "sport": "Soccer",
        "thesportsdb_team_id": 133643,
        "espn_sport": "soccer",
        "espn_league": "sco.1",
        "competitionName": "Scottish Premiership",
        "espn_team_names": ["Heart of Midlothian", "Hearts"],
    },
    {
        "key": "montreal-canadiens",
        "name": "Montreal Canadiens",
        "type": "team",
        "sport": "Ice Hockey",
        "espn_sport": "hockey",
        "espn_league": "nhl",
        "espn_team_names": ["Montreal Canadiens", "Canadiens"],
        "crest": "https://a.espncdn.com/i/teamlogos/nhl/500/mtl.png",
    },
    {
        "key": "wieczysta-krakow",
        "name": "Wieczysta Kraków",
        "type": "team",
        "sport": "Soccer",
        "thesportsdb_team_id": 152462,
    },
    {
        "key": "hutnik-krakow",
        "name": "Hutnik Kraków",
        "type": "team",
        "sport": "Soccer",
        "thesportsdb_team_id": 153534,
    },
    {
        "key": "champions-league",
        "name": "Champions League",
        "type": "competition",
        "sport": "Soccer",
        "season": "2026-2027",
        "api_football_id": 2,
        "thesportsdb_id": 4480,
        "standing": {"provider": "espn", "sport": "soccer", "league": "uefa.champions"},
        "leaguePhaseTable": True,
    },
    {
        "key": "europa-league",
        "name": "Europa League",
        "type": "competition",
        "sport": "Soccer",
        "season": "2026-2027",
        "api_football_id": 3,
        "thesportsdb_id": 4481,
        "standing": {"provider": "espn", "sport": "soccer", "league": "uefa.europa"},
        "leaguePhaseTable": True,
    },
    {
        "key": "conference-league",
        "name": "Conference League",
        "type": "competition",
        "sport": "Soccer",
        "season": "2026-2027",
        "api_football_id": 848,
        "thesportsdb_id": 5071,
        "standing": {"provider": "espn", "sport": "soccer", "league": "uefa.europa.conf"},
        "leaguePhaseTable": True,
    },
    {
        "key": "fa-cup",
        "name": "FA Cup",
        "type": "competition",
        "sport": "Soccer",
        "api_football_id": 45,
        "thesportsdb_id": 4482,
        "country": "Anglia",
        "roundType": "cup",
    },
    {
        "key": "world-cup",
        "name": "FIFA World Cup",
        "type": "competition",
        "sport": "Soccer",
        "thesportsdb_id": 4429,
        "espn_sport": "soccer",
        "espn_league": "fifa.world",
        "nextTournament": {
            "status": "confirmed",
            "dateLabel": "13-14 czerwca 2030 - otwarcie",
            "host": "Maroko, Portugalia i Hiszpania; mecze stulecia w Argentynie, Paragwaju i Urugwaju",
            "startDate": "2030-06-13",
            "endDate": "2030-07-21",
            "sourceLabel": "FIFA",
            "note": "FIFA potwierdza okno otwarcia 13-14 czerwca 2030; konkretne pary i godziny przyjda pozniej.",
        },
    },
    {
        "key": "nhl",
        "name": "NHL",
        "type": "competition",
        "sport": "Ice Hockey",
        "espn_sport": "hockey",
        "espn_league": "nhl",
        "thesportsdb_id": 4380,
    },
]
KITCHEN_LEAGUES.extend([
    {"key": "efl-cup", "name": "Carabao Cup", "type": "competition", "sport": "Soccer", "thesportsdb_id": 4570, "badge": "https://r2.thesportsdb.com/images/media/league/badge/x1va771565372556.png", "country": "Anglia", "roundType": "cup"},
    {"key": "polish-cup", "name": "Puchar Polski", "type": "competition", "sport": "Soccer", "thesportsdb_id": 5838, "badge": "https://r2.thesportsdb.com/images/media/league/badge/t5x8f41772206659.png", "country": "Polska", "roundType": "cup"},
    {"key": "mls", "name": "MLS", "type": "competition", "sport": "Soccer", "thesportsdb_id": 4346, "badge": "https://r2.thesportsdb.com/images/media/league/badge/dqo6r91549878326.png", "country": "USA/Kanada", "seasonMode": "year"},
    {"key": "brasileirao", "name": "Brasileirão Série A", "type": "competition", "sport": "Soccer", "thesportsdb_id": 4351, "badge": "https://r2.thesportsdb.com/images/media/league/badge/lywv7t1766787179.png", "country": "Brazylia", "seasonMode": "year"},
    {"key": "liga-portugal", "name": "Liga Portugal", "type": "competition", "sport": "Soccer", "thesportsdb_id": 4344, "badge": "https://r2.thesportsdb.com/images/media/league/badge/lkfko71751917970.png", "country": "Portugalia"},
    {"key": "turkish-super-lig", "name": "Süper Lig", "type": "competition", "sport": "Soccer", "thesportsdb_id": 4339, "badge": "https://r2.thesportsdb.com/images/media/league/badge/h7xx231601671132.png", "country": "Turcja"},
    {"key": "saudi-pro-league", "name": "Saudi Pro League", "type": "competition", "sport": "Soccer", "thesportsdb_id": 4668, "badge": "https://r2.thesportsdb.com/images/media/league/badge/w67i621701772123.png", "country": "Arabia Saudyjska"},
    {"key": "czech-first-league", "name": "Czech First League", "type": "competition", "sport": "Soccer", "thesportsdb_id": 4631, "badge": "https://r2.thesportsdb.com/images/media/league/badge/4v9f4d1725904127.png", "country": "Czechy"},
    {"key": "liga-mx", "name": "Liga MX", "type": "competition", "sport": "Soccer", "thesportsdb_id": 4350, "badge": "https://r2.thesportsdb.com/images/media/league/badge/mav5rx1686157960.png", "country": "Meksyk"},
    {"key": "danish-superliga", "name": "Danish Superliga", "type": "competition", "sport": "Soccer", "thesportsdb_id": 4340, "badge": "https://r2.thesportsdb.com/images/media/league/badge/28uq381687624585.png", "country": "Dania"},
    {"key": "swedish-allsvenskan", "name": "Swedish Allsvenskan", "type": "competition", "sport": "Soccer", "thesportsdb_id": 4347, "badge": "https://r2.thesportsdb.com/images/media/league/badge/denok11707459183.png", "country": "Szwecja", "seasonMode": "year"},
    {"key": "norwegian-eliteserien", "name": "Norwegian Eliteserien", "type": "competition", "sport": "Soccer", "thesportsdb_id": 4358, "badge": "https://r2.thesportsdb.com/images/media/league/badge/owo80l1512822583.png", "country": "Norwegia", "seasonMode": "year"},
    {"key": "finnish-veikkausliiga", "name": "Finnish Veikkausliiga", "type": "competition", "sport": "Soccer", "thesportsdb_id": 4636, "badge": "https://r2.thesportsdb.com/images/media/league/badge/s9v1tg1742782748.png", "country": "Finlandia", "seasonMode": "year"},
    {"key": "swiss-super-league", "name": "Swiss Super League", "type": "competition", "sport": "Soccer", "thesportsdb_id": 4675, "badge": "https://r2.thesportsdb.com/images/media/league/badge/id6q2r1635867584.png", "country": "Szwajcaria"},
    {"key": "serbian-super-liga", "name": "Serbian Super Liga", "type": "competition", "sport": "Soccer", "thesportsdb_id": 4671, "badge": "https://r2.thesportsdb.com/images/media/league/badge/lu8cvs1578940052.png", "country": "Serbia"},
    {"key": "croatian-first-league", "name": "Croatian First Football League", "type": "competition", "sport": "Soccer", "thesportsdb_id": 4629, "badge": "https://r2.thesportsdb.com/images/media/league/badge/b3svsa1686819371.png", "country": "Chorwacja"},
    {"key": "austrian-bundesliga", "name": "Austrian Bundesliga", "type": "competition", "sport": "Soccer", "thesportsdb_id": 4621, "badge": "https://r2.thesportsdb.com/images/media/league/badge/vcgyu71686617925.png", "country": "Austria"},
    {"key": "ukrainian-premier-league", "name": "Ukrainian Premier League", "type": "competition", "sport": "Soccer", "thesportsdb_id": 4354, "badge": "https://r2.thesportsdb.com/images/media/league/badge/qprvpy1471773025.png", "country": "Ukraina"},
    {"key": "azerbaijani-premier-league", "name": "Azerbaijani Premier League", "type": "competition", "sport": "Soccer", "thesportsdb_id": 4693, "badge": "https://r2.thesportsdb.com/images/media/league/badge/urt6hw1614346226.png", "country": "Azerbejdżan"},
    {"key": "bulgarian-first-league", "name": "Bulgarian First League", "type": "competition", "sport": "Soccer", "thesportsdb_id": 4626, "badge": "https://r2.thesportsdb.com/images/media/league/badge/nujbma1730047938.png", "country": "Bułgaria"},
    {"key": "slovenian-prvaliga", "name": "Slovenian 1. SNL", "type": "competition", "sport": "Soccer", "thesportsdb_id": 4692, "badge": "https://r2.thesportsdb.com/images/media/league/badge/t1v1s91635866998.png", "country": "Słowenia"},
    {"key": "hungarian-nb-i", "name": "Hungarian NB I", "type": "competition", "sport": "Soccer", "thesportsdb_id": 4690, "badge": "https://r2.thesportsdb.com/images/media/league/badge/7o3q3t1616017529.png", "country": "Węgry"},
    {"key": "icelandic-urvalsdeild", "name": "Icelandic Úrvalsdeild karla", "type": "competition", "sport": "Soccer", "thesportsdb_id": 4642, "badge": "https://r2.thesportsdb.com/images/media/league/badge/zvg1hs1760654850.png", "country": "Islandia", "seasonMode": "year"},
    {"key": "slovak-first-league", "name": "Slovak First Football League", "type": "competition", "sport": "Soccer", "thesportsdb_id": 4672, "badge": "https://r2.thesportsdb.com/images/media/league/badge/sxh5831689798996.png", "country": "Słowacja"},
    {"key": "german-2-bundesliga", "name": "2. Bundesliga", "type": "competition", "sport": "Soccer", "thesportsdb_id": 4399, "badge": "https://r2.thesportsdb.com/images/media/league/badge/hl40981534764789.png", "country": "Niemcy"},
    {"key": "italian-serie-b", "name": "Serie B", "type": "competition", "sport": "Soccer", "thesportsdb_id": 4394, "badge": "https://r2.thesportsdb.com/images/media/league/badge/uf5kph1598011132.png", "country": "Włochy"},
    {"key": "spanish-la-liga-2", "name": "LaLiga 2", "type": "competition", "sport": "Soccer", "thesportsdb_id": 4400, "badge": "https://r2.thesportsdb.com/images/media/league/badge/r7u6821688425700.png", "country": "Hiszpania"},
])

def national_tournament(
    key,
    name,
    group,
    date_label=None,
    host=None,
    start_date=None,
    end_date=None,
    source_label="",
    note="",
    badge=None,
):
    date_text = (date_label or "").lower()
    has_specific_dates = bool(re.search(r"\d{1,2}\s*(?:[a-ząćęłńóśźż]+)?\s*[-–]\s*\d{1,2}\s+[a-ząćęłńóśźż]+", date_text))
    missing_host = (
        not host
        or "do potwierdzenia" in host.lower()
        or "do wyboru" in host.lower()
        or "brak potwierdzonego" in host.lower()
        or "zostanie" in host.lower()
    )
    missing_dates = not date_label or not has_specific_dates or "tbc" in date_text or "brak potwierdzonych" in date_text
    meta = {
        "status": "confirmed" if not missing_dates and not missing_host else "unconfirmed",
        "dateLabel": date_label or "brak potwierdzonych dat",
        "host": host or "brak potwierdzonego gospodarza",
        "sourceLabel": source_label,
        "note": note,
    }
    if start_date:
        meta["startDate"] = start_date
    if end_date:
        meta["endDate"] = end_date
    return {
        "key": key,
        "name": name,
        "type": "competition",
        "sport": "Soccer",
        "settingsGroup": f"Reprezentacje - {group}",
        "roundType": "cup",
        "defaultEnabled": False,
        "badge": badge or NATIONAL_TOURNAMENT_BADGES.get(key, ""),
        "nextTournament": meta,
    }


KITCHEN_LEAGUES.extend([
    national_tournament("uefa-euro", "UEFA EURO", "UEFA", "9 czerwca - 9 lipca 2028", "Anglia, Szkocja, Walia i Irlandia", "2028-06-09", "2028-07-09", "UEFA"),
    national_tournament("copa-america", "Copa America", "CONMEBOL", note="Kolejna edycja nie ma jeszcze oficjalnie potwierdzonego gospodarza i dat."),
    national_tournament("afcon", "Africa Cup of Nations", "CAF", "19 czerwca - 17 lipca 2027", "Kenia, Tanzania i Uganda", "2027-06-19", "2027-07-17", "CAF"),
    national_tournament("afc-asian-cup", "AFC Asian Cup", "AFC", "7 stycznia - 5 lutego 2027", "Arabia Saudyjska: Rijad, Dżudda i Al-Chubar", "2027-01-07", "2027-02-05", "AFC"),
    national_tournament("concacaf-gold-cup", "CONCACAF Gold Cup", "CONCACAF", "lato 2027", "gospodarz do potwierdzenia", "2027-06-01", "2027-08-31", "CONCACAF", "CONCACAF potwierdził lato 2027, ale nie podał jeszcze dokładnego terminarza."),
    national_tournament("ofc-nations-cup", "OFC Nations Cup", "OFC", "kwalifikacje 2028: daty TBC", "kwalifikacje: Wyspy Cooka", None, None, "OFC", "OFC potwierdził gospodarza kwalifikacji; finały 2028 bez potwierdzonego gospodarza/dat."),
    national_tournament("uefa-nations-league", "UEFA Nations League", "UEFA", "faza ligowa: 24 września - 17 listopada 2026", "mecze domowe i wyjazdowe w Europie", "2026-09-24", "2026-11-17", "UEFA", "Najbliższe kolejki: 24 września - 6 października; finały odbędą się 9-13 czerwca 2027."),
    national_tournament("concacaf-nations-league", "CONCACAF Nations League", "CONCACAF", "marzec 2027", "SoFi Stadium, Inglewood/Los Angeles", "2027-03-01", "2027-03-31", "CONCACAF"),
    national_tournament("cafa-nations-cup", "CAFA Nations Cup", "AFC", note="Edycja 2025 już się odbyła; kolejna edycja 2027 bez potwierdzonych dat/gospodarza."),
    national_tournament("uefa-euro-qualifiers", "UEFA EURO qualifiers", "UEFA", "2027", "mecze domowe i wyjazdowe w Europie", "2027-01-01", "2027-12-31", "UEFA", "Dokładny terminarz kwalifikacji EURO 2028 będzie potwierdzany po losowaniu."),
    national_tournament("fifa-world-cup-qualifiers", "FIFA World Cup qualifiers", "FIFA", note="Kwalifikacje do MŚ 2026 są praktycznie zamknięte; cykl 2030 nie ma jeszcze pełnego potwierdzonego kalendarza."),
    national_tournament("afcon-qualifiers", "AFCON qualifiers", "CAF", "2026-2027", "mecze domowe i wyjazdowe w Afryce", "2026-05-19", "2027-03-31", "CAF", "CAF potwierdził drogę kwalifikacji do AFCON 2027; mecze są rozłożone po oknach międzynarodowych."),
    national_tournament("fifa-u20-world-cup", "FIFA U-20 World Cup", "FIFA", "2027", "Azerbejdżan i Uzbekistan", "2027-01-01", "2027-12-31", "FIFA", "Gospodarze są potwierdzeni; dokładne daty turnieju nie są jeszcze potwierdzone."),
    national_tournament("fifa-u17-world-cup", "FIFA U-17 World Cup", "FIFA", "19 listopada - 13 grudnia 2026", "Katar", "2026-11-19", "2026-12-13", "FIFA"),
    national_tournament("uefa-u21-championship", "UEFA U-21 Championship", "UEFA", "lato 2027", "Albania i Serbia", "2027-06-01", "2027-07-31", "UEFA", "UEFA potwierdziła gospodarzy; dokładne daty finałów są nadal do potwierdzenia."),
    national_tournament("uefa-u19-championship", "UEFA U-19 Championship", "UEFA", "lato 2027", "Czechy", "2027-06-01", "2027-08-31", "UEFA", "UEFA potwierdziła gospodarza; dokładne daty finałów są nadal do potwierdzenia."),
    national_tournament("uefa-u17-championship", "UEFA U-17 Championship", "UEFA", "25 maja - 7 czerwca 2026", "Estonia", "2026-05-25", "2026-06-07", "UEFA"),
    national_tournament("eaff-e1", "EAFF E-1 Football Championship", "AFC", note="Edycja 2025 już się odbyła; kolejna edycja nie ma jeszcze potwierdzonych dat/gospodarza."),
    national_tournament("saff-championship", "SAFF Championship", "AFC", "21 września - 6 października 2026", "Bangladesz", "2026-09-21", "2026-10-06", "SAFF", "Gospodarz według decyzji SAFF; finalny komunikat sponsorki/terminarza może jeszcze doprecyzować szczegóły."),
    national_tournament("waff-championship", "WAFF Championship", "AFC", "listopad 2026", "Oman", "2026-11-01", "2026-11-30", "WAFF", "Potwierdzone ogólne okno miesiąca, bez pełnego terminarza."),
    national_tournament("asean-championship", "ASEAN Championship", "AFC", "lipiec - sierpień 2026", "format dom/wyjazd w regionie ASEAN", "2026-07-01", "2026-08-31", "AFF"),
    national_tournament("conifa-world-football-cup", "CONIFA World Football Cup", "CONIFA", note="Brak potwierdzonego kolejnego turnieju w oficjalnym kalendarzu CONIFA."),
    national_tournament("conifa-european-football-cup", "CONIFA European Football Cup", "CONIFA", "2-6 czerwca 2026", "Padania / Carate Brianza, Wlochy", "2026-06-02", "2026-06-06", "CONIFA", "Terminarz meczow jest pobierany z wikitextu strony turnieju i odswiezany razem z wynikami."),
    national_tournament("conifa-africa-football-cup", "CONIFA Africa Football Cup", "CONIFA", note="Brak potwierdzonych danych o kolejnej edycji."),
    national_tournament("conifa-asia-football-cup", "CONIFA Asia Football Cup", "CONIFA", note="Brak potwierdzonych danych o kolejnej edycji."),
    national_tournament("conifa-south-america-football-cup", "CONIFA South America Football Cup", "CONIFA", note="Brak potwierdzonych danych o kolejnej edycji."),
    national_tournament("island-games", "Island Games", "Inne", "3-9 lipca 2027", "Wyspy Owcze", "2027-07-03", "2027-07-09", "IIGA"),
])
TOURNAMENT_METADATA_OVERRIDES = {
    "copa-america": {
        "status": "unconfirmed",
        "dateLabel": "brak potwierdzonych dat",
        "host": "brak potwierdzonego gospodarza",
        "note": "CONMEBOL nie oglosil jeszcze kolejnej meskiej edycji po Copa America 2024.",
    },
    "afcon": {
        "status": "confirmed",
        "dateLabel": "19 czerwca - 17 lipca 2027",
        "host": "Kenia, Tanzania i Uganda",
        "startDate": "2027-06-19",
        "endDate": "2027-07-17",
        "note": "CAF potwierdzil daty meczu otwarcia i finalu; kraj meczu otwarcia/finalu ma zostac ogloszony pozniej.",
    },
    "afc-asian-cup": {
        "status": "confirmed",
        "dateLabel": "7 stycznia - 5 lutego 2027",
        "host": "Arabia Saudyjska",
        "startDate": "2027-01-07",
        "endDate": "2027-02-05",
        "note": "AFC opublikowal terminarz turnieju; final zaplanowano na 5 lutego 2027.",
    },
    "concacaf-nations-league": {
        "status": "unconfirmed",
        "dateLabel": "marzec 2027",
        "host": "SoFi Stadium, Inglewood/Los Angeles",
        "startDate": "2027-03-01",
        "endDate": "2027-03-31",
        "note": "Concacaf potwierdzil miesiac i stadion; dokladne dni meczowe final four jeszcze TBC.",
    },
    "fifa-u20-world-cup": {
        "status": "unconfirmed",
        "dateLabel": "2027",
        "host": "Azerbejdzan i Uzbekistan",
        "startDate": "2027-01-01",
        "endDate": "2027-12-31",
        "note": "FIFA potwierdzila wspolnych gospodarzy; dokladne daty turnieju nie sa jeszcze potwierdzone.",
    },
    "uefa-u17-championship": {
        "status": "unconfirmed",
        "dateLabel": "finaly: lato 2027",
        "host": "Lotwa",
        "startDate": "2027-05-01",
        "endDate": "2027-07-31",
        "note": "Edycja 2026 juz sie skonczyla; UEFA potwierdzila Lotwe jako gospodarza finalow 2027, bez dokladnych dat.",
    },
    "uefa-u21-championship": {
        "status": "unconfirmed",
        "dateLabel": "lato 2027",
        "host": "Albania i Serbia",
        "startDate": "2027-06-01",
        "endDate": "2027-07-31",
        "note": "UEFA potwierdzila gospodarzy; daty meczow i losowania pozostaja TBC.",
    },
    "uefa-u19-championship": {
        "status": "unconfirmed",
        "dateLabel": "lato 2027",
        "host": "Czechy",
        "startDate": "2027-06-01",
        "endDate": "2027-08-31",
        "note": "UEFA potwierdzila Czechy jako gospodarza; dokladne daty finalow sa nadal TBC.",
    },
    "asean-championship": {
        "status": "confirmed",
        "dateLabel": "24 lipca - 26 sierpnia 2026",
        "host": "format dom/wyjazd w regionie ASEAN",
        "startDate": "2026-07-24",
        "endDate": "2026-08-26",
        "note": "Turniej zostal przeniesiony z okna koncoworocznego na 24 lipca - 26 sierpnia 2026.",
    },
    "conifa-european-football-cup": {
        "status": "unconfirmed",
        "dateLabel": "brak potwierdzonych dat kolejnej edycji",
        "host": "brak potwierdzonego gospodarza",
        "startDate": None,
        "endDate": None,
        "note": "Edycja 2026 juz sie skonczyla; kolejna edycja nie ma jeszcze oficjalnego kalendarza.",
    },
}
for league in KITCHEN_LEAGUES:
    override = TOURNAMENT_METADATA_OVERRIDES.get(league.get("key"))
    if override:
        league.setdefault("nextTournament", {}).update(override)
    if league.get("key") == "uefa-nations-league":
        league.update({
            "season": "2026-2027",
            "api_football_id": 5,
            "thesportsdb_id": 4490,
        })
    elif league.get("key") == "concacaf-nations-league":
        league.update({
            "espn_sport": "soccer",
            "espn_league": "concacaf.nations.league",
        })
    elif league.get("key") == "afcon-qualifiers":
        league.update({
            "espn_sport": "soccer",
            "espn_league": "caf.nations_qual",
        })
KITCHEN_RESULTS_ONLY_LEAGUE_KEYS = {
    "afcon",
    "afcon-qualifiers",
    "concacaf-gold-cup",
    "concacaf-nations-league",
}
KITCHEN_CUP_KEYS = {
    "champions-league",
    "europa-league",
    "conference-league",
    "fa-cup",
    "efl-cup",
    "polish-cup",
    "world-cup",
}
KITCHEN_UEFA_QUALIFIER_KEYS = {"champions-league", "europa-league", "conference-league"}
KITCHEN_FULL_ROUND_LEAGUE_KEYS = KITCHEN_UEFA_QUALIFIER_KEYS
KITCHEN_FULL_ROUND_NUMBERS = ["400"]
KITCHEN_UEFA_STAGE_WINDOWS = {
    "champions-league": [
        {"stage": "I runda kwalifikacji", "leg": "1. mecz", "start": "2026-07-07", "end": "2026-07-08"},
        {"stage": "I runda kwalifikacji", "leg": "rewanz", "start": "2026-07-14", "end": "2026-07-15"},
        {"stage": "II runda kwalifikacji", "leg": "1. mecz", "start": "2026-07-21", "end": "2026-07-22"},
        {"stage": "II runda kwalifikacji", "leg": "rewanz", "start": "2026-07-28", "end": "2026-07-29"},
        {"stage": "III runda kwalifikacji", "leg": "1. mecz", "start": "2026-08-04", "end": "2026-08-05"},
        {"stage": "III runda kwalifikacji", "leg": "rewanz", "start": "2026-08-11", "end": "2026-08-11"},
        {"stage": "play-off", "leg": "1. mecz", "start": "2026-08-18", "end": "2026-08-19"},
        {"stage": "play-off", "leg": "rewanz", "start": "2026-08-25", "end": "2026-08-26"},
    ],
    "europa-league": [
        {"stage": "I runda kwalifikacji", "leg": "1. mecz", "start": "2026-07-09", "end": "2026-07-09"},
        {"stage": "I runda kwalifikacji", "leg": "rewanz", "start": "2026-07-16", "end": "2026-07-16"},
        {"stage": "II runda kwalifikacji", "leg": "1. mecz", "start": "2026-07-23", "end": "2026-07-23"},
        {"stage": "II runda kwalifikacji", "leg": "rewanz", "start": "2026-07-30", "end": "2026-07-30"},
        {"stage": "III runda kwalifikacji", "leg": "1. mecz", "start": "2026-08-06", "end": "2026-08-06"},
        {"stage": "III runda kwalifikacji", "leg": "rewanz", "start": "2026-08-13", "end": "2026-08-13"},
        {"stage": "play-off", "leg": "1. mecz", "start": "2026-08-20", "end": "2026-08-20"},
        {"stage": "play-off", "leg": "rewanz", "start": "2026-08-27", "end": "2026-08-27"},
    ],
    "conference-league": [
        {"stage": "I runda kwalifikacji", "leg": "1. mecz", "start": "2026-07-07", "end": "2026-07-09"},
        {"stage": "I runda kwalifikacji", "leg": "rewanz", "start": "2026-07-14", "end": "2026-07-16"},
        {"stage": "II runda kwalifikacji", "leg": "1. mecz", "start": "2026-07-21", "end": "2026-07-23"},
        {"stage": "II runda kwalifikacji", "leg": "rewanz", "start": "2026-07-30", "end": "2026-07-30"},
        {"stage": "III runda kwalifikacji", "leg": "1. mecz", "start": "2026-08-06", "end": "2026-08-06"},
        {"stage": "III runda kwalifikacji", "leg": "rewanz", "start": "2026-08-13", "end": "2026-08-13"},
        {"stage": "play-off", "leg": "1. mecz", "start": "2026-08-20", "end": "2026-08-20"},
        {"stage": "play-off", "leg": "rewanz", "start": "2026-08-27", "end": "2026-08-27"},
    ],
}
WORLD_CUP_GROUP_RE = re.compile(r"\bgroup\s+([A-Z])\b", re.I)
KITCHEN_TEAM_CREST_FALLBACKS = {
    "olimpia grudziadz": "https://r2.thesportsdb.com/images/media/team/badge/fwmqh21580815683.png",
    "sandecja nowy sacz": "https://r2.thesportsdb.com/images/media/team/badge/jtq1cl1681320690.png",
    "podbeskidzie bielsko biala": "https://r2.thesportsdb.com/images/media/team/badge/41k2fu1681320772.png",
    "slask ii wroclaw": "https://r2.thesportsdb.com/images/media/team/badge/e4sikw1760240630.png",
    "slask wroclaw ii": "https://r2.thesportsdb.com/images/media/team/badge/e4sikw1760240630.png",
}
KITCHEN_TEAM_CREST_ALIASES = {
    "sandecja nowy sacz": "Sandecja Nowy Sącz",
    "podbeskidzie bielsko biala": "Podbeskidzie Bielsko-Biała",
    "slask ii wroclaw": "Śląsk II Wrocław",
    "slask wroclaw ii": "Śląsk II Wrocław",
}
KITCHEN_TERMINAL_LIVE_STATUSES = {
    "match finished",
    "finished",
    "ft",
    "full time",
    "final",
    "ended",
    "aet",
    "after extra time",
    "aot",
    "after overtime",
    "ap",
    "after penalties",
    "pen",
    "pens",
    "penalties",
}
KITCHEN_LIVE_MAX_AGE_HOURS = 8
KITCHEN_SUPPLEMENTAL_MATCHES = [
    {
        "id": "manual:polish-ii-liga-playoff:olimpia-sandecja:2026-06-02",
        "provider": "manual",
        "leagueKey": "polish-ii-liga",
        "leagueName": "Polska II liga",
        "sourceType": "competition",
        "competitionName": "Betclic 2 Liga - baraże",
        "playedAt": "2026-06-02T16:00:00",
        "status": "FT",
        "round": "Półfinał baraży",
        "roundType": "cup",
        "home": {"name": "Olimpia Grudziądz", "crest": ""},
        "away": {"name": "Sandecja Nowy Sącz", "crest": ""},
        "score": {"home": 1, "away": 2},
    },
    {
        "id": "manual:polish-ii-liga-playoff:podbeskidzie-slask-ii:2026-06-02",
        "provider": "manual",
        "leagueKey": "polish-ii-liga",
        "leagueName": "Polska II liga",
        "sourceType": "competition",
        "competitionName": "Betclic 2 Liga - baraże",
        "playedAt": "2026-06-02T13:00:00",
        "status": "FT",
        "round": "Półfinał baraży",
        "roundType": "cup",
        "home": {"name": "Podbeskidzie Bielsko-Biała", "crest": ""},
        "away": {"name": "Śląsk II Wrocław", "crest": ""},
        "score": {"home": 2, "away": 1},
    },
]
KITCHEN_SUPPLEMENTAL_NEXT_MATCHES = [
    {
        "id": "official-next:uefa-nations-league:poland-bosnia:2026-09-25",
        "provider": "uefa-schedule",
        "teamKey": "uefa-nations-league",
        "teamName": "Polska",
        "competitionName": "UEFA Nations League - Liga B, grupa B4",
        "kickoffAt": "2026-09-25T20:45:00+02:00",
        "round": "1. kolejka",
        "roundType": "league",
        "home": {"name": "Polska", "crest": "https://a.espncdn.com/i/teamlogos/countries/500/pol.png"},
        "away": {"name": "Bośnia i Hercegowina", "crest": "https://a.espncdn.com/i/teamlogos/countries/500/bih.png"},
    },
    {
        "id": "official-next:uefa-nations-league:sweden-poland:2026-09-28",
        "provider": "uefa-schedule",
        "teamKey": "uefa-nations-league",
        "teamName": "Polska",
        "competitionName": "UEFA Nations League - Liga B, grupa B4",
        "kickoffAt": "2026-09-28T20:45:00+02:00",
        "round": "2. kolejka",
        "roundType": "league",
        "home": {"name": "Szwecja", "crest": "https://a.espncdn.com/i/teamlogos/countries/500/swe.png"},
        "away": {"name": "Polska", "crest": "https://a.espncdn.com/i/teamlogos/countries/500/pol.png"},
    },
    {
        "id": "official-next:uefa-nations-league:poland-romania:2026-10-02",
        "provider": "uefa-schedule",
        "teamKey": "uefa-nations-league",
        "teamName": "Polska",
        "competitionName": "UEFA Nations League - Liga B, grupa B4",
        "kickoffAt": "2026-10-02T20:45:00+02:00",
        "round": "3. kolejka",
        "roundType": "league",
        "home": {"name": "Polska", "crest": "https://a.espncdn.com/i/teamlogos/countries/500/pol.png"},
        "away": {"name": "Rumunia", "crest": "https://a.espncdn.com/i/teamlogos/countries/500/rou.png"},
    },
    {
        "id": "official-next:uefa-nations-league:bosnia-poland:2026-10-05",
        "provider": "uefa-schedule",
        "teamKey": "uefa-nations-league",
        "teamName": "Polska",
        "competitionName": "UEFA Nations League - Liga B, grupa B4",
        "kickoffAt": "2026-10-05T20:45:00+02:00",
        "round": "4. kolejka",
        "roundType": "league",
        "home": {"name": "Bośnia i Hercegowina", "crest": "https://a.espncdn.com/i/teamlogos/countries/500/bih.png"},
        "away": {"name": "Polska", "crest": "https://a.espncdn.com/i/teamlogos/countries/500/pol.png"},
    },
    {
        "id": "manual-next:polish-ii-liga-playoff-final:2026-06-06",
        "provider": "manual",
        "teamKey": "polish-ii-liga",
        "teamName": "Polska II liga",
        "competitionName": "Betclic 2 Liga - baraże",
        "kickoffAt": "2026-06-06T13:45:00",
        "round": "Finał baraży",
        "roundType": "cup",
        "home": {"name": "Podbeskidzie Bielsko-Biała", "crest": ""},
        "away": {"name": "Sandecja Nowy Sącz", "crest": ""},
    },
]
KITCHEN_NEXT_TEAMS = [
    {"key": "liverpool", "name": "Liverpool", "thesportsdb_team_id": 133602},
    {"key": "hearts", "name": "Hearts", "thesportsdb_team_id": 133643},
    {"key": "besiktas", "name": "Beşiktaş", "thesportsdb_team_id": 133794},
    {
        "key": "montreal-canadiens",
        "name": "Montreal Canadiens",
        "espn_sport": "hockey",
        "espn_league": "nhl",
        "espn_team_names": ["Montreal Canadiens", "Canadiens"],
        "crest": "https://a.espncdn.com/i/teamlogos/nhl/500/mtl.png",
    },
    {"key": "wieczysta-krakow", "name": "Wieczysta Kraków", "thesportsdb_team_id": 152462},
    {"key": "hutnik-krakow", "name": "Hutnik Kraków", "thesportsdb_team_id": 153534},
    {"key": "poland", "name": "Polska", "thesportsdb_team_id": 133901},
]
KITCHEN_NEXT_WINDOW_DAYS = 14
KITCHEN_IMAGE_HOSTS = {
    "a.espncdn.com",
    "espncdn.com",
    "r2.thesportsdb.com",
    "www.thesportsdb.com",
    "thesportsdb.com",
    "static.files.bbci.co.uk",
    "upload.wikimedia.org",
    "www.conifa.org",
}
KITCHEN_IMAGE_MAX_BYTES = 3 * 1024 * 1024


def kitchen_source_is_cup(source):
    return bool(source and (source.get("roundType") == "cup" or source.get("key") in KITCHEN_CUP_KEYS))


KITCHEN_KNOCKOUT_ROUND_MARKERS = (
    "playoff",
    "play off",
    "play-offs",
    "play offs",
    "promotion",
    "relegation",
    "semi final",
    "semifinal",
    "semi-final",
    "quarter final",
    "quarterfinal",
    "quarter-final",
    "final",
    "baraz",
)


def kitchen_event_is_knockout(source, *values):
    haystack = " ".join(normalize_lookup_text(value) for value in values if value)
    if (source or {}).get("key") == "world-cup":
        if "group" in haystack:
            return False
        if any(marker in haystack for marker in KITCHEN_KNOCKOUT_ROUND_MARKERS):
            return True
    if kitchen_source_is_cup(source):
        return True
    if any(marker in haystack for marker in KITCHEN_KNOCKOUT_ROUND_MARKERS):
        return True
    # TheSportsDB uses round 0 for Polish promotion playoff matches.
    return any(parse_optional_int(value) == 0 for value in values)


def kitchen_match_round_type(source, *values):
    return "cup" if kitchen_event_is_knockout(source, *values) else "league"


def kitchen_round_value(raw_round, source):
    if kitchen_event_is_knockout(source, raw_round):
        return None
    value = str(raw_round or "").strip()
    return value or None


def kitchen_round_type(source):
    return "cup" if kitchen_source_is_cup(source) else "league"


def kitchen_league_season(source, now=None):
    today = (now.date() if isinstance(now, datetime) else date.today())
    if (source or {}).get("season"):
        return str((source or {}).get("season"))
    if (source or {}).get("seasonMode") == "year":
        return str(today.year)
    return current_football_season(today)
POLISH_NAMEDAYS_PATH = ROOT / "data" / "polish-namedays.json"
KITCHEN_LEAGUE_ORDER = {
    league["key"]: index
    for index, league in enumerate(KITCHEN_LEAGUES)
}
GOOGLE_CALENDAR_DATA_DIR = ROOT / "data" / "google-calendar"
GOOGLE_CALENDAR_STATE_JSON = GOOGLE_CALENDAR_DATA_DIR / "state.json"
GOOGLE_CALENDAR_CACHE_JSON = GOOGLE_CALENDAR_DATA_DIR / "events-cache.json"
GOOGLE_CALENDAR_OVERRIDES_JSON = GOOGLE_CALENDAR_DATA_DIR / "overrides.json"
GOOGLE_CALENDAR_CACHE_SCHEMA_VERSION = 4
GOOGLE_CALENDAR_TIMEZONE = ZoneInfo(os.environ.get("DASHBOARD_TIMEZONE") or os.environ.get("TZ") or "Europe/Warsaw")
GOOGLE_CALENDAR_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_CALENDAR_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_CALENDAR_API_BASE = "https://www.googleapis.com/calendar/v3"
GOOGLE_SHEETS_API_BASE = "https://sheets.googleapis.com/v4"
GOOGLE_CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
    "https://www.googleapis.com/auth/tasks.readonly",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
]
GOOGLE_CALENDAR_SCOPE = " ".join(GOOGLE_CALENDAR_SCOPES)
GOOGLE_CALENDAR_LIST_REFRESH_SECONDS = 10 * 60
GOOGLE_CALENDAR_SYNC_MIN_INTERVAL_SECONDS = 60
GOOGLE_TASKS_API_BASE = "https://tasks.googleapis.com/tasks/v1"
CINEMA_CITY_DEFAULT_SHEET_ID = "1WqWJEOCg8qC-l2S7CA4Dwog3nQ18tCAlbFf_4d5aoog"
CINEMA_CITY_DEFAULT_SHEET_NAME = "Filters"
CINEMA_CITY_DEFAULT_SHEET_RANGE = "A:Z"
SPOTIFY_DATA_DIR = ROOT / "data" / "spotify"
SPOTIFY_STATE_JSON = SPOTIFY_DATA_DIR / "state.json"
SPOTIFY_SCREENSAVER_SETTINGS_JSON = SPOTIFY_DATA_DIR / "screensaver-settings.json"
SPOTIFY_AUTH_URL = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_CURRENTLY_PLAYING_URL = "https://api.spotify.com/v1/me/player/currently-playing"
SPOTIFY_QUEUE_URL = "https://api.spotify.com/v1/me/player/queue"
SPOTIFY_PLAYER_API_BASE = "https://api.spotify.com/v1/me/player"
SPOTIFY_SCOPES = [
    "user-read-currently-playing",
    "user-read-playback-state",
    "user-modify-playback-state",
]
SPOTIFY_SCOPE = " ".join(SPOTIFY_SCOPES)
DEFAULT_SPOTIFY_SCREENSAVER_IDLE_MINUTES = 3
DEFAULT_SPOTIFY_SCREENSAVER_CHECK_INTERVAL_MS = 5000
JSON_WRITE_LOCKS = {}
JSON_WRITE_LOCKS_GUARD = threading.Lock()
STEP_UPDATE_SUBSCRIBERS = set()
STEP_UPDATE_SUBSCRIBERS_LOCK = threading.Lock()
LIVE_WORKOUT_SUBSCRIBERS = set()
LIVE_WORKOUT_SUBSCRIBERS_LOCK = threading.Lock()
LIVE_WORKOUT_LATEST = None
WINDOWS_REPLACE_RETRY_DELAYS = (0.05, 0.12, 0.25, 0.5, 1.0)
DEFAULT_ALLOWED_API_ORIGINS = {
    "http://127.0.0.1:8000",
    "http://localhost:8000",
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://127.0.0.1:5174",
    "http://localhost:5174",
    "http://127.0.0.1:5175",
    "http://localhost:5175",
}
PROTECTED_STATIC_SEGMENTS = {
    "benchmark_content",
    ".git",
    "__pycache__",
    "node_modules",
    "scripts",
    "tests",
    "reports",
}
PROTECTED_STATIC_NAMES = {
    ".env",
    ".env.development",
    ".env.production",
    "package.json",
    "package-lock.json",
    "server.py",
    "server.log",
    "watchlist.sqlite",
}
PROTECTED_STATIC_EXTS = {
    ".bat",
    ".cmd",
    ".db",
    ".log",
    ".ps1",
    ".py",
    ".pyc",
    ".sqlite",
}


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


def normalize_origin(value):
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = urllib.parse.urlsplit(raw)
        port = parsed.port
    except ValueError:
        return ""
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower()
    if (
        scheme not in {"http", "https"}
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        return ""
    default_port = 80 if scheme == "http" else 443
    host_display = f"[{host}]" if ":" in host else host
    return f"{scheme}://{host_display}{f':{port}' if port and port != default_port else ''}"


def origin_from_url(value):
    parsed = urllib.parse.urlsplit(str(value or "").strip())
    if not parsed.scheme or not parsed.netloc:
        return ""
    return normalize_origin(urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "", "", "")))


def allowed_api_origins():
    raw = str(os.environ.get("DASHBOARD_ALLOWED_ORIGINS", "") or "").strip()
    if not raw:
        return set(DEFAULT_ALLOWED_API_ORIGINS)
    return {
        normalize_origin(part)
        for part in raw.split(",")
        if normalize_origin(part)
    }


def is_allowed_api_origin(value):
    origin = normalize_origin(value)
    return bool(origin) and origin in allowed_api_origins()


def is_request_host_origin(value, host_header):
    origin = normalize_origin(value)
    host = str(host_header or "").strip()
    if not origin or not host:
        return False
    return origin in {
        normalize_origin(f"http://{host}"),
        normalize_origin(f"https://{host}"),
    }


REMOTE_TOKEN_WRITE_PATHS = {
    "/api/steps/events/upsert",
    "/api/health-connect/snapshot",
    "/api/live-workout/telemetry",
    "/api/reading/books",
    "/api/reading/history",
    "/api/reading/settings",
    "/api/ring/phone/ingest",
    "/api/ring/phone/status",
}

FINANCE_COMPANION_ADMIN_RE = re.compile(r"/api/budget/companion/(?:devices|pair|revoke)")
FINANCE_COMPANION_REMOTE_RE = re.compile(
    r"/api/budget/(?:receipts(?:/.*)?|receipt-items(?:/.*)?|products/barcode(?:/.*)?|products/pending|companion/status)"
)
FINANCE_RECEIPT_SOURCE_CONTENT_RE = re.compile(
    r"/api/budget/(?:receipts/[^/]+/sources/[^/]+/content|receipt-items/[^/]+/crop)"
)

HABITS_API_PATHS = {
    "/api/habits/snapshot",
    "/api/habits/sync",
    "/api/habits/reminders/settings",
    "/api/habits/reminders/action",
    "/api/habits/supplements",
    "/api/habits/supplements/slots",
    "/api/habits/supplements/regimen",
    "/api/habits/supplements/product",
    "/api/habits/supplements/claim",
}
FEELINGS_API_PREFIX = "/api/feelings"


def configured_dashboard_tokens():
    raw = str(os.environ.get("DASHBOARD_WRITE_TOKEN", "") or "").strip()
    steps = str(os.environ.get("DASHBOARD_STEPS_WRITE_TOKEN", "") or "").strip()
    habits = str(os.environ.get("DASHBOARD_HABITS_TOKEN", "") or "").strip()
    return {token for token in {raw, steps, habits} if token}


def configured_todo_phone_tokens():
    tokens = {token for token in {
        str(os.environ.get("DASHBOARD_TODO_TOKEN", "") or "").strip(),
        str(os.environ.get("DASHBOARD_WRITE_TOKEN", "") or "").strip(),
    } if token}
    token_path = Path.home() / ".cleaning-dashboard" / "todo-phone-token"
    try:
        saved = token_path.read_text(encoding="utf-8").strip()
        if saved:
            tokens.add(saved)
    except OSError:
        pass
    return tokens


def configured_live_workout_tokens():
    general = str(os.environ.get("DASHBOARD_WRITE_TOKEN", "") or "").strip()
    live_workout = str(os.environ.get("DASHBOARD_LIVE_WORKOUT_TOKEN", "") or "").strip()
    return {token for token in {general, live_workout} if token}


def configured_habits_tokens():
    general = str(os.environ.get("DASHBOARD_WRITE_TOKEN", "") or "").strip()
    habits = str(os.environ.get("DASHBOARD_HABITS_TOKEN", "") or "").strip()
    return {token for token in {general, habits} if token}


def configured_feelings_tokens():
    general = str(os.environ.get("DASHBOARD_WRITE_TOKEN", "") or "").strip()
    feelings = str(os.environ.get("DASHBOARD_FEELINGS_TOKEN", "") or "").strip()
    habits = str(os.environ.get("DASHBOARD_HABITS_TOKEN", "") or "").strip()
    return {token for token in {general, feelings, habits} if token}


def extract_dashboard_token(headers):
    auth = str(headers.get("Authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return str(headers.get("X-Dashboard-Token") or "").strip()


def is_valid_dashboard_token(headers):
    supplied = extract_dashboard_token(headers)
    if not supplied:
        return False
    return any(hmac.compare_digest(supplied, token) for token in configured_dashboard_tokens())


def is_valid_finance_companion_token(headers):
    supplied = extract_dashboard_token(headers)
    return bool(supplied) and FINANCE_SERVICE.validate_companion_token(supplied)


def is_valid_habits_token(headers):
    supplied = extract_dashboard_token(headers)
    if not supplied:
        return False
    return any(hmac.compare_digest(supplied, token) for token in configured_habits_tokens())


def is_valid_feelings_token(headers):
    supplied = extract_dashboard_token(headers)
    if not supplied:
        return False
    return any(hmac.compare_digest(supplied, token) for token in configured_feelings_tokens())


def is_valid_live_workout_token(headers):
    supplied = extract_dashboard_token(headers)
    if not supplied:
        return False
    return any(
        hmac.compare_digest(supplied, token)
        for token in configured_live_workout_tokens()
    )


def token_fingerprint(value):
    token = str(value or "").strip()
    if not token:
        return "none"
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:10]


def subscribe_step_updates():
    subscriber = queue.Queue(maxsize=20)
    with STEP_UPDATE_SUBSCRIBERS_LOCK:
        STEP_UPDATE_SUBSCRIBERS.add(subscriber)
    return subscriber


def unsubscribe_step_updates(subscriber):
    with STEP_UPDATE_SUBSCRIBERS_LOCK:
        STEP_UPDATE_SUBSCRIBERS.discard(subscriber)


def broadcast_step_update(payload):
    with STEP_UPDATE_SUBSCRIBERS_LOCK:
        subscribers = list(STEP_UPDATE_SUBSCRIBERS)
    for subscriber in subscribers:
        try:
            subscriber.put_nowait(payload)
        except queue.Full:
            try:
                subscriber.get_nowait()
                subscriber.put_nowait(payload)
            except queue.Empty:
                pass


def normalize_live_workout_telemetry(payload):
    if not isinstance(payload, dict):
        raise ValueError("JSON payload must be an object")

    timestamp = payload.get("timestamp")
    heart_rate = payload.get("heart_rate")
    status = str(payload.get("status") or "").strip().lower()
    if isinstance(timestamp, bool) or not isinstance(timestamp, int) or timestamp <= 0:
        raise ValueError("timestamp must be a positive integer")
    if isinstance(heart_rate, bool) or not isinstance(heart_rate, int) or not 30 <= heart_rate <= 240:
        raise ValueError("heart_rate must be an integer between 30 and 240")
    if status not in {"ready", "running", "paused", "finished"}:
        raise ValueError("status must be ready, running, paused or finished")
    normalized = {
        "timestamp": timestamp,
        "heart_rate": heart_rate,
        "status": status,
    }
    cadence_rpm = payload.get("cadence_rpm")
    if cadence_rpm is not None:
        if isinstance(cadence_rpm, bool) or not isinstance(cadence_rpm, (int, float)) or not 0 <= cadence_rpm <= 250:
            raise ValueError("cadence_rpm must be a number between 0 and 250")
        normalized["cadence_rpm"] = round(float(cadence_rpm), 1)
    return normalized


def normalize_live_workout_telemetry_payload(payload):
    """Accept one legacy telemetry object or a buffered array from the watch."""
    if isinstance(payload, list):
        if not payload:
            raise ValueError("telemetry batch must contain at least one sample")
        if len(payload) > LIVE_WORKOUT_TELEMETRY_MAX_SAMPLES:
            raise ValueError(
                f"telemetry batch cannot exceed {LIVE_WORKOUT_TELEMETRY_MAX_SAMPLES} samples"
            )
        normalized = []
        for index, sample in enumerate(payload):
            try:
                normalized.append(normalize_live_workout_telemetry(sample))
            except ValueError as exc:
                raise ValueError(f"telemetry[{index}]: {exc}") from exc
        return normalized, True
    return [normalize_live_workout_telemetry(payload)], False


def subscribe_live_workout():
    subscriber = queue.Queue(maxsize=60)
    with LIVE_WORKOUT_SUBSCRIBERS_LOCK:
        LIVE_WORKOUT_SUBSCRIBERS.add(subscriber)
        latest = dict(LIVE_WORKOUT_LATEST) if LIVE_WORKOUT_LATEST else None
    if latest:
        subscriber.put_nowait(latest)
    return subscriber


def latest_live_workout_telemetry():
    with LIVE_WORKOUT_SUBSCRIBERS_LOCK:
        return dict(LIVE_WORKOUT_LATEST) if LIVE_WORKOUT_LATEST else None


def unsubscribe_live_workout(subscriber):
    with LIVE_WORKOUT_SUBSCRIBERS_LOCK:
        LIVE_WORKOUT_SUBSCRIBERS.discard(subscriber)


def broadcast_live_workout(payload):
    global LIVE_WORKOUT_LATEST
    normalized = dict(payload)
    with LIVE_WORKOUT_SUBSCRIBERS_LOCK:
        LIVE_WORKOUT_LATEST = normalized
        subscribers = list(LIVE_WORKOUT_SUBSCRIBERS)
    for subscriber in subscribers:
        try:
            subscriber.put_nowait(normalized)
        except queue.Full:
            try:
                subscriber.get_nowait()
                subscriber.put_nowait(normalized)
            except queue.Empty:
                pass
    return len(subscribers)


def is_protected_static_path(path):
    clean = urllib.parse.unquote(urlparse(path).path or "/")
    if clean in {"", "/"}:
        return False

    normalized = Path(clean.lstrip("/"))
    lower_parts = [part.lower() for part in normalized.parts if part not in {"", "."}]
    if not lower_parts:
        return False

    clean_lower = clean.lower()
    if clean_lower.startswith("/data/raw/") or clean_lower.startswith("/data/google-calendar/"):
        return True

    # Financial runtime data is API-only. This explicitly covers the legacy
    # JSON during migration, SQLite sidecars, and safety backups.
    if (
        clean_lower == "/data/budget.json"
        or clean_lower.startswith("/data/finance.sqlite")
        or clean_lower.startswith("/data/jobhunt/")
        or clean_lower.startswith("/data/jobhunt.sqlite")
        or clean_lower == "/data/.finance-account-key"
        or clean_lower.startswith("/data/budget-backups/")
        or clean_lower.startswith("/data/backups/")
        or clean_lower.startswith("/data/finance-imports/")
        or clean_lower.startswith("/data/finance-receipts/")
        or clean_lower.startswith("/data/language-learning/")
        or clean_lower.startswith("/data/audio/language-learning/")
        or clean_lower.startswith("/data/reference/")
        or clean_lower == "/data/settings/bills.json"
    ):
        return True

    if any(part in PROTECTED_STATIC_SEGMENTS for part in lower_parts):
        return True

    name = lower_parts[-1]
    if name.startswith(".") or name in PROTECTED_STATIC_NAMES:
        return True

    suffix = Path(name).suffix.lower()
    if suffix in PROTECTED_STATIC_EXTS or name.endswith((".sqlite-wal", ".sqlite-shm", ".db-wal", ".db-shm")):
        return True

    return False


def rssi_to_signal_percent(rssi):
    try:
        value = float(rssi)
    except (TypeError, ValueError):
        return None
    percent = (value - (-100.0)) / ((-50.0) - (-100.0)) * 100.0
    return max(0, min(100, round(percent)))


def seconds_since_iso(value):
    if not value:
        return None
    try:
        then = datetime.fromisoformat(str(value))
        return max(0, int((datetime.now() - then).total_seconds()))
    except ValueError:
        return None


def parse_realistic_weight_kg(value):
    try:
        weight_kg = float(str(value or "").replace(",", "."))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(weight_kg):
        return None
    if not REALISTIC_WEIGHT_MIN_KG <= weight_kg <= REALISTIC_WEIGHT_MAX_KG:
        return None
    return weight_kg


def read_latest_weight_measurement():
    if SCALE_LATEST_JSON.exists():
        with SCALE_LATEST_JSON.open("r", encoding="utf-8") as f:
            payload = json.load(f)
        if isinstance(payload, dict) and payload.get("weight_kg") is not None:
            weight_kg = parse_realistic_weight_kg(payload.get("weight_kg"))
            if payload.get("has_weight") is False or is_181d_idle_payload(payload) or weight_kg is None:
                history_payload = latest_weight_history_event()
                if history_payload:
                    payload = history_payload
                    weight_kg = parse_realistic_weight_kg(payload.get("weight_kg"))
            if weight_kg is None:
                return {"ok": False, "error": "No realistic scale measurement yet"}
            payload = {**payload, "weight_kg": weight_kg}
            payload["signal_percent"] = rssi_to_signal_percent(payload.get("rssi"))
            payload["age_seconds"] = seconds_since_iso(payload.get("timestamp"))
            return payload

    if not SCALE_MEASUREMENTS_CSV.exists():
        return {"ok": False, "error": "No scale measurement yet"}

    latest = None
    with SCALE_MEASUREMENTS_CSV.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if parse_realistic_weight_kg(row.get("weight_kg")) is not None:
                latest = row

    if not latest:
        return {"ok": False, "error": "No scale measurement yet"}

    weight_kg = parse_realistic_weight_kg(latest.get("weight_kg"))
    if weight_kg is None:
        return {"ok": False, "error": "Invalid scale measurement"}

    return {
        "ok": True,
        "timestamp": latest.get("timestamp") or None,
        "address": latest.get("address") or None,
        "name": latest.get("name") or None,
        "rssi": int(latest["rssi"]) if str(latest.get("rssi") or "").lstrip("-").isdigit() else None,
        "signal_percent": rssi_to_signal_percent(latest.get("rssi")),
        "age_seconds": seconds_since_iso(latest.get("timestamp")),
        "type": latest.get("type") or None,
        "weight_kg": weight_kg,
        "stable": str(latest.get("stable") or "").lower() == "true",
        "unit": latest.get("unit") or "kg",
        "impedance": latest.get("impedance") or None,
        "raw_hex": latest.get("raw_hex") or None,
    }


def read_scale_signal():
    source = SCALE_SIGNAL_JSON if SCALE_SIGNAL_JSON.exists() else SCALE_LATEST_JSON
    if not source.exists():
        return {"ok": False, "error": "No scale signal yet"}

    with source.open("r", encoding="utf-8") as f:
        payload = json.load(f)

    if not isinstance(payload, dict) or payload.get("rssi") is None:
        return {"ok": False, "error": "No scale signal yet"}

    percent = payload.get("signal_percent")
    if percent is None:
        percent = rssi_to_signal_percent(payload.get("rssi"))

    return {
        "ok": True,
        "timestamp": payload.get("timestamp"),
        "address": payload.get("address"),
        "name": payload.get("name"),
        "rssi": payload.get("rssi"),
        "signal_percent": percent,
        "age_seconds": seconds_since_iso(payload.get("timestamp")),
        "source": payload.get("source") or "BLE_ADV",
    }


def read_sensor_latest():
    """Serve GET /api/sensor/latest — returns the most recent env-sensor reading."""
    if not SENSOR_LATEST_JSON.exists():
        return {"ok": False, "error": "No sensor reading yet"}
    try:
        with SENSOR_LATEST_JSON.open("r", encoding="utf-8") as f:
            payload = json.load(f)
        if not isinstance(payload, dict):
            return {"ok": False, "error": "Sensor data corrupt"}
        return {
            **payload,
            "ok": True,
            "age_seconds": seconds_since_iso(payload.get("timestamp")),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def read_sensor_history(hours: float = 24.0, date_value=None, month_value=None):
    """Return saved sensor rows for a rolling window, local day, or local month."""
    if not SENSOR_READINGS_JSONL.exists():
        return []

    if date_value:
        range_start = datetime.strptime(str(date_value), "%Y-%m-%d")
        range_end = range_start + timedelta(days=1)
    elif month_value:
        range_start = datetime.strptime(str(month_value), "%Y-%m")
        range_end = (
            datetime(range_start.year + 1, 1, 1)
            if range_start.month == 12
            else datetime(range_start.year, range_start.month + 1, 1)
        )
    else:
        range_start = datetime.now() - timedelta(hours=max(0.1, float(hours)))
        range_end = None

    rows = []
    try:
        with SENSOR_READINGS_JSONL.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = row.get("timestamp")
                if not ts:
                    continue
                try:
                    dt = datetime.fromisoformat(ts)
                    if dt >= range_start and (range_end is None or dt < range_end):
                        rows.append(row)
                except (ValueError, TypeError):
                    pass
    except Exception:
        pass
    return rows


def parse_weight_history_row(row):
    if not isinstance(row, dict):
        return None

    has_weight = row.get("has_weight")
    if has_weight is False or str(has_weight).lower() == "false":
        return None

    timestamp = str(row.get("timestamp") or "").strip()
    if not timestamp:
        return None

    weight_kg = parse_realistic_weight_kg(row.get("weight_kg"))
    if weight_kg is None:
        return None

    if not timestamp[:10] or len(timestamp) < 10:
        return None

    return {
        "timestamp": timestamp,
        "day": timestamp[:10],
        "weight_kg": weight_kg,
        "rssi": row.get("rssi"),
        "address": row.get("address"),
        "name": row.get("name"),
        "type": row.get("type"),
        "unit": row.get("unit") or "kg",
        "impedance": row.get("impedance"),
        "raw_hex": row.get("raw_hex"),
    }


def weight_event_dedupe_key(event):
    try:
        weight = round(float(event.get("weight_kg")), 3)
    except (TypeError, ValueError):
        weight = event.get("weight_kg")
    return (
        event.get("timestamp"),
        weight,
        event.get("type"),
        event.get("raw_hex"),
    )


def dedupe_weight_events(events):
    unique = []
    seen = set()
    for event in events:
        key = weight_event_dedupe_key(event)
        if key in seen:
            continue
        seen.add(key)
        unique.append(event)
    return unique


def is_181d_idle_payload(payload):
    if not isinstance(payload, dict) or payload.get("type") != "181D":
        return False
    raw_hex = str(payload.get("raw_hex") or "").strip()
    if not raw_hex:
        return False
    try:
        first_byte = int(raw_hex.split()[0], 16)
    except (ValueError, IndexError):
        return False
    return bool(first_byte & (1 << 7))


def latest_weight_history_event():
    source = SCALE_DATA_DIR / "scale_measurements.jsonl"
    latest = None
    if source.exists():
        with source.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    parsed = parse_weight_history_row(json.loads(line))
                except json.JSONDecodeError:
                    parsed = None
                if parsed:
                    latest = parsed

    if not latest and SCALE_MEASUREMENTS_CSV.exists():
        with SCALE_MEASUREMENTS_CSV.open("r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                parsed = parse_weight_history_row(row)
                if parsed:
                    latest = parsed

    if not latest:
        return None

    return {
        "ok": True,
        "timestamp": latest.get("timestamp"),
        "address": latest.get("address"),
        "name": latest.get("name"),
        "rssi": latest.get("rssi"),
        "type": latest.get("type"),
        "weight_kg": latest.get("weight_kg"),
        "stable": True,
        "has_weight": True,
        "unit": latest.get("unit"),
        "impedance": latest.get("impedance"),
        "raw_hex": latest.get("raw_hex"),
    }


def read_weight_events():
    source = SCALE_DATA_DIR / "scale_measurements.jsonl"
    events = []

    if source.exists():
        with source.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError:
                    continue
                parsed = parse_weight_history_row(raw)
                if not parsed:
                    continue
                events.append(
                    {
                        "timestamp": parsed["timestamp"],
                        "day": parsed["day"],
                        "weight_kg": round(parsed["weight_kg"], 2),
                        "rssi": parsed.get("rssi"),
                        "type": parsed.get("type"),
                        "unit": parsed.get("unit") or "kg",
                        "raw_hex": parsed.get("raw_hex"),
                    }
                )

    if not events and SCALE_MEASUREMENTS_CSV.exists():
        with SCALE_MEASUREMENTS_CSV.open("r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                parsed = parse_weight_history_row(row)
                if parsed:
                    events.append(
                        {
                            "timestamp": parsed["timestamp"],
                            "day": parsed["day"],
                            "weight_kg": round(parsed["weight_kg"], 2),
                            "rssi": parsed.get("rssi"),
                            "type": parsed.get("type"),
                            "unit": parsed.get("unit") or "kg",
                            "raw_hex": parsed.get("raw_hex"),
                        }
                    )

    events.sort(key=lambda item: item["timestamp"], reverse=True)
    events = dedupe_weight_events(events)
    return {"ok": True, "events": events, "count": len(events)}


def all_weight_history_events_chronological():
    source = SCALE_DATA_DIR / "scale_measurements.jsonl"
    events = []

    if source.exists():
        with source.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    parsed = parse_weight_history_row(json.loads(line))
                except json.JSONDecodeError:
                    parsed = None
                if parsed:
                    events.append(parsed)
    elif SCALE_MEASUREMENTS_CSV.exists():
        with SCALE_MEASUREMENTS_CSV.open("r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                parsed = parse_weight_history_row(row)
                if parsed:
                    events.append(parsed)

    events.sort(key=lambda item: item["timestamp"])
    return dedupe_weight_events(events)


def daily_weight_points(events):
    groups = {}
    for event in events:
        group = groups.setdefault(event["day"], [])
        group.append(float(event["weight_kg"]))

    points = []
    for day, weights in groups.items():
        try:
            point_day = date.fromisoformat(day)
        except ValueError:
            continue
        points.append(
            {
                "day": day,
                "date": point_day,
                "weight_kg": sum(weights) / len(weights),
                "count": len(weights),
            }
        )
    points.sort(key=lambda item: item["date"])
    return points


def value_on_day(points, target_day):
    if not points:
        return None

    previous_point = None
    next_point = None
    for point in points:
        point_day = point["date"]
        if point_day == target_day:
            return point["weight_kg"]
        if point_day < target_day:
            previous_point = point
        elif point_day > target_day:
            next_point = point
            break

    if previous_point and next_point:
        total_days = max(1, (next_point["date"] - previous_point["date"]).days)
        elapsed_days = (target_day - previous_point["date"]).days
        ratio = elapsed_days / total_days
        return previous_point["weight_kg"] + (next_point["weight_kg"] - previous_point["weight_kg"]) * ratio
    return None


def average_for_window(points, end_day, days):
    start = end_day - timedelta(days=days - 1)
    values = [
        point["weight_kg"]
        for point in points
        if start <= point["date"] <= end_day
    ]
    if not values:
        return None
    return sum(values) / len(values)


def linear_rate_for_window(points, end_day, days):
    start = end_day - timedelta(days=days - 1)
    window = [
        point
        for point in points
        if start <= point["date"] <= end_day
    ]
    if len(window) < 2:
        return None

    x_values = [(point["date"] - window[0]["date"]).days for point in window]
    y_values = [point["weight_kg"] for point in window]
    x_mean = sum(x_values) / len(x_values)
    y_mean = sum(y_values) / len(y_values)
    denominator = sum((x - x_mean) ** 2 for x in x_values)
    if denominator == 0:
        return None
    slope_per_day = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_values, y_values)) / denominator
    return slope_per_day * 7


def extreme_change_for_window(points, days, find_max=True):
    if len(points) < 2:
        return None

    first_day = points[0]["date"]
    last_day = points[-1]["date"]
    current_end = first_day + timedelta(days=days)
    best = None

    while current_end <= last_day:
        current_start = current_end - timedelta(days=days)
        start_weight = value_on_day(points, current_start)
        end_weight = value_on_day(points, current_end)
        if start_weight is not None and end_weight is not None:
            change = end_weight - start_weight
            if (find_max and change <= 0) or (not find_max and change >= 0):
                current_end += timedelta(days=1)
                continue
            if best is None or (change > best["change_kg"] if find_max else change < best["change_kg"]):
                best = {
                    "change_kg": change,
                    "start_day": current_start.isoformat(),
                    "end_day": current_end.isoformat(),
                }
        current_end += timedelta(days=1)

    return best


def trend_status(rate):
    if rate is None:
        return None
    if rate < -0.2:
        return "spadkowe"
    if rate > 0.2:
        return "wzrostowe"
    return "stabilne"


def read_weight_stats():
    events = all_weight_history_events_chronological()
    if not events:
        return {"ok": True, "stats": {"measurement_count": 0}}

    points = daily_weight_points(events)
    latest = events[-1]
    latest_day = date.fromisoformat(latest["day"])
    latest_weight = float(latest["weight_kg"])
    latest_day_weight = value_on_day(points, latest_day)
    current_change_weight = latest_day_weight if latest_day_weight is not None else latest_weight
    first = events[0]
    weights = [float(event["weight_kg"]) for event in events]
    highest = max(events, key=lambda event: float(event["weight_kg"]))
    lowest = min(events, key=lambda event: float(event["weight_kg"]))
    may_1_2026 = date(2026, 5, 1)
    events_since_may_1_2026 = [
        event for event in events
        if date.fromisoformat(event["day"]) >= may_1_2026
    ]
    highest_since_may_1_2026 = (
        max(events_since_may_1_2026, key=lambda event: float(event["weight_kg"]))
        if events_since_may_1_2026 else None
    )
    lowest_since_may_1_2026 = (
        min(events_since_may_1_2026, key=lambda event: float(event["weight_kg"]))
        if events_since_may_1_2026 else None
    )

    def change_from(value):
        if value is None:
            return None
        return current_change_weight - value

    previous_change = None
    if len(events) >= 2:
        previous_change = latest_weight - float(events[-2]["weight_kg"])

    changes = {
        "previous": previous_change,
        "days_7": change_from(value_on_day(points, latest_day - timedelta(days=7))),
        "days_30": change_from(value_on_day(points, latest_day - timedelta(days=30))),
        "first": latest_weight - float(first["weight_kg"]) if len(events) >= 2 else None,
    }

    moving_averages = {
        "days_7": average_for_window(points, latest_day, 7),
        "days_14": average_for_window(points, latest_day, 14),
        "days_30": average_for_window(points, latest_day, 30),
    }

    rates = {}
    for days in (7, 14, 30):
        start_weight = value_on_day(points, latest_day - timedelta(days=days))
        change = None if start_weight is None else current_change_weight - start_weight
        rate = None if change is None else (change / days) * 7
        rates[f"days_{days}"] = {
            "kg_per_week": rate,
            "status": trend_status(rate),
        }

    extreme_changes = {}
    for days in (7, 30):
        extreme_changes[f"days_{days}"] = {
            "gain": extreme_change_for_window(points, days, find_max=True),
            "loss": extreme_change_for_window(points, days, find_max=False),
        }

    since_may_1_2026 = None
    rate_since_may_1_2026 = None
    if latest_day >= may_1_2026:
        may_1_weight = value_on_day(points, may_1_2026)
        if may_1_weight is not None:
            since_may_1_2026 = current_change_weight - may_1_weight
            days_since_may_1_2026 = (latest_day - may_1_2026).days
            if days_since_may_1_2026 > 0:
                rate_since_may_1_2026 = (since_may_1_2026 / days_since_may_1_2026) * 7

    if rate_since_may_1_2026 is not None:
        rates["since_may_1_2026"] = {
            "kg_per_week": rate_since_may_1_2026,
            "status": trend_status(rate_since_may_1_2026),
        }

    def rounded_extreme_change(value):
        if value is None:
            return None
        return {
            **value,
            "change_kg": round(value["change_kg"], 2),
        }

    return {
        "ok": True,
        "stats": {
            "current_weight_kg": round(latest_weight, 2),
            "current_timestamp": latest["timestamp"],
            "measurement_count": len(events),
            "first_timestamp": first["timestamp"],
            "last_timestamp": latest["timestamp"],
            "first_weight_kg": round(float(first["weight_kg"]), 2),
            "highest_weight_kg": round(float(highest["weight_kg"]), 2),
            "highest_timestamp": highest["timestamp"],
            "lowest_weight_kg": round(float(lowest["weight_kg"]), 2),
            "lowest_timestamp": lowest["timestamp"],
            "highest_weight_kg_since_may_1_2026": (
                round(float(highest_since_may_1_2026["weight_kg"]), 2)
                if highest_since_may_1_2026 else None
            ),
            "highest_timestamp_since_may_1_2026": (
                highest_since_may_1_2026["timestamp"] if highest_since_may_1_2026 else None
            ),
            "lowest_weight_kg_since_may_1_2026": (
                round(float(lowest_since_may_1_2026["weight_kg"]), 2)
                if lowest_since_may_1_2026 else None
            ),
            "lowest_timestamp_since_may_1_2026": (
                lowest_since_may_1_2026["timestamp"] if lowest_since_may_1_2026 else None
            ),
            "changes": {key: None if value is None else round(value, 2) for key, value in changes.items()},
            "moving_averages": {
                key: None if value is None else round(value, 2)
                for key, value in moving_averages.items()
            },
            "rates": {
                key: {
                    "kg_per_week": None if value["kg_per_week"] is None else round(value["kg_per_week"], 2),
                    "status": value["status"],
                }
                for key, value in rates.items()
            },
            "extreme_changes": {
                key: {
                    "gain": rounded_extreme_change(value["gain"]),
                    "loss": rounded_extreme_change(value["loss"]),
                }
                for key, value in extreme_changes.items()
            },
            "since_may_1_2026": None if since_may_1_2026 is None else round(since_may_1_2026, 2),
        },
    }


def read_steps_store():
    if not STEPS_JSON.exists():
        return {"days": {}}
    try:
        with STEPS_JSON.open("r", encoding="utf-8") as f:
            payload = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"days": {}}
    if not isinstance(payload, dict) or not isinstance(payload.get("days"), dict):
        return {"days": {}}
    return {"days": payload["days"]}


def write_steps_store(store):
    rewrite_json_file(STEPS_JSON, {"days": store.get("days", {})})


def normalize_steps_day(value):
    raw = str(value or "").strip()
    try:
        date.fromisoformat(raw)
    except ValueError:
        raise ValueError("Invalid day")
    return raw


def normalize_steps_value(value):
    try:
        steps = int(round(float(value)))
    except (TypeError, ValueError):
        raise ValueError("Invalid steps")
    return max(0, steps)


AUTOMATIC_STEP_SOURCES = {"automatic", "health-connect", "health_connect", "phone"}


def compose_steps_event(day, row):
    raw = row if isinstance(row, dict) else {"steps": row}
    legacy_steps = normalize_steps_value(raw.get("normal_steps", raw.get("steps", 0)))
    legacy_source = str(raw.get("normal_source") or raw.get("source") or "manual")
    has_explicit_automatic = raw.get("automatic_steps") is not None
    if "manual_steps" in raw or has_explicit_automatic:
        manual_steps = normalize_steps_value(raw.get("manual_steps", 0))
        automatic_steps = normalize_steps_value(raw.get("automatic_steps") or 0)
    elif legacy_source.lower() in AUTOMATIC_STEP_SOURCES:
        manual_steps = 0
        automatic_steps = legacy_steps
        has_explicit_automatic = True
    else:
        manual_steps = legacy_steps
        automatic_steps = 0
    normal_mode = str(raw.get("normal_mode") or ("automatic" if has_explicit_automatic else "manual"))
    if normal_mode not in {"manual", "automatic"}:
        normal_mode = "automatic" if has_explicit_automatic else "manual"
    if normal_mode == "automatic" and has_explicit_automatic:
        normal_steps = automatic_steps
        normal_source = "health_connect"
    else:
        normal_steps = manual_steps
        normal_source = str(raw.get("manual_source") or (legacy_source if legacy_source.lower() not in AUTOMATIC_STEP_SOURCES else "manual"))
    sessions = {}
    raw_sessions = raw.get("virtual_walk_sessions")
    if not isinstance(raw_sessions, dict):
        raw_sessions = {}
    for session_id, session in raw_sessions.items():
        if not isinstance(session, dict):
            continue
        try:
            virtual_steps = normalize_steps_value(session.get("steps"))
        except ValueError:
            continue
        sessions[str(session_id)] = {
            **session,
            "steps": virtual_steps,
            "source": "virtual_walk",
        }
    virtual_steps = sum(session["steps"] for session in sessions.values())
    return {
        "day": day,
        "steps": normal_steps + virtual_steps,
        "normal_steps": normal_steps,
        "manual_steps": manual_steps,
        "automatic_steps": automatic_steps,
        "automatic_available": has_explicit_automatic,
        "automatic_raw_steps": normalize_steps_value(raw.get("automatic_raw_steps") or automatic_steps),
        "automatic_excluded_steps": normalize_steps_value(raw.get("automatic_excluded_steps") or 0),
        "automatic_captured_at": raw.get("automatic_captured_at"),
        "automatic_excluded_intervals": raw.get("automatic_excluded_intervals") if isinstance(raw.get("automatic_excluded_intervals"), list) else [],
        "normal_mode": normal_mode,
        "virtual_steps": virtual_steps,
        "updated_at": raw.get("updated_at"),
        "source": normal_source,
        "normal_source": normal_source,
        "sources": [
            {"key": "manual", "source": "manual", "steps": manual_steps, "counted": normal_mode == "manual"},
            {"key": "automatic", "source": "health_connect", "steps": automatic_steps, "counted": normal_mode == "automatic" and has_explicit_automatic},
            {"key": "virtual_walk", "source": "virtual_walk", "steps": virtual_steps, "counted": True},
        ],
        "virtual_walk_sessions": sessions,
    }


def live_workout_step_exclusions(day, now_ms=None):
    normalized_day = normalize_steps_day(day)
    zone = ZoneInfo(os.environ.get("DASHBOARD_TIMEZONE") or os.environ.get("TZ") or "Europe/Warsaw")
    local_day = date.fromisoformat(normalized_day)
    day_start = int(datetime.combine(local_day, datetime.min.time(), tzinfo=zone).timestamp() * 1000)
    day_end = int(datetime.combine(local_day + timedelta(days=1), datetime.min.time(), tzinfo=zone).timestamp() * 1000)
    current_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    intervals = []
    active = False
    for session in LIVE_WORKOUT_STORE.history(limit=10000):
        if session.get("started_by") != "dashboard":
            continue
        try:
            started_at = int(session.get("started_at"))
        except (TypeError, ValueError):
            continue
        status = str(session.get("status") or "")
        if status in {"running", "paused"}:
            ended_at = current_ms
            active = True
        else:
            ended_at = session.get("ended_at")
            if ended_at is None:
                ended_at = started_at + int(max(0, float(session.get("duration_seconds") or 0)) * 1000)
            try:
                ended_at = int(ended_at)
            except (TypeError, ValueError):
                continue
        start = max(day_start, started_at)
        end = min(day_end, ended_at)
        if end <= start:
            continue
        intervals.append({
            "start": start,
            "end": end,
            "session_id": session.get("id"),
            "status": status,
            "workout_type": session.get("workout_type"),
        })
    intervals.sort(key=lambda item: (item["start"], item["end"]))
    return {"ok": True, "day": normalized_day, "active": active, "intervals": intervals}


def automatic_step_payload_covers_exclusions(payload, required_intervals):
    if not required_intervals:
        return True
    raw_steps = (payload or {}).get("raw_steps")
    excluded_steps = (payload or {}).get("excluded_steps")
    supplied_intervals = (payload or {}).get("excluded_intervals")
    if raw_steps is None or excluded_steps is None or not isinstance(supplied_intervals, list):
        return False
    counted_steps = normalize_steps_value((payload or {}).get("steps"))
    raw_steps = normalize_steps_value(raw_steps)
    excluded_steps = normalize_steps_value(excluded_steps)
    if counted_steps != max(0, raw_steps - excluded_steps):
        return False

    for required in required_intervals:
        required_session_id = str(required.get("session_id") or "")
        try:
            required_start = int(required.get("start"))
            required_end = int(required.get("end"))
        except (TypeError, ValueError):
            return False
        covered = False
        for supplied in supplied_intervals:
            if not isinstance(supplied, dict):
                continue
            if str(supplied.get("session_id") or "") != required_session_id:
                continue
            try:
                supplied_start = int(supplied.get("start"))
                supplied_end = int(supplied.get("end"))
            except (TypeError, ValueError):
                continue
            if supplied_start <= required_start and supplied_end >= required_end:
                covered = True
                break
        if not covered:
            return False
    return True


def upsert_steps_event(payload):
    day = normalize_steps_day((payload or {}).get("day"))
    steps = normalize_steps_value((payload or {}).get("steps"))
    source = str((payload or {}).get("source") or "manual").strip() or "manual"
    store = read_steps_store()
    existing = compose_steps_event(day, store["days"].get(day, {}))
    supplied_automatic = (payload or {}).get("automatic_steps")
    supplied_manual = (payload or {}).get("manual_steps")
    if source.lower() in AUTOMATIC_STEP_SOURCES:
        exclusions = live_workout_step_exclusions(day)
        if exclusions["active"]:
            return {
                "ok": True,
                "ignored": True,
                "reason": "live_workout_active",
                "event": existing,
                "exclusions": exclusions["intervals"],
            }
        if not automatic_step_payload_covers_exclusions(payload, exclusions["intervals"]):
            return {
                "ok": True,
                "ignored": True,
                "reason": "workout_exclusions_required",
                "event": existing,
                "exclusions": exclusions["intervals"],
            }
    sessions = dict(existing["virtual_walk_sessions"])
    supplied_sessions = (payload or {}).get("virtual_walk_sessions")
    if isinstance(supplied_sessions, dict):
        for session_id, session in supplied_sessions.items():
            if isinstance(session, dict):
                sessions[str(session_id)] = {**session, "source": "virtual_walk"}
    if source == "virtual_walk":
        session_id = str((payload or {}).get("session_id") or "").strip()
        if not session_id:
            raise ValueError("session_id is required for virtual_walk steps")
        sessions[session_id] = {
            "steps": steps,
            "source": "virtual_walk",
            "workout_id": session_id,
            "duration_seconds": max(0, round(float((payload or {}).get("duration_seconds") or 0), 3)),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        manual_steps = existing["manual_steps"]
        automatic_steps = existing["automatic_steps"]
        automatic_available = existing["automatic_available"]
        normal_mode = existing["normal_mode"]
        manual_source = existing["normal_source"] if normal_mode == "manual" else "manual"
    elif source.lower() in AUTOMATIC_STEP_SOURCES:
        manual_steps = normalize_steps_value(supplied_manual) if supplied_manual is not None else existing["manual_steps"]
        automatic_steps = steps
        automatic_available = True
        requested_mode = str((payload or {}).get("normal_mode") or "")
        normal_mode = requested_mode if requested_mode in {"manual", "automatic"} else ("manual" if manual_steps > 0 else "automatic")
        manual_source = existing["normal_source"] if existing["normal_mode"] == "manual" else "manual"
    else:
        manual_steps = normalize_steps_value((payload or {}).get("manual_steps", (payload or {}).get("normal_steps", steps)))
        automatic_steps = normalize_steps_value(supplied_automatic) if supplied_automatic is not None else existing["automatic_steps"]
        automatic_available = supplied_automatic is not None or existing["automatic_available"]
        requested_mode = str((payload or {}).get("normal_mode") or "")
        normal_mode = requested_mode if requested_mode in {"manual", "automatic"} and automatic_available else "manual"
        manual_source = source
    store["days"][day] = {
        "steps": manual_steps,
        "normal_steps": manual_steps,
        "manual_steps": manual_steps,
        "automatic_steps": automatic_steps if automatic_available else None,
        "automatic_raw_steps": normalize_steps_value((payload or {}).get("raw_steps") if (payload or {}).get("raw_steps") is not None else existing["automatic_raw_steps"]),
        "automatic_excluded_steps": normalize_steps_value((payload or {}).get("excluded_steps") if (payload or {}).get("excluded_steps") is not None else existing["automatic_excluded_steps"]),
        "automatic_captured_at": (payload or {}).get("captured_at") or existing["automatic_captured_at"],
        "automatic_excluded_intervals": (payload or {}).get("excluded_intervals") if isinstance((payload or {}).get("excluded_intervals"), list) else existing["automatic_excluded_intervals"],
        "normal_mode": normal_mode,
        "manual_source": manual_source,
        "source": manual_source,
        "normal_source": manual_source,
        "virtual_walk_sessions": sessions,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    write_steps_store(store)
    event = compose_steps_event(day, store["days"][day])
    broadcast_step_update({"type": "steps-updated", "event": event})
    return {"ok": True, "event": event}


def delete_steps_event(payload):
    day = normalize_steps_day((payload or {}).get("day"))
    store = read_steps_store()
    existing = compose_steps_event(day, store["days"].get(day, {}))
    deleted = 1 if day in store["days"] and existing["manual_steps"] > 0 else 0
    if existing["virtual_walk_sessions"] or existing["automatic_available"]:
        store["days"][day] = {
            "steps": 0,
            "normal_steps": 0,
            "manual_steps": 0,
            "automatic_steps": existing["automatic_steps"] if existing["automatic_available"] else None,
            "automatic_raw_steps": existing["automatic_raw_steps"],
            "automatic_excluded_steps": existing["automatic_excluded_steps"],
            "automatic_captured_at": existing["automatic_captured_at"],
            "automatic_excluded_intervals": existing["automatic_excluded_intervals"],
            "normal_mode": "automatic" if existing["automatic_available"] else "manual",
            "source": "manual",
            "normal_source": "manual",
            "manual_source": "manual",
            "virtual_walk_sessions": existing["virtual_walk_sessions"],
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
    else:
        store["days"].pop(day, None)
    write_steps_store(store)
    if existing["virtual_walk_sessions"] or existing["automatic_available"]:
        broadcast_step_update({"type": "steps-updated", "event": compose_steps_event(day, store["days"][day])})
    else:
        broadcast_step_update({"type": "steps-deleted", "day": day, "deleted": deleted})
    return {"ok": True, "deleted": deleted}


def normalize_health_snapshot(payload):
    if not isinstance(payload, dict):
        raise ValueError("Invalid health snapshot")
    day = normalize_steps_day(payload.get("day") or date.today().isoformat())
    snapshot = {
        "day": day,
        "received_at": datetime.now().isoformat(timespec="seconds"),
        "source": str(payload.get("source") or "health-connect"),
        "payload": payload,
    }
    return snapshot


def write_health_snapshot(payload):
    snapshot = normalize_health_snapshot(payload)
    HEALTH_DATA_DIR.mkdir(parents=True, exist_ok=True)
    rewrite_json_file(HEALTH_LATEST_JSON, snapshot)
    line = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
    with HEALTH_SNAPSHOTS_JSONL.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    return {"ok": True, "snapshot": {"day": snapshot["day"], "received_at": snapshot["received_at"]}}


def read_health_latest():
    if not HEALTH_LATEST_JSON.exists():
        return {"ok": False, "error": "No Health Connect snapshot yet"}
    try:
        with HEALTH_LATEST_JSON.open("r", encoding="utf-8") as f:
            payload = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"ok": False, "error": "Invalid Health Connect snapshot"}
    return {"ok": True, "snapshot": payload}


def _health_sleep_snapshot_score(snapshot):
    payload = snapshot.get("payload") if isinstance(snapshot, dict) else None
    payload = payload if isinstance(payload, dict) else {}
    sleep = payload.get("sleep") if isinstance(payload.get("sleep"), dict) else {}
    sessions = sleep.get("sessions") if isinstance(sleep.get("sessions"), list) else []
    total_seconds = 0.0
    valid_sessions = 0
    for session in sessions:
        if not isinstance(session, dict):
            continue
        try:
            start = datetime.fromisoformat(str(session.get("start") or "").replace("Z", "+00:00"))
            end = datetime.fromisoformat(str(session.get("end") or "").replace("Z", "+00:00"))
            duration = (end - start).total_seconds()
        except (TypeError, ValueError):
            continue
        if duration > 0:
            valid_sessions += 1
            total_seconds += duration
    heart_rate = payload.get("heart_rate") if isinstance(payload.get("heart_rate"), dict) else {}
    samples = heart_rate.get("samples") if isinstance(heart_rate.get("samples"), list) else []
    received_at = str(snapshot.get("received_at") or "") if isinstance(snapshot, dict) else ""
    return total_seconds, valid_sessions, len(samples), received_at


def read_health_sleep_history():
    """Return one richest Health Connect sleep snapshot per captured day."""
    best_by_day = {}
    latest_received_at = ""

    def consider(snapshot):
        nonlocal latest_received_at
        if not isinstance(snapshot, dict):
            return
        payload = snapshot.get("payload")
        if not isinstance(payload, dict):
            return
        day = str(snapshot.get("day") or payload.get("day") or "").strip()
        if not day:
            return
        received_at = str(snapshot.get("received_at") or "")
        if received_at > latest_received_at:
            latest_received_at = received_at
        current = best_by_day.get(day)
        if current is None or _health_sleep_snapshot_score(snapshot) > _health_sleep_snapshot_score(current):
            best_by_day[day] = snapshot

    if HEALTH_SNAPSHOTS_JSONL.exists():
        try:
            with HEALTH_SNAPSHOTS_JSONL.open("r", encoding="utf-8") as source:
                for line in source:
                    try:
                        consider(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except OSError:
            pass

    latest = read_health_latest().get("snapshot")
    consider(latest)

    snapshots = []
    for day in sorted(best_by_day, reverse=True):
        snapshot = best_by_day[day]
        payload = snapshot["payload"]
        snapshots.append({
            "day": day,
            "received_at": snapshot.get("received_at"),
            "source": snapshot.get("source") or "health-connect",
            "payload": {
                "day": payload.get("day") or day,
                "timezone": payload.get("timezone"),
                "window_start": payload.get("window_start"),
                "window_end": payload.get("window_end"),
                "heart_rate": payload.get("heart_rate") or {"samples": []},
                "sleep": payload.get("sleep") or {"sessions": []},
            },
        })
    return {
        "ok": True,
        "latestReceivedAt": latest_received_at or None,
        "snapshots": snapshots,
    }


def read_steps_events():
    store = read_steps_store()
    events = []
    for day, row in store["days"].items():
        try:
            parsed_day = normalize_steps_day(day)
            event = compose_steps_event(parsed_day, row)
        except ValueError:
            continue
        events.append(event)
    events.sort(key=lambda item: item["day"], reverse=True)
    return {"ok": True, "events": events, "count": len(events)}


def read_live_workout_backup():
    workouts = []
    for summary in LIVE_WORKOUT_STORE.history(limit=10000):
        detail = LIVE_WORKOUT_STORE.session(summary.get("id"))
        if detail:
            workouts.append(detail)
    return {
        "workouts": workouts,
        "weightEvents": read_weight_events().get("events", []),
        "stepEvents": read_steps_events().get("events", []),
        "healthSnapshot": read_health_latest().get("snapshot"),
        "planTracking": read_settings_payload("live-workout-plan").get("data"),
        "strengthData": STRENGTH_STORE.export_data(),
    }


def merge_weight_backup_events(events):
    source = SCALE_DATA_DIR / "scale_measurements.jsonl"
    existing = []
    if source.exists():
        with source.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                except (json.JSONDecodeError, TypeError):
                    continue
                if parse_weight_history_row(row):
                    existing.append(row)
    seen = {weight_event_dedupe_key(parse_weight_history_row(row) or row) for row in existing}
    imported = 0
    for event in events if isinstance(events, list) else []:
        parsed = parse_weight_history_row(event)
        if not parsed:
            continue
        key = weight_event_dedupe_key(parsed)
        if key in seen:
            continue
        existing.append({**parsed, "stable": True, "has_weight": True})
        seen.add(key)
        imported += 1
    if imported:
        existing.sort(key=lambda row: str(row.get("timestamp") or ""))
        rewrite_jsonl_file(source, existing)
        latest = latest_weight_history_event()
        if latest:
            rewrite_json_file(SCALE_LATEST_JSON, latest)
    return imported


def import_live_workout_backup(payload):
    if not isinstance(payload, dict) or payload.get("kind") != "cleaning-dashboard-full-backup":
        raise ValueError("Invalid backup format")
    if payload.get("schemaVersion") != 1:
        raise ValueError("Unsupported backup schema")

    workout_count = 0
    for item in payload.get("workouts", []):
        if not isinstance(item, dict) or item.get("started_at") is None:
            continue
        imported = dict(item)
        raw_id = str(imported.get("id") or "")
        if not re.fullmatch(r"[a-zA-Z0-9-]+", raw_id):
            imported["id"] = f"backup-{uuid.uuid4()}"
        LIVE_WORKOUT_STORE.import_summary(imported)
        workout_count += 1

    weight_count = merge_weight_backup_events(payload.get("weightEvents", []))
    step_count = 0
    for event in payload.get("stepEvents", []):
        try:
            upsert_steps_event(event)
            step_count += 1
        except (TypeError, ValueError):
            continue

    plan_tracking = payload.get("planTracking")
    if isinstance(plan_tracking, dict):
        write_settings_payload("live-workout-plan", {"data": plan_tracking})

    strength_data = payload.get("strengthData")
    strength_merged = STRENGTH_STORE.import_data(strength_data) if isinstance(strength_data, dict) else {}

    health_imported = False
    snapshot = payload.get("healthSnapshot")
    if isinstance(snapshot, dict) and isinstance(snapshot.get("payload"), dict):
        current = read_health_latest().get("snapshot")
        if not current or str(snapshot.get("day") or "") >= str(current.get("day") or ""):
            write_health_snapshot(snapshot["payload"])
            health_imported = True

    return {
        "ok": True,
        "merged": {
            "workouts": workout_count,
            "weightEvents": weight_count,
            "stepEvents": step_count,
            "healthSnapshot": health_imported,
            "planTracking": isinstance(plan_tracking, dict),
            "strengthData": strength_merged,
        },
    }


def read_steps_history(limit_days=30, end_day=None):
    store = read_steps_store()
    days = max(1, int(limit_days or 30))
    try:
        end = date.fromisoformat(str(end_day)) if end_day else date.today()
    except ValueError:
        end = date.today()
    today = date.today()
    if end > today:
        end = today
    start = end - timedelta(days=days - 1)

    daily = []
    for offset in range(days):
        current_day = start + timedelta(days=offset)
        key = current_day.isoformat()
        row = store["days"].get(key)
        steps = 0
        normal_steps = 0
        manual_steps = 0
        automatic_steps = 0
        automatic_available = False
        normal_mode = "manual"
        virtual_steps = 0
        sources = []
        filled = True
        if row is not None:
            try:
                event = compose_steps_event(key, row)
                steps = event["steps"]
                normal_steps = event["normal_steps"]
                manual_steps = event["manual_steps"]
                automatic_steps = event["automatic_steps"]
                automatic_available = event["automatic_available"]
                normal_mode = event["normal_mode"]
                virtual_steps = event["virtual_steps"]
                sources = event["sources"]
                filled = False
            except ValueError:
                steps = 0
        daily.append({
            "day": key,
            "steps": steps,
            "normal_steps": normal_steps,
            "manual_steps": manual_steps,
            "automatic_steps": automatic_steps,
            "automatic_available": automatic_available,
            "normal_mode": normal_mode,
            "virtual_steps": virtual_steps,
            "sources": sources,
            "filled": filled,
        })
    return {"ok": True, "daily": daily, "count": len(daily)}


def read_diet_store():
    if not DIET_JSON.exists():
        return {"goal_kcal": DIET_DEFAULT_GOAL_KCAL, "days": {}}
    try:
        with DIET_JSON.open("r", encoding="utf-8") as f:
            payload = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"goal_kcal": DIET_DEFAULT_GOAL_KCAL, "days": {}}
    if not isinstance(payload, dict):
        return {"goal_kcal": DIET_DEFAULT_GOAL_KCAL, "days": {}}
    goal = normalize_diet_kcal(payload.get("goal_kcal", DIET_DEFAULT_GOAL_KCAL))
    days = payload.get("days") if isinstance(payload.get("days"), dict) else {}
    return {"goal_kcal": goal, "days": days}


def write_diet_store(store):
    rewrite_json_file(
        DIET_JSON,
        {
            "goal_kcal": normalize_diet_kcal(store.get("goal_kcal", DIET_DEFAULT_GOAL_KCAL)),
            "days": store.get("days", {}),
        },
    )


def normalize_diet_day(value):
    raw = str(value or "").strip()
    try:
        date.fromisoformat(raw)
    except ValueError:
        raise ValueError("Invalid day")
    return raw


def normalize_diet_kcal(value):
    try:
        kcal = int(round(float(str(value).replace(",", "."))))
    except (TypeError, ValueError):
        raise ValueError("Invalid kcal")
    return max(0, kcal)


DIET_ESTIMATE_FIELDS = {
    "estimated_kcal",
    "calories_source",
    "estimate_confidence",
    "estimate_reason",
    "estimate_components",
    "estimated_at",
}

DIET_IGNORE_FIELDS = {
    "ignored_at",
}


def clean_diet_estimate_text(value):
    return re.sub(r"\s+", " ", str(value or "").strip())[:400]


def normalize_diet_estimate_confidence(value):
    text = str(value or "").strip().lower()
    return text if text in {"high", "medium", "low"} else "low"


def normalize_diet_estimate_components(value):
    if not isinstance(value, dict):
        return {}
    allowed = {
        "baselineCalories": "baseline_calories",
        "weightAdjustment": "weight_adjustment",
        "stepsAdjustment": "steps_adjustment",
        "dailyTrendKg": "daily_trend_kg",
        "weightSurpriseKg": "weight_surprise_kg",
        "baselineSteps": "baseline_steps",
        "knownStepDays": "known_step_days",
    }
    components = {}
    for source_key, target_key in allowed.items():
        raw = value.get(source_key, value.get(target_key))
        if raw is None:
            components[target_key] = None
            continue
        try:
            parsed = float(str(raw).replace(",", "."))
        except (TypeError, ValueError):
            components[target_key] = None
            continue
        components[target_key] = round(parsed, 4) if target_key == "daily_trend_kg" else round(parsed, 3)
    return components


def row_has_manual_diet_meals(row):
    return isinstance(row, dict) and bool(row.get("meals"))


def row_is_ignored_diet_day(row):
    return isinstance(row, dict) and (row.get("calories_source") == "ignored" or bool(row.get("ignored_at")))


def clear_diet_estimate(row):
    if not isinstance(row, dict):
        return
    for key in DIET_ESTIMATE_FIELDS:
        row.pop(key, None)


def clear_diet_ignore(row):
    if not isinstance(row, dict):
        return
    for key in DIET_IGNORE_FIELDS:
        row.pop(key, None)
    if row.get("calories_source") == "ignored":
        row.pop("calories_source", None)


def clean_diet_text(value):
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if not text:
        raise ValueError("Missing meal name")
    return text[:180].lower()


def normalize_diet_meal(row):
    if not isinstance(row, dict):
        raise ValueError("Invalid meal")
    meal_id = str(row.get("id") or "").strip()
    if not meal_id:
        meal_id = f"meal-{int(time.time() * 1000)}"
    return {
        "id": meal_id[:80],
        "name": clean_diet_text(row.get("name")),
        "kcal": normalize_diet_kcal(row.get("kcal")),
    }


def normalize_diet_day_row(day, row, default_goal):
    meals = []
    if isinstance(row, dict) and isinstance(row.get("meals"), list):
        for meal in row["meals"]:
            try:
                meals.append(normalize_diet_meal(meal))
            except ValueError:
                continue
    goal = default_goal
    if isinstance(row, dict) and row.get("goal_kcal") is not None:
        try:
            goal = normalize_diet_kcal(row.get("goal_kcal"))
        except ValueError:
            goal = default_goal
    total = sum(meal["kcal"] for meal in meals)
    estimated_kcal = None
    if not meals and isinstance(row, dict) and row.get("estimated_kcal") is not None:
        try:
            estimated_kcal = normalize_diet_kcal(row.get("estimated_kcal"))
        except ValueError:
            estimated_kcal = None
    ignored = isinstance(row, dict) and (row.get("calories_source") == "ignored" or row.get("ignored_at"))
    calories_source = "manual" if meals else "ignored" if ignored else "estimated" if estimated_kcal else "missing"
    final_total = total if calories_source == "manual" else ((estimated_kcal or 0) if calories_source == "estimated" else 0)
    return {
        "day": day,
        "goal_kcal": goal,
        "total_kcal": final_total,
        "manual_kcal": total if meals else None,
        "estimated_kcal": estimated_kcal,
        "calories_source": calories_source,
        "estimate_confidence": normalize_diet_estimate_confidence(row.get("estimate_confidence")) if isinstance(row, dict) and estimated_kcal else None,
        "estimate_reason": clean_diet_estimate_text(row.get("estimate_reason")) if isinstance(row, dict) and estimated_kcal else "",
        "estimate_components": normalize_diet_estimate_components(row.get("estimate_components")) if isinstance(row, dict) and estimated_kcal else {},
        "ignored": calories_source == "ignored",
        "ignored_at": row.get("ignored_at") if isinstance(row, dict) and calories_source == "ignored" else None,
        "remaining_kcal": goal - final_total,
        "meals": meals,
    }


def read_diet_days():
    store = read_diet_store()
    goal = normalize_diet_kcal(store.get("goal_kcal", DIET_DEFAULT_GOAL_KCAL))
    days = []
    for day, row in store.get("days", {}).items():
        try:
            parsed_day = normalize_diet_day(day)
        except ValueError:
            continue
        days.append(normalize_diet_day_row(parsed_day, row, goal))
    days.sort(key=lambda item: item["day"], reverse=True)
    return {"ok": True, "goal_kcal": goal, "days": days, "count": len(days)}


def read_diet_history(limit_days=30, end_day=None):
    store = read_diet_store()
    goal = normalize_diet_kcal(store.get("goal_kcal", DIET_DEFAULT_GOAL_KCAL))
    days = max(1, int(limit_days or 30))
    try:
        end = date.fromisoformat(str(end_day)) if end_day else date.today()
    except ValueError:
        end = date.today()
    today = date.today()
    if end > today:
        end = today
    start = end - timedelta(days=days - 1)

    daily = []
    for offset in range(days):
        current_day = start + timedelta(days=offset)
        key = current_day.isoformat()
        row = normalize_diet_day_row(key, store.get("days", {}).get(key, {}), goal)
        daily.append(
            {
                "day": key,
                "goal_kcal": row["goal_kcal"],
                "total_kcal": row["total_kcal"],
                "estimated_kcal": row["estimated_kcal"],
                "calories_source": row["calories_source"],
                "estimate_confidence": row["estimate_confidence"],
                "estimate_reason": row["estimate_reason"],
                "estimate_components": row["estimate_components"],
                "ignored": row["ignored"],
                "ignored_at": row["ignored_at"],
                "meal_count": len(row["meals"]),
                "filled": row["calories_source"] != "manual",
            }
        )
    return {"ok": True, "goal_kcal": goal, "daily": daily, "count": len(daily)}


def upsert_diet_meal(payload):
    day = normalize_diet_day((payload or {}).get("day"))
    meal = normalize_diet_meal(payload or {})
    store = read_diet_store()
    days = store.setdefault("days", {})
    row = days.setdefault(day, {"goal_kcal": store.get("goal_kcal", DIET_DEFAULT_GOAL_KCAL), "meals": []})
    if not isinstance(row, dict):
        row = {"goal_kcal": store.get("goal_kcal", DIET_DEFAULT_GOAL_KCAL), "meals": []}
        days[day] = row
    meals = row.setdefault("meals", [])
    replaced = False
    for index, existing in enumerate(list(meals)):
        if isinstance(existing, dict) and str(existing.get("id") or "") == meal["id"]:
            meals[index] = meal
            replaced = True
            break
    if not replaced:
        meals.append(meal)
    clear_diet_estimate(row)
    clear_diet_ignore(row)
    row["updated_at"] = datetime.now().isoformat(timespec="seconds")
    write_diet_store(store)
    return {"ok": True, "meal": meal, "day": normalize_diet_day_row(day, row, store.get("goal_kcal", DIET_DEFAULT_GOAL_KCAL))}


def delete_diet_meal(payload):
    day = normalize_diet_day((payload or {}).get("day"))
    meal_id = str((payload or {}).get("id") or "").strip()
    if not meal_id:
        raise ValueError("Missing meal id")
    store = read_diet_store()
    row = store.get("days", {}).get(day)
    deleted = 0
    if isinstance(row, dict) and isinstance(row.get("meals"), list):
        kept = []
        for meal in row["meals"]:
            if isinstance(meal, dict) and str(meal.get("id") or "") == meal_id:
                deleted += 1
                continue
            kept.append(meal)
        row["meals"] = kept
        row["updated_at"] = datetime.now().isoformat(timespec="seconds")
        if not kept:
            store.get("days", {}).pop(day, None)
        write_diet_store(store)
    return {"ok": True, "deleted": deleted}


def remove_virtual_walk_steps(session_id):
    safe_id = str(session_id or "").strip()
    if not safe_id:
        return 0
    store = read_steps_store()
    removed_steps = 0
    changed_events = []
    deleted_days = []
    for day, row in list(store["days"].items()):
        try:
            event = compose_steps_event(day, row)
        except ValueError:
            continue
        sessions = dict(event["virtual_walk_sessions"])
        removed = sessions.pop(safe_id, None)
        if removed is None:
            continue
        removed_steps += normalize_steps_value(removed.get("steps"))
        if event["manual_steps"] > 0 or event["automatic_available"] or sessions:
            store["days"][day] = {
                "steps": event["manual_steps"],
                "normal_steps": event["manual_steps"],
                "manual_steps": event["manual_steps"],
                "automatic_steps": event["automatic_steps"] if event["automatic_available"] else None,
                "automatic_raw_steps": event["automatic_raw_steps"],
                "automatic_excluded_steps": event["automatic_excluded_steps"],
                "automatic_captured_at": event["automatic_captured_at"],
                "automatic_excluded_intervals": event["automatic_excluded_intervals"],
                "normal_mode": event["normal_mode"],
                "source": event["normal_source"],
                "normal_source": event["normal_source"],
                "manual_source": event["normal_source"] if event["normal_mode"] == "manual" else "manual",
                "virtual_walk_sessions": sessions,
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            }
            changed_events.append((day, store["days"][day]))
        else:
            store["days"].pop(day, None)
            deleted_days.append(day)
    if not removed_steps and not changed_events and not deleted_days:
        return 0
    write_steps_store(store)
    for day, row in changed_events:
        broadcast_step_update({"type": "steps-updated", "event": compose_steps_event(day, row)})
    for day in deleted_days:
        broadcast_step_update({"type": "steps-deleted", "day": day, "deleted": 1})
    return removed_steps


def upsert_diet_estimates(payload):
    estimates = (payload or {}).get("estimates")
    if not isinstance(estimates, list):
        raise ValueError("Invalid estimates")
    store = read_diet_store()
    days = store.setdefault("days", {})
    saved = 0
    skipped_manual = 0
    skipped_ignored = 0
    now = datetime.now().isoformat(timespec="seconds")

    for item in estimates:
        if not isinstance(item, dict):
            continue
        try:
            day = normalize_diet_day(item.get("day") or item.get("date"))
            estimated_kcal = normalize_diet_kcal(item.get("estimatedCalories", item.get("estimated_kcal")))
        except ValueError:
            continue
        row = days.setdefault(day, {"goal_kcal": store.get("goal_kcal", DIET_DEFAULT_GOAL_KCAL), "meals": []})
        if not isinstance(row, dict):
            row = {"goal_kcal": store.get("goal_kcal", DIET_DEFAULT_GOAL_KCAL), "meals": []}
            days[day] = row
        if row_has_manual_diet_meals(row):
            skipped_manual += 1
            continue
        if row_is_ignored_diet_day(row):
            skipped_ignored += 1
            continue
        row["estimated_kcal"] = estimated_kcal
        row["calories_source"] = "estimated"
        row["estimate_confidence"] = normalize_diet_estimate_confidence(item.get("estimateConfidence", item.get("estimate_confidence")))
        row["estimate_reason"] = clean_diet_estimate_text(item.get("estimateReason", item.get("estimate_reason")))
        row["estimate_components"] = normalize_diet_estimate_components(item.get("estimateComponents", item.get("estimate_components")))
        row["estimated_at"] = now
        saved += 1

    if saved:
        write_diet_store(store)
    return {"ok": True, "saved": saved, "skipped_manual": skipped_manual, "skipped_ignored": skipped_ignored}


def delete_diet_estimates(payload):
    raw_days = (payload or {}).get("days")
    day_filter = None
    if isinstance(raw_days, list):
        day_filter = set()
        for raw_day in raw_days:
            try:
                day_filter.add(normalize_diet_day(raw_day))
            except ValueError:
                continue
    store = read_diet_store()
    days = store.setdefault("days", {})
    deleted = 0
    for day in list(days.keys()):
        if day_filter is not None and day not in day_filter:
            continue
        row = days.get(day)
        if not isinstance(row, dict) or row.get("estimated_kcal") is None:
            continue
        clear_diet_estimate(row)
        deleted += 1
        if not row_has_manual_diet_meals(row):
            days.pop(day, None)
    if deleted:
        write_diet_store(store)
    return {"ok": True, "deleted": deleted}


def ignore_diet_days(payload):
    raw_days = (payload or {}).get("days")
    if not isinstance(raw_days, list):
        raise ValueError("Invalid days")
    store = read_diet_store()
    days = store.setdefault("days", {})
    ignored = 0
    skipped_manual = 0
    now = datetime.now().isoformat(timespec="seconds")

    for raw_day in raw_days:
        try:
            day = normalize_diet_day(raw_day)
        except ValueError:
            continue
        row = days.setdefault(day, {"goal_kcal": store.get("goal_kcal", DIET_DEFAULT_GOAL_KCAL), "meals": []})
        if not isinstance(row, dict):
            row = {"goal_kcal": store.get("goal_kcal", DIET_DEFAULT_GOAL_KCAL), "meals": []}
            days[day] = row
        if row_has_manual_diet_meals(row):
            skipped_manual += 1
            continue
        clear_diet_estimate(row)
        row["calories_source"] = "ignored"
        row["ignored_at"] = now
        ignored += 1

    if ignored:
        write_diet_store(store)
    return {"ok": True, "ignored": ignored, "skipped_manual": skipped_manual}


def file_write_lock(path):
    key = str(Path(path).resolve())
    with JSON_WRITE_LOCKS_GUARD:
        lock = JSON_WRITE_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            JSON_WRITE_LOCKS[key] = lock
        return lock


def replace_file_with_retries(tmp_path, path):
    last_error = None
    for delay in (0, *WINDOWS_REPLACE_RETRY_DELAYS):
        if delay:
            time.sleep(delay)
        try:
            os.replace(tmp_path, path)
            return
        except PermissionError as exc:
            last_error = exc
    raise last_error


def temp_path_for_atomic_write(path):
    fd, name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
        text=True,
    )
    os.close(fd)
    return Path(name)


def rewrite_json_file(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with file_write_lock(path):
        tmp_path = temp_path_for_atomic_write(path)
        try:
            tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            replace_file_with_retries(tmp_path, path)
        finally:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass


def read_json_file(path, default):
    try:
        if not path.exists():
            return default
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except Exception:
        return default


def normalize_settings_name(raw):
    name = str(raw or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", name):
        raise ValueError("Invalid settings name")
    if name in SETTINGS_ALLOWED_NAMES or name.startswith("cleaning-history-"):
        return name
    raise ValueError("Unknown settings name")


def settings_path(name):
    normalized = normalize_settings_name(name)
    return SETTINGS_DATA_DIR / f"{normalized}.json"


def read_settings_payload(name):
    normalized = normalize_settings_name(name)
    path = settings_path(normalized)
    return {
        "ok": True,
        "name": normalized,
        "data": read_json_file(path, None),
        "storedPath": path.relative_to(ROOT).as_posix(),
    }


def write_settings_payload(name, payload):
    normalized = normalize_settings_name(name)
    data = payload.get("data") if isinstance(payload, dict) and "data" in payload else payload
    path = settings_path(normalized)
    rewrite_json_file(path, data)
    return {
        "ok": True,
        "name": normalized,
        "data": data,
        "storedPath": path.relative_to(ROOT).as_posix(),
    }


def default_budget_payload():
    return {
        "source": {"name": "", "importedAt": "", "rows": 0},
        "settings": {
            "savingsCategories": ["regularne oszczedzanie", "oszczedzanie"],
            "ignoredCategories": [],
            "userCategories": ["Jedzenie", "Zakupy spozywcze", "Chemia i dom", "Kawa i slodycze", "Restauracje", "Bary", "Delivery", "Transport", "Taxi", "Komunikacja miejska", "Rachunki", "Mieszkanie", "Subskrypcje", "Telefon i internet", "Zdrowie", "Apteka", "Ubrania", "Elektronika", "Kosmetyki", "Rozrywka", "Kultura", "Sport", "Podroze", "Prezenty", "Oszczednosci", "Przelewy", "Gotowka", "Praca", "Inne"],
            "merchantTypes": ["Sklep spozywczy", "Sklep convenience", "Dyskont", "Drogeria", "Apteka", "Restauracja", "Bar", "Kawiarnia", "Piekarnia", "Delivery", "Taxi", "Transport publiczny", "Paliwo", "Parking", "Subskrypcja", "Marketplace", "Sklep internetowy", "Usluga", "Przelew", "Bankomat", "Bank", "Urzad", "Przychodnia", "Silownia", "Kino", "Hotel", "Loty", "Inne"],
            "rejectedSuggestionKeys": [],
        },
        "transactions": [],
    }


def normalize_budget_payload(payload):
    data = payload if isinstance(payload, dict) else {}
    source = data.get("source") if isinstance(data.get("source"), dict) else {}
    settings = data.get("settings") if isinstance(data.get("settings"), dict) else {}
    defaults = default_budget_payload()
    transactions = data.get("transactions") if isinstance(data.get("transactions"), list) else []
    cleaned_transactions = [item for item in transactions if isinstance(item, dict)]
    return {
        "source": {
            "name": str(source.get("name") or "").strip(),
            "importedAt": str(source.get("importedAt") or "").strip(),
            "rows": len(cleaned_transactions),
        },
        "settings": {
            "savingsCategories": settings.get("savingsCategories") if isinstance(settings.get("savingsCategories"), list) else defaults["settings"]["savingsCategories"],
            "ignoredCategories": settings.get("ignoredCategories") if isinstance(settings.get("ignoredCategories"), list) else [],
            "userCategories": settings.get("userCategories") if isinstance(settings.get("userCategories"), list) else defaults["settings"]["userCategories"],
            "merchantTypes": settings.get("merchantTypes") if isinstance(settings.get("merchantTypes"), list) else defaults["settings"]["merchantTypes"],
            "rejectedSuggestionKeys": settings.get("rejectedSuggestionKeys") if isinstance(settings.get("rejectedSuggestionKeys"), list) else [],
        },
        "transactions": cleaned_transactions,
    }


def read_budget_payload():
    return FINANCE_SERVICE.compatibility_payload()


def write_budget_payload(payload):
    del payload
    raise FinanceError(
        "Full Budget snapshot replacement is disabled; use annotation, settings, or import operations."
    )


def import_budget_csv_from_payload(payload):
    if not isinstance(payload, dict):
        raise ValueError("Invalid budget import payload")
    raw_b64 = str(payload.get("contentBase64") or payload.get("content_base64") or "")
    if not raw_b64:
        raise ValueError("Missing CSV content")
    try:
        raw = base64.b64decode(raw_b64, validate=True)
    except Exception as exc:
        raise ValueError("Invalid CSV content") from exc
    if len(raw) > BUDGET_IMPORT_MAX_BYTES:
        raise ValueError("CSV is too large")

    filename = Path(str(payload.get("filename") or "budget.csv")).name or "budget.csv"
    import_result = FINANCE_SERVICE.import_csv(raw, filename)
    return {
        "ok": True,
        "data": FINANCE_SERVICE.compatibility_payload(),
        "importResult": import_result,
    }


class GoogleCalendarApiError(Exception):
    def __init__(self, status, body):
        super().__init__(f"Google Calendar API error {status}: {body}")
        self.status = status
        self.body = body


def rewrite_jsonl_file(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with file_write_lock(path):
        tmp_path = temp_path_for_atomic_write(path)
        try:
            with tmp_path.open("w", encoding="utf-8") as f:
                for row in rows:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
            replace_file_with_retries(tmp_path, path)
        finally:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass


def rewrite_csv_file(path, rows, fieldnames):
    path.parent.mkdir(parents=True, exist_ok=True)
    with file_write_lock(path):
        tmp_path = temp_path_for_atomic_write(path)
        try:
            with tmp_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            replace_file_with_retries(tmp_path, path)
        finally:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass


def delete_weight_event(payload):
    timestamp = str((payload or {}).get("timestamp") or "").strip()
    if not timestamp:
        raise ValueError("Missing timestamp")

    deleted = 0

    if MEASUREMENTS_JSONL := (SCALE_DATA_DIR / "scale_measurements.jsonl"):
        if MEASUREMENTS_JSONL.exists():
            kept = []
            with MEASUREMENTS_JSONL.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if str(row.get("timestamp") or "") == timestamp:
                        deleted += 1
                        continue
                    kept.append(row)
            rewrite_jsonl_file(MEASUREMENTS_JSONL, kept)

    if SCALE_MEASUREMENTS_CSV.exists():
        with SCALE_MEASUREMENTS_CSV.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or []
            kept = []
            for row in reader:
                if str(row.get("timestamp") or "") == timestamp:
                    deleted += 1
                    continue
                kept.append(row)
        if fieldnames:
            rewrite_csv_file(SCALE_MEASUREMENTS_CSV, kept, fieldnames)

    latest = latest_weight_history_event()
    if latest:
        rewrite_json_file(SCALE_LATEST_JSON, latest)
    elif SCALE_LATEST_JSON.exists():
        SCALE_LATEST_JSON.unlink()

    return {"ok": True, "deleted": deleted, "events": read_weight_events()["events"]}


def read_weight_history(limit_days=90, fill_missing=False, end_day=None):
    source = SCALE_DATA_DIR / "scale_measurements.jsonl"
    rows = []

    if source.exists():
        with source.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    parsed = parse_weight_history_row(json.loads(line))
                except json.JSONDecodeError:
                    parsed = None
                if parsed:
                    rows.append(parsed)

    if not rows and SCALE_MEASUREMENTS_CSV.exists():
        with SCALE_MEASUREMENTS_CSV.open("r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                parsed = parse_weight_history_row(row)
                if parsed:
                    rows.append(parsed)

    groups = {}
    for row in rows:
        group = groups.setdefault(row["day"], {"day": row["day"], "weights": [], "timestamps": []})
        group["weights"].append(row["weight_kg"])
        group["timestamps"].append(row["timestamp"])

    daily = []
    for day, group in groups.items():
        weights = group["weights"]
        timestamps = sorted(group["timestamps"])
        if not weights:
            continue
        daily.append(
            {
                "day": day,
                "avg_weight_kg": round(sum(weights) / len(weights), 2),
                "count": len(weights),
                "first_timestamp": timestamps[0],
                "last_timestamp": timestamps[-1],
            }
        )

    daily.sort(key=lambda item: item["day"])
    if fill_missing:
        days = max(1, int(limit_days or 30))
        try:
            end = date.fromisoformat(str(end_day)) if end_day else date.today()
        except ValueError:
            end = date.today()
        today = date.today()
        if end > today:
            end = today
        start = end - timedelta(days=days - 1)
        by_day = {item["day"]: item for item in daily}
        real_points = []
        for item in daily:
            try:
                item_day = date.fromisoformat(item["day"])
            except ValueError:
                continue
            real_points.append((item_day, item["avg_weight_kg"]))

        filled = []
        for offset in range(days):
            current_day = start + timedelta(days=offset)
            key = current_day.isoformat()
            real = by_day.get(key)
            if real:
                filled.append({**real, "filled": False})
                continue

            previous_point = None
            next_point = None
            for point_day, point_value in real_points:
                if point_day < current_day:
                    previous_point = (point_day, point_value)
                elif point_day > current_day:
                    next_point = (point_day, point_value)
                    break

            if previous_point and next_point:
                prev_day, prev_value = previous_point
                next_day, next_value = next_point
                total_days = max(1, (next_day - prev_day).days)
                elapsed_days = (current_day - prev_day).days
                ratio = elapsed_days / total_days
                value = round(prev_value + (next_value - prev_value) * ratio, 2)
            elif previous_point:
                value = previous_point[1]
            elif next_point:
                value = next_point[1]
            else:
                value = None

            if value is not None:
                filled.append(
                    {
                        "day": key,
                        "avg_weight_kg": value,
                        "count": 0,
                        "first_timestamp": None,
                        "last_timestamp": None,
                        "filled": True,
                    }
                )
        daily = filled
    elif limit_days and len(daily) > limit_days:
        daily = daily[-int(limit_days):]

    return {"ok": True, "daily": daily, "count": len(daily)}


def read_weight_dashboard_summary(
    weight_days=30,
    weight_end=None,
    weight_period=False,
    steps_days=30,
    steps_end=None,
    steps_all=False,
):
    weight_events = read_weight_events()
    steps_events = read_steps_events()
    return {
        "ok": True,
        "signal": read_scale_signal(),
        "weight_history": None
        if weight_period
        else read_weight_history(limit_days=weight_days, fill_missing=True, end_day=weight_end),
        "weight_events": weight_events,
        "weight_stats": read_weight_stats(),
        "steps_history": None
        if steps_all
        else read_steps_history(limit_days=steps_days, end_day=steps_end),
        "steps_events": steps_events,
        "health": read_health_latest(),
    }


def normalize_poster_key(value: str) -> str:
    if not value:
        return ""
    s = str(value).lower()
    s = s.replace("&", "and")
    s = s.replace("’", "").replace("'", "").replace("`", "")
    s = re.sub(r"[^a-z0-9]+", "", s)
    return s

def bm_slugify(value: str) -> str:
    s = str(value or "").strip().lower()
    if not s:
        return ""
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.replace("&", "and")
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    return s


def bm_cover_slug(artist: str, album: str) -> str:
    a = bm_slugify(artist)
    b = bm_slugify(album)
    base = "--".join([part for part in (a, b) if part])
    return base or "unknown"


def save_bm365_cover(payload):
    data_url = payload.get("dataUrl") or payload.get("data_url")
    artist = payload.get("artist") or ""
    album = payload.get("album") or ""

    if not data_url:
        raise ValueError("Missing dataUrl")

    match = re.match(r"^data:(image/[a-zA-Z0-9.+-]+);base64,(.+)$", data_url, re.S)
    if not match:
        raise ValueError("Invalid data URL")

    mime = match.group(1).lower()
    b64 = match.group(2).strip()
    ext = COVER_MIME_EXT.get(mime)
    if not ext:
        raise ValueError("Unsupported image type")

    raw = base64.b64decode(b64)
    if len(raw) > COVER_MAX_BYTES:
        raise ValueError("Image too large")

    slug = bm_cover_slug(artist, album)
    COVERS_DIR.mkdir(parents=True, exist_ok=True)

    for existing_ext in COVER_FILE_EXTS:
        candidate = COVERS_DIR / f"{slug}{existing_ext}"
        if candidate.exists():
            candidate.unlink()

    path = COVERS_DIR / f"{slug}{ext}"
    path.write_bytes(raw)
    return {"ok": True, "url": f"./covers/{slug}{ext}", "slug": slug}


def save_music_artwork(payload):
    """Store a user-selected Music genre/project image as a normalized 16:9 WebP."""
    kind = str(payload.get("kind") or "").strip().lower()
    key = str(payload.get("key") or "").strip().lower()
    data_url = payload.get("dataUrl") or payload.get("data_url")
    directories = {
        "genre": ROOT / "assets" / "music" / "genres",
        "project": ROOT / "assets" / "music" / "projects",
    }
    if kind not in directories:
        raise ValueError("Unsupported artwork kind")
    if not re.fullmatch(r"[a-z0-9_-]{1,160}", key):
        raise ValueError("Invalid artwork key")
    match = re.match(r"^data:(image/[a-zA-Z0-9.+-]+);base64,(.+)$", str(data_url or ""), re.S)
    if not match or match.group(1).lower() not in COVER_MIME_EXT:
        raise ValueError("Unsupported image type")
    raw = base64.b64decode(match.group(2).strip())
    if not raw or len(raw) > COVER_MAX_BYTES:
        raise ValueError("Image is empty or too large")
    try:
        from PIL import Image, ImageOps
        with Image.open(io.BytesIO(raw)) as source:
            image = ImageOps.fit(source.convert("RGB"), (640, 360), method=Image.Resampling.LANCZOS)
            output = io.BytesIO()
            image.save(output, format="WEBP", quality=90, method=6)
    except Exception as exc:
        raise ValueError("Could not process image") from exc
    directory = directories[kind]
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{key}.webp"
    path.write_bytes(output.getvalue())
    return {"ok": True, "kind": kind, "key": key, "url": f"./assets/music/{kind}s/{key}.webp", "width": 640, "height": 360}




def bm365_fetch_rows(force=False):
    del force
    return BM365_STORE.get_albums()


def bm365_release_year_rows(force=False):
    with BM365_RELEASE_YEARS_CACHE_LOCK:
        cached_rows = BM365_RELEASE_YEARS_CACHE.get("rows")
        fetched_at = float(BM365_RELEASE_YEARS_CACHE.get("fetched_at") or 0)
        if (
            not force
            and cached_rows is not None
            and time.time() - fetched_at < BM365_RELEASE_YEARS_CACHE_TTL
        ):
            return [dict(row) for row in cached_rows]

    spreadsheet_id = (
        os.environ.get("BM365_SHEET_ID", BM365_DEFAULT_SHEET_ID).strip()
        or BM365_DEFAULT_SHEET_ID
    )
    sheet_name = (
        os.environ.get("BM365_SHEET_NAME", BM365_DEFAULT_SHEET_NAME).strip()
        or BM365_DEFAULT_SHEET_NAME
    )
    escaped_sheet_name = sheet_name.replace("'", "''")
    range_name = f"'{escaped_sheet_name}'!A2:E"
    encoded_range = urllib.parse.quote(range_name, safe="")
    data = google_sheets_api_request(
        "GET",
        f"/spreadsheets/{urllib.parse.quote(spreadsheet_id, safe='')}/values/{encoded_range}",
        query={
            "majorDimension": "ROWS",
            "valueRenderOption": "FORMATTED_VALUE",
        },
    )
    values = data.get("values") if isinstance(data, dict) else []
    rows = []
    for offset, values_row in enumerate(values if isinstance(values, list) else [], start=2):
        if not isinstance(values_row, list):
            continue
        artist = str(values_row[2] if len(values_row) > 2 else "").strip()
        album = str(values_row[3] if len(values_row) > 3 else "").strip()
        year_match = re.search(r"\b(19\d{2}|20\d{2}|2100)\b", str(
            values_row[4] if len(values_row) > 4 else ""
        ))
        if not artist and not album:
            continue
        rows.append({
            "rowId": offset,
            "artist": artist,
            "album": album,
            "year": year_match.group(1) if year_match else "",
        })

    with BM365_RELEASE_YEARS_CACHE_LOCK:
        BM365_RELEASE_YEARS_CACHE["rows"] = [dict(row) for row in rows]
        BM365_RELEASE_YEARS_CACHE["fetched_at"] = time.time()
    return rows


def bm365_metadata_snapshot():
    snapshot = BM365_METADATA_STORE.snapshot()
    stored_metadata = snapshot.get("metadata") or []
    by_row_id = {int(item["rowId"]): dict(item) for item in stored_metadata}
    release_year_error = None
    release_year_count = 0
    try:
        for item in bm365_release_year_rows():
            row_id = int(item["rowId"])
            current = by_row_id.get(row_id, {
                "rowId": row_id,
                "artist": item.get("artist") or "",
                "album": item.get("album") or "",
                "description": "",
            })
            current["year"] = item.get("year") or ""
            by_row_id[row_id] = current
            if current["year"]:
                release_year_count += 1
    except Exception as exc:
        release_year_error = str(exc)
        log_line(f"BM365 release years load failed: {exc}", tag="api", level="warn")

    metadata = [by_row_id[row_id] for row_id in sorted(by_row_id)]
    result = {
        **snapshot,
        "metadata": metadata,
        "count": len(metadata),
        "releaseYearsCount": release_year_count,
    }
    if release_year_error:
        result["releaseYearsError"] = release_year_error
    return result


def album_identity_part(value):
    text = unicodedata.normalize("NFKD", str(value or "")).casefold()
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.translate(str.maketrans({
        "ł": "l", "đ": "d", "ð": "d", "þ": "th",
        "æ": "ae", "œ": "oe", "ø": "o",
    }))
    text = text.replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def album_identity_key(artist, album):
    return album_identity_part(artist), album_identity_part(album)


def album_rating_value(value):
    try:
        rating = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return rating if math.isfinite(rating) and 0.5 <= rating <= 5 else None


def bm365_rate_remote(row, rating):
    rating = album_rating_value(rating)
    if rating is None:
        raise ValueError("Invalid BM365 rating")
    target = {"rowId": row.get("rowId"), "date": row.get("date")}
    updated = BM365_STORE.rate_album(target, rating, propagate=False)
    BM365_STORE.invalidate_cross_cache()
    BM365_SHEETS_SYNCER.notify()
    return {"ok": True, "album": updated}


def sync_album_rating_across_lists(
    payload,
    *,
    source,
    bm_rows=None,
    ba_row=None,
    rym_row=None,
):
    artist = str(payload.get("artist") or "").strip()
    album = str(payload.get("album") or "").strip()
    rating = album_rating_value(payload.get("rating"))
    if not artist or not album or rating is None:
        raise ValueError("artist, album and a valid rating are required")

    key = album_identity_key(artist, album)
    if bm_rows is None:
        bm_rows = bm365_fetch_rows(force=True)
    bm_row = next((
        row for row in bm_rows
        if album_identity_key(row.get("artist"), row.get("album")) == key
    ), None)
    if ba_row is None:
        ba_row = next((
            row for row in BRUTAL_ASSAULT_2027_STORE.list()
            if album_identity_key(row.get("artist"), row.get("album")) == key
        ), None)
    if rym_row is None:
        rym_row = next((
            row for row in RYM_POLISH_BLACK_METAL_STORE.list()
            if album_identity_key(row.get("artist"), row.get("album")) == key
        ), None)

    matched_lists = [
        name
        for name, row in (
            ("bm365", bm_row),
            ("brutal-assault-2027", ba_row),
            ("rym-polish-black-metal-top-100", rym_row),
        )
        if row
    ]
    updated = {}
    if ba_row:
        if source != "brutal-assault-2027" and album_rating_value(ba_row.get("rating")) != rating:
            ba_row = BRUTAL_ASSAULT_2027_STORE.update(ba_row.get("rowId"), {"rating": rating})
        updated["brutal-assault-2027"] = ba_row
    if rym_row:
        if source != "rym-polish-black-metal-top-100" and album_rating_value(rym_row.get("rating")) != rating:
            rym_row = RYM_POLISH_BLACK_METAL_STORE.update(rym_row.get("rowId"), {"rating": rating})
        updated["rym-polish-black-metal-top-100"] = rym_row
    if bm_row:
        if source != "bm365" and album_rating_value(bm_row.get("rating")) != rating:
            bm365_rate_remote(bm_row, rating)
            bm_row = {**bm_row, "rating": rating, "listened": "TAK"}
        updated["bm365"] = bm_row

    return {
        "ok": True,
        "matched": any(item != source for item in matched_lists),
        "matchedLists": matched_lists,
        "rating": rating,
        "albums": updated,
    }


def brutal_assault_2027_cross_sync():
    ba_rows = BRUTAL_ASSAULT_2027_STORE.list()
    bm_rows = bm365_fetch_rows()
    bm_by_key = {
        album_identity_key(row.get("artist"), row.get("album")): row
        for row in bm_rows
    }
    rym_by_key = {
        album_identity_key(row.get("artist"), row.get("album")): row
        for row in RYM_POLISH_BLACK_METAL_STORE.list()
    }
    matches = []

    for ba_row in ba_rows:
        key = album_identity_key(ba_row.get("artist"), ba_row.get("album"))
        bm_row = bm_by_key.get(key)
        if not bm_row:
            continue

        ba_rating = album_rating_value(ba_row.get("rating"))
        bm_rating = album_rating_value(bm_row.get("rating"))
        rym_row = rym_by_key.get(key)
        rym_rating = album_rating_value(rym_row.get("rating")) if rym_row else None
        canonical_rating = bm_rating if bm_rating is not None else (
            ba_rating if ba_rating is not None else rym_rating
        )
        source = "bm365" if bm_rating is not None else (
            "brutal-assault-2027" if ba_rating is not None else "rym-polish-black-metal-top-100"
        )
        present_ratings = [bm_rating, ba_rating]
        if rym_row:
            present_ratings.append(rym_rating)
        if canonical_rating is not None and any(
            value != canonical_rating for value in present_ratings
        ):
            sync_result = sync_album_rating_across_lists(
                {"artist": ba_row.get("artist"), "album": ba_row.get("album"), "rating": canonical_rating},
                source=source,
                bm_rows=bm_rows,
                ba_row=ba_row,
                rym_row=rym_row,
            )
            ba_row = sync_result["albums"].get("brutal-assault-2027") or ba_row
            bm_rating = canonical_rating
            ba_rating = canonical_rating

        matches.append({
            "artist": ba_row.get("artist"),
            "album": ba_row.get("album"),
            "baRowId": ba_row.get("rowId"),
            "baDate": ba_row.get("date"),
            "bmRowId": bm_row.get("rowId"),
            "bmDate": bm_row.get("date"),
            "rating": bm_rating if bm_rating is not None else ba_rating,
        })

    return matches


def brutal_assault_2027_snapshot_with_cross_list():
    cross_list_error = None
    try:
        matches = brutal_assault_2027_cross_sync()
    except Exception as exc:
        matches = []
        cross_list_error = str(exc)
        log_line(f"BA2027 cross-list sync failed: {exc}", tag="api", level="warn")

    snapshot = BRUTAL_ASSAULT_2027_STORE.snapshot()
    matches_by_ba_id = {str(item.get("baRowId")): item for item in matches}
    rym_by_key = {
        album_identity_key(row.get("artist"), row.get("album")): row
        for row in RYM_POLISH_BLACK_METAL_STORE.list()
    }
    for row in snapshot.get("rows") or []:
        cross_lists = []
        match = matches_by_ba_id.get(str(row.get("rowId")))
        if match:
            cross_lists.append({
                "key": "bm365",
                "label": "Black Metal 365",
                "rowId": match.get("bmRowId"),
                "date": match.get("bmDate"),
                "rating": match.get("rating"),
            })
        rym_row = rym_by_key.get(album_identity_key(row.get("artist"), row.get("album")))
        if rym_row:
            cross_lists.append({
                "key": "rym-polish-black-metal-top-100",
                "label": "Top 100 RYM Polish BM",
                "rowId": rym_row.get("rowId"),
                "rank": rym_row.get("sourceRank"),
                "rating": rym_row.get("rating"),
            })
        if cross_lists:
            row["crossLists"] = cross_lists
            row["crossList"] = cross_lists[0]
    snapshot["matches"] = matches
    if cross_list_error:
        snapshot["crossListError"] = cross_list_error
    return snapshot


def rym_polish_black_metal_snapshot_with_cross_lists():
    snapshot = RYM_POLISH_BLACK_METAL_STORE.snapshot()
    ba_by_key = {
        album_identity_key(row.get("artist"), row.get("album")): row
        for row in BRUTAL_ASSAULT_2027_STORE.list()
    }
    bm_rows = []
    bm_by_key = {}
    cross_list_error = None
    try:
        bm_rows = bm365_fetch_rows()
        bm_by_key = {
            album_identity_key(row.get("artist"), row.get("album")): row
            for row in bm_rows
        }
    except Exception as exc:
        cross_list_error = str(exc)
        log_line(f"RYM Polish BM cross-list lookup failed: {exc}", tag="api", level="warn")

    for row in snapshot.get("rows") or []:
        key = album_identity_key(row.get("artist"), row.get("album"))
        cross_lists = []
        bm_row = bm_by_key.get(key)
        ba_row = ba_by_key.get(key)

        bm_rating = album_rating_value(bm_row.get("rating")) if bm_row else None
        ba_rating = album_rating_value(ba_row.get("rating")) if ba_row else None
        rym_rating = album_rating_value(row.get("rating"))
        canonical_rating = bm_rating if bm_rating is not None else (
            ba_rating if ba_rating is not None else rym_rating
        )
        source = "bm365" if bm_rating is not None else (
            "brutal-assault-2027" if ba_rating is not None else "rym-polish-black-metal-top-100"
        )
        present_ratings = [rym_rating]
        if bm_row:
            present_ratings.append(bm_rating)
        if ba_row:
            present_ratings.append(ba_rating)
        if canonical_rating is not None and any(
            value != canonical_rating for value in present_ratings
        ):
            try:
                sync_result = sync_album_rating_across_lists(
                    {"artist": row.get("artist"), "album": row.get("album"), "rating": canonical_rating},
                    source=source,
                    bm_rows=bm_rows,
                    ba_row=ba_row,
                    rym_row=row,
                )
                row.update(sync_result["albums"].get("rym-polish-black-metal-top-100") or {})
                ba_row = sync_result["albums"].get("brutal-assault-2027") or ba_row
                bm_row = sync_result["albums"].get("bm365") or bm_row
            except Exception as exc:
                cross_list_error = str(exc)
                log_line(f"RYM Polish BM rating repair failed: {exc}", tag="api", level="warn")

        if bm_row:
            cross_lists.append({
                "key": "bm365",
                "label": "Black Metal 365",
                "rowId": bm_row.get("rowId"),
                "date": bm_row.get("date"),
                "rating": bm_row.get("rating"),
            })
        if ba_row:
            cross_lists.append({
                "key": "brutal-assault-2027",
                "label": "Brutal Assault 2027",
                "rowId": ba_row.get("rowId"),
                "date": ba_row.get("date"),
                "rating": ba_row.get("rating"),
            })
        if cross_lists:
            row["crossLists"] = cross_lists
            row["crossList"] = cross_lists[0]

    if cross_list_error:
        snapshot["crossListError"] = cross_list_error
    return snapshot


def sync_ba_rating_to_bm(ba_album):
    return sync_album_rating_across_lists(
        ba_album,
        source="brutal-assault-2027",
        ba_row=ba_album,
    )


def sync_bm_rating_to_ba(payload):
    return sync_album_rating_across_lists(payload, source="bm365")


def bm365_local_cover_path(slug: str):
    if not slug:
        return None
    for ext in COVER_FILE_EXTS:
        candidate = COVERS_DIR / f"{slug}{ext}"
        if candidate.exists():
            return candidate
    return None


def bm365_itunes_cover_url(artist: str, album: str):
    term = f"{artist} {album}".strip()
    if not term:
        return None
    params = urllib.parse.urlencode({"term": term, "entity": "album", "limit": 1})
    url = f"{BM365_ITUNES_URL}?{params}"
    data = http_get_json(url, timeout=15)
    items = data.get("results") or []
    if not items:
        return None
    art = items[0].get("artworkUrl100") or items[0].get("artworkUrl60")
    if not art:
        return None
    return re.sub(r"/(\d+)x(\d+)bb\.(jpg|png)", r"/600x600bb.\3", art)


def bm365_mb_cover_url(artist: str, album: str):
    term = f"{artist} {album}".strip()
    if not term:
        return None
    global BM365_MB_LAST_CALL
    wait = BM365_MB_MIN_DELAY - (time.time() - BM365_MB_LAST_CALL)
    if wait > 0:
        time.sleep(wait)
    BM365_MB_LAST_CALL = time.time()
    query = f'artist:"{artist}" AND release:"{album}"'
    params = urllib.parse.urlencode({"query": query, "fmt": "json", "limit": 1})
    url = f"{BM365_MB_URL}?{params}"
    headers = {"User-Agent": WIKI_UA}
    data = http_get_json(url, headers=headers, timeout=20)
    releases = data.get("releases") or []
    if not releases:
        return None
    mbid = releases[0].get("id")
    if not mbid:
        return None
    caa_url = f"{BM365_CAA_URL}{mbid}"
    caa = http_get_json(caa_url, headers=headers, timeout=20)
    images = caa.get("images") or []
    if not images:
        return None
    img = next((img for img in images if img.get("front")), images[0])
    thumbs = img.get("thumbnails") or {}
    return thumbs.get("500") or thumbs.get("large") or thumbs.get("small") or img.get("image")


def bm365_find_cover_url(artist: str, album: str):
    try:
        url = bm365_itunes_cover_url(artist, album)
        if url:
            return url
    except Exception:
        pass
    try:
        return bm365_mb_cover_url(artist, album)
    except Exception:
        return None


def bm365_download_image(url: str, slug: str):
    if not url or not slug:
        return None
    headers = {"User-Agent": WIKI_UA}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read()
        ctype = (resp.headers.get("Content-Type") or "").split(";")[0].lower()
    if len(raw) > COVER_MAX_BYTES:
        raise ValueError("Image too large")
    ext = COVER_MIME_EXT.get(ctype)
    if not ext:
        path_ext = Path(urllib.parse.urlparse(url).path).suffix.lower()
        if path_ext == ".jpeg":
            path_ext = ".jpg"
        if path_ext in COVER_FILE_EXTS:
            ext = ".jpg" if path_ext == ".jpeg" else path_ext
        else:
            ext = ".jpg"
    COVERS_DIR.mkdir(parents=True, exist_ok=True)
    for existing_ext in COVER_FILE_EXTS:
        candidate = COVERS_DIR / f"{slug}{existing_ext}"
        if candidate.exists():
            candidate.unlink()
    path = COVERS_DIR / f"{slug}{ext}"
    path.write_bytes(raw)
    return f"./covers/{slug}{ext}"


def bm365_download_all_covers(limit=0, force=False):
    rows = bm365_fetch_rows()
    seen = set()
    ordered = []
    for row in rows:
        slug = bm_cover_slug(row.get("artist"), row.get("album"))
        if not slug or slug in seen:
            continue
        seen.add(slug)
        row["slug"] = slug
        ordered.append(row)

    total = len(ordered)
    saved = skipped = missing = errors = 0
    missing_items = []
    processed = 0
    max_items = int(limit) if limit else 0

    for row in ordered:
        if max_items and processed >= max_items:
            break
        processed += 1

        slug = row.get("slug")
        if not force and bm365_local_cover_path(slug):
            skipped += 1
            continue

        try:
            url = bm365_find_cover_url(row.get("artist"), row.get("album"))
            if not url:
                missing += 1
                if len(missing_items) < 50:
                    missing_items.append(f"{row.get('artist', '')} - {row.get('album', '')}")
                continue
            bm365_download_image(url, slug)
            saved += 1
        except Exception as exc:
            errors += 1
            log_line(
                f"bm365 cover error: {row.get('artist', '-')} - {row.get('album', '-')}: {exc}",
                tag="api",
                level="warn",
            )
        time.sleep(0.1)

    return {
        "ok": True,
        "total": total,
        "processed": processed,
        "saved": saved,
        "skipped": skipped,
        "missing": missing,
        "errors": errors,
        "missing_sample": missing_items,
    }


def brutal_assault_2027_download_all_covers(limit=0, force=False):
    rows = BRUTAL_ASSAULT_2027_STORE.list()
    seen = set()
    ordered = []
    for row in rows:
        slug = bm_cover_slug(row.get("artist"), row.get("album"))
        if not slug or slug in seen:
            continue
        seen.add(slug)
        ordered.append({**row, "slug": slug})

    total = len(ordered)
    saved = skipped = missing = errors = 0
    missing_items = []
    processed = 0
    max_items = int(limit) if limit else 0

    for row in ordered:
        if max_items and processed >= max_items:
            break
        processed += 1
        slug = row["slug"]
        if not force and bm365_local_cover_path(slug):
            skipped += 1
            continue
        try:
            url = bm365_find_cover_url(row.get("artist"), row.get("album"))
            if not url:
                missing += 1
                if len(missing_items) < 50:
                    missing_items.append(f"{row.get('artist', '')} - {row.get('album', '')}")
                continue
            bm365_download_image(url, slug)
            saved += 1
        except Exception as exc:
            errors += 1
            log_line(
                f"BA2027 cover error: {row.get('artist', '-')} - {row.get('album', '-')}: {exc}",
                tag="api",
                level="warn",
            )
        time.sleep(0.1)

    return {
        "ok": True,
        "total": total,
        "processed": processed,
        "saved": saved,
        "skipped": skipped,
        "missing": missing,
        "errors": errors,
        "missing_sample": missing_items,
    }


def brutal_assault_2027_download_cover(artist, album, force=False):
    artist = str(artist or "").strip()
    album = str(album or "").strip()
    if not artist or not album:
        raise ValueError("Artist and album are required")

    slug = bm_cover_slug(artist, album)
    existing = bm365_local_cover_path(slug)
    if existing and not force:
        return {"ok": True, "url": f"./covers/{existing.name}", "cached": True}

    source_url = bm365_find_cover_url(artist, album)
    if not source_url:
        return {"ok": True, "url": None, "missing": True}

    local_url = bm365_download_image(source_url, slug)
    return {"ok": True, "url": local_url, "cached": False}


def reading_cover_slug(title: str, author: str, key: str = "") -> str:
    title_part = bm_slugify(title)
    author_part = bm_slugify(author)
    fallback = bm_slugify(key)
    base = "--".join([part for part in (title_part, author_part) if part]) or fallback or "unknown"
    return f"reading--{base}"


def save_cover_bytes(slug: str, raw: bytes, content_type: str = "", ext_hint: str = ""):
    if not slug:
        raise ValueError("Missing cover slug")
    if not raw:
        raise ValueError("Uploaded file is empty")
    if len(raw) > COVER_MAX_BYTES:
        raise ValueError("Image too large")

    ctype = (content_type or "").split(";")[0].lower()
    ext = COVER_MIME_EXT.get(ctype)
    if not ext:
        path_ext = Path(str(ext_hint or "")).suffix.lower()
        if path_ext == ".jpeg":
            path_ext = ".jpg"
        ext = path_ext if path_ext in COVER_FILE_EXTS else ".jpg"

    COVERS_DIR.mkdir(parents=True, exist_ok=True)
    for existing_ext in COVER_FILE_EXTS:
        candidate = COVERS_DIR / f"{slug}{existing_ext}"
        if candidate.exists():
            candidate.unlink()

    path = COVERS_DIR / f"{slug}{ext}"
    path.write_bytes(raw)
    return f"./covers/{slug}{ext}"


def download_cover_bytes(url: str):
    parsed = urllib.parse.urlparse(str(url or ""))
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Unsupported cover URL")
    req = urllib.request.Request(url, headers={"User-Agent": WIKI_UA})
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read()
        ctype = (resp.headers.get("Content-Type") or "").split(";")[0].lower()
    if ctype and not ctype.startswith("image/"):
        raise ValueError("Cover URL did not return an image")
    return raw, ctype, parsed.path


def save_reading_cover(payload):
    title = payload.get("title") or payload.get("bookTitle") or ""
    author = payload.get("author") or payload.get("bookAuthor") or ""
    key = payload.get("key") or payload.get("bookKey") or ""
    slug = reading_cover_slug(title, author, key)
    data_url = payload.get("dataUrl") or payload.get("data_url")
    source_url = payload.get("sourceUrl") or payload.get("source_url")

    if data_url:
        match = re.match(r"^data:(image/[a-zA-Z0-9.+-]+);base64,(.+)$", data_url, re.S)
        if not match:
            raise ValueError("Invalid data URL")
        mime = match.group(1).lower()
        if mime not in COVER_MIME_EXT:
            raise ValueError("Unsupported image type")
        raw = base64.b64decode(match.group(2).strip())
        url = save_cover_bytes(slug, raw, mime)
        return {"ok": True, "url": url, "slug": slug}

    if source_url:
        existing = bm365_local_cover_path(slug)
        if existing:
            return {
                "ok": True,
                "url": f"./covers/{existing.name}",
                "slug": slug,
                "cached": True,
            }
        raw, ctype, path_hint = download_cover_bytes(source_url)
        url = save_cover_bytes(slug, raw, ctype, path_hint)
        return {"ok": True, "url": url, "slug": slug}

    raise ValueError("Missing dataUrl or sourceUrl")


def event_cover_slug(event):
    event_id = str((event or {}).get("id") or "").strip()
    title = str((event or {}).get("title") or "").strip()
    date_value = str((event or {}).get("date") or "").strip()
    base = bm_slugify(event_id) or bm_slugify(f"{date_value}-{title}") or "event"
    return f"event--{base}"


def save_event_cover_bytes(slug, raw, content_type):
    if not slug:
        raise ValueError("Missing event cover slug")
    if not raw:
        raise ValueError("Uploaded file is empty")
    if len(raw) > COVER_MAX_BYTES:
        raise ValueError("Image too large")

    mime = (content_type or "").split(";")[0].lower()
    ext = COVER_MIME_EXT.get(mime)
    if not ext:
        raise ValueError("Unsupported image type")

    EVENT_PUBLIC_COVERS_DIR.mkdir(parents=True, exist_ok=True)
    EVENT_COVERS_DIR.mkdir(parents=True, exist_ok=True)
    for existing_ext in COVER_FILE_EXTS:
        for directory in (EVENT_PUBLIC_COVERS_DIR, EVENT_COVERS_DIR):
            candidate = directory / f"{slug}{existing_ext}"
            if candidate.exists():
                candidate.unlink()

    filename = f"{slug}{ext}"
    (EVENT_PUBLIC_COVERS_DIR / filename).write_bytes(raw)
    try:
        (EVENT_COVERS_DIR / filename).write_bytes(raw)
    except OSError:
        pass
    return f"/assets/events/{filename}?v={int(time.time())}"


def delete_event_cover_files(event):
    slug = event_cover_slug(event)
    for existing_ext in COVER_FILE_EXTS:
        for directory in (EVENT_PUBLIC_COVERS_DIR, EVENT_COVERS_DIR):
            candidate = directory / f"{slug}{existing_ext}"
            if candidate.exists():
                candidate.unlink()


def save_event_countdown_cover(payload):
    event = payload.get("event") if isinstance(payload.get("event"), dict) else payload
    if not isinstance(event, dict):
        raise ValueError("Event payload must be an object")
    event_id = str(event.get("id") or "").strip()
    data_url = payload.get("dataUrl") or payload.get("data_url")
    remove = payload.get("remove") is True
    if not event_id:
        raise ValueError("Missing event id")
    if not data_url and not remove:
        raise ValueError("Missing dataUrl")

    if remove:
        delete_event_cover_files(event)
        url = ""
    else:
        match = re.match(r"^data:(image/[a-zA-Z0-9.+-]+);base64,(.+)$", data_url, re.S)
        if not match:
            raise ValueError("Invalid data URL")
        mime = match.group(1).lower()
        if mime not in COVER_MIME_EXT:
            raise ValueError("Unsupported image type")

        raw = base64.b64decode(match.group(2).strip())
        url = save_event_cover_bytes(event_cover_slug(event), raw, mime)

    if str(event.get("category") or "").strip() == "phases_of_the_moon":
        settings = read_json_file(EVENT_COUNTDOWN_SETTINGS_JSON, {})
        settings = dict(settings) if isinstance(settings, dict) else {}
        covers = settings.get("countdownCategoryCovers")
        covers = dict(covers) if isinstance(covers, dict) else {}
        if url:
            covers["phases_of_the_moon"] = url
        else:
            covers.pop("phases_of_the_moon", None)
        settings["countdownCategoryCovers"] = covers
        rewrite_json_file(EVENT_COUNTDOWN_SETTINGS_JSON, settings)

    external = event.get("external") if isinstance(event.get("external"), dict) else {}
    if external.get("provider") == "google_calendar" and external.get("calendarId") and external.get("eventId"):
        overrides = read_google_calendar_overrides()
        key = google_calendar_event_key(external.get("calendarId"), external.get("eventId"))
        override = overrides.setdefault("events", {}).get(key)
        if not isinstance(override, dict):
            override = {}
        override["coverImage"] = url or None
        override["updatedAt"] = datetime.now().isoformat(timespec="seconds")
        overrides["events"][key] = override
        write_google_calendar_overrides(overrides)

        cache = read_google_calendar_cache()
        cached = cache.setdefault("events", {}).get(key)
        if isinstance(cached, dict):
            cached["coverImage"] = url or None
            cache["events"][key] = apply_google_calendar_override(cached, overrides)
            write_google_calendar_cache(cache)
        return {"ok": True, "url": url, "event": {**event, "coverImage": url}}

    events = read_json_file(EVENTS_JSON, [])
    if not isinstance(events, list):
        raise ValueError("Local events store is invalid")
    updated = False
    for item in events:
        if isinstance(item, dict) and str(item.get("id") or "") == event_id:
            if url:
                item["coverImage"] = url
            else:
                item.pop("coverImage", None)
            updated = True
            break
    if not updated:
        raise ValueError("Event not found in local events")
    rewrite_json_file(EVENTS_JSON, events)
    return {"ok": True, "url": url, "event": {**event, "coverImage": url}}


def read_event_countdown_categories():
    settings = read_json_file(EVENT_COUNTDOWN_SETTINGS_JSON, {})
    settings = settings if isinstance(settings, dict) else {}
    label_overrides = settings.get("countdownCategoryLabels", {})
    label_overrides = label_overrides if isinstance(label_overrides, dict) else {}
    categories = [
        {
            "id": category_id,
            "label": " ".join(str(label_overrides.get(category_id) or label).split())[:80],
            "custom": False,
        }
        for category_id, label in EVENT_COUNTDOWN_CATEGORY_LABELS.items()
    ]
    custom_categories = settings.get("countdownCategories", [])
    used_ids = {category["id"] for category in categories}
    for row in custom_categories if isinstance(custom_categories, list) else []:
        if not isinstance(row, dict):
            continue
        category_id = str(row.get("id") or "").strip().lower()
        label = " ".join(str(row.get("label") or "").split())
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", category_id) or not label or category_id in used_ids:
            continue
        used_ids.add(category_id)
        categories.append({"id": category_id, "label": label[:80], "custom": True})
    return categories


def read_event_countdown_category_covers():
    settings = read_json_file(EVENT_COUNTDOWN_SETTINGS_JSON, {})
    covers = settings.get("countdownCategoryCovers", {}) if isinstance(settings, dict) else {}
    if not isinstance(covers, dict):
        return {}
    return {
        str(category_id): str(url)
        for category_id, url in covers.items()
        if re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", str(category_id)) and str(url).strip()
    }


def save_event_countdown_category(payload):
    label = " ".join(str((payload or {}).get("label") or "").split())
    requested_id = str((payload or {}).get("id") or "").strip().lower()
    if not label or len(label) > 80:
        raise ValueError("Category name must contain between 1 and 80 characters")

    existing = read_event_countdown_categories()
    normalized_label = label.casefold()
    same_label = next(
        (row for row in existing if row["label"].casefold() == normalized_label and row["id"] != requested_id),
        None,
    )
    if requested_id:
        target = next((row for row in existing if row["id"] == requested_id), None)
        if not target:
            raise ValueError("Category not found")
        if same_label:
            raise ValueError("A category with this name already exists")

        settings = read_json_file(EVENT_COUNTDOWN_SETTINGS_JSON, {})
        settings = dict(settings) if isinstance(settings, dict) else {}
        if requested_id in EVENT_COUNTDOWN_CATEGORY_LABELS:
            label_overrides = settings.get("countdownCategoryLabels")
            label_overrides = dict(label_overrides) if isinstance(label_overrides, dict) else {}
            label_overrides[requested_id] = label
            settings["countdownCategoryLabels"] = label_overrides
        else:
            custom_categories = settings.get("countdownCategories")
            custom_categories = list(custom_categories) if isinstance(custom_categories, list) else []
            updated = False
            for row in custom_categories:
                if isinstance(row, dict) and str(row.get("id") or "").strip().lower() == requested_id:
                    row["label"] = label
                    updated = True
                    break
            if not updated:
                raise ValueError("Category not found")
            settings["countdownCategories"] = custom_categories
        rewrite_json_file(EVENT_COUNTDOWN_SETTINGS_JSON, settings)
        categories = read_event_countdown_categories()
        category = next(row for row in categories if row["id"] == requested_id)
        return {"ok": True, "category": category, "categories": categories}

    if same_label:
        return {"ok": True, "category": same_label, "categories": existing}

    base_id = bm_slugify(label).replace("-", "_")[:56] or "category"
    used_ids = {row["id"] for row in existing}
    category_id = base_id
    suffix = 2
    while category_id in used_ids:
        category_id = f"{base_id[:56 - len(str(suffix))]}_{suffix}"
        suffix += 1

    settings = read_json_file(EVENT_COUNTDOWN_SETTINGS_JSON, {})
    settings = dict(settings) if isinstance(settings, dict) else {}
    custom_categories = settings.get("countdownCategories")
    custom_categories = list(custom_categories) if isinstance(custom_categories, list) else []
    category = {"id": category_id, "label": label, "custom": True}
    custom_categories.append(category)
    settings["countdownCategories"] = custom_categories
    rewrite_json_file(EVENT_COUNTDOWN_SETTINGS_JSON, settings)
    return {"ok": True, "category": category, "categories": read_event_countdown_categories()}


def upsert_local_dashboard_event(payload):
    event = payload.get("event") if isinstance(payload.get("event"), dict) else payload
    if not isinstance(event, dict):
        raise ValueError("Event payload must be an object")

    title = str(event.get("title") or "").strip()
    iso_date = str(event.get("date") or "").strip()[:10]
    category = str(event.get("category") or "").strip()
    if not title:
        raise ValueError("Event title is required")
    try:
        datetime.strptime(iso_date, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("Event date must use YYYY-MM-DD") from exc
    if category not in {row["id"] for row in read_event_countdown_categories()}:
        raise ValueError("A valid event category is required")

    events = read_json_file(EVENTS_JSON, [])
    if not isinstance(events, list):
        raise ValueError("Local events store is invalid")

    event_id = str(event.get("id") or "").strip()
    existing_index = next((
        index for index, item in enumerate(events)
        if isinstance(item, dict) and event_id and str(item.get("id") or "") == event_id
    ), None)
    if existing_index is None:
        base_id = f"event-{iso_date}-{bm_slugify(title) or 'event'}"
        used_ids = {str(item.get("id") or "") for item in events if isinstance(item, dict)}
        event_id = base_id
        suffix = 2
        while event_id in used_ids:
            event_id = f"{base_id}-{suffix}"
            suffix += 1

    category_types = {
        "concert": "concert",
        "match": "match",
        "stadium_match": "match",
    }
    existing = events[existing_index] if existing_index is not None else {}
    stored = {
        **existing,
        "id": event_id,
        "date": iso_date,
        "title": title,
        "type": str(event.get("type") or category_types.get(category) or "custom"),
        "isDayOff": bool(event.get("isDayOff")),
        "isShortDay": bool(event.get("isShortDay")),
        "source": "local",
        "countdown": True,
        "category": category,
    }
    for field in ("startTime", "endTime", "notes", "actionNeeded", "actionStatus", "coverImage"):
        value = event.get(field)
        if value not in (None, ""):
            stored[field] = value
        else:
            stored.pop(field, None)

    if existing_index is None:
        events.append(stored)
    else:
        events[existing_index] = stored
    rewrite_json_file(EVENTS_JSON, events)
    return {"ok": True, "event": stored}


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

FILM_LIBRARY_COLUMNS = [
    ("canonical_key", "TEXT"),
    ("title", "TEXT"),
    ("release_year", "INTEGER"),
    ("type", "TEXT"),
    ("runtime", "TEXT"),
    ("director", "TEXT"),
    ("country", "TEXT"),
    ("poster_url", "TEXT"),
    ("poster_source", "TEXT"),
    ("wikipedia_url", "TEXT"),
    ("imdb_url", "TEXT"),
    ("notes", "TEXT"),
    ("rating_1_10", "REAL"),
    ("watched", "INTEGER"),
    ("watched_date", "TEXT"),
    ("created_at", "TEXT"),
    ("updated_at", "TEXT"),
]

FILM_LIST_COLUMNS = [
    ("slug", "TEXT"),
    ("name", "TEXT"),
    ("description", "TEXT"),
    ("category", "TEXT"),
    ("source_kind", "TEXT"),
    ("source_year", "INTEGER"),
    ("pinned", "INTEGER"),
    ("is_active", "INTEGER"),
    ("created_at", "TEXT"),
    ("updated_at", "TEXT"),
]

FILM_LIST_ITEM_COLUMNS = [
    ("list_id", "INTEGER"),
    ("film_id", "INTEGER"),
    ("ordinal", "INTEGER"),
    ("added_at", "TEXT"),
    ("notes", "TEXT"),
    ("where_to_watch", "TEXT"),
    ("nominated_categories", "TEXT"),
    ("won_categories", "TEXT"),
    ("nominations_number", "INTEGER"),
]

FILM_LIBRARY_UPDATE_FIELDS = {
    "watched",
    "watched_date",
    "rating_1_10",
    "notes",
    "poster_url",
    "poster_source",
}


def today_iso() -> str:
    return date.today().isoformat()


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def parse_year(value):
    try:
        year = int(value)
    except (TypeError, ValueError):
        return None
    return year if 1900 <= year <= 2100 else None


def clean_wikipedia_url(url):
    value = clean_text(url)
    if not value:
        return None
    if "wikipedia.org/wiki/Special:Search" in value:
        return None
    return value


def parse_release_year(value):
    year = parse_year(value)
    if year:
        return year
    if not value:
        return None
    match = re.search(r"(19|20)\d{2}", str(value))
    return parse_year(match.group(0)) if match else None


def film_release_year_from_title(title):
    if not title:
        return None
    match = re.search(r"\((19|20)\d{2}(?:\s+film)?\)", str(title), flags=re.IGNORECASE)
    return parse_year(match.group(0)[1:5]) if match else None


def build_film_key(title, imdb_url=None, wikipedia_url=None, release_year=None):
    imdb_id = imdb_id_from_url(imdb_url)
    if imdb_id:
        return f"imdb:{imdb_id}"
    wiki = clean_wikipedia_url(wikipedia_url)
    if wiki:
        return f"wiki:{normalize_title_key(wiki)}"
    title_key = normalize_title_key(title)
    if not title_key:
        return None
    year = parse_year(release_year)
    return f"title:{title_key}:{year or 0}"


def ensure_sqlite_columns(conn, table_name, columns):
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table_name});")
    existing = {row[1] for row in cur.fetchall()}
    for name, ctype in columns:
        if name not in existing:
            cur.execute(f"ALTER TABLE {table_name} ADD COLUMN {name} {ctype};")
    conn.commit()


def ensure_films_tables(conn):
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS film_library (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            canonical_key TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            release_year INTEGER,
            type TEXT,
            runtime TEXT,
            director TEXT,
            country TEXT,
            poster_url TEXT,
            poster_source TEXT,
            wikipedia_url TEXT,
            imdb_url TEXT,
            notes TEXT,
            rating_1_10 REAL,
            watched INTEGER DEFAULT 0,
            watched_date TEXT,
            created_at TEXT,
            updated_at TEXT
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS film_lists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            description TEXT,
            category TEXT,
            source_kind TEXT,
            source_year INTEGER,
            pinned INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            created_at TEXT,
            updated_at TEXT
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS film_list_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            list_id INTEGER NOT NULL,
            film_id INTEGER NOT NULL,
            ordinal INTEGER,
            added_at TEXT,
            notes TEXT,
            where_to_watch TEXT,
            nominated_categories TEXT,
            won_categories TEXT,
            nominations_number INTEGER,
            UNIQUE(list_id, film_id)
        );
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_film_lists_slug ON film_lists(slug);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_film_items_list ON film_list_items(list_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_film_items_film ON film_list_items(film_id);")
    conn.commit()
    ensure_sqlite_columns(conn, "film_library", FILM_LIBRARY_COLUMNS)
    ensure_sqlite_columns(conn, "film_lists", FILM_LIST_COLUMNS)
    ensure_sqlite_columns(conn, "film_list_items", FILM_LIST_ITEM_COLUMNS)


def ensure_film_list(
    conn,
    slug,
    name,
    description="",
    category="custom",
    source_kind="manual",
    source_year=None,
    pinned=0,
    is_active=1,
):
    cur = conn.cursor()
    now = now_iso()
    row = cur.execute("SELECT id FROM film_lists WHERE slug = ?;", (slug,)).fetchone()
    if row:
        list_id = row[0]
        cur.execute(
            """
            UPDATE film_lists
            SET name = ?, description = ?, category = ?, source_kind = ?, source_year = ?,
                pinned = ?, is_active = ?, updated_at = ?
            WHERE id = ?;
            """,
            (name, description, category, source_kind, source_year, pinned, is_active, now, list_id),
        )
        conn.commit()
        return list_id

    cur.execute(
        """
        INSERT INTO film_lists (
            slug, name, description, category, source_kind, source_year,
            pinned, is_active, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (slug, name, description, category, source_kind, source_year, pinned, is_active, now, now),
    )
    conn.commit()
    return cur.lastrowid


def unique_film_list_slug(conn, base_slug):
    base = bm_slugify(base_slug) or "lista-filmowa"
    cur = conn.cursor()
    taken = {row[0] for row in cur.execute("SELECT slug FROM film_lists;").fetchall()}
    if base not in taken:
        return base
    idx = 2
    while f"{base}-{idx}" in taken:
        idx += 1
    return f"{base}-{idx}"


def fill_film_metadata(existing, incoming):
    merged = dict(existing or {})
    now = now_iso()
    for key in (
        "title",
        "release_year",
        "type",
        "runtime",
        "director",
        "country",
        "poster_url",
        "poster_source",
        "wikipedia_url",
        "imdb_url",
    ):
        if not merged.get(key) and incoming.get(key):
            merged[key] = incoming.get(key)

    if incoming.get("watched"):
        merged["watched"] = 1
    else:
        merged["watched"] = normalize_bool(merged.get("watched"))

    if not merged.get("watched_date") and incoming.get("watched_date"):
        merged["watched_date"] = incoming.get("watched_date")
    if merged.get("rating_1_10") is None and incoming.get("rating_1_10") is not None:
        merged["rating_1_10"] = incoming.get("rating_1_10")
    if not merged.get("notes") and incoming.get("notes"):
        merged["notes"] = incoming.get("notes")
    merged["updated_at"] = now
    if not merged.get("created_at"):
        merged["created_at"] = now
    return merged


def upsert_film_library_row(conn, payload, fetch_missing_poster=True):
    data = {
        "canonical_key": payload.get("canonical_key"),
        "title": clean_text(payload.get("title")),
        "release_year": parse_release_year(payload.get("release_year")),
        "type": clean_text(payload.get("type")),
        "runtime": clean_text(payload.get("runtime")),
        "director": clean_text(payload.get("director")),
        "country": normalize_country_list(payload.get("country")),
        "poster_url": clean_text(payload.get("poster_url")),
        "poster_source": clean_text(payload.get("poster_source")),
        "wikipedia_url": clean_wikipedia_url(payload.get("wikipedia_url")),
        "imdb_url": clean_text(payload.get("imdb_url")),
        "notes": clean_text(payload.get("notes")),
        "rating_1_10": normalize_float(payload.get("rating_1_10")),
        "watched": normalize_bool(payload.get("watched")),
        "watched_date": normalize_date_input(payload.get("watched_date")),
    }
    if not data["canonical_key"]:
        data["canonical_key"] = build_film_key(
            data["title"],
            imdb_url=data["imdb_url"],
            wikipedia_url=data["wikipedia_url"],
            release_year=data["release_year"],
        )
    if not data["title"] or not data["canonical_key"]:
        raise ValueError("Film title is required")

    cur = conn.cursor()
    row = cur.execute(
        "SELECT * FROM film_library WHERE canonical_key = ?;",
        (data["canonical_key"],),
    ).fetchone()

    # Startup syncs are local-only. Reuse an existing library poster before
    # considering remote enrichment so restarts do not hammer Wikipedia.
    if not data["poster_url"] and row and row["poster_url"]:
        data["poster_url"] = row["poster_url"]
        data["poster_source"] = data["poster_source"] or row["poster_source"]
    elif not data["poster_url"] and fetch_missing_poster:
        data["poster_url"] = wiki_poster(data["title"])
        if data["poster_url"] and not data["poster_source"]:
            data["poster_source"] = "wikipedia"

    if row:
        merged = fill_film_metadata(dict(row), data)
        cur.execute(
            """
            UPDATE film_library
            SET title = ?, release_year = ?, type = ?, runtime = ?, director = ?, country = ?,
                poster_url = ?, poster_source = ?, wikipedia_url = ?, imdb_url = ?, notes = ?,
                rating_1_10 = ?, watched = ?, watched_date = ?, updated_at = ?
            WHERE id = ?;
            """,
            (
                merged.get("title"),
                merged.get("release_year"),
                merged.get("type"),
                merged.get("runtime"),
                merged.get("director"),
                merged.get("country"),
                merged.get("poster_url"),
                merged.get("poster_source"),
                merged.get("wikipedia_url"),
                merged.get("imdb_url"),
                merged.get("notes"),
                merged.get("rating_1_10"),
                merged.get("watched"),
                merged.get("watched_date"),
                merged.get("updated_at"),
                row["id"],
            ),
        )
        conn.commit()
        return row["id"]

    now = now_iso()
    cur.execute(
        """
        INSERT INTO film_library (
            canonical_key, title, release_year, type, runtime, director, country,
            poster_url, poster_source, wikipedia_url, imdb_url, notes,
            rating_1_10, watched, watched_date, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (
            data["canonical_key"],
            data["title"],
            data["release_year"],
            data["type"],
            data["runtime"],
            data["director"],
            data["country"],
            data["poster_url"],
            data["poster_source"],
            data["wikipedia_url"],
            data["imdb_url"],
            data["notes"],
            data["rating_1_10"],
            data["watched"],
            data["watched_date"],
            now,
            now,
        ),
    )
    conn.commit()
    return cur.lastrowid


def normalize_list_item_payload(payload):
    return {
        "notes": clean_text(payload.get("notes")),
        "where_to_watch": clean_text(payload.get("where_to_watch")),
        "nominated_categories": clean_text(payload.get("nominated_categories")),
        "won_categories": clean_text(payload.get("won_categories")),
        "nominations_number": normalize_int(payload.get("nominations_number")),
        "ordinal": normalize_int(payload.get("ordinal")),
    }


def upsert_film_list_item(conn, list_id, film_id, payload):
    cur = conn.cursor()
    incoming = normalize_list_item_payload(payload)
    row = cur.execute(
        "SELECT * FROM film_list_items WHERE list_id = ? AND film_id = ?;",
        (list_id, film_id),
    ).fetchone()
    if row:
        existing = dict(row)
        merged = {
            "notes": existing.get("notes") or incoming.get("notes"),
            "where_to_watch": existing.get("where_to_watch") or incoming.get("where_to_watch"),
            "nominated_categories": existing.get("nominated_categories") or incoming.get("nominated_categories"),
            "won_categories": incoming.get("won_categories") or existing.get("won_categories"),
            "nominations_number": existing.get("nominations_number")
            if existing.get("nominations_number") is not None
            else incoming.get("nominations_number"),
            "ordinal": existing.get("ordinal")
            if existing.get("ordinal") is not None
            else incoming.get("ordinal"),
        }
        cur.execute(
            """
            UPDATE film_list_items
            SET ordinal = ?, notes = ?, where_to_watch = ?, nominated_categories = ?,
                won_categories = ?, nominations_number = ?
            WHERE id = ?;
            """,
            (
                merged["ordinal"],
                merged["notes"],
                merged["where_to_watch"],
                merged["nominated_categories"],
                merged["won_categories"],
                merged["nominations_number"],
                existing["id"],
            ),
        )
        conn.commit()
        return existing["id"]

    cur.execute(
        """
        INSERT INTO film_list_items (
            list_id, film_id, ordinal, added_at, notes, where_to_watch,
            nominated_categories, won_categories, nominations_number
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (
            list_id,
            film_id,
            incoming["ordinal"],
            now_iso(),
            incoming["notes"],
            incoming["where_to_watch"],
            incoming["nominated_categories"],
            incoming["won_categories"],
            incoming["nominations_number"],
        ),
    )
    conn.commit()
    return cur.lastrowid


def film_payload_from_watchlist_row(row):
    item = dict(row)
    title = clean_text(item.get("title"))
    wiki_url = clean_wikipedia_url(item.get("wikipedia_url"))
    imdb_url = clean_text(item.get("imdb_url"))
    release_year = film_release_year_from_title(title)
    return {
        "canonical_key": build_film_key(title, imdb_url=imdb_url, wikipedia_url=wiki_url, release_year=release_year),
        "title": title,
        "release_year": release_year,
        "type": clean_text(item.get("type")),
        "runtime": clean_text(item.get("runtime"))
        or clean_text(item.get("runtime_helper"))
        or clean_text(item.get("runtime_helper_2")),
        "director": clean_text(item.get("director_s")),
        "country": item.get("country"),
        "poster_url": clean_text(item.get("poster_url")),
        "poster_source": clean_text(item.get("poster_source")),
        "wikipedia_url": wiki_url,
        "imdb_url": imdb_url,
        "notes": clean_text(item.get("notes")),
        "rating_1_10": item.get("rating_1_10"),
        "watched": item.get("watched"),
        "watched_date": item.get("watched_date"),
    }


def sync_watchlist_to_film_library(conn=None, fetch_missing_posters=False):
    close_conn = False
    if conn is None:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        close_conn = True
    else:
        conn.row_factory = sqlite3.Row

    ensure_films_tables(conn)
    ensure_film_list(
        conn,
        "moja-lista",
        "Moja lista",
        description="Własna lista filmów poza festiwalami i nagrodami.",
        category="personal",
        source_kind="manual",
        pinned=1,
    )

    cur = conn.cursor()
    rows = cur.execute(
        "SELECT rowid AS id, * FROM watchlist ORDER BY oscars_year DESC, title ASC;"
    ).fetchall()
    synced = 0
    for row in rows:
        year = parse_year(row["oscars_year"]) or 2026
        list_id = ensure_film_list(
            conn,
            f"oscars-{year}",
            f"Oscars {year}",
            description=f"Lista Oscarów {year} zaimportowana do wspólnej biblioteki.",
            category="awards",
            source_kind="oscars",
            source_year=year,
            pinned=1 if year == 2026 else 0,
        )
        film_id = upsert_film_library_row(
            conn,
            film_payload_from_watchlist_row(row),
            fetch_missing_poster=fetch_missing_posters,
        )
        upsert_film_list_item(
            conn,
            list_id,
            film_id,
            {
                "notes": row["notes"],
                "where_to_watch": row["where_to_watch"],
                "nominated_categories": row["nominated_categories"],
                "won_categories": row["won_categories"],
                "nominations_number": row["nominations_number"],
            },
        )
        synced += 1

    if close_conn:
        conn.close()
    return synced


def hydrate_library_posters(rows):
    result = [dict(row) for row in rows]
    index = build_local_poster_index()
    if index == ({}, []):
        return result
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


def fetch_film_lists():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    ensure_films_tables(conn)
    rows = conn.execute(
        """
        SELECT
            l.*,
            COUNT(li.id) AS item_count,
            SUM(CASE WHEN COALESCE(f.watched, 0) = 1 THEN 1 ELSE 0 END) AS watched_count,
            SUM(CASE WHEN f.rating_1_10 IS NOT NULL THEN 1 ELSE 0 END) AS rated_count,
            SUM(CASE WHEN COALESCE(li.won_categories, '') <> '' THEN 1 ELSE 0 END) AS winners_count
        FROM film_lists l
        LEFT JOIN film_list_items li ON li.list_id = l.id
        LEFT JOIN film_library f ON f.id = li.film_id
        GROUP BY l.id
        ORDER BY l.pinned DESC, COALESCE(l.source_year, 0) DESC, LOWER(l.name) ASC;
        """
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


FILM_LIBRARY_DEFAULT_LIMIT = 60
FILM_LIBRARY_MAX_LIMIT = 200


def normalize_film_library_pagination(limit=None, offset=0):
    try:
        normalized_limit = FILM_LIBRARY_DEFAULT_LIMIT if limit in (None, "") else int(limit)
        normalized_offset = int(offset or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid film library pagination") from exc
    if normalized_limit <= 0 or normalized_offset < 0:
        raise ValueError("Invalid film library pagination")
    return min(normalized_limit, FILM_LIBRARY_MAX_LIMIT), normalized_offset


def fetch_film_library(list_slug=None, query=None, limit=None, offset=0):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    ensure_films_tables(conn)
    cur = conn.cursor()
    params = []
    where = []
    join = ""
    selected_list = None
    selected_columns = """
            NULL AS selected_nominated_categories,
            NULL AS selected_won_categories,
            NULL AS selected_nominations_number,
            NULL AS selected_where_to_watch
    """

    if list_slug:
        selected_list = cur.execute(
            "SELECT id, slug, name, source_kind, source_year FROM film_lists WHERE slug = ?;",
            (list_slug,),
        ).fetchone()
        if not selected_list:
            conn.close()
            return {
                "selected_list": None,
                "items": [],
                "pagination": {"limit": limit, "offset": offset, "total": 0, "has_more": False},
            }
        join = "JOIN film_list_items sli ON sli.film_id = f.id AND sli.list_id = ?"
        params.append(selected_list["id"])
        selected_columns = """
            sli.nominated_categories AS selected_nominated_categories,
            sli.won_categories AS selected_won_categories,
            sli.nominations_number AS selected_nominations_number,
            sli.where_to_watch AS selected_where_to_watch
        """

    if query:
        q = f"%{str(query).strip().lower()}%"
        where.append(
            "(LOWER(COALESCE(f.title, '')) LIKE ? OR LOWER(COALESCE(f.director, '')) LIKE ? OR LOWER(COALESCE(f.notes, '')) LIKE ?)"
        )
        params.extend([q, q, q])

    from_sql = f"""
        FROM film_library f
        {join}
    """
    where_sql = " WHERE " + " AND ".join(where) if where else ""
    total = cur.execute(
        f"SELECT COUNT(1) {from_sql} {where_sql}",
        params,
    ).fetchone()[0]

    sql = f"""
        SELECT
            f.*,
            {selected_columns}
        {from_sql}
    """
    sql += where_sql
    sql += " ORDER BY COALESCE(f.watched, 0) ASC, COALESCE(f.rating_1_10, -1) DESC, LOWER(f.title) ASC;"
    query_params = list(params)
    if limit is not None:
        limit, offset = normalize_film_library_pagination(limit, offset)
        sql = sql.rstrip(";") + " LIMIT ? OFFSET ?;"
        query_params.extend([limit, offset])
    else:
        offset = 0
    rows = cur.execute(sql, query_params).fetchall()
    items = hydrate_library_posters(rows)

    pagination = {
        "limit": limit,
        "offset": offset,
        "total": total,
        "has_more": offset + len(items) < total,
    }

    if not items:
        conn.close()
        return {
            "selected_list": dict(selected_list) if selected_list else None,
            "items": [],
            "pagination": pagination,
        }

    film_ids = [row["id"] for row in items]
    placeholders = ",".join("?" for _ in film_ids)
    memberships = cur.execute(
        f"""
        SELECT
            li.film_id,
            l.slug,
            l.name,
            l.category,
            l.source_kind,
            l.source_year,
            li.nominations_number,
            li.where_to_watch,
            li.won_categories,
            li.nominated_categories
        FROM film_list_items li
        JOIN film_lists l ON l.id = li.list_id
        WHERE li.film_id IN ({placeholders})
        ORDER BY l.pinned DESC, COALESCE(l.source_year, 0) DESC, LOWER(l.name) ASC;
        """,
        film_ids,
    ).fetchall()

    membership_map = {}
    for row in memberships:
        membership_map.setdefault(row["film_id"], []).append(
            {
                "slug": row["slug"],
                "name": row["name"],
                    "category": row["category"],
                    "source_kind": row["source_kind"],
                    "source_year": row["source_year"],
                    "nominations_number": row["nominations_number"],
                    "where_to_watch": row["where_to_watch"],
                    "won_categories": row["won_categories"],
                    "nominated_categories": row["nominated_categories"],
                }
            )

    for item in items:
        item["lists"] = membership_map.get(item["id"], [])

    conn.close()
    return {
        "selected_list": dict(selected_list) if selected_list else None,
        "items": items,
        "pagination": pagination,
    }


def fetch_film_summary():
    lists = fetch_film_lists()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    total = cur.execute("SELECT COUNT(1) FROM film_library;").fetchone()[0]
    watched = cur.execute("SELECT COUNT(1) FROM film_library WHERE COALESCE(watched, 0) = 1;").fetchone()[0]
    rated = cur.execute("SELECT COUNT(1) FROM film_library WHERE rating_1_10 IS NOT NULL;").fetchone()[0]
    avg = cur.execute("SELECT AVG(rating_1_10) FROM film_library WHERE rating_1_10 IS NOT NULL;").fetchone()[0]
    conn.close()

    featured = None
    oscars_2026 = next((item for item in lists if item.get("slug") == "oscars-2026"), None)
    today = today_iso()
    in_results_window = "2026-03-15" <= today <= "2026-03-17"

    if oscars_2026 and in_results_window and (oscars_2026.get("winners_count") or 0) > 0:
        featured = {
            "title": "Wyniki Oscarów 2026",
            "meta": f"{oscars_2026.get('winners_count') or 0} zwycięskich tytułów",
            "copy": "Widget pokazuje zwycięzców w oknie po gali, ale biblioteka pozostaje wspólnym rdzeniem dla wszystkich list.",
            "href": "./films.html?list=oscars-2026",
            "slug": "oscars-2026",
        }
    elif lists:
        current = lists[0]
        current_slug = clean_text(current.get("slug"))
        featured = {
            "title": current.get("name") or "Biblioteka filmów",
            "meta": f"{current.get('item_count') or 0} filmów na liście",
            "copy": current.get("description") or "Jedna biblioteka filmów, wiele list ponad nią.",
            "href": f"./films.html?list={urllib.parse.quote(current_slug)}" if current_slug else "./films.html",
            "slug": current_slug,
        }

    return {
        "total_films": total,
        "watched": watched,
        "rated": rated,
        "avg_rating": round(avg, 2) if avg is not None else None,
        "total_lists": len(lists),
        "lists": lists[:6],
        "featured": featured,
    }


def build_films_static_snapshot():
    return {
        "generated_at": now_iso(),
        "summary": fetch_film_summary(),
        "lists": fetch_film_lists(),
        "items": fetch_film_library().get("items", []),
    }


def write_films_static_snapshot():
    FILMS_DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = build_films_static_snapshot()
    FILMS_SNAPSHOT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return payload


def normalize_library_patch(patch):
    out = {}
    if "watched" in patch:
        watched = normalize_bool(patch.get("watched"))
        out["watched"] = watched
        if watched == 1 and not patch.get("watched_date"):
            out["watched_date"] = today_iso()
        if watched == 0 and "watched_date" not in patch:
            out["watched_date"] = None

    if "watched_date" in patch:
        wd = patch.get("watched_date")
        out["watched_date"] = normalize_date_input(wd) if wd not in (None, "") else None

    if "rating_1_10" in patch:
        n = normalize_float(patch.get("rating_1_10"))
        out["rating_1_10"] = max(0, min(10, n)) if n is not None else None

    if "notes" in patch:
        out["notes"] = clean_text(patch.get("notes"))

    if "poster_url" in patch:
        val = clean_text(patch.get("poster_url"))
        out["poster_url"] = val
        out["poster_source"] = "manual" if val else None

    return out


def update_library_film(film_id, patch):
    if film_id is None:
        return None
    fields = {k: v for k, v in normalize_library_patch(patch).items() if k in FILM_LIBRARY_UPDATE_FIELDS}
    if not fields:
        return None
    fields["updated_at"] = now_iso()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    assignments = ", ".join(f"{key} = ?" for key in fields.keys())
    params = list(fields.values()) + [film_id]
    cur.execute(f"UPDATE film_library SET {assignments} WHERE id = ?;", params)
    conn.commit()
    row = cur.execute("SELECT * FROM film_library WHERE id = ?;", (film_id,)).fetchone()
    result = hydrate_library_posters([row])[0] if row else None
    conn.close()
    write_films_static_snapshot()
    return result


CLASSICAL_CATEGORIES = {
    "Solo Piano",
    "Solo Instrument",
    "Solo Instrument(s) and Orchestra",
    "Chamber",
    "Soloist(s) + Orchestra",
    "Orchestral",
    "Stage",
    "Stage / Ballet / Opera",
    "Vocal",
    "Choral",
    "Arrangement / Orchestration",
    "Other",
}

CLASSICAL_STATUSES = {"Not listened", "In progress", "Listened", "Revisit", "Skipped"}
CLASSICAL_REACTIONS = {"", "❤️", "👍", "😐", "👎", "🧠", "🌙", "🧊", "🌀", "🔁", "⭐"}
CLASSICAL_WORK_FIELDS = {
    "title",
    "year",
    "catalogue",
    "category",
    "instrumentation",
    "version",
    "isArrangement",
    "arrangerName",
    "originalWorkId",
    "sourceNotes",
    "normalizationConfidence",
    "normalizationReason",
    "needsReview",
    "hidden",
}
CLASSICAL_COMPOSER_FIELDS = {
    "name",
    "birthDate",
    "deathDate",
    "birthPlace",
    "deathPlace",
    "bioShort",
}


def ensure_classical_files():
    CLASSICAL_COMPOSERS_DIR.mkdir(parents=True, exist_ok=True)
    CLASSICAL_PROGRESS_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not CLASSICAL_PROGRESS_PATH.exists():
        rewrite_json_file(CLASSICAL_PROGRESS_PATH, {})
    if not CLASSICAL_COMPOSER_INDEX.exists():
        ids = sorted(path.stem for path in CLASSICAL_COMPOSERS_DIR.glob("*.json") if path.name != "index.json")
        rewrite_json_file(CLASSICAL_COMPOSER_INDEX, ids)


def classical_index_ids():
    ensure_classical_files()
    ids = read_json_file(CLASSICAL_COMPOSER_INDEX, [])
    if not isinstance(ids, list):
        ids = []
    seen = []
    for item in ids:
        cid = clean_text(item)
        if cid and cid not in seen:
            seen.append(cid)
    for path in sorted(CLASSICAL_COMPOSERS_DIR.glob("*.json")):
        if path.name == "index.json":
            continue
        if path.stem not in seen:
            seen.append(path.stem)
    return seen


def write_classical_index(ids):
    clean_ids = []
    for item in ids:
        cid = clean_text(item)
        if cid and cid not in clean_ids:
            clean_ids.append(cid)
    rewrite_json_file(CLASSICAL_COMPOSER_INDEX, clean_ids)
    return clean_ids


def classical_composer_path(composer_id):
    cid = bm_slugify(composer_id or "")
    if not cid:
        raise ValueError("Composer id is required")
    return CLASSICAL_COMPOSERS_DIR / f"{cid}.json"


def read_classical_progress():
    ensure_classical_files()
    progress = read_json_file(CLASSICAL_PROGRESS_PATH, {})
    return progress if isinstance(progress, dict) else {}


def write_classical_progress(progress):
    rewrite_json_file(CLASSICAL_PROGRESS_PATH, progress if isinstance(progress, dict) else {})
    return progress


def read_classical_composer(composer_id):
    path = classical_composer_path(composer_id)
    data = read_json_file(path, None)
    if not isinstance(data, dict):
        return None
    data.setdefault("composerId", path.stem)
    data.setdefault("works", [])
    return data


def write_classical_composer(composer):
    if not isinstance(composer, dict):
        raise ValueError("Invalid composer payload")
    cid = bm_slugify(composer.get("composerId") or composer.get("name") or "")
    if not cid:
        raise ValueError("Composer id is required")
    composer["composerId"] = cid
    rewrite_json_file(classical_composer_path(cid), composer)
    ids = classical_index_ids()
    if cid not in ids:
        ids.append(cid)
        write_classical_index(ids)
    return composer


def read_classical_composers():
    composers = []
    for cid in classical_index_ids():
        composer = read_classical_composer(cid)
        if composer:
            composers.append(composer)
    return composers


def read_classical_known_composers():
    rows = read_json_file(CLASSICAL_KNOWN_COMPOSERS_PATH, [])
    return rows if isinstance(rows, list) else []


def iter_classical_works(works, level=0, parent=None):
    if not isinstance(works, list):
        return
    for work in works:
        if not isinstance(work, dict):
            continue
        yield work, level, parent
        yield from iter_classical_works(work.get("parts") or [], level + 1, work)


def find_classical_work(works, work_id):
    for work, _level, parent in iter_classical_works(works):
        if work.get("workId") == work_id:
            return work, parent
    return None, None


def classical_work_count(composer, include_hidden=False):
    count = 0
    for work, _level, _parent in iter_classical_works(composer.get("works") or []):
        if include_hidden or not work.get("hidden"):
            count += 1
    return count


def resolve_classical_display_category(category, instrumentation, is_arrangement=False):
    if is_arrangement:
        return "Arrangement / Orchestration"
    inst = [str(item or "").strip().lower() for item in (instrumentation or [])]
    if category == "Solo Instrument" and "piano" in inst:
        return "Solo Piano"
    return category if category in CLASSICAL_CATEGORIES else "Other"


def normalize_classical_instrumentation(value):
    if isinstance(value, list):
        raw = value
    else:
        raw = str(value or "").split(",")
    out = []
    for item in raw:
        text = clean_text(item)
        if text and text not in out:
            out.append(text)
    return out


def normalize_classical_rating(value):
    if value in (None, ""):
        return None
    try:
        rating = float(value)
    except (TypeError, ValueError):
        return None
    rating = round(rating * 2) / 2
    if rating < 0.5 or rating > 5:
        return None
    return rating


def normalize_classical_work_patch(patch):
    if not isinstance(patch, dict):
        return {}
    out = {}
    for key in CLASSICAL_WORK_FIELDS:
        if key not in patch:
            continue
        value = patch.get(key)
        if key == "instrumentation":
            out[key] = normalize_classical_instrumentation(value)
        elif key == "category":
            category = clean_text(value) or "Other"
            out[key] = category if category in CLASSICAL_CATEGORIES else "Other"
        elif key in {"isArrangement", "needsReview", "hidden"}:
            out[key] = bool(value)
        elif key == "normalizationConfidence":
            try:
                out[key] = max(0.0, min(1.0, float(value)))
            except (TypeError, ValueError):
                out[key] = 0.0
        else:
            out[key] = clean_text(value) if value not in (None, "") else ("" if key in {"sourceNotes", "normalizationReason"} else None)
    if "category" in out or "instrumentation" in out or "isArrangement" in out:
        category = out.get("category")
        instrumentation = out.get("instrumentation")
        is_arrangement = out.get("isArrangement")
        out["_recomputeDisplayCategory"] = True
        out["_displayCategoryInput"] = (category, instrumentation, is_arrangement)
    return out


def fetch_classical_library():
    composers = read_classical_composers()
    progress = read_classical_progress()
    known = read_classical_known_composers()
    summary = build_classical_summary(composers, progress)
    return {
        "ok": True,
        "composers": composers,
        "progress": progress,
        "knownComposers": known,
        "summary": summary,
    }


def build_classical_summary(composers=None, progress=None):
    composers = composers if composers is not None else read_classical_composers()
    progress = progress if progress is not None else read_classical_progress()
    composer_by_id = {item.get("composerId"): item for item in composers}
    work_by_id = {}
    total = 0
    listened = 0

    for composer in composers:
        for work, _level, _parent in iter_classical_works(composer.get("works") or []):
            if work.get("hidden"):
                continue
            total += 1
            work_by_id[work.get("workId")] = (work, composer)
            if (progress.get(work.get("workId")) or {}).get("status") in {"Listened", "Revisit"}:
                listened += 1

    rated_entries = []
    listened_entries = []
    for work_id, entry in progress.items():
        if not isinstance(entry, dict) or work_id not in work_by_id:
            continue
        stamp = entry.get("_updatedAt") or ""
        if entry.get("rating") is not None:
            rated_entries.append((stamp, work_id, entry))
        if entry.get("status") and entry.get("status") != "Not listened":
            listened_entries.append((stamp, work_id, entry))

    latest_tuple = sorted(rated_entries or listened_entries, key=lambda item: item[0] or "", reverse=True)[:1]
    if latest_tuple:
        _stamp, latest_work_id, latest_progress = latest_tuple[0]
        latest_work, latest_composer = work_by_id[latest_work_id]
    else:
        latest_composer = composer_by_id.get("maurice-ravel") or (composers[0] if composers else None)
        latest_work = None
        latest_progress = None

    return {
        "totalWorks": total,
        "listenedWorks": listened,
        "composerCount": len(composers),
        "featuredComposer": latest_composer,
        "latestRatedWork": latest_work if latest_progress and latest_progress.get("rating") is not None else None,
        "latestProgress": latest_progress,
    }


def update_classical_progress(payload):
    work_id = clean_text(payload.get("workId"))
    if not work_id:
        raise ValueError("Work id is required")
    patch = payload.get("patch") or {}
    if not isinstance(patch, dict):
        raise ValueError("Invalid progress patch")
    progress = read_classical_progress()
    current = progress.get(work_id) if isinstance(progress.get(work_id), dict) else {}
    next_entry = dict(current)

    if "status" in patch:
        status = clean_text(patch.get("status")) or "Not listened"
        next_entry["status"] = status if status in CLASSICAL_STATUSES else "Not listened"
    if "rating" in patch:
        next_entry["rating"] = normalize_classical_rating(patch.get("rating"))
    if "reaction" in patch:
        reaction = clean_text(patch.get("reaction")) or ""
        next_entry["reaction"] = reaction if reaction in CLASSICAL_REACTIONS else ""
    if "notes" in patch:
        next_entry["notes"] = clean_text(patch.get("notes")) or ""

    next_entry["_updatedAt"] = now_iso()
    progress[work_id] = next_entry
    write_classical_progress(progress)
    return {"ok": True, "workId": work_id, "progress": next_entry, "summary": build_classical_summary(progress=progress)}


def update_classical_composer_metadata(payload):
    composer_id = clean_text(payload.get("composerId"))
    composer = read_classical_composer(composer_id)
    if not composer:
        raise ValueError("Composer not found")
    patch = payload.get("patch") or {}
    if not isinstance(patch, dict):
        raise ValueError("Invalid composer patch")

    for key in CLASSICAL_COMPOSER_FIELDS:
        if key in patch:
            composer[key] = clean_text(patch.get(key)) or ""
    if isinstance(patch.get("image"), dict):
        image = composer.get("image") if isinstance(composer.get("image"), dict) else {}
        for key in ("localFile", "source", "sourceUrl", "license"):
            if key in patch["image"]:
                image[key] = clean_text(patch["image"].get(key)) or ""
        composer["image"] = image
    composer["updatedAt"] = now_iso()
    write_classical_composer(composer)
    return {"ok": True, "composer": composer, "summary": build_classical_summary()}


def sanitize_classical_image_filename(composer_id, filename, mime):
    cid = bm_slugify(composer_id or "")
    if not cid:
        raise ValueError("Composer id is required")
    original = Path(str(filename or "")).name
    suffix = Path(original).suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg"}:
        suffix = CLASSICAL_IMAGE_MIME_EXT.get(str(mime or "").lower(), "")
    if suffix == ".jpeg":
        suffix = ".jpg"
    if not suffix:
        raise ValueError("Unsupported image type")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{cid}-{stamp}{suffix}"


def decode_classical_image_payload(payload):
    b64_data = payload.get("contentBase64") or payload.get("content_base64")
    if not isinstance(b64_data, str) or not b64_data.strip():
        raise ValueError("Missing contentBase64")
    try:
        raw = base64.b64decode(b64_data, validate=True)
    except Exception as exc:
        raise ValueError("Invalid base64 payload") from exc
    if not raw:
        raise ValueError("Uploaded file is empty")
    if len(raw) > CLASSICAL_IMAGE_MAX_BYTES:
        raise ValueError("Image too large (max 8 MB)")
    return raw


def upload_classical_composer_image(payload):
    composer_id = clean_text(payload.get("composerId"))
    composer = read_classical_composer(composer_id)
    if not composer:
        raise ValueError("Composer not found")
    mime = clean_text(payload.get("mimeType")) or "application/octet-stream"
    suffix = Path(str(payload.get("filename") or "")).suffix.lower()
    if suffix == ".jpeg":
        suffix = ".jpg"
    if mime.lower() not in CLASSICAL_IMAGE_MIME_EXT and suffix not in {".jpg", ".png", ".webp", ".gif", ".svg"}:
        raise ValueError("Unsupported image type")
    raw = decode_classical_image_payload(payload)
    filename = sanitize_classical_image_filename(composer_id, payload.get("filename"), mime)

    CLASSICAL_PUBLIC_ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    CLASSICAL_ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    public_path = CLASSICAL_PUBLIC_ASSETS_DIR / filename
    public_path.write_bytes(raw)
    try:
        (CLASSICAL_ASSETS_DIR / filename).write_bytes(raw)
    except OSError:
        pass

    image = composer.get("image") if isinstance(composer.get("image"), dict) else {}
    image.update({
        "localFile": f"/assets/composers/{filename}",
        "source": "Local upload",
        "sourceUrl": "",
        "license": "Personal local file",
    })
    composer["image"] = image
    composer["updatedAt"] = now_iso()
    write_classical_composer(composer)
    return {
        "ok": True,
        "composer": composer,
        "image": image,
        "storedPath": public_path.relative_to(ROOT).as_posix(),
        "summary": build_classical_summary(),
    }


def decode_classical_rym_html_payload(payload):
    b64_data = payload.get("contentBase64") or payload.get("content_base64")
    if not isinstance(b64_data, str) or not b64_data.strip():
        raise ValueError("Missing saved RYM HTML file")
    try:
        raw = base64.b64decode(b64_data, validate=True)
    except Exception as exc:
        raise ValueError("Invalid saved HTML payload") from exc
    if not raw:
        raise ValueError("Saved RYM HTML file is empty")
    if len(raw) > CLASSICAL_RYM_HTML_MAX_BYTES:
        raise ValueError("Saved RYM HTML file is too large (max 15 MB)")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            return raw.decode("windows-1252")
        except UnicodeDecodeError as exc:
            raise ValueError("Saved RYM HTML must be UTF-8 or Windows-1252 text") from exc


def import_classical_rym_saved_html(payload):
    composer_id = bm_slugify(payload.get("composerId") or "")
    if not composer_id:
        raise ValueError("Composer id is required")
    composer = read_classical_composer(composer_id)
    if not composer:
        raise ValueError("Composer not found")

    mode = clean_text(payload.get("mode")) or "preview"
    if mode not in {"preview", "import"}:
        raise ValueError("Import mode must be preview or import")

    html_text = decode_classical_rym_html_payload(payload)
    if 'id="works"' not in html_text and "id='works'" not in html_text and "id=works" not in html_text:
        # The Node/Cheerio parser still performs the final structural check; this gives a quicker UI error.
        raise ValueError("RYM works list missing: expected ul#works in the saved HTML file")

    CLASSICAL_RYM_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = bm_slugify(Path(str(payload.get("filename") or "rym-saved.html")).stem) or "rym-saved"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    html_path = CLASSICAL_RYM_UPLOADS_DIR / f"{composer_id}-{stamp}-{safe_name}.html"
    html_path.write_text(html_text, encoding="utf-8")

    script_path = ROOT / "scripts" / "importers" / "import-rym-works.js"
    if not script_path.exists():
        raise ValueError("RYM importer script is missing")

    command = [
        "node",
        str(script_path),
        "--composer-id",
        composer_id,
        "--file",
        str(html_path),
        "--data",
        str(classical_composer_path(composer_id)),
        f"--{mode}",
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=45,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ValueError("Node.js is required to run the RYM importer") from exc
    except subprocess.TimeoutExpired as exc:
        raise ValueError("RYM import timed out") from exc

    output = (completed.stdout or "").strip()
    error_output = (completed.stderr or "").strip()
    if completed.returncode != 0:
        raise ValueError(error_output or output or "RYM import failed")

    result_composer = read_classical_composer(composer_id) if mode == "import" else composer
    return {
        "ok": True,
        "mode": mode,
        "composer": result_composer,
        "summary": build_classical_summary(),
        "output": output,
        "storedHtml": html_path.relative_to(ROOT).as_posix(),
    }


def update_classical_work_metadata(payload):
    composer_id = clean_text(payload.get("composerId"))
    work_id = clean_text(payload.get("workId"))
    composer = read_classical_composer(composer_id)
    if not composer:
        raise ValueError("Composer not found")
    work, _parent = find_classical_work(composer.get("works") or [], work_id)
    if not work:
        raise ValueError("Work not found")

    patch = normalize_classical_work_patch(payload.get("patch") or {})
    merge_into = clean_text((payload.get("patch") or {}).get("mergeInto"))
    for key, value in patch.items():
        if key.startswith("_"):
            continue
        work[key] = value
        work.setdefault("userMetadataOverrides", {})[key] = value

    if patch.get("_recomputeDisplayCategory"):
        category = work.get("category") or "Other"
        instrumentation = work.get("instrumentation") or []
        display = resolve_classical_display_category(category, instrumentation, bool(work.get("isArrangement")))
        work["displayCategory"] = display
        work.setdefault("userMetadataOverrides", {})["displayCategory"] = display

    if merge_into and merge_into != work_id:
        target, _target_parent = find_classical_work(composer.get("works") or [], merge_into)
        if not target:
            raise ValueError("Merge target not found")
        work["hidden"] = True
        work.setdefault("userMetadataOverrides", {})["mergedInto"] = merge_into
        note = clean_text(work.get("sourceNotes")) or ""
        merge_note = f"Merged into {merge_into} on {today_iso()}."
        work["sourceNotes"] = f"{note}\n{merge_note}".strip()

    work["updatedAt"] = now_iso()
    write_classical_composer(composer)
    return {"ok": True, "composer": composer, "work": work, "summary": build_classical_summary()}


def search_classical_composers(query, limit=10):
    q = (clean_text(query) or "").lower()
    existing_ids = set(classical_index_ids())
    rows = []
    candidates = read_classical_known_composers() + [
        {
            "composerId": item.get("composerId"),
            "name": item.get("name"),
            "birthDate": item.get("birthDate"),
            "deathDate": item.get("deathDate"),
            "birthPlace": item.get("birthPlace"),
            "deathPlace": item.get("deathPlace"),
            "image": item.get("image") or {},
            "bioShort": item.get("bioShort") or "",
        }
        for item in read_classical_composers()
    ]
    seen = set()
    for item in candidates:
        name = clean_text(item.get("name")) or ""
        cid = bm_slugify(item.get("composerId") or name)
        if not cid or cid in seen:
            continue
        haystack = f"{name} {item.get('birthPlace') or ''}".lower()
        if q and q not in haystack:
            continue
        seen.add(cid)
        entry = dict(item)
        entry["composerId"] = cid
        entry["alreadyInLibrary"] = cid in existing_ids
        rows.append(entry)
        if len(rows) >= limit:
            break
    return rows


def add_classical_composer(payload):
    composer_id = bm_slugify(payload.get("composerId") or payload.get("name") or "")
    if not composer_id:
        raise ValueError("Composer name is required")
    existing = read_classical_composer(composer_id)
    if existing:
        return existing
    match = next((item for item in read_classical_known_composers() if bm_slugify(item.get("composerId") or item.get("name") or "") == composer_id), None)
    source = match or payload
    composer = {
        "composerId": composer_id,
        "name": clean_text(source.get("name")) or composer_id.replace("-", " ").title(),
        "birthDate": clean_text(source.get("birthDate")) or "",
        "deathDate": clean_text(source.get("deathDate")) or "",
        "birthPlace": clean_text(source.get("birthPlace")) or "",
        "deathPlace": clean_text(source.get("deathPlace")) or "",
        "image": source.get("image") if isinstance(source.get("image"), dict) else {"localFile": "", "source": "", "sourceUrl": "", "license": ""},
        "bioShort": clean_text(source.get("bioShort")) or "",
        "sources": [{"name": "Manual Add Composer", "url": "", "notes": "Basic profile only. Full works are imported only after Import Works."}],
        "works": [],
        "createdAt": now_iso(),
        "updatedAt": now_iso(),
    }
    return write_classical_composer(composer)


def refresh_classical_placeholder(payload, kind):
    composer_id = clean_text(payload.get("composerId"))
    composer = read_classical_composer(composer_id)
    if not composer:
        raise ValueError("Composer not found")
    composer["lastImportStatus"] = {
        "kind": kind,
        "updatedAt": now_iso(),
        "message": "Adapter placeholder completed. Seed/manual data was preserved.",
    }
    write_classical_composer(composer)
    return {"ok": True, "composer": composer, "message": composer["lastImportStatus"]["message"]}


def create_film_list(payload):
    name = clean_text(payload.get("name"))
    if not name:
        raise ValueError("List name is required")
    category = clean_text(payload.get("category")) or "custom"
    description = clean_text(payload.get("description")) or ""
    source_year = parse_year(payload.get("source_year"))

    conn = sqlite3.connect(DB_PATH)
    ensure_films_tables(conn)
    slug = unique_film_list_slug(conn, payload.get("slug") or name)
    list_id = ensure_film_list(
        conn,
        slug,
        name,
        description=description,
        category=category,
        source_kind="manual",
        source_year=source_year,
        pinned=1 if category == "personal" else 0,
    )
    conn.close()
    write_films_static_snapshot()
    lists = fetch_film_lists()
    return next((item for item in lists if item.get("id") == list_id), None)


def add_film_to_library(payload):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    ensure_films_tables(conn)

    film_id = normalize_int(payload.get("film_id"))
    if film_id:
        film_row = conn.execute("SELECT * FROM film_library WHERE id = ?;", (film_id,)).fetchone()
        if not film_row:
            conn.close()
            raise ValueError("Film not found")
    else:
        title = clean_text(payload.get("title"))
        if not title:
            conn.close()
            raise ValueError("Film title is required")

        release_year = parse_release_year(payload.get("release_year")) or film_release_year_from_title(title)
        wikipedia_url = clean_wikipedia_url(payload.get("wikipedia_url"))
        imdb_url = clean_text(payload.get("imdb_url"))

        film_id = upsert_film_library_row(
            conn,
            {
                "title": title,
                "release_year": release_year,
                "type": clean_text(payload.get("type")) or "Film",
                "runtime": clean_text(payload.get("runtime")),
                "director": clean_text(payload.get("director")),
                "country": clean_text(payload.get("country")),
                "poster_url": clean_text(payload.get("poster_url")),
                "poster_source": clean_text(payload.get("poster_source")) or payload.get("source") or "manual",
                "wikipedia_url": wikipedia_url,
                "imdb_url": imdb_url,
                "notes": clean_text(payload.get("notes")),
                "rating_1_10": payload.get("rating_1_10"),
                "watched": payload.get("watched"),
                "watched_date": payload.get("watched_date"),
            },
        )

    target_list = clean_text(payload.get("list_slug"))
    if target_list:
        row = conn.execute("SELECT id FROM film_lists WHERE slug = ?;", (target_list,)).fetchone()
        if not row:
            conn.close()
            raise ValueError("Target list not found")
        upsert_film_list_item(
            conn,
            row["id"],
            film_id,
            {
                "notes": payload.get("list_notes"),
                "where_to_watch": payload.get("where_to_watch"),
                "nominated_categories": payload.get("nominated_categories"),
                "won_categories": payload.get("won_categories"),
                "nominations_number": payload.get("nominations_number"),
            },
        )

    film = conn.execute("SELECT * FROM film_library WHERE id = ?;", (film_id,)).fetchone()
    conn.close()
    write_films_static_snapshot()
    return hydrate_library_posters([film])[0] if film else None


def search_films_wikipedia(query, limit=8):
    q = clean_text(query)
    if not q:
        return []
    headers = {"User-Agent": WIKI_UA}
    search_params = {
        "action": "query",
        "list": "search",
        "srsearch": f'{q} film',
        "format": "json",
        "srlimit": max(1, min(int(limit or 8), 12)),
        "utf8": 1,
    }
    search_url = f"https://en.wikipedia.org/w/api.php?{urllib.parse.urlencode(search_params)}"
    data = http_get_json(search_url, headers=headers, timeout=20)
    hits = (data.get("query") or {}).get("search") or []
    if not hits:
        return []

    pageids = [str(item.get("pageid")) for item in hits if item.get("pageid")]
    details = {}
    if pageids:
        detail_params = {
            "action": "query",
            "pageids": "|".join(pageids),
            "prop": "pageimages|extracts|info",
            "format": "json",
            "formatversion": 2,
            "inprop": "url",
            "piprop": "thumbnail",
            "pithumbsize": 360,
            "exintro": 1,
            "explaintext": 1,
        }
        detail_url = f"https://en.wikipedia.org/w/api.php?{urllib.parse.urlencode(detail_params)}"
        detail_data = http_get_json(detail_url, headers=headers, timeout=20)
        for page in (detail_data.get("query") or {}).get("pages") or []:
            details[str(page.get("pageid"))] = page

    results = []
    for item in hits:
        pageid = str(item.get("pageid"))
        detail = details.get(pageid, {})
        title = clean_text(detail.get("title") or item.get("title"))
        if not title:
            continue
        results.append(
            {
                "source": "wikipedia",
                "title": title,
                "release_year": film_release_year_from_title(title),
                "description": clean_text(detail.get("extract")) or re.sub(r"<[^>]+>", "", item.get("snippet") or ""),
                "poster_url": ((detail.get("thumbnail") or {}).get("source")),
                "poster_source": "wikipedia" if (detail.get("thumbnail") or {}).get("source") else None,
                "wikipedia_url": clean_text(detail.get("fullurl")),
                "imdb_url": None,
            }
        )
    return results

def log_line(msg: str, tag: str = "api", level: str = "info", console: bool = True):
    ts_file = fmt_time(short=False)
    line = f"[{ts_file}] [{tag}] {msg}"
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    if not console:
        return
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


def record_live_workout_console_result(success, samples=0, sse_clients=None, now=None):
    current = time.monotonic() if now is None else float(now)
    snapshot = None
    with LIVE_WORKOUT_CONSOLE_STATS_LOCK:
        stats = LIVE_WORKOUT_CONSOLE_STATS
        if stats["started_at"] is None:
            stats["started_at"] = current
        stats["requests"] += 1
        stats["successes" if success else "failures"] += 1
        if success:
            stats["samples"] += max(0, int(samples))
        if sse_clients is not None:
            stats["sse_clients"] = max(0, int(sse_clients))
        elapsed = current - stats["started_at"]
        if elapsed >= LIVE_WORKOUT_CONSOLE_SUMMARY_INTERVAL_SEC:
            snapshot = dict(stats)
            snapshot["elapsed"] = elapsed
            stats.update({
                "started_at": current,
                "requests": 0,
                "successes": 0,
                "failures": 0,
                "samples": 0,
                "sse_clients": 0,
            })

    if snapshot is None:
        return None

    success_rate = snapshot["successes"] / snapshot["requests"] * 100
    elapsed_minutes = max(1, round(snapshot["elapsed"] / 60))
    message = (
        f"telemetry summary {elapsed_minutes}m | requests={snapshot['requests']} | "
        f"success={success_rate:.1f}% | samples={snapshot['samples']} | "
        f"errors={snapshot['failures']} | SSE={snapshot['sse_clients']}"
    )
    log_line(
        message,
        tag="live-workout",
        level="success" if snapshot["failures"] == 0 else "warn",
    )
    return message


def log_json(title: str, payload, tag: str = "api", level: str = "dim"):
    log_line(title, tag=tag, level=level)
    try:
        pretty = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    except Exception:
        pretty = str(payload)
    for line in pretty.splitlines():
        log_line(f"  {line}", tag=tag, level=level)


def show_http_log_in_console(status, method, path=""):
    mode = str(os.environ.get("DASHBOARD_HTTP_LOG", "compact") or "compact").strip().lower()
    if mode in {"all", "full", "verbose", "1", "true", "yes", "on"}:
        return True
    if mode in {"off", "none", "0", "false", "no"}:
        return False
    if mode in {"errors", "error"}:
        return status >= 400
    if path == "/api/live-workout/telemetry":
        return False
    return status >= 300 or method not in {"GET", "HEAD", "OPTIONS"}


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
    req_headers = {"User-Agent": WIKI_UA, "Accept": "application/json"}
    req_headers.update(headers or {})
    req = urllib.request.Request(url, headers=req_headers)
    started = time.perf_counter()
    def fetch():
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read().decode("utf-8")
            status = getattr(resp, "status", 200) or 200
        return (json.loads(data) if data else {}), status
    try:
        payload, status, cache_hit = FOOTBALL_REQUEST_CONTROL.get(url, fetch)
        received = next((len(payload[key]) for key in ("response", "events", "results", "table")
                         if isinstance(payload, dict) and isinstance(payload.get(key), list)), None)
        if not cache_hit:
            try:
                record_football_request(FOOTBALL_DIAGNOSTICS_JSON, url, status,
                                        (time.perf_counter() - started) * 1000, received)
            except Exception:
                pass
        return payload
    except Exception as exc:
        if not (isinstance(exc, RuntimeError) and " cooldown:" in str(exc)):
            try:
                record_football_request(FOOTBALL_DIAGNOSTICS_JSON, url,
                                        exc.code if isinstance(exc, urllib.error.HTTPError) else None,
                                        (time.perf_counter() - started) * 1000,
                                        error=f"{type(exc).__name__}: {getattr(exc, 'code', '')}")
            except Exception:
                pass
        raise


def wiki_get_json(url, headers=None, timeout=10, attempts=3):
    """Fetch Wikimedia JSON and honor short HTTP 429 rate limits."""
    total_attempts = max(1, int(attempts or 1))
    for attempt in range(total_attempts):
        try:
            return http_get_json(url, headers=headers, timeout=timeout)
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt + 1 >= total_attempts:
                raise
            retry_after = str(exc.headers.get("Retry-After") or "").strip()
            try:
                delay = float(retry_after)
            except ValueError:
                delay = float(2 ** attempt)
            time.sleep(max(0.25, min(delay, 15.0)))
    return {}


def http_request_json(url, method="GET", headers=None, payload=None, timeout=20):
    data = None
    req_headers = dict(headers or {})
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        req_headers.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            if not raw:
                return {}
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise GoogleCalendarApiError(exc.code, body) from exc


def http_post_form_json(url, fields, timeout=20):
    data = urllib.parse.urlencode(fields).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise GoogleCalendarApiError(exc.code, body) from exc


def parse_optional_int(value):
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_lookup_text(value):
    raw = unicodedata.normalize("NFKD", str(value or ""))
    raw = "".join(ch for ch in raw if not unicodedata.combining(ch))
    return raw.lower()


def find_nested_by_key(obj, predicate):
    if isinstance(obj, dict):
        for key, value in obj.items():
            if predicate(normalize_lookup_text(key)):
                return value
        for value in obj.values():
            found = find_nested_by_key(value, predicate)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = find_nested_by_key(value, predicate)
            if found is not None:
                return found
    return None


def normalize_gios_aqi_payload(payload):
    category = find_nested_by_key(
        payload,
        lambda key: "nazwa kategorii indeksu" in key and "wskaznik" not in key,
    )
    value = find_nested_by_key(payload, lambda key: key == "wartosc indeksu")
    computed_at = find_nested_by_key(payload, lambda key: "data wykonania obliczen indeksu" in key)
    if isinstance(computed_at, str):
        computed_at = computed_at.strip().replace(" ", "T")
    return {
        "category": category,
        "value": value,
        "computedAt": computed_at,
    }


def read_kitchen_aqi():
    errors = []
    for url in GIOS_AQI_URLS:
        try:
            aqi = normalize_gios_aqi_payload(http_get_json(url, timeout=12))
            if aqi.get("category") is not None or aqi.get("value") is not None:
                return aqi, None
            errors.append(f"{url}: empty AQI payload")
        except Exception as exc:
            errors.append(f"{url}: {exc}")
    return None, "; ".join(errors)


def strip_wiki_markup(value):
    text = re.sub(r"<ref\b.*", "", str(value or ""), flags=re.I)
    text = re.sub(r"\{\{.*?\}\}", "", text)
    text = re.sub(r"\[\[([^|\]]+)\|([^\]]+)\]\]", r"\2", text)
    text = re.sub(r"\[\[([^\]]+)\]\]", r"\1", text)
    text = re.sub(r"'{2,}", "", text)
    text = text.replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", text).strip()


def load_polish_namedays():
    try:
        calendar = json.loads(POLISH_NAMEDAYS_PATH.read_text(encoding="utf-8"))
        return calendar.get("days", {})
    except (OSError, ValueError, TypeError):
        return {}


POLISH_NAMEDAYS = load_polish_namedays()


def moon_phase_info(today):
    synodic_month = 29.53058867
    known_new_moon = datetime(2000, 1, 6, 18, 14)
    noon = datetime(today.year, today.month, today.day, 12)
    age = ((noon - known_new_moon).total_seconds() / 86400.0) % synodic_month
    illumination = (1 - math.cos(2 * math.pi * (age / synodic_month))) / 2

    if age < 1.84566 or age >= 27.68493:
        label = "nów"
    elif age < 5.53699:
        label = "sierp rosnący"
    elif age < 9.22831:
        label = "pierwsza kwadra"
    elif age < 12.91963:
        label = "garbaty rosnący"
    elif age < 16.61096:
        label = "pełnia"
    elif age < 20.30228:
        label = "garbaty malejący"
    elif age < 23.99361:
        label = "ostatnia kwadra"
    else:
        label = "sierp malejący"

    return {
        "label": label,
        "ageDays": round(age, 1),
        "illumination": round(illumination * 100),
        "phase": round(age / synodic_month, 4),
    }


def daily_kitchen_info(today=None):
    today = today or date.today()
    namedays = POLISH_NAMEDAYS.get(f"{today.month:02d}-{today.day:02d}", [])
    return {
        "date": today.isoformat(),
        "namedays": namedays,
        "moon": moon_phase_info(today),
    }


def fetch_kitchen_image(url):
    parsed = urllib.parse.urlparse(str(url or "").strip())
    if parsed.scheme != "https" or parsed.hostname not in KITCHEN_IMAGE_HOSTS:
        raise ValueError("Image host not allowed")
    req = urllib.request.Request(url, headers={"User-Agent": WIKI_UA})
    with urllib.request.urlopen(req, timeout=12) as resp:
        content_type = resp.headers.get("Content-Type") or "image/png"
        if not content_type.lower().startswith("image/"):
            raise ValueError("Not an image")
        data = resp.read(KITCHEN_IMAGE_MAX_BYTES + 1)
    if len(data) > KITCHEN_IMAGE_MAX_BYTES:
        raise ValueError("Image too large")
    return data, content_type


def normalize_kitchen_clozemaster_url(value, allow_empty=False):
    raw = str(value or "").strip()
    if not raw:
        if allow_empty:
            return ""
        return KITCHEN_DEFAULT_CLOZEMASTER_URL
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme != "https" or parsed.netloc.lower() != "www.clozemaster.com":
        raise ValueError("Clozemaster URL must start with https://www.clozemaster.com/")
    return urllib.parse.urlunparse(parsed)


def normalize_kitchen_recipe(value):
    raw = value if isinstance(value, dict) else {}
    content = str(raw.get("content") or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(content) > KITCHEN_RECIPE_MAX_LENGTH:
        raise ValueError(f"Recipe is too long (max {KITCHEN_RECIPE_MAX_LENGTH} characters)")
    return {
        "enabled": bool(normalize_bool(raw.get("enabled"))) and bool(content),
        "content": content,
    }


def static_league_for_thesportsdb_id(league_id):
    needle = str(league_id or "")
    return next(
        (league for league in kitchen_competitions() if str(league.get("thesportsdb_id") or "") == needle),
        None,
    )


def dynamic_league_key(league_id):
    static = static_league_for_thesportsdb_id(league_id)
    return static["key"] if static else f"tsdb-{league_id}"


def polish_country_name(value):
    raw = str(value or "").strip()
    if not raw:
        return ""
    key = normalize_lookup_text(raw).replace(" and ", "/")
    if "/" in key:
        parts = [polish_country_name(part) for part in re.split(r"[/,]+", raw) if str(part).strip()]
        return "/".join(part for part in parts if part)
    return COUNTRY_PL_NAMES.get(key, raw)


def fetch_thesportsdb_league_catalog():
    payload = http_get_json(f"{THESPORTSDB_API_BASE}/all_leagues.php", timeout=14)
    rows = []
    for item in payload.get("leagues") or []:
        league_id = str(item.get("idLeague") or "").strip()
        name = str(item.get("strLeague") or "").strip()
        sport = str(item.get("strSport") or "").strip() or "Soccer"
        if not league_id or not name:
            continue
        badge = ""
        try:
            detail = http_get_json(f"{THESPORTSDB_API_BASE}/lookupleague.php?id={league_id}", timeout=10)
            league_detail = ((detail.get("leagues") or [{}])[0] or {})
            badge = league_detail.get("strBadge") or league_detail.get("strLogo") or ""
            country = polish_country_name(league_detail.get("strCountry") or "")
        except Exception:
            badge = ""
            country = ""
        rows.append({
            "key": dynamic_league_key(league_id),
            "name": name,
            "sport": sport,
            "kind": "competition",
            "thesportsdb_id": parse_optional_int(league_id),
            "badge": badge,
            "tableAvailable": True,
            "country": country,
            "group": "Hokej" if sport == "Ice Hockey" else (country or ("Ligi krajowe" if sport == "Soccer" else sport)),
            "source": "thesportsdb",
        })
    return rows


def fetch_thesportsdb_league_badge(league_id):
    key = str(league_id or "")
    if not key:
        return ""
    if key in KITCHEN_LEAGUE_BADGE_CACHE:
        return KITCHEN_LEAGUE_BADGE_CACHE[key]
    try:
        detail = http_get_json(f"{THESPORTSDB_API_BASE}/lookupleague.php?id={key}", timeout=10)
        league_detail = ((detail.get("leagues") or [{}])[0] or {})
        badge = league_detail.get("strBadge") or league_detail.get("strLogo") or ""
    except Exception:
        badge = ""
    KITCHEN_LEAGUE_BADGE_CACHE[key] = badge
    return badge


def kitchen_league_group(league):
    if league.get("settingsGroup"):
        return league["settingsGroup"]
    key = league.get("key")
    sport = league.get("sport")
    country = polish_country_name(league.get("country") or {
        "premier-league": "Anglia",
        "ekstraklasa": "Polska",
        "polish-i-liga": "Polska",
        "polish-ii-liga": "Polska",
        "fa-cup": "Anglia",
    }.get(key))
    if key == "world-cup":
        return "Świat"
    if key in {"champions-league", "europa-league", "conference-league"}:
        return "Europa"
    if country:
        return country
    if sport == "Ice Hockey":
        return "Hokej"
    return "Ligi krajowe"


def read_thesportsdb_league_catalog():
    cached = read_json_file(KITCHEN_LEAGUES_CATALOG_JSON, {})
    cached_at = parse_match_datetime(cached.get("updatedAt")) if isinstance(cached, dict) else None
    if (
        isinstance(cached, dict)
        and cached.get("schemaVersion") == KITCHEN_LEAGUES_CATALOG_SCHEMA_VERSION
        and isinstance(cached.get("leagues"), list)
        and cached_at
        and (datetime.now().replace(microsecond=0) - cached_at).total_seconds() < KITCHEN_LEAGUES_CACHE_TTL
    ):
        return cached["leagues"]
    try:
        leagues = fetch_thesportsdb_league_catalog()
        rewrite_json_file(KITCHEN_LEAGUES_CATALOG_JSON, {
            "schemaVersion": KITCHEN_LEAGUES_CATALOG_SCHEMA_VERSION,
            "updatedAt": datetime.now().replace(microsecond=0).isoformat(),
            "leagues": leagues,
        })
        return leagues
    except Exception:
        return cached.get("leagues") if isinstance(cached, dict) and isinstance(cached.get("leagues"), list) else []


def kitchen_available_result_leagues():
    catalog = read_thesportsdb_league_catalog()
    catalog_by_id = {
        str(item.get("thesportsdb_id") or ""): item
        for item in catalog
        if item.get("thesportsdb_id")
    }
    static_options = [
        {
            "key": league["key"],
            "name": league["name"],
            "sport": league.get("sport") or "Soccer",
            "kind": "competition",
            "badge": (
                KITCHEN_LEAGUE_BADGES.get(league["key"])
                or
                league.get("badge")
                or
                (catalog_by_id.get(str(league.get("thesportsdb_id") or "")) or {}).get("badge")
                or fetch_thesportsdb_league_badge(league.get("thesportsdb_id"))
            ),
            "tableAvailable": bool(
                (league.get("standing") or league.get("thesportsdb_id"))
                and league.get("key") != "nhl"
                and (not kitchen_source_is_cup(league) or league.get("leaguePhaseTable"))
            ),
            "group": kitchen_league_group(league),
            "source": "configured",
            "nextTournament": league.get("nextTournament"),
        }
        for league in kitchen_competitions()
    ]
    by_key = {item["key"]: item for item in static_options}
    for item in catalog:
        key = item["key"]
        if key not in by_key:
            by_key[key] = {
                **item,
                "group": "Hokej" if item.get("sport") == "Ice Hockey" else polish_country_name(item.get("country") or item.get("group")) or "Ligi krajowe",
            }
    return sorted(
        by_key.values(),
        key=lambda item: (
            {
                "Świat": 0,
                "Europa": 1,
                "Anglia": 2,
                "Polska": 3,
                "Reprezentacje - FIFA": 20,
                "Reprezentacje - UEFA": 21,
                "Reprezentacje - CONMEBOL": 22,
                "Reprezentacje - CAF": 23,
                "Reprezentacje - AFC": 24,
                "Reprezentacje - CONCACAF": 25,
                "Reprezentacje - OFC": 26,
                "Reprezentacje - CONIFA": 27,
                "Reprezentacje - Inne": 28,
                "Hokej": 98,
            }.get(item.get("group"), 9),
            str(item.get("group") or ""),
            str(item.get("sport") or ""),
            str(item.get("name") or ""),
        ),
    )


def kitchen_available_result_teams():
    by_key = {}
    crest_by_team = {}
    for source in list(kitchen_teams()) + list(KITCHEN_NEXT_TEAMS):
        if KITCHEN_TEAM_CRESTS.get(source.get("key")):
            crest_by_team[source["key"]] = KITCHEN_TEAM_CRESTS[source["key"]]
            continue
        if source.get("key") in crest_by_team or not source.get("thesportsdb_team_id"):
            continue
        source_name = normalize_lookup_text(source.get("name"))
        for endpoint, field in [("eventsnext", "events"), ("eventslast", "results")]:
            if source.get("key") in crest_by_team:
                break
            try:
                payload = http_get_json(
                    f"{THESPORTSDB_API_BASE}/{endpoint}.php?id={source['thesportsdb_team_id']}",
                    timeout=10,
                )
                for item in payload.get(field) or []:
                    for name_key, badge_key in [
                        ("strHomeTeam", "strHomeTeamBadge"),
                        ("strAwayTeam", "strAwayTeamBadge"),
                    ]:
                        if normalize_lookup_text(item.get(name_key)) == source_name and item.get(badge_key):
                            crest_by_team[source["key"]] = item.get(badge_key)
                            break
                    if source.get("key") in crest_by_team:
                        break
            except Exception:
                continue
    target_team_keys = {team["key"] for team in kitchen_teams()} | {team["key"] for team in KITCHEN_NEXT_TEAMS}
    if len(crest_by_team) < len(target_team_keys):
        try:
            settings = {"sports": {"enabledTeamKeys": [team["key"] for team in kitchen_teams()]}}
            recent_cutoff = datetime.now().replace(microsecond=0) - timedelta(days=30)
            for match in fetch_thesportsdb_team_scores(recent_cutoff, settings=settings):
                source = match.get("leagueKey")
                if source in crest_by_team:
                    continue
                for side in ["home", "away"]:
                    team = match.get(side) or {}
                    if team.get("crest"):
                        crest_by_team[source] = team.get("crest")
                        break
        except Exception:
            pass
    for team in kitchen_teams():
        by_key[team["key"]] = {
            "key": team["key"],
            "name": team["name"],
            "kind": "team",
            "crest": KITCHEN_TEAM_CRESTS.get(team["key"]) or crest_by_team.get(team["key"]) or team.get("crest") or "",
            "hasRecentResults": True,
            "hasNextMatches": any(next_team.get("key") == team["key"] for next_team in KITCHEN_NEXT_TEAMS),
        }
    for team in KITCHEN_NEXT_TEAMS:
        current = by_key.setdefault(
            team["key"],
            {
                "key": team["key"],
                "name": team["name"],
                "kind": "team",
                "crest": KITCHEN_TEAM_CRESTS.get(team["key"]) or crest_by_team.get(team["key"]) or team.get("crest") or "",
                "hasRecentResults": False,
                "hasNextMatches": True,
            },
        )
        current["hasNextMatches"] = True
        if not current.get("crest") and crest_by_team.get(team["key"]):
            current["crest"] = crest_by_team[team["key"]]
    return list(by_key.values())


def default_kitchen_sports_settings():
    return {
        "windowHours": KITCHEN_DEFAULT_WINDOW_HOURS,
        "enabledLeagueKeys": [
            league["key"]
            for league in kitchen_competitions()
            if league.get("defaultEnabled", True) is not False
        ],
        "standingsLeagueKeys": [
            league["key"]
            for league in kitchen_competitions()
            if league.get("standing")
        ],
        "enabledTeamKeys": [team["key"] for team in kitchen_available_result_teams()],
    }


def normalize_kitchen_settings_payload(raw):
    raw = raw if isinstance(raw, dict) else {}
    sports_defaults = default_kitchen_sports_settings()
    league_keys = {league["key"] for league in kitchen_available_result_leagues()}
    team_keys = {team["key"] for team in kitchen_available_result_teams()}
    sports = raw.get("sports") if isinstance(raw.get("sports"), dict) else raw

    window_hours = parse_optional_int(sports.get("windowHours"))
    if window_hours not in KITCHEN_WINDOW_HOUR_OPTIONS:
        window_hours = KITCHEN_DEFAULT_WINDOW_HOURS

    raw_leagues = sports.get("enabledLeagueKeys") if "enabledLeagueKeys" in sports else sports_defaults["enabledLeagueKeys"]
    raw_standings = sports.get("standingsLeagueKeys") if "standingsLeagueKeys" in sports else sports_defaults["standingsLeagueKeys"]
    raw_teams = sports.get("enabledTeamKeys") if "enabledTeamKeys" in sports else sports_defaults["enabledTeamKeys"]
    enabled_leagues = [key for key in (raw_leagues or []) if key in league_keys]
    standings_leagues = [key for key in (raw_standings or []) if key in league_keys and key in enabled_leagues]
    enabled_teams = [key for key in (raw_teams or []) if key in team_keys]

    return {
        "windowHours": window_hours,
        "enabledLeagueKeys": enabled_leagues,
        "standingsLeagueKeys": standings_leagues,
        "enabledTeamKeys": enabled_teams,
    }


def kitchen_settings_signature(settings):
    sports = settings.get("sports") or {}
    return {
        "windowHours": sports.get("windowHours") or KITCHEN_DEFAULT_WINDOW_HOURS,
        "enabledLeagueKeys": sorted(sports.get("enabledLeagueKeys") or []),
        "standingsLeagueKeys": sorted(sports.get("standingsLeagueKeys") or []),
        "enabledTeamKeys": sorted(sports.get("enabledTeamKeys") or []),
    }


def kitchen_upcoming_tournaments(limit=12, today=None):
    today = today or datetime.now(KITCHEN_TIMEZONE).date()
    tournaments = []
    for league in kitchen_competitions():
        tournament = league.get("nextTournament")
        if not isinstance(tournament, dict):
            continue
        start = parse_kitchen_date(tournament.get("startDate"))
        end = parse_kitchen_date(tournament.get("endDate")) or start
        if not start or (end and end < today):
            continue
        days_until = max(0, (start - today).days)
        if start <= today and (not end or today <= end):
            days_label = "trwa"
            sort_days = 0
        elif days_until == 0:
            days_label = "dzisiaj"
            sort_days = 0
        elif days_until == 1:
            days_label = "jutro"
            sort_days = 1
        else:
            days_label = f"za {days_until} dni"
            sort_days = days_until
        tournaments.append({
            "key": league.get("key"),
            "name": league.get("name"),
            "group": league.get("settingsGroup") or kitchen_league_group(league),
            "status": tournament.get("status") or "unconfirmed",
            "dateLabel": tournament.get("dateLabel") or "",
            "host": tournament.get("host") or "",
            "startDate": tournament.get("startDate"),
            "endDate": tournament.get("endDate"),
            "daysUntil": days_until,
            "daysLabel": days_label,
            "sortDays": sort_days,
            "note": tournament.get("note") or "",
            "sourceLabel": tournament.get("sourceLabel") or "",
        })
    tournaments.sort(key=lambda item: (item.get("sortDays", 99999), item.get("startDate") or "", item.get("name") or ""))
    return tournaments[:limit]


def read_kitchen_settings():
    raw = read_json_file(KITCHEN_SETTINGS_JSON, {})
    if not isinstance(raw, dict):
        raw = {}
    try:
        clozemaster_url = normalize_kitchen_clozemaster_url(raw.get("clozemasterUrl"))
    except ValueError:
        clozemaster_url = KITCHEN_DEFAULT_CLOZEMASTER_URL
    sports = normalize_kitchen_settings_payload(raw.get("sports") if isinstance(raw.get("sports"), dict) else raw)
    recipe = normalize_kitchen_recipe(raw.get("recipe"))
    return {
        "ok": True,
        "clozemasterUrl": clozemaster_url,
        "defaultClozemasterUrl": KITCHEN_DEFAULT_CLOZEMASTER_URL,
        "sports": sports,
        "recipe": recipe,
        "sportsOptions": {
            "windowHours": KITCHEN_WINDOW_HOUR_OPTIONS,
            "leagues": kitchen_available_result_leagues(),
            "teams": kitchen_available_result_teams(),
            "nextTournaments": kitchen_upcoming_tournaments(),
        },
        "updatedAt": raw.get("updatedAt") or "",
    }


def write_kitchen_settings(payload):
    if not isinstance(payload, dict):
        raise ValueError("Invalid settings payload")
    current = read_kitchen_settings()
    next_url = normalize_kitchen_clozemaster_url(
        payload.get("clozemasterUrl", current.get("clozemasterUrl")),
        allow_empty=True,
    ) or KITCHEN_DEFAULT_CLOZEMASTER_URL
    sports = normalize_kitchen_settings_payload(payload.get("sports") or current.get("sports"))
    recipe = normalize_kitchen_recipe(payload.get("recipe", current.get("recipe")))
    settings = {
        "clozemasterUrl": next_url,
        "sports": sports,
        "recipe": recipe,
        "updatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    if (
        next_url == current.get("clozemasterUrl")
        and sports == current.get("sports")
        and recipe == current.get("recipe")
        and current.get("updatedAt")
    ):
        settings["updatedAt"] = current.get("updatedAt")
    rewrite_json_file(KITCHEN_SETTINGS_JSON, settings)
    return read_kitchen_settings()


def read_kitchen_weather():
    current = {}
    weather_error = None
    try:
        weather = http_get_json(OPEN_METEO_KITCHEN_URL, timeout=12)
        current = weather.get("current") or {}
    except Exception as exc:
        weather_error = str(exc)

    aqi, aqi_error = read_kitchen_aqi()

    return {
        "ok": True,
        "updatedAt": now_iso(),
        "weather": {
            "temp": current.get("temperature_2m"),
            "feels": current.get("apparent_temperature"),
            "code": current.get("weather_code"),
            "wind": current.get("wind_speed_10m"),
            "gust": current.get("wind_gusts_10m"),
            "hum": current.get("relative_humidity_2m"),
            "prcp": current.get("precipitation"),
            "cloud": current.get("cloud_cover"),
            "time": current.get("time"),
        },
        "weatherError": weather_error,
        "aqi": aqi,
        "aqiError": aqi_error,
        "daily": daily_kitchen_info(date.today()),
    }


def current_football_season(today=None):
    today = today or date.today()
    return today.year if today.month >= 7 else today.year - 1


def parse_match_datetime(value, naive_tz=None):
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    normalized = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None and naive_tz is not None:
        parsed = parsed.replace(tzinfo=naive_tz)
    if parsed.tzinfo is not None:
        return parsed.astimezone(KITCHEN_TIMEZONE).replace(tzinfo=None)
    return parsed


def kitchen_local_iso(value, naive_tz=None):
    parsed = parse_match_datetime(value, naive_tz=naive_tz)
    return parsed.isoformat(timespec="seconds") if parsed else value


def match_is_recent(match, cutoff):
    played_at = parse_match_datetime(match.get("playedAt"))
    if not played_at:
        return False
    return played_at >= cutoff


def api_football_key():
    return (
        os.environ.get("API_FOOTBALL_KEY")
        or os.environ.get("APISPORTS_KEY")
        or os.environ.get("API_SPORTS_KEY")
        or ""
    ).strip()


def api_football_league_id(league):
    env_key = f"API_FOOTBALL_{league['key'].upper().replace('-', '_')}_ID"
    return parse_optional_int(os.environ.get(env_key)) or league["api_football_id"]


def kitchen_competitions():
    return [source for source in KITCHEN_LEAGUES if source.get("type") == "competition"]


def kitchen_teams():
    return [source for source in KITCHEN_LEAGUES if source.get("type") == "team"]


def resolve_kitchen_competition(key):
    static = kitchen_league_by_key(key)
    if static:
        return dict(static)
    raw = str(key or "")
    if raw.startswith("tsdb-"):
        league_id = parse_optional_int(raw.replace("tsdb-", "", 1))
        if league_id:
            catalog = next(
                (item for item in read_thesportsdb_league_catalog() if item.get("key") == raw),
                None,
            )
            return {
                "key": raw,
                "name": (catalog or {}).get("name") or f"TheSportsDB {league_id}",
                "type": "competition",
                "sport": (catalog or {}).get("sport") or "Soccer",
                "thesportsdb_id": league_id,
            }
    return None


def selected_kitchen_competitions(settings):
    enabled = ((settings or {}).get("sports") or {}).get("enabledLeagueKeys") or []
    out = []
    for key in enabled:
        league = resolve_kitchen_competition(key)
        if league:
            out.append(league)
    return out


def selected_kitchen_teams(settings):
    enabled = set(((settings or {}).get("sports") or {}).get("enabledTeamKeys") or [])
    return [team for team in kitchen_teams() if team["key"] in enabled]


def selected_kitchen_next_teams(settings):
    enabled = set(((settings or {}).get("sports") or {}).get("enabledTeamKeys") or [])
    return [team for team in KITCHEN_NEXT_TEAMS if team["key"] in enabled]


def conifa_euro_2026_enabled(settings):
    enabled = set(((settings or {}).get("sports") or {}).get("enabledLeagueKeys") or [])
    return CONIFA_EURO_2026_KEY in enabled


def fetch_wikipedia_wikitext(page_title):
    params = urllib.parse.urlencode(
        {
            "action": "parse",
            "page": page_title,
            "prop": "wikitext",
            "format": "json",
            "formatversion": "2",
        }
    )
    payload = http_get_json(f"{WIKIPEDIA_API_URL}?{params}", headers={"User-Agent": WIKI_UA}, timeout=12)
    return ((payload.get("parse") or {}).get("wikitext") or "")


def extract_wiki_templates(wikitext, template_name):
    needle = "{{" + template_name
    templates = []
    start = 0
    while True:
        index = wikitext.find(needle, start)
        if index < 0:
            break
        depth = 0
        pos = index
        while pos < len(wikitext) - 1:
            pair = wikitext[pos:pos + 2]
            if pair == "{{":
                depth += 1
                pos += 2
                continue
            if pair == "}}":
                depth -= 1
                pos += 2
                if depth == 0:
                    templates.append(wikitext[index:pos])
                    break
                continue
            pos += 1
        start = pos
    return templates


def wiki_template_params(template):
    params = {}
    for line in str(template or "").splitlines():
        line = line.strip()
        if not line.startswith("|") or "=" not in line:
            continue
        key, value = line[1:].split("=", 1)
        params[key.strip()] = value.strip()
    return params


def wiki_team_name(value):
    text = str(value or "").strip()
    text = re.sub(r"\{\{fb(?:-[^|}]*)?\|([^|}]+)(?:\|[^}]*)?\}\}", r"\1", text, flags=re.I)
    text = re.sub(r"\{\{flagicon image\|[^}]+\}\}", "", text, flags=re.I)
    text = strip_wiki_markup(text)
    return text or "TBC"


def conifa_team_crest(team_name):
    normalized = re.sub(r"\s+", " ", normalize_lookup_text(team_name)).strip()
    return CONIFA_EURO_2026_TEAM_CRESTS.get(normalized, "")


def parse_wiki_score(params):
    score1 = parse_optional_int(params.get("score1"))
    score2 = parse_optional_int(params.get("score2"))
    if score1 is not None and score2 is not None:
        return score1, score2
    raw = str(params.get("score") or "").strip()
    match = re.search(r"(\d+)\s*(?:-|–|—|&ndash;)\s*(\d+)", raw)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def conifa_fixture_round(index):
    if index <= 3:
        return "Group A"
    if index <= 6:
        return "Group B"
    return {
        7: "5th-place match",
        8: "Third-place match",
        9: "Final",
    }.get(index, "Placement match")


def conifa_fixture_datetime(params):
    raw_date = strip_wiki_markup(params.get("date"))
    raw_time = strip_wiki_markup(params.get("time")) or "00:00"
    try:
        parsed = datetime.strptime(f"{raw_date} {raw_time}", "%d %B %Y %H:%M")
    except ValueError:
        return None
    return parsed.replace(tzinfo=KITCHEN_TIMEZONE)


def fetch_conifa_euro_2026_fixtures():
    source = kitchen_league_by_key(CONIFA_EURO_2026_KEY) or {
        "key": CONIFA_EURO_2026_KEY,
        "name": "CONIFA European Football Cup",
        "type": "competition",
        "sport": "Soccer",
    }
    wikitext = fetch_wikipedia_wikitext(CONIFA_EURO_2026_WIKI_PAGE)
    fixtures = []
    for index, template in enumerate(extract_wiki_templates(wikitext, "Football box"), 1):
        params = wiki_template_params(template)
        kickoff = conifa_fixture_datetime(params)
        if not kickoff:
            continue
        score = parse_wiki_score(params)
        home = wiki_team_name(params.get("team1"))
        away = wiki_team_name(params.get("team2"))
        round_name = strip_wiki_markup(params.get("round")) or conifa_fixture_round(index)
        fixture = {
            "id": f"wikipedia:{CONIFA_EURO_2026_KEY}:{kickoff.date().isoformat()}:{index}",
            "provider": "wikipedia",
            "leagueKey": source["key"],
            "leagueName": source["name"],
            "sourceType": "competition",
            "competitionName": "CONIFA European Football Cup 2026",
            "playedAt": kitchen_local_iso(kickoff.isoformat()),
            "kickoffAt": kitchen_local_iso(kickoff.isoformat()),
            "status": "FT" if score else "Scheduled",
            "round": round_name,
            "roundType": kitchen_round_type(source),
            "venue": strip_wiki_markup(params.get("stadium")),
            "location": strip_wiki_markup(params.get("location")),
            "home": {"name": home, "crest": conifa_team_crest(home)},
            "away": {"name": away, "crest": conifa_team_crest(away)},
        }
        if score:
            fixture["score"] = {"home": score[0], "away": score[1]}
        fixtures.append(fixture)
    fixtures.sort(key=lambda item: parse_match_datetime(item.get("kickoffAt")) or datetime.max)
    return fixtures


def fetch_conifa_euro_2026_scores(cutoff, now=None, settings=None):
    if not conifa_euro_2026_enabled(settings or read_kitchen_settings()):
        return []
    now = now or datetime.now().replace(microsecond=0)
    matches = []
    for fixture in fetch_conifa_euro_2026_fixtures():
        if not fixture.get("score"):
            continue
        played_at = parse_match_datetime(fixture.get("playedAt"))
        if played_at and cutoff <= played_at <= now:
            item = dict(fixture)
            item.pop("kickoffAt", None)
            matches.append(item)
    return matches


def fetch_conifa_euro_2026_next_matches(now=None, settings=None):
    if not conifa_euro_2026_enabled(settings or read_kitchen_settings()):
        return []
    now = now or datetime.now().replace(microsecond=0)
    end = now + timedelta(hours=CONIFA_EURO_2026_NEXT_WINDOW_HOURS)
    matches = []
    for fixture in fetch_conifa_euro_2026_fixtures():
        kickoff = parse_match_datetime(fixture.get("kickoffAt"))
        if not kickoff or kickoff < now or kickoff > end or fixture.get("score"):
            continue
        matches.append(
            {
                "id": fixture["id"].replace("wikipedia:", "wikipedia-next:", 1),
                "provider": fixture["provider"],
                "teamKey": CONIFA_EURO_2026_KEY,
                "teamName": "CONIFA European Football Cup 2026",
                "competitionName": fixture["competitionName"],
                "kickoffAt": fixture["kickoffAt"],
                "round": fixture.get("round"),
                "roundType": fixture.get("roundType"),
                "venue": fixture.get("venue") or "",
                "location": fixture.get("location") or "",
                "home": fixture["home"],
                "away": fixture["away"],
            }
        )
    matches.sort(key=lambda item: parse_match_datetime(item.get("kickoffAt")) or datetime.max)
    return matches


def normalize_api_football_fixture(item, league):
    fixture = item.get("fixture") or {}
    status = fixture.get("status") or {}
    league_payload = item.get("league") or {}
    teams = item.get("teams") or {}
    home = teams.get("home") or {}
    away = teams.get("away") or {}
    goals = item.get("goals") or {}
    score_home = goals.get("home")
    score_away = goals.get("away")
    if score_home is None or score_away is None:
        return None
    status_short = str(status.get("short") or "").upper()
    if status_short not in {"FT", "AET", "PEN"}:
        return None

    match = {
        "id": f"api-football:{fixture.get('id')}",
        "provider": "api-football",
        "leagueKey": league["key"],
        "leagueName": league["name"],
        "sourceType": league.get("type") or "competition",
        "competitionName": league_payload.get("name") or league["name"],
        "playedAt": kitchen_local_iso(fixture.get("date")),
        "status": status.get("short") or status.get("long") or "FT",
        "round": kitchen_round_value(league_payload.get("round"), league),
        "roundType": kitchen_match_round_type(league, league_payload.get("round"), league_payload.get("name")),
        "home": {
            "name": home.get("name") or "Gospodarze",
            "crest": home.get("logo") or "",
        },
        "away": {
            "name": away.get("name") or "Goście",
            "crest": away.get("logo") or "",
        },
        "score": {
            "home": score_home,
            "away": score_away,
        },
    }
    return add_kitchen_match_metadata(
        match,
        league,
        league_payload.get("round"),
        league_payload.get("name"),
        league_payload.get("type"),
    )


def fetch_api_football_scores(cutoff, now, settings=None):
    key = api_football_key()
    if not key:
        return []

    season = current_football_season(now.date())
    from_day = cutoff.date().isoformat()
    to_day = now.date().isoformat()
    headers = {"x-apisports-key": key}
    matches = []

    for league in selected_kitchen_competitions(settings or read_kitchen_settings()):
        if not league.get("api_football_id"):
            continue
        params = urllib.parse.urlencode(
            {
                "league": api_football_league_id(league),
                "season": season,
                "from": from_day,
                "to": to_day,
            }
        )
        payload = http_get_json(f"{API_FOOTBALL_BASE}/fixtures?{params}", headers=headers, timeout=14)
        for item in payload.get("response") or []:
            match = normalize_api_football_fixture(item, league)
            if match and match_is_recent(match, cutoff):
                matches.append(match)

    return matches


def normalize_thesportsdb_event(item, source):
    score_home = parse_optional_int(item.get("intHomeScore"))
    score_away = parse_optional_int(item.get("intAwayScore"))
    if score_home is None or score_away is None:
        return None
    status = str(item.get("strStatus") or "").strip().lower()
    if status and status not in {"match finished", "finished", "ft", "full time", "after extra time", "penalties"}:
        return None

    played_at = item.get("strTimestamp") or f"{item.get('dateEvent', '')}T{item.get('strTime', '00:00:00')}"
    round_value = item.get("strRound") or item.get("strGroup") or item.get("intRound")
    match = {
        "id": f"thesportsdb:{item.get('idEvent')}",
        "provider": "thesportsdb",
        "leagueKey": source["key"],
        "leagueName": source["name"],
        "sourceType": source.get("type") or "competition",
        "competitionName": item.get("strLeague") or source["name"],
        "playedAt": kitchen_local_iso(played_at, naive_tz=timezone.utc),
        "status": "FT",
        "round": kitchen_round_value(round_value, source),
        "roundType": kitchen_match_round_type(
            source,
            round_value,
            item.get("strEvent"),
            item.get("strFilename"),
        ),
        "home": {
            "name": item.get("strHomeTeam") or "Gospodarze",
            "crest": item.get("strHomeTeamBadge") or "",
        },
        "away": {
            "name": item.get("strAwayTeam") or "Goście",
            "crest": item.get("strAwayTeamBadge") or "",
        },
        "score": {
            "home": score_home,
            "away": score_away,
        },
    }
    return add_kitchen_match_metadata(
        match,
        source,
        round_value,
        item.get("strGroup"),
        item.get("strEvent"),
        item.get("strFilename"),
        item.get("strLeague"),
    )


def normalize_thesportsdb_live_event(item, source):
    score_home = parse_optional_int(item.get("intHomeScore"))
    score_away = parse_optional_int(item.get("intAwayScore"))
    if score_home is None or score_away is None:
        return None
    status = str(item.get("strStatus") or item.get("strProgress") or "").strip()
    status_key = status.lower()
    if not status_key or status_key in {"not started", "ns"} or kitchen_live_status_is_terminal(status):
        return None

    played_at = item.get("strTimestamp") or f"{item.get('dateEvent', '')}T{item.get('strTime', '00:00:00')}"
    played_at_iso = kitchen_local_iso(played_at, naive_tz=timezone.utc)
    round_value = item.get("strRound") or item.get("strGroup") or item.get("intRound")
    match = {
        "id": f"thesportsdb-live:{item.get('idEvent')}",
        "eventId": str(item.get("idEvent") or ""),
        "provider": "thesportsdb",
        "leagueKey": source["key"],
        "leagueName": source["name"],
        "sourceType": source.get("type") or "competition",
        "competitionName": item.get("strLeague") or source["name"],
        "playedAt": played_at_iso,
        "status": status or "LIVE",
        "statusText": status or "Live",
        "clock": str(item.get("strProgress") or status or "").strip(),
        "round": kitchen_round_value(round_value, source),
        "roundType": kitchen_match_round_type(
            source,
            round_value,
            item.get("strEvent"),
            item.get("strFilename"),
        ),
        "home": {
            "name": item.get("strHomeTeam") or "Gospodarze",
            "crest": item.get("strHomeTeamBadge") or "",
        },
        "away": {
            "name": item.get("strAwayTeam") or "Goście",
            "crest": item.get("strAwayTeamBadge") or "",
        },
        "score": {
            "home": score_home,
            "away": score_away,
        },
        "details": [],
    }
    if kitchen_live_match_is_stale(match):
        return None
    return add_kitchen_match_metadata(
        match,
        source,
        round_value,
        item.get("strGroup"),
        item.get("strEvent"),
        item.get("strFilename"),
        item.get("strLeague"),
    )


def fetch_thesportsdb_live_scores(now=None, settings=None):
    now = now or datetime.now().replace(microsecond=0)
    settings = settings or read_kitchen_settings()
    matches = []
    source_by_league_id = {
        str(source.get("thesportsdb_id")): source
        for source in selected_kitchen_competitions(settings)
        if source.get("thesportsdb_id")
    }
    sports = sorted({source.get("sport") or "Soccer" for source in selected_kitchen_competitions(settings)})
    day = now.date().isoformat()
    for sport in sports:
        params = urllib.parse.urlencode({"d": day, "s": sport})
        payload = http_get_json(f"{THESPORTSDB_API_BASE}/eventsday.php?{params}", timeout=12)
        for item in payload.get("events") or []:
            source = source_by_league_id.get(str(item.get("idLeague") or ""))
            if not source:
                continue
            match = normalize_thesportsdb_live_event(item, source)
            if match:
                matches.append(match)
    return dedupe_matches(matches)


def normalize_espn_event(item, source):
    competitions = item.get("competitions") or []
    competition = competitions[0] if competitions else {}
    competitors = competition.get("competitors") or []
    if len(competitors) < 2:
        return None

    by_side = {entry.get("homeAway"): entry for entry in competitors}
    home = by_side.get("home") or competitors[0]
    away = by_side.get("away") or competitors[1]

    def team_payload(entry):
        team = entry.get("team") or {}
        return {
            "name": team.get("displayName") or team.get("name") or "Team",
            "crest": team.get("logo") or "",
        }

    score_home = parse_optional_int(home.get("score"))
    score_away = parse_optional_int(away.get("score"))
    if score_home is None or score_away is None:
        return None

    league = (item.get("league") or {}) or ((item.get("leagues") or [{}])[0] if item.get("leagues") else {})
    season = item.get("season") or {}
    status = competition.get("status") or item.get("status") or {}
    status_type = status.get("type") or {}
    if not bool(status_type.get("completed")):
        return None

    match = {
        "id": f"espn:{item.get('id')}",
        "eventId": str(item.get("id") or ""),
        "provider": "espn",
        "leagueKey": source["key"],
        "leagueName": source["name"],
        "sourceType": source.get("type") or "competition",
        "competitionName": league.get("name") or source.get("competitionName") or source["name"],
        "playedAt": kitchen_local_iso(item.get("date")),
        "status": status_type.get("description") or status_type.get("shortDetail") or "FT",
        "round": kitchen_round_value(None, source),
        "roundType": kitchen_match_round_type(
            source,
            season.get("slug"),
            season.get("type"),
            league.get("name"),
        ),
        "home": team_payload(home),
        "away": team_payload(away),
        "score": {
            "home": score_home,
            "away": score_away,
        },
    }
    return add_kitchen_match_metadata(
        match,
        source,
        competition.get("altGameNote"),
        season.get("slug"),
        season.get("type"),
        league.get("name"),
    )


def espn_event_is_live(item):
    competitions = item.get("competitions") or []
    competition = competitions[0] if competitions else {}
    status = competition.get("status") or item.get("status") or {}
    status_type = status.get("type") or {}
    state = str(status_type.get("state") or "").lower()
    return state == "in" and not bool(status_type.get("completed"))


def normalize_espn_live_event(item, source):
    competitions = item.get("competitions") or []
    competition = competitions[0] if competitions else {}
    competitors = competition.get("competitors") or []
    if len(competitors) < 2:
        return None

    by_side = {entry.get("homeAway"): entry for entry in competitors}
    home = by_side.get("home") or competitors[0]
    away = by_side.get("away") or competitors[1]

    def team_payload(entry):
        team = entry.get("team") or {}
        return {
            "name": team.get("displayName") or team.get("name") or "Team",
            "crest": team.get("logo") or "",
        }

    score_home = parse_optional_int(home.get("score"))
    score_away = parse_optional_int(away.get("score"))
    if score_home is None or score_away is None:
        return None

    status = competition.get("status") or item.get("status") or {}
    status_type = status.get("type") or {}
    if not espn_event_is_live(item):
        return None

    league = (item.get("league") or {}) or ((item.get("leagues") or [{}])[0] if item.get("leagues") else {})
    season = item.get("season") or {}
    match = {
        "id": f"espn-live:{item.get('id')}",
        "eventId": str(item.get("id") or ""),
        "provider": "espn",
        "leagueKey": source["key"],
        "leagueName": source["name"],
        "sourceType": source.get("type") or "competition",
        "competitionName": league.get("name") or source.get("competitionName") or source["name"],
        "playedAt": kitchen_local_iso(item.get("date")),
        "status": status_type.get("shortDetail") or status_type.get("detail") or status_type.get("description") or "LIVE",
        "statusText": status_type.get("detail") or status_type.get("description") or "Live",
        "clock": status.get("displayClock") or status_type.get("shortDetail") or "",
        "round": kitchen_round_value(None, source),
        "roundType": kitchen_match_round_type(
            source,
            season.get("slug"),
            season.get("type"),
            league.get("name"),
        ),
        "home": team_payload(home),
        "away": team_payload(away),
        "score": {
            "home": score_home,
            "away": score_away,
        },
    }
    return add_kitchen_match_metadata(
        match,
        source,
        competition.get("altGameNote"),
        season.get("slug"),
        season.get("type"),
        league.get("name"),
    )


def normalize_espn_key_event(item):
    event_type = (item.get("type") or {})
    raw_kind = str(event_type.get("type") or event_type.get("text") or "").lower()
    if bool(item.get("scoringPlay")) or "goal" in raw_kind or "scored" in raw_kind:
        kind = "goal"
    elif "red-card" in raw_kind or raw_kind == "red card":
        kind = "red-card"
    elif "yellow-card" in raw_kind or raw_kind == "yellow card":
        kind = "yellow-card"
    else:
        return None
    raw_text = item.get("shortText") or item.get("text") or ""
    text = str(raw_text or "").strip()
    tag = ""
    lower_text = text.lower()
    if kind == "goal":
        if "penalty" in lower_text:
            tag = "karny"
        elif "free kick" in lower_text or "free-kick" in lower_text:
            tag = "rzut wolny"
        text = re.sub(r"\bGoal\b\s*[-–]?\s*", "", text, flags=re.I)
        text = re.sub(
            r"\s*[-–]\s*(Header|Volley|Left Footed Shot|Right Footed Shot|Shot).*?$",
            "",
            text,
            flags=re.I,
        )
    elif kind == "yellow-card":
        text = re.sub(r"\bYellow Card\b\s*[-–]?\s*", "", text, flags=re.I)
    elif kind == "red-card":
        text = re.sub(r"\bRed Card\b\s*[-–]?\s*", "", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip(" -–")
    return {
        "kind": kind,
        "label": event_type.get("text") or kind,
        "minute": ((item.get("clock") or {}).get("displayValue") or "").strip(),
        "team": ((item.get("team") or {}).get("displayName") or "").strip(),
        "text": text,
        "tag": tag,
    }


def fetch_espn_match_details(match, source):
    event_id = match.get("eventId")
    if not event_id or not source.get("espn_sport") or not source.get("espn_league"):
        return []
    url = f"{ESPN_SCOREBOARD_BASE}/{source['espn_sport']}/{source['espn_league']}/summary?event={urllib.parse.quote(event_id)}"
    payload = http_get_json(url, timeout=12)
    details = []
    for item in payload.get("keyEvents") or []:
        detail = normalize_espn_key_event(item)
        if detail:
            details.append(detail)
    return details[-8:]


def fetch_espn_live_scores(now=None, settings=None):
    now = now or datetime.now().replace(microsecond=0)
    settings = settings or read_kitchen_settings()
    matches = []
    sources = selected_kitchen_competitions(settings) + selected_kitchen_teams(settings)
    for source in sources:
        if not source.get("espn_sport") or not source.get("espn_league"):
            continue
        names = {normalize_lookup_text(name) for name in source.get("espn_team_names") or []}
        if source.get("type") == "team" and not names:
            names = {normalize_lookup_text(source["name"])}
        day = now.date().isoformat().replace("-", "")
        params = urllib.parse.urlencode({"dates": day})
        url = f"{ESPN_SCOREBOARD_BASE}/{source['espn_sport']}/{source['espn_league']}/scoreboard?{params}"
        payload = http_get_json(url, timeout=12)
        for item in payload.get("events") or []:
            match = normalize_espn_live_event(item, source)
            if not match:
                continue
            if names:
                team_names = {
                    normalize_lookup_text((match.get("home") or {}).get("name")),
                    normalize_lookup_text((match.get("away") or {}).get("name")),
                }
                if not (team_names & names):
                    continue
            try:
                match["details"] = fetch_espn_match_details(match, source)
            except Exception:
                match["details"] = []
            matches.append(match)
    return dedupe_matches(matches)


def espn_days(cutoff, now):
    days = []
    current = cutoff.date()
    end = now.date()
    while current <= end:
        days.append(current.isoformat().replace("-", ""))
        current += timedelta(days=1)
    return days


def fetch_espn_team_scores(cutoff, now=None, settings=None):
    now = now or datetime.now().replace(microsecond=0)
    matches = []
    for source in selected_kitchen_teams(settings or read_kitchen_settings()):
        if not source.get("espn_sport") or not source.get("espn_league"):
            continue
        names = {normalize_lookup_text(name) for name in source.get("espn_team_names") or []}
        if not names:
            names = {normalize_lookup_text(source["name"])}
        for day in espn_days(cutoff, now):
            params = urllib.parse.urlencode({"dates": day})
            url = f"{ESPN_SCOREBOARD_BASE}/{source['espn_sport']}/{source['espn_league']}/scoreboard?{params}"
            payload = http_get_json(url, timeout=12)
            for item in payload.get("events") or []:
                match = normalize_espn_event(item, source)
                if not match or not match_is_recent(match, cutoff):
                    continue
                team_names = {
                    normalize_lookup_text((match.get("home") or {}).get("name")),
                    normalize_lookup_text((match.get("away") or {}).get("name")),
                }
                if team_names & names:
                    matches.append(match)
    return matches


def fetch_espn_competition_scores(cutoff, now=None, settings=None):
    now = now or datetime.now().replace(microsecond=0)
    matches = []
    for source in selected_kitchen_competitions(settings or read_kitchen_settings()):
        if not source.get("espn_sport") or not source.get("espn_league"):
            continue
        for day in espn_days(cutoff, now):
            params = urllib.parse.urlencode({"dates": day})
            url = f"{ESPN_SCOREBOARD_BASE}/{source['espn_sport']}/{source['espn_league']}/scoreboard?{params}"
            payload = http_get_json(url, timeout=12)
            for item in payload.get("events") or []:
                match = normalize_espn_event(item, source)
                if not match or not match_is_recent(match, cutoff):
                    continue
                if source.get("sport") == "Soccer":
                    try:
                        match["details"] = fetch_espn_match_details(match, source)
                    except Exception:
                        match["details"] = []
                matches.append(match)
    return matches


def fetch_thesportsdb_scores(cutoff, now=None, settings=None):
    now = now or datetime.now().replace(microsecond=0)
    settings = settings or read_kitchen_settings()
    matches = []
    errors = []
    rate_limited = False
    bulk_success = False
    source_by_league_id = {
        str(source.get("thesportsdb_id")): source
        for source in selected_kitchen_competitions(settings)
        if source.get("thesportsdb_id")
    }
    sports = sorted({source.get("sport") or "Soccer" for source in selected_kitchen_competitions(settings)})
    days = []
    current_day = cutoff.date()
    while current_day <= now.date():
        days.append(current_day.isoformat())
        current_day += timedelta(days=1)

    for sport in sports:
        for day in days:
            try:
                params = urllib.parse.urlencode({"d": day, "s": sport})
                payload = http_get_json(f"{THESPORTSDB_API_BASE}/eventsday.php?{params}", timeout=12)
                bulk_success = True
                for item in payload.get("events") or []:
                    source = source_by_league_id.get(str(item.get("idLeague") or ""))
                    if not source:
                        continue
                    match = normalize_thesportsdb_event(item, source)
                    if match and match_is_recent(match, cutoff):
                        matches.append(match)
            except Exception as exc:
                errors.append(f"{sport} {day}: {exc}")
                if isinstance(exc, urllib.error.HTTPError) and exc.code == 429:
                    rate_limited = True

    # Fallback for sparse sports where eventsday may omit a league on quiet days.
    if not rate_limited and not bulk_success:
        for league in selected_kitchen_competitions(settings):
            if any(match.get("leagueKey") == league["key"] for match in matches):
                continue
            if not league.get("thesportsdb_id"):
                continue
            try:
                url = f"{THESPORTSDB_API_BASE}/eventspastleague.php?id={league['thesportsdb_id']}"
                payload = http_get_json(url, timeout=12)
                recent_events = payload.get("events") or []
                for item in recent_events:
                    match = normalize_thesportsdb_event(item, league)
                    if match and match_is_recent(match, cutoff):
                        matches.append(match)
            except Exception as exc:
                errors.append(f"{league['key']}: {exc}")
    if not rate_limited:
        matches.extend(fetch_thesportsdb_team_scores(cutoff, errors=errors, settings=settings))
    try:
        matches.extend(fetch_espn_team_scores(cutoff, now=now, settings=settings))
    except Exception as exc:
        errors.append(f"espn: {exc}")
    if errors and not matches:
        raise RuntimeError("; ".join(errors))
    return matches


def fetch_supplemental_kitchen_scores(cutoff, settings=None):
    settings = settings or read_kitchen_settings()
    selected_keys = {league["key"] for league in selected_kitchen_competitions(settings)}
    matches = []
    for match in KITCHEN_SUPPLEMENTAL_MATCHES:
        if selected_keys and match.get("leagueKey") not in selected_keys:
            continue
        if match_is_recent(match, cutoff):
            matches.append(dict(match))
    return matches


def fetch_thesportsdb_team_scores(cutoff, errors=None, settings=None):
    matches = []
    errors = errors if errors is not None else []
    for team in selected_kitchen_teams(settings or read_kitchen_settings()):
        if not team.get("thesportsdb_team_id"):
            continue
        try:
            url = f"{THESPORTSDB_API_BASE}/eventslast.php?id={team['thesportsdb_team_id']}"
            payload = http_get_json(url, timeout=12)
            for item in payload.get("results") or []:
                match = normalize_thesportsdb_event(item, team)
                if match and match_is_recent(match, cutoff):
                    matches.append(match)
                    break
        except Exception as exc:
            errors.append(f"{team['key']}: {exc}")
    return matches


def kitchen_league_by_key(key):
    return next((league for league in KITCHEN_LEAGUES if league.get("key") == key), None)


def world_cup_group_name(*values):
    for value in values:
        match = WORLD_CUP_GROUP_RE.search(str(value or ""))
        if match:
            return f"Group {match.group(1).upper()}"
    return ""


def world_cup_group_label(value):
    group = world_cup_group_name(value)
    if not group:
        return ""
    return f"Grupa {group.rsplit(' ', 1)[-1]}"


def world_cup_stage_label(*values):
    group_label = world_cup_group_label(" ".join(str(value or "") for value in values))
    if group_label:
        return group_label
    text = normalize_lookup_text(" ".join(str(value or "") for value in values if value))
    labels = [
        (("round of 32", "rd of 32"), "1/16 fina\u0142u"),
        (("round of 16", "rd of 16"), "1/8 fina\u0142u"),
        (("quarterfinal", "quarter final", "quarter-finals", "quarter-finals"), "\u0107wier\u0107fina\u0142"),
        (("semifinal", "semi final", "semi-finals", "semifinals"), "p\u00f3\u0142fina\u0142"),
        (("3rd place", "third place"), "mecz o 3. miejsce"),
        (("final",), "fina\u0142"),
        (("group stage", "group-stage", "group"), "faza grupowa"),
    ]
    for needles, label in labels:
        if any(needle in text for needle in needles):
            return label
    return ""


def world_cup_match_metadata(*values):
    group = world_cup_group_name(*values)
    return {
        "group": group,
        "groupLabel": world_cup_group_label(group),
        "stageLabel": world_cup_stage_label(*values),
    }


def add_world_cup_metadata(match, *values):
    if not match or (match.get("leagueKey") or match.get("teamKey")) != "world-cup":
        return match
    metadata = world_cup_match_metadata(*values)
    for key, value in metadata.items():
        if value:
            match[key] = value
    if match.get("groupLabel"):
        match["round"] = match["groupLabel"]
        match["roundType"] = "league"
    elif match.get("stageLabel"):
        match["round"] = match["stageLabel"]
        match["roundType"] = "cup"
    return match


def parse_kitchen_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except Exception:
        return None


def match_local_date(match):
    parsed = parse_match_datetime((match or {}).get("kickoffAt") or (match or {}).get("playedAt"))
    if parsed:
        return parsed.date()
    return parse_kitchen_date((match or {}).get("kickoffAt") or (match or {}).get("playedAt"))


def uefa_stage_metadata(match, source):
    key = (source or {}).get("key") or (match or {}).get("leagueKey") or (match or {}).get("teamKey")
    windows = KITCHEN_UEFA_STAGE_WINDOWS.get(key) or []
    match_day = match_local_date(match)
    if not match_day:
        return {}
    for window in windows:
        start = parse_kitchen_date(window.get("start"))
        end = parse_kitchen_date(window.get("end")) or start
        if start and end and start <= match_day <= end:
            stage = window.get("stage") or ""
            leg = window.get("leg") or ""
            return {
                "stageLabel": stage,
                "legLabel": leg,
                "round": " - ".join(part for part in [stage, leg] if part),
                "roundType": "cup",
            }
    return {}


def add_kitchen_match_metadata(match, source=None, *values):
    if not match:
        return match
    for key, value in uefa_stage_metadata(match, source).items():
        if value:
            match[key] = value
    return add_world_cup_metadata(match, *values)


def two_leg_team_key(team):
    return normalize_lookup_text((team or {}).get("name") or "")


def two_leg_pair_key(match):
    teams = sorted([
        two_leg_team_key((match or {}).get("home")),
        two_leg_team_key((match or {}).get("away")),
    ])
    if len(teams) != 2 or not teams[0] or not teams[1]:
        return None
    return (
        (match or {}).get("leagueKey") or (match or {}).get("teamKey") or "",
        (match or {}).get("stageLabel") or (match or {}).get("round") or "",
        "|".join(teams),
    )


def match_score_text(match):
    score = (match or {}).get("score") or {}
    home = score.get("home")
    away = score.get("away")
    if home is None or away is None:
        return ""
    return f"{home}:{away}"


def team_score_from_match(match, team_name):
    target = two_leg_team_key({"name": team_name})
    score = (match or {}).get("score") or {}
    if target and target == two_leg_team_key((match or {}).get("home")):
        return parse_optional_int(score.get("home"))
    if target and target == two_leg_team_key((match or {}).get("away")):
        return parse_optional_int(score.get("away"))
    return None


def enrich_kitchen_two_leg_matches(matches):
    items = [dict(match) for match in (matches or []) if match]
    groups = {}
    for match in items:
        if (match.get("leagueKey") or match.get("teamKey")) not in KITCHEN_UEFA_QUALIFIER_KEYS:
            continue
        key = two_leg_pair_key(match)
        if key:
            groups.setdefault(key, []).append(match)
    for group in groups.values():
        group.sort(key=lambda item: parse_match_datetime(item.get("playedAt") or item.get("kickoffAt")) or datetime.max)
        if len(group) < 2:
            continue
        first = group[0]
        first_score = match_score_text(first)
        if not first.get("legLabel"):
            first["legLabel"] = "1. mecz"
        for match in group[1:]:
            match.setdefault("legLabel", "rewanz")
            if not first_score:
                continue
            match["firstLeg"] = {
                "home": (first.get("home") or {}).get("name") or "",
                "away": (first.get("away") or {}).get("name") or "",
                "score": first_score,
            }
            match["firstLegLabel"] = f"1. mecz: {(first.get('home') or {}).get('name') or ''} {first_score} {(first.get('away') or {}).get('name') or ''}".strip()
            current_score = match_score_text(match)
            if current_score:
                home_name = (match.get("home") or {}).get("name") or ""
                away_name = (match.get("away") or {}).get("name") or ""
                home_total = team_score_from_match(first, home_name)
                away_total = team_score_from_match(first, away_name)
                home_now = parse_optional_int((match.get("score") or {}).get("home"))
                away_now = parse_optional_int((match.get("score") or {}).get("away"))
                if None not in {home_total, away_total, home_now, away_now}:
                    match["aggregateLabel"] = f"dwumecz: {home_total + home_now}:{away_total + away_now}"
    return items


def world_cup_enabled(settings):
    enabled = set(((settings or {}).get("sports") or {}).get("enabledLeagueKeys") or [])
    return "world-cup" in enabled


def espn_leader_stat_value(leader, *names):
    value = leader.get("value")
    if isinstance(value, (int, float)):
        return int(value) if float(value).is_integer() else value
    return parse_optional_int(stat_display(((leader.get("athlete") or {}).get("statistics") or []), *names)) or 0


def normalize_espn_leader(leader, stat_names):
    athlete = leader.get("athlete") or {}
    team = athlete.get("team") or {}
    value = espn_leader_stat_value(leader, *stat_names)
    return {
        "name": athlete.get("shortName") or athlete.get("displayName") or "Player",
        "fullName": athlete.get("displayName") or athlete.get("shortName") or "Player",
        "teamName": team.get("displayName") or team.get("name") or "",
        "teamCrest": logo_from_espn_team(team),
        "value": value,
    }


def fetch_world_cup_leaderboards(settings=None):
    if not world_cup_enabled(settings or read_kitchen_settings()):
        return {}
    now = datetime.now().replace(microsecond=0)
    start = parse_match_datetime(FIFA_WORLD_CUP_2026.get("kickoffAt")) or now
    source = kitchen_league_by_key("world-cup") or {
        "key": "world-cup",
        "name": "FIFA World Cup",
        "type": "competition",
        "sport": "Soccer",
        "espn_sport": "soccer",
        "espn_league": "fifa.world",
    }
    goals = {}
    assists = {}

    def add_stat(bucket, athlete, team):
        if not athlete:
            return
        name = athlete.get("shortName") or athlete.get("displayName") or athlete.get("fullName")
        full_name = athlete.get("displayName") or athlete.get("fullName") or name
        if not name and not full_name:
            return
        key = str(athlete.get("id") or normalize_lookup_text(full_name or name))
        current = bucket.setdefault(key, {
            "name": name or full_name,
            "fullName": full_name or name,
            "teamName": team.get("displayName") or team.get("name") or "",
            "teamCrest": team.get("logo") or logo_from_espn_team(team),
            "value": 0,
        })
        current["value"] += 1
        if not current.get("teamCrest") and (team.get("logo") or logo_from_espn_team(team)):
            current["teamCrest"] = team.get("logo") or logo_from_espn_team(team)

    def team_map_for_event(item):
        competition = (item.get("competitions") or [{}])[0] or {}
        out = {}
        for entry in competition.get("competitors") or []:
            team = entry.get("team") or {}
            team_id = str(team.get("id") or "")
            if team_id:
                out[team_id] = team
        return out

    for day in espn_days(start, now):
        params = urllib.parse.urlencode({"dates": day})
        payload = http_get_json(f"{ESPN_SCOREBOARD_BASE}/soccer/fifa.world/scoreboard?{params}", timeout=12)
        for event in payload.get("events") or []:
            match = normalize_espn_event(event, source)
            if not match:
                continue
            team_by_id = team_map_for_event(event)
            event_id = str(event.get("id") or "")
            if not event_id:
                continue
            try:
                summary = http_get_json(
                    f"{ESPN_SCOREBOARD_BASE}/soccer/fifa.world/summary?event={urllib.parse.quote(event_id)}",
                    timeout=12,
                )
            except Exception:
                continue
            for item in summary.get("keyEvents") or []:
                event_type = item.get("type") or {}
                kind_text = " ".join([
                    str(event_type.get("type") or ""),
                    str(event_type.get("text") or ""),
                    str(item.get("text") or ""),
                    str(item.get("shortText") or ""),
                ]).lower()
                if not (item.get("scoringPlay") or "goal" in kind_text or "scored" in kind_text):
                    continue
                if item.get("shootout") or item.get("ownGoal") or "own goal" in kind_text:
                    continue
                participants = [
                    participant.get("athlete") or {}
                    for participant in item.get("participants") or []
                    if participant.get("athlete")
                ]
                team = team_by_id.get(str((item.get("team") or {}).get("id") or "")) or item.get("team") or {}
                add_stat(goals, participants[0] if participants else {}, team)
                if "assisted by" in kind_text and len(participants) > 1:
                    add_stat(assists, participants[1], team)

    def ranked(bucket):
        leaders = [item for item in bucket.values() if parse_optional_int(item.get("value"))]
        leaders.sort(key=lambda leader: (-parse_optional_int(leader.get("value")), leader.get("name") or ""))
        for index, leader in enumerate(leaders, 1):
            leader["rank"] = index
        return leaders[:5]

    return {
        "leagueKey": "world-cup",
        "leagueName": "FIFA World Cup",
        "goals": ranked(goals),
        "assists": ranked(assists),
    }


def stat_display(stats, *names):
    for name in names:
        normalized_name = normalize_lookup_text(name)
        if not normalized_name:
            continue
        for stat in stats or []:
            keys = {
                normalize_lookup_text(stat.get("name")),
                normalize_lookup_text(stat.get("type")),
                normalize_lookup_text(stat.get("abbreviation")),
                normalize_lookup_text(stat.get("shortDisplayName")),
            }
            if normalized_name in keys:
                value = stat.get("displayValue")
                if value not in {None, ""}:
                    return str(value)
                raw_value = stat.get("value")
                if isinstance(raw_value, float) and raw_value.is_integer():
                    return str(int(raw_value))
                if raw_value is not None:
                    return str(raw_value)
    return ""


def stat_number(stats, *names):
    value = stat_display(stats, *names)
    try:
        return float(str(value).replace("+", ""))
    except (TypeError, ValueError):
        return 0.0


def logo_from_espn_team(team):
    logos = team.get("logos") or []
    if logos and isinstance(logos[0], dict):
        return logos[0].get("href") or ""
    return team.get("logo") or ""


def normalize_espn_standing_entry(entry, league, rank=None):
    team = entry.get("team") or {}
    stats = entry.get("stats") or []
    note = entry.get("note") or {}
    actual_rank = stat_display(stats, "rank", "playoffSeed") or rank
    record = stat_display(stats, "overall", "total")
    if "," in record:
        record = record.split(",", 1)[0].strip()
    if not record:
        wins = stat_display(stats, "wins")
        draws = stat_display(stats, "ties", "draws")
        losses = stat_display(stats, "losses")
        record = "-".join(part for part in [wins, draws, losses] if part != "")
    return {
        "rank": parse_optional_int(actual_rank) or rank,
        "name": team.get("displayName") or team.get("name") or "Team",
        "shortName": team.get("shortDisplayName") or team.get("abbreviation") or "",
        "crest": logo_from_espn_team(team),
        "played": stat_display(stats, "gamesPlayed"),
        "wins": stat_display(stats, "wins"),
        "draws": stat_display(stats, "ties", "draws"),
        "losses": stat_display(stats, "losses"),
        "goalsFor": stat_display(stats, "pointsFor", "goalsFor", "for"),
        "goalsAgainst": stat_display(stats, "pointsAgainst", "goalsAgainst", "against"),
        "gd": stat_display(stats, "pointDifferential", "pointsDiff", "differential"),
        "points": stat_display(stats, "points"),
        "record": record,
        "zoneLabel": standing_zone_label(note.get("description")),
        "_pointsSort": stat_number(stats, "points"),
        "_winsSort": stat_number(stats, "wins"),
        "_gdSort": stat_number(stats, "pointDifferential", "pointsDiff", "differential"),
        "_leagueKey": league["key"],
    }


def fetch_espn_standings(league):
    standing = league.get("standing") or {}
    url = (
        f"{ESPN_WEB_BASE}/{standing['sport']}/{standing['league']}/standings"
        "?region=us&lang=en"
    )
    payload = http_get_json(url, timeout=14)
    entries = []
    for child in payload.get("children") or []:
        standings = child.get("standings") or {}
        entries.extend(standings.get("entries") or [])
    if not entries:
        entries = ((payload.get("standings") or {}).get("entries") or [])

    seen = set()
    rows = []
    for entry in entries:
        team_id = ((entry.get("team") or {}).get("id") or (entry.get("team") or {}).get("uid"))
        if team_id and team_id in seen:
            continue
        if team_id:
            seen.add(team_id)
        rows.append(normalize_espn_standing_entry(entry, league, rank=len(rows) + 1))

    if standing.get("sport") == "hockey":
        rows.sort(key=lambda row: (-row["_pointsSort"], -row["_winsSort"], -row["_gdSort"], row["name"]))
        for index, row in enumerate(rows, 1):
            row["rank"] = index
    else:
        rows.sort(key=lambda row: row.get("rank") or 999)

    for row in rows:
        row.pop("_pointsSort", None)
        row.pop("_winsSort", None)
        row.pop("_gdSort", None)
        row.pop("_leagueKey", None)
    return rows


def fetch_world_cup_group_standings(league):
    url = f"{ESPN_WEB_BASE}/soccer/fifa.world/standings?region=us&lang=en"
    payload = http_get_json(url, timeout=14)
    standings = {}
    for child in payload.get("children") or []:
        group = world_cup_group_name(child.get("name"), child.get("abbreviation"))
        entries = ((child.get("standings") or {}).get("entries") or [])
        if not group or not entries:
            continue
        rows = [
            normalize_espn_standing_entry(entry, league, rank=index)
            for index, entry in enumerate(entries, 1)
        ]
        rows.sort(key=lambda row: row.get("rank") or 999)
        rows = enrich_standing_zones(rows)
        for row in rows:
            row.pop("_pointsSort", None)
            row.pop("_winsSort", None)
            row.pop("_gdSort", None)
            row.pop("_leagueKey", None)
        key = f"world-cup:{group}"
        standings[key] = {
            "leagueKey": key,
            "leagueName": league.get("name") or "FIFA World Cup",
            "group": group,
            "groupLabel": world_cup_group_label(group),
            "complete": len(rows) >= 4,
            "rows": rows,
            "legend": standing_zone_legend(rows),
        }
    return standings


def normalize_thesportsdb_standing_entry(item):
    record = "-".join(
        part
        for part in [
            str(item.get("intWin") or ""),
            str(item.get("intDraw") or ""),
            str(item.get("intLoss") or ""),
        ]
        if part != ""
    )
    return {
        "rank": parse_optional_int(item.get("intRank")),
        "name": item.get("strTeam") or "Team",
        "shortName": "",
        "crest": item.get("strBadge") or "",
        "played": str(item.get("intPlayed") or ""),
        "wins": str(item.get("intWin") or ""),
        "draws": str(item.get("intDraw") or ""),
        "losses": str(item.get("intLoss") or ""),
        "goalsFor": str(item.get("intGoalsFor") or ""),
        "goalsAgainst": str(item.get("intGoalsAgainst") or ""),
        "gd": str(item.get("intGoalDifference") or ""),
        "points": str(item.get("intPoints") or ""),
        "record": record,
        "zoneLabel": standing_zone_label(item.get("strDescription")),
    }


def standing_zone_label(value):
    raw = str(value or "").strip()
    if not raw:
        return ""
    compact = re.sub(r"\s+", " ", raw)
    lower = compact.lower()
    if "champions league" in lower:
        return "Champions League"
    if "europa league" in lower:
        return "Europa League"
    if "conference league" in lower:
        return "Conference League"
    if "relegation" in lower or "spadek" in lower:
        return "Spadek"
    return compact


def standing_zone_kind(label):
    lower = str(label or "").lower()
    if "champions" in lower:
        return "champions"
    if "europa" in lower:
        return "europa"
    if "conference" in lower:
        return "conference"
    if "spadek" in lower or "relegation" in lower:
        return "relegation"
    return ""


def standing_zone_abbrev(label):
    kind = standing_zone_kind(label)
    return {
        "champions": "UCL",
        "europa": "UEL",
        "conference": "UECL",
        "relegation": "Spadek",
    }.get(kind, str(label or ""))


def enrich_standing_zones(rows):
    enriched = []
    for row in rows or []:
        item = dict(row)
        label = standing_zone_label(item.get("zoneLabel") or item.get("description"))
        kind = standing_zone_kind(label)
        item["zoneLabel"] = label
        item["zoneKind"] = kind
        item["zoneAbbrev"] = standing_zone_abbrev(label) if kind else ""
        enriched.append(item)
    return enriched


def standing_zone_legend(rows):
    groups = []
    current = None
    for row in rows or []:
        rank = parse_optional_int(row.get("rank"))
        label = standing_zone_label(row.get("zoneLabel"))
        kind = standing_zone_kind(label)
        if not rank or not label or not kind:
            current = None
            continue
        abbrev = standing_zone_abbrev(label)
        if current and current["label"] == label and current["kind"] == kind and current["end"] == rank - 1:
            current["end"] = rank
            continue
        current = {
            "start": rank,
            "end": rank,
            "label": label,
            "kind": kind,
            "abbrev": abbrev,
        }
        groups.append(current)
    for group in groups:
        group["places"] = str(group["start"]) if group["start"] == group["end"] else f"{group['start']}-{group['end']}"
    return groups


def normalize_api_football_standing_entry(item):
    all_stats = item.get("all") or {}
    goals = all_stats.get("goals") or {}
    record = "-".join(
        str(value)
        for value in [
            all_stats.get("win"),
            all_stats.get("draw"),
            all_stats.get("lose"),
        ]
        if value is not None
    )
    team = item.get("team") or {}
    return {
        "rank": parse_optional_int(item.get("rank")),
        "name": team.get("name") or "Team",
        "shortName": "",
        "crest": team.get("logo") or "",
        "played": str(all_stats.get("played") or ""),
        "wins": str(all_stats.get("win") or ""),
        "draws": str(all_stats.get("draw") or ""),
        "losses": str(all_stats.get("lose") or ""),
        "goalsFor": str(goals.get("for") or ""),
        "goalsAgainst": str(goals.get("against") or ""),
        "gd": str(item.get("goalsDiff") or ""),
        "points": str(item.get("points") or ""),
        "record": record,
        "zoneLabel": standing_zone_label(item.get("description")),
    }


def fetch_api_football_standings(league):
    key = api_football_key()
    if not key or not league.get("api_football_id"):
        return []
    season = current_football_season()
    if league.get("seasonMode") == "year":
        season = date.today().year
    params = urllib.parse.urlencode({
        "league": api_football_league_id(league),
        "season": season,
    })
    payload = http_get_json(
        f"{API_FOOTBALL_BASE}/standings?{params}",
        headers={"x-apisports-key": key},
        timeout=14,
    )
    league_payload = ((payload.get("response") or [{}])[0] or {}).get("league") or {}
    groups = league_payload.get("standings") or []
    table = groups[0] if groups and isinstance(groups[0], list) else []
    rows = [normalize_api_football_standing_entry(item) for item in table]
    rows.sort(key=lambda row: row.get("rank") or 999)
    return rows


def clean_bbc_text(value):
    text = html.unescape(re.sub(r"<[^>]+>", " ", str(value or "")))
    text = re.sub(r"\s+", " ", text).strip()
    try:
        fixed = text.encode("latin1").decode("utf-8")
        if fixed.count("�") <= text.count("�"):
            return fixed
    except UnicodeError:
        pass
    return text


def bbc_table_zones(page_html):
    key_match = re.search(r'<div id="football-[^"]+-table-key".*?</div></div></div>', page_html, flags=re.S)
    key_html = key_match.group(0) if key_match else page_html
    zones = {}
    for positions, label_html in re.findall(
        r"Position\s*<span[^>]*>(.*?)</span>.*?<span>\s*:\s*<span[^>]*>(.*?)</span>",
        key_html,
        flags=re.S,
    ):
        label = standing_zone_label(clean_bbc_text(label_html))
        for number in re.findall(r"\d+", clean_bbc_text(positions)):
            rank = parse_optional_int(number)
            if rank:
                zones[rank] = label
    return zones


def fetch_bbc_standings(league):
    slug = BBC_FOOTBALL_TABLE_SLUGS.get(league.get("key"))
    if not slug:
        return []
    url = f"https://www.bbc.co.uk/sport/football/{slug}/table"
    req = urllib.request.Request(url, headers={"User-Agent": WIKI_UA, "Accept": "text/html"})
    with urllib.request.urlopen(req, timeout=14) as resp:
        page_html = resp.read().decode("utf-8", errors="replace")
    table_match = re.search(r'<table[^>]*data-testid="football-table"[^>]*>.*?</table>', page_html, flags=re.S)
    if not table_match:
        return []
    zones = bbc_table_zones(page_html)
    rows = []
    for row_html in re.findall(r"<tr\b[^>]*>(.*?)</tr>", table_match.group(0), flags=re.S):
        cells = {
            label: body
            for label, body in re.findall(r'<td\b[^>]*aria-label="([^"]+)"[^>]*>(.*?)</td>', row_html, flags=re.S)
        }
        team_html = cells.get("Team") or ""
        if not team_html:
            continue
        rank = parse_optional_int(clean_bbc_text(re.search(r'<span[^>]*Rank[^>]*>(.*?)</span>', team_html, flags=re.S).group(1)) if re.search(r'<span[^>]*Rank[^>]*>(.*?)</span>', team_html, flags=re.S) else None)
        hidden_names = re.findall(r'<span[^>]*VisuallyHidden[^>]*>(.*?)</span>', team_html, flags=re.S)
        name = clean_bbc_text(hidden_names[-1] if hidden_names else "")
        if not name:
            css_name = re.search(r'content:"([^"]+)"', team_html)
            name = clean_bbc_text(css_name.group(1) if css_name else "Team")
        crest_match = re.search(r'<img[^>]+src="([^"]+)"', team_html)
        crest = html.unescape(crest_match.group(1)) if crest_match else ""
        if "placeholder-badge" in crest:
            crest = ""
        wins = clean_bbc_text(cells.get("Won"))
        draws = clean_bbc_text(cells.get("Drawn"))
        losses = clean_bbc_text(cells.get("Lost"))
        rows.append({
            "rank": rank or len(rows) + 1,
            "name": name,
            "shortName": "",
            "crest": crest,
            "played": clean_bbc_text(cells.get("Played")),
            "wins": wins,
            "draws": draws,
            "losses": losses,
            "goalsFor": clean_bbc_text(cells.get("Goals For")),
            "goalsAgainst": clean_bbc_text(cells.get("Goals Against")),
            "gd": clean_bbc_text(cells.get("Goal Difference")),
            "points": clean_bbc_text(cells.get("Points")),
            "record": "-".join(part for part in [wins, draws, losses] if part != ""),
            "zoneLabel": standing_zone_label(zones.get(rank)),
        })
    rows.sort(key=lambda row: row.get("rank") or 999)
    return rows


def fetch_thesportsdb_standings(league):
    season_base = str(kitchen_league_season(league))
    season = (
        season_base
        if league.get("seasonMode") == "year" or "-" in season_base
        else f"{season_base}-{int(season_base) + 1}"
    )
    params = urllib.parse.urlencode({"l": league["thesportsdb_id"], "s": season})
    payload = http_get_json(f"{THESPORTSDB_API_BASE}/lookuptable.php?{params}", timeout=14)
    rows = [
        normalize_thesportsdb_standing_entry(item)
        for item in (payload.get("table") or [])
    ]
    rows.sort(key=lambda row: row.get("rank") or 999)
    return rows


def fetch_thesportsdb_reconstructed_standings(league, now=None):
    """Build a full table when the public lookuptable endpoint returns only its top rows."""
    if not league.get("thesportsdb_id"):
        return []
    now = now or datetime.now().replace(microsecond=0)
    season_base = str(kitchen_league_season(league, now=now))
    season = (
        season_base
        if league.get("seasonMode") == "year" or "-" in season_base
        else f"{season_base}-{int(season_base) + 1}"
    )
    params = urllib.parse.urlencode({"id": league["thesportsdb_id"], "s": season})
    payload = http_get_json(f"{THESPORTSDB_API_BASE}/eventsseason.php?{params}", timeout=14)
    teams = {}

    def ensure_team(name, crest):
        key = standing_team_key(name)
        if not key:
            return None
        row = teams.setdefault(key, {
            "name": name,
            "crest": crest or "",
            "played": 0,
            "wins": 0,
            "draws": 0,
            "losses": 0,
            "goalsFor": 0,
            "goalsAgainst": 0,
            "points": 0,
        })
        if crest and not row.get("crest"):
            row["crest"] = crest
        return row

    for event in payload.get("events") or []:
        home_score = parse_optional_int(event.get("intHomeScore"))
        away_score = parse_optional_int(event.get("intAwayScore"))
        if home_score is None or away_score is None:
            continue
        played_at = parse_match_datetime(
            event.get("strTimestamp")
            or f"{event.get('dateEvent', '')}T{event.get('strTime', '00:00:00')}",
            naive_tz=timezone.utc,
        )
        if played_at and played_at > now:
            continue
        status = str(event.get("strStatus") or "").strip().lower()
        if status and not kitchen_live_status_is_terminal(status):
            continue
        home = ensure_team(event.get("strHomeTeam"), event.get("strHomeTeamBadge"))
        away = ensure_team(event.get("strAwayTeam"), event.get("strAwayTeamBadge"))
        if not home or not away:
            continue
        for row, scored, conceded in ((home, home_score, away_score), (away, away_score, home_score)):
            row["played"] += 1
            row["goalsFor"] += scored
            row["goalsAgainst"] += conceded
        if home_score > away_score:
            home["wins"] += 1
            home["points"] += 3
            away["losses"] += 1
        elif away_score > home_score:
            away["wins"] += 1
            away["points"] += 3
            home["losses"] += 1
        else:
            home["draws"] += 1
            away["draws"] += 1
            home["points"] += 1
            away["points"] += 1

    ranked = sorted(
        teams.values(),
        key=lambda row: (
            -row["points"],
            -(row["goalsFor"] - row["goalsAgainst"]),
            -row["goalsFor"],
            -row["wins"],
            normalize_lookup_text(row["name"]),
        ),
    )
    rows = []
    for rank, row in enumerate(ranked, 1):
        gd = row["goalsFor"] - row["goalsAgainst"]
        rows.append({
            "rank": rank,
            "name": row["name"],
            "shortName": "",
            "crest": row.get("crest") or "",
            "played": str(row["played"]),
            "wins": str(row["wins"]),
            "draws": str(row["draws"]),
            "losses": str(row["losses"]),
            "goalsFor": str(row["goalsFor"]),
            "goalsAgainst": str(row["goalsAgainst"]),
            "gd": f"{gd:+d}" if gd else "0",
            "points": str(row["points"]),
            "record": f"{row['wins']}-{row['draws']}-{row['losses']}",
            "zoneLabel": "",
        })
    return rows


def merge_standing_crests(rows, crest_rows):
    crests = {
        standing_team_key(row.get("name")): row.get("crest")
        for row in crest_rows or []
        if standing_team_key(row.get("name")) and row.get("crest")
    }
    return [
        {**row, "crest": row.get("crest") or crests.get(standing_team_key(row.get("name"))) or ""}
        for row in rows or []
    ]


def fetch_kitchen_standings(settings=None, league_keys=None):
    settings = settings or read_kitchen_settings()
    requested_keys = set(league_keys or [])
    standings_enabled = set((settings.get("sports") or {}).get("standingsLeagueKeys") or [])
    standings = {}
    thesportsdb_rate_limited = False
    for league in selected_kitchen_competitions(settings):
        if requested_keys and league["key"] not in requested_keys:
            continue
        if league["key"] not in standings_enabled and league["key"] != "world-cup":
            continue
        if league["key"] == "world-cup":
            try:
                standings.update(fetch_world_cup_group_standings(league))
            except Exception:
                pass
            continue
        standing = league.get("standing") or {}
        if not standing and not league.get("thesportsdb_id"):
            continue
        try:
            if standing.get("provider") == "espn":
                rows = fetch_espn_standings(league)
                if len(rows) < 8:
                    rows = fetch_api_football_standings(league) or rows
            elif standing.get("provider") == "thesportsdb" or league.get("thesportsdb_id"):
                try:
                    rows = [] if thesportsdb_rate_limited else fetch_thesportsdb_standings(league)
                except Exception as exc:
                    rows = []
                    thesportsdb_rate_limited = isinstance(exc, urllib.error.HTTPError) and exc.code == 429
                reconstructed = []
                if not thesportsdb_rate_limited and (
                    len(rows) < KITCHEN_STANDINGS_MIN_ROWS or any(not row.get("crest") for row in rows)
                ):
                    try:
                        reconstructed = fetch_thesportsdb_reconstructed_standings(league)
                    except Exception as exc:
                        reconstructed = []
                        thesportsdb_rate_limited = isinstance(exc, urllib.error.HTTPError) and exc.code == 429
                if len(rows) < KITCHEN_STANDINGS_MIN_ROWS and len(reconstructed) >= KITCHEN_STANDINGS_MIN_ROWS:
                    rows = reconstructed
                elif reconstructed:
                    rows = merge_standing_crests(rows, reconstructed)
                if len(rows) < 8:
                    rows = fetch_bbc_standings(league) or fetch_api_football_standings(league) or rows
            else:
                rows = []
            if rows:
                rows = enrich_standing_zones(rows)
                standings[league["key"]] = {
                    "leagueKey": league["key"],
                    "leagueName": league["name"],
                    "complete": len(rows) >= 8,
                    "rows": rows,
                    "legend": standing_zone_legend(rows),
                }
        except Exception:
            continue
    return standings


def standing_team_key(value):
    return normalize_lookup_text(value).replace(" fc", "").replace(" afc", "").strip()


def kitchen_team_crest_key(value):
    key = normalize_lookup_text(value)
    key = key.replace("ł", "l").replace("Ł", "l")
    key = re.sub(r"[^a-z0-9]+", " ", key)
    key = re.sub(r"\b(fc|ks|tsk|sa)\b", " ", key)
    key = re.sub(r"\s+", " ", key).strip()
    return key


def read_kitchen_team_crest_cache():
    payload = read_json_file(KITCHEN_TEAM_CRESTS_JSON, {})
    if not isinstance(payload, dict):
        return {"schemaVersion": 1, "updatedAt": "", "teams": {}}
    teams = payload.get("teams")
    if not isinstance(teams, dict):
        payload["teams"] = {}
    else:
        normalized_teams = {}
        for key, row in teams.items():
            if not isinstance(row, dict):
                continue
            normalized_key = kitchen_team_crest_key(row.get("name") or key)
            if not normalized_key:
                continue
            current = normalized_teams.get(normalized_key)
            if not current or (row.get("crest") and not current.get("crest")):
                normalized_teams[normalized_key] = row
        payload["teams"] = normalized_teams
    payload.setdefault("schemaVersion", 1)
    payload.setdefault("updatedAt", "")
    return payload


def write_kitchen_team_crest_cache(cache):
    cache["schemaVersion"] = 1
    cache["updatedAt"] = datetime.now().replace(microsecond=0).isoformat()
    rewrite_json_file(KITCHEN_TEAM_CRESTS_JSON, cache)


def cache_kitchen_team_crest(name, crest, source="runtime", cache=None):
    if not name or not crest:
        return False
    cache = cache or read_kitchen_team_crest_cache()
    teams = cache.setdefault("teams", {})
    key = kitchen_team_crest_key(name)
    if not key:
        return False
    current = teams.get(key) if isinstance(teams.get(key), dict) else {}
    changed = current.get("crest") != crest or current.get("name") != name
    current.update({
        "name": name,
        "crest": crest,
        "source": source,
        "updatedAt": datetime.now().replace(microsecond=0).isoformat(),
    })
    teams[key] = current
    return changed


def collect_kitchen_team_crests(matches, cache=None):
    cache = cache or read_kitchen_team_crest_cache()
    changed = False
    for match in matches or []:
        if not isinstance(match, dict):
            continue
        for side in ("home", "away"):
            team = match.get(side) or {}
            if cache_kitchen_team_crest(team.get("name"), team.get("crest"), match.get("provider") or "payload", cache=cache):
                changed = True
    return changed


def kitchen_team_cache_crest(name, cache=None):
    if not name:
        return ""
    cache = cache or read_kitchen_team_crest_cache()
    entry = (cache.get("teams") or {}).get(kitchen_team_crest_key(name))
    if isinstance(entry, dict):
        return entry.get("crest") or ""
    return ""


def kitchen_known_team_crest(name):
    key = kitchen_team_crest_key(name)
    return KITCHEN_TEAM_CREST_FALLBACKS.get(key) or ""


def fetch_thesportsdb_team_crest_by_name(name, league_id=None):
    if not name:
        return ""
    query_name = KITCHEN_TEAM_CREST_ALIASES.get(kitchen_team_crest_key(name), name)
    url = f"{THESPORTSDB_API_BASE}/searchteams.php?{urllib.parse.urlencode({'t': query_name})}"
    payload = http_get_json(url, timeout=10)
    teams = payload.get("teams") or []
    if not isinstance(teams, list):
        return ""
    desired_key = kitchen_team_crest_key(name)
    league_id = str(league_id or "")

    def score_team(item):
        if not isinstance(item, dict) or item.get("strSport") != "Soccer":
            return -1
        names = [
            item.get("strTeam"),
            item.get("strTeamAlternate"),
            item.get("strTeamShort"),
        ]
        normalized_names = {kitchen_team_crest_key(value) for value in names if value}
        score = 0
        if desired_key in normalized_names:
            score += 10
        if league_id and league_id in {
            str(item.get(f"idLeague{suffix}") or "")
            for suffix in ("", "2", "3", "4", "5", "6", "7")
        }:
            score += 5
        if item.get("strBadge"):
            score += 1
        return score

    ranked = sorted(teams, key=score_team, reverse=True)
    best = ranked[0] if ranked and score_team(ranked[0]) > 0 else None
    if not best:
        return ""
    return best.get("strBadge") or best.get("strLogo") or ""


def resolve_kitchen_team_crest(name, league_id=None, cache=None):
    cache = cache or read_kitchen_team_crest_cache()
    crest = kitchen_team_cache_crest(name, cache=cache)
    if crest:
        return crest
    crest = kitchen_known_team_crest(name)
    source = "known"
    if not crest:
        try:
            crest = fetch_thesportsdb_team_crest_by_name(name, league_id=league_id)
            source = "thesportsdb-search"
        except Exception:
            crest = ""
    if crest:
        cache_kitchen_team_crest(name, crest, source=source, cache=cache)
    return crest


def hydrate_kitchen_team_crests(matches, settings=None, cache=None):
    cache = cache or read_kitchen_team_crest_cache()
    league_by_key = {league.get("key"): league for league in selected_kitchen_competitions(settings)}
    changed = collect_kitchen_team_crests(matches, cache=cache)
    for match in matches or []:
        if not isinstance(match, dict):
            continue
        league = league_by_key.get(match.get("leagueKey") or match.get("teamKey")) or {}
        league_id = league.get("thesportsdb_id")
        for side in ("home", "away"):
            team = match.get(side) or {}
            if team.get("crest"):
                continue
            crest = resolve_kitchen_team_crest(team.get("name"), league_id=league_id, cache=cache)
            if crest:
                team["crest"] = crest
                changed = True
    if changed:
        write_kitchen_team_crest_cache(cache)
    return matches


def hydrate_kitchen_standing_crests(standings, settings=None, cache=None):
    cache = cache or read_kitchen_team_crest_cache()
    selected = {league.get("key"): league for league in selected_kitchen_competitions(settings)}
    changed = False
    for league_key, standing in (standings or {}).items():
        league = selected.get(str(league_key).split(":", 1)[0]) or {}
        league_id = league.get("thesportsdb_id")
        for row in (standing or {}).get("rows") or []:
            if row.get("crest"):
                if cache_kitchen_team_crest(row.get("name"), row.get("crest"), "standings", cache=cache):
                    changed = True
                continue
            crest = resolve_kitchen_team_crest(row.get("name"), league_id=league_id, cache=cache)
            if crest:
                row["crest"] = crest
                changed = True
    if changed:
        write_kitchen_team_crest_cache(cache)
    return standings


def compact_match_score(match):
    home = (match.get("home") or {}).get("name") or "Home"
    away = (match.get("away") or {}).get("name") or "Away"
    score = match.get("score") or {}
    return f"{home} {score.get('home', '-')}:{score.get('away', '-')} {away}"


def kitchen_live_status_is_terminal(*values):
    haystack = " ".join(str(value or "").strip().lower() for value in values if value is not None)
    if not haystack:
        return True
    tokens = {token for token in re.split(r"[^a-z0-9]+", haystack) if token}
    if tokens & KITCHEN_TERMINAL_LIVE_STATUSES:
        return True
    return any(status in haystack for status in KITCHEN_TERMINAL_LIVE_STATUSES if " " in status)


def kitchen_live_match_is_stale(match, now=None):
    played_at = parse_match_datetime((match or {}).get("playedAt"))
    if not played_at:
        return False
    now = now or datetime.now().replace(microsecond=0)
    return (now - played_at).total_seconds() > KITCHEN_LIVE_MAX_AGE_HOURS * 3600


def nhl_fact_for_match(match):
    if match.get("leagueKey") != "nhl":
        return ""
    names = [
        (match.get("home") or {}).get("name") or "",
        (match.get("away") or {}).get("name") or "",
    ]
    for name in names:
        key = normalize_lookup_text(name)
        for needle, fact in NHL_TEAM_FACTS.items():
            if needle in key:
                return fact
    seed = sum(ord(char) for char in " ".join(names))
    return NHL_GENERIC_FACTS[seed % len(NHL_GENERIC_FACTS)]


def match_mentions_team(match, team_name):
    needle = standing_team_key(team_name)
    if not needle:
        return False
    names = [
        (match.get("home") or {}).get("name"),
        (match.get("away") or {}).get("name"),
    ]
    for name in names:
        key = standing_team_key(name)
        if key == needle or (needle and needle in key) or (key and key in needle):
            return True
    return False


def movement_match_for_row(row, league_key, matches):
    league_matches = [
        match for match in matches
        if match.get("leagueKey") == league_key and match_mentions_team(match, row.get("name"))
    ]
    league_matches.sort(key=lambda item: parse_match_datetime(item.get("playedAt")) or datetime.min, reverse=True)
    return compact_match_score(league_matches[0]) if league_matches else ""


def standings_context_rows(rows, center_rank, size=7):
    total = len(rows)
    if not total:
        return []
    size = min(size, total)
    center_index = max(0, min(total - 1, (parse_optional_int(center_rank) or 1) - 1))
    start = max(0, min(total - size, center_index - (size // 2)))
    return rows[start:start + size]


def standings_section(title, rows, standing, league_key):
    rows = enrich_standing_zones(rows)
    return {
        "leagueKey": league_key,
        "leagueName": standing.get("leagueName") or league_key,
        "complete": bool(standing.get("complete")),
        "rows": rows,
        "legend": standing_zone_legend(rows),
        "changed": True,
        "title": title,
    }


def standings_with_position_changes(current_standings, previous_standings, matches):
    if not isinstance(previous_standings, dict) or not previous_standings:
        return {}
    changed = {}
    for league_key, standing in (current_standings or {}).items():
        rows = (standing or {}).get("rows") or []
        previous_rows = ((previous_standings.get(league_key) or {}).get("rows") or [])
        previous_by_team = {
            standing_team_key(row.get("name")): row
            for row in previous_rows
            if standing_team_key(row.get("name"))
        }
        league_matches = [match for match in matches if match.get("leagueKey") == league_key]
        match_team_keys = {
            standing_team_key((match.get(side) or {}).get("name"))
            for match in league_matches
            for side in ["home", "away"]
        }
        changed_rows = []
        enriched_rows = []
        for row in rows:
            enriched = dict(row)
            team_key = standing_team_key(row.get("name"))
            previous = previous_by_team.get(team_key)
            previous_rank = parse_optional_int((previous or {}).get("rank"))
            current_rank = parse_optional_int(row.get("rank"))
            if previous_rank and current_rank and previous_rank != current_rank:
                direction = "up" if current_rank < previous_rank else "down"
                enriched["previousRank"] = previous_rank
                enriched["rankDelta"] = abs(previous_rank - current_rank)
                enriched["movement"] = direction
                enriched["movementMatch"] = movement_match_for_row(row, league_key, matches)
                changed_rows.append(enriched)
            elif team_key in match_team_keys:
                enriched["movementMatch"] = movement_match_for_row(row, league_key, matches)
            enriched_rows.append(enriched)
        if changed_rows:
            total = len(enriched_rows)
            focus_ranks = [
                parse_optional_int(row.get("rank"))
                for row in enriched_rows
                if row.get("movement") or standing_team_key(row.get("name")) in match_team_keys
            ]
            focus_ranks = [rank for rank in focus_ranks if rank]
            top_needed = any(rank <= 6 for rank in focus_ranks)
            bottom_needed = any(rank > max(0, total - 6) for rank in focus_ranks)
            sections = []
            if top_needed:
                sections.append(standings_section("Zmiany w tabeli - góra", enriched_rows[:7], standing, league_key))
            if bottom_needed:
                sections.append(standings_section("Zmiany w tabeli - dół", enriched_rows[-7:], standing, league_key))
            if not sections:
                center = sorted(focus_ranks)[len(focus_ranks) // 2] if focus_ranks else changed_rows[0].get("rank")
                sections.append(standings_section(
                    "Zmiany w tabeli - środek",
                    standings_context_rows(enriched_rows, center, 7),
                    standing,
                    league_key,
                ))
            changed[league_key] = {
                "leagueKey": league_key,
                "leagueName": standing.get("leagueName") or league_key,
                "complete": bool(standing.get("complete")),
                "rows": sections[0]["rows"],
                "sections": sections,
                "changed": True,
            }
    return changed


KITCHEN_STANDINGS_MIN_ROWS = 10


def standings_snapshot_for_league(league_key, standing, matches):
    rows = (standing or {}).get("rows") or []
    if len(rows) < KITCHEN_STANDINGS_MIN_ROWS:
        return None
    league_matches = [match for match in matches if match.get("leagueKey") == league_key]
    match_team_keys = {
        standing_team_key((match.get(side) or {}).get("name"))
        for match in league_matches
        for side in ["home", "away"]
    }
    enriched_rows = []
    focus_ranks = []
    for row in rows:
        enriched = dict(row)
        team_key = standing_team_key(row.get("name"))
        if team_key in match_team_keys:
            enriched["movementMatch"] = movement_match_for_row(row, league_key, matches)
            rank = parse_optional_int(row.get("rank"))
            if rank:
                focus_ranks.append(rank)
        enriched_rows.append(enriched)
    total = len(enriched_rows)
    sections = []
    if not league_matches:
        top_needed = True
        bottom_needed = total > 10
    else:
        top_needed = not focus_ranks or any(rank <= 6 for rank in focus_ranks)
        bottom_needed = any(rank > max(0, total - 6) for rank in focus_ranks)
    if top_needed:
        sections.append(standings_section("Tabela - góra", enriched_rows[:7], standing, league_key))
    if bottom_needed:
        sections.append(standings_section("Tabela - dół", enriched_rows[-7:], standing, league_key))
    if not sections:
        center = sorted(focus_ranks)[len(focus_ranks) // 2]
        sections.append(standings_section(
            "Tabela - środek",
            standings_context_rows(enriched_rows, center, 7),
            standing,
            league_key,
        ))
    for section in sections:
        section["changed"] = False
    return {
        "leagueKey": league_key,
        "leagueName": standing.get("leagueName") or league_key,
        "complete": bool(standing.get("complete")),
        "rows": sections[0]["rows"],
        "sections": sections,
        "changed": False,
    }


def standings_for_display(current_standings, changed_standings, matches):
    display = dict(changed_standings or {})
    for league_key, standing in (current_standings or {}).items():
        if league_key in display:
            continue
        if str(league_key).startswith("world-cup:"):
            display[league_key] = standing
            continue
        snapshot = standings_snapshot_for_league(league_key, standing, matches)
        if snapshot:
            display[league_key] = snapshot
    return display


def standings_snapshot_for_league(league_key, standing, matches):
    rows = (standing or {}).get("rows") or []
    if len(rows) < KITCHEN_STANDINGS_MIN_ROWS:
        return None
    league_matches = [match for match in matches if match.get("leagueKey") == league_key]
    match_team_keys = {
        standing_team_key((match.get(side) or {}).get("name"))
        for match in league_matches
        for side in ["home", "away"]
    }
    enriched_rows = []
    for row in rows:
        enriched = dict(row)
        team_key = standing_team_key(row.get("name"))
        if team_key in match_team_keys:
            enriched["movementMatch"] = movement_match_for_row(row, league_key, matches)
        enriched_rows.append(enriched)
    enriched_rows = enrich_standing_zones(enriched_rows)
    legend = standing_zone_legend(enriched_rows)
    sections = []
    chunk_size = 10
    chunks = [enriched_rows[index:index + chunk_size] for index in range(0, len(enriched_rows), chunk_size)]
    for index, chunk in enumerate(chunks):
        start_rank = parse_optional_int(chunk[0].get("rank")) or index * chunk_size + 1
        end_rank = parse_optional_int(chunk[-1].get("rank")) or start_rank + len(chunk) - 1
        if len(chunks) == 2:
            title = "Tabela - g\u00f3ra" if index == 0 else "Tabela - d\u00f3\u0142"
        else:
            title = f"Tabela - miejsca {start_rank}-{end_rank}"
        section = standings_section(title, chunk, standing, league_key)
        section["legend"] = legend
        section["changed"] = False
        section["page"] = index + 1
        section["pageCount"] = len(chunks)
        sections.append(section)
    return {
        "leagueKey": league_key,
        "leagueName": standing.get("leagueName") or league_key,
        "complete": bool(standing.get("complete")),
        "rows": enriched_rows,
        "legend": legend,
        "sections": sections,
        "changed": False,
    }


def standings_for_display(current_standings, changed_standings, matches):
    display = {}
    for league_key, standing in (current_standings or {}).items():
        if str(league_key).startswith("world-cup:"):
            display[league_key] = standing
            continue
        snapshot = standings_snapshot_for_league(league_key, standing, matches)
        if snapshot:
            display[league_key] = snapshot
    return display


def normalize_thesportsdb_next_event(item, source):
    kickoff_at = item.get("strTimestamp") or f"{item.get('dateEvent', '')}T{item.get('strTime', '00:00:00')}"
    round_value = item.get("strRound") or item.get("strGroup") or item.get("intRound")
    match = {
        "id": f"thesportsdb-next:{item.get('idEvent')}",
        "provider": "thesportsdb",
        "teamKey": source["key"],
        "teamName": source["name"],
        "competitionName": item.get("strLeague") or "",
        "kickoffAt": kitchen_local_iso(kickoff_at, naive_tz=timezone.utc),
        "round": kitchen_round_value(round_value, source),
        "roundType": kitchen_match_round_type(
            source,
            round_value,
            item.get("strEvent"),
            item.get("strFilename"),
        ),
        "home": {
            "name": item.get("strHomeTeam") or "Gospodarze",
            "crest": item.get("strHomeTeamBadge") or "",
        },
        "away": {
            "name": item.get("strAwayTeam") or "Goście",
            "crest": item.get("strAwayTeamBadge") or "",
        },
    }
    return add_kitchen_match_metadata(
        match,
        source,
        round_value,
        item.get("strGroup"),
        item.get("strEvent"),
        item.get("strFilename"),
        item.get("strLeague"),
    )


def normalize_espn_next_event(item, source, team_name=None):
    competitions = item.get("competitions") or []
    competition = competitions[0] if competitions else {}
    competitors = competition.get("competitors") or []
    if len(competitors) < 2:
        return None

    by_side = {entry.get("homeAway"): entry for entry in competitors}
    home = by_side.get("home") or competitors[0]
    away = by_side.get("away") or competitors[1]

    def team_payload(entry):
        team = entry.get("team") or {}
        return {
            "name": team.get("displayName") or team.get("name") or "Team",
            "crest": team.get("logo") or "",
        }

    kickoff_at = kitchen_local_iso(item.get("date"))
    if not kickoff_at:
        return None
    league = (item.get("league") or {}) or ((item.get("leagues") or [{}])[0] if item.get("leagues") else {})
    season = item.get("season") or {}
    match = {
        "id": f"espn-next:{source['key']}:{item.get('id')}",
        "provider": "espn",
        "teamKey": source["key"],
        "teamName": team_name or source.get("name") or source["key"],
        "competitionName": league.get("name") or source.get("competitionName") or source.get("name") or "",
        "kickoffAt": kickoff_at,
        "round": kitchen_round_value(None, source),
        "roundType": kitchen_match_round_type(
            source,
            season.get("slug"),
            season.get("type"),
            league.get("name"),
        ),
        "home": team_payload(home),
        "away": team_payload(away),
    }
    return add_kitchen_match_metadata(
        match,
        source,
        competition.get("altGameNote"),
        season.get("slug"),
        season.get("type"),
        league.get("name"),
    )


def fetch_espn_next_matches_for_source(source, now, end, team_name=None, all_matches=False):
    if not source.get("espn_sport") or not source.get("espn_league"):
        return []
    names = {normalize_lookup_text(name) for name in source.get("espn_team_names") or []}
    if source.get("type") == "team" and not names:
        names = {normalize_lookup_text(source.get("name"))}
    matches = []
    current = now.date()
    while current <= end.date():
        params = urllib.parse.urlencode({"dates": current.isoformat().replace("-", "")})
        url = f"{ESPN_SCOREBOARD_BASE}/{source['espn_sport']}/{source['espn_league']}/scoreboard?{params}"
        payload = http_get_json(url, timeout=12)
        for item in payload.get("events") or []:
            match = normalize_espn_next_event(item, source, team_name=team_name)
            if not match:
                continue
            kickoff = parse_match_datetime(match.get("kickoffAt"))
            if not kickoff or kickoff < now or kickoff > end:
                continue
            if names and not all_matches:
                event_names = {
                    normalize_lookup_text((match.get("home") or {}).get("name")),
                    normalize_lookup_text((match.get("away") or {}).get("name")),
                }
                if not (event_names & names):
                    continue
            matches.append(match)
        current += timedelta(days=1)
    matches.sort(key=lambda item: parse_match_datetime(item.get("kickoffAt")) or datetime.max)
    return matches


def fetch_thesportsdb_next_matches_for_competition(source, now, end):
    if not source.get("thesportsdb_id"):
        return []
    url = f"{THESPORTSDB_API_BASE}/eventsnextleague.php?id={source['thesportsdb_id']}"
    payload = http_get_json(url, timeout=12)
    matches = []
    for item in payload.get("events") or []:
        match = normalize_thesportsdb_next_event(item, source)
        kickoff = parse_match_datetime(match.get("kickoffAt"))
        if kickoff and now <= kickoff <= end:
            matches.append(match)
    matches.sort(key=lambda item: parse_match_datetime(item.get("kickoffAt")) or datetime.max)
    return matches


def fetch_thesportsdb_round_events_for_competition(source):
    if not source.get("thesportsdb_id") or source.get("key") not in KITCHEN_FULL_ROUND_LEAGUE_KEYS:
        return []
    season = kitchen_league_season(source)
    events = []
    for round_number in KITCHEN_FULL_ROUND_NUMBERS:
        params = urllib.parse.urlencode(
            {
                "id": source["thesportsdb_id"],
                "r": round_number,
                "s": season,
            }
        )
        payload = http_get_json(f"{THESPORTSDB_API_BASE}/eventsround.php?{params}", timeout=14)
        events.extend(payload.get("events") or [])
    return events


def fetch_thesportsdb_round_scores(cutoff, now=None, settings=None):
    now = now or datetime.now().replace(microsecond=0)
    matches = []
    for source in selected_kitchen_competitions(settings or read_kitchen_settings()):
        if source.get("key") not in KITCHEN_FULL_ROUND_LEAGUE_KEYS:
            continue
        try:
            round_matches = []
            for item in fetch_thesportsdb_round_events_for_competition(source):
                match = normalize_thesportsdb_event(item, source)
                if match:
                    round_matches.append(match)
            round_matches = enrich_kitchen_two_leg_matches(round_matches)
            matches.extend(match for match in round_matches if match_is_recent(match, cutoff))
        except Exception:
            continue
    return matches


def fetch_thesportsdb_round_next_matches_for_competition(source, now, end):
    if source.get("key") not in KITCHEN_FULL_ROUND_LEAGUE_KEYS:
        return []
    all_matches = []
    for item in fetch_thesportsdb_round_events_for_competition(source):
        score_home = parse_optional_int(item.get("intHomeScore"))
        score_away = parse_optional_int(item.get("intAwayScore"))
        if score_home is None or score_away is None:
            match = normalize_thesportsdb_next_event(item, source)
        else:
            match = normalize_thesportsdb_event(item, source)
        if match:
            all_matches.append(match)
    all_matches = enrich_kitchen_two_leg_matches(all_matches)
    matches = []
    for match in all_matches:
        kickoff = parse_match_datetime(match.get("kickoffAt") or match.get("playedAt"))
        if kickoff and now <= kickoff <= end and not match.get("score"):
            matches.append(match)
    matches.sort(key=lambda item: parse_match_datetime(item.get("kickoffAt")) or datetime.max)
    return matches


def fetch_world_cup_next_matches(now=None):
    now = now or datetime.now().replace(microsecond=0)
    source = kitchen_league_by_key("world-cup") or {
        "key": "world-cup",
        "name": "FIFA World Cup 2026",
        "type": "competition",
        "sport": "Soccer",
        "espn_sport": "soccer",
        "espn_league": "fifa.world",
    }
    end = now + timedelta(hours=FIFA_WORLD_CUP_2026_NEXT_WINDOW_HOURS)
    return fetch_espn_next_matches_for_source(
        source,
        now,
        end,
        team_name=FIFA_WORLD_CUP_2026["leagueName"],
        all_matches=True,
    )


def next_match_key(match):
    kickoff = parse_match_datetime(match.get("kickoffAt"))
    aliases = {
        "polska": "poland",
        "bosnia i hercegowina": "bosnia herzegovina",
        "bosnia-herzegovina": "bosnia herzegovina",
        "szwecja": "sweden",
        "rumunia": "romania",
    }

    def team_key(team):
        key = normalize_lookup_text((team or {}).get("name"))
        return aliases.get(key, key)

    return (
        (kickoff.isoformat(timespec="minutes") if kickoff else match.get("kickoffAt") or ""),
        team_key(match.get("home")),
        team_key(match.get("away")),
    )


def dedupe_next_matches(matches):
    deduped = {}
    for match in matches or []:
        deduped.setdefault(next_match_key(match), match)
    return sorted(
        deduped.values(),
        key=lambda item: parse_match_datetime(item.get("kickoffAt")) or datetime.max,
    )


def filter_kitchen_next_matches(matches):
    return [
        match for match in matches or []
        if (match.get("teamKey") or match.get("leagueKey")) not in KITCHEN_RESULTS_ONLY_LEAGUE_KEYS
    ]


def fetch_next_kitchen_matches(now=None, settings=None):
    settings = settings or read_kitchen_settings()
    now = now or datetime.now().replace(microsecond=0)
    end = now + timedelta(days=KITCHEN_NEXT_WINDOW_DAYS)
    matches = []
    thesportsdb_rate_limited = False
    try:
        matches.extend(fetch_world_cup_next_matches(now=now))
    except Exception:
        pass
    try:
        matches.extend(fetch_conifa_euro_2026_next_matches(now=now, settings=settings))
    except Exception:
        pass
    for league in selected_kitchen_competitions(settings):
        if league.get("espnNextMatches"):
            try:
                matches.extend(fetch_espn_next_matches_for_source(league, now, end, all_matches=True))
            except Exception:
                pass
        if not thesportsdb_rate_limited:
            try:
                matches.extend(fetch_thesportsdb_round_next_matches_for_competition(league, now, end))
            except Exception as exc:
                thesportsdb_rate_limited = isinstance(exc, urllib.error.HTTPError) and exc.code == 429
        if not thesportsdb_rate_limited:
            try:
                matches.extend(fetch_thesportsdb_next_matches_for_competition(league, now, end))
            except Exception as exc:
                thesportsdb_rate_limited = isinstance(exc, urllib.error.HTTPError) and exc.code == 429
    for team in selected_kitchen_next_teams(settings):
        candidates = []
        try:
            if team.get("thesportsdb_team_id") and not thesportsdb_rate_limited:
                url = f"{THESPORTSDB_API_BASE}/eventsnext.php?id={team['thesportsdb_team_id']}"
                payload = http_get_json(url, timeout=12)
                for item in payload.get("events") or []:
                    match = normalize_thesportsdb_next_event(item, team)
                    kickoff = parse_match_datetime(match.get("kickoffAt"))
                    if kickoff and now <= kickoff <= end:
                        candidates.append(match)
        except Exception:
            pass
        try:
            candidates.extend(fetch_espn_next_matches_for_source(team, now, end))
        except Exception:
            pass
        candidates.sort(key=lambda item: parse_match_datetime(item.get("kickoffAt")) or datetime.max)
        if candidates:
            matches.append(candidates[0])
    selected_league_keys = {league["key"] for league in selected_kitchen_competitions(settings)}
    for match in KITCHEN_SUPPLEMENTAL_NEXT_MATCHES:
        if selected_league_keys and match.get("teamKey") not in selected_league_keys:
            continue
        kickoff = parse_match_datetime(match.get("kickoffAt"))
        if kickoff and now <= kickoff <= end:
            matches.append(dict(match))
    return dedupe_next_matches(filter_kitchen_next_matches(matches))


def fetch_live_kitchen_matches(now=None, settings=None):
    now = now or datetime.now().replace(microsecond=0)
    settings = settings or read_kitchen_settings()
    matches = []
    errors = []
    try:
        matches.extend(fetch_espn_live_scores(now=now, settings=settings))
    except Exception as exc:
        errors.append(f"espn-live: {exc}")
    try:
        matches.extend(fetch_thesportsdb_live_scores(now=now, settings=settings))
    except Exception as exc:
        errors.append(f"thesportsdb-live: {exc}")
    matches = sort_kitchen_matches(dedupe_matches(matches))
    matches = [
        match for match in matches
        if not kitchen_live_status_is_terminal(match.get("status"), match.get("statusText"), match.get("clock"))
        and not kitchen_live_match_is_stale(match, now=now)
    ]
    matches = hydrate_kitchen_team_crests(matches, settings=settings)
    return matches, errors


def build_world_cup_countdown_slide(now=None):
    now = now or datetime.now().replace(microsecond=0)
    kickoff = parse_match_datetime(FIFA_WORLD_CUP_2026.get("kickoffAt"))
    seconds_until = None
    if kickoff:
        seconds_until = max(0, int((kickoff - now).total_seconds()))
    return {
        "type": "worldCupCountdown",
        "leagueKey": FIFA_WORLD_CUP_2026["leagueKey"],
        "leagueName": FIFA_WORLD_CUP_2026["leagueName"],
        "eyebrow": FIFA_WORLD_CUP_2026.get("eyebrow") or FIFA_WORLD_CUP_2026["leagueName"],
        "title": FIFA_WORLD_CUP_2026["title"],
        "matchupTitle": FIFA_WORLD_CUP_2026.get("matchupTitle") or "",
        "kickoffAt": kitchen_local_iso(FIFA_WORLD_CUP_2026["kickoffAt"]),
        "displayDate": FIFA_WORLD_CUP_2026["displayDate"],
        "venue": FIFA_WORLD_CUP_2026["venue"],
        "city": FIFA_WORLD_CUP_2026["city"],
        "image": FIFA_WORLD_CUP_2026["image"],
        "lockupImage": FIFA_WORLD_CUP_2026["lockupImage"],
        "home": FIFA_WORLD_CUP_2026["home"],
        "away": FIFA_WORLD_CUP_2026["away"],
        "secondsUntil": seconds_until,
    }


def world_cup_groups_in_matches(matches):
    groups = {}
    for match in [
        match for match in matches
        if match.get("leagueKey") == "world-cup"
        and match.get("group")
        and parse_match_datetime(match.get("playedAt"))
    ]:
        group = match.get("group")
        played_at = parse_match_datetime(match.get("playedAt"))
        if group and (group not in groups or played_at > groups[group]):
            groups[group] = played_at
    return [
        group for group, _played_at in sorted(
            groups.items(),
            key=lambda item: item[1],
            reverse=True,
        )
    ]


def build_kitchen_slides(matches, standings, next_matches, leaderboards=None, settings=None):
    settings = settings or read_kitchen_settings()
    next_matches = filter_kitchen_next_matches(next_matches)
    slides = []
    by_league = {}
    for match in matches:
        by_league.setdefault(match.get("leagueKey"), []).append(match)

    for league in selected_kitchen_competitions(settings):
        key = league["key"]
        league_matches = by_league.get(key, [])
        if league_matches:
            enriched_matches = []
            for match in league_matches:
                item = dict(match)
                fact = nhl_fact_for_match(match)
                if fact:
                    item["fact"] = fact
                enriched_matches.append(item)
            slides.append({
                "type": "results",
                "leagueKey": key,
                "leagueName": league["name"],
                "title": "Wyniki",
                "matches": enriched_matches,
            })

        if key == "world-cup":
            for group in world_cup_groups_in_matches(league_matches):
                standing = standings.get(f"world-cup:{group}") if isinstance(standings, dict) else None
                rows = (standing or {}).get("rows") or []
                if rows:
                    group_label = (standing or {}).get("groupLabel") or world_cup_group_label(group)
                    slides.append({
                        "type": "standings",
                        "leagueKey": f"world-cup:{group}",
                        "leagueName": league["name"],
                        "part": "world-cup-group",
                        "title": f"Tabela - {group_label}",
                        "group": group,
                        "groupLabel": group_label,
                        "rows": rows,
                        "legend": (standing or {}).get("legend") or [],
                        "complete": True,
                        "changed": False,
                    })
            continue

        if kitchen_source_is_cup(league) and not league.get("leaguePhaseTable"):
            continue

        standing = standings.get(key) if isinstance(standings, dict) else None
        sections = (standing or {}).get("sections") if isinstance(standing, dict) else None
        rows = (standing or {}).get("rows") or []
        if not sections and rows:
            snapshot = standings_snapshot_for_league(key, standing, league_matches)
            sections = (snapshot or {}).get("sections") or []
        for section in sections or []:
            section_rows = (section or {}).get("rows") or []
            if not section_rows:
                continue
            slides.append(
                {
                    "type": "standings",
                    "leagueKey": key,
                    "leagueName": league["name"],
                    "part": "changes",
                    "title": (section or {}).get("title") or "Zmiany w tabeli",
                    "rows": section_rows,
                    "legend": (section or {}).get("legend") or (standing or {}).get("legend") or [],
                    "complete": bool((section or {}).get("complete")),
                    "changed": bool((section or {}).get("changed")),
                }
            )

    for team in selected_kitchen_teams(settings):
        for match in by_league.get(team["key"], []):
            item = {"type": "match", **match}
            fact = nhl_fact_for_match(match)
            if fact:
                item["fact"] = fact
            slides.append(item)

    if next_matches:
        slides.append(
            {
                "type": "next",
                "leagueName": "Następne mecze",
                "title": f"Najbliższe {KITCHEN_NEXT_WINDOW_DAYS} dni",
                "matches": next_matches,
            }
        )
    if leaderboards and (leaderboards.get("goals") or leaderboards.get("assists")):
        slides.append({
            "type": "leaderboards",
            "leagueKey": "world-cup",
            "leagueName": leaderboards.get("leagueName") or "FIFA World Cup",
            "title": "Liderzy turnieju",
            "goals": leaderboards.get("goals") or [],
            "assists": leaderboards.get("assists") or [],
        })
    return slides


def first_scored_event(events):
    for item in events:
        if parse_optional_int(item.get("intHomeScore")) is not None and parse_optional_int(item.get("intAwayScore")) is not None:
            return item
    return events[0] if events else None


def latest_round_value(matches):
    dated = [
        match for match in matches
        if parse_match_datetime(match.get("playedAt")) is not None
    ]
    if not dated:
        return None
    dated.sort(key=lambda item: parse_match_datetime(item.get("playedAt")) or datetime.min, reverse=True)
    return dated[0].get("round")


def dedupe_matches(matches):
    seen = {}
    out = []
    for match in matches:
        key = (
            match.get("leagueKey"),
            normalize_lookup_text((match.get("home") or {}).get("name")),
            normalize_lookup_text((match.get("away") or {}).get("name")),
            str(match.get("playedAt") or "")[:10],
        )
        existing = seen.get(key)
        if existing:
            if match.get("round") and not existing.get("round"):
                existing["round"] = match.get("round")
            if match.get("competitionName") and not existing.get("competitionName"):
                existing["competitionName"] = match.get("competitionName")
            if match.get("roundType") == "cup":
                existing["roundType"] = "cup"
            if match.get("provider") == "manual":
                for side in ("home", "away"):
                    incoming_team = match.get(side) or {}
                    existing_team = existing.setdefault(side, {})
                    if incoming_team.get("name"):
                        existing_team["name"] = incoming_team["name"]
                    if incoming_team.get("crest") and not existing_team.get("crest"):
                        existing_team["crest"] = incoming_team.get("crest")
            continue
        seen[key] = match
        out.append(match)
    return out


def sort_kitchen_matches(matches):
    def key(item):
        league_index = KITCHEN_LEAGUE_ORDER.get(item.get("leagueKey"), 999)
        played_at = parse_match_datetime(item.get("playedAt")) or datetime.min
        played_score = (
            played_at.toordinal() * 86400
            + played_at.hour * 3600
            + played_at.minute * 60
            + played_at.second
        )
        return (league_index, -played_score)

    return sorted(matches, key=key)


def cached_kitchen_scores_fallback(cached, cutoff, settings, window_hours, now=None, error=None, live_matches=None):
    if not isinstance(cached, dict):
        return None
    cached_matches = cached.get("matches")
    if not isinstance(cached_matches, list):
        return None

    selected_keys = {
        source["key"]
        for source in (selected_kitchen_competitions(settings) + selected_kitchen_teams(settings))
    }
    matches = sort_kitchen_matches([
        match
        for match in cached_matches
        if match_is_recent(match, cutoff)
        and (not selected_keys or match.get("leagueKey") in selected_keys)
    ])
    next_matches = filter_kitchen_next_matches(cached.get("nextMatches"))
    live_matches = live_matches if isinstance(live_matches, list) else (
        cached.get("liveMatches") if isinstance(cached.get("liveMatches"), list) else []
    )
    matches = hydrate_kitchen_team_crests(matches, settings=settings)
    next_matches = hydrate_kitchen_team_crests(next_matches, settings=settings)
    live_matches = hydrate_kitchen_team_crests(live_matches, settings=settings)
    leaderboards = cached.get("leaderboards") if isinstance(cached.get("leaderboards"), dict) else {}
    cached_standings = cached.get("standings") if isinstance(cached.get("standings"), dict) else {}
    cached_standings = hydrate_kitchen_standing_crests(cached_standings, settings=settings)
    display_standings = standings_for_display(cached_standings, {}, matches)
    slides = build_kitchen_slides(matches, display_standings, next_matches, leaderboards=leaderboards, settings=settings)
    if not matches and not slides:
        return None

    payload = dict(cached)
    updated_at = (now or datetime.now().replace(microsecond=0)).isoformat()
    payload.update({
        "ok": True,
        "schemaVersion": KITCHEN_SCORES_SCHEMA_VERSION,
        "provider": cached.get("provider") or "cache",
        "updatedAt": updated_at,
        "mode": f"recent-{window_hours}h",
        "windowHours": window_hours,
        "settings": settings.get("sports") or {},
        "settingsSignature": kitchen_settings_signature(settings),
        "matches": matches,
        "standings": cached_standings,
        "standingChanges": {},
        "displayStandings": display_standings,
        "leaderboards": leaderboards,
        "nextMatches": next_matches,
        "liveMatches": live_matches,
        "slides": slides,
        "cached": True,
        "stale": True,
    })
    if error:
        payload["error"] = error
    return payload


_FOOTBALL_REFRESH_LOCK = threading.Lock()


def read_kitchen_scores(force=False):
    # Both desktop and tablet enter the same cache/refresh owner.
    with _FOOTBALL_REFRESH_LOCK:
        previous = read_json_file(KITCHEN_SCORES_JSON, {})
        payload = _read_kitchen_scores(force=force)
        if payload.get("stale") or payload.get("cachedScoreFallback"):
            payload["updatedAt"] = previous.get("updatedAt")
        if payload.get("cachedNextFallback"):
            payload["nextMatchesUpdatedAt"] = previous.get("nextMatchesUpdatedAt")
        if payload.get("liveError") or not payload.get("ok", True):
            payload["liveError"] = payload.get("liveError") or "Live refresh unavailable"
            payload["liveMatches"] = previous.get("liveMatches") or []
            payload["liveUpdatedAt"] = previous.get("liveUpdatedAt")
        else:
            payload["liveUpdatedAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        # Preserve results/fixture timestamps while publishing the same live snapshot
        # to the tablet response and desktop reader.
        rewrite_json_file(KITCHEN_SCORES_JSON, payload)
        return payload


def _read_kitchen_scores(force=False):
    now = datetime.now().replace(microsecond=0)
    settings = read_kitchen_settings()
    window_hours = parse_optional_int((settings.get("sports") or {}).get("windowHours")) or KITCHEN_DEFAULT_WINDOW_HOURS
    cutoff = now - timedelta(hours=window_hours)
    signature = kitchen_settings_signature(settings)
    cached = read_json_file(KITCHEN_SCORES_JSON, {})
    cached_at = parse_match_datetime(cached.get("updatedAt")) if isinstance(cached, dict) else None
    cached_slides = cached.get("slides") if isinstance(cached, dict) else None
    cached_signature = cached.get("settingsSignature") if isinstance(cached, dict) else None
    cached_schema = cached.get("schemaVersion") if isinstance(cached, dict) else None
    has_cached_slides = isinstance(cached_slides, list) and len(cached_slides) > 0
    live_matches = []
    live_errors = []
    try:
        live_matches, live_errors = fetch_live_kitchen_matches(now=now, settings=settings)
    except Exception as exc:
        live_errors = [f"live: {exc}"]
    if (
        not force
        and cached_schema == KITCHEN_SCORES_SCHEMA_VERSION
        and cached_signature == signature
        and has_cached_slides
        and cached_at
        and (now - cached_at).total_seconds() < KITCHEN_SCORES_CACHE_TTL
    ):
        if isinstance(cached.get("matches"), list):
            cached["matches"] = sort_kitchen_matches(hydrate_kitchen_team_crests([
                match for match in cached["matches"]
                if match_is_recent(match, cutoff)
            ], settings=settings))
        if isinstance(cached.get("nextMatches"), list):
            cached["nextMatches"] = hydrate_kitchen_team_crests(
                filter_kitchen_next_matches(cached["nextMatches"]), settings=settings
            )
        if isinstance(cached.get("liveMatches"), list):
            cached["liveMatches"] = hydrate_kitchen_team_crests(cached["liveMatches"], settings=settings)
        cached_standings = cached.get("standings") if isinstance(cached.get("standings"), dict) else {}
        cached["standings"] = hydrate_kitchen_standing_crests(cached_standings, settings=settings)
        cached["displayStandings"] = standings_for_display(
            cached["standings"],
            cached.get("standingChanges") or {},
            cached.get("matches") or [],
        )
        cached["slides"] = build_kitchen_slides(
            cached.get("matches") or [],
            cached["displayStandings"],
            cached.get("nextMatches") or [],
            leaderboards=cached.get("leaderboards") or {},
            settings=settings,
        )
        cached["liveMatches"] = hydrate_kitchen_team_crests(live_matches, settings=settings)
        if live_errors:
            cached["liveError"] = "; ".join(live_errors)
        else:
            cached.pop("liveError", None)
        cached["cached"] = True
        return cached

    provider = "mixed"
    error = None
    try:
        matches = []
        score_errors = []
        if api_football_key():
            provider = "api-football+fallbacks"
            try:
                matches.extend(fetch_api_football_scores(cutoff, now, settings=settings))
            except Exception as exc:
                score_errors.append(f"api-football: {exc}")
            try:
                matches.extend(fetch_thesportsdb_team_scores(cutoff, settings=settings))
            except Exception as exc:
                score_errors.append(f"thesportsdb-teams: {exc}")
            try:
                matches.extend(fetch_espn_team_scores(cutoff, now=now, settings=settings))
            except Exception as exc:
                score_errors.append(f"espn-teams: {exc}")
        try:
            espn_matches = fetch_espn_competition_scores(cutoff, now=now, settings=settings)
            if espn_matches:
                matches.extend(espn_matches)
        except Exception as exc:
            score_errors.append(f"espn: {exc}")
        try:
            fallback_matches = fetch_thesportsdb_scores(cutoff, now=now, settings=settings)
            if fallback_matches:
                matches.extend(fallback_matches)
        except Exception as exc:
            score_errors.append(f"thesportsdb: {exc}")
        try:
            conifa_matches = fetch_conifa_euro_2026_scores(cutoff, now=now, settings=settings)
            if conifa_matches:
                matches.extend(conifa_matches)
        except Exception as exc:
            score_errors.append(f"conifa-euro-2026: {exc}")
        try:
            matches.extend(fetch_supplemental_kitchen_scores(cutoff, settings=settings))
        except Exception as exc:
            score_errors.append(f"supplemental: {exc}")
        cached_score_fallback = False
        if not matches and score_errors and isinstance(cached, dict) and isinstance(cached.get("matches"), list):
            selected_keys = {
                source["key"]
                for source in (selected_kitchen_competitions(settings) + selected_kitchen_teams(settings))
            }
            matches = [
                match for match in cached.get("matches") or []
                if match_is_recent(match, cutoff)
                and (not selected_keys or match.get("leagueKey") in selected_keys)
            ]
            cached_score_fallback = bool(matches)
        football_input_count = len(matches)
        matches = sort_kitchen_matches(dedupe_matches(matches))
        matches = hydrate_kitchen_team_crests(matches, settings=settings)

        next_end = now + timedelta(days=KITCHEN_NEXT_WINDOW_DAYS)
        selected_next_keys = {
            source["key"]
            for source in (selected_kitchen_competitions(settings) + selected_kitchen_next_teams(settings))
        }
        cached_next_matches = [
            match for match in (cached.get("nextMatches") or [])
            if (kickoff := parse_match_datetime(match.get("kickoffAt")))
            and now <= kickoff <= next_end
            and (not selected_next_keys or (match.get("teamKey") or match.get("leagueKey")) in selected_next_keys)
            and (match.get("teamKey") or match.get("leagueKey")) not in KITCHEN_RESULTS_ONLY_LEAGUE_KEYS
        ] if isinstance(cached, dict) and isinstance(cached.get("nextMatches"), list) else []
        next_cache_at = parse_match_datetime(
            cached.get("nextMatchesUpdatedAt") or cached.get("updatedAt")
        ) if isinstance(cached, dict) else None
        next_cache_fresh = bool(
            cached_next_matches
            and next_cache_at
            and (now - next_cache_at).total_seconds() < KITCHEN_NEXT_MATCHES_CACHE_TTL
        )
        next_matches = list(cached_next_matches) if next_cache_fresh else fetch_next_kitchen_matches(now=now, settings=settings)
        cached_next_fallback = False
        if not next_matches and cached_next_matches:
            next_matches = list(cached_next_matches)
            cached_next_fallback = True
        next_matches_updated_at = (
            cached.get("nextMatchesUpdatedAt") or cached.get("updatedAt")
            if next_cache_fresh or cached_next_fallback
            else now.isoformat()
        )
        next_matches = dedupe_next_matches(next_matches)
        next_matches = hydrate_kitchen_team_crests(next_matches, settings=settings)

        previous_standings = (
            cached.get("standings")
            if isinstance(cached, dict) and cached_signature == signature and isinstance(cached.get("standings"), dict)
            else {}
        )
        standings_enabled = set((settings.get("sports") or {}).get("standingsLeagueKeys") or [])
        if "world-cup" in set((settings.get("sports") or {}).get("enabledLeagueKeys") or []):
            standings_enabled.add("world-cup")
        standings_cache_at = parse_match_datetime(
            cached.get("standingsUpdatedAt") or cached.get("updatedAt")
        ) if isinstance(cached, dict) else None
        standings_cache_fresh = bool(
            standings_cache_at
            and (now - standings_cache_at).total_seconds() < KITCHEN_STANDINGS_CACHE_TTL
        )
        standings = {
            league_key: previous_standings[league_key]
            for league_key in standings_enabled
            if standings_cache_fresh
            and league_key in previous_standings
            and len((previous_standings[league_key] or {}).get("rows") or []) >= KITCHEN_STANDINGS_MIN_ROWS
        }
        standings_to_fetch = standings_enabled - set(standings)
        if standings_to_fetch:
            standings.update(fetch_kitchen_standings(settings=settings, league_keys=standings_to_fetch))
        standings_updated_at = (
            cached.get("standingsUpdatedAt") or cached.get("updatedAt")
            if not standings_to_fetch
            else now.isoformat()
        )
        for league_key in standings_enabled:
            current_rows = ((standings.get(league_key) or {}).get("rows") or [])
            previous = previous_standings.get(league_key) or {}
            previous_rows = previous.get("rows") or []
            if len(current_rows) < KITCHEN_STANDINGS_MIN_ROWS <= len(previous_rows):
                standings[league_key] = {**previous, "stale": True}
        standings = hydrate_kitchen_standing_crests(standings, settings=settings)
        standing_changes = standings_with_position_changes(
            standings,
            previous_standings,
            matches,
        )
        try:
            leaderboards = fetch_world_cup_leaderboards(settings=settings)
        except Exception as exc:
            leaderboards = cached.get("leaderboards") if isinstance(cached, dict) and isinstance(cached.get("leaderboards"), dict) else {}
            score_errors.append(f"world-cup-leaderboards: {exc}")
        display_standings = standings_for_display(standings, standing_changes, matches)
        slides = build_kitchen_slides(matches, display_standings, next_matches, leaderboards=leaderboards, settings=settings)
        payload = {
            "ok": True,
            "schemaVersion": KITCHEN_SCORES_SCHEMA_VERSION,
            "provider": provider,
            "updatedAt": now.isoformat(),
            "mode": f"recent-{window_hours}h",
            "windowHours": window_hours,
            "settings": settings.get("sports") or {},
            "settingsSignature": signature,
            "matches": matches,
            "standings": standings,
            "standingsUpdatedAt": standings_updated_at,
            "standingChanges": standing_changes,
            "displayStandings": display_standings,
            "leaderboards": leaderboards,
            "nextMatches": next_matches,
            "nextMatchesUpdatedAt": next_matches_updated_at,
            "liveMatches": live_matches,
            "liveError": "; ".join(live_errors) if live_errors else None,
            "sourceErrors": score_errors,
            "cachedScoreFallback": cached_score_fallback,
            "cachedNextFallback": cached_next_fallback,
            "slides": slides,
            "cached": False,
        }
        rewrite_json_file(KITCHEN_SCORES_JSON, payload)
        try:
            record_football_sync(FOOTBALL_DIAGNOSTICS_JSON, payload, football_input_count)
        except OSError:
            pass
        try:
            store_football_snapshot(payload)
        except (OSError, sqlite3.Error, ValueError) as exc:
            print(f"football store ingest failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return payload
    except Exception as exc:
        error = str(exc)

    fallback = cached_kitchen_scores_fallback(cached, cutoff, settings, window_hours, now=now, error=error, live_matches=live_matches)
    if fallback:
        return fallback

    if (
        isinstance(cached, dict)
        and cached.get("matches") is not None
        and cached_schema == KITCHEN_SCORES_SCHEMA_VERSION
        and cached_signature == signature
    ):
        if isinstance(cached.get("matches"), list):
            cached["matches"] = sort_kitchen_matches([
                match for match in cached["matches"]
                if match_is_recent(match, cutoff)
            ])
        if not isinstance(cached.get("slides"), list):
            cached["slides"] = [{"type": "match", **match} for match in cached.get("matches") or []]
        cached["ok"] = True
        cached["cached"] = True
        cached["stale"] = True
        cached["error"] = error
        cached["windowHours"] = window_hours
        return cached
    return {
        "ok": False,
        "error": error or "Could not fetch scores",
        "windowHours": window_hours,
        "matches": [],
        "liveMatches": [],
        "slides": [],
    }


def kitchen_source_debug_payload(source, cached):
    matches = cached.get("matches") if isinstance(cached, dict) and isinstance(cached.get("matches"), list) else []
    live_matches = cached.get("liveMatches") if isinstance(cached, dict) and isinstance(cached.get("liveMatches"), list) else []
    key = source.get("key")
    providers = []
    if source.get("api_football_id"):
        providers.append(f"API-Football #{source.get('api_football_id')}")
    if source.get("thesportsdb_id"):
        providers.append(f"TheSportsDB #{source.get('thesportsdb_id')}")
    if source.get("espn_sport") and source.get("espn_league"):
        providers.append(f"ESPN {source.get('espn_sport')}/{source.get('espn_league')}")
    if source.get("thesportsdb_team_id"):
        providers.append(f"TheSportsDB team #{source.get('thesportsdb_team_id')}")
    if key == CONIFA_EURO_2026_KEY:
        providers.append("Wikipedia wikitext")
    return {
        "key": key,
        "name": source.get("name"),
        "type": source.get("type"),
        "sport": source.get("sport"),
        "country": source.get("country") or kitchen_league_group(source),
        "providers": providers or ["brak skonfigurowanego zrodla"],
        "cachedMatches": len([match for match in matches if match.get("leagueKey") == key]),
        "cachedLiveMatches": len([match for match in live_matches if match.get("leagueKey") == key]),
    }


def read_kitchen_debug():
    settings = read_kitchen_settings()
    cached = read_json_file(KITCHEN_SCORES_JSON, {})
    sports = settings.get("sports") or {}
    selected_sources = selected_kitchen_competitions(settings) + selected_kitchen_teams(settings)
    errors = []
    if isinstance(cached, dict):
        if cached.get("error"):
            errors.append(cached.get("error"))
        if cached.get("liveError"):
            errors.append(cached.get("liveError"))
        errors.extend(cached.get("sourceErrors") or [])
    return {
        "ok": True,
        "updatedAt": datetime.now().replace(microsecond=0).isoformat(),
        "cacheUpdatedAt": cached.get("updatedAt") if isinstance(cached, dict) else "",
        "provider": cached.get("provider") if isinstance(cached, dict) else "",
        "windowHours": sports.get("windowHours") or KITCHEN_DEFAULT_WINDOW_HOURS,
        "selectedLeagueKeys": sports.get("enabledLeagueKeys") or [],
        "selectedTeamKeys": sports.get("enabledTeamKeys") or [],
        "sources": [kitchen_source_debug_payload(source, cached if isinstance(cached, dict) else {}) for source in selected_sources],
        "errors": [str(error) for error in errors if error],
    }


def football_store():
    global _FOOTBALL_STORE
    if _FOOTBALL_STORE is None:
        with _FOOTBALL_STORE_LOCK:
            if _FOOTBALL_STORE is None:
                _FOOTBALL_STORE = FootballStore(ROOT / "data" / "football.sqlite")
    return _FOOTBALL_STORE


def store_football_snapshot(scores):
    settings = read_json_file(KITCHEN_SETTINGS_JSON, {})
    crests = read_json_file(KITCHEN_TEAM_CRESTS_JSON, {})
    diagnostics = read_json_file(FOOTBALL_DIAGNOSTICS_JSON, {})
    catalog = [{**item, "country": item.get("country") or kitchen_league_group(item)}
               for item in KITCHEN_LEAGUES] + KITCHEN_NEXT_TEAMS
    view = build_football_snapshot(scores, settings, catalog, crests, diagnostics,
                                   api_key_configured=bool(api_football_key()),
                                   cooldowns=FOOTBALL_REQUEST_CONTROL.cooldowns(),
                                   preferred_crests=KITCHEN_TEAM_CRESTS,
                                   request_usage=FOOTBALL_REQUEST_CONTROL.usage())
    try:
        football_store().ingest(view)
    except (OSError, sqlite3.Error) as exc:
        view["sourceErrors"].append(f"football store: {type(exc).__name__}")
        view["storageError"] = type(exc).__name__
        print(f"football store ingest failed: {type(exc).__name__}: {exc}", file=sys.stderr)
    return view


def read_football_dashboard():
    """Desktop reads local cache and history without initiating provider requests."""
    view = store_football_snapshot(read_json_file(KITCHEN_SCORES_JSON, {}))
    current_matches = list(view["matches"])
    try:
        store = football_store()
        view["matches"] = merge_match_history(view["matches"], store.matches())
        view["storedData"] = store.counts()
        view["mappings"] = store.mappings()
        view["mappingConflicts"] = store.mapping_conflicts()
    except (OSError, sqlite3.Error) as exc:
        view["sourceErrors"].append(f"football store read: {type(exc).__name__}")
        view["storageError"] = type(exc).__name__
        view["storedData"] = {}
        view["mappings"] = []
        view["mappingConflicts"] = []
    view["duplicateCandidates"] = possible_duplicate_matches(view["matches"])
    missing = []
    for club in view["clubs"]:
        if not club.get("followed") or any(club["key"] in row.get("clubKeys", []) for row in current_matches):
            continue
        historical = sum(club["key"] in row.get("clubKeys", []) for row in view["matches"])
        reason = ("No configured provider team ID" if not club.get("providerIds") else
                  f"No match in the current Kitchen snapshot; {historical} in local history. The recent-result window is {view['following']['windowHours']} h.")
        missing.append({"type": "club", "key": club["key"], "name": club["name"], "explanation": reason})
    for competition in view["competitions"]:
        if competition.get("followed") and not any(row.get("competitionKey") == competition["key"] for row in current_matches):
            missing.append({"type": "competition", "key": competition["key"], "name": competition["name"],
                            "explanation": "No match in the current Kitchen snapshot; check the selected time window, provider request history and current errors."})
    view["missingData"] = missing
    view["storageNote"] = ("SQLite is unavailable; this view currently shows the Kitchen JSON cache only."
                           if view.get("storageError") else
                           "Kitchen JSON is the current cache; data/football.sqlite retains normalized matches, clubs, competitions and provider mappings after the Kitchen time window rolls forward.")
    return view


def read_football_competition_table(key):
    """On-demand table via existing adapters, published back to the shared cache."""
    with _FOOTBALL_REFRESH_LOCK:
        scores = read_json_file(KITCHEN_SCORES_JSON, {})
        existing = (scores.get("standings") or {}).get(key) or {}
        stamp = parse_match_datetime(existing.get("updatedAt") or scores.get("standingsUpdatedAt"))
        if existing.get("rows") and stamp and not existing.get("stale") and (datetime.now() - stamp).total_seconds() < KITCHEN_STANDINGS_CACHE_TTL:
            return {**existing, "updatedAt": existing.get("updatedAt") or scores.get("standingsUpdatedAt")}
        settings = read_kitchen_settings()
        # Browse untracked competitions without changing favourites.
        settings = {**settings, "sports": {**settings.get("sports", {}), "enabledLeagueKeys": [key], "standingsLeagueKeys": [key]}}
        tables = fetch_kitchen_standings(settings=settings, league_keys={key})
        table = tables.get(key)
        if not table or not table.get("rows"):
            raise ValueError("Competition table unavailable")
        table = {**table, "updatedAt": datetime.now().isoformat(timespec="seconds")}
        scores["standings"] = {**scores.get("standings", {}), key: table}
        rewrite_json_file(KITCHEN_SCORES_JSON, scores)
        return table


_FOOTBALL_HUB = None
_FOOTBALL_HUB_LOCK = threading.Lock()


def football_hub():
    global _FOOTBALL_HUB
    with _FOOTBALL_HUB_LOCK:
        if _FOOTBALL_HUB is None:
            _FOOTBALL_HUB = FootballHub(football_store(), http_get_json,
                KITCHEN_LEAGUES + KITCHEN_NEXT_TEAMS, THESPORTSDB_API_BASE, api_football_key(), standings_fetch=read_football_competition_table)
        return _FOOTBALL_HUB


def read_football_settings():
    raw = read_json_file(FOOTBALL_SETTINGS_JSON, {})
    if not isinstance(raw, dict):
        raw = {}
    max_slides = raw.get("kitchenMaxSlides")
    return {
        "ok": True,
        "kitchenMaxSlides": max_slides if isinstance(max_slides, int) and not isinstance(max_slides, bool) and 1 <= max_slides <= 12 else 6,
        "kitchenShowStandings": raw.get("kitchenShowStandings") if isinstance(raw.get("kitchenShowStandings"), bool) else True,
        "kitchenShowUpcoming": raw.get("kitchenShowUpcoming") if isinstance(raw.get("kitchenShowUpcoming"), bool) else True,
    }


def write_football_settings(payload):
    if not isinstance(payload, dict):
        raise ValueError("Invalid football settings")
    current = read_football_settings()
    result = {}
    for key in ("kitchenShowStandings", "kitchenShowUpcoming"):
        value = payload.get(key, current[key])
        if not isinstance(value, bool):
            raise ValueError(f"Invalid {key}")
        result[key] = value
    max_slides = payload.get("kitchenMaxSlides", current["kitchenMaxSlides"])
    if not isinstance(max_slides, int) or isinstance(max_slides, bool) or not 1 <= max_slides <= 12:
        raise ValueError("kitchenMaxSlides must be 1-12")
    result["kitchenMaxSlides"] = max_slides
    rewrite_json_file(FOOTBALL_SETTINGS_JSON, result)
    return read_football_settings()


def google_calendar_config():
    calendars_raw = os.environ.get("GOOGLE_CALENDAR_IDS") or os.environ.get("GOOGLE_CALENDAR_ID") or "primary"
    calendars = [
        item.strip()
        for item in re.split(r"[,;\n]+", calendars_raw)
        if item.strip()
    ]
    return {
        "client_id": os.environ.get("GOOGLE_CALENDAR_CLIENT_ID", "").strip(),
        "client_secret": os.environ.get("GOOGLE_CALENDAR_CLIENT_SECRET", "").strip(),
        "redirect_uri": (
            os.environ.get("GOOGLE_CALENDAR_REDIRECT_URI", "").strip()
            or "http://127.0.0.1:8000/api/google-calendar/oauth/callback"
        ),
        "calendar_ids": calendars or ["primary"],
        "auto_calendars": any(item.lower() in {"auto", "*", "all"} for item in calendars),
    }


def google_calendar_is_configured():
    config = google_calendar_config()
    return bool(config["client_id"] and config["client_secret"])


def read_google_calendar_state():
    data = read_json_file(GOOGLE_CALENDAR_STATE_JSON, {})
    return data if isinstance(data, dict) else {}


def write_google_calendar_state(state):
    rewrite_json_file(GOOGLE_CALENDAR_STATE_JSON, state)


def parse_google_calendar_state_datetime(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def google_calendar_list_is_stale(state):
    calendars = state.get("available_calendars")
    if not isinstance(calendars, list) or not calendars:
        return True
    synced_at = parse_google_calendar_state_datetime(state.get("calendar_list_sync_at"))
    if not synced_at:
        return True
    return datetime.now() - synced_at > timedelta(seconds=GOOGLE_CALENDAR_LIST_REFRESH_SECONDS)


def google_calendar_sync_is_fresh(state):
    synced_at = parse_google_calendar_state_datetime(state.get("last_sync_at"))
    if not synced_at:
        return False
    return datetime.now() - synced_at < timedelta(seconds=GOOGLE_CALENDAR_SYNC_MIN_INTERVAL_SECONDS)


def write_google_calendar_sync_state(state):
    latest = read_google_calendar_state()
    merged = dict(latest)

    latest_calendars = latest.get("calendars") if isinstance(latest.get("calendars"), dict) else {}
    sync_calendars = state.get("calendars") if isinstance(state.get("calendars"), dict) else {}
    merged["calendars"] = {**latest_calendars, **sync_calendars}

    if state.get("last_sync_at"):
        merged["last_sync_at"] = state.get("last_sync_at")

    write_google_calendar_state(merged)


def read_google_calendar_cache():
    data = read_json_file(GOOGLE_CALENDAR_CACHE_JSON, {"events": {}})
    if not isinstance(data, dict):
        return {"events": {}}
    if not isinstance(data.get("events"), dict):
        data["events"] = {}
    return data


def write_google_calendar_cache(cache):
    cache["schemaVersion"] = GOOGLE_CALENDAR_CACHE_SCHEMA_VERSION
    cache["updatedAt"] = datetime.now().isoformat(timespec="seconds")
    rewrite_json_file(GOOGLE_CALENDAR_CACHE_JSON, cache)


def read_google_calendar_overrides():
    data = read_json_file(GOOGLE_CALENDAR_OVERRIDES_JSON, {"events": {}})
    if not isinstance(data, dict):
        return {"events": {}}
    if not isinstance(data.get("events"), dict):
        data["events"] = {}
    return data


def write_google_calendar_overrides(overrides):
    overrides["updatedAt"] = datetime.now().isoformat(timespec="seconds")
    rewrite_json_file(GOOGLE_CALENDAR_OVERRIDES_JSON, overrides)


def google_calendar_cache_needs_schema_refresh():
    cache = read_google_calendar_cache()
    try:
        version = int(cache.get("schemaVersion") or 0)
    except (TypeError, ValueError):
        version = 0
    return version < GOOGLE_CALENDAR_CACHE_SCHEMA_VERSION and bool(cache.get("events"))


def google_calendar_status():
    config = google_calendar_config()
    state = read_google_calendar_state()
    calendars = state.get("calendars") if isinstance(state.get("calendars"), dict) else {}
    cache = read_google_calendar_cache()
    granted_scope = str(state.get("scope") or "")
    return {
        "configured": google_calendar_is_configured(),
        "connected": bool(state.get("refresh_token")),
        "calendarIds": config["calendar_ids"],
        "autoCalendars": config["auto_calendars"],
        "redirectUri": config["redirect_uri"],
        "scope": GOOGLE_CALENDAR_SCOPE,
        "grantedScope": granted_scope,
        "tasksScopeGranted": "https://www.googleapis.com/auth/tasks.readonly" in granted_scope.split(),
        "sheetsScopeGranted": "https://www.googleapis.com/auth/spreadsheets.readonly" in granted_scope.split(),
        "lastSyncAt": state.get("last_sync_at"),
        "calendarListSyncAt": state.get("calendar_list_sync_at"),
        "calendarListStale": google_calendar_list_is_stale(state),
        "cacheUpdatedAt": cache.get("updatedAt"),
        "cachedEvents": len(cache.get("events", {})),
        "availableCalendars": state.get("available_calendars") if isinstance(state.get("available_calendars"), list) else [],
        "calendars": {
            calendar_id: {
                "lastSyncAt": value.get("last_sync_at"),
                "hasSyncToken": bool(value.get("syncToken")),
            }
            for calendar_id, value in calendars.items()
            if isinstance(value, dict)
        },
    }
    return add_world_cup_metadata(
        match,
        competition.get("altGameNote"),
        season.get("slug"),
        season.get("type"),
        league.get("name"),
    )


def make_google_calendar_auth_url():
    config = google_calendar_config()
    if not google_calendar_is_configured():
        raise ValueError("Missing GOOGLE_CALENDAR_CLIENT_ID or GOOGLE_CALENDAR_CLIENT_SECRET")

    state_token = base64.urlsafe_b64encode(os.urandom(24)).decode("ascii").rstrip("=")
    state = read_google_calendar_state()
    state["pending_oauth_state"] = state_token
    state["pending_oauth_at"] = datetime.now().isoformat(timespec="seconds")
    write_google_calendar_state(state)

    params = {
        "client_id": config["client_id"],
        "redirect_uri": config["redirect_uri"],
        "response_type": "code",
        "scope": GOOGLE_CALENDAR_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state_token,
    }
    return f"{GOOGLE_CALENDAR_AUTH_URL}?{urllib.parse.urlencode(params)}"


def handle_google_calendar_callback(query):
    config = google_calendar_config()
    if not google_calendar_is_configured():
        raise ValueError("Google Calendar OAuth is not configured")

    code = (query.get("code") or [""])[0]
    incoming_state = (query.get("state") or [""])[0]
    if not code:
        raise ValueError("Missing OAuth code")

    state = read_google_calendar_state()
    expected_state = state.get("pending_oauth_state")
    if not expected_state or incoming_state != expected_state:
        raise ValueError("OAuth state mismatch")

    token = http_post_form_json(
        GOOGLE_CALENDAR_TOKEN_URL,
        {
            "client_id": config["client_id"],
            "client_secret": config["client_secret"],
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": config["redirect_uri"],
        },
    )
    if not token.get("access_token"):
        raise ValueError("Google did not return an access token")

    state["access_token"] = token["access_token"]
    if token.get("refresh_token"):
        state["refresh_token"] = token["refresh_token"]
    state["expires_at"] = int(time.time()) + int(token.get("expires_in") or 3600) - 60
    state["scope"] = token.get("scope")
    state["token_type"] = token.get("token_type")
    state["connected_at"] = datetime.now().isoformat(timespec="seconds")
    state.pop("pending_oauth_state", None)
    state.pop("pending_oauth_at", None)
    write_google_calendar_state(state)
    return google_calendar_status()


def google_calendar_access_token():
    config = google_calendar_config()
    state = read_google_calendar_state()
    if not state.get("refresh_token") and not state.get("access_token"):
        raise ValueError("Google Calendar is not connected")

    if state.get("access_token") and int(state.get("expires_at") or 0) > int(time.time()) + 60:
        return state["access_token"]

    if not state.get("refresh_token"):
        raise ValueError("Missing Google refresh token. Reconnect Google Calendar.")

    token = http_post_form_json(
        GOOGLE_CALENDAR_TOKEN_URL,
        {
            "client_id": config["client_id"],
            "client_secret": config["client_secret"],
            "refresh_token": state["refresh_token"],
            "grant_type": "refresh_token",
        },
    )
    if not token.get("access_token"):
        raise ValueError("Google did not refresh the access token")

    state["access_token"] = token["access_token"]
    state["expires_at"] = int(time.time()) + int(token.get("expires_in") or 3600) - 60
    state["token_type"] = token.get("token_type", state.get("token_type"))
    write_google_calendar_state(state)
    return state["access_token"]


def google_calendar_api_request(method, path, query=None, payload=None):
    token = google_calendar_access_token()
    url = f"{GOOGLE_CALENDAR_API_BASE}{path}"
    if query:
        url = f"{url}?{urllib.parse.urlencode(query)}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    return http_request_json(url, method=method, headers=headers, payload=payload, timeout=25)


def google_tasks_api_request(method, path, query=None, payload=None):
    token = google_calendar_access_token()
    url = f"{GOOGLE_TASKS_API_BASE}{path}"
    if query:
        url = f"{url}?{urllib.parse.urlencode(query)}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    return http_request_json(url, method=method, headers=headers, payload=payload, timeout=25)


def google_sheets_api_request(method, path, query=None, payload=None):
    token = google_calendar_access_token()
    url = f"{GOOGLE_SHEETS_API_BASE}{path}"
    if query:
        url = f"{url}?{urllib.parse.urlencode(query)}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    return http_request_json(url, method=method, headers=headers, payload=payload, timeout=25)


def cinema_city_sheet_range():
    sheet_name = os.environ.get("CINEMA_CITY_SHEET_NAME", CINEMA_CITY_DEFAULT_SHEET_NAME).strip() or CINEMA_CITY_DEFAULT_SHEET_NAME
    raw_range = os.environ.get("CINEMA_CITY_SHEET_RANGE", CINEMA_CITY_DEFAULT_SHEET_RANGE).strip() or CINEMA_CITY_DEFAULT_SHEET_RANGE
    return f"{sheet_name}!{raw_range}"


def cinema_city_sheet_config():
    return {
        "spreadsheet_id": os.environ.get("CINEMA_CITY_SHEET_ID", CINEMA_CITY_DEFAULT_SHEET_ID).strip() or CINEMA_CITY_DEFAULT_SHEET_ID,
        "sheet_name": os.environ.get("CINEMA_CITY_SHEET_NAME", CINEMA_CITY_DEFAULT_SHEET_NAME).strip() or CINEMA_CITY_DEFAULT_SHEET_NAME,
        "range": os.environ.get("CINEMA_CITY_SHEET_RANGE", CINEMA_CITY_DEFAULT_SHEET_RANGE).strip() or CINEMA_CITY_DEFAULT_SHEET_RANGE,
        "watched_start_cell": os.environ.get("CINEMA_CITY_WATCHED_START_CELL", "D2").strip() or "D2",
        "average_cell": os.environ.get("CINEMA_CITY_AVERAGE_CELL", "E2").strip() or "E2",
    }


def cinema_city_column_index(value):
    letters = re.sub(r"[^A-Za-z]", "", str(value or "")).upper()
    if not letters:
        return 0
    index = 0
    for letter in letters:
        index = index * 26 + (ord(letter) - ord("A") + 1)
    return index - 1


def cinema_city_parse_a1_cell(value):
    match = re.match(r"^\s*([A-Za-z]+)(\d+)\s*$", str(value or ""))
    if not match:
        return None
    row = int(match.group(2))
    if row < 1:
        return None
    return {
        "column": cinema_city_column_index(match.group(1)),
        "row": row - 1,
    }


def cinema_city_parse_range_start(value):
    raw = str(value or "").split("!", 1)[-1].split(":", 1)[0]
    match = re.match(r"^\s*([A-Za-z]*)(\d*)\s*$", raw)
    if not match:
        return {"column": 0, "row": 0}
    return {
        "column": cinema_city_column_index(match.group(1)),
        "row": int(match.group(2)) - 1 if match.group(2) else 0,
    }


def cinema_city_cell_value(rows, range_name, cell_name):
    cell = cinema_city_parse_a1_cell(cell_name)
    if not cell:
        return None
    start = cinema_city_parse_range_start(range_name)
    row_index = cell["row"] - start["row"]
    column_index = cell["column"] - start["column"]
    if row_index < 0 or column_index < 0:
        return None
    if row_index >= len(rows) or not isinstance(rows[row_index], list):
        return None
    row = rows[row_index]
    return row[column_index] if column_index < len(row) else None


def cinema_city_count_cells_from(rows, range_name, start_cell):
    cell = cinema_city_parse_a1_cell(start_cell)
    if not cell:
        return 0
    start = cinema_city_parse_range_start(range_name)
    row_index = cell["row"] - start["row"]
    column_index = cell["column"] - start["column"]
    if row_index < 0 or column_index < 0:
        return 0
    count = 0
    for row in rows[row_index:]:
        if not isinstance(row, list):
            continue
        value = row[column_index] if column_index < len(row) else ""
        if cinema_city_is_watched_movie_cell(value):
            count += 1
    return count


def cinema_city_parse_number(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value or "").strip()
    if not text:
        return None
    cleaned = re.sub(r"[^0-9,.\-]", "", text)
    if not cleaned:
        return None
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    else:
        cleaned = cleaned.replace(",", ".")
    try:
        number = float(cleaned)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def cinema_city_is_watched_movie_cell(value):
    text = str(value or "").strip()
    if not text:
        return False
    normalized = re.sub(r"\s+", " ", text).strip().lower()
    header_markers = {
        "film",
        "films",
        "movie",
        "movies",
        "watched",
        "watched movies",
        "obejrzane",
        "obejrzane filmy",
        "filmy obejrzane",
    }
    return normalized not in header_markers


def cinema_city_parse_period_from_header(value):
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    match = re.match(r"^watched\s+(.+?)\s*-\s*(.+)$", text, flags=re.IGNORECASE)
    if not match:
        return None
    start = cinema_city_parse_month_day(match.group(1))
    end = cinema_city_parse_month_day(match.group(2))
    if not start or not end:
        return None
    return {
        "raw": text,
        "startMonth": start[0],
        "startDay": start[1],
        "endMonth": end[0],
        "endDay": end[1],
    }


def cinema_city_parse_month_day(value):
    match = re.search(r"\b([A-Za-z]+)\s+(\d{1,2})\b", str(value or "").strip())
    if not match:
        return None
    month_name = match.group(1).lower()
    months = {
        "jan": 1, "january": 1,
        "feb": 2, "february": 2,
        "mar": 3, "march": 3,
        "apr": 4, "april": 4,
        "may": 5,
        "jun": 6, "june": 6,
        "jul": 7, "july": 7,
        "aug": 8, "august": 8,
        "sep": 9, "sept": 9, "september": 9,
        "oct": 10, "october": 10,
        "nov": 11, "november": 11,
        "dec": 12, "december": 12,
    }
    month = months.get(month_name)
    day = int(match.group(2))
    if not month or day < 1 or day > 31:
        return None
    return month, day


def cinema_city_period_dates(period, reference_date):
    for start_year in (reference_date.year, reference_date.year - 1, reference_date.year + 1):
        try:
            start = date(start_year, period["startMonth"], period["startDay"])
            end_year = start_year
            if (period["endMonth"], period["endDay"]) <= (period["startMonth"], period["startDay"]):
                end_year += 1
            end = date(end_year, period["endMonth"], period["endDay"])
        except ValueError:
            continue
        if start <= reference_date < end:
            return start, end
    return None, None


def cinema_city_period_label(start, end):
    if not start or not end:
        return ""
    months = {
        1: "sty", 2: "lut", 3: "mar", 4: "kwi", 5: "maj", 6: "cze",
        7: "lip", 8: "sie", 9: "wrz", 10: "paź", 11: "lis", 12: "gru",
    }
    return f"w okresie {start.day} {months.get(start.month, start.month)} - {end.day} {months.get(end.month, end.month)}"


def cinema_city_find_active_watched_columns(rows, reference_date):
    headers = rows[0] if rows and isinstance(rows[0], list) else []
    candidates = []
    for index, header in enumerate(headers):
        period = cinema_city_parse_period_from_header(header)
        if not period:
            continue
        start, end = cinema_city_period_dates(period, reference_date)
        price_header = headers[index + 1] if index + 1 < len(headers) else ""
        price_matches = str(price_header or "").strip().lower().startswith("price per ticket")
        candidate = {
            "watched_index": index,
            "price_index": index + 1 if price_matches else None,
            "period": period,
            "start": start,
            "end": end,
            "active": bool(start and end),
        }
        candidates.append(candidate)
    active = next((candidate for candidate in candidates if candidate["active"]), None)
    if active:
        return active
    return candidates[-1] if candidates else {"watched_index": 0, "price_index": 1, "period": None, "start": None, "end": None}


def read_cinema_city_filters():
    config = cinema_city_sheet_config()
    range_name = cinema_city_sheet_range()
    encoded_range = urllib.parse.quote(range_name, safe="")
    data = google_sheets_api_request(
        "GET",
        f"/spreadsheets/{urllib.parse.quote(config['spreadsheet_id'], safe='')}/values/{encoded_range}",
        query={
            "majorDimension": "ROWS",
            "valueRenderOption": "FORMATTED_VALUE",
        },
    )
    rows = data.get("values") if isinstance(data, dict) else []
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], list):
        raise ValueError("Cinema City Filters sheet is empty")

    aliases = {
        "watched": "watched",
        "never watch": "neverWatch",
        "do not watch": "neverWatch",
        "kids keywords": "kidsKeywords",
        "watchedsubscription": "watchedSubscription",
        "watched subscription": "watchedSubscription",
    }
    columns = {}
    for index, header in enumerate(rows[0]):
        field = aliases.get(normalize_filter_text(header))
        if field:
            columns[field] = index
    required = {"watched", "neverWatch", "kidsKeywords", "watchedSubscription"}
    missing = sorted(required - set(columns))
    if missing:
        raise ValueError(f"Cinema City Filters sheet is missing columns: {', '.join(missing)}")

    filters = {field: [] for field in required}
    seen = {field: set() for field in required}
    for row in rows[1:]:
        if not isinstance(row, list):
            continue
        for field, column_index in columns.items():
            value = str(row[column_index] if column_index < len(row) else "").strip()
            normalized = normalize_filter_text(value)
            if value and normalized and normalized not in seen[field]:
                filters[field].append(value)
                seen[field].add(normalized)
    return filters


def read_cinema_city_monthly_stats():
    config = cinema_city_sheet_config()
    spreadsheet_id = config["spreadsheet_id"]
    if not spreadsheet_id:
        raise ValueError("Missing CINEMA_CITY_SHEET_ID")
    range_name = cinema_city_sheet_range()
    encoded_range = urllib.parse.quote(range_name, safe="")
    data = google_sheets_api_request(
        "GET",
        f"/spreadsheets/{urllib.parse.quote(spreadsheet_id, safe='')}/values/{encoded_range}",
        query={
            "majorDimension": "ROWS",
            "valueRenderOption": "UNFORMATTED_VALUE",
        },
    )
    rows = data.get("values") if isinstance(data, dict) else []
    if not isinstance(rows, list):
        rows = []

    watched_start_cell = config["watched_start_cell"]
    average_cell = config["average_cell"]
    average_cell_value = cinema_city_cell_value(rows, range_name, average_cell)
    watched_count = cinema_city_count_cells_from(rows, range_name, watched_start_cell)
    price_per_film = cinema_city_parse_number(average_cell_value)

    return {
        "ok": True,
        "configured": True,
        "watchedCount": watched_count,
        "pricePerFilm": price_per_film,
        "updatedAt": datetime.now().isoformat(timespec="seconds"),
        "source": "google_sheets",
        "spreadsheetId": spreadsheet_id,
        "sheetName": config["sheet_name"],
        "range": range_name,
        "watchedStartCell": watched_start_cell,
        "averageCell": average_cell,
        "averageCellValue": average_cell_value,
        "periodLabel": "",
        "periodHeader": None,
    }


def spotify_config():
    redirect_uri = (
        os.environ.get("SPOTIFY_REDIRECT_URI", "").strip()
        or "http://127.0.0.1:8000/api/spotify/oauth/callback"
    )
    return {
        "client_id": os.environ.get("SPOTIFY_CLIENT_ID", "").strip(),
        "client_secret": os.environ.get("SPOTIFY_CLIENT_SECRET", "").strip(),
        "redirect_uri": redirect_uri,
    }


def spotify_is_configured():
    config = spotify_config()
    return bool(config["client_id"] and config["client_secret"] and config["redirect_uri"])


def read_spotify_state():
    data = read_json_file(SPOTIFY_STATE_JSON, {})
    return data if isinstance(data, dict) else {}


def write_spotify_state(state):
    rewrite_json_file(SPOTIFY_STATE_JSON, state)


def spotify_status():
    config = spotify_config()
    state = read_spotify_state()
    has_env_refresh = bool(os.environ.get("SPOTIFY_REFRESH_TOKEN", "").strip())
    has_env_access = bool(os.environ.get("SPOTIFY_ACCESS_TOKEN", "").strip())
    return {
        "configured": spotify_is_configured(),
        "connected": bool(state.get("refresh_token") or state.get("access_token") or has_env_refresh or has_env_access),
        "redirectUri": config["redirect_uri"],
        "scope": SPOTIFY_SCOPE,
        "connectedAt": state.get("connected_at"),
        "reason": "" if spotify_is_configured() else "Missing SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, or SPOTIFY_REDIRECT_URI",
    }


def make_spotify_auth_url(next_url=""):
    config = spotify_config()
    if not spotify_is_configured():
        raise ValueError("Missing SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, or SPOTIFY_REDIRECT_URI")

    state_token = base64.urlsafe_b64encode(os.urandom(24)).decode("ascii").rstrip("=")
    state = read_spotify_state()
    state["pending_oauth_state"] = state_token
    state["pending_oauth_at"] = datetime.now().isoformat(timespec="seconds")
    state["pending_next_url"] = sanitize_spotify_next_url(next_url)
    write_spotify_state(state)

    params = {
        "client_id": config["client_id"],
        "response_type": "code",
        "redirect_uri": config["redirect_uri"],
        "scope": SPOTIFY_SCOPE,
        "state": state_token,
        "show_dialog": "true",
    }
    return f"{SPOTIFY_AUTH_URL}?{urllib.parse.urlencode(params)}"


def sanitize_spotify_next_url(next_url):
    next_url = str(next_url or "").strip()
    if not next_url:
        return "/spotify-screensaver"

    parsed = urllib.parse.urlparse(next_url)
    if not parsed.scheme and next_url.startswith("/"):
        return next_url

    if parsed.scheme in {"http", "https"}:
        host = (parsed.hostname or "").lower()
        if host in {"localhost", "127.0.0.1", "::1"}:
            return next_url

    return "/spotify-screensaver"


def handle_spotify_callback(query):
    config = spotify_config()
    if not spotify_is_configured():
        raise ValueError("Spotify OAuth is not configured")

    code = (query.get("code") or [""])[0]
    incoming_state = (query.get("state") or [""])[0]
    if not code:
        raise ValueError("Missing OAuth code")

    state = read_spotify_state()
    expected_state = state.get("pending_oauth_state")
    if not expected_state or incoming_state != expected_state:
        raise ValueError("OAuth state mismatch")

    token = http_post_form_json(
        SPOTIFY_TOKEN_URL,
        {
            "client_id": config["client_id"],
            "client_secret": config["client_secret"],
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": config["redirect_uri"],
        },
    )
    if not token.get("access_token"):
        raise ValueError("Spotify did not return an access token")

    state["access_token"] = token["access_token"]
    if token.get("refresh_token"):
        state["refresh_token"] = token["refresh_token"]
    state["expires_at"] = int(time.time()) + int(token.get("expires_in") or 3600) - 60
    state["scope"] = token.get("scope")
    state["token_type"] = token.get("token_type")
    state["connected_at"] = datetime.now().isoformat(timespec="seconds")
    next_url = sanitize_spotify_next_url(state.get("pending_next_url"))
    state.pop("pending_oauth_state", None)
    state.pop("pending_oauth_at", None)
    state.pop("pending_next_url", None)
    write_spotify_state(state)
    return next_url


def spotify_access_token():
    config = spotify_config()
    state = read_spotify_state()
    env_access_token = os.environ.get("SPOTIFY_ACCESS_TOKEN", "").strip()
    env_refresh_token = os.environ.get("SPOTIFY_REFRESH_TOKEN", "").strip()

    if state.get("access_token") and int(state.get("expires_at") or 0) > int(time.time()) + 60:
        return state["access_token"]

    refresh_token = state.get("refresh_token") or env_refresh_token
    if refresh_token and spotify_is_configured():
        token = http_post_form_json(
            SPOTIFY_TOKEN_URL,
            {
                "client_id": config["client_id"],
                "client_secret": config["client_secret"],
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
        if not token.get("access_token"):
            raise ValueError("Spotify did not refresh the access token")

        state["access_token"] = token["access_token"]
        state["refresh_token"] = token.get("refresh_token") or refresh_token
        state["expires_at"] = int(time.time()) + int(token.get("expires_in") or 3600) - 60
        state["token_type"] = token.get("token_type", state.get("token_type"))
        write_spotify_state(state)
        return state["access_token"]

    if env_access_token:
        return env_access_token

    raise ValueError("Spotify is not connected")


def spotify_api_request(method, url, token=None, timeout=10):
    token = token or spotify_access_token()
    data = b"" if method in {"POST", "PUT", "DELETE"} else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise ValueError(f"Spotify API error {exc.code}: {body}") from exc


def normalize_spotify_track(item):
    if not isinstance(item, dict) or item.get("type") != "track":
        return None
    album = item.get("album") if isinstance(item.get("album"), dict) else {}
    artists = item.get("artists") if isinstance(item.get("artists"), list) else []
    images = album.get("images") if isinstance(album.get("images"), list) else []
    images = sorted(
        [image for image in images if isinstance(image, dict)],
        key=lambda image: int(image.get("width") or 0),
        reverse=True,
    )
    return {
        "title": str(item.get("name") or ""),
        "artist": ", ".join(str(artist.get("name") or "") for artist in artists if isinstance(artist, dict) and artist.get("name")),
        "album": str(album.get("name") or ""),
        "albumCoverUrl": str((images[0] if images else {}).get("url") or ""),
        "durationMs": int(item.get("duration_ms") or 0),
    }


def read_spotify_next_track(token):
    try:
        payload = spotify_api_request("GET", SPOTIFY_QUEUE_URL, token=token, timeout=10)
    except Exception:
        return None
    queue = payload.get("queue") if isinstance(payload.get("queue"), list) else []
    for item in queue:
        track = normalize_spotify_track(item)
        if track:
            return {
                "title": track["title"],
                "artist": track["artist"],
                "album": track["album"],
                "albumCoverUrl": track["albumCoverUrl"],
            }
    return None


def artist_fact_slug(value):
    return bm_slugify(value) or "artist"


def normalize_artist_fact_payload(payload):
    if not isinstance(payload, dict):
        raise ValueError("Artist facts JSON must be an object")
    artist = str(payload.get("artist") or "").strip()
    if not artist:
        raise ValueError("Artist facts JSON needs an artist field")
    facts_raw = payload.get("facts")
    if not isinstance(facts_raw, list):
        raise ValueError("Artist facts JSON needs a facts array")
    facts = []
    for item in facts_raw[:80]:
        if isinstance(item, str):
            text = item.strip()
            if text:
                facts.append({"text": text})
            continue
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        fact = {"text": text}
        for key in ("title", "year", "source", "sourceUrl"):
            value = str(item.get(key) or "").strip()
            if value:
                fact[key] = value
        facts.append(fact)
    if not facts:
        raise ValueError("Artist facts JSON needs at least one non-empty fact")

    commons = payload.get("commons") if isinstance(payload.get("commons"), dict) else {}
    category = str(commons.get("category") or payload.get("commonsCategory") or "").strip()
    if not category:
        category = artist
    if not category.lower().startswith("category:"):
        category = f"Category:{category}"
    try:
        media_limit = int(commons.get("limit") or payload.get("mediaLimit") or 6)
    except (TypeError, ValueError):
        media_limit = 6

    media = []
    media_raw = payload.get("media")
    if isinstance(media_raw, list):
        for item in media_raw[:12]:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or item.get("localUrl") or "").strip()
            if not url:
                continue
            media.append({
                "title": str(item.get("title") or "").strip(),
                "caption": str(item.get("caption") or "").strip(),
                "credit": str(item.get("credit") or "").strip(),
                "license": str(item.get("license") or "").strip(),
                "sourceUrl": str(item.get("sourceUrl") or "").strip(),
                "url": url,
                "localUrl": str(item.get("localUrl") or "").strip(),
            })

    result = {
        "artist": artist,
        "slug": artist_fact_slug(artist),
        "summary": str(payload.get("summary") or "").strip(),
        "facts": facts,
        "commons": {
            "category": category,
            "limit": max(0, min(12, media_limit)),
        },
        "slideSeconds": max(4, min(120, int(payload.get("slideSeconds") or 14))),
        "updatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    if media:
        result["media"] = media
    return result


def write_artist_facts(payload):
    data = normalize_artist_fact_payload(payload)
    path = ARTIST_FACTS_DIR / f"{data['slug']}.json"
    rewrite_json_file(path, data)
    return {"ok": True, "artist": data["artist"], "slug": data["slug"], "path": str(path.relative_to(ROOT))}


def read_artist_facts_for(artist):
    raw_artist = str(artist or "").strip()
    if not raw_artist:
        return {"ok": True, "artist": "", "facts": [], "media": []}
    slug = artist_fact_slug(raw_artist)
    path = ARTIST_FACTS_DIR / f"{slug}.json"
    data = read_json_file(path, None)
    if not isinstance(data, dict):
        return {"ok": True, "artist": raw_artist, "slug": slug, "facts": [], "media": []}
    try:
        normalized = normalize_artist_fact_payload(data)
    except ValueError:
        normalized = data
    media = read_commons_media_for_artist(normalized)
    if not media and isinstance(normalized.get("media"), list):
        media = normalized.get("media")[:12]
    return {"ok": True, **normalized, "media": media}


def commons_cache_path(slug):
    return ARTIST_MEDIA_CACHE_DIR / f"{slug}-commons.json"


def read_commons_media_for_artist(facts_payload):
    commons = facts_payload.get("commons") if isinstance(facts_payload.get("commons"), dict) else {}
    category = str(commons.get("category") or "").strip()
    limit = max(0, min(12, int(commons.get("limit") or 6)))
    if not category or not limit:
        return []
    slug = str(facts_payload.get("slug") or artist_fact_slug(facts_payload.get("artist")) or "artist")
    cache_path = commons_cache_path(slug)
    cached = read_json_file(cache_path, {})
    now = time.time()
    if isinstance(cached, dict) and now - float(cached.get("fetchedAt", 0) or 0) < ARTIST_MEDIA_CACHE_TTL:
        media = cached.get("media")
        if isinstance(media, list):
            return media[:limit]

    query = {
        "action": "query",
        "format": "json",
        "generator": "categorymembers",
        "gcmtitle": category,
        "gcmtype": "file",
        "gcmlimit": str(limit),
        "prop": "imageinfo",
        "iiprop": "url|mime|extmetadata",
        "iiurlwidth": "1200",
    }
    url = f"{COMMONS_API_URL}?{urllib.parse.urlencode(query)}"
    req = urllib.request.Request(url, headers={"User-Agent": WIKI_UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return cached.get("media", [])[:limit] if isinstance(cached, dict) else []

    pages = payload.get("query", {}).get("pages", {})
    media = []
    for page in pages.values() if isinstance(pages, dict) else []:
        info = (page.get("imageinfo") or [{}])[0] if isinstance(page.get("imageinfo"), list) else {}
        if not isinstance(info, dict) or not str(info.get("mime") or "").startswith("image/"):
            continue
        meta = info.get("extmetadata") if isinstance(info.get("extmetadata"), dict) else {}
        caption = str((meta.get("ImageDescription") or {}).get("value") or page.get("title") or "").strip()
        credit = str((meta.get("Artist") or {}).get("value") or "").strip()
        license_name = str((meta.get("LicenseShortName") or {}).get("value") or "").strip()
        media_item = {
            "title": str(page.get("title") or "").replace("File:", ""),
            "caption": strip_html(caption)[:280],
            "credit": strip_html(credit)[:180],
            "license": strip_html(license_name)[:80],
            "sourceUrl": str(info.get("descriptionurl") or ""),
            "url": str(info.get("thumburl") or info.get("url") or ""),
            "mime": str(info.get("mime") or ""),
        }
        media_item["localUrl"] = cache_commons_media_file(media_item)
        media.append(media_item)
    rewrite_json_file(cache_path, {"fetchedAt": now, "media": media})
    return media[:limit]


def strip_html(value):
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    return re.sub(r"\s+", " ", text).strip()


def cache_commons_media_file(media_item):
    url = str(media_item.get("url") or "").strip()
    mime = str(media_item.get("mime") or "").lower()
    if not url or not mime.startswith("image/"):
        return ""
    ext = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }.get(mime, ".jpg")
    name = f"{hashlib.sha256(url.encode('utf-8')).hexdigest()[:24]}{ext}"
    path = ARTIST_MEDIA_CACHE_DIR / name
    if path.exists() and path.stat().st_size > 0:
        return f"/artist-media/{name}"
    ARTIST_MEDIA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": WIKI_UA, "Accept": mime})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read(ARTIST_MEDIA_MAX_BYTES + 1)
            if len(data) > ARTIST_MEDIA_MAX_BYTES:
                return ""
            path.write_bytes(data)
            return f"/artist-media/{name}"
    except Exception:
        return ""


def control_spotify_player(action):
    action = str(action or "").strip().lower()
    endpoints = {
        "previous": ("POST", f"{SPOTIFY_PLAYER_API_BASE}/previous"),
        "next": ("POST", f"{SPOTIFY_PLAYER_API_BASE}/next"),
        "play": ("PUT", f"{SPOTIFY_PLAYER_API_BASE}/play"),
        "pause": ("PUT", f"{SPOTIFY_PLAYER_API_BASE}/pause"),
    }
    if action not in endpoints:
        raise ValueError("Unsupported Spotify player action")

    method, url = endpoints[action]
    spotify_api_request(method, url, timeout=10)
    return {"ok": True, "action": action}


def empty_spotify_screensaver_status(reason="", needs_auth=False):
    return {
        "shouldShow": False,
        "isPlaying": False,
        "nothingPlaying": True,
        "title": "",
        "artist": "",
        "album": "",
        "albumCoverUrl": "",
        "progressMs": 0,
        "durationMs": 0,
        "fetchedAt": int(time.time() * 1000),
        "reason": reason,
        "needsAuth": bool(needs_auth),
    }


def read_spotify_screensaver_status():
    if not spotify_is_configured() and not os.environ.get("SPOTIFY_ACCESS_TOKEN", "").strip():
        return empty_spotify_screensaver_status("Spotify is not configured", needs_auth=True)

    try:
        token = spotify_access_token()
    except Exception as exc:
        return empty_spotify_screensaver_status(str(exc), needs_auth=True)

    url = f"{SPOTIFY_CURRENTLY_PLAYING_URL}?{urllib.parse.urlencode({'additional_types': 'track'})}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8")
            if not raw:
                return empty_spotify_screensaver_status("Nothing is currently playing")
            payload = json.loads(raw)
    except urllib.error.HTTPError as exc:
        if exc.code in {204, 205}:
            return empty_spotify_screensaver_status("Nothing is currently playing")
        if exc.code in {401, 403}:
            return empty_spotify_screensaver_status("Spotify authorization failed", needs_auth=True)
        return empty_spotify_screensaver_status(f"Spotify API returned {exc.code}")
    except Exception as exc:
        return empty_spotify_screensaver_status(str(exc))

    item = payload.get("item") if isinstance(payload.get("item"), dict) else {}
    track = normalize_spotify_track(item)
    is_track = payload.get("currently_playing_type") == "track" and bool(track)
    is_playing = bool(payload.get("is_playing"))
    nothing_playing = not is_track
    should_show = bool(is_track and is_playing and not nothing_playing)
    settings = read_spotify_screensaver_config()
    next_track = read_spotify_next_track(token) if settings.get("showNextTrack") else None

    return {
        "shouldShow": should_show,
        "isPlaying": is_playing,
        "nothingPlaying": nothing_playing,
        "title": track["title"] if track else "",
        "artist": track["artist"] if track else "",
        "album": track["album"] if track else "",
        "albumCoverUrl": track["albumCoverUrl"] if track else "",
        "progressMs": int(payload.get("progress_ms") or 0),
        "durationMs": track["durationMs"] if track else 0,
        "nextTrack": next_track,
        "fetchedAt": int(time.time() * 1000),
        "reason": "" if should_show else ("Spotify is paused" if is_track else "Nothing is currently playing"),
        "needsAuth": False,
    }


def normalize_spotify_screensaver_settings(raw):
    raw = raw if isinstance(raw, dict) else {}

    def bool_setting(key, fallback=False):
        value = raw.get(key, fallback)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    def number_setting(key, fallback, min_value, max_value):
        try:
            value = float(raw.get(key, fallback))
        except (TypeError, ValueError):
            value = fallback
        return max(min_value, min(max_value, value))

    try:
        idle_minutes = float(raw.get("idleMinutes", DEFAULT_SPOTIFY_SCREENSAVER_IDLE_MINUTES))
    except (TypeError, ValueError):
        idle_minutes = DEFAULT_SPOTIFY_SCREENSAVER_IDLE_MINUTES
    idle_minutes = max(0.25, min(120, idle_minutes))

    try:
        check_interval_ms = int(raw.get("checkIntervalMs", DEFAULT_SPOTIFY_SCREENSAVER_CHECK_INTERVAL_MS))
    except (TypeError, ValueError):
        check_interval_ms = DEFAULT_SPOTIFY_SCREENSAVER_CHECK_INTERVAL_MS
    check_interval_ms = max(1000, min(60000, check_interval_ms))
    background_mode = str(raw.get("backgroundMode") or "black").strip().lower()
    if background_mode not in {"black", "blur", "gradient", "ambient"}:
        background_mode = "black"
    progress_style = str(raw.get("progressStyle") or "minimal").strip().lower()
    if progress_style not in {"minimal", "slim", "glow", "rail"}:
        progress_style = "minimal"
    screensaver_layout = str(raw.get("screensaverLayout") or "center").strip().lower()
    if screensaver_layout not in {"center", "safe-bottom", "side-right", "side-left", "compact"}:
        screensaver_layout = "center"
    artist_fact_layout = str(raw.get("artistFactLayout") or "side-card").strip().lower()
    if artist_fact_layout not in {"side-card", "left-panel", "bottom-wide", "full-height", "text-focus"}:
        artist_fact_layout = "side-card"
    artist_fact_media_mode = str(raw.get("artistFactMediaMode") or "media").strip().lower()
    if artist_fact_media_mode not in {"media", "text"}:
        artist_fact_media_mode = "media"
    show_next_track = bool_setting("showNextTrack")
    next_track_timing_unit = str(raw.get("nextTrackTimingUnit") or "seconds").strip().lower()
    if next_track_timing_unit not in {"seconds", "percent"}:
        next_track_timing_unit = "seconds"
    next_track_window_max = 100 if next_track_timing_unit == "percent" else 600
    next_track_start_window = number_setting("nextTrackStartWindow", 12, 0, next_track_window_max)
    next_track_end_window = number_setting("nextTrackEndWindow", 20, 0, next_track_window_max)
    try:
        cover_scale = float(raw.get("coverScale", 1.08))
    except (TypeError, ValueError):
        cover_scale = 1.08
    cover_scale = max(0.75, min(1.35, cover_scale))
    try:
        control_scale = float(raw.get("controlScale", 1))
    except (TypeError, ValueError):
        control_scale = 1
    control_scale = max(0.1, min(1, control_scale))

    return {
        "idleMinutes": idle_minutes,
        "checkIntervalMs": check_interval_ms,
        "backgroundMode": background_mode,
        "progressStyle": progress_style,
        "screensaverLayout": screensaver_layout,
        "showNextTrack": show_next_track,
        "nextTrackShowAtStart": bool_setting("nextTrackShowAtStart", False),
        "nextTrackShowAtEnd": bool_setting("nextTrackShowAtEnd", True),
        "nextTrackTimingUnit": next_track_timing_unit,
        "nextTrackStartWindow": next_track_start_window,
        "nextTrackEndWindow": next_track_end_window,
        "coverScale": cover_scale,
        "controlScale": control_scale,
        "showArtistFacts": bool_setting("showArtistFacts", False),
        "artistFactSlideSeconds": number_setting("artistFactSlideSeconds", 14, 4, 120),
        "artistFactLayout": artist_fact_layout,
        "artistFactMediaMode": artist_fact_media_mode,
    }


def read_spotify_screensaver_config():
    raw = read_json_file(SPOTIFY_SCREENSAVER_SETTINGS_JSON, {})
    settings = normalize_spotify_screensaver_settings(raw)
    spotify = spotify_status()
    return {
        "ok": True,
        **settings,
        "spotify": spotify,
        "screensaverUrl": "/spotify-screensaver",
        "manualUrl": "/spotify-screensaver.html?manual=1",
        "updatedAt": raw.get("updatedAt", "") if isinstance(raw, dict) else "",
    }


def write_spotify_screensaver_config(payload):
    if not isinstance(payload, dict):
        raise ValueError("Invalid screensaver settings payload")
    current = read_spotify_screensaver_config()
    settings = normalize_spotify_screensaver_settings({
        "idleMinutes": payload.get("idleMinutes", current.get("idleMinutes")),
        "checkIntervalMs": payload.get("checkIntervalMs", current.get("checkIntervalMs")),
        "backgroundMode": payload.get("backgroundMode", current.get("backgroundMode")),
        "progressStyle": payload.get("progressStyle", current.get("progressStyle")),
        "screensaverLayout": payload.get("screensaverLayout", current.get("screensaverLayout")),
        "showNextTrack": payload.get("showNextTrack", current.get("showNextTrack")),
        "nextTrackShowAtStart": payload.get("nextTrackShowAtStart", current.get("nextTrackShowAtStart")),
        "nextTrackShowAtEnd": payload.get("nextTrackShowAtEnd", current.get("nextTrackShowAtEnd")),
        "nextTrackTimingUnit": payload.get("nextTrackTimingUnit", current.get("nextTrackTimingUnit")),
        "nextTrackStartWindow": payload.get("nextTrackStartWindow", current.get("nextTrackStartWindow")),
        "nextTrackEndWindow": payload.get("nextTrackEndWindow", current.get("nextTrackEndWindow")),
        "coverScale": payload.get("coverScale", current.get("coverScale")),
        "controlScale": payload.get("controlScale", current.get("controlScale")),
        "showArtistFacts": payload.get("showArtistFacts", current.get("showArtistFacts")),
        "artistFactSlideSeconds": payload.get("artistFactSlideSeconds", current.get("artistFactSlideSeconds")),
        "artistFactLayout": payload.get("artistFactLayout", current.get("artistFactLayout")),
        "artistFactMediaMode": payload.get("artistFactMediaMode", current.get("artistFactMediaMode")),
    })
    rewrite_json_file(SPOTIFY_SCREENSAVER_SETTINGS_JSON, {
        **settings,
        "updatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
    })
    return read_spotify_screensaver_config()


def list_google_calendars():
    calendars = []
    page_token = None
    while True:
        query = {
            "maxResults": 250,
            "showHidden": "true",
        }
        if page_token:
            query["pageToken"] = page_token
        data = google_calendar_api_request("GET", "/users/me/calendarList", query=query)
        for item in data.get("items", []):
            calendar_id = item.get("id")
            if not calendar_id:
                continue
            calendars.append({
                "id": calendar_id,
                "summary": item.get("summary") or calendar_id,
                "backgroundColor": item.get("backgroundColor"),
                "foregroundColor": item.get("foregroundColor"),
                "accessRole": item.get("accessRole"),
                "primary": bool(item.get("primary")),
                "selected": item.get("selected") is not False,
                "hidden": bool(item.get("hidden")),
            })
        page_token = data.get("nextPageToken")
        if not page_token:
            break

    calendars.sort(key=lambda item: (not item.get("primary"), item.get("summary", "").lower()))
    state = read_google_calendar_state()
    state["available_calendars"] = calendars
    state["calendar_list_sync_at"] = datetime.now().isoformat(timespec="seconds")
    write_google_calendar_state(state)
    return calendars


def google_calendars_for_sync(force_refresh=False):
    config = google_calendar_config()
    if not config["auto_calendars"]:
        available = read_google_calendar_state().get("available_calendars")
        lookup = {
            item.get("id"): item
            for item in available
            if isinstance(item, dict) and item.get("id")
        } if isinstance(available, list) else {}
        return [
            lookup.get(calendar_id) or {"id": calendar_id, "summary": calendar_id, "accessRole": "writer"}
            for calendar_id in config["calendar_ids"]
            if calendar_id.lower() not in {"auto", "*", "all"}
        ]

    state = read_google_calendar_state()
    calendars = state.get("available_calendars")
    if force_refresh or google_calendar_list_is_stale(state):
        calendars = list_google_calendars()
    return [
        calendar for calendar in calendars
        if calendar.get("accessRole") in {"reader", "writer", "owner"}
    ]


def google_calendar_bool(value):
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def parse_google_event_datetime(value):
    text = str(value or "").strip()
    if "T" not in text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed
    return parsed.astimezone(GOOGLE_CALENDAR_TIMEZONE)


def google_event_date(value):
    if not value:
        return ""
    parsed = parse_google_event_datetime(value)
    if parsed:
        return parsed.date().isoformat()
    return str(value)[:10]


def google_event_time(value):
    parsed = parse_google_event_datetime(value)
    if parsed:
        return parsed.strftime("%H:%M")
    return None


GOOGLE_TASK_FALLBACK_COLOR = "#f6bf26"
GOOGLE_TASK_DISPLAY_CALENDAR_ID = "__google_tasks__"
GOOGLE_TASK_MARKERS = (
    "tasks.google.com/task/",
    "changes made to the title, description, or attachments will not be saved",
)
GOOGLE_TASK_ID_RE = re.compile(r"tasks\.google\.com/task/([A-Za-z0-9_-]+)")
MATCH_CALENDAR_NAMES = {
    "besiktas",
    "besiktas",
    "cracovia",
    "hearts",
    "liverpool",
    "poland",
}


def is_google_task_event(event):
    text = " ".join(
        str(value or "")
        for value in (
            event.get("description") if isinstance(event, dict) else "",
            event.get("htmlLink") if isinstance(event, dict) else "",
        )
    ).lower()
    return any(marker in text for marker in GOOGLE_TASK_MARKERS)


def google_task_id_from_event(event):
    text = " ".join(
        str(value or "")
        for value in (
            event.get("description") if isinstance(event, dict) else "",
            event.get("htmlLink") if isinstance(event, dict) else "",
        )
    )
    match = GOOGLE_TASK_ID_RE.search(text)
    return match.group(1) if match else ""


def google_task_is_completed(task):
    if not isinstance(task, dict):
        return False
    return task.get("status") == "completed" or bool(task.get("completed"))


def list_google_task_status_lookup():
    lookup = {}
    page_token = None
    tasklists = []
    while True:
        query = {"maxResults": 100}
        if page_token:
            query["pageToken"] = page_token
        data = google_tasks_api_request("GET", "/users/@me/lists", query=query)
        tasklists.extend(item for item in data.get("items", []) if isinstance(item, dict) and item.get("id"))
        page_token = data.get("nextPageToken")
        if not page_token:
            break

    for tasklist in tasklists:
        tasklist_id = urllib.parse.quote(tasklist.get("id"), safe="")
        page_token = None
        while True:
            query = {
                "maxResults": 100,
                "showCompleted": "true",
                "showDeleted": "true",
                "showHidden": "true",
            }
            if page_token:
                query["pageToken"] = page_token
            data = google_tasks_api_request("GET", f"/lists/{tasklist_id}/tasks", query=query)
            for task in data.get("items", []):
                if isinstance(task, dict) and task.get("id"):
                    lookup[task["id"]] = task
            page_token = data.get("nextPageToken")
            if not page_token:
                break
    return lookup


def is_task_calendar(calendar):
    summary = str((calendar or {}).get("summary") or "").strip().lower()
    calendar_id = str((calendar or {}).get("id") or "").strip().lower()
    return summary in {"tasks", "zadania"} or "task" in summary or calendar_id.endswith("#tasks")


def find_google_task_calendar(calendars):
    return next(
        (
            calendar for calendar in calendars
            if isinstance(calendar, dict) and is_task_calendar(calendar)
        ),
        None,
    )


def google_task_calendar_from_state():
    calendars = read_google_calendar_state().get("available_calendars") or []
    return find_google_task_calendar(calendars if isinstance(calendars, list) else [])


def google_task_calendar_color(task_calendar=None):
    return (task_calendar or {}).get("backgroundColor") or GOOGLE_TASK_FALLBACK_COLOR


def normalize_calendar_summary(value):
    text = unicodedata.normalize("NFKD", str(value or "").strip().lower())
    return "".join(char for char in text if not unicodedata.combining(char))


def is_match_calendar(calendar):
    summary = normalize_calendar_summary((calendar or {}).get("summary"))
    return summary in MATCH_CALENDAR_NAMES


def google_event_to_dashboard_event(event, calendar_id, calendar_meta=None, task_lookup=None):
    if not isinstance(event, dict) or not event.get("id"):
        return None
    private = ((event.get("extendedProperties") or {}).get("private") or {})
    start = event.get("start") or {}
    end = event.get("end") or {}
    iso_date = google_event_date(start.get("date") or start.get("dateTime"))
    if not iso_date:
        return None

    is_task = is_google_task_event(event)
    task_id = google_task_id_from_event(event) if is_task else ""
    task = task_lookup.get(task_id) if task_lookup is not None and task_id else None
    if is_task and google_task_is_completed(task):
        return None
    task_calendar = google_task_calendar_from_state() if is_task else None
    display_calendar = task_calendar or calendar_meta or {}
    task_display_id = task_calendar.get("id") if task_calendar else GOOGLE_TASK_DISPLAY_CALENDAR_ID
    task_summary = task_calendar.get("summary") if task_calendar else "Tasks"
    event_type = "task" if is_task else private.get("dashboardType") or ("match" if is_match_calendar(calendar_meta) else "personal_event")
    dashboard_id = private.get("dashboardEventId") or f"google:{calendar_id}:{event.get('id')}"
    access_role = (calendar_meta or {}).get("accessRole")
    return {
        "id": dashboard_id,
        "date": iso_date,
        "title": event.get("summary") or "(bez tytulu)",
        "type": event_type,
        "isDayOff": google_calendar_bool(private.get("isDayOff")),
        "isShortDay": google_calendar_bool(private.get("isShortDay")),
        "countdown": google_calendar_bool(private.get("dashboardCountdown")),
        "category": private.get("dashboardCategory") or None,
        "source": "google_calendar",
        "startTime": google_event_time(start.get("dateTime")),
        "endTime": google_event_time(end.get("dateTime")),
        "notes": event.get("description") or None,
        "actionNeeded": private.get("actionNeeded") or None,
        "actionStatus": private.get("actionStatus") or None,
        "external": {
            "provider": "google_calendar",
            "calendarId": calendar_id,
            "start": start,
            "end": end,
            "displayCalendarId": task_display_id if is_task else calendar_id,
            "calendarSummary": task_summary if is_task else display_calendar.get("summary") or calendar_id,
            "calendarColor": google_task_calendar_color(task_calendar) if is_task else display_calendar.get("backgroundColor"),
            "accessRole": access_role,
            "canWrite": access_role in {"writer", "owner"},
            "eventId": event.get("id"),
            "etag": event.get("etag"),
            "updated": event.get("updated"),
            "htmlLink": event.get("htmlLink"),
            "status": event.get("status"),
            "isTask": is_task,
            "taskId": task_id or None,
            "taskStatus": task.get("status") if isinstance(task, dict) else None,
            "taskCompletedAt": task.get("completed") if isinstance(task, dict) else None,
        },
    }


def dashboard_event_to_google_payload(event):
    if not isinstance(event, dict):
        raise ValueError("Event payload must be an object")
    iso_date = str(event.get("date") or "").strip()[:10]
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", iso_date):
        raise ValueError("Event date must use YYYY-MM-DD")
    try:
        end_date = (datetime.strptime(iso_date, "%Y-%m-%d").date() + timedelta(days=1)).isoformat()
    except ValueError as exc:
        raise ValueError("Invalid event date") from exc

    event_id = str(event.get("id") or "").strip()
    private = {
        "dashboardType": str(event.get("type") or "custom"),
        "isDayOff": "true" if event.get("isDayOff") else "false",
        "isShortDay": "true" if event.get("isShortDay") else "false",
        "dashboardCountdown": "true" if event.get("countdown") else "false",
    }
    if event.get("category"):
        private["dashboardCategory"] = str(event.get("category"))
    if event_id:
        private["dashboardEventId"] = event_id
    if event.get("actionNeeded"):
        private["actionNeeded"] = str(event.get("actionNeeded"))
    if event.get("actionStatus"):
        private["actionStatus"] = str(event.get("actionStatus"))

    return {
        "summary": str(event.get("title") or "").strip() or "(bez tytulu)",
        "description": str(event.get("notes") or ""),
        "start": {"date": iso_date},
        "end": {"date": end_date},
        "extendedProperties": {"private": private},
    }


def google_calendar_event_key(calendar_id, event_id):
    return f"{google_calendar_cache_key_prefix(calendar_id)}{event_id}"


def google_calendar_cache_key_prefix(calendar_id):
    safe_calendar = base64.urlsafe_b64encode(str(calendar_id).encode("utf-8")).decode("ascii").rstrip("=")
    return f"{safe_calendar}:"


def purge_google_calendar_cache(calendar_id):
    cache = read_google_calendar_cache()
    events_cache = cache.setdefault("events", {})
    cache_prefix = google_calendar_cache_key_prefix(calendar_id)
    keys = [key for key in events_cache if str(key).startswith(cache_prefix)]
    for key in keys:
        events_cache.pop(key, None)
    if keys:
        write_google_calendar_cache(cache)
    return len(keys)


GOOGLE_DASHBOARD_OVERRIDE_FIELDS = {
    "type",
    "isDayOff",
    "isShortDay",
    "countdown",
    "category",
    "coverImage",
    "actionNeeded",
    "actionStatus",
}


def apply_google_calendar_override(event, overrides=None):
    if not isinstance(event, dict):
        return event
    external = event.get("external") if isinstance(event.get("external"), dict) else {}
    calendar_id = external.get("calendarId")
    event_id = external.get("eventId")
    if not calendar_id or not event_id:
        return event
    overrides = overrides or read_google_calendar_overrides()
    override = (overrides.get("events") or {}).get(google_calendar_event_key(calendar_id, event_id))
    if not isinstance(override, dict):
        return event
    merged = {**event}
    for field in GOOGLE_DASHBOARD_OVERRIDE_FIELDS:
        if field in override:
            merged[field] = override.get(field)
    return merged


def upsert_google_calendar_event_override(payload):
    event = payload.get("event") if isinstance(payload.get("event"), dict) else payload
    if not isinstance(event, dict):
        raise ValueError("Event payload must be an object")
    external = event.get("external") if isinstance(event.get("external"), dict) else {}
    if external.get("provider") != "google_calendar" or not external.get("calendarId") or not external.get("eventId"):
        raise ValueError("Only existing Google Calendar events can receive dashboard overrides")

    key = google_calendar_event_key(external.get("calendarId"), external.get("eventId"))
    overrides = read_google_calendar_overrides()
    existing = overrides.setdefault("events", {}).get(key)
    override = existing if isinstance(existing, dict) else {}
    for field in GOOGLE_DASHBOARD_OVERRIDE_FIELDS:
        if field in event:
            override[field] = event.get(field)
    override["updatedAt"] = datetime.now().isoformat(timespec="seconds")
    overrides["events"][key] = override
    write_google_calendar_overrides(overrides)

    cache = read_google_calendar_cache()
    cached = cache.setdefault("events", {}).get(key)
    if isinstance(cached, dict):
        cache["events"][key] = apply_google_calendar_override(cached, overrides)
        write_google_calendar_cache(cache)
    return {"ok": True, "event": apply_google_calendar_override(event, overrides)}


def sync_google_calendar(calendar_id, force=False, calendar_meta=None, task_lookup=None):
    state = read_google_calendar_state()
    calendars = state.setdefault("calendars", {})
    calendar_state = calendars.setdefault(calendar_id, {})
    sync_token = None if force else calendar_state.get("syncToken")
    cache = read_google_calendar_cache()
    events_cache = cache.setdefault("events", {})
    cache_prefix = google_calendar_cache_key_prefix(calendar_id)
    if sync_token and not any(str(key).startswith(cache_prefix) for key in events_cache):
        sync_token = None

    changed = 0
    page_token = None
    next_sync_token = None
    encoded_calendar_id = urllib.parse.quote(calendar_id, safe="")

    while True:
        query = {
            "maxResults": 2500,
            "showDeleted": "true",
            "singleEvents": "true",
        }
        if sync_token:
            query["syncToken"] = sync_token
        if page_token:
            query["pageToken"] = page_token
        try:
            data = google_calendar_api_request(
                "GET",
                f"/calendars/{encoded_calendar_id}/events",
                query=query,
            )
        except GoogleCalendarApiError as exc:
            if exc.status == 410 and sync_token:
                calendar_state.pop("syncToken", None)
                write_google_calendar_sync_state(state)
                return sync_google_calendar(calendar_id, force=True)
            raise

        for item in data.get("items", []):
            event_id = item.get("id")
            if not event_id:
                continue
            key = google_calendar_event_key(calendar_id, event_id)
            if item.get("status") == "cancelled":
                if key in events_cache:
                    events_cache.pop(key, None)
                    changed += 1
                continue
            normalized = google_event_to_dashboard_event(
                item,
                calendar_id,
                calendar_meta=calendar_meta,
                task_lookup=task_lookup,
            )
            if normalized:
                events_cache[key] = normalized
                changed += 1
            elif is_google_task_event(item) and task_lookup is not None and key in events_cache:
                events_cache.pop(key, None)
                changed += 1

        page_token = data.get("nextPageToken")
        next_sync_token = data.get("nextSyncToken") or next_sync_token
        if not page_token:
            break

    if next_sync_token:
        calendar_state["syncToken"] = next_sync_token
    calendar_state["last_sync_at"] = datetime.now().isoformat(timespec="seconds")
    state["last_sync_at"] = calendar_state["last_sync_at"]
    write_google_calendar_sync_state(state)
    write_google_calendar_cache(cache)
    return {"calendarId": calendar_id, "changed": changed, "cachedEvents": len(events_cache)}


def sync_all_google_calendars(force=False):
    results = []
    errors = []
    calendars = google_calendars_for_sync(force_refresh=force)
    task_lookup = None
    try:
        task_lookup = list_google_task_status_lookup()
    except Exception as exc:
        task_lookup = None
        results.append({"service": "google_tasks", "error": str(exc)})
    purged_tasks = purge_completed_google_task_events(task_lookup)
    for calendar in calendars:
        calendar_id = calendar.get("id")
        if calendar_id:
            try:
                results.append(sync_google_calendar(calendar_id, force=force, calendar_meta=calendar, task_lookup=task_lookup))
            except GoogleCalendarApiError as exc:
                purged = purge_google_calendar_cache(calendar_id) if exc.status in {403, 404, 410} else 0
                error = {
                    "calendarId": calendar_id,
                    "calendarSummary": calendar.get("summary") or calendar_id,
                    "status": exc.status,
                    "error": str(exc),
                    "purgedEvents": purged,
                }
                errors.append(error)
                results.append(error)
    if purged_tasks:
        results.append({"service": "google_tasks", "purgedCompletedTasks": purged_tasks})
    return {"ok": not errors, "results": results, "errors": errors, "status": google_calendar_status()}


def google_calendar_cached_events():
    cache = read_google_calendar_cache()
    overrides = read_google_calendar_overrides()
    calendar_lookup = {
        item.get("id"): item
        for item in (read_google_calendar_state().get("available_calendars") or [])
        if isinstance(item, dict) and item.get("id")
    }
    events = []
    for event in cache.get("events", {}).values():
        if isinstance(event, dict):
            events.append(apply_google_calendar_override(merge_calendar_meta_into_event(event, calendar_lookup), overrides))
    return events


def purge_completed_google_task_events(task_lookup):
    if task_lookup is None:
        return 0
    cache = read_google_calendar_cache()
    events_cache = cache.setdefault("events", {})
    removed = 0
    for key, event in list(events_cache.items()):
        if not isinstance(event, dict):
            continue
        external = event.get("external") if isinstance(event.get("external"), dict) else {}
        is_task = bool(external.get("isTask")) or event.get("type") == "task" or any(
            marker in str(event.get("notes") or "").lower()
            for marker in GOOGLE_TASK_MARKERS
        )
        if not is_task:
            continue
        task_id = external.get("taskId") or google_task_id_from_event({
            "description": event.get("notes"),
            "htmlLink": external.get("htmlLink"),
        })
        task = task_lookup.get(task_id) if task_id else None
        if google_task_is_completed(task):
            events_cache.pop(key, None)
            removed += 1
    if removed:
        write_google_calendar_cache(cache)
    return removed


def merge_calendar_meta_into_event(event, calendar_lookup):
    external = event.get("external") if isinstance(event.get("external"), dict) else {}
    calendar_id = external.get("calendarId")
    calendar = calendar_lookup.get(calendar_id)
    is_task = bool(external.get("isTask")) or event.get("type") == "task" or any(
        marker in str(event.get("notes") or "").lower()
        for marker in GOOGLE_TASK_MARKERS
    )
    task_calendar = find_google_task_calendar(calendar_lookup.values()) if is_task else None
    display_calendar = task_calendar or calendar
    if not display_calendar:
        return event
    merged = {**event}
    merged_external = {**external}
    if is_task:
        merged["type"] = "task"
        merged_external["isTask"] = True
        merged_external["displayCalendarId"] = (
            task_calendar.get("id") if task_calendar and task_calendar.get("id") else GOOGLE_TASK_DISPLAY_CALENDAR_ID
        )
        merged_external["calendarSummary"] = task_calendar.get("summary") if task_calendar else "Tasks"
        merged_external["calendarColor"] = google_task_calendar_color(task_calendar)
    else:
        if is_match_calendar(display_calendar):
            merged["type"] = "match"
        merged_external["calendarSummary"] = display_calendar.get("summary") or merged_external.get("calendarSummary") or calendar_id
        merged_external["calendarColor"] = display_calendar.get("backgroundColor") or merged_external.get("calendarColor")
    role_calendar = calendar or display_calendar
    merged_external["accessRole"] = role_calendar.get("accessRole") or merged_external.get("accessRole")
    merged_external["canWrite"] = (role_calendar.get("accessRole") or merged_external.get("accessRole")) in {"writer", "owner"}
    merged["external"] = merged_external
    return merged


def read_events_payload(sync_google=False, include_local=True, include_google=True, include_past=False, window_days=None):
    events = []
    google_result = None
    google_error = None
    if include_local:
        local_events = read_json_file(EVENTS_JSON, [])
        if isinstance(local_events, list):
            events.extend(local_events)

    if include_google and google_calendar_is_configured() and read_google_calendar_state().get("refresh_token"):
        force_schema_sync = google_calendar_cache_needs_schema_refresh()
        state = read_google_calendar_state()
        should_sync_google = force_schema_sync or (sync_google and not google_calendar_sync_is_fresh(state))
        if should_sync_google:
            try:
                google_result = sync_all_google_calendars(force=force_schema_sync)
            except Exception as exc:
                google_error = str(exc)
        events.extend(google_calendar_cached_events())

    if not include_past:
        now = datetime.now()
        events = [event for event in events if dashboard_event_is_upcoming(event, now)]
    if window_days is not None:
        now = datetime.now()
        events = [event for event in events if dashboard_event_is_within_window(event, now, window_days)]

    return {
        "ok": True,
        "events": events,
        "countdownCategories": read_event_countdown_categories(),
        "countdownCategoryCovers": read_event_countdown_category_covers(),
        "google": {
            **google_calendar_status(),
            "syncResult": google_result,
            "syncError": google_error,
            "partialSyncErrors": google_result.get("errors") if isinstance(google_result, dict) else [],
        },
    }


def dashboard_event_is_upcoming(event, now=None):
    now = now or datetime.now()
    iso_date = str((event or {}).get("date") or "")[:10]
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", iso_date):
        return False
    today_iso = now.date().isoformat()
    if iso_date > today_iso:
        return True
    if iso_date < today_iso:
        return False
    start_time = str((event or {}).get("startTime") or "").strip()
    match = re.match(r"^(\d{1,2}):(\d{2})", start_time)
    if not match:
        return True
    try:
        event_time = datetime.strptime(
            f"{int(match.group(1)):02d}:{int(match.group(2)):02d}",
            "%H:%M",
        ).time()
    except ValueError:
        return True
    return event_time > now.time()


def dashboard_event_is_within_window(event, now=None, window_days=None):
    try:
        days = int(window_days)
    except (TypeError, ValueError):
        return True
    if days <= 0:
        return True
    now = now or datetime.now()
    iso_date = str((event or {}).get("date") or "")[:10]
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", iso_date):
        return False
    try:
        event_date = datetime.strptime(iso_date, "%Y-%m-%d").date()
    except ValueError:
        return False
    return now.date() <= event_date <= (now.date() + timedelta(days=days))


def upsert_google_calendar_event(payload):
    config = google_calendar_config()
    event = payload.get("event") if isinstance(payload.get("event"), dict) else payload
    enforce_google_calendar_write_policy(event)
    external = event.get("external") if isinstance(event, dict) and isinstance(event.get("external"), dict) else {}
    calendar_id = payload.get("calendarId") or external.get("calendarId") or default_google_write_calendar_id(config)
    event_id = payload.get("eventId") or external.get("eventId")
    google_payload = dashboard_event_to_google_payload(event)
    encoded_calendar_id = urllib.parse.quote(calendar_id, safe="")

    if event_id:
        encoded_event_id = urllib.parse.quote(event_id, safe="")
        google_event = google_calendar_api_request(
            "PATCH",
            f"/calendars/{encoded_calendar_id}/events/{encoded_event_id}",
            payload=google_payload,
        )
    else:
        google_event = google_calendar_api_request(
            "POST",
            f"/calendars/{encoded_calendar_id}/events",
            payload=google_payload,
        )

    calendar_lookup = {
        item.get("id"): item
        for item in (read_google_calendar_state().get("available_calendars") or [])
        if isinstance(item, dict) and item.get("id")
    }
    normalized = google_event_to_dashboard_event(
        google_event,
        calendar_id,
        calendar_meta=calendar_lookup.get(calendar_id),
    )
    cache = read_google_calendar_cache()
    if normalized:
        key = google_calendar_event_key(calendar_id, google_event.get("id"))
        cache.setdefault("events", {})[key] = normalized
        write_google_calendar_cache(cache)
    return {"ok": True, "event": normalized, "googleEvent": google_event}


def default_google_write_calendar_id(config=None):
    config = config or google_calendar_config()
    explicit = [
        item for item in config.get("calendar_ids", [])
        if str(item).lower() not in {"auto", "*", "all"}
    ]
    if explicit:
        return explicit[0]
    calendars = google_calendars_for_sync(force_refresh=False)
    writable = [item for item in calendars if item.get("accessRole") in {"writer", "owner"}]
    primary = next((item for item in writable if item.get("primary")), None)
    chosen = primary or (writable[0] if writable else None)
    return chosen.get("id") if chosen else "primary"


def enforce_google_calendar_write_policy(event):
    if not isinstance(event, dict):
        raise ValueError("Event payload must be an object")
    external = event.get("external") if isinstance(event.get("external"), dict) else {}
    if external.get("provider") == "google_calendar" and external.get("eventId"):
        return
    if event.get("type") == "payday":
        return
    if event.get("countdown") and str(event.get("category") or "") in {
        row["id"] for row in read_event_countdown_categories()
    }:
        return
    raise ValueError(
        "Google writes are limited to existing Google Calendar events and payday events. "
        "Local widget events are read-only until explicitly enabled."
    )


def delete_google_calendar_event(payload):
    external = payload.get("external") if isinstance(payload.get("external"), dict) else {}
    calendar_id = payload.get("calendarId") or external.get("calendarId")
    event_id = payload.get("eventId") or external.get("eventId")
    if not calendar_id or not event_id:
        raise ValueError("calendarId and eventId are required")
    encoded_calendar_id = urllib.parse.quote(calendar_id, safe="")
    encoded_event_id = urllib.parse.quote(event_id, safe="")
    try:
        google_calendar_api_request(
            "DELETE",
            f"/calendars/{encoded_calendar_id}/events/{encoded_event_id}",
        )
    except GoogleCalendarApiError as exc:
        if exc.status not in {404, 410}:
            raise
    cache = read_google_calendar_cache()
    cache.setdefault("events", {}).pop(google_calendar_event_key(calendar_id, event_id), None)
    write_google_calendar_cache(cache)
    return {"ok": True, "deleted": True}


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
    data = wiki_get_json(search_url, headers=headers)
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
    data = wiki_get_json(img_url, headers=headers)
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
    candidates = [key]
    if key.startswith("best "):
        candidates.append(key[5:])
    for candidate in candidates:
        if candidate in CATEGORY_ALIASES:
            return CATEGORY_ALIASES[candidate]
        if candidate in CANONICAL_BY_KEY:
            return CANONICAL_BY_KEY[candidate]
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


def merge_winners_maps(*maps):
    merged = {}
    for winners_map in maps:
        if not winners_map:
            continue
        for y, titles in winners_map.items():
            year_map = merged.setdefault(y, {})
            for key, categories in titles.items():
                if not key:
                    continue
                year_map.setdefault(key, set()).update(categories or [])
    return merged


def ordinal_number(n):
    n = int(n)
    if 10 <= (n % 100) <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def wikipedia_awards_page_title(year):
    try:
        y = int(year)
    except (TypeError, ValueError):
        return None
    if y < 1929:
        return None
    ceremony_no = y - 1928
    return f"{ordinal_number(ceremony_no)}_Academy_Awards"


def fetch_wikipedia_wikitext(page_title):
    if not page_title:
        return ""
    params = urllib.parse.urlencode(
        {
            "action": "parse",
            "page": page_title,
            "prop": "wikitext",
            "formatversion": 2,
            "format": "json",
            "redirects": 1,
        }
    )
    data = http_get_json(
        f"{WIKIPEDIA_API_URL}?{params}",
        headers={"User-Agent": WIKI_UA},
        timeout=20,
    )
    parsed = data.get("parse") if isinstance(data, dict) else {}
    return parsed.get("wikitext") or ""


def strip_wiki_markup(text):
    if not text:
        return ""
    s = str(text)
    s = re.sub(r"<!--.*?-->", "", s, flags=re.S)
    s = re.sub(r"<ref[^>/]*/>", "", s)
    s = re.sub(r"<ref[^>]*>.*?</ref>", "", s, flags=re.S)
    s = re.sub(r"<small>.*?</small>", "", s, flags=re.S)
    s = re.sub(r"'''+", "", s)
    s = re.sub(r"\[\[([^|\]]+)\|([^\]]+)\]\]", r"\2", s)
    s = re.sub(r"\[\[([^\]]+)\]\]", r"\1", s)
    s = s.replace("‡", "").replace("†", "")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def parse_wiki_award_label(template_text):
    inner = str(template_text or "").strip()
    if not inner.startswith("{{Award category|") or not inner.endswith("}}"):
        return None
    linked_labels = re.findall(r"\[\[(?:[^|\]]+\|)?([^\]]+)\]\]", inner)
    if linked_labels:
        label = strip_wiki_markup(linked_labels[-1])
    else:
        payload = inner[len("{{Award category|") : -2]
        parts = payload.split("|")
        label = strip_wiki_markup(parts[-1]) if parts else ""
    return normalize_category(label)


def extract_wiki_winner_line(chunk):
    if not chunk:
        return None
    for raw_line in str(chunk).splitlines():
        line = raw_line.strip()
        if not line.startswith("*") or line.startswith("**"):
            continue
        if "'''" in line or "‡" in line:
            return line
    return None


def extract_films_from_wiki_winner_line(line, category):
    if not line:
        return []

    cleaned = strip_wiki_markup(line)
    if category == "Music (Original Song)":
        m = re.search(r"from\s+([^;,(]+)", cleaned, flags=re.IGNORECASE)
        if m:
            film = clean_film_title(m.group(1))
            return [film] if film else []

    matches = []
    for pattern in (
        r"'{2,5}\[\[([^|\]]+)\|([^\]]+)\]\]'{2,5}",
        r"'{2,5}\[\[([^\]]+)\]\]'{2,5}",
        r"'{2,5}([^'\n]+)'{2,5}",
    ):
        for match in re.finditer(pattern, line):
            raw = match.group(2) if match.lastindex and match.lastindex > 1 else match.group(1)
            title = clean_film_title(strip_wiki_markup(raw))
            if title:
                matches.append(title)
    return list(dict.fromkeys(matches[:1]))


def build_wikipedia_winners_map(year):
    page_title = wikipedia_awards_page_title(year)
    wikitext = fetch_wikipedia_wikitext(page_title)
    if not wikitext:
        return {}, page_title

    marker_re = re.compile(r"\{\{Award category\|[^}]+\}\}")
    matches = list(marker_re.finditer(wikitext))
    if not matches:
        return {}, page_title

    winners_for_year = {}
    for idx, match in enumerate(matches):
        category = parse_wiki_award_label(match.group(0))
        if not category:
            continue
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(wikitext)
        winner_line = extract_wiki_winner_line(wikitext[start:end])
        if not winner_line:
            continue
        films = extract_films_from_wiki_winner_line(winner_line, category)
        for film in films:
            key = normalize_title_key(film)
            if not key:
                continue
            winners_for_year.setdefault(key, set()).add(category)

    if not winners_for_year:
        return {}, page_title
    return {int(year): winners_for_year}, page_title


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
    winners_map = {}
    sources = []

    try:
        csv_path = download_winners_csv(force=force)
        rows = parse_winners_rows(csv_path)
        winners_map = merge_winners_maps(winners_map, build_winners_map(rows, year=year))
        sources.append(csv_path.name)
    except Exception as exc:
        log_line(f"winners csv fallback error: {exc}", tag="api", level="warn")

    wiki_years = []
    if year:
        if int(year) >= 2026:
            wiki_years.append(int(year))
    else:
        wiki_years.extend([y for y in available_years() if y >= 2026])

    for wiki_year in wiki_years:
        try:
            wiki_map, page_title = build_wikipedia_winners_map(wiki_year)
            winners_map = merge_winners_maps(winners_map, wiki_map)
            if wiki_map and page_title:
                sources.append(f"wikipedia:{page_title}")
        except Exception as exc:
            log_line(f"wikipedia winners fallback error ({wiki_year}): {exc}", tag="api", level="warn")

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

    sync_watchlist_to_film_library()
    write_films_static_snapshot()

    return {
        "ok": True,
        "year": year,
        "updated_files": updated_files,
        "updated_rows": updated_rows,
        "matched_rows": matched_rows,
        "source": ", ".join(dict.fromkeys(sources)) if sources else None,
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
    conn.row_factory = sqlite3.Row
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
    ensure_films_tables(conn)
    try:
        sync_watchlist_to_film_library(conn)
    except Exception as exc:
        log_line(f"Film library sync skipped during startup: {exc}", tag="api", level="warn")
    conn.close()
    try:
        write_films_static_snapshot()
    except Exception as exc:
        log_line(f"Film static snapshot skipped during startup: {exc}", tag="api", level="warn")

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
    sync_watchlist_to_film_library(conn)
    conn.close()
    write_films_static_snapshot()
    return dict(row) if row else None


def sanitize_habit_db_filename(name):
    raw = str(name or "").strip()
    base = Path(raw).name if raw else ""
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(base).stem).strip(".-_")
    if not stem:
        stem = "habit-upload"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{stem}-{stamp}.db"


def decode_habit_db_payload(payload):
    b64_data = payload.get("contentBase64") or payload.get("content_base64")
    if not isinstance(b64_data, str) or not b64_data.strip():
        raise ValueError("Missing contentBase64")
    try:
        raw = base64.b64decode(b64_data, validate=True)
    except Exception as exc:
        raise ValueError("Invalid base64 payload") from exc
    if not raw:
        raise ValueError("Uploaded file is empty")
    if len(raw) > HABIT_UPLOAD_MAX_BYTES:
        max_mb = HABIT_UPLOAD_MAX_BYTES // (1024 * 1024)
        raise ValueError(f"File too large (max {max_mb} MB)")
    return raw


def validate_uploaded_habit_db(db_path):
    required = {"habits", "repetitions"}
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            rows = cur.execute("SELECT lower(name) FROM sqlite_master WHERE type='table';").fetchall()
    except Exception as exc:
        raise ValueError("Uploaded file is not a valid SQLite database") from exc
    present = {row[0] for row in rows if row and row[0]}
    missing = sorted(required - present)
    if missing:
        raise ValueError(f"DB missing required table(s): {', '.join(missing)}")


def run_habit_build(db_path=None, csv_path=None):
    if not HABIT_BUILD_SCRIPT.exists():
        raise RuntimeError(f"Missing script: {HABIT_BUILD_SCRIPT}")
    if not db_path and not csv_path:
        raise ValueError("Habit import needs a DB or CSV source")
    with tempfile.TemporaryDirectory(prefix="habit-build-") as temporary:
        temporary_path = Path(temporary)
        staged = {
            HABIT_DATA_JSON: temporary_path / "habit-data.json",
            HABIT_DATA_JS: temporary_path / "habit-data.js",
            HABIT_CONFLICTS_JSON: temporary_path / "conflicts.json",
            HABIT_REPORT_JSON: temporary_path / "report.json",
            HABIT_REPORT_HTML: temporary_path / "report.html",
        }
        if HABIT_REPORT_HTML.exists():
            shutil.copyfile(HABIT_REPORT_HTML, staged[HABIT_REPORT_HTML])
        cmd = [
            sys.executable, str(HABIT_BUILD_SCRIPT),
            "--out", str(staged[HABIT_DATA_JSON]),
            "--js", str(staged[HABIT_DATA_JS]),
            "--conflicts", str(staged[HABIT_CONFLICTS_JSON]),
            "--report", str(staged[HABIT_REPORT_JSON]),
            "--report-html", str(staged[HABIT_REPORT_HTML]),
        ]
        if db_path:
            cmd.extend(["--db", str(db_path)])
        if csv_path:
            cmd.extend(["--csv", str(csv_path)])
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()
            raise RuntimeError(detail or f"build-habits.py failed with exit code {proc.returncode}")
        try:
            report = json.loads(staged[HABIT_REPORT_JSON].read_text(encoding="utf-8"))
        except Exception as exc:
            raise RuntimeError("Habit import report was not generated") from exc
        if not report.get("kept_points"):
            raise ValueError("No habit checkmarks were found in the uploaded data")
        summary = {
            "habits": report.get("habits"),
            "input_points": report.get("input_points"),
            "kept_points": report.get("kept_points"),
            "conflicts": report.get("conflicts"),
            "generated_at": report.get("generated_at"),
        }
        for destination, source in staged.items():
            if not source.exists():
                raise RuntimeError(f"Habit output was not generated: {source.name}")
            destination.parent.mkdir(parents=True, exist_ok=True)
        for destination, source in staged.items():
            os.replace(source, destination)
        return summary


def import_habit_db_from_payload(payload):
    raw = decode_habit_db_payload(payload)
    filename = sanitize_habit_db_filename(payload.get("filename"))
    HABIT_DB_DIR.mkdir(parents=True, exist_ok=True)
    destination = HABIT_DB_DIR / filename
    destination.write_bytes(raw)

    try:
        validate_uploaded_habit_db(destination)
    except Exception:
        try:
            destination.unlink()
        except Exception as exc:
            thesportsdb_rate_limited = isinstance(exc, urllib.error.HTTPError) and exc.code == 429
        raise

    summary = run_habit_build(destination)
    rel_path = destination.relative_to(ROOT).as_posix()
    log_line(f"Imported habits DB: {rel_path}", tag="api", level="success")
    return {
        "ok": True,
        "file": filename,
        "size_bytes": len(raw),
        "stored_path": rel_path,
        "summary": summary,
    }


def sanitize_habit_upload_stem(name):
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(str(name or "habit-upload")).stem).strip(".-_")
    return stem or "habit-upload"


def import_habit_file_from_payload(payload):
    raw = decode_habit_db_payload(payload)
    original_name = Path(str(payload.get("filename") or "")).name
    suffix = Path(original_name).suffix.lower()
    if suffix == ".db":
        return {**import_habit_db_from_payload(payload), "format": "db"}
    if suffix not in {".csv", ".zip"}:
        raise ValueError("Supported habit formats are .db, .csv and .zip")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    destination = HABIT_CSV_DIR / f"{sanitize_habit_upload_stem(original_name)}-{stamp}"
    destination.mkdir(parents=True, exist_ok=False)
    stored_files = []
    try:
        if suffix == ".csv":
            text = raw.decode("utf-8-sig", errors="replace")
            first_cell = text.splitlines()[0].split(",", 1)[0].strip().lower() if text.splitlines() else ""
            if first_cell not in {"date", "day"} and not original_name.lower().startswith("habits"):
                raise ValueError("A standalone per-habit CSV has no habit name. Import the Loop ZIP export instead.")
            target = destination / ("Habits.csv" if original_name.lower().startswith("habits") else "Checkmarks.csv")
            target.write_bytes(raw)
            stored_files.append(target)
        else:
            try:
                archive = zipfile.ZipFile(io.BytesIO(raw))
            except Exception as exc:
                raise ValueError("Uploaded file is not a valid ZIP archive") from exc
            with archive:
                csv_members = [member for member in archive.infolist() if not member.is_dir() and member.filename.lower().endswith(".csv")]
                if not csv_members:
                    raise ValueError("ZIP archive contains no CSV files")
                if len(csv_members) > 500:
                    raise ValueError("ZIP archive contains too many CSV files")
                expanded_size = sum(member.file_size for member in csv_members)
                if expanded_size > HABIT_UPLOAD_MAX_BYTES * 2:
                    raise ValueError("Expanded ZIP content is too large")
                for member in csv_members:
                    normalized = member.filename.replace("\\", "/").lstrip("/")
                    parts = [part for part in Path(normalized).parts if part not in {"", "."}]
                    if not parts or ".." in parts:
                        raise ValueError("ZIP archive contains an unsafe path")
                    target = destination.joinpath(*parts)
                    if destination.resolve() not in target.resolve().parents:
                        raise ValueError("ZIP archive contains an unsafe path")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.read(member))
                    stored_files.append(target)

        summary = run_habit_build(csv_path=destination)
        if not summary.get("kept_points"):
            raise ValueError("No habit checkmarks were found in the uploaded CSV data")
    except Exception:
        for path in sorted(destination.rglob("*"), reverse=True):
            try:
                if path.is_file():
                    path.unlink()
                elif path.is_dir():
                    path.rmdir()
            except OSError:
                pass
        try:
            destination.rmdir()
        except OSError:
            pass
        raise

    rel_path = destination.relative_to(ROOT).as_posix()
    log_line(f"Imported habits {suffix}: {rel_path}", tag="api", level="success")
    return {
        "ok": True,
        "format": suffix.removeprefix("."),
        "file": original_name,
        "size_bytes": len(raw),
        "stored_path": rel_path,
        "stored_files": len(stored_files),
        "summary": summary,
    }


CLIENT_DISCONNECT_WINERRORS = {10053, 10054}


def is_client_disconnect_error(exc):
    if isinstance(exc, (BrokenPipeError, ConnectionAbortedError, ConnectionResetError)):
        return True
    return isinstance(exc, OSError) and getattr(exc, "winerror", None) in CLIENT_DISCONNECT_WINERRORS


class DashboardHTTPServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if is_client_disconnect_error(exc):
            return
        super().handle_error(request, client_address)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        # SimpleHTTPRequestHandler handles the request inside __init__, so
        # response hooks must already have their state for inherited methods
        # such as HEAD.
        self._cors_origin = None
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, format, *args):
        try:
            if len(args) >= 2 and isinstance(args[0], str):
                request_line = args[0]
                status = int(args[1])
                method = request_line.split(" ", 1)[0]
                path = request_line.split(" ")[1] if " " in request_line else request_line
                level = "success" if 200 <= status < 300 else "warn" if 300 <= status < 400 else "error"
                log_line(
                    f"{status} {method} {path}",
                    tag="http",
                    level=level,
                    console=show_http_log_in_console(status, method, path),
                )
                return
        except Exception:
            pass
        super().log_message(format, *args)

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        if self._cors_origin:
            self.send_header("Access-Control-Allow-Origin", self._cors_origin)
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Dashboard-Token")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
            self.send_header("Vary", "Origin")
        super().end_headers()

    def list_directory(self, path):
        self.send_error(404)
        return None

    def request_origin(self):
        return normalize_origin(self.headers.get("Origin"))

    def request_referer_origin(self):
        return origin_from_url(self.headers.get("Referer"))

    def reject_live_workout_auth(self):
        supplied = extract_dashboard_token(self.headers)
        expected = sorted(
            token_fingerprint(token)
            for token in configured_live_workout_tokens()
        )
        if not expected:
            status = 503
            code = "live_workout_auth_not_configured"
            message = "Live Workout bearer token is not configured on the server"
        elif not supplied:
            status = 401
            code = "missing_bearer_token"
            message = "Authorization: Bearer token is required"
        else:
            status = 401
            code = "invalid_bearer_token"
            message = "Invalid Live Workout bearer token"
        log_line(
            "auth rejected "
            f"client={self.client_address[0]} status={status} code={code} "
            f"supplied_fp={token_fingerprint(supplied)} "
            f"expected_fp={','.join(expected) if expected else 'none'}",
            tag="live-workout",
            level="error",
        )
        record_live_workout_console_result(False)
        self.send_json({"error": message, "code": code}, status=status)
        return False

    def reject_habits_auth(self):
        supplied = extract_dashboard_token(self.headers)
        if not configured_habits_tokens():
            status, code, message = 503, "habits_auth_not_configured", "Habits bearer token is not configured"
        elif not supplied:
            status, code, message = 401, "missing_bearer_token", "Authorization: Bearer token is required"
        else:
            status, code, message = 401, "invalid_bearer_token", "Invalid Habits bearer token"
        log_line(
            f"auth rejected client={self.client_address[0]} status={status} code={code} "
            f"supplied_fp={token_fingerprint(supplied)}",
            tag="habits",
            level="error",
        )
        self.send_json({"error": message, "code": code}, status=status)
        return False

    def reject_feelings_auth(self):
        supplied = extract_dashboard_token(self.headers)
        if not configured_feelings_tokens():
            status, code, message = 503, "feelings_auth_not_configured", "How I Feel bearer token is not configured"
        elif not supplied:
            status, code, message = 401, "missing_bearer_token", "Authorization: Bearer token is required"
        else:
            status, code, message = 401, "invalid_bearer_token", "Invalid How I Feel bearer token"
        log_line(
            f"auth rejected client={self.client_address[0]} status={status} code={code} "
            f"supplied_fp={token_fingerprint(supplied)}",
            tag="feelings",
            level="error",
        )
        self.send_json({"error": message, "code": code}, status=status)
        return False

    def authorize_api_request(self, path, require_origin=False):
        if path.startswith(("/cleaning-dashboard/api/sync", "/cleaning-dashboard/api/journal/")):
            path = path.removeprefix("/cleaning-dashboard")
        if not str(path or "").startswith("/api/"):
            return True

        if path == "/api/sync" or path.startswith("/api/sync/") or path.startswith("/api/journal/"):
            try:
                authorize_sync(self, allowed_api_origins())
                return True
            except SyncError as exc:
                self.send_json(exc.payload(), status=exc.status)
                return False

        self._cors_origin = None
        local_client = self.client_address[0] in {"127.0.0.1", "::1", "localhost"}
        if path == "/api/phone-todo":
            supplied = extract_dashboard_token(self.headers)
            try:
                lan_client = ipaddress.ip_address(self.client_address[0]).is_private
            except ValueError:
                lan_client = False
            if (local_client or lan_client) and supplied and any(
                hmac.compare_digest(supplied, token) for token in configured_todo_phone_tokens()
            ):
                return True
            self.send_json({"ok": False, "error": "A valid phone todo token is required"}, status=401)
            return False
        if path in {"/api/phone-tracker/sync", "/api/phone-tracker/config", "/api/phone-tracker/apps"}:
            device_id = self.headers.get("X-Phone-Device-ID", "")
            token = extract_dashboard_token(self.headers)
            try:
                lan_client = ipaddress.ip_address(self.client_address[0]).is_private
            except ValueError:
                lan_client = False
            if lan_client and PHONE_TRACKER.authenticate(device_id, token):
                return True
            self.send_json({"error": "A paired phone token is required"}, status=401)
            return False
        is_finance_companion_admin = bool(FINANCE_COMPANION_ADMIN_RE.fullmatch(path))
        is_receipt_source_content = bool(FINANCE_RECEIPT_SOURCE_CONTENT_RE.fullmatch(path))
        is_finance_companion_remote = bool(FINANCE_COMPANION_REMOTE_RE.fullmatch(path)) and not is_receipt_source_content
        if is_receipt_source_content and not local_client:
            origin = self.request_origin()
            referer_origin = self.request_referer_origin()
            same_origin = (
                is_request_host_origin(origin, self.headers.get("Host"))
                or is_request_host_origin(referer_origin, self.headers.get("Host"))
            )
            if not same_origin:
                self.send_json({"ok": False, "error": "Receipt previews require a same-origin dashboard request."}, status=403)
                return False
        if is_finance_companion_remote and is_valid_finance_companion_token(self.headers):
            return True
        if is_finance_companion_admin and not local_client:
            self.send_json({"ok": False, "error": "Companion pairing and revocation are localhost-only."}, status=403)
            return False
        if is_finance_companion_remote and not local_client:
            self.send_json({"ok": False, "error": "A valid Dashboard Companion bearer token is required."}, status=401)
            return False
        is_live_workout_write = path == "/api/live-workout/telemetry"
        is_habits_api = path in HABITS_API_PATHS
        is_feelings_api = path == FEELINGS_API_PREFIX or path.startswith(f"{FEELINGS_API_PREFIX}/")
        is_reading_progress_write = bool(re.fullmatch(r"/api/reading/books/[^/]+/progress", path))
        is_reading_book_write = bool(re.fullmatch(r"/api/reading/books/[^/]+", path))
        is_cleaning_write = bool(
            path in {"/api/cleaning/tasks", "/api/cleaning/history/undo", "/api/cleaning/settings", "/api/cleaning/phone-goal"}
            or re.fullmatch(r"/api/cleaning/tasks/[^/]+(?:/done)?", path)
            or re.fullmatch(r"/api/cleaning/history/actions/[^/]+", path)
        )
        if is_habits_api and is_valid_habits_token(self.headers):
            return True
        if is_feelings_api and is_valid_feelings_token(self.headers):
            return True
        if is_live_workout_write and is_valid_live_workout_token(self.headers):
            log_line(
                "auth accepted "
                f"client={self.client_address[0]} "
                f"token_fp={token_fingerprint(extract_dashboard_token(self.headers))}",
                tag="live-workout",
                level="success",
                console=False,
            )
            return True
        if (
            (path in REMOTE_TOKEN_WRITE_PATHS or is_reading_progress_write or is_reading_book_write or is_cleaning_write)
            and not is_live_workout_write
            and is_valid_dashboard_token(self.headers)
        ):
            return True

        origin = self.request_origin()
        if is_live_workout_write and not local_client:
            if origin and origin != "null" and is_allowed_api_origin(origin):
                self._cors_origin = origin
            return self.reject_live_workout_auth()
        if origin and origin != "null":
            if not is_allowed_api_origin(origin) and not is_request_host_origin(origin, self.headers.get("Host")):
                if path.startswith("/api/language/"):
                    self.send_json(
                        {
                            "ok": False,
                            "error": "Origin not allowed",
                            "code": "origin_not_allowed",
                            "details": [],
                        },
                        status=403,
                    )
                else:
                    self.send_json({"error": "Origin not allowed"}, status=403)
                return False
            self._cors_origin = origin
            return True
        if origin == "null" and local_client:
            return True

        referer_origin = self.request_referer_origin()
        if referer_origin and (
            is_allowed_api_origin(referer_origin)
            or is_request_host_origin(referer_origin, self.headers.get("Host"))
        ):
            self._cors_origin = referer_origin
            return True

        if local_client:
            if is_live_workout_write:
                log_line(
                    f"auth bypassed for local client={self.client_address[0]}",
                    tag="live-workout",
                    level="dim",
                )
            return True

        if is_habits_api:
            return self.reject_habits_auth()
        if is_feelings_api:
            return self.reject_feelings_auth()

        if require_origin:
            if path.startswith("/api/language/"):
                self.send_json(
                    {
                        "ok": False,
                        "error": "Origin required",
                        "code": "origin_required",
                        "details": [],
                    },
                    status=403,
                )
            else:
                self.send_json({"error": "Origin required"}, status=403)
            return False
        return True

    def authorize_static_request(self, path):
        if is_protected_static_path(path):
            self.send_error(404)
            return False
        return True

    def send_json(self, payload, status=200):
        data = json.dumps(payload).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.end_headers()
            self.wfile.write(data)
            return True
        except OSError as exc:
            if not is_client_disconnect_error(exc):
                raise
            self.close_connection = True
            return False

    def phone_tracker_local_admin(self):
        if self.client_address[0] not in {"127.0.0.1", "::1", "localhost"}:
            return False
        host = urlparse("http://" + (self.headers.get("Host") or "")).hostname
        if host not in {"127.0.0.1", "localhost", "::1"}:
            return False
        origin = self.request_origin() or self.request_referer_origin()
        return not origin or urlparse(origin).hostname in {"127.0.0.1", "localhost", "::1"}

    def dispatch_phone_tracker_get(self, path, query):
        if not path.startswith("/api/phone-tracker/"):
            return False
        try:
            params = urllib.parse.parse_qs(query)
            one = lambda key, default="": (params.get(key) or [default])[0]
            if path == "/api/phone-tracker/devices":
                self.send_json({"devices": PHONE_TRACKER.devices()})
            elif path == "/api/phone-tracker/status":
                devices = PHONE_TRACKER.devices()
                self.send_json({"devices": devices, "last_sync": max((d["last_sync"] for d in devices if d["last_sync"]), default=None)})
            elif path == "/api/phone-tracker/config":
                device_id = self.headers.get("X-Phone-Device-ID", "")
                self.send_json({**PHONE_TRACKER.config(device_id),"access":PHONE_ACCESS.config(device_id)})
            elif path == "/api/phone-tracker/access":
                if not self.phone_tracker_local_admin():
                    raise PhoneTrackerError("App access settings are available on the PC only",403)
                self.send_json(PHONE_ACCESS.overview(one("device_id")))
            elif path == "/api/phone-tracker/access/history":
                if not self.phone_tracker_local_admin():
                    raise PhoneTrackerError("App access history is available on the PC only",403)
                self.send_json({"days":PHONE_ACCESS.history(one("device_id"),one("target","com.instagram.android"),int(one("days","30")))})
            elif path == "/api/phone-tracker/rules":
                self.send_json({"rules":PHONE_TRACKER.rules(one("device_id"))})
            elif path == "/api/phone-tracker/retention":
                self.send_json(PHONE_TRACKER.retention())
            elif path == "/api/phone-tracker/override-policy":
                if not self.phone_tracker_local_admin():
                    raise PhoneTrackerError("Override settings are available on the PC only",403)
                policy = PHONE_TRACKER.override_policy(one("device_id"))
                self.send_json({key:value for key,value in policy.items() if key not in {"pin_salt","pin_hash"}})
            elif path == "/api/phone-tracker/summary":
                self.send_json(PHONE_TRACKER.summary(one("range", "today"), one("tz", "UTC"),
                    one("device_id") or None, one("start") or None, one("end") or None,
                    int(one("attribution_seconds", "120")), one("source") == "sample"))
            elif path == "/api/phone-tracker/insights":
                self.send_json(PHONE_TRACKER.insights(one("tz","UTC"),one("device_id") or None,
                    one("days","30"),one("source")=="sample",one("metric","notifications"),
                    one("operator",">="),one("threshold","100"),one("outcome","screen_time")))
            elif path == "/api/phone-tracker/events":
                from phone_tracker import time_window
                start, end = time_window(one("range", "today"), one("tz", "UTC"),
                                         one("start") or None, one("end") or None)
                self.send_json({"events": PHONE_TRACKER.events(one("device_id") or None,
                    start,end,min(int(one("limit", "1000")),5000),sample=one("source") == "sample")})
            else:
                self.send_json({"error": "Unknown Phone Tracker endpoint"}, status=404)
        except (PhoneTrackerError, ValueError) as exc:
            self.send_json({"error": str(exc)}, status=getattr(exc, "status", 400))
        return True

    def dispatch_phone_tracker_post(self, path):
        if not path.startswith("/api/phone-tracker/"):
            return False
        try:
            if path == "/api/phone-tracker/sync":
                body = self.read_json_body(max_bytes=1024*1024)
                if body.get("device_id") != self.headers.get("X-Phone-Device-ID"):
                    raise PhoneTrackerError("Device ID does not match token", 401)
                self.send_json(PHONE_TRACKER.ingest(body,self.client_address[0]))
            elif path == "/api/phone-tracker/apps":
                body = self.read_json_body(max_bytes=1024*1024)
                if body.get("device_id") != self.headers.get("X-Phone-Device-ID"):
                    raise PhoneTrackerError("Device ID does not match token",401)
                self.send_json(PHONE_TRACKER.save_apps(body["device_id"],body.get("apps")))
            elif path == "/api/phone-tracker/pair":
                if not self.phone_tracker_local_admin():
                    raise PhoneTrackerError("Pairing is available on the PC only",403)
                body = self.read_json_body(max_bytes=4096)
                self.send_json(PHONE_TRACKER.pair(body.get("label")),status=201)
            elif path == "/api/phone-tracker/access":
                if not self.phone_tracker_local_admin():
                    raise PhoneTrackerError("App access settings are available on the PC only",403)
                body = self.read_json_body(max_bytes=16384)
                self.send_json(PHONE_ACCESS.save_policy(body.get("device_id"),body.get("policy")),status=200)
            elif path == "/api/phone-tracker/access/plan":
                if not self.phone_tracker_local_admin():
                    raise PhoneTrackerError("App access settings are available on the PC only",403)
                body = self.read_json_body(max_bytes=4096)
                self.send_json(PHONE_ACCESS.plan_action(body.get("device_id"),body.get("target"),body.get("action")))
            elif path in {"/api/phone-tracker/rules", "/api/phone-tracker/external-condition", "/api/phone-tracker/category", "/api/phone-tracker/place"}:
                if not self.phone_tracker_local_admin():
                    raise PhoneTrackerError("Rule settings are available on the PC only",403)
                body = self.read_json_body(max_bytes=16384)
                device_id = body.get("device_id")
                if path.endswith("/rules"):
                    self.send_json(PHONE_TRACKER.save_rule(device_id,body.get("rule")),status=201)
                elif path.endswith("/external-condition"):
                    self.send_json(PHONE_TRACKER.set_external_condition(device_id,body.get("name"),body.get("value")))
                elif path.endswith("/place"):
                    self.send_json(PHONE_TRACKER.rename_place(device_id,body.get("cluster_key"),body.get("label")))
                else:
                    self.send_json(PHONE_TRACKER.set_category(device_id,body.get("package_name"),body.get("category")))
            elif path == "/api/phone-tracker/sample":
                if not self.phone_tracker_local_admin():
                    raise PhoneTrackerError("Sample generation is available on the PC only",403)
                body = self.read_json_body(max_bytes=4096)
                self.send_json(PHONE_TRACKER.generate_sample(int(body.get("days",1)),body.get("tz","UTC")),status=201)
            elif path == "/api/phone-tracker/retention":
                if not self.phone_tracker_local_admin():
                    raise PhoneTrackerError("Retention settings are available on the PC only",403)
                self.send_json(PHONE_TRACKER.set_retention(self.read_json_body(max_bytes=4096)))
            elif path == "/api/phone-tracker/override-policy":
                if not self.phone_tracker_local_admin():
                    raise PhoneTrackerError("Override settings are available on the PC only",403)
                body = self.read_json_body(max_bytes=4096)
                self.send_json(PHONE_TRACKER.set_override_policy(body.get("device_id"),body))
            else:
                self.send_json({"error": "Unknown Phone Tracker endpoint"},status=404)
        except (PhoneTrackerError, TimelineError) as exc:
            self.send_json({"error": str(exc)}, status=getattr(exc,"status",400))
        return True

    def dispatch_phone_tracker_delete(self, path, query):
        if not path.startswith("/api/phone-tracker/"):
            return False
        if not self.phone_tracker_local_admin():
            self.send_json({"error": "Phone data deletion is available on the PC only"},status=403)
            return True
        try:
            params = urllib.parse.parse_qs(query)
            one = lambda key, default="": (params.get(key) or [default])[0]
            if path == "/api/phone-tracker/events":
                self.send_json(PHONE_TRACKER.delete_events(one("range", "today"),one("tz", "UTC"),
                    one("start") or None,one("end") or None,one("source") == "sample"))
            elif path == "/api/phone-tracker/all" and one("confirm") == "delete":
                self.send_json(PHONE_TRACKER.delete_all())
            elif path == "/api/phone-tracker/sample":
                self.send_json(PHONE_TRACKER.clear_sample())
            elif re.fullmatch(r"/api/phone-tracker/rules/[a-fA-F0-9-]{36}",path):
                self.send_json(PHONE_TRACKER.delete_rule(path.rsplit("/",1)[1]))
            elif re.fullmatch(r"/api/phone-tracker/devices/[a-fA-F0-9-]{36}",path):
                self.send_json(PHONE_TRACKER.revoke(path.rsplit("/",1)[1]))
            else:
                self.send_json({"error": "Unknown Phone Tracker deletion"},status=404)
        except PhoneTrackerError as exc:
            self.send_json({"error":str(exc)},status=exc.status)
        return True

    def send_language_error(self, exc):
        if isinstance(exc, LanguageError):
            self.send_json(exc.as_payload(), status=exc.status)
            return
        if isinstance(exc, TimelineError):
            self.send_json(
                {
                    "ok": False,
                    "error": str(exc),
                    "code": exc.code,
                    "details": list(exc.details or []),
                },
                status=exc.status,
            )
            return
        log_line(f"Language API failed: {type(exc).__name__}", tag="language", level="error")
        self.send_json(
            {
                "ok": False,
                "error": "Language operation failed",
                "code": "language_internal_error",
                "details": [],
            },
            status=500,
        )

    def send_bytes(self, data, content_type, status=200, cache_seconds=86400, extra_headers=None):
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store, max-age=0" if cache_seconds <= 0 else f"public, max-age={cache_seconds}")
            for name, value in (extra_headers or {}).items():
                self.send_header(str(name), str(value))
            self.end_headers()
            self.wfile.write(data)
            return True
        except OSError as exc:
            if not is_client_disconnect_error(exc):
                raise
            self.close_connection = True
            return False

    def read_json_body(self, max_bytes=10 * 1024 * 1024):
        try:
            length = int(self.headers.get("Content-Length", ""))
        except (TypeError, ValueError):
            raise TimelineError("Valid Content-Length is required", status=411, code="invalid_content_length")
        if length <= 0:
            raise TimelineError("Request body is required", code="empty_body")
        if length > max_bytes:
            raise TimelineError("Payload is too large", status=413, code="payload_too_large")
        raw = self.rfile.read(length)
        if len(raw) != length:
            raise TimelineError("Incomplete request body", code="incomplete_body")
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise TimelineError("Invalid JSON", code="invalid_json")

    def send_local_audio(self, path, content_type):
        total_size = path.stat().st_size
        start = 0
        end = total_size - 1
        status = 200
        range_header = str(self.headers.get("Range") or "").strip()
        if range_header:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header)
            if not match or (not match.group(1) and not match.group(2)):
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{total_size}")
                self.end_headers()
                return
            if match.group(1):
                start = int(match.group(1))
                end = int(match.group(2)) if match.group(2) else end
            else:
                suffix_length = int(match.group(2))
                start = max(0, total_size - suffix_length)
            if start >= total_size or end < start:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{total_size}")
                self.end_headers()
                return
            end = min(end, total_size - 1)
            status = 206

        content_length = max(0, end - start + 1)
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(content_length))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "private, no-store, max-age=0")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{total_size}")
        self.end_headers()
        with path.open("rb") as source:
            source.seek(start)
            remaining = content_length
            while remaining > 0:
                chunk = source.read(min(64 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def send_step_stream(self):
        subscriber = subscribe_step_updates()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            while True:
                try:
                    payload = subscriber.get(timeout=25)
                    data = json.dumps(payload, ensure_ascii=False)
                    self.wfile.write(f"event: steps\ndata: {data}\n\n".encode("utf-8"))
                except queue.Empty:
                    self.wfile.write(b": keep-alive\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            unsubscribe_step_updates(subscriber)

    def send_live_workout_stream(self):
        subscriber = subscribe_live_workout()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            log_line(
                f"SSE connected client={self.client_address[0]}:{self.client_address[1]}",
                tag="live-workout",
                level="success",
            )
            while True:
                try:
                    payload = subscriber.get(timeout=20)
                    data = json.dumps(payload, ensure_ascii=False)
                    self.wfile.write(f"event: telemetry\ndata: {data}\n\n".encode("utf-8"))
                except queue.Empty:
                    self.wfile.write(b": keep-alive\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            unsubscribe_live_workout(subscriber)
            log_line(
                f"SSE disconnected client={self.client_address[0]}:{self.client_address[1]}",
                tag="live-workout",
                level="dim",
            )

    def send_feelings_error(self, exc):
        if isinstance(exc, FeelingsError):
            self.send_json(exc.as_payload(), status=exc.status)
            return
        log_line(f"Feelings API failed: {type(exc).__name__}: {exc}", tag="feelings", level="error")
        self.send_json(
            {"ok": False, "error": "Feelings operation failed", "code": "feelings_internal_error"},
            status=500,
        )

    def dispatch_feelings_get(self, path, query_string=""):
        if not path.startswith("/api/feelings"):
            return False
        try:
            FEELINGS_SERVICE.initialize()
            query = urllib.parse.parse_qs(query_string)
            checkin_match = re.fullmatch(r"/api/feelings/checkins/([^/]+)", path)
            if path == "/api/feelings/checkins":
                self.send_json(FEELINGS_SERVICE.list_checkins(query))
                return True
            if checkin_match:
                self.send_json({"ok": True, "checkin": FEELINGS_SERVICE.get_checkin(urllib.parse.unquote(checkin_match.group(1)))})
                return True
            if path == "/api/feelings/emotions":
                self.send_json(FEELINGS_SERVICE.list_emotions())
                return True
            if path == "/api/feelings/tags":
                self.send_json(FEELINGS_SERVICE.list_tags())
                return True
            if path == "/api/feelings/insights":
                raw_days = (query.get("days") or [None])[0]
                self.send_json(FEELINGS_SERVICE.insights(int(raw_days) if raw_days else None))
                return True
            if path == "/api/feelings/export":
                export_format = str((query.get("format") or ["json"])[0]).lower()
                if export_format == "csv":
                    data = FEELINGS_SERVICE.export_csv().encode("utf-8-sig")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/csv; charset=utf-8")
                    self.send_header("Content-Disposition", 'attachment; filename="how-i-feel.csv"')
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(data)
                else:
                    self.send_json(FEELINGS_SERVICE.export_data())
                return True
            self.send_json({"ok": False, "error": "Not found"}, status=404)
        except Exception as exc:
            self.send_feelings_error(exc)
        return True

    def dispatch_feelings_post(self, path):
        if not path.startswith("/api/feelings"):
            return False
        try:
            FEELINGS_SERVICE.initialize()
            payload = self.read_json_body(max_bytes=12 * 1024 * 1024)
            if path == "/api/feelings/checkins":
                self.send_json(FEELINGS_SERVICE.create_checkin(payload), status=201)
                return True
            if path == "/api/feelings/emotions":
                self.send_json(FEELINGS_SERVICE.create_emotion(payload), status=201)
                return True
            if path == "/api/feelings/tags":
                self.send_json(FEELINGS_SERVICE.create_tag(payload), status=201)
                return True
            if path == "/api/feelings/import":
                self.send_json(FEELINGS_SERVICE.import_export(payload))
                return True
            self.send_json({"ok": False, "error": "Not found"}, status=404)
        except Exception as exc:
            self.send_feelings_error(exc)
        return True

    def dispatch_feelings_patch(self, path):
        match = re.fullmatch(r"/api/feelings/checkins/([^/]+)", path)
        if not path.startswith("/api/feelings"):
            return False
        try:
            if not match:
                raise FeelingsError("Not found", status=404, code="not_found")
            FEELINGS_SERVICE.initialize()
            payload = self.read_json_body(max_bytes=1024 * 1024)
            self.send_json(FEELINGS_SERVICE.update_checkin(urllib.parse.unquote(match.group(1)), payload))
        except Exception as exc:
            self.send_feelings_error(exc)
        return True

    def dispatch_feelings_delete(self, path, query_string=""):
        match = re.fullmatch(r"/api/feelings/checkins/([^/]+)", path)
        if not path.startswith("/api/feelings"):
            return False
        try:
            if not match:
                raise FeelingsError("Not found", status=404, code="not_found")
            query = urllib.parse.parse_qs(query_string)
            if (query.get("confirm") or [""])[0] != "delete":
                raise FeelingsError("Deletion requires explicit confirmation", status=409, code="confirmation_required")
            FEELINGS_SERVICE.initialize()
            self.send_json(FEELINGS_SERVICE.delete_checkin(urllib.parse.unquote(match.group(1))))
        except Exception as exc:
            self.send_feelings_error(exc)
        return True

    def send_jobhunt_error(self, exc):
        if isinstance(exc, JobhuntError):
            self.send_json(exc.as_payload(), status=exc.status)
            return
        if isinstance(exc, TimelineError):
            self.send_json(
                {"ok": False, "error": str(exc), "code": exc.code, "details": []},
                status=exc.status,
            )
            return
        log_line(f"Job Hunt API failed: {type(exc).__name__}", tag="jobhunt", level="error")
        self.send_json(
            {
                "ok": False,
                "error": "Job Hunt operation failed",
                "code": "jobhunt_internal_error",
                "details": [],
            },
            status=500,
        )

    def dispatch_jobhunt_get(self, path, query_string=""):
        if not path.startswith("/api/jobhunt"):
            return False
        try:
            if path == "/api/jobhunt/health":
                self.send_json(JOBHUNT_SERVICE.health())
                return True
            if path == "/api/jobhunt/overview":
                self.send_json(JOBHUNT_SERVICE.overview())
                return True
            if path == "/api/jobhunt/jobs":
                query = urllib.parse.parse_qs(query_string)
                self.send_json(JOBHUNT_SERVICE.list_jobs(
                    limit=(query.get("limit") or [500])[0],
                    offset=(query.get("offset") or [0])[0],
                ))
                return True
            if path == "/api/jobhunt/settings/match":
                self.send_json(JOBHUNT_SERVICE.get_match_settings())
                return True
            if path == "/api/jobhunt/profile":
                self.send_json(JOBHUNT_SERVICE.get_profile())
                return True
            if path == "/api/jobhunt/assessments":
                self.send_json(JOBHUNT_SERVICE.list_assessments())
                return True
            if path == "/api/jobhunt/tracks":
                self.send_json(JOBHUNT_SERVICE.list_tracks())
                return True
            if path in {
                "/api/jobhunt/analytics/market",
                "/api/jobhunt/analytics/sources",
                "/api/jobhunt/analytics/applications",
                "/api/jobhunt/analytics/tradeoffs",
            }:
                query = urllib.parse.parse_qs(query_string)
                window = (query.get("window") or ["90d"])[0]
                if path.endswith("/market"):
                    response = JOBHUNT_SERVICE.get_market_analytics(
                        window=window,
                        track_id=(query.get("trackId") or [None])[0],
                        source=(query.get("source") or [None])[0],
                        geography=(query.get("geography") or [None])[0],
                    )
                elif path.endswith("/sources"):
                    response = JOBHUNT_SERVICE.get_source_analytics(window=window)
                elif path.endswith("/applications"):
                    response = JOBHUNT_SERVICE.get_application_analytics(
                        window=window,
                        track_id=(query.get("trackId") or [None])[0],
                        source=(query.get("source") or [None])[0],
                    )
                else:
                    raw_track_ids = query.get("trackId") or []
                    if not raw_track_ids and query.get("trackIds"):
                        raw_track_ids = (query.get("trackIds") or [""])[0].split(",")
                    response = JOBHUNT_SERVICE.get_tradeoff_analytics(raw_track_ids, window=window)
                self.send_json(response)
                return True
            if path == "/api/jobhunt/economic-scenarios":
                query = urllib.parse.parse_qs(query_string)
                self.send_json(JOBHUNT_SERVICE.list_economic_scenarios(
                    (query.get("trackId") or [None])[0]
                ))
                return True
            if path in {"/api/jobhunt/career-intelligence", "/api/jobhunt/career-intelligence/adjacent"}:
                response = (
                    JOBHUNT_SERVICE.get_career_intelligence()
                    if path.endswith("career-intelligence")
                    else JOBHUNT_SERVICE.get_adjacent_careers()
                )
                self.send_json(response)
                return True
            if path == "/api/jobhunt/career-intelligence/track-proposals":
                self.send_json(JOBHUNT_SERVICE.list_track_proposals())
                return True
            if path == "/api/jobhunt/experiments/templates":
                self.send_json(JOBHUNT_SERVICE.list_experiment_templates())
                return True
            if path == "/api/jobhunt/experiments":
                query = urllib.parse.parse_qs(query_string)
                self.send_json(JOBHUNT_SERVICE.list_experiments(
                    status=(query.get("status") or [None])[0],
                    track_id=(query.get("trackId") or [None])[0],
                    proposal_id=(query.get("proposalId") or [None])[0],
                ))
                return True
            if path == "/api/jobhunt/sources":
                self.send_json(JOBHUNT_SERVICE.list_sources())
                return True
            if path == "/api/jobhunt/worker/status":
                self.send_json(JOBHUNT_SERVICE.worker_status())
                return True
            if path == "/api/jobhunt/worker/jobs":
                query = urllib.parse.parse_qs(query_string)
                self.send_json(JOBHUNT_SERVICE.list_worker_jobs(
                    states=(query.get("states") or [None])[0],
                    limit=(query.get("limit") or [100])[0],
                ))
                return True
            if path == "/api/jobhunt/sources/nav/status":
                self.send_json(JOBHUNT_SERVICE.nav_status())
                return True
            if path == "/api/jobhunt/sources/nav/feed-state":
                self.send_json(JOBHUNT_SERVICE.nav_feed_state())
                return True
            if path == "/api/jobhunt/sources/pracuj/status":
                self.send_json(JOBHUNT_SERVICE.pracuj_status())
                return True
            if path == "/api/jobhunt/sources/pracuj/mail-state":
                self.send_json(JOBHUNT_SERVICE.pracuj_mail_state())
                return True
            if path == "/api/jobhunt/sources/pracuj/bindings":
                self.send_json(JOBHUNT_SERVICE.pracuj_bindings())
                return True
            if path == "/api/jobhunt/sources/jobbnorge/status":
                self.send_json(JOBHUNT_SERVICE.jobbnorge_status())
                return True
            if path == "/api/jobhunt/sources/jobbnorge/sync-state":
                self.send_json(JOBHUNT_SERVICE.jobbnorge_sync_state())
                return True
            if path == "/api/jobhunt/listings":
                query = urllib.parse.parse_qs(query_string)
                self.send_json(JOBHUNT_SERVICE.list_source_listings(
                    source_id=(query.get("sourceId") or [None])[0],
                    limit=(query.get("limit") or [200])[0],
                    offset=(query.get("offset") or [0])[0],
                ))
                return True
            if path == "/api/jobhunt/ingestion/storage-health":
                self.send_json(JOBHUNT_SERVICE.storage_health())
                return True
            if path == "/api/jobhunt/ai/status":
                self.send_json(JOBHUNT_SERVICE.ai_status())
                return True
            if path == "/api/jobhunt/ai/config-summary":
                self.send_json(JOBHUNT_SERVICE.ai_config_summary())
                return True
            if path == "/api/jobhunt/review":
                query = urllib.parse.parse_qs(query_string)
                self.send_json(JOBHUNT_SERVICE.list_reviews(
                    state=(query.get("state") or ["open"])[0],
                    limit=(query.get("limit") or [200])[0],
                ))
                return True
            if path == "/api/jobhunt/duplicates":
                query = urllib.parse.parse_qs(query_string)
                self.send_json(JOBHUNT_SERVICE.list_duplicates(
                    state=(query.get("state") or ["open"])[0],
                    limit=(query.get("limit") or [200])[0],
                ))
                return True
            if path == "/api/jobhunt/dedupe/merges":
                query = urllib.parse.parse_qs(query_string)
                self.send_json(JOBHUNT_SERVICE.list_dedupe_merges(
                    state=(query.get("state") or [None])[0],
                    limit=(query.get("limit") or [200])[0],
                ))
                return True
            if path == "/api/jobhunt/dedupe/summary":
                self.send_json(JOBHUNT_SERVICE.dedupe_summary())
                return True
            match = re.fullmatch(r"/api/jobhunt/duplicates/([^/]+)", path)
            if match:
                self.send_json(JOBHUNT_SERVICE.get_duplicate(urllib.parse.unquote(match.group(1))))
                return True
            match = re.fullmatch(r"/api/jobhunt/dedupe/merges/([^/]+)", path)
            if match:
                self.send_json(JOBHUNT_SERVICE.get_dedupe_merge(urllib.parse.unquote(match.group(1))))
                return True
            match = re.fullmatch(r"/api/jobhunt/worker/jobs/([^/]+)", path)
            if match:
                self.send_json(JOBHUNT_SERVICE.get_worker_job(urllib.parse.unquote(match.group(1))))
                return True
            match = re.fullmatch(r"/api/jobhunt/sources/([^/]+)", path)
            if match:
                self.send_json(JOBHUNT_SERVICE.get_source(urllib.parse.unquote(match.group(1))))
                return True
            match = re.fullmatch(r"/api/jobhunt/listings/([^/]+)/captures", path)
            if match:
                self.send_json(JOBHUNT_SERVICE.list_listing_captures(urllib.parse.unquote(match.group(1))))
                return True
            match = re.fullmatch(r"/api/jobhunt/listings/([^/]+)", path)
            if match:
                self.send_json(JOBHUNT_SERVICE.get_source_listing(urllib.parse.unquote(match.group(1))))
                return True
            match = re.fullmatch(r"/api/jobhunt/captures/([^/]+)", path)
            if match:
                self.send_json(JOBHUNT_SERVICE.get_raw_capture(urllib.parse.unquote(match.group(1))))
                return True
            match = re.fullmatch(r"/api/jobhunt/captures/([^/]+)/extraction-runs", path)
            if match:
                self.send_json(JOBHUNT_SERVICE.list_capture_extraction_runs(urllib.parse.unquote(match.group(1))))
                return True
            match = re.fullmatch(r"/api/jobhunt/extraction-runs/([^/]+)/facts", path)
            if match:
                self.send_json(JOBHUNT_SERVICE.get_extraction_facts(urllib.parse.unquote(match.group(1))))
                return True
            match = re.fullmatch(r"/api/jobhunt/extraction-runs/([^/]+)", path)
            if match:
                self.send_json(JOBHUNT_SERVICE.get_extraction_run(urllib.parse.unquote(match.group(1))))
                return True
            match = re.fullmatch(r"/api/jobhunt/review/([^/]+)", path)
            if match:
                self.send_json(JOBHUNT_SERVICE.get_review(urllib.parse.unquote(match.group(1))))
                return True
            match = re.fullmatch(r"/api/jobhunt/evaluations/([^/]+)", path)
            if match:
                self.send_json(JOBHUNT_SERVICE.get_evaluation(urllib.parse.unquote(match.group(1))))
                return True
            match = re.fullmatch(r"/api/jobhunt/experiments/([^/]+)", path)
            if match:
                self.send_json(JOBHUNT_SERVICE.get_experiment(urllib.parse.unquote(match.group(1))))
                return True
            match = re.fullmatch(r"/api/jobhunt/tracks/([^/]+)/skills/(intelligence|unmapped|meta)", path)
            if match:
                query = urllib.parse.parse_qs(query_string)
                values = {
                    "population": (query.get("population") or ["current"])[0],
                    "window": (query.get("window") or ["90d"])[0],
                    "requirement_class": (query.get("requirementClass") or ["all"])[0],
                    "user_state": (query.get("userState") or ["all"])[0],
                    "minimum_demand": (query.get("minimumDemand") or [0])[0],
                    "sort": (query.get("sort") or ["priority"])[0],
                }
                track_id = urllib.parse.unquote(match.group(1))
                action = match.group(2)
                response = {
                    "intelligence": JOBHUNT_SERVICE.get_track_skill_intelligence,
                    "unmapped": JOBHUNT_SERVICE.get_track_unmapped_skills,
                    "meta": JOBHUNT_SERVICE.get_track_skill_meta,
                }[action](track_id, **values)
                self.send_json(response)
                return True
            match = re.fullmatch(r"/api/jobhunt/tracks/([^/]+)/skills/([^/]+)", path)
            if match:
                query = urllib.parse.parse_qs(query_string)
                self.send_json(JOBHUNT_SERVICE.get_track_skill_detail(
                    urllib.parse.unquote(match.group(1)),
                    urllib.parse.unquote(match.group(2)),
                    population=(query.get("population") or ["current"])[0],
                    window=(query.get("window") or ["90d"])[0],
                ))
                return True
            match = re.fullmatch(r"/api/jobhunt/tracks/([^/]+)/evaluation-policy/history", path)
            if match:
                self.send_json(JOBHUNT_SERVICE.get_track_evaluation_policy_history(
                    urllib.parse.unquote(match.group(1))
                ))
                return True
            match = re.fullmatch(r"/api/jobhunt/tracks/([^/]+)/analytics", path)
            if match:
                query = urllib.parse.parse_qs(query_string)
                self.send_json(JOBHUNT_SERVICE.get_track_analytics(
                    urllib.parse.unquote(match.group(1)),
                    window=(query.get("window") or ["90d"])[0],
                ))
                return True
            match = re.fullmatch(r"/api/jobhunt/tracks/([^/]+)/evaluation-policy", path)
            if match:
                self.send_json(JOBHUNT_SERVICE.get_track_evaluation_policy(
                    urllib.parse.unquote(match.group(1))
                ))
                return True
            match = re.fullmatch(r"/api/jobhunt/tracks/([^/]+)/evaluations", path)
            if match:
                self.send_json(JOBHUNT_SERVICE.list_track_evaluations(
                    urllib.parse.unquote(match.group(1))
                ))
                return True
            match = re.fullmatch(r"/api/jobhunt/tracks/([^/]+)/search-profiles", path)
            if match:
                self.send_json(JOBHUNT_SERVICE.list_search_profiles(urllib.parse.unquote(match.group(1))))
                return True
            match = re.fullmatch(r"/api/jobhunt/tracks/([^/]+)", path)
            if match:
                self.send_json(JOBHUNT_SERVICE.get_track(urllib.parse.unquote(match.group(1))))
                return True
            match = re.fullmatch(r"/api/jobhunt/jobs/([^/]+)/tracks", path)
            if match:
                self.send_json(JOBHUNT_SERVICE.get_job_tracks(urllib.parse.unquote(match.group(1))))
                return True
            match = re.fullmatch(r"/api/jobhunt/jobs/([^/]+)/facts", path)
            if match:
                self.send_json(JOBHUNT_SERVICE.get_job_facts(urllib.parse.unquote(match.group(1))))
                return True
            match = re.fullmatch(r"/api/jobhunt/jobs/([^/]+)/evaluations", path)
            if match:
                self.send_json(JOBHUNT_SERVICE.list_job_evaluations(
                    urllib.parse.unquote(match.group(1))
                ))
                return True
            match = re.fullmatch(r"/api/jobhunt/assessments/([^/]+)", path)
            if match:
                query = urllib.parse.parse_qs(query_string)
                self.send_json(JOBHUNT_SERVICE.get_assessment(
                    urllib.parse.unquote(match.group(1)),
                    (query.get("version") or [None])[0],
                ))
                return True
            match = re.fullmatch(r"/api/jobhunt/assessment-runs/([^/]+)", path)
            if match:
                self.send_json(JOBHUNT_SERVICE.get_assessment_run(urllib.parse.unquote(match.group(1))))
                return True
            match = re.fullmatch(r"/api/jobhunt/jobs/([^/]+)", path)
            if match:
                self.send_json(JOBHUNT_SERVICE.get_job(urllib.parse.unquote(match.group(1))))
                return True
            match = re.fullmatch(r"/api/jobhunt/applications/([^/]+)", path)
            if match:
                self.send_json(JOBHUNT_SERVICE.get_application(urllib.parse.unquote(match.group(1))))
                return True
            match = re.fullmatch(r"/api/jobhunt/migrations/([^/]+)", path)
            if match:
                self.send_json(JOBHUNT_SERVICE.get_migration(urllib.parse.unquote(match.group(1))))
                return True
            self.send_json({"ok": False, "error": "Not found", "code": "not_found"}, status=404)
        except Exception as exc:
            self.send_jobhunt_error(exc)
        return True

    def dispatch_jobhunt_post(self, path):
        if not path.startswith("/api/jobhunt"):
            return False
        try:
            if path == "/api/jobhunt/jobs":
                payload = self.read_json_body(max_bytes=1024 * 1024)
                self.send_json(JOBHUNT_SERVICE.create_job(payload), status=201)
                return True
            if path == "/api/jobhunt/migrations/local-storage":
                payload = self.read_json_body(max_bytes=5 * 1024 * 1024)
                self.send_json(JOBHUNT_SERVICE.migrate_local_storage(payload))
                return True
            if path == "/api/jobhunt/assessment-runs":
                payload = self.read_json_body(max_bytes=64 * 1024)
                self.send_json(JOBHUNT_SERVICE.start_assessment(payload), status=201)
                return True
            if path == "/api/jobhunt/tracks":
                payload = self.read_json_body(max_bytes=64 * 1024)
                self.send_json(JOBHUNT_SERVICE.create_track(payload), status=201)
                return True
            if path == "/api/jobhunt/experiments":
                payload = self.read_json_body(max_bytes=128 * 1024)
                self.send_json(JOBHUNT_SERVICE.create_experiment(payload), status=201)
                return True
            if path == "/api/jobhunt/manual-import":
                payload = self.read_json_body(max_bytes=2 * 1024 * 1024)
                self.send_json(JOBHUNT_SERVICE.manual_import(payload), status=201)
                return True
            if path in {
                "/api/jobhunt/sources/nav/enable",
                "/api/jobhunt/sources/nav/pause",
                "/api/jobhunt/sources/nav/sync",
            }:
                payload = self.read_json_body(max_bytes=1024)
                action = path.rsplit("/", 1)[-1]
                response = {
                    "enable": JOBHUNT_SERVICE.nav_enable,
                    "pause": JOBHUNT_SERVICE.nav_pause,
                    "sync": JOBHUNT_SERVICE.nav_sync,
                }[action](payload)
                self.send_json(response, status=202 if action == "sync" else 200)
                return True
            if path in {
                "/api/jobhunt/sources/pracuj/enable",
                "/api/jobhunt/sources/pracuj/pause",
                "/api/jobhunt/sources/pracuj/sync",
            }:
                payload = self.read_json_body(max_bytes=1024)
                action = path.rsplit("/", 1)[-1]
                response = {
                    "enable": JOBHUNT_SERVICE.pracuj_enable,
                    "pause": JOBHUNT_SERVICE.pracuj_pause,
                    "sync": JOBHUNT_SERVICE.pracuj_sync,
                }[action](payload)
                self.send_json(response, status=202 if action == "sync" else 200)
                return True
            if path == "/api/jobhunt/sources/pracuj/bindings":
                payload = self.read_json_body(max_bytes=64 * 1024)
                self.send_json(JOBHUNT_SERVICE.create_pracuj_binding(payload), status=201)
                return True
            if path in {
                "/api/jobhunt/sources/jobbnorge/enable",
                "/api/jobhunt/sources/jobbnorge/pause",
                "/api/jobhunt/sources/jobbnorge/sync",
            }:
                payload = self.read_json_body(max_bytes=1024)
                action = path.rsplit("/", 1)[-1]
                response = {
                    "enable": JOBHUNT_SERVICE.jobbnorge_enable,
                    "pause": JOBHUNT_SERVICE.jobbnorge_pause,
                    "sync": JOBHUNT_SERVICE.jobbnorge_sync,
                }[action](payload)
                self.send_json(response, status=202 if action == "sync" else 200)
                return True
            match = re.fullmatch(r"/api/jobhunt/worker/jobs/([^/]+)/cancel", path)
            if match:
                self.read_json_body(max_bytes=1024)
                self.send_json(JOBHUNT_SERVICE.cancel_worker_job(
                    urllib.parse.unquote(match.group(1))
                ))
                return True
            match = re.fullmatch(r"/api/jobhunt/tracks/([^/]+)/economic-scenarios", path)
            if match:
                payload = self.read_json_body(max_bytes=128 * 1024)
                self.send_json(JOBHUNT_SERVICE.save_economic_scenario(
                    urllib.parse.unquote(match.group(1)), payload,
                ), status=201)
                return True
            match = re.fullmatch(r"/api/jobhunt/career-intelligence/track-proposals/([^/]+)/(save|accept|dismiss)", path)
            if match:
                payload = self.read_json_body(max_bytes=64 * 1024)
                self.send_json(JOBHUNT_SERVICE.decide_track_proposal(
                    urllib.parse.unquote(match.group(1)), match.group(2), payload,
                ))
                return True
            match = re.fullmatch(r"/api/jobhunt/experiments/([^/]+)/(start|complete|abandon|apply-insight|notes)", path)
            if match:
                payload = self.read_json_body(max_bytes=128 * 1024)
                experiment_id = urllib.parse.unquote(match.group(1))
                action = match.group(2)
                response = {
                    "start": JOBHUNT_SERVICE.start_experiment,
                    "complete": JOBHUNT_SERVICE.complete_experiment,
                    "abandon": JOBHUNT_SERVICE.abandon_experiment,
                    "apply-insight": JOBHUNT_SERVICE.apply_experiment_insight,
                    "notes": JOBHUNT_SERVICE.add_experiment_note,
                }[action](experiment_id, payload)
                self.send_json(response)
                return True
            match = re.fullmatch(r"/api/jobhunt/captures/([^/]+)/extract", path)
            if match:
                self.read_json_body(max_bytes=1024)
                self.send_json(JOBHUNT_SERVICE.extract_capture(urllib.parse.unquote(match.group(1))))
                return True
            match = re.fullmatch(r"/api/jobhunt/captures/([^/]+)/ai-extract", path)
            if match:
                payload = self.read_json_body(max_bytes=1024)
                self.send_json(JOBHUNT_SERVICE.ai_extract_capture(
                    urllib.parse.unquote(match.group(1)), payload
                ))
                return True
            match = re.fullmatch(r"/api/jobhunt/review/([^/]+)/(resolve|dismiss)", path)
            if match:
                payload = self.read_json_body(max_bytes=64 * 1024)
                self.send_json(JOBHUNT_SERVICE.close_review(
                    urllib.parse.unquote(match.group(1)), payload,
                    dismissed=match.group(2) == "dismiss",
                ))
                return True
            match = re.fullmatch(r"/api/jobhunt/duplicates/([^/]+)/(merge|not-duplicate|dismiss)", path)
            if match:
                payload = self.read_json_body(max_bytes=64 * 1024)
                candidate_id = urllib.parse.unquote(match.group(1))
                action = match.group(2)
                if action == "merge":
                    self.send_json(JOBHUNT_SERVICE.merge_duplicate(candidate_id, payload))
                else:
                    self.send_json(JOBHUNT_SERVICE.decide_duplicate(
                        candidate_id, payload, dismissed=action == "dismiss",
                    ))
                return True
            match = re.fullmatch(r"/api/jobhunt/dedupe/merges/([^/]+)/unmerge", path)
            if match:
                payload = self.read_json_body(max_bytes=64 * 1024)
                self.send_json(JOBHUNT_SERVICE.unmerge(
                    urllib.parse.unquote(match.group(1)), payload,
                ))
                return True
            match = re.fullmatch(r"/api/jobhunt/jobs/([^/]+)/dedupe-scan", path)
            if match:
                payload = self.read_json_body(max_bytes=1024)
                self.send_json(JOBHUNT_SERVICE.explicit_dedupe_scan(
                    urllib.parse.unquote(match.group(1)), payload,
                ))
                return True
            match = re.fullmatch(r"/api/jobhunt/jobs/([^/]+)/overrides", path)
            if match:
                payload = self.read_json_body(max_bytes=64 * 1024)
                self.send_json(JOBHUNT_SERVICE.create_override(
                    urllib.parse.unquote(match.group(1)), payload
                ), status=201)
                return True
            match = re.fullmatch(r"/api/jobhunt/jobs/([^/]+)/tracks/([^/]+)/evaluate", path)
            if match:
                payload = self.read_json_body(max_bytes=1024)
                self.send_json(JOBHUNT_SERVICE.explicit_evaluate_job_track(
                    urllib.parse.unquote(match.group(1)),
                    urllib.parse.unquote(match.group(2)),
                    payload,
                ))
                return True
            match = re.fullmatch(r"/api/jobhunt/tracks/([^/]+)/evaluation-policy", path)
            if match:
                payload = self.read_json_body(max_bytes=64 * 1024)
                self.send_json(JOBHUNT_SERVICE.create_track_evaluation_policy(
                    urllib.parse.unquote(match.group(1)), payload,
                ), status=201)
                return True
            match = re.fullmatch(r"/api/jobhunt/tracks/([^/]+)/search-profiles", path)
            if match:
                payload = self.read_json_body(max_bytes=64 * 1024)
                self.send_json(JOBHUNT_SERVICE.create_search_profile(
                    urllib.parse.unquote(match.group(1)), payload
                ), status=201)
                return True
            match = re.fullmatch(r"/api/jobhunt/jobs/([^/]+)/tracks", path)
            if match:
                payload = self.read_json_body(max_bytes=64 * 1024)
                self.send_json(JOBHUNT_SERVICE.set_job_tracks(
                    urllib.parse.unquote(match.group(1)), payload
                ))
                return True
            match = re.fullmatch(r"/api/jobhunt/profile/(experience|education|certifications|languages|skills|preferences|constraints|evidence)", path)
            if match:
                payload = self.read_json_body(max_bytes=64 * 1024)
                self.send_json(JOBHUNT_SERVICE.save_profile_record(match.group(1), payload), status=201)
                return True
            match = re.fullmatch(r"/api/jobhunt/assessment-runs/([^/]+)/(responses|complete|abandon)", path)
            if match:
                run_id = urllib.parse.unquote(match.group(1))
                action = match.group(2)
                if action == "responses":
                    payload = self.read_json_body(max_bytes=256 * 1024)
                    self.send_json(JOBHUNT_SERVICE.save_assessment_responses(run_id, payload))
                elif action == "complete":
                    self.read_json_body(max_bytes=1024)
                    self.send_json(JOBHUNT_SERVICE.complete_assessment(run_id))
                else:
                    self.read_json_body(max_bytes=1024)
                    self.send_json(JOBHUNT_SERVICE.abandon_assessment(run_id))
                return True
            match = re.fullmatch(r"/api/jobhunt/applications/([^/]+)/events", path)
            if match:
                payload = self.read_json_body(max_bytes=64 * 1024)
                self.send_json(JOBHUNT_SERVICE.application_command(
                    urllib.parse.unquote(match.group(1)), payload
                ))
                return True
            self.send_json({"ok": False, "error": "Not found", "code": "not_found"}, status=404)
        except Exception as exc:
            self.send_jobhunt_error(exc)
        return True

    def dispatch_jobhunt_patch(self, path):
        if not path.startswith("/api/jobhunt"):
            return False
        try:
            if path == "/api/jobhunt/settings/match":
                payload = self.read_json_body(max_bytes=64 * 1024)
                self.send_json(JOBHUNT_SERVICE.update_match_settings(payload))
                return True
            if path == "/api/jobhunt/profile":
                payload = self.read_json_body(max_bytes=64 * 1024)
                self.send_json(JOBHUNT_SERVICE.update_profile(payload))
                return True
            match = re.fullmatch(r"/api/jobhunt/experiments/([^/]+)", path)
            if match:
                payload = self.read_json_body(max_bytes=128 * 1024)
                self.send_json(JOBHUNT_SERVICE.update_experiment(
                    urllib.parse.unquote(match.group(1)), payload,
                ))
                return True
            match = re.fullmatch(r"/api/jobhunt/tracks/([^/]+)", path)
            if match:
                payload = self.read_json_body(max_bytes=64 * 1024)
                self.send_json(JOBHUNT_SERVICE.update_track(
                    urllib.parse.unquote(match.group(1)), payload
                ))
                return True
            match = re.fullmatch(r"/api/jobhunt/search-profiles/([^/]+)", path)
            if match:
                payload = self.read_json_body(max_bytes=64 * 1024)
                self.send_json(JOBHUNT_SERVICE.update_search_profile(
                    urllib.parse.unquote(match.group(1)), payload
                ))
                return True
            match = re.fullmatch(r"/api/jobhunt/sources/pracuj/bindings/([^/]+)", path)
            if match:
                payload = self.read_json_body(max_bytes=64 * 1024)
                self.send_json(JOBHUNT_SERVICE.update_pracuj_binding(
                    urllib.parse.unquote(match.group(1)), payload
                ))
                return True
            match = re.fullmatch(r"/api/jobhunt/profile/(experience|education|certifications|languages|skills|preferences|constraints|evidence)/([^/]+)", path)
            if match:
                payload = self.read_json_body(max_bytes=64 * 1024)
                self.send_json(JOBHUNT_SERVICE.save_profile_record(
                    match.group(1), payload, record_id=urllib.parse.unquote(match.group(2))
                ))
                return True
            match = re.fullmatch(r"/api/jobhunt/jobs/([^/]+)", path)
            if match:
                payload = self.read_json_body(max_bytes=1024 * 1024)
                self.send_json(JOBHUNT_SERVICE.update_job(
                    urllib.parse.unquote(match.group(1)), payload
                ))
                return True
            self.send_json({"ok": False, "error": "Not found", "code": "not_found"}, status=404)
        except Exception as exc:
            self.send_jobhunt_error(exc)
        return True

    def dispatch_jobhunt_delete(self, path):
        if not path.startswith("/api/jobhunt"):
            return False
        try:
            match = re.fullmatch(r"/api/jobhunt/jobs/([^/]+)", path)
            if match:
                self.send_json(JOBHUNT_SERVICE.delete_job(urllib.parse.unquote(match.group(1))))
                return True
            match = re.fullmatch(r"/api/jobhunt/profile/(experience|education|certifications|languages|skills|preferences|constraints|evidence)/([^/]+)", path)
            if match:
                self.send_json(JOBHUNT_SERVICE.delete_profile_record(
                    match.group(1), urllib.parse.unquote(match.group(2))
                ))
                return True
            self.send_json({"ok": False, "error": "Not found", "code": "not_found"}, status=404)
        except Exception as exc:
            self.send_jobhunt_error(exc)
        return True

    def send_mental_health_error(self, exc):
        if isinstance(exc, MentalHealthError):
            self.send_json(exc.as_payload(), status=exc.status)
            return
        if isinstance(exc, TimelineError):
            self.send_json(
                {"ok": False, "error": str(exc), "code": exc.code},
                status=exc.status,
            )
            return
        log_line(
            f"Mental Health API failed: {type(exc).__name__}",
            tag="mental-health",
            level="error",
        )
        self.send_json(
            {"ok": False, "error": "Mental Health operation failed", "code": "mental_health_internal_error"},
            status=500,
        )

    def dispatch_mental_health_get(self, path, query_string=""):
        if not path.startswith("/api/mental-health"):
            return False
        try:
            query = urllib.parse.parse_qs(query_string)
            if path == "/api/mental-health/health":
                self.send_json(MENTAL_HEALTH_STORE.health())
            elif path == "/api/mental-health/overview":
                self.send_json(MENTAL_HEALTH_STORE.overview())
            elif path == "/api/mental-health/registry":
                self.send_json({"instruments": MENTAL_HEALTH_STORE.overview()["registry"]})
            elif path == "/api/mental-health/assessments":
                self.send_json({"assessments": MENTAL_HEALTH_STORE.list_assessments(
                    instrument_id=(query.get("instrumentId") or [None])[0],
                    limit=int((query.get("limit") or [500])[0]),
                )})
            elif path == "/api/mental-health/analytics":
                self.send_json(MENTAL_HEALTH_STORE.analytics(int((query.get("days") or [90])[0])))
            elif path == "/api/mental-health/export":
                self.send_json(MENTAL_HEALTH_STORE.export_data())
            else:
                self.send_json({"ok": False, "error": "Not found", "code": "not_found"}, status=404)
        except (TypeError, ValueError) as exc:
            self.send_mental_health_error(MentalHealthError(str(exc)))
        except Exception as exc:
            self.send_mental_health_error(exc)
        return True

    def dispatch_mental_health_post(self, path):
        if not path.startswith("/api/mental-health"):
            return False
        try:
            payload = self.read_json_body(max_bytes=5 * 1024 * 1024)
            if path == "/api/mental-health/assessments":
                self.send_json(MENTAL_HEALTH_STORE.create_assessment(payload), status=201)
            elif path == "/api/mental-health/checkins":
                self.send_json(MENTAL_HEALTH_STORE.create_checkin(payload), status=201)
            elif path == "/api/mental-health/events":
                self.send_json(MENTAL_HEALTH_STORE.create_event(payload), status=201)
            elif path == "/api/mental-health/custom-questionnaires":
                self.send_json(MENTAL_HEALTH_STORE.create_custom_definition(payload), status=201)
            elif path == "/api/mental-health/settings":
                self.send_json(MENTAL_HEALTH_STORE.update_settings(payload))
            elif path == "/api/mental-health/import":
                self.send_json(MENTAL_HEALTH_STORE.import_data(payload))
            else:
                schedule_match = re.fullmatch(r"/api/mental-health/schedules/([^/]+)", path)
                baseline_match = re.fullmatch(r"/api/mental-health/assessments/([^/]+)/baseline", path)
                draft_match = re.fullmatch(r"/api/mental-health/drafts/([^/]+)", path)
                if schedule_match:
                    self.send_json(MENTAL_HEALTH_STORE.update_schedule(
                        urllib.parse.unquote(schedule_match.group(1)), payload
                    ))
                elif baseline_match:
                    self.send_json(MENTAL_HEALTH_STORE.set_baseline(
                        urllib.parse.unquote(baseline_match.group(1))
                    ))
                elif draft_match:
                    self.send_json(MENTAL_HEALTH_STORE.save_draft(
                        urllib.parse.unquote(draft_match.group(1)), payload
                    ))
                else:
                    self.send_json({"ok": False, "error": "Not found", "code": "not_found"}, status=404)
        except Exception as exc:
            self.send_mental_health_error(exc)
        return True

    def dispatch_mental_health_delete(self, path, query_string=""):
        if not path.startswith("/api/mental-health"):
            return False
        try:
            assessment_match = re.fullmatch(r"/api/mental-health/assessments/([^/]+)", path)
            checkin_match = re.fullmatch(r"/api/mental-health/checkins/([^/]+)", path)
            event_match = re.fullmatch(r"/api/mental-health/events/([^/]+)", path)
            if assessment_match:
                self.send_json(MENTAL_HEALTH_STORE.delete_assessment(urllib.parse.unquote(assessment_match.group(1))))
            elif checkin_match:
                self.send_json(MENTAL_HEALTH_STORE.delete_entry("checkins", urllib.parse.unquote(checkin_match.group(1))))
            elif event_match:
                self.send_json(MENTAL_HEALTH_STORE.delete_entry("events", urllib.parse.unquote(event_match.group(1))))
            elif path == "/api/mental-health/all":
                query = urllib.parse.parse_qs(query_string)
                if (query.get("confirm") or [""])[0] != "delete":
                    self.send_json({"ok": False, "error": "Deletion requires confirm=delete"}, status=409)
                else:
                    self.send_json(MENTAL_HEALTH_STORE.delete_all())
            else:
                self.send_json({"ok": False, "error": "Not found", "code": "not_found"}, status=404)
        except Exception as exc:
            self.send_mental_health_error(exc)
        return True

    def do_OPTIONS(self):
        self._cors_origin = None
        path = urlparse(self.path).path
        if not path.startswith("/api/"):
            self.send_response(404)
            self.end_headers()
            return
        origin = self.request_origin()
        if not is_allowed_api_origin(origin):
            self.send_response(403)
            self.end_headers()
            return
        self._cors_origin = origin
        self.send_response(204)
        self.end_headers()

    def do_HEAD(self):
        self._cors_origin = None
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/cleaning-dashboard" or path.startswith("/cleaning-dashboard/"):
            stripped_path = path.removeprefix("/cleaning-dashboard") or "/"
            self.path = stripped_path + (f"?{parsed.query}" if parsed.query else "")
            path = stripped_path
        if not self.authorize_static_request(path):
            return
        super().do_HEAD()

    def do_GET(self):
        self._cors_origin = None
        parsed = urlparse(self.path)
        path = parsed.path
        if not self.authorize_api_request(
            path,
            require_origin=path.startswith("/api/jobhunt/") or path.startswith("/api/mental-health/")
                or path.startswith("/api/phone-tracker/"),
        ):
            return
        if path == "/cleaning-dashboard" or path.startswith("/cleaning-dashboard/"):
            stripped_path = path.removeprefix("/cleaning-dashboard") or "/"
            self.path = stripped_path + (f"?{parsed.query}" if parsed.query else "")
            parsed = urlparse(self.path)
            path = parsed.path
        if not self.authorize_static_request(path):
            return
        if path == "/api/dashboard/runtime-status":
            self.send_json(read_dashboard_runtime_status(ROOT))
            return
        if dispatch_sync(self, JOURNAL_STORE):
            return
        if path == "/api/phone-todo":
            self.send_json({"ok": True, "items": phone_todo_active_items(read_json_file(settings_path("todo"), []))})
            return
        if self.dispatch_phone_tracker_get(path, parsed.query):
            return
        if self.dispatch_feelings_get(path, parsed.query):
            return
        if self.dispatch_jobhunt_get(path, parsed.query):
            return
        if self.dispatch_mental_health_get(path, parsed.query):
            return
        if path == "/api/language/health":
            try:
                self.send_json(LANGUAGE_SERVICE.health())
            except Exception as exc:
                self.send_language_error(exc)
            return
        if path == "/api/language/generation/provider-health":
            try:
                self.send_json(LANGUAGE_SERVICE.generation_provider_health())
            except Exception as exc:
                self.send_language_error(exc)
            return
        if path == "/api/language/reference/health":
            try:
                self.send_json(LANGUAGE_SERVICE.reference_health())
            except Exception as exc:
                self.send_language_error(exc)
            return
        if path == "/api/language/profiles":
            try:
                self.send_json(LANGUAGE_SERVICE.list_profiles())
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_anki_status_match = re.fullmatch(r"/api/language/profiles/([^/]+)/anki/status", path)
        if language_anki_status_match:
            try:
                self.send_json(LANGUAGE_SERVICE.anki_status(language_anki_status_match.group(1)))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_anki_insights_match = re.fullmatch(r"/api/language/profiles/([^/]+)/anki/insights", path)
        if language_anki_insights_match:
            try:
                params = urllib.parse.parse_qs(parsed.query)
                try:
                    offset = int((params.get("offset") or ["0"])[0])
                    limit = int((params.get("limit") or ["50"])[0])
                except ValueError as exc:
                    raise LanguageError("Anki pagination must use integers", code="invalid_anki_pagination", status=400) from exc
                refresh = (params.get("refresh") or ["false"])[0]
                if refresh not in {"true", "false"}:
                    raise LanguageError("refresh must be true or false", code="invalid_anki_refresh", status=400)
                self.send_json(LANGUAGE_SERVICE.anki_insights(
                    language_anki_insights_match.group(1), offset=offset, limit=limit,
                    query=(params.get("q") or [""])[0], refresh=refresh == "true",
                    deck_name=(params.get("deck") or [None])[0],
                ))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_anki_config_match = re.fullmatch(r"/api/language/profiles/([^/]+)/anki/config", path)
        if language_anki_config_match:
            try:
                self.send_json(LANGUAGE_SERVICE.anki_config(language_anki_config_match.group(1)))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_anki_decks_match = re.fullmatch(r"/api/language/profiles/([^/]+)/anki/decks", path)
        if language_anki_decks_match:
            try:
                self.send_json(LANGUAGE_SERVICE.anki_decks(language_anki_decks_match.group(1)))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_anki_models_match = re.fullmatch(r"/api/language/profiles/([^/]+)/anki/models", path)
        if language_anki_models_match:
            try:
                self.send_json(LANGUAGE_SERVICE.anki_models(language_anki_models_match.group(1)))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_anki_fields_match = re.fullmatch(r"/api/language/profiles/([^/]+)/anki/models/([^/]+)/fields", path)
        if language_anki_fields_match:
            try:
                self.send_json(LANGUAGE_SERVICE.anki_model_fields(
                    language_anki_fields_match.group(1), urllib.parse.unquote(language_anki_fields_match.group(2))
                ))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_anki_runs_match = re.fullmatch(r"/api/language/profiles/([^/]+)/anki/sync-runs", path)
        if language_anki_runs_match:
            try:
                query = urllib.parse.parse_qs(parsed.query)
                self.send_json(LANGUAGE_SERVICE.anki_sync_runs(
                    language_anki_runs_match.group(1), limit=(query.get("limit") or [20])[0]
                ))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_lemma_anki_match = re.fullmatch(r"/api/language/lemmas/([^/]+)/anki", path)
        if language_lemma_anki_match:
            try:
                self.send_json(LANGUAGE_SERVICE.get_lemma_anki(language_lemma_anki_match.group(1)))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_overview_match = re.fullmatch(r"/api/language/profiles/([^/]+)/overview", path)
        if language_overview_match:
            try:
                query = urllib.parse.parse_qs(parsed.query)
                self.send_json(LANGUAGE_SERVICE.overview(
                    language_overview_match.group(1),
                    as_of=(query.get("asOf") or [None])[0],
                ))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_today_match = re.fullmatch(r"/api/language/profiles/([^/]+)/today-summary", path)
        if language_today_match:
            try:
                self.send_json(LANGUAGE_SERVICE.today_summary(language_today_match.group(1)))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_surface_preview_match = re.fullmatch(r"/api/language/profiles/([^/]+)/lexical-preview", path)
        if language_surface_preview_match:
            try:
                query = urllib.parse.parse_qs(parsed.query)
                self.send_json(LANGUAGE_SERVICE.lookup_surface_preview(
                    language_surface_preview_match.group(1), (query.get("surface") or [""])[0]
                ))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_surface_meanings_match = re.fullmatch(r"/api/language/profiles/([^/]+)/lexical-meanings", path)
        if language_surface_meanings_match:
            try:
                query = urllib.parse.parse_qs(parsed.query)
                self.send_json(LANGUAGE_SERVICE.lookup_surface_meanings(
                    language_surface_meanings_match.group(1), (query.get("surface") or [""])[0]
                ))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_gamification_match = re.fullmatch(r"/api/language/profiles/([^/]+)/gamification", path)
        if language_gamification_match:
            try:
                query = urllib.parse.parse_qs(parsed.query)
                self.send_json(LANGUAGE_SERVICE.gamification(
                    language_gamification_match.group(1),
                    as_of=(query.get("asOf") or [None])[0],
                ))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_achievements_match = re.fullmatch(r"/api/language/profiles/([^/]+)/achievements", path)
        if language_achievements_match:
            try:
                query = urllib.parse.parse_qs(parsed.query)
                self.send_json(LANGUAGE_SERVICE.achievements(
                    language_achievements_match.group(1),
                    as_of=(query.get("asOf") or [None])[0],
                ))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_curriculum_item_match = re.fullmatch(
            r"/api/language/profiles/([^/]+)/curriculum/([^/]+)/versions/(\d+)/items/([a-f0-9]{32})",
            path,
        )
        if language_curriculum_item_match:
            try:
                self.send_json(LANGUAGE_SERVICE.curriculum_item(
                    language_curriculum_item_match.group(1),
                    urllib.parse.unquote(language_curriculum_item_match.group(2)),
                    language_curriculum_item_match.group(3),
                    language_curriculum_item_match.group(4),
                ))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_curriculum_pack_match = re.fullmatch(
            r"/api/language/profiles/([^/]+)/curriculum/([^/]+)/versions/(\d+)", path
        )
        if language_curriculum_pack_match:
            try:
                self.send_json(LANGUAGE_SERVICE.curriculum_pack(
                    language_curriculum_pack_match.group(1),
                    urllib.parse.unquote(language_curriculum_pack_match.group(2)),
                    language_curriculum_pack_match.group(3),
                ))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_benchmark_run_match = re.fullmatch(r"/api/language/profiles/([^/]+)/benchmarks/([a-f0-9]{32})", path)
        if language_benchmark_run_match:
            try:
                self.send_json(LANGUAGE_SERVICE.benchmark_run(*language_benchmark_run_match.groups()))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_benchmarks_match = re.fullmatch(r"/api/language/profiles/([^/]+)/benchmarks", path)
        if language_benchmarks_match:
            try:
                self.send_json(LANGUAGE_SERVICE.benchmark_runs(language_benchmarks_match.group(1)))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_norway_match = re.fullmatch(r"/api/language/profiles/([^/]+)/norway-preparation", path)
        if language_norway_match:
            try:
                self.send_json(LANGUAGE_SERVICE.norway_preparation(language_norway_match.group(1)))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_curriculum_match = re.fullmatch(r"/api/language/profiles/([^/]+)/curriculum", path)
        if language_curriculum_match:
            try:
                self.send_json(LANGUAGE_SERVICE.curriculum(language_curriculum_match.group(1)))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_collections_match = re.fullmatch(r"/api/language/profiles/([^/]+)/collections", path)
        if language_collections_match:
            try:
                self.send_json(LANGUAGE_SERVICE.collections(language_collections_match.group(1)))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_quests_match = re.fullmatch(r"/api/language/profiles/([^/]+)/quests", path)
        if language_quests_match:
            try:
                query = urllib.parse.parse_qs(parsed.query)
                self.send_json(LANGUAGE_SERVICE.quests(
                    language_quests_match.group(1), as_of=(query.get("asOf") or [None])[0]
                ))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_campaigns_match = re.fullmatch(r"/api/language/profiles/([^/]+)/campaigns", path)
        if language_campaigns_match:
            try:
                self.send_json(LANGUAGE_SERVICE.campaigns(language_campaigns_match.group(1)))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_statistics_match = re.fullmatch(r"/api/language/profiles/([^/]+)/statistics", path)
        if language_statistics_match:
            try:
                query = urllib.parse.parse_qs(parsed.query)
                self.send_json(LANGUAGE_SERVICE.statistics(
                    language_statistics_match.group(1),
                    range_name=(query.get("range") or ["30d"])[0],
                    as_of=(query.get("asOf") or [None])[0],
                ))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_listening_match = re.fullmatch(r"/api/language/profiles/([^/]+)/listening", path)
        if language_listening_match:
            try:
                query = urllib.parse.parse_qs(parsed.query)
                self.send_json(LANGUAGE_SERVICE.listening_materials(
                    language_listening_match.group(1), limit=(query.get("limit") or [100])[0]
                ))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_grammar_match = re.fullmatch(r"/api/language/profiles/([^/]+)/grammar(?:/patterns/([^/]+))?", path)
        if language_grammar_match:
            try:
                self.send_json(LANGUAGE_SERVICE.grammar_summary(*language_grammar_match.groups()))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_text_grammar_match = re.fullmatch(r"/api/language/texts/([^/]+)/grammar", path)
        if language_text_grammar_match:
            try:
                query = urllib.parse.parse_qs(parsed.query)
                self.send_json(LANGUAGE_SERVICE.text_grammar(language_text_grammar_match.group(1), (query.get("profileId") or [None])[0]))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_listening_progress_match = re.fullmatch(
            r"/api/language/texts/([^/]+)/listening-progress", path
        )
        if language_listening_progress_match:
            try:
                query = urllib.parse.parse_qs(parsed.query)
                self.send_json(LANGUAGE_SERVICE.listening_progress(
                    language_listening_progress_match.group(1),
                    profile_id=(query.get("profileId") or [None])[0],
                ))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_content_list_match = re.fullmatch(r"/api/language/profiles/([^/]+)/content", path)
        if language_content_list_match:
            try:
                query = urllib.parse.parse_qs(parsed.query)
                self.send_json(LANGUAGE_SERVICE.content_items(
                    language_content_list_match.group(1), limit=(query.get("limit") or [100])[0]
                ))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_content_media_match = re.fullmatch(r"/api/language/content/media/([^/]+)", path)
        if language_content_media_match:
            try:
                media_path, content_type = LANGUAGE_SERVICE.content_media_file(
                    language_content_media_match.group(1)
                )
                self.send_local_audio(media_path, content_type)
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_content_detail_match = re.fullmatch(r"/api/language/content/([^/]+)", path)
        if language_content_detail_match:
            try:
                self.send_json(LANGUAGE_SERVICE.content_detail(language_content_detail_match.group(1)))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_mistake_detail_match = re.fullmatch(
            r"/api/language/profiles/([^/]+)/mistakes/([^/]+)", path
        )
        if language_mistake_detail_match:
            try:
                query = urllib.parse.parse_qs(parsed.query)
                self.send_json(LANGUAGE_SERVICE.mistake_detail(
                    language_mistake_detail_match.group(1),
                    urllib.parse.unquote(language_mistake_detail_match.group(2)),
                    as_of=(query.get("asOf") or [None])[0],
                ))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_mistakes_match = re.fullmatch(r"/api/language/profiles/([^/]+)/mistakes", path)
        if language_mistakes_match:
            try:
                query = urllib.parse.parse_qs(parsed.query)
                self.send_json(LANGUAGE_SERVICE.mistakes(
                    language_mistakes_match.group(1),
                    as_of=(query.get("asOf") or [None])[0],
                    limit=(query.get("limit") or [10])[0],
                ))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_remediation_match = re.fullmatch(r"/api/language/profiles/([^/]+)/remediation", path)
        if language_remediation_match:
            try:
                query = urllib.parse.parse_qs(parsed.query)
                self.send_json(LANGUAGE_SERVICE.remediation(
                    language_remediation_match.group(1),
                    as_of=(query.get("asOf") or [None])[0],
                    limit=(query.get("limit") or [5])[0],
                ))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_cloze_tracks_match = re.fullmatch(r"/api/language/profiles/([^/]+)/cloze/tracks", path)
        if language_cloze_tracks_match:
            try:
                self.send_json(LANGUAGE_SERVICE.cloze_tracks(language_cloze_tracks_match.group(1)))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_cloze_statistics_match = re.fullmatch(r"/api/language/profiles/([^/]+)/cloze/statistics", path)
        if language_cloze_statistics_match:
            try:
                self.send_json(LANGUAGE_SERVICE.cloze_statistics(language_cloze_statistics_match.group(1)))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_cloze_session_match = re.fullmatch(r"/api/language/cloze/sessions/([^/]+)", path)
        if language_cloze_session_match:
            try:
                self.send_json(LANGUAGE_SERVICE.get_cloze_session(language_cloze_session_match.group(1)))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_cloze_audio_match = re.fullmatch(r"/api/language/cloze/audio/([a-f0-9]{64})\.mp3", path)
        if language_cloze_audio_match:
            try:
                audio_path, content_type = LANGUAGE_SERVICE.cloze_audio_file(language_cloze_audio_match.group(1))
                self.send_local_audio(audio_path, content_type)
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_generated_audio_match = re.fullmatch(r"/api/language/audio/([a-f0-9]{64})\.mp3", path)
        if language_generated_audio_match:
            try:
                audio_path, content_type = LANGUAGE_SERVICE.generated_audio_file(
                    language_generated_audio_match.group(1)
                )
                self.send_local_audio(audio_path, content_type)
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_plan_match = re.fullmatch(r"/api/language/profiles/([^/]+)/learning-plan", path)
        language_session_match = re.fullmatch(r"/api/language/profiles/([^/]+)/study-session", path)
        if language_session_match:
            try:
                query = urllib.parse.parse_qs(parsed.query)
                raw_minutes = (query.get("minutes") or [None])[0]
                if raw_minutes not in {"10", "20", "30"} or set(query) != {"minutes"} or len(query["minutes"]) != 1:
                    from language_learning.errors import LanguageValidationError
                    raise LanguageValidationError("minutes must be 10, 20, or 30", details=["minutes"])
                self.send_json(LANGUAGE_SERVICE.study_session(language_session_match.group(1), int(raw_minutes)))
            except Exception as exc:
                self.send_language_error(exc)
            return
        if language_plan_match:
            try:
                query = urllib.parse.parse_qs(parsed.query)
                self.send_json(LANGUAGE_SERVICE.learning_plan(
                    language_plan_match.group(1), as_of=(query.get("asOf") or [None])[0]
                ))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_widget_match = re.fullmatch(r"/api/language/profiles/([^/]+)/widget-summary", path)
        if language_widget_match:
            try:
                self.send_json(LANGUAGE_SERVICE.widget_summary(language_widget_match.group(1)))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_topics_match = re.fullmatch(r"/api/language/profiles/([^/]+)/topics", path)
        if language_topics_match:
            try:
                query = urllib.parse.parse_qs(parsed.query)
                self.send_json(LANGUAGE_SERVICE.list_topics(
                    language_topics_match.group(1),
                    include_archived=(query.get("includeArchived") or [False])[0],
                    as_of=(query.get("asOf") or [None])[0],
                ))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_topic_match = re.fullmatch(r"/api/language/topics/([^/]+)", path)
        if language_topic_match:
            try:
                self.send_json(LANGUAGE_SERVICE.get_topic(language_topic_match.group(1)))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_goals_match = re.fullmatch(r"/api/language/profiles/([^/]+)/goals", path)
        if language_goals_match:
            try:
                query = urllib.parse.parse_qs(parsed.query)
                self.send_json(LANGUAGE_SERVICE.list_goals(
                    language_goals_match.group(1), as_of=(query.get("asOf") or [None])[0]
                ))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_text_list_match = re.fullmatch(r"/api/language/profiles/([^/]+)/texts", path)
        if language_text_list_match:
            try:
                query = urllib.parse.parse_qs(parsed.query)
                self.send_json(LANGUAGE_SERVICE.list_texts(
                    language_text_list_match.group(1),
                    limit=(query.get("limit") or [50])[0],
                    cursor=(query.get("cursor") or [None])[0],
                ))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_series_list_match = re.fullmatch(r"/api/language/profiles/([^/]+)/reading-series", path)
        if language_series_list_match:
            try:
                self.send_json(LANGUAGE_SERVICE.list_reading_series(language_series_list_match.group(1)))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_profile_match = re.fullmatch(r"/api/language/profiles/([^/]+)", path)
        if language_profile_match:
            try:
                self.send_json(LANGUAGE_SERVICE.get_profile(language_profile_match.group(1)))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_vocabulary_anki_match = re.fullmatch(r"/api/language/profiles/([^/]+)/vocabulary/anki-status", path)
        if language_vocabulary_anki_match:
            try:
                query = urllib.parse.parse_qs(parsed.query)
                lemma_ids = (query.get("ids") or [""])[0].split(",") if query.get("ids") else []
                self.send_json(LANGUAGE_SERVICE.vocabulary_anki_status(
                    language_vocabulary_anki_match.group(1), lemma_ids,
                ))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_vocabulary_match = re.fullmatch(r"/api/language/profiles/([^/]+)/vocabulary", path)
        if language_vocabulary_match:
            try:
                query = urllib.parse.parse_qs(parsed.query)
                self.send_json(LANGUAGE_SERVICE.search_lemmas(
                    language_vocabulary_match.group(1),
                    query=(query.get("q") or [""])[0],
                    status=(query.get("status") or [None])[0],
                    disposition=(query.get("disposition") or [None])[0],
                    limit=(query.get("limit") or [50])[0],
                    cursor=(query.get("cursor") or [None])[0],
                ))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_phrasebook_list_match = re.fullmatch(r"/api/language/profiles/([^/]+)/phrasebook", path)
        if language_phrasebook_list_match:
            try:
                query = urllib.parse.parse_qs(parsed.query)
                self.send_json(LANGUAGE_SERVICE.list_phrasebook_entries(
                    language_phrasebook_list_match.group(1),
                    query=(query.get("q") or [""])[0],
                    source_type=(query.get("sourceType") or [None])[0],
                    limit=(query.get("limit") or [50])[0],
                    cursor=(query.get("cursor") or [None])[0],
                ))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_phrasebook_match = re.fullmatch(r"/api/language/phrasebook/([^/]+)", path)
        if language_phrasebook_match:
            try:
                self.send_json(LANGUAGE_SERVICE.get_phrasebook_entry(language_phrasebook_match.group(1)))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_lemma_lexical_match = re.fullmatch(r"/api/language/lemmas/([^/]+)/lexical-detail", path)
        language_word_audio_match = re.fullmatch(r"/api/language/(lemmas|tokens)/([^/]+)/audio", path)
        if language_word_audio_match:
            try:
                kind, word_id = language_word_audio_match.groups()
                result = (LANGUAGE_SERVICE.word_audio_for_lemma(word_id) if kind == "lemmas"
                          else LANGUAGE_SERVICE.word_audio_for_token(word_id))
                self.send_json(result)
            except Exception as exc:
                self.send_language_error(exc)
            return
        if language_lemma_lexical_match:
            try:
                self.send_json(LANGUAGE_SERVICE.get_lemma_lexical_detail(language_lemma_lexical_match.group(1)))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_lemma_preview_match = re.fullmatch(r"/api/language/lemmas/([^/]+)/preview", path)
        if language_lemma_preview_match:
            try:
                self.send_json(LANGUAGE_SERVICE.get_lemma_preview(language_lemma_preview_match.group(1)))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_lemma_reference_match = re.fullmatch(r"/api/language/lemmas/([^/]+)/reference", path)
        if language_lemma_reference_match:
            try:
                self.send_json(LANGUAGE_SERVICE.get_lemma_reference(language_lemma_reference_match.group(1)))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_lemma_match = re.fullmatch(r"/api/language/lemmas/([^/]+)", path)
        if language_lemma_match:
            try:
                self.send_json(LANGUAGE_SERVICE.get_lemma(language_lemma_match.group(1)))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_form_mapping_match = re.fullmatch(
            r"/api/language/forms/([^/]+)/mapping", path
        )
        if language_form_mapping_match:
            try:
                self.send_json(
                    LANGUAGE_SERVICE.get_form_mapping(
                        language_form_mapping_match.group(1)
                    )
                )
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_text_reference_match = re.fullmatch(r"/api/language/texts/([^/]+)/reference-profile", path)
        if language_text_reference_match:
            try:
                self.send_json(LANGUAGE_SERVICE.get_text_reference_profile(language_text_reference_match.group(1)))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_reader_study_notes_match = re.fullmatch(r"/api/language/texts/([^/]+)/study-notes", path)
        if language_reader_study_notes_match:
            try:
                self.send_json(LANGUAGE_SERVICE.reader_study_notes(language_reader_study_notes_match.group(1)))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_text_match = re.fullmatch(r"/api/language/texts/([^/]+)", path)
        language_generation_context_match = re.fullmatch(r"/api/language/generation-requests/([^/]+)/context-pack", path)
        if language_generation_context_match:
            try:
                self.send_json(LANGUAGE_SERVICE.get_generation_context(language_generation_context_match.group(1)))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_generation_candidates_match = re.fullmatch(r"/api/language/generation-requests/([^/]+)/candidates", path)
        if language_generation_candidates_match:
            try:
                self.send_json(LANGUAGE_SERVICE.list_generation_candidates(language_generation_candidates_match.group(1)))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_generation_request_match = re.fullmatch(r"/api/language/generation-requests/([^/]+)", path)
        if language_generation_request_match:
            try:
                self.send_json(LANGUAGE_SERVICE.get_generation_request(language_generation_request_match.group(1)))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_generation_revision_match = re.fullmatch(r"/api/language/generation-candidates/([^/]+)/revision-prompt", path)
        if language_generation_revision_match:
            try:
                self.send_json(LANGUAGE_SERVICE.generation_revision_prompt(language_generation_revision_match.group(1)))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_generation_candidate_match = re.fullmatch(r"/api/language/generation-candidates/([^/]+)", path)
        if language_generation_candidate_match:
            try:
                self.send_json(LANGUAGE_SERVICE.get_generation_candidate(language_generation_candidate_match.group(1)))
            except Exception as exc:
                self.send_language_error(exc)
            return
        if language_text_match:
            try:
                self.send_json(LANGUAGE_SERVICE.get_text(language_text_match.group(1)))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_job_match = re.fullmatch(r"/api/language/jobs/([^/]+)", path)
        if language_job_match:
            try:
                self.send_json(LANGUAGE_SERVICE.get_analysis_job(language_job_match.group(1)))
            except Exception as exc:
                self.send_language_error(exc)
            return
        if path == "/api/language/export":
            try:
                self.send_json(LANGUAGE_SERVICE.export_data())
            except Exception as exc:
                self.send_language_error(exc)
            return
        if path == "/api/ai-usage":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                history_hours = (query.get("historyHours") or [None])[0]
                session_limit = (query.get("sessionLimit") or [20])[0]
                self.send_json(AI_USAGE_SERVICE.get_dashboard(
                    history_hours=float(history_hours) if history_hours is not None else None,
                    session_limit=int(session_limit),
                ))
            except (TypeError, ValueError):
                self.send_json({"error": "Invalid AI usage query"}, status=400)
            except Exception as exc:
                log_line(f"AI usage state failed: {exc}", tag="ai-usage", level="error")
                self.send_json({"error": "Could not load AI usage"}, status=500)
            return
        if path == "/api/synchrobook/books":
            try:
                self.send_json(SYNCHROBOOK.list_books())
            except Exception as exc:
                log_line(f"Synchrobook library failed: {exc}", tag="synchrobook", level="error")
                self.send_json({"error": "Could not load the Synchrobook library"}, status=500)
            return
        if path == "/api/synchrobook/processing-settings":
            try:
                self.send_json(SYNCHROBOOK.get_processing_settings())
            except Exception as exc:
                log_line(f"Synchrobook settings failed: {exc}", tag="synchrobook", level="error")
                self.send_json({"error": "Could not load Synchrobook processing settings"}, status=500)
            return
        if path == "/api/synchrobook/jobs":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                limit = int((query.get("limit") or [30])[0])
                self.send_json(SYNCHROBOOK.list_jobs(limit))
            except (TypeError, ValueError):
                self.send_json({"error": "Invalid jobs limit", "code": "invalid_limit"}, status=400)
            except Exception as exc:
                log_line(f"Synchrobook jobs failed: {exc}", tag="synchrobook", level="error")
                self.send_json({"error": "Could not load Synchrobook jobs"}, status=500)
            return
        synchrobook_guide_match = re.fullmatch(
            r"/api/synchrobook/books/([a-f0-9]{32})/reading-guide", path
        )
        if synchrobook_guide_match:
            try:
                self.send_json(READING_GUIDE.state(synchrobook_guide_match.group(1)))
            except ReadingGuideError as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            except Exception as exc:
                log_line(f"Reading Guide state failed: {exc}", tag="synchrobook", level="error")
                self.send_json({"error": "Could not load Reading Guide"}, status=500)
            return
        synchrobook_job_match = re.fullmatch(r"/api/synchrobook/jobs/([a-f0-9]{32})", path)
        if synchrobook_job_match:
            try:
                self.send_json(SYNCHROBOOK.get_job(synchrobook_job_match.group(1)))
            except SynchrobookError as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            return
        synchrobook_artifact_match = re.fullmatch(
            r"/api/synchrobook/books/([a-f0-9]{32})/(alignment|report)", path
        )
        if synchrobook_artifact_match:
            try:
                self.send_json(SYNCHROBOOK.artifact(
                    synchrobook_artifact_match.group(1), synchrobook_artifact_match.group(2)
                ))
            except SynchrobookError as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            return
        synchrobook_media_match = re.fullmatch(
            r"/api/synchrobook/books/([a-f0-9]{32})/(audio|cover)", path
        )
        if synchrobook_media_match:
            try:
                media_path, content_type = SYNCHROBOOK.media_file(
                    synchrobook_media_match.group(1), synchrobook_media_match.group(2)
                )
                if synchrobook_media_match.group(2) == "audio":
                    self.send_local_audio(media_path, content_type)
                else:
                    self.send_bytes(media_path.read_bytes(), content_type, cache_seconds=86400)
            except SynchrobookError as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        synchrobook_book_match = re.fullmatch(r"/api/synchrobook/books/([a-f0-9]{32})", path)
        if synchrobook_book_match:
            try:
                self.send_json(SYNCHROBOOK.get_book(synchrobook_book_match.group(1)))
            except SynchrobookError as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            return
        if path == "/api/ring/state":
            try:
                state = RING_COLLECTOR.state()
                state["wear"] = RING_PHONE_BRIDGE.wear_state((state.get("device") or {}).get("deviceId"))
                self.send_json(state)
            except Exception as exc:
                log_line(f"Ring state failed: {exc}", tag="ring", level="error")
                self.send_json({"ok": False, "error": "Could not load ring state", "code": "ring_state_failed"}, status=500)
            return
        if path == "/api/ring/capabilities":
            try:
                state = RING_COLLECTOR.state()
                self.send_json({"ok": True, "capabilities": state["capabilities"]})
            except Exception as exc:
                log_line(f"Ring capabilities failed: {exc}", tag="ring", level="error")
                self.send_json({"ok": False, "error": "Could not load ring capabilities"}, status=500)
            return
        if path == "/api/ring/diagnostics":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                limit = max(1, min(500, int(query.get("limit", [100])[0] or 100)))
                self.send_json(RING_COLLECTOR.diagnostics(limit))
            except (TypeError, ValueError):
                self.send_json({"ok": False, "error": "Invalid diagnostics limit", "code": "invalid_limit"}, status=400)
            except Exception as exc:
                log_line(f"Ring diagnostics failed: {exc}", tag="ring", level="error")
                self.send_json({"ok": False, "error": "Could not load ring diagnostics"}, status=500)
            return
        if path == "/api/ring/history":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                limit = max(1, min(10000, int(query.get("limit", [2000])[0] or 2000)))
                self.send_json({"ok": True, **RING_COLLECTOR.store.history(limit=limit)})
            except (TypeError, ValueError):
                self.send_json({"ok": False, "error": "Invalid ring history limit", "code": "invalid_limit"}, status=400)
            except Exception as exc:
                log_line(f"Ring history failed: {exc}", tag="ring", level="error")
                self.send_json({"ok": False, "error": "Could not load ring history"}, status=500)
            return
        if path in {"/api/cleaning/state", "/api/cleaning/tasks", "/api/cleaning/history", "/api/cleaning/settings"}:
            try:
                query = urllib.parse.parse_qs(parsed.query)
                if path == "/api/cleaning/settings":
                    self.send_json(CLEANING_STORE.get_settings())
                    return
                apartment_id = (query.get("apartment") or [""])[0]
                if path == "/api/cleaning/state":
                    result = CLEANING_STORE.get_state(apartment_id)
                elif path == "/api/cleaning/tasks":
                    filters = {key: values[0] for key, values in query.items() if values}
                    result = {
                        "ok": True,
                        "apartmentId": apartment_id,
                        "tasks": CLEANING_STORE.get_tasks(apartment_id, filters),
                    }
                else:
                    result = CLEANING_STORE.get_history(
                        apartment_id,
                        (query.get("range") or ["month"])[0],
                        (query.get("offset") or [0])[0],
                    )
                self.send_json(result)
            except CleaningError as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            except Exception as exc:
                log_line(f"Cleaning read failed: {exc}", tag="cleaning", level="error")
                self.send_json({"error": "Could not load cleaning data"}, status=500)
            return
        if path == "/api/reading/state":
            try:
                self.send_json(READING_STORE.state())
            except ReadingError as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            except Exception as exc:
                log_line(f"Reading state failed: {exc}", tag="reading", level="error")
                self.send_json({"error": "Could not load reading state"}, status=500)
            return
        if path == "/api/reading/books":
            try:
                state = READING_STORE.state()
                self.send_json({"books": state["books"], "stats": state["stats"]})
            except ReadingError as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            except Exception as exc:
                log_line(f"Reading books failed: {exc}", tag="reading", level="error")
                self.send_json({"error": "Could not load reading books"}, status=500)
            return
        if path == "/api/reading/history":
            try:
                self.send_json(READING_STORE.history())
            except ReadingError as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            except Exception as exc:
                log_line(f"Reading history failed: {exc}", tag="reading", level="error")
                self.send_json({"error": "Could not load reading history"}, status=500)
            return
        if path == "/api/reading/settings":
            try:
                self.send_json(READING_STORE.get_settings())
            except ReadingError as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            except Exception as exc:
                log_line(f"Reading settings failed: {exc}", tag="reading", level="error")
                self.send_json({"error": "Could not load reading settings"}, status=500)
            return
        if path == "/api/habits/health":
            self.send_json(HABITS_STORE.health())
            return
        if path == "/api/habits/snapshot":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                self.send_json(HABITS_STORE.snapshot(
                    from_date=query.get("from", [None])[0],
                    to_date=query.get("to", [None])[0],
                ))
            except HabitsError as exc:
                self.send_json({"error": str(exc), "code": exc.code}, status=exc.status)
            except Exception as exc:
                log_line(f"Snapshot failed: {exc}", tag="habits", level="error")
                self.send_json({"error": "Could not load habits"}, status=500)
            return
        if path == "/api/habits/supplements":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                self.send_json(SUPPLEMENTS_STORE.snapshot(query.get("date", [None])[0]))
            except ValueError as exc:
                self.send_json({"error": str(exc)}, status=400)
            except Exception as exc:
                log_line(f"Supplement snapshot failed: {exc}", tag="habits", level="error")
                self.send_json({"error": "Could not load supplements"}, status=500)
            return
        if path == "/api/live-workout/plan":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                self.send_json(LIVE_WORKOUT_PLAN_SERVICE.response(query.get("date", [None])[0]))
            except (ValueError, OSError, json.JSONDecodeError) as exc:
                log_line(f"Live Workout plan failed: {exc}", tag="live-workout", level="error")
                self.send_json({"error": "Could not load workout plan"}, status=500)
            return
        if path == "/api/strength/dashboard":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                self.send_json(STRENGTH_STORE.dashboard((query.get("week") or [None])[0]))
            except StrengthError as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            except Exception as exc:
                log_line(f"Strength dashboard failed: {exc}", tag="strength", level="error")
                self.send_json({"error": "Could not load Strength dashboard"}, status=500)
            return
        if path == "/api/strength/exercises":
            self.send_json({"exercises": STRENGTH_STORE.exercises()})
            return
        if path == "/api/strength/history":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                limit = max(1, min(1000, int((query.get("limit") or [200])[0])))
                self.send_json({"sets": STRENGTH_STORE.history(limit)})
            except (TypeError, ValueError):
                self.send_json({"error": "Invalid Strength history limit"}, status=400)
            return
        if path == "/api/strength/equipment":
            self.send_json({"items": STRENGTH_STORE.equipment()})
            return
        if path == "/api/strength/settings":
            self.send_json(STRENGTH_STORE.settings())
            return
        if path == "/api/live-workout/session":
            self.send_json({"session": LIVE_WORKOUT_STORE.active_dashboard_session()})
            return
        if path == "/api/live-workout/history":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                limit = max(1, min(200, int(query.get("limit", [30])[0] or 30)))
                self.send_json({"sessions": LIVE_WORKOUT_STORE.history(limit=limit)})
            except (TypeError, ValueError):
                self.send_json({"error": "Invalid history limit"}, status=400)
            except Exception as exc:
                log_line(f"Live Workout history failed: {exc}", tag="api", level="error")
                self.send_json({"error": "Could not load workout history"}, status=500)
            return
        if path == "/api/live-workout/latest":
            self.send_json({"telemetry": latest_live_workout_telemetry()})
            return
        if path == "/api/live-workout/heart-rate-history":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                limit = max(1, min(100000, int(query.get("limit", [1000])[0] or 1000)))
                from_timestamp = query.get("from", [None])[0]
                to_timestamp = query.get("to", [None])[0]
                watch_samples = LIVE_WORKOUT_STORE.heart_rate_history(
                    limit=limit,
                    from_timestamp=int(from_timestamp) if from_timestamp is not None else None,
                    to_timestamp=int(to_timestamp) if to_timestamp is not None else None,
                )
                try:
                    ring_archive = RING_COLLECTOR.store.heart_rate_archive(
                        limit=limit,
                        from_timestamp=int(from_timestamp) if from_timestamp is not None else None,
                        to_timestamp=int(to_timestamp) if to_timestamp is not None else None,
                    )
                except Exception as exc:
                    log_line(f"COLMI HR fallback unavailable: {exc}", tag="ring", level="warning")
                    ring_archive = {"heartRate": [], "watchHeartRateReference": []}
                samples = merge_heart_rate_archive_sources(watch_samples, ring_archive, limit)
                self.send_json({
                    "samples": samples,
                    "sources": {
                        "smartwatch": sum(1 for sample in samples if sample.get("source") == "smartwatch"),
                        "smartRing": sum(1 for sample in samples if sample.get("source") == "smart_ring"),
                    },
                })
            except (TypeError, ValueError):
                self.send_json({"error": "Invalid heart-rate history query"}, status=400)
            except Exception as exc:
                log_line(f"Heart-rate history failed: {exc}", tag="api", level="error")
                self.send_json({"error": "Could not load heart-rate history"}, status=500)
            return
        if path == "/api/live-workout/backup":
            try:
                self.send_json(read_live_workout_backup())
            except Exception as exc:
                log_line(f"Live Workout backup failed: {exc}", tag="api", level="error")
                self.send_json({"error": "Could not create workout backup"}, status=500)
            return
        live_workout_session_match = re.fullmatch(
            r"/api/live-workout/history/([a-zA-Z0-9-]+)", path
        )
        if live_workout_session_match:
            try:
                session = LIVE_WORKOUT_STORE.session(live_workout_session_match.group(1))
                if not session:
                    self.send_json({"error": "Workout session not found"}, status=404)
                else:
                    self.send_json(session)
            except Exception as exc:
                log_line(f"Live Workout session failed: {exc}", tag="api", level="error")
                self.send_json({"error": "Could not load workout session"}, status=500)
            return
        if path == "/api/live-workout/stream":
            self.send_live_workout_stream()
            return
        if path == "/spotify-screensaver":
            self.path = "/spotify-screensaver.html"
            super().do_GET()
            return
        if path == "/artist-facts-screensaver":
            self.path = "/artist-facts-screensaver.html"
            super().do_GET()
            return
        if path == "/classical-library" or path.startswith("/classical-library/composer/"):
            self.path = "/classical-library.html"
            super().do_GET()
            return
        if path == "/timeline":
            self.path = "/timeline.html"
            super().do_GET()
            return
        if path == "/journal-ocr":
            self.path = "/journal-ocr.html"
            super().do_GET()
            return
        if path.startswith("/assets/"):
            asset_path = ROOT / "public" / urllib.parse.unquote(path.lstrip("/"))
            if asset_path.exists() and asset_path.is_file():
                self.path = f"/public{path}"
                super().do_GET()
                return
        if path.startswith("/posters/"):
            self.path = f"/public{path}"
            super().do_GET()
            return
        if path.startswith("/artist-media/"):
            name = Path(urllib.parse.unquote(path.removeprefix("/artist-media/"))).name
            media_path = ARTIST_MEDIA_CACHE_DIR / name
            if not media_path.exists() or media_path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
                self.send_error(404)
                return
            content_type = {
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".png": "image/png",
                ".webp": "image/webp",
                ".gif": "image/gif",
            }.get(media_path.suffix.lower(), "application/octet-stream")
            self.send_bytes(media_path.read_bytes(), content_type, cache_seconds=604800)
            return
        if path == "/api/journal-htr/status":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                runtime = JOURNAL_HTR_RUNTIME.snapshot()
                health_override = None
                if runtime["state"] != "online":
                    health_override = {
                        "online": False,
                        "error": runtime.get("detail") or "Serwer OCR jest zatrzymany.",
                        "code": f"runtime_{runtime['state']}",
                    }
                payload = JOURNAL_HTR.status(
                    force_health=query.get("refresh") == ["1"],
                    health_override=health_override,
                )
                payload["runtime"] = runtime
                self.send_json(payload)
            except JournalHtrError as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            except Exception as exc:
                log_line(f"Journal HTR status failed: {type(exc).__name__}", tag="api", level="error")
                self.send_json({"error": "Could not load Journal HTR status"}, status=500)
            return
        if path == "/api/journal-htr/projects":
            try:
                self.send_json({"projects": JOURNAL_HTR._require_store().list_projects()})
            except JournalHtrError as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            return
        if path == "/api/journal-htr/pages":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                project_id = (query.get("projectId") or [None])[0]
                self.send_json({"pages": JOURNAL_HTR.list_pages(project_id)})
            except JournalHtrError as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            return
        htr_page_file_match = re.fullmatch(r"/api/journal-htr/pages/([a-f0-9]{32})/file", path)
        if htr_page_file_match:
            try:
                query = urllib.parse.parse_qs(parsed.query)
                variant = (query.get("variant") or ["working"])[0]
                file_path, content_type = JOURNAL_HTR.image_file(
                    htr_page_file_match.group(1), variant
                )
                self.send_bytes(
                    file_path.read_bytes(),
                    content_type,
                    cache_seconds=0,
                )
            except JournalHtrError as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            return
        if path == "/api/journal-htr/lines":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                filters = {
                    "status": (query.get("status") or [None])[0],
                    "language": (query.get("language") or [None])[0],
                    "projectId": (query.get("projectId") or [None])[0],
                    "modelId": (query.get("modelId") or [None])[0],
                    "dateFrom": (query.get("dateFrom") or [None])[0],
                    "dateTo": (query.get("dateTo") or [None])[0],
                }
                filters = {key: value for key, value in filters.items() if value}
                training_value = (query.get("useForTraining") or [None])[0]
                if training_value in {"true", "false"}:
                    filters["useForTraining"] = training_value == "true"
                if (query.get("segmentationIssue") or [""])[0] == "true":
                    filters["segmentationIssue"] = True
                page_id = (query.get("pageId") or [None])[0]
                self.send_json({
                    "lines": JOURNAL_HTR._require_store().list_lines(
                        page_id=page_id, filters=filters
                    )
                })
            except JournalHtrError as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            return
        htr_revision_match = re.fullmatch(
            r"/api/journal-htr/lines/([a-f0-9]{32})/revisions", path
        )
        if htr_revision_match:
            try:
                self.send_json({
                    "revisions": JOURNAL_HTR._require_store().line_revisions(
                        htr_revision_match.group(1)
                    )
                })
            except JournalHtrError as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            return
        if path == "/api/journal-htr/dataset/stats":
            self.send_json(JOURNAL_HTR._require_store().dataset_stats())
            return
        if path == "/api/journal-htr/datasets":
            self.send_json({"datasets": JOURNAL_HTR._require_store().list_datasets()})
            return
        if path == "/api/journal-htr/models":
            self.send_json({"models": JOURNAL_HTR.list_models()})
            return
        if path == "/api/journal-htr/jobs":
            self.send_json({"jobs": JOURNAL_HTR._require_store().list_jobs()})
            return
        htr_job_match = re.fullmatch(r"/api/journal-htr/jobs/([a-f0-9]{32})", path)
        if htr_job_match:
            try:
                self.send_json(JOURNAL_HTR._require_store().get_job(htr_job_match.group(1)))
            except JournalHtrError as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            return
        if path == "/api/voice-journal/health":
            try:
                self.send_json(voice_journal_health())
            except Exception as exc:
                log_line(f"Voice journal health check failed: {exc}", tag="api", level="error")
                self.send_json({"status": "error", "error": "Voice journal health check failed"}, status=500)
            return
        if path == "/api/timeline":
            try:
                self.send_json(TIMELINE_STORE.snapshot())
            except Exception as exc:
                log_line(f"Timeline load failed: {exc}", tag="api", level="error")
                self.send_json({"error": "Could not load timeline"}, status=500)
            return
        if path == "/api/timeline/summary":
            try:
                self.send_json(TIMELINE_STORE.summary())
            except Exception as exc:
                log_line(f"Timeline summary failed: {exc}", tag="api", level="error")
                self.send_json({"error": "Could not load timeline summary"}, status=500)
            return
        if path == "/api/timeline/activity":
            try:
                query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
                today = date.today()
                from_day = query.get("from", [(today - timedelta(days=36525)).isoformat()])[0]
                to_day = query.get("to", [today.isoformat()])[0]
                raw_sources = query.get("sources", [""])[0]
                sources = [value.strip() for value in raw_sources.split(",") if value.strip()] if "sources" in query else None
                journal_content = query.get("journalContent", ["full"])[0]
                self.send_json(TIMELINE_ACTIVITY.query(from_day, to_day, sources, journal_content))
            except ValueError as exc:
                self.send_json({"error": str(exc), "code": "invalid_activity_query"}, status=400)
            except Exception as exc:
                log_line(f"Timeline activity load failed: {exc}", tag="api", level="error")
                self.send_json({"error": "Could not load timeline activity"}, status=500)
            return
        if path == "/api/lastfm/status":
            try:
                self.send_json(LASTFM_STORE.status())
            except Exception as exc:
                log_line(f"Last.fm status failed: {exc}", tag="lastfm", level="error")
                self.send_json({"error": "Could not load Last.fm status"}, status=500)
            return
        if path == "/api/journal/entries":
            try:
                self.send_json({"entries": JOURNAL_STORE.list()})
            except JournalError as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            except Exception as exc:
                log_line(f"Journal list failed: {exc}", tag="api", level="error")
                self.send_json({"error": "Could not load journal entries"}, status=500)
            return
        journal_entry_match = re.fullmatch(r"/api/journal/entries/([a-f0-9]{32})", path)
        if journal_entry_match:
            try:
                self.send_json(JOURNAL_STORE.get(journal_entry_match.group(1)))
            except JournalError as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            except Exception as exc:
                log_line(f"Journal entry read failed: {exc}", tag="api", level="error")
                self.send_json({"error": "Could not load journal entry"}, status=500)
            return
        if path == "/api/voice-journal/entries":
            try:
                entries = VOICE_JOURNAL_STORE.list()
                publications = JOURNAL_STORE.voice_publication_lookup()
                for entry in entries:
                    entry["journalPublication"] = publications.get(entry.get("id"))
                self.send_json({"entries": entries})
            except (JournalError, VoiceJournalError) as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            except Exception as exc:
                log_line(f"Voice journal list failed: {exc}", tag="api", level="error")
                self.send_json({"error": "Could not load voice journal entries"}, status=500)
            return
        job_result_match = re.fullmatch(r"/api/voice-journal/jobs/([a-f0-9]{32})/result", path)
        if job_result_match:
            try:
                self.send_json(VOICE_JOURNAL_JOBS.result(job_result_match.group(1)))
            except VoiceJournalError as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            except Exception as exc:
                log_line(f"Voice journal job result failed: {exc}", tag="api", level="error")
                self.send_json({"error": "Could not load transcription result"}, status=500)
            return
        job_match = re.fullmatch(r"/api/voice-journal/jobs/([a-f0-9]{32})", path)
        if job_match:
            try:
                self.send_json(VOICE_JOURNAL_JOBS.get(job_match.group(1)))
            except VoiceJournalError as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            except Exception as exc:
                log_line(f"Voice journal job status failed: {exc}", tag="api", level="error")
                self.send_json({"error": "Could not load transcription job"}, status=500)
            return
        audio_match = re.fullmatch(r"/api/voice-journal/entries/([a-f0-9]{32})/audio", path)
        if audio_match:
            try:
                audio_path, content_type, _ = VOICE_JOURNAL_STORE.audio_file(audio_match.group(1))
                self.send_local_audio(audio_path, content_type)
            except VoiceJournalError as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as exc:
                log_line(f"Voice journal audio failed: {exc}", tag="api", level="error")
                self.send_json({"error": "Could not stream voice journal audio"}, status=500)
            return
        if path == "/api/spotify/status":
            self.send_json(spotify_status())
            return
        if path == "/api/spotify/auth/start":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                auth_url = make_spotify_auth_url((query.get("next") or [""])[0])
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=400)
                return
            self.send_response(302)
            self.send_header("Location", auth_url)
            self.end_headers()
            return
        if path == "/api/spotify/oauth/callback":
            try:
                next_url = handle_spotify_callback(urllib.parse.parse_qs(parsed.query))
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=400)
                return
            self.send_response(302)
            self.send_header("Location", next_url)
            self.end_headers()
            return
        if path == "/api/screensaver-status":
            self.send_json(read_spotify_screensaver_status())
            return
        if path == "/api/screensaver-config":
            self.send_json(read_spotify_screensaver_config())
            return
        if path == "/api/budget/receipts":
            try:
                query = {key: values[0] for key, values in urllib.parse.parse_qs(parsed.query).items()}
                self.send_json({"ok": True, "receipts": FINANCE_SERVICE.list_receipts(
                    status=query.get("status") or None, limit=int(query.get("limit") or 200)
                )})
            except FinanceError as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=400)
            return
        if path == "/api/budget/receipts/processing-health":
            try:
                self.send_json({"ok": True, "health": FINANCE_SERVICE.receipt_processing_health()})
            except FinanceError as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=400)
            return
        receipt_sources_match = re.fullmatch(r"/api/budget/receipts/([^/]+)/sources", path)
        if receipt_sources_match:
            try:
                self.send_json({"ok": True, "sources": FINANCE_SERVICE.receipt_sources(receipt_sources_match.group(1))})
            except FinanceNotFoundError as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=404)
            return
        receipt_source_content_match = re.fullmatch(r"/api/budget/receipts/([^/]+)/sources/([^/]+)/content", path)
        if receipt_source_content_match:
            try:
                source = FINANCE_SERVICE.receipt_source_content(
                    receipt_source_content_match.group(1), receipt_source_content_match.group(2)
                )
                self.send_bytes(
                    source["content"], source["mimeType"], cache_seconds=0,
                    extra_headers={
                        "Content-Disposition": "inline",
                        "X-Content-Type-Options": "nosniff",
                        "Content-Security-Policy": "sandbox; default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'",
                    },
                )
            except FinanceNotFoundError as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=404)
            except FinanceError as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=400)
            return
        receipt_item_crop_match = re.fullmatch(r"/api/budget/receipt-items/([^/]+)/crop", path)
        if receipt_item_crop_match:
            try:
                crop = FINANCE_SERVICE.receipt_item_crop(receipt_item_crop_match.group(1))
                self.send_bytes(
                    crop["content"], crop["mimeType"], cache_seconds=0,
                    extra_headers={
                        "Content-Disposition": "inline",
                        "X-Content-Type-Options": "nosniff",
                        "Content-Security-Policy": "sandbox; default-src 'none'; img-src 'self'",
                    },
                )
            except FinanceNotFoundError as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=404)
            except FinanceError as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=400)
            return
        receipt_detail_match = re.fullmatch(r"/api/budget/receipts/([^/]+)", path)
        if receipt_detail_match:
            try:
                self.send_json({"ok": True, "receipt": FINANCE_SERVICE.receipt_detail(receipt_detail_match.group(1))})
            except FinanceNotFoundError as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=404)
            except FinanceError as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=400)
            return
        if path == "/api/budget/receipt-items/review/groups":
            self.send_json({"ok": True, "groups": FINANCE_SERVICE.receipt_item_groups()})
            return
        if path == "/api/budget/product-categories":
            self.send_json({"ok": True, "categories": FINANCE_SERVICE.receipt_product_categories()})
            return
        product_detail_match = re.fullmatch(r"/api/budget/products/([^/]+)", path)
        if product_detail_match:
            try:
                self.send_json({"ok": True, "product": FINANCE_SERVICE.receipt_product(product_detail_match.group(1))})
            except FinanceNotFoundError as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=404)
            return
        barcode_lookup_match = re.fullmatch(r"/api/budget/products/barcode/(\d+)", path)
        if barcode_lookup_match:
            try:
                self.send_json({"ok": True, **FINANCE_SERVICE.lookup_receipt_barcode(barcode_lookup_match.group(1))})
            except FinanceError as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=400)
            return
        if path == "/api/budget/companion/status":
            self.send_json({"ok": True, "connected": True})
            return
        if path == "/api/budget/companion/devices":
            self.send_json({"ok": True, "devices": FINANCE_SERVICE.companion_devices()})
            return
        if path == "/api/budget":
            try:
                self.send_json({"ok": True, "data": read_budget_payload(), "storage": "sqlite"})
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=500)
            return
        if path == "/api/budget/export/transactions.csv":
            try:
                query = {key: values[0] for key, values in urllib.parse.parse_qs(parsed.query).items()}
                self.send_bytes(FINANCE_SERVICE.export_transactions_csv(query), "text/csv; charset=utf-8", cache_seconds=0)
            except FinanceError as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=400)
            return
        if path == "/api/budget/categories":
            try:
                self.send_json({"ok": True, "categories": FINANCE_SERVICE.categories()})
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=500)
            return
        if path == "/api/budget/merchants":
            try:
                self.send_json({"ok": True, "merchants": FINANCE_SERVICE.merchants()})
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=500)
            return
        if path == "/api/budget/merchant-types":
            try:
                self.send_json({"ok": True, "merchantTypes": FINANCE_SERVICE.merchant_types()})
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=500)
            return
        if path == "/api/budget/rules":
            try:
                self.send_json({"ok": True, "rules": FINANCE_SERVICE.rules()})
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=500)
            return
        planning_match = re.fullmatch(
            r"/api/budget/(overview|data-quality|accounts|onboarding|classification-bootstrap|obligations|subscriptions|bills|upcoming|recurring-candidates|budgets|budget-suggestion|planned-items|goals|safe-to-spend|forecast|report|trends|category-trends|merchant-trends|recurring-trends|insights)",
            path,
        )
        if planning_match:
            try:
                query = {key: values[0] for key, values in urllib.parse.parse_qs(parsed.query).items()}
                self.send_json({"ok": True, "data": FINANCE_SERVICE.planning_payload(planning_match.group(1), query)})
            except FinanceNotFoundError as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=404)
            except FinanceError as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=400)
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=500)
            return
        if path == "/api/budget/review":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                status = (query.get("status") or ["open"])[0]
                limit = int((query.get("limit") or ["500"])[0])
                self.send_json({"ok": True, "items": FINANCE_SERVICE.review_items(status, limit)})
            except FinanceError as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=400)
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=500)
            return
        if path == "/api/budget/review/groups":
            try:
                query = {key: values[0] for key, values in urllib.parse.parse_qs(parsed.query).items()}
                self.send_json({"ok": True, "data": FINANCE_SERVICE.review_groups(query)})
            except FinanceError as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=400)
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=500)
            return
        review_group_transactions_match = re.fullmatch(r"/api/budget/review/groups/([^/]+)/transactions", path)
        if review_group_transactions_match:
            try:
                self.send_json({"ok": True, "transactions": FINANCE_SERVICE.review_group_transactions(review_group_transactions_match.group(1))})
            except FinanceNotFoundError as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=404)
            except FinanceError as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=400)
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=500)
            return
        if path == "/api/budget/periods":
            try:
                query = {key: values[0] for key, values in urllib.parse.parse_qs(parsed.query).items()}
                self.send_json({"ok": True, "period": FINANCE_SERVICE.resolve_period(query)})
            except FinanceValidationError as exc:
                self.send_json({"ok": False, "error": str(exc), **exc.result}, status=400)
            return
        analytics_match = re.fullmatch(r"/api/budget/analytics/([a-z-]+)", path)
        if analytics_match:
            try:
                query = {key: values[0] for key, values in urllib.parse.parse_qs(parsed.query).items()}
                self.send_json({
                    "ok": True,
                    "period": FINANCE_SERVICE.resolve_period(query),
                    "data": FINANCE_SERVICE.analytics_payload(analytics_match.group(1), query),
                })
            except FinanceValidationError as exc:
                self.send_json({"ok": False, "error": str(exc), **exc.result}, status=400)
            except FinanceNotFoundError as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=404)
            return
        explanation_match = re.fullmatch(r"/api/budget/transactions/([^/]+)/classification", path)
        if explanation_match:
            try:
                self.send_json({
                    "ok": True,
                    "classification": FINANCE_SERVICE.classification_explanation(explanation_match.group(1)),
                })
            except FinanceNotFoundError as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=404)
            return
        if path == "/api/budget/summary":
            try:
                self.send_json({"ok": True, "summary": FINANCE_SERVICE.summary()})
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=500)
            return
        if path == "/api/budget/transactions":
            try:
                query = {key: values[0] for key, values in urllib.parse.parse_qs(parsed.query).items()}
                self.send_json({"ok": True, **FINANCE_SERVICE.query_transactions(query)})
            except FinanceValidationError as exc:
                self.send_json({"ok": False, "error": str(exc), **exc.result}, status=400)
            return
        if path == "/api/budget/imports":
            try:
                self.send_json({"ok": True, "imports": FINANCE_SERVICE.import_history()})
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=500)
            return
        rollback_preview_match = re.fullmatch(r"/api/budget/imports/([^/]+)/rollback-preview", path)
        if rollback_preview_match:
            try:
                self.send_json({"ok": True, "preview": FINANCE_SERVICE.rollback_import_preview(rollback_preview_match.group(1))})
            except FinanceNotFoundError as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=404)
            return
        if path.startswith("/api/settings/"):
            try:
                name = urllib.parse.unquote(path.removeprefix("/api/settings/"))
                self.send_json(read_settings_payload(name))
            except ValueError as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=404)
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=500)
            return
        if path == "/api/artist-facts":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                self.send_json(read_artist_facts_for((query.get("artist") or [""])[0]))
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=500)
            return
        if path == "/api/kitchen/image":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                data, content_type = fetch_kitchen_image(query.get("u", [""])[0])
                self.send_bytes(data, content_type)
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=400)
            return
        if path == "/api/kitchen/settings":
            try:
                self.send_json(read_kitchen_settings())
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=500)
            return
        if path == "/api/events":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                sync_google = str(query.get("sync", ["1"])[0] or "1").lower() in {"1", "true", "yes"}
                include_local = str(query.get("local", ["1"])[0] or "1").lower() in {"1", "true", "yes"}
                include_google = str(query.get("google", ["1"])[0] or "1").lower() in {"1", "true", "yes"}
                include_past = str(query.get("past", ["0"])[0] or "0").lower() in {"1", "true", "yes"}
                try:
                    window_days = int(query.get("days", ["0"])[0] or 0)
                except (TypeError, ValueError):
                    window_days = 0
                self.send_json(
                    read_events_payload(
                        sync_google=sync_google,
                        include_local=include_local,
                        include_google=include_google,
                        include_past=include_past,
                        window_days=window_days if window_days > 0 else None,
                    )
                )
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=500)
            return
        if path == "/api/kitchen/scores":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                force = str(query.get("force", ["0"])[0] or "0").lower() in {"1", "true", "yes"}
                self.send_json({**read_kitchen_scores(force=force), "footballPresentation": read_football_settings()})
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc), "matches": []}, status=500)
            return
        if path == "/api/football":
            try:
                self.send_json(read_football_dashboard())
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=500)
            return
        if path in {"/api/football/entity", "/api/football/search", "/api/football/learn", "/api/football/refresh"}:
            try:
                query = urllib.parse.parse_qs(parsed.query)
                if path.endswith("/learn"):
                    self.send_json({"ok": True, "items": read_json_file(ROOT / "data" / "football-knowledge.json", [])})
                elif path.endswith("/refresh"):
                    read_kitchen_scores()  # No force; respect the shared refresh policy.
                    self.send_json(read_football_dashboard())
                elif path.endswith("/search"):
                    self.send_json({"ok": True, "items": football_hub().search(read_football_dashboard(), query.get("q", [""])[0], query.get("kind", [""])[0])})
                else:
                    self.send_json(football_hub().detail(query.get("type", [""])[0], query.get("id", [""])[0],
                        query.get("section", ["overview"])[0], read_football_dashboard(), query.get("year", [""])[0]))
            except ValueError as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=404)
            except Exception:
                self.send_json({"ok": False, "error": "Football service temporarily unavailable"}, status=503)
            return
        if path == "/api/football/settings":
            self.send_json(read_football_settings())
            return
        if path == "/api/kitchen/debug":
            try:
                self.send_json(read_kitchen_debug())
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=500)
            return
        if path == "/api/kitchen/weather":
            try:
                self.send_json(read_kitchen_weather())
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=500)
            return
        if path == "/api/cinema-city/repertoire":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                force = (query.get("refresh") or ["0"])[0] == "1"
                repertoire = read_cinema_city_repertoire(force=force)
                self.send_json(apply_repertoire_filters(repertoire, read_cinema_city_filters()))
            except CinemaCityRepertoireError as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=502)
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=500)
            return
        if path == "/api/cinema-city/monthly-stats":
            try:
                self.send_json(read_cinema_city_monthly_stats())
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc), "google": google_calendar_status()}, status=500)
            return
        if path == "/api/google-calendar/status":
            self.send_json({"ok": True, "google": google_calendar_status()})
            return
        if path == "/api/google-calendar/calendars":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                refresh = str(query.get("refresh", ["0"])[0] or "0").lower() in {"1", "true", "yes"}
                calendars = list_google_calendars() if refresh else google_calendars_for_sync(force_refresh=False)
                self.send_json({"ok": True, "calendars": calendars, "google": google_calendar_status()})
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=500)
            return
        if path == "/api/google-calendar/auth/start":
            try:
                auth_url = make_google_calendar_auth_url()
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=400)
                return
            self.send_response(302)
            self.send_header("Location", auth_url)
            self.end_headers()
            return
        if path == "/api/google-calendar/oauth/callback":
            try:
                status_payload = handle_google_calendar_callback(urllib.parse.parse_qs(parsed.query))
                sync_error = ""
                try:
                    sync_all_google_calendars(force=True)
                except Exception as exc:
                    sync_error = str(exc)
                body = (
                    "<!doctype html><meta charset='utf-8'>"
                    "<title>Google Calendar connected</title>"
                    "<body style='font-family:system-ui;background:#111;color:#eee;padding:32px'>"
                    "<h1>Google Calendar connected</h1>"
                    "<p>Możesz zamknąć tę kartę i odświeżyć dashboard.</p>"
                    f"<pre>{json.dumps({'status': status_payload, 'syncError': sync_error}, ensure_ascii=False, indent=2)}</pre>"
                    "</body>"
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=400)
            return
        if path == "/api/google-calendar/sync":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                force = str(query.get("force", ["0"])[0] or "0").lower() in {"1", "true", "yes"}
                self.send_json(sync_all_google_calendars(force=force))
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=500)
            return
        if path == "/api/weight/dashboard-summary":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                weight_days = max(1, min(3650, int(query.get("weight_days", [30])[0] or 30)))
                steps_days = max(1, min(3650, int(query.get("steps_days", [30])[0] or 30)))
                weight_period = str(query.get("weight_period", ["0"])[0]).lower() in {"1", "true", "yes"}
                steps_all = str(query.get("steps_all", ["0"])[0]).lower() in {"1", "true", "yes"}
                self.send_json(
                    read_weight_dashboard_summary(
                        weight_days=weight_days,
                        weight_end=query.get("weight_end", [None])[0],
                        weight_period=weight_period,
                        steps_days=steps_days,
                        steps_end=query.get("steps_end", [None])[0],
                        steps_all=steps_all,
                    )
                )
            except ValueError:
                self.send_json({"ok": False, "error": "Invalid dashboard summary range"}, status=400)
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=500)
            return
        if path == "/api/weight/latest":
            try:
                self.send_json(read_latest_weight_measurement())
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=500)
            return
        if path == "/api/weight/signal":
            try:
                self.send_json(read_scale_signal())
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=500)
            return
        if path == "/api/weight/history":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                limit_days = int(query.get("days", [90])[0] or 90)
                fill_missing = str(query.get("fill", ["0"])[0] or "0").lower() in {"1", "true", "yes"}
                end_day = query.get("end", [None])[0]
                self.send_json(
                    read_weight_history(
                        limit_days=limit_days,
                        fill_missing=fill_missing,
                        end_day=end_day,
                    )
                )
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=500)
            return
        if path == "/api/weight/events":
            try:
                self.send_json(read_weight_events())
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=500)
            return
        if path == "/api/weight/stats":
            try:
                self.send_json(read_weight_stats())
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=500)
            return
        if path == "/api/sensor/latest":
            try:
                self.send_json(read_sensor_latest())
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=500)
            return
        if path == "/api/sensor/history":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                hours = float(query.get("hours", [24])[0] or 24)
                date_value = query.get("date", [None])[0]
                month_value = query.get("month", [None])[0]
                self.send_json(read_sensor_history(
                    hours=hours,
                    date_value=date_value,
                    month_value=month_value,
                ))
            except ValueError as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=400)
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=500)
            return
        if path == "/api/steps/history":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                limit_days = int(query.get("days", [30])[0] or 30)
                end_day = query.get("end", [None])[0]
                self.send_json(read_steps_history(limit_days=limit_days, end_day=end_day))
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=500)
            return
        if path == "/api/steps/events":
            try:
                self.send_json(read_steps_events())
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=500)
            return
        if path == "/api/steps/exclusions":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                requested_day = query.get("day", [date.today().isoformat()])[0]
                self.send_json(live_workout_step_exclusions(requested_day))
            except ValueError as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=400)
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=500)
            return
        if path == "/api/steps/stream":
            self.send_step_stream()
            return
        if path == "/api/health-connect/latest":
            try:
                self.send_json(read_health_latest())
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=500)
            return
        if path == "/api/health-connect/history":
            try:
                self.send_json(read_health_sleep_history())
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=500)
            return
        if path == "/api/diet/days":
            try:
                self.send_json(read_diet_days())
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=500)
            return
        if path == "/api/diet/history":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                limit_days = int(query.get("days", [30])[0] or 30)
                end_day = query.get("end", [None])[0]
                self.send_json(read_diet_history(limit_days=limit_days, end_day=end_day))
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=500)
            return
        if path == "/api/films/summary":
            try:
                self.send_json(fetch_film_summary())
            except Exception as exc:
                self.send_json({"error": str(exc)}, status=500)
            return
        if path == "/api/films/lists":
            try:
                self.send_json({"lists": fetch_film_lists()})
            except Exception as exc:
                self.send_json({"error": str(exc)}, status=500)
            return
        if path == "/api/films/library":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                list_slug = clean_text(query.get("list", [None])[0])
                q = clean_text(query.get("q", [None])[0])
                limit, offset = normalize_film_library_pagination(
                    query.get("limit", [FILM_LIBRARY_DEFAULT_LIMIT])[0],
                    query.get("offset", [0])[0],
                )
                self.send_json(
                    fetch_film_library(
                        list_slug=list_slug,
                        query=q,
                        limit=limit,
                        offset=offset,
                    )
                )
            except ValueError as exc:
                self.send_json({"error": str(exc)}, status=400)
            except Exception as exc:
                self.send_json({"error": str(exc)}, status=500)
            return
        if path == "/api/films/search":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                q = clean_text(query.get("q", [None])[0])
                limit = int(query.get("limit", [8])[0] or 8)
                self.send_json({"results": search_films_wikipedia(q, limit=limit)})
            except Exception as exc:
                self.send_json({"error": str(exc)}, status=500)
            return
        if path == "/api/classical-library":
            try:
                self.send_json(fetch_classical_library())
            except Exception as exc:
                self.send_json({"error": str(exc)}, status=500)
            return
        if path == "/api/classical-library/summary":
            try:
                self.send_json(build_classical_summary())
            except Exception as exc:
                self.send_json({"error": str(exc)}, status=500)
            return
        if path == "/api/classical-library/composer":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                composer_id = clean_text(query.get("composerId", [None])[0])
                composer = read_classical_composer(composer_id)
                if not composer:
                    self.send_json({"error": "Composer not found"}, status=404)
                    return
                self.send_json({"ok": True, "composer": composer, "progress": read_classical_progress()})
            except Exception as exc:
                self.send_json({"error": str(exc)}, status=500)
            return
        if path == "/api/classical-library/search-composers":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                q = clean_text(query.get("q", [None])[0])
                limit = int(query.get("limit", [10])[0] or 10)
                self.send_json({"ok": True, "results": search_classical_composers(q, limit=limit)})
            except Exception as exc:
                self.send_json({"error": str(exc)}, status=500)
            return
        if path == "/api/music/overview":
            try:
                payload = MUSIC_STORE.overview()
                payload["lastfm"] = MUSIC_STORE.decorate_history_media(
                    LASTFM_STORE.music_history(period="today", limit=8, include_live=True)
                )
                self.send_json(payload)
            except (MusicError, LastFmError) as exc:
                status = getattr(exc, "status", 400)
                self.send_json(exc.as_payload() if isinstance(exc, MusicError) else {"error": str(exc)}, status=status)
            except Exception as exc:
                log_line(f"Music overview failed: {exc}", tag="music", level="error")
                self.send_json({"error": "Could not load Music overview"}, status=500)
            return
        if path == "/api/music/library":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                filters = {key: values[0] for key, values in query.items() if values}
                library = MUSIC_STORE.list_releases(filters)
                MUSIC_ENRICHMENT.prioritize_visible_covers(library['rows'])
                self.send_json(library)
            except (MusicError, ValueError) as exc:
                self.send_json(exc.as_payload() if isinstance(exc, MusicError) else {"error": str(exc)}, status=getattr(exc, "status", 400))
            return
        if path == "/api/music/missing-metadata":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                filters = {key: values[0] for key, values in query.items() if values}
                self.send_json(MUSIC_STORE.missing_metadata(filters))
            except (MusicError, ValueError) as exc:
                self.send_json(exc.as_payload() if isinstance(exc, MusicError) else {"error": str(exc)}, status=getattr(exc, "status", 400))
            return
        if path == "/api/music/enrichment/status":
            self.send_json(MUSIC_ENRICHMENT.status())
            return
        music_release_match = re.fullmatch(r"/api/music/releases/(\d+)", path)
        if music_release_match:
            try:
                payload = MUSIC_STORE.release_detail(int(music_release_match.group(1)))
                release = payload["release"]
                matched = LASTFM_STORE.match_albums([{"artist": release["artist_credit"], "album": release["title"]}])
                payload["lastfm"] = (matched.get("albums") or [None])[0]
                self.send_json(payload)
            except (MusicError, TimelineError) as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            except Exception as exc:
                log_line(f"Music release load failed: {exc}", tag="music", level="error")
                self.send_json({"error": "Could not load Music release"}, status=500)
            return
        if path == "/api/music/genres/tree":
            self.send_json(MUSIC_STORE.genre_tree())
            return
        if path == "/api/music/genres":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                self.send_json(MUSIC_STORE.genres({key: values[0] for key, values in query.items() if values}))
            except (MusicError, ValueError) as exc:
                self.send_json(exc.as_payload() if isinstance(exc, MusicError) else {"error": str(exc)}, status=getattr(exc, "status", 400))
            return
        music_genre_match = re.fullmatch(r"/api/music/genres/(\d+)", path)
        if music_genre_match:
            try:
                self.send_json(MUSIC_STORE.genre_detail(int(music_genre_match.group(1))))
            except MusicError as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            return
        if path == "/api/music/rankings/artists":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                ranking = MUSIC_STORE.artist_ranking(
                    min_ratings=(query.get("minRatings") or [3])[0],
                    limit=(query.get("limit") or [100])[0],
                    offset=(query.get("offset") or [0])[0],
                    sort=(query.get("sort") or ["weighted"])[0],
                    period={key: values[0] for key, values in query.items() if values},
                )
                MUSIC_ENRICHMENT.prioritize_artist_photos(row['name'] for row in ranking['rows'] if not row.get('image'))
                self.send_json(ranking)
            except (MusicError, ValueError) as exc:
                self.send_json(exc.as_payload() if isinstance(exc, MusicError) else {"error": str(exc)},
                               status=getattr(exc, "status", 400))
            return
        if path == "/api/music/rankings":
            self.send_json(MUSIC_STORE.rankings())
            return
        music_ranking_match = re.fullmatch(r"/api/music/rankings/(\d+)", path)
        if music_ranking_match:
            try:
                self.send_json(MUSIC_STORE.ranking_detail(int(music_ranking_match.group(1))))
            except MusicError as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            return
        if path == "/api/music/lists":
            self.send_json(MUSIC_STORE.lists())
            return
        if path == "/api/music/search":
            query = urllib.parse.parse_qs(parsed.query)
            self.send_json(MUSIC_STORE.search((query.get("q") or [""])[0], (query.get("limit") or [8])[0]))
            return
        music_import_match = re.fullmatch(r"/api/music/imports/(\d+)", path)
        if music_import_match:
            try:
                self.send_json(MUSIC_STORE.get_import(int(music_import_match.group(1))))
            except MusicError as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            return
        if path == "/api/music/lastfm":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                history = LASTFM_STORE.music_history(
                    period=(query.get("period") or ["all"])[0],
                    limit=(query.get("limit") or [30])[0],
                    offset=(query.get("offset") or [0])[0],
                    include_live=(query.get("live") or ["0"])[0] in {"1", "true", "yes"},
                )
                history = MUSIC_STORE.decorate_history_media(history)
                MUSIC_ENRICHMENT.prioritize_artist_photos(row['artist'] for row in history['topArtists'] if not row.get('image'))
                self.send_json(history)
            except LastFmError as exc:
                self.send_json({"error": str(exc)}, status=400)
            return
        if path == "/api/brutal-assault-2027/albums":
            try:
                result = brutal_assault_2027_snapshot_with_cross_list()
                result["communityRatingsPending"] = BRUTAL_ASSAULT_2027_RATINGS.schedule(
                    result.get("rows") or []
                )
                self.send_json(result)
            except Exception as exc:
                log_line(f"Brutal Assault 2027 load failed: {exc}", tag="api", level="error")
                self.send_json({"error": "Could not load Brutal Assault 2027 albums"}, status=500)
            return
        if path == "/api/brutal-assault-2027/official":
            try:
                self.send_json(BRUTAL_ASSAULT_2027_MONITOR.snapshot())
            except Exception as exc:
                log_line(f"BA2027 monitor state load failed: {exc}", tag="api", level="error")
                self.send_json({"error": "Could not load official BA2027 status"}, status=500)
            return
        if path == "/api/rym-polish-black-metal/albums":
            try:
                self.send_json(rym_polish_black_metal_snapshot_with_cross_lists())
            except Exception as exc:
                log_line(f"RYM Polish BM load failed: {exc}", tag="api", level="error")
                self.send_json({"error": "Could not load RYM Polish black-metal albums"}, status=500)
            return
        if path == "/api/bm365/state":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                self.send_json(BM365_STORE.get_state((query.get("today") or [None])[0]))
            except Bm365Error as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            except Exception as exc:
                log_line(f"BM365 state load failed: {exc}", tag="api", level="error")
                self.send_json({"error": "Could not load BM365 state"}, status=500)
            return
        if path == "/api/bm365/albums":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                filters = {key: values[0] for key, values in query.items() if values}
                self.send_json(BM365_STORE.snapshot(filters))
            except Bm365Error as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            except Exception as exc:
                log_line(f"BM365 albums load failed: {exc}", tag="api", level="error")
                self.send_json({"error": "Could not load BM365 albums"}, status=500)
            return
        if path == "/api/bm365/summary":
            try:
                self.send_json(BM365_STORE.get_summary())
            except Exception as exc:
                log_line(f"BM365 summary load failed: {exc}", tag="api", level="error")
                self.send_json({"error": "Could not load BM365 summary"}, status=500)
            return
        if path == "/api/bm365/metadata":
            try:
                self.send_json(bm365_metadata_snapshot())
            except Exception as exc:
                log_line(f"BM365 metadata load failed: {exc}", tag="api", level="error")
                self.send_json({"error": "Could not load BM365 metadata"}, status=500)
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
            self.send_json(dict(LAST_UPDATE))
            return
        if path == "/":
            self.path = "/index.html"
        super().do_GET()

    def do_POST(self):
        self._cors_origin = None
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/live-workout/telemetry":
            authorization = str(self.headers.get("Authorization") or "").strip()
            auth_scheme = authorization.split(" ", 1)[0] if authorization else "none"
            supplied_token = extract_dashboard_token(self.headers)
            log_line(
                "POST arrived "
                f"client={self.client_address[0]}:{self.client_address[1]} "
                f"content_length={self.headers.get('Content-Length') or 'missing'} "
                f"content_type={self.headers.get('Content-Type') or 'missing'} "
                f"origin={self.headers.get('Origin') or 'none'} "
                f"auth_scheme={auth_scheme} token_fp={token_fingerprint(supplied_token)}",
                tag="live-workout",
                level="info",
                console=False,
            )
        if not self.authorize_api_request(path, require_origin=True):
            return
        if dispatch_sync(self, JOURNAL_STORE):
            return
        if path == "/api/phone-todo":
            try:
                payload = self.read_json_body(max_bytes=4096)
                items = update_phone_todo_file(
                    settings_path("todo"), payload, file_write_lock,
                    temp_path_for_atomic_write, replace_file_with_retries,
                )
                self.send_json({"ok": True, "items": items})
            except ValueError as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=400)
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=500)
            return
        if self.dispatch_phone_tracker_post(path):
            return
        if self.dispatch_feelings_post(path):
            return
        if self.dispatch_jobhunt_post(path):
            return
        if self.dispatch_mental_health_post(path):
            return
        language_content_audio_match = re.fullmatch(r"/api/language/profiles/([^/]+)/content/audio", path)
        if language_content_audio_match:
            try:
                try:
                    length = int(self.headers.get("Content-Length", ""))
                except (TypeError, ValueError) as exc:
                    raise TimelineError("Valid Content-Length is required", status=411, code="invalid_content_length") from exc
                if length <= 0:
                    raise TimelineError("Audio body is required", code="empty_body")
                if length > MAX_MEDIA_BYTES:
                    raise TimelineError("Audio file exceeds the 64 MiB limit", status=413, code="media_too_large")
                raw = self.rfile.read(length)
                if len(raw) != length:
                    raise TimelineError("Incomplete audio upload", code="incomplete_body")
                query = urllib.parse.parse_qs(parsed.query)
                result = LANGUAGE_SERVICE.import_content_audio(
                    language_content_audio_match.group(1), data=raw,
                    title=(query.get("title") or [""])[0],
                    original_name=(query.get("fileName") or [""])[0],
                    mime_type=str(self.headers.get("Content-Type") or ""),
                )
                self.send_json(result, status=201)
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_content_list_match = re.fullmatch(r"/api/language/profiles/([^/]+)/content", path)
        if language_content_list_match:
            try:
                payload = self.read_json_body(max_bytes=2 * 1024 * 1024 + 64 * 1024)
                self.send_json(LANGUAGE_SERVICE.create_content(language_content_list_match.group(1), payload), status=201)
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_content_transcript_match = re.fullmatch(r"/api/language/content/([^/]+)/transcripts", path)
        if language_content_transcript_match:
            try:
                payload = self.read_json_body(max_bytes=2 * 1024 * 1024 + 64 * 1024)
                self.send_json(LANGUAGE_SERVICE.add_content_transcript(
                    language_content_transcript_match.group(1), payload
                ), status=201)
            except Exception as exc:
                self.send_language_error(exc)
            return
        if path.startswith("/api/budget/"):
            budget_category_match = re.fullmatch(r"/api/budget/categories", path)
            budget_merchant_match = re.fullmatch(r"/api/budget/merchants", path)
            budget_alias_match = re.fullmatch(r"/api/budget/merchants/(\d+)/aliases", path)
            budget_rule_match = re.fullmatch(r"/api/budget/rules", path)
            budget_rule_action_match = re.fullmatch(r"/api/budget/rules/(\d+)/(preview|apply)", path)
            budget_classification_match = re.fullmatch(r"/api/budget/transactions/([^/]+)/classification", path)
            budget_review_match = re.fullmatch(r"/api/budget/review/([^/]+)/(status|correct)", path)
            budget_review_group_match = re.fullmatch(r"/api/budget/review/groups/([^/]+)/(preview|apply)", path)
            budget_review_undo_match = re.fullmatch(r"/api/budget/review/groups/undo-latest", path)
            receipt_import_match = re.fullmatch(r"/api/budget/receipts/import", path)
            receipt_match = re.fullmatch(r"/api/budget/receipts/([^/]+)/match", path)
            receipt_delete_match = re.fullmatch(r"/api/budget/receipts/([^/]+)/delete", path)
            receipt_reprocess_match = re.fullmatch(r"/api/budget/receipts/([^/]+)/reprocess", path)
            receipt_metadata_match = re.fullmatch(r"/api/budget/receipts/([^/]+)/metadata", path)
            receipt_parse_review_match = re.fullmatch(r"/api/budget/receipts/([^/]+)/parse-review", path)
            receipt_reprocess_all_match = re.fullmatch(r"/api/budget/receipts/reprocess-needing-ocr", path)
            receipt_item_match = re.fullmatch(r"/api/budget/receipt-items/([^/]+)/classify", path)
            receipt_group_match = re.fullmatch(r"/api/budget/receipt-items/review/groups/([^/]+)/(preview|apply)", path)
            receipt_group_undo_match = re.fullmatch(r"/api/budget/receipt-items/review/undo-latest", path)
            receipt_product_match = re.fullmatch(r"/api/budget/products", path)
            receipt_pending_product_match = re.fullmatch(r"/api/budget/products/pending", path)
            companion_pair_match = re.fullmatch(r"/api/budget/companion/pair", path)
            companion_revoke_match = re.fullmatch(r"/api/budget/companion/revoke", path)
            budget_planning_match = re.fullmatch(
                r"/api/budget/(obligations|budgets|planned-items|goals|occurrence-status|simulate|account-role|safe-settings|deactivate-obligation|bills-notifications)",
                path,
            )
            if any((
                budget_category_match, budget_merchant_match, budget_alias_match,
                budget_rule_match, budget_rule_action_match,
                budget_classification_match, budget_review_match, budget_review_group_match,
                budget_review_undo_match, budget_planning_match, receipt_import_match, receipt_match,
                receipt_delete_match, receipt_reprocess_match, receipt_metadata_match, receipt_parse_review_match,
                receipt_reprocess_all_match,
                receipt_item_match, receipt_group_match, receipt_group_undo_match,
                receipt_product_match, receipt_pending_product_match, companion_pair_match, companion_revoke_match,
            )):
                try:
                    payload = self.read_json_body(max_bytes=RECEIPT_IMPORT_MAX_BYTES if receipt_import_match else 256 * 1024)
                    if receipt_import_match:
                        result = {"receipt": FINANCE_SERVICE.import_receipt(payload)}
                    elif receipt_reprocess_all_match:
                        result = {"reprocess": FINANCE_SERVICE.reprocess_receipts_needing_ocr()}
                    elif receipt_delete_match:
                        result = {"delete": FINANCE_SERVICE.delete_receipt(receipt_delete_match.group(1))}
                    elif receipt_reprocess_match:
                        result = {"receipt": FINANCE_SERVICE.reprocess_receipt(receipt_reprocess_match.group(1))}
                    elif receipt_metadata_match:
                        result = {"receipt": FINANCE_SERVICE.update_receipt_metadata(receipt_metadata_match.group(1), payload)}
                    elif receipt_parse_review_match:
                        result = {"receipt": FINANCE_SERVICE.apply_receipt_parse_review(receipt_parse_review_match.group(1), payload)}
                    elif receipt_match:
                        result = {"match": FINANCE_SERVICE.match_receipt(receipt_match.group(1), payload.get("transactionId") or None)}
                    elif receipt_item_match:
                        result = {"classification": FINANCE_SERVICE.classify_receipt_item(receipt_item_match.group(1), payload)}
                    elif receipt_group_match:
                        group_id = receipt_group_match.group(1)
                        operation = receipt_group_match.group(2)
                        result = {operation: FINANCE_SERVICE.receipt_item_preview(group_id, payload)
                                  if operation == "preview" else FINANCE_SERVICE.receipt_item_apply(group_id, payload)}
                    elif receipt_group_undo_match:
                        result = {"undo": FINANCE_SERVICE.undo_receipt_item_review()}
                    elif receipt_pending_product_match:
                        result = {"product": FINANCE_SERVICE.save_pending_receipt_barcode(payload)}
                    elif receipt_product_match:
                        result = {"product": FINANCE_SERVICE.create_receipt_product(payload)}
                    elif companion_pair_match:
                        result = {"device": FINANCE_SERVICE.pair_companion_device(str(payload.get("name") or "Dashboard Companion"))}
                    elif companion_revoke_match:
                        result = {"device": FINANCE_SERVICE.revoke_companion_device(str(payload.get("deviceId") or ""))}
                    elif budget_planning_match:
                        result = {"data": FINANCE_SERVICE.planning_mutation(budget_planning_match.group(1), payload)}
                    elif budget_category_match:
                        result = {"category": FINANCE_SERVICE.create_category(payload)}
                    elif budget_merchant_match:
                        result = {"merchant": FINANCE_SERVICE.create_merchant(payload)}
                    elif budget_alias_match:
                        result = {"alias": FINANCE_SERVICE.add_merchant_alias(
                            int(budget_alias_match.group(1)), payload.get("alias")
                        )}
                    elif budget_rule_match:
                        result = FINANCE_SERVICE.create_rule(payload)
                    elif budget_rule_action_match:
                        rule_id = int(budget_rule_action_match.group(1))
                        include_manual = bool(payload.get("includeManual"))
                        operation = budget_rule_action_match.group(2)
                        result = {
                            operation: FINANCE_SERVICE.preview_rule(rule_id, include_manual)
                            if operation == "preview"
                            else FINANCE_SERVICE.apply_rule(rule_id, include_manual)
                        }
                    elif budget_classification_match:
                        result = {"classification": FINANCE_SERVICE.classify_manually(
                            budget_classification_match.group(1), payload
                        )}
                    elif budget_review_group_match:
                        group_id = budget_review_group_match.group(1)
                        operation = budget_review_group_match.group(2)
                        result = {operation: FINANCE_SERVICE.review_group_preview(group_id, payload)
                                  if operation == "preview" else FINANCE_SERVICE.apply_review_group(group_id, payload)}
                    elif budget_review_undo_match:
                        result = {"undo": FINANCE_SERVICE.undo_latest_review_group()}
                    elif budget_review_match.group(2) == "correct":
                        result = FINANCE_SERVICE.correct_review(budget_review_match.group(1), payload)
                    else:
                        result = {"item": FINANCE_SERVICE.update_review(
                            budget_review_match.group(1),
                            str(payload.get("issueType") or ""),
                            str(payload.get("status") or ""),
                        )}
                    created = any((budget_category_match, budget_merchant_match, budget_rule_match, receipt_import_match,
                                   receipt_product_match, receipt_pending_product_match, companion_pair_match))
                    self.send_json({"ok": True, **result}, status=201 if created else 200)
                except FinanceValidationError as exc:
                    self.send_json({"ok": False, "error": str(exc), **exc.result}, status=400)
                except FinanceNotFoundError as exc:
                    self.send_json({"ok": False, "error": str(exc)}, status=404)
                except FinanceError as exc:
                    self.send_json({"ok": False, "error": str(exc)}, status=400)
                except (TypeError, ValueError) as exc:
                    self.send_json({"ok": False, "error": str(exc)}, status=400)
                return
        if path == "/api/language/profiles":
            try:
                payload = self.read_json_body(max_bytes=64 * 1024)
                result = LANGUAGE_SERVICE.create_profile(payload)
                self.send_json(result, status=201 if result["data"]["created"] else 200)
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_benchmarks_match = re.fullmatch(r"/api/language/profiles/([^/]+)/benchmarks", path)
        if language_benchmarks_match:
            try:
                payload = self.read_json_body(max_bytes=1024)
                if payload:
                    raise LanguageError("Benchmark start does not accept options", code="invalid_benchmark_request")
                self.send_json(LANGUAGE_SERVICE.start_benchmark(language_benchmarks_match.group(1)), status=201)
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_benchmark_action_match = re.fullmatch(
            r"/api/language/profiles/([^/]+)/benchmarks/([a-f0-9]{32})/(responses|complete)", path
        )
        if language_benchmark_action_match:
            try:
                profile_id, run_id, action = language_benchmark_action_match.groups()
                if action == "responses":
                    payload = self.read_json_body(max_bytes=4 * 1024)
                    result = LANGUAGE_SERVICE.benchmark_response(profile_id, run_id, payload)
                else:
                    payload = self.read_json_body(max_bytes=1024)
                    if payload:
                        raise LanguageError("Benchmark completion does not accept options", code="invalid_benchmark_request")
                    result = LANGUAGE_SERVICE.complete_benchmark(profile_id, run_id)
                self.send_json(result)
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_phrasebook_list_match = re.fullmatch(r"/api/language/profiles/([^/]+)/phrasebook", path)
        if language_phrasebook_list_match:
            try:
                payload = self.read_json_body(max_bytes=64 * 1024)
                result = LANGUAGE_SERVICE.create_phrasebook_entry(language_phrasebook_list_match.group(1), payload)
                self.send_json(result, status=201 if result["data"]["created"] else 200)
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_lemma_translation_match = re.fullmatch(r"/api/language/lemmas/([^/]+)/translations", path)
        if language_lemma_translation_match:
            try:
                payload = self.read_json_body(max_bytes=8 * 1024)
                self.send_json(LANGUAGE_SERVICE.upsert_lemma_translation(language_lemma_translation_match.group(1), payload))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_anki_test_match = re.fullmatch(r"/api/language/profiles/([^/]+)/anki/test", path)
        if language_anki_test_match:
            try:
                payload = self.read_json_body(max_bytes=4 * 1024)
                if payload:
                    raise LanguageError("Anki test does not accept options", code="invalid_anki_test", status=400)
                self.send_json(LANGUAGE_SERVICE.test_anki(language_anki_test_match.group(1)))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_anki_web_sync_match = re.fullmatch(r"/api/language/profiles/([^/]+)/anki/sync-web", path)
        if language_anki_web_sync_match:
            try:
                payload = self.read_json_body(max_bytes=4 * 1024)
                if set(payload) - {"force"} or not isinstance(payload.get("force", False), bool):
                    raise LanguageError("Anki web sync accepts only a boolean force option", code="invalid_anki_web_sync", status=400)
                self.send_json(LANGUAGE_SERVICE.sync_anki_web(
                    language_anki_web_sync_match.group(1), force=payload.get("force", False)
                ))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_anki_pull_match = re.fullmatch(r"/api/language/profiles/([^/]+)/anki/pull", path)
        if language_anki_pull_match:
            try:
                payload = self.read_json_body(max_bytes=4 * 1024)
                if payload:
                    raise LanguageError("Anki pull does not accept options", code="invalid_anki_pull", status=400)
                self.send_json(LANGUAGE_SERVICE.pull_anki(language_anki_pull_match.group(1)))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_anki_preview_match = re.fullmatch(r"/api/language/lemmas/([^/]+)/anki/preview", path)
        if language_anki_preview_match:
            try:
                payload = self.read_json_body(max_bytes=16 * 1024)
                self.send_json(LANGUAGE_SERVICE.preview_anki_note(language_anki_preview_match.group(1), payload))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_anki_commit_match = re.fullmatch(r"/api/language/lemmas/([^/]+)/anki/commit", path)
        if language_anki_commit_match:
            try:
                payload = self.read_json_body(max_bytes=16 * 1024)
                self.send_json(LANGUAGE_SERVICE.commit_anki_note(language_anki_commit_match.group(1), payload))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_anki_link_match = re.fullmatch(r"/api/language/lemmas/([^/]+)/anki/link", path)
        if language_anki_link_match:
            try:
                payload = self.read_json_body(max_bytes=16 * 1024)
                self.send_json(LANGUAGE_SERVICE.link_anki_note(language_anki_link_match.group(1), payload))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_anki_resolve_match = re.fullmatch(r"/api/language/lemmas/([^/]+)/anki/resolve", path)
        if language_anki_resolve_match:
            try:
                payload = self.read_json_body(max_bytes=16 * 1024)
                self.send_json(LANGUAGE_SERVICE.resolve_anki_conflict(language_anki_resolve_match.group(1), payload))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_cloze_sessions_match = re.fullmatch(r"/api/language/profiles/([^/]+)/cloze/sessions", path)
        if language_cloze_sessions_match:
            try:
                payload = self.read_json_body(max_bytes=16 * 1024)
                self.send_json(
                    LANGUAGE_SERVICE.start_cloze_session(language_cloze_sessions_match.group(1), payload),
                    status=201,
                )
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_cloze_attempt_match = re.fullmatch(r"/api/language/cloze/sessions/([^/]+)/attempts", path)
        if language_cloze_attempt_match:
            try:
                payload = self.read_json_body(max_bytes=32 * 1024)
                result = LANGUAGE_SERVICE.submit_cloze_attempt(language_cloze_attempt_match.group(1), payload)
                self.send_json(result, status=201 if result["data"]["created"] else 200)
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_cloze_audio_match = re.fullmatch(
            r"/api/language/cloze/sessions/([^/]+)/items/(\d+)/audio", path
        )
        language_word_audio_match = re.fullmatch(r"/api/language/(lemmas|tokens)/([^/]+)/audio", path)
        if language_word_audio_match:
            try:
                payload = self.read_json_body(max_bytes=1024)
                if payload != {}:
                    raise LanguageError("Word audio does not accept options", code="word_audio_options_forbidden", status=400)
                kind, word_id = language_word_audio_match.groups()
                result = (LANGUAGE_SERVICE.word_audio_for_lemma(word_id, retry=True) if kind == "lemmas"
                          else LANGUAGE_SERVICE.word_audio_for_token(word_id, retry=True))
                self.send_json(result, status=202 if result["data"]["state"] in {"QUEUED", "RUNNING"} else 200)
            except Exception as exc:
                self.send_language_error(exc)
            return
        if language_cloze_audio_match:
            try:
                payload = self.read_json_body(max_bytes=4 * 1024)
                route_index = int(language_cloze_audio_match.group(2))
                if not isinstance(payload, dict):
                    raise LanguageError(
                        "JSON payload must be an object", code="invalid_json_object", status=400,
                    )
                if "itemIndex" in payload and payload["itemIndex"] != route_index:
                    raise LanguageError(
                        "Cloze audio item index does not match the route",
                        code="cloze_audio_item_mismatch", status=400,
                    )
                payload["itemIndex"] = route_index
                result = LANGUAGE_SERVICE.generate_cloze_audio(
                    language_cloze_audio_match.group(1), payload,
                )
                self.send_json(result, status=200)
            except Exception as exc:
                log_line(
                    f"Cloze audio request failed: {type(exc).__name__} "
                    f"code={getattr(exc, 'code', 'unknown')}",
                    tag="language", level="error",
                )
                self.send_language_error(exc)
            return
        language_cloze_report_match = re.fullmatch(r"/api/language/cloze/sessions/([^/]+)/report", path)
        if language_cloze_report_match:
            try:
                payload = self.read_json_body(max_bytes=8 * 1024)
                result = LANGUAGE_SERVICE.report_cloze_item(language_cloze_report_match.group(1), payload)
                self.send_json(result, status=201 if result["data"]["created"] else 200)
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_topics_match = re.fullmatch(r"/api/language/profiles/([^/]+)/topics", path)
        language_generation_requests_match = re.fullmatch(r"/api/language/profiles/([^/]+)/generation-requests", path)
        language_series_create_match = re.fullmatch(r"/api/language/profiles/([^/]+)/reading-series", path)
        if language_series_create_match:
            try:
                payload = self.read_json_body(max_bytes=16 * 1024)
                self.send_json(LANGUAGE_SERVICE.create_reading_series(language_series_create_match.group(1), payload), status=201)
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_campaigns_match = re.fullmatch(r"/api/language/profiles/([^/]+)/campaigns", path)
        if language_campaigns_match:
            try:
                payload = self.read_json_body(max_bytes=32 * 1024)
                self.send_json(
                    LANGUAGE_SERVICE.create_campaign(language_campaigns_match.group(1), payload), status=201
                )
            except Exception as exc:
                self.send_language_error(exc)
            return
        if language_generation_requests_match:
            try:
                payload = self.read_json_body(max_bytes=64 * 1024)
                self.send_json(LANGUAGE_SERVICE.create_generation_request(language_generation_requests_match.group(1), payload), status=201)
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_generation_automatic_match = re.fullmatch(
            r"/api/language/generation-requests/([^/]+)/(automatic|cancel)", path
        )
        if language_generation_automatic_match:
            try:
                payload = self.read_json_body(max_bytes=1024)
                request_id, action = language_generation_automatic_match.groups()
                if action == "automatic":
                    result = LANGUAGE_SERVICE.start_automatic_generation(request_id, payload)
                    status = 202
                else:
                    result = LANGUAGE_SERVICE.cancel_automatic_generation(request_id, payload)
                    status = 200
                self.send_json(result, status=status)
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_generated_sentence_audio_match = re.fullmatch(
            r"/api/language/texts/([^/]+)/sentences/([^/]+)/audio", path
        )
        if language_generated_sentence_audio_match:
            try:
                payload = self.read_json_body(max_bytes=1024)
                text_id, sentence_id = language_generated_sentence_audio_match.groups()
                result = LANGUAGE_SERVICE.generate_generated_text_audio(
                    text_id, sentence_id, payload
                )
                self.send_json(result, status=200)
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_sentence_translate_match = re.fullmatch(
            r"/api/language/texts/([^/]+)/sentences/([^/]+)/translate", path
        )
        if language_sentence_translate_match:
            try:
                payload = self.read_json_body(max_bytes=1024)
                text_id, sentence_id = language_sentence_translate_match.groups()
                self.send_json(LANGUAGE_SERVICE.translate_reader_sentence(text_id, sentence_id, payload))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_reader_study_notes_import_match = re.fullmatch(r"/api/language/texts/([^/]+)/study-notes/import", path)
        if language_reader_study_notes_import_match:
            try:
                payload = self.read_json_body(max_bytes=512 * 1024)
                self.send_json(LANGUAGE_SERVICE.import_reader_study_notes(
                    language_reader_study_notes_import_match.group(1), payload,
                ))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_story_anki_match = re.fullmatch(
            r"/api/language/texts/([^/]+)/anki-story/(preview|create)", path
        )
        if language_story_anki_match:
            try:
                text_id, action = language_story_anki_match.groups()
                payload = self.read_json_body(max_bytes=1024)
                result = (LANGUAGE_SERVICE.preview_reader_story_anki(text_id)
                          if action == "preview" else
                          LANGUAGE_SERVICE.create_reader_story_anki(text_id, payload))
                self.send_json(result)
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_listening_session_match = re.fullmatch(
            r"/api/language/texts/([^/]+)/listening-sessions", path
        )
        if language_listening_session_match:
            try:
                payload = self.read_json_body(max_bytes=16 * 1024)
                result = LANGUAGE_SERVICE.start_listening_session(
                    language_listening_session_match.group(1), payload
                )
                self.send_json(result, status=201 if result["data"]["created"] else 200)
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_listening_event_match = re.fullmatch(
            r"/api/language/listening-sessions/([^/]+)/sentence-events", path
        )
        if language_listening_event_match:
            try:
                payload = self.read_json_body(max_bytes=16 * 1024)
                result = LANGUAGE_SERVICE.record_listening_sentence_event(
                    language_listening_event_match.group(1), payload
                )
                self.send_json(result, status=201 if result["data"]["created"] else 200)
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_generation_import_match = re.fullmatch(r"/api/language/generation-requests/([^/]+)/candidates", path)
        if language_generation_import_match:
            try:
                payload = self.read_json_body(max_bytes=300 * 1024)
                self.send_json(LANGUAGE_SERVICE.import_generation_candidate(language_generation_import_match.group(1), payload), status=201)
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_generation_action_match = re.fullmatch(r"/api/language/generation-candidates/([^/]+)/(analyze|accept|reject)", path)
        if language_generation_action_match:
            try:
                payload = self.read_json_body(max_bytes=16 * 1024)
                candidate_id, action = language_generation_action_match.groups()
                if action == "analyze":
                    result = LANGUAGE_SERVICE.analyze_generation_candidate(candidate_id, payload)
                    status = 202 if result["data"]["candidate"]["status"] in {"QUEUED", "ANALYZING"} else 200
                elif action == "accept":
                    result = LANGUAGE_SERVICE.accept_generation_candidate(candidate_id, payload)
                    status = 201 if result["data"]["created"] else 200
                else:
                    result = LANGUAGE_SERVICE.reject_generation_candidate(candidate_id, payload)
                    status = 200
                self.send_json(result, status=status)
            except Exception as exc:
                self.send_language_error(exc)
            return
        if language_topics_match:
            try:
                payload = self.read_json_body(max_bytes=32 * 1024)
                self.send_json(
                    LANGUAGE_SERVICE.create_topic(language_topics_match.group(1), payload),
                    status=201,
                )
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_topic_lemma_match = re.fullmatch(r"/api/language/topics/([^/]+)/lemmas", path)
        if language_topic_lemma_match:
            try:
                payload = self.read_json_body(max_bytes=16 * 1024)
                result = LANGUAGE_SERVICE.assign_topic_lemma(language_topic_lemma_match.group(1), payload)
                self.send_json(result, status=201 if result["data"]["created"] else 200)
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_goals_match = re.fullmatch(r"/api/language/profiles/([^/]+)/goals", path)
        if language_goals_match:
            try:
                payload = self.read_json_body(max_bytes=32 * 1024)
                self.send_json(
                    LANGUAGE_SERVICE.create_goal(language_goals_match.group(1), payload),
                    status=201,
                )
            except Exception as exc:
                self.send_language_error(exc)
            return
        if path == "/api/language/lemmas/merge":
            try:
                payload = self.read_json_body(max_bytes=64 * 1024)
                self.send_json(LANGUAGE_SERVICE.merge_lemmas(payload))
            except Exception as exc:
                self.send_language_error(exc)
            return
        if path == "/api/language/texts":
            try:
                payload = self.read_json_body(max_bytes=2 * 1024 * 1024 + 64 * 1024)
                self.send_json(LANGUAGE_SERVICE.create_text_draft(payload), status=201)
            except Exception as exc:
                self.send_language_error(exc)
            return
        if path == "/api/language/study-sessions":
            try:
                payload = self.read_json_body(max_bytes=16 * 1024)
                result = LANGUAGE_SERVICE.start_reader_session(payload)
                self.send_json(
                    result, status=201 if result["data"]["created"] else 200
                )
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_exposure_batch_match = re.fullmatch(
            r"/api/language/study-sessions/([^/]+)/exposures", path
        )
        if language_exposure_batch_match:
            try:
                payload = self.read_json_body(max_bytes=128 * 1024)
                result = LANGUAGE_SERVICE.record_reader_exposure_batch(
                    language_exposure_batch_match.group(1), payload
                )
                self.send_json(
                    result, status=201 if result["data"]["created"] else 200
                )
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_grammar_analysis_match = re.fullmatch(r"/api/language/texts/([^/]+)/grammar-analysis", path)
        if language_grammar_analysis_match:
            try:
                result = LANGUAGE_SERVICE.enqueue_grammar(language_grammar_analysis_match.group(1), self.read_json_body(max_bytes=4096))
                self.send_json(result, status=202 if result["data"]["job"]["state"] in {"QUEUED", "RUNNING"} else 200)
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_analyze_match = re.fullmatch(r"/api/language/texts/([^/]+)/analyze", path)
        if language_analyze_match:
            try:
                payload = self.read_json_body(max_bytes=4 * 1024)
                result = LANGUAGE_SERVICE.enqueue_analysis(language_analyze_match.group(1), payload)
                state = result["data"]["job"]["state"]
                self.send_json(result, status=202 if state in {"QUEUED", "RUNNING"} else 200)
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_preview_match = re.fullmatch(r"/api/language/texts/([^/]+)/reanalyze/preview", path)
        if language_preview_match:
            try:
                payload = self.read_json_body(max_bytes=4 * 1024)
                result = LANGUAGE_SERVICE.enqueue_reanalysis_preview(
                    language_preview_match.group(1), payload
                )
                state = result["data"]["job"]["state"]
                self.send_json(result, status=202 if state in {"QUEUED", "RUNNING"} else 200)
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_commit_match = re.fullmatch(r"/api/language/texts/([^/]+)/reanalyze/commit", path)
        if language_commit_match:
            try:
                payload = self.read_json_body(max_bytes=4 * 1024)
                result = LANGUAGE_SERVICE.enqueue_reanalysis_commit(
                    language_commit_match.group(1), payload
                )
                state = result["data"]["job"]["state"]
                self.send_json(result, status=202 if state in {"QUEUED", "RUNNING"} else 200)
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_cancel_match = re.fullmatch(r"/api/language/jobs/([^/]+)/cancel", path)
        if language_cancel_match:
            try:
                payload = self.read_json_body(max_bytes=4 * 1024)
                if payload:
                    raise LanguageError(
                        "Language cancellation does not accept options",
                        code="invalid_language_job_cancellation",
                        status=400,
                    )
                self.send_json(LANGUAGE_SERVICE.cancel_analysis_job(language_cancel_match.group(1)))
            except Exception as exc:
                self.send_language_error(exc)
            return
        if path == "/api/language/backup":
            try:
                payload = self.read_json_body(max_bytes=4 * 1024)
                if payload:
                    raise LanguageError(
                        "Language backup does not accept destination options",
                        code="invalid_backup_request",
                        status=400,
                    )
                self.send_json(LANGUAGE_SERVICE.backup_database(), status=201)
            except Exception as exc:
                self.send_language_error(exc)
            return
        if path == "/api/strength/sessions":
            try:
                payload = self.read_json_body(max_bytes=256 * 1024)
                self.send_json({"session": STRENGTH_STORE.start_session(payload)}, status=201)
            except StrengthError as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            except (TypeError, ValueError) as exc:
                self.send_json({"error": str(exc), "code": "invalid_strength_session"}, status=400)
            return
        strength_complete_match = re.fullmatch(r"/api/strength/sessions/([a-zA-Z0-9-]+)/complete", path)
        if strength_complete_match:
            try:
                payload = self.read_json_body(max_bytes=64 * 1024)
                self.send_json({"session": STRENGTH_STORE.complete_session(strength_complete_match.group(1), payload)})
            except StrengthError as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            return
        if path == "/api/strength/sets":
            try:
                payload = self.read_json_body(max_bytes=256 * 1024)
                self.send_json(STRENGTH_STORE.save_set(payload), status=201)
            except StrengthError as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            except (TypeError, ValueError) as exc:
                self.send_json({"error": str(exc), "code": "invalid_strength_set"}, status=400)
            return
        if path == "/api/strength/equipment":
            try:
                payload = self.read_json_body(max_bytes=256 * 1024)
                self.send_json({"items": STRENGTH_STORE.update_equipment(payload)})
            except StrengthError as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            except (TypeError, ValueError) as exc:
                self.send_json({"error": str(exc), "code": "invalid_equipment"}, status=400)
            return
        if path == "/api/strength/recovery":
            try:
                payload = self.read_json_body(max_bytes=64 * 1024)
                self.send_json(STRENGTH_STORE.report_recovery(payload), status=201)
            except StrengthError as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            return
        if path == "/api/strength/settings":
            try:
                payload = self.read_json_body(max_bytes=64 * 1024)
                self.send_json(STRENGTH_STORE.update_settings(payload))
            except StrengthError as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            except (TypeError, ValueError) as exc:
                self.send_json({"error": str(exc), "code": "invalid_xp_settings"}, status=400)
            return
        if path == "/api/music/legacy/sync":
            try:
                legacy = MUSIC_STORE.sync_legacy_catalog()
                metadata = MUSIC_STORE.refresh_imported_metadata()
                covers = MUSIC_STORE.sync_local_covers()
                self.send_json({"ok": True, "legacy": legacy, "metadata": metadata, "covers": covers})
            except MusicError as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            except Exception as exc:
                log_line(f"Music legacy sync failed: {exc}", tag="music", level="error")
                self.send_json({"ok": False, "error": "Could not sync legacy Music projects"}, status=500)
            return
        if path == "/api/music/imports/preview":
            try:
                payload = self.read_json_body(max_bytes=16 * 1024 * 1024)
                self.send_json(MUSIC_STORE.preview_import(
                    filename=payload.get("filename"),
                    html=payload.get("html"),
                    captured_at=payload.get("capturedAt"),
                    reparse=bool(payload.get("reparse")),
                ))
            except MusicError as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            except (ValueError, TimelineError) as exc:
                self.send_json({"ok": False, "error": str(exc), "code": "invalid_music_import"}, status=400)
            except Exception as exc:
                log_line(f"Music import preview failed: {exc}", tag="music", level="error")
                self.send_json({"error": "Could not parse Music import"}, status=500)
            return
        music_import_commit_match = re.fullmatch(r"/api/music/imports/(\d+)/commit", path)
        if music_import_commit_match:
            try:
                payload = self.read_json_body(max_bytes=1024 * 1024)
                self.send_json(MUSIC_STORE.commit_import(
                    int(music_import_commit_match.group(1)), payload.get("resolutions") or {}
                ))
            except (MusicError, TimelineError) as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            except Exception as exc:
                log_line(f"Music import commit failed: {exc}", tag="music", level="error")
                self.send_json({"error": "Could not commit Music import"}, status=500)
            return
        music_rating_match = re.fullmatch(r"/api/music/releases/(\d+)/rating", path)
        if music_rating_match:
            try:
                payload = self.read_json_body(max_bytes=16 * 1024)
                self.send_json(MUSIC_STORE.set_rating(int(music_rating_match.group(1)), payload.get("rating")))
            except (MusicError, TimelineError, TypeError, ValueError) as exc:
                self.send_json(exc.as_payload() if hasattr(exc, "as_payload") else {"error": str(exc)}, status=getattr(exc, "status", 400))
            return
        if path == "/api/music/artwork":
            try:
                payload = self.read_json_body(max_bytes=8 * 1024 * 1024)
                self.send_json(save_music_artwork(payload))
            except (ValueError, TypeError) as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=400)
            return
        music_cover_match = re.fullmatch(r"/api/music/releases/(\d+)/cover", path)
        if music_cover_match:
            try:
                release_id = int(music_cover_match.group(1))
                payload = self.read_json_body(max_bytes=8 * 1024 * 1024)
                release = MUSIC_STORE.release_detail(release_id)["release"]
                result = save_bm365_cover({
                    "dataUrl": payload.get("dataUrl"),
                    "artist": release["artist_credit"],
                    "album": release["title"],
                })
                self.send_json(MUSIC_STORE.set_cover(release_id, result.get("url")))
            except MusicError as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            except (ValueError, TypeError) as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=400)
            return
        music_cover_fetch_match = re.fullmatch(r"/api/music/releases/(\d+)/cover/fetch", path)
        if music_cover_fetch_match:
            try:
                release_id = int(music_cover_fetch_match.group(1))
                self.send_json(MUSIC_ENRICHMENT.enqueue(release_id, retry=True))
            except MusicError as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            except Exception as exc:
                log_line(f"Music cover fetch failed: {exc}", tag="music", level="warn")
                self.send_json({"ok": False, "error": str(exc)}, status=400)
            return
        if path == "/api/music/covers/fetch":
            try:
                payload = self.read_json_body(max_bytes=16 * 1024)
                self.send_json({"ok": True, "queued": MUSIC_ENRICHMENT.enqueue_missing(payload.get("limit") or 25)})
            except (MusicError, ValueError, TypeError) as exc:
                self.send_json(exc.as_payload() if hasattr(exc, "as_payload") else {"error": str(exc)}, status=getattr(exc, "status", 400))
            return
        if path == "/api/music/enrichment/queue":
            try:
                payload = self.read_json_body(max_bytes=16 * 1024)
                release_id = payload.get("releaseId")
                if release_id is not None:
                    self.send_json(MUSIC_ENRICHMENT.enqueue(int(release_id), retry=True))
                else:
                    self.send_json({"ok": True, "queued": MUSIC_ENRICHMENT.enqueue_missing(payload.get("limit") or 50)})
            except (ValueError, TypeError) as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=400)
            return
        if path == "/api/music/rankings":
            try:
                payload = self.read_json_body(max_bytes=64 * 1024)
                self.send_json(MUSIC_STORE.create_personal_ranking(
                    payload.get("name"), genre_id=payload.get("genreId"),
                    include_descendants=payload.get("includeDescendants", False), filters=payload.get("filters")
                ), status=201)
            except (MusicError, TimelineError) as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            return
        music_ranking_entries_match = re.fullmatch(r"/api/music/rankings/(\d+)/entries", path)
        if music_ranking_entries_match:
            try:
                payload = self.read_json_body(max_bytes=64 * 1024)
                self.send_json(MUSIC_STORE.update_personal_ranking(
                    int(music_ranking_entries_match.group(1)), action=payload.get("action"),
                    release_id=payload.get("releaseId"), position=payload.get("position")
                ))
            except (MusicError, TimelineError) as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            return
        if path == "/api/music/lists":
            try:
                payload = self.read_json_body(max_bytes=64 * 1024)
                self.send_json(MUSIC_STORE.create_list(payload.get("name"), payload.get("description")), status=201)
            except (MusicError, TimelineError) as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            return
        music_list_entries_match = re.fullmatch(r"/api/music/lists/(\d+)/entries", path)
        if music_list_entries_match:
            try:
                payload = self.read_json_body(max_bytes=64 * 1024)
                self.send_json(MUSIC_STORE.update_list_entry(
                    int(music_list_entries_match.group(1)), action=payload.get("action"),
                    release_id=payload.get("releaseId"), note=payload.get("note")
                ))
            except (MusicError, TimelineError) as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            return
        if path == "/api/synchrobook/processing-settings":
            try:
                payload = self.read_json_body(max_bytes=8 * 1024)
                self.send_json(SYNCHROBOOK.save_processing_settings(payload))
            except (SynchrobookError, TimelineError) as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            return
        if path == "/api/synchrobook/import":
            try:
                length = int(self.headers.get("Content-Length", ""))
            except (TypeError, ValueError):
                self.send_json({"error": "Valid Content-Length is required", "code": "invalid_content_length"}, status=411)
                return
            try:
                result = SYNCHROBOOK.import_book(
                    self.headers.get("Content-Type", ""), length, self.rfile
                )
                self.send_json(result, status=202)
            except SynchrobookError as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            except Exception as exc:
                log_line(f"Synchrobook import failed: {exc}", tag="synchrobook", level="error")
                self.send_json({"error": "Could not import the Synchrobook files"}, status=500)
            return
        synchrobook_guide_match = re.fullmatch(
            r"/api/synchrobook/books/([a-f0-9]{32})/reading-guide", path
        )
        if synchrobook_guide_match:
            try:
                payload = self.read_json_body(max_bytes=16 * 1024 * 1024)
                self.send_json(READING_GUIDE.execute(synchrobook_guide_match.group(1), payload))
            except (ReadingGuideError, TimelineError) as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            except Exception as exc:
                log_line(f"Reading Guide action failed: {exc}", tag="synchrobook", level="error")
                self.send_json({"error": "Could not update Reading Guide"}, status=500)
            return
        synchrobook_resume_match = re.fullmatch(
            r"/api/synchrobook/jobs/([a-f0-9]{32})/resume", path
        )
        if synchrobook_resume_match:
            try:
                payload = self.read_json_body(max_bytes=8 * 1024)
                priority = int(payload.get("priority") or 0)
                self.send_json(
                    SYNCHROBOOK.resume_job(synchrobook_resume_match.group(1), priority),
                    status=202,
                )
            except (SynchrobookError, TimelineError) as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            except (TypeError, ValueError):
                self.send_json({"error": "Invalid queue priority", "code": "invalid_priority"}, status=400)
            return
        synchrobook_progress_match = re.fullmatch(
            r"/api/synchrobook/books/([a-f0-9]{32})/progress", path
        )
        if synchrobook_progress_match:
            try:
                self.send_json(SYNCHROBOOK.save_progress(
                    synchrobook_progress_match.group(1), self.read_json_body(max_bytes=32 * 1024)
                ))
            except (SynchrobookError, TimelineError) as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            return
        synchrobook_action_match = re.fullmatch(
            r"/api/synchrobook/books/([a-f0-9]{32})/(rebuild-alignment|retranscribe)", path
        )
        if synchrobook_action_match:
            try:
                # Consume and validate the small JSON request body before queuing.
                self.read_json_body(max_bytes=8 * 1024)
                kind = "alignment" if synchrobook_action_match.group(2) == "rebuild-alignment" else "transcription"
                self.send_json(SYNCHROBOOK.queue_action(synchrobook_action_match.group(1), kind), status=202)
            except (SynchrobookError, TimelineError) as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            return
        if path in {"/api/ring/phone/ingest", "/api/ring/phone/status"}:
            try:
                payload = self.read_json_body(
                    max_bytes=8 * 1024 * 1024 if path.endswith("/ingest") else 16 * 1024
                )
                self.send_json(
                    RING_PHONE_BRIDGE.ingest(payload)
                    if path.endswith("/ingest")
                    else RING_PHONE_BRIDGE.status(payload)
                )
            except RingPhoneBridgeError as exc:
                self.send_json({"ok": False, "error": str(exc), "code": "invalid_ring_phone_batch"}, status=400)
            except Exception as exc:
                log_line(f"Ring phone ingest failed: {exc}", tag="ring", level="error")
                self.send_json({"ok": False, "error": "Could not ingest ring phone batch"}, status=500)
            return
        if path in {"/api/ring/scan", "/api/ring/connect", "/api/ring/disconnect", "/api/ring/sync", "/api/ring/presence"}:
            try:
                payload = self.read_json_body(max_bytes=16 * 1024)
                if path == "/api/ring/scan":
                    self.send_json(RING_COLLECTOR.scan(payload.get("timeoutSeconds", 8)))
                elif path == "/api/ring/connect":
                    self.send_json(RING_COLLECTOR.connect(payload.get("deviceId")))
                elif path == "/api/ring/disconnect":
                    self.send_json(RING_COLLECTOR.disconnect())
                elif path == "/api/ring/presence":
                    result = RING_COLLECTOR.presence()
                    ring_state = result.get("state") or {}
                    ring_state["wear"] = RING_PHONE_BRIDGE.wear_state(
                        (ring_state.get("device") or {}).get("deviceId")
                    )
                    self.send_json(result)
                else:
                    self.send_json(RING_COLLECTOR.sync())
            except RingError as exc:
                log_line(f"Ring operation failed: {exc.code}: {exc}", tag="ring", level="error")
                self.send_json(exc.as_payload(), status=exc.status)
            except TimelineError as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            except (TypeError, ValueError) as exc:
                self.send_json({"ok": False, "error": str(exc), "code": "invalid_ring_request"}, status=400)
            except Exception as exc:
                log_line(f"Ring operation failed: {exc}", tag="ring", level="error")
                self.send_json({"ok": False, "error": "Ring operation failed", "code": "ring_operation_failed"}, status=500)
            return
        cleaning_done_match = re.fullmatch(r"/api/cleaning/tasks/([^/]+)/done", path)
        if path in {"/api/cleaning/tasks", "/api/cleaning/history/undo", "/api/cleaning/settings", "/api/cleaning/phone-goal"} or cleaning_done_match:
            try:
                payload = self.read_json_body(max_bytes=256 * 1024)
                if path == "/api/cleaning/tasks":
                    apartment_id = payload.get("apartmentId", payload.get("apartment"))
                    task = CLEANING_STORE.add_task(apartment_id, payload)
                    self.send_json({"ok": True, "task": task}, status=201)
                elif path == "/api/cleaning/history/undo":
                    self.send_json(CLEANING_STORE.revert_last_action(payload.get("actionId", payload.get("action_id"))))
                elif path == "/api/cleaning/settings":
                    self.send_json(CLEANING_STORE.update_settings(payload))
                elif path == "/api/cleaning/phone-goal":
                    from zoneinfo import ZoneInfo
                    cleaning_day = (datetime.now(ZoneInfo("Europe/Warsaw")) - timedelta(hours=6)).date().isoformat()
                    if payload.get("day") != cleaning_day:
                        raise CleaningError("Cleaning goal is for another day", status=400)
                    target = int(payload.get("target", -1))
                    if not (0 <= target <= 10000):
                        raise CleaningError("Invalid cleaning goal progress", status=400)
                    done = CLEANING_STORE.count_actions_for_day(payload.get("apartmentId"), cleaning_day)
                    PHONE_ACCESS.set_cleaning_target(payload.get("apartmentId"),cleaning_day,target)
                    target = PHONE_ACCESS.cleaning_target(cleaning_day) or 0
                    complete = target > 0 and done >= target
                    for device in PHONE_TRACKER.devices():
                        if not device["is_sample"]:
                            PHONE_TRACKER.set_external_condition(device["device_id"], "cleaning_done_today", complete)
                    self.send_json({"ok": True, "complete": complete, "done": done, "target": target})
                else:
                    task_id = urllib.parse.unquote(cleaning_done_match.group(1))
                    self.send_json(CLEANING_STORE.mark_done(
                        task_id,
                        payload.get("apartmentId", payload.get("apartment")),
                        done_at=payload.get("doneAt", payload.get("done_at")),
                        source=payload.get("source", "cleaning-page"),
                    ))
            except (CleaningError, TimelineError) as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            except Exception as exc:
                log_line(f"Cleaning write failed: {exc}", tag="cleaning", level="error")
                self.send_json({"error": "Could not save cleaning data"}, status=500)
            return
        if path == "/api/reading/books":
            try:
                payload = self.read_json_body(max_bytes=1024 * 1024)
                book = READING_STORE.create_book(payload)
                self.send_json({"ok": True, "book_id": book["book_id"], "book": book}, status=201)
            except (ReadingError, TimelineError) as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            except Exception as exc:
                log_line(f"Reading book create failed: {exc}", tag="reading", level="error")
                self.send_json({"error": "Could not create reading book"}, status=500)
            return
        if path == "/api/reading/history":
            try:
                payload = self.read_json_body(max_bytes=8 * 1024 * 1024)
                self.send_json(READING_STORE.replace_history(payload))
            except (ReadingError, TimelineError) as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            except Exception as exc:
                log_line(f"Reading history save failed: {exc}", tag="reading", level="error")
                self.send_json({"error": "Could not save reading history"}, status=500)
            return
        if path == "/api/reading/settings":
            try:
                payload = self.read_json_body(max_bytes=2 * 1024 * 1024)
                self.send_json(READING_STORE.replace_settings(payload))
            except (ReadingError, TimelineError) as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            except Exception as exc:
                log_line(f"Reading settings save failed: {exc}", tag="reading", level="error")
                self.send_json({"error": "Could not save reading settings"}, status=500)
            return
        if path == "/api/habits/sync":
            try:
                payload = self.read_json_body(max_bytes=5 * 1024 * 1024)
                self.send_json(HABITS_STORE.sync(payload))
            except HabitsError as exc:
                self.send_json({"error": str(exc), "code": exc.code}, status=exc.status)
            except Exception as exc:
                log_line(f"Sync failed: {exc}", tag="habits", level="error")
                self.send_json({"error": "Habits synchronization failed"}, status=500)
            return
        if path == "/api/habits/reminders/settings":
            try:
                payload = self.read_json_body(max_bytes=256 * 1024)
                self.send_json(HABITS_STORE.save_reminder_settings(payload))
            except HabitsError as exc:
                self.send_json({"error": str(exc), "code": exc.code}, status=exc.status)
            except Exception as exc:
                log_line(f"Reminder settings save failed: {exc}", tag="habits", level="error")
                self.send_json({"error": "Could not save reminder settings"}, status=500)
            return
        if path == "/api/habits/reminders/action":
            try:
                payload = self.read_json_body(max_bytes=64 * 1024)
                self.send_json(HABITS_STORE.reminder_action(payload))
            except HabitsError as exc:
                self.send_json({"error": str(exc), "code": exc.code}, status=exc.status)
            except Exception as exc:
                log_line(f"Reminder action failed: {exc}", tag="habits", level="error")
                self.send_json({"error": "Could not update reminder"}, status=500)
            return
        if path in {"/api/habits/supplements/slots", "/api/habits/supplements/regimen",
                    "/api/habits/supplements/product", "/api/habits/supplements/claim"}:
            try:
                payload = self.read_json_body(max_bytes=64 * 1024)
                action = {
                    "/api/habits/supplements/slots": SUPPLEMENTS_STORE.save_slots,
                    "/api/habits/supplements/regimen": SUPPLEMENTS_STORE.save_regimen,
                    "/api/habits/supplements/product": SUPPLEMENTS_STORE.change_product,
                    "/api/habits/supplements/claim": SUPPLEMENTS_STORE.claim_slot,
                }[path]
                self.send_json(action(payload))
            except ValueError as exc:
                self.send_json({"error": str(exc)}, status=400)
            except Exception as exc:
                log_line(f"Supplement update failed: {exc}", tag="habits", level="error")
                self.send_json({"error": "Could not update supplements"}, status=500)
            return
        if path == "/api/live-workout/session":
            try:
                payload = self.read_json_body(max_bytes=256 * 1024)
                action = str(payload.get("action") or "").strip().lower()
                if action == "start":
                    session = LIVE_WORKOUT_STORE.start_dashboard_session(
                        {
                            "title": payload.get("title"),
                            "plan_id": payload.get("plan_id"),
                            "plan_date": payload.get("plan_date"),
                            "planned_duration_minutes": payload.get("planned_duration_minutes"),
                            "target_zones": payload.get("target_zones"),
                            "workout_type": payload.get("workout_type"),
                            "sub_type": payload.get("sub_type"),
                            "strength_data": payload.get("strength_data"),
                        },
                        timestamp=payload.get("timestamp"),
                    )
                elif action == "cancel":
                    session = LIVE_WORKOUT_STORE.cancel_dashboard_session(
                        session_id=payload.get("session_id"),
                    )
                else:
                    session = LIVE_WORKOUT_STORE.control_dashboard_session(
                        action,
                        timestamp=payload.get("timestamp"),
                        session_id=payload.get("session_id"),
                        summary={
                            "duration_seconds": payload.get("elapsed_seconds"),
                            "zones": payload.get("zone_seconds"),
                            "interval_progress_seconds": payload.get("interval_progress_seconds"),
                            "plan_completed_at_elapsed": payload.get("plan_completed_at_elapsed"),
                            "plan_completed": payload.get("plan_completed"),
                            "active_calories": payload.get("active_calories"),
                            "active_calories_keytel_raw": payload.get("active_calories_keytel_raw"),
                            "calorie_method": payload.get("calorie_method"),
                            "calorie_calibration_factor": payload.get("calorie_calibration_factor"),
                            "training_load": payload.get("training_load"),
                            "virtual_walk_active_seconds": payload.get("virtual_walk_active_seconds"),
                            "virtual_walk_outside_seconds": payload.get("virtual_walk_outside_seconds"),
                            "virtual_steps": payload.get("virtual_steps"),
                            "cadence_rpm_avg": payload.get("cadence_rpm_avg"),
                            "strength_data": payload.get("strength_data"),
                            "session_rpe": payload.get("session_rpe"),
                            "notes": payload.get("notes"),
                        },
                    )
                if not session:
                    self.send_json({"error": "No active workout session"}, status=409)
                    return
                if action == "finish" and session.get("workout_type") == "virtual_walk":
                    workout_day = datetime.fromtimestamp(session["started_at"] / 1000).date().isoformat()
                    upsert_steps_event({
                        "day": workout_day,
                        "steps": session.get("virtual_steps") or 0,
                        "source": "virtual_walk",
                        "session_id": session["id"],
                        "duration_seconds": session.get("duration_seconds") or 0,
                    })
                log_line(
                    f"session action={action} id={session['id']} status={session['status']}",
                    tag="live-workout",
                    level="success",
                )
                self.send_json({"ok": True, "session": session})
            except (TypeError, ValueError) as exc:
                self.send_json({"error": str(exc), "code": "invalid_session_action"}, status=400)
            except Exception as exc:
                log_line(
                    f"session control failed: {type(exc).__name__}: {exc}",
                    tag="live-workout",
                    level="error",
                )
                self.send_json({"error": "Could not control workout session"}, status=500)
            return
        if path == "/api/live-workout/backup/import":
            try:
                payload = self.read_json_body(max_bytes=25 * 1024 * 1024)
                result = import_live_workout_backup(payload)
                log_line(
                    f"backup merged {json.dumps(result.get('merged'), ensure_ascii=False)}",
                    tag="live-workout",
                    level="success",
                )
                self.send_json(result)
            except (TypeError, ValueError) as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=400)
            except Exception as exc:
                log_line(f"backup import failed: {type(exc).__name__}: {exc}", tag="live-workout", level="error")
                self.send_json({"ok": False, "error": "Could not import backup"}, status=500)
            return
        if path == "/api/live-workout/telemetry":
            try:
                raw_payload = self.read_json_body(max_bytes=LIVE_WORKOUT_TELEMETRY_MAX_BYTES)
                telemetries, is_batch = normalize_live_workout_telemetry_payload(raw_payload)
                raw_samples = raw_payload if is_batch else [raw_payload]
                if is_batch:
                    log_line(
                        "payload batch "
                        f"samples={len(telemetries)} "
                        f"first_timestamp={telemetries[0]['timestamp']} "
                        f"last_timestamp={telemetries[-1]['timestamp']}",
                        tag="live-workout",
                        level="info",
                        console=False,
                    )
                else:
                    log_line(
                        f"payload {json.dumps(telemetries[0], ensure_ascii=False, sort_keys=True)}",
                        tag="live-workout",
                        level="info",
                        console=False,
                    )

                accepted = []
                stream_actions = []
                flatline_deletions = []
                latest_wear_state = "worn"
                for raw_telemetry, telemetry in zip(raw_samples, telemetries):
                    wear = LIVE_WORKOUT_WEAR_DETECTOR.observe(telemetry)
                    latest_wear_state = wear["wear_state"]
                    if wear["became_off_wrist"]:
                        flatline_start = wear["flatline_start"]
                        flatline_deletions.append(
                            (flatline_start, wear["timestamp"], wear["flatline_heart_rates"])
                        )
                        accepted = [
                            item for item in accepted
                            if not (
                                flatline_start <= item[2] <= wear["timestamp"]
                                and item[1]["heart_rate"] in wear["flatline_heart_rates"]
                            )
                        ]
                        stream_actions = [
                            item for item in stream_actions
                            if not (
                                item[0] == "telemetry"
                                and flatline_start <= item[2] <= wear["timestamp"]
                                and item[1]["heart_rate"] in wear["flatline_heart_rates"]
                            )
                        ]
                    if wear["wear_state"] == "worn":
                        accepted.append((raw_telemetry, telemetry, wear["timestamp"]))
                        stream_actions.append(("telemetry", telemetry, wear["timestamp"]))
                    else:
                        # Flat heart-rate values alone cannot reliably prove that the
                        # watch is off the wrist. Keep the storage-quality heuristic,
                        # but never let it suppress a valid live BPM reading.
                        stream_actions.append(("live_telemetry", telemetry, wear["timestamp"]))

                for start, end, heart_rates in flatline_deletions:
                    LIVE_WORKOUT_STORE.discard_heart_rate_flatline(start, end, heart_rates)
                accepted_raw = [item[0] for item in accepted]
                if len(accepted_raw) == 1 and not is_batch:
                    LIVE_WORKOUT_STORE.archive_heart_rate(accepted_raw[0])
                elif accepted_raw:
                    LIVE_WORKOUT_STORE.archive_heart_rates(accepted_raw)

                session = None
                subscriber_count = 0
                for action, telemetry, _timestamp in stream_actions:
                    if action == "telemetry":
                        ingested_session = LIVE_WORKOUT_STORE.ingest_dashboard(telemetry)
                        if ingested_session:
                            session = ingested_session
                    subscriber_count = broadcast_live_workout(telemetry)

                response_payload = {
                    "ok": True,
                    "telemetry": telemetries[-1],
                    "session_id": session.get("id") if session else None,
                    "wear_state": latest_wear_state,
                }
                if is_batch:
                    response_payload["accepted"] = len(telemetries)
                self.send_json(response_payload, status=202)
                log_line(
                    f"telemetry 202 | samples={len(telemetries)} | "
                    f"session={session.get('id') if session else '-'} | "
                    f"SSE={subscriber_count}",
                    tag="live-workout",
                    level="success",
                    console=False,
                )
                record_live_workout_console_result(
                    True,
                    samples=len(telemetries),
                    sse_clients=subscriber_count,
                )
            except TimelineError as exc:
                status = getattr(exc, "status", 400)
                code = getattr(exc, "code", "invalid_request")
                log_line(
                    f"response status={status} code={code} error={exc}",
                    tag="live-workout",
                    level="error",
                )
                record_live_workout_console_result(False)
                self.send_json(
                    {"error": str(exc), "code": code},
                    status=status,
                )
            except ValueError as exc:
                log_line(
                    f"response status=400 code=invalid_telemetry error={exc}",
                    tag="live-workout",
                    level="error",
                )
                record_live_workout_console_result(False)
                self.send_json({"error": str(exc), "code": "invalid_telemetry"}, status=400)
            except Exception as exc:
                log_line(
                    f"response status=500 code=telemetry_store_failed error={type(exc).__name__}: {exc}",
                    tag="live-workout",
                    level="error",
                )
                record_live_workout_console_result(False)
                self.send_json({"error": "Could not save workout telemetry"}, status=500)
            return
        if path in {"/api/lastfm/match", "/api/lastfm/sync"}:
            try:
                if path == "/api/lastfm/match":
                    payload = self.read_json_body(max_bytes=1024 * 1024)
                    self.send_json(LASTFM_STORE.match_albums(payload.get("albums") or []))
                else:
                    self.send_json(LASTFM_STORE.sync(force=True))
            except (TimelineError, LastFmError, ValueError) as exc:
                status = getattr(exc, "status", 400)
                self.send_json({"error": str(exc)}, status=status)
            except Exception as exc:
                log_line(f"Last.fm request failed: {exc}", tag="lastfm", level="error")
                self.send_json({"error": "Last.fm request failed"}, status=500)
            return
        if path in {
            "/api/journal-htr/server/start",
            "/api/journal-htr/server/stop",
        }:
            try:
                runtime = (
                    JOURNAL_HTR_RUNTIME.start()
                    if path.endswith("/start")
                    else JOURNAL_HTR_RUNTIME.stop()
                )
                status = 202 if runtime["state"] in {"starting", "stopping"} else 200
                self.send_json({"runtime": runtime}, status=status)
            except Exception as exc:
                log_line(
                    f"Journal HTR runtime action failed: {type(exc).__name__}",
                    tag="api",
                    level="error",
                )
                self.send_json(
                    {"error": "Could not change Journal HTR server state"},
                    status=500,
                )
            return
        if path == "/api/journal-htr/upload":
            try:
                length = int(self.headers.get("Content-Length", ""))
            except (TypeError, ValueError):
                self.send_json(
                    {"error": "Valid Content-Length is required", "code": "invalid_content_length"},
                    status=411,
                )
                return
            try:
                if length <= 0:
                    raise JournalHtrError("Request body is required", code="empty_body")
                if length > JOURNAL_HTR.max_multipart_bytes:
                    raise JournalHtrError(
                        "Upload request is too large",
                        status=413,
                        code="payload_too_large",
                    )
                raw = self.rfile.read(length)
                if len(raw) != length:
                    raise JournalHtrError("Incomplete request body", code="incomplete_body")
                self.send_json(
                    JOURNAL_HTR.upload(self.headers.get("Content-Type", ""), raw),
                    status=202,
                )
            except JournalHtrError as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            except Exception as exc:
                log_line(f"Journal HTR upload failed: {type(exc).__name__}", tag="api", level="error")
                self.send_json({"error": "Could not save HTR upload"}, status=500)
            return
        htr_json_routes = {
            "/api/journal-htr/projects",
            "/api/journal-htr/segment",
            "/api/journal-htr/transcribe",
            "/api/journal-htr/pages/reorder",
            "/api/journal-htr/sync",
            "/api/journal-htr/datasets",
            "/api/journal-htr/training/jobs",
            "/api/journal-htr/export",
        }
        htr_rotate_match = re.fullmatch(
            r"/api/journal-htr/pages/([a-f0-9]{32})/rotate", path
        )
        htr_preprocess_match = re.fullmatch(
            r"/api/journal-htr/pages/([a-f0-9]{32})/preprocess", path
        )
        htr_job_cancel_match = re.fullmatch(
            r"/api/journal-htr/jobs/([a-f0-9]{32})/cancel", path
        )
        htr_line_merge_match = re.fullmatch(
            r"/api/journal-htr/lines/([a-f0-9]{32})/merge", path
        )
        htr_model_action_match = re.fullmatch(
            r"/api/journal-htr/models/([a-zA-Z0-9._-]+)/"
            r"(activate|archive|cancel-training)", path
        )
        if (
            path in htr_json_routes
            or htr_rotate_match
            or htr_preprocess_match
            or htr_job_cancel_match
            or htr_line_merge_match
            or htr_model_action_match
        ):
            try:
                payload = self.read_json_body() if path not in {
                    "/api/journal-htr/sync",
                } and not htr_job_cancel_match and not htr_model_action_match else {}
                if path == "/api/journal-htr/projects":
                    result = JOURNAL_HTR.create_project(payload)
                    status = 201
                elif path == "/api/journal-htr/segment":
                    result = JOURNAL_HTR.start_segmentation(
                        payload.get("pageIds") or [],
                        payload.get("modelId"),
                        replace_existing=bool(payload.get("replaceExisting")),
                    )
                    status = 202
                elif path == "/api/journal-htr/transcribe":
                    result = JOURNAL_HTR.start_transcription(
                        payload.get("pageIds") or [], str(payload.get("modelId") or "")
                    )
                    status = 202
                elif path == "/api/journal-htr/pages/reorder":
                    result = JOURNAL_HTR.reorder_pages(payload.get("pageIds") or [])
                    status = 200
                elif path == "/api/journal-htr/sync":
                    result = JOURNAL_HTR.sync()
                    status = 202
                elif path == "/api/journal-htr/datasets":
                    result = JOURNAL_HTR._require_store().create_dataset(payload)
                    status = 201
                elif path == "/api/journal-htr/training/jobs":
                    result = JOURNAL_HTR.start_training(payload)
                    status = 202
                elif path == "/api/journal-htr/export":
                    result = JOURNAL_HTR.export_to_journal(payload)
                    status = 201
                elif htr_rotate_match:
                    result = JOURNAL_HTR.rotate_page(
                        htr_rotate_match.group(1), int(payload.get("angle") or 0)
                    )
                    status = 200
                elif htr_preprocess_match:
                    result = JOURNAL_HTR.preprocess_page(
                        htr_preprocess_match.group(1), payload
                    )
                    status = 202
                elif htr_job_cancel_match:
                    result = JOURNAL_HTR.cancel_job(htr_job_cancel_match.group(1))
                    status = 200
                elif htr_line_merge_match:
                    result = JOURNAL_HTR.merge_lines(
                        htr_line_merge_match.group(1),
                        str(payload.get("otherLineId") or ""),
                    )
                    status = 200
                elif htr_model_action_match:
                    if htr_model_action_match.group(2) == "activate":
                        result = JOURNAL_HTR.activate_model(htr_model_action_match.group(1))
                    elif htr_model_action_match.group(2) == "cancel-training":
                        result = JOURNAL_HTR.cancel_model_training(htr_model_action_match.group(1))
                    else:
                        result = JOURNAL_HTR.archive_model(htr_model_action_match.group(1))
                    status = 200
                self.send_json(result, status=status)
            except (JournalHtrError, TimelineError) as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            except Exception as exc:
                log_line(f"Journal HTR action failed: {type(exc).__name__}", tag="api", level="error")
                self.send_json({"error": "Journal HTR action failed"}, status=500)
            return
        if path in {"/api/timeline/items", "/api/timeline/categories", "/api/timeline/import"}:
            try:
                payload = self.read_json_body()
                if path == "/api/timeline/items":
                    self.send_json(TIMELINE_STORE.create_item(payload), status=201)
                elif path == "/api/timeline/categories":
                    self.send_json(TIMELINE_STORE.create_category(payload), status=201)
                else:
                    report = TIMELINE_STORE.import_snapshot(
                        payload.get("data"),
                        mode=str(payload.get("mode") or "merge"),
                        conflict=str(payload.get("conflict") or "overwrite"),
                        dry_run=bool(payload.get("dryRun")),
                    )
                    self.send_json({"ok": True, "report": report})
            except TimelineError as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            except Exception as exc:
                log_line(f"Timeline write failed: {exc}", tag="api", level="error")
                self.send_json({"error": "Could not save timeline data"}, status=500)
            return
        if path in {"/api/timeline/activity/habits/import", "/api/timeline/activity/emotions/import", "/api/timeline/activity/self-care"}:
            try:
                payload = self.read_json_body(max_bytes=HABIT_UPLOAD_MAX_BYTES * 2)
                if path.endswith("/habits/import"):
                    self.send_json(import_habit_file_from_payload(payload))
                elif path.endswith("/emotions/import"):
                    filename = Path(str(payload.get("filename") or "Check-in_data.csv")).name
                    if Path(filename).suffix.lower() != ".csv":
                        raise ValueError("How We Feel import requires a .csv file")
                    self.send_json(TIMELINE_ACTIVITY.import_emotions_csv(decode_habit_db_payload(payload), filename))
                else:
                    self.send_json(TIMELINE_ACTIVITY.record_self_care(payload), status=201)
            except TimelineError as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            except ValueError as exc:
                self.send_json({"error": str(exc), "code": "invalid_activity_payload"}, status=400)
            except Exception as exc:
                log_line(f"Timeline activity write failed: {exc}", tag="api", level="error")
                self.send_json({"error": "Could not update timeline activity"}, status=500)
            return
        if path == "/api/journal/context":
            try:
                payload = self.read_json_body()
                self.send_json(JOURNAL_CONTEXT.query(payload.get("dates")))
            except ValueError as exc:
                self.send_json({"error": str(exc), "code": "invalid_journal_context"}, status=400)
            except Exception as exc:
                log_line(f"Journal context load failed: {exc}", tag="api", level="error")
                self.send_json({"error": "Could not load journal context"}, status=500)
            return
        journal_publish_match = re.fullmatch(r"/api/journal/publish/voice-journal/([a-f0-9]{32})", path)
        if journal_publish_match:
            try:
                voice_entry = VOICE_JOURNAL_STORE.get(journal_publish_match.group(1))
                self.send_json(JOURNAL_STORE.publish_voice_entry(voice_entry), status=201)
            except (JournalError, VoiceJournalError) as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            except Exception as exc:
                log_line(f"Journal voice publication failed: {exc}", tag="api", level="error")
                self.send_json({"error": "Could not publish voice journal entry"}, status=500)
            return
        if path == "/api/journal/entries":
            try:
                length = int(self.headers.get("Content-Length", ""))
            except (TypeError, ValueError):
                self.send_json({"error": "Valid Content-Length is required"}, status=411)
                return
            if length <= 0 or length > JOURNAL_MAX_PAYLOAD_BYTES:
                self.send_json(
                    {"error": "Invalid journal payload size"},
                    status=413 if length > JOURNAL_MAX_PAYLOAD_BYTES else 400,
                )
                return
            raw = self.rfile.read(length)
            if len(raw) != length:
                self.send_json({"error": "Incomplete request body"}, status=400)
                return
            try:
                payload = json.loads(raw.decode("utf-8"))
                self.send_json(JOURNAL_STORE.create(payload), status=201)
            except json.JSONDecodeError:
                self.send_json({"error": "Invalid JSON"}, status=400)
            except JournalError as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            except Exception as exc:
                log_line(f"Journal create failed: {exc}", tag="api", level="error")
                self.send_json({"error": "Could not create journal entry"}, status=500)
            return
        cancel_match = re.fullmatch(r"/api/voice-journal/jobs/([a-f0-9]{32})/cancel", path)
        if cancel_match:
            try:
                self.send_json(VOICE_JOURNAL_JOBS.cancel(cancel_match.group(1)))
            except VoiceJournalError as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            except Exception as exc:
                log_line(f"Voice journal job cancellation failed: {exc}", tag="api", level="error")
                self.send_json({"error": "Could not cancel transcription job"}, status=500)
            return
        if not path.startswith("/api/settings/") and path not in {
            "/api/films/lists/create",
            "/api/films/library/add",
            "/api/films/library/update",
            "/api/classical-library/progress/update",
            "/api/classical-library/composer/update",
            "/api/classical-library/work/update",
            "/api/classical-library/composer/image",
            "/api/classical-library/composer/add",
            "/api/classical-library/composer/refresh",
            "/api/classical-library/works/import",
            "/api/classical-library/works/refresh",
            "/api/oscars/update",
            "/api/oscars/reset",
            "/api/oscars/posters",
            "/api/oscars/details",
            "/api/oscars/winners",
            "/api/bm365/cover",
            "/api/bm365/covers",
            "/api/bm365/mark",
            "/api/bm365/rate",
            "/api/bm365/sync-sheets",
            "/api/bm365/metadata/update",
            "/api/bm365/metadata/descriptions/import",
            "/api/brutal-assault-2027/albums",
            "/api/brutal-assault-2027/official/check",
            "/api/brutal-assault-2027/albums/update",
            "/api/brutal-assault-2027/albums/descriptions/import",
            "/api/brutal-assault-2027/sync-rating",
            "/api/brutal-assault-2027/cover",
            "/api/brutal-assault-2027/covers",
            "/api/rym-polish-black-metal/albums/update",
            "/api/rym-polish-black-metal/albums/descriptions/import",
            "/api/rym-polish-black-metal/cover",
            "/api/reading/cover",
            "/api/habits/upload-db",
            "/api/weight/events/delete",
            "/api/steps/events/upsert",
            "/api/steps/events/delete",
            "/api/health-connect/snapshot",
            "/api/diet/meals/upsert",
            "/api/diet/meals/delete",
            "/api/diet/estimates/upsert",
            "/api/diet/estimates/delete",
            "/api/diet/days/ignore",
            "/api/kitchen/settings",
            "/api/football/settings",
            "/api/screensaver-config",
            "/api/budget/save",
            "/api/budget/import-csv",
            "/api/budget/annotations",
            "/api/budget/settings",
            "/api/budget/imports/rollback",
            "/api/budget/migrate-legacy",
            "/api/artist-facts",
            "/api/spotify/player",
            "/api/google-calendar/sync",
            "/api/events/local/upsert",
            "/api/events/override",
            "/api/events/countdown-cover",
            "/api/events/google/upsert",
            "/api/events/google/delete",
            "/api/events/categories",
            "/api/voice-journal/transcribe",
            "/api/voice-journal/entries",
            "/api/voice-journal/jobs",
        }:
            self.send_json({"error": "Not found"}, status=404)
            return

        if path == "/api/voice-journal/jobs":
            try:
                length = int(self.headers.get("Content-Length", ""))
            except (TypeError, ValueError):
                self.send_json({"error": "Valid Content-Length is required", "code": "invalid_content_length"}, status=411)
                return
            if length <= 0:
                self.send_json({"error": "Request body is required", "code": "empty_body"}, status=400)
                return
            if length > VOICE_JOURNAL_MAX_MULTIPART_BYTES:
                self.send_json({"error": "Upload is too large", "code": "payload_too_large"}, status=413)
                return
            raw = self.rfile.read(length)
            if len(raw) != length:
                self.send_json({"error": "Incomplete request body", "code": "incomplete_body"}, status=400)
                return
            try:
                job = VOICE_JOURNAL_JOBS.submit(self.headers.get("Content-Type", ""), raw)
                self.send_json(job, status=202)
            except VoiceJournalError as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            except Exception as exc:
                log_line(f"Voice journal job submission failed: {exc}", tag="api", level="error")
                self.send_json({"error": "Could not queue transcription", "code": "job_submission_failed"}, status=500)
            return

        if path == "/api/voice-journal/entries":
            try:
                length = int(self.headers.get("Content-Length", ""))
            except (TypeError, ValueError):
                self.send_json({"error": "Valid Content-Length is required", "code": "invalid_content_length"}, status=411)
                return
            if length <= 0:
                self.send_json({"error": "Request body is required", "code": "empty_body"}, status=400)
                return
            if length > VOICE_JOURNAL_MAX_MULTIPART_BYTES:
                self.send_json({"error": "Upload is too large", "code": "payload_too_large"}, status=413)
                return
            raw = self.rfile.read(length)
            if len(raw) != length:
                self.send_json({"error": "Incomplete request body", "code": "incomplete_body"}, status=400)
                return
            try:
                audio_part, entry_payload = parse_create_entry_request(self.headers.get("Content-Type", ""), raw)
                self.send_json(VOICE_JOURNAL_STORE.create(audio_part, entry_payload), status=201)
            except VoiceJournalError as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            except Exception as exc:
                log_line(f"Voice journal create failed: {exc}", tag="api", level="error")
                self.send_json({"error": "Could not save voice journal entry"}, status=500)
            return

        if path == "/api/voice-journal/transcribe":
            try:
                length = int(self.headers.get("Content-Length", ""))
            except (TypeError, ValueError):
                self.send_json({"error": "Valid Content-Length is required", "code": "invalid_content_length"}, status=411)
                return
            if length <= 0:
                self.send_json({"error": "Request body is required", "code": "empty_body"}, status=400)
                return
            if length > VOICE_JOURNAL_MAX_MULTIPART_BYTES:
                self.send_json({"error": "Upload is too large", "code": "payload_too_large"}, status=413)
                return
            raw = self.rfile.read(length)
            if len(raw) != length:
                self.send_json({"error": "Incomplete request body", "code": "incomplete_body"}, status=400)
                return
            try:
                result = transcribe_voice_journal_multipart(self.headers.get("Content-Type", ""), raw)
                self.send_json(result)
            except VoiceJournalError as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            except Exception as exc:
                log_line(f"Voice journal transcription failed: {exc}", tag="api", level="error")
                self.send_json({"error": "Transcription failed", "code": "transcription_failed"}, status=500)
            return

        length = int(self.headers.get("Content-Length", 0))
        if path == "/api/budget/import-csv" and length > BUDGET_IMPORT_MAX_BYTES * 2:
            self.send_json({"ok": False, "error": "Payload too large"}, status=413)
            return
        if path == "/api/habits/upload-db" and length > HABIT_UPLOAD_MAX_BYTES * 2:
            self.send_json({"error": "Payload too large"}, status=413)
            return
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except json.JSONDecodeError:
            self.send_json({"error": "Invalid JSON"}, status=400)
            return

        try:
            if path.startswith("/api/settings/"):
                try:
                    name = urllib.parse.unquote(path.removeprefix("/api/settings/"))
                    result = write_settings_payload(name, payload)
                except ValueError as exc:
                    self.send_json({"ok": False, "error": str(exc)}, status=400)
                    return
                self.send_json(result)
                return

            if path == "/api/films/lists/create":
                try:
                    result = create_film_list(payload)
                except ValueError as exc:
                    self.send_json({"error": str(exc)}, status=400)
                    return
                self.send_json({"ok": True, "list": result})
                return

            if path == "/api/films/library/add":
                try:
                    result = add_film_to_library(payload)
                except ValueError as exc:
                    self.send_json({"error": str(exc)}, status=400)
                    return
                self.send_json({"ok": True, "film": result})
                return

            if path == "/api/films/library/update":
                film_id = payload.get("id")
                patch = payload.get("patch") or {}
                result = update_library_film(film_id, patch)
                if not result:
                    self.send_json({"error": "Update failed"}, status=400)
                    return
                self.send_json({"ok": True, "film": result})
                return

            if path == "/api/classical-library/progress/update":
                try:
                    self.send_json(update_classical_progress(payload))
                except ValueError as exc:
                    self.send_json({"error": str(exc)}, status=400)
                return

            if path == "/api/classical-library/composer/update":
                try:
                    self.send_json(update_classical_composer_metadata(payload))
                except ValueError as exc:
                    self.send_json({"error": str(exc)}, status=400)
                return

            if path == "/api/classical-library/work/update":
                try:
                    self.send_json(update_classical_work_metadata(payload))
                except ValueError as exc:
                    self.send_json({"error": str(exc)}, status=400)
                return

            if path == "/api/classical-library/composer/image":
                try:
                    self.send_json(upload_classical_composer_image(payload))
                except ValueError as exc:
                    self.send_json({"error": str(exc)}, status=400)
                return

            if path == "/api/classical-library/composer/add":
                try:
                    composer = add_classical_composer(payload)
                    self.send_json({"ok": True, "composer": composer, "summary": build_classical_summary()})
                except ValueError as exc:
                    self.send_json({"error": str(exc)}, status=400)
                return

            if path == "/api/classical-library/composer/refresh":
                try:
                    self.send_json(refresh_classical_placeholder(payload, "composer-profile"))
                except ValueError as exc:
                    self.send_json({"error": str(exc)}, status=400)
                return

            if path == "/api/classical-library/works/import":
                try:
                    if payload.get("contentBase64") or payload.get("content_base64"):
                        self.send_json(import_classical_rym_saved_html(payload))
                    else:
                        self.send_json(refresh_classical_placeholder(payload, "import-works"))
                except ValueError as exc:
                    self.send_json({"error": str(exc)}, status=400)
                return

            if path == "/api/classical-library/works/refresh":
                try:
                    self.send_json(refresh_classical_placeholder(payload, "refresh-work-catalogue"))
                except ValueError as exc:
                    self.send_json({"error": str(exc)}, status=400)
                return

            if path == "/api/habits/upload-db":
                try:
                    result = import_habit_db_from_payload(payload)
                except ValueError as exc:
                    self.send_json({"error": str(exc)}, status=400)
                    return
                self.send_json(result)
                return

            if path == "/api/weight/events/delete":
                try:
                    result = delete_weight_event(payload)
                except ValueError as exc:
                    self.send_json({"ok": False, "error": str(exc)}, status=400)
                    return
                self.send_json(result)
                return

            if path == "/api/steps/events/upsert":
                try:
                    result = upsert_steps_event(payload)
                except ValueError as exc:
                    self.send_json({"ok": False, "error": str(exc)}, status=400)
                    return
                self.send_json(result)
                return

            if path == "/api/steps/events/delete":
                try:
                    result = delete_steps_event(payload)
                except ValueError as exc:
                    self.send_json({"ok": False, "error": str(exc)}, status=400)
                    return
                self.send_json(result)
                return

            if path == "/api/health-connect/snapshot":
                try:
                    result = write_health_snapshot(payload)
                except ValueError as exc:
                    self.send_json({"ok": False, "error": str(exc)}, status=400)
                    return
                self.send_json(result)
                return

            if path == "/api/diet/meals/upsert":
                try:
                    result = upsert_diet_meal(payload)
                except ValueError as exc:
                    self.send_json({"ok": False, "error": str(exc)}, status=400)
                    return
                self.send_json(result)
                return

            if path == "/api/diet/meals/delete":
                try:
                    result = delete_diet_meal(payload)
                except ValueError as exc:
                    self.send_json({"ok": False, "error": str(exc)}, status=400)
                    return
                self.send_json(result)
                return

            if path == "/api/diet/estimates/upsert":
                try:
                    result = upsert_diet_estimates(payload)
                except ValueError as exc:
                    self.send_json({"ok": False, "error": str(exc)}, status=400)
                    return
                self.send_json(result)
                return

            if path == "/api/diet/estimates/delete":
                try:
                    result = delete_diet_estimates(payload)
                except ValueError as exc:
                    self.send_json({"ok": False, "error": str(exc)}, status=400)
                    return
                self.send_json(result)
                return

            if path == "/api/diet/days/ignore":
                try:
                    result = ignore_diet_days(payload)
                except ValueError as exc:
                    self.send_json({"ok": False, "error": str(exc)}, status=400)
                    return
                self.send_json(result)
                return

            if path == "/api/kitchen/settings":
                try:
                    result = write_kitchen_settings(payload)
                except ValueError as exc:
                    self.send_json({"ok": False, "error": str(exc)}, status=400)
                    return
                self.send_json(result)
                return

            if path == "/api/football/settings":
                try:
                    result = write_football_settings(payload)
                except ValueError as exc:
                    self.send_json({"ok": False, "error": str(exc)}, status=400)
                    return
                self.send_json(result)
                return

            if path == "/api/screensaver-config":
                try:
                    result = write_spotify_screensaver_config(payload)
                except ValueError as exc:
                    self.send_json({"ok": False, "error": str(exc)}, status=400)
                    return
                self.send_json(result)
                return

            if path == "/api/budget/save":
                self.send_json({
                    "ok": False,
                    "error": "Full Budget snapshot replacement is disabled.",
                }, status=410)
                return

            if path == "/api/budget/import-csv":
                try:
                    result = import_budget_csv_from_payload(payload)
                except FinanceValidationError as exc:
                    self.send_json({"ok": False, "error": str(exc), **exc.result}, status=400)
                    return
                except ValueError as exc:
                    self.send_json({"ok": False, "error": str(exc)}, status=400)
                    return
                self.send_json(result)
                return

            if path == "/api/budget/annotations":
                try:
                    updates = payload.get("updates") if isinstance(payload, dict) else None
                    result = FINANCE_SERVICE.update_annotations(updates)
                except FinanceValidationError as exc:
                    self.send_json({"ok": False, "error": str(exc), **exc.result}, status=400)
                    return
                except FinanceNotFoundError as exc:
                    self.send_json({"ok": False, "error": str(exc)}, status=404)
                    return
                self.send_json({"ok": True, "transactions": result})
                return

            if path == "/api/budget/settings":
                try:
                    settings = payload.get("settings") if isinstance(payload, dict) else None
                    result = FINANCE_SERVICE.update_settings(settings)
                except FinanceValidationError as exc:
                    self.send_json({"ok": False, "error": str(exc), **exc.result}, status=400)
                    return
                self.send_json({"ok": True, "settings": result})
                return

            if path == "/api/budget/imports/rollback":
                try:
                    batch_id = payload.get("batchId") if isinstance(payload, dict) else ""
                    result = FINANCE_SERVICE.rollback_import(batch_id)
                except FinanceNotFoundError as exc:
                    self.send_json({"ok": False, "error": str(exc)}, status=404)
                    return
                except FinanceError as exc:
                    self.send_json({"ok": False, "error": str(exc)}, status=409)
                    return
                self.send_json({"ok": True, "rollback": result})
                return

            if path == "/api/budget/migrate-legacy":
                try:
                    data = payload.get("data") if isinstance(payload, dict) else None
                    verification = FINANCE_SERVICE.migrate_browser_legacy_payload(data)
                except FinanceValidationError as exc:
                    self.send_json({"ok": False, "error": str(exc), **exc.result}, status=400)
                    return
                except FinanceError as exc:
                    self.send_json({"ok": False, "error": str(exc)}, status=409)
                    return
                self.send_json({
                    "ok": True,
                    "verification": verification,
                    "data": FINANCE_SERVICE.compatibility_payload(),
                })
                return

            if path == "/api/artist-facts":
                try:
                    result = write_artist_facts(payload)
                except ValueError as exc:
                    self.send_json({"ok": False, "error": str(exc)}, status=400)
                    return
                self.send_json(result)
                return

            if path == "/api/spotify/player":
                try:
                    result = control_spotify_player(payload.get("action"))
                except ValueError as exc:
                    self.send_json({"ok": False, "error": str(exc)}, status=400)
                    return
                self.send_json(result)
                return

            if path == "/api/google-calendar/sync":
                force = bool(payload.get("force"))
                result = sync_all_google_calendars(force=force)
                self.send_json(result)
                return

            if path == "/api/events/local/upsert":
                try:
                    result = upsert_local_dashboard_event(payload)
                except ValueError as exc:
                    self.send_json({"ok": False, "error": str(exc)}, status=400)
                    return
                self.send_json(result)
                return

            if path == "/api/events/categories":
                try:
                    result = save_event_countdown_category(payload)
                except ValueError as exc:
                    self.send_json({"ok": False, "error": str(exc)}, status=400)
                    return
                self.send_json(result)
                return

            if path == "/api/events/google/upsert":
                try:
                    result = upsert_google_calendar_event(payload)
                except ValueError as exc:
                    self.send_json({"ok": False, "error": str(exc)}, status=400)
                    return
                self.send_json(result)
                return

            if path == "/api/events/override":
                try:
                    result = upsert_google_calendar_event_override(payload)
                except ValueError as exc:
                    self.send_json({"ok": False, "error": str(exc)}, status=400)
                    return
                self.send_json(result)
                return

            if path == "/api/events/countdown-cover":
                try:
                    result = save_event_countdown_cover(payload)
                except ValueError as exc:
                    self.send_json({"ok": False, "error": str(exc)}, status=400)
                    return
                self.send_json(result)
                return

            if path == "/api/events/google/delete":
                try:
                    result = delete_google_calendar_event(payload)
                except ValueError as exc:
                    self.send_json({"ok": False, "error": str(exc)}, status=400)
                    return
                self.send_json(result)
                return

            if path == "/api/bm365/cover":
                try:
                    result = save_bm365_cover(payload)
                except ValueError as exc:
                    self.send_json({"error": str(exc)}, status=400)
                    return
                self.send_json(result)
                return

            if path == "/api/bm365/covers":
                limit = payload.get("limit") or 0
                force = bool(payload.get("force"))
                try:
                    result = bm365_download_all_covers(limit=limit, force=force)
                except Exception as exc:
                    self.send_json({"error": str(exc)}, status=500)
                    return
                self.send_json(result)
                return

            if path == "/api/bm365/mark":
                try:
                    album = BM365_STORE.mark_listened(
                        {"rowId": payload.get("rowId"), "date": payload.get("date")},
                        payload.get("listened", True),
                    )
                    BM365_SHEETS_SYNCER.notify()
                    self.send_json({"ok": True, "album": album})
                except Bm365Error as exc:
                    self.send_json(exc.as_payload(), status=exc.status)
                return

            if path == "/api/bm365/rate":
                try:
                    album = BM365_STORE.rate_album(
                        {"rowId": payload.get("rowId"), "date": payload.get("date")},
                        payload.get("rating"),
                    )
                    BM365_SHEETS_SYNCER.notify()
                    self.send_json({"ok": True, "album": album})
                except (Bm365Error, BrutalAssaultError) as exc:
                    self.send_json(exc.as_payload(), status=exc.status)
                return

            if path == "/api/bm365/sync-sheets":
                self.send_json({"ok": True, **BM365_SHEETS_SYNCER.flush_once(force=True)})
                return

            if path == "/api/bm365/metadata/update":
                try:
                    row_id = int(payload.get("id") or payload.get("rowId"))
                    metadata = BM365_STORE.update_metadata(
                        row_id,
                        year=payload.get("year") if "year" in payload else None,
                        description=payload.get("description") if "description" in payload else None,
                    )
                    self.send_json({"ok": True, "metadata": [metadata], "updated": metadata})
                except (TypeError, ValueError) as exc:
                    if isinstance(exc, (Bm365Error, Bm365MetadataError)):
                        self.send_json(exc.as_payload(), status=exc.status)
                    else:
                        self.send_json(
                            Bm365MetadataError(
                                "album id is required", code="invalid_album_id"
                            ).as_payload(),
                            status=400,
                        )
                except Exception as exc:
                    log_line(f"BM365 metadata update failed: {exc}", tag="api", level="error")
                    self.send_json({"error": "Could not update BM365 metadata"}, status=500)
                return

            if path == "/api/bm365/metadata/descriptions/import":
                try:
                    import_result = BM365_STORE.bulk_update_descriptions(
                        payload.get("descriptions"),
                        overwrite=bool(payload.get("overwrite")),
                    )
                    self.send_json({"ok": True, **import_result})
                except (Bm365Error, Bm365MetadataError) as exc:
                    self.send_json(exc.as_payload(), status=exc.status)
                except Exception as exc:
                    log_line(f"BM365 description import failed: {exc}", tag="api", level="error")
                    self.send_json({"error": "Could not import BM365 descriptions"}, status=500)
                return

            if path == "/api/brutal-assault-2027/albums":
                try:
                    album = BRUTAL_ASSAULT_2027_STORE.create(payload)
                    BM365_STORE.invalidate_cross_cache()
                    pending = BRUTAL_ASSAULT_2027_RATINGS.schedule(
                        [album], priority=0, force=True
                    )
                    result = brutal_assault_2027_snapshot_with_cross_list()
                    self.send_json(
                        {**result, "album": album, "communityRatingsPending": pending},
                        status=201,
                    )
                except BrutalAssaultError as exc:
                    self.send_json(exc.as_payload(), status=exc.status)
                return

            if path == "/api/brutal-assault-2027/official/check":
                try:
                    self.send_json(BRUTAL_ASSAULT_2027_MONITOR.check())
                except Exception as exc:
                    log_line(f"BA2027 manual check failed: {exc}", tag="api", level="error")
                    self.send_json({"error": "Could not check official BA2027 pages"}, status=500)
                return

            if path == "/api/brutal-assault-2027/albums/update":
                try:
                    album = BRUTAL_ASSAULT_2027_STORE.update(
                        payload.get("id") or payload.get("rowId"),
                        payload,
                    )
                    BM365_STORE.invalidate_cross_cache()
                    pending = 0
                    if not album.get("rymRating") and not album.get("communityCheckedAt"):
                        pending = BRUTAL_ASSAULT_2027_RATINGS.schedule(
                            [album], priority=0, force=True
                        )
                    cross_sync_error = None
                    if album_rating_value(album.get("rating")) is not None:
                        try:
                            sync_ba_rating_to_bm(album)
                        except Exception as exc:
                            cross_sync_error = str(exc)
                            log_line(f"BA2027 cross-list rating sync failed: {exc}", tag="api", level="warn")
                    result = (
                        BRUTAL_ASSAULT_2027_STORE.snapshot()
                        if cross_sync_error
                        else brutal_assault_2027_snapshot_with_cross_list()
                    )
                    response = {
                        **result,
                        "album": album,
                        "communityRatingsPending": pending,
                    }
                    if cross_sync_error:
                        response["crossListError"] = cross_sync_error
                    self.send_json(response)
                except BrutalAssaultError as exc:
                    self.send_json(exc.as_payload(), status=exc.status)
                return

            if path == "/api/brutal-assault-2027/albums/descriptions/import":
                try:
                    import_result = BRUTAL_ASSAULT_2027_STORE.bulk_update_descriptions(
                        payload.get("descriptions"),
                        overwrite=bool(payload.get("overwrite")),
                    )
                    snapshot = brutal_assault_2027_snapshot_with_cross_list()
                    self.send_json({**snapshot, **import_result})
                except BrutalAssaultError as exc:
                    self.send_json(exc.as_payload(), status=exc.status)
                return

            if path == "/api/brutal-assault-2027/sync-rating":
                try:
                    self.send_json(sync_bm_rating_to_ba(payload))
                except ValueError as exc:
                    self.send_json({"error": str(exc)}, status=400)
                return

            if path == "/api/brutal-assault-2027/cover":
                try:
                    result = save_bm365_cover(payload)
                except ValueError as exc:
                    self.send_json({"error": str(exc)}, status=400)
                    return
                self.send_json(result)
                return

            if path == "/api/brutal-assault-2027/covers":
                try:
                    if payload.get("artist") and payload.get("album"):
                        result = brutal_assault_2027_download_cover(
                            payload.get("artist"),
                            payload.get("album"),
                            force=bool(payload.get("force")),
                        )
                    else:
                        result = brutal_assault_2027_download_all_covers(
                            limit=payload.get("limit") or 0,
                            force=bool(payload.get("force")),
                        )
                except Exception as exc:
                    self.send_json({"error": str(exc)}, status=500)
                    return
                self.send_json(result)
                return

            if path == "/api/rym-polish-black-metal/albums/update":
                try:
                    album = RYM_POLISH_BLACK_METAL_STORE.update(
                        payload.get("id") or payload.get("rowId"),
                        {
                            key: payload[key]
                            for key in ("rating", "listened", "description")
                            if key in payload
                        },
                    )
                    cross_sync_error = None
                    if "rating" in payload and album_rating_value(album.get("rating")) is not None:
                        try:
                            sync_album_rating_across_lists(
                                album,
                                source="rym-polish-black-metal-top-100",
                                rym_row=album,
                            )
                        except Exception as exc:
                            cross_sync_error = str(exc)
                            log_line(f"RYM Polish BM cross-list rating sync failed: {exc}", tag="api", level="warn")
                    result = (
                        RYM_POLISH_BLACK_METAL_STORE.snapshot()
                        if cross_sync_error
                        else rym_polish_black_metal_snapshot_with_cross_lists()
                    )
                    response = {**result, "album": album}
                    if cross_sync_error:
                        response["crossListError"] = cross_sync_error
                    self.send_json(response)
                except BrutalAssaultError as exc:
                    self.send_json(exc.as_payload(), status=exc.status)
                return

            if path == "/api/rym-polish-black-metal/albums/descriptions/import":
                try:
                    import_result = RYM_POLISH_BLACK_METAL_STORE.bulk_update_descriptions(
                        payload.get("descriptions"),
                        overwrite=bool(payload.get("overwrite")),
                    )
                    snapshot = rym_polish_black_metal_snapshot_with_cross_lists()
                    self.send_json({**snapshot, **import_result})
                except BrutalAssaultError as exc:
                    self.send_json(exc.as_payload(), status=exc.status)
                return

            if path == "/api/rym-polish-black-metal/cover":
                try:
                    result = save_bm365_cover(payload)
                except ValueError as exc:
                    self.send_json({"error": str(exc)}, status=400)
                    return
                self.send_json(result)
                return

            if path == "/api/reading/cover":
                try:
                    result = save_reading_cover(payload)
                except ValueError as exc:
                    self.send_json({"error": str(exc)}, status=400)
                    return
                except Exception as exc:
                    self.send_json({"error": str(exc)}, status=500)
                    return
                self.send_json(result)
                return

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

    def do_PATCH(self):
        self._cors_origin = None
        path = urlparse(self.path).path
        if not self.authorize_api_request(path, require_origin=True):
            return
        if dispatch_sync(self, JOURNAL_STORE):
            return
        if self.dispatch_feelings_patch(path):
            return
        if self.dispatch_jobhunt_patch(path):
            return
        language_grammar_review_match = re.fullmatch(r"/api/language/grammar/occurrences/([^/]+)/review", path)
        if language_grammar_review_match:
            try:
                self.send_json(LANGUAGE_SERVICE.review_grammar(language_grammar_review_match.group(1), self.read_json_body(max_bytes=4096)))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_alignment_match = re.fullmatch(r"/api/language/content/alignments/([^/]+)", path)
        if language_alignment_match:
            try:
                payload = self.read_json_body(max_bytes=8 * 1024)
                self.send_json(LANGUAGE_SERVICE.correct_content_alignment(
                    language_alignment_match.group(1), payload
                ))
            except Exception as exc:
                self.send_language_error(exc)
            return
        budget_category_match = re.fullmatch(r"/api/budget/categories/(\d+)", path)
        budget_rule_match = re.fullmatch(r"/api/budget/rules/(\d+)", path)
        if budget_category_match or budget_rule_match:
            try:
                payload = self.read_json_body(max_bytes=64 * 1024)
                if budget_category_match:
                    result = {"category": FINANCE_SERVICE.update_category(int(budget_category_match.group(1)), payload)}
                else:
                    result = {"rule": FINANCE_SERVICE.update_rule(int(budget_rule_match.group(1)), payload)}
                self.send_json({"ok": True, **result})
            except FinanceNotFoundError as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=404)
            except FinanceError as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=400)
            return
        language_anki_config_match = re.fullmatch(r"/api/language/profiles/([^/]+)/anki/config", path)
        if language_anki_config_match:
            try:
                payload = self.read_json_body(max_bytes=32 * 1024)
                self.send_json(LANGUAGE_SERVICE.update_anki_config(language_anki_config_match.group(1), payload))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_profile_match = re.fullmatch(r"/api/language/profiles/([^/]+)", path)
        if language_profile_match:
            try:
                payload = self.read_json_body(max_bytes=64 * 1024)
                self.send_json(LANGUAGE_SERVICE.update_profile(language_profile_match.group(1), payload))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_topic_match = re.fullmatch(r"/api/language/topics/([^/]+)", path)
        if language_topic_match:
            try:
                payload = self.read_json_body(max_bytes=32 * 1024)
                self.send_json(LANGUAGE_SERVICE.update_topic(language_topic_match.group(1), payload))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_goal_match = re.fullmatch(r"/api/language/goals/([^/]+)", path)
        if language_goal_match:
            try:
                payload = self.read_json_body(max_bytes=32 * 1024)
                self.send_json(LANGUAGE_SERVICE.update_goal(language_goal_match.group(1), payload))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_campaign_match = re.fullmatch(r"/api/language/campaigns/([^/]+)", path)
        if language_campaign_match:
            try:
                payload = self.read_json_body(max_bytes=32 * 1024)
                self.send_json(LANGUAGE_SERVICE.update_campaign(language_campaign_match.group(1), payload))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_phrasebook_match = re.fullmatch(r"/api/language/phrasebook/([^/]+)", path)
        if language_phrasebook_match:
            try:
                payload = self.read_json_body(max_bytes=16 * 1024)
                self.send_json(LANGUAGE_SERVICE.update_phrasebook_entry(language_phrasebook_match.group(1), payload))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_lemma_match = re.fullmatch(r"/api/language/lemmas/([^/]+)", path)
        if language_lemma_match:
            try:
                payload = self.read_json_body(max_bytes=128 * 1024)
                self.send_json(LANGUAGE_SERVICE.update_lemma(language_lemma_match.group(1), payload))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_form_mapping_match = re.fullmatch(
            r"/api/language/forms/([^/]+)/mapping", path
        )
        if language_form_mapping_match:
            try:
                payload = self.read_json_body(max_bytes=16 * 1024)
                self.send_json(
                    LANGUAGE_SERVICE.lock_form_mapping(
                        language_form_mapping_match.group(1), payload
                    )
                )
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_session_match = re.fullmatch(
            r"/api/language/study-sessions/([^/]+)", path
        )
        if language_session_match:
            try:
                payload = self.read_json_body(max_bytes=16 * 1024)
                self.send_json(
                    LANGUAGE_SERVICE.update_reader_session(
                        language_session_match.group(1), payload
                    )
                )
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_listening_session_match = re.fullmatch(
            r"/api/language/listening-sessions/([^/]+)", path
        )
        if language_listening_session_match:
            try:
                payload = self.read_json_body(max_bytes=8 * 1024)
                self.send_json(LANGUAGE_SERVICE.close_listening_session(
                    language_listening_session_match.group(1), payload
                ))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_reading_progress_match = re.fullmatch(
            r"/api/language/texts/([^/]+)/reading-progress", path
        )
        if language_reading_progress_match:
            try:
                payload = self.read_json_body(max_bytes=32 * 1024)
                self.send_json(
                    LANGUAGE_SERVICE.update_reading_progress(
                        language_reading_progress_match.group(1), payload
                    )
                )
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_series_update_match = re.fullmatch(r"/api/language/reading-series/([^/]+)", path)
        if language_series_update_match:
            try:
                payload = self.read_json_body(max_bytes=16 * 1024)
                self.send_json(LANGUAGE_SERVICE.update_reading_series(language_series_update_match.group(1), payload))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_text_series_match = re.fullmatch(r"/api/language/texts/([^/]+)/series", path)
        if language_text_series_match:
            try:
                payload = self.read_json_body(max_bytes=8 * 1024)
                self.send_json(LANGUAGE_SERVICE.assign_text_to_series(language_text_series_match.group(1), payload))
            except Exception as exc:
                self.send_language_error(exc)
            return
        bm365_metadata_match = re.fullmatch(r"/api/bm365/albums/(\d+)/metadata", path)
        if bm365_metadata_match:
            try:
                payload = self.read_json_body(max_bytes=64 * 1024)
                album = BM365_STORE.update_metadata(
                    bm365_metadata_match.group(1),
                    year=payload.get("year") if "year" in payload else None,
                    description=payload.get("description") if "description" in payload else None,
                )
                self.send_json({"ok": True, "album": album, "metadata": [album], "updated": album})
            except Bm365Error as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            except Exception as exc:
                log_line(f"BM365 metadata update failed: {exc}", tag="api", level="error")
                self.send_json({"error": "Could not update BM365 metadata"}, status=500)
            return
        cleaning_task_match = re.fullmatch(r"/api/cleaning/tasks/([^/]+)", path)
        if cleaning_task_match:
            try:
                payload = self.read_json_body(max_bytes=256 * 1024)
                task_id = urllib.parse.unquote(cleaning_task_match.group(1))
                self.send_json({"ok": True, "task": CLEANING_STORE.update_task(task_id, payload)})
            except (CleaningError, TimelineError) as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            except Exception as exc:
                log_line(f"Cleaning task update failed: {exc}", tag="cleaning", level="error")
                self.send_json({"error": "Could not update cleaning task"}, status=500)
            return
        reading_progress_match = re.fullmatch(r"/api/reading/books/([^/]+)/progress", path)
        if reading_progress_match:
            try:
                payload = self.read_json_body(max_bytes=64 * 1024)
                book_id = urllib.parse.unquote(reading_progress_match.group(1))
                self.send_json(READING_STORE.update_progress(
                    book_id,
                    payload.get("pageCurrent", payload.get("page_current")),
                    record_history=payload.get("recordHistory", True) is not False,
                    day=payload.get("day"),
                ))
            except (ReadingError, TimelineError) as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            except Exception as exc:
                log_line(f"Reading progress save failed: {exc}", tag="reading", level="error")
                self.send_json({"error": "Could not save reading progress"}, status=500)
            return
        reading_book_match = re.fullmatch(r"/api/reading/books/([^/]+)", path)
        if reading_book_match:
            try:
                payload = self.read_json_body(max_bytes=1024 * 1024)
                book_id = urllib.parse.unquote(reading_book_match.group(1))
                book = READING_STORE.update_book(book_id, payload)
                self.send_json({"ok": True, "book_id": book["book_id"], "book": book})
            except (ReadingError, TimelineError) as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            except Exception as exc:
                log_line(f"Reading book update failed: {exc}", tag="reading", level="error")
                self.send_json({"error": "Could not update reading book"}, status=500)
            return
        htr_line_match = re.fullmatch(r"/api/journal-htr/lines/([a-f0-9]{32})", path)
        if htr_line_match:
            try:
                payload = self.read_json_body(max_bytes=1024 * 1024)
                self.send_json(JOURNAL_HTR.update_line(htr_line_match.group(1), payload))
            except (JournalHtrError, TimelineError) as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            except Exception as exc:
                log_line(f"Journal HTR line update failed: {type(exc).__name__}", tag="api", level="error")
                self.send_json({"error": "Could not update HTR line"}, status=500)
            return
        timeline_item_match = re.fullmatch(r"/api/timeline/items/([a-zA-Z0-9._-]+)", path)
        timeline_category_match = re.fullmatch(r"/api/timeline/categories/([a-zA-Z0-9._-]+)", path)
        if timeline_item_match or timeline_category_match:
            try:
                payload = self.read_json_body()
                if timeline_item_match:
                    result = TIMELINE_STORE.update_item(timeline_item_match.group(1), payload)
                else:
                    result = TIMELINE_STORE.update_category(timeline_category_match.group(1), payload)
                self.send_json(result)
            except TimelineError as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            except Exception as exc:
                log_line(f"Timeline update failed: {exc}", tag="api", level="error")
                self.send_json({"error": "Could not update timeline data"}, status=500)
            return
        journal_match = re.fullmatch(r"/api/journal/entries/([a-f0-9]{32})", path)
        if journal_match:
            try:
                length = int(self.headers.get("Content-Length", ""))
            except (TypeError, ValueError):
                self.send_json({"error": "Valid Content-Length is required"}, status=411)
                return
            if length <= 0 or length > JOURNAL_MAX_PAYLOAD_BYTES:
                self.send_json(
                    {"error": "Invalid journal payload size"},
                    status=413 if length > JOURNAL_MAX_PAYLOAD_BYTES else 400,
                )
                return
            raw = self.rfile.read(length)
            if len(raw) != length:
                self.send_json({"error": "Incomplete request body"}, status=400)
                return
            try:
                payload = json.loads(raw.decode("utf-8"))
                if isinstance(payload, dict) and "expectedVersion" in payload and payload["expectedVersion"] is None:
                    raise SyncError("VALIDATION_ERROR", "expectedVersion cannot be null")
                expected = payload.pop("expectedVersion", None) if isinstance(payload, dict) else None
                self.send_json(JOURNAL_STORE.update(journal_match.group(1), payload, expected_version=expected))
            except json.JSONDecodeError:
                self.send_json({"error": "Invalid JSON"}, status=400)
            except SyncError as exc:
                self.send_json(exc.payload(), status=exc.status)
            except JournalError as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            except Exception as exc:
                log_line(f"Journal update failed: {exc}", tag="api", level="error")
                self.send_json({"error": "Could not update journal entry"}, status=500)
            return
        match = re.fullmatch(r"/api/voice-journal/entries/([a-f0-9]{32})", path)
        if not match:
            self.send_json({"error": "Not found"}, status=404)
            return
        try:
            length = int(self.headers.get("Content-Length", ""))
        except (TypeError, ValueError):
            self.send_json({"error": "Valid Content-Length is required"}, status=411)
            return
        voice_journal_update_limit = 8 * 1024 * 1024
        if length <= 0 or length > voice_journal_update_limit:
            self.send_json({"error": "Invalid update payload size"}, status=413 if length > voice_journal_update_limit else 400)
            return
        raw = self.rfile.read(length)
        if len(raw) != length:
            self.send_json({"error": "Incomplete request body"}, status=400)
            return
        try:
            payload = json.loads(raw.decode("utf-8"))
            self.send_json(VOICE_JOURNAL_STORE.update(match.group(1), payload))
        except json.JSONDecodeError:
            self.send_json({"error": "Invalid JSON"}, status=400)
        except VoiceJournalError as exc:
            self.send_json(exc.as_payload(), status=exc.status)
        except Exception as exc:
            log_line(f"Voice journal update failed: {exc}", tag="api", level="error")
            self.send_json({"error": "Could not update voice journal entry"}, status=500)

    def do_DELETE(self):
        self._cors_origin = None
        parsed = urlparse(self.path)
        path = parsed.path
        if not self.authorize_api_request(path, require_origin=True):
            return
        if dispatch_sync(self, JOURNAL_STORE):
            return
        if self.dispatch_phone_tracker_delete(path, parsed.query):
            return
        if self.dispatch_feelings_delete(path, parsed.query):
            return
        if self.dispatch_jobhunt_delete(path):
            return
        if self.dispatch_mental_health_delete(path, parsed.query):
            return
        budget_rule_match = re.fullmatch(r"/api/budget/rules/(\d+)", path)
        if budget_rule_match:
            query = urllib.parse.parse_qs(parsed.query)
            if (query.get("confirm") or [""])[0] != "delete":
                self.send_json({"ok": False, "error": "Rule deletion requires confirm=delete"}, status=409)
                return
            try:
                self.send_json({"ok": True, "deleted": FINANCE_SERVICE.delete_rule(int(budget_rule_match.group(1)))})
            except FinanceNotFoundError as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=404)
            return
        language_topic_lemma_match = re.fullmatch(
            r"/api/language/topics/([^/]+)/lemmas/([^/]+)", path
        )
        if language_topic_lemma_match:
            try:
                self.send_json(LANGUAGE_SERVICE.remove_topic_lemma(
                    language_topic_lemma_match.group(1), language_topic_lemma_match.group(2)
                ))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_phrasebook_match = re.fullmatch(r"/api/language/phrasebook/([^/]+)", path)
        if language_phrasebook_match:
            try:
                self.send_json(LANGUAGE_SERVICE.delete_phrasebook_entry(language_phrasebook_match.group(1)))
            except Exception as exc:
                self.send_language_error(exc)
            return
        language_lemma_translation_match = re.fullmatch(r"/api/language/lemmas/([^/]+)/translations", path)
        if language_lemma_translation_match:
            try:
                query = urllib.parse.parse_qs(parsed.query)
                self.send_json(LANGUAGE_SERVICE.delete_lemma_translation(
                    language_lemma_translation_match.group(1),
                    (query.get("targetLocale") or [None])[0],
                ))
            except Exception as exc:
                self.send_language_error(exc)
            return
        synchrobook_book_match = re.fullmatch(r"/api/synchrobook/books/([a-f0-9]{32})", path)
        if synchrobook_book_match:
            try:
                query = urllib.parse.parse_qs(parsed.query)
                if (query.get("confirm") or [""])[0] != "delete":
                    raise SynchrobookError(
                        "Permanent deletion requires confirm=delete",
                        status=409,
                        code="confirmation_required",
                    )
                self.send_json(SYNCHROBOOK.delete_book(synchrobook_book_match.group(1)))
            except SynchrobookError as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            except Exception as exc:
                log_line(f"Synchrobook delete failed: {exc}", tag="synchrobook", level="error")
                self.send_json({"error": "Could not delete the Synchrobook"}, status=500)
            return
        cleaning_task_match = re.fullmatch(r"/api/cleaning/tasks/([^/]+)", path)
        cleaning_action_match = re.fullmatch(r"/api/cleaning/history/actions/([^/]+)", path)
        if cleaning_action_match:
            try:
                query = urllib.parse.parse_qs(parsed.query)
                apartment_id = (query.get("apartment") or [None])[0]
                action_id = urllib.parse.unquote(cleaning_action_match.group(1))
                self.send_json(CLEANING_STORE.remove_action(action_id, apartment_id))
            except CleaningError as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            except Exception as exc:
                log_line(f"Cleaning action delete failed: {exc}", tag="cleaning", level="error")
                self.send_json({"error": "Could not delete cleaning action"}, status=500)
            return
        if cleaning_task_match:
            try:
                task_id = urllib.parse.unquote(cleaning_task_match.group(1))
                self.send_json(CLEANING_STORE.delete_task(task_id, soft_delete=True))
            except CleaningError as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            except Exception as exc:
                log_line(f"Cleaning task delete failed: {exc}", tag="cleaning", level="error")
                self.send_json({"error": "Could not delete cleaning task"}, status=500)
            return
        live_workout_match = re.fullmatch(r"/api/live-workout/session/([a-zA-Z0-9-]+)", path)
        if live_workout_match:
            try:
                query = urllib.parse.parse_qs(parsed.query)
                if (query.get("confirm") or [""])[0] != "delete":
                    self.send_json(
                        {"error": "Permanent deletion requires confirm=delete", "code": "confirmation_required"},
                        status=409,
                    )
                    return
                session_id = live_workout_match.group(1)
                session = LIVE_WORKOUT_STORE.delete_session(session_id)
                if not session:
                    self.send_json({"error": "Workout session not found"}, status=404)
                    return
                removed_steps = remove_virtual_walk_steps(session_id) if session.get("workout_type") == "virtual_walk" else 0
                log_line(
                    f"session deleted id={session_id} virtual_steps_removed={removed_steps}",
                    tag="live-workout",
                    level="success",
                )
                self.send_json({"ok": True, "deleted": session_id, "virtual_steps_removed": removed_steps})
            except Exception as exc:
                log_line(f"session delete failed: {type(exc).__name__}: {exc}", tag="live-workout", level="error")
                self.send_json({"error": "Could not delete workout session"}, status=500)
            return
        htr_page_match = re.fullmatch(r"/api/journal-htr/pages/([a-f0-9]{32})", path)
        htr_model_match = re.fullmatch(
            r"/api/journal-htr/models/([a-zA-Z0-9._-]+)", path
        )
        if htr_page_match or htr_model_match:
            try:
                query = urllib.parse.parse_qs(parsed.query)
                if (query.get("confirm") or [""])[0] != "delete":
                    raise JournalHtrError(
                        "Permanent deletion requires confirm=delete",
                        status=409,
                        code="confirmation_required",
                    )
                result = (
                    JOURNAL_HTR.delete_page(htr_page_match.group(1))
                    if htr_page_match
                    else JOURNAL_HTR.delete_model(htr_model_match.group(1))
                )
                self.send_json(result)
            except JournalHtrError as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            except Exception as exc:
                log_line(f"Journal HTR delete failed: {type(exc).__name__}", tag="api", level="error")
                self.send_json({"error": "Could not delete HTR object"}, status=500)
            return
        timeline_item_match = re.fullmatch(r"/api/timeline/items/([a-zA-Z0-9._-]+)", path)
        timeline_category_match = re.fullmatch(r"/api/timeline/categories/([a-zA-Z0-9._-]+)", path)
        if timeline_item_match or timeline_category_match:
            try:
                if timeline_item_match:
                    result = TIMELINE_STORE.delete_item(timeline_item_match.group(1))
                else:
                    values = urllib.parse.parse_qs(parsed.query)
                    move_to = str((values.get("moveTo") or [""])[0]).strip() or None
                    result = TIMELINE_STORE.delete_category(timeline_category_match.group(1), move_to=move_to)
                self.send_json(result)
            except TimelineError as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            except Exception as exc:
                log_line(f"Timeline delete failed: {exc}", tag="api", level="error")
                self.send_json({"error": "Could not delete timeline data"}, status=500)
            return
        journal_match = re.fullmatch(r"/api/journal/entries/([a-f0-9]{32})", path)
        if journal_match:
            try:
                values = urllib.parse.parse_qs(parsed.query, keep_blank_values=True).get("expectedVersion")
                expected = None
                if values is not None:
                    if len(values) != 1 or not re.fullmatch(r"[1-9][0-9]{0,15}", values[0]):
                        raise SyncError("VALIDATION_ERROR", "Invalid expectedVersion")
                    expected = int(values[0])
                self.send_json(JOURNAL_STORE.delete(journal_match.group(1), expected_version=expected))
            except SyncError as exc:
                self.send_json(exc.payload(), status=exc.status)
            except JournalError as exc:
                self.send_json(exc.as_payload(), status=exc.status)
            except Exception as exc:
                log_line(f"Journal delete failed: {exc}", tag="api", level="error")
                self.send_json({"error": "Could not delete journal entry"}, status=500)
            return
        match = re.fullmatch(r"/api/voice-journal/entries/([a-f0-9]{32})", path)
        if not match:
            self.send_json({"error": "Not found"}, status=404)
            return
        values = urllib.parse.parse_qs(parsed.query)
        delete_audio_value = str((values.get("deleteAudio") or ["false"])[0]).lower()
        if delete_audio_value not in {"true", "false"}:
            self.send_json({"error": "deleteAudio must be true or false"}, status=400)
            return
        try:
            self.send_json(VOICE_JOURNAL_STORE.delete(
                match.group(1),
                delete_audio=delete_audio_value == "true",
            ))
        except VoiceJournalError as exc:
            self.send_json(exc.as_payload(), status=exc.status)
        except Exception as exc:
            log_line(f"Voice journal delete failed: {exc}", tag="api", level="error")
            self.send_json({"error": "Could not delete voice journal entry"}, status=500)


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
        sync_watchlist_to_film_library(conn)
        conn.close()
        write_films_static_snapshot()
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
    sync_watchlist_to_film_library(conn)
    conn.close()
    write_films_static_snapshot()
    return total

def run():
    log_line("Server starting...", tag="api", level="info")
    load_env_files()
    JOBHUNT_SERVICE.initialize()
    LANGUAGE_SERVICE.initialize()
    LANGUAGE_SERVICE.ensure_bokmal_profile()
    LANGUAGE_JOBS.start()
    BM365_SHEETS_SYNCER.api_base = os.environ.get("BM365_API_BASE", BM365_API_BASE)
    ensure_db()
    BM365_STORE.initialize()
    BM365_METADATA_STORE.initialize()
    BRUTAL_ASSAULT_2027_STORE.initialize()
    BRUTAL_ASSAULT_2027_MONITOR.start()
    RYM_POLISH_BLACK_METAL_STORE.initialize()
    BM365_STORE.get_albums()
    LASTFM_STORE.initialize()
    MUSIC_STORE.initialize()
    legacy_music = MUSIC_STORE.sync_legacy_catalog()
    imported_music = MUSIC_STORE.refresh_imported_metadata()
    music_covers = MUSIC_STORE.sync_local_covers()
    MUSIC_ENRICHMENT.start()
    log_line(
        f"Music legacy sync: {legacy_music['linked']} linked, "
        f"{legacy_music['created']} created, {legacy_music['ambiguous']} ambiguous; "
        f"metadata {imported_music['updated']} updated; covers {music_covers['matched']} matched",
        tag="music",
        level="success",
    )
    HABITS_STORE.initialize(ROOT / "data" / "habit-data.json")
    READING_STORE.initialize()
    TIMELINE_STORE.initialize()
    VOICE_JOURNAL_STORE.initialize()
    AI_USAGE_SERVICE.initialize()
    feelings_status = FEELINGS_SERVICE.initialize()
    log_line(
        f"Feelings seed: {feelings_status['seedStatus']} ({feelings_status['legacyCount']} legacy check-ins)",
        tag="feelings",
        level="success",
    )
    SYNCHROBOOK.start()
    LIVE_WORKOUT_STORE.initialize()
    STRENGTH_STORE.initialize()
    strength_migration = STRENGTH_STORE.migrate_live_workout_history(
        LIVE_WORKOUT_STORE.history(limit=10000)
    )
    if strength_migration["sessions"] or strength_migration["sets"]:
        log_line(
            f"Strength migration: {strength_migration['sessions']} sessions, {strength_migration['sets']} sets",
            tag="strength",
            level="success",
        )
    RING_COLLECTOR.start()
    VOICE_JOURNAL_JOBS.start()
    JOURNAL_HTR.initialize(start_worker=False)
    LASTFM_STORE.start_auto_sync(log_line)
    BM365_SHEETS_SYNCER.start()
    JOBHUNT_WORKER.start()
    port = int(os.environ.get("DASHBOARD_PORT", "8000"))
    host = os.environ.get("DASHBOARD_HOST", "127.0.0.1").strip() or "127.0.0.1"
    server = DashboardHTTPServer((host, port), Handler)
    visible_host = "127.0.0.1" if host in {"", "0.0.0.0"} else host
    log_line(f"Server running: http://{visible_host}:{port}", tag="api", level="success")
    if host == "0.0.0.0":
        log_line(f"LAN enabled: use http://YOUR-PC-IP:{port}", tag="api", level="success")
    try:
        server.serve_forever()
    finally:
        BRUTAL_ASSAULT_2027_MONITOR.stop()
        JOBHUNT_WORKER.stop()
        LANGUAGE_JOBS.stop()
        BM365_SHEETS_SYNCER.stop()
        LASTFM_STORE.stop_auto_sync()
        VOICE_JOURNAL_JOBS.stop()
        SYNCHROBOOK.stop()
        JOURNAL_HTR.stop()
        RING_COLLECTOR.stop()
        AI_USAGE_SERVICE.stop()


if __name__ == "__main__":
    run()
