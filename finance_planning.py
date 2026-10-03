"""Deterministic planning products built on the canonical finance database.

This module owns obligations, Bills compatibility, budgets, goals, forecasts,
safe-to-spend, reports, and deterministic diagnostics.  It never creates bank
transactions and does not make probabilistic commitments from recurring
candidates.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import statistics
import uuid
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from finance_importer import normalize_text, transaction_family
from finance_repository import FinanceError, FinanceNotFoundError, FinanceRepository, utc_now


OUTFLOW_KINDS = {"bill", "subscription", "installment", "rent", "service", "saving"}
INCOME_KINDS = {"income", "salary"}
VALID_CADENCES = {"once", "weekly", "monthly", "quarterly", "annual"}
POLISH_MONTHS = ("styczen", "luty", "marzec", "kwiecien", "maj", "czerwiec",
                 "lipiec", "sierpien", "wrzesien", "pazdziernik", "listopad", "grudzien")
GOAL_AVERAGE_START = date(2026, 5, 1)


def _goal_movement(amount_minor: int, kind: str, description: str) -> str | None:
    if amount_minor > 0 and kind in {"transfer", "saving"}:
        return "deposit"
    if amount_minor < 0 and (kind in {"transfer", "saving"}
                             or transaction_family(description) == "goal_withdrawal"):
        return "withdrawal"
    return None


def _expense_budget_month(transaction_date: str, description: str) -> str:
    """Assign advance rent to its named month without changing the bank date."""
    actual = _date(transaction_date)
    text = normalize_text(description)
    if "czynsz" not in text and "najem" not in text:
        return actual.strftime("%Y-%m")
    match = re.search(r"\bza (?:miesiac )?(" + "|".join(POLISH_MONTHS) + r")\b", text)
    next_month = _month_add(actual.replace(day=1), 1)
    if match and POLISH_MONTHS[next_month.month - 1] == match.group(1):
        return next_month.strftime("%Y-%m")
    return actual.strftime("%Y-%m")


def _date(value: Any, *, field: str = "date") -> date:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise FinanceError(f"Invalid {field}; expected YYYY-MM-DD.") from exc


def _minor(payload: dict[str, Any], key: str = "amount", *, required: bool = True) -> int | None:
    minor_key = f"{key}Minor"
    value = payload.get(minor_key)
    if value is None and key in payload:
        try:
            value = round(float(payload[key]) * 100)
        except (TypeError, ValueError) as exc:
            raise FinanceError(f"Invalid {key}.") from exc
    if value is None:
        if required:
            raise FinanceError(f"{key} is required.")
        return None
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise FinanceError(f"Invalid {key}.") from exc
    if result < 0:
        raise FinanceError(f"{key} cannot be negative.")
    return result


def _money(minor: int | float | None) -> float:
    return round(float(minor or 0) / 100, 2)


def _month_add(value: date, months: int) -> date:
    index = value.year * 12 + value.month - 1 + months
    year, month_index = divmod(index, 12)
    month = month_index + 1
    return date(year, month, min(value.day, monthrange(year, month)[1]))


def _month_end(value: date) -> date:
    return date(value.year, value.month, monthrange(value.year, value.month)[1])


def _daterange_for_cadence(start: date, end: date, cadence: str):
    current = start
    step_months = {"monthly": 1, "quarterly": 3, "annual": 12}.get(cadence)
    while current <= end:
        yield current
        if cadence == "once":
            break
        if cadence == "weekly":
            current += timedelta(days=7)
        else:
            current = _month_add(current, step_months or 1)


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _legacy_definitions() -> list[dict[str, Any]]:
    """Return the complete definition layer formerly embedded in bills-store.js."""
    definitions: list[dict[str, Any]] = []

    def monthly(key: str, name: str, provider: str, group: str, amount: int,
                first: str, count: int, due_day: int, kind: str, *, automatic: bool = False,
                note: str = "") -> None:
        start = _date(first)
        occurrences = []
        for index in range(count):
            due = _month_add(start, index)
            due = date(due.year, due.month, min(due_day, monthrange(due.year, due.month)[1]))
            occurrences.append({"key": f"{key}-{due:%Y-%m}", "date": due.isoformat(), "amount": amount})
        definitions.append({
            "legacyKey": key, "name": name, "provider": provider, "group": group,
            "amount": amount, "kind": kind, "cadence": "monthly", "start": occurrences[0]["date"],
            "end": occurrences[-1]["date"], "dueDay": due_day, "automatic": automatic,
            "note": note, "occurrences": occurrences,
        })

    def once(key: str, name: str, provider: str, group: str, amount: int, due: str,
             kind: str, *, automatic: bool = False, note: str = "") -> None:
        definitions.append({
            "legacyKey": key, "name": name, "provider": provider, "group": group,
            "amount": amount, "kind": kind, "cadence": "once", "start": due, "end": due,
            "dueDay": int(due[-2:]), "automatic": automatic, "note": note,
            "occurrences": [{"key": key, "date": due, "amount": amount}],
        })

    monthly("rent", "Najem + czynsz administracyjny", "Mieszkanie", "Mieszkanie", 257825,
            "2026-08-05", 9, 5, "rent", note="Umowa do 30.04.2027; płatne z góry")
    monthly("play-internet", "Internet", "Play", "Mieszkanie", 7699,
            "2026-08-22", 9, 22, "service")
    for index, (due, amount) in enumerate((("2026-10-16", 21138), ("2026-12-16", 21138),
                                           ("2027-02-16", 21516), ("2027-04-16", 20381)), 1):
        once(f"orlen-gaz-{index}", "Gaz", "PGNiG / ORLEN", "Mieszkanie", amount, due, "bill")
    for index, (due, amount) in enumerate((("2026-09-21", 13511), ("2026-10-20", 13899),
                                           ("2026-11-20", 13511), ("2026-12-21", 13899)), 1):
        once(f"tauron-prad-{index}", "Prąd", "Tauron", "Mieszkanie", amount, due, "bill")
    for index, due in enumerate(("2026-10-12", "2026-11-10"), 1):
        once(f"allegro-pay-rower-{index}", "Rower stacjonarny", "Allegro Pay", "Raty",
             19450, due, "installment", note=f"{index} z 2 rat")
    monthly("santander-piano", "Pianino cyfrowe", "Santander — rata", "Raty", 14720,
            "2026-09-11", 12, 11, "installment", note="Raty 4–15 z 15")

    subscriptions = (
        ("chatgpt", "ChatGPT", "OpenAI", 10000, 17, None),
        ("cinema-city", "Cinema City Unlimited", "Cinema City", 5099, 16, None),
        ("spotify", "Spotify", "Spotify", 2699, 8, None),
        ("google-one", "Google One", "Google", 9799, 4, None),
        ("songsterr", "Songsterr", "Songsterr", 1999, 19, None),
        ("canal-plus", "Canal+", "CANAL+", 7900, 29, None),
        ("glovo-prime", "Glovo Prime", "Glovo", 1999, 2, "2026-09"),
    )
    for key, name, provider, amount, due_day, start_month in subscriptions:
        start = f"{start_month or '2026-08'}-{due_day:02d}"
        definition = {
            "legacyKey": f"subscription-{key}", "subscriptionId": key, "name": name,
            "provider": provider, "group": "Subskrypcje", "amount": amount,
            "kind": "subscription", "cadence": "monthly", "start": start, "end": None,
            "dueDay": due_day, "automatic": True, "note": "", "occurrences": [],
        }
        definitions.append(definition)
    return definitions


class FinancePlanningService:
    def __init__(self, repository: FinanceRepository, *, legacy_bills_path: Path | str | None = None,
                 backup_directory: Path | str | None = None):
        self.repository = repository
        self.legacy_bills_path = Path(legacy_bills_path) if legacy_bills_path else None
        self.backup_directory = Path(backup_directory) if backup_directory else repository.database_path.parent / "budget-backups"

    # ------------------------------------------------------------------ migration
    def migrate_legacy_bills(self) -> dict[str, Any] | None:
        path = self.legacy_bills_path
        if not path or not path.exists():
            return None
        raw = path.read_bytes()
        source_hash = hashlib.sha256(raw).hexdigest()
        marker_key = "pack_c_legacy_bills_v1"
        with self.repository.read_connection() as connection:
            marker = connection.execute("SELECT verification_json FROM data_migrations WHERE key=?", (marker_key,)).fetchone()
            if marker:
                return json.loads(marker[0])
        try:
            state = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FinanceError("Legacy Bills settings are invalid; migration was not started.") from exc

        definitions = _legacy_definitions()
        for custom in state.get("customBills") or []:
            if not isinstance(custom, dict) or not custom.get("id"):
                continue
            definitions.append({
                "legacyKey": str(custom["id"]), "name": str(custom.get("name") or "Planowana płatność"),
                "provider": str(custom.get("provider") or ""), "group": str(custom.get("category") or "Mieszkanie"),
                "amount": int(custom.get("amountCents") or 0), "kind": "bill",
                "cadence": "monthly" if custom.get("recurrence") == "monthly" else "once",
                "start": str(custom.get("due") or ""),
                "end": f"{custom['endMonth']}-28" if custom.get("endMonth") else None,
                "dueDay": int(str(custom.get("due") or "00")[-2:] or 0),
                "automatic": bool(custom.get("automatic")), "note": "", "occurrences": [],
            })

        self.backup_directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        source_backup = self.backup_directory / f"bills-legacy-source-{stamp}.json"
        snapshot_backup = self.backup_directory / f"bills-legacy-snapshot-{stamp}.json"
        shutil.copyfile(path, source_backup)
        snapshot_backup.write_text(json.dumps({"state": state, "definitions": definitions}, ensure_ascii=False, indent=2), encoding="utf-8")

        paid = {str(key) for key, value in (state.get("paid") or {}).items() if value}
        cancelled = {str(key) for key, value in (state.get("cancelledSubscriptions") or {}).items() if value}
        now = utc_now()
        inserted = 0
        expected_occurrences = 0
        with self.repository.transaction() as connection:
            for definition in definitions:
                if not definition.get("start") or int(definition.get("amount") or 0) <= 0:
                    continue
                legacy_key = definition["legacyKey"]
                obligation_id = f"obl_{hashlib.sha256(legacy_key.encode()).hexdigest()[:24]}"
                subscription_id = definition.get("subscriptionId")
                active = not (subscription_id and subscription_id in cancelled)
                installment_count = None
                if definition["kind"] == "installment":
                    installment_count = len(definition.get("occurrences") or []) or None
                connection.execute(
                    """
                    INSERT OR IGNORE INTO obligations(
                        id, legacy_key, name, provider, kind, display_group, amount_minor, currency,
                        cadence, next_expected_date, start_date, end_date, due_day, automatic,
                        active, confirmed, essential, installment_total_minor,
                        installment_remaining_minor, installment_count, installment_remaining_count,
                        note, notification_json, provenance, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'PLN', ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, 'legacy_bills', ?, ?)
                    """,
                    (obligation_id, legacy_key, definition["name"], definition["provider"], definition["kind"],
                     definition["group"], definition["amount"], definition["cadence"], definition["start"],
                     definition["start"], definition.get("end"), definition.get("dueDay"), int(definition["automatic"]),
                     int(active), int(definition["kind"] in {"rent", "bill", "service"}),
                     definition["amount"] * installment_count if installment_count else None,
                     definition["amount"] * installment_count if installment_count else None,
                     installment_count, installment_count, definition.get("note") or "",
                     json.dumps({"legacySubscriptionId": subscription_id, "notificationsEnabled": bool(state.get("notificationsEnabled"))}),
                     now, now),
                )
                if connection.execute("SELECT changes()").fetchone()[0]:
                    inserted += 1
                occurrences = list(definition.get("occurrences") or [])
                known_keys = {item["key"] for item in occurrences}
                for paid_key in sorted(paid):
                    if paid_key in known_keys or not paid_key.startswith(f"{legacy_key}-"):
                        continue
                    month = paid_key[-7:]
                    if len(month) != 7 or month[4] != "-":
                        continue
                    year, month_number = (int(part) for part in month.split("-"))
                    due_day = min(int(definition.get("dueDay") or 1), monthrange(year, month_number)[1])
                    amount = definition["amount"]
                    due = date(year, month_number, due_day).isoformat()
                    if legacy_key == "subscription-chatgpt" and month == "2026-09":
                        amount, due = 48844, "2026-09-16"
                    occurrences.append({"key": paid_key, "date": due, "amount": amount})
                    known_keys.add(paid_key)
                for occurrence in occurrences:
                    expected_occurrences += 1
                    status = "paid" if occurrence["key"] in paid else "expected"
                    connection.execute(
                        """INSERT OR IGNORE INTO obligation_occurrences(
                            id, obligation_id, expected_date, amount_minor, status,
                            legacy_occurrence_key, paid_at, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (_id("occ"), obligation_id, occurrence["date"], occurrence["amount"], status,
                         occurrence["key"], now if status == "paid" else None, now, now),
                    )

            verification = {
                "sourceSha256": source_hash,
                "sourceDefinitionCount": len(definitions),
                "canonicalObligationCount": connection.execute(
                    "SELECT COUNT(*) FROM obligations WHERE provenance='legacy_bills'"
                ).fetchone()[0],
                "sourcePaidCount": len(paid),
                "canonicalPaidCount": connection.execute(
                    "SELECT COUNT(*) FROM obligation_occurrences WHERE status='paid' AND legacy_occurrence_key IS NOT NULL"
                ).fetchone()[0],
                "expectedOccurrenceCount": expected_occurrences,
                "inserted": inserted,
                "sourceBackup": str(source_backup),
                "snapshotBackup": str(snapshot_backup),
            }
            if verification["canonicalObligationCount"] < len(definitions) or verification["canonicalPaidCount"] < len(paid):
                raise FinanceError("Legacy Bills migration verification failed; no changes were committed.")
            connection.execute(
                "INSERT INTO data_migrations(key, applied_at, verification_json) VALUES (?, ?, ?)",
                (marker_key, now, json.dumps(verification, ensure_ascii=False, sort_keys=True)),
            )
        return verification

    # ------------------------------------------------------------------ diagnostics/accounts
    def data_quality(self) -> dict[str, Any]:
        with self.repository.read_connection() as connection:
            row = dict(connection.execute(
                """SELECT COUNT(*) total,
                    SUM(merchant_id IS NOT NULL) merchant,
                    SUM(category_id IS NOT NULL) category,
                    SUM(transaction_kind IS NOT NULL) kind,
                    SUM(merchant_id IS NULL) unknown_merchants,
                    SUM(category_id IS NULL) missing_categories,
                    SUM(classification_conflict=1) rule_conflicts
                FROM transactions"""
            ).fetchone())
            total = int(row["total"] or 0)
            provenance: dict[str, int] = {}
            provenance_by_field: dict[str, dict[str, int]] = {}
            for column in ("merchant_source", "category_source", "merchant_type_source", "kind_source"):
                field_counts: dict[str, int] = {}
                for source, count in connection.execute(
                    f"SELECT COALESCE({column}, 'missing'), COUNT(*) FROM transactions GROUP BY COALESCE({column}, 'missing')"
                ):
                    source = str(source)
                    field_counts[source] = int(count)
                    bucket = {
                        "manual": "manual", "migrated": "migrated", "rule": "rule",
                        "merchant_default": "default", "system_fallback": "fallback",
                    }.get(source, source)
                    provenance[bucket] = provenance.get(bucket, 0) + int(count)
                provenance_by_field[column.removesuffix("_source")] = field_counts
            ambiguous = connection.execute("SELECT COUNT(*) FROM ambiguous_merchant_aliases").fetchone()[0]
            review_remaining = connection.execute(
                """SELECT COUNT(*) FROM transactions WHERE merchant_id IS NULL OR category_id IS NULL
                   OR transaction_kind IS NULL OR classification_conflict=1 OR taxonomy_review_required=1"""
            ).fetchone()[0]
            active_rules = connection.execute(
                "SELECT COUNT(*) FROM classification_rules WHERE enabled=1"
            ).fetchone()[0]
            bootstrap = dict(connection.execute(
                """SELECT COUNT(*) patterns,
                          SUM(decision='merchant_default') defaults_created,
                          SUM(decision='review') requiring_review
                   FROM classification_bootstrap_audit"""
            ).fetchone())
        percent = lambda value: round((int(value or 0) / total * 100), 1) if total else 100.0
        return {
            "totalTransactions": total,
            "merchantCoveragePercent": percent(row["merchant"]),
            "categoryCoveragePercent": percent(row["category"]),
            "transactionKindCoveragePercent": percent(row["kind"]),
            "unknownMerchantCount": int(row["unknown_merchants"] or 0),
            "missingCategoryCount": int(row["missing_categories"] or 0),
            "ruleConflictCount": int(row["rule_conflicts"] or 0),
            "ambiguousAliasCount": int(ambiguous),
            "reviewRemainingCount": int(review_remaining),
            "reviewedCount": max(0, total - int(review_remaining)),
            "activeRuleCount": int(active_rules),
            "classificationBootstrap": {
                "patternsAnalyzed": int(bootstrap.get("patterns") or 0),
                "defaultsCreated": int(bootstrap.get("defaults_created") or 0),
                "requiringReview": int(bootstrap.get("requiring_review") or 0),
                "threshold": "minimum 3 transactions and 100% consistent category/kind/type",
            },
            "provenanceCounts": provenance,
            "provenanceByField": provenance_by_field,
        }

    def accounts(self) -> list[dict[str, Any]]:
        with self.repository.read_connection() as connection:
            rows = connection.execute(
                """SELECT a.id, a.display_label, a.role, a.include_safe_to_spend,
                    COALESCE(a.balance_minor,
                      (SELECT t.raw_balance_minor FROM transactions t WHERE t.account_id=a.id
                       AND t.raw_balance_minor IS NOT NULL ORDER BY t.transaction_date DESC, t.id DESC LIMIT 1)) balance_minor,
                    (SELECT MAX(b.imported_at) FROM transactions t
                     JOIN transaction_imports ti ON ti.transaction_id=t.id
                     JOIN import_batches b ON b.id=ti.batch_id
                     WHERE t.account_id=a.id AND b.status='completed') last_imported_at,
                    (SELECT MAX(t.transaction_date) FROM transactions t WHERE t.account_id=a.id) latest_transaction_date
                FROM accounts a ORDER BY a.display_label"""
            ).fetchall()
        settings = self.repository.read_settings()
        spending = [row for row in rows if row["role"] == "spending"]
        selected_id = settings.get("mainSpendingAccountId")
        main_id = next((row["id"] for row in spending if row["id"] == selected_id), None)
        if main_id is None:
            main_id = next((row["id"] for row in spending if row["display_label"].casefold() == "konto główne"), None)
        if main_id is None and spending:
            main_id = min(row["id"] for row in spending)
        return [{"id": row["id"], "displayLabel": row["display_label"], "role": row["role"],
                 "includeSafeToSpend": bool(row["include_safe_to_spend"]), "balance": _money(row["balance_minor"]),
                 "main": row["id"] == main_id, "lastImportedAt": row["last_imported_at"],
                 "latestTransactionDate": row["latest_transaction_date"]} for row in rows]

    def classification_bootstrap(self) -> list[dict[str, Any]]:
        with self.repository.read_connection() as connection:
            rows = connection.execute(
                """SELECT a.*,m.canonical_name,c.name default_category,pc.name parent_category
                   FROM classification_bootstrap_audit a JOIN merchants m ON m.id=a.merchant_id
                   LEFT JOIN categories c ON c.id=m.default_category_id
                   LEFT JOIN categories pc ON pc.id=c.parent_id
                   ORDER BY a.decision='review',a.occurrence_count DESC,m.canonical_name"""
            ).fetchall()
        return [{
            "merchantId": row["merchant_id"], "merchant": row["canonical_name"],
            "occurrenceCount": row["occurrence_count"], "categoryCount": row["category_count"],
            "kindCount": row["kind_count"], "merchantTypeCount": row["merchant_type_count"],
            "decision": row["decision"], "reason": row["reason"],
            "defaultCategory": " / ".join(filter(None, (row["parent_category"], row["default_category"]))) or None,
        } for row in rows]

    def update_account(self, account_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        role = str(payload.get("role") or "")
        if role not in {"spending", "savings", "excluded"}:
            raise FinanceError("Invalid account role.")
        include = int(bool(payload.get("includeSafeToSpend", role == "spending")))
        display_label = " ".join(str(payload.get("displayLabel") or "").split())[:120]
        with self.repository.transaction() as connection:
            result = connection.execute(
                """UPDATE accounts SET role=?, include_safe_to_spend=?,
                   display_label=CASE WHEN ?='' THEN display_label ELSE ? END, updated_at=? WHERE id=?""",
                (role, include, display_label, display_label, utc_now(), account_id),
            )
            if result.rowcount != 1:
                raise FinanceNotFoundError("Account was not found.")
            settings = {"accountRolesConfigured": True}
            if payload.get("main") and role == "spending":
                settings["mainSpendingAccountId"] = account_id
            self.repository.write_settings(settings, connection=connection)
        return next(account for account in self.accounts() if account["id"] == account_id)

    def update_safe_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        buffer_minor = _minor(payload, "buffer", required=False)
        if buffer_minor is None:
            buffer_minor = int(payload.get("bufferMinor") or 0)
        self.repository.write_settings({
            "safeToSpendBufferMinor": buffer_minor,
            "safeToSpendConfigured": True,
        })
        return {"safetyBuffer": _money(buffer_minor), "configured": True}

    # ------------------------------------------------------------------ obligations/Bills
    @staticmethod
    def _obligation_dict(row: Any) -> dict[str, Any]:
        return {
            "id": row["id"], "legacyKey": row["legacy_key"], "name": row["name"],
            "provider": row["provider"], "kind": row["kind"], "group": row["display_group"],
            "amount": _money(row["amount_minor"]), "amountMinor": row["amount_minor"],
            "currency": row["currency"], "accountId": row["account_id"], "categoryId": row["category_id"],
            "merchantId": row["merchant_id"], "cadence": row["cadence"],
            "nextExpectedDate": row["next_expected_date"], "startDate": row["start_date"],
            "endDate": row["end_date"], "dueDay": row["due_day"], "automatic": bool(row["automatic"]),
            "active": bool(row["active"]), "confirmed": bool(row["confirmed"]),
            "essential": bool(row["essential"]), "installmentTotal": _money(row["installment_total_minor"]),
            "installmentRemaining": _money(row["installment_remaining_minor"]),
            "installmentCount": row["installment_count"], "installmentRemainingCount": row["installment_remaining_count"],
            "note": row["note"], "provenance": row["provenance"],
        }

    def obligations(self, *, active: bool | None = None, kind: str | None = None) -> list[dict[str, Any]]:
        clauses, params = [], []
        if active is not None:
            clauses.append("active=?"); params.append(int(active))
        if kind:
            clauses.append("kind=?"); params.append(kind)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        with self.repository.read_connection() as connection:
            rows = connection.execute(f"SELECT * FROM obligations {where} ORDER BY active DESC, next_expected_date, name", params).fetchall()
        return [self._obligation_dict(row) for row in rows]

    def subscriptions(self) -> list[dict[str, Any]]:
        items = self.obligations(kind="subscription")
        multiplier = {"weekly": 52, "monthly": 12, "quarterly": 4, "annual": 1, "once": 1}
        with self.repository.read_connection() as connection:
            for item in items:
                charges = connection.execute(
                    """SELECT expected_date, amount_minor, status FROM obligation_occurrences
                       WHERE obligation_id=? ORDER BY expected_date DESC""", (item["id"],)
                ).fetchall()
                values = [row["amount_minor"] for row in reversed(charges)]
                item["monthlyEquivalent"] = _money(item["amountMinor"] * multiplier[item["cadence"]] / 12)
                item["annualCost"] = _money(item["amountMinor"] * multiplier[item["cadence"]])
                item["historicalCharges"] = [
                    {"date": row["expected_date"], "amount": _money(row["amount_minor"]), "status": row["status"]}
                    for row in charges
                ]
                item["priceChanges"] = [
                    {"from": _money(before), "to": _money(after)}
                    for before, after in zip(values, values[1:]) if before != after
                ]
        return items

    def save_obligation(self, payload: dict[str, Any], obligation_id: str | None = None) -> dict[str, Any]:
        name = " ".join(str(payload.get("name") or "").split())[:160]
        if not name:
            raise FinanceError("Obligation name is required.")
        kind = str(payload.get("kind") or "bill")
        if kind not in OUTFLOW_KINDS | INCOME_KINDS:
            raise FinanceError("Invalid obligation kind.")
        cadence = str(payload.get("cadence") or "once")
        if cadence not in VALID_CADENCES:
            raise FinanceError("Invalid obligation cadence.")
        amount = _minor(payload)
        start = _date(payload.get("startDate") or payload.get("nextExpectedDate"), field="start date")
        next_date = _date(payload.get("nextExpectedDate") or start.isoformat(), field="next expected date")
        end_value = payload.get("endDate") or None
        if end_value and _date(end_value, field="end date") < start:
            raise FinanceError("End date cannot precede start date.")
        now = utc_now()
        target_id = obligation_id or _id("obl")
        with self.repository.transaction() as connection:
            if obligation_id:
                result = connection.execute(
                    """UPDATE obligations SET name=?, provider=?, kind=?, display_group=?, amount_minor=?, currency=?,
                       account_id=?, category_id=?, merchant_id=?, cadence=?, next_expected_date=?, start_date=?, end_date=?,
                       due_day=?, automatic=?, active=?, confirmed=?, essential=?, installment_total_minor=?,
                       installment_remaining_minor=?, installment_count=?, installment_remaining_count=?, note=?, updated_at=?
                       WHERE id=?""",
                    (name, str(payload.get("provider") or "")[:160], kind, str(payload.get("group") or "Bills")[:80], amount,
                     str(payload.get("currency") or "PLN")[:3].upper(), payload.get("accountId"), payload.get("categoryId"),
                     payload.get("merchantId"), cadence, next_date.isoformat(), start.isoformat(), end_value,
                     int(payload.get("dueDay") or next_date.day), int(bool(payload.get("automatic"))),
                     int(payload.get("active", True) is not False), int(payload.get("confirmed", True) is not False),
                     int(bool(payload.get("essential"))), _minor(payload, "installmentTotal", required=False),
                     _minor(payload, "installmentRemaining", required=False), payload.get("installmentCount"),
                     payload.get("installmentRemainingCount"), str(payload.get("note") or "")[:1000], now, target_id),
                )
                if result.rowcount != 1:
                    raise FinanceNotFoundError("Obligation was not found.")
            else:
                connection.execute(
                    """INSERT INTO obligations(id,name,provider,kind,display_group,amount_minor,currency,account_id,
                       category_id,merchant_id,cadence,next_expected_date,start_date,end_date,due_day,automatic,active,
                       confirmed,essential,installment_total_minor,installment_remaining_minor,installment_count,
                       installment_remaining_count,note,notification_json,provenance,created_at,updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'manual',?,?)""",
                    (target_id, name, str(payload.get("provider") or "")[:160], kind, str(payload.get("group") or "Bills")[:80],
                     amount, str(payload.get("currency") or "PLN")[:3].upper(), payload.get("accountId"), payload.get("categoryId"),
                     payload.get("merchantId"), cadence, next_date.isoformat(), start.isoformat(), end_value,
                     int(payload.get("dueDay") or next_date.day), int(bool(payload.get("automatic"))),
                     int(payload.get("active", True) is not False), int(payload.get("confirmed", True) is not False),
                     int(bool(payload.get("essential"))), _minor(payload, "installmentTotal", required=False),
                     _minor(payload, "installmentRemaining", required=False), payload.get("installmentCount"),
                     payload.get("installmentRemainingCount"), str(payload.get("note") or "")[:1000], "{}", now, now),
                )
        return next(item for item in self.obligations() if item["id"] == target_id)

    def _generated_occurrences(self, date_from: date, date_to: date, *, confirmed_only: bool = True) -> list[dict[str, Any]]:
        clauses = ["active=1"]
        if confirmed_only:
            clauses.append("confirmed=1")
        with self.repository.read_connection() as connection:
            obligations = connection.execute(f"SELECT * FROM obligations WHERE {' AND '.join(clauses)}").fetchall()
            stored = connection.execute(
                """SELECT oo.*, o.name, o.provider, o.kind, o.display_group, o.automatic, o.note obligation_note,
                          o.cadence, o.legacy_key
                   FROM obligation_occurrences oo JOIN obligations o ON o.id=oo.obligation_id
                   WHERE o.active=1 AND (
                       oo.expected_date BETWEEN ? AND ?
                       OR (o.cadence IN ('monthly', 'quarterly', 'annual')
                           AND substr(oo.expected_date, 1, 7) BETWEEN ? AND ?)
                   )""",
                (date_from.isoformat(), date_to.isoformat(),
                 date_from.strftime("%Y-%m"), date_to.strftime("%Y-%m")),
            ).fetchall()
        by_pair = {(row["obligation_id"], row["expected_date"]): row for row in stored}
        by_legacy_key = {
            (row["obligation_id"], row["legacy_occurrence_key"]): row
            for row in stored if row["legacy_occurrence_key"]
        }
        result: list[dict[str, Any]] = []
        for obligation in obligations:
            start = max(_date(obligation["start_date"]), date_from)
            first = _date(obligation["start_date"])
            cadence = obligation["cadence"]
            end = min(date_to, _date(obligation["end_date"]) if obligation["end_date"] else date_to)
            if cadence == "once" and (first < date_from or first > end):
                continue
            if cadence == "weekly":
                delta = max(0, (start - first).days)
                first = first + timedelta(days=math.ceil(delta / 7) * 7)
            elif cadence != "once":
                step = {"monthly": 1, "quarterly": 3, "annual": 12}[cadence]
                while first < start:
                    first = _month_add(first, step)
            for expected in _daterange_for_cadence(first, end, cadence):
                generated_legacy_key = None
                if obligation["legacy_key"]:
                    if obligation["legacy_key"].startswith("subscription-") or cadence == "monthly":
                        generated_legacy_key = f"{obligation['legacy_key']}-{expected:%Y-%m}"
                    else:
                        generated_legacy_key = obligation["legacy_key"]
                stored_row = by_pair.get((obligation["id"], expected.isoformat()))
                if not stored_row and generated_legacy_key:
                    stored_row = by_legacy_key.get((obligation["id"], generated_legacy_key))
                effective_date = _date(stored_row["expected_date"]) if stored_row else expected
                if effective_date < date_from or effective_date > date_to:
                    continue
                status = stored_row["status"] if stored_row else "expected"
                amount = stored_row["amount_minor"] if stored_row else obligation["amount_minor"]
                legacy_key = stored_row["legacy_occurrence_key"] if stored_row else generated_legacy_key
                result.append({
                    "id": stored_row["id"] if stored_row else f"{obligation['id']}:{expected.isoformat()}",
                    "obligationId": obligation["id"], "legacyKey": legacy_key,
                    "date": effective_date.isoformat(), "amountMinor": int(amount), "amount": _money(amount),
                    "status": status, "name": obligation["name"], "provider": obligation["provider"],
                    "kind": obligation["kind"], "group": obligation["display_group"],
                    "automatic": bool(obligation["automatic"]), "note": obligation["note"],
                    "cadence": cadence, "paidAt": stored_row["paid_at"] if stored_row else None,
                })
        # Stored overrides whose dates differ from the generated cadence remain authoritative.
        present = {(item["obligationId"], item["date"]) for item in result}
        for row in stored:
            if row["expected_date"] < date_from.isoformat() or row["expected_date"] > date_to.isoformat():
                continue
            if (row["obligation_id"], row["expected_date"]) in present:
                continue
            result.append({"id": row["id"], "obligationId": row["obligation_id"],
                "legacyKey": row["legacy_occurrence_key"], "date": row["expected_date"],
                "amountMinor": row["amount_minor"], "amount": _money(row["amount_minor"]), "status": row["status"],
                "name": row["name"], "provider": row["provider"], "kind": row["kind"],
                "group": row["display_group"], "automatic": bool(row["automatic"]),
                "note": row["obligation_note"], "cadence": row["cadence"],
                "paidAt": row["paid_at"]})
        return sorted(result, key=lambda item: (item["date"], item["name"], item["id"]))

    def upcoming(self, *, date_from: str | None = None, date_to: str | None = None,
                 days: int = 30, reference_date: str | None = None,
                 include_completed: bool = False) -> list[dict[str, Any]]:
        today = _date(reference_date) if reference_date else date.today()
        start = _date(date_from) if date_from else today
        end = _date(date_to) if date_to else start + timedelta(days=max(0, min(int(days), 366)))
        events = self._generated_occurrences(start, end)
        if include_completed:
            return events
        return [event for event in events if event["status"] not in {"paid", "matched", "skipped", "dismissed"}]

    def bills_payload(self, reference_date: str | None = None) -> dict[str, Any]:
        today = _date(reference_date) if reference_date else date.today()
        start = date(2026, 8, 1) if today < date(2027, 8, 1) else _month_add(date(today.year, today.month, 1), -1)
        end = max(date(2027, 8, 31), _month_add(date(today.year, today.month, 1), 12))
        occurrences = self._generated_occurrences(start, end)
        bills = []
        for item in occurrences:
            status = item["status"]
            due_date = _date(item["date"])
            paid = status in {"paid", "matched"} or (item["automatic"] and due_date < today)
            reminder_from = due_date - timedelta(days=7)
            if item["kind"] == "rent":
                previous_month_end = due_date.replace(day=1) - timedelta(days=1)
                reminder_from = previous_month_end - timedelta(days=1)
            bills.append({
                "id": item["legacyKey"] or item["id"], "obligationId": item["obligationId"],
                "name": item["name"], "provider": item["provider"], "category": item["group"],
                "amountCents": item["amountMinor"], "due": item["date"], "month": item["date"][:7],
                "reminderFrom": reminder_from.isoformat(),
                "kind": item["kind"], "automatic": item["automatic"],
                "status": status, "paidAt": item.get("paidAt"),
                "paid": paid,
                "subscriptionId": item["obligationId"] if item["kind"] == "subscription" else None,
                "customId": item["obligationId"] if item["kind"] == "bill" and (
                    not item["legacyKey"] or str(item["legacyKey"]).startswith("custom-")
                ) else None,
                "note": item["note"],
            })
        settings = self.repository.read_settings()
        return {"bills": bills, "notificationsEnabled": bool(settings.get("billsNotificationsEnabled", True)),
                "source": "finance.sqlite"}

    def set_occurrence_status(self, occurrence_key: str, status: str) -> dict[str, Any]:
        if status not in {"expected", "paid", "skipped", "dismissed"}:
            raise FinanceError("Invalid occurrence status.")
        with self.repository.transaction() as connection:
            stored = connection.execute(
                "SELECT * FROM obligation_occurrences WHERE id=? OR legacy_occurrence_key=?",
                (occurrence_key, occurrence_key),
            ).fetchone()
            if stored:
                now = utc_now()
                connection.execute(
                    "UPDATE obligation_occurrences SET status=?,paid_at=?,updated_at=? WHERE id=?",
                    (status, now if status == "paid" else None, now, stored["id"]),
                )
                return {"id": stored["id"], "status": status,
                        "dueDate": stored["expected_date"],
                        "paidAt": now if status == "paid" else None}
        # Generated occurrence key contains an obligation id and ISO date.
        if ":" not in occurrence_key:
            # Resolve a generated legacy key from the Bills projection.
            match = next((item for item in self.bills_payload()["bills"] if item["id"] == occurrence_key), None)
            if not match:
                raise FinanceNotFoundError("Expected payment was not found.")
            obligation_id, expected_date, legacy = match["obligationId"], match["due"], occurrence_key
        else:
            obligation_id, expected_date = occurrence_key.rsplit(":", 1)
            _date(expected_date)
            legacy = None
        with self.repository.transaction() as connection:
            obligation = connection.execute("SELECT amount_minor FROM obligations WHERE id=?", (obligation_id,)).fetchone()
            if not obligation:
                raise FinanceNotFoundError("Obligation was not found.")
            occurrence_id = _id("occ")
            connection.execute(
                """INSERT INTO obligation_occurrences(id,obligation_id,expected_date,amount_minor,status,
                   legacy_occurrence_key,paid_at,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)""",
                (occurrence_id, obligation_id, expected_date, obligation["amount_minor"], status,
                 legacy, utc_now() if status == "paid" else None, utc_now(), utc_now()),
            )
        return {"id": occurrence_id, "status": status, "dueDate": expected_date,
                "paidAt": utc_now() if status == "paid" else None}

    def deactivate_obligation(self, obligation_id: str) -> dict[str, Any]:
        with self.repository.transaction() as connection:
            result = connection.execute("UPDATE obligations SET active=0, updated_at=? WHERE id=?", (utc_now(), obligation_id))
            if result.rowcount != 1:
                raise FinanceNotFoundError("Obligation was not found.")
        return {"id": obligation_id, "active": False}

    def set_bills_notifications(self, enabled: bool) -> dict[str, Any]:
        self.repository.write_settings({"billsNotificationsEnabled": bool(enabled)})
        return {"enabled": bool(enabled)}

    # ------------------------------------------------------------------ recurring detection
    def recurring_candidates(self, *, minimum: int = 3) -> list[dict[str, Any]]:
        with self.repository.read_connection() as connection:
            rows = connection.execute(
                """SELECT t.id, t.transaction_date, ABS(t.amount_minor) amount_minor, t.transaction_kind,
                          COALESCE(m.canonical_name, NULLIF(TRIM(t.merchant), ''), t.raw_description) merchant,
                          t.merchant_id, t.category_id
                   FROM transactions t LEFT JOIN merchants m ON m.id=t.merchant_id
                   WHERE t.transaction_kind NOT IN ('transfer','saving')
                   ORDER BY merchant, t.transaction_date"""
            ).fetchall()
        groups: dict[tuple[Any, ...], list[Any]] = {}
        for row in rows:
            key = (row["merchant_id"] or str(row["merchant"]).casefold(), row["transaction_kind"], row["category_id"])
            groups.setdefault(key, []).append(row)
        candidates = []
        for values in groups.values():
            if len(values) < minimum:
                continue
            dates = sorted(_date(row["transaction_date"]) for row in values)
            intervals = [(right - left).days for left, right in zip(dates, dates[1:])]
            median_interval = statistics.median(intervals)
            cadence = None
            for name, low, high in (("weekly", 5, 9), ("monthly", 25, 35), ("quarterly", 75, 100), ("annual", 330, 400)):
                if low <= median_interval <= high and sum(low <= interval <= high for interval in intervals) / len(intervals) >= .6:
                    cadence = name; break
            if not cadence:
                continue
            amounts = [int(row["amount_minor"]) for row in values]
            mean = statistics.mean(amounts)
            variance = (max(amounts) - min(amounts)) / mean * 100 if mean else 0
            next_date = _month_add(dates[-1], {"monthly": 1, "quarterly": 3, "annual": 12}[cadence]) \
                if cadence != "weekly" else dates[-1] + timedelta(days=7)
            candidates.append({
                "candidateId": hashlib.sha256(repr((values[0]["merchant"], values[0]["transaction_kind"], values[0]["category_id"])).encode()).hexdigest()[:20],
                "merchant": values[0]["merchant"], "transactionKind": values[0]["transaction_kind"],
                "categoryId": values[0]["category_id"], "cadence": cadence, "confirmed": False,
                "evidence": {"occurrenceCount": len(values), "medianIntervalDays": median_interval,
                             "amountMin": _money(min(amounts)), "amountMax": _money(max(amounts)),
                             "amountVariancePercent": round(variance, 1), "lastOccurrence": dates[-1].isoformat(),
                             "likelyNextDate": next_date.isoformat()},
            })
        return sorted(candidates, key=lambda item: (-item["evidence"]["occurrenceCount"], item["merchant"]))

    # ------------------------------------------------------------------ budgets
    def _aon_salary_budget(self, month: str) -> dict[str, Any] | None:
        start = _date(month + "-01")
        previous = _month_add(start, -1)
        title = re.compile(rf"\bWYNAGRODZENIE ZA\s*0?{previous.month}/{previous.year}\b", re.IGNORECASE)
        with self.repository.read_connection() as connection:
            rows = connection.execute(
                """SELECT transaction_date, amount_minor, raw_description FROM transactions
                   WHERE transaction_date BETWEEN ? AND ? AND amount_minor > 0
                     AND UPPER(raw_description) LIKE '%AON SP. Z O.O.%'
                     AND UPPER(raw_description) LIKE '%WYNAGRODZENIE ZA%'""",
                (previous.isoformat(), _month_end(previous).isoformat()),
            ).fetchall()
        paychecks = [row for row in rows if title.search(row["raw_description"])]
        if not paychecks:
            return None
        return {"amountMinor": sum(row["amount_minor"] for row in paychecks),
            "sourceMonth": previous.strftime("%Y-%m"),
            "sourceDate": max(row["transaction_date"] for row in paychecks)}

    def _month_income_sources_minor(self, month: str) -> dict[str, int]:
        start = _date(month + "-01"); end = _month_end(start)
        with self.repository.read_connection() as connection:
            rows = connection.execute(
                """SELECT amount_minor,transaction_kind,raw_description FROM transactions
                   WHERE transaction_date BETWEEN ? AND ? AND amount_minor>0
                     AND transaction_kind IN ('salary','income','refund','other')""",
                (start.isoformat(), end.isoformat()),
            ).fetchall()
        incomes: dict[str, int] = {}
        labels = {"salary": "Inne wynagrodzenia", "income": "Inne dochody",
                  "refund": "Zwroty", "other": "Pozostałe wpływy"}
        for row in rows:
            description = str(row["raw_description"] or "").upper()
            if "AON SP. Z O.O." in description and "WYNAGRODZENIE ZA" in description:
                continue  # This paycheck funds the following month.
            source = labels[row["transaction_kind"]]
            incomes[source] = incomes.get(source, 0) + int(row["amount_minor"])
        paycheck = self._aon_salary_budget(month)
        if paycheck:
            incomes["Wynagrodzenie AON"] = incomes.get("Wynagrodzenie AON", 0) + paycheck["amountMinor"]
        return incomes

    def save_budget(self, payload: dict[str, Any]) -> dict[str, Any]:
        month = str(payload.get("month") or date.today().strftime("%Y-%m"))
        if not (len(month) == 7 and month[4] == "-"):
            raise FinanceError("Invalid budget month.")
        _date(month + "-01")
        category_id = payload.get("categoryId")
        category_id = int(category_id) if category_id not in (None, "") else None
        limit_minor = _minor(payload, "limit")
        now = utc_now()
        with self.repository.transaction() as connection:
            existing = connection.execute("SELECT id FROM budgets WHERE month=? AND category_id IS ?", (month, category_id)).fetchone()
            if existing:
                connection.execute("UPDATE budgets SET limit_minor=?, updated_at=? WHERE id=?", (limit_minor, now, existing["id"]))
            else:
                connection.execute("INSERT INTO budgets(month,category_id,limit_minor,created_at,updated_at) VALUES (?,?,?,?,?)",
                                   (month, category_id, limit_minor, now, now))
        return next(item for item in self.budget_status(month) if item["categoryId"] == category_id)

    def budget_status(self, month: str | None = None, reference_date: str | None = None) -> list[dict[str, Any]]:
        reference = _date(reference_date) if reference_date else date.today()
        month = month or reference.strftime("%Y-%m")
        start = _date(month + "-01"); end = _month_end(start)
        if reference < start: elapsed = 0.0
        elif reference > end: elapsed = 100.0
        else: elapsed = reference.day / end.day * 100
        with self.repository.read_connection() as connection:
            rows = connection.execute(
                """SELECT b.*, c.name category_name
                   FROM budgets b LEFT JOIN categories c ON c.id=b.category_id
                   WHERE b.month=? ORDER BY b.category_id IS NOT NULL, c.name""",
                (month,),
            ).fetchall()
            expense_rows = connection.execute(
                """SELECT t.transaction_date,t.amount_minor,t.raw_description,t.category_id,c.parent_id
                   FROM transactions t LEFT JOIN categories c ON c.id=t.category_id
                   WHERE t.transaction_kind='expense' AND t.amount_minor<0
                     AND t.transaction_date BETWEEN ? AND ?""",
                (_month_add(start, -1).isoformat(), end.isoformat()),
            ).fetchall()
        month_expenses = [transaction for transaction in expense_rows
                          if _expense_budget_month(transaction["transaction_date"], transaction["raw_description"]) == month
                          and transaction_family(transaction["raw_description"]) != "goal_withdrawal"]
        auto_spent = sum(-int(transaction["amount_minor"]) for transaction in month_expenses)
        result = []
        for row in rows:
            spent = sum(-int(transaction["amount_minor"]) for transaction in month_expenses
                        if row["category_id"] is None or row["category_id"] in
                        (transaction["category_id"], transaction["parent_id"]))
            limit = int(row["limit_minor"])
            used = spent / limit * 100 if limit else 0
            projected = round(spent / (elapsed / 100)) if 0 < elapsed < 100 else spent
            result.append({"id": row["id"], "month": month, "categoryId": row["category_id"],
                "category": row["category_name"] or "Overall", "limit": _money(limit), "spent": _money(spent),
                "remaining": _money(max(0, limit - spent)), "usedPercent": round(used, 1),
                "elapsedPercent": round(elapsed, 1), "paceDeviationPoints": round(used - elapsed, 1),
                "projected": _money(projected), "status": "over" if used > 100 else "ahead" if used > elapsed + 10 else "on_pace"})
        if not any(item["categoryId"] is None for item in result):
            income_minor = sum(self._month_income_sources_minor(month).values())
            paycheck = self._aon_salary_budget(month)
            if income_minor:
                spent, limit = int(auto_spent or 0), income_minor
                used = spent / limit * 100
                projected = round(spent / (elapsed / 100)) if 0 < elapsed < 100 else spent
                result.insert(0, {"id": None, "month": month, "categoryId": None,
                    "category": "Budżet ogólny", "limit": _money(limit), "spent": _money(spent),
                    "remaining": _money(max(0, limit - spent)), "usedPercent": round(used, 1),
                    "elapsedPercent": round(elapsed, 1), "paceDeviationPoints": round(used - elapsed, 1),
                    "projected": _money(projected),
                    "status": "over" if used > 100 else "ahead" if used > elapsed + 10 else "on_pace",
                    "source": "monthly_inflows", "sourceDate": paycheck["sourceDate"] if paycheck else None})
        overall = next((item for item in result if item["categoryId"] is None), None)
        if overall:
            remaining_start = max(start, reference)
            remaining_days = max(0, (end - remaining_start).days + 1)
            planned_minor = 0
            if remaining_days:
                planned_minor += sum(event["amountMinor"] for event in
                    self._generated_occurrences(remaining_start, end)
                    if event["kind"] in OUTFLOW_KINDS and event["status"] not in {"paid", "matched", "skipped", "dismissed"})
                planned_minor += sum(item["amountMinor"] for item in self.planned_items()
                    if remaining_start.isoformat() <= item["date"] <= end.isoformat()
                    and item["kind"] in {"expense", "saving"})
            free_minor = round(overall["limit"] * 100) - round(overall["spent"] * 100) - planned_minor
            overall.update({"dailyLimit": _money(round(overall["limit"] * 100 / end.day)),
                "plannedRemaining": _money(planned_minor), "freeAfterScheduled": _money(free_minor),
                "remainingDays": remaining_days,
                "freePerDay": _money(round(free_minor / remaining_days)) if remaining_days else None})
        return result

    def budget_suggestion(self, month: str | None = None, category_id: int | None = None) -> dict[str, Any]:
        month = month or date.today().strftime("%Y-%m")
        _date(month + "-01")
        paycheck = self._aon_salary_budget(month)
        with self.repository.read_connection() as connection:
            rows = connection.execute(
                """SELECT SUBSTR(t.transaction_date,1,7) month,SUM(ABS(t.amount_minor)) spent_minor
                   FROM transactions t LEFT JOIN categories c ON c.id=t.category_id
                   WHERE t.transaction_kind='expense' AND SUBSTR(t.transaction_date,1,7)<?
                     AND (? IS NULL OR t.category_id=? OR c.parent_id=?)
                   GROUP BY SUBSTR(t.transaction_date,1,7) ORDER BY month""",
                (month, category_id, category_id, category_id),
            ).fetchall()
        values = [int(row["spent_minor"] or 0) for row in rows]
        average = round(sum(values) / len(values)) if values else 0
        suggested = int(math.ceil(average / 5000) * 5000) if average else 0
        previous = rows[-1] if rows else None
        return {
            "month": month, "categoryId": category_id, "historyMonthCount": len(values),
            "averageMonthly": _money(average),
            "previousMonth": previous["month"] if previous else None,
            "previousMonthSpending": _money(previous["spent_minor"] if previous else 0),
            "suggestedLimit": _money(suggested), "applied": False,
            "salaryBudget": {"amount": _money(paycheck["amountMinor"]), "sourceMonth": paycheck["sourceMonth"],
                "sourceDate": paycheck["sourceDate"]} if paycheck and category_id is None else None,
            "explanation": "Sugestia jest zaokrągloną w górę średnią historyczną; nie jest zapisywana automatycznie.",
        }

    # ------------------------------------------------------------------ planned items/goals
    def planned_items(self, *, active_only: bool = True) -> list[dict[str, Any]]:
        where = "WHERE status='planned'" if active_only else ""
        with self.repository.read_connection() as connection:
            rows = connection.execute(f"SELECT * FROM planned_items {where} ORDER BY planned_date,name").fetchall()
        return [{"id": r["id"], "name": r["name"], "date": r["planned_date"], "amount": _money(r["amount_minor"]),
                 "amountMinor": r["amount_minor"], "currency": r["currency"], "accountId": r["account_id"],
                 "categoryId": r["category_id"], "kind": r["kind"], "note": r["note"],
                 "includeSafeToSpend": bool(r["include_safe_to_spend"]), "status": r["status"]} for r in rows]

    def save_planned_item(self, payload: dict[str, Any], item_id: str | None = None) -> dict[str, Any]:
        name = " ".join(str(payload.get("name") or "").split())[:160]
        if not name: raise FinanceError("Planned item name is required.")
        planned_date = _date(payload.get("date"), field="planned date").isoformat()
        kind = str(payload.get("kind") or "expense")
        if kind not in {"expense", "income", "saving"}: raise FinanceError("Invalid planned item kind.")
        target = item_id or _id("plan"); now = utc_now(); amount = _minor(payload)
        with self.repository.transaction() as connection:
            if item_id:
                result = connection.execute(
                    """UPDATE planned_items SET name=?,planned_date=?,amount_minor=?,currency=?,account_id=?,category_id=?,
                       kind=?,note=?,include_safe_to_spend=?,status=?,updated_at=? WHERE id=?""",
                    (name, planned_date, amount, str(payload.get("currency") or "PLN")[:3].upper(), payload.get("accountId"),
                     payload.get("categoryId"), kind, str(payload.get("note") or "")[:1000],
                     int(payload.get("includeSafeToSpend", True) is not False), str(payload.get("status") or "planned"), now, target))
                if result.rowcount != 1: raise FinanceNotFoundError("Planned item was not found.")
            else:
                connection.execute(
                    """INSERT INTO planned_items(id,name,planned_date,amount_minor,currency,account_id,category_id,kind,note,
                       include_safe_to_spend,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?, 'planned',?,?)""",
                    (target, name, planned_date, amount, str(payload.get("currency") or "PLN")[:3].upper(), payload.get("accountId"),
                     payload.get("categoryId"), kind, str(payload.get("note") or "")[:1000],
                     int(payload.get("includeSafeToSpend", True) is not False), now, now))
        return next(item for item in self.planned_items(active_only=False) if item["id"] == target)

    def goals(self, reference_date: str | None = None) -> list[dict[str, Any]]:
        today = _date(reference_date) if reference_date else date.today()
        with self.repository.read_connection() as connection:
            rows = connection.execute(
                """SELECT g.*,a.balance_minor linked_balance_minor
                   FROM goals g LEFT JOIN accounts a ON a.id=g.linked_account_id
                   ORDER BY g.active DESC,g.is_primary DESC,g.created_at"""
            ).fetchall()
        result = []
        for row in rows:
            target = row["target_minor"]
            allocated = max(0, row["linked_balance_minor"]) if row["linked_account_id"] is not None and row["linked_balance_minor"] is not None else row["allocated_minor"]
            monthly = row["monthly_contribution_minor"]
            remaining = max(0, target - allocated)
            required = None
            if row["target_date"] and _date(row["target_date"]) > today:
                months = max(1, (_date(row["target_date"]).year - today.year) * 12 + _date(row["target_date"]).month - today.month)
                required = math.ceil(remaining / months)
            completion = None
            if remaining == 0: completion = today.isoformat()
            elif monthly > 0: completion = _month_add(today, math.ceil(remaining / monthly)).isoformat()
            result.append({"id": row["id"], "name": row["name"], "kind": row["kind"],
                "target": _money(target), "allocated": _money(allocated), "remaining": _money(remaining),
                "progressPercent": round(min(100, allocated / target * 100), 1), "targetDate": row["target_date"],
                "linkedAccountId": row["linked_account_id"], "monthlyContribution": _money(monthly),
                "requiredMonthlyContribution": _money(required) if required is not None else None,
                "estimatedCompletionDate": completion, "primary": bool(row["is_primary"]),
                "active": bool(row["active"]), "completedAt": row["completed_at"]})
        return result

    def save_goal(self, payload: dict[str, Any], goal_id: str | None = None) -> dict[str, Any]:
        name = " ".join(str(payload.get("name") or "").split())[:160]
        if not name: raise FinanceError("Goal name is required.")
        kind = str(payload.get("kind") or "general")
        if kind not in {"general", "emergency_fund"}: raise FinanceError("Invalid goal kind.")
        target = _minor(payload, "target")
        if not target: raise FinanceError("Goal target must be greater than zero.")
        allocated = _minor(payload, "allocated", required=False) or 0
        monthly = _minor(payload, "monthlyContribution", required=False) or 0
        target_date = payload.get("targetDate") or None
        if target_date: _date(target_date, field="target date")
        target_id = goal_id or _id("goal"); now = utc_now(); completed = now if allocated >= target else None
        with self.repository.transaction() as connection:
            if payload.get("primary"):
                connection.execute("UPDATE goals SET is_primary=0 WHERE is_primary=1")
            if goal_id:
                result = connection.execute(
                    """UPDATE goals SET name=?,kind=?,target_minor=?,allocated_minor=?,currency=?,target_date=?,
                       linked_account_id=?,monthly_contribution_minor=?,is_primary=?,active=?,completed_at=?,updated_at=? WHERE id=?""",
                    (name, kind, target, allocated, str(payload.get("currency") or "PLN")[:3].upper(), target_date,
                     payload.get("linkedAccountId"), monthly, int(bool(payload.get("primary"))),
                     int(payload.get("active", True) is not False), completed, now, target_id))
                if result.rowcount != 1: raise FinanceNotFoundError("Goal was not found.")
            else:
                connection.execute(
                    """INSERT INTO goals(id,name,kind,target_minor,allocated_minor,currency,target_date,linked_account_id,
                       monthly_contribution_minor,is_primary,active,completed_at,created_at,updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (target_id, name, kind, target, allocated, str(payload.get("currency") or "PLN")[:3].upper(),
                     target_date, payload.get("linkedAccountId"), monthly, int(bool(payload.get("primary"))),
                     int(payload.get("active", True) is not False), completed, now, now))
        return next(goal for goal in self.goals() if goal["id"] == target_id)

    # ------------------------------------------------------------------ safe-to-spend/forecast
    def _liquid_balance_minor(self) -> int:
        with self.repository.read_connection() as connection:
            row = connection.execute(
                """SELECT COALESCE(SUM(balance_minor),0) FROM (
                     SELECT a.id, COALESCE(a.balance_minor,
                       (SELECT t.raw_balance_minor FROM transactions t WHERE t.account_id=a.id
                        AND t.raw_balance_minor IS NOT NULL ORDER BY t.transaction_date DESC,t.id DESC LIMIT 1)) balance_minor
                     FROM accounts a WHERE a.role='spending' AND a.include_safe_to_spend=1)"""
            ).fetchone()
        return int(row[0] or 0)

    def safe_to_spend(self, *, horizon: str = "end_of_month", custom_date: str | None = None,
                      reference_date: str | None = None) -> dict[str, Any]:
        today = _date(reference_date) if reference_date else date.today()
        income_unknown = False
        if horizon == "custom":
            end = _date(custom_date, field="custom horizon")
        elif horizon == "next_income":
            incomes = [event for event in self._generated_occurrences(today, today + timedelta(days=366)) if event["kind"] in INCOME_KINDS]
            if incomes: end = _date(incomes[0]["date"])
            else: end = _month_end(today); income_unknown = True
        else:
            horizon = "end_of_month"; end = _month_end(today)
        events = self._generated_occurrences(today, end)
        obligation_minor = sum(e["amountMinor"] for e in events if e["kind"] in OUTFLOW_KINDS and e["status"] not in {"paid", "matched", "skipped", "dismissed"})
        planned = [item for item in self.planned_items() if today.isoformat() <= item["date"] <= end.isoformat() and item["includeSafeToSpend"]]
        planned_expenses = sum(item["amountMinor"] for item in planned if item["kind"] == "expense")
        planned_savings = sum(item["amountMinor"] for item in planned if item["kind"] == "saving")
        settings = self.repository.read_settings()
        buffer_minor = int(settings.get("safeToSpendBufferMinor") or 0)
        liquid = self._liquid_balance_minor()
        safe = liquid - obligation_minor - planned_expenses - planned_savings - buffer_minor
        days = max(1, (end - today).days + 1)
        account_roles_configured = bool(settings.get("accountRolesConfigured"))
        configured = account_roles_configured
        return {"horizon": horizon, "asOf": today.isoformat(), "horizonDate": end.isoformat(),
            "configured": configured,
            "setup": [
                {"key": "accounts", "label": "Wybierz konta płynne", "complete": account_roles_configured},
                {"key": "obligations", "label": "Potwierdź przyszłe zobowiązania", "complete": True},
                {"key": "commitments", "label": "Dodaj planowane oszczędności (opcjonalnie)", "complete": True},
            ],
            "nextIncomeUnknown": income_unknown, "liquidBalance": _money(liquid),
            "confirmedObligations": _money(obligation_minor), "plannedExpenses": _money(planned_expenses),
            "plannedSavingsCommitments": _money(planned_savings), "safetyBuffer": _money(buffer_minor),
            "safeToSpend": _money(safe), "safePerDay": _money(math.floor(safe / days)), "remainingDays": days,
            "formula": "liquid balance - confirmed obligations - planned expenses - planned savings - safety buffer"}

    def onboarding(self) -> dict[str, Any]:
        quality = self.data_quality()
        settings = self.repository.read_settings()
        with self.repository.read_connection() as connection:
            completed_imports = int(connection.execute(
                "SELECT COUNT(*) FROM import_batches WHERE status='completed'"
            ).fetchone()[0])
            open_review = int(connection.execute(
                """SELECT COUNT(*) FROM transactions WHERE merchant_id IS NULL OR category_id IS NULL
                   OR transaction_kind IS NULL OR classification_conflict=1 OR taxonomy_review_required=1"""
            ).fetchone()[0])
            obligations = int(connection.execute(
                "SELECT COUNT(*) FROM obligations WHERE active=1 AND confirmed=1"
            ).fetchone()[0])
            budgets = int(connection.execute("SELECT COUNT(*) FROM budgets").fetchone()[0])
            goals = int(connection.execute("SELECT COUNT(*) FROM goals WHERE active=1").fetchone()[0])
        items = [
            ("import", "Zaimportuj historię bankową", "Transakcje tworzą podstawę wszystkich obliczeń.", "transactions", completed_imports > 0),
            ("quality", "Sprawdź jakość danych", "Pokrycie pokazuje, którym analizom można ufać.", "settings", quality["totalTransactions"] > 0),
            ("review", "Przejrzyj nierozpoznane transakcje", "Poprawki budują wiedzę do kolejnych importów.", "review", open_review == 0),
            ("accounts", "Ustaw role kont", "Tylko wskazane konta zasilają Safe-to-spend.", "settings", bool(settings.get("accountRolesConfigured"))),
            ("recurring", "Sprawdź rachunki i płatności cykliczne", "Potwierdzone terminy trafiają do prognozy.", "recurring", obligations > 0),
            ("budget", "Ustaw pierwszy budżet", "Limit pomaga kontrolować tempo wydatków.", "budgets",
             budgets > 0 or bool(self._month_income_sources_minor(date.today().strftime("%Y-%m")))),
            ("goal", "Dodaj pierwszy cel finansowy", "Cel śledzi tylko jawnie przydzielone środki.", "goals", goals > 0),
        ]
        return {"items": [
            {"key": key, "title": title, "why": why, "target": target, "complete": complete}
            for key, title, why, target, complete in items
        ], "completed": sum(item[-1] for item in items), "total": len(items)}

    def forecast(self, *, horizon: str = "30", reference_date: str | None = None) -> dict[str, Any]:
        today = _date(reference_date) if reference_date else date.today()
        if horizon == "end_of_month": end = _month_end(today)
        else:
            days = int(horizon)
            if days not in {7, 30, 90}: raise FinanceError("Forecast horizon must be 7, 30, 90, or end_of_month.")
            end = today + timedelta(days=days)
        events = []
        for event in self._generated_occurrences(today, end):
            if event["status"] in {"paid", "matched", "skipped", "dismissed"}: continue
            signed = event["amountMinor"] if event["kind"] in INCOME_KINDS else -event["amountMinor"]
            events.append({"date": event["date"], "name": event["name"], "kind": event["kind"],
                           "amountMinor": signed, "source": "obligation", "sourceId": event["obligationId"]})
        for item in self.planned_items():
            if today.isoformat() <= item["date"] <= end.isoformat():
                signed = item["amountMinor"] if item["kind"] == "income" else -item["amountMinor"]
                events.append({"date": item["date"], "name": item["name"], "kind": item["kind"],
                               "amountMinor": signed, "source": "planned_item", "sourceId": item["id"]})
        events.sort(key=lambda item: (item["date"], item["name"]))
        balance = self._liquid_balance_minor(); stream = []
        for event in events:
            balance += event["amountMinor"]
            stream.append({**event, "amount": _money(event["amountMinor"]), "projectedBalance": _money(balance)})
        return {"asOf": today.isoformat(), "horizonDate": end.isoformat(),
                "startingBalance": _money(self._liquid_balance_minor()), "endingBalance": _money(balance), "events": stream}

    def simulate(self, payload: dict[str, Any]) -> dict[str, Any]:
        base_safe = self.safe_to_spend(horizon=str(payload.get("horizon") or "end_of_month"), custom_date=payload.get("customDate"), reference_date=payload.get("referenceDate"))
        base_forecast = self.forecast(horizon=str(payload.get("forecastHorizon") or "end_of_month"), reference_date=payload.get("referenceDate"))
        adjustment = 0
        goal_monthly = 0
        for scenario in payload.get("scenarios") or []:
            amount = _minor(scenario, required=False) or 0
            kind = scenario.get("kind")
            if kind in {"spend_now", "subscription", "rent_increase"}: adjustment -= amount
            elif kind == "income": adjustment += amount
            elif kind == "goal_contribution": adjustment -= amount; goal_monthly += amount
            elif kind == "salary_delay":
                original = _date(scenario.get("originalDate"), field="original salary date")
                delayed = original + timedelta(days=int(scenario.get("days") or 0))
                horizon_date = _date(base_safe["horizonDate"])
                if original <= horizon_date < delayed:
                    adjustment -= amount
        goal_timelines = []
        for goal in self.goals(payload.get("referenceDate")):
            monthly = round(goal["monthlyContribution"] * 100) + goal_monthly
            remaining = round(goal["remaining"] * 100)
            completion = None
            if remaining <= 0:
                completion = payload.get("referenceDate") or date.today().isoformat()
            elif monthly > 0:
                completion = _month_add(_date(payload.get("referenceDate")) if payload.get("referenceDate") else date.today(), math.ceil(remaining / monthly)).isoformat()
            goal_timelines.append({"id": goal["id"], "name": goal["name"], "monthlyContribution": _money(monthly),
                                   "estimatedCompletionDate": completion})
        return {"persistent": False, "safeToSpend": _money(round(base_safe["safeToSpend"] * 100) + adjustment),
                "endingBalance": _money(round(base_forecast["endingBalance"] * 100) + adjustment),
                "goalMonthlyContributionDelta": _money(goal_monthly), "base": {"safeToSpend": base_safe["safeToSpend"],
                "endingBalance": base_forecast["endingBalance"]}, "goalTimelines": goal_timelines}

    # ------------------------------------------------------------------ reports/trends/insights
    def report(self, month: str | None = None) -> dict[str, Any]:
        month = month or date.today().strftime("%Y-%m")
        start = _date(month + "-01"); end = _month_end(start); previous = _month_add(start, -1)
        def metrics(begin: date, finish: date) -> dict[str, int]:
            with self.repository.read_connection() as connection:
                row = connection.execute(
                    """SELECT
                       COALESCE(SUM(CASE WHEN transaction_kind='salary' AND amount_minor>0 THEN amount_minor ELSE 0 END),0) salary,
                       COALESCE(SUM(CASE WHEN transaction_kind='income' AND amount_minor>0 THEN amount_minor ELSE 0 END),0) other_income,
                       COALESCE(SUM(CASE WHEN transaction_kind='refund' AND amount_minor>0 THEN amount_minor ELSE 0 END),0) refunds,
                       COALESCE(SUM(CASE WHEN transaction_kind='expense' AND amount_minor<0 THEN ABS(amount_minor) ELSE 0 END),0) expenses,
                       COALESCE(SUM(CASE WHEN transaction_kind='saving' THEN ABS(amount_minor) ELSE 0 END),0) savings,
                       COALESCE(SUM(CASE WHEN transaction_kind='transfer' THEN ABS(amount_minor) ELSE 0 END),0) transfers
                       FROM transactions WHERE transaction_date BETWEEN ? AND ?""", (begin.isoformat(), finish.isoformat())).fetchone()
            return dict(row)
        current, prev = metrics(start, end), metrics(previous, _month_end(previous))
        total_income = current["salary"] + current["other_income"]
        net = total_income + current["refunds"] - current["expenses"] - current["savings"]
        with self.repository.read_connection() as connection:
            top_categories = [dict(row) for row in connection.execute(
                """SELECT COALESCE(c.name,'Unclassified') name,SUM(ABS(t.amount_minor)) amount_minor FROM transactions t
                   LEFT JOIN categories c ON c.id=t.category_id WHERE t.transaction_kind='expense'
                   AND t.transaction_date BETWEEN ? AND ? GROUP BY COALESCE(c.name,'Unclassified') ORDER BY amount_minor DESC LIMIT 5""",
                (start.isoformat(), end.isoformat()))]
            top_merchants = [dict(row) for row in connection.execute(
                """SELECT COALESCE(m.canonical_name,'Unknown') name,SUM(ABS(t.amount_minor)) amount_minor FROM transactions t
                   LEFT JOIN merchants m ON m.id=t.merchant_id WHERE t.transaction_kind='expense'
                   AND t.transaction_date BETWEEN ? AND ? GROUP BY COALESCE(m.canonical_name,'Unknown') ORDER BY amount_minor DESC LIMIT 5""",
                (start.isoformat(), end.isoformat()))]
            largest = [dict(row) for row in connection.execute(
                """SELECT t.id,t.transaction_date date,COALESCE(m.canonical_name,'Transaction') merchant,ABS(t.amount_minor) amount_minor
                   FROM transactions t LEFT JOIN merchants m ON m.id=t.merchant_id WHERE t.transaction_kind='expense'
                   AND t.transaction_date BETWEEN ? AND ? ORDER BY ABS(t.amount_minor) DESC LIMIT 5""",
                (start.isoformat(), end.isoformat()))]
        recurring = self._generated_occurrences(start, end)
        recurring_cost = sum(e["amountMinor"] for e in recurring if e["kind"] in OUTFLOW_KINDS)
        subscription_cost = sum(e["amountMinor"] for e in recurring if e["kind"] == "subscription")
        return {"month": month, "salary": _money(current["salary"]), "otherIncome": _money(current["other_income"]),
            "income": _money(total_income), "refunds": _money(current["refunds"]), "expenses": _money(current["expenses"]),
            "savings": _money(current["savings"]), "transfers": _money(current["transfers"]), "netCashFlow": _money(net),
            "savingsRate": round(current["savings"] / total_income * 100, 1) if total_income else None,
            "recurringCosts": _money(recurring_cost), "subscriptionCost": _money(subscription_cost),
            "topCategories": [{"name": r["name"], "amount": _money(r["amount_minor"])} for r in top_categories],
            "topMerchants": [{"name": r["name"], "amount": _money(r["amount_minor"])} for r in top_merchants],
            "largestTransactions": [{**r, "amount": _money(r.pop("amount_minor"))} for r in largest],
            "budgets": self.budget_status(month), "goals": self.goals(end.isoformat()),
            "previousMonth": {"expenses": _money(prev["expenses"]), "income": _money(prev["salary"] + prev["other_income"]),
                              "savings": _money(prev["savings"])}}

    def _overview_month_activity(self, month: str, goals: list[dict[str, Any]],
                                 accounts: list[dict[str, Any]]) -> dict[str, Any]:
        start = _date(month + "-01"); end = _month_end(start)
        average_end = min(end, date.today())
        average_end_month = average_end.replace(day=1)
        average_months = max(0, (average_end_month.year - GOAL_AVERAGE_START.year) * 12
                             + average_end_month.month - GOAL_AVERAGE_START.month + 1)
        linked_goal_accounts = {goal["linkedAccountId"] for goal in goals
            if goal["active"] and goal["kind"] == "emergency_fund" and goal["linkedAccountId"] is not None}
        goal_accounts = linked_goal_accounts or {account["id"] for account in accounts if account["role"] == "savings"}
        first_goal_date = None
        history_rows = []
        with self.repository.read_connection() as connection:
            rows = connection.execute(
                """SELECT t.account_id,t.transaction_date,t.amount_minor,t.transaction_kind,t.raw_description,
                          c.name category_name,pc.name parent_name
                   FROM transactions t LEFT JOIN categories c ON c.id=t.category_id
                   LEFT JOIN categories pc ON pc.id=c.parent_id
                   WHERE t.transaction_date BETWEEN ? AND ?""",
                (_month_add(start, -1).isoformat(), end.isoformat()),
            ).fetchall()
            if goal_accounts:
                placeholders = ",".join("?" for _ in goal_accounts)
                account_ids = tuple(sorted(goal_accounts))
                first_goal_date = connection.execute(
                    f"SELECT MIN(transaction_date) FROM transactions WHERE account_id IN ({placeholders})",
                    account_ids,
                ).fetchone()[0]
                if first_goal_date and first_goal_date <= average_end.isoformat():
                    history_rows = connection.execute(
                        f"""SELECT transaction_date,amount_minor,transaction_kind,raw_description
                            FROM transactions WHERE account_id IN ({placeholders})
                              AND transaction_date BETWEEN ? AND ?""",
                        (*account_ids, first_goal_date, average_end.isoformat()),
                    ).fetchall()
        expenses: dict[str, int] = {}
        deposits = withdrawals = average_deposits = average_withdrawals = 0
        lifetime_deposits = lifetime_withdrawals = 0
        for row in rows:
            amount = int(row["amount_minor"])
            kind = row["transaction_kind"]
            actual_month = row["transaction_date"][:7]
            if amount < 0 and kind == "expense" and transaction_family(row["raw_description"]) != "goal_withdrawal" and _expense_budget_month(row["transaction_date"], row["raw_description"]) == month:
                category = row["parent_name"] or row["category_name"]
                if not category:
                    category = "Podatki" if transaction_family(row["raw_description"]) == "tax_transfer" else "Bez kategorii"
                expenses[category] = expenses.get(category, 0) - amount
            if row["account_id"] in goal_accounts:
                movement = _goal_movement(amount, kind, row["raw_description"])
                if actual_month == month:
                    if movement == "deposit": deposits += amount
                    elif movement == "withdrawal": withdrawals -= amount
        for row in history_rows:
            amount = int(row["amount_minor"])
            movement = _goal_movement(amount, row["transaction_kind"], row["raw_description"])
            if movement == "deposit": lifetime_deposits += amount
            elif movement == "withdrawal": lifetime_withdrawals -= amount
            if row["transaction_date"] >= GOAL_AVERAGE_START.isoformat():
                if movement == "deposit": average_deposits += amount
                elif movement == "withdrawal": average_withdrawals -= amount
        incomes = self._month_income_sources_minor(month)
        total_income = sum(incomes.values()); total_expenses = sum(expenses.values())
        lifetime_start = _date(first_goal_date).replace(day=1) if first_goal_date and first_goal_date <= average_end.isoformat() else None
        lifetime_months = ((average_end_month.year - lifetime_start.year) * 12
                           + average_end_month.month - lifetime_start.month + 1) if lifetime_start else 0
        income_start = min(GOAL_AVERAGE_START, lifetime_start) if lifetime_start else GOAL_AVERAGE_START
        income_by_month = {}
        if income_start <= average_end_month:
            count = ((average_end_month.year - income_start.year) * 12
                     + average_end_month.month - income_start.month + 1)
            for offset in range(count):
                income_month = _month_add(income_start, offset).strftime("%Y-%m")
                income_by_month[income_month] = total_income if income_month == month else sum(
                    self._month_income_sources_minor(income_month).values())
        average_income = sum(value for income_month, value in income_by_month.items()
                             if income_month >= GOAL_AVERAGE_START.strftime("%Y-%m"))
        lifetime_income = sum(value for income_month, value in income_by_month.items()
                              if lifetime_start and income_month >= lifetime_start.strftime("%Y-%m"))
        return {"income": _money(total_income), "expenses": _money(total_expenses),
            "remainingFromIncome": _money(total_income - total_expenses),
            "expenseCategories": [{"name": name, "amount": _money(amount)} for name, amount in
                sorted(expenses.items(), key=lambda item: (-item[1], item[0]))],
            "incomeSources": [{"name": name, "amount": _money(amount)} for name, amount in
                sorted(incomes.items(), key=lambda item: (-item[1], item[0]))],
            "goalDeposits": _money(deposits), "goalWithdrawals": _money(withdrawals),
            "goalDepositRate": round(deposits / total_income * 100, 1) if total_income else None,
            "goalWithdrawalRate": round(withdrawals / total_income * 100, 1) if total_income else None,
            "goalAverageMonths": average_months,
            "goalAverageFrom": GOAL_AVERAGE_START.strftime("%Y-%m") if average_months else None,
            "goalAverageTo": average_end_month.strftime("%Y-%m") if average_months else None,
            "goalAverageDeposits": _money(average_deposits / average_months) if average_months else None,
            "goalAverageWithdrawals": _money(average_withdrawals / average_months) if average_months else None,
            "goalAverageDepositRate": round(average_deposits / average_income * 100, 1) if average_income else None,
            "goalAverageWithdrawalRate": round(average_withdrawals / average_income * 100, 1) if average_income else None,
            "goalLifetimeMonths": lifetime_months,
            "goalLifetimeFrom": lifetime_start.strftime("%Y-%m") if lifetime_start else None,
            "goalLifetimeTo": average_end_month.strftime("%Y-%m") if lifetime_start else None,
            "goalLifetimeDeposits": _money(lifetime_deposits / lifetime_months) if lifetime_months else None,
            "goalLifetimeWithdrawals": _money(lifetime_withdrawals / lifetime_months) if lifetime_months else None,
            "goalLifetimeDepositRate": round(lifetime_deposits / lifetime_income * 100, 1) if lifetime_income else None,
            "goalLifetimeWithdrawalRate": round(lifetime_withdrawals / lifetime_income * 100, 1) if lifetime_income else None}

    def trends(self, range_name: str = "12M") -> list[dict[str, Any]]:
        today = date.today(); months = {"3M": 3, "6M": 6, "12M": 12}.get(range_name.upper())
        start = date(1900, 1, 1) if range_name.lower() == "all" else _month_add(date(today.year, today.month, 1), -(months or 12) + 1)
        with self.repository.read_connection() as connection:
            rows = connection.execute(
                """SELECT SUBSTR(transaction_date,1,7) month,
                   SUM(CASE WHEN transaction_kind='expense' THEN ABS(amount_minor) ELSE 0 END) expenses,
                   SUM(CASE WHEN transaction_kind IN ('salary','income') AND amount_minor>0 THEN amount_minor ELSE 0 END) income,
                   SUM(CASE WHEN transaction_kind='saving' THEN ABS(amount_minor) ELSE 0 END) savings,
                   SUM(CASE WHEN transaction_kind='refund' AND amount_minor>0 THEN amount_minor ELSE 0 END) refunds
                   FROM transactions WHERE transaction_date>=? GROUP BY SUBSTR(transaction_date,1,7) ORDER BY month""",
                (start.isoformat(),)).fetchall()
        return [{"month": r["month"], "expenses": _money(r["expenses"]), "income": _money(r["income"]),
                 "savings": _money(r["savings"]), "netCashFlow": _money(r["income"] + r["refunds"] - r["expenses"] - r["savings"]),
                 "savingsRate": round(r["savings"] / r["income"] * 100, 1) if r["income"] else None} for r in rows]

    def dimension_trends(self, dimension: str, range_name: str = "12M") -> list[dict[str, Any]]:
        if dimension not in {"category", "merchant"}:
            raise FinanceError("Trend dimension must be category or merchant.")
        today = date.today(); months = {"3M": 3, "6M": 6, "12M": 12}.get(range_name.upper())
        start = date(1900, 1, 1) if range_name.lower() == "all" else _month_add(date(today.year, today.month, 1), -(months or 12) + 1)
        if dimension == "category":
            join, label = "LEFT JOIN categories d ON d.id=t.category_id", "COALESCE(d.name,'Unclassified')"
        else:
            join, label = "LEFT JOIN merchants d ON d.id=t.merchant_id", "COALESCE(d.canonical_name,'Unknown')"
        with self.repository.read_connection() as connection:
            rows = connection.execute(
                f"""SELECT SUBSTR(t.transaction_date,1,7) month,{label} label,SUM(ABS(t.amount_minor)) amount_minor
                    FROM transactions t {join} WHERE t.transaction_kind='expense' AND t.transaction_date>=?
                    GROUP BY month,label ORDER BY month,amount_minor DESC""", (start.isoformat(),)
            ).fetchall()
        return [{"month": row["month"], "label": row["label"], "amount": _money(row["amount_minor"])} for row in rows]

    def recurring_trends(self, range_name: str = "12M") -> list[dict[str, Any]]:
        today = date.today(); months = {"3M": 3, "6M": 6, "12M": 12}.get(range_name.upper(), 12)
        start = _month_add(date(today.year, today.month, 1), -months + 1)
        result = []
        for offset in range(months):
            month = _month_add(start, offset); events = self._generated_occurrences(month, _month_end(month))
            result.append({"month": month.strftime("%Y-%m"), "amount": _money(sum(
                event["amountMinor"] for event in events if event["kind"] in OUTFLOW_KINDS
            ))})
        return result

    def insights(self, reference_date: str | None = None) -> list[dict[str, Any]]:
        today = _date(reference_date) if reference_date else date.today()
        report = self.report(today.strftime("%Y-%m")); quality = self.data_quality(); insights = []
        for budget in report["budgets"]:
            if budget["paceDeviationPoints"] > 10:
                insights.append({"code": "budget_ahead_of_pace", "severity": "attention",
                    "title": f"{budget['category']}: tempo ponad planem",
                    "reason": f"Wykorzystano {budget['usedPercent']}% limitu przy {budget['elapsedPercent']}% miesiąca.",
                    "numbers": {"usedPercent": budget["usedPercent"], "elapsedPercent": budget["elapsedPercent"],
                                "projected": budget["projected"]}, "period": report["month"], "target": "budgets"})
        upcoming = [e for e in self.upcoming(days=7, reference_date=today.isoformat()) if e["kind"] in OUTFLOW_KINDS]
        if upcoming:
            total = sum(e["amountMinor"] for e in upcoming)
            insights.append({"code": "upcoming_obligations", "severity": "info", "title": "Płatności w ciągu 7 dni",
                "reason": f"{len(upcoming)} potwierdzonych zdarzeń na {_money(total):.2f} PLN.",
                "numbers": {"count": len(upcoming), "amount": _money(total)}, "period": f"{today}–{today + timedelta(days=7)}", "target": "recurring"})
        if quality["categoryCoveragePercent"] < 95:
            insights.append({"code": "classification_coverage", "severity": "attention", "title": "Niepełna klasyfikacja",
                "reason": f"Kategorie przypisano do {quality['categoryCoveragePercent']}% transakcji; brak dla {quality['missingCategoryCount']}.",
                "numbers": {"coveragePercent": quality["categoryCoveragePercent"], "missing": quality["missingCategoryCount"]},
                "period": "all", "target": "review"})
        subscriptions = self.subscriptions()
        if subscriptions:
            monthly = sum(item["monthlyEquivalent"] for item in subscriptions)
            annual = sum(item["annualCost"] for item in subscriptions)
            insights.append({"code": "subscription_total", "severity": "info", "title": "Koszt subskrypcji",
                "reason": f"Aktywne subskrypcje kosztują {monthly:.2f} PLN miesięcznie i {annual:.2f} PLN rocznie.",
                "numbers": {"monthly": round(monthly, 2), "annual": round(annual, 2), "count": len(subscriptions)},
                "period": today.strftime("%Y-%m"), "target": "recurring"})
        primary = next((goal for goal in report["goals"] if goal["primary"] and goal["active"]), None)
        if primary:
            insights.append({"code": "primary_goal_progress", "severity": "info", "title": primary["name"],
                "reason": f"Postęp {primary['progressPercent']}%; pozostało {primary['remaining']:.2f} PLN.",
                "numbers": {"progressPercent": primary["progressPercent"], "remaining": primary["remaining"]},
                "period": today.isoformat(), "target": "goals"})
        return insights

    def overview(self, reference_date: str | None = None) -> dict[str, Any]:
        today = _date(reference_date) if reference_date else date.today()
        report = self.report(today.strftime("%Y-%m")); safe = self.safe_to_spend(reference_date=today.isoformat())
        upcoming = self.upcoming(days=30, reference_date=today.isoformat())
        accounts = self.accounts()
        goals = [goal for goal in report["goals"] if goal["active"]]
        activity = self._overview_month_activity(today.strftime("%Y-%m"), goals, accounts)
        main_account = next((account for account in accounts if account["main"]), None)
        available = main_account["balance"] if main_account else None
        planned_payments = sum(item["amountMinor"] for item in self.planned_items()
            if today.isoformat() <= item["date"] <= safe["horizonDate"] and item["kind"] in {"expense", "saving"})
        free = None if available is None else _money(round(available * 100)
            - round(safe["confirmedObligations"] * 100) - planned_payments)
        return {"asOf": today.isoformat(), "freshness": self._freshness(today), "liquidBalance": safe["liquidBalance"],
            "availableBalance": available, "freeBalance": free, "mainAccountName": main_account["displayLabel"] if main_account else None,
            "accountImports": [{"id": account["id"], "name": account["displayLabel"],
                "role": "main" if account["main"] else "savings", "lastImportedAt": account["lastImportedAt"],
                "latestTransactionDate": account["latestTransactionDate"]}
                for account in sorted(accounts, key=lambda account: (not account["main"], account["displayLabel"]))
                if account["main"] or account["role"] == "savings"],
            "safeToSpend": safe, "expenses": activity["expenses"], "income": activity["income"],
            "remainingFromIncome": activity["remainingFromIncome"],
            "expenseCategories": activity["expenseCategories"], "incomeSources": activity["incomeSources"],
            "goalDeposits": activity["goalDeposits"], "goalWithdrawals": activity["goalWithdrawals"],
            "goalDepositRate": activity["goalDepositRate"],
            "goalWithdrawalRate": activity["goalWithdrawalRate"],
            "goalAverageMonths": activity["goalAverageMonths"],
            "goalAverageFrom": activity["goalAverageFrom"],
            "goalAverageTo": activity["goalAverageTo"],
            "goalAverageDeposits": activity["goalAverageDeposits"],
            "goalAverageWithdrawals": activity["goalAverageWithdrawals"],
            "goalAverageDepositRate": activity["goalAverageDepositRate"],
            "goalAverageWithdrawalRate": activity["goalAverageWithdrawalRate"],
            "goalLifetimeMonths": activity["goalLifetimeMonths"],
            "goalLifetimeFrom": activity["goalLifetimeFrom"],
            "goalLifetimeTo": activity["goalLifetimeTo"],
            "goalLifetimeDeposits": activity["goalLifetimeDeposits"],
            "goalLifetimeWithdrawals": activity["goalLifetimeWithdrawals"],
            "goalLifetimeDepositRate": activity["goalLifetimeDepositRate"],
            "goalLifetimeWithdrawalRate": activity["goalLifetimeWithdrawalRate"],
            "netCashFlow": report["netCashFlow"], "savings": report["savings"], "savingsRate": report["savingsRate"],
            "upcoming": upcoming[:8], "upcoming30Days": _money(sum(e["amountMinor"] for e in upcoming if e["kind"] in OUTFLOW_KINDS)),
            "budgets": report["budgets"], "goals": goals,
            "trends": self.trends("6M"), "insights": self.insights(today.isoformat()), "dataQuality": self.data_quality()}

    def _freshness(self, reference: date) -> dict[str, Any]:
        with self.repository.read_connection() as connection:
            latest = connection.execute("SELECT MAX(transaction_date) FROM transactions").fetchone()[0]
        if not latest: return {"latestTransactionDate": None, "ageDays": None, "status": "empty"}
        age = (reference - _date(latest)).days
        return {"latestTransactionDate": latest, "ageDays": age, "status": "fresh" if age <= 3 else "aging" if age <= 14 else "stale"}
