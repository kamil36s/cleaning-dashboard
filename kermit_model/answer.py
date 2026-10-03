"""Phase 5 draft validation, without Phase 6 claim-level grounding."""

import json
import re


MAX_ANSWER_CHARS = 4000
MAX_UNCERTAINTY = 8
MAX_DRAFT_BYTES = 12000
ACTION = re.compile(r"\b(?:I|we|Kermit)(?:'ve|'d)?\s+(?:(?:have|had|did|just|already|personally)\s+)?(?:changed|updated|deleted|ran|run|checked|opened|fetched|restarted|queried|inspected|executed|modified|read|wrote|used)\b", re.I)

class DraftValidationError(ValueError):
    def __init__(self, category, message):
        super().__init__(message)
        self.category = category


def validate(raw, pack):
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_DRAFT_BYTES:
        raise DraftValidationError("oversized_response", "invalid draft size")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DraftValidationError("malformed_json", "draft is not JSON") from exc
    if not isinstance(data, dict) or set(data) != {"answer", "citedEvidenceIds", "uncertainty", "conflictsMentioned"}:
        raise DraftValidationError("schema_violation", "invalid draft fields")
    answer = data["answer"]
    if not isinstance(answer, str) or not answer.strip() or len(answer) > MAX_ANSWER_CHARS:
        raise DraftValidationError("schema_violation", "invalid answer")
    if ACTION.search(answer):
        raise DraftValidationError("action_claim", "invalid action claim")
    ids = {e["evidenceId"] for e in pack["selectedEvidence"]}
    conflicts = {c["id"] for c in pack["conflicts"]}
    references = data["citedEvidenceIds"]
    if not isinstance(references, list) or len(references) > 12 or any(not isinstance(i, str) for i in references) or len(references) != len(set(references)) or not set(references) <= ids:
        raise DraftValidationError("unknown_evidence_id", "unsupported evidence ID")
    diagnostics = pack.get("diagnostics", {})
    broad_property = (not any(s.get("score", 0) > 0 for s in pack.get("candidateSubsystems", []))
                      and bool(diagnostics.get("sectionIntents")))
    by_id = {e["evidenceId"]: e for e in pack["selectedEvidence"]}
    for reference in references:
        item = by_id[reference]
        signals = set(item.get("relevanceSignals", []))
        supported = (diagnostics.get("supportStatus") != "none" and
                     bool(signals & ({"section_intent_match", "finding_match"} if broad_property else
                                     {"section_intent_match", "subsystem_match", "finding_match", "direct_match"})))
        if not supported:
            raise DraftValidationError("unrelated_evidence_id", "cited evidence is unrelated to the request")
    if not isinstance(data["uncertainty"], list) or len(data["uncertainty"]) > MAX_UNCERTAINTY or any(not isinstance(x, str) or len(x) > 500 for x in data["uncertainty"]):
        raise DraftValidationError("schema_violation", "invalid uncertainty")
    mentioned = data["conflictsMentioned"]
    if not isinstance(mentioned, list) or len(mentioned) > 8 or any(not isinstance(x, str) for x in mentioned) or len(mentioned) != len(set(mentioned)):
        raise DraftValidationError("schema_violation", "invalid conflict IDs")
    if not set(mentioned) <= conflicts:
        raise DraftValidationError("unknown_conflict_id", "unsupported conflict ID")
    requested = {"conflict:" + match.upper() for match in re.findall(r"\b([A-Z][A-Z0-9]*-\d{2})\b",
                                                               pack.get("normalizedQuestion", ""), re.I)}
    if requested.intersection(conflicts) - set(mentioned):
        raise DraftValidationError("missing_conflict_id", "requested finding was not declared")
    return data
