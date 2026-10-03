"""Offline Phase 6 CLI; no dashboard or runtime adapter."""

import argparse
import json

from .evaluation import evaluate
from .service import ask_grounded


def main():
    parser = argparse.ArgumentParser(description="Kermit Phase 6 local grounding prototype")
    parser.add_argument("command", choices=("ask", "eval"))
    parser.add_argument("question", nargs="?")
    parser.add_argument("--provider", choices=("fake", "ollama"), default="fake")
    parser.add_argument("--profile", choices=("quick", "normal", "deep", "max"), default="quick")
    parser.add_argument("--allow-memory-pressure", action="store_true")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--explain", action="store_true")
    parser.add_argument("--case-number", type=int, action="append")
    parser.add_argument("--wait-for-memory", action="store_true")
    args = parser.parse_intermixed_args()
    if args.command == "ask" and not args.question:
        parser.error("ask requires a question")
    if args.command == "eval" and args.question:
        parser.error("eval takes no question")
    if args.command == "ask" and (args.case_number or args.wait_for_memory):
        parser.error("case selection and memory waiting are eval-only")
    if args.case_number and any(not 1 <= n <= 15 for n in args.case_number):
        parser.error("case numbers must be between 1 and 15")
    result = (ask_grounded(args.question, profile=args.profile, provider=args.provider,
                           allow_memory_pressure=args.allow_memory_pressure, explain=args.explain)
              if args.command == "ask" else evaluate(provider=args.provider, profile=args.profile,
                                                        allow_memory_pressure=args.allow_memory_pressure,
                                                        case_numbers=args.case_number,
                                                        wait_for_memory=args.wait_for_memory))
    if args.format == "json" or args.command == "eval":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(result["answer"])


if __name__ == "__main__":
    main()
