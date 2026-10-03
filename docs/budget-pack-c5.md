# Budget Pack C.5 product policy

Pack C.5 keeps `finance.sqlite` as the sole runtime source of truth. The later
additive schema version 6 stores account balance snapshots and import date-filter
counts. Version 7 adds cross-format account aliases, source-format provenance,
and derived merchant hints for official bank statements. It does not add receipts, OCR, product data, AI, mobile
scanning, or investments.

## Canonical categories

Personal categories use at most two levels. Transaction kind remains a separate
classification field: salary, transfer, refund, saving, and cash are kinds, not
substitutes for spending categories. Historical names remain in
`transactions.legacy_category_name`; `category_migration_audit` records every
legacy-to-canonical mapping, its ambiguity state, count, and application time.
Ambiguous mappings use `Inne / Do ustalenia` and set
`taxonomy_review_required`, so they appear in Review rather than being guessed.

## Mixed-retailer policy

A bank description does not reveal the contents of a basket. Biedronka, Żabka,
Lidl, Carrefour, Auchan, Lewiatan, Kaufland, Aldi, Netto, and comparable mixed
retailers therefore use `Zakupy codzienne / Zakupy mieszane`. They must not be
classified as food, household chemicals, alcohol, or personal care without
receipt/item evidence. Pack D may later add product-level evidence, but must not
rewrite this bank-transaction policy implicitly.

## Classification bootstrap

Historical data creates a merchant default only when one merchant has at least
three transactions and its category, transaction kind, and available merchant
type are fully consistent. Anything else remains a recommendation requiring
review. `classification_bootstrap_audit` stores counts, the decision, and a
human-readable reason. Exact aliases, normalized-description history, merchant
defaults, and stable merchant patterns feed Review suggestions; no probability
or AI score is produced.

## Account privacy

The CSV own-account field exists only while parsing an import. A 32-byte local
secret stored outside the database produces an HMAC-SHA256 matching key. The
account entity receives an unrelated local `acct_*` identifier. The raw value is
not stored in accounts, transactions, API payloads, exports, browser storage, or
labels. Existing relationships are preserved by `account_id`; a private SQLite
backup is created before the destructive privacy migration.

## Paid-ahead obligations

An occurrence keeps its contractual `expected_date`. Marking it paid changes
only its canonical status and records `paid_at`; undoing payment clears
`paid_at`. Paid and matched occurrences remain available when completed items
are requested, but are excluded from unpaid upcoming totals, Safe-to-spend, and
forecast events. Automatic obligations do not become paid merely because their
date passed.
