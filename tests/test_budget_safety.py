import tempfile
import unittest
from pathlib import Path

import server
from finance_repository import FinanceError, FinanceStorageError
from finance_service import FinanceService


class BudgetSafetyTests(unittest.TestCase):
    def test_finance_runtime_files_are_not_static(self):
        protected = (
            "/data/budget.json",
            "/data/%62udget.json",
            "/data/finance.sqlite",
            "/data/finance.sqlite-wal",
            "/data/budget-backups/budget.json",
            "/data/settings/bills.json",
            "/data/backups/finance/budget.json",
        )
        for path in protected:
            with self.subTest(path=path):
                self.assertTrue(server.is_protected_static_path(path))

        self.assertFalse(server.is_protected_static_path("/budget.html"))

    def test_corrupt_existing_budget_storage_is_an_error(self):
        with tempfile.TemporaryDirectory() as directory:
            corrupt = Path(directory) / "finance.sqlite"
            corrupt.write_bytes(b"not-a-sqlite-database")
            with self.assertRaisesRegex(FinanceStorageError, "corrupt"):
                FinanceService(corrupt).ensure_ready()
            self.assertEqual(corrupt.read_bytes(), b"not-a-sqlite-database")

    def test_missing_budget_storage_is_a_clean_first_run(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "finance.sqlite"
            payload = FinanceService(missing).compatibility_payload()
            self.assertEqual(payload["transactions"], [])
            self.assertTrue(missing.exists())

    def test_legacy_full_snapshot_write_is_disabled(self):
        with self.assertRaisesRegex(FinanceError, "disabled"):
            server.write_budget_payload({"transactions": []})


if __name__ == "__main__":
    unittest.main()
