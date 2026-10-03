"""Run the full benchmark browser flow against an isolated Language API fixture."""

from pathlib import Path
import subprocess

from tests.test_language_api import LanguageApiTests


def main() -> None:
    fixture = LanguageApiTests()
    fixture.setUp()
    try:
        script = Path(__file__).with_name("smoke_language_benchmarks_cdp.mjs")
        url = f"http://127.0.0.1:{fixture.port}/language.html#benchmarks"
        subprocess.run(["node", str(script), url], check=True, timeout=120)
    finally:
        fixture.tearDown()


if __name__ == "__main__":
    main()
