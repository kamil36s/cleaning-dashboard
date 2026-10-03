import argparse
import json

from kermit_retrieval import RetrievalError

from .config import configured
from .evaluation import evaluate
from .fake_provider import FakeProvider
from .ollama_provider import OllamaProvider
from .provider import ProviderFailure
from .resources import preflight
from .service import ask


def main():
    parser = argparse.ArgumentParser(description="Kermit Phase 5 local model prototype")
    parser.add_argument("command", choices=("ask", "health", "resources", "eval"))
    parser.add_argument("question", nargs="?")
    parser.add_argument("--provider", choices=("fake", "ollama"))
    parser.add_argument("--profile", choices=("quick", "normal", "deep", "max"), default="normal")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--explain", action="store_true")
    parser.add_argument("--allow-memory-pressure", action="store_true")
    args = parser.parse_intermixed_args()
    if args.command == "ask" and not args.question:
        parser.error("ask requires a question")
    if args.command != "ask" and args.question:
        parser.error("question is only valid for ask")
    if args.allow_memory_pressure and args.command != "ask":
        parser.error("--allow-memory-pressure is only valid for ask")
    try:
        selected_provider = args.provider or ("ollama" if args.command == "resources" else None)
        config = configured(args.profile, selected_provider)
        if args.command == "ask":
            result = ask(args.question, profile=args.profile, provider=args.provider, explain=args.explain,
                         allow_memory_pressure=args.allow_memory_pressure)
        elif args.command == "health":
            provider = FakeProvider() if config.provider == "fake" else OllamaProvider()
            result = {"model": config.model, "profile": config.profile, **provider.health(config)}
        elif args.command == "resources":
            if config.provider != "ollama":
                parser.error("resources requires the ollama provider")
            result = preflight(config, OllamaProvider())
        else:
            result = evaluate(provider=config.provider, profile=args.profile)
    except (ValueError, RetrievalError, ProviderFailure) as exc:
        parser.exit(1, f"Kermit model: {exc}\n")
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    elif args.command == "ask":
        print(result["answer"])
        if args.explain:
            print("Diagnostics: " + json.dumps({k: v for k, v in result.items() if k != "answer"}, ensure_ascii=False, sort_keys=True))
    elif args.command == "resources":
        print(result["message"])
    elif args.command == "health":
        print(f"{result['provider']} {result['model']}: {result['state']}")
    else:
        print(f"{result['passed']}/{result['questions']} deterministic checks passed")
        for row in result["rows"]:
            if not all(row["checks"].values()):
                print(f"FAIL {row['question']}: {row['checks']}")
    if args.command == "ask":
        if result.get("resource") and result["resource"]["state"] == "red":
            return 3
        return {"waiting_for_memory": 3, "confirmation_required": 4}.get(result["status"], 0)
    if args.command == "resources":
        return {"red": 3, "yellow": 4}.get(result["state"], 0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
