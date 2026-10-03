"""Safe, explicit synchronization between canonical Language data and AnkiConnect."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo

from .errors import LanguageConflictError, LanguageNotFoundError, LanguageValidationError
from .anki_insights import _card_state, build_insights, lexical_key
from .providers.anki import (
    AnkiAdapter,
    AnkiAdapterError,
    AnkiTimeoutError,
    DEFAULT_ENDPOINT,
    MIN_API_VERSION,
    validate_local_endpoint,
)
from .store import LanguageStore, canonical_json, utc_now


ANKI_SYNC_POLICY_VERSION = "language.anki-sync/v1"
TEMPLATE_PURPOSE = "VOCABULARY"
FIELD_KEYS = frozenset({
    "target", "lemma", "context", "translation", "definition", "notes",
    "source", "topic", "dashboardKey",
})
CONFLICT_STATES = frozenset({"NONE", "LOCAL_CHANGED", "REMOTE_CHANGED", "BOTH_CHANGED"})
ANKI_LOCAL_TIMEZONE = ZoneInfo("Europe/Warsaw")


def _hash_fields(fields: dict[str, str]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(fields).encode("utf-8")).hexdigest()


def _anki_query_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


class AnkiSyncService:
    def __init__(
        self,
        store: LanguageStore,
        *,
        adapter_factory: Callable[..., Any] | None = None,
        api_key_getter: Callable[[], str | None] | None = None,
    ) -> None:
        self.store = store
        self.adapter_factory = adapter_factory or AnkiAdapter
        self.api_key_getter = api_key_getter or (
            lambda: os.environ.get("LANGUAGE_ANKI_CONNECT_API_KEY") or None
        )
        self._web_sync_lock = threading.Lock()
        self._last_web_sync_at: str | None = None
        self._last_web_sync_monotonic: float | None = None
        self._insights_lock = threading.Lock()
        self._insights_cache: tuple[str, float, dict[str, Any]] | None = None
        self._card_catalog_cache: tuple[str, float, list[dict[str, Any]]] | None = None
        self._vocabulary_card_cache: tuple[str, float, dict[str, Any]] | None = None

    @staticmethod
    def default_config() -> dict[str, Any]:
        return {
            "enabled": False,
            "autoSync": False,
            "endpoint": DEFAULT_ENDPOINT,
            "deckName": "",
            "modelName": "",
            "fieldMap": {},
        }

    def _config(self, profile_id: str) -> dict[str, Any]:
        result = self.default_config()
        result.update(self.store.get_anki_config(profile_id))
        if not isinstance(result.get("fieldMap"), dict):
            result["fieldMap"] = {}
        return result

    def public_config(self, profile_id: str) -> dict[str, Any]:
        config = self._config(profile_id)
        return {
            **config,
            "apiKeyConfigured": bool(self.api_key_getter()),
            "apiKeySource": "SERVER_ENVIRONMENT" if self.api_key_getter() else "NOT_CONFIGURED",
        }

    def update_config(self, profile_id: str, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise LanguageValidationError("Anki configuration must be an object")
        unknown = sorted(set(payload) - {"enabled", "autoSync", "endpoint", "deckName", "modelName", "fieldMap"})
        if unknown:
            raise LanguageValidationError("Anki configuration contains unsupported fields", details=unknown)
        config = self._config(profile_id)
        for key in ("enabled", "autoSync"):
            if key in payload:
                if not isinstance(payload[key], bool):
                    raise LanguageValidationError(f"{key} must be boolean", details=[key])
                config[key] = payload[key]
        if "endpoint" in payload:
            try:
                config["endpoint"] = validate_local_endpoint(payload["endpoint"])
            except ValueError as exc:
                raise LanguageValidationError(str(exc), code="invalid_anki_endpoint", details=["endpoint"]) from exc
        for key in ("deckName", "modelName"):
            if key in payload:
                value = payload[key]
                if not isinstance(value, str) or len(value.strip()) > 200:
                    raise LanguageValidationError(f"{key} must be a short string", details=[key])
                config[key] = value.strip()
        if "fieldMap" in payload:
            mapping = payload["fieldMap"]
            if not isinstance(mapping, dict) or set(mapping) - FIELD_KEYS:
                raise LanguageValidationError("fieldMap contains unsupported keys", details=["fieldMap"])
            normalized: dict[str, str] = {}
            for key, value in mapping.items():
                if not isinstance(value, str) or len(value.strip()) > 200:
                    raise LanguageValidationError("fieldMap values must be short strings", details=[key])
                if value.strip():
                    normalized[key] = value.strip()
            if len(set(normalized.values())) != len(normalized):
                raise LanguageValidationError("Each Anki field may be mapped only once", details=["fieldMap"])
            config["fieldMap"] = normalized
        self.store.update_anki_config(profile_id, config)
        self._vocabulary_card_cache = None
        return self.public_config(profile_id)

    def vocabulary_card_states(self, profile_id: str, lemma_ids: list[str]) -> dict[str, Any]:
        """Read current card queues across every Anki deck; never infer absence when offline."""
        if not self._config(profile_id)["enabled"]:
            return {"status": "NOT_CONFIGURED", "observedAt": None, "lemmas": {}}
        config = self._config(profile_id)
        cache_key = f"{profile_id}|{config['endpoint']}|{json.dumps(config['fieldMap'], sort_keys=True)}"
        with self._insights_lock:
            cached = self._vocabulary_card_cache
            if cached and cached[0] == cache_key and time.monotonic() - cached[1] < 60:
                catalog = cached[2]
            else:
                try:
                    adapter = self._adapter(profile_id, timeout_seconds=10.0)
                    deck_names = adapter.deck_names()
                    root_decks = [name for name in deck_names if not any(
                        name.startswith(other + "::") for other in deck_names
                    )]
                    card_ids: set[int] = set()
                    for name in root_decks:
                        card_ids.update(adapter.find_cards(f'deck:"{_anki_query_value(name)}"'))
                    if len(card_ids) > 15000:
                        return {"status": "TOO_LARGE", "observedAt": None, "lemmas": {}}
                    cards = []
                    sorted_ids = sorted(card_ids)
                    for index in range(0, len(sorted_ids), 75):
                        cards.extend(adapter.cards_info(sorted_ids[index:index + 75]))
                except AnkiAdapterError as exc:
                    return {"status": exc.state, "observedAt": None, "lemmas": {}, "message": str(exc)}
                with self.store.connection() as connection:
                    rows = connection.execute(
                        "SELECT id,lemma_normalized FROM vocabulary_lemmas WHERE language_profile_id=? AND merged_into_id IS NULL",
                        (profile_id,),
                    ).fetchall()
                    links = connection.execute(
                        "SELECT lemma_id,external_note_id FROM anki_note_links WHERE language_profile_id=?",
                        (profile_id,),
                    ).fetchall()
                by_word: dict[str, list[str]] = {}
                for row in rows:
                    by_word.setdefault(row["lemma_normalized"], []).append(row["id"])
                by_note = {int(row["external_note_id"]): row["lemma_id"] for row in links}
                by_lemma: dict[str, dict[str, list[str]]] = {}
                lemma_field = config["fieldMap"].get("lemma")
                for card in cards:
                    note_id = card.get("note")
                    lemma_id = by_note.get(int(note_id)) if note_id is not None else None
                    if lemma_id is None:
                        fields = card.get("fields") or {}
                        source = fields.get(lemma_field, {}).get("value") if lemma_field else None
                        word = lexical_key(source or self._card_front(card))
                        matches = by_word.get(word, []) if word else []
                        lemma_id = matches[0] if len(matches) == 1 else None
                    deck_name = card.get("deckName")
                    if lemma_id and isinstance(deck_name, str) and deck_name:
                        by_lemma.setdefault(lemma_id, {}).setdefault(deck_name, []).append(_card_state(card))
                catalog = {"observedAt": utc_now(), "lemmas": by_lemma}
                self._vocabulary_card_cache = (cache_key, time.monotonic(), catalog)
        return {
            "status": "CURRENT", "observedAt": catalog["observedAt"],
            "lemmas": {lemma_id: [
                {"deckName": name, "statuses": statuses}
                for name, statuses in sorted(catalog["lemmas"].get(lemma_id, {}).items())
            ] for lemma_id in lemma_ids},
        }

    def _adapter(self, profile_id: str, *, require_enabled: bool = True, timeout_seconds: float = 3.0) -> Any:
        config = self._config(profile_id)
        if require_enabled and not config["enabled"]:
            raise LanguageValidationError("Anki integration is not enabled", code="anki_not_configured")
        return self.adapter_factory(
            config["endpoint"], api_key=self.api_key_getter(), timeout_seconds=timeout_seconds
        )

    @staticmethod
    def _adapter_error(exc: AnkiAdapterError) -> dict[str, Any]:
        return {"status": exc.state, "errorCode": exc.code, "message": str(exc)}

    @staticmethod
    def _recent_review_days(adapter: Any, deck_names: list[str]) -> list[dict[str, Any]]:
        today = datetime.now(ANKI_LOCAL_TIMEZONE).date()
        first_day = today - timedelta(days=6)
        start_id = int(datetime.combine(first_day, datetime.min.time(), ANKI_LOCAL_TIMEZONE).timestamp() * 1000)
        reviews = {row[0]: row for name in deck_names for row in adapter.card_reviews(name, start_id)}
        counts = {(first_day + timedelta(days=offset)).isoformat(): 0 for offset in range(7)}
        cards: dict[str, set[int]] = {day: set() for day in counts}
        for row in reviews.values():
            if row[3] in {1, 2, 3, 4}:
                day = datetime.fromtimestamp(row[0] / 1000, ANKI_LOCAL_TIMEZONE).date().isoformat()
                if day in counts:
                    counts[day] += 1
                    cards[day].add(row[1])
        return [{"date": day, "answers": count, "cards": len(cards[day])}
                for day, count in counts.items()]

    def status(self, profile_id: str, *, probe: bool = True) -> dict[str, Any]:
        config = self.public_config(profile_id)
        summary = self.store.anki_profile_summary(profile_id)
        configured = bool(config["deckName"])
        write_configured = bool(config["modelName"] and config["fieldMap"].get("target"))
        if not config["enabled"]:
            return {
                "status": "NOT_CONFIGURED", "configured": False, "writeConfigured": write_configured, "connection": None,
                "config": config, **self._summary_api(summary), "policyVersion": ANKI_SYNC_POLICY_VERSION,
            }
        if not probe:
            return {
                "status": "PARTIALLY_CONFIGURED" if not configured else "NOT_CHECKED",
                "configured": configured, "writeConfigured": write_configured, "connection": None, "config": config,
                **self._summary_api(summary), "policyVersion": ANKI_SYNC_POLICY_VERSION,
            }
        try:
            adapter = self._adapter(profile_id)
            capabilities = adapter.capabilities().api()
            decks = []
            if capabilities["supported"]:
                for name in sorted(adapter.deck_names(), key=str.casefold):
                    try:
                        counts = adapter.deck_stats(name)
                        query = f'deck:"{_anki_query_value(name)}"'
                        new_done = len(adapter.find_cards(f"{query} introduced:1"))
                        reviews_done = len(adapter.find_cards(f"{query} rated:1 -introduced:1"))
                        decks.append({"name": name, **counts,
                                      "newCompletedToday": new_done,
                                      "reviewsCompletedToday": reviews_done,
                                      "newPlannedToday": new_done + counts["new"],
                                      "reviewsPlannedToday": reviews_done + counts["due"],
                                      "answeredCardsToday": new_done + reviews_done,
                                      "observedAt": utc_now()})
                    except AnkiAdapterError as exc:
                        decks.append({"name": name, "error": str(exc)})
            week = None
            if capabilities["supported"] and not any(
                "error" in item and item["name"].casefold() != "default" for item in decks
            ):
                try:
                    week = self._recent_review_days(adapter, [item["name"] for item in decks
                        if "error" not in item and item["name"].casefold() != "default"])
                    today = datetime.now(ANKI_LOCAL_TIMEZONE).date().isoformat()
                    self.store.observe_anki_daily_plans(profile_id, today, decks)
                    plans = self.store.recent_anki_daily_plans(profile_id, week[0]["date"])
                    current_decks = [item for item in decks if item["name"].casefold() != "default"
                        and not any(item["name"].startswith(parent["name"] + "::")
                                    for parent in decks if parent is not item)]
                    current_plan = sum(item["newPlannedToday"] + item["reviewsPlannedToday"]
                                       for item in current_decks)
                    current_done = sum(item["newCompletedToday"] + item["reviewsCompletedToday"]
                                       for item in current_decks)
                    for day in week:
                        is_today = day["date"] == today
                        planned = current_plan if is_today else plans.get(day["date"])
                        day["planned"] = planned
                        day["complete"] = None if planned is None else planned > 0 and (
                            current_done >= planned if is_today else day["cards"] >= planned)
                except AnkiAdapterError:
                    pass
            deck = next((item for item in decks if item["name"] == config["deckName"]), None)
        except AnkiAdapterError as exc:
            return {
                **self._adapter_error(exc), "configured": configured, "writeConfigured": write_configured, "connection": None,
                "config": config, **self._summary_api(summary), "policyVersion": ANKI_SYNC_POLICY_VERSION,
            }
        state = "VERSION_UNSUPPORTED" if not capabilities["supported"] else (
            "CONNECTED" if configured else "PARTIALLY_CONFIGURED"
        )
        if capabilities["supported"] and config["deckName"] and deck is None:
            state = "DECK_MISSING"
        return {
            "status": state, "configured": configured, "writeConfigured": write_configured, "connection": capabilities,
            "config": config, **self._summary_api(summary),
            "dueCount": deck.get("due") if deck else None,
            "deck": deck, "decks": decks, "week": week, "lastWebSyncAt": self._last_web_sync_at,
            "policyVersion": ANKI_SYNC_POLICY_VERSION,
        }

    def sync_web(self, profile_id: str, *, force: bool = False) -> dict[str, Any]:
        config = self._config(profile_id)
        if not config["enabled"] or not config["deckName"]:
            raise LanguageValidationError("Select an Anki deck before syncing", code="anki_deck_not_configured")
        if not force and not config["autoSync"]:
            return {"skipped": "AUTO_SYNC_DISABLED", "status": self.status(profile_id, probe=True)}
        with self._web_sync_lock:
            now = time.monotonic()
            if not force and self._last_web_sync_monotonic is not None and now - self._last_web_sync_monotonic < 300:
                return {"skipped": "RECENT_SYNC", "status": self.status(profile_id, probe=True)}
            try:
                self._require_supported(profile_id)
                self.reconcile_manual_knowledge(profile_id)
                self._adapter(profile_id, timeout_seconds=30.0).sync_web()
            except AnkiAdapterError as exc:
                raise LanguageValidationError(str(exc), code=exc.code) from exc
            self._last_web_sync_monotonic = time.monotonic()
            self._last_web_sync_at = utc_now()
            self._insights_cache = None
            self._card_catalog_cache = None
            result = {"syncedAt": self._last_web_sync_at, "status": self.status(profile_id, probe=True)}
        try:
            insights = self.deck_insights(profile_id, limit=1, refresh=True)
            result["matchedVocabularyCards"] = insights["inventory"]["matchedVocabularyCards"]
        except LanguageValidationError as exc:
            result["insightsError"] = str(exc)
        return result

    @staticmethod
    def _card_front(card: dict[str, Any]) -> str:
        fields = card.get("fields") or {}
        ordered = sorted(fields.values(), key=lambda item: item.get("order", 0))
        return str((fields.get("Front") or (ordered[0] if ordered else {})).get("value", ""))

    def _all_deck_cards(self, profile_id: str, adapter: Any) -> list[dict[str, Any]]:
        config = self._config(profile_id)
        name = config["deckName"]
        cache_key = f"{profile_id}|{config['endpoint']}|{name}"
        cached = self._insights_cache
        if cached and cached[0] == cache_key and time.monotonic() - cached[1] < 300:
            return cached[2]["cards"]
        catalog = self._card_catalog_cache
        if catalog and catalog[0] == cache_key and time.monotonic() - catalog[1] < 300:
            return catalog[2]
        ids = adapter.find_cards(f'deck:"{_anki_query_value(name)}"')
        cards: list[dict[str, Any]] = []
        for index in range(0, len(ids), 75):
            cards.extend(adapter.cards_info(ids[index:index + 75]))
        self._card_catalog_cache = (cache_key, time.monotonic(), cards)
        return cards

    def reflect_manual_knowledge(self, lemma_id: str, *, status: str) -> dict[str, Any]:
        with self.store.connection() as connection:
            row = connection.execute(
                "SELECT id,language_profile_id,lemma_normalized FROM vocabulary_lemmas WHERE id=? AND merged_into_id IS NULL",
                (lemma_id,),
            ).fetchone()
            if row is None:
                return {"state": "NO_LEMMA"}
            ambiguous = connection.execute(
                "SELECT COUNT(*) FROM vocabulary_lemmas WHERE language_profile_id=? AND lemma_normalized=? AND merged_into_id IS NULL",
                (row["language_profile_id"], row["lemma_normalized"]),
            ).fetchone()[0] != 1
        profile_id = row["language_profile_id"]
        config = self._config(profile_id)
        if ambiguous or not config["enabled"] or not config["deckName"]:
            return {"state": "NO_SAFE_MATCH"}
        try:
            adapter = self._adapter(profile_id, timeout_seconds=30.0)
            notes = sorted({int(card["note"]) for card in self._all_deck_cards(profile_id, adapter)
                            if lexical_key(self._card_front(card)) == row["lemma_normalized"].casefold()
                            and card.get("note") is not None})
            if not notes:
                return {"state": "NO_SAFE_MATCH"}
            status_tags = ["dashboard_status_new", "dashboard_status_learning",
                           "dashboard_status_known", "dashboard_status_mastered", "dashboard_status_ignored"]
            adapter.remove_tags(notes, status_tags)
            adapter.add_tags(notes, [f"dashboard_status_{status.lower()}"])
            return {"state": "TAGGED", "notes": len(notes), "tag": f"dashboard_status_{status.lower()}",
                    "schedulingChanged": False}
        except AnkiAdapterError as exc:
            return {"state": "PENDING_ANKI", "reason": exc.code}

    def reconcile_manual_knowledge(self, profile_id: str) -> dict[str, int]:
        config = self._config(profile_id)
        if not config["enabled"] or not config["deckName"]:
            return {"tagged": 0}
        with self.store.connection() as connection:
            rows = connection.execute(
                "SELECT l.lemma_normalized,k.knowledge_status,k.disposition "
                "FROM vocabulary_lemmas l JOIN lemma_knowledge k ON k.lemma_id=l.id "
                "WHERE l.language_profile_id=? AND l.merged_into_id IS NULL AND k.manual_status_override=1 "
                "AND l.lemma_normalized NOT IN (SELECT lemma_normalized FROM vocabulary_lemmas "
                "WHERE language_profile_id=? AND merged_into_id IS NULL GROUP BY lemma_normalized HAVING COUNT(*)>1)",
                (profile_id, profile_id),
            ).fetchall()
        desired = {row["lemma_normalized"].casefold():
                   f"dashboard_status_{'ignored' if row['disposition'] == 'IGNORED' else row['knowledge_status'].lower()}"
                   for row in rows}
        if not desired:
            return {"tagged": 0}
        adapter = self._adapter(profile_id, timeout_seconds=30.0)
        matched: dict[int, str] = {}
        for card in self._all_deck_cards(profile_id, adapter):
            key = lexical_key(self._card_front(card))
            if key in desired and card.get("note") is not None:
                matched[int(card["note"])] = desired[key]
        if not matched:
            return {"tagged": 0}
        current: dict[int, dict[str, Any]] = {}
        note_ids = sorted(matched)
        for index in range(0, len(note_ids), 75):
            for note in adapter.notes_info(note_ids[index:index + 75]):
                current[int(note["noteId"])] = note
        grouped: dict[str, list[int]] = {}
        all_tags = ["dashboard_status_new", "dashboard_status_learning",
                    "dashboard_status_known", "dashboard_status_mastered", "dashboard_status_ignored"]
        for note_id, tag in matched.items():
            present = set(current.get(note_id, {}).get("tags") or []) & set(all_tags)
            if present != {tag}:
                grouped.setdefault(tag, []).append(note_id)
        for tag, ids in grouped.items():
            adapter.remove_tags(ids, all_tags)
            adapter.add_tags(ids, [tag])
        return {"tagged": sum(map(len, grouped.values()))}

    def deck_insights(self, profile_id: str, *, offset: int = 0, limit: int = 50,
                      query: str = "", refresh: bool = False, deck_name: str | None = None) -> dict[str, Any]:
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise LanguageValidationError("offset must be a non-negative integer", details=["offset"])
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise LanguageValidationError("limit must be between 1 and 100", details=["limit"])
        if not isinstance(query, str) or len(query) > 120:
            raise LanguageValidationError("query must be a short string", details=["query"])
        config = self._config(profile_id)
        selected = config["deckName"]
        deck_name = deck_name or selected
        if not isinstance(deck_name, str) or len(deck_name) > 200:
            raise LanguageValidationError("Anki deck name is invalid", details=["deck"])
        cache_key = f"{profile_id}|{config['endpoint']}|{deck_name}"
        if not config["enabled"] or not deck_name:
            raise LanguageValidationError("Select an Anki deck first", code="anki_deck_not_configured")
        try:
            all_names = self._adapter(profile_id).deck_names()
        except AnkiAdapterError as exc:
            raise LanguageValidationError(str(exc), code=exc.code) from exc
        available = sorted({name for name in all_names if name == selected or
                            (name.startswith("Reader Stories::") and name.count("::") == 1)})
        if deck_name not in available:
            raise LanguageValidationError("This deck is not selected for Language insights", code="anki_deck_not_available")
        with self._insights_lock:
            cached = self._insights_cache
            fresh = refresh or cached is None or cached[0] != cache_key or time.monotonic() - cached[1] >= 300
            if fresh:
                try:
                    self._require_supported(profile_id)
                    adapter = self._adapter(profile_id, timeout_seconds=30.0)
                    if deck_name not in all_names:
                        raise LanguageValidationError("Selected Anki deck is missing", code="anki_deck_missing")
                    descendants = [name for name in all_names if name == deck_name or name.startswith(deck_name + "::")]
                    source_decks = [name for name in descendants if not any(
                        other.startswith(name + "::") for other in descendants
                    )]
                    ids = sorted({card_id for name in source_decks for card_id in
                                  adapter.find_cards(f'deck:"{_anki_query_value(name)}"')})
                    cards = []
                    for index in range(0, len(ids), 75):
                        cards.extend(adapter.cards_info(ids[index:index + 75]))
                    reviews_by_id = {row[0]: row for name in source_decks for row in adapter.card_reviews(name)}
                    # Anki already applies the parent deck's daily limits to its children.
                    # Summing child counters overstates cards actually available today.
                    deck_counts = adapter.deck_stats(deck_name)
                    data = {
                        "cards": cards, "reviews": list(reviews_by_id.values()),
                        "counts": {key: deck_counts[key] for key in ("new", "learn", "due")},
                        "options": adapter.deck_config(deck_name),
                        "forecastIds": [
                            {card_id for name in source_decks for card_id in
                             adapter.find_cards(f'deck:"{_anki_query_value(name)}" is:review prop:due={day}')}
                            for day in range(1, 15)
                        ],
                        "observedAt": utc_now(),
                    }
                except AnkiAdapterError as exc:
                    raise LanguageValidationError(str(exc), code=exc.code) from exc
                self._insights_cache = (cache_key, time.monotonic(), data)
                self._card_catalog_cache = (cache_key, time.monotonic(), cards)
            else:
                data = cached[2]
        with self.store.connection() as connection:
            rows = connection.execute(
                "SELECT l.id,l.lemma_display,l.lemma_normalized,k.knowledge_status,k.manual_status_override "
                "FROM vocabulary_lemmas l JOIN lemma_knowledge k ON k.lemma_id=l.id "
                "WHERE l.language_profile_id=? AND l.merged_into_id IS NULL",
                (profile_id,),
            ).fetchall()
        vocabulary: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            item = dict(row)
            vocabulary.setdefault(str(item["lemma_normalized"]).casefold(), []).append(item)
        if fresh:
            all_cards = build_insights(
                deck_name=deck_name, counts=data["counts"], options=data["options"],
                cards=data["cards"], reviews=data["reviews"], forecast_ids=data["forecastIds"],
                vocabulary=vocabulary, observed_at=data["observedAt"],
                offset=0, limit=len(data["cards"]), query="",
            )["cards"]["items"]
            signals: dict[str, list[dict[str, Any]]] = {}
            for card in all_cards:
                if card["lemma"] and card["knowledge"].get("lastReviewId"):
                    signals.setdefault(card["lemma"]["id"], []).append(card)
            for lemma_id, related in signals.items():
                weakest = min(related, key=lambda item: item["knowledge"]["score"])
                estimate = weakest["knowledge"]
                identity = sorted((item["cardId"], item["knowledge"]["lastReviewId"]) for item in related)
                key = "anki-review-v1:" + hashlib.sha256(canonical_json(identity).encode("utf-8")).hexdigest()
                self.store.apply_anki_knowledge_signal(
                    lemma_id, idempotency_key=key, status=estimate["status"],
                    recognition=max(0, min(5, round(estimate["score"] / 20))),
                    payload={"score": estimate["score"], "status": estimate["status"],
                             "cards": identity, "matchBasis": "EXACT_SINGLE_WORD_OR_ARTICLE_WORD"},
                )
            if signals:
                with self.store.connection() as connection:
                    refreshed = connection.execute(
                        "SELECT l.id,l.lemma_display,l.lemma_normalized,k.knowledge_status,k.manual_status_override "
                        "FROM vocabulary_lemmas l JOIN lemma_knowledge k ON k.lemma_id=l.id "
                        "WHERE l.language_profile_id=? AND l.merged_into_id IS NULL",
                        (profile_id,),
                    ).fetchall()
                vocabulary.clear()
                for row in refreshed:
                    item = dict(row)
                    vocabulary.setdefault(str(item["lemma_normalized"]).casefold(), []).append(item)
        result = build_insights(
            deck_name=deck_name, counts=data["counts"], options=data["options"],
            cards=data["cards"], reviews=data["reviews"], forecast_ids=data["forecastIds"],
            vocabulary=vocabulary, observed_at=data["observedAt"],
            offset=offset, limit=limit, query=query,
        )
        result["availableDecks"] = available
        return result

    def _summary_api(self, summary: dict[str, Any]) -> dict[str, Any]:
        last = LanguageStore.api_row(summary.get("lastRun"))
        due = None
        if last:
            due = (last.get("result") or {}).get("dueCount")
        return {
            "linkedVocabulary": summary["linkedVocabulary"],
            "conflicts": summary["conflicts"],
            "lastSync": last,
            "dueCount": due,
        }

    def test_connection(self, profile_id: str) -> dict[str, Any]:
        run = self.store.create_anki_sync_run(profile_id, "TEST", {})
        status = self.status(profile_id, probe=True)
        success = status["status"] in {"CONNECTED", "PARTIALLY_CONFIGURED"}
        finished = self.store.finish_anki_sync_run(
            run["id"], status="COMPLETED" if success else "FAILED",
            counts={"probes": 1}, warnings=[] if success else [status.get("message", status["status"])],
            errors=[] if success else [{"code": status.get("errorCode", status["status"])}],
            result={"connectionStatus": status["status"]},
        )
        return {"status": status, "run": LanguageStore.api_row(finished)}

    def decks(self, profile_id: str) -> dict[str, Any]:
        self._require_supported(profile_id)
        return {"items": self._adapter(profile_id).deck_names()}

    def models(self, profile_id: str) -> dict[str, Any]:
        self._require_supported(profile_id)
        return {"items": self._adapter(profile_id).model_names()}

    def model_fields(self, profile_id: str, model_name: str) -> dict[str, Any]:
        self._require_supported(profile_id)
        return {"modelName": model_name, "items": self._adapter(profile_id).model_field_names(model_name)}

    def _require_supported(self, profile_id: str) -> dict[str, Any]:
        capabilities = self._adapter(profile_id).capabilities().api()
        if not capabilities["supported"]:
            raise LanguageValidationError("AnkiConnect version is unsupported", code="anki_version_unsupported")
        return capabilities

    @staticmethod
    def _dashboard_key(profile_id: str, lemma_id: str, purpose: str) -> str:
        return f"language-dashboard:{profile_id}:{lemma_id}:{purpose.casefold()}"

    @staticmethod
    def _stable_tag(profile_id: str, lemma_id: str, purpose: str) -> str:
        return f"language_dashboard_{profile_id}_{lemma_id}_{purpose.casefold()}"

    def _projection(self, lemma_id: str, *, sentence_id: str | None = None) -> dict[str, Any]:
        detail = self.store.get_lemma_detail(lemma_id)
        lemma = detail["lemma"]
        profile_id = str(lemma["language_profile_id"])
        context = self.store.anki_context(lemma_id, sentence_id)
        with self.store.connection() as connection:
            topic_names = [str(row[0]) for row in connection.execute(
                "SELECT t.display_name FROM topic_lemmas tl JOIN topics t ON t.id=tl.topic_id "
                "WHERE tl.lemma_id=? AND t.archived=0 ORDER BY t.display_name,t.id", (lemma_id,)
            )]
        source = ""
        if context:
            source = str(context.get("title") or "")
            if context.get("source_reference"):
                source = f"{source} / {context['source_reference']}" if source else str(context["source_reference"])
        key = self._dashboard_key(profile_id, lemma_id, TEMPLATE_PURPOSE)
        logical = {
            "target": str(lemma["lemma_display"]),
            "lemma": str(lemma["lemma_display"]),
            "context": str(context.get("exact_text") or "") if context else "",
            "translation": "",
            "definition": "",
            "notes": str(lemma.get("user_notes") or ""),
            "source": source,
            "topic": ", ".join(topic_names),
            "dashboardKey": key,
        }
        return {"profileId": profile_id, "lemma": lemma, "logicalFields": logical, "context": context, "dashboardKey": key}

    @staticmethod
    def _mapped_fields(logical: dict[str, str], mapping: dict[str, str]) -> dict[str, str]:
        return {remote: logical.get(key, "") for key, remote in mapping.items() if remote}

    @staticmethod
    def _remote_fields(note: dict[str, Any], expected_names: set[str]) -> dict[str, str]:
        source = note.get("fields") if isinstance(note.get("fields"), dict) else {}
        result: dict[str, str] = {}
        for name in expected_names:
            value = source.get(name, "")
            if isinstance(value, dict):
                value = value.get("value", "")
            result[name] = str(value or "")
        return result

    def _stable_search(self, adapter: Any, projection: dict[str, Any], config: dict[str, Any]) -> list[int]:
        key_field = config["fieldMap"].get("dashboardKey")
        if key_field:
            query = f'"{_anki_query_value(key_field)}:{_anki_query_value(projection["dashboardKey"])}"'
        else:
            query = f'tag:{self._stable_tag(projection["profileId"], projection["lemma"]["id"], TEMPLATE_PURPOSE)}'
        return adapter.find_notes(query)

    def _validate_config_remote(self, adapter: Any, config: dict[str, Any]) -> None:
        if not config["deckName"] or config["deckName"] not in adapter.deck_names():
            raise LanguageValidationError("Configured Anki deck is missing", code="anki_deck_missing")
        if not config["modelName"] or config["modelName"] not in adapter.model_names():
            raise LanguageValidationError("Configured Anki model is missing", code="anki_model_missing")
        available = set(adapter.model_field_names(config["modelName"]))
        mapping = config["fieldMap"]
        if not mapping.get("target") or set(mapping.values()) - available:
            raise LanguageValidationError("Configured Anki field mapping is invalid", code="anki_field_map_invalid")

    def _note_payload(self, projection: dict[str, Any], config: dict[str, Any], fields: dict[str, str]) -> dict[str, Any]:
        return {
            "deckName": config["deckName"],
            "modelName": config["modelName"],
            "fields": fields,
            "options": {"allowDuplicate": False},
            "tags": [self._stable_tag(projection["profileId"], projection["lemma"]["id"], TEMPLATE_PURPOSE)],
        }

    def preview(self, lemma_id: str, payload: Any = None) -> dict[str, Any]:
        payload = payload or {}
        if not isinstance(payload, dict):
            raise LanguageValidationError("Anki preview payload must be an object")
        sentence_id = payload.get("sentenceId")
        projection = self._projection(lemma_id, sentence_id=sentence_id)
        config = self._config(projection["profileId"])
        adapter = self._adapter(projection["profileId"])
        capabilities = self._require_supported(projection["profileId"])
        self._validate_config_remote(adapter, config)
        fields = self._mapped_fields(projection["logicalFields"], config["fieldMap"])
        local_hash = _hash_fields(fields)
        link = self.store.get_anki_note_link(lemma_id, TEMPLATE_PURPOSE)
        note: dict[str, Any] | None = None
        stale_link = False
        match_basis = None
        if link:
            infos = adapter.notes_info([int(link["external_note_id"])])
            if infos:
                note = infos[0]
                match_basis = "LOCAL_LINK"
            else:
                stale_link = True
        if note is None:
            matches = self._stable_search(adapter, projection, config)
            if len(matches) > 1:
                raise LanguageConflictError(
                    "Multiple Anki notes share the dashboard identity", code="anki_stable_identity_conflict"
                )
            if matches:
                infos = adapter.notes_info(matches)
                note = infos[0] if infos else None
                match_basis = "STABLE_KEY"
        remote_fields: dict[str, str] = {}
        conflicts: list[dict[str, str]] = []
        conflict_state = "NONE"
        action = "CREATE"
        external_note_id = None
        can_add = None
        if note is not None:
            external_note_id = int(note.get("noteId") or note.get("id"))
            remote_fields = self._remote_fields(note, set(fields))
            remote_hash = _hash_fields(remote_fields)
            if link:
                local_changed = local_hash != link.get("last_pushed_hash")
                remote_changed = remote_hash != link.get("last_pulled_hash")
                conflict_state = (
                    "BOTH_CHANGED" if local_changed and remote_changed else
                    "LOCAL_CHANGED" if local_changed else
                    "REMOTE_CHANGED" if remote_changed else "NONE"
                )
                if conflict_state == "NONE":
                    action = "NO_CHANGE"
                elif conflict_state == "LOCAL_CHANGED":
                    action = "UPDATE"
                else:
                    action = "CONFLICT"
                previous_local = json.loads(link.get("last_local_fields_json") or "{}")
                for name in sorted(set(fields) | set(remote_fields)):
                    if fields.get(name) != remote_fields.get(name):
                        conflicts.append({
                            "field": name,
                            "lastSynced": str(previous_local.get(name, "")),
                            "dashboardProposed": fields.get(name, ""),
                            "ankiCurrent": remote_fields.get(name, ""),
                        })
                self.store.set_anki_link_conflict(
                    link["id"], state=conflict_state, local_fields=fields, remote_fields=remote_fields
                )
            else:
                action = "LINK_EXISTING"
        else:
            can_add = adapter.can_add_note(self._note_payload(projection, config, fields))
            if not can_add:
                action = "DUPLICATE_RISK"
        fingerprint = _hash_fields({
            **fields, "__action": action, "__externalNoteId": str(external_note_id or "")
        })
        return {
            "policyVersion": ANKI_SYNC_POLICY_VERSION,
            "lemmaId": lemma_id,
            "templatePurpose": TEMPLATE_PURPOSE,
            "deckName": config["deckName"], "modelName": config["modelName"],
            "logicalFields": projection["logicalFields"], "mappedFields": fields,
            "context": LanguageStore.api_value(projection["context"]),
            "dashboardKey": projection["dashboardKey"], "action": action,
            "existingNoteId": external_note_id, "matchBasis": match_basis,
            "staleLocalLink": stale_link, "canAdd": can_add,
            "conflictState": conflict_state, "conflicts": conflicts,
            "previewFingerprint": fingerprint, "capabilities": capabilities,
        }

    def commit(self, lemma_id: str, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict) or payload.get("confirm") is not True:
            raise LanguageValidationError("Anki commit requires explicit confirmation", code="anki_confirmation_required")
        preview = self.preview(lemma_id, {"sentenceId": payload.get("sentenceId")})
        if payload.get("previewFingerprint") != preview["previewFingerprint"]:
            raise LanguageConflictError("Anki preview is stale", code="anki_preview_stale")
        if preview["action"] in {"CONFLICT", "DUPLICATE_RISK"}:
            raise LanguageConflictError("Anki commit requires conflict or duplicate resolution", code="anki_commit_blocked")
        detail = self.store.get_lemma_detail(lemma_id)
        profile_id = str(detail["lemma"]["language_profile_id"])
        config = self._config(profile_id)
        adapter = self._adapter(profile_id)
        capabilities = self._require_supported(profile_id)
        run = self.store.create_anki_sync_run(profile_id, "PUSH", capabilities)
        fields = preview["mappedFields"]
        note_id = preview["existingNoteId"]
        action = preview["action"]
        warnings: list[Any] = []
        try:
            if action == "CREATE":
                note_payload = self._note_payload(self._projection(lemma_id, sentence_id=payload.get("sentenceId")), config, fields)
                try:
                    note_id = adapter.add_note(note_payload)
                except AnkiTimeoutError:
                    matches = self._stable_search(adapter, self._projection(lemma_id, sentence_id=payload.get("sentenceId")), config)
                    if len(matches) != 1:
                        raise
                    note_id = matches[0]
                    warnings.append("Creation timed out after remote success; reconciled by stable dashboard identity.")
                    action = "RECONCILED_AFTER_TIMEOUT"
            elif action == "UPDATE":
                adapter.update_note_fields(int(note_id), fields)
            elif action == "LINK_EXISTING":
                action = "LINKED_EXISTING"
            remote_info = adapter.notes_info([int(note_id)])
            remote_fields = self._remote_fields(remote_info[0], set(fields)) if remote_info else dict(fields)
            local_hash = _hash_fields(fields)
            remote_hash = _hash_fields(remote_fields)
            projection = self._projection(lemma_id, sentence_id=payload.get("sentenceId"))
            link = self.store.upsert_anki_note_link({
                "language_profile_id": profile_id, "lemma_id": lemma_id,
                "template_purpose": TEMPLATE_PURPOSE, "external_note_id": int(note_id),
                "deck_name": config["deckName"], "model_name": config["modelName"],
                "dashboard_key": projection["dashboardKey"],
                "source_document_id": projection["context"].get("text_document_id") if projection["context"] else None,
                "source_sentence_id": projection["context"].get("sentence_id") if projection["context"] else None,
                "last_pushed_hash": local_hash, "last_pulled_hash": remote_hash,
                "last_local_fields": fields, "last_remote_fields": remote_fields,
                "conflict_state": "NONE", "last_sync_at": utc_now(),
            })
            finished = self.store.finish_anki_sync_run(
                run["id"], status="COMPLETED", counts={"succeeded": 1, "failed": 0},
                warnings=warnings, errors=[], result={"action": action, "externalNoteId": int(note_id)},
            )
            return {"action": action, "link": LanguageStore.api_row(link), "run": LanguageStore.api_row(finished)}
        except Exception as exc:
            self.store.finish_anki_sync_run(
                run["id"], status="FAILED", counts={"succeeded": 0, "failed": 1}, warnings=warnings,
                errors=[{"code": getattr(exc, "code", "anki_commit_failed"), "message": str(exc)[:500]}], result={},
            )
            raise

    def link_existing(self, lemma_id: str, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise LanguageValidationError("Anki link payload must be an object")
        note_id = payload.get("externalNoteId")
        if isinstance(note_id, bool) or not isinstance(note_id, int) or note_id <= 0:
            raise LanguageValidationError("externalNoteId must be a positive integer")
        detail = self.store.get_lemma_detail(lemma_id)
        profile_id = str(detail["lemma"]["language_profile_id"])
        adapter = self._adapter(profile_id)
        notes = adapter.notes_info([note_id])
        if not notes:
            raise LanguageNotFoundError("Anki note was not found", code="anki_note_not_found")
        note = notes[0]
        preview = {
            "action": "LINK_EXISTING", "externalNoteId": note_id,
            "deckName": note.get("deckName"), "modelName": note.get("modelName"),
            "fields": sorted((note.get("fields") or {}).keys()),
            "stableIdentityChange": (
                {"field": self._config(profile_id)["fieldMap"].get("dashboardKey"), "value": self._dashboard_key(profile_id, lemma_id, TEMPLATE_PURPOSE)}
                if self._config(profile_id)["fieldMap"].get("dashboardKey")
                else {"tag": self._stable_tag(profile_id, lemma_id, TEMPLATE_PURPOSE)}
            ),
        }
        if payload.get("confirm") is not True:
            return {"preview": preview, "mutated": False}
        existing = self.store.get_anki_note_link_by_external(note_id)
        if existing and existing["lemma_id"] != lemma_id:
            raise LanguageConflictError("Anki note is already linked to another lemma", code="anki_note_already_linked")
        projection = self._projection(lemma_id, sentence_id=payload.get("sentenceId"))
        config = self._config(profile_id)
        key_field = config["fieldMap"].get("dashboardKey")
        if key_field:
            existing_value = self._remote_fields(note, {key_field}).get(key_field, "")
            if existing_value and existing_value != projection["dashboardKey"]:
                raise LanguageConflictError(
                    "Existing note has a different dashboard identity", code="anki_note_identity_conflict"
                )
            adapter.update_note_fields(note_id, {key_field: projection["dashboardKey"]})
        else:
            adapter.add_tags([note_id], [self._stable_tag(profile_id, lemma_id, TEMPLATE_PURPOSE)])
        refreshed = adapter.notes_info([note_id])
        note = refreshed[0] if refreshed else note
        fields = self._mapped_fields(projection["logicalFields"], config["fieldMap"])
        remote = self._remote_fields(note, set(fields))
        run = self.store.create_anki_sync_run(profile_id, "LINK", {})
        link = self.store.upsert_anki_note_link({
            "language_profile_id": profile_id, "lemma_id": lemma_id, "template_purpose": TEMPLATE_PURPOSE,
            "external_note_id": note_id, "deck_name": str(note.get("deckName") or config["deckName"]),
            "model_name": str(note.get("modelName") or config["modelName"]), "dashboard_key": projection["dashboardKey"],
            "source_document_id": projection["context"].get("text_document_id") if projection["context"] else None,
            "source_sentence_id": projection["context"].get("sentence_id") if projection["context"] else None,
            "last_pushed_hash": _hash_fields(fields), "last_pulled_hash": _hash_fields(remote),
            "last_local_fields": fields, "last_remote_fields": remote, "conflict_state": "NONE",
        })
        finished = self.store.finish_anki_sync_run(
            run["id"], status="COMPLETED", counts={"linked": 1}, warnings=[], errors=[], result={"externalNoteId": note_id}
        )
        return {"preview": preview, "mutated": True, "link": LanguageStore.api_row(link), "run": LanguageStore.api_row(finished)}

    def resolve_conflict(self, lemma_id: str, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict) or payload.get("resolution") not in {"DASHBOARD_WINS", "ANKI_WINS"}:
            raise LanguageValidationError("resolution must be DASHBOARD_WINS or ANKI_WINS")
        preview = self.preview(lemma_id, {"sentenceId": payload.get("sentenceId")})
        link = self.store.get_anki_note_link(lemma_id, TEMPLATE_PURPOSE)
        if not link or preview["conflictState"] not in {"REMOTE_CHANGED", "BOTH_CHANGED"}:
            raise LanguageConflictError("No resolvable Anki conflict exists", code="anki_conflict_missing")
        adapter = self._adapter(str(link["language_profile_id"]))
        remote_info = adapter.notes_info([int(link["external_note_id"])])
        if not remote_info:
            raise LanguageNotFoundError("Linked Anki note is missing", code="anki_note_not_found")
        fields = preview["mappedFields"]
        remote = self._remote_fields(remote_info[0], set(fields))
        if payload["resolution"] == "DASHBOARD_WINS":
            adapter.update_note_fields(int(link["external_note_id"]), fields)
            remote = dict(fields)
        updated = self.store.set_anki_link_conflict(
            link["id"], state="NONE", local_fields=fields, remote_fields=remote,
            local_hash=_hash_fields(fields), remote_hash=_hash_fields(remote), synced=True,
        )
        return {"resolution": payload["resolution"], "link": LanguageStore.api_row(updated)}

    def lemma_state(self, lemma_id: str) -> dict[str, Any]:
        detail = self.store.get_lemma_detail(lemma_id)
        profile_id = str(detail["lemma"]["language_profile_id"])
        linked = self.store.anki_link_detail(lemma_id, TEMPLATE_PURPOSE)
        return {
            "status": self.status(profile_id, probe=False),
            "linked": linked is not None,
            "link": LanguageStore.api_row(linked["link"]) if linked else None,
            "cards": [LanguageStore.api_row(row) for row in linked["cards"]] if linked else [],
        }

    def pull(self, profile_id: str, *, evidence_recorder: Callable[[str, dict[str, Any]], Any]) -> dict[str, Any]:
        capabilities = self._require_supported(profile_id)
        adapter = self._adapter(profile_id)
        run = self.store.create_anki_sync_run(profile_id, "PULL", capabilities)
        with self.store.connection() as connection:
            links = [dict(row) for row in connection.execute(
                "SELECT * FROM anki_note_links WHERE language_profile_id=? ORDER BY id", (profile_id,)
            )]
        errors: list[dict[str, Any]] = []
        warnings: list[str] = []
        succeeded = 0
        try:
            deck_name = self._config(profile_id)["deckName"]
            due_query = f'deck:"{_anki_query_value(deck_name)}" is:due' if deck_name else "is:due"
            due_ids = set(adapter.find_cards(due_query))
        except Exception as exc:
            self.store.finish_anki_sync_run(
                run["id"], status="FAILED", counts={"total": len(links), "succeeded": 0, "failed": len(links)},
                warnings=[], errors=[{"code": getattr(exc, "code", "anki_pull_failed"), "message": str(exc)[:500]}],
                result={},
            )
            raise
        observed_at = utc_now()
        for link in links:
            try:
                notes = adapter.notes_info([int(link["external_note_id"])])
                if not notes:
                    warnings.append(f"Linked note {link['external_note_id']} is missing.")
                    continue
                card_ids = adapter.find_cards(f"nid:{int(link['external_note_id'])}")
                cards = adapter.cards_info(card_ids) if card_ids else []
                snapshots = self.store.replace_anki_card_snapshots(
                    link["id"], int(link["external_note_id"]), cards, observed_at
                )
                for card in snapshots:
                    evidence_recorder(link["lemma_id"], {
                        "externalCardId": card["external_card_id"],
                        "externalNoteId": card["external_note_id"],
                        "reviews": card.get("reviews"), "lapses": card.get("lapses"),
                        "interval": card.get("interval"), "ease": card.get("ease"),
                        "observedAt": observed_at,
                    })
                succeeded += 1
            except Exception as exc:
                errors.append({
                    "externalNoteId": link["external_note_id"],
                    "code": getattr(exc, "code", "anki_pull_item_failed"), "message": str(exc)[:500],
                })
        status = "PARTIAL" if errors or warnings else "COMPLETED"
        if links and succeeded == 0 and errors:
            status = "FAILED"
        result = {"dueCount": len(due_ids), "observedAt": observed_at}
        finished = self.store.finish_anki_sync_run(
            run["id"], status=status,
            counts={"total": len(links), "succeeded": succeeded, "failed": len(errors), "missing": len(warnings)},
            warnings=warnings, errors=errors, result=result,
        )
        return {"run": LanguageStore.api_row(finished), **result}

    def sync_runs(self, profile_id: str, limit: int = 20) -> dict[str, Any]:
        return {"items": [LanguageStore.api_row(row) for row in self.store.list_anki_sync_runs(profile_id, limit)]}


__all__ = ["ANKI_SYNC_POLICY_VERSION", "AnkiSyncService", "CONFLICT_STATES"]
