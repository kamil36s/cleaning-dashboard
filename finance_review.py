"""Pack C.6 deterministic finance review groups, evidence, and safe bulk actions."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from collections import Counter, defaultdict
from datetime import date
from typing import Any

from finance_importer import transaction_family
from finance_repository import FinanceError, FinanceNotFoundError, FinanceRepository, normalize_entity_name, utc_now


CATEGORY_REQUIRED_KINDS = frozenset({"expense"})
MERCHANT_RELEVANT_KINDS = frozenset({"expense", "refund", "other"})
NON_CATEGORY_KINDS = frozenset({"transfer", "saving", "salary", "income", "refund", "cash", "other"})
MIXED_RETAILERS = (
    "biedronka", "zabka", "lidl", "carrefour", "auchan", "lewiatan",
    "kaufland", "aldi", "netto", "delikatesy centrum",
)

_BOILERPLATE = (
    r"\bzakup przy uzyciu karty\s*-?\s*internet\b",
    r"\bzakup przy uzyciu karty(?: w kraju| za granica)?\b",
    r"\bblik zakup e-commerce\b",
    r"\btransakcja nierozliczona\b",
    r"\bplatnosc karta\b",
    r"\btransakcja karta\b",
)


def category_required(kind: Any) -> bool:
    return str(kind or "") in CATEGORY_REQUIRED_KINDS


def semantic_transaction_kind(row: sqlite3.Row | dict[str, Any]) -> str | None:
    """Interpret exact bank rails for Review without rewriting canonical history."""
    stored = row["transaction_kind"]
    family = transaction_family(row["raw_description"], row["raw_category"])
    raw = normalize_entity_name(f"{row['raw_category']} {row['raw_description']}")
    amount = int(row["amount_minor"])
    if family in {"goal_withdrawal", "goal_deposit", "incoming_transfer", "outgoing_transfer", "blik_p2p_in", "blik_p2p_out"}:
        return "transfer"
    if family == "goal_transfer":
        return "saving" if amount < 0 else "transfer"
    if family in {"cash_withdrawal", "cash_deposit"}:
        return "cash"
    if family == "salary":
        return "salary"
    if family == "refund":
        return "refund"
    if family == "interest" and amount >= 0:
        return "income"
    # Historical mojibake can obscure Polish letters, so retain only broad,
    # rail-specific tokens. No merchant/person inference is made here.
    if "przelew" in raw or "p2p" in raw or "celu" in raw:
        return "transfer"
    if "bankom" in raw or "gotow" in raw:
        return "cash"
    if "wynagrod" in raw or "pensja" in raw:
        return "salary"
    if "zwrot" in raw and amount >= 0:
        return "refund"
    if "oszcz" in raw:
        return "saving" if amount < 0 else "transfer"
    if "wplywy" in raw and amount >= 0:
        return "income"
    return stored


def row_category_required(row: sqlite3.Row | dict[str, Any]) -> bool:
    return category_required(semantic_transaction_kind(row))


def normalize_grouping_description(raw_description: Any, raw_category: Any = "") -> str:
    """Remove known bank rail wording while retaining entity-specific text."""
    text = normalize_entity_name(raw_description)
    for pattern in _BOILERPLATE:
        text = re.sub(pattern, " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\bdata transakcji\s*:?\s*\d{2}[./-]\d{2}[./-]\d{4}\b", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" -/.,")
    generic = {"", "przelew", "zakup", "transakcja", "platnosc"}
    if text in generic:
        category_text = normalize_entity_name(raw_category)
        return category_text if category_text not in generic else text
    return text


def _ratio_label(count: int, total: int, label: str) -> str:
    return f"{count} z {total} historycznych transakcji: {label}."


class FinanceReviewService:
    def __init__(self, repository: FinanceRepository):
        self.repository = repository

    @staticmethod
    def _scope_bounds(scope: str, month: str | None) -> tuple[str | None, str | None]:
        if scope == "all_history":
            return None, None
        if scope != "selected_month" or not re.fullmatch(r"\d{4}-\d{2}", str(month or "")):
            raise FinanceError("Review scope requires a selected YYYY-MM month.")
        year, number = map(int, str(month).split("-"))
        if not 1 <= number <= 12:
            raise FinanceError("Review month is invalid.")
        next_month = date(year + (number == 12), 1 if number == 12 else number + 1, 1)
        return f"{year:04d}-{number:02d}-01", next_month.isoformat()

    @staticmethod
    def _in_scope(row: sqlite3.Row, bounds: tuple[str | None, str | None]) -> bool:
        start, end = bounds
        return start is None or start <= row["transaction_date"] < end

    @staticmethod
    def _issues(row: sqlite3.Row) -> list[str]:
        result = []
        kind = semantic_transaction_kind(row)
        if row["merchant_id"] is None and kind in MERCHANT_RELEVANT_KINDS:
            result.append("unknown_merchant")
        if row["category_id"] is None and category_required(kind):
            result.append("missing_category")
        if row["transaction_kind"] is None:
            result.append("missing_transaction_kind")
        if row["classification_conflict"]:
            result.append("rule_conflict")
        if row["taxonomy_review_required"]:
            result.append("ambiguous_category_mapping")
        return result

    def _rows(self, connection: sqlite3.Connection) -> list[sqlite3.Row]:
        return connection.execute(
            """SELECT t.*,m.canonical_name merchant,m.default_category_id,m.merchant_type_id merchant_default_type_id,
                      c.name category,pc.name parent_category,mt.name merchant_type
               FROM transactions t
               LEFT JOIN merchants m ON m.id=t.merchant_id
               LEFT JOIN categories c ON c.id=t.category_id
               LEFT JOIN categories pc ON pc.id=c.parent_id
               LEFT JOIN merchant_types mt ON mt.id=t.merchant_type_id
               ORDER BY t.transaction_date,t.id"""
        ).fetchall()

    @staticmethod
    def _group_key(row: sqlite3.Row, alias_merchants: dict[str, int], grouping_merchants: dict[str, int] | None = None) -> tuple[str, str, str]:
        normalized = normalize_grouping_description(row["raw_description"], row["raw_category"])
        merchant_id = row["merchant_id"] or alias_merchants.get(normalize_entity_name(row["raw_description"])) or (grouping_merchants or {}).get(normalized)
        family = transaction_family(row["raw_description"], row["raw_category"])
        if merchant_id:
            key = f"merchant:{int(merchant_id)}"
        else:
            # Exact normalized entity text + banking rail + kind is conservative. Amount is never a key.
            key = f"pattern:{family}:{row['transaction_kind'] or 'unknown'}:{normalized}"
        return key, normalized, family

    @staticmethod
    def _group_id(key: str) -> str:
        return "rvg_" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]

    @staticmethod
    def _distribution(rows: list[sqlite3.Row], field: str, label_field: str | None = None) -> list[dict[str, Any]]:
        labels: dict[Any, str] = {}
        counts = Counter()
        for row in rows:
            value = row[field]
            if value is None:
                continue
            counts[value] += 1
            labels[value] = str(row[label_field] if label_field else value)
        total = sum(counts.values())
        return [
            {"id": value if isinstance(value, int) else None, "value": value, "label": labels[value],
             "count": count, "ratio": round(count / total, 4) if total else 0}
            for value, count in counts.most_common()
        ]

    def _load_model(self, connection: sqlite3.Connection) -> tuple[list[sqlite3.Row], dict[str, tuple[str, str]], dict[str, list[sqlite3.Row]]]:
        rows = self._rows(connection)
        aliases = {str(r["normalized_alias"]): int(r["merchant_id"]) for r in connection.execute("SELECT normalized_alias,merchant_id FROM merchant_aliases")}
        grouping_candidates: dict[str, set[int]] = defaultdict(set)
        for row in rows:
            if row["merchant_id"] is not None:
                grouping_candidates[normalize_grouping_description(row["raw_description"], row["raw_category"])].add(int(row["merchant_id"]))
        grouping_merchants = {key: next(iter(values)) for key, values in grouping_candidates.items() if len(values) == 1}
        decisions = {(str(r["transaction_id"]), str(r["issue_type"])): str(r["status"]) for r in connection.execute("SELECT transaction_id,issue_type,status FROM review_decisions")}
        grouped: dict[str, list[sqlite3.Row]] = defaultdict(list)
        keys: dict[str, tuple[str, str]] = {}
        for row in rows:
            key, normalized, family = self._group_key(row, aliases, grouping_merchants)
            group_id = self._group_id(key)
            grouped[group_id].append(row)
            keys[group_id] = (normalized, family)
        return rows, decisions, grouped

    def _metrics_for_model(self, rows: list[sqlite3.Row], decisions: dict[tuple[str, str], str],
                           grouped: dict[str, list[sqlite3.Row]], month: str) -> dict[str, Any]:
        selected_bounds = self._scope_bounds("selected_month", month)
        def scope_counts(bounds):
            scoped = [row for row in rows if self._in_scope(row, bounds)]
            transaction_ids = set(); issue_count = 0; group_ids = set()
            for group_id, group_rows in grouped.items():
                for row in group_rows:
                    if not self._in_scope(row, bounds): continue
                    issues = [issue for issue in self._issues(row) if decisions.get((row["id"], issue)) not in {"ignored", "resolved"}]
                    if issues:
                        transaction_ids.add(row["id"]); group_ids.add(group_id); issue_count += len(issues)
            return {"groups": len(group_ids), "transactions": len(transaction_ids), "issues": issue_count, "totalTransactions": len(scoped)}
        total = len(rows)
        category_required_rows = [row for row in rows if row_category_required(row)]
        merchant_relevant = [row for row in rows if semantic_transaction_kind(row) in MERCHANT_RELEVANT_KINDS]
        raw_missing = sum(row["category_id"] is None for row in rows)
        required_missing = sum(row["category_id"] is None for row in category_required_rows)
        excluded = Counter(str(semantic_transaction_kind(row) or "unknown") for row in rows if row["category_id"] is None and not row_category_required(row))
        conflict_count = sum(bool(row["classification_conflict"]) for row in rows)
        ignored = sum(status == "ignored" for status in decisions.values())
        resolved = sum(status == "resolved" for status in decisions.values())
        percent = lambda numerator, denominator: round(numerator / denominator * 100, 1) if denominator else 100.0
        return {
            "categoryRequiredKinds": sorted(CATEGORY_REQUIRED_KINDS),
            "merchant": {"recognized": sum(row["merchant_id"] is not None for row in merchant_relevant), "relevant": len(merchant_relevant),
                         "coveragePercent": percent(sum(row["merchant_id"] is not None for row in merchant_relevant), len(merchant_relevant))},
            "category": {"categorized": len(category_required_rows) - required_missing, "required": len(category_required_rows),
                         "coveragePercent": percent(len(category_required_rows) - required_missing, len(category_required_rows)),
                         "rawCategorized": total - raw_missing, "rawTotal": total, "rawCoveragePercent": percent(total - raw_missing, total),
                         "rawMissing": raw_missing, "requiredMissing": required_missing, "excludedMissingByKind": dict(sorted(excluded.items()))},
            "transactionKind": {"classified": sum(row["transaction_kind"] is not None for row in rows), "total": total,
                                "coveragePercent": percent(sum(row["transaction_kind"] is not None for row in rows), total)},
            "ruleConflicts": conflict_count, "ignoredIssues": ignored, "resolvedIssues": resolved,
            "allHistory": scope_counts((None, None)), "selectedPeriod": {"month": month, **scope_counts(selected_bounds)},
        }

    def _suggestion(self, connection: sqlite3.Connection, group_rows: list[sqlite3.Row], normalized: str) -> dict[str, Any]:
        merchant_dist = self._distribution(group_rows, "merchant_id", "merchant")
        category_dist = self._distribution(group_rows, "category_id", "category")
        kind_dist = self._distribution(group_rows, "transaction_kind")
        type_dist = self._distribution(group_rows, "merchant_type_id", "merchant_type")
        evidence: list[str] = []
        suggestion: dict[str, Any] = {}
        exact_alias = connection.execute(
            """SELECT m.id,m.canonical_name,m.default_category_id,c.name category,pc.name parent_category
               FROM merchant_aliases a JOIN merchants m ON m.id=a.merchant_id
               LEFT JOIN categories c ON c.id=m.default_category_id LEFT JOIN categories pc ON pc.id=c.parent_id
               WHERE a.normalized_alias=?""", (normalize_entity_name(group_rows[0]["raw_description"]),)
        ).fetchone()
        if exact_alias:
            suggestion.update({"merchantId": int(exact_alias["id"]), "merchant": exact_alias["canonical_name"]})
            evidence.append("Dokładny alias opisu wskazuje to miejsce.")
            if exact_alias["default_category_id"]:
                suggestion.update({"categoryId": int(exact_alias["default_category_id"]), "category": exact_alias["category"], "parentCategory": exact_alias["parent_category"]})
                evidence.append("Miejsce ma ścisłą kategorię domyślną.")
        for dist, id_key, label_key, wording in (
            (merchant_dist, "merchantId", "merchant", "miejsce"),
            (category_dist, "categoryId", "category", "kategorię"),
            (kind_dist, None, "transactionKind", "rodzaj"),
            (type_dist, "merchantTypeId", "merchantType", "typ miejsca"),
        ):
            if not dist:
                continue
            top = dist[0]
            if top["ratio"] >= .8 and top["count"] >= 2:
                if id_key:
                    suggestion.setdefault(id_key, top["value"])
                suggestion.setdefault(label_key, top["label"])
                evidence.append(_ratio_label(top["count"], sum(item["count"] for item in dist), f"{wording} {top['label']}"))
        mixed = any(name in normalized for name in MIXED_RETAILERS)
        if mixed:
            broad = connection.execute(
                """SELECT c.id,c.name,p.name parent FROM categories c JOIN categories p ON p.id=c.parent_id
                   WHERE p.normalized_name=? AND c.normalized_name=?""",
                (normalize_entity_name("Zakupy codzienne"), normalize_entity_name("Zakupy mieszane")),
            ).fetchone()
            if broad:
                suggestion.update({"categoryId": int(broad["id"]), "category": broad["name"], "parentCategory": broad["parent"]})
                evidence.append("Sprzedawca mieszany pozostaje w szerokiej kategorii bez danych z paragonu.")
        semantic_kinds = {semantic_transaction_kind(row) for row in group_rows if semantic_transaction_kind(row)}
        exact_bank_kind = not kind_dist and len(semantic_kinds) == 1
        if exact_bank_kind:
            suggestion["transactionKind"] = next(iter(semantic_kinds))
            evidence.append("Dokładna semantyka operacji bankowej wskazuje rodzaj transakcji.")
        relevant = category_dist or merchant_dist or kind_dist
        top_ratios = [dist[0]["ratio"] for dist in (merchant_dist, category_dist, kind_dist) if dist]
        sample = max([sum(item["count"] for item in dist) for dist in (merchant_dist, category_dist, kind_dist) if dist] or [0])
        if exact_bank_kind or (exact_alias and exact_alias["default_category_id"]) or (sample >= 3 and top_ratios and all(value == 1 for value in top_ratios)):
            confidence = "exact"
        elif sample >= 3 and top_ratios and all(value >= .8 for value in top_ratios):
            confidence = "strong"
        elif relevant:
            confidence = "mixed"
        else:
            confidence = "unknown"
        return {
            **suggestion, "confidence": confidence, "evidence": evidence,
            "history": {"merchants": merchant_dist, "categories": category_dist, "merchantTypes": type_dist, "transactionKinds": kind_dist},
            "mixedRetailer": mixed,
        }

    def groups(self, *, scope: str = "selected_month", month: str | None = None,
               sort: str = "impact", quick_clean: bool = False, limit: int = 200) -> dict[str, Any]:
        bounds = self._scope_bounds(scope, month)
        with self.repository.read_connection() as connection:
            rows, decisions, grouped = self._load_model(connection)
            result = []
            for group_id, history_rows in grouped.items():
                scoped = [row for row in history_rows if self._in_scope(row, bounds)]
                unresolved: list[tuple[sqlite3.Row, list[str]]] = []
                for row in scoped:
                    issues = [issue for issue in self._issues(row) if decisions.get((row["id"], issue)) not in {"ignored", "resolved"}]
                    if issues:
                        unresolved.append((row, issues))
                if not unresolved:
                    continue
                normalized = normalize_grouping_description(history_rows[0]["raw_description"], history_rows[0]["raw_category"])
                suggestion = self._suggestion(connection, history_rows, normalized)
                issue_counts = Counter(issue for _, issues in unresolved for issue in issues)
                required_suggestions = {
                    "unknown_merchant": "merchantId", "missing_category": "categoryId",
                    "missing_transaction_kind": "transactionKind", "ambiguous_category_mapping": "categoryId",
                }
                suggestion["resolvesAllFields"] = all(
                    issue not in required_suggestions or suggestion.get(required_suggestions[issue]) is not None
                    for issue in issue_counts
                ) and "rule_conflict" not in issue_counts
                if "ambiguous_category_mapping" in issue_counts and suggestion.get("categoryId") is not None:
                    suggestion["resolvesAllFields"] = suggestion["resolvesAllFields"] and all(
                        "ambiguous_category_mapping" not in issues or row["category_id"] in (None, suggestion["categoryId"])
                        for row, issues in unresolved
                    )
                if not suggestion["resolvesAllFields"]:
                    suggestion["confidence"] = "unknown" if not suggestion["evidence"] else "mixed"
                if quick_clean and (suggestion["confidence"] not in {"exact", "strong"} or not suggestion["resolvesAllFields"]):
                    continue
                dates = [row["transaction_date"] for row in history_rows]
                scoped_rows = [row for row, _ in unresolved]
                merchants_present = sum(row["merchant_id"] is not None for row in history_rows)
                category_requiring = sum(row_category_required(row) for row in history_rows)
                categories_present = sum(row_category_required(row) and row["category_id"] is not None for row in history_rows)
                display = next((row["merchant"] for row in history_rows if row["merchant"]), None) or normalized or history_rows[0]["raw_category"]
                samples = []
                for row in history_rows[-3:]:
                    samples.append({"id": row["id"], "date": row["transaction_date"], "description": row["raw_description"],
                                    "amount": row["amount_minor"] / 100, "currency": row["currency"]})
                guided_row = max(scoped_rows, key=lambda row: (row["transaction_date"], row["id"]))
                result.append({
                    "id": group_id, "displayName": display, "normalizedDescription": normalized,
                    "transactionCount": len(history_rows), "reviewTransactionCount": len(scoped_rows),
                    "dateFrom": min(dates), "dateTo": max(dates),
                    "totalAbsoluteAmount": sum(abs(row["amount_minor"]) for row in history_rows) / 100,
                    "transactionKinds": sorted({row["transaction_kind"] or "unknown" for row in history_rows}),
                    "merchantCoverage": {"recognized": merchants_present, "relevant": len(history_rows)},
                    "categoryCoverage": {"categorized": categories_present, "required": category_requiring},
                    "suggestion": suggestion, "samples": samples, "unresolvedFields": sorted(issue_counts),
                    "rememberOptions": {
                        "merchantDefault": any(row["merchant_id"] is not None for row in history_rows),
                        "exactDescriptionRule": len({row["raw_description"] for row in history_rows}) == 1,
                    },
                    "guidedTransaction": {"id": guided_row["id"], "date": guided_row["transaction_date"],
                                          "description": guided_row["raw_description"],
                                          "amount": guided_row["amount_minor"] / 100, "currency": guided_row["currency"]},
                    "issueCounts": dict(issue_counts), "historicalTransactionCount": len(history_rows),
                    "impactScore": len(scoped_rows) * 100000 + sum(abs(row["amount_minor"]) for row in scoped_rows),
                })
            summary = self._metrics_for_model(rows, decisions, grouped, month or date.today().isoformat()[:7])
        sort_keys = {
            "impact": lambda item: (item["impactScore"], item["dateTo"]),
            "transactions": lambda item: (item["reviewTransactionCount"], item["dateTo"]),
            "newest": lambda item: (item["dateTo"], item["reviewTransactionCount"]),
            "easiest": lambda item: ({"exact": 3, "strong": 2, "mixed": 1, "unknown": 0}[item["suggestion"]["confidence"]], item["reviewTransactionCount"]),
            "value": lambda item: (item["totalAbsoluteAmount"], item["reviewTransactionCount"]),
        }
        if sort not in sort_keys:
            raise FinanceError("Unsupported Review sort.")
        result.sort(key=sort_keys[sort], reverse=True)
        selected = summary["allHistory"] if scope == "all_history" else summary["selectedPeriod"]
        quick = [item for item in result if item["suggestion"]["confidence"] in {"exact", "strong"} and item["suggestion"]["resolvesAllFields"]]
        return {
            "scope": scope, "month": month, "groups": result[:max(1, min(500, int(limit)))],
            "counts": {"groups": len(result), "transactions": sum(item["reviewTransactionCount"] for item in result)},
            "quickClean": {"groups": len(quick), "transactions": sum(item["reviewTransactionCount"] for item in quick)},
            "metrics": summary, "selectedCounts": selected,
        }

    def metrics(self, *, month: str | None = None) -> dict[str, Any]:
        month = month or date.today().isoformat()[:7]
        with self.repository.read_connection() as connection:
            rows, decisions, grouped = self._load_model(connection)
            return self._metrics_for_model(rows, decisions, grouped, month)

    def _find_group(self, connection: sqlite3.Connection, group_id: str) -> tuple[list[sqlite3.Row], dict[str, tuple[str, str]]]:
        _, decisions, grouped = self._load_model(connection)
        if group_id not in grouped:
            raise FinanceNotFoundError("Review group was not found.")
        return grouped[group_id], decisions

    def group_transactions(self, group_id: str) -> list[dict[str, Any]]:
        with self.repository.read_connection() as connection:
            rows, decisions = self._find_group(connection, group_id)
            return [{
                "id": row["id"], "date": row["transaction_date"], "amount": row["amount_minor"] / 100,
                "currency": row["currency"], "description": row["raw_description"],
                "merchant": row["merchant"], "category": row["category"], "parentCategory": row["parent_category"],
                "transactionKind": row["transaction_kind"],
                "issues": [issue for issue in self._issues(row) if decisions.get((row["id"], issue)) not in {"ignored", "resolved"}],
            } for row in sorted(rows, key=lambda item: (item["transaction_date"], item["id"]), reverse=True)]

    @staticmethod
    def _classification(payload: dict[str, Any], suggestion: dict[str, Any] | None = None) -> dict[str, Any]:
        source = payload.get("classification") or suggestion or {}
        result = {}
        for key in ("merchantId", "categoryId", "merchantTypeId"):
            if source.get(key) not in (None, ""):
                result[key] = int(source[key])
        if source.get("transactionKind"):
            result["transactionKind"] = str(source["transactionKind"])
        merchant_name = re.sub(r"\s+", " ", str(source.get("merchantName") or "").strip())
        if merchant_name:
            result["merchantName"] = merchant_name[:500]
        return result

    def preview(self, group_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        scope = str(payload.get("scope") or "selected_month")
        month = payload.get("month")
        bounds = self._scope_bounds(scope, month)
        target_transaction_id = str(payload.get("targetTransactionId") or "").strip() or None
        with self.repository.read_connection() as connection:
            group_rows, decisions = self._find_group(connection, group_id)
            if target_transaction_id and target_transaction_id not in {str(row["id"]) for row in group_rows}:
                raise FinanceError("The selected transaction does not belong to this Review group.")
            normalized = normalize_grouping_description(group_rows[0]["raw_description"], group_rows[0]["raw_category"])
            suggestion = self._suggestion(connection, group_rows, normalized)
            classification = self._classification(payload, suggestion)
            targets = []
            changes = Counter()
            for row in group_rows:
                if not self._in_scope(row, bounds): continue
                if target_transaction_id and str(row["id"]) != target_transaction_id: continue
                open_issues = [issue for issue in self._issues(row) if decisions.get((row["id"], issue)) not in {"ignored", "resolved"}]
                if not open_issues: continue
                row_changes = {}
                for api_key, column in (("merchantId", "merchant_id"), ("categoryId", "category_id"), ("merchantTypeId", "merchant_type_id"), ("transactionKind", "transaction_kind")):
                    has_value = api_key in classification or (api_key == "merchantId" and "merchantName" in classification)
                    if has_value and row[column] is None:
                        row_changes[column] = classification.get(api_key, classification.get("merchantName")); changes[column] += 1
                if (classification.get("categoryId") is not None and row["taxonomy_review_required"]
                        and row["category_id"] == classification["categoryId"]):
                    row_changes["taxonomy_review_required"] = 0; changes["taxonomy_review_required"] += 1
                if row_changes: targets.append({"id": row["id"], "changes": row_changes})
            remember = bool(payload.get("remember"))
            mechanism = None
            if remember:
                merchant_id = classification.get("merchantId") or next((row["merchant_id"] for row in group_rows if row["merchant_id"]), None)
                if (merchant_id or classification.get("merchantName")) and classification.get("categoryId"):
                    mechanism = "merchant_default"
                elif classification.get("categoryId") and len({row["raw_description"] for row in group_rows}) == 1:
                    mechanism = "exact_description_rule"
            return {
                "groupId": group_id, "scope": scope, "month": month, "transactionCount": len(targets),
                "changes": {"merchant": changes["merchant_id"], "category": changes["category_id"],
                            "merchantType": changes["merchant_type_id"], "transactionKind": changes["transaction_kind"],
                            "taxonomyReview": changes["taxonomy_review_required"]},
                "manualClassificationsOverwritten": 0, "historicalValuesOverwritten": 0, "amountsChanged": 0,
                "rememberMechanism": mechanism, "classification": classification,
                "targetTransactionId": target_transaction_id,
                "targetIds": [item["id"] for item in targets],
            }

    def apply(self, group_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        preview = self.preview(group_id, payload)
        if not payload.get("confirm"):
            raise FinanceError("Bulk Review application requires explicit confirmation.")
        remember_only = bool(payload.get("remember") and preview.get("rememberMechanism"))
        if not preview["transactionCount"] and not remember_only:
            raise FinanceError("Ta decyzja nie uzupełnia żadnego z brakujących pól w tej grupie.")
        action_id = "rva_" + uuid.uuid4().hex
        with self.repository.transaction() as connection:
            group_rows, _ = self._find_group(connection, group_id)
            by_id = {row["id"]: row for row in group_rows}
            previous = []
            applied = []
            classification = dict(preview["classification"])
            created_merchant_id = None
            if classification.get("merchantName") and not classification.get("merchantId"):
                merchant_name = classification["merchantName"]
                normalized_name = normalize_entity_name(merchant_name)
                if not normalized_name:
                    raise FinanceError("Podaj prawidłową nazwę miejsca.")
                merchant = connection.execute("SELECT id FROM merchants WHERE normalized_name=?", (normalized_name,)).fetchone()
                if merchant:
                    classification["merchantId"] = int(merchant["id"])
                else:
                    now = utc_now()
                    cursor = connection.execute(
                        """INSERT INTO merchants(canonical_name,normalized_name,default_category_id,merchant_type_id,created_at,updated_at)
                           VALUES (?,?,NULL,?,?,?)""",
                        (merchant_name, normalized_name, classification.get("merchantTypeId"), now, now),
                    )
                    classification["merchantId"] = int(cursor.lastrowid)
                    created_merchant_id = classification["merchantId"]
                preview["classification"] = classification
            mapping = (("merchantId", "merchant_id", "merchant_source"), ("categoryId", "category_id", "category_source"),
                       ("merchantTypeId", "merchant_type_id", "merchant_type_source"), ("transactionKind", "transaction_kind", "kind_source"))
            for transaction_id in preview["targetIds"]:
                row = by_id[transaction_id]
                fields = {}; before = {"id": transaction_id}; after = {"id": transaction_id}
                for api_key, column, source_column in mapping:
                    if api_key in classification and row[column] is None:
                        fields[column] = classification[api_key]
                        before[column] = row[column]; before[source_column] = row[source_column]
                        after[column] = classification[api_key]; after[source_column] = "manual"
                if (classification.get("categoryId") is not None and row["taxonomy_review_required"]
                        and row["category_id"] == classification["categoryId"]):
                    fields["taxonomy_review_required"] = 0
                    before["taxonomy_review_required"] = row["taxonomy_review_required"]
                    after["taxonomy_review_required"] = 0
                if not fields: continue
                assignments = [] ; parameters = []
                for api_key, column, source_column in mapping:
                    if column in fields:
                        assignments.extend((f"{column}=?", f"{source_column}='manual'")); parameters.append(fields[column])
                if "category_id" in fields:
                    assignments.append("taxonomy_review_required=0")
                    before["taxonomy_review_required"] = row["taxonomy_review_required"]
                    after["taxonomy_review_required"] = 0
                elif "taxonomy_review_required" in fields:
                    assignments.append("taxonomy_review_required=0")
                assignments.append("updated_at=?"); parameters.extend((utc_now(), transaction_id))
                connection.execute(f"UPDATE transactions SET {', '.join(assignments)} WHERE id=?", parameters)
                previous.append(before); applied.append(after)
            mechanism = None; entity_id = None
            remember_metadata: dict[str, Any] = {
                "aliasesCreated": [], "merchantDefaultCreated": False,
                "merchantCreatedId": created_merchant_id,
            }
            if payload.get("remember"):
                merchant_id = classification.get("merchantId") or next((row["merchant_id"] for row in group_rows if row["merchant_id"]), None)
                if merchant_id and classification.get("categoryId"):
                    current = connection.execute("SELECT default_category_id FROM merchants WHERE id=?", (merchant_id,)).fetchone()
                    if current and current["default_category_id"] in (None, classification["categoryId"]):
                        changed_default = connection.execute("UPDATE merchants SET default_category_id=?,updated_at=? WHERE id=? AND default_category_id IS NULL", (classification["categoryId"], utc_now(), merchant_id)).rowcount == 1
                        mechanism = "merchant_default" if changed_default else "merchant_default_existing"
                        entity_id = int(merchant_id)
                        remember_metadata.update({"merchantDefaultCreated": changed_default, "merchantId": int(merchant_id), "categoryId": classification["categoryId"]})
                if classification.get("merchantId"):
                    for raw in {row["raw_description"] for row in group_rows}:
                        alias = normalize_entity_name(raw)
                        try:
                            inserted = connection.execute("INSERT OR IGNORE INTO merchant_aliases(merchant_id,normalized_alias,source,created_at,updated_at) VALUES (?,?, 'manual',?,?)", (classification["merchantId"], alias, utc_now(), utc_now())).rowcount == 1
                            if inserted:
                                remember_metadata["aliasesCreated"].append(alias)
                        except sqlite3.IntegrityError:
                            pass
                if mechanism is None and classification.get("categoryId") and len({row["raw_description"] for row in group_rows}) == 1:
                    raw = group_rows[0]["raw_description"]
                    cursor = connection.execute("INSERT INTO classification_rules(name,priority,enabled,stop_processing,created_at,updated_at) VALUES (?,?,?,?,?,?)", (f"Review: {raw[:60]}",100,1,0,utc_now(),utc_now()))
                    entity_id = int(cursor.lastrowid)
                    connection.execute("INSERT INTO rule_conditions(rule_id,field,operator,value_text,position) VALUES (?,?,?,?,0)", (entity_id,"raw_description","equals",raw))
                    connection.execute("INSERT INTO rule_actions(rule_id,field,value_id,position) VALUES (?,?,?,0)", (entity_id,"category",classification["categoryId"]))
                    mechanism = "exact_description_rule"
            connection.execute(
                """INSERT INTO review_bulk_actions(id,group_id,scope,transaction_count,fields_json,previous_json,applied_json,
                   remember_mechanism,remember_entity_id,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (action_id, group_id, preview["scope"], len(applied), json.dumps({
                    "changes": preview["changes"], "remember": remember_metadata,
                    "origin": "guided_review" if payload.get("origin") == "guided_review" else "review",
                    "targetTransactionId": preview.get("targetTransactionId"),
                }, sort_keys=True),
                 json.dumps(previous, ensure_ascii=False), json.dumps(applied, ensure_ascii=False), mechanism, entity_id, utc_now()),
            )
        return {**preview, "actionId": action_id, "applied": len(applied), "rememberMechanism": mechanism, "undoAvailable": True}

    def undo_latest(self) -> dict[str, Any]:
        with self.repository.transaction() as connection:
            action = connection.execute("SELECT * FROM review_bulk_actions WHERE undone_at IS NULL ORDER BY created_at DESC LIMIT 1").fetchone()
            if not action:
                raise FinanceNotFoundError("There is no Review bulk action to undo.")
            previous = json.loads(action["previous_json"]); applied = {item["id"]: item for item in json.loads(action["applied_json"])}
            audit_fields = json.loads(action["fields_json"])
            remember = audit_fields.get("remember", {}) if isinstance(audit_fields, dict) else {}
            restored = 0
            for before in previous:
                current = connection.execute("SELECT * FROM transactions WHERE id=?", (before["id"],)).fetchone()
                expected = applied[before["id"]]
                changed_columns = [key for key in before if key != "id"]
                if any(current[key] != expected.get(key) for key in changed_columns):
                    continue
                connection.execute(f"UPDATE transactions SET {', '.join(f'{key}=?' for key in changed_columns)},updated_at=? WHERE id=?", (*[before[key] for key in changed_columns], utc_now(), before["id"]))
                restored += 1
            if action["remember_mechanism"] == "exact_description_rule" and action["remember_entity_id"]:
                connection.execute("DELETE FROM classification_rules WHERE id=?", (action["remember_entity_id"],))
            if remember.get("merchantDefaultCreated") and remember.get("merchantId"):
                connection.execute(
                    "UPDATE merchants SET default_category_id=NULL,updated_at=? WHERE id=? AND default_category_id=?",
                    (utc_now(), remember["merchantId"], remember.get("categoryId")),
                )
            for alias in remember.get("aliasesCreated") or []:
                connection.execute(
                    "DELETE FROM merchant_aliases WHERE normalized_alias=? AND merchant_id=? AND source='manual'",
                    (alias, remember.get("merchantId")),
                )
            if remember.get("merchantCreatedId"):
                connection.execute(
                    "DELETE FROM merchants WHERE id=? AND NOT EXISTS (SELECT 1 FROM transactions WHERE merchant_id=?)",
                    (remember["merchantCreatedId"], remember["merchantCreatedId"]),
                )
            connection.execute("UPDATE review_bulk_actions SET undone_at=? WHERE id=?", (utc_now(), action["id"]))
        return {"actionId": action["id"], "restored": restored, "transactionCount": int(action["transaction_count"])}
