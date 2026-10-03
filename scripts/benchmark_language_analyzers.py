"""Repeatable, read-only Phase 0 benchmark over the committed Bokmål oracle."""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import importlib
import importlib.metadata
import json
from pathlib import Path
import platform
import statistics
import sys
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from language_learning.analysis import NorwegianBokmalStanzaAnalyzer  # noqa: E402
from language_learning.analysis.base import normalize_lookup  # noqa: E402
from language_learning.schemas import AnalysisDocument, AnalyzerHealthState  # noqa: E402


FIXTURE_PATH = ROOT / "tests" / "fixtures" / "language" / "nb" / "phase0_bokmal_cases.json"


def rss_bytes() -> int | None:
    if sys.platform == "win32":
        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        get_current_process = ctypes.windll.kernel32.GetCurrentProcess
        get_current_process.restype = wintypes.HANDLE
        get_process_memory_info = ctypes.windll.psapi.GetProcessMemoryInfo
        get_process_memory_info.argtypes = (
            wintypes.HANDLE,
            ctypes.POINTER(ProcessMemoryCounters),
            wintypes.DWORD,
        )
        get_process_memory_info.restype = wintypes.BOOL
        process = get_current_process()
        if get_process_memory_info(process, ctypes.byref(counters), counters.cb):
            return int(counters.WorkingSetSize)
        return None
    try:
        import resource

        value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(value if sys.platform == "darwin" else value * 1024)
    except (ImportError, OSError):
        return None


def load_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def all_tokens(document: AnalysisDocument) -> list[Any]:
    return [token for sentence in document.sentences for token in sentence.tokens]


def expected_token(document: AnalysisDocument, expected: dict[str, Any]) -> Any | None:
    matches = [token for token in all_tokens(document) if token.surface == expected["surface"]]
    occurrence = int(expected.get("occurrence", 1))
    return matches[occurrence - 1] if len(matches) >= occurrence else None


def evaluate_stanza_oracle(
    fixture: dict[str, Any], documents: dict[str, AnalysisDocument]
) -> dict[str, Any]:
    metrics = {
        "sentence": [0, 0],
        "tokenFound": [0, 0],
        "kind": [0, 0],
        "normalizedLookup": [0, 0],
        "lemma": [0, 0],
        "pos": [0, 0],
        "morphologyFeature": [0, 0],
    }
    failures: list[dict[str, Any]] = []
    exact_offset_tokens = 0
    token_count = 0

    def check(metric: str, expected: Any, actual: Any, context: dict[str, Any]) -> None:
        metrics[metric][1] += 1
        if expected == actual:
            metrics[metric][0] += 1
        else:
            failures.append({**context, "field": metric, "expected": expected, "actual": actual})

    for case in fixture["cases"]:
        document = documents[case["id"]]
        document.validate()
        for token in all_tokens(document):
            token_count += 1
            if case["text"][token.start : token.end] == token.surface:
                exact_offset_tokens += 1
        for index, expected_sentence in enumerate(case.get("expectedSentenceTexts", [])):
            actual = document.sentences[index].text if len(document.sentences) > index else None
            check("sentence", expected_sentence, actual, {"case": case["id"], "index": index})
        for expected in case.get("expectedTokens", []):
            token = expected_token(document, expected)
            context = {"case": case["id"], "surface": expected["surface"]}
            check("tokenFound", True, token is not None, context)
            if token is None:
                continue
            check("kind", expected["kind"], token.kind.value, context)
            if "normalizedLookup" in expected:
                check("normalizedLookup", expected["normalizedLookup"], token.normalized_lookup, context)
            if "lemma" in expected:
                check("lemma", expected["lemma"], token.selected_lemma, context)
            if "pos" in expected:
                check("pos", expected["pos"], token.pos, context)
            elif "posAnyOf" in expected:
                metrics["pos"][1] += 1
                if token.pos in expected["posAnyOf"]:
                    metrics["pos"][0] += 1
                else:
                    failures.append(
                        {**context, "field": "pos", "expected": expected["posAnyOf"], "actual": token.pos}
                    )
            for key, expected_value in expected.get("morphologyContains", {}).items():
                check(
                    "morphologyFeature",
                    expected_value,
                    token.morphology.get(key),
                    {**context, "feature": key},
                )

    return {
        "metrics": {
            key: {
                "correct": value[0],
                "total": value[1],
                "percent": round(100 * value[0] / value[1], 2) if value[1] else None,
            }
            for key, value in metrics.items()
        },
        "offsets": {
            "exact": exact_offset_tokens,
            "total": token_count,
            "percent": round(100 * exact_offset_tokens / token_count, 2) if token_count else None,
        },
        "failures": failures,
    }


