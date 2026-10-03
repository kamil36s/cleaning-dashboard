"""Normalized finance entities, rule management, and deterministic review workflow."""

from __future__ import annotations

import json
import sqlite3
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from finance_classification import (
    ACTION_FIELDS,
    CONDITION_OPERATORS,
    TRANSACTION_KINDS,
    classification_explanation,
    classify_transaction,
    classify_transactions,
    rule_matching_transaction_ids,
)
from finance_repository import FinanceError, FinanceNotFoundError, FinanceRepository, normalize_entity_name, utc_now


def _clean_name(value: Any, *, maximum: int = 200) -> str:
    name = " ".join(str(value or "").strip().split())[:maximum]
    if not name:
        raise FinanceError("Name is required.")
    return name


def _minor(value: Any) -> int:
    try:
        return int((Decimal(str(value)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise FinanceError("Rule amount must be a valid number.") from exc


class FinanceOperationsService:
    def __init__(self, repository: FinanceRepository):
        self.repository = repository

    @staticmethod
    def _category_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": int(row["id"]), "name": row["name"], "parentId": row["parent_id"],
            "parentName": row["parent_name"] if "parent_name" in row.keys() else None,
            "sortOrder": int(row["sort_order"]), "active": bool(row["is_active"]),
        }

    def list_categories(self) -> list[dict[str, Any]]:
        with self.repository.read_connection() as connection:
            rows = connection.execute(
                """SELECT c.*,p.name parent_name FROM categories c
                   LEFT JOIN categories p ON p.id=c.parent_id WHERE c.is_active=1
                   ORDER BY c.parent_id IS NOT NULL,c.parent_id,c.sort_order,c.normalized_name,c.id"""
            ).fetchall()
        return [self._category_dict(row) for row in rows]

    def create_category(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = _clean_name(payload.get("name"))
        normalized = normalize_entity_name(name)
        parent_id = payload.get("parentId")
        if parent_id in ("", None):
            parent_id = None
        else:
            parent_id = int(parent_id)
        sort_order = int(payload.get("sortOrder") or 0)
        with self.repository.transaction() as connection:
            if parent_id is not None:
                parent = connection.execute(
                    "SELECT id, parent_id FROM categories WHERE id=? AND is_active=1", (parent_id,)
                ).fetchone()
                if not parent or parent["parent_id"] is not None:
                    raise FinanceError("Subcategories must belong to an active top-level category.")
            duplicate = connection.execute(
                "SELECT id FROM categories WHERE normalized_name=? AND parent_id IS ?",
                (normalized, parent_id),
            ).fetchone()
            if duplicate:
                raise FinanceError("A category with this normalized name already exists at this level.")
            now = utc_now()
            cursor = connection.execute(
                """
                INSERT INTO categories(name, normalized_name, parent_id, sort_order, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (name, normalized, parent_id, sort_order, now, now),
            )
            row = connection.execute("SELECT * FROM categories WHERE id=?", (cursor.lastrowid,)).fetchone()
        return self._category_dict(row)

    def update_category(self, category_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        name = _clean_name(payload.get("name"))
        normalized = normalize_entity_name(name)
        with self.repository.transaction() as connection:
            current = connection.execute("SELECT * FROM categories WHERE id=?", (category_id,)).fetchone()
            if not current:
                raise FinanceNotFoundError("Category was not found.")
            duplicate = connection.execute(
                "SELECT id FROM categories WHERE normalized_name=? AND parent_id IS ? AND id<>?",
                (normalized, current["parent_id"], category_id),
            ).fetchone()
            if duplicate:
                raise FinanceError("A category with this normalized name already exists at this level.")
            connection.execute(
                "UPDATE categories SET name=?, normalized_name=?, updated_at=? WHERE id=?",
                (name, normalized, utc_now(), category_id),
            )
            row = connection.execute("SELECT * FROM categories WHERE id=?", (category_id,)).fetchone()
        return self._category_dict(row)

    def _resolve_category(self, connection: sqlite3.Connection, value: Any) -> tuple[int | None, str]:
        if value in (None, ""):
            return None, ""
        if isinstance(value, int) or str(value).isdigit():
            row = connection.execute("SELECT id, name FROM categories WHERE id=? AND is_active=1", (int(value),)).fetchone()
            if not row:
                raise FinanceNotFoundError("Category was not found.")
            return int(row["id"]), str(row["name"])
        name = _clean_name(value)
        normalized = normalize_entity_name(name)
        rows = connection.execute(
            "SELECT id, name FROM categories WHERE normalized_name=? AND is_active=1 ORDER BY parent_id IS NOT NULL, id",
            (normalized,),
        ).fetchall()
        if len(rows) > 1:
            raise FinanceError("Category name is ambiguous; use a category id.")
        if rows:
            return int(rows[0]["id"]), str(rows[0]["name"])
        now = utc_now()
        cursor = connection.execute(
            "INSERT INTO categories(name, normalized_name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (name, normalized, now, now),
        )
        return int(cursor.lastrowid), name

    def _resolve_type(self, connection: sqlite3.Connection, value: Any) -> tuple[int | None, str]:
        if value in (None, ""):
            return None, ""
        if isinstance(value, int) or str(value).isdigit():
            row = connection.execute("SELECT id, name FROM merchant_types WHERE id=? AND is_active=1", (int(value),)).fetchone()
            if not row:
                raise FinanceNotFoundError("Merchant type was not found.")
            return int(row["id"]), str(row["name"])
        name = _clean_name(value)
        normalized = normalize_entity_name(name)
        row = connection.execute("SELECT id, name FROM merchant_types WHERE normalized_name=?", (normalized,)).fetchone()
        if row:
            return int(row["id"]), str(row["name"])
        now = utc_now()
        cursor = connection.execute(
            "INSERT INTO merchant_types(name, normalized_name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (name, normalized, now, now),
        )
        return int(cursor.lastrowid), name

    def _resolve_merchant(self, connection: sqlite3.Connection, value: Any) -> tuple[int | None, str]:
        if value in (None, ""):
            return None, ""
        if isinstance(value, int) or str(value).isdigit():
            row = connection.execute("SELECT id, canonical_name FROM merchants WHERE id=? AND is_active=1", (int(value),)).fetchone()
            if not row:
                raise FinanceNotFoundError("Merchant was not found.")
            return int(row["id"]), str(row["canonical_name"])
        name = _clean_name(value, maximum=500)
        normalized = normalize_entity_name(name)
        row = connection.execute("SELECT id, canonical_name FROM merchants WHERE normalized_name=?", (normalized,)).fetchone()
        if row:
            return int(row["id"]), str(row["canonical_name"])
        now = utc_now()
        cursor = connection.execute(
            "INSERT INTO merchants(canonical_name, normalized_name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (name, normalized, now, now),
        )
        return int(cursor.lastrowid), name

    def list_merchant_types(self) -> list[dict[str, Any]]:
        with self.repository.read_connection() as connection:
            rows = connection.execute("SELECT * FROM merchant_types ORDER BY normalized_name, id").fetchall()
        return [{"id": int(row["id"]), "name": row["name"], "active": bool(row["is_active"])} for row in rows]

    def list_merchants(self) -> list[dict[str, Any]]:
        with self.repository.read_connection() as connection:
            rows = connection.execute(
                """
                SELECT m.*, c.name AS default_category, mt.name AS merchant_type,
                       COUNT(DISTINCT ma.id) AS alias_count
                FROM merchants m LEFT JOIN categories c ON c.id=m.default_category_id
                LEFT JOIN merchant_types mt ON mt.id=m.merchant_type_id
                LEFT JOIN merchant_aliases ma ON ma.merchant_id=m.id
                GROUP BY m.id ORDER BY m.normalized_name, m.id
                """
            ).fetchall()
        return [{
            "id": int(row["id"]), "canonicalName": row["canonical_name"],
            "defaultCategoryId": row["default_category_id"], "defaultCategory": row["default_category"],
            "merchantTypeId": row["merchant_type_id"], "merchantType": row["merchant_type"],
            "active": bool(row["is_active"]), "aliasCount": int(row["alias_count"]),
        } for row in rows]

    def create_merchant(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = _clean_name(payload.get("canonicalName"), maximum=500)
        normalized = normalize_entity_name(name)
        with self.repository.transaction() as connection:
            if connection.execute("SELECT id FROM merchants WHERE normalized_name=?", (normalized,)).fetchone():
                raise FinanceError("A merchant with this normalized name already exists.")
            category_id, _ = self._resolve_category(connection, payload.get("defaultCategoryId"))
            type_id, _ = self._resolve_type(connection, payload.get("merchantTypeId"))
            now = utc_now()
            cursor = connection.execute(
                """
                INSERT INTO merchants(canonical_name, normalized_name, default_category_id, merchant_type_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (name, normalized, category_id, type_id, now, now),
            )
            merchant_id = int(cursor.lastrowid)
            for alias_value in payload.get("aliases") or []:
                alias = normalize_entity_name(alias_value)
                if alias:
                    connection.execute("DELETE FROM ambiguous_merchant_aliases WHERE normalized_alias=?", (alias,))
                    connection.execute(
                        "INSERT INTO merchant_aliases(merchant_id, normalized_alias, source, created_at, updated_at) VALUES (?, ?, 'manual', ?, ?)",
                        (merchant_id, alias, now, now),
                    )
        return next(item for item in self.list_merchants() if item["id"] == merchant_id)

    def add_merchant_alias(self, merchant_id: int, alias_value: Any) -> dict[str, Any]:
        alias = normalize_entity_name(_clean_name(alias_value, maximum=1000))
        with self.repository.transaction() as connection:
            if not connection.execute("SELECT id FROM merchants WHERE id=?", (merchant_id,)).fetchone():
                raise FinanceNotFoundError("Merchant was not found.")
            try:
                connection.execute("DELETE FROM ambiguous_merchant_aliases WHERE normalized_alias=?", (alias,))
                cursor = connection.execute(
                    "INSERT INTO merchant_aliases(merchant_id, normalized_alias, source, created_at, updated_at) VALUES (?, ?, 'manual', ?, ?)",
                    (merchant_id, alias, utc_now(), utc_now()),
                )
            except sqlite3.IntegrityError as exc:
                raise FinanceError("This normalized alias is already assigned.") from exc
        return {"id": int(cursor.lastrowid), "merchantId": merchant_id, "normalizedAlias": alias, "source": "manual"}

    def manual_update(self, transaction_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        allowed = {"merchant", "merchantId", "category", "categoryId", "merchantType", "merchantTypeId", "transactionKind", "note"}
        if set(payload) - allowed:
            raise FinanceError("Manual classification contains unsupported fields.")
        with self.repository.transaction() as connection:
            current = connection.execute("SELECT * FROM transactions WHERE id=?", (transaction_id,)).fetchone()
            if not current:
                raise FinanceNotFoundError("Transaction was not found.")
            merchant_value = payload.get("merchantId", payload.get("merchant")) if ({"merchant", "merchantId"} & set(payload)) else current["merchant_id"]
            category_value = payload.get("categoryId", payload.get("category")) if ({"category", "categoryId"} & set(payload)) else current["category_id"]
            type_value = payload.get("merchantTypeId", payload.get("merchantType")) if ({"merchantType", "merchantTypeId"} & set(payload)) else current["merchant_type_id"]
            merchant_id, merchant_name = self._resolve_merchant(connection, merchant_value)
            category_id, category_name = self._resolve_category(connection, category_value)
            type_id, type_name = self._resolve_type(connection, type_value)
            kind = payload.get("transactionKind", current["transaction_kind"])
            if kind not in TRANSACTION_KINDS:
                raise FinanceError("Unsupported transaction kind.")
            note = str(payload.get("note", current["note"]) or "")[:4000]
            merchant_changed = bool({"merchant", "merchantId"} & set(payload))
            category_changed = bool({"category", "categoryId"} & set(payload))
            type_changed = bool({"merchantType", "merchantTypeId"} & set(payload))
            kind_changed = "transactionKind" in payload
            connection.execute(
                """
                UPDATE transactions SET merchant_id=?, category_id=?, merchant_type_id=?, transaction_kind=?,
                  merchant=?, user_category=?, merchant_type=?, note=?,
                  merchant_source=CASE WHEN ? THEN 'manual' ELSE merchant_source END,
                  category_source=CASE WHEN ? THEN 'manual' ELSE category_source END,
                  merchant_type_source=CASE WHEN ? THEN 'manual' ELSE merchant_type_source END,
                  kind_source=CASE WHEN ? THEN 'manual' ELSE kind_source END,
                  merchant_rule_id=CASE WHEN ? THEN NULL ELSE merchant_rule_id END,
                  category_rule_id=CASE WHEN ? THEN NULL ELSE category_rule_id END,
                  merchant_type_rule_id=CASE WHEN ? THEN NULL ELSE merchant_type_rule_id END,
                  kind_rule_id=CASE WHEN ? THEN NULL ELSE kind_rule_id END,
                  taxonomy_review_required=CASE WHEN ? THEN 0 ELSE taxonomy_review_required END,
                  classification_conflict=0, updated_at=? WHERE id=?
                """,
                (
                    merchant_id, category_id, type_id, kind, merchant_name, category_name, type_name, note,
                    merchant_changed, category_changed, type_changed, kind_changed,
                    merchant_changed, category_changed, type_changed, kind_changed,
                    category_changed, utc_now(), transaction_id,
                ),
            )
            if merchant_changed and merchant_id:
                alias = normalize_entity_name(current["raw_description"])
                if alias:
                    ambiguous = connection.execute(
                        "SELECT 1 FROM ambiguous_merchant_aliases WHERE normalized_alias=?", (alias,)
                    ).fetchone()
                    existing_alias = connection.execute(
                        "SELECT merchant_id FROM merchant_aliases WHERE normalized_alias=?", (alias,)
                    ).fetchone()
                    if not ambiguous and existing_alias and int(existing_alias["merchant_id"]) != merchant_id:
                        connection.execute("DELETE FROM merchant_aliases WHERE normalized_alias=?", (alias,))
                        connection.execute(
                            "INSERT INTO ambiguous_merchant_aliases(normalized_alias, created_at) VALUES (?, ?)",
                            (alias, utc_now()),
                        )
                    elif not ambiguous and not existing_alias:
                        connection.execute(
                            "INSERT INTO merchant_aliases(merchant_id, normalized_alias, source, created_at, updated_at) VALUES (?, ?, 'manual', ?, ?)",
                            (merchant_id, alias, utc_now(), utc_now()),
                        )
            result = classification_explanation(connection, transaction_id)
        return result

    def list_rules(self) -> list[dict[str, Any]]:
        with self.repository.read_connection() as connection:
            rules = connection.execute("SELECT * FROM classification_rules ORDER BY priority, id").fetchall()
            result = []
            for row in rules:
                item = {
                    "id": int(row["id"]), "name": row["name"], "priority": int(row["priority"]),
                    "enabled": bool(row["enabled"]), "stopProcessing": bool(row["stop_processing"]),
                }
                item["conditions"] = [dict(value) for value in connection.execute(
                    "SELECT field, operator, value_text, value_minor FROM rule_conditions WHERE rule_id=? ORDER BY position,id", (row["id"],)
                )]
                item["actions"] = [dict(value) for value in connection.execute(
                    "SELECT field, value_text, value_id FROM rule_actions WHERE rule_id=? ORDER BY position,id", (row["id"],)
                )]
                result.append(item)
        return result

    def create_rule(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = _clean_name(payload.get("name"), maximum=300)
        conditions = payload.get("conditions")
        actions = payload.get("actions")
        if not isinstance(conditions, list) or not conditions or len(conditions) > 20:
            raise FinanceError("A rule requires between 1 and 20 conditions.")
        if not isinstance(actions, list) or not actions or len(actions) > 10:
            raise FinanceError("A rule requires between 1 and 10 actions.")
        priority = max(-100000, min(100000, int(payload.get("priority", 100))))
        with self.repository.transaction() as connection:
            now = utc_now()
            cursor = connection.execute(
                "INSERT INTO classification_rules(name,priority,enabled,stop_processing,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                (name, priority, int(payload.get("enabled", True)), int(payload.get("stopProcessing", False)), now, now),
            )
            rule_id = int(cursor.lastrowid)
            for position, condition in enumerate(conditions):
                field = str(condition.get("field") or "")
                operator = str(condition.get("operator") or "")
                if field not in CONDITION_OPERATORS or operator not in CONDITION_OPERATORS[field]:
                    raise FinanceError("Unsupported rule condition.")
                value_text = condition.get("value")
                value_minor = None
                if field == "amount":
                    if operator == "between":
                        values = condition.get("value")
                        if not isinstance(values, list) or len(values) != 2:
                            raise FinanceError("Amount between requires two values.")
                        value_text = json.dumps([_minor(values[0]), _minor(values[1])])
                    else:
                        value_minor = _minor(condition.get("value"))
                        value_text = None
                elif field == "sign" and value_text not in {"positive", "negative", "zero"}:
                    raise FinanceError("Rule sign must be positive, negative, or zero.")
                connection.execute(
                    "INSERT INTO rule_conditions(rule_id,field,operator,value_text,value_minor,position) VALUES (?,?,?,?,?,?)",
                    (rule_id, field, operator, None if value_text is None else str(value_text), value_minor, position),
                )
            for position, action in enumerate(actions):
                field = str(action.get("field") or "")
                if field not in ACTION_FIELDS:
                    raise FinanceError("Unsupported rule action.")
                value_id = None
                value_text = None
                if field == "merchant":
                    value_id, _ = self._resolve_merchant(connection, action.get("valueId", action.get("value")))
                elif field == "category":
                    value_id, _ = self._resolve_category(connection, action.get("valueId", action.get("value")))
                elif field == "merchant_type":
                    value_id, _ = self._resolve_type(connection, action.get("valueId", action.get("value")))
                else:
                    value_text = str(action.get("value") or "")
                    if value_text not in TRANSACTION_KINDS:
                        raise FinanceError("Unsupported transaction kind action.")
                connection.execute(
                    "INSERT INTO rule_actions(rule_id,field,value_text,value_id,position) VALUES (?,?,?,?,?)",
                    (rule_id, field, value_text, value_id, position),
                )
        return next(rule for rule in self.list_rules() if rule["id"] == rule_id)

    def set_rule_state(self, rule_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        assignments = []
        params: list[Any] = []
        for key, column in (("name", "name"), ("priority", "priority"), ("enabled", "enabled"), ("stopProcessing", "stop_processing")):
            if key in payload:
                assignments.append(f"{column}=?")
                value = payload[key]
                params.append(int(bool(value)) if key in {"enabled", "stopProcessing"} else value)
        if not assignments:
            raise FinanceError("No rule fields to update.")
        with self.repository.transaction() as connection:
            result = connection.execute(
                f"UPDATE classification_rules SET {', '.join(assignments)}, updated_at=? WHERE id=?",
                (*params, utc_now(), rule_id),
            )
            if result.rowcount != 1:
                raise FinanceNotFoundError("Classification rule was not found.")
        return next(rule for rule in self.list_rules() if rule["id"] == rule_id)

    def delete_rule(self, rule_id: int) -> dict[str, Any]:
        with self.repository.transaction() as connection:
            result = connection.execute("DELETE FROM classification_rules WHERE id=?", (rule_id,))
            if result.rowcount != 1:
                raise FinanceNotFoundError("Classification rule was not found.")
        return {"id": rule_id, "deleted": True}

    def preview_rule(self, rule_id: int, *, include_manual: bool = False) -> dict[str, Any]:
        with self.repository.read_connection() as connection:
            transaction_ids = rule_matching_transaction_ids(connection, rule_id)
            result = classify_transactions(
                connection, transaction_ids, rule_id=rule_id, include_manual=include_manual, persist=False
            )
        result.pop("results", None)
        result["ruleId"] = rule_id
        return result

    def apply_rule(self, rule_id: int, *, include_manual: bool = False) -> dict[str, Any]:
        with self.repository.transaction() as connection:
            transaction_ids = rule_matching_transaction_ids(connection, rule_id)
            result = classify_transactions(
                connection, transaction_ids, rule_id=rule_id, include_manual=include_manual, persist=True
            )
        result.pop("results", None)
        result["ruleId"] = rule_id
        return result

    def explain(self, transaction_id: str) -> dict[str, Any]:
        with self.repository.read_connection() as connection:
            return classification_explanation(connection, transaction_id)

    def list_review(self, status: str = "open", limit: int = 500) -> list[dict[str, Any]]:
        if status not in {"open", "resolved", "ignored", "all"}:
            raise FinanceError("Unsupported review status.")
        with self.repository.read_connection() as connection:
            rows = connection.execute(
                """
                SELECT t.id, t.transaction_date, t.amount_minor, t.currency, t.raw_description,
                       t.merchant_id, t.category_id, t.transaction_kind, t.classification_conflict,
                       t.taxonomy_review_required,m.canonical_name AS merchant,c.name AS category,
                       pc.name AS parent_category,m.default_category_id,
                       dc.name AS default_category
                FROM transactions t LEFT JOIN merchants m ON m.id=t.merchant_id
                LEFT JOIN categories c ON c.id=t.category_id
                LEFT JOIN categories pc ON pc.id=c.parent_id
                LEFT JOIN categories dc ON dc.id=m.default_category_id
                ORDER BY t.transaction_date DESC, t.id
                """
            ).fetchall()
            decisions = {(row["transaction_id"], row["issue_type"]): row["status"] for row in connection.execute(
                "SELECT * FROM review_decisions"
            )}
            aliases = {str(alias["normalized_alias"]): dict(alias) for alias in connection.execute(
                """SELECT ma.normalized_alias,ma.merchant_id,m.canonical_name merchant
                   FROM merchant_aliases ma JOIN merchants m ON m.id=ma.merchant_id"""
            )}
        items = []
        merchant_candidates: dict[str, set[int]] = {}
        history: dict[str, list[Any]] = {}
        for row in rows:
            history.setdefault(normalize_entity_name(row["raw_description"]), []).append(row)
            if row["merchant_id"] is not None:
                merchant_candidates.setdefault(normalize_entity_name(row["raw_description"]), set()).add(int(row["merchant_id"]))
        for row in rows:
            issues = []
            if row["merchant_id"] is None and row["transaction_kind"] not in {"transfer", "saving", "cash"}:
                candidates = merchant_candidates.get(normalize_entity_name(row["raw_description"]), set())
                issues.append("ambiguous_classification" if len(candidates) > 1 else "unknown_merchant")
            if row["category_id"] is None:
                issues.append("missing_category")
            if row["transaction_kind"] is None:
                issues.append("missing_transaction_kind")
            if row["classification_conflict"]:
                issues.append("rule_conflict")
            if row["taxonomy_review_required"]:
                issues.append("ambiguous_category_mapping")
            normalized = normalize_entity_name(row["raw_description"])
            matching = history.get(normalized, [])
            suggestion: dict[str, Any] = {"evidence": [], "similarCount": len(matching)}
            alias = aliases.get(normalized)
            if alias:
                suggestion.update({"merchantId": alias["merchant_id"], "merchant": alias["merchant"]})
                suggestion["evidence"].append("Dokładny znany alias opisu")
            for source_key, output_id, output_label, label in (
                ("merchant_id", "merchantId", "merchant", "miejsce"),
                ("category_id", "categoryId", "category", "kategorię"),
                ("transaction_kind", "transactionKind", None, "rodzaj transakcji"),
            ):
                values = {item[source_key] for item in matching if item[source_key] is not None}
                if len(matching) >= 2 and len(values) == 1:
                    value = next(iter(values))
                    suggestion.setdefault(output_id, value)
                    if output_label:
                        named = next((item[output_label] for item in matching if item[source_key] == value), None)
                        suggestion.setdefault(output_label, named)
                    suggestion["evidence"].append(
                        f"{len(matching)} zgodnych historycznych opisów wskazuje {label}"
                    )
            if row["default_category_id"] is not None:
                suggestion.setdefault("categoryId", row["default_category_id"])
                suggestion.setdefault("category", row["default_category"])
                suggestion["evidence"].append(f"Wartość domyślna miejsca: {row['default_category']}")
            if not suggestion["evidence"]:
                suggestion = None
            for issue in issues:
                item_status = decisions.get((row["id"], issue), "open")
                if status != "all" and item_status != status:
                    continue
                items.append({
                    "transactionId": row["id"], "issueType": issue, "status": item_status,
                    "date": row["transaction_date"], "amount": row["amount_minor"] / 100,
                    "currency": row["currency"], "merchantId": row["merchant_id"],
                    "merchant": row["merchant"], "categoryId": row["category_id"], "category": row["category"],
                    "parentCategory": row["parent_category"],
                    "transactionKind": row["transaction_kind"], "description": row["raw_description"],
                    "suggestion": suggestion,
                    "rulePreview": {
                        "conditionLabel": f'opis jest równy „{row["raw_description"]}”',
                        "historicalMatches": len(matching),
                    },
                })
                if len(items) >= max(1, min(500, int(limit))):
                    return items
        return items

    def review_action(self, transaction_id: str, issue_type: str, status: str) -> dict[str, Any]:
        if issue_type not in {"unknown_merchant", "missing_category", "missing_transaction_kind", "rule_conflict", "ambiguous_classification", "ambiguous_category_mapping"}:
            raise FinanceError("Unsupported review issue.")
        if status not in {"resolved", "ignored"}:
            raise FinanceError("Review status must be resolved or ignored.")
        with self.repository.transaction() as connection:
            if not connection.execute("SELECT id FROM transactions WHERE id=?", (transaction_id,)).fetchone():
                raise FinanceNotFoundError("Transaction was not found.")
            connection.execute(
                """
                INSERT INTO review_decisions(transaction_id,issue_type,status,updated_at) VALUES (?,?,?,?)
                ON CONFLICT(transaction_id,issue_type) DO UPDATE SET status=excluded.status, updated_at=excluded.updated_at
                """,
                (transaction_id, issue_type, status, utc_now()),
            )
        return {"transactionId": transaction_id, "issueType": issue_type, "status": status}

    def update_similar(self, transaction_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self.repository.read_connection() as connection:
            source = connection.execute(
                "SELECT raw_description FROM transactions WHERE id=?", (transaction_id,)
            ).fetchone()
            if not source:
                raise FinanceNotFoundError("Transaction was not found.")
            normalized = normalize_entity_name(source["raw_description"])
            ids = [str(row["id"]) for row in connection.execute(
                "SELECT id,raw_description FROM transactions"
            ) if normalize_entity_name(row["raw_description"]) == normalized]
        for target_id in ids:
            self.manual_update(target_id, payload)
        return {"matched": len(ids), "transactionIds": ids}

    def classify_imported(self, connection: sqlite3.Connection, transaction_id: str) -> dict[str, Any]:
        return classify_transaction(connection, transaction_id, persist=True)
