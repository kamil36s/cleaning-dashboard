import sqlite3
import tempfile
import unittest
from pathlib import Path

from finance_importer import assign_fingerprint, transaction_base_key
from finance_repository import FinanceRepository
from finance_service import FinanceService


def csv_bytes(rows):
    header = "#Data operacji;#Opis operacji;#Rachunek;#Kategoria;#Kwota;#Saldo po operacji"
    return (header + "\n" + "\n".join(rows) + "\n").encode("utf-8")


class FinanceFoundationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.database = self.root / "finance.sqlite"
        self.service = FinanceService(self.database)
        self.service.ensure_ready()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_versioned_schema_contains_foundation_tables_and_indexes(self):
        self.assertEqual(self.service.repository.schema_versions(), [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11])
        with sqlite3.connect(self.database) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            indexes = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'index'"
                )
            }
        self.assertTrue({
            "schema_version", "accounts", "import_batches", "transactions",
            "transaction_imports", "categories", "merchants", "merchant_aliases",
            "merchant_types", "classification_rules", "rule_conditions",
            "rule_actions", "review_decisions",
            "ambiguous_merchant_aliases",
            "account_match_aliases",
        }.issubset(tables))
        self.assertIn("idx_transactions_date", indexes)
        self.assertIn("idx_transaction_imports_batch", indexes)
        self.assertIn("idx_transactions_kind_date", indexes)

    def test_fingerprint_ignores_classification_and_balance(self):
        base = {
            "transaction_date": "2026-01-02",
            "amount_minor": -1234,
            "currency": "PLN",
            "raw_description": "Sklep testowy",
            "raw_account": "PL00 0000 0000 1234",
            "raw_category": "Old",
            "raw_balance_minor": 10000,
            "merchant": "Manual merchant",
        }
        changed = {
            **base,
            "raw_category": "New",
            "raw_balance_minor": 9000,
            "merchant": "Changed annotation",
        }
        self.assertEqual(transaction_base_key(base), transaction_base_key(changed))
        self.assertEqual(assign_fingerprint(base, 1), assign_fingerprint(changed, 1))
        self.assertNotEqual(assign_fingerprint(base, 1), assign_fingerprint(base, 2))

    def test_multiple_accounts_are_distinct_and_masked(self):
        self.service.import_csv(
            csv_bytes([
                "01.01.2026;A;PL00 0000 1111;Zakupy;-10,00;100,00",
                "01.01.2026;B;PL00 0000 2222;Zakupy;-20,00;80,00",
            ]),
            "accounts.csv",
        )
        accounts = self.service.repository.list_accounts()
        self.assertEqual(len(accounts), 2)
        self.assertEqual(
            {item["display_label"] for item in accounts},
            {"Konto główne", "Konto 2"},
        )
        self.assertTrue(all("PL00" not in item["display_label"] for item in accounts))

    def test_import_batch_records_required_metadata(self):
        result = self.service.import_csv(
            csv_bytes([
                "01.01.2026;A;Konto 1234;Zakupy;-10,00;100,00",
                "bad-date;B;Konto 1234;Zakupy;-20,00;80,00",
            ]),
            "history.csv",
        )
        batch = self.service.repository.list_batches()[0]
        self.assertEqual(batch["id"], result["batchId"])
        self.assertEqual(batch["filename"], "history.csv")
        self.assertEqual(batch["row_count"], 2)
        self.assertEqual(batch["accepted_count"], 1)
        self.assertEqual(batch["duplicate_count"], 0)
        self.assertEqual(batch["invalid_count"], 1)
        self.assertEqual(batch["date_from"], "2026-01-01")
        self.assertEqual(batch["date_to"], "2026-01-01")
        self.assertEqual(batch["status"], "completed")


if __name__ == "__main__":
    unittest.main()
