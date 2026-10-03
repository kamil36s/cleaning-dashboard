import argparse
import json

from .service import RetrievalError, retrieve


def main():
    parser = argparse.ArgumentParser(description="Read-only Kermit evidence retrieval")
    parser.add_argument("command", choices=("query",))
    parser.add_argument("question")
    parser.add_argument("--format", choices=("json", "text"), default="text")
    parser.add_argument("--explain", action="store_true")
    parser.add_argument("--subsystem-id")
    parser.add_argument("--page-id")
    parser.add_argument("--widget-id")
    parser.add_argument("--route")
    parser.add_argument("--entity-type")
    args = parser.parse_args()
    context = {k: v for k, v in (("subsystemId", args.subsystem_id), ("pageId", args.page_id),
                                  ("widgetId", args.widget_id), ("route", args.route), ("entityType", args.entity_type)) if v is not None}
    try:
        result = retrieve({"contractVersion": 1, "question": args.question, "optionalContext": context})
    except RetrievalError as exc:
        parser.exit(1, f"Kermit retrieval failed: {exc}\n")
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    else:
        print(f"Claim: {result['claimType']}; subsystems: {', '.join(s['id'] for s in result['candidateSubsystems'])}")
        for item in result["selectedEvidence"]:
            print(f"{item['evidenceId']} [{item['layer']}] {item['path']} {item['locator']} ({item['freshness']})")
            print(item.get("excerpt", item.get("metadata", {})))
        if result["conflicts"]:
            print("Findings: " + ", ".join(c["id"] for c in result["conflicts"]))
        if result["uncertainty"]:
            print("Limitations: " + "; ".join(result["uncertainty"]))
        if args.explain:
            print("Diagnostics: " + json.dumps(result["diagnostics"], ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
