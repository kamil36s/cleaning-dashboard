"""Finance use-cases between HTTP/CLI callers and SQLite persistence."""

from __future__ import annotations

import hashlib
import csv
import io
import json
import shutil
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from finance_importer import (
    CsvImportError,
    account_match_key,
    assign_fingerprint,
    mask_account,
    parse_csv_bytes,
    parse_date,
    transaction_base_key,
)
from finance_analytics import FinanceAnalyticsService
from finance_classification import TRANSACTION_KINDS
from finance_operations import FinanceOperationsService
from finance_planning import FinancePlanningService
from finance_review import FinanceReviewService
from finance_receipts import FinanceReceiptService
from finance_repository import (
    FinanceError,
    FinanceNotFoundError,
    FinanceRepository,
    utc_now,
)


DEFAULT_SETTINGS = {
    "savingsCategories": ["regularne oszczędzanie", "oszczędzanie"],
    "ignoredCategories": [],
    "userCategories": [
        "Jedzenie", "Zakupy spożywcze", "Chemia i dom", "Kawa i słodycze",
        "Restauracje", "Bary", "Delivery", "Transport", "Taxi",
        "Komunikacja miejska", "Rachunki", "Mieszkanie", "Subskrypcje",
        "Telefon i internet", "Zdrowie", "Apteka", "Ubrania", "Elektronika",
        "Kosmetyki", "Rozrywka", "Kultura", "Sport", "Podróże", "Prezenty",
        "Oszczędności", "Przelewy", "Gotówka", "Praca", "Inne",
    ],
    "merchantTypes": [
        "Sklep spożywczy", "Sklep convenience", "Dyskont", "Drogeria", "Apteka",
        "Restauracja", "Bar", "Kawiarnia", "Piekarnia", "Delivery", "Taxi",
        "Transport publiczny", "Paliwo", "Parking", "Subskrypcja", "Marketplace",
        "Sklep internetowy", "Usługa", "Przelew", "Bankomat", "Bank", "Urząd",
        "Przychodnia", "Siłownia", "Kino", "Hotel", "Loty", "Inne",
    ],
    "rejectedSuggestionKeys": [],
}


class FinanceMigrationError(FinanceError):
    pass


class FinanceValidationError(FinanceError):
    def __init__(self, message: str, result: dict[str, Any]):
        super().__init__(message)
        self.result = result


