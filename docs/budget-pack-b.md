# Budget Pack B architecture

## Canonical classification

`finance.sqlite` is canonical. Raw bank description, account, category, amount,
balance, currency, and date remain immutable import facts. Personal
classification uses normalized category, merchant, merchant-type, and
transaction-kind identifiers. The Pack A text columns remain as migration and
compatibility evidence; they are not the canonical relationship.

Categories and subcategories share the `categories` table. A subcategory has a
top-level `parent_id`; deeper nesting is rejected. Names are normalized by
trimming, collapsing whitespace, case folding, and removing diacritics for
duplicate detection.

Merchant type is a normalized entity. It normally belongs to a merchant as its
default. A transaction-level reference is retained as an explicit override so
historical Pack A annotations are preserved even when one merchant has more
than one historical type. Migration chooses the merchant's most frequent type
as its default, with the lower stable ID breaking ties.

## Precedence and provenance

Classification precedence is:

1. manual or migrated transaction assignment;
2. first matching rule action;
3. merchant default category/type;
4. deterministic imported bank category/operation mapping;
5. system fallback.

Merchant aliases are resolved before rules and are marked `imported_raw`.
Rules may replace that provisional merchant. Historical rule application does
not replace `manual` or `migrated` values unless `includeManual=true` is an
explicit request.

Each classified field stores its source and, for rule results, its rule ID.
`GET /api/budget/transactions/{id}/classification` exposes the explanation.

## Rules

Rules are ordered by ascending `priority`, then ascending stable rule ID. All
conditions in a rule must match. The first matching rule to assign a field wins
that field. If a later matching rule proposes a different value, it does not
override the winner and the transaction receives a reviewable `rule_conflict`.
`stop_processing` ends evaluation after that matching rule. Disabled rules are
not evaluated.

Rule preview uses the same classifier without persistence. Historical apply is
one `BEGIN IMMEDIATE` transaction, so any failure rolls back all changes.
`future_only` stores an enabled rule without rewriting history;
`existing_and_future` stores it and atomically applies it to matching existing
transactions.

## Review queue

Review issues are derived from current transaction state to avoid redundant,
stale rows: unknown merchant, ambiguous historical merchant mapping, missing
category, missing meaningful kind, and rule conflict. Only user decisions (`resolved` or `ignored`) are stored in
`review_decisions`. If a correction removes the underlying issue, it naturally
leaves the open queue. Corrections can optionally create a persistent rule.

## Periods

The backend period service defines current calendar month, latest month with
data, previous calendar month, previous data month, arbitrary date range,
rolling 7/30/90 days, and calendar year. Every resolved period includes an
equal preceding comparison period, latest transaction date, and freshness.
Current month is based on the requested/reference date; latest-data month is
based on the maximum transaction date and is never silently substituted for
current month.

## Metrics

All monetary formulas use integer minor units and canonical transaction kind:

- expenses: absolute negative amounts whose kind is `expense`;
- salary: positive amounts whose kind is `salary`;
- other income: positive amounts whose kind is `income`;
- total income: salary + other income (refunds excluded);
- savings: absolute amounts whose kind is `saving`;
- refunds: positive amounts whose kind is `refund`;
- transfers: absolute amounts whose kind is `transfer`, reported but excluded
  from spending and income;
- net cash flow: total income + refunds - expenses - savings;
- savings rate: savings / total income; `null` when total income is zero;
- daily average: expenses divided by inclusive days in the selected period.

Period percentage change is `(current - previous) / abs(previous) * 100` and is
`null` when the previous value is zero.
