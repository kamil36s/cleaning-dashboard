"""Re-ground saved Phase 5 benchmark drafts without another model call."""

import argparse
import json
from pathlib import Path

from kermit_grounding import ground
from kermit_grounding.evaluation import SEMANTIC
from kermit_model.evaluation import CASES
from kermit_retrieval import retrieve


def replay(paths):
    drafts = {}
    for path in paths:
        report = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        for row in report["rows"]:
            if row["draftStatus"] in ("draft", "insufficient_evidence"):
                drafts[row["question"]] = row
    result = []
    for number, (question, _, expected_conflict) in enumerate(CASES, 1):
        raw = drafts[question]
        pack = retrieve({"contractVersion": 1, "question": question})
        final = ground(pack, {"answer": raw["rawAnswer"],
                              "citedEvidenceIds": raw["rawCitedEvidenceIds"], "uncertainty": []})
        spec = SEMANTIC.get(question, {})
        answer = final["answer"].casefold()
        by_claim = {claim["claimId"]: claim for claim in final["claims"]}
        selected_ids = {e["evidenceId"] for e in pack["selectedEvidence"]}
        cited_ids = {c["evidenceId"] for c in final["citations"]}
        side_bound = all(
            finding["status"] == ("independently_cited" if finding["type"] in
                                   ("FACTUAL_CONFLICT", "DOCUMENTATION_DRIFT") else "not_a_two_sided_conflict")
            and all(set(side["selectedEvidenceIds"]) <= selected_ids & cited_ids for side in finding["evidenceSides"])
            and (finding["type"] == "TEST_COVERAGE_GAP" or
                 all(side["selectedEvidenceIds"] for side in finding["evidenceSides"]))
            for finding in final["conflicts"])
        checks = {
            "expectedConflict": expected_conflict is None or expected_conflict in
                                {c["conflictId"] for c in final["conflicts"]},
            "forbiddenAbsent": all(term.casefold() not in answer for term in spec.get("forbidden_claims", ())),
            "expectedPresent": all(term.casefold() in answer for term in spec.get("expected_supported_claims", ())),
            "citationsBound": all(c["evidenceId"] in {e["evidenceId"] for e in pack["selectedEvidence"]}
                                  for c in final["citations"]),
            "displayedClaimsApproved": all(claim_id is None or
                                            by_claim[claim_id]["supportStatus"] in ("supported", "conflicted")
                                            for claim_id in final["displayedClaimIds"]),
            "findingSidesBound": side_bound,
        }
        result.append({"caseNumber": number, "question": question, "rawAnswer": raw["rawAnswer"],
                       "rawCitedEvidenceIds": raw["rawCitedEvidenceIds"],
                       "rawClaimStatuses": [c["supportStatus"] for c in final["claims"]
                                            if c["claimId"].startswith("C")],
                       "draftLatencyMs": raw["draftLatencyMs"], "final": final, "checks": checks})
    return {"cases": len(result), "passedChecks": sum(all(row["checks"].values()) for row in result),
            "rows": result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", nargs="+", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = json.dumps(replay(args.report), ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload)


if __name__ == "__main__":
    main()
