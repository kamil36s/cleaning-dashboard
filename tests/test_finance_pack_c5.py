import sqlite3
import tempfile
import unittest
from pathlib import Path

from finance_service import FinanceService


HEADER = "#Data operacji;#Opis operacji;#Rachunek;#Kategoria;#Kwota;#Saldo po operacji"


class FinancePackC5Tests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        (self.root / "settings").mkdir()
        self.database = self.root / "finance.sqlite"
        self.service = FinanceService(self.database)
        self.service.ensure_ready()

    def tearDown(self):
        self.temp_dir.cleanup()

    def import_rows(self, *rows):
        return self.service.import_csv((HEADER + "\n" + "\n".join(rows) + "\n").encode(), "c5.csv")

    def annotate(self, **values):
        transaction = self.service.compatibility_payload()["transactions"][0]
        self.service.repository.update_annotations([{"id": transaction["id"], "merchant": "", "merchantType": "", "userCategory": "", "note": "", **values}])
        self.service.repository.initialize()
        return self.service.compatibility_payload()["transactions"][0]

    def test_privacy_discards_raw_account_and_reimport_is_stable(self):
        first = self.import_rows("01.01.2026;Test;PL00 1111 2222 3333;Zakupy;-10,00;90,00")
        with sqlite3.connect(self.database) as connection:
            connection.execute("UPDATE transactions SET fingerprint='legacy-pre-c5-fingerprint'")
        second = self.import_rows("01.01.2026;Test;PL00 1111 2222 3333;Zakupy;-10,00;90,00")
        self.assertEqual((first["imported"], second["duplicates"]), (1, 1))
        with sqlite3.connect(self.database) as connection:
            account = connection.execute("SELECT account_key,match_key,raw_identifier,display_label FROM accounts").fetchone()
            transaction = connection.execute("SELECT raw_account,account_id FROM transactions").fetchone()
        self.assertTrue(account[0].startswith("acct_"))
        self.assertEqual(len(account[1]), 64)
        self.assertEqual((account[2], transaction[0]), ("", ""))
        self.assertNotIn("3333", account[3])
        self.assertEqual(transaction[1], 1)
        self.assertNotIn("3333", str(self.service.compatibility_payload()))
        self.assertNotIn("3333", self.service.export_transactions_csv({}).decode("utf-8-sig"))

    def test_taxonomy_maps_legacy_and_preserves_audit_without_data_loss(self):
        self.import_rows("01.01.2026;WOLT;Konto prywatne;Bank;-25,00;75,00")
        before = self.service.repository.summary()
        row = self.annotate(merchant="Wolt", userCategory="Food delivery")
        after = self.service.repository.summary()
        self.assertEqual(before, after)
        self.assertEqual((row["parentCategory"], row["userCategory"]), ("Jedzenie poza domem", "Delivery"))
        self.assertEqual(row["legacyCategory"], "Food delivery")
        with sqlite3.connect(self.database) as connection:
            audit = connection.execute("SELECT mapping_status,transaction_count FROM category_migration_audit WHERE legacy_name='Food delivery'").fetchone()
        self.assertEqual(audit, ("mapped", 1))

    def test_ambiguous_mapping_enters_review_and_mixed_retailer_stays_broad(self):
        self.import_rows(
            "01.01.2026;BIEDRONKA 1;Konto prywatne;Bank;-20,00;80,00",
            "02.01.2026;UNKNOWN;Konto prywatne;Bank;-5,00;75,00",
        )
        rows = self.service.compatibility_payload()["transactions"]
        updates = []
        for row in rows:
            updates.append({"id": row["id"], "merchant": "Biedronka" if "BIEDRONKA" in row["description"] else "Inne", "merchantType": "", "userCategory": "Zakupy" if "BIEDRONKA" in row["description"] else "Inne", "note": ""})
        self.service.repository.update_annotations(updates)
        self.service.repository.initialize()
        mapped = {row["description"]: row for row in self.service.compatibility_payload()["transactions"]}
        self.assertEqual((mapped["BIEDRONKA 1"]["parentCategory"], mapped["BIEDRONKA 1"]["userCategory"]), ("Zakupy codzienne", "Zakupy mieszane"))
        issues = {(item["description"], item["issueType"]) for item in self.service.review_items()}
        self.assertIn(("UNKNOWN", "ambiguous_category_mapping"), issues)

    def test_bootstrap_requires_three_fully_consistent_transactions(self):
        self.import_rows(
            "01.01.2026;WOLT A;Konto;Bank;-10,00;90,00",
            "02.01.2026;WOLT B;Konto;Bank;-11,00;79,00",
            "03.01.2026;WOLT C;Konto;Bank;-12,00;67,00",
        )
        for row in self.service.compatibility_payload()["transactions"]:
            self.service.repository.update_annotations([{"id": row["id"], "merchant": "Wolt", "merchantType": "Delivery", "userCategory": "Food delivery", "note": ""}])
        self.service.repository.initialize()
        with sqlite3.connect(self.database) as connection:
            default = connection.execute("SELECT default_category_id FROM merchants WHERE canonical_name='Wolt'").fetchone()[0]
            audit = connection.execute("SELECT occurrence_count,decision FROM classification_bootstrap_audit JOIN merchants ON merchants.id=merchant_id WHERE canonical_name='Wolt'").fetchone()
        self.assertIsNotNone(default)
        self.assertEqual(audit, (3, "merchant_default"))

    def test_bootstrap_rejects_inconsistent_merchant_history(self):
        self.import_rows(
            "01.01.2026;VARIABLE A;Konto;Bank;-10,00;90,00",
            "02.01.2026;VARIABLE B;Konto;Bank;-11,00;79,00",
            "03.01.2026;VARIABLE C;Konto;Bank;-12,00;67,00",
        )
        first = self.service.create_category({"name": "Variable first"})
        second = self.service.create_category({"name": "Variable second"})
        rows = self.service.compatibility_payload()["transactions"]
        for index, row in enumerate(rows):
            self.service.classify_manually(row["id"], {"merchant": "Variable", "categoryId": first["id"] if index < 2 else second["id"], "transactionKind": "expense"})
        self.service.repository.initialize()
        with sqlite3.connect(self.database) as connection:
            default = connection.execute("SELECT default_category_id FROM merchants WHERE canonical_name='Variable'").fetchone()[0]
            decision = connection.execute("SELECT decision FROM classification_bootstrap_audit JOIN merchants ON merchants.id=merchant_id WHERE canonical_name='Variable'").fetchone()[0]
        self.assertIsNone(default)
        self.assertEqual(decision, "review")

    def test_review_exposes_evidence_bulk_correction_and_rule_creation(self):
        self.import_rows(
            "01.01.2026;SAME SHOP;Konto;Bank;-10,00;90,00",
            "02.01.2026;SAME SHOP;Konto;Bank;-11,00;79,00",
        )
        rows = self.service.compatibility_payload()["transactions"]
        category = self.service.create_category({"name": "Test C5"})
        self.service.classify_manually(rows[0]["id"], {"merchant": "Same", "categoryId": category["id"], "transactionKind": "expense"})
        item = next(item for item in self.service.review_items() if item["transactionId"] == rows[1]["id"])
        self.assertTrue(item["suggestion"]["evidence"])
        corrected = self.service.correct_review(rows[1]["id"], {"correction": {"merchant": "Same", "categoryId": category["id"], "transactionKind": "expense"}, "applyToSimilar": True, "rule": {"name": "Same exact", "conditions": [{"field": "raw_description", "operator": "equals", "value": "SAME SHOP"}], "actions": [{"field": "merchant", "value": "Same"}]}})
        self.assertEqual(corrected["similar"]["matched"], 2)
        self.assertEqual(len(self.service.rules()), 1)

    def test_onboarding_budget_suggestion_and_goal_calculations(self):
        self.import_rows("01.01.2026;SHOP;Konto;Bank;-100,00;900,00")
        category = self.service.create_category({"name": "History"})
        row = self.service.compatibility_payload()["transactions"][0]
        self.service.classify_manually(row["id"], {"categoryId": category["id"], "transactionKind": "expense"})
        suggestion = self.service.planning.budget_suggestion("2026-02", category["id"])
        self.assertEqual((suggestion["averageMonthly"], suggestion["suggestedLimit"], suggestion["applied"]), (100.0, 100.0, False))
        onboarding = self.service.planning.onboarding()
        self.assertTrue(next(item for item in onboarding["items"] if item["key"] == "import")["complete"])
        goal = self.service.planning.save_goal({"name": "Fundusz bezpieczeństwa", "kind": "emergency_fund", "target": 10000, "allocated": 1000, "monthlyContribution": 500, "targetDate": "2028-01-01"})
        self.assertEqual(goal["remaining"], 9000)
        self.assertIsNotNone(goal["requiredMonthlyContribution"])

    def test_future_occurrence_paid_early_keeps_due_date_and_is_excluded(self):
        self.import_rows("01.09.2026;SALDO;Konto;Bank;1000,00;1000,00")
        obligation = self.service.planning.save_obligation({"name": "Rata", "amount": 100, "kind": "installment", "cadence": "monthly", "startDate": "2026-10-10", "nextExpectedDate": "2026-10-10", "confirmed": True})
        generated_id = f"{obligation['id']}:2026-10-10"
        paid = self.service.planning.set_occurrence_status(generated_id, "paid")
        self.assertEqual(paid["dueDate"], "2026-10-10")
        self.assertIsNotNone(paid["paidAt"])
        visible = self.service.planning.upcoming(date_from="2026-10-01", date_to="2026-10-31", reference_date="2026-09-01", include_completed=True)
        self.assertEqual(visible[0]["status"], "paid")
        self.assertEqual(self.service.planning.upcoming(date_from="2026-10-01", date_to="2026-10-31", reference_date="2026-09-01"), [])
        forecast = self.service.planning.forecast(horizon="90", reference_date="2026-09-01")
        self.assertFalse(any(event["date"] == "2026-10-10" for event in forecast["events"]))
        safe = self.service.planning.safe_to_spend(reference_date="2026-10-01")
        self.assertEqual(safe["confirmedObligations"], 0)
        restarted = FinanceService(self.database); restarted.ensure_ready()
        persisted = restarted.planning.upcoming(date_from="2026-10-01", date_to="2026-10-31", reference_date="2026-09-01", include_completed=True)
        self.assertEqual((persisted[0]["date"], persisted[0]["status"]), ("2026-10-10", "paid"))

    def test_automatic_monthly_bill_uses_the_same_canonical_paid_state(self):
        obligation = self.service.planning.save_obligation({"name": "Automatyczny rachunek", "amount": 50, "kind": "bill", "cadence": "monthly", "startDate": "2026-10-12", "nextExpectedDate": "2026-10-12", "automatic": True, "confirmed": True})
        occurrence_id = f"{obligation['id']}:2026-10-12"
        self.service.planning.set_occurrence_status(occurrence_id, "paid")
        finance = self.service.planning.upcoming(date_from="2026-10-01", date_to="2026-10-31", reference_date="2026-09-01", include_completed=True)[0]
        bill = next(item for item in self.service.planning.bills_payload("2026-09-01")["bills"] if item["obligationId"] == obligation["id"] and item["due"] == "2026-10-12")
        self.assertEqual((finance["status"], bill["status"], bill["paid"]), ("paid", "paid", True))
        self.assertEqual(finance["date"], bill["due"])
        self.assertIsNotNone(bill["paidAt"])


if __name__ == "__main__":
    unittest.main()
