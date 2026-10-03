"""Measure read paths for the Language product surfaces on a generated local fixture."""

from pathlib import Path
import json
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.benchmark_language_operations import fixture
from tests.test_language_api import LanguageApiTests
from tests.test_language_dictionary_phrasebook import FakeDictionary


def measure(call, count=20):
    samples = []
    result = None
    for _ in range(count):
        start = time.perf_counter()
        result = call()
        samples.append((time.perf_counter() - start) * 1000)
    return {"medianMs": round(statistics.median(samples), 2),
            "p95Ms": round(sorted(samples)[int(count * .95) - 1], 2),
            "payloadBytes": len(json.dumps(result).encode("utf-8"))}


def main():
    environment = LanguageApiTests()
    environment.setUp()
    try:
        fixture(environment.store, environment.profile["id"], lemmas=250, texts=12, events=500)
        environment.service.dictionary_provider = FakeDictionary()
        profile = environment.profile["id"]
        lemma = f"{1:032x}"
        result = {
            "fixture": {"lemmas": 251, "texts": 12, "knowledgeEvents": 500},
            "today": measure(lambda: environment.service.today_summary(profile)),
            "widget": measure(lambda: environment.service.widget_summary(profile)),
            "hoverPreview": measure(lambda: environment.service.get_lemma_preview(lemma)),
            "untrackedLookup": measure(lambda: environment.service.lookup_surface_preview(profile, "ukjent")),
            "fullLexicalDetailFakeProvider": measure(lambda: environment.service.get_lemma_lexical_detail(lemma)),
            "readerDocument": measure(lambda: environment.service.get_text(f"{100001:032x}")),
        }
        print(json.dumps(result, indent=2))
    finally:
        environment.tearDown()


if __name__ == "__main__":
    main()
