import json
import tempfile
import unittest
from pathlib import Path

from finance_service import FinanceService
from finance_planning import _expense_budget_month


HEADER = "#Data operacji;#Opis operacji;#Rachunek;#Kategoria;#Kwota;#Saldo po operacji"


class FinancePackCTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        (root / "settings").mkdir()
        self.bills_path = root / "settings" / "bills.json"
        self.bills_path.write_text(json.dumps({
            "paid": {"rent-2026-08": True, "subscription-chatgpt-2026-09": True},
            "cancelledSubscriptions": {"cinema-city": True},
            "customBills": [{
                "id": "custom-test", "name": "Telefon", "provider": "Play",
                "category": "Mieszkanie", "amountCents": 3500, "due": "2026-09-13",
                "recurrence": "monthly", "endMonth": "", "automatic": True,
            }],
            "notificationsEnabled": True,
        }), encoding="utf-8")
        self.service = FinanceService(root / "finance.sqlite")
        self.migration = self.service.ensure_ready()

    def tearDown(self):
        self.temp_dir.cleanup()

    def import_rows(self, *rows):
        return self.service.import_csv((HEADER + "\n" + "\n".join(rows) + "\n").encode(), "pack-c.csv")

    def test_bills_migration_is_verified_idempotent_and_private_backup_exists(self):
        verification = self.migration["bills"]
        self.assertEqual(self.service.repository.schema_versions(), [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11])
        self.assertEqual(verification["sourceDefinitionCount"], 21)
        self.assertEqual(verification["canonicalObligationCount"], 21)
        self.assertEqual(verification["sourcePaidCount"], verification["canonicalPaidCount"])
        self.assertTrue(Path(verification["sourceBackup"]).is_file())
        self.assertTrue(Path(verification["snapshotBackup"]).is_file())
        count = len(self.service.planning.obligations())
        second = self.service.planning.migrate_legacy_bills()
        self.assertEqual(len(self.service.planning.obligations()), count)
        self.assertEqual(second["canonicalObligationCount"], count)
        bills = self.service.planning.bills_payload("2026-09-17")
        self.assertEqual(bills["source"], "finance.sqlite")
        september_chatgpt = [
            item for item in bills["bills"]
            if item["id"] == "subscription-chatgpt-2026-09"
        ]
        self.assertEqual(len(september_chatgpt), 1)
        self.assertEqual(september_chatgpt[0]["amountCents"], 48844)
        self.assertEqual(september_chatgpt[0]["due"], "2026-09-16")
        self.assertTrue(september_chatgpt[0]["paid"])
        self.assertTrue(next(item for item in bills["bills"] if item["id"] == "subscription-google-one-2026-09")["paid"])
        self.assertTrue(next(item for item in bills["bills"] if item["name"] == "Telefon" and item["month"] == "2026-09")["paid"])
        self.assertFalse(next(item for item in bills["bills"] if item["id"] == "subscription-canal-plus-2026-09")["paid"])
        self.assertFalse(any(item["name"] == "Cinema City Unlimited" for item in bills["bills"]))

    def test_data_quality_and_monthly_recurring_candidate_evidence(self):
        self.import_rows(
            "01.06.2026;GYM CLUB;Konto 1234;Sport;-100,00;900,00",
            "01.07.2026;GYM CLUB;Konto 1234;Sport;-101,00;799,00",
            "01.08.2026;GYM CLUB;Konto 1234;Sport;-100,00;699,00",
        )
        for transaction in self.service.compatibility_payload()["transactions"]:
            self.service.classify_manually(transaction["id"], {
                "merchant": "Gym Club", "category": "Sport", "transactionKind": "expense",
            })
        quality = self.service.planning.data_quality()
        self.assertEqual(quality["totalTransactions"], 3)
        self.assertEqual(quality["merchantCoveragePercent"], 100)
        candidate = self.service.planning.recurring_candidates()[0]
        self.assertEqual(candidate["cadence"], "monthly")
        self.assertFalse(candidate["confirmed"])
        self.assertEqual(candidate["evidence"]["occurrenceCount"], 3)
        self.assertEqual(candidate["evidence"]["likelyNextDate"], "2026-09-01")

    def test_budget_goal_safe_to_spend_and_forecast_are_deterministic(self):
        self.import_rows(
            "01.09.2026;Opening;Konto 1234;Other;1000,00;1000,00",
            "05.09.2026;Food;Konto 1234;Food;-100,00;900,00",
        )
        rows = self.service.compatibility_payload()["transactions"]
        expense = next(row for row in rows if row["description"] == "Food")
        self.service.classify_manually(expense["id"], {"category": "Food", "merchant": "Shop", "transactionKind": "expense"})
        category_id = expense = next(row for row in self.service.compatibility_payload()["transactions"] if row["description"] == "Food")["categoryId"]
        self.service.planning.save_budget({"month": "2026-09", "categoryId": category_id, "limit": 500})
        budget = next(item for item in self.service.planning.budget_status("2026-09", "2026-09-17")
                      if item["categoryId"] == category_id)
        self.assertEqual(budget["spent"], 100)
        self.assertEqual(budget["remaining"], 400)
        self.assertGreater(budget["projected"], 100)

        self.service.planning.save_obligation({
            "name": "Insurance", "kind": "bill", "amount": 100, "cadence": "once",
            "startDate": "2026-09-20", "nextExpectedDate": "2026-09-20", "confirmed": True,
        })
        self.service.planning.save_planned_item({
            "name": "Concert", "date": "2026-09-25", "amount": 50,
            "kind": "expense", "includeSafeToSpend": True,
        })
        with self.service.repository.transaction() as connection:
            connection.execute("UPDATE obligations SET active=0 WHERE provenance='legacy_bills'")
        self.service.repository.write_settings({"safeToSpendBufferMinor": 10000})
        safe = self.service.planning.safe_to_spend(reference_date="2026-09-17")
        self.assertEqual(safe["liquidBalance"], 900)
        self.assertEqual(safe["confirmedObligations"], 100)
        self.assertEqual(safe["plannedExpenses"], 50)
        self.assertEqual(safe["safetyBuffer"], 100)
        self.assertEqual(safe["safeToSpend"], 650)
        forecast = self.service.planning.forecast(horizon="end_of_month", reference_date="2026-09-17")
        self.assertEqual([event["date"] for event in forecast["events"]], ["2026-09-20", "2026-09-25"])
        self.assertEqual(forecast["endingBalance"], 750)

        goal = self.service.planning.save_goal({
            "name": "Emergency", "kind": "emergency_fund", "target": 50000,
            "allocated": 5000, "targetDate": "2027-09-17", "monthlyContribution": 1000,
            "primary": True,
        })
        self.assertEqual(goal["progressPercent"], 10)
        self.assertEqual(goal["remaining"], 45000)
        self.assertIsNotNone(goal["requiredMonthlyContribution"])

    def test_overview_uses_main_account_and_pending_payments_for_free_balance(self):
        self.import_rows(
            "01.10.2026;Opening A;Konto A;Other;1000,00;1000,00",
            "01.10.2026;Opening B;Konto B;Other;500,00;500,00",
        )
        with self.service.repository.transaction() as connection:
            connection.execute("UPDATE obligations SET active=0 WHERE provenance='legacy_bills'")
        accounts = self.service.planning.accounts()
        self.assertEqual(sum(account["main"] for account in accounts), 1)
        account_b = next(account for account in accounts if account["balance"] == 500)
        self.service.planning.update_account(account_b["id"], {"role": "spending", "main": True})
        self.assertTrue(next(account for account in FinanceService(self.service.repository.database_path).planning.accounts()
            if account["id"] == account_b["id"])["main"])
        self.service.planning.save_obligation({
            "name": "Subscription", "kind": "subscription", "amount": 75, "cadence": "once",
            "startDate": "2026-10-20", "nextExpectedDate": "2026-10-20", "confirmed": True,
        })
        self.service.planning.save_planned_item({"name": "Plan", "date": "2026-10-22", "amount": 25, "kind": "expense"})
        self.service.planning.save_planned_item({"name": "Saving", "date": "2026-10-23", "amount": 15, "kind": "saving"})
        self.service.planning.save_planned_item({
            "name": "Another plan", "date": "2026-10-24", "amount": 10,
            "kind": "expense", "includeSafeToSpend": False,
        })
        self.service.planning.update_safe_settings({"buffer": 100})
        self.service.planning.save_goal({
            "name": "Poduszka bezpieczeństwa", "kind": "emergency_fund", "target": 55000,
            "allocated": 18000, "primary": True,
        })

        overview = self.service.planning.overview("2026-10-02")
        self.assertEqual(overview["availableBalance"], 500)
        self.assertEqual(overview["freeBalance"], 375)
        self.assertEqual(overview["mainAccountName"], account_b["displayLabel"])
        self.assertEqual(overview["safeToSpend"]["safeToSpend"], 1285)
        self.assertEqual(overview["goals"][0]["target"], 55000)
        self.assertEqual(overview["goals"][0]["allocated"], 18000)
        self.assertTrue(overview["safeToSpend"]["configured"])
        self.assertFalse(any(item["key"] == "buffer" for item in overview["safeToSpend"]["setup"]))
        self.assertEqual(len(overview["accountImports"]), 1)
        self.assertIsNotNone(overview["accountImports"][0]["lastImportedAt"])
        self.assertEqual(overview["accountImports"][0]["latestTransactionDate"], "2026-10-01")

    def test_aon_paycheck_funds_next_month_budget_without_changing_cashflow(self):
        self.import_rows(
            "29.09.2026;AON SP. Z O.O. WYNAGRODZENIE ZA 9/2026;Konto;Other;5131,98;5131,98",
            "02.10.2026;Food;Konto;Food;-100,00;5031,98",
            "02.10.2026;Bonus;Konto;Income;50,00;5081,98",
        )
        expense = next(row for row in self.service.compatibility_payload()["transactions"] if row["description"] == "Food")
        self.service.classify_manually(expense["id"], {"transactionKind": "expense", "category": "Food"})
        bonus = next(row for row in self.service.compatibility_payload()["transactions"] if row["description"] == "Bonus")
        self.service.classify_manually(bonus["id"], {"transactionKind": "income"})
        october = self.service.planning.budget_status("2026-10", "2026-10-02")
        self.assertEqual(len(october), 1)
        self.assertEqual((october[0]["limit"], october[0]["spent"], october[0]["remaining"]),
            (5181.98, 100, 5081.98))
        self.assertEqual(october[0]["source"], "monthly_inflows")
        self.assertEqual(october[0]["dailyLimit"], 167.16)
        self.service.planning.save_obligation({
            "name": "Upcoming", "kind": "bill", "amount": 75, "cadence": "once",
            "startDate": "2026-10-20", "nextExpectedDate": "2026-10-20", "confirmed": True,
        })
        with self.service.repository.transaction() as connection:
            connection.execute("UPDATE obligations SET active=0 WHERE provenance='legacy_bills'")
        october = self.service.planning.budget_status("2026-10", "2026-10-02")[0]
        self.assertEqual((october["plannedRemaining"], october["freeAfterScheduled"], october["remainingDays"]),
            (75, 5006.98, 30))
        self.assertEqual(october["freePerDay"], 166.90)
        overview = self.service.planning.overview("2026-10-02")
        self.assertEqual((overview["income"], overview["expenses"], overview["remainingFromIncome"]),
            (5181.98, 100, 5081.98))
        self.assertEqual(overview["incomeSources"], [
            {"name": "Wynagrodzenie AON", "amount": 5131.98},
            {"name": "Inne dochody", "amount": 50.0},
        ])
        self.assertEqual(overview["budgets"][0]["limit"], overview["income"])
        self.assertEqual(sum(item["amount"] for item in overview["expenseCategories"]), 100)
        self.assertFalse(any(item["key"] == "safe" for item in self.service.planning.onboarding()["items"]))
        self.assertEqual(self.service.planning.budget_suggestion("2026-10")["salaryBudget"]["sourceDate"], "2026-09-29")
        self.assertEqual(self.service.planning.report("2026-10")["income"], 50)
        self.service.planning.save_budget({"month": "2026-10", "limit": 4000})
        manual = self.service.planning.budget_status("2026-10", "2026-10-02")
        self.assertEqual(len(manual), 1)
        self.assertEqual(manual[0]["limit"], 4000)
        self.assertNotIn("source", manual[0])

    def test_unconfirmed_candidate_never_enters_forecast(self):
        self.import_rows(
            "01.06.2026;POSSIBLE;Konto 1234;Raw;-10,00;90,00",
            "01.07.2026;POSSIBLE;Konto 1234;Raw;-10,00;80,00",
            "01.08.2026;POSSIBLE;Konto 1234;Raw;-10,00;70,00",
        )
        self.assertTrue(self.service.planning.recurring_candidates())
        forecast = self.service.planning.forecast(horizon="30", reference_date="2026-09-01")
        self.assertFalse(any(event["name"] == "POSSIBLE" for event in forecast["events"]))

    def test_auto_budget_uses_current_month_inflows_without_aon_paycheck(self):
        self.import_rows(
            "01.10.2026;Additional income;Konto;Income;91,65;91,65",
            "02.10.2026;Refund;Konto;Refund;8,35;100,00",
        )
        for transaction in self.service.compatibility_payload()["transactions"]:
            self.service.classify_manually(transaction["id"], {
                "transactionKind": "refund" if transaction["description"] == "Refund" else "income"})
        overview = self.service.planning.overview("2026-10-02")
        self.assertEqual(overview["income"], 100)
        self.assertEqual(overview["budgets"][0]["limit"], 100)
        self.assertEqual(overview["budgets"][0]["source"], "monthly_inflows")

    def test_goal_card_counts_monthly_deposits_and_withdrawals(self):
        self.import_rows(
            "29.09.2026;AON SP. Z O.O. WYNAGRODZENIE ZA 9/2026;Konto;Income;1000,00;1000,00",
            "01.10.2026;Deposit to goal;Cele;Saving;100,00;100,00",
            "02.10.2026;Withdrawal from goal;Cele;Saving;-30,00;70,00",
        )
        for transaction in self.service.compatibility_payload()["transactions"]:
            if transaction["description"] in {"Deposit to goal", "Withdrawal from goal"}:
                self.service.classify_manually(transaction["id"], {"transactionKind": "transfer"})
        savings_account = next(account for account in self.service.planning.accounts()
                               if account["balance"] == 70)
        self.service.planning.update_account(savings_account["id"], {"role": "savings"})
        self.service.planning.save_goal({"name": "Emergency", "kind": "emergency_fund", "target": 55000,
                                        "allocated": 70, "linkedAccountId": savings_account["id"], "primary": True})

        overview = self.service.planning.overview("2026-10-02")
        self.assertEqual((overview["goalDeposits"], overview["goalWithdrawals"], overview["goalDepositRate"]),
                         (100, 30, 10.0))

    def test_goal_averages_use_may_and_first_account_month_and_include_bank_withdrawals(self):
        self.import_rows(
            "10.04.2026;April income;Konto;Income;100,00;100,00",
            "11.04.2026;April deposit;Cele;Saving;50,00;50,00",
            "12.04.2026;WYPŁATA Z CELU;Cele;Saving;-10,00;40,00",
            "10.05.2026;May income;Konto;Income;200,00;300,00",
            "11.05.2026;May deposit;Cele;Saving;100,00;140,00",
            "12.05.2026;WYPŁATA Z CELU;Cele;Saving;-40,00;100,00",
            "29.09.2026;AON SP. Z O.O. WYNAGRODZENIE ZA 9/2026;Konto;Income;1000,00;1300,00",
            "01.10.2026;October deposit;Cele;Saving;100,00;200,00",
            "02.10.2026;October withdrawal;Cele;Saving;-30,00;170,00",
        )
        for transaction in self.service.compatibility_payload()["transactions"]:
            description = transaction["description"]
            if description in {"April deposit", "May deposit", "October deposit", "October withdrawal"}:
                kind = "transfer"
            elif description == "WYPŁATA Z CELU":
                kind = "expense"  # mBank labels this internal withdrawal as an expense.
            else:
                kind = "income"
            self.service.classify_manually(transaction["id"], {"transactionKind": kind})
        savings_account = next(account for account in self.service.planning.accounts()
                               if account["balance"] == 170)
        self.service.planning.update_account(savings_account["id"], {"role": "savings"})
        self.service.planning.save_goal({"name": "Emergency", "kind": "emergency_fund", "target": 55000,
                                        "allocated": 170, "linkedAccountId": savings_account["id"], "primary": True})

        overview = self.service.planning.overview("2026-10-02")
        self.assertEqual((overview["goalDeposits"], overview["goalWithdrawals"]), (100, 30))
        self.assertEqual((overview["goalAverageMonths"], overview["goalAverageFrom"], overview["goalAverageTo"]),
                         (6, "2026-05", "2026-10"))
        self.assertEqual((overview["goalAverageDeposits"], overview["goalAverageWithdrawals"]), (33.33, 11.67))
        self.assertEqual((overview["goalAverageDepositRate"], overview["goalAverageWithdrawalRate"]), (16.7, 5.8))
        self.assertEqual((overview["goalLifetimeMonths"], overview["goalLifetimeFrom"]), (7, "2026-04"))
        self.assertEqual((overview["goalLifetimeDeposits"], overview["goalLifetimeWithdrawals"]), (35.71, 11.43))
        self.assertEqual((overview["goalLifetimeDepositRate"], overview["goalLifetimeWithdrawalRate"]), (19.2, 6.2))
        self.assertEqual(self.service.planning.overview("2026-05-17")["expenses"], 0)
        self.assertEqual(self.service.planning.budget_status("2026-05", "2026-05-17")[0]["spent"], 0)

    def test_advance_rent_is_budgeted_for_named_month_without_moving_bank_transaction(self):
        self.import_rows(
            "29.09.2026;AON SP. Z O.O. WYNAGRODZENIE ZA 9/2026;Konto;Income;5000,00;5000,00",
            "30.09.2026;CZYNSZ NAJMU ZA MIESIĄC PAŹDZIERNIK;Konto;Czynsz i wynajem;-2578,25;2421,75",
            "02.10.2026;Food;Konto;Food;-100,00;2321,75",
        )
        rent = next(row for row in self.service.compatibility_payload()["transactions"]
                    if "CZYNSZ NAJMU" in row["description"])
        food = next(row for row in self.service.compatibility_payload()["transactions"]
                    if row["description"] == "Food")
        self.service.classify_manually(rent["id"], {"transactionKind": "expense", "category": "Mieszkanie"})
        self.service.classify_manually(food["id"], {"transactionKind": "expense", "category": "Jedzenie"})

        september = self.service.planning.overview("2026-09-30")
        october = self.service.planning.overview("2026-10-02")
        self.assertEqual(september["expenses"], 0)
        self.assertEqual(october["expenses"], 2678.25)
        self.assertEqual(october["remainingFromIncome"], 2321.75)
        self.assertEqual(self.service.planning.budget_status("2026-10", "2026-10-02")[0]["spent"], 2678.25)
        self.assertEqual(next(row for row in self.service.compatibility_payload()["transactions"]
                              if row["id"] == rent["id"])["date"], "2026-09-30")
        self.assertEqual(_expense_budget_month("2026-12-30", "Czynsz najmu za miesiąc styczeń"), "2027-01")

    def test_report_and_non_persistent_simulation(self):
        self.import_rows(
            "02.09.2026;Salary;Konto 1234;Income;1000,00;1000,00",
            "03.09.2026;Expense;Konto 1234;Food;-250,00;750,00",
            "04.09.2026;Saving;Konto 1234;Saving;-100,00;650,00",
        )
        kinds = {"Salary": "salary", "Expense": "expense", "Saving": "saving"}
        for row in self.service.compatibility_payload()["transactions"]:
            self.service.classify_manually(row["id"], {"merchant": row["description"], "category": "Test", "transactionKind": kinds[row["description"]]})
        report = self.service.planning.report("2026-09")
        self.assertEqual(report["income"], 1000)
        self.assertEqual(report["expenses"], 250)
        self.assertEqual(report["savings"], 100)
        self.assertEqual(report["netCashFlow"], 650)
        before = len(self.service.planning.obligations())
        simulation = self.service.planning.simulate({"referenceDate": "2026-09-17", "scenarios": [{"kind": "spend_now", "amount": 100}]})
        self.assertFalse(simulation["persistent"])
        self.assertEqual(len(self.service.planning.obligations()), before)

    def test_rollback_preview_and_csv_formula_protection(self):
        result = self.import_rows("01.09.2026;=CMD();Konto 1234;Raw;-10,00;90,00")
        preview = self.service.rollback_import_preview(result["batchId"])
        self.assertEqual(preview["associated"], 1)
        self.assertEqual(preview["deleted"], 1)
        exported = self.service.export_transactions_csv({}).decode("utf-8-sig")
        self.assertIn("'=CMD()", exported)


if __name__ == "__main__":
    unittest.main()
