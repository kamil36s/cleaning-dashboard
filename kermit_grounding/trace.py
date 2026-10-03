"""Opt-in, process-local development trace. Never exposed by the HTTP service."""

import argparse
import json
import os

from kermit_model.config import configured
from kermit_model.prompt import build_prompt, select_evidence, serialize_evidence
from kermit_model.service import generate_draft
from kermit_retrieval import retrieve

from .service import ground


def trace(question, profile="quick", *, provider="ollama"):
    pack = retrieve({"contractVersion": 1, "question": question})
    config = configured(profile, provider)
    messages, prompt_info = build_prompt(pack, reasoning=config.reasoning,
                                         evidence_limit=config.evidence_limit)
    raw = {}
    draft = generate_draft(pack, config=config, trace_sink=raw.update)
    decisions = []
    final = ground(pack, draft, trace_sink=decisions.append) if draft["status"] in (
        "draft", "insufficient_evidence") else None
    return {"question": pack["normalizedQuestion"], "retrievalRevision": pack["evidenceAsOf"],
            "retrievedEvidence": pack["selectedEvidence"],
            "modelFacingEvidence": json.loads(serialize_evidence(
                pack, select_evidence(pack, config.evidence_limit))),
            "modelProfile": profile, "model": config.model,
            "outputTokens": config.max_output_tokens, "promptInfo": prompt_info,
            "systemPrompt": messages[0]["content"], "rawModel": raw,
            "validatedDraft": {key: value for key, value in draft.items()
                               if key not in ("diagnostics", "resource", "usage")},
            "claimsAndBindings": decisions, "finalResponse": final,
            "resourceGate": {key: (draft.get("resource") or {}).get(key)
                             for key in ("state", "availableMb", "minimumMb", "recommendedMb")}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question")
    parser.add_argument("--profile", choices=("quick", "normal"), default="quick")
    args = parser.parse_args()
    if os.environ.get("KERMIT_DEV_TRACE") != "1":
        parser.error("set KERMIT_DEV_TRACE=1 in the trusted local shell to enable tracing")
    print(json.dumps(trace(args.question, args.profile), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
