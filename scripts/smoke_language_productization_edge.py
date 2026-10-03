"""Real Edge productization screenshots against an isolated Language fixture."""

from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.benchmark_language_operations import fixture
from tests.test_language_api import LanguageApiTests


def main() -> None:
    environment = LanguageApiTests()
    environment.setUp()
    try:
        fixture(environment.store, environment.profile["id"], lemmas=250, texts=12, events=500)
        with environment.store.connection() as db:
            # Exercise the seven Reader states without changing the canonical fixture.
            for index, (state, disposition) in enumerate((
                ("NEW", "TRACKED"), ("LEARNING", "TRACKED"),
                ("KNOWN", "TRACKED"), ("MASTERED", "TRACKED"),
                ("NEW", "IGNORED"), ("NEW", "EXCLUDED"),
            )):
                db.execute("UPDATE lemma_knowledge SET knowledge_status=?,disposition=? WHERE lemma_id=?",
                           (state, disposition, f"{index + 21:032x}"))
            db.execute("UPDATE text_tokens SET selected_lemma_id=NULL,resolution_state='UNRESOLVED' WHERE id=?",
                       (f"{300000 + 27:032x}",))
            db.execute("UPDATE text_tokens SET selected_lemma_id=? WHERE id=?",
                       (f"{21:032x}", f"{300000 + 30:032x}"))
        url = f"http://127.0.0.1:{environment.port}/language.html#overview"
        driver = ROOT / "scripts/smoke_language_productization_cdp.mjs"
        output = ROOT / "reports/language-productization"
        output.mkdir(parents=True, exist_ok=True)
        for width, height in ((2048, 1010), (1440, 1000), (430, 900), (390, 844)):
            if len(sys.argv) > 1 and width != int(sys.argv[1]):
                continue
            subprocess.run(["node", str(driver), url, str(width), str(height), str(output)],
                           check=True, timeout=180, cwd=ROOT)
    finally:
        environment.tearDown()


if __name__ == "__main__":
    main()
