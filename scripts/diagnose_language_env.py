"""Read-only diagnostics for the Language Learning Phase 0 toolchain.

This script never installs packages, downloads models, writes language data, or
performs Anki mutations. The only network-shaped operation is a short request
to an explicitly loopback AnkiConnect URL using its read-only ``version`` action.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import sys
from typing import Any
from urllib import error, parse, request


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from language_learning.analysis import NorwegianBokmalStanzaAnalyzer  # noqa: E402
from language_learning.schemas import AnalyzerHealthState  # noqa: E402


ANKI_DEFAULT_URL = "http://127.0.0.1:8765"
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def package_status(distribution: str, module: str) -> dict[str, Any]:
    try:
        imported = importlib.import_module(module)
        version = importlib.metadata.version(distribution)
        return {"available": True, "version": version, "error": None, "module": imported.__name__}
    except Exception as exc:
        return {
            "available": False,
            "version": None,
            "error": f"{type(exc).__name__}: {exc}",
            "module": module,
        }


def wordfreq_status() -> dict[str, Any]:
    package = package_status("wordfreq", "wordfreq")
    if not package["available"]:
        return package
    try:
        wordfreq = importlib.import_module("wordfreq")
        supported = "nb" in wordfreq.available_languages()
        samples = {
            word: wordfreq.zipf_frequency(word, "nb")
            for word in ("jobb", "jobben", "jobber", "jobbene", "ærlig", "øl")
        }
        package.update(
            {
                "nbSupported": supported,
                "metric": "Zipf frequency score only",
                "samples": samples,
                "rankPolicy": "No Top-N lemma rank inferred; external ranked frequency dataset required.",
            }
        )
    except Exception as exc:
        package.update({"nbSupported": False, "error": f"{type(exc).__name__}: {exc}"})
    return package


def simplemma_status() -> dict[str, Any]:
    package = package_status("simplemma", "simplemma")
    if not package["available"]:
        return package
    try:
        simplemma = importlib.import_module("simplemma")
        package.update(
            {
                "nbProbe": {
                    surface: simplemma.lemmatize(surface, lang="nb")
                    for surface in ("jobb", "jobben", "jobber", "jobbene")
                },
                "role": "comparison only; not a canonical or fallback adapter",
            }
        )
    except Exception as exc:
        package["error"] = f"{type(exc).__name__}: {exc}"
    return package


def anki_status(url: str, api_key: str | None, *, timeout: float = 1.5) -> dict[str, Any]:
    parsed = parse.urlparse(url)
    result: dict[str, Any] = {
        "configuredUrl": url,
        "apiKeyConfigured": bool(api_key),
        "reachable": False,
        "apiVersion": None,
        "nonBlocking": True,
        "action": "version (read-only)",
    }
    if parsed.scheme != "http" or parsed.hostname not in LOOPBACK_HOSTS:
        result["error"] = "Only an explicit loopback HTTP AnkiConnect URL is allowed in Phase 0."
        return result

    payload: dict[str, Any] = {"action": "version", "version": 5}
    if api_key:
        payload["key"] = api_key
    body = json.dumps(payload).encode("utf-8")
    probe = request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(probe, timeout=timeout) as response:
            decoded = json.loads(response.read().decode("utf-8"))
        if decoded.get("error"):
            result["error"] = str(decoded["error"])
        else:
            result["reachable"] = True
            result["apiVersion"] = decoded.get("result")
    except (error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def build_report(*, verify_model_load: bool = True) -> dict[str, Any]:
    analyzer = NorwegianBokmalStanzaAnalyzer()
    health = analyzer.health(verify_load=verify_model_load)
    report = {
        "diagnosticVersion": "language-phase0-diagnostic/v1",
        "readOnly": True,
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
        },
        "canonicalAnalyzer": {
            "id": health.analyzer_id,
            "state": health.state.value,
            "packageVersion": health.package_version,
            "modelVersion": health.model_version,
            "processors": list(health.processors),
            "details": dict(health.details),
            "guidance": health.guidance,
        },
        "wordfreq": wordfreq_status(),
        "simplemma": simplemma_status(),
        "ankiConnect": anki_status(
            os.environ.get("LANGUAGE_ANKICONNECT_URL", ANKI_DEFAULT_URL).strip() or ANKI_DEFAULT_URL,
            os.environ.get("LANGUAGE_ANKICONNECT_KEY") or None,
        ),
        "configuration": {
            "LANGUAGE_STANZA_MODEL_DIR": "configured"
            if os.environ.get("LANGUAGE_STANZA_MODEL_DIR")
            else "default",
            "LANGUAGE_ANKICONNECT_URL": "configured"
            if os.environ.get("LANGUAGE_ANKICONNECT_URL")
            else "default loopback",
            "LANGUAGE_ANKICONNECT_KEY": "configured"
            if os.environ.get("LANGUAGE_ANKICONNECT_KEY")
            else "not configured",
        },
    }
    wordfreq_ready = bool(report["wordfreq"].get("available")) and bool(
        report["wordfreq"].get("nbSupported")
    )
    report["overall"] = (
        "READY"
        if health.state is AnalyzerHealthState.AVAILABLE and wordfreq_ready
        else "INCOMPLETE"
    )
    return report


def print_human(report: dict[str, Any]) -> None:
    print("Language Learning Phase 0 environment report")
    print("=" * 78)
    print(f"Python             {report['python']['version']} ({report['python']['platform']})")
    analyzer = report["canonicalAnalyzer"]
    print(
        f"Canonical analyzer {analyzer['state']}: {analyzer['id']} "
        f"package={analyzer['packageVersion'] or 'missing'} "
        f"model={analyzer['modelVersion'] or 'missing'}"
    )
    print(f"Processors         {','.join(analyzer['processors'])}")
    print(f"Download policy    {analyzer['details'].get('downloadMethod', 'not loaded')}")
    if analyzer.get("guidance"):
        print(f"Analyzer guidance  {analyzer['guidance']}")

    wordfreq = report["wordfreq"]
    print(
        f"wordfreq           {'AVAILABLE' if wordfreq.get('available') else 'UNAVAILABLE'} "
        f"version={wordfreq.get('version') or 'missing'} nb={wordfreq.get('nbSupported', False)}"
    )
    if wordfreq.get("samples"):
        print("wordfreq samples   " + ", ".join(f"{key}={value}" for key, value in wordfreq["samples"].items()))
    print(f"Rank policy        {wordfreq.get('rankPolicy', 'not evaluated')}")

    simplemma = report["simplemma"]
    print(
        f"Simplemma          {'AVAILABLE' if simplemma.get('available') else 'UNAVAILABLE'} "
        f"version={simplemma.get('version') or 'missing'} ({simplemma.get('role', 'comparison unavailable')})"
    )
    anki = report["ankiConnect"]
    print(
        f"AnkiConnect        {'REACHABLE' if anki['reachable'] else 'UNAVAILABLE'} "
        f"version={anki.get('apiVersion') or 'unknown'} (non-blocking, read-only probe)"
    )
    if anki.get("error"):
        print(f"Anki detail        {anki['error']}")
    print(f"Secret state       Anki key {report['configuration']['LANGUAGE_ANKICONNECT_KEY']}")
    print(f"\nOverall: {report['overall']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    parser.add_argument(
        "--no-model-load",
        action="store_true",
        help="Check model files without loading the canonical pipeline",
    )
    args = parser.parse_args()
    report = build_report(verify_model_load=not args.no_model_load)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print_human(report)
    return 0 if report["overall"] == "READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())

