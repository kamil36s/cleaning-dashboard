"""Deterministic transaction classification, rules, and review helpers.

Precedence is manual/migrated > first matching rule > merchant default >
system fallback. Rules are evaluated by (priority ASC, id ASC). The first rule
to assign a field wins; a later differing assignment records a conflict unless
an earlier matching rule stopped processing.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Iterable

from finance_importer import normalize_text, transaction_family
from finance_repository import FinanceNotFoundError, normalize_entity_name, utc_now


TRANSACTION_KINDS = frozenset(
    {"expense", "income", "salary", "transfer", "refund", "saving", "cash", "other"}
)
CLASSIFICATION_SOURCES = frozenset(
    {"migrated", "manual", "rule", "merchant_default", "imported_raw", "system_fallback"}
)
PROTECTED_SOURCES = frozenset({"manual", "migrated"})

CONDITION_OPERATORS = {
    "raw_description": {"contains", "equals"},
    "normalized_description": {"contains", "equals"},
    "merchant": {"equals"},
    "account": {"equals"},
    "bank_category": {"contains", "equals"},
    "amount": {"eq", "gt", "gte", "lt", "lte", "between"},
    "sign": {"equals"},
    "currency": {"equals"},
}
ACTION_FIELDS = {"merchant", "category", "merchant_type", "transaction_kind"}


BANK_CATEGORY_MAP = {
    "regularne oszczedzanie": ("Oszczędności", None),
    "lokaty i konto oszcz.": ("Oszczędności", None),
    "przelew na twoje cele": ("Oszczędności", None),
    "wplata na cel": ("Oszczędności", None),
    "wyplata z celu": ("Oszczędności", None),
    "kapitalizacja odsetek": ("Oszczędności", None),
    "podatek od odsetek kapitalowych": ("Opłaty i prowizje", None),
    "oplata-przelew wewn. zdefiniowany": ("Opłaty i prowizje", None),
    "zywnosc i chemia domowa": ("Zakupy codzienne", "Zakupy mieszane"),
    "jedzenie poza domem": ("Jedzenie poza domem", "Restauracje"),
    "wyjscia i wydarzenia": ("Rozrywka", "Wydarzenia"),
    "przejazdy": ("Transport", "Inny transport"),
    "zdrowie i uroda": ("Zdrowie", None),
    "podroze i wyjazdy": ("Podróże", "Inne podróże"),
    "oplaty i odsetki": ("Opłaty i prowizje", None),
    "multimedia, ksiazki i prasa": ("Rozrywka", "Hobby"),
    "tv, internet, telefon": ("Usługi i subskrypcje", "Rachunki i usługi"),
    "odziez i obuwie": ("Zakupy", "Odzież"),
    "osobiste - inne": ("Zakupy", "Inne zakupy"),
    "paliwo": ("Transport", "Paliwo"),
    "remont i ogrod": ("Zakupy", "Dom"),
    "czynsz i wynajem": ("Mieszkanie", "Czynsz"),
    "papierosy": ("Zakupy codzienne", "Używki"),
    "alkohol": ("Zakupy codzienne", "Używki"),
    "rozrywka - inne": ("Rozrywka", None),
    "sport i hobby": ("Rozrywka", "Hobby"),
    "elektronika": ("Zakupy", "Elektronika"),
    "platnosci - inne": ("Usługi i subskrypcje", "Inne usługi"),
    "codzienne wydatki - inne": ("Zakupy codzienne", "Zakupy mieszane"),
    "prezenty i wsparcie": ("Zakupy", "Inne zakupy"),
}

DESCRIPTION_CATEGORY_OVERRIDES = (
    (("biedronka", "zabka", "lidl", "carrefour", "auchan", "kaufland", "netto", "lewiatan", "aldi"), ("Zakupy codzienne", "Zakupy mieszane")),
    (("apteka",), ("Zdrowie", "Apteka")),
    (("znanylekarz", "cm4m"), ("Zdrowie", "Lekarze")),
    (("rossmann", "super-pharm"), ("Higiena i uroda", None)),
    (("bolt",), ("Transport", "Taxi / rideshare")),
    (("mpk ", "jakdojade", "autolinee", "busitalia"), ("Transport", "Komunikacja")),
    (("pkp intercity", "trenitalia"), ("Transport", "Kolej")),
    (("hostel", "airbnb"), ("Podróże", "Noclegi")),
    (("openai",), ("Usługi i subskrypcje", "Aplikacje")),
    (("google one", "songsterr"), ("Usługi i subskrypcje", "Subskrypcje")),
    (("smokegod", "tabaccheria"), ("Zakupy codzienne", "Używki")),
    (("wolt", "pyszne", "glovo"), ("Jedzenie poza domem", "Delivery")),
    (("mcdonald", "kfc", "burger king", "pizza", "restaur", "bistro"), ("Jedzenie poza domem", "Restauracje")),
    (("orlen", "circle k", "shell", "bp "), ("Transport", "Paliwo")),
    (("cinema city", "multikino"), ("Rozrywka", "Kino")),
    (("steam", "playstation", "xbox"), ("Rozrywka", "Gry")),
    (("allegro", "amazon"), ("Zakupy", "Inne zakupy")),
    (("h&m", "reserved", "zalando", "cropp", "house "), ("Zakupy", "Odzież")),
)

MERCHANT_PROFILES = (
    (("biedronka", "jmp s.a."), "Biedronka", "Supermarket", ("Zakupy codzienne", "Zakupy mieszane")),
    (("zabka",), "Żabka", "Sklep spożywczy", ("Zakupy codzienne", "Zakupy mieszane")),
    (("freshmarket",), "Freshmarket", "Sklep spożywczy", ("Zakupy codzienne", "Zakupy mieszane")),
    (("kocyk",), "Kocyk", "Sklep spożywczy", ("Zakupy codzienne", "Zakupy mieszane")),
    (("stokrotka",), "Stokrotka", "Supermarket", ("Zakupy codzienne", "Zakupy mieszane")),
    (("tesco",), "Tesco", "Supermarket", ("Zakupy codzienne", "Zakupy mieszane")),
    (("topaz",), "Topaz", "Supermarket", ("Zakupy codzienne", "Zakupy mieszane")),
    (("kefirek",), "Kefirek", "Sklep spożywczy", ("Zakupy codzienne", "Zakupy mieszane")),
    (("delikatesy centrum", "mila s.a"), None, "Supermarket", ("Zakupy codzienne", "Zakupy mieszane")),
    (("lidl",), "Lidl", "Supermarket", ("Zakupy codzienne", "Zakupy mieszane")),
    (("carrefour",), "Carrefour", "Supermarket", ("Zakupy codzienne", "Zakupy mieszane")),
    (("auchan",), "Auchan", "Supermarket", ("Zakupy codzienne", "Zakupy mieszane")),
    (("kaufland",), "Kaufland", "Supermarket", ("Zakupy codzienne", "Zakupy mieszane")),
    (("netto",), "Netto", "Supermarket", ("Zakupy codzienne", "Zakupy mieszane")),
    (("rossmann",), "Rossmann", "Drogeria", ("Higiena i uroda", None)),
    (("apteka",), None, "Apteka", ("Zdrowie", "Apteka")),
    (("steska", "awiteks", "lajkonik", "piekarnia", "pod telegrafem", "vicenti", "dobra paczkarnia"), None, "Piekarnia", ("Zakupy codzienne", "Spożywcze")),
    (("duzy ben", "tobacco", "smoke shop", "smokegod"), None, "Sklep z używkami", ("Zakupy codzienne", "Używki")),
    (("bolt",), "Bolt", "Taxi / rideshare", ("Transport", "Taxi / rideshare")),
    (("uber",), "Uber", "Taxi / rideshare", ("Transport", "Taxi / rideshare")),
    (("mpk", "jakdojade"), None, "Komunikacja miejska", ("Transport", "Komunikacja")),
    (("pkp intercity", "intercity.pl"), "PKP Intercity", "Kolej", ("Transport", "Kolej")),
    (("orlen",), "Orlen", "Stacja paliw", ("Transport", "Paliwo")),
    (("circle k",), "Circle K", "Stacja paliw", ("Transport", "Paliwo")),
    (("shell",), "Shell", "Stacja paliw", ("Transport", "Paliwo")),
    (("lotos", "stacja paliw", "bp-"), None, "Stacja paliw", ("Transport", "Paliwo")),
    (("openai", "chatgpt"), "OpenAI / ChatGPT", "Aplikacja", ("Usługi i subskrypcje", "Aplikacje")),
    (("google one",), "Google One", "Subskrypcja", ("Usługi i subskrypcje", "Subskrypcje")),
    (("spotify",), "Spotify", "Subskrypcja", ("Usługi i subskrypcje", "Subskrypcje")),
    (("netflix",), "Netflix", "Subskrypcja", ("Usługi i subskrypcje", "Subskrypcje")),
    (("wolt",), "Wolt", "Delivery", ("Jedzenie poza domem", "Delivery")),
    (("pyszne",), "Pyszne.pl", "Delivery", ("Jedzenie poza domem", "Delivery")),
    (("glovo",), "Glovo", "Delivery", ("Jedzenie poza domem", "Delivery")),
    (("mcdonald",), "McDonald's", "Restauracja", ("Jedzenie poza domem", "Restauracje")),
    (("kfc",), "KFC", "Restauracja", ("Jedzenie poza domem", "Restauracje")),
    (("subway", "falafel", "kebab", "north fish", "green way", "pierog", "bar mleczny", "olimp/"), None, "Restauracja", ("Jedzenie poza domem", "Restauracje")),
    (("good lood",), "Good Lood", "Lodziarnia", ("Jedzenie poza domem", "Kawa i przekąski")),
    (("cafe", "kawa", "espresso", "kawiarnia"), None, "Kawiarnia", ("Jedzenie poza domem", "Kawa i przekąski")),
    (("betel", " pub", "pub ", "klub kwadrat", "klub re", "kraftowy"), None, "Bar / klub", ("Zakupy codzienne", "Używki")),
    (("cinema city",), "Cinema City", "Kino", ("Rozrywka", "Kino")),
    (("steam",), "Steam", "Gry", ("Rozrywka", "Gry")),
    (("empik",), "Empik", "Księgarnia / multimedia", ("Rozrywka", "Hobby")),
    (("bonito",), "Bonito.pl", "Księgarnia", ("Rozrywka", "Hobby")),
    (("inmedio", "ksiegarnia"), None, "Księgarnia / prasa", ("Rozrywka", "Hobby")),
    (("off festival", "orange warsaw fest", "goingapp", "hype park"), None, "Wydarzenia", ("Rozrywka", "Wydarzenia")),
    (("allegro",), "Allegro", "Marketplace", ("Zakupy", "Inne zakupy")),
    (("ikea", "obi ", "leroy merlin"), None, "Dom i wyposażenie", ("Zakupy", "Dom")),
    (("h and m", "h&m", "new yorker", "zalando"), None, "Odzież", ("Zakupy", "Odzież")),
    (("doladowania.play", "www.upc", "ebok.upc"), None, "Telekomunikacja", ("Usługi i subskrypcje", "Rachunki i usługi")),
    (("koleo",), "Koleo", "Kolej", ("Transport", "Kolej")),
    (("neobus", "flixbus"), None, "Autokar", ("Transport", "Inny transport")),
    (("taxify",), "Bolt", "Taxi / rideshare", ("Transport", "Taxi / rideshare")),
    (("barber",), None, "Fryzjer / barber", ("Higiena i uroda", None)),
    (("medimprove", "poradnia"), None, "Lekarze", ("Zdrowie", "Lekarze")),
    (("italki", "the linguist"), None, "Edukacja", ("Edukacja", None)),
    (("airbnb",), "Airbnb", "Nocleg", ("Podróże", "Noclegi")),
    (("booking.com",), "Booking.com", "Nocleg", ("Podróże", "Noclegi")),
)


def _merchant_profile(hint: str) -> tuple[str, str, tuple[str, str | None] | None]:
    normalized = normalize_text(hint)
    for needles, canonical, merchant_type, category in MERCHANT_PROFILES:
        if any(needle in normalized for needle in needles):
            return canonical or hint, merchant_type, category
    return hint, "Sprzedawca", None


def _ensure_imported_merchant(
    connection: sqlite3.Connection, hint: str
) -> tuple[int | None, str | None]:
    hint = " ".join(str(hint or "").split())[:300]
    if not hint:
        return None, None
    canonical, type_name, category_target = _merchant_profile(hint)
    normalized = normalize_entity_name(canonical)
    row = connection.execute(
        "SELECT id,merchant_type_id,default_category_id FROM merchants WHERE normalized_name=? AND is_active=1",
        (normalized,),
    ).fetchone()
    now = utc_now()
    type_id = None
    if type_name:
        type_normalized = normalize_entity_name(type_name)
        type_row = connection.execute(
            "SELECT id FROM merchant_types WHERE normalized_name=?", (type_normalized,)
        ).fetchone()
        if type_row:
            type_id = int(type_row["id"])
        else:
            type_id = int(connection.execute(
                "INSERT INTO merchant_types(name,normalized_name,created_at,updated_at) VALUES (?,?,?,?)",
                (type_name, type_normalized, now, now),
            ).lastrowid)
    category_id = _category_id(connection, *category_target) if category_target else None
    if row:
        connection.execute(
            """UPDATE merchants SET
                 merchant_type_id=COALESCE(merchant_type_id,?),
                 default_category_id=COALESCE(default_category_id,?),updated_at=? WHERE id=?""",
            (type_id, category_id, now, row["id"]),
        )
        return int(row["id"]), canonical
    merchant_id = int(connection.execute(
        """INSERT INTO merchants(canonical_name,normalized_name,default_category_id,merchant_type_id,created_at,updated_at)
           VALUES (?,?,?,?,?,?)""",
        (canonical, normalized, category_id, type_id, now, now),
    ).lastrowid)
    return merchant_id, canonical


def _category_id(
    connection: sqlite3.Connection, parent_name: str, child_name: str | None
) -> int | None:
    parent = connection.execute(
        "SELECT id FROM categories WHERE normalized_name=? AND parent_id IS NULL AND is_active=1",
        (normalize_entity_name(parent_name),),
    ).fetchone()
    if not parent:
        return None
    if child_name is None:
        return int(parent["id"])
    child = connection.execute(
        "SELECT id FROM categories WHERE normalized_name=? AND parent_id=? AND is_active=1",
        (normalize_entity_name(child_name), parent["id"]),
    ).fetchone()
    return int(child["id"]) if child else None


def _imported_defaults(
    connection: sqlite3.Connection, transaction: Any
) -> tuple[int | None, str]:
    description = normalize_text(transaction["raw_description"])
    raw_category = normalize_text(transaction["raw_category"])
    category_target = next(
        (target for needles, target in DESCRIPTION_CATEGORY_OVERRIDES if any(needle in description for needle in needles)),
        BANK_CATEGORY_MAP.get(raw_category),
    )
    amount = int(transaction["amount_minor"])
    family = transaction_family(transaction["raw_description"], transaction["raw_category"])
    if family in {"goal_transfer", "goal_withdrawal", "goal_deposit", "interest"}:
        category_target = ("Oszczędności", None)
    elif family == "fee":
        category_target = ("Opłaty i prowizje", None)
    category_id = _category_id(connection, *category_target) if category_target else None

    account = normalize_text(transaction["account_display"])
    if family == "goal_transfer":
        kind = "transfer" if account == "cele" else "saving" if amount < 0 else "transfer"
    elif family in {"goal_withdrawal", "goal_deposit"}:
        kind = "transfer"
    elif family == "interest":
        kind = "income" if amount >= 0 else "expense"
    elif family == "refund":
        kind = "refund"
    elif family in {"cash_withdrawal", "cash_deposit"}:
        kind = "cash"
    elif family == "salary":
        kind = "salary"
    elif family in {"incoming_transfer", "blik_p2p_in"}:
        kind = "salary" if any(token in description for token in ("wynagrodzenie", "pensja", "wyplata za")) else "income"
    elif family == "outgoing_transfer":
        kind = "transfer" if "wewnetrzny" in raw_category else "expense"
    elif family == "blik_p2p_out":
        kind = "expense"
    elif family in {"card_purchase", "blik_purchase", "credit", "fee"}:
        kind = "expense"
    elif raw_category == "regularne oszczedzanie":
        kind = "saving" if amount < 0 else "transfer"
    elif raw_category in {"lokaty i konto oszcz.", "przelew na twoje cele", "wplata na cel", "wyplata z celu"}:
        kind = "transfer"
    elif raw_category == "kapitalizacja odsetek":
        kind = "income"
    elif raw_category == "wynagrodzenie":
        kind = "salary"
    elif amount > 0 and "zwrot" in description:
        kind = "refund"
    elif raw_category == "wplywy - inne" and amount > 0:
        kind = "income"
    elif raw_category == "wyplata gotowki":
        kind = "cash"
    else:
        kind = "expense" if amount < 0 else "other"
    return category_id, kind


def _entity_row(
    connection: sqlite3.Connection, table: str, entity_id: int | None
) -> sqlite3.Row | None:
    if entity_id is None:
        return None
    return connection.execute(f"SELECT * FROM {table} WHERE id = ?", (entity_id,)).fetchone()


def _rule_rows(connection: sqlite3.Connection, rule_id: int | None = None) -> list[dict[str, Any]]:
    where = "WHERE r.enabled = 1" if rule_id is None else "WHERE r.id = ?"
    params: tuple[Any, ...] = () if rule_id is None else (rule_id,)
    rules = connection.execute(
        f"SELECT r.* FROM classification_rules r {where} ORDER BY r.priority, r.id", params
    ).fetchall()
    result: list[dict[str, Any]] = []
    for rule in rules:
        item = dict(rule)
        item["conditions"] = [dict(row) for row in connection.execute(
            "SELECT * FROM rule_conditions WHERE rule_id = ? ORDER BY position, id", (rule["id"],)
        )]
        item["actions"] = [dict(row) for row in connection.execute(
            "SELECT * FROM rule_actions WHERE rule_id = ? ORDER BY position, id", (rule["id"],)
        )]
        result.append(item)
    return result


def _condition_matches(condition: dict[str, Any], transaction: Any) -> bool:
    field = condition["field"]
    operator = condition["operator"]
    wanted = str(condition.get("value_text") or "")
    if field == "raw_description":
        actual = str(transaction["raw_description"] or "")
        return wanted.casefold() in actual.casefold() if operator == "contains" else actual.casefold() == wanted.casefold()
    if field == "normalized_description":
        actual = normalize_entity_name(transaction["raw_description"])
        normalized_wanted = normalize_entity_name(wanted)
        return normalized_wanted in actual if operator == "contains" else actual == normalized_wanted
    if field == "merchant":
        actual = normalize_entity_name(transaction["merchant_name"] or transaction["merchant"])
        return actual == normalize_entity_name(wanted)
    if field == "account":
        return normalize_entity_name(transaction["account_display"]) == normalize_entity_name(wanted)
    if field == "bank_category":
        actual = str(transaction["raw_category"] or "")
        return wanted.casefold() in actual.casefold() if operator == "contains" else actual.casefold() == wanted.casefold()
    if field == "currency":
        return str(transaction["currency"] or "").upper() == wanted.upper()
    if field == "sign":
        amount = int(transaction["amount_minor"])
        actual = "positive" if amount > 0 else "negative" if amount < 0 else "zero"
        return actual == wanted
    if field == "amount":
        amount = int(transaction["amount_minor"])
        if operator == "between":
            try:
                low, high = json.loads(wanted)
                return int(low) <= amount <= int(high)
            except (TypeError, ValueError, json.JSONDecodeError):
                return False
        target = int(condition.get("value_minor") or 0)
        return {
            "eq": amount == target,
            "gt": amount > target,
            "gte": amount >= target,
            "lt": amount < target,
            "lte": amount <= target,
        }.get(operator, False)
    return False


def _transaction_row(connection: sqlite3.Connection, transaction_id: str) -> sqlite3.Row:
    row = connection.execute(
        """
        SELECT t.*, a.display_label AS account_display, m.canonical_name AS merchant_name
        FROM transactions t
        JOIN accounts a ON a.id = t.account_id
        LEFT JOIN merchants m ON m.id = t.merchant_id
        WHERE t.id = ?
        """,
        (transaction_id,),
    ).fetchone()
    if not row:
        raise FinanceNotFoundError("Transaction was not found.")
    return row


def _action_value(action: dict[str, Any]) -> Any:
    return action.get("value_id") if action["field"] != "transaction_kind" else action.get("value_text")


def classify_transaction(
    connection: sqlite3.Connection,
    transaction_id: str,
    *,
    rules: list[dict[str, Any]] | None = None,
    include_manual: bool = False,
    persist: bool = True,
) -> dict[str, Any]:
    transaction = _transaction_row(connection, transaction_id)
    original = dict(transaction)
    values = {
        "merchant": transaction["merchant_id"],
        "category": transaction["category_id"],
        "merchant_type": transaction["merchant_type_id"],
        "transaction_kind": transaction["transaction_kind"],
    }
    sources = {
        "merchant": transaction["merchant_source"],
        "category": transaction["category_source"],
        "merchant_type": transaction["merchant_type_source"],
        "transaction_kind": transaction["kind_source"],
    }
    rule_ids = {
        "merchant": transaction["merchant_rule_id"],
        "category": transaction["category_rule_id"],
        "merchant_type": transaction["merchant_type_rule_id"],
        "transaction_kind": transaction["kind_rule_id"],
    }
    protected = {
        field for field, source in sources.items()
        if not include_manual and source in PROTECTED_SOURCES
    }
    for field in values:
        if field not in protected:
            values[field] = None
            sources[field] = None
            rule_ids[field] = None

    explanation: list[dict[str, Any]] = []
    normalized_description = normalize_entity_name(transaction["raw_description"])
    if "merchant" not in protected and normalized_description:
        alias = connection.execute(
            """
            SELECT ma.merchant_id, m.canonical_name
            FROM merchant_aliases ma JOIN merchants m ON m.id = ma.merchant_id
            WHERE ma.normalized_alias = ? AND m.is_active = 1
            """,
            (normalized_description,),
        ).fetchone()
        if alias:
            values["merchant"] = int(alias["merchant_id"])
            sources["merchant"] = "imported_raw"
            explanation.append({"field": "merchant", "source": "imported_raw", "matched": "merchant alias"})
    if "merchant" not in protected and values["merchant"] is None:
        merchant_id, merchant_name = _ensure_imported_merchant(
            connection, transaction["import_merchant_hint"]
        )
        if merchant_id is not None:
            values["merchant"] = merchant_id
            sources["merchant"] = "imported_raw"
            explanation.append({
                "field": "merchant", "source": "imported_raw",
                "matched": "statement merchant", "merchant": merchant_name,
            })

    transaction_context = dict(transaction)
    resolved_merchant = _entity_row(connection, "merchants", values["merchant"])
    if resolved_merchant:
        transaction_context["merchant_name"] = resolved_merchant["canonical_name"]

    winning_actions: dict[str, Any] = {}
    conflict = False
    matched_rules: list[int] = []
    for rule in rules if rules is not None else _rule_rows(connection):
        if not int(rule["enabled"]):
            continue
        if not all(_condition_matches(condition, transaction_context) for condition in rule["conditions"]):
            continue
        rule_id = int(rule["id"])
        matched_rules.append(rule_id)
        for action in rule["actions"]:
            field = action["field"]
            if field in protected:
                continue
            candidate = _action_value(action)
            if field in winning_actions:
                if winning_actions[field] != candidate:
                    conflict = True
                continue
            winning_actions[field] = candidate
            values[field] = candidate
            sources[field] = "rule"
            rule_ids[field] = rule_id
            explanation.append({"field": field, "source": "rule", "ruleId": rule_id, "ruleName": rule["name"]})
        if int(rule["stop_processing"]):
            break

    merchant = _entity_row(connection, "merchants", values["merchant"])
    if merchant:
        if values["category"] is None and "category" not in protected and merchant["default_category_id"] is not None:
            values["category"] = int(merchant["default_category_id"])
            sources["category"] = "merchant_default"
            explanation.append({"field": "category", "source": "merchant_default", "merchantId": merchant["id"]})
        if values["merchant_type"] is None and "merchant_type" not in protected and merchant["merchant_type_id"] is not None:
            values["merchant_type"] = int(merchant["merchant_type_id"])
            sources["merchant_type"] = "merchant_default"
            explanation.append({"field": "merchant_type", "source": "merchant_default", "merchantId": merchant["id"]})
    imported_category, imported_kind = _imported_defaults(connection, transaction)
    if values["category"] is None and "category" not in protected and imported_category is not None:
        values["category"] = imported_category
        sources["category"] = "imported_raw"
        explanation.append({"field": "category", "source": "imported_raw", "matched": "bank category"})
    if values["transaction_kind"] is None and "transaction_kind" not in protected:
        values["transaction_kind"] = imported_kind
        sources["transaction_kind"] = "imported_raw"
        explanation.append({"field": "transaction_kind", "source": "imported_raw", "matched": "bank operation"})
    if values["transaction_kind"] is None and "transaction_kind" not in protected:
        values["transaction_kind"] = "expense" if int(transaction["amount_minor"]) < 0 else "other"
        sources["transaction_kind"] = "system_fallback"
        explanation.append({"field": "transaction_kind", "source": "system_fallback"})

    changes = {
        field: original[{"merchant": "merchant_id", "category": "category_id", "merchant_type": "merchant_type_id", "transaction_kind": "transaction_kind"}[field]] != value
        for field, value in values.items()
    }
    if persist:
        connection.execute(
            """
            UPDATE transactions SET
                merchant_id = ?, category_id = ?, merchant_type_id = ?, transaction_kind = ?,
                merchant_source = ?, category_source = ?, merchant_type_source = ?, kind_source = ?,
                merchant_rule_id = ?, category_rule_id = ?, merchant_type_rule_id = ?, kind_rule_id = ?,
                classification_conflict = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                values["merchant"], values["category"], values["merchant_type"], values["transaction_kind"],
                sources["merchant"], sources["category"], sources["merchant_type"], sources["transaction_kind"],
                rule_ids["merchant"], rule_ids["category"], rule_ids["merchant_type"], rule_ids["transaction_kind"],
                int(conflict), utc_now(), transaction_id,
            ),
        )
    return {
        "transactionId": transaction_id,
        "values": values,
        "sources": sources,
        "ruleIds": rule_ids,
        "matchedRuleIds": matched_rules,
        "conflict": conflict,
        "changes": changes,
        "explanation": explanation,
    }


