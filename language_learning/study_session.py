"""Read-only, bounded composition of existing Language study work."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from .errors import LanguageValidationError
from .statistics import DEFAULT_TIMEZONE


POLICY_VERSION = "language.study-session-builder/v1"
SOURCES = ("Anki", "Mistake Intelligence", "LearningPlan", "Goals", "Reader",
           "Listening", "Curriculum", "Grammar", "Benchmarks")
MAX_SEGMENTS = {10: 3, 20: 4, 30: 5}
MINUTES = {
    "ANKI_DUE": 5, "CLOZE_MISTAKES": 5, "REVIEW_WEAK": 5,
    "RECYCLE_WORDS": 5, "GOAL_GAP": 5, "CONTINUE_READING": 7,
    "CONTINUE_LISTENING": 7, "READ_TEXT": 7, "LISTENING_STUDY": 7,
    "CURRICULUM_GAP": 5, "CORE_GRAMMAR": 3,
}
PRIORITY = {
    "ANKI_DUE": 100, "CLOZE_MISTAKES": 95, "GOAL_GAP": 80,
    "CONTINUE_READING": 75, "CONTINUE_LISTENING": 75,
    "REVIEW_WEAK": 70, "RECYCLE_WORDS": 65,
    "CURRICULUM_GAP": 60, "CORE_GRAMMAR": 50,
    "READ_TEXT": 45, "LISTENING_STUDY": 45,
}
OWNER = {
    "ANKI_DUE": "Anki", "CLOZE_MISTAKES": "Mistake Intelligence",
    "GOAL_GAP": "Goals", "CONTINUE_READING": "Reader",
    "CONTINUE_LISTENING": "Listening", "REVIEW_WEAK": "LearningPlan",
    "RECYCLE_WORDS": "LearningPlan", "CURRICULUM_GAP": "Curriculum",
    "CORE_GRAMMAR": "Grammar", "READ_TEXT": "Reader",
    "LISTENING_STUDY": "Listening",
}
MODE = {
    "ANKI_DUE": "anki", "CLOZE_MISTAKES": "cloze", "REVIEW_WEAK": "cloze",
    "RECYCLE_WORDS": "cloze", "CONTINUE_READING": "reader",
    "READ_TEXT": "reader", "CONTINUE_LISTENING": "listening",
    "LISTENING_STUDY": "listening", "CURRICULUM_GAP": "curriculum",
    "CORE_GRAMMAR": "grammar", "GOAL_GAP": "goal",
}


def _candidate(kind, key, title, reason, href, *, reference=None, score=None):
    if not href or not href.startswith("#") or kind not in MINUTES:
        return None
    return {
        "segmentId": f"{kind.lower()}:{key}", "segmentType": kind,
        "sourceOwner": OWNER[kind], "title": title, "reason": reason,
        "estimatedMinutes": MINUTES[kind], "destinationRoute": href,
        "sourceReference": reference or key,
        "selectionRule": POLICY_VERSION, "prioritySummary": "Owner evidence and bounded study value",
        "_score": PRIORITY[kind] if score is None else score,
        "_mode": MODE[kind],
    }


def compose(profile_id, minutes, local_date, candidates, *, unavailable=()):
    """Pure deterministic policy; no canonical state is written."""
    if type(minutes) is not int or minutes not in MAX_SEGMENTS:
        raise LanguageValidationError("minutes must be 10, 20, or 30", details=["minutes"])
    unique = {row["segmentId"]: row for row in candidates if row is not None}
    ordered = sorted(unique.values(), key=lambda row: (-row["_score"], row["segmentId"]))
    fingerprint_input = {
        "policy": POLICY_VERSION, "profile": profile_id, "date": local_date,
        "minutes": minutes, "candidates": ordered,
        "unavailable": sorted(set(unavailable)),
    }
    fingerprint = hashlib.sha256(json.dumps(fingerprint_input, sort_keys=True, ensure_ascii=False,
                                             separators=(",", ":")).encode()).hexdigest()
    selected = []
    used_modes = set()
    remaining = minutes
    while len(selected) < MAX_SEGMENTS[minutes]:
        fitting = [row for row in ordered if row not in selected and row["estimatedMinutes"] <= remaining
                   and row["destinationRoute"] not in {used["destinationRoute"] for used in selected}]
        if not fitting:
            break
        # A small diversity discount breaks near ties; urgent owner work still wins.
        best = min(fitting, key=lambda row: (-(row["_score"] - (12 if row["_mode"] in used_modes else 0)),
                                             -row["_score"], row["segmentId"]))
        selected.append(best)
        used_modes.add(best["_mode"])
        remaining -= best["estimatedMinutes"]
    public = [{key: value for key, value in row.items() if not key.startswith("_")} for row in selected]
    availability = {name: ("UNAVAILABLE" if name in unavailable else
                           "ELIGIBLE" if any(row["sourceOwner"] == name for row in ordered) else
                           "NO_ELIGIBLE_WORK") for name in SOURCES}
    return {
        "policyVersion": POLICY_VERSION, "estimationPolicyVersion": POLICY_VERSION,
        "generatedAtLocalDate": local_date, "timezone": DEFAULT_TIMEZONE,
        "snapshotFingerprint": fingerprint, "requestedMinutes": minutes,
        "plannedMinutes": minutes - remaining, "segmentCount": len(public),
        "segments": public, "unavailableSources": sorted(set(unavailable)),
        "sourceAvailability": availability,
    }


class StudySessionBuilder:
    def __init__(self, service):
        self.service = service

    def build(self, profile_id, minutes, *, as_of=None):
        service = self.service
        profile_id = service._id(profile_id, "profileId")
        service.store.get_profile(profile_id)
        if type(minutes) is not int or minutes not in MAX_SEGMENTS:
            raise LanguageValidationError("minutes must be 10, 20, or 30", details=["minutes"])
        now = as_of or datetime.now(timezone.utc)
        local_date = now.astimezone(ZoneInfo(DEFAULT_TIMEZONE)).date().isoformat()
        snapshot_as_of = datetime.combine(now.astimezone(ZoneInfo(DEFAULT_TIMEZONE)).date(),
                                          time(23, 59, 59), ZoneInfo(DEFAULT_TIMEZONE))
        candidates = []
        unavailable = []

        def collect(name, function):
            try:
                return function()
            except Exception:
                unavailable.append(name)
                return None

        anki = collect("Anki", lambda: service.anki_sync_service.status(profile_id, probe=False))
        due = anki.get("dueCount") if anki else None
        last = anki.get("lastSync") if anki else None
        sync_time = (last or {}).get("startedAt") or (last or {}).get("started_at")
        same_day = False
        if sync_time:
            try:
                same_day = datetime.fromisoformat(sync_time.replace("Z", "+00:00")).astimezone(
                    ZoneInfo(DEFAULT_TIMEZONE)).date().isoformat() == local_date
            except (TypeError, ValueError):
                pass
        if (anki and anki.get("configured") and same_day and
                (last or {}).get("status") in {"COMPLETED", "PARTIAL"} and
                type(due) is int and due > 0):
            candidates.append(_candidate("ANKI_DUE", "due", "Review due Anki cards",
                                         f"Today's stored Anki sync reported {due} due cards; check Anki for the live queue.",
                                         "#reviews", reference="anki:latest-sync"))
        elif anki and not anki.get("configured"):
            unavailable.append("Anki")

        plan = collect("LearningPlan", lambda: service.learning_plan_service.build(profile_id, as_of=snapshot_as_of,
                                                                                     anki=anki, cloze=None))
        if plan:
            remediation = plan.get("cloze", {}).get("remediation") or []
            for item in plan.get("items") or []:
                kind = item.get("kind")
                if kind not in MINUTES or kind == "ANKI_DUE":
                    continue
                if kind == "CLOZE_MISTAKES":
                    if not remediation:
                        continue
                    reason = f"{len(remediation)} current mistake target(s) are eligible for remediation."
                else:
                    reason = item.get("detail") or item.get("title")
                if kind == "GOAL_GAP":
                    # Goals are targets, not an activity. Select a real current modality.
                    matching = next((row for row in plan["items"] if row.get("kind") in
                                     {"CONTINUE_READING", "CONTINUE_LISTENING", "READ_TEXT"}), None)
                    if not matching:
                        continue
                    href = matching["href"]
                    reason = f"{reason} Open existing {matching['kind'].replace('_', ' ').lower()} work."
                else:
                    href = item["href"]
                candidates.append(_candidate(kind, item["id"], item["title"], reason, href,
                                             reference=item["id"]))

        reader = collect("Reader", lambda: service.store.list_texts(profile_id, limit=20, offset=0))
        if reader:
            completed_routes = {f"#reader/text/{row['id']}" for row in reader["items"]
                                if row.get("reading_status") in {"COMPLETED", "COMPLETE"}}
            candidates = [row for row in candidates if row is not None and
                          not (row["destinationRoute"] in completed_routes and
                               row["segmentType"] in {"READ_TEXT", "GOAL_GAP"})]
        if reader and not any(row and row["_mode"] == "reader" for row in candidates):
            text = next((row for row in reader["items"] if row.get("processing_state") == "ANALYZED"
                         and row.get("reading_status") not in {"COMPLETED", "COMPLETE"}), None)
            if text:
                candidates.append(_candidate("READ_TEXT", text["id"], f"Read {text['title']}",
                                             "An analyzed Reader text is ready for an explicit reading session.",
                                             f"#reader/text/{text['id']}", reference=text["id"]))

        listening = collect("Listening", lambda: service.store.list_listening_materials(profile_id, limit=3))
        if listening and not any(row and row["_mode"] == "listening" for row in candidates):
            material = next((row for row in listening["items"] if row.get("listening_status") != "COMPLETED"
                             and int(row.get("eligible_sentence_count") or 0) > 0), None)
            if material:
                candidates.append(_candidate("LISTENING_STUDY", material["text_document_id"],
                                             f"Listen to {material['title']}",
                                             "An analyzed text has available listening material and is not completed.",
                                             f"#listening/text/{material['text_document_id']}",
                                             reference=material["text_document_id"]))

        has_study_context = any(row and row["sourceOwner"] != "Anki" for row in candidates)
        curriculum = collect("Curriculum", lambda: service.curriculum_service.landing(profile_id))
        if curriculum:
            for pack in curriculum.get("packs") or []:
                progress = pack.get("progress") or {}
                gap = int(progress.get("eligibleDenominator") or 0) - int(progress.get("completed") or 0)
                if gap > 0 and (has_study_context or int(progress.get("completed") or 0) > 0):
                    candidates.append(_candidate("CURRICULUM_GAP", pack["id"], f"Review {pack['name']}",
                                                 f"{gap} eligible items in this reviewed pack are not yet acquired.",
                                                 f"#curriculum/{pack['id']}/v/{pack['version']}",
                                                 reference=f"{pack['id']}/v/{pack['version']}"))

        grammar = collect("Grammar", lambda: service.grammar.summary(profile_id))
        if grammar:
            for pattern in grammar.get("items") or []:
                if pattern.get("state") == "ENCOUNTERED" and pattern.get("authoritativeCount", 0) > 0:
                    candidates.append(_candidate("CORE_GRAMMAR", pattern["patternId"],
                                                 f"Review {pattern.get('name') or pattern['patternId']} examples",
                                                 "You encountered a supported pattern in real study; review its source examples.",
                                                 f"#grammar/pattern/{pattern['patternId']}",
                                                 reference=pattern["patternId"]))

        # Benchmarks are descriptive. A completed weak dimension only breaks close
        # ties between already eligible Reader/Listening work; it creates no work.
        history = collect("Benchmarks", lambda: service.assessment.list_runs(profile_id))
        completed = next((run for run in (history or {}).get("runs", []) if run.get("status") == "COMPLETED"), None)
        if completed:
            scores = completed.get("scores") or {}
            available = [(name, scores.get(name, {}).get("percent")) for name in ("READING", "LISTENING")]
            available = [(name, value) for name, value in available if isinstance(value, (int, float))]
            if len(available) == 2 and available[0][1] != available[1][1]:
                weak = {"READING": "reader", "LISTENING": "listening"}[
                    min(available, key=lambda item: item[1])[0]]
                for row in candidates:
                    if row and row["_mode"] == weak:
                        row["_score"] += 2
                        row["prioritySummary"] = "Eligible owner work; completed benchmark tie break (+2)"
                        row["reason"] += " A completed benchmark modestly favored this modality; scores are descriptive."
                        if (completed.get("comparison") or {}).get("state") == "REPEAT_INFLUENCED":
                            row["reason"] += " Repeated-form scores may reflect familiarity."
        result = compose(profile_id, minutes, local_date, candidates, unavailable=unavailable)
        if plan is not None:
            result["sourceAvailability"]["LearningPlan"] = "AVAILABLE"
        if completed is not None:
            result["sourceAvailability"]["Benchmarks"] = "AVAILABLE"
        return result
