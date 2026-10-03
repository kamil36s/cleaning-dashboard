import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from finance_service import FinanceService


HEADER = "#Data operacji;#Opis operacji;#Rachunek;#Kategoria;#Kwota;#Saldo po operacji"


class FinancePackC7ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "finance.sqlite"
        self.service = FinanceService(self.database)
        self.service.ensure_ready()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_guided_single_transaction_uses_c6_preview_audit_and_undo(self):
        csv = "\n".join((
            HEADER,
            "01.09.2026;FIXTURE SERVICE;Konto;Bank;-10,00;90,00",
            "02.09.2026;FIXTURE SERVICE;Konto;Bank;-11,00;79,00",
            "",
        ))
        self.service.import_csv(csv.encode(), "c7.csv")
        rows = self.service.compatibility_payload()["transactions"]
        category = next(item for item in self.service.categories() if item["name"] == "Inne usługi")
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute(
                "UPDATE transactions SET merchant_id=NULL,category_id=NULL,transaction_kind='expense'"
            )
            connection.commit()
        group = self.service.review.groups(scope="all_history", month="2026-09")["groups"][0]
        target_id = rows[0]["id"]
        payload = {
            "scope": "all_history",
            "month": "2026-09",
            "targetTransactionId": target_id,
            "classification": {"categoryId": category["id"], "transactionKind": "expense"},
            "origin": "guided_review",
        }
        preview = self.service.review.preview(group["id"], payload)
        self.assertEqual(preview["targetIds"], [target_id])
        self.assertEqual(preview["transactionCount"], 1)
        self.assertEqual(preview["amountsChanged"], 0)

        applied = self.service.review.apply(group["id"], {**payload, "confirm": True})
        self.assertEqual(applied["applied"], 1)
        with closing(sqlite3.connect(self.database)) as connection:
            connection.row_factory = sqlite3.Row
            stored = connection.execute(
                "SELECT id,amount_minor,category_id FROM transactions ORDER BY transaction_date"
            ).fetchall()
            audit = connection.execute(
                "SELECT fields_json FROM review_bulk_actions WHERE id=?", (applied["actionId"],)
            ).fetchone()
        changed = next(row for row in stored if row["id"] == target_id)
        untouched = next(row for row in stored if row["id"] != target_id)
        self.assertEqual((changed["amount_minor"], changed["category_id"]), (round(rows[0]["amount"] * 100), category["id"]))
        self.assertIsNone(untouched["category_id"])
        self.assertEqual(json.loads(audit["fields_json"])["origin"], "guided_review")

        undone = self.service.review.undo_latest()
        self.assertEqual(undone["restored"], 1)
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertIsNone(connection.execute(
                "SELECT category_id FROM transactions WHERE id=?", (target_id,)
            ).fetchone()[0])

    def test_single_transaction_target_must_belong_to_group(self):
        csv = HEADER + "\n01.09.2026;FIXTURE;Konto;Bank;-10,00;90,00\n"
        self.service.import_csv(csv.encode(), "c7.csv")
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute("UPDATE transactions SET merchant_id=NULL,category_id=NULL,transaction_kind='expense'")
            connection.commit()
        group = self.service.review.groups(scope="all_history", month="2026-09")["groups"][0]
        with self.assertRaisesRegex(Exception, "does not belong"):
            self.service.review.preview(group["id"], {
                "scope": "all_history", "month": "2026-09", "targetTransactionId": "tx_not_here",
                "classification": {"transactionKind": "expense"},
            })

    def test_remember_can_create_future_rule_when_current_category_is_already_set(self):
        csv = HEADER + "\n01.09.2026;ONE OFF DOCTOR;Konto;Bank;-350,00;650,00\n"
        self.service.import_csv(csv.encode(), "c7-remember.csv")
        transaction_id = self.service.compatibility_payload()["transactions"][0]["id"]
        category = self.service.create_category({"name": "Lekarze test"})
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute(
                "UPDATE transactions SET merchant_id=NULL,category_id=?,category_source='manual',transaction_kind='expense' WHERE id=?",
                (category["id"], transaction_id),
            )
            connection.commit()
        group = self.service.review.groups(scope="all_history", month="2026-09")["groups"][0]
        payload = {
            "scope": "all_history",
            "month": "2026-09",
            "classification": {"categoryId": category["id"], "transactionKind": "expense"},
            "remember": True,
            "origin": "guided_review",
        }

        preview = self.service.review.preview(group["id"], payload)
        self.assertEqual(preview["transactionCount"], 0)
        self.assertEqual(preview["rememberMechanism"], "exact_description_rule")

        applied = self.service.review.apply(group["id"], {**payload, "confirm": True})
        self.assertEqual(applied["applied"], 0)
        self.assertEqual(applied["rememberMechanism"], "exact_description_rule")
        self.assertEqual(len(self.service.rules()), 1)

        undone = self.service.review.undo_latest()
        self.assertEqual(undone["restored"], 0)
        self.assertEqual(len(self.service.rules()), 0)

    def test_guided_apply_creates_a_new_merchant_atomically_and_resolves_the_group(self):
        csv = HEADER + "\n01.09.2026;CM4M TEST;Konto;Bank;-350,00;650,00\n"
        self.service.import_csv(csv.encode(), "c7-new-merchant.csv")
        transaction_id = self.service.compatibility_payload()["transactions"][0]["id"]
        category = self.service.create_category({"name": "Lekarze atomic"})
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute(
                "UPDATE transactions SET merchant_id=NULL,category_id=?,category_source='manual',transaction_kind='expense' WHERE id=?",
                (category["id"], transaction_id),
            )
            connection.commit()
        group = self.service.review.groups(scope="all_history", month="2026-09")["groups"][0]
        payload = {
            "scope": "all_history",
            "month": "2026-09",
            "classification": {"merchantName": "CM4M Warszawska", "categoryId": category["id"]},
            "remember": True,
            "origin": "guided_review",
        }

        preview = self.service.review.preview(group["id"], payload)
        self.assertEqual(preview["changes"]["merchant"], 1)
        self.assertEqual(preview["rememberMechanism"], "merchant_default")
        applied = self.service.review.apply(group["id"], {**payload, "confirm": True})
        self.assertEqual(applied["applied"], 1)
        self.assertEqual(applied["rememberMechanism"], "merchant_default")
        with closing(sqlite3.connect(self.database)) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                """SELECT m.canonical_name,m.default_category_id,t.merchant_id
                   FROM transactions t JOIN merchants m ON m.id=t.merchant_id WHERE t.id=?""",
                (transaction_id,),
            ).fetchone()
        self.assertEqual(row["canonical_name"], "CM4M Warszawska")
        self.assertEqual(row["default_category_id"], category["id"])
        self.service.review.undo_latest()
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM merchants WHERE canonical_name='CM4M Warszawska'"
            ).fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
