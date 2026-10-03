"""Run the fixed Phase 5 questions through one local model, stopping at the Resource Gate.

The JSONL output is a local review artifact. This runner does not change retrieval,
the evidence pack, the prompt, or the validator.
"""

import argparse
import json
from pathlib import Path
import subprocess
import sys
from threading import Event, Thread

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kermit_model.config import configured
from kermit_model.evaluation import CASES, QUALITY, _mentions
from kermit_model.service import ask
from kermit_model.resources import read_physical_memory


TIER_A = (0, 4, 7, 8, 14)


def loaded_processes():
    command = ("Get-Process | Where-Object { $_.ProcessName -eq 'llama-server' } | "
               "Select-Object ProcessName,Id,WorkingSet64,PrivateMemorySize64 | ConvertTo-Json -Compress")
    completed = subprocess.run(["powershell", "-NoProfile", "-Command", command],
                               capture_output=True, text=True, timeout=5, check=False)
    if completed.returncode or not completed.stdout.strip():
        return []
    parsed = json.loads(completed.stdout)
    return parsed if isinstance(parsed, list) else [parsed]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tier", choices=("a", "full"), required=True)
    parser.add_argument("--profile", choices=("quick", "normal", "deep", "max"), default="quick")
    parser.add_argument("--start", type=int, default=0, help="zero-based position within the selected tier")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config = configured(args.profile, "ollama")
    indices = TIER_A if args.tier == "a" else range(len(CASES))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for position, index in enumerate(indices):
        if position < args.start:
            continue
        question, subsystem, conflict = CASES[index]
        observations = []
        stopped = Event()
        def observe():
            while not stopped.is_set():
                try:
                    observations.append(read_physical_memory().available_mb)
                except OSError:
                    pass
                stopped.wait(0.25)
        sampler = Thread(target=observe, daemon=True)
        sampler.start()
        try:
            result = ask(question, profile=args.profile, provider="ollama", explain=True)
        finally:
            stopped.set()
            sampler.join(timeout=2)
        diagnostic = result["diagnostics"]
        ids = set(diagnostic["retrieval"]["evidenceIds"])
        checks = {}
        if result["finishReason"] != "resource_gate":
            checks = {"validDraft": result["status"] in ("draft", "insufficient_evidence"),
                      "citationsBound": set(result["citedEvidenceIds"]) <= ids,
                      "conflictPreserved": conflict is None or
                          (conflict in result["conflictsMentioned"] and conflict.split(":")[-1] in result["answer"]),
                      "answerBounded": len(result["answer"]) <= 4000,
                      "noActionClaim": result["status"] != "invalid"}
            if "never indexed" in question:
                checks["insufficientEvidenceAcknowledged"] = ("insufficient" in result["answer"].casefold()
                                                                 and not result["citedEvidenceIds"])
            if question in QUALITY:
                required, forbidden = QUALITY[question]
                checks["requiredConcepts"] = all(_mentions(result["answer"], term) for term in required)
                checks["forbiddenClaimsAbsent"] = all(not _mentions(result["answer"], term) for term in forbidden)
        record = {"tier": args.tier, "position": position, "caseIndex": index,
                  "question": question, "expectedSubsystem": subsystem, "expectedConflict": conflict,
                  "checks": checks, "lowestAvailableDuringCallMb": min(observations) if observations else None,
                  "loadedProcessesAfterCall": loaded_processes() if result.get("resource") else [],
                  "result": result}
        with args.output.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(f"{position + 1}/{len(indices)} {question}: {result['status']} "
              f"{result['latencyMs'] / 1000:.1f}s gate={result.get('resource', {}).get('state')} "
              f"checks={'pass' if checks and all(checks.values()) else 'review'}", flush=True)
        if result["finishReason"] == "resource_gate":
            print("Stopped at Resource Gate; resume with --start after resources recover.", flush=True)
            return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
