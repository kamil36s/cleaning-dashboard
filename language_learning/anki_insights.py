"""Read-only, versioned interpretation of one Anki deck's cards and revlog."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
import html
import math
import re
from typing import Any
from zoneinfo import ZoneInfo


POLICY_VERSION = "language.anki-insights/v1"
LOCAL_TIMEZONE = ZoneInfo("Europe/Warsaw")
_SOUND = re.compile(r"\[sound:[^\]]+\]", re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")
_WORD = re.compile(r"[^\W\d_]+(?:[-'][^\W\d_]+)*", re.UNICODE)
_RATING_QUALITY = {1: 0.0, 2: 0.38, 3: 0.78, 4: 1.0}


def plain_field(value: str) -> str:
    """Only display text: never expose remote card template HTML in the dashboard."""
    text = _SOUND.sub("", str(value or ""))
    text = _TAG.sub(" ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()[:500]


def lexical_key(front: str) -> str | None:
    """Match only a simple word or a Norwegian article plus one word."""
    words = _WORD.findall(plain_field(front).casefold())
    if len(words) == 1:
        return words[0]
    if len(words) == 2 and words[0] in {"en", "ei", "et"}:
        return words[1]
    return None


def knowledge_estimate(card: dict[str, Any], reviews: list[list[int]]) -> dict[str, Any]:
    """A display estimate, separate from Anki's scheduling and manual Reader state."""
    reviews = sorted((row for row in reviews if row[3] in _RATING_QUALITY), key=lambda row: row[0])
    interval = max(0, int(card.get("interval") or 0))
    reps = max(0, int(card.get("reps") or 0))
    if reps == 0 and not reviews:
        return {"status": "NEW", "score": 0, "reviewCount": 0, "lastRating": None, "lastReviewAt": None}
    recent = reviews[-5:]
    if recent:
        weights = list(range(1, len(recent) + 1))
        quality = sum(weight * _RATING_QUALITY[row[3]] for weight, row in zip(weights, recent)) / sum(weights)
        last_rating = recent[-1][3]
        last_review_at = datetime.fromtimestamp(recent[-1][0] / 1000, tz=LOCAL_TIMEZONE).isoformat()
    else:
        quality = max(0.2, 0.75 - min(0.4, int(card.get("lapses") or 0) / max(1, reps)))
        last_rating = None
        last_review_at = None
    interval_quality = min(1.0, math.log1p(interval) / math.log1p(30))
    score = round(100 * (0.62 * quality + 0.38 * interval_quality))
    if last_rating == 1:
        score = min(score, 39)
    elif last_rating == 2:
        score = min(score, 64)
    if score >= 78 and interval >= 21 and (last_rating in {3, 4, None}):
        status = "MASTERED"
    elif score >= 55 and interval >= 7 and last_rating != 1:
        status = "KNOWN"
    else:
        status = "LEARNING"
    return {"status": status, "score": score, "reviewCount": len(reviews) or reps,
            "lastRating": last_rating, "lastReviewAt": last_review_at,
            "lastReviewId": reviews[-1][0] if reviews else None}


def _card_state(card: dict[str, Any]) -> str:
    queue = int(card.get("queue") or 0)
    if queue == -2:
        return "SUSPENDED"
    if queue in {-3, -1}:
        return "BURIED"
    if queue == 0:
        return "NEW"
    if queue in {1, 3}:
        return "LEARNING"
    return "REVIEW"


def _material_category(card: dict[str, Any]) -> str:
    queue = int(card.get("queue") or 0)
    card_type = int(card.get("type") if card.get("type") is not None else (2 if queue == 2 else 0))
    reps = int(card.get("reps") or 0)
    if queue == -2:
        return "suspended"
    if card_type == 0 and reps == 0:
        return "unseen"
    if card_type == 2 and int(card.get("interval") or 0) >= 21:
        return "mature"
    return "learningYoung"


