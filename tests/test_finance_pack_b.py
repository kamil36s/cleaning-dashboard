import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from finance_service import FinanceService


HEADER = "#Data operacji;#Opis operacji;#Rachunek;#Kategoria;#Kwota;#Saldo po operacji"


class FinancePackBTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "finance.sqlite"
        self.service = FinanceService(self.database)
        self.service.ensure_ready()

    def tearDown(self):
        self.temp_dir.cleanup()

    def import_rows(self, *rows):
        return self.service.import_csv((HEADER + "\n" + "\n".join(rows) + "\n").encode(), "test.csv")

    def transaction(self, description=None):
        rows = self.service.compatibility_payload()["transactions"]
        return next(row for row in rows if description is None or row["description"] == description)

    def test_schema_and_annotation_migration_preserve_counts_and_values(self):
        self.assertEqual(self.service.repository.schema_versions(), [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11])
        self.import_rows(
            "01.01.2026;A;Konto 1234;Raw;-10,00;90,00",
            "02.01.2026;B;Konto 1234;Raw;20,00;110,00",
        )
        rows = self.service.compatibility_payload()["transactions"]
        self.service.update_annotations([{
            "id": rows[0]["id"], "merchant": " Shop  ", "merchantType": " Store ",
            "userCategory": " Food ", "note": "keep",
        }])
        before = self.service.repository.summary()
        self.service.repository.initialize()
        after = self.service.repository.summary()
        self.assertEqual(before, after)
        with sqlite3.connect(self.database) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute("SELECT * FROM transactions WHERE note='keep'").fetchone()
            self.assertIsNotNone(row["merchant_id"])
            self.assertIsNotNone(row["merchant_type_id"])
            self.assertIsNotNone(row["category_id"])

    def test_categories_create_hierarchy_rename_and_normalized_duplicate(self):
        parent = self.service.create_category({"name": "Food"})
        child = self.service.create_category({"name": "Groceries", "parentId": parent["id"]})
        renamed = self.service.update_category(child["id"], {"name": "Supermarket"})
        self.assertEqual(renamed["parentId"], parent["id"])
        self.assertEqual(renamed["name"], "Supermarket")
        with self.assertRaisesRegex(Exception, "normalized name"):
            self.service.create_category({"name": "  food "})

    def test_merchant_alias_matches_new_import_and_normalizes_duplicates(self):
        merchant = self.service.create_merchant({"canonicalName": "Biedronka", "aliases": ["BIEDRONKA 1234 KRAKOW"]})
        self.import_rows("01.01.2026;Biedronka 1234 Krakow;Konto 1234;Zakupy;-10,00;90,00")
        transaction = self.transaction()
        self.assertEqual(transaction["merchantId"], merchant["id"])
        self.assertEqual(transaction["classification"]["merchantSource"], "imported_raw")
        with self.assertRaisesRegex(Exception, "normalized name"):
            self.service.create_merchant({"canonicalName": " biedronka "})

    def test_safe_kind_fallback_and_no_largest_positive_salary_heuristic(self):
        self.import_rows(
            "01.01.2026;Small positive;Konto 1234;Incoming;10,00;10,00",
            "02.01.2026;Largest positive;Konto 1234;Incoming;9999,00;10009,00",
            "03.01.2026;Negative;Konto 1234;Purchase;-2,00;10007,00",
        )
        values = {row["description"]: row["transactionKind"] for row in self.service.compatibility_payload()["transactions"]}
        self.assertEqual(values["Largest positive"], "other")
        self.assertEqual(values["Small positive"], "other")
        self.assertEqual(values["Negative"], "expense")

    def test_rules_order_conflict_stop_disabled_preview_and_historical_apply(self):
        food = self.service.create_category({"name": "Food"})
        other = self.service.create_category({"name": "Other"})
        self.import_rows("01.01.2026;RULE SHOP;Konto 1234;Raw;-10,00;90,00")
        first = self.service.create_rule({
            "name": "first", "priority": 10,
            "conditions": [{"field": "normalized_description", "operator": "contains", "value": "rule shop"}],
            "actions": [{"field": "category", "valueId": food["id"]}],
        })["rule"]
        second = self.service.create_rule({
            "name": "second", "priority": 20,
            "conditions": [
                {"field": "normalized_description", "operator": "contains", "value": "rule"},
                {"field": "sign", "operator": "equals", "value": "negative"},
            ],
            "actions": [
                {"field": "category", "valueId": other["id"]},
                {"field": "transaction_kind", "value": "cash"},
            ],
        })["rule"]
        preview = self.service.preview_rule(first["id"])
        self.assertEqual(preview["matched"], 1)
        self.assertEqual(preview["changes"]["category"], 1)
        self.service.apply_rule(first["id"])
        self.assertEqual(self.transaction()["userCategory"], "Food")
        # Reclassifying against all enabled rules demonstrates first-wins and conflict semantics.
        transaction_id = self.transaction()["id"]
        with self.service.repository.transaction() as connection:
            from finance_classification import classify_transaction
            result = classify_transaction(connection, transaction_id)
        self.assertEqual(result["values"]["category"], food["id"])
        self.assertEqual(result["values"]["transaction_kind"], "cash")
        self.assertTrue(result["conflict"])
        self.service.update_rule(first["id"], {"stopProcessing": True})
        with self.service.repository.transaction() as connection:
            from finance_classification import classify_transaction
            stopped = classify_transaction(connection, transaction_id)
        self.assertFalse(stopped["conflict"])
        self.assertEqual(stopped["values"]["transaction_kind"], "expense")
        self.service.update_rule(first["id"], {"enabled": False})
        self.assertFalse(next(rule for rule in self.service.rules() if rule["id"] == first["id"])["enabled"])
        self.assertTrue(next(rule for rule in self.service.rules() if rule["id"] == second["id"])["enabled"])

    def test_multiple_rule_actions_apply_during_import(self):
        food = self.service.create_category({"name": "Groceries"})
        merchant = self.service.create_merchant({"canonicalName": "Shop"})
        self.service.create_rule({
            "name": "new shop", "priority": 5,
            "conditions": [{"field": "raw_description", "operator": "contains", "value": "NEW SHOP"}],
            "actions": [
                {"field": "merchant", "valueId": merchant["id"]},
                {"field": "category", "valueId": food["id"]},
                {"field": "transaction_kind", "value": "expense"},
            ],
        })
        self.import_rows("01.01.2026;NEW SHOP TERMINAL;Konto 1234;Raw;-10,00;90,00")
        row = self.transaction()
        self.assertEqual((row["merchant"], row["userCategory"], row["transactionKind"]), ("Shop", "Groceries", "expense"))
        explanation = self.service.classification_explanation(row["id"])
        self.assertTrue(any(field["source"] == "rule" and field["rule"] for field in explanation["fields"]))

    def test_manual_precedence_and_duplicate_reimport_preserve_classification(self):
        manual = self.service.create_category({"name": "Manual"})
        automated = self.service.create_category({"name": "Automated"})
        line = "01.01.2026;SAME ITEM;Konto 1234;Raw;-10,00;90,00"
        self.import_rows(line)
        transaction_id = self.transaction()["id"]
        self.service.classify_manually(transaction_id, {"categoryId": manual["id"], "transactionKind": "saving"})
        rule = self.service.create_rule({
            "name": "auto", "conditions": [{"field": "raw_description", "operator": "equals", "value": "SAME ITEM"}],
            "actions": [{"field": "category", "valueId": automated["id"]}, {"field": "transaction_kind", "value": "expense"}],
        })["rule"]
        self.service.apply_rule(rule["id"])
        self.import_rows(line)
        row = self.transaction()
        self.assertEqual(row["userCategory"], "Manual")
        self.assertEqual(row["transactionKind"], "saving")
        self.service.apply_rule(rule["id"], include_manual=True)
        self.assertEqual(self.transaction()["userCategory"], "Automated")

    def test_review_queue_unknown_missing_resolve_ignore_and_rule_from_correction(self):
        self.import_rows("01.01.2026;UNKNOWN;Konto 1234;Raw;-10,00;90,00")
        row = self.transaction()
        issues = {item["issueType"] for item in self.service.review_items()}
        self.assertEqual(issues, {"unknown_merchant", "missing_category"})
        self.service.update_review(row["id"], "unknown_merchant", "ignored")
        ignored = self.service.review_items("ignored")
        self.assertEqual(ignored[0]["issueType"], "unknown_merchant")
        result = self.service.correct_review(row["id"], {
            "correction": {"merchant": "Known", "category": "Food"},
            "resolveIssues": ["missing_category"],
            "rule": {
                "name": "Known future", "conditions": [{"field": "raw_description", "operator": "equals", "value": "UNKNOWN"}],
                "actions": [{"field": "merchant", "value": "Known"}],
            },
        })
        self.assertIsNotNone(result["rule"])
        self.assertEqual(self.service.review_items(), [])

    def test_review_queue_marks_conflicting_historical_merchant_evidence_ambiguous(self):
        self.import_rows(
            "01.01.2026;SAME RAW;Konto 1234;Raw;-1,00;99,00",
            "01.01.2026;SAME RAW;Konto 1234;Raw;-1,00;98,00",
            "01.01.2026;SAME RAW;Konto 1234;Raw;-1,00;97,00",
        )
        rows = self.service.compatibility_payload()["transactions"]
        self.service.classify_manually(rows[0]["id"], {"merchant": "Merchant A"})
        self.service.classify_manually(rows[1]["id"], {"merchant": "Merchant B"})
        issues = [item for item in self.service.review_items() if item["transactionId"] == rows[2]["id"]]
        self.assertIn("ambiguous_classification", {item["issueType"] for item in issues})
        with sqlite3.connect(self.database) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM merchant_aliases").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM ambiguous_merchant_aliases").fetchone()[0], 1)

    def test_periods_analytics_formulas_comparison_and_pagination(self):
        self.import_rows(
            "01.09.2026;Expense A;Konto 1234;Raw;-100,00;900,00",
            "02.09.2026;Salary;Konto 1234;Raw;1000,00;1900,00",
            "03.09.2026;Income;Konto 1234;Raw;100,00;2000,00",
            "04.09.2026;Refund;Konto 1234;Raw;20,00;2020,00",
            "05.09.2026;Transfer;Konto 1234;Raw;-300,00;1720,00",
            "06.09.2026;Saving;Konto 1234;Raw;-200,00;1520,00",
            "01.08.2026;Old Expense;Konto 1234;Raw;-50,00;1570,00",
        )
        kinds = {
            "Expense A": "expense", "Salary": "salary", "Income": "income", "Refund": "refund",
            "Transfer": "transfer", "Saving": "saving", "Old Expense": "expense",
        }
        for row in self.service.compatibility_payload()["transactions"]:
            self.service.classify_manually(row["id"], {"transactionKind": kinds[row["description"]], "category": "Test", "merchant": row["description"]})
        period = self.service.resolve_period({"period": "current_month", "referenceDate": "2026-09-17"})
        summary = self.service.analytics.get_period_summary(period)
        self.assertEqual(summary["expenses"], 100)
        self.assertEqual(summary["salary"], 1000)
        self.assertEqual(summary["otherIncome"], 100)
        self.assertEqual(summary["totalIncome"], 1100)
        self.assertEqual(summary["refunds"], 20)
        self.assertEqual(summary["savings"], 200)
        self.assertEqual(summary["transfers"], 300)
        self.assertEqual(summary["netCashFlow"], 820)
        self.assertAlmostEqual(summary["savingsRate"], 200 / 1100 * 100)
        comparison = self.service.analytics.compare_periods(period)
        self.assertEqual(comparison["changes"]["expenses"]["absoluteChange"], 50)
        zero_period = self.service.resolve_period({"period": "date_range", "dateFrom": "2025-01-01", "dateTo": "2025-01-31"})
        self.assertIsNone(self.service.analytics.compare_periods(zero_period)["changes"]["expenses"]["percentageChange"])
        latest = self.service.resolve_period({"period": "latest_data_month", "referenceDate": "2026-10-17"})
        self.assertEqual(latest["period_start"], "2026-09-01")
        self.assertEqual(latest["data_freshness"]["status"], "stale")
        rolling = self.service.resolve_period({"period": "rolling_30", "referenceDate": "2026-09-17"})
        self.assertEqual(rolling["period_start"], "2026-08-19")
        query = self.service.query_transactions({"page": 2, "limit": 2, "transactionKind": "expense", "sort": "date_desc"})
        self.assertEqual(query["total"], 2)
        self.assertEqual(query["transactions"], [])
        self.assertTrue(self.service.analytics.get_category_breakdown(period))
        self.assertTrue(self.service.analytics.get_merchant_breakdown(period))


if __name__ == "__main__":
    unittest.main()
