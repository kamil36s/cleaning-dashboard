import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class BudgetCliSafetyTests(unittest.TestCase):
    def test_legacy_output_option_cannot_overwrite_a_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            csv_path = root / "fixture.csv"
            output_path = root / "protected.json"
            csv_path.write_text(
                "#Data operacji;#Opis operacji;#Rachunek;#Kategoria;#Kwota\n"
                "01.01.2026;Fixture;TEST 1234;Test;-1,00\n",
                encoding="utf-8",
            )
            output_path.write_text("do-not-overwrite", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "import_budget_csv.py"),
                    str(csv_path),
                    "--output",
                    str(output_path),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(output_path.read_text(encoding="utf-8"), "do-not-overwrite")


if __name__ == "__main__":
    unittest.main()
