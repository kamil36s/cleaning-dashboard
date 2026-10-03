"""Central period semantics and SQLite-backed deterministic finance analytics."""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta, timezone
from typing import Any

from finance_repository import FinanceRepository


def _parse_date(value: str | date | None, fallback: date | None = None) -> date:
    if isinstance(value, date):
        return value
    if value:
        return date.fromisoformat(str(value)[:10])
    if fallback:
        return fallback
    return datetime.now(timezone.utc).date()


def _month_bounds(value: date) -> tuple[date, date]:
    return value.replace(day=1), value.replace(day=calendar.monthrange(value.year, value.month)[1])


def _shift_month(value: date, offset: int) -> date:
    month_index = value.year * 12 + value.month - 1 + offset
    return date(month_index // 12, month_index % 12 + 1, 1)


class FinancePeriodService:
    def __init__(self, repository: FinanceRepository):
        self.repository = repository

    def latest_transaction_date(self) -> str | None:
        return self.repository.summary()["date_to"]

    def resolve(
        self,
        period: str = "current_month",
        *,
        reference_date: str | date | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        year: int | None = None,
    ) -> dict[str, Any]:
        today = _parse_date(reference_date)
        latest_text = self.latest_transaction_date()
        latest = _parse_date(latest_text, today) if latest_text else today
        comparison_kind = "previous_equivalent"
        if period == "current_month":
            start, end = _month_bounds(today)
            previous_start = _shift_month(start, -1)
            previous_end = _month_bounds(previous_start)[1]
        elif period == "latest_data_month":
            start, end = _month_bounds(latest)
            previous_start = _shift_month(start, -1)
            previous_end = _month_bounds(previous_start)[1]
        elif period == "previous_calendar_month":
            start = _shift_month(today.replace(day=1), -1)
            start, end = _month_bounds(start)
            previous_start = _shift_month(start, -1)
            previous_end = _month_bounds(previous_start)[1]
        elif period == "previous_data_month":
            start = _shift_month(latest.replace(day=1), -1)
            start, end = _month_bounds(start)
            previous_start = _shift_month(start, -1)
            previous_end = _month_bounds(previous_start)[1]
        elif period in {"rolling_7", "rolling_30", "rolling_90"}:
            days = int(period.split("_")[1])
            end = today
            start = end - timedelta(days=days - 1)
            previous_end = start - timedelta(days=1)
            previous_start = previous_end - timedelta(days=days - 1)
        elif period == "calendar_year":
            selected_year = int(year or today.year)
            start, end = date(selected_year, 1, 1), date(selected_year, 12, 31)
            previous_start, previous_end = date(selected_year - 1, 1, 1), date(selected_year - 1, 12, 31)
        elif period == "date_range":
            if not date_from or not date_to:
                raise ValueError("date_range requires date_from and date_to")
            start, end = _parse_date(date_from), _parse_date(date_to)
            if start > end:
                raise ValueError("date_from must not be after date_to")
            span = (end - start).days + 1
            previous_end = start - timedelta(days=1)
            previous_start = previous_end - timedelta(days=span - 1)
        else:
            raise ValueError("Unsupported finance period")
        return {
            "period": period,
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
            "comparison_period": {
                "kind": comparison_kind,
                "period_start": previous_start.isoformat(),
                "period_end": previous_end.isoformat(),
            },
            "latest_transaction_date": latest_text,
            "data_freshness": self.freshness(reference_date=today),
        }

    def freshness(self, *, reference_date: str | date | None = None) -> dict[str, Any]:
        latest_text = self.latest_transaction_date()
        if not latest_text:
            return {"latest_transaction_date": None, "age_days": None, "status": "empty"}
        age = (_parse_date(reference_date) - _parse_date(latest_text)).days
        return {
            "latest_transaction_date": latest_text,
            "age_days": max(0, age),
            "status": "current" if age <= 1 else "stale",
        }


class FinanceAnalyticsService:
    """Metrics use transaction kind, never amount sign as semantic identity.

    Expenses are negative `expense` transactions. Total income is salary plus
    other `income` and excludes refunds/transfers. Net cash flow is total income
    + refunds - expenses - savings. Savings rate is savings / total income.
    """

    def __init__(self, repository: FinanceRepository):
        self.repository = repository
        self.periods = FinancePeriodService(repository)

    @staticmethod
    def _range(period: dict[str, Any]) -> tuple[str, str]:
        return str(period["period_start"]), str(period["period_end"])

    def get_period_summary(self, period: dict[str, Any]) -> dict[str, Any]:
        start, end = self._range(period)
        with self.repository.read_connection() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS transaction_count,
                  COALESCE(SUM(CASE WHEN transaction_kind='expense' AND amount_minor<0 THEN -amount_minor END),0) expenses,
                  COALESCE(SUM(CASE WHEN transaction_kind='salary' AND amount_minor>0 THEN amount_minor END),0) salary,
                  COALESCE(SUM(CASE WHEN transaction_kind='income' AND amount_minor>0 THEN amount_minor END),0) other_income,
                  COALESCE(SUM(CASE WHEN transaction_kind='saving' THEN ABS(amount_minor) END),0) savings,
                  COALESCE(SUM(CASE WHEN transaction_kind='refund' AND amount_minor>0 THEN amount_minor END),0) refunds,
                  COALESCE(SUM(CASE WHEN transaction_kind='transfer' THEN ABS(amount_minor) END),0) transfers
                FROM transactions WHERE transaction_date BETWEEN ? AND ?
                """,
                (start, end),
            ).fetchone()
        values = {key: int(row[key]) for key in row.keys() if key != "transaction_count"}
        total_income = values["salary"] + values["other_income"]
        net_cash_flow = total_income + values["refunds"] - values["expenses"] - values["savings"]
        days = (_parse_date(end) - _parse_date(start)).days + 1
        return {
            "periodStart": start,
            "periodEnd": end,
            "transactionCount": int(row["transaction_count"]),
            "expenses": values["expenses"] / 100,
            "salary": values["salary"] / 100,
            "otherIncome": values["other_income"] / 100,
            "totalIncome": total_income / 100,
            "savings": values["savings"] / 100,
            "refunds": values["refunds"] / 100,
            "transfers": values["transfers"] / 100,
            "netCashFlow": net_cash_flow / 100,
            "savingsRate": None if total_income == 0 else values["savings"] * 100 / total_income,
            "dailyAverage": values["expenses"] / 100 / days,
        }

    def _breakdown(self, period: dict[str, Any], dimension: str, kinds: tuple[str, ...]) -> list[dict[str, Any]]:
        start, end = self._range(period)
        if dimension == "category":
            select = "c.id AS id, c.name AS name, pc.id AS parent_id, pc.name AS parent_name"
            joins = "LEFT JOIN categories c ON c.id=t.category_id LEFT JOIN categories pc ON pc.id=c.parent_id"
            group = "c.id, c.name, pc.id, pc.name"
        else:
            select = "m.id AS id, m.canonical_name AS name, NULL AS parent_id, NULL AS parent_name"
            joins = "LEFT JOIN merchants m ON m.id=t.merchant_id"
            group = "m.id, m.canonical_name"
        placeholders = ",".join("?" for _ in kinds)
        with self.repository.read_connection() as connection:
            rows = connection.execute(
                f"""
                SELECT {select}, SUM(ABS(t.amount_minor)) AS amount_minor, COUNT(*) AS transaction_count
                FROM transactions t {joins}
                WHERE t.transaction_date BETWEEN ? AND ? AND t.transaction_kind IN ({placeholders})
                GROUP BY {group} ORDER BY amount_minor DESC, name
                """,
                (start, end, *kinds),
            ).fetchall()
        return [{
            "id": row["id"], "name": row["name"] or "Unclassified",
            "parentId": row["parent_id"], "parentName": row["parent_name"],
            "amount": int(row["amount_minor"]) / 100, "transactionCount": int(row["transaction_count"]),
        } for row in rows]

    def get_category_breakdown(self, period: dict[str, Any]) -> list[dict[str, Any]]:
        return self._breakdown(period, "category", ("expense",))

    def get_merchant_breakdown(self, period: dict[str, Any]) -> list[dict[str, Any]]:
        return self._breakdown(period, "merchant", ("expense",))

    def get_income_breakdown(self, period: dict[str, Any]) -> list[dict[str, Any]]:
        return self._breakdown(period, "merchant", ("salary", "income"))

    def get_cash_flow(self, period: dict[str, Any]) -> list[dict[str, Any]]:
        start, end = self._range(period)
        with self.repository.read_connection() as connection:
            rows = connection.execute(
                """
                SELECT transaction_date,
                  SUM(CASE WHEN transaction_kind IN ('salary','income') AND amount_minor>0 THEN amount_minor ELSE 0 END) AS income,
                  SUM(CASE WHEN transaction_kind='refund' AND amount_minor>0 THEN amount_minor ELSE 0 END) AS refunds,
                  SUM(CASE WHEN transaction_kind='expense' AND amount_minor<0 THEN -amount_minor ELSE 0 END) AS expenses,
                  SUM(CASE WHEN transaction_kind='saving' THEN ABS(amount_minor) ELSE 0 END) AS savings
                FROM transactions WHERE transaction_date BETWEEN ? AND ?
                GROUP BY transaction_date ORDER BY transaction_date
                """,
                (start, end),
            ).fetchall()
        return [{
            "date": row["transaction_date"], "income": row["income"] / 100,
            "refunds": row["refunds"] / 100, "expenses": row["expenses"] / 100,
            "savings": row["savings"] / 100,
            "netCashFlow": (row["income"] + row["refunds"] - row["expenses"] - row["savings"]) / 100,
        } for row in rows]

    def get_savings_summary(self, period: dict[str, Any]) -> dict[str, Any]:
        summary = self.get_period_summary(period)
        return {key: summary[key] for key in ("periodStart", "periodEnd", "savings", "totalIncome", "savingsRate")}

    def get_daily_average(self, period: dict[str, Any]) -> float:
        return self.get_period_summary(period)["dailyAverage"]

    def compare_periods(self, period: dict[str, Any]) -> dict[str, Any]:
        current = self.get_period_summary(period)
        comparison = period["comparison_period"]
        previous = self.get_period_summary(comparison)
        metrics = {}
        for key in ("expenses", "salary", "otherIncome", "totalIncome", "savings", "refunds", "netCashFlow", "dailyAverage"):
            absolute = current[key] - previous[key]
            metrics[key] = {
                "current": current[key], "previous": previous[key], "absoluteChange": absolute,
                "percentageChange": None if previous[key] == 0 else absolute * 100 / abs(previous[key]),
            }
        return {"current": current, "previous": previous, "changes": metrics}

    def get_largest_transactions(self, period: dict[str, Any], limit: int = 10) -> list[dict[str, Any]]:
        start, end = self._range(period)
        with self.repository.read_connection() as connection:
            rows = connection.execute(
                """
                SELECT t.id, t.transaction_date, t.amount_minor, t.currency, t.transaction_kind,
                       m.canonical_name AS merchant, c.name AS category
                FROM transactions t LEFT JOIN merchants m ON m.id=t.merchant_id
                LEFT JOIN categories c ON c.id=t.category_id
                WHERE t.transaction_date BETWEEN ? AND ?
                ORDER BY ABS(t.amount_minor) DESC, t.transaction_date DESC, t.id LIMIT ?
                """,
                (start, end, max(1, min(100, int(limit)))),
            ).fetchall()
        return [{**dict(row), "amount": row["amount_minor"] / 100} for row in rows]

    def get_data_freshness(self, reference_date: str | date | None = None) -> dict[str, Any]:
        return self.periods.freshness(reference_date=reference_date)
