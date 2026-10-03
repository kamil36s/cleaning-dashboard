import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from finance_service import FinanceMigrationError, FinanceService


class FinanceMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.legacy = self.root / "budget.json"
        self.database = self.root / "finance.sqlite"
        self.backups = self.root / "backups"

    def tearDown(self):
        self.temp_dir.cleanup()

    def fixture(self):
        return {
            "source": {
                "name": "fixture.csv",
                "importedAt": "2026-05-10T10:00:00+00:00",
                "rows": 3,
            },
            "settings": {
                "userCategories": ["Custom"],
                "merchantTypes": ["Custom type"],
                "rejectedSuggestionKeys": ["candidate:test"],
            },
            "transactions": [
                {
                    "id": "legacy-mutable-id-1",
                    "date": "2026-01-01",
                    "description": "Fixture A",
                    "account": "TEST ACCOUNT 1111",
                    "category": "Old category",
                    "amount": -10.25,
                    "balanceAfter": 90.75,
                    "currency": "PLN",
                    "merchant": "Merchant",
                    "merchantType": "Shop",
                    "userCategory": "Custom",
                    "note": "Annotation",
                },
                {
                    "id": "legacy-mutable-id-2",
                    "date": "2026-01-02",
                    "description": "Fixture B",
                    "account": "TEST ACCOUNT 1111",
                    "category": "Income",
                    "amount": 100.00,
                    "balanceAfter": 190.75,
                    "currency": "PLN",
                    "merchant": "",
                    "merchantType": "",
                    "userCategory": "Salary",
                    "note": "",
                },
                {
                    "id": "legacy-mutable-id-3",
                    "date": "2026-01-03",
                    "description": "Fixture C",
                    "account": "TEST ACCOUNT 2222",
                    "category": "Fee",
                    "amount": -0.75,
                    "balanceAfter": None,
                    "currency": "PLN",
                    "merchant": "Bank",
                    "merchantType": "Bank",
                    "userCategory": "Fees",
                    "note": "",
                },
            ],
        }

    def service(self):
        return FinanceService(
            self.database,
            legacy_json_path=self.legacy,
            backup_directory=self.backups,
        )

    def test_json_migration_is_verified_backed_up_and_idempotent(self):
        payload = self.fixture()
        original = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.legacy.write_bytes(original)

        first = self.service()
        verification = first.ensure_ready()

        self.assertEqual(verification["before"], verification["after"])
        self.assertEqual(verification["after"]["count"], 3)
        self.assertEqual(verification["after"]["date_min"], "2026-01-01")
        self.assertEqual(verification["after"]["date_max"], "2026-01-03")
        self.assertEqual(verification["after"]["signed_minor"], 8900)
        self.assertEqual(verification["after"]["negative_minor"], -1100)
        self.assertEqual(verification["after"]["positive_minor"], 10000)
        self.assertEqual(verification["after"]["annotations"], {
            "merchant": 2,
            "merchantType": 2,
            "userCategory": 3,
            "note": 1,
        })
        self.assertEqual(self.legacy.read_bytes(), original)
        backup_files = list(self.backups.glob("budget.before-sqlite-*.json"))
        self.assertEqual(len(backup_files), 1)
        self.assertEqual(
            hashlib.sha256(backup_files[0].read_bytes()).hexdigest(),
            hashlib.sha256(original).hexdigest(),
        )

        compatible = first.compatibility_payload()
        self.assertEqual(len(compatible["transactions"]), 3)
        annotated = next(row for row in compatible["transactions"] if row["note"])
        self.assertEqual(annotated["merchant"], "Merchant")
        self.assertEqual(annotated["merchantType"], "Shop")
        self.assertEqual(annotated["userCategory"], "Do ustalenia")
        self.assertEqual(annotated["legacyCategory"], "Custom")
        self.assertNotEqual(annotated["id"], "legacy-mutable-id-1")
        self.assertEqual(compatible["settings"]["rejectedSuggestionKeys"], ["candidate:test"])

        second = self.service()
        repeated = second.ensure_ready()
        self.assertEqual(repeated, verification)
        self.assertEqual(second.repository.transaction_count(), 3)
        self.assertEqual(len(list(self.backups.glob("budget.before-sqlite-*.json"))), 1)

    def test_corrupt_legacy_file_is_not_replaced_or_treated_as_empty(self):
        self.legacy.write_text("{broken", encoding="utf-8")
        service = self.service()
        with self.assertRaisesRegex(FinanceMigrationError, "corrupt"):
            service.ensure_ready()
        self.assertEqual(self.legacy.read_text(encoding="utf-8"), "{broken")
        self.assertEqual(service.repository.transaction_count(), 0)
        self.assertEqual(list(self.backups.glob("*")), [])

    def test_existing_database_without_marker_stops_ambiguous_migration(self):
        initial = FinanceService(self.database)
        initial.ensure_ready()
        initial.import_csv(
            (
                "#Data operacji;#Opis operacji;#Rachunek;#Kategoria;#Kwota\n"
                "01.01.2026;Existing;TEST 1111;Test;-1,00\n"
            ).encode("utf-8"),
            "existing.csv",
        )
        self.legacy.write_text(json.dumps(self.fixture()), encoding="utf-8")

        with self.assertRaisesRegex(FinanceMigrationError, "ambiguous"):
            self.service().ensure_ready()
        self.assertEqual(initial.repository.transaction_count(), 1)
        self.assertEqual(list(self.backups.glob("*")), [])

    def test_browser_legacy_bridge_is_one_shot_and_backed_up(self):
        service = FinanceService(self.database, backup_directory=self.backups)
        service.ensure_ready()
        verification = service.migrate_browser_legacy_payload(self.fixture())
        self.assertEqual(verification["before"], verification["after"])
        self.assertEqual(service.repository.transaction_count(), 3)
        self.assertTrue(list(self.backups.glob("browser-legacy-source-*.json")))
        with self.assertRaisesRegex(Exception, "empty finance database"):
            service.migrate_browser_legacy_payload(self.fixture())


if __name__ == "__main__":
    unittest.main()
