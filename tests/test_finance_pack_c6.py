import sqlite3
import tempfile
import unittest
from pathlib import Path

from finance_review import category_required, normalize_grouping_description, semantic_transaction_kind
from finance_service import FinanceService


HEADER = "#Data operacji;#Opis operacji;#Rachunek;#Kategoria;#Kwota;#Saldo po operacji"


class FinancePackC6Tests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        (root / "settings").mkdir()
        self.database = root / "finance.sqlite"
        self.service = FinanceService(self.database)
        self.service.ensure_ready()

    def tearDown(self):
        self.temp_dir.cleanup()

    def import_rows(self, *rows):
        self.service.import_csv((HEADER + "\n" + "\n".join(rows) + "\n").encode(), "c6.csv")
        return self.service.compatibility_payload()["transactions"]

    def test_category_requirement_is_semantic(self):
        self.assertTrue(category_required("expense"))
        for kind in ("transfer", "salary", "saving", "refund", "cash", "income", "other", None):
            self.assertFalse(category_required(kind), kind)

        row = {"transaction_kind": "expense", "raw_description": "PRZELEW DO ODBIORCY", "raw_category": "PRZELEW ZEWNĘTRZNY WYCHODZĄCY", "amount_minor": -1000}
        self.assertEqual(semantic_transaction_kind(row), "transfer")

    def test_bank_boilerplate_normalization_preserves_entity(self):
        self.assertEqual(normalize_grouping_description("UBER.COM BLIK ZAKUP E-COMMERCE"), "uber.com")
        self.assertEqual(normalize_grouping_description("24.PLAY.PL BLIK ZAKUP E-COMMERCE"), "24.play.pl")
        self.assertEqual(normalize_grouping_description("BOLT POLAND SP. Z O.O. ZAKUP PRZY UŻYCIU KARTY - INTERNET"), "bolt poland sp. z o.o")

    def test_counts_distinguish_scope_issues_transactions_and_groups(self):
        rows = self.import_rows(
            "02.08.2026;OLD UNKNOWN;Konto;Bank;-10,00;90,00",
            "02.09.2026;CURRENT UNKNOWN;Konto;Bank;-12,00;78,00",
        )
        with sqlite3.connect(self.database) as connection:
            connection.execute("UPDATE transactions SET merchant_id=NULL,category_id=NULL,transaction_kind='expense'")
        metrics = self.service.review.metrics(month="2026-09")
        self.assertEqual(metrics["allHistory"]["transactions"], 2)
        self.assertEqual(metrics["allHistory"]["issues"], 4)
        self.assertEqual(metrics["selectedPeriod"]["transactions"], 1)
        self.assertEqual(metrics["selectedPeriod"]["groups"], 1)

    def test_repeated_normalized_merchant_groups_and_personal_transfers_stay_separate(self):
        rows = self.import_rows(
            "01.09.2026;UBER.COM BLIK ZAKUP E-COMMERCE;Konto;Bank;-10,00;90,00",
            "02.09.2026;UBER.COM ZAKUP PRZY UŻYCIU KARTY - INTERNET;Konto;Bank;-11,00;79,00",
            "03.09.2026;PRZELEW JAN ALFA;Konto;Bank;-20,00;59,00",
            "04.09.2026;PRZELEW JAN BETA;Konto;Bank;-21,00;38,00",
        )
        category = self.service.create_category({"name": "C6 taxi"})
        uber = next(row for row in rows if "BLIK" in row["description"])
        self.service.classify_manually(uber["id"], {"merchant": "Uber C6", "categoryId": category["id"], "transactionKind": "expense"})
        with sqlite3.connect(self.database) as connection:
            connection.execute("UPDATE transactions SET merchant_id=NULL,category_id=NULL,transaction_kind='expense' WHERE raw_description LIKE 'UBER.COM ZAKUP%'")
            connection.execute("UPDATE transactions SET merchant_id=NULL,category_id=NULL,transaction_kind=NULL WHERE raw_description LIKE 'PRZELEW JAN%'")
        result = self.service.review.groups(scope="selected_month", month="2026-09")
        uber_group = next(item for item in result["groups"] if "uber" in item["displayName"].lower())
        self.assertEqual(uber_group["transactionCount"], 2)
        personal = [item for item in result["groups"] if "przelew jan" in item["displayName"]]
        self.assertEqual(len(personal), 2)

    def test_history_strength_mixed_retailer_and_safe_application_undo(self):
        rows = self.import_rows(
            "01.09.2026;BIEDRONKA 100;Konto;Bank;-10,00;90,00",
            "02.09.2026;BIEDRONKA 100;Konto;Bank;-11,00;79,00",
            "03.09.2026;BIEDRONKA 100;Konto;Bank;-12,00;67,00",
        )
        broad = next(item for item in self.service.categories() if item["parentName"] == "Zakupy codzienne" and item["name"] == "Zakupy mieszane")
        for row in rows[:2]:
            self.service.classify_manually(row["id"], {"merchant": "Biedronka", "categoryId": broad["id"], "transactionKind": "expense"})
        with sqlite3.connect(self.database) as connection:
            target = rows[2]["id"]
            connection.execute("UPDATE transactions SET merchant_id=NULL,category_id=NULL,transaction_kind='expense' WHERE id=?", (target,))
        group = self.service.review.groups(scope="all_history", month="2026-09")["groups"][0]
        self.assertTrue(group["suggestion"]["mixedRetailer"])
        self.assertEqual(group["suggestion"]["categoryId"], broad["id"])
        payload = {"scope": "all_history", "month": "2026-09", "classification": {"merchantId": group["suggestion"]["merchantId"], "categoryId": broad["id"]}, "remember": True}
        preview = self.service.review.preview(group["id"], payload)
        self.assertEqual((preview["transactionCount"], preview["manualClassificationsOverwritten"]), (1, 0))
        applied = self.service.review.apply(group["id"], {**payload, "confirm": True})
        self.assertEqual((applied["applied"], applied["rememberMechanism"]), (1, "merchant_default"))
        with sqlite3.connect(self.database) as connection:
            classified = connection.execute("SELECT category_id FROM transactions WHERE id=?", (target,)).fetchone()[0]
        self.assertEqual(classified, broad["id"])
        undone = self.service.review.undo_latest()
        self.assertEqual(undone["restored"], 1)
        with sqlite3.connect(self.database) as connection:
            self.assertIsNone(connection.execute("SELECT category_id FROM transactions WHERE id=?", (target,)).fetchone()[0])
            self.assertIsNone(connection.execute("SELECT default_category_id FROM merchants WHERE canonical_name='Biedronka'").fetchone()[0])

    def test_historical_evidence_classes_unanimous_dominant_conflicting_and_insufficient(self):
        descriptions = []
        for prefix, count in (("EXACT", 4), ("DOMINANT", 6), ("MIXED", 5), ("SHORT", 2)):
            descriptions.extend(f"{prefix} {index}" for index in range(count))
        rows = self.import_rows(*[
            f"{index + 1:02d}.09.2026;{description};Konto;Bank;-10,00;90,00"
            for index, description in enumerate(descriptions)
        ])
        first = self.service.create_category({"name": "Evidence first"})
        second = self.service.create_category({"name": "Evidence second"})
        by_description = {row["description"]: row for row in rows}
        plans = {
            "EXACT": [first["id"], first["id"], first["id"], None],
            "DOMINANT": [first["id"], first["id"], first["id"], first["id"], second["id"], None],
            "MIXED": [first["id"], first["id"], second["id"], second["id"], None],
            "SHORT": [first["id"], None],
        }
        for prefix, categories in plans.items():
            for index, category_id in enumerate(categories):
                row = by_description[f"{prefix} {index}"]
                payload = {"merchant": f"Merchant {prefix}", "transactionKind": "expense"}
                if category_id is not None:
                    payload["categoryId"] = category_id
                self.service.classify_manually(row["id"], payload)
        result = self.service.review.groups(scope="all_history", month="2026-09")
        strengths = {item["displayName"]: item["suggestion"]["confidence"] for item in result["groups"]}
        self.assertEqual(strengths["Merchant EXACT"], "exact")
        self.assertEqual(strengths["Merchant DOMINANT"], "strong")
        self.assertEqual(strengths["Merchant MIXED"], "mixed")
        self.assertEqual(strengths["Merchant SHORT"], "mixed")

    def test_remember_uses_exact_rule_when_no_merchant_can_resolve_group(self):
        rows = self.import_rows("01.09.2026;ONE OFF SERVICE;Konto;Bank;-10,00;90,00")
        category = self.service.create_category({"name": "Exact rule target"})
        with sqlite3.connect(self.database) as connection:
            connection.execute("UPDATE transactions SET merchant_id=NULL,category_id=NULL,transaction_kind='expense' WHERE id=?", (rows[0]["id"],))
        group = self.service.review.groups(scope="all_history", month="2026-09")["groups"][0]
        payload = {"scope": "all_history", "month": "2026-09", "classification": {"categoryId": category["id"]}, "remember": True, "confirm": True}
        result = self.service.review.apply(group["id"], payload)
        self.assertEqual(result["rememberMechanism"], "exact_description_rule")
        self.assertEqual(len(self.service.rules()), 1)
        self.service.review.undo_latest()
        self.assertEqual(len(self.service.rules()), 0)


if __name__ == "__main__":
    unittest.main()