def classify_transactions(
    connection: sqlite3.Connection,
    transaction_ids: Iterable[str],
    *,
    rule_id: int | None = None,
    include_manual: bool = False,
    persist: bool = True,
) -> dict[str, Any]:
    rules = _rule_rows(connection, rule_id)
    if rule_id is not None and not rules:
        raise FinanceNotFoundError("Classification rule was not found.")
    results = [
        classify_transaction(
            connection, transaction_id, rules=rules, include_manual=include_manual, persist=persist
        )
        for transaction_id in transaction_ids
    ]
    change_counts = {field: sum(item["changes"][field] for item in results) for field in ACTION_FIELDS}
    changed_transactions = sum(any(item["changes"].values()) for item in results)
    return {
        "matched": len(results),
        "changedTransactions": changed_transactions,
        "changes": change_counts,
        "alreadyIdentical": len(results) - changed_transactions,
        "conflicts": sum(item["conflict"] for item in results),
        "results": results,
    }


def rule_matching_transaction_ids(connection: sqlite3.Connection, rule_id: int) -> list[str]:
    rules = _rule_rows(connection, rule_id)
    if not rules:
        raise FinanceNotFoundError("Classification rule was not found.")
    rule = rules[0]
    rows = connection.execute(
        """
        SELECT t.*, a.display_label AS account_display, m.canonical_name AS merchant_name
        FROM transactions t JOIN accounts a ON a.id = t.account_id
        LEFT JOIN merchants m ON m.id = t.merchant_id ORDER BY t.transaction_date, t.id
        """
    ).fetchall()
    return [str(row["id"]) for row in rows if all(_condition_matches(item, row) for item in rule["conditions"])]


def classification_explanation(connection: sqlite3.Connection, transaction_id: str) -> dict[str, Any]:
    row = _transaction_row(connection, transaction_id)
    fields = []
    for name, value_column, source_column, rule_column in (
        ("merchant", "merchant_id", "merchant_source", "merchant_rule_id"),
        ("category", "category_id", "category_source", "category_rule_id"),
        ("merchantType", "merchant_type_id", "merchant_type_source", "merchant_type_rule_id"),
        ("transactionKind", "transaction_kind", "kind_source", "kind_rule_id"),
    ):
        rule = None
        if row[rule_column]:
            rule = connection.execute(
                "SELECT id, name, priority FROM classification_rules WHERE id = ?", (row[rule_column],)
            ).fetchone()
        fields.append({
            "field": name,
            "value": row[value_column],
            "source": row[source_column],
            "rule": dict(rule) if rule else None,
        })
    return {"transactionId": transaction_id, "conflict": bool(row["classification_conflict"]), "fields": fields}