def benchmark_stanza(fixture: dict[str, Any], repetitions: int) -> dict[str, Any]:
    memory_before = rss_bytes()
    started = time.perf_counter()
    analyzer = NorwegianBokmalStanzaAnalyzer()
    health = analyzer.health(verify_load=True)
    cold_seconds = time.perf_counter() - started
    memory_after_load = rss_bytes()
    if health.state is not AnalyzerHealthState.AVAILABLE:
        return {
            "available": False,
            "health": health.state.value,
            "guidance": health.guidance,
            "coldInitializationSeconds": round(cold_seconds, 4),
        }

    documents: dict[str, AnalysisDocument] = {}
    run_seconds: list[float] = []
    for repetition in range(repetitions):
        run_started = time.perf_counter()
        current = {
            case["id"]: analyzer.analyze(case["text"], language_code=fixture["languageCode"])
            for case in fixture["cases"]
        }
        run_seconds.append(time.perf_counter() - run_started)
        if repetition == 0:
            documents = current
    memory_after_analysis = rss_bytes()
    evaluation = evaluate_stanza_oracle(fixture, documents)
    total_characters = sum(len(case["text"]) for case in fixture["cases"])
    total_tokens = sum(len(all_tokens(document)) for document in documents.values())

    return {
        "available": True,
        "health": health.state.value,
        "packageVersion": health.package_version,
        "modelVersion": health.model_version,
        "modelFingerprint": health.details.get("modelFingerprint"),
        "processorPackages": health.details.get("resourceManifest"),
        "downloadMethod": health.details.get("downloadMethod"),
        "mwtRequired": health.details.get("mwtRequired"),
        "coldInitializationSeconds": round(cold_seconds, 4),
        "warmCorpusSeconds": [round(value, 4) for value in run_seconds],
        "warmCorpusMedianSeconds": round(statistics.median(run_seconds), 4),
        "fixtureCharacters": total_characters,
        "fixtureTokens": total_tokens,
        "approximateRssDeltaLoadMiB": (
            round((memory_after_load - memory_before) / 1024 / 1024, 2)
            if memory_before is not None and memory_after_load is not None
            else None
        ),
        "approximateRssDeltaAfterAnalysisMiB": (
            round((memory_after_analysis - memory_before) / 1024 / 1024, 2)
            if memory_before is not None and memory_after_analysis is not None
            else None
        ),
        "metadata": {
            "tokenization": True,
            "sentenceBoundaries": True,
            "pos": True,
            "morphology": True,
            "contextualLemma": True,
            "alternativeCandidates": False,
            "tokenConfidence": False,
            "lexiconMembership": False,
        },
        "oracle": evaluation,
    }


