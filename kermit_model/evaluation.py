"""Deterministic answer-envelope checks over representative Phase 4 questions."""

import re

from .service import ask


# Adapted from Phase 4's pilot benchmark; findings include all requested conflict cases.
CASES = (
    ("What does the Quote widget do?", "quote", None),
    ("What happens when the primary quote provider fails?", "quote", None),
    ("What is the canonical Finance store?", "finance", None),
    ("What happens during Finance review?", "finance", None),
    ("How does the generation job recover after interruption?", "language-learning", None),
    ("What is rebuildable reference data?", "language-learning", None),
    ("Where does weather data come from?", "weather", None),
    ("Which pilots depend on external providers?", None, None),
    ("What is W-02?", "weather", "conflict:W-02"),
    ("What is F-01?", "finance", "conflict:F-01"),
    ("What is F-02?", "finance", "conflict:F-02"),
    ("What is F-03?", "finance", "conflict:F-03"),
    ("What is F-04?", "finance", "conflict:F-04"),
    ("What does L-01 mean?", "language-learning", "conflict:L-01"),
    ("Explain a private journal entry that was never indexed", None, None),
)

# Content probes are reported for real-model review, not fake-provider release gates.
QUALITY = {
    "What does the Quote widget do?": (("quote", "provider"), ("database",)),
    "What is the canonical Finance store?": (("sqlite", "canonical"), ("cache is canonical",)),
    "What is rebuildable reference data?": (("reference", "rebuild"), ("canonical user state",)),
    "How does the generation job recover after interruption?": (("requeu", "attempt"), ()),
    "Where does weather data come from?": (("open-meteo",), ("finance.sqlite",)),
    "Which pilots depend on external providers?": (("quote", "weather", "language", "external"), ("none of the provided evidence",)),
    "What is W-02?": (("null", "zero"), ("null is always unknown",)),
    "What is F-01?": (("csv", "original"), ("byte-exact archive exists",)),
    "What is F-02?": (("utc", "date"), ("one default timezone",)),
    "What is F-03?": (("fresh", "stale"), ("one shared threshold",)),
    "What is F-04?": (("categor", "receipt"), ("same category allocation",)),
    "What does L-01 mean?": (("responsejsonschema",), ("no schema is sent",)),
}


def _mentions(text, term):
    if term == "zero" and re.search(r"\b0\b", text):
        return True
    normalized = "".join(ch for ch in text.casefold() if ch.isalnum())
    return "".join(ch for ch in term.casefold() if ch.isalnum()) in normalized


def evaluate(*, provider="fake", profile="normal"):
    rows = []
    for question, subsystem, conflict in CASES:
        result = ask(question, provider=provider, profile=profile, explain=True)
        diagnostics = result["diagnostics"]
        answer = result["answer"]
        cited = set(result["citedEvidenceIds"])
        available = set(diagnostics["retrieval"]["evidenceIds"])
        blocked = result["finishReason"] == "resource_gate"
        checks = {} if blocked else {
            "validDraft": result["status"] in ("draft", "insufficient_evidence"),
            "citationsBound": cited <= available,
            "conflictPreserved": conflict is None or conflict in result["conflictsMentioned"] and conflict.split(":")[-1] in answer,
            "answerBounded": len(answer) <= 4000,
            "noActionClaim": result["status"] != "invalid",
        }
        if not blocked and "never indexed" in question:
            checks["insufficientEvidenceAcknowledged"] = "insufficient" in answer.casefold() and not cited
        if not blocked and provider == "ollama" and question in QUALITY:
            required, forbidden = QUALITY[question]
            checks["requiredConcepts"] = all(_mentions(answer, term) for term in required)
            checks["forbiddenClaimsAbsent"] = all(not _mentions(answer, term) for term in forbidden)
        failure = ("RESOURCE_BLOCKED" if blocked else result.get("failureCategory") or
                   ("factual_evaluation_failure" if provider == "ollama" and not all(checks.values()) else None))
        resource = result.get("resource") or {}
        prompt = diagnostics["prompt"]
        usage = result.get("usage") or {}
        duration = usage.get("eval_duration")
        rows.append({"question": question, "status": result["status"],
                     "outcome": "RESOURCE_BLOCKED" if blocked else "EVALUATED", "checks": checks,
                     "evidenceIds": sorted(available), "citedEvidenceIds": result["citedEvidenceIds"],
                     "conflictsMentioned": result["conflictsMentioned"],
                     "profile": profile, "cold": not resource.get("modelResident") if resource else None,
                     "resourceState": resource.get("state"), "availableMb": resource.get("availableMb"),
                     "evidenceCount": prompt["evidenceCount"], "evidenceBytes": prompt["evidenceBytes"],
                     "promptEstimate": prompt["approxTokens"],
                     "outputBudget": diagnostics["generationOptions"]["num_predict"],
                     "latencyMs": result["latencyMs"], "tokensPerSecond": round(usage["eval_count"] * 1e9 / duration, 1) if duration else None,
                     "finishReason": result["finishReason"], "failureCategory": failure,
                     "structuralValidity": None if blocked else result["status"] in ("draft", "insufficient_evidence"),
                     "groundingResult": None if blocked else checks.get("requiredConcepts"),
                     "conflictResult": None if blocked else checks.get("conflictPreserved"),
                     "answer": answer if provider == "ollama" else None})
    return {"provider": provider, "profile": profile, "questions": len(rows),
            "evaluated": sum(row["outcome"] == "EVALUATED" for row in rows),
            "resourceBlocked": sum(row["outcome"] == "RESOURCE_BLOCKED" for row in rows),
            "passed": sum(row["outcome"] == "EVALUATED" and all(row["checks"].values()) for row in rows), "rows": rows}
