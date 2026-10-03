import tempfile
import unittest
from pathlib import Path

from finance_service import FinanceService, FinanceValidationError


HEADER = "#Data operacji;#Opis operacji;#Rachunek;#Kategoria;#Kwota;#Saldo po operacji"


def csv_text(*rows):
    return HEADER + "\n" + "\n".join(rows) + "\n"


class FinanceImportTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "finance.sqlite"
        self.service = FinanceService(self.database)
        self.service.ensure_ready()

    def tearDown(self):
        self.temp_dir.cleanup()

    def import_text(self, text, name="history.csv", encoding="utf-8"):
        return self.service.import_csv(text.encode(encoding), name)

    def test_correct_polish_csv_and_cp1250(self):
        text = csv_text(
            "09.05.2026;ŻÓŁĆ sklep;Konto 1234;Żywność;-42,10 PLN;1 925,74 PLN"
        )
        result = self.import_text(text, encoding="cp1250")
        transaction = self.service.compatibility_payload()["transactions"][0]
        self.assertEqual(result["encoding"], "cp1250")
        self.assertEqual(result["imported"], 1)
        self.assertEqual(transaction["description"], "ŻÓŁĆ sklep")
        self.assertEqual(transaction["amount"], -42.10)

    def test_utf8_bom(self):
        raw = csv_text(
            "09.05.2026;Żabka;Konto 1234;Żywność;-12,00;100,00"
        ).encode("utf-8-sig")
        result = self.service.import_csv(raw, "bom.csv")
        self.assertEqual(result["encoding"], "utf-8-sig")
        self.assertEqual(result["imported"], 1)

    def test_csv_import_keeps_no_source_file_in_service_directory(self):
        raw = csv_text("09.05.2026;Shop;Konto 1234;Food;-12,00;100,00").encode("utf-8")
        result = self.service.import_csv(raw, "source.csv")
        self.assertEqual(result["imported"], 1)
        files = {path.name for path in self.database.parent.iterdir() if path.is_file()}
        self.assertFalse(any(name.endswith(".csv") for name in files))
        self.assertFalse((self.database.parent / "finance-imports").exists())

    def test_malformed_amount_date_and_short_row_are_invalid_not_zero_rows(self):
        result = self.import_text(csv_text(
            "09.05.2026;Valid;Konto 1234;Zakupy;-10,00;100,00",
            "08.05.2026;Bad amount;Konto 1234;Zakupy;abc;100,00",
            "not-a-date;Bad date;Konto 1234;Zakupy;-20,00;80,00",
            "07.05.2026;Short",
        ))
        self.assertEqual(result["imported"], 1)
        self.assertEqual(result["invalid"], 3)
        self.assertEqual(
            {error["code"] for error in result["errors"]},
            {"invalid_amount", "invalid_date", "short_row"},
        )
        self.assertEqual(self.service.repository.transaction_count(), 1)
        self.assertTrue(all("Bad" not in error["message"] for error in result["errors"]))

    def test_missing_required_header_records_failed_batch(self):
        with self.assertRaises(FinanceValidationError) as raised:
            self.import_text("date;description\n2026-01-01;test\n", "bad.csv")
        self.assertEqual(raised.exception.result["status"], "failed")
        batch = self.service.import_history()[0]
        self.assertEqual(batch["status"], "failed")
        self.assertEqual(batch["accepted_count"], 0)
        self.assertEqual(self.service.repository.transaction_count(), 0)

    def test_explicit_unsupported_currency_is_rejected(self):
        text = (
            HEADER + ";#Waluta\n"
            "09.05.2026;Euro item;Konto 1234;Zakupy;-10,00;100,00;EUR\n"
        )
        result = self.import_text(text)
        self.assertEqual(result["imported"], 0)
        self.assertEqual(result["invalid"], 1)
        self.assertEqual(result["errors"][0]["code"], "unsupported_currency")

    def test_repeat_and_overlap_are_deduplicated(self):
        first = csv_text(
            "10.05.2026;A;Konto 1234;Zakupy;-10,00;100,00",
            "09.05.2026;B;Konto 1234;Zakupy;-20,00;80,00",
        )
        repeated = self.import_text(first, "first.csv")
        repeat_result = self.import_text(first, "repeat.csv")
        overlap_result = self.import_text(csv_text(
            "09.05.2026;B;Konto 1234;Zakupy;-20,00;80,00",
            "08.05.2026;C;Konto 1234;Zakupy;-30,00;50,00",
        ), "overlap.csv")
        self.assertEqual(repeated["imported"], 2)
        self.assertEqual(repeat_result["duplicates"], 2)
        self.assertEqual(overlap_result["duplicates"], 1)
        self.assertEqual(overlap_result["imported"], 1)
        self.assertEqual(self.service.repository.transaction_count(), 3)

    def test_changed_bank_category_and_balance_do_not_duplicate_or_erase_annotations(self):
        self.import_text(csv_text(
            "09.05.2026;Same event;Konto 1234;Old category;-20,00;80,00"
        ))
        transaction = self.service.compatibility_payload()["transactions"][0]
        self.service.update_annotations([{
            "id": transaction["id"],
            "merchant": "My merchant",
            "merchantType": "Shop",
            "userCategory": "My category",
            "note": "keep me",
        }])
        result = self.import_text(csv_text(
            "09.05.2026;Same event;Konto 1234;New category;-20,00;999,00"
        ), "changed.csv")
        current = self.service.compatibility_payload()["transactions"][0]
        self.assertEqual(result["duplicates"], 1)
        self.assertEqual(self.service.repository.transaction_count(), 1)
        self.assertEqual(current["merchant"], "My merchant")
        self.assertEqual(current["userCategory"], "My category")
        self.assertEqual(current["note"], "keep me")

    def test_legitimate_identical_same_day_events_use_occurrence_ordinal(self):
        result = self.import_text(csv_text(
            "09.05.2026;Transit ticket;Konto 1234;Transport;-4,00;96,00",
            "09.05.2026;Transit ticket;Konto 1234;Transport;-4,00;92,00",
        ))
        self.assertEqual(result["imported"], 2)
        self.assertEqual(self.service.repository.transaction_count(), 2)
        self.assertEqual(len({row["id"] for row in self.service.compatibility_payload()["transactions"]}), 2)

    def test_rollback_does_not_delete_transaction_also_seen_in_another_batch(self):
        first = self.import_text(csv_text(
            "10.05.2026;A;Konto 1234;Zakupy;-10,00;100,00",
            "09.05.2026;B;Konto 1234;Zakupy;-20,00;80,00",
        ), "first.csv")
        second = self.import_text(csv_text(
            "09.05.2026;B;Konto 1234;Zakupy;-20,00;80,00",
            "08.05.2026;C;Konto 1234;Zakupy;-30,00;50,00",
        ), "second.csv")

        rollback = self.service.rollback_import(first["batchId"])

        self.assertEqual(rollback["deleted"], 1)
        self.assertEqual(rollback["detached"], 1)
        remaining = {row["description"] for row in self.service.compatibility_payload()["transactions"]}
        self.assertEqual(remaining, {"B", "C"})
        self.assertEqual(
            next(batch for batch in self.service.import_history() if batch["id"] == first["batchId"])["status"],
            "rolled_back",
        )
        self.assertEqual(
            next(batch for batch in self.service.import_history() if batch["id"] == second["batchId"])["status"],
            "completed",
        )

    def test_mbank_goal_statement_is_filtered_and_becomes_a_savings_account(self):
        text = """mBank S.A.;;;;;;;
#Rodzaj rachunku;;;;;;;
CEL;;;;;;;
#Waluta;;;;;;;
PLN;;;;;;;
#Numer rachunku;;;;;;;
XXX!;;;;;;;
#Data księgowania;#Data operacji;#Opis operacji;#Tytuł;#Nadawca/Odbiorca;#Numer konta;#Kwota;#Saldo po operacji
31.12.2025;31.12.2025;PRZELEW NA TWOJE CELE;SKLEP;KARTA;'Oszczędności';1,00;1,00
01.01.2026;01.01.2026;PRZELEW NA TWOJE CELE;BIEDRONKA;KARTA;'Oszczędności';2,00;3,00
02.01.2026;02.01.2026;KAPITALIZACJA ODSETEK;;;;1,00;4,00
;;;;;;#Saldo końcowe;4,00 PLN
"""
        result = self.service.import_csv(
            text.encode("cp1250"), "cele.csv", date_from="2026-01-01"
        )

        self.assertEqual((result["imported"], result["filteredOut"], result["invalid"]), (2, 1, 0))
        self.assertEqual(result["format"], "mbank_account_statement")
        account = self.service.planning.accounts()[0]
        self.assertEqual(
            (account["displayLabel"], account["role"], account["includeSafeToSpend"], account["balance"]),
            ("Cele", "savings", False, 4.0),
        )
        transactions = {row["category"]: row for row in self.service.compatibility_payload()["transactions"]}
        self.assertEqual(transactions["PRZELEW NA TWOJE CELE"]["transactionKind"], "transfer")
        self.assertEqual(transactions["KAPITALIZACJA ODSETEK"]["transactionKind"], "income")
        self.assertEqual(transactions["PRZELEW NA TWOJE CELE"]["userCategory"], "Oszczędności")

        goal = self.service.planning.save_goal({
            "name": "Poduszka bezpieczeństwa", "kind": "emergency_fund",
            "target": 55000, "linkedAccountId": account["id"], "primary": True,
        })
        self.assertEqual((goal["allocated"], goal["remaining"], goal["progressPercent"]), (4.0, 54996.0, 0.0))

    def test_mbank_categories_assign_safe_canonical_categories_and_kinds(self):
        result = self.import_text(csv_text(
            "01.01.2026;PRZELEW NA TWOJE CELE;Konto 1234;Regularne oszczędzanie;-10,00;90,00",
            "02.01.2026;Bolt ZAKUP PRZY UŻYCIU KARTY;Konto 1234;Przejazdy;-20,00;70,00",
            "03.01.2026;PRACODAWCA;Konto 1234;Wynagrodzenie;1000,00;1070,00",
        ))
        self.assertEqual(result["imported"], 3)
        rows = {row["description"]: row for row in self.service.compatibility_payload()["transactions"]}
        self.assertEqual((rows["PRZELEW NA TWOJE CELE"]["userCategory"], rows["PRZELEW NA TWOJE CELE"]["transactionKind"]), ("Oszczędności", "saving"))
        self.assertEqual((rows["Bolt ZAKUP PRZY UŻYCIU KARTY"]["parentCategory"], rows["Bolt ZAKUP PRZY UŻYCIU KARTY"]["userCategory"]), ("Transport", "Taxi / rideshare"))
        self.assertEqual(rows["PRACODAWCA"]["transactionKind"], "salary")

    def test_cross_format_overlap_aliases_account_and_preserves_occurrences(self):
        operation_list = csv_text(
            "02.01.2026;Biedronka ZAKUP PRZY UŻYCIU KARTY; eKonto 1234;Żywność i chemia domowa;-10,00;90,00",
            "02.01.2026;Biedronka ZAKUP PRZY UŻYCIU KARTY; eKonto 1234;Żywność i chemia domowa;-10,00;80,00",
        )
        first = self.import_text(operation_list, "lista-operacji.csv")
        statement = """mBank S.A.;;;;;;;
#Rodzaj rachunku;;;;;;;
EKONTO;;;;;;;
#Waluta;;;;;;;
PLN;;;;;;;
#Data księgowania;#Data operacji;#Opis operacji;#Tytuł;#Nadawca/Odbiorca;#Numer konta;#Kwota;#Saldo po operacji
03.01.2026;03.01.2026;ZAKUP PRZY UŻYCIU KARTY;JMP S.A. BIEDRONKA 123; ;'';-10,00;70,00
03.01.2026;03.01.2026;ZAKUP PRZY UŻYCIU KARTY;JMP S.A. BIEDRONKA 123; ;'';-10,00;60,00
;;;;;;#Saldo końcowe;60,00 PLN
"""
        second = self.service.import_csv(statement.encode("cp1250"), "statement.csv")

        self.assertEqual((first["imported"], second["imported"], second["duplicates"]), (2, 0, 2))
        self.assertEqual(self.service.repository.transaction_count(), 2)
        self.assertEqual(len(self.service.repository.list_accounts()), 1)

    def test_tax_transfer_in_operation_list_and_statement_is_one_payment(self):
        first = self.import_text(csv_text(
            "02.10.2026;URZAD SKARBOWY KRAKOW-SRODMIESCIE; eKonto 1234;Przelewy;-952,00;3809,96",
        ), "tax-operations.csv")
        statement = """mBank S.A.;;;;;;;
#Rodzaj rachunku;;;;;;;
EKONTO;;;;;;;
#Waluta;;;;;;;
PLN;;;;;;;
#Data księgowania;#Data operacji;#Opis operacji;#Tytuł;#Nadawca/Odbiorca;#Numer konta;#Kwota;#Saldo po operacji
02.10.2026;02.10.2026;PRZELEW PODATKOWY;P94053107395;URZAD SKARBOWY;'';-952,00;3809,96
;;;;;;#Saldo końcowe;3809,96 PLN
"""
        second = self.service.import_csv(statement.encode("cp1250"), "tax-statement.csv")

        self.assertEqual((first["imported"], second["imported"], second["duplicates"]), (1, 0, 1))
        self.assertEqual(self.service.repository.transaction_count(), 1)
        with self.service.repository.read_connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM transaction_imports").fetchone()[0], 2)
        self.assertEqual(self.service.planning.overview("2026-10-02")["expenseCategories"],
                         [{"name": "Podatki", "amount": 952.0}])

    def test_statement_creates_canonical_merchant_type_and_category(self):
        statement = """mBank S.A.;;;;;;;
#Rodzaj rachunku;;;;;;;
EKONTO;;;;;;;
#Waluta;;;;;;;
PLN;;;;;;;
#Data księgowania;#Data operacji;#Opis operacji;#Tytuł;#Nadawca/Odbiorca;#Numer konta;#Kwota;#Saldo po operacji
03.01.2026;03.01.2026;ZAKUP PRZY UŻYCIU KARTY;JMP S.A. BIEDRONKA 123; ;'';-10,00;90,00
;;;;;;#Saldo końcowe;90,00 PLN
"""
        self.service.import_csv(statement.encode("cp1250"), "statement.csv")
        row = self.service.compatibility_payload()["transactions"][0]
        self.assertEqual((row["merchant"], row["parentCategory"], row["userCategory"]), ("Biedronka", "Zakupy codzienne", "Zakupy mieszane"))
        self.assertEqual(row["merchantType"], "Supermarket")


if __name__ == "__main__":
    unittest.main()