def benchmark_simplemma(fixture: dict[str, Any]) -> dict[str, Any]:
    memory_before = rss_bytes()
    started = time.perf_counter()
    try:
        simplemma = importlib.import_module("simplemma")
        package_version = importlib.metadata.version("simplemma")
    except Exception as exc:
        return {"available": False, "error": f"{type(exc).__name__}: {exc}"}

    comparisons: list[dict[str, Any]] = []
    for case in fixture["cases"]:
        for expected in case.get("expectedTokens", []):
            if "lemma" not in expected:
                continue
            actual = normalize_lookup(simplemma.lemmatize(expected["surface"], lang="nb"))
            wanted = normalize_lookup(expected["lemma"])
            comparisons.append(
                {
                    "case": case["id"],
                    "surface": expected["surface"],
                    "expected": wanted,
                    "actual": actual,
                    "correct": wanted == actual,
                }
            )
    elapsed = time.perf_counter() - started
    memory_after = rss_bytes()
    correct = sum(1 for item in comparisons if item["correct"])
    return {
        "available": True,
        "packageVersion": package_version,
        "startupAndFixtureSeconds": round(elapsed, 4),
        "approximateRssDeltaMiB": (
            round((memory_after - memory_before) / 1024 / 1024, 2)
            if memory_before is not None and memory_after is not None
            else None
        ),
        "lemmaCorrect": correct,
        "lemmaTotal": len(comparisons),
        "lemmaPercent": round(100 * correct / len(comparisons), 2) if comparisons else None,
        "failures": [item for item in comparisons if not item["correct"]],
        "metadata": {
            "tokenizationUsed": False,
            "sentenceBoundariesUsed": False,
            "pos": False,
            "morphology": False,
            "contextualLemma": False,
            "alternativeCandidates": False,
            "tokenConfidence": False,
            "lexiconMembership": True,
            "offline": True,
        },
    }


def build_report(repetitions: int) -> dict[str, Any]:
    fixture = load_fixture()
    return {
        "benchmarkVersion": "language-phase0-benchmark/v1",
        "fixtureVersion": fixture["fixtureVersion"],
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "torch": _optional_version("torch"),
        },
        "stanza": benchmark_stanza(fixture, repetitions),
        "simplemma": benchmark_simplemma(fixture),
    }


def _optional_version(distribution: str) -> str | None:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return None


def print_human(report: dict[str, Any]) -> None:
    stanza = report["stanza"]
    simplemma = report["simplemma"]
    print("Language Learning Phase 0 Bokmål benchmark")
    print("=" * 78)
    print(f"Fixture            {report['fixtureVersion']}")
    print(f"Environment        Python {report['environment']['python']} on {report['environment']['platform']}")
    if stanza.get("available"):
        oracle = stanza["oracle"]
        print(
            f"Stanza             {stanza['packageVersion']} / {stanza['modelVersion']} "
            f"cold={stanza['coldInitializationSeconds']}s "
            f"warm median={stanza['warmCorpusMedianSeconds']}s"
        )
        print(
            f"Stanza offsets     {oracle['offsets']['exact']}/{oracle['offsets']['total']} "
            f"({oracle['offsets']['percent']}%)"
        )
        for name, metric in oracle["metrics"].items():
            print(f"Stanza {name:<16} {metric['correct']}/{metric['total']} ({metric['percent']}%)")
        for failure in oracle["failures"]:
            print("  deviation:", json.dumps(failure, ensure_ascii=False, sort_keys=True))
    else:
        print(f"Stanza             UNAVAILABLE: {stanza.get('guidance') or stanza.get('error')}")
    if simplemma.get("available"):
        print(
            f"Simplemma          {simplemma['packageVersion']} lemma={simplemma['lemmaCorrect']}/"
            f"{simplemma['lemmaTotal']} ({simplemma['lemmaPercent']}%) "
            f"startup+fixture={simplemma['startupAndFixtureSeconds']}s"
        )
        for failure in simplemma["failures"]:
            print("  miss:", json.dumps(failure, ensure_ascii=False, sort_keys=True))
    else:
        print(f"Simplemma          UNAVAILABLE: {simplemma.get('error')}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    parser.add_argument("--repetitions", type=int, default=3, choices=range(1, 11))
    args = parser.parse_args()
    report = build_report(args.repetitions)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print_human(report)
    return 0 if report["stanza"].get("available") else 1


if __name__ == "__main__":
    raise SystemExit(main())
