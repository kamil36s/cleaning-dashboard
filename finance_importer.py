"""Authoritative CSV decoding, validation, normalization, and fingerprinting."""

from __future__ import annotations

import csv
import hashlib
import hmac
import io
import re
import unicodedata
from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any


FIELD_ALIASES = {
    "booking_date": ("data ksiegowania",),
    "transaction_date": ("data operacji", "data"),
    "raw_description": ("opis operacji", "opis"),
    "raw_title": ("tytuł", "tytul"),
    "raw_counterparty": ("nadawca/odbiorca",),
    "raw_account": ("rachunek", "konto"),
    "raw_category": ("kategoria",),
    "amount_minor": ("kwota",),
    "raw_balance_minor": ("saldo po operacji", "saldo"),
    "currency": ("waluta",),
}
REQUIRED_FIELDS = ("transaction_date", "raw_description", "amount_minor")


class CsvImportError(ValueError):
    def __init__(self, message: str, *, code: str, row_count: int = 0):
        super().__init__(message)
        self.code = code
        self.row_count = row_count


def normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").strip().casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.translate(str.maketrans({"ł": "l", "đ": "d", "ø": "o", "ß": "ss"}))
    return re.sub(r"\s+", " ", text)


def normalize_header(value: Any) -> str:
    return normalize_text(str(value or "").lstrip("#").lstrip("\ufeff"))


def account_key(raw_account: str) -> str:
    """Legacy unkeyed digest retained for compatibility with old fingerprints."""
    canonical = re.sub(r"\s+", "", normalize_text(raw_account))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def account_match_key(raw_account: str, secret: bytes) -> str:
    """Return a stable keyed identifier without retaining the bank value."""
    canonical = re.sub(r"\s+", "", normalize_text(raw_account))
    if not canonical or not secret:
        raise ValueError("Account identifier and local fingerprint key are required")
    return hmac.new(secret, canonical.encode("utf-8"), hashlib.sha256).hexdigest()


def mask_account(raw_account: str) -> str:
    # The imported own-account value is transient. Never derive a persistent
    # user-facing label from its suffix.
    return "Konto główne"


def parse_date(value: Any) -> str:
    text = str(value or "").strip()
    for pattern in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, pattern).date().isoformat()
        except ValueError:
            continue
    raise ValueError("Invalid transaction date")


