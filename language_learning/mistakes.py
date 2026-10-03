"""Deterministic, read-only mistake diagnosis over canonical Cloze attempts."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
import hashlib
import json
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from .analysis.base import normalize_lookup
from .errors import LanguageNotFoundError
from .reference_core.models import VocabularyLemmaIdentity
from .statistics import DEFAULT_TIMEZONE


OBSERVATION_POLICY_VERSION = "language.mistakes-observation/v1"
CLUSTER_POLICY_VERSION = "language.mistakes-clustering/v1"
CONFUSABLE_POLICY_VERSION = "language.mistakes-confusable/v1"
SEVERITY_POLICY_VERSION = "language.mistakes-severity/v1"
REMEDIATION_POLICY_VERSION = "language.mistakes-remediation/v1"

MIN_NEGATIVE_ATTEMPTS = 2
MIN_DIRECT_CONFUSIONS = 2
MIN_CONTEXT_FAILURES = 2
MIN_OTHER_CONTEXT_SUCCESSES = 2
RECOVERY_SUCCESSES = 2
RECENT_DAYS = 7
CURRENT_DAYS = 30
MAX_SUMMARY_CLUSTERS = 10
MAX_REMEDIATION_ITEMS = 5
MAX_DETAIL_EVIDENCE = 50


def _utc(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _as_of(value: Any) -> datetime:
    return _utc(value) or datetime.now(timezone.utc)


def _safe_json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _cluster_id(category: str, key: Iterable[Any]) -> str:
    raw = "\x1f".join([CLUSTER_POLICY_VERSION, category, *(str(item) for item in key)])
    return "mi_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _evidence_payload(row: dict[str, Any]) -> dict[str, Any]:
    snapshot = row["snapshot"]
    source = snapshot.get("source") or {}
    return {
        "attemptId": row["id"],
        "sessionId": row["session_id"],
        "attemptedAt": row["attempted_at"],
        "outcome": row["outcome"],
        "questionType": row["question_type"],
        "expectedSurface": row["expected_surface_form"],
        "userAnswer": row.get("user_answer") or row.get("chosen_option"),
        "normalizedAnswer": row.get("normalized_answer"),
        "sourceContextType": row["source_context_type"],
        "sourceId": source.get("sourceId") or row.get("reference_sentence_source"),
        "sourceEntityId": source.get("sourceEntityId"),
        "sentenceId": source.get("sentenceId") or row.get("reference_sentence_id"),
        "contextFingerprint": (source.get("provenance") or {}).get("sentenceFingerprint")
        or snapshot.get("fingerprint") or row.get("item_fingerprint"),
        "observationPolicyVersion": OBSERVATION_POLICY_VERSION,
    }


class MistakeIntelligenceService:
    """Derive explainable clusters and remediation without mutating learning truth."""

    def __init__(self, store: Any, *, reference_service: Any | None = None):
        self.store = store
        self.reference_service = reference_service
        self._cache: dict[tuple[str, date, tuple[Any, ...]], dict[str, Any]] = {}

    def attach_reference_service(self, service: Any | None) -> None:
        self.reference_service = service
        self._cache.clear()

    def _form_resolution(
        self, profile_id: str, forms: list[dict[str, Any]], attempts: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in forms:
            grouped[str(row.get("normalized_form") or "")].append(row)
        result: dict[str, dict[str, Any]] = {}
        unresolved = []
        for normalized in sorted({str(row.get("normalized_answer") or "") for row in attempts if row.get("normalized_answer")}):
            candidates = grouped.get(normalized, [])
            lemma_ids = {str(row["lemma_id"]) for row in candidates}
            if len(lemma_ids) == 1 and candidates:
                preferred = next(
                    (row for row in candidates if str(row.get("ambiguity_state") or "").upper() != "AMBIGUOUS"),
                    candidates[0],
                )
                result[normalized] = {
                    "status": "MATCHED_USER_LEMMA",
                    "lemmaId": preferred["lemma_id"],
                    "lemma": preferred["lemma_display"],
                    "lemmaNormalized": preferred["lemma_normalized"],
                    "partOfSpeech": preferred.get("part_of_speech"),
                    "morphology": _safe_json(preferred.get("morphology_json")),
                    "analyzerEvidence": bool(preferred.get("provider_id"))
                    and str(preferred.get("ambiguity_state") or "").upper() != "AMBIGUOUS",
                    "providerId": preferred.get("provider_id"),
                    "providerVersion": preferred.get("provider_version"),
                }
            elif len(lemma_ids) > 1:
                result[normalized] = {"status": "AMBIGUOUS", "candidates": len(lemma_ids)}
            else:
                unresolved.append(normalized)

        if unresolved and self.reference_service is not None:
            try:
                profile = self.store.get_profile(profile_id)
                identities = [
                    VocabularyLemmaIdentity(str(profile["language_code"]), value, None, None)
                    for value in unresolved
                ]
                resolutions = self.reference_service.resolve_user_lemmas(identities)
                for normalized, resolution in zip(unresolved, resolutions):
                    candidates = resolution.get("candidates") or []
                    if resolution.get("status") == "MATCHED" and len(candidates) == 1:
                        candidate = candidates[0]
                        result[normalized] = {
                            "status": "MATCHED_REFERENCE_LEMMA",
                            "referenceLemmaId": candidate.get("id"),
                            "referenceStableKey": candidate.get("stableKey"),
                            "lemma": candidate.get("canonicalForm") or normalized,
                            "lemmaNormalized": candidate.get("normalizedForm") or normalized,
                            "partOfSpeech": candidate.get("partOfSpeech"),
                            "resolverRuleVersion": resolution.get("ruleVersion"),
                        }
                    else:
                        result[normalized] = {
                            "status": resolution.get("status") or "UNRESOLVED",
                            "resolverRuleVersion": resolution.get("ruleVersion"),
                        }
            except Exception:
                for normalized in unresolved:
                    result.setdefault(normalized, {"status": "UNRESOLVED"})
        for normalized in unresolved:
            result.setdefault(normalized, {"status": "UNRESOLVED"})
        return result

    @staticmethod
    def _attempt_rows(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows = []
        seen = set()
        for item in raw:
            attempt_id = str(item["id"])
            if attempt_id in seen:
                continue
            seen.add(attempt_id)
            snapshot = _safe_json(item.get("item_snapshot_json"))
            normalized = str(item.get("normalized_answer") or "")
            if not normalized and (item.get("user_answer") or item.get("chosen_option")):
                normalized = normalize_lookup(str(item.get("user_answer") or item.get("chosen_option")))
            rows.append({
                **item,
                "id": attempt_id,
                "snapshot": snapshot,
                "normalized_answer": normalized,
                "question_type": str(item.get("question_type") or "MULTIPLE_CHOICE"),
                "source_context_type": str(item.get("source_context_type") or "TATOEBA"),
            })
        return rows

    @staticmethod
    def _context_key(row: dict[str, Any]) -> tuple[str, str, str]:
        source = row["snapshot"].get("source") or {}
        return (
            row["source_context_type"],
            str(source.get("sourceEntityId") or source.get("sourceId") or row.get("reference_sentence_source") or ""),
            str(source.get("sentenceId") or row.get("reference_sentence_id") or ""),
        )

    def _state_and_priority(
        self, negatives: list[dict[str, Any]], successes: list[dict[str, Any]], now: datetime,
    ) -> dict[str, Any]:
        latest_negative = max((_utc(row["attempted_at"]) for row in negatives), default=None)
        later = [row for row in successes if (_utc(row["attempted_at"]) or datetime.min.replace(tzinfo=timezone.utc)) > latest_negative]
        later_dates = {
            (_utc(row["attempted_at"]) or now).astimezone(ZoneInfo(DEFAULT_TIMEZONE)).date()
            for row in later
        }
        recent7 = sum(1 for row in negatives if 0 <= (now - (_utc(row["attempted_at"]) or now)).days < RECENT_DAYS)
        recent30 = sum(1 for row in negatives if 0 <= (now - (_utc(row["attempted_at"]) or now)).days < CURRENT_DAYS)
        if len(later) >= RECOVERY_SUCCESSES and len(later_dates) >= 2:
            state = "RECOVERED"
        elif later:
            state = "IMPROVING"
        elif recent30:
            state = "ACTIVE"
        else:
            state = "WATCH"
        incorrect = sum(1 for row in negatives if row["outcome"] == "INCORRECT")
        reveals = sum(1 for row in negatives if row["outcome"] == "REVEALED")
        contexts = {self._context_key(row) for row in negatives}
        score = (
            incorrect * 2 + reveals + recent7 * 2 + max(0, recent30 - recent7)
            + min(2, max(0, len(contexts) - 1)) - min(6, len(later) * 2)
        )
        if state == "RECOVERED":
            score = min(score, 2)
        score = max(0, score)
        severity = "HIGH" if score >= 10 else "MEDIUM" if score >= 6 else "LOW"
        reasons = [
            f"{incorrect} incorrect attempt{'s' if incorrect != 1 else ''}",
            f"{reveals} reveal{'s' if reveals != 1 else ''}",
            f"{recent7} qualifying failure{'s' if recent7 != 1 else ''} in the last 7 days",
            f"{recent30} qualifying failure{'s' if recent30 != 1 else ''} in the last 30 days",
            f"{len(later)} correct attempt{'s' if len(later) != 1 else ''} after the latest failure",
        ]
        return {
            "state": state,
            "severity": severity,
            "priorityScore": score,
            "incorrectCount": incorrect,
            "revealCount": reveals,
            "recent7Count": recent7,
            "recent30Count": recent30,
            "laterSuccessCount": len(later),
            "laterSuccessDates": len(later_dates),
            "contextCount": len(contexts),
            "lastFailureAt": latest_negative.isoformat().replace("+00:00", "Z") if latest_negative else None,
            "lastRecoveryAt": max((row["attempted_at"] for row in later), default=None),
            "reasons": reasons,
        }

    def _cluster(
        self, category: str, key: tuple[Any, ...], target_rows: list[dict[str, Any]],
        negatives: list[dict[str, Any]], successes: list[dict[str, Any]], now: datetime,
        *, title: str, explanation: str, extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        target = target_rows[0]
        current = self._state_and_priority(negatives, successes, now)
        evidence = sorted([*negatives, *successes], key=lambda row: (row["attempted_at"], row["id"]))
        first_failure = min(row["attempted_at"] for row in negatives)
        local_now = now.astimezone(ZoneInfo(DEFAULT_TIMEZONE)).date()
        first_day = (_utc(first_failure) or now).astimezone(ZoneInfo(DEFAULT_TIMEZONE)).date()
        recovered_day = (
            (_utc(current["lastRecoveryAt"]) or now).astimezone(ZoneInfo(DEFAULT_TIMEZONE)).date()
            if current["lastRecoveryAt"] else None
        )
        return {
            "id": _cluster_id(category, key),
            "category": category,
            "title": title,
            "explanation": explanation,
            "target": {
                "lemmaId": target["target_lemma_id"],
                "lemma": target["lemma_display"],
                "lemmaNormalized": target["lemma_normalized"],
                "partOfSpeech": target.get("part_of_speech"),
                "knowledgeStatus": target.get("knowledge_status"),
            },
            **current,
            "historicalFailureCount": len(negatives),
            "firstFailureAt": first_failure,
            "newInLast7Days": 0 <= (local_now - first_day).days < RECENT_DAYS,
            "recoveredInLast7Days": bool(recovered_day and 0 <= (local_now - recovered_day).days < RECENT_DAYS),
            "sourceSummary": dict(sorted({
                source: sum(1 for row in negatives if row["source_context_type"] == source)
                for source in {row["source_context_type"] for row in negatives}
            }.items())),
            "evidenceCount": len(evidence),
            "recentEvidence": [_evidence_payload(row) for row in evidence[-5:]],
            "_evidence": evidence,
            **(extra or {}),
        }

    def _compute(self, profile_id: str, *, as_of: Any = None) -> dict[str, Any]:
        now = _as_of(as_of)
        study_date = now.astimezone(ZoneInfo(DEFAULT_TIMEZONE)).date()
        signature = self.store.cloze_mistake_signature(profile_id)
        cache_key = (profile_id, study_date, signature)
        if as_of is None and cache_key in self._cache:
            return self._cache[cache_key]
        inputs = self.store.cloze_mistake_inputs(profile_id)
        attempts = self._attempt_rows(inputs["attempts"])
        resolution = self._form_resolution(profile_id, inputs["forms"], attempts)
        by_target: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in attempts:
            by_target[str(row["target_lemma_id"])].append(row)
        clusters: list[dict[str, Any]] = []

        for target_id, rows in sorted(by_target.items()):
            negatives = [row for row in rows if row["outcome"] in {"INCORRECT", "REVEALED"}]
            successes = [row for row in rows if row["outcome"] == "CORRECT"]
            if len(negatives) >= MIN_NEGATIVE_ATTEMPTS:
                clusters.append(self._cluster(
                    "TARGET_LEMMA_DIFFICULTY", (target_id,), rows, negatives, successes, now,
                    title=f"{rows[0]['lemma_display']} needs repeated recall practice",
                    explanation="At least two canonical incorrect or revealed Cloze attempts target this lemma.",
                ))

            direct: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
            morphology: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
            unresolved: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for row in negatives:
                if row["outcome"] != "INCORRECT" or not row.get("normalized_answer"):
                    continue
                answer = str(row["normalized_answer"])
                resolved = resolution.get(answer, {"status": "UNRESOLVED"})
                resolved_id = str(resolved.get("lemmaId") or resolved.get("referenceStableKey") or "")
                if resolved_id and resolved_id != target_id:
                    direct[(resolved_id, answer)].append(row)
                elif resolved.get("lemmaId") == target_id:
                    expected_morphology = row["snapshot"].get("morphology") or {}
                    wrong_morphology = resolved.get("morphology") or {}
                    if (
                        resolved.get("analyzerEvidence") and expected_morphology and wrong_morphology
                        and normalize_lookup(str(row["expected_surface_form"])) != answer
                        and expected_morphology != wrong_morphology
                    ):
                        morphology[(normalize_lookup(str(row["expected_surface_form"])), answer)].append(row)
                elif resolved.get("status") in {"UNRESOLVED", "UNMATCHED", "AMBIGUOUS", "UNAVAILABLE"}:
                    unresolved[answer].append(row)

            for (wrong_id, answer), matching in sorted(direct.items()):
                if len(matching) < MIN_DIRECT_CONFUSIONS:
                    continue
                resolved = resolution[answer]
                clusters.append(self._cluster(
                    "DIRECTIONAL_CONFUSION", (target_id, wrong_id), rows, matching, successes, now,
                    title=f"{rows[0]['lemma_display']} is repeatedly answered as {resolved.get('lemma') or answer}",
                    explanation="The learner directly supplied or selected the same other resolved lemma at least twice; direction is preserved.",
                    extra={"confusion": {
                        "expectedLemmaId": target_id,
                        "suppliedLemmaId": resolved.get("lemmaId"),
                        "suppliedReferenceStableKey": resolved.get("referenceStableKey"),
                        "suppliedLemma": resolved.get("lemma") or answer,
                        "normalizedAnswer": answer,
                        "direction": "EXPECTED_TO_SUPPLIED",
                        "relationshipClaim": "LEARNER_RESPONSE_ONLY",
                    }},
                ))

            for (expected, answer), matching in sorted(morphology.items()):
                if len(matching) < MIN_NEGATIVE_ATTEMPTS:
                    continue
                clusters.append(self._cluster(
                    "INFLECTION_CONFUSION", (target_id, expected, answer), rows, matching, successes, now,
                    title=f"Repeated form difficulty for {rows[0]['lemma_display']}",
                    explanation="The exact wrong form resolves to the target lemma and analyzer morphology differs from the expected form.",
                    extra={"formPattern": {"expectedNormalized": expected, "suppliedNormalized": answer}},
                ))

            for answer, matching in sorted(unresolved.items()):
                if len(matching) < MIN_NEGATIVE_ATTEMPTS:
                    continue
                clusters.append(self._cluster(
                    "UNRESOLVED_FORM_DIFFICULTY", (target_id, answer), rows, matching, successes, now,
                    title=f"Repeated unresolved answer for {rows[0]['lemma_display']}",
                    explanation="The same exact normalized answer recurred, but it does not safely resolve to a canonical lemma.",
                    extra={"unresolvedAnswer": answer, "lemmaRelationship": "NONE"},
                ))

            by_context: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
            for row in negatives:
                by_context[self._context_key(row)].append(row)
            for context_key, matching in sorted(by_context.items()):
                other_successes = [row for row in successes if self._context_key(row) != context_key]
                if len(matching) < MIN_CONTEXT_FAILURES or len(other_successes) < MIN_OTHER_CONTEXT_SUCCESSES:
                    continue
                clusters.append(self._cluster(
                    "CONTEXT_DIFFICULTY", (target_id, *context_key), rows, matching, other_successes, now,
                    title=f"{rows[0]['lemma_display']} is difficult in one exact context",
                    explanation="Failures repeat in one frozen source context while at least two correct attempts exist elsewhere.",
                    extra={"context": {
                        "sourceContextType": context_key[0], "sourceEntityId": context_key[1],
                        "sentenceId": context_key[2], "otherContextSuccesses": len(other_successes),
                    }},
                ))

        clusters.sort(key=lambda item: (
            1 if item["state"] == "RECOVERED" else 0,
            -int(item["priorityScore"]), -int(item["recent30Count"]),
            str(item["target"]["lemmaNormalized"]), item["category"], item["id"],
        ))
        result = {
            "studyDate": study_date.isoformat(),
            "timezone": DEFAULT_TIMEZONE,
            "policies": {
                "observation": OBSERVATION_POLICY_VERSION,
                "clustering": CLUSTER_POLICY_VERSION,
                "confusable": CONFUSABLE_POLICY_VERSION,
                "severity": SEVERITY_POLICY_VERSION,
                "remediation": REMEDIATION_POLICY_VERSION,
            },
            "thresholds": {
                "minimumNegativeAttempts": MIN_NEGATIVE_ATTEMPTS,
                "minimumDirectConfusions": MIN_DIRECT_CONFUSIONS,
                "minimumContextFailures": MIN_CONTEXT_FAILURES,
                "minimumOtherContextSuccesses": MIN_OTHER_CONTEXT_SUCCESSES,
                "recoverySuccesses": RECOVERY_SUCCESSES,
                "recoveryDates": 2,
                "recentDays": RECENT_DAYS,
                "currentDays": CURRENT_DAYS,
            },
            "sourceAvailability": {
                "cloze": "AVAILABLE",
                "ankiReviewHistory": "NOT_SUPPORTED",
                "ankiReason": "Only current card aggregates are canonical; individual lapse events are unavailable.",
                "grammar": "UNAVAILABLE",
                "listening": "UNAVAILABLE",
            },
            "observationCount": sum(1 for row in attempts if row["outcome"] in {"INCORRECT", "REVEALED"}),
            "historicalIncorrectCount": sum(1 for row in attempts if row["outcome"] == "INCORRECT"),
            "historicalRevealCount": sum(1 for row in attempts if row["outcome"] == "REVEALED"),
            "clusters": clusters,
        }
        if as_of is None:
            self._cache = {key: value for key, value in self._cache.items() if key[0] != profile_id}
            self._cache[cache_key] = result
        return result

    @staticmethod
    def _public_cluster(cluster: dict[str, Any], *, include_evidence: bool = False) -> dict[str, Any]:
        result = {key: value for key, value in cluster.items() if key != "_evidence"}
        if include_evidence:
            result["evidence"] = [
                _evidence_payload(row) for row in cluster["_evidence"][-MAX_DETAIL_EVIDENCE:]
            ]
            result["evidenceTruncated"] = len(cluster["_evidence"]) > MAX_DETAIL_EVIDENCE
        return result

    def remediation(self, profile_id: str, *, as_of: Any = None, limit: int = MAX_REMEDIATION_ITEMS) -> dict[str, Any]:
        computed = self._compute(profile_id, as_of=as_of)
        bounded = max(0, min(int(limit), 10))
        items = []
        seen_targets = set()
        action_map = {
            "INFLECTION_CONFUSION": "PRACTICE_TYPED_FORM",
            "DIRECTIONAL_CONFUSION": "REVIEW_LEXICAL_DETAIL",
            "CONTEXT_DIFFICULTY": "REVISIT_READER_CONTEXT",
            "UNRESOLVED_FORM_DIFFICULTY": "PRACTICE_TYPED_FORM",
            "TARGET_LEMMA_DIFFICULTY": "RECYCLE_RECENT_FAILURE",
        }
        for cluster in computed["clusters"]:
            if cluster["state"] == "RECOVERED":
                continue
            target_id = str(cluster["target"]["lemmaId"])
            if target_id in seen_targets:
                continue
            seen_targets.add(target_id)
            action = action_map[cluster["category"]]
            href = f"#vocabulary/lemma/{target_id}" if action == "REVIEW_LEXICAL_DETAIL" else "#cloze"
            items.append({
                "id": f"remediation:{cluster['id']}", "clusterId": cluster["id"],
                "actionKind": action, "targetLemmaId": target_id,
                "targetLemma": cluster["target"]["lemma"], "state": cluster["state"],
                "severity": cluster["severity"], "priorityScore": cluster["priorityScore"],
                "title": cluster["title"], "reason": cluster["explanation"], "href": href,
            })
            if len(items) >= bounded:
                break
        return {
            "policyVersion": REMEDIATION_POLICY_VERSION,
            "studyDate": computed["studyDate"], "timezone": computed["timezone"],
            "items": items, "totalCandidates": len([
                item for item in computed["clusters"] if item["state"] != "RECOVERED"
            ]),
        }

    def summary(self, profile_id: str, *, as_of: Any = None, limit: int = MAX_SUMMARY_CLUSTERS) -> dict[str, Any]:
        computed = self._compute(profile_id, as_of=as_of)
        bounded = max(1, min(int(limit), 25))
        active = [item for item in computed["clusters"] if item["state"] != "RECOVERED"]
        recovered = [item for item in computed["clusters"] if item["state"] == "RECOVERED"]
        remediation = self.remediation(profile_id, as_of=as_of)
        return {
            **{key: value for key, value in computed.items() if key != "clusters"},
            "activeClusterCount": len(active), "recoveredClusterCount": len(recovered),
            "newInLast7Days": sum(1 for item in computed["clusters"] if item["newInLast7Days"]),
            "recoveredInLast7Days": sum(1 for item in recovered if item["recoveredInLast7Days"]),
            "topProblems": [self._public_cluster(item) for item in active[:bounded]],
            "recentRecoveries": [self._public_cluster(item) for item in recovered[:5]],
            "remediation": remediation,
        }

    def detail(self, profile_id: str, cluster_id: str, *, as_of: Any = None) -> dict[str, Any]:
        computed = self._compute(profile_id, as_of=as_of)
        cluster = next((item for item in computed["clusters"] if item["id"] == cluster_id), None)
        if cluster is None:
            raise LanguageNotFoundError("Mistake cluster was not found", code="mistake_cluster_not_found")
        return {
            "policies": computed["policies"], "thresholds": computed["thresholds"],
            "cluster": self._public_cluster(cluster, include_evidence=True),
        }


__all__ = [
    "CLUSTER_POLICY_VERSION", "CONFUSABLE_POLICY_VERSION", "MistakeIntelligenceService",
    "OBSERVATION_POLICY_VERSION", "REMEDIATION_POLICY_VERSION", "SEVERITY_POLICY_VERSION",
]
