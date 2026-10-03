"""Deterministic Phase 5 classifiers and analytics derived from canonical facts."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
import json
from typing import Any, Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .errors import LanguageValidationError


CLASSIFIER_POLICY_VERSION = "language.classifiers/v1"
STATISTICS_POLICY_VERSION = "language.statistics/v2"
TOPIC_MASTERY_POLICY_VERSION = "language.topic-mastery/v1"
GOAL_RULE_VERSION = "language.goals/v2"
DEFAULT_TIMEZONE = "Europe/Warsaw"
RECENT_DAYS = 14
UNDEREXPOSED_THRESHOLD = 3
ACTIVE_RECALL_THRESHOLD = 4
ACTIVE_PRODUCTION_THRESHOLD = 3


def _parse_datetime(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _safe_json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise LanguageValidationError("timezone is invalid", details=["timezone"]) from exc


def _as_utc(value: datetime | str | None) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = _parse_datetime(value) if value else datetime.now(timezone.utc)
    if parsed is None:
        raise LanguageValidationError("asOf is invalid", details=["asOf"])
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def classify_lemma(row: dict[str, Any], *, as_of: datetime | str | None = None) -> dict[str, Any]:
    now = _as_utc(as_of)
    status = str(row.get("knowledge_status") or row.get("knowledgeStatus") or "NEW").upper()
    disposition = str(row.get("disposition") or "TRACKED").upper()
    recognition = row.get("recognition")
    recall = row.get("recall")
    production = row.get("production")
    exposures = int(row.get("total_exposures") or row.get("totalExposures") or 0)
    tracked = disposition == "TRACKED"

    mastered = tracked and status == "MASTERED"
    active = tracked and not mastered and status == "KNOWN" and (
        (recall is not None and int(recall) >= ACTIVE_RECALL_THRESHOLD)
        or (production is not None and int(production) >= ACTIVE_PRODUCTION_THRESHOLD)
    )
    passive = tracked and status == "KNOWN" and not mastered and not active
    weak = tracked and (
        status == "LEARNING"
        or (
            status == "KNOWN"
            and any(value is not None and int(value) <= 2 for value in (recognition, recall, production))
        )
    )
    meaningful_at = _parse_datetime(
        row.get("first_advanced_at")
        or row.get("firstAdvancedAt")
        or row.get("first_seen_at")
        or row.get("firstSeenAt")
    )
    recent = tracked and meaningful_at is not None and timedelta(0) <= now - meaningful_at < timedelta(days=RECENT_DAYS)
    underexposed = tracked and status in {"LEARNING", "KNOWN"} and exposures < UNDEREXPOSED_THRESHOLD

    reasons: list[str] = []
    if weak:
        reasons.append("learning" if status == "LEARNING" else "low knowledge score")
    if recent:
        reasons.append("recently added")
    if underexposed:
        reasons.append(f"{exposures} exposure{'s' if exposures != 1 else ''}")
    return {
        "policyVersion": CLASSIFIER_POLICY_VERSION,
        "passive": passive,
        "active": active,
        "mastered": mastered,
        "weak": weak,
        "recent": recent,
        "underexposed": underexposed,
        "reasons": reasons,
    }


def week_bounds(
    as_of: datetime | str | None = None,
    *,
    timezone_name: str = DEFAULT_TIMEZONE,
    week_start: int = 1,
) -> tuple[datetime, datetime]:
    if not 1 <= int(week_start) <= 7:
        raise LanguageValidationError("weekStart must be from 1 to 7", details=["weekStart"])
    zone = _timezone(timezone_name)
    local = _as_utc(as_of).astimezone(zone)
    days_back = (local.isoweekday() - int(week_start)) % 7
    start_date = local.date() - timedelta(days=days_back)
    local_start = datetime.combine(start_date, time.min, tzinfo=zone)
    local_end = datetime.combine(start_date + timedelta(days=7), time.min, tzinfo=zone)
    return local_start.astimezone(timezone.utc), local_end.astimezone(timezone.utc)


def _range_bounds(
    range_name: str,
    as_of: datetime,
    facts: dict[str, list[dict[str, Any]]],
    zone: ZoneInfo,
) -> tuple[datetime, datetime]:
    days = {"7d": 7, "30d": 30, "90d": 90}
    end = as_of
    if range_name in days:
        local_today = end.astimezone(zone).date()
        local_start = datetime.combine(
            local_today - timedelta(days=days[range_name] - 1),
            time.min,
            tzinfo=zone,
        )
        return local_start.astimezone(timezone.utc), end
    candidates: list[datetime] = []
    for group, fields in (
        (facts.get("lemmas", []), ("created_at",)),
        (facts.get("events", []), ("created_at",)),
        (facts.get("exposures", []), ("occurred_at",)),
        (facts.get("sessions", []), ("started_at",)),
        (facts.get("progress", []), ("last_read_at", "completed_at")),
        (facts.get("listeningEvents", []), ("occurred_at",)),
        (facts.get("listeningProgress", []), ("last_listened_at", "completed_at")),
    ):
        for row in group:
            for field in fields:
                parsed = _parse_datetime(row.get(field))
                if parsed:
                    candidates.append(parsed)
    return (min(candidates) if candidates else end - timedelta(days=30)), end


def _knowledge_change(event: dict[str, Any]) -> tuple[str | None, str | None, str | None, str | None]:
    payload = _safe_json(event.get("payload_json"))
    before = payload.get("before") if isinstance(payload.get("before"), dict) else {}
    applied = payload.get("applied") if isinstance(payload.get("applied"), dict) else {}
    status = applied.get("knowledge_status")
    disposition = applied.get("disposition")
    return before.get("knowledge_status"), status, before.get("disposition"), disposition


def _date_points(start: datetime, end: datetime, zone: ZoneInfo) -> list[date]:
    first = start.astimezone(zone).date()
    last = end.astimezone(zone).date()
    return [first + timedelta(days=index) for index in range(max(0, (last - first).days) + 1)]


def _vocabulary_series(
    facts: dict[str, list[dict[str, Any]]],
    *,
    start: datetime,
    end: datetime,
    zone: ZoneInfo,
) -> list[dict[str, Any]]:
    timeline: list[tuple[datetime, int, str, dict[str, Any]]] = []
    allowed_ids = {str(row["id"]) for row in facts.get("lemmas", [])}
    for lemma in facts.get("lemmas", []):
        created = _parse_datetime(lemma.get("created_at"))
        if created:
            timeline.append((created, 0, str(lemma["id"]), {"status": "NEW", "disposition": "TRACKED"}))
    for event in facts.get("events", []):
        if str(event.get("lemma_id")) not in allowed_ids:
            continue
        occurred = _parse_datetime(event.get("created_at"))
        if not occurred:
            continue
        _, status, _, disposition = _knowledge_change(event)
        if status or disposition:
            timeline.append((occurred, 1, str(event["lemma_id"]), {"status": status, "disposition": disposition}))
    timeline.sort(key=lambda item: (item[0], item[1], item[2]))
    states: dict[str, dict[str, str]] = {}
    index = 0
    points: list[dict[str, Any]] = []
    for local_day in _date_points(start, end, zone):
        boundary = datetime.combine(local_day + timedelta(days=1), time.min, tzinfo=zone).astimezone(timezone.utc)
        while index < len(timeline) and timeline[index][0] < boundary and timeline[index][0] <= end:
            _, _, lemma_id, change = timeline[index]
            current = states.setdefault(lemma_id, {"status": "NEW", "disposition": "TRACKED"})
            if change.get("status"):
                current["status"] = str(change["status"])
            if change.get("disposition"):
                current["disposition"] = str(change["disposition"])
            index += 1
        counts = Counter(
            item["status"] for item in states.values() if item["disposition"] != "EXCLUDED"
        )
        points.append({
            "date": local_day.isoformat(),
            "learning": counts["LEARNING"],
            "known": counts["KNOWN"],
            "mastered": counts["MASTERED"],
            "knownWords": sum(1 for item in states.values()
                              if item["disposition"] == "TRACKED"
                              and item["status"] in {"KNOWN", "MASTERED"}),
            "totalTracked": sum(counts.values()),
        })
    return points


def _local_date(value: Any, zone: ZoneInfo) -> date | None:
    parsed = _parse_datetime(value)
    return parsed.astimezone(zone).date() if parsed else None


def _current_streak(qualifying: set[date], today: date) -> int:
    if not qualifying:
        return 0
    cursor = today if today in qualifying else today - timedelta(days=1)
    if cursor not in qualifying:
        return 0
    streak = 0
    while cursor in qualifying:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def _best_streak(qualifying: set[date]) -> int:
    best = current = 0
    previous = None
    for day in sorted(qualifying):
        current = current + 1 if previous and (day - previous).days == 1 else 1
        best = max(best, current)
        previous = day
    return best


def topic_mastery(topic: dict[str, Any], lemma_rows: Iterable[dict[str, Any]], *, as_of=None) -> dict[str, Any]:
    rows = list(lemma_rows)
    total_weight = sum(float(row.get("weight") or 0) for row in rows)
    weighted = 0.0
    statuses = Counter()
    classifier_counts = Counter()
    provenance = Counter()
    frequency_available = 0
    for row in rows:
        status = str(row.get("knowledge_status") or "NEW")
        statuses[status] += 1
        factor = {"NEW": 0.0, "LEARNING": 0.35, "KNOWN": 0.75, "MASTERED": 1.0}.get(status, 0.0)
        weighted += float(row.get("weight") or 0) * factor
        classified = classify_lemma(row, as_of=as_of)
        for key in ("passive", "active", "mastered"):
            if classified[key]:
                classifier_counts[key] += 1
        provenance[str(row.get("provenance") or "UNKNOWN")] += 1
        if row.get("frequency_score") is not None:
            frequency_available += 1
    return {
        "policyVersion": TOPIC_MASTERY_POLICY_VERSION,
        "topic": topic,
        "mappedLemmaCount": len(rows),
        "totalWeight": round(total_weight, 3),
        "weightedMasteryPercent": round((weighted / total_weight) * 100, 1) if total_weight else None,
        "knowledgeCounts": {
            "new": statuses["NEW"], "learning": statuses["LEARNING"],
            "known": statuses["KNOWN"], "mastered": statuses["MASTERED"],
        },
        "classifierCounts": {
            "passive": classifier_counts["passive"],
            "active": classifier_counts["active"],
            "mastered": classifier_counts["mastered"],
        },
        "denominatorQuality": {
            "scope": "USER_MAPPED_LEMMAS_ONLY",
            "mappedLemmas": len(rows),
            "frequencyAvailable": frequency_available,
            "provenance": dict(sorted(provenance.items())),
            "completeTopicDomain": False,
            "message": "Mastery covers only the lemmas explicitly mapped to this topic.",
        },
    }


class StatisticsService:
    def __init__(self, store: Any):
        self.store = store

    def classifiers(self, profile_id: str, *, as_of=None) -> list[dict[str, Any]]:
        return [
            {**self.store.api_row(row), "classifiers": classify_lemma(row, as_of=as_of)}
            for row in self.store.classifier_rows(profile_id)
        ]

    def topic_summaries(self, profile_id: str, *, include_archived: bool = False, as_of=None) -> list[dict[str, Any]]:
        result = []
        for topic in self.store.list_topics(profile_id, include_archived=include_archived):
            detail = self.store.get_topic(str(topic["id"]))
            result.append(topic_mastery(self.store.api_row(topic), detail["lemmas"], as_of=as_of))
        return result

    def calculate(
        self,
        profile_id: str,
        *,
        range_name: str = "30d",
        timezone_name: str = DEFAULT_TIMEZONE,
        as_of: datetime | str | None = None,
    ) -> dict[str, Any]:
        if range_name not in {"7d", "30d", "90d", "all"}:
            raise LanguageValidationError("range is invalid", details=["range"])
        zone = _timezone(timezone_name)
        now = _as_utc(as_of)
        facts = self.store.statistics_facts(profile_id)
        start, end = _range_bounds(range_name, now, facts, zone)
        in_range = lambda value: (parsed := _parse_datetime(value)) is not None and start <= parsed <= end

        classifiers = self.classifiers(profile_id, as_of=now)
        classifier_counts = {
            key: sum(1 for row in classifiers if row["classifiers"][key])
            for key in ("passive", "active", "mastered", "weak", "recent", "underexposed")
        }
        knowledge_counts = Counter(
            row.get("knowledgeStatus") for row in classifiers if row.get("disposition") != "EXCLUDED"
        )

        exposures = [
            row for row in facts["exposures"]
            if row.get("source_type") == "READER" and in_range(row.get("occurred_at"))
        ]
        exposure_by_day: Counter[str] = Counter()
        exposure_by_lemma: Counter[str] = Counter()
        for row in exposures:
            local_day = _local_date(row.get("occurred_at"), zone)
            count = int(row.get("occurrence_count") or 0)
            if local_day:
                exposure_by_day[local_day.isoformat()] += count
            exposure_by_lemma[str(row.get("lemma_id"))] += count

        sessions = [
            row for row in facts["sessions"]
            if row.get("session_type") == "READER" and in_range(row.get("started_at"))
        ]
        active_seconds = sum(int(row.get("active_seconds") or 0) for row in sessions)
        study_by_day: Counter[str] = Counter()
        qualifying_days: set[date] = set()
        for row in sessions:
            local_day = _local_date(row.get("started_at"), zone)
            seconds = int(row.get("active_seconds") or 0)
            if local_day and seconds > 0:
                study_by_day[local_day.isoformat()] += seconds
                qualifying_days.add(local_day)
        for row in exposures:
            local_day = _local_date(row.get("occurred_at"), zone)
            if local_day:
                qualifying_days.add(local_day)

        progress = [row for row in facts["progress"] if in_range(row.get("last_read_at"))]
        completed = [row for row in facts["progress"] if row.get("completed_at") and in_range(row.get("completed_at"))]
        coverage_history = []
        for row in completed:
            snapshot = _safe_json(row.get("coverage_snapshot_json"))
            coverage_history.append({
                "textDocumentId": row.get("text_document_id"),
                "title": row.get("title"),
                "completedAt": row.get("completed_at"),
                "tokenCoveragePercent": snapshot.get("tokenCoveragePercent"),
                "uniqueLemmaCoveragePercent": snapshot.get("uniqueLemmaCoveragePercent"),
                "policyVersion": snapshot.get("policyVersion"),
            })
            local_day = _local_date(row.get("completed_at"), zone)
            if local_day:
                qualifying_days.add(local_day)

        distribution = {"1-2": 0, "3-5": 0, "6-10": 0, "11+": 0}
        for count in exposure_by_lemma.values():
            distribution["1-2" if count <= 2 else "3-5" if count <= 5 else "6-10" if count <= 10 else "11+"] += 1

        advanced_in_range = 0
        for event in facts["events"]:
            if not in_range(event.get("created_at")):
                continue
            before_status, after_status, _, _ = _knowledge_change(event)
            if before_status == "NEW" and after_status in {"LEARNING", "KNOWN", "MASTERED"}:
                advanced_in_range += 1

        completed_tokens = sum(int(row.get("token_count") or 0) for row in completed)
        coverage_values = [
            float(row["tokenCoveragePercent"])
            for row in coverage_history
            if isinstance(row.get("tokenCoveragePercent"), (int, float))
        ]
        today = now.astimezone(zone).date()
        all_qualifying: set[date] = set()
        for row in facts["sessions"]:
            if row.get("session_type") == "READER" and int(row.get("active_seconds") or 0) > 0:
                local_day = _local_date(row.get("started_at"), zone)
                if local_day:
                    all_qualifying.add(local_day)
        for row in facts["exposures"]:
            if row.get("source_type") != "READER":
                continue
            local_day = _local_date(row.get("occurred_at"), zone)
            if local_day:
                all_qualifying.add(local_day)
        for row in facts["progress"]:
            local_day = _local_date(row.get("completed_at"), zone)
            if local_day:
                all_qualifying.add(local_day)

        topic_summaries = self.topic_summaries(profile_id, as_of=now)
        classifier_by_id = {str(row["id"]): row for row in classifiers}
        high_exposure = []
        for lemma_id, count in sorted(
            exposure_by_lemma.items(),
            key=lambda item: (-item[1], str(classifier_by_id.get(item[0], {}).get("lemmaNormalized") or ""), item[0]),
        )[:10]:
            lemma = classifier_by_id.get(lemma_id)
            if lemma:
                high_exposure.append({
                    "lemmaId": lemma_id,
                    "lemma": lemma.get("lemmaDisplay"),
                    "occurrenceCount": count,
                })
        underexposed_items = [
            {
                "lemmaId": row["id"],
                "lemma": row.get("lemmaDisplay"),
                "totalExposures": int(row.get("totalExposures") or 0),
            }
            for row in classifiers if row["classifiers"]["underexposed"]
        ][:10]
        listening_events = [
            row for row in facts.get("listeningEvents", [])
            if in_range(row.get("occurred_at"))
        ]
        listening_active_ms = sum(int(row.get("active_ms") or 0) for row in listening_events)
        listening_by_source = {}
        for source in ("BROWSER_TTS", "CLOUD_TTS", "AUTHENTIC_MEDIA"):
            source_rows = [row for row in listening_events if row.get("playback_source") == source]
            source_active_ms = sum(int(row.get("active_ms") or 0) for row in source_rows)
            listening_by_source[source] = {
                "activeMs": source_active_ms,
                "activeSeconds": round(source_active_ms / 1000, 3),
                "events": len(source_rows),
                "qualifiedEvents": sum(int(row.get("qualified") or 0) for row in source_rows),
            }
        listening_sessions = {
            str(row.get("study_session_id")) for row in listening_events
            if int(row.get("active_ms") or 0) > 0
        }
        listened_sentences = {
            (str(row.get("text_document_id")), str(row.get("sentence_id")))
            for row in listening_events if int(row.get("qualified") or 0) == 1
        }
        listening_days = {
            day for row in listening_events
            if int(row.get("active_ms") or 0) > 0
            and (day := _local_date(row.get("occurred_at"), zone)) is not None
        }
        listening_completed = [
            row for row in facts.get("listeningProgress", [])
            if row.get("completed_at") and in_range(row.get("completed_at"))
        ]
        listening_exposures = [
            row for row in facts["exposures"]
            if row.get("source_type") == "LISTENING" and in_range(row.get("occurred_at"))
        ]
        return {
            "policyVersion": STATISTICS_POLICY_VERSION,
            "classifierPolicyVersion": CLASSIFIER_POLICY_VERSION,
            "range": range_name,
            "timezone": timezone_name,
            "periodStart": start.isoformat().replace("+00:00", "Z"),
            "periodEnd": end.isoformat().replace("+00:00", "Z"),
            "vocabulary": {
                "totalTracked": sum(knowledge_counts.values()),
                "knownWords": sum(1 for row in classifiers
                                  if row.get("disposition") == "TRACKED"
                                  and row.get("knowledgeStatus") in {"KNOWN", "MASTERED"}),
                "knowledgeCounts": {
                    "new": knowledge_counts["NEW"], "learning": knowledge_counts["LEARNING"],
                    "known": knowledge_counts["KNOWN"], "mastered": knowledge_counts["MASTERED"],
                },
                "classifierCounts": classifier_counts,
                "newlyAdvanced": advanced_in_range,
                "series": _vocabulary_series(facts, start=start, end=end, zone=zone),
            },
            "exposures": {
                "totalReaderOccurrences": sum(int(row.get("occurrence_count") or 0) for row in exposures),
                "uniqueLemmas": len(exposure_by_lemma),
                "byDay": [{"date": key, "count": exposure_by_day[key]} for key in sorted(exposure_by_day)],
                "distribution": distribution,
                "highExposure": high_exposure,
                "underexposed": underexposed_items,
            },
            "reading": {
                "activeSeconds": active_seconds,
                "activeMinutes": round(active_seconds / 60, 1),
                "textsStarted": sum(1 for row in progress if row.get("status") in {"IN_PROGRESS", "COMPLETED"}),
                "textsCompleted": len(completed),
                "analyzedTokensInCompletedTexts": completed_tokens,
                "byDay": [{"date": key, "activeSeconds": study_by_day[key]} for key in sorted(study_by_day)],
                "recent": [self.store.api_row(row) for row in facts["texts"][:5]],
            },
            "listening": {
                "activeMs": listening_active_ms,
                "activeSeconds": round(listening_active_ms / 1000, 3),
                "activeMinutes": round(listening_active_ms / 60000, 1),
                "sessions": len(listening_sessions),
                "sentencesListened": len(listened_sentences),
                "textsCompleted": len(listening_completed),
                "studyDays": len(listening_days),
                "exposureOccurrences": sum(
                    int(row.get("occurrence_count") or 0) for row in listening_exposures
                ),
                "exposureEvents": len(listening_exposures),
                "byPlaybackSource": listening_by_source,
                "comprehensionClaim": "NONE",
                "definition": "Actual audible playback lifecycle only; minutes are activity, not comprehension.",
            },
            "studyTime": {
                "readingActiveSeconds": active_seconds,
                "listeningActiveSeconds": round(listening_active_ms / 1000, 3),
                "modalitySumSeconds": round(active_seconds + (listening_active_ms / 1000), 3),
                "overlapPolicy": "MODALITY_SUM_MAY_OVERLAP_IN_READ_LISTEN_MODE",
                "aggregateIsUniqueWallClock": False,
            },
            "streak": {
                "currentDays": _current_streak(all_qualifying, today),
                "bestDays": _best_streak(all_qualifying),
                "studyDaysLast7": sum(1 for day in all_qualifying if 0 <= (today - day).days < 7),
                "studyDaysLast30": sum(1 for day in all_qualifying if 0 <= (today - day).days < 30),
                "qualifyingDaysInRange": len(qualifying_days),
                "definition": "A local day with Reader active seconds, Reader exposure, or explicit text completion.",
            },
            "coverage": {
                "completedTextAveragePercent": round(sum(coverage_values) / len(coverage_values), 1) if coverage_values else None,
                "history": coverage_history,
                "historicalSnapshotsRescored": False,
            },
            "topics": topic_summaries,
            "frequencyCoverage": {
                "configured": False,
                "status": "NOT_CONFIGURED",
                "message": "wordfreq Zipf scores are available; exact lemma ranks are not configured.",
            },
        }

    def goal_progress(self, goal: dict[str, Any], *, as_of=None) -> dict[str, Any]:
        now = _as_utc(as_of)
        goal_zone = _timezone(str(goal.get("timezone") or DEFAULT_TIMEZONE))
        local_today = now.astimezone(goal_zone).date()
        active_from = date.fromisoformat(str(goal["active_from"])) if goal.get("active_from") else None
        active_until = date.fromisoformat(str(goal["active_until"])) if goal.get("active_until") else None
        within_active_dates = (
            (active_from is None or local_today >= active_from)
            and (active_until is None or local_today <= active_until)
        )
        start, end = week_bounds(
            now,
            timezone_name=str(goal.get("timezone") or DEFAULT_TIMEZONE),
            week_start=int(goal.get("week_start") or 1),
        )
        facts = self.store.statistics_facts(str(goal["language_profile_id"]))
        metric = str(goal["metric"])
        current = 0.0
        if metric == "NEW_WORDS":
            for event in facts["events"]:
                occurred = _parse_datetime(event.get("created_at"))
                before_status, after_status, _, _ = _knowledge_change(event)
                if occurred and start <= occurred < end and before_status == "NEW" and after_status in {"LEARNING", "KNOWN", "MASTERED"}:
                    current += 1
        elif metric == "ACTIVE_READING_MINUTES":
            current = sum(
                int(row.get("active_seconds") or 0) for row in facts["sessions"]
                if row.get("session_type") == "READER"
                and (occurred := _parse_datetime(row.get("started_at"))) is not None
                and start <= occurred < end
            ) / 60
        elif metric == "TEXTS_COMPLETED":
            current = sum(
                1 for row in facts["progress"]
                if (occurred := _parse_datetime(row.get("completed_at"))) is not None
                and start <= occurred < end
            )
        elif metric == "READER_EXPOSURES":
            current = sum(
                int(row.get("occurrence_count") or 0) for row in facts["exposures"]
                if row.get("source_type") == "READER"
                and (occurred := _parse_datetime(row.get("occurred_at"))) is not None
                and start <= occurred < end
            )
        elif metric == "LISTENING_ACTIVE_MINUTES":
            current = sum(
                int(row.get("active_ms") or 0) for row in facts.get("listeningEvents", [])
                if (occurred := _parse_datetime(row.get("occurred_at"))) is not None
                and start <= occurred < end
            ) / 60000
        elif metric == "LISTENING_SESSIONS":
            current = len({
                str(row.get("study_session_id")) for row in facts.get("listeningEvents", [])
                if int(row.get("active_ms") or 0) > 0
                and (occurred := _parse_datetime(row.get("occurred_at"))) is not None
                and start <= occurred < end
            })
        elif metric == "LISTENING_TEXTS_COMPLETED":
            current = sum(
                1 for row in facts.get("listeningProgress", [])
                if (occurred := _parse_datetime(row.get("completed_at"))) is not None
                and start <= occurred < end
            )
        target = float(goal["target_value"])
        return {
            "goal": self.store.api_row(goal),
            "ruleVersion": GOAL_RULE_VERSION,
            "current": round(current, 2),
            "target": target,
            "remaining": round(max(0.0, target - current), 2),
            "percentage": round(min(100.0, (current / target) * 100), 1),
            "completed": current >= target,
            "activeNow": bool(goal.get("enabled")) and within_active_dates,
            "periodStart": start.isoformat().replace("+00:00", "Z"),
            "periodEnd": end.isoformat().replace("+00:00", "Z"),
        }

    def goals(self, profile_id: str, *, as_of=None) -> list[dict[str, Any]]:
        return [self.goal_progress(goal, as_of=as_of) for goal in self.store.list_goals(profile_id)]


__all__ = [
    "ACTIVE_PRODUCTION_THRESHOLD",
    "ACTIVE_RECALL_THRESHOLD",
    "CLASSIFIER_POLICY_VERSION",
    "DEFAULT_TIMEZONE",
    "GOAL_RULE_VERSION",
    "RECENT_DAYS",
    "STATISTICS_POLICY_VERSION",
    "StatisticsService",
    "TOPIC_MASTERY_POLICY_VERSION",
    "UNDEREXPOSED_THRESHOLD",
    "classify_lemma",
    "topic_mastery",
    "week_bounds",
]
