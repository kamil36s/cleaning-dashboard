# Budget Pack C architecture

Pack C turns the canonical Pack A/B transaction and classification foundation
into a deterministic personal-finance product. It introduces no AI, cloud
finance sync, open-banking connection, or investment advice.

## Dependency direction and source of truth

`finance.sqlite` is the sole runtime source of truth for transactions,
classification, accounts, financial obligations, expected occurrences,
budgets, planned items, goals, and finance settings.

The two dashboard surfaces intentionally remain separate:

- the compact Finance widget answers “what is my overall position?”;
- the standalone Bills widget answers “what exactly must I pay or remember?”.

Both use `/api/budget/*`. `js/bills-store.js` retains the old schedule only as
an offline/migration fallback. After successful hydration it renders canonical
obligation occurrences and writes changes through Finance APIs.

## Schema version 4

Version 4 adds account roles and safe-to-spend inclusion plus these tables:

- `obligations` — confirmed recurring/one-off definitions;
- `obligation_occurrences` — expected-date overrides, payment state, and
  optional transaction matches;
- `planned_items` — non-bank future plans;
- `budgets` — overall/category monthly limits;
- `goals` — explicitly allocated financial goals.

Amounts remain integer minor units. Date indexes cover upcoming events,
planned items, month/category budgets, and active goals. Candidate recurring
activity is derived from canonical transactions and is never silently promoted
to a commitment.

## Legacy Bills migration

The one-shot migration key is `pack_c_legacy_bills_v1`. The migration combines
the former hard-coded definitions with `data/settings/bills.json`, including:

- bills, rent, services, installments, and subscriptions;
- custom one-off/monthly items;
- automatic/manual behavior;
- cancelled subscriptions;
- paid occurrence IDs;
- notification preference metadata.

Before insertion it creates byte-for-byte and expanded-definition backups in
`data/budget-backups/`. Inserts use stable `legacy_key` uniqueness and the
migration marker, so restarts cannot duplicate obligations. It verifies source
definition count and paid-state count in the same transaction. It never deletes
or rewrites `data/settings/bills.json`.

Production migration on 2026-09-17 verified 21 source definitions and all 13
paid occurrence flags. Both counts matched canonical storage.

## Obligation and recurrence semantics

An obligation has a kind (`bill`, `subscription`, `installment`, `rent`,
`service`, `saving`, `income`, or `salary`), amount/currency, optional account,
category and merchant, cadence, start/end and next expected dates,
automatic/manual flag, active/confirmed flags, installment totals/counts,
notes, notification metadata, and provenance.

Occurrence status is one of `expected`, `matched`, `paid`, `overdue`, `skipped`,
or `dismissed`. Expected events never create fake bank transactions.
Unconfirmed recurring candidates never enter safe-to-spend or forecast.

Recurring detection groups canonical transactions by merchant, kind, and
category. It requires at least three occurrences and a 60% interval-consistency
threshold in deterministic windows: weekly 5–9 days, monthly 25–35, quarterly
75–100, and annual 330–400. Evidence includes count, median interval, amount
range/variance, last occurrence, and likely next date.

Subscriptions expose monthly equivalent, annual cost, occurrence history, and
stored price changes. Installments retain totals and remaining amount/count.

## Budgets

Budgets are keyed by calendar month and optional category. A null category is
the overall spending budget. Category budgets include direct category and
subcategory spending. For each budget the service returns limit, spent,
remaining, used percentage, elapsed-month percentage, pace deviation in
percentage points, and projected month-end spend.

Projection is `spent / elapsed_fraction`; completed months use actual spend.
Status is numeric: over 100%, over elapsed pace by more than 10 points, or on
pace. Zero limits and zero spend do not divide by zero.

## Safe-to-spend and account roles

Account roles are `spending`, `savings`, and `excluded`. Only spending accounts
with `include_safe_to_spend=1` contribute their latest imported balance.
Savings-account money is not assumed to be spendable or allocated to a goal.

The exact formula is:

`liquid included balances`

`− unpaid confirmed outflow occurrences through the horizon`

`− included planned one-off expenses`

`− included planned savings commitments`

`− configured safety buffer`

`= safe to spend`

Safe daily spending is safe-to-spend divided by inclusive remaining days. The
supported horizons are end of month, a custom date, and next confirmed income.
If no confirmed future income exists, the response explicitly marks the next
income as unknown and uses month end for the calculation window.

## Planned items and goals

Planned items are plans, not transactions. They have date, positive magnitude,
expense/income/saving kind, optional account/category, note, status, and an
explicit safe-to-spend inclusion flag.

Goals store target, explicit current allocation, optional target date and
linked account, planned monthly contribution, primary status, and completion
state. Calculations return remaining amount, progress, required monthly
contribution, and estimated completion. `emergency_fund` is a first-class goal
kind; no default target is hard-coded. Essential-expense month coverage is not
computed until the user configures an essential-category set.

## Forecast and what-if assumptions

Forecasts are chronological event streams from current liquid balance through
confirmed obligation/income occurrences and planned items. Supported horizons
are 7, 30, and 90 days plus end of month. Paid, matched, skipped, and dismissed
events are excluded. Candidate recurring patterns are excluded.

What-if requests are non-persistent. They can adjust immediate spending,
subscriptions/rent, income timing, and monthly goal contributions, returning
changed safe-to-spend, month-end balance, and goal completion dates.

## Reports, history, and insights

Monthly reports calculate salary, other income, refunds, expenses, savings,
transfers, net cash flow, savings rate, category/merchant leaders, largest
transactions, recurring/subscription cost, budgets, goals, and previous-month
comparisons. Backend trends support 3M/6M/12M/all totals plus category,
merchant, and recurring-cost series.

Insights are deterministic records containing a code, reason, numbers, period,
severity, and drill-down target. Current rules cover budget pace, upcoming
confirmed obligations, classification coverage, and primary-goal progress.
They do not claim to be professional financial or investment advice.

## UI information architecture

The Finance application navigation is: Overview, Transactions, Review,
Budgets, Recurring, Goals, Reports, and Settings. Overview contains position
KPIs, upcoming events, budgets, goals, trends, and deterministic attention
cards. Transactions use backend pagination. Dictionaries, account roles,
rules, import history, and data quality live in Settings/Review rather than the
Overview.

CSV import remains explicit but secondary. Filtered CSV export omits raw
account identifiers and internal provenance by default and prefixes values
that could trigger spreadsheet formulas.

## Privacy and recovery

The Python static server and Vite deny direct access to `finance.sqlite`, its
sidecars, finance backups/imports, the legacy budget source, and
`data/settings/bills.json`. Finance errors do not include raw transaction rows.
Import rollback retains Pack A provenance safeguards. Rule deletion requires an
explicit confirmation query.

## Future Investments extension

Investments are not implemented. A future section can add instrument,
holding/lot, trade, valuation, and contribution tables linked to the existing
accounts without overloading bank transactions or financial obligations.
Brokerage connectivity, security recommendations, and automatic investing
remain out of scope.
