"""Bounded deterministic Phase 5 learning recommendations."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .statistics import CLASSIFIER_POLICY_VERSION, DEFAULT_TIMEZONE, StatisticsService


LEARNING_PLAN_RULE_VERSION = "language.learning-plan/v6"
RECYCLE_RULE_VERSION = "language.recycle/v1"


class LearningPlanService:
    def __init__(self, store: Any, statistics: StatisticsService, mistake_intelligence: Any | None = None):
        self.store = store
        self.statistics = statistics
        self.mistake_intelligence = mistake_intelligence

    def words_to_recycle(self, profile_id: str, *, as_of=None, limit: int = 8) -> dict[str, Any]:
        rows = self.statistics.classifiers(profile_id, as_of=as_of)
        candidates = []
        for row in rows:
            flags = row["classifiers"]
            categories = [
                label for label, key in (
                    ("Weak", "weak"), ("Recent", "recent"), ("Underexposed", "underexposed")
                ) if flags[key]
            ]
            if not categories:
                continue
            candidates.append({
                "lemmaId": row["id"],
                "lemma": row["lemmaDisplay"],
                "partOfSpeech": row.get("partOfSpeech"),
                "categories": categories,
                "reasons": flags["reasons"],
                "exposures": int(row.get("totalExposures") or 0),
                "lastSeenAt": row.get("lastSeenAt"),
                "knowledgeStatus": row.get("knowledgeStatus"),
                "frequencyScore": row.get("frequencyScore"),
                "_priority": (
                    0 if flags["weak"] else 1 if flags["recent"] else 2,
                    int(row.get("totalExposures") or 0),
                    -(float(row.get("frequencyScore")) if row.get("frequencyScore") is not None else -1),
                    str(row.get("lemmaNormalized") or ""),
                    str(row["id"]),
                ),
            })
        candidates.sort(key=lambda item: item["_priority"])
        selected = candidates[: max(0, min(int(limit), 20))]
        for item in selected:
            item.pop("_priority", None)
        return {
            "ruleVersion": RECYCLE_RULE_VERSION,
            "classifierPolicyVersion": CLASSIFIER_POLICY_VERSION,
            "items": selected,
            "totalCandidates": len(candidates),
        }

    def build(
        self, profile_id: str, *, as_of=None, anki: dict[str, Any] | None = None,
        cloze: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = as_of or datetime.now(timezone.utc)
        facts = self.store.statistics_facts(profile_id)
        recycle = self.words_to_recycle(profile_id, as_of=now)
        goals = [item for item in self.statistics.goals(profile_id, as_of=now) if item["activeNow"]]
        items: list[dict[str, Any]] = []

        unfinished = sorted(
            (
                row for row in facts["texts"]
                if row.get("processing_state") == "ANALYZED"
                and row.get("reading_status") == "IN_PROGRESS"
            ),
            key=lambda row: (str(row.get("last_read_at") or ""), str(row.get("id"))),
            reverse=True,
        )
        if unfinished:
            text = unfinished[0]
            items.append({
                "id": f"continue:{text['id']}",
                "kind": "CONTINUE_READING",
                "priority": 100,
                "title": f"Continue “{text['title']}”",
                "detail": "Resume the unfinished Reader text from its saved source position.",
                "href": f"#reader/text/{text['id']}",
            })

        unfinished_listening = sorted(
            (
                row for row in facts.get("listeningProgress", [])
                if row.get("status") == "IN_PROGRESS"
            ),
            key=lambda row: (str(row.get("last_listened_at") or ""), str(row.get("text_document_id"))),
            reverse=True,
        )
        if unfinished_listening:
            listening = unfinished_listening[0]
            items.append({
                "id": f"continue-listening:{listening['text_document_id']}",
                "kind": "CONTINUE_LISTENING",
                "priority": 95,
                "title": f"Continue listening to \"{listening['title']}\"",
                "detail": "Resume the last meaningful sentence. This is a dashboard recommendation, not SRS due work.",
                "href": f"#listening/text/{listening['text_document_id']}",
            })

        incomplete_goals = sorted(
            (goal for goal in goals if not goal["completed"]),
            key=lambda goal: (goal["percentage"], str(goal["goal"]["id"])),
        )
        if incomplete_goals:
            goal = incomplete_goals[0]
            metric = goal["goal"]["metric"]
            labels = {
                "NEW_WORDS": "Advance new vocabulary",
                "ACTIVE_READING_MINUTES": "Read actively toward this week's goal",
                "TEXTS_COMPLETED": "Complete a Reader text",
                "READER_EXPOSURES": "Read for real vocabulary exposure",
                "LISTENING_ACTIVE_MINUTES": "Listen actively toward this week's goal",
                "LISTENING_SESSIONS": "Complete a real listening session",
                "LISTENING_TEXTS_COMPLETED": "Complete a text by listening",
            }
            items.append({
                "id": f"goal:{goal['goal']['id']}",
                "kind": "GOAL_GAP",
                "priority": 90,
                "title": labels.get(metric, "Work toward a weekly goal"),
                "detail": f"{goal['remaining']:g} {str(goal['goal']['unit']).lower()} remaining this period.",
                "href": "#goals",
            })

        due_count = anki.get("dueCount") if isinstance(anki, dict) else None
        if anki and anki.get("status") == "CONNECTED" and isinstance(due_count, int) and due_count > 0:
            items.append({
                "id": "anki:due",
                "kind": "ANKI_DUE",
                "priority": 85,
                "title": f"Review {due_count} due Anki card{'s' if due_count != 1 else ''}",
                "detail": "Scheduling and answering remain in Anki.",
                "href": "#reviews",
            })

        remediation = (
            self.mistake_intelligence.remediation(profile_id, as_of=now)
            if self.mistake_intelligence is not None else {"items": []}
        )
        remediation_items = remediation.get("items") or []
        mistake_targets = len({str(item.get("targetLemmaId")) for item in remediation_items})
        if remediation_items:
            preview = ", ".join(str(item.get("targetLemma")) for item in remediation_items[:3])
            items.append({
                "id": "cloze:mistakes",
                "kind": "CLOZE_MISTAKES",
                "priority": 82,
                "title": f"Practice {mistake_targets} current mistake target{'s' if mistake_targets != 1 else ''}",
                "detail": f"{preview}. Shared deterministic remediation; Anki scheduling remains separate.",
                "href": "#cloze",
            })

        weak = [item for item in recycle["items"] if "Weak" in item["categories"]]
        if weak:
            preview = ", ".join(item["lemma"] for item in weak[:3])
            items.append({
                "id": "review:weak",
                "kind": "REVIEW_WEAK",
                "priority": 80,
                "title": "Practice weak vocabulary in Cloze",
                "detail": f"{preview}. Dashboard practice only; Anki keeps scheduling ownership.",
                "href": "#cloze",
            })

        underexposed = [item for item in recycle["items"] if "Underexposed" in item["categories"]]
        if underexposed:
            preview = ", ".join(item["lemma"] for item in underexposed[:3])
            items.append({
                "id": "recycle:underexposed",
                "kind": "RECYCLE_WORDS",
                "priority": 70,
                "title": "Practice underexposed words in Cloze",
                "detail": f"{preview}. Uses canonical learner evidence without creating due dates.",
                "href": "#cloze",
            })

        analyzed = [row for row in facts["texts"] if row.get("processing_state") == "ANALYZED"]
        if not unfinished and analyzed:
            text = sorted(analyzed, key=lambda row: (str(row.get("updated_at") or ""), str(row["id"])), reverse=True)[0]
            items.append({
                "id": f"read:{text['id']}",
                "kind": "READ_TEXT",
                "priority": 60,
                "title": f"Read “{text['title']}”",
                "detail": "Start an explicit Reader session when you are ready.",
                "href": f"#reader/text/{text['id']}",
            })
        elif not analyzed:
            items.append({
                "id": "reader:add-text",
                "kind": "ADD_TEXT",
                "priority": 50,
                "title": "Add and analyze a text",
                "detail": "Reader activity starts only after you explicitly begin reading.",
                "href": "#reader",
            })

        items.sort(key=lambda item: (-int(item["priority"]), item["id"]))
        return {
            "ruleVersion": LEARNING_PLAN_RULE_VERSION,
            "timezone": DEFAULT_TIMEZONE,
            "items": items[:5],
            "wordsToRecycle": recycle,
            "anki": {
                "status": anki.get("status") if isinstance(anki, dict) else "NOT_IMPLEMENTED",
                "recommendations": due_count if isinstance(due_count, int) else 0,
            },
            "cloze": {
                "practiceSystem": "DASHBOARD_CLOZE_PRACTICE",
                "mistakeTargets": mistake_targets,
                "remediationPolicyVersion": remediation.get("policyVersion"),
                "remediation": remediation_items,
            },
            "listening": {
                "ownership": "DASHBOARD_RECOMMENDATION_NOT_SRS",
                "unfinishedTexts": len(unfinished_listening),
            },
        }


__all__ = ["LEARNING_PLAN_RULE_VERSION", "RECYCLE_RULE_VERSION", "LearningPlanService"]