def build_insights(
    *, deck_name: str, counts: dict[str, int], options: dict[str, Any],
    cards: list[dict[str, Any]], reviews: list[list[int]], forecast_ids: list[set[int]],
    vocabulary: dict[str, list[dict[str, Any]]], observed_at: str,
    offset: int = 0, limit: int = 50, query: str = "",
) -> dict[str, Any]:
    today = datetime.now(LOCAL_TIMEZONE).date()
    by_card: dict[int, list[list[int]]] = defaultdict(list)
    history: dict[str, dict[str, int]] = defaultdict(lambda: {
        "again": 0, "hard": 0, "good": 0, "easy": 0, "minutes": 0,
        "newIntroduced": 0, "reviewAnswers": 0, "learningAnswers": 0,
    })
    seen_cards: set[int] = set()
    for row in sorted(reviews, key=lambda entry: entry[0]):
        by_card[row[1]].append(row)
        date = datetime.fromtimestamp(row[0] / 1000, tz=LOCAL_TIMEZONE).date().isoformat()
        if row[3] in {1, 2, 3, 4}:
            if row[1] not in seen_cards:
                history[date]["newIntroduced"] += 1
                seen_cards.add(row[1])
            if row[8] in {1, 2, 3}:
                history[date]["reviewAnswers"] += 1
            else:
                history[date]["learningAnswers"] += 1
            history[date][{1: "again", 2: "hard", 3: "good", 4: "easy"}[row[3]]] += 1
            history[date]["minutes"] += max(0, row[7])
    history_items = []
    for day in range(29, -1, -1):
        date = (today - timedelta(days=day)).isoformat()
        bucket = history[date]
        history_items.append({"date": date, "again": bucket["again"], "hard": bucket["hard"],
                              "good": bucket["good"], "easy": bucket["easy"],
                              "newIntroduced": bucket["newIntroduced"],
                              "reviewAnswers": bucket["reviewAnswers"],
                              "learningAnswers": bucket["learningAnswers"],
                              "reviews": sum(bucket[key] for key in ("again", "hard", "good", "easy")),
                              "minutes": round(bucket["minutes"] / 60000, 1)})
    new_limit = max(0, int((options.get("new") or {}).get("perDay") or 0))
    review_limit = max(0, int((options.get("rev") or {}).get("perDay") or 0))
    new_remaining = sum(_card_state(card) == "NEW" for card in cards)
    forecast = []
    for day, ids in enumerate(forecast_ids, start=1):
        forecast.append({"date": (today + timedelta(days=day)).isoformat(), "dayOffset": day,
                         "scheduledReviews": len(ids),
                         "possibleNew": min(new_limit, max(0, new_remaining - (day - 1) * new_limit))})
    due_base = None
    for day, ids in enumerate(forecast_ids, start=1):
        match = next((card for card in cards if card.get("cardId") in ids and int(card.get("queue") or 0) == 2), None)
        if match is not None:
            due_base = int(match["due"]) - day
            break
    items = []
    matched = 0
    states: dict[str, int] = defaultdict(int)
    material_progress = {"mature": 0, "learningYoung": 0, "unseen": 0, "suspended": 0}
    for card in cards:
        state = _card_state(card)
        states[state] += 1
        material_progress[_material_category(card)] += 1
        fields = card.get("fields") or {}
        ordered = sorted(fields.items(), key=lambda pair: pair[1].get("order", 0))
        front = plain_field((fields.get("Front") or (ordered[0][1] if ordered else {})).get("value", ""))
        back = plain_field((fields.get("Back") or (ordered[1][1] if len(ordered) > 1 else {})).get("value", ""))
        key = lexical_key(front)
        matches = vocabulary.get(key or "", [])
        match = matches[0] if len(matches) == 1 else None
        if match:
            matched += 1
        estimate = knowledge_estimate(card, by_card.get(int(card["cardId"]), []))
        due_offset = (int(card["due"]) - due_base) if due_base is not None and state == "REVIEW" else None
        items.append({"cardId": card["cardId"], "noteId": card.get("note"),
                      "front": front, "back": back, "state": state,
                      "dueOffset": due_offset, "intervalDays": card.get("interval"),
                      "reps": card.get("reps"), "lapses": card.get("lapses"),
                      "knowledge": estimate,
                      "lemma": ({"id": match["id"], "display": match["lemma_display"],
                                  "knowledgeStatus": match["knowledge_status"],
                                  "manualOverride": bool(match["manual_status_override"])} if match else None)})
    items.sort(key=lambda item: (item["state"] != "REVIEW", item["dueOffset"] if item["dueOffset"] is not None else 99999, item["cardId"]))
    search = query.casefold().strip()
    if search:
        items = [item for item in items if search in item["front"].casefold() or search in item["back"].casefold()]
    total_filtered = len(items)
    today_history = history_items[-1]
    return {
        "policyVersion": POLICY_VERSION, "deckName": deck_name, "observedAt": observed_at,
        "today": {"new": counts["new"], "learning": counts["learn"], "reviewsDue": counts["due"],
                  "answered": today_history["reviews"], "again": today_history["again"],
                  "newIntroduced": today_history["newIntroduced"],
                  "reviewAnswers": today_history["reviewAnswers"],
                  "hard": today_history["hard"], "good": today_history["good"],
                  "easy": today_history["easy"]},
        "inventory": {"totalCards": len(cards), "newRemaining": new_remaining,
                      "matchedVocabularyCards": matched, "states": dict(states),
                      "materialProgress": material_progress},
        "limits": {"newPerDay": new_limit, "reviewsPerDay": review_limit},
        "history": history_items, "forecast": forecast,
        "cards": {"items": items[offset:offset + limit], "total": total_filtered,
                  "offset": offset, "limit": limit, "query": query},
        "forecastNote": "Review counts assume no further answers or rescheduling. Future new cards are capacity, not reserved cards.",
    }


__all__ = ["POLICY_VERSION", "build_insights", "knowledge_estimate", "lexical_key", "plain_field"]