def parse_money_minor(value: Any, *, allow_empty: bool = False) -> int | None:
    text = str(value if value is not None else "").strip()
    if not text:
        if allow_empty:
            return None
        raise ValueError("Amount is required")
    text = re.sub(r"\b[A-Za-z]{3}\b", "", text)
    text = text.replace("\u00a0", "").replace(" ", "")
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        value_decimal = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError("Invalid amount") from exc
    if not value_decimal.is_finite():
        raise ValueError("Invalid amount")
    cents = (value_decimal * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(cents)


def transaction_base_key(transaction: dict[str, Any], account_identity: str | None = None) -> str:
    """Build the documented dedupe base.

    Bank category, balance, merchant, user category/type, and note are excluded.
    Exact repeated events are distinguished with an occurrence ordinal by
    ``assign_fingerprint``.
    """

    return "|".join(
        (
            transaction["transaction_date"],
            str(transaction["amount_minor"]),
            transaction["currency"],
            normalize_text(transaction["raw_description"]),
            account_identity or account_key(transaction["raw_account"]),
        )
    )


def assign_fingerprint(
    transaction: dict[str, Any], occurrence: int, account_identity: str | None = None
) -> str:
    base = transaction_base_key(transaction, account_identity)
    return hashlib.sha256(f"{base}|{occurrence}".encode("utf-8")).hexdigest()


def decode_csv(raw: bytes) -> tuple[str, str]:
    if not raw:
        raise CsvImportError("CSV file is empty.", code="empty_file")
    for encoding in ("utf-8-sig", "cp1250"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise CsvImportError("Unsupported CSV encoding.", code="unsupported_encoding")


def _dialect(text: str) -> csv.Dialect | str:
    try:
        return csv.Sniffer().sniff(text[:8192], delimiters=";,\t")
    except csv.Error:
        # Malformed/short data rows can make Sniffer reject an otherwise clear
        # header. Pick the delimiter with the strongest first-20-line signal;
        # structural row validation still happens below.
        sample_lines = [line for line in text.splitlines()[:20] if line.strip()]
        counts = {
            delimiter: max((line.count(delimiter) for line in sample_lines), default=0)
            for delimiter in (";", ",", "\t")
        }
        delimiter, count = max(counts.items(), key=lambda item: item[1])
        if count <= 0:
            raise CsvImportError(
                "CSV delimiter could not be detected.", code="invalid_structure"
            )
        return delimiter


def _column_map(headers: list[str]) -> dict[str, int]:
    normalized = [normalize_header(header) for header in headers]
    columns: dict[str, int] = {}
    for field, aliases in FIELD_ALIASES.items():
        accepted = {normalize_header(alias) for alias in aliases}
        columns[field] = next(
            (index for index, header in enumerate(normalized) if header in accepted), -1
        )
    missing = [field for field in REQUIRED_FIELDS if columns[field] < 0]
    if missing:
        labels = [FIELD_ALIASES[field][0] for field in missing]
        raise CsvImportError(
            f"Missing required CSV headers: {', '.join(labels)}.",
            code="missing_headers",
        )
    return columns


def _metadata_value(rows: list[list[str]], label: str) -> str:
    wanted = normalize_header(label)
    for index, row in enumerate(rows):
        if not row or normalize_header(row[0]) != wanted:
            continue
        for cell in row[1:]:
            if str(cell).strip():
                return str(cell).strip()
        for following in rows[index + 1 : index + 3]:
            for cell in following:
                if str(cell).strip():
                    return str(cell).strip()
    return ""


def _closing_balance(rows: list[list[str]]) -> int | None:
    wanted = normalize_header("saldo koncowe")
    for row in rows:
        for index, value in enumerate(row):
            if normalize_header(value) != wanted:
                continue
            for candidate in row[index + 1 :]:
                if not str(candidate).strip():
                    continue
                try:
                    return parse_money_minor(candidate)
                except ValueError:
                    break
    return None


def _parse_filter_date(value: str | None, field: str) -> str | None:
    if value in (None, ""):
        return None
    try:
        return parse_date(value)
    except ValueError as exc:
        raise CsvImportError(f"Invalid {field} date filter.", code="invalid_date_filter") from exc


def _statement_description(operation: str, title: str) -> str:
    operation = " ".join(operation.split())
    title = " ".join(title.split())
    if title and normalize_text(title) != normalize_text(operation):
        return f"{operation} — {title}"
    return operation


def _merchant_hint(operation: str, title: str) -> str:
    family = transaction_family(operation, operation)
    if family not in {"card_purchase", "blik_purchase", "refund"}:
        return ""
    value = re.split(r"\s+DATA TRANSAKCJI\s*:", title, maxsplit=1, flags=re.IGNORECASE)[0]
    value = re.sub(r"\s+/[^/]{0,40}$", "", value).strip(" .-/")
    value = re.sub(r"\s+", " ", value)
    if not value or normalize_text(value) in {"zakup", "transakcja", "platnosc"}:
        return ""
    return value[:300]


def transaction_family(raw_description: Any, raw_category: Any = "") -> str:
    """Return a conservative cross-export operation family for fuzzy dedupe.

    mBank's operation list and official statement may differ in wording and by
    one or two calendar days. The family deliberately describes the banking
    rail, not the merchant/category, so occurrence counting can still preserve
    two legitimate same-value operations.
    """

    text = f"{normalize_text(raw_description)} {normalize_text(raw_category)}"
    patterns = (
        ("salary", ("wynagrodzenie", "pensja")),
        ("goal_transfer", ("przelew na twoje cele",)),
        ("goal_withdrawal", ("wyplata z celu",)),
        ("goal_deposit", ("wplata na cel",)),
        ("tax_transfer", ("przelew podatkowy", "urzad skarbowy")),
        ("interest", ("kapitalizacja odsetek",)),
        ("refund", ("zwrot towaru", "zwrot zakupu", "blik kor. zakupu", "moneyback")),
        ("blik_p2p_out", ("blik p2p-wychodzacy",)),
        ("blik_p2p_in", ("blik p2p-przychodzacy",)),
        ("blik_purchase", ("blik zakup", "transakcja blik")),
        ("card_purchase", ("zakup przy uzyciu karty", "zakup karta", "zakup przy uzyciu karty")),
        ("cash_withdrawal", ("wyplata w bankomacie", "wyplata gotowki", "blik wyplata atm")),
        ("cash_deposit", ("wplata we wplatomacie",)),
        ("incoming_transfer", ("przelew zewnetrzny przychodzacy", "przelew wewnetrzny przychodzacy", "przelew przych.", "express elixir przych")),
        ("outgoing_transfer", ("przelew zewnetrzny wychodzacy", "przelew wewnetrzny wychodzacy", "przelew mtransfer wychodzacy", "przelew sepa wychodzacy", "express elixir wych")),
        ("credit", ("kredyt - splata", "kredyt - wczesniejsza splata", "kredyt - uznanie")),
        ("fee", ("prowizja", "oplata", "podatek od odsetek")),
        ("incoming_transfer", ("wplywy - inne",)),
    )
    for family, needles in patterns:
        if any(needle in text for needle in needles):
            return family
    return "other"


def parse_csv_bytes(
    raw: bytes,
    *,
    account_secret: bytes | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    date_from = _parse_filter_date(date_from, "start")
    date_to = _parse_filter_date(date_to, "end")
    if date_from and date_to and date_from > date_to:
        raise CsvImportError("Start date must not be after end date.", code="invalid_date_filter")
    text, encoding = decode_csv(raw)
    try:
        detected = _dialect(text)
        rows = list(csv.reader(
            io.StringIO(text),
            detected if not isinstance(detected, str) else csv.excel,
            **({"delimiter": detected} if isinstance(detected, str) else {}),
        ))
    except csv.Error as exc:
        raise CsvImportError("Malformed CSV structure.", code="invalid_structure") from exc

    header_index = -1
    headers: list[str] = []
    for index, row in enumerate(rows[:60]):
        normalized = {normalize_header(cell) for cell in row}
        if "data operacji" in normalized and "kwota" in normalized:
            header_index, headers = index, row
            break
    if header_index < 0:
        raise CsvImportError("Budget CSV header row was not found.", code="missing_headers")

    columns = _column_map(headers)
    required_last_index = max(columns[field] for field in REQUIRED_FIELDS)
    normalized_headers = {normalize_header(header) for header in headers}
    is_account_statement = "data ksiegowania" in normalized_headers and "saldo po operacji" in normalized_headers
    preamble = rows[:header_index]
    account_type = _metadata_value(preamble, "rodzaj rachunku")
    metadata_currency = _metadata_value(preamble, "waluta").upper()
    if is_account_statement:
        if normalize_text(account_type) == "cel":
            fallback_account = "mBank:CEL"
            account_display_label = "Cele"
            account_role = "savings"
            include_safe_to_spend = False
        else:
            fallback_account = f"mBank:{account_type or 'rachunek'}"
            account_display_label = "Konto główne"
            account_role = "spending"
            include_safe_to_spend = True
    else:
        fallback_account = ""
        account_display_label = "Konto główne"
        account_role = "spending"
        include_safe_to_spend = True
    occurrences: Counter[str] = Counter()
    transactions: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    row_count = 0
    source_row_count = 0
    filtered_count = 0
    all_valid_dates: list[str] = []

    for source_index, row in enumerate(rows[header_index + 1 :], start=header_index + 2):
        if not any(str(cell).strip() for cell in row):
            continue
        date_index = columns["transaction_date"]
        if len(row) <= date_index or not str(row[date_index]).strip():
            continue
        if len(row) <= required_last_index:
            source_row_count += 1
            row_count += 1
            errors.append({
                "row": source_index,
                "code": "short_row",
                "message": "Row has fewer columns than the header.",
            })
            continue

        def cell(field: str) -> str:
            index = columns[field]
            return str(row[index]).strip() if 0 <= index < len(row) else ""

        raw_date = cell("transaction_date")
        # mBank account statements end with balance and legal footer rows. They
        # are not transaction rows and must not inflate the invalid count.
        if not raw_date:
            continue
        source_row_count += 1
        try:
            transaction_date = parse_date(raw_date)
        except ValueError:
            row_count += 1
            errors.append({
                "row": source_index,
                "code": "invalid_date",
                "message": "Transaction date is invalid.",
            })
            continue
        all_valid_dates.append(transaction_date)
        if (date_from and transaction_date < date_from) or (date_to and transaction_date > date_to):
            filtered_count += 1
            continue
        row_count += 1
        try:
            amount_minor = parse_money_minor(cell("amount_minor"))
            balance_minor = parse_money_minor(cell("raw_balance_minor"), allow_empty=True)
        except ValueError:
            errors.append({
                "row": source_index,
                "code": "invalid_amount",
                "message": "Amount or balance is invalid.",
            })
            continue

        operation = cell("raw_description")
        raw_title = cell("raw_title")
        description = _statement_description(operation, raw_title) if is_account_statement else operation
        raw_account = cell("raw_account") or fallback_account
        raw_category = cell("raw_category") or (operation if is_account_statement else "")
        if not description or not raw_account or not raw_category:
            errors.append({
                "row": source_index,
                "code": "missing_value",
                "message": "A required transaction value is missing.",
            })
            continue

        currency = cell("currency").upper() if columns["currency"] >= 0 else metadata_currency or "PLN"
        currency = currency or "PLN"
        if not re.fullmatch(r"[A-Z]{3}", currency):
            errors.append({
                "row": source_index,
                "code": "invalid_currency",
                "message": "Currency must be a three-letter code.",
            })
            continue
        if currency != "PLN":
            errors.append({
                "row": source_index,
                "code": "unsupported_currency",
                "message": "Only PLN imports are supported by the current Budget UI.",
            })
            continue

        transaction = {
            "transaction_date": transaction_date,
            "amount_minor": amount_minor,
            "currency": currency,
            "raw_description": description,
            "raw_account": raw_account,
            "raw_category": raw_category,
            "raw_balance_minor": balance_minor,
            "source_row": source_index,
            "account_display_label": account_display_label,
            "account_role": account_role,
            "include_safe_to_spend": include_safe_to_spend,
            "statement_format": "mbank_account_statement" if is_account_statement else "mbank_operation_list",
            "merchant_hint": _merchant_hint(operation, raw_title) if is_account_statement else "",
        }
        identity = account_match_key(raw_account, account_secret) if account_secret else None
        transaction["account_match_key"] = identity
        base = transaction_base_key(transaction, identity)
        occurrences[base] += 1
        transaction["occurrence"] = occurrences[base]
        transaction["fingerprint"] = assign_fingerprint(
            transaction, occurrences[base], identity
        )
        transactions.append(transaction)

    closing_balance = _closing_balance(rows) if is_account_statement else None
    snapshots: list[dict[str, Any]] = []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for transaction in transactions:
        grouped.setdefault(transaction["account_match_key"] or transaction["raw_account"], []).append(transaction)
    for group in grouped.values():
        latest_date = max(item["transaction_date"] for item in group)
        latest = [item for item in group if item["transaction_date"] == latest_date]
        # Statements are chronological; operation lists are reverse chronological.
        snapshot_row = max(latest, key=lambda item: item["source_row"]) if is_account_statement else min(latest, key=lambda item: item["source_row"])
        source_latest = max(all_valid_dates) if all_valid_dates else None
        snapshot_balance = snapshot_row.get("raw_balance_minor")
        if closing_balance is not None and latest_date == source_latest:
            snapshot_balance = closing_balance
        if snapshot_balance is not None:
            snapshot_row["account_balance_snapshot_minor"] = snapshot_balance
            snapshot_row["account_balance_snapshot_date"] = latest_date
            snapshots.append({
                "accountMatchKey": snapshot_row["account_match_key"],
                "balanceMinor": snapshot_balance,
                "date": latest_date,
            })

    dates = [transaction["transaction_date"] for transaction in transactions]
    return {
        "encoding": encoding,
        "row_count": row_count,
        "source_row_count": source_row_count,
        "filtered_count": filtered_count,
        "transactions": transactions,
        "invalid_count": len(errors),
        "errors": errors[:100],
        "date_from": min(dates) if dates else None,
        "date_to": max(dates) if dates else None,
        "account_snapshots": snapshots,
        "format": "mbank_account_statement" if is_account_statement else "mbank_operation_list",
    }