def _minor_from_legacy(value: Any, *, allow_empty: bool = False) -> int | None:
    if value is None or value == "":
        if allow_empty:
            return None
        value = 0
    try:
        decimal_value = Decimal(str(value))
    except InvalidOperation as exc:
        raise FinanceMigrationError("Legacy Budget contains an invalid amount.") from exc
    if not decimal_value.is_finite():
        raise FinanceMigrationError("Legacy Budget contains an invalid amount.")
    return int((decimal_value * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _json_metrics(transactions: list[dict[str, Any]]) -> dict[str, Any]:
    amounts = [_minor_from_legacy(item.get("amount")) or 0 for item in transactions]
    dates = [str(item.get("date") or "") for item in transactions if item.get("date")]
    return {
        "count": len(transactions),
        "date_min": min(dates) if dates else None,
        "date_max": max(dates) if dates else None,
        "signed_minor": sum(amounts),
        "negative_minor": sum(value for value in amounts if value < 0),
        "positive_minor": sum(value for value in amounts if value > 0),
        "annotations": {
            key: sum(bool(str(item.get(key) or "").strip()) for item in transactions)
            for key in ("merchant", "merchantType", "userCategory", "note")
        },
    }


class FinanceService:
    def __init__(
        self,
        database_path: Path | str,
        *,
        legacy_json_path: Path | str | None = None,
        backup_directory: Path | str | None = None,
    ):
        self.repository = FinanceRepository(database_path)
        self.legacy_json_path = Path(legacy_json_path) if legacy_json_path else None
        default_backup = Path(database_path).parent / "budget-backups"
        self.backup_directory = Path(backup_directory) if backup_directory else default_backup
        self.operations = FinanceOperationsService(self.repository)
        self.review = FinanceReviewService(self.repository)
        self.receipts = FinanceReceiptService(self.repository)
        self.analytics = FinanceAnalyticsService(self.repository)
        default_bills = Path(database_path).parent / "settings" / "bills.json"
        self.planning = FinancePlanningService(
            self.repository,
            legacy_bills_path=default_bills,
            backup_directory=self.backup_directory,
        )
        self._ready = False

    def ensure_ready(self) -> dict[str, Any] | None:
        self.repository.initialize()
        migration = self.migrate_legacy_json()
        # A legacy migration may insert Pack A rows after the Pack B schema was
        # created, so rerun the idempotent annotation normalizer.
        self.repository.initialize()
        self.receipts.initialize()
        bills_migration = self.planning.migrate_legacy_bills()
        self._ready = True
        if migration:
            return {**migration, "billsMigration": bills_migration} if bills_migration else migration
        if bills_migration:
            return {"bills": bills_migration}
        return None

    def _ensure_ready(self) -> None:
        if not self._ready:
            self.ensure_ready()

    def validate_companion_token(self, token: str) -> bool:
        self._ensure_ready()
        return self.receipts.validate_device_token(token)

    def pair_companion_device(self, name: str) -> dict[str, Any]:
        self._ensure_ready()
        return self.receipts.pair_device(name)

    def companion_devices(self) -> list[dict[str, Any]]:
        self._ensure_ready()
        return self.receipts.devices()

    def revoke_companion_device(self, device_id: str) -> dict[str, Any]:
        self._ensure_ready()
        return self.receipts.revoke_device(device_id)

    def import_receipt(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._ensure_ready()
        return self.receipts.import_base64(payload)

    def list_receipts(self, status: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        self._ensure_ready()
        return self.receipts.list_receipts(status=status, limit=limit)

    def receipt_detail(self, receipt_id: str) -> dict[str, Any]:
        self._ensure_ready()
        return self.receipts.get_receipt(receipt_id)

    def receipt_sources(self, receipt_id: str) -> list[dict[str, Any]]:
        self._ensure_ready()
        return self.receipts.list_sources(receipt_id)

    def receipt_source_content(self, receipt_id: str, source_id: str) -> dict[str, Any]:
        self._ensure_ready()
        return self.receipts.source_content(receipt_id, source_id)

    def delete_receipt(self, receipt_id: str) -> dict[str, Any]:
        self._ensure_ready()
        return self.receipts.delete_receipt(receipt_id)

    def receipt_item_crop(self, item_id: str) -> dict[str, Any]:
        self._ensure_ready()
        return self.receipts.item_crop(item_id)

    def receipt_processing_health(self) -> dict[str, Any]:
        self._ensure_ready()
        return self.receipts.processing_health()

    def reprocess_receipt(self, receipt_id: str) -> dict[str, Any]:
        self._ensure_ready()
        return self.receipts.reprocess_receipt(receipt_id)

    def reprocess_receipts_needing_ocr(self) -> dict[str, Any]:
        self._ensure_ready()
        return self.receipts.reprocess_needing_ocr()

    def update_receipt_metadata(self, receipt_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._ensure_ready()
        return self.receipts.update_metadata(receipt_id, payload)

    def apply_receipt_parse_review(self, receipt_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._ensure_ready()
        return self.receipts.apply_parse_review(receipt_id, payload)

    def match_receipt(self, receipt_id: str, transaction_id: str | None = None) -> dict[str, Any]:
        self._ensure_ready()
        return self.receipts.match_receipt(receipt_id, transaction_id=transaction_id, auto_link=False)

    def receipt_item_groups(self) -> list[dict[str, Any]]:
        self._ensure_ready()
        return self.receipts.review_groups()

    def receipt_item_preview(self, group_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._ensure_ready()
        return self.receipts.review_preview(group_id, payload)

    def receipt_item_apply(self, group_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._ensure_ready()
        return self.receipts.review_apply(group_id, payload)

    def classify_receipt_item(self, item_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._ensure_ready()
        return self.receipts.classify_item(item_id, payload)

    def undo_receipt_item_review(self) -> dict[str, Any]:
        self._ensure_ready()
        return self.receipts.undo_latest_review()

    def receipt_product_categories(self) -> list[dict[str, Any]]:
        self._ensure_ready()
        return self.receipts.product_categories()

    def receipt_product(self, product_id: str) -> dict[str, Any]:
        self._ensure_ready()
        return self.receipts.product_detail(product_id)

    def create_receipt_product(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._ensure_ready()
        return self.receipts.create_product(payload)

    def lookup_receipt_barcode(self, barcode: str) -> dict[str, Any]:
        self._ensure_ready()
        return self.receipts.lookup_barcode(barcode)

    def save_pending_receipt_barcode(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._ensure_ready()
        return self.receipts.save_pending_barcode(payload)

    @staticmethod
    def _safe_filename(filename: Any) -> str:
        return Path(str(filename or "budget.csv")).name[:255] or "budget.csv"

    def import_csv(
        self,
        raw: bytes,
        filename: str,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict[str, Any]:
        self._ensure_ready()
        safe_filename = self._safe_filename(filename)
        batch_id = self.repository.create_batch(safe_filename)
        try:
            parsed = parse_csv_bytes(
                raw,
                account_secret=self.repository.account_secret(),
                date_from=date_from,
                date_to=date_to,
            )
        except CsvImportError as exc:
            errors = [{"row": None, "code": exc.code, "message": str(exc)}]
            self.repository.finish_batch(
                batch_id,
                status="failed",
                row_count=exc.row_count,
                accepted_count=0,
                duplicate_count=0,
                invalid_count=max(1, exc.row_count),
                filtered_count=0,
                source_format=None,
                date_from=None,
                date_to=None,
                errors=errors,
            )
            result = {
                "batchId": batch_id,
                "imported": 0,
                "duplicates": 0,
                "invalid": max(1, exc.row_count),
                "errors": errors,
                "status": "failed",
            }
            raise FinanceValidationError(str(exc), result) from exc

        imported = 0
        duplicates = 0
        try:
            with self.repository.transaction() as connection:
                for transaction in parsed["transactions"]:
                    account_id = self.repository.resolve_account(
                        connection,
                        match_key=transaction["account_match_key"],
                        display_label=transaction.get("account_display_label") or mask_account(transaction["raw_account"]),
                        role=transaction.get("account_role") or "spending",
                        include_safe_to_spend=transaction.get("include_safe_to_spend", True),
                        alias_existing=transaction.get("statement_format") == "mbank_account_statement",
                    )
                    if transaction.get("account_balance_snapshot_minor") is not None:
                        self.repository.update_account_balance(
                            connection,
                            account_id,
                            balance_minor=int(transaction["account_balance_snapshot_minor"]),
                            balance_as_of=str(transaction["account_balance_snapshot_date"]),
                        )
                    transaction_id = self.repository.find_transaction_id(
                        connection, transaction["fingerprint"],
                        transaction=transaction, account_id=account_id,
                        batch_id=batch_id, source_format=parsed["format"],
                    )
                    created = transaction_id is None
                    if created:
                        transaction_id = self.repository.insert_transaction(
                            connection,
                            transaction,
                            account_id=account_id,
                            batch_id=batch_id,
                        )
                        self.operations.classify_imported(connection, transaction_id)
                        imported += 1
                    else:
                        duplicates += 1
                    self.repository.associate_import(
                        connection,
                        transaction_id=transaction_id,
                        batch_id=batch_id,
                        row_number=transaction["source_row"],
                        created_by_batch=created,
                    )
                self.repository.finish_batch(
                    batch_id,
                    status="completed",
                    row_count=parsed["row_count"],
                    accepted_count=imported,
                    duplicate_count=duplicates,
                    invalid_count=parsed["invalid_count"],
                    filtered_count=parsed["filtered_count"],
                    source_format=parsed["format"],
                    date_from=parsed["date_from"],
                    date_to=parsed["date_to"],
                    errors=parsed["errors"],
                    connection=connection,
                )
        except Exception:
            self.repository.finish_batch(
                batch_id,
                status="failed",
                row_count=parsed["row_count"],
                accepted_count=0,
                duplicate_count=0,
                invalid_count=parsed["invalid_count"],
                filtered_count=parsed["filtered_count"],
                source_format=parsed["format"],
                date_from=parsed["date_from"],
                date_to=parsed["date_to"],
                errors=[{"row": None, "code": "storage_error", "message": "Import could not be stored."}],
            )
            raise

        return {
            "batchId": batch_id,
            "imported": imported,
            "duplicates": duplicates,
            "invalid": parsed["invalid_count"],
            "filteredOut": parsed["filtered_count"],
            "sourceRows": parsed["source_row_count"],
            "format": parsed["format"],
            "errors": parsed["errors"],
            "status": "completed",
            "encoding": parsed["encoding"],
        }

    def migrate_legacy_json(self) -> dict[str, Any] | None:
        source = self.legacy_json_path
        if source is None:
            return None
        source_key = str(source.resolve())
        recorded = self.repository.legacy_migration(source_key)
        if recorded:
            return json.loads(recorded["verification_json"])
        if not source.exists():
            return None
        if self.repository.transaction_count() > 0:
            raise FinanceMigrationError(
                "Legacy Budget migration is ambiguous because the finance database is not empty."
            )

        try:
            raw = source.read_bytes()
            payload = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise FinanceMigrationError(
                "Legacy Budget storage exists but is unreadable or corrupt; it was not replaced."
            ) from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("transactions", []), list):
            raise FinanceMigrationError("Legacy Budget storage has an invalid structure.")
        transactions = payload.get("transactions", [])
        if any(not isinstance(item, dict) for item in transactions):
            raise FinanceMigrationError("Legacy Budget contains an invalid transaction record.")

        before = _json_metrics(transactions)
        source_hash = hashlib.sha256(raw).hexdigest()
        self.backup_directory.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup_path = self.backup_directory / f"budget.before-sqlite-{timestamp}.json"
        shutil.copy2(source, backup_path)
        if hashlib.sha256(backup_path.read_bytes()).hexdigest() != source_hash:
            raise FinanceMigrationError("Legacy Budget backup verification failed.")

        batch_id = self.repository.create_batch(
            self._safe_filename((payload.get("source") or {}).get("name") or source.name),
            imported_at=str((payload.get("source") or {}).get("importedAt") or utc_now()),
        )
        occurrences: Counter[str] = Counter()
        try:
            with self.repository.transaction() as connection:
                for row_number, item in enumerate(transactions, start=1):
                    try:
                        transaction_date = parse_date(item.get("date"))
                    except ValueError as exc:
                        raise FinanceMigrationError(
                            "Legacy Budget contains an invalid transaction date."
                        ) from exc
                    transaction = {
                        "transaction_date": transaction_date,
                        "amount_minor": _minor_from_legacy(item.get("amount")),
                        "currency": str(item.get("currency") or "PLN").strip().upper() or "PLN",
                        "raw_description": str(item.get("description") or ""),
                        "raw_account": str(item.get("account") or ""),
                        "raw_category": str(item.get("category") or ""),
                        "raw_balance_minor": _minor_from_legacy(
                            item.get("balanceAfter"), allow_empty=True
                        ),
                        "merchant": str(item.get("merchant") or ""),
                        "merchant_type": str(item.get("merchantType") or ""),
                        "user_category": str(item.get("userCategory") or ""),
                        "note": str(item.get("note") or ""),
                    }
                    identity = account_match_key(
                        transaction["raw_account"], self.repository.account_secret()
                    )
                    transaction["account_match_key"] = identity
                    base = transaction_base_key(transaction, identity)
                    occurrences[base] += 1
                    transaction["occurrence"] = occurrences[base]
                    transaction["fingerprint"] = assign_fingerprint(
                        transaction, occurrences[base], identity
                    )
                    account_id = self.repository.resolve_account(
                        connection,
                        match_key=identity,
                        display_label=mask_account(transaction["raw_account"]),
                    )
                    transaction_id = self.repository.insert_transaction(
                        connection,
                        transaction,
                        account_id=account_id,
                        batch_id=batch_id,
                    )
                    self.repository.associate_import(
                        connection,
                        transaction_id=transaction_id,
                        batch_id=batch_id,
                        row_number=row_number,
                        created_by_batch=True,
                    )
                settings = payload.get("settings") if isinstance(payload.get("settings"), dict) else {}
                self.repository.write_settings(settings, connection=connection)
                self.repository.finish_batch(
                    batch_id,
                    status="completed",
                    row_count=len(transactions),
                    accepted_count=len(transactions),
                    duplicate_count=0,
                    invalid_count=0,
                    filtered_count=0,
                    source_format="legacy_json",
                    date_from=before["date_min"],
                    date_to=before["date_max"],
                    errors=[],
                    connection=connection,
                )
                after_rows = connection.execute(
                    "SELECT * FROM transactions ORDER BY transaction_date, id"
                ).fetchall()
                after = {
                    "count": len(after_rows),
                    "date_min": min((row["transaction_date"] for row in after_rows), default=None),
                    "date_max": max((row["transaction_date"] for row in after_rows), default=None),
                    "signed_minor": sum(row["amount_minor"] for row in after_rows),
                    "negative_minor": sum(row["amount_minor"] for row in after_rows if row["amount_minor"] < 0),
                    "positive_minor": sum(row["amount_minor"] for row in after_rows if row["amount_minor"] > 0),
                    "annotations": {
                        "merchant": sum(bool(row["merchant"]) for row in after_rows),
                        "merchantType": sum(bool(row["merchant_type"]) for row in after_rows),
                        "userCategory": sum(bool(row["user_category"]) for row in after_rows),
                        "note": sum(bool(row["note"]) for row in after_rows),
                    },
                }
                if before != after:
                    raise FinanceMigrationError(
                        "Legacy Budget verification mismatch; the source was left untouched."
                    )
                verification = {"before": before, "after": after}
                self.repository.record_legacy_migration(
                    connection,
                    source_key=source_key,
                    source_sha256=source_hash,
                    backup_path=str(backup_path),
                    verification=verification,
                )
        except Exception:
            # The pending batch is harmless metadata, but mark it explicitly.
            try:
                self.repository.finish_batch(
                    batch_id,
                    status="failed",
                    row_count=len(transactions),
                    accepted_count=0,
                    duplicate_count=0,
                    invalid_count=0,
                    filtered_count=0,
                    source_format="legacy_json",
                    date_from=before["date_min"],
                    date_to=before["date_max"],
                    errors=[{"row": None, "code": "migration_failed", "message": "Migration verification failed."}],
                )
            except Exception:
                pass
            raise
        return verification

    def compatibility_payload(self) -> dict[str, Any]:
        self._ensure_ready()
        rows = self.repository.list_transactions()
        settings = {**DEFAULT_SETTINGS, **self.repository.read_settings()}
        latest = self.repository.latest_completed_batch()
        transactions = [
            {
                "id": row["id"],
                "date": row["transaction_date"],
                "description": row["raw_description"],
                "account": row["account_display"],
                "accountDisplay": row["account_display"],
                "category": row["raw_category"],
                "amount": row["amount_minor"] / 100,
                "balanceAfter": None if row["raw_balance_minor"] is None else row["raw_balance_minor"] / 100,
                "currency": row["currency"],
                "merchantId": row["merchant_id"],
                "merchant": row["merchant_name"] or row["merchant"],
                "merchantTypeId": row["merchant_type_id"],
                "merchantType": row["merchant_type_name"] or row["merchant_type"],
                "categoryId": row["category_id"],
                "userCategory": row["category_name"] or row["user_category"],
                "legacyCategory": row["legacy_category_name"] or None,
                "parentCategory": row["parent_category_name"],
                "transactionKind": row["transaction_kind"],
                "classification": {
                    "merchantSource": row["merchant_source"],
                    "categorySource": row["category_source"],
                    "merchantTypeSource": row["merchant_type_source"],
                    "transactionKindSource": row["kind_source"],
                    "conflict": bool(row["classification_conflict"]),
                },
                "note": row["note"],
            }
            for row in rows
        ]
        return {
            "source": {
                "name": latest["filename"] if latest else "",
                "importedAt": latest["imported_at"] if latest else "",
                "rows": len(transactions),
            },
            "settings": settings,
            "transactions": transactions,
        }

    def import_history(self) -> list[dict[str, Any]]:
        self._ensure_ready()
        return self.repository.list_batches()

    def update_annotations(self, updates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        self._ensure_ready()
        if not isinstance(updates, list) or not updates or len(updates) > 500:
            raise FinanceValidationError(
                "Annotation updates must contain between 1 and 500 transactions.",
                {"errors": [{"code": "invalid_updates", "message": "Invalid annotation update list."}]},
            )
        cleaned = []
        for update in updates:
            if not isinstance(update, dict) or not str(update.get("id") or ""):
                raise FinanceValidationError(
                    "Each annotation update requires a transaction id.",
                    {"errors": [{"code": "invalid_update", "message": "Transaction id is required."}]},
                )
            cleaned.append({
                "id": str(update["id"]),
                "merchant": str(update.get("merchant") or "")[:500],
                "merchantType": str(update.get("merchantType") or "")[:200],
                "category": str(update.get("userCategory") or "")[:200],
                "note": str(update.get("note") or "")[:4000],
            })
        changed = []
        for update in cleaned:
            transaction_id = update.pop("id")
            explanation = self.operations.manual_update(transaction_id, update)
            changed.append({"id": transaction_id, "classification": explanation})
        return changed

    def update_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        self._ensure_ready()
        if not isinstance(settings, dict):
            raise FinanceValidationError(
                "Budget settings must be an object.",
                {"errors": [{"code": "invalid_settings", "message": "Invalid settings."}]},
            )
        allowed = set(DEFAULT_SETTINGS)
        unknown = set(settings) - allowed
        if unknown:
            raise FinanceValidationError(
                "Budget settings contain unsupported fields.",
                {"errors": [{"code": "invalid_settings", "message": "Unsupported setting field."}]},
            )
        cleaned: dict[str, list[str]] = {}
        for key, value in settings.items():
            if not isinstance(value, list) or len(value) > 1000:
                raise FinanceValidationError(
                    "Budget setting values must be lists.",
                    {"errors": [{"code": "invalid_settings", "message": "Setting value must be a list."}]},
                )
            cleaned[key] = [str(item).strip()[:500] for item in value if str(item).strip()]
        self.repository.write_settings(cleaned)
        return {**DEFAULT_SETTINGS, **self.repository.read_settings()}

    def summary(self) -> dict[str, Any]:
        self._ensure_ready()
        summary = self.repository.summary()
        return {
            "transactionCount": summary["transaction_count"],
            "dateFrom": summary["date_from"],
            "dateTo": summary["date_to"],
            "net": summary["signed_minor"] / 100,
            "totalNegative": summary["negative_minor"] / 100,
            "totalPositive": summary["positive_minor"] / 100,
        }

    @staticmethod
    def _query_transaction_payload(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"], "date": row["transaction_date"],
            "description": row["raw_description"], "accountId": row["account_id"],
            "accountDisplay": row["account_display"], "bankCategory": row["raw_category"],
            "amount": row["amount_minor"] / 100, "currency": row["currency"],
            "merchantId": row["merchant_id"], "merchant": row["merchant_name"] or row["merchant"],
            "categoryId": row["category_id"], "category": row["category_name"] or row["user_category"],
            "legacyCategory": row["legacy_category_name"] or None,
            "parentCategory": row["parent_category_name"],
            "merchantTypeId": row["merchant_type_id"],
            "merchantType": row["merchant_type_name"] or row["merchant_type"],
            "transactionKind": row["transaction_kind"], "note": row["note"],
            "classification": {
                "merchantSource": row["merchant_source"], "categorySource": row["category_source"],
                "merchantTypeSource": row["merchant_type_source"], "transactionKindSource": row["kind_source"],
                "conflict": bool(row["classification_conflict"]),
            },
        }

    def query_transactions(self, query: dict[str, Any]) -> dict[str, Any]:
        self._ensure_ready()
        kind = str(query.get("transactionKind") or "") or None
        if kind and kind not in TRANSACTION_KINDS:
            raise FinanceValidationError(
                "Unsupported transaction kind.",
                {"errors": [{"code": "invalid_transaction_kind", "message": "Unsupported transaction kind."}]},
            )
        try:
            result = self.repository.query_transactions(
                page=int(query.get("page") or 1), limit=int(query.get("limit") or 50),
                date_from=query.get("dateFrom") or None, date_to=query.get("dateTo") or None,
                account_id=int(query["accountId"]) if query.get("accountId") else None,
                category_id=int(query["categoryId"]) if query.get("categoryId") else None,
                merchant_id=int(query["merchantId"]) if query.get("merchantId") else None,
                merchant_type_id=int(query["merchantTypeId"]) if query.get("merchantTypeId") else None,
                transaction_kind=kind, text=query.get("text") or None,
                amount_min_minor=round(float(query["amountMin"]) * 100) if query.get("amountMin") not in (None, "") else None,
                amount_max_minor=round(float(query["amountMax"]) * 100) if query.get("amountMax") not in (None, "") else None,
                sort=str(query.get("sort") or "date_desc"),
            )
        except (TypeError, ValueError) as exc:
            raise FinanceValidationError(
                "Invalid transaction query.",
                {"errors": [{"code": "invalid_query", "message": "Invalid transaction query."}]},
            ) from exc
        transactions = [self._query_transaction_payload(row) for row in result["rows"]]
        indicators = self.receipts.transaction_indicators([item["id"] for item in transactions])
        for transaction in transactions:
            transaction["receipt"] = indicators.get(transaction["id"])
        return {
            "transactions": transactions,
            "page": result["page"], "limit": result["limit"], "total": result["total"],
            "hasMore": result["page"] * result["limit"] < result["total"],
        }

    def categories(self) -> list[dict[str, Any]]:
        self._ensure_ready()
        return self.operations.list_categories()

    def create_category(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._ensure_ready()
        return self.operations.create_category(payload)

    def update_category(self, category_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        self._ensure_ready()
        return self.operations.update_category(category_id, payload)

    def merchants(self) -> list[dict[str, Any]]:
        self._ensure_ready()
        return self.operations.list_merchants()

    def merchant_types(self) -> list[dict[str, Any]]:
        self._ensure_ready()
        return self.operations.list_merchant_types()

    def create_merchant(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._ensure_ready()
        return self.operations.create_merchant(payload)

    def add_merchant_alias(self, merchant_id: int, alias: Any) -> dict[str, Any]:
        self._ensure_ready()
        return self.operations.add_merchant_alias(merchant_id, alias)

    def classify_manually(self, transaction_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._ensure_ready()
        return self.operations.manual_update(transaction_id, payload)

    def rules(self) -> list[dict[str, Any]]:
        self._ensure_ready()
        return self.operations.list_rules()

    def create_rule(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._ensure_ready()
        mode = str(payload.get("application") or "future_only")
        if mode not in {"future_only", "existing_and_future"}:
            raise FinanceValidationError(
                "Unsupported rule application mode.",
                {"errors": [{"code": "invalid_application", "message": "Unsupported rule application mode."}]},
            )
        rule = self.operations.create_rule(payload)
        application = None
        if mode == "existing_and_future":
            application = self.operations.apply_rule(rule["id"], include_manual=bool(payload.get("includeManual")))
        return {"rule": rule, "application": application}

    def update_rule(self, rule_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        self._ensure_ready()
        return self.operations.set_rule_state(rule_id, payload)

    def delete_rule(self, rule_id: int) -> dict[str, Any]:
        self._ensure_ready()
        return self.operations.delete_rule(rule_id)

    def preview_rule(self, rule_id: int, include_manual: bool = False) -> dict[str, Any]:
        self._ensure_ready()
        return self.operations.preview_rule(rule_id, include_manual=include_manual)

    def apply_rule(self, rule_id: int, include_manual: bool = False) -> dict[str, Any]:
        self._ensure_ready()
        return self.operations.apply_rule(rule_id, include_manual=include_manual)

    def classification_explanation(self, transaction_id: str) -> dict[str, Any]:
        self._ensure_ready()
        return self.operations.explain(transaction_id)

    def review_items(self, status: str = "open", limit: int = 500) -> list[dict[str, Any]]:
        self._ensure_ready()
        return self.operations.list_review(status=status, limit=limit)

    def update_review(self, transaction_id: str, issue_type: str, status: str) -> dict[str, Any]:
        self._ensure_ready()
        return self.operations.review_action(transaction_id, issue_type, status)

    def correct_review(self, transaction_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._ensure_ready()
        correction = payload.get("correction") if isinstance(payload, dict) else None
        if not isinstance(correction, dict):
            raise FinanceValidationError(
                "Review correction is required.",
                {"errors": [{"code": "invalid_correction", "message": "Review correction is required."}]},
            )
        result = self.operations.manual_update(transaction_id, correction)
        similar_result = None
        if payload.get("applyToSimilar"):
            similar_result = self.operations.update_similar(transaction_id, correction)
        rule_result = None
        if payload.get("rule"):
            rule_payload = dict(payload["rule"])
            rule_payload.setdefault("application", "future_only")
            rule_result = self.create_rule(rule_payload)
        for issue in payload.get("resolveIssues") or []:
            self.operations.review_action(transaction_id, str(issue), "resolved")
        return {"classification": result, "similar": similar_result, "rule": rule_result}

    def review_groups(self, query: dict[str, Any]) -> dict[str, Any]:
        self._ensure_ready()
        return self.review.groups(
            scope=str(query.get("scope") or "selected_month"),
            month=query.get("month") or None,
            sort=str(query.get("sort") or "impact"),
            quick_clean=str(query.get("quickClean") or "").lower() in {"1", "true", "yes"},
            limit=int(query.get("limit") or 200),
        )

    def review_group_preview(self, group_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._ensure_ready()
        return self.review.preview(group_id, payload)

    def review_group_transactions(self, group_id: str) -> list[dict[str, Any]]:
        self._ensure_ready()
        return self.review.group_transactions(group_id)

    def apply_review_group(self, group_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._ensure_ready()
        return self.review.apply(group_id, payload)

    def undo_latest_review_group(self) -> dict[str, Any]:
        self._ensure_ready()
        return self.review.undo_latest()

    def resolve_period(self, query: dict[str, Any]) -> dict[str, Any]:
        self._ensure_ready()
        try:
            return self.analytics.periods.resolve(
                str(query.get("period") or "current_month"),
                reference_date=query.get("referenceDate") or None,
                date_from=query.get("dateFrom") or None, date_to=query.get("dateTo") or None,
                year=int(query["year"]) if query.get("year") else None,
            )
        except (TypeError, ValueError) as exc:
            raise FinanceValidationError(
                "Invalid finance period.",
                {"errors": [{"code": "invalid_period", "message": "Invalid finance period."}]},
            ) from exc

    def analytics_payload(self, resource: str, query: dict[str, Any]) -> Any:
        period = self.resolve_period(query)
        if resource == "summary":
            return self.analytics.get_period_summary(period)
        if resource == "categories":
            return self.receipts.analytics_category_breakdown(period)
        if resource == "merchants":
            return self.analytics.get_merchant_breakdown(period)
        if resource == "income":
            return self.analytics.get_income_breakdown(period)
        if resource == "cash-flow":
            return self.analytics.get_cash_flow(period)
        if resource == "savings":
            return self.analytics.get_savings_summary(period)
        if resource == "compare":
            return self.analytics.compare_periods(period)
        if resource == "largest":
            return self.analytics.get_largest_transactions(period, int(query.get("limit") or 10))
        if resource == "freshness":
            return self.analytics.get_data_freshness(query.get("referenceDate") or None)
        raise FinanceNotFoundError("Analytics resource was not found.")

    def planning_payload(self, resource: str, query: dict[str, Any]) -> Any:
        """Read-only Pack C resources. All calculations remain backend-canonical."""
        self._ensure_ready()
        reference = query.get("referenceDate") or None
        if resource == "overview":
            return self.planning.overview(reference)
        if resource == "data-quality":
            legacy = self.planning.data_quality()
            month = str(query.get("month") or query.get("referenceDate") or "")[:7] or None
            return {**legacy, "reviewModel": self.review.metrics(month=month), "receipts": self.receipts.data_quality()}
        if resource == "accounts":
            return self.planning.accounts()
        if resource == "onboarding":
            return self.planning.onboarding()
        if resource == "classification-bootstrap":
            return self.planning.classification_bootstrap()
        if resource == "obligations":
            active = query.get("active")
            return self.planning.obligations(
                active=None if active in (None, "") else str(active).lower() not in {"0", "false", "no"},
                kind=query.get("kind") or None,
            )
        if resource == "subscriptions":
            return self.planning.subscriptions()
        if resource == "bills":
            return self.planning.bills_payload(reference)
        if resource == "upcoming":
            return self.planning.upcoming(
                date_from=query.get("dateFrom") or None, date_to=query.get("dateTo") or None,
                days=int(query.get("days") or 30), reference_date=reference,
                include_completed=str(query.get("includeCompleted") or "").lower() in {"1", "true", "yes"},
            )
        if resource == "recurring-candidates":
            return self.planning.recurring_candidates(minimum=int(query.get("minimum") or 3))
        if resource == "budgets":
            return self.planning.budget_status(query.get("month") or None, reference)
        if resource == "budget-suggestion":
            return self.planning.budget_suggestion(
                query.get("month") or None,
                int(query["categoryId"]) if query.get("categoryId") else None,
            )
        if resource == "planned-items":
            return self.planning.planned_items(active_only=str(query.get("all") or "").lower() not in {"1", "true"})
        if resource == "goals":
            return self.planning.goals(reference)
        if resource == "safe-to-spend":
            return self.planning.safe_to_spend(
                horizon=str(query.get("horizon") or "end_of_month"),
                custom_date=query.get("customDate") or None, reference_date=reference,
            )
        if resource == "forecast":
            return self.planning.forecast(horizon=str(query.get("horizon") or "30"), reference_date=reference)
        if resource == "report":
            return self.planning.report(query.get("month") or None)
        if resource == "trends":
            return self.planning.trends(str(query.get("range") or "12M"))
        if resource == "category-trends":
            return self.planning.dimension_trends("category", str(query.get("range") or "12M"))
        if resource == "merchant-trends":
            return self.planning.dimension_trends("merchant", str(query.get("range") or "12M"))
        if resource == "recurring-trends":
            return self.planning.recurring_trends(str(query.get("range") or "12M"))
        if resource == "insights":
            return self.planning.insights(reference)
        raise FinanceNotFoundError("Finance planning resource was not found.")

    def planning_mutation(self, resource: str, payload: dict[str, Any]) -> Any:
        self._ensure_ready()
        if resource == "obligations":
            return self.planning.save_obligation(payload)
        if resource == "budgets":
            return self.planning.save_budget(payload)
        if resource == "planned-items":
            return self.planning.save_planned_item(payload)
        if resource == "goals":
            return self.planning.save_goal(payload)
        if resource == "occurrence-status":
            return self.planning.set_occurrence_status(str(payload.get("id") or ""), str(payload.get("status") or ""))
        if resource == "simulate":
            return self.planning.simulate(payload)
        if resource == "account-role":
            return self.planning.update_account(int(payload.get("id")), payload)
        if resource == "safe-settings":
            return self.planning.update_safe_settings(payload)
        if resource == "deactivate-obligation":
            return self.planning.deactivate_obligation(str(payload.get("id") or ""))
        if resource == "bills-notifications":
            return self.planning.set_bills_notifications(bool(payload.get("enabled")))
        raise FinanceNotFoundError("Finance planning resource was not found.")

    def export_transactions_csv(self, query: dict[str, Any]) -> bytes:
        """Export the filtered public transaction view with spreadsheet-injection protection."""
        self._ensure_ready()
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(["date", "merchant", "category", "transaction_kind", "account", "amount", "currency"])
        page = 1

        def safe(value: Any) -> str:
            text = str(value or "")
            return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text

        while True:
            result = self.query_transactions({**query, "page": page, "limit": 200})
            for row in result["transactions"]:
                writer.writerow([
                    row["date"], safe(row["merchant"] or row["description"]), safe(row["category"]),
                    row["transactionKind"], safe(row["accountDisplay"]), f"{row['amount']:.2f}", row["currency"],
                ])
            if not result["hasMore"]:
                break
            page += 1
        return output.getvalue().encode("utf-8-sig")

    def rollback_import(self, batch_id: str) -> dict[str, int | str]:
        self._ensure_ready()
        return self.repository.rollback_batch(str(batch_id or ""))

    def rollback_import_preview(self, batch_id: str) -> dict[str, int | str]:
        self._ensure_ready()
        return self.repository.rollback_preview(str(batch_id or ""))

    def migrate_browser_legacy_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        """One-shot bridge for old localStorage data on a genuinely empty DB.

        The submitted payload is first persisted as a private backup. This is
        intentionally not a general snapshot replacement endpoint.
        """
        self._ensure_ready()
        if self.repository.transaction_count() != 0:
            raise FinanceError("Browser legacy migration is only allowed for an empty finance database.")
        if not isinstance(payload, dict) or not isinstance(payload.get("transactions"), list):
            raise FinanceValidationError(
                "Legacy Budget payload has an invalid structure.",
                {"errors": [{"code": "invalid_legacy_payload", "message": "Invalid legacy payload."}]},
            )
        self.backup_directory.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        source = self.backup_directory / f"browser-legacy-source-{timestamp}.json"
        source.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        previous_source = self.legacy_json_path
        try:
            self.legacy_json_path = source
            verification = self.migrate_legacy_json()
        finally:
            self.legacy_json_path = previous_source
        return verification or {"before": {}, "after": {}}
