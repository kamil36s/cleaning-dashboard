"""Isolated Phase 12 real-Edge navigation and layout smoke."""

from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.benchmark_language_operations import fixture as synthetic_fixture
from tests.test_language_api import LanguageApiTests


def main() -> None:
    environment = LanguageApiTests()
    environment.setUp()
    try:
        synthetic_fixture(environment.store, environment.profile["id"],
                          lemmas=250, texts=12, events=500)
        url = f"http://127.0.0.1:{environment.port}/language.html#overview"
        driver = ROOT / "scripts/smoke_language_phase12_cdp.mjs"
        for width, height in ((1440, 1000), (430, 900), (390, 844)):
            subprocess.run(["node", str(driver), url, str(width), str(height)],
                           check=True, timeout=90, cwd=ROOT)
    finally:
        environment.tearDown()


if __name__ == "__main__":
    main()
