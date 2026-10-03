"""Evidence-driven Phase 7.6 gamification over canonical Language facts."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, time, timezone
import hashlib
import json
import math
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from .cloze import FAST_TRACK_BANDS, FAST_TRACK_VERSION
from .errors import LanguageConflictError, LanguageValidationError
from .statistics import DEFAULT_TIMEZONE, week_bounds
from .store import canonical_json, utc_now


XP_POLICY_VERSION = "language.gamification-xp/v1"
LEVEL_POLICY_VERSION = "language.gamification-levels/v1"
ACHIEVEMENT_POLICY_VERSION = "language.gamification-achievements/v1"
COLLECTION_POLICY_VERSION = "language.gamification-collections/v1"
QUEST_POLICY_VERSION = "language.gamification-quests/v1"
CAMPAIGN_POLICY_VERSION = "language.gamification-campaigns/v2"
LISTENING_XP_POLICY_VERSION = "language.gamification-listening-xp/v1"
FAST_TRACK_STATE_VERSION = "language.gamification-fast-track-state/v1"
COLLECTION_TIER_VERSION = "language.gamification-collection-tiers/v1"

XP_VALUES = {
    "READER_ACTIVE_MINUTE": 2,
    "READER_TEXT_COMPLETED": 20,
    "READER_EXPOSURE_EVENT": 1,
    "CLOZE_CORRECT": 5,
    "CLOZE_INCORRECT": 2,
    "CLOZE_RECOVERY_BONUS": 3,
    "WEEKLY_GOAL_COMPLETED": 15,
    "DAILY_QUEST_COMPLETED": 5,
    "LISTENING_ACTIVE_MINUTE": 2,
}

READER_MINUTES_PER_SESSION_CAP = 30
READER_EXPOSURE_EVENTS_PER_DAY_CAP = 20
CLOZE_SCORED_ATTEMPTS_PER_TARGET_DAY_CAP = 3
CLOZE_RECOVERY_BONUSES_PER_TARGET_DAY_CAP = 1
LISTENING_ACTIVE_MINUTES_PER_DAY_CAP = 20


def _as_utc(value: datetime | str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _local_date(value: Any, zone: ZoneInfo) -> date | None:
    if not value:
        return None
    try:
        return _as_utc(str(value)).astimezone(zone).date()
    except (TypeError, ValueError):
        return None


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def level_floor(level: int) -> int:
    """Cumulative XP floor: 25 * (level - 1) * level."""
    safe = max(1, int(level))
    return 25 * (safe - 1) * safe


def level_from_xp(lifetime_xp: int) -> dict[str, Any]:
    xp = max(0, int(lifetime_xp))
    level = max(1, int((math.sqrt(1 + (4 * xp / 25)) - 1) // 2) + 1)
    while level_floor(level + 1) <= xp:
        level += 1
    while level > 1 and level_floor(level) > xp:
        level -= 1
    floor = level_floor(level)
    next_floor = level_floor(level + 1)
    into = xp - floor
    needed = next_floor - xp
    width = next_floor - floor
    return {
        "label": f"Norwegian Level {level}",
        "level": level,
        "lifetimeXp": xp,
        "currentLevelXpFloor": floor,
        "nextLevelXp": next_floor,
        "xpIntoLevel": into,
        "xpNeeded": needed,
        "progressPercent": round(into * 100 / width, 1) if width else 100.0,
        "ruleVersion": LEVEL_POLICY_VERSION,
        "proficiencyClaim": "NONE",
    }


ACHIEVEMENT_DEFINITIONS = (
    ("FIRST_STUDY", "SPECIAL", "First real study", "Record the first qualifying Reader or Cloze activity.", 1),
    ("READER_FIRST_COMPLETION", "READER", "First Reader completion", "Explicitly complete one Reader text.", 1),
    ("READER_5_COMPLETIONS", "READER", "Five Reader completions", "Explicitly complete five Reader texts.", 5),
    ("READER_100_EXPOSURES", "READER", "100 Reader exposures", "Record 100 canonical Reader exposure occurrences.", 100),
    ("READER_1000_EXPOSURES", "READER", "1,000 Reader exposures", "Record 1,000 canonical Reader exposure occurrences.", 1000),
    ("CLOZE_FIRST_SESSION", "CLOZE", "First Cloze session", "Complete one dashboard Cloze session.", 1),
    ("CLOZE_100_ATTEMPTS", "CLOZE", "100 Cloze answers", "Record 100 explicit Cloze outcomes.", 100),
    ("CLOZE_500_ATTEMPTS", "CLOZE", "500 Cloze answers", "Record 500 explicit Cloze outcomes.", 500),
    ("CLOZE_FIRST_RECOVERY", "CLOZE", "First Cloze recovery", "Answer correctly after an earlier incorrect or revealed attempt for the same target.", 1),
    ("VOCABULARY_100_TRACKED", "VOCABULARY", "100 tracked lemmas", "Track 100 non-excluded vocabulary lemmas.", 100),
    ("VOCABULARY_500_TRACKED", "VOCABULARY", "500 tracked lemmas", "Track 500 non-excluded vocabulary lemmas.", 500),
    ("FAST_TRACK_1_RELIABLE_25", "FAST_TRACK", "Fast Track 1 · 25 reliable", "Reach the Reliable threshold for 25 playable Fast Track 1 targets.", 25),
    ("CONSISTENCY_7_DAYS", "CONSISTENCY", "Seven study days", "Record qualifying activity on seven distinct canonical study days.", 7),
    ("CONSISTENCY_30_DAYS", "CONSISTENCY", "Thirty study days", "Record qualifying activity on thirty distinct canonical study days.", 30),
    ("ANKI_FIRST_LINK", "ANKI", "First Anki link", "Create one stable Language-to-Anki note link.", 1),
    ("GENERATED_FIRST_STUDIED", "GENERATED_READING", "Generated text studied", "Begin real Reader study of one accepted generated text.", 1),
    ("GOAL_FIRST_COMPLETION", "GOALS", "First weekly goal completed", "Reach one supported weekly Goal from canonical activity.", 1),
)


def _threshold_time(rows: Iterable[dict[str, Any]], threshold: int, count_key: str | None, time_key: str) -> str | None:
    total = 0
    for row in rows:
        total += int(row.get(count_key) or 0) if count_key else 1
        if total >= threshold:
            return str(row.get(time_key) or utc_now())
    return None


def _qualifying_reader_dates(facts: dict[str, Any], zone: ZoneInfo) -> dict[date, str]:
    evidence: dict[date, str] = {}
    candidates: list[tuple[str, date]] = []
    for row in facts["sessions"]:
        if row.get("session_type") == "READER" and int(row.get("active_seconds") or 0) > 0:
            if day := _local_date(row.get("started_at"), zone):
                candidates.append((str(row.get("started_at")), day))
    for row in facts["exposures"]:
        if row.get("source_type") == "READER" and (day := _local_date(row.get("occurred_at"), zone)):
            candidates.append((str(row.get("occurred_at")), day))
    for row in facts["progress"]:
        if row.get("completed_at") and (day := _local_date(row.get("completed_at"), zone)):
            candidates.append((str(row.get("completed_at")), day))
    for timestamp, day in sorted(candidates):
        evidence.setdefault(day, timestamp)
    return evidence


class GamificationService:
    """Derived reward overlay. It never writes canonical learning tables."""

    def __init__(self, store: Any, statistics: Any, *, cloze_service: Any | None = None,
                 curriculum_service: Any | None = None):
        self.store = store
        self.statistics = statistics
        self.cloze_service = cloze_service
        self.curriculum_service = curriculum_service

    def attach_cloze_service(self, service: Any) -> None:
        self.cloze_service = service

    def attach_curriculum_service(self, service: Any) -> None:
        self.curriculum_service = service

    @staticmethod
    def _award(store: Any, profile_id: str, *, source_type: str, source_id: str,
               reward_key: str, amount: int, awarded_at: str, metadata: dict[str, Any] | None = None,
               rule_version: str = XP_POLICY_VERSION) -> bool:
        _, created = store.record_gamification_award({
            "language_profile_id": profile_id,
            "source_type": source_type,
            "source_id": source_id,
            "reward_key": reward_key,
            "rule_version": rule_version,
            "xp_amount": amount,
            "awarded_at": awarded_at,
            "metadata": metadata or {},
        })
        return created

    def reconcile_profile(self, profile_id: str, *, as_of: Any = None) -> dict[str, Any]:
        """Idempotently backfill/reconcile all currently supported canonical evidence."""
        now = _as_utc(as_of)
        zone = ZoneInfo(DEFAULT_TIMEZONE)
        facts = self.store.gamification_facts(profile_id)
        created = Counter()
        awarded_xp = 0

        def award(**values: Any) -> None:
            nonlocal awarded_xp
            amount = int(values.pop("amount"))
            if self._award(self.store, profile_id, amount=amount, **values):
                created[str(values["reward_key"])] += 1
                awarded_xp += amount

        for session in facts["sessions"]:
            if session.get("session_type") != "READER":
                continue
            minutes = min(READER_MINUTES_PER_SESSION_CAP, int(session.get("active_seconds") or 0) // 60)
            for minute in range(1, minutes + 1):
                award(
                    source_type="STUDY_SESSION", source_id=str(session["id"]),
                    reward_key=f"reader.active-minute.{minute}", amount=XP_VALUES["READER_ACTIVE_MINUTE"],
                    awarded_at=str(session.get("ended_at") or session.get("started_at") or utc_now()),
                    metadata={"minuteOrdinal": minute, "sessionMinuteCap": READER_MINUTES_PER_SESSION_CAP},
                )

        for progress in facts["progress"]:
            if not progress.get("completed_at"):
                continue
            award(
                source_type="TEXT_COMPLETION", source_id=str(progress["text_document_id"]),
                reward_key="reader.text-completed", amount=XP_VALUES["READER_TEXT_COMPLETED"],
                awarded_at=str(progress["completed_at"]), metadata={"sourceType": progress.get("source_type")},
            )

        exposures_by_day: dict[date, list[dict[str, Any]]] = defaultdict(list)
        for exposure in facts["exposures"]:
            if exposure.get("source_type") == "READER":
                day = _local_date(exposure.get("occurred_at"), zone)
                if day:
                    exposures_by_day[day].append(exposure)
        for day, rows in exposures_by_day.items():
            for exposure in rows[:READER_EXPOSURE_EVENTS_PER_DAY_CAP]:
                award(
                    source_type="EXPOSURE_EVENT", source_id=str(exposure["id"]),
                    reward_key="reader.exposure-event", amount=XP_VALUES["READER_EXPOSURE_EVENT"],
                    awarded_at=str(exposure["occurred_at"]),
                    metadata={"localStudyDate": day.isoformat(), "dailyEventCap": READER_EXPOSURE_EVENTS_PER_DAY_CAP},
                )

        listening_by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for event in facts.get("listeningEvents", []):
            day = str(event.get("local_study_date") or "")
            if day and int(event.get("active_ms") or 0) > 0:
                listening_by_day[day].append(event)
        for day, rows in listening_by_day.items():
            complete_minutes = min(
                LISTENING_ACTIVE_MINUTES_PER_DAY_CAP,
                sum(int(row.get("active_ms") or 0) for row in rows) // 60_000,
            )
            awarded_at = str(rows[-1].get("occurred_at") or utc_now())
            for minute in range(1, complete_minutes + 1):
                award(
                    source_type="LISTENING_DAY",
                    source_id=f"{day}:{minute}",
                    reward_key="listening.active-minute",
                    amount=XP_VALUES["LISTENING_ACTIVE_MINUTE"],
                    awarded_at=awarded_at,
                    metadata={
                        "localStudyDate": day,
                        "minuteOrdinal": minute,
                        "dailyMinuteCap": LISTENING_ACTIVE_MINUTES_PER_DAY_CAP,
                        "canonicalSource": "LISTENING_SENTENCE_EVENTS",
                    },
                    rule_version=LISTENING_XP_POLICY_VERSION,
                )

        prior_negative: set[str] = set()
        cloze_daily: Counter[tuple[str, str]] = Counter()
        recovery_daily: Counter[tuple[str, str]] = Counter()
        for attempt in facts["attempts"]:
            target = str(attempt["reference_target_stable_key"])
            outcome = str(attempt["outcome"])
            day = _local_date(attempt.get("attempted_at"), zone)
            day_key = day.isoformat() if day else "unknown"
            if outcome in {"INCORRECT", "REVEALED"}:
                prior_negative.add(target)
            if outcome not in {"CORRECT", "INCORRECT"}:
                continue
            cap_key = (target, day_key)
            if cloze_daily[cap_key] >= CLOZE_SCORED_ATTEMPTS_PER_TARGET_DAY_CAP:
                continue
            cloze_daily[cap_key] += 1
            reward = "CLOZE_CORRECT" if outcome == "CORRECT" else "CLOZE_INCORRECT"
            award(
                source_type="CLOZE_ATTEMPT", source_id=str(attempt["id"]),
                reward_key=reward.lower().replace("_", "."), amount=XP_VALUES[reward],
                awarded_at=str(attempt["attempted_at"]),
                metadata={"outcome": outcome, "target": target, "localStudyDate": day_key,
                          "perTargetDailyCap": CLOZE_SCORED_ATTEMPTS_PER_TARGET_DAY_CAP},
            )
            if outcome == "CORRECT" and target in prior_negative and recovery_daily[cap_key] < CLOZE_RECOVERY_BONUSES_PER_TARGET_DAY_CAP:
                recovery_daily[cap_key] += 1
                award(
                    source_type="CLOZE_ATTEMPT", source_id=str(attempt["id"]),
                    reward_key="cloze.recovery-bonus", amount=XP_VALUES["CLOZE_RECOVERY_BONUS"],
                    awarded_at=str(attempt["attempted_at"]),
                    metadata={"target": target, "localStudyDate": day_key,
                              "perTargetDailyCap": CLOZE_RECOVERY_BONUSES_PER_TARGET_DAY_CAP},
                )

        for goal in self.statistics.goals(profile_id, as_of=now):
            if goal["completed"] and goal["activeNow"]:
                source_id = f"{goal['goal']['id']}:{goal['periodStart']}"
                award(
                    source_type="WEEKLY_GOAL", source_id=source_id,
                    reward_key="goal.week-completed", amount=XP_VALUES["WEEKLY_GOAL_COMPLETED"],
                    awarded_at=_utc_text(now),
                    metadata={"goalId": goal["goal"]["id"], "periodStart": goal["periodStart"],
                              "goalRuleVersion": goal["ruleVersion"]},
                )

        for snapshot in self.store.list_quest_snapshots(profile_id, limit=400):
            for quest in self._quest_progress(profile_id, snapshot)["items"]:
                if quest["completed"]:
                    award(
                        source_type="DAILY_QUEST", source_id=f"{snapshot['id']}:{quest['key']}",
                        reward_key="quest.completed", amount=XP_VALUES["DAILY_QUEST_COMPLETED"],
                        awarded_at=_utc_text(now),
                        metadata={"localStudyDate": snapshot["localStudyDate"], "questKey": quest["key"]},
                    )

        achievements = self.achievements(profile_id, as_of=now, facts=facts, unlock=True)
        return {
            "ruleVersion": XP_POLICY_VERSION,
            "listeningRuleVersion": LISTENING_XP_POLICY_VERSION,
            "profileId": profile_id,
            "sourceAwardsCreated": dict(created),
            "awardsCreated": sum(created.values()),
            "xpAwarded": awarded_xp,
            "lifetimeXp": self.store.gamification_ledger(profile_id, recent_limit=0)["lifetimeXp"],
            "achievementsUnlocked": achievements["newlyUnlocked"],
            "canonicalMutation": "NONE",
        }

    def level(self, profile_id: str) -> dict[str, Any]:
        return level_from_xp(self.store.gamification_ledger(profile_id, recent_limit=0)["lifetimeXp"])

    @staticmethod
    def _recovery_attempts(attempts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        failed: set[str] = set()
        recovered: list[dict[str, Any]] = []
        for row in attempts:
            target = str(row["reference_target_stable_key"])
            if row["outcome"] in {"INCORRECT", "REVEALED"}:
                failed.add(target)
            elif row["outcome"] == "CORRECT" and target in failed:
                recovered.append(row)
                failed.remove(target)
        return recovered

    @staticmethod
    def _fast_track_states(attempts: list[dict[str, Any]], zone: ZoneInfo) -> dict[str, dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in attempts:
            grouped[str(row["reference_target_stable_key"])].append(row)
        result = {}
        for key, rows in grouped.items():
            rows = sorted(rows, key=lambda row: str(row.get("attempted_at") or ""))
            correct = [row for row in rows if row["outcome"] == "CORRECT"]
            correct_days = {_local_date(row.get("attempted_at"), zone) for row in correct}
            correct_days.discard(None)
            state = "ENCOUNTERED"
            reliable_at = None
            if correct:
                state = "PRACTICED"
            if len(correct) >= 3 and len(correct_days) >= 2:
                state = "RELIABLE"
                observed_days: set[date] = set()
                observed_correct = 0
                for row in correct:
                    observed_correct += 1
                    if day := _local_date(row.get("attempted_at"), zone):
                        observed_days.add(day)
                    if observed_correct >= 3 and len(observed_days) >= 2:
                        reliable_at = row.get("attempted_at")
                        break
            result[key] = {
                "state": state, "attempts": len(rows), "correct": len(correct),
                "correctStudyDays": len(correct_days),
                "lastAttemptedAt": rows[-1].get("attempted_at"),
                "reliableAt": reliable_at,
            }
        return result

    def _achievement_metrics(self, profile_id: str, facts: dict[str, Any], *, as_of: Any = None) -> dict[str, dict[str, Any]]:
        zone = ZoneInfo(DEFAULT_TIMEZONE)
        attempts = facts["attempts"]
        recoveries = self._recovery_attempts(attempts)
        reader_progress = [row for row in facts["progress"] if row.get("completed_at")]
        reader_exposures = [row for row in facts["exposures"] if row.get("source_type") == "READER"]
        tracked = [row for row in facts["lemmas"] if row.get("disposition") != "EXCLUDED"]
        dates = _qualifying_reader_dates(facts, zone)
        first_events = []
        first_events.extend(
            {"at": row.get("started_at")} for row in facts["sessions"]
            if row.get("session_type") == "READER" and int(row.get("active_seconds") or 0) > 0
        )
        first_events.extend({"at": row.get("occurred_at")} for row in reader_exposures)
        first_events.extend({"at": row.get("attempted_at")} for row in attempts)
        generated_text_ids = {
            str(row["text_document_id"]) for row in facts["progress"]
            if row.get("source_type") == "GENERATED_MANUAL_LLM" and row.get("status") in {"IN_PROGRESS", "COMPLETED"}
        }
        reliable = self._fast_track_states(attempts, zone)
        track1_keys: set[str] = set()
        if self.cloze_service is not None:
            try:
                track1_keys = {
                    str(row["stable_key"]) for row in self.cloze_service.reference.playable_targets(*FAST_TRACK_BANDS["FAST_TRACK_1"])
                }
            except Exception:
                track1_keys = set()
        reliable_track1 = [value for key, value in reliable.items() if key in track1_keys and value["state"] == "RELIABLE"]
        completed_goals = [item for item in self.statistics.goals(profile_id, as_of=as_of) if item["completed"] and item["activeNow"]]
        metrics = {
            "FIRST_STUDY": (len(first_events), min((str(row["at"]) for row in first_events if row.get("at")), default=None)),
            "READER_FIRST_COMPLETION": (len(reader_progress), _threshold_time(reader_progress, 1, None, "completed_at")),
            "READER_5_COMPLETIONS": (len(reader_progress), _threshold_time(reader_progress, 5, None, "completed_at")),
            "READER_100_EXPOSURES": (sum(int(row.get("occurrence_count") or 0) for row in reader_exposures), _threshold_time(reader_exposures, 100, "occurrence_count", "occurred_at")),
            "READER_1000_EXPOSURES": (sum(int(row.get("occurrence_count") or 0) for row in reader_exposures), _threshold_time(reader_exposures, 1000, "occurrence_count", "occurred_at")),
            "CLOZE_FIRST_SESSION": (len(facts["completedClozeSessions"]), _threshold_time(facts["completedClozeSessions"], 1, None, "completed_at")),
            "CLOZE_100_ATTEMPTS": (len(attempts), _threshold_time(attempts, 100, None, "attempted_at")),
            "CLOZE_500_ATTEMPTS": (len(attempts), _threshold_time(attempts, 500, None, "attempted_at")),
            "CLOZE_FIRST_RECOVERY": (len(recoveries), _threshold_time(recoveries, 1, None, "attempted_at")),
            "VOCABULARY_100_TRACKED": (len(tracked), _threshold_time(tracked, 100, None, "created_at")),
            "VOCABULARY_500_TRACKED": (len(tracked), _threshold_time(tracked, 500, None, "created_at")),
            "FAST_TRACK_1_RELIABLE_25": (
                len(reliable_track1),
                _threshold_time(
                    sorted(reliable_track1, key=lambda row: str(row.get("reliableAt") or "")),
                    25,
                    None,
                    "reliableAt",
                ),
            ),
            "CONSISTENCY_7_DAYS": (len(dates), list(dates.values())[6] if len(dates) >= 7 else None),
            "CONSISTENCY_30_DAYS": (len(dates), list(dates.values())[29] if len(dates) >= 30 else None),
            "ANKI_FIRST_LINK": (len(facts["ankiLinks"]), _threshold_time(facts["ankiLinks"], 1, None, "created_at")),
            "GENERATED_FIRST_STUDIED": (len(generated_text_ids), min((str(row.get("last_read_at")) for row in facts["progress"] if str(row.get("text_document_id")) in generated_text_ids and row.get("last_read_at")), default=None)),
            "GOAL_FIRST_COMPLETION": (len(completed_goals), _utc_text(_as_utc(as_of)) if completed_goals else None),
        }
        return {key: {"current": current, "earnedAt": earned_at} for key, (current, earned_at) in metrics.items()}

    def achievements(self, profile_id: str, *, as_of: Any = None, facts: dict[str, Any] | None = None,
                     unlock: bool = False) -> dict[str, Any]:
        facts = facts or self.store.gamification_facts(profile_id)
        metrics = self._achievement_metrics(profile_id, facts, as_of=as_of)
        existing = self.store.achievement_unlocks(profile_id)
        unlock_by_key = {row["achievementKey"]: row for row in existing}
        newly_unlocked = 0
        items = []
        for key, category, name, description, target in ACHIEVEMENT_DEFINITIONS:
            metric = metrics[key]
            current = int(metric["current"])
            reached = current >= target
            if unlock and reached and key not in unlock_by_key:
                row, created = self.store.unlock_achievement({
                    "language_profile_id": profile_id, "achievement_key": key,
                    "definition_version": ACHIEVEMENT_POLICY_VERSION,
                    "unlocked_at": metric["earnedAt"] or _utc_text(_as_utc(as_of)),
                    "snapshot": {"current": current, "target": target, "policyVersion": ACHIEVEMENT_POLICY_VERSION},
                })
                if created:
                    newly_unlocked += 1
                unlock_by_key[key] = self.store.api_row(row)
            unlocked = unlock_by_key.get(key)
            items.append({
                "key": key, "category": category, "name": name, "description": description,
                "current": min(current, target), "rawCurrent": current, "target": target,
                "progressPercent": round(min(100, current * 100 / target), 1),
                "state": "UNLOCKED" if unlocked else "LOCKED",
                "unlockedAt": unlocked.get("unlockedAt") if unlocked else None,
                "definitionVersion": ACHIEVEMENT_POLICY_VERSION,
            })
        unlocked_count = sum(1 for item in items if item["state"] == "UNLOCKED")
        recent = sorted((item for item in items if item["unlockedAt"]), key=lambda item: item["unlockedAt"], reverse=True)[:5]
        return {
            "policyVersion": ACHIEVEMENT_POLICY_VERSION,
            "visibleTotal": len(items), "unlockedCount": unlocked_count,
            "completionLabel": f"{unlocked_count} / {len(items)} achievements",
            "items": items, "recentUnlocks": recent, "newlyUnlocked": newly_unlocked,
            "secretAchievements": 0,
        }

    @staticmethod
    def _tier(progress: float) -> str:
        if progress >= 100:
            return "COMPLETE"
        if progress >= 75:
            return "GOLD"
        if progress >= 50:
            return "SILVER"
        if progress >= 25:
            return "BRONZE"
        return "NONE"

    def collections(self, profile_id: str, *, facts: dict[str, Any] | None = None) -> dict[str, Any]:
        facts = facts or self.store.gamification_facts(profile_id)
        attempts = facts["attempts"]
        states = self._fast_track_states(attempts, ZoneInfo(DEFAULT_TIMEZONE))
        items = []
        ranked_all: list[dict[str, Any]] = []
        playable_ids: set[str] = set()
        reference_available = False
        if self.cloze_service is not None:
            try:
                ranked_all = self.cloze_service.reference.targets()
                playable_ids = self.cloze_service.reference.playable_target_ids()
                reference_available = True
            except Exception:
                pass
        for key, bounds in FAST_TRACK_BANDS.items():
            ranked = [row for row in ranked_all if bounds[0] <= int(row["rank"]) <= bounds[1]]
            playable_keys = {str(row["stable_key"]) for row in ranked if str(row["id"]) in playable_ids}
            status = "AVAILABLE" if reference_available else "REFERENCE_UNAVAILABLE"
            state_counts = Counter(
                states[target]["state"] if target in states else "UNSEEN" for target in playable_keys
            )
            reliable = state_counts["RELIABLE"]
            total = len(playable_keys)
            percent = round(reliable * 100 / total, 1) if total else 0.0
            items.append({
                "collectionKey": key, "name": key.replace("FAST_TRACK_", "Fast Track "),
                "kind": "FAST_TRACK", "status": status,
                "collectionVersion": COLLECTION_POLICY_VERSION,
                "denominatorSource": "KELLY SOURCE_LEARNER_RANK intersected with Phase 9A translated/playable targets",
                "denominatorVersion": FAST_TRACK_VERSION,
                "totalEligible": total, "mapped": total,
                "unresolved": max(0, len(ranked) - total), "excluded": 0,
                "completed": reliable, "progressPercent": percent,
                "stateCounts": {name: state_counts[name] for name in ("UNSEEN", "ENCOUNTERED", "PRACTICED", "RELIABLE")},
                "completionStateRule": "RELIABLE requires at least 3 CORRECT attempts across at least 2 Europe/Warsaw study dates; Reveal/Skip never count as correct.",
                "completionRuleVersion": FAST_TRACK_STATE_VERSION,
                "tier": self._tier(percent), "tierVersion": COLLECTION_TIER_VERSION,
                "allRankedTargets": len(ranked), "playableEligibleTargets": total,
            })

        completed_texts = sum(1 for row in facts["progress"] if row.get("completed_at"))
        cloze_attempts = len(attempts)
        for key, name, current, target, source in (
            ("READER_10_TEXTS", "Reader · 10 completed texts", completed_texts, 10, "Canonical explicit Reader completions"),
            ("CLOZE_1000_ATTEMPTS", "Cloze · 1,000 answers", cloze_attempts, 1000, "Canonical Cloze attempts"),
        ):
            progress = round(min(100, current * 100 / target), 1)
            items.append({
                "collectionKey": key, "name": name, "kind": "MILESTONE", "status": "AVAILABLE",
                "collectionVersion": COLLECTION_POLICY_VERSION, "denominatorSource": source,
                "denominatorVersion": COLLECTION_POLICY_VERSION, "totalEligible": target, "mapped": target,
                "unresolved": 0, "excluded": 0, "completed": min(current, target),
                "rawCompleted": current, "progressPercent": progress,
                "completionRuleVersion": COLLECTION_POLICY_VERSION,
                "tier": self._tier(progress), "tierVersion": COLLECTION_TIER_VERSION,
            })

        topics: dict[str, dict[str, Any]] = {}
        for row in facts["topics"]:
            topic = topics.setdefault(str(row["id"]), {
                "name": row["display_name"], "archived": bool(row["archived"]), "rows": [],
            })
            if row.get("lemma_id"):
                topic["rows"].append(row)
        for topic_id, topic in topics.items():
            mapped = len(topic["rows"])
            completed = sum(
                1 for row in topic["rows"]
                if row.get("disposition") != "EXCLUDED" and row.get("knowledge_status") in {"KNOWN", "MASTERED"}
            )
            percent = round(completed * 100 / mapped, 1) if mapped else 0.0
            items.append({
                "collectionKey": f"TOPIC:{topic_id}", "name": f"Topic · {topic['name']}",
                "kind": "USER_TOPIC", "status": "ARCHIVED" if topic["archived"] else "AVAILABLE",
                "collectionVersion": COLLECTION_POLICY_VERSION,
                "denominatorSource": "USER_MAPPED_LEMMAS_ONLY", "denominatorVersion": "language.topic-mastery/v1",
                "totalEligible": mapped, "mapped": mapped, "unresolved": 0, "excluded": 0,
                "completed": completed, "progressPercent": percent,
                "completionRuleVersion": COLLECTION_POLICY_VERSION,
                "tier": self._tier(percent), "tierVersion": COLLECTION_TIER_VERSION,
                "completeTopicDomain": False,
            })
        if self.curriculum_service is not None:
            for curriculum in self.curriculum_service.collection_summaries(profile_id):
                progress = float(curriculum.get("progressPercent") or 0)
                items.append({
                    **curriculum,
                    "tier": self._tier(progress),
                    "tierVersion": COLLECTION_TIER_VERSION,
                })
        return {
            "policyVersion": COLLECTION_POLICY_VERSION,
            "fastTrackStateVersion": FAST_TRACK_STATE_VERSION,
            "tierVersion": COLLECTION_TIER_VERSION,
            "items": items,
            "idiomMweBoundary": "No phrase mastery or whole-database completion is claimed; Phase 7.5C expression detection remains annotation-only.",
        }

    def _quest_candidates(self, profile_id: str, *, as_of: Any) -> list[dict[str, Any]]:
        facts = self.store.gamification_facts(profile_id)
        goals = [item for item in self.statistics.goals(profile_id, as_of=as_of) if item["activeNow"] and not item["completed"]]
        unfinished = any(row.get("status") == "IN_PROGRESS" for row in facts["progress"])
        mistakes = int(self.store.cloze_summary(profile_id).get("mistakeTargets") or 0)
        candidates = []
        if mistakes:
            candidates.append({"key": "CLOZE_ATTEMPTS", "title": "Answer 10 Cloze questions", "target": 10, "unit": "answers", "href": "#cloze", "reason": "Real Cloze mistakes are available."})
        if unfinished:
            candidates.append({"key": "READER_TEXTS_COMPLETED", "title": "Complete one Reader text", "target": 1, "unit": "text", "href": "#reader", "reason": "An unfinished Reader text exists."})
        for goal in goals:
            metric = goal["goal"]["metric"]
            mapping = {
                "ACTIVE_READING_MINUTES": ("READER_ACTIVE_MINUTES", "Read actively for 10 minutes", 10, "minutes", "#reader"),
                "TEXTS_COMPLETED": ("READER_TEXTS_COMPLETED", "Complete one Reader text", 1, "text", "#reader"),
                "READER_EXPOSURES": ("READER_EXPOSURES", "Record 5 Reader exposure events", 5, "events", "#reader"),
            }
            if metric in mapping:
                key, title, target, unit, href = mapping[metric]
                candidates.append({"key": key, "title": title, "target": target, "unit": unit, "href": href, "reason": "Selected from the largest supported weekly Goal gap."})
                break
        candidates.extend([
            {"key": "READER_ACTIVE_MINUTES", "title": "Read actively for 10 minutes", "target": 10, "unit": "minutes", "href": "#reader", "reason": "Bounded canonical Reader activity."},
            {"key": "CLOZE_ATTEMPTS", "title": "Answer 10 Cloze questions", "target": 10, "unit": "answers", "href": "#cloze", "reason": "Bounded canonical Cloze practice."},
            {"key": "READER_EXPOSURES", "title": "Record 5 Reader exposure events", "target": 5, "unit": "events", "href": "#reader", "reason": "Canonical Reader exposure evidence."},
        ])
        deduplicated = []
        seen = set()
        for item in candidates:
            if item["key"] not in seen:
                seen.add(item["key"])
                deduplicated.append(item)
        return deduplicated[:3]

    def quests(self, profile_id: str, *, as_of: Any = None) -> dict[str, Any]:
        now = _as_utc(as_of)
        zone = ZoneInfo(DEFAULT_TIMEZONE)
        local_day = now.astimezone(zone).date().isoformat()
        snapshot = self.store.get_quest_snapshot(profile_id, local_day, QUEST_POLICY_VERSION)
        if snapshot is None:
            items = self._quest_candidates(profile_id, as_of=now)
            fingerprint = "sha256:" + hashlib.sha256(canonical_json({"date": local_day, "items": items}).encode("utf-8")).hexdigest()
            snapshot, _ = self.store.create_quest_snapshot({
                "language_profile_id": profile_id, "local_study_date": local_day,
                "timezone": DEFAULT_TIMEZONE, "rule_version": QUEST_POLICY_VERSION,
                "canonical_fingerprint": fingerprint, "quests": items,
            })
        return self._quest_progress(profile_id, snapshot)

    def _quest_progress(self, profile_id: str, snapshot: dict[str, Any]) -> dict[str, Any]:
        zone = ZoneInfo(str(snapshot["timezone"]))
        local_day = date.fromisoformat(str(snapshot["localStudyDate"]))
        start = datetime.combine(local_day, time.min, tzinfo=zone).astimezone(timezone.utc)
        end = datetime.combine(local_day.fromordinal(local_day.toordinal() + 1), time.min, tzinfo=zone).astimezone(timezone.utc)
        activity = self.store.gamification_activity_window(profile_id, _utc_text(start), _utc_text(end))
        values = {
            "READER_ACTIVE_MINUTES": int(activity["readerActiveSeconds"]) // 60,
            "READER_TEXTS_COMPLETED": int(activity["readerTextsCompleted"]),
            "READER_EXPOSURES": int(activity["readerExposureEvents"]),
            "CLOZE_ATTEMPTS": int(activity["clozeAttempts"]),
        }
        items = []
        for quest in snapshot.get("quests") or []:
            current = values.get(str(quest["key"]), 0)
            target = int(quest["target"])
            items.append({
                **quest, "current": min(current, target), "rawCurrent": current,
                "completed": current >= target,
                "progressPercent": round(min(100, current * 100 / target), 1),
                "rewardXp": XP_VALUES["DAILY_QUEST_COMPLETED"],
            })
        return {
            "ruleVersion": QUEST_POLICY_VERSION, "localStudyDate": snapshot["localStudyDate"],
            "timezone": snapshot["timezone"], "snapshotId": snapshot["id"],
            "canonicalFingerprint": snapshot["canonicalFingerprint"], "items": items,
            "completedCount": sum(1 for item in items if item["completed"]),
        }

    def weekly_missions(self, profile_id: str, *, as_of: Any = None) -> dict[str, Any]:
        goals = self.statistics.goals(profile_id, as_of=as_of)
        return {
            "ruleVersion": QUEST_POLICY_VERSION,
            "ownership": "EXISTING_GOALS",
            "items": [{
                "missionKey": f"GOAL:{item['goal']['id']}:{item['periodStart']}",
                "title": item["goal"]["metric"].replace("_", " ").title(),
                "current": item["current"], "target": item["target"],
                "unit": item["goal"]["unit"], "completed": item["completed"],
                "progressPercent": item["percentage"], "periodStart": item["periodStart"],
                "periodEnd": item["periodEnd"], "goalRuleVersion": item["ruleVersion"],
            } for item in goals if item["goal"].get("enabled")],
        }

    def _campaign_milestones(self, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list) or not 1 <= len(value) <= 12:
            raise LanguageValidationError("milestones must contain 1 to 12 items", details=["milestones"])
        allowed = {"FAST_TRACK_RELIABLE", "READER_TEXTS_COMPLETED", "CLOZE_ATTEMPTS", "STUDY_DAYS", "TOPIC_KNOWN", "ANKI_LINKED_NOTES", "CURRICULUM_PACK_PROGRESS", "LISTENING_ACTIVE_MINUTES", "LISTENING_TEXTS_COMPLETED"}
        future = {"PRACTICAL_PACK", "LISTENING", "GRAMMAR", "WAREHOUSE", "SAFETY", "HOUSING", "WORK"}
        result = []
        seen = set()
        for index, raw in enumerate(value):
            if not isinstance(raw, dict):
                raise LanguageValidationError("Campaign milestone must be an object", details=[f"milestones[{index}]"])
            kind = str(raw.get("type") or "").upper()
            if kind in future:
                raise LanguageConflictError("That campaign dimension is not available before its owning phase", code="campaign_dimension_unavailable")
            if kind not in allowed:
                raise LanguageValidationError("Campaign milestone type is unsupported", details=[f"milestones[{index}].type"])
            try:
                target = int(raw.get("target"))
            except (TypeError, ValueError) as exc:
                raise LanguageValidationError("Campaign milestone target must be an integer", details=[f"milestones[{index}].target"]) from exc
            maximum = 100 if kind == "CURRICULUM_PACK_PROGRESS" else 100000
            if not 1 <= target <= maximum:
                raise LanguageValidationError("Campaign milestone target is out of range", details=[f"milestones[{index}].target"])
            item = {"type": kind, "target": target}
            if kind == "FAST_TRACK_RELIABLE":
                track = str(raw.get("trackKey") or "").upper()
                if track not in FAST_TRACK_BANDS:
                    raise LanguageValidationError("trackKey is invalid", details=[f"milestones[{index}].trackKey"])
                item["trackKey"] = track
            if kind == "TOPIC_KNOWN":
                topic_id = str(raw.get("topicId") or "")
                if not topic_id:
                    raise LanguageValidationError("topicId is required", details=[f"milestones[{index}].topicId"])
                item["topicId"] = topic_id
            if kind == "CURRICULUM_PACK_PROGRESS":
                if self.curriculum_service is None:
                    raise LanguageConflictError(
                        "Curriculum packs are not configured", code="curriculum_unavailable"
                    )
                pack_id = str(raw.get("packId") or "")
                try:
                    pack_version = int(raw.get("packVersion"))
                except (TypeError, ValueError) as exc:
                    raise LanguageValidationError(
                        "packVersion must be a positive integer",
                        details=[f"milestones[{index}].packVersion"],
                    ) from exc
                pack = self.curriculum_service.pack(pack_id, pack_version)
                if pack["pack"]["status"] != "ACTIVE":
                    raise LanguageConflictError(
                        "Campaigns can target only active curriculum pack versions",
                        code="curriculum_pack_not_active",
                    )
                item.update({
                    "packId": pack_id,
                    "packVersion": pack_version,
                    "packFingerprint": pack["pack"]["fingerprint"],
                })
            identity = canonical_json(item)
            if identity not in seen:
                seen.add(identity)
                result.append(item)
        return result

    def create_campaign(self, profile_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise LanguageValidationError("JSON payload must be an object", code="invalid_json_object")
        name = str(payload.get("name") or "").strip()
        if not name or len(name) > 120:
            raise LanguageValidationError("Campaign name is required and must be at most 120 characters", details=["name"])
        try:
            target = date.fromisoformat(str(payload.get("targetDate") or ""))
        except ValueError as exc:
            raise LanguageValidationError("targetDate must be an ISO date", details=["targetDate"]) from exc
        row = self.store.create_campaign({
            "language_profile_id": profile_id, "name": name,
            "description": str(payload.get("description") or "").strip()[:1000] or None,
            "target_date": target.isoformat(), "enabled": bool(payload.get("enabled", True)),
            "milestones": self._campaign_milestones(payload.get("milestones")),
            "rule_version": CAMPAIGN_POLICY_VERSION,
        })
        return self._campaign_progress(row)

    def update_campaign(self, campaign_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise LanguageValidationError("JSON payload must be an object", code="invalid_json_object")
        current = self.store.get_campaign(campaign_id)
        changes: dict[str, Any] = {"rule_version": CAMPAIGN_POLICY_VERSION}
        if "name" in payload:
            name = str(payload["name"] or "").strip()
            if not name or len(name) > 120:
                raise LanguageValidationError("Campaign name is required and must be at most 120 characters", details=["name"])
            changes["name"] = name
        if "description" in payload:
            changes["description"] = str(payload["description"] or "").strip()[:1000] or None
        if "targetDate" in payload:
            try:
                changes["target_date"] = date.fromisoformat(str(payload["targetDate"])).isoformat()
            except ValueError as exc:
                raise LanguageValidationError("targetDate must be an ISO date", details=["targetDate"]) from exc
        if "enabled" in payload:
            changes["enabled"] = 1 if bool(payload["enabled"]) else 0
        if "milestones" in payload:
            changes["milestones_json"] = canonical_json(self._campaign_milestones(payload["milestones"]))
        return self._campaign_progress(self.store.update_campaign(campaign_id, changes))

    def _campaign_progress(self, campaign: dict[str, Any], *, facts: dict[str, Any] | None = None,
                           collection_items: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
        profile_id = str(campaign["languageProfileId"])
        facts = facts or self.store.gamification_facts(profile_id)
        needs_fast_track = any(item.get("type") == "FAST_TRACK_RELIABLE" for item in campaign.get("milestones") or [])
        needs_curriculum = any(item.get("type") == "CURRICULUM_PACK_PROGRESS" for item in campaign.get("milestones") or [])
        collections = collection_items or {}
        if needs_fast_track and not collections:
            collections = {
                item["collectionKey"]: item
                for item in self.collections(profile_id, facts=facts)["items"]
                if item.get("kind") == "FAST_TRACK"
            }
        if needs_curriculum and not any(item.get("kind") == "CURRICULUM_PACK" for item in collections.values()):
            if self.curriculum_service is not None:
                collections.update({
                    item["collectionKey"]: item
                    for item in self.curriculum_service.collection_summaries(profile_id)
                })
        if needs_curriculum and self.curriculum_service is not None:
            for milestone in campaign.get("milestones") or []:
                if milestone.get("type") != "CURRICULUM_PACK_PROGRESS":
                    continue
                key = f"CURRICULUM:{milestone['packId']}:v{milestone['packVersion']}"
                if key not in collections:
                    pinned = self.curriculum_service.collection_summary(
                        profile_id, milestone["packId"], milestone["packVersion"]
                    )
                    collections[key] = {
                        "kind": "CURRICULUM_PACK",
                        "progressPercent": pinned["progress"]["progressPercent"],
                        "completionRuleVersion": pinned["progress"]["progressPolicyVersion"],
                    }
        study_days = len(_qualifying_reader_dates(facts, ZoneInfo(DEFAULT_TIMEZONE)))
        topics: dict[str, int] = Counter()
        for row in facts["topics"]:
            if row.get("lemma_id") and row.get("disposition") != "EXCLUDED" and row.get("knowledge_status") in {"KNOWN", "MASTERED"}:
                topics[str(row["id"])] += 1
        values = {
            "READER_TEXTS_COMPLETED": sum(1 for row in facts["progress"] if row.get("completed_at")),
            "CLOZE_ATTEMPTS": len(facts["attempts"]), "STUDY_DAYS": study_days,
            "ANKI_LINKED_NOTES": len(facts["ankiLinks"]),
            "LISTENING_ACTIVE_MINUTES": sum(
                int(row.get("active_ms") or 0) for row in facts.get("listeningEvents", [])
            ) // 60_000,
            "LISTENING_TEXTS_COMPLETED": sum(
                1 for row in facts.get("listeningProgress", []) if row.get("completed_at")
            ),
        }
        milestones = []
        for item in campaign.get("milestones") or []:
            kind = item["type"]
            if kind == "FAST_TRACK_RELIABLE":
                current = int(collections.get(item["trackKey"], {}).get("completed") or 0)
            elif kind == "TOPIC_KNOWN":
                current = int(topics.get(item["topicId"], 0))
            elif kind == "CURRICULUM_PACK_PROGRESS":
                key = f"CURRICULUM:{item['packId']}:v{item['packVersion']}"
                current = float(collections.get(key, {}).get("progressPercent") or 0)
            else:
                current = int(values.get(kind, 0))
            target = int(item["target"])
            milestones.append({
                **item, "current": current, "completed": current >= target,
                "progressPercent": round(min(100, current * 100 / target), 1),
                "evidenceRuleVersion": (
                    collections.get(
                        f"CURRICULUM:{item.get('packId')}:v{item.get('packVersion')}", {}
                    ).get("completionRuleVersion")
                    if kind == "CURRICULUM_PACK_PROGRESS"
                    else COLLECTION_POLICY_VERSION
                ) or COLLECTION_POLICY_VERSION,
            })
        today = datetime.now(ZoneInfo(DEFAULT_TIMEZONE)).date()
        target_date = date.fromisoformat(str(campaign["targetDate"]))
        return {
            **campaign, "ruleVersion": CAMPAIGN_POLICY_VERSION,
            "dateState": "PAST" if target_date < today else "TODAY" if target_date == today else "FUTURE",
            "milestones": milestones,
            "completedMilestones": sum(1 for item in milestones if item["completed"]),
            "milestoneCount": len(milestones), "universalReadinessPercent": None,
            "nextMilestone": next((item for item in milestones if not item["completed"]), None),
        }

    def campaigns(self, profile_id: str) -> dict[str, Any]:
        rows = self.store.list_campaigns(profile_id)
        if not rows:
            return {"ruleVersion": CAMPAIGN_POLICY_VERSION, "items": []}
        facts = self.store.gamification_facts(profile_id)
        needs_collections = any(
            item.get("type") in {"FAST_TRACK_RELIABLE", "CURRICULUM_PACK_PROGRESS"}
            for row in rows
            for item in row.get("milestones") or []
        )
        collections = None
        if needs_collections:
            collections = {
                item["collectionKey"]: item
                for item in self.collections(profile_id, facts=facts)["items"]
                if item.get("kind") in {"FAST_TRACK", "CURRICULUM_PACK"}
            }
        return {
            "ruleVersion": CAMPAIGN_POLICY_VERSION,
            "items": [self._campaign_progress(row, facts=facts, collection_items=collections) for row in rows],
        }

    def summary(self, profile_id: str, *, as_of: Any = None, statistics: dict[str, Any] | None = None) -> dict[str, Any]:
        ledger = self.store.gamification_ledger(profile_id)
        level = level_from_xp(ledger["lifetimeXp"])
        unlocks = self.store.achievement_unlocks(profile_id)
        quests = self.quests(profile_id, as_of=as_of)
        campaigns = self.campaigns(profile_id)["items"]
        stats = statistics or self.statistics.calculate(
            profile_id, range_name="30d", timezone_name=DEFAULT_TIMEZONE, as_of=as_of
        )
        return {
            "policyVersions": {
                "xp": XP_POLICY_VERSION, "levels": LEVEL_POLICY_VERSION,
                "achievements": ACHIEVEMENT_POLICY_VERSION, "collections": COLLECTION_POLICY_VERSION,
                "quests": QUEST_POLICY_VERSION, "campaigns": CAMPAIGN_POLICY_VERSION,
            },
            "level": level, "recentXp": ledger["recent"],
            "achievementCount": len(unlocks),
            "recentAchievement": sorted(unlocks, key=lambda row: row["unlockedAt"], reverse=True)[0] if unlocks else None,
            "today": quests,
            "weeklyMissions": self.weekly_missions(profile_id, as_of=as_of),
            "streak": stats.get("streak") or {},
            "campaign": next((item for item in campaigns if item.get("enabled")), None),
            "noPenaltyPolicy": "Missing a day never removes XP, level, achievements, or completed collection evidence.",
        }

    def progress(self, profile_id: str, *, as_of: Any = None) -> dict[str, Any]:
        summary = self.summary(profile_id, as_of=as_of)
        return {
            **summary,
            "achievements": self.achievements(profile_id, as_of=as_of),
            "collections": self.collections(profile_id),
            "campaigns": self.campaigns(profile_id),
        }


__all__ = [
    "ACHIEVEMENT_DEFINITIONS", "ACHIEVEMENT_POLICY_VERSION", "CAMPAIGN_POLICY_VERSION",
    "COLLECTION_POLICY_VERSION", "FAST_TRACK_STATE_VERSION", "GamificationService",
    "LEVEL_POLICY_VERSION", "QUEST_POLICY_VERSION", "XP_POLICY_VERSION", "XP_VALUES",
    "level_floor", "level_from_xp",
]
