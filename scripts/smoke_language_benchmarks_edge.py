"""Isolated headless Edge smoke for the Language benchmark route."""

from __future__ import annotations

import pathlib
import subprocess
import tempfile

from tests.test_language_api import LanguageApiTests
from language_learning.assessment import load_content


def main() -> None:
    edge = pathlib.Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
    if not edge.is_file():
        raise SystemExit("Edge is not installed")
    fixture = LanguageApiTests()
    fixture.setUp()
    try:
        run = fixture.service.start_benchmark(fixture.profile["id"])["data"]
        routes = ["#benchmarks", f"#benchmarks/run/{run['id']}"]
        for width, height in ((1440, 1000), (390, 844)):
            for route in routes:
                with tempfile.TemporaryDirectory() as profile:
                    command = [str(edge), "--headless=new", "--disable-gpu", "--no-first-run",
                               "--disable-extensions", "--virtual-time-budget=12000",
                               f"--window-size={width},{height}", f"--user-data-dir={profile}",
                               "--dump-dom", f"http://127.0.0.1:{fixture.port}/language.html{route}"]
                    result = subprocess.run(command, capture_output=True, text=True, timeout=35, errors="replace")
                    html = result.stdout
                    expected = "Norway Preparation" if route == "#benchmarks" else "Vocabulary recognition"
                    ok = result.returncode == 0 and expected in html and "language-benchmark-card" in html
                    print(f"{width}x{height} {route}: {'PASS' if ok else 'FAIL'} ({result.returncode})")
                    if not ok:
                        print(result.stderr[-500:])
                        raise SystemExit(1)
        keys = {item["id"]: item["answer"] for item in load_content()[0]["forms"][run["formId"]]}
        for item in run["items"]:
            if item["dimension"] == "LISTENING":
                continue
            fixture.service.benchmark_response(fixture.profile["id"], run["id"], {
                "itemId": item["id"], "response": keys[item["id"]]
            })
        with tempfile.TemporaryDirectory() as profile:
            result = subprocess.run(
                [str(edge), "--headless=new", "--disable-gpu", "--no-first-run",
                 "--virtual-time-budget=12000", "--window-size=390,844",
                 f"--user-data-dir={profile}", "--dump-dom",
                 f"http://127.0.0.1:{fixture.port}/language.html#benchmarks/run/{run['id']}"],
                capture_output=True, text=True, timeout=35, errors="replace",
            )
            html = result.stdout
            ok = result.returncode == 0 and "13 / 16 answered" in html and (
                "Play audio" in html or "Mark Listening unavailable" in html
            )
            print(f"390x844 Listening capability branch: {'PASS' if ok else 'FAIL'}")
            if not ok:
                raise SystemExit(1)
        for item in run["items"]:
            if item["dimension"] != "LISTENING":
                continue
            fixture.service.benchmark_response(fixture.profile["id"], run["id"], {
                "itemId": item["id"], "response": keys[item["id"]]
            })
        fixture.service.complete_benchmark(fixture.profile["id"], run["id"])
        fixture.service.start_benchmark(fixture.profile["id"])
        with tempfile.TemporaryDirectory() as profile:
            result = subprocess.run(
                [str(edge), "--headless=new", "--disable-gpu", "--no-first-run",
                 "--virtual-time-budget=12000", "--window-size=390,844",
                 f"--user-data-dir={profile}", "--dump-dom",
                 f"http://127.0.0.1:{fixture.port}/language.html#benchmarks/run/{run['id']}"],
                capture_output=True, text=True, timeout=35, errors="replace",
            )
            html = result.stdout
            ok = result.returncode == 0 and all(label in html for label in (
                "Vocabulary recognition", "Cloze", "Reading comprehension", "Listening comprehension",
                "6 / 6", "4 / 4", "3 / 3",
            )) and "global score" not in html.lower()
            print(f"390x844 completed baseline + checkpoint available: {'PASS' if ok else 'FAIL'}")
            if not ok:
                raise SystemExit(1)
    finally:
        fixture.tearDown()


if __name__ == "__main__":
    main()
