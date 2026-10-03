"""Phase 6 report with explicit claim checks; manual real-model review remains required."""

import time

from kermit_model.config import configured
from kermit_model.evaluation import CASES
from kermit_model.service import generate_draft
from kermit_retrieval import retrieve

from .service import ground


SEMANTIC = {
    "Which pilots depend on external providers?": {
        "expected_rejected_claims": ("Quote has no external provider",),
        "forbidden_claims": ("Quote has no external provider",),
        "expected_supported_claims": ("External requests",),
    },
    "What is the canonical Finance store?": {
        "forbidden_claims": ("cache is canonical", "fake.sqlite", "reading.sqlite"),
        "expected_supported_claims": ("finance.sqlite",),
    },
    "What is rebuildable reference data?": {
        "forbidden_claims": ("reference data is canonical user state",),
        "expected_supported_claims": ("rebuildable",),
    },
}


def evaluate(*, provider="fake", profile="quick", allow_memory_pressure=False,
             case_numbers=None, wait_for_memory=False):
    rows = []
    config = configured(profile, provider)
    selected = set(case_numbers or range(1, len(CASES) + 1))
    deadline = time.monotonic() + 900 if wait_for_memory else 0
    for number, (question, _, expected_conflict) in enumerate(CASES, 1):
        if number not in selected:
            continue
        pack = retrieve({"contractVersion": 1, "question": question})
        draft = generate_draft(pack, config=config, allow_memory_pressure=allow_memory_pressure)
        while (wait_for_memory and draft["status"] == "waiting_for_memory" and
               time.monotonic() + 15 < deadline):
            time.sleep(15)
            draft = generate_draft(pack, config=config, allow_memory_pressure=allow_memory_pressure)
        if draft["status"] not in ("draft", "insufficient_evidence"):
            rows.append({"question": question, "draftStatus": draft["status"], "finalStatus": draft["status"],
                         "resourceState": (draft.get("resource") or {}).get("state"),
                         "rawAnswer": None, "finalAnswer": None, "checks": {},
                         "draftLatencyMs": draft["latencyMs"], "groundingLatencyMs": 0})
            continue
        final = ground(pack, draft)
        spec = SEMANTIC.get(question, {})
        text = final["answer"].casefold()
        claims_by_id = {claim["claimId"]: claim for claim in final["claims"]}
        selected_ids = {e["evidenceId"] for e in pack["selectedEvidence"]}
        cited_ids = {c["evidenceId"] for c in final["citations"]}
        checks = {
            "citation_binding": all(c["evidenceId"] in {e["evidenceId"] for e in pack["selectedEvidence"]}
                                    for c in final["citations"]),
            "no_unsupported_final_claim": all(claim_id is None or
                                              claims_by_id[claim_id]["supportStatus"] in ("supported", "conflicted")
                                              for claim_id in final["displayedClaimIds"]),
            "expected_conflict": expected_conflict is None or any(c["conflictId"] == expected_conflict
                                                                   for c in final["conflicts"]),
            "forbidden_claims": all(term.casefold() not in text for term in spec.get("forbidden_claims", ())),
            "expected_supported_claims": all(term.casefold() in text for term in spec.get("expected_supported_claims", ())),
            "insufficiency": "never indexed" not in question or (not final["citations"] and
                             "insufficient" in text),
            "finding_sides": all(
                finding["status"] == ("independently_cited" if finding["type"] in
                                      ("FACTUAL_CONFLICT", "DOCUMENTATION_DRIFT") else "not_a_two_sided_conflict")
                and all(set(side["selectedEvidenceIds"]) <= selected_ids & cited_ids
                        for side in finding["evidenceSides"])
                and (finding["type"] == "TEST_COVERAGE_GAP" or
                     all(side["selectedEvidenceIds"] for side in finding["evidenceSides"]))
                for finding in final["conflicts"]),
        }
        rows.append({"question": question, "draftStatus": draft["status"],
                     "finalStatus": final["groundingStatus"], "checks": checks,
                     "rawAnswer": draft["answer"] if provider == "ollama" else None,
                     "rawCitedEvidenceIds": draft["citedEvidenceIds"],
                     "finalAnswer": final["answer"] if provider == "ollama" else None,
                     "finalCitationIds": [c["evidenceId"] for c in final["citations"]],
                     "displayedClaimIds": final["displayedClaimIds"],
                     "rawClaimStatuses": [c["supportStatus"] for c in final["claims"] if c["claimId"].startswith("C")],
                     "removedClaims": sum(c["supportStatus"] in ("unsupported", "contradicted") for c in final["claims"]),
                     "conflictIds": [c["conflictId"] for c in final["conflicts"]],
                     "draftLatencyMs": draft["latencyMs"], "groundingLatencyMs": final["groundingLatencyMs"]})
    return {"contractVersion": 1, "provider": provider, "profile": profile, "rows": rows,
            "evaluated": sum(bool(r["checks"]) for r in rows),
            "passedChecks": sum(bool(r["checks"]) and all(r["checks"].values()) for r in rows)}
