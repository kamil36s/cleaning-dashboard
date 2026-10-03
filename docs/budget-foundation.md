# Budget finance foundation

Budget runtime data lives in ignored `data/finance.sqlite` and is available to
the browser only through `/api/budget*`. The legacy `data/budget.json` remains
untouched as a migration source and has a byte-for-byte private backup under
`data/budget-backups/`.

The dependency direction is:

`finance_repository.py` → `finance_service.py` → `server.py` API → Budget UI

`finance_importer.py` is the only authoritative CSV parser and transaction
fingerprint implementation. The CLI and browser upload both call the same
service.

The parser accepts both mBank operation lists and full electronic account
statements. Full statements may obtain their own-account identity, currency,
account role, and closing balance from the preamble/footer instead of requiring
the operation-list `Rachunek` and `Kategoria` columns. A `CEL` statement creates
a separate `Cele` savings account excluded from Safe-to-spend. Its closing
balance is stored as an account snapshot; a financial goal linked to that
account reads this balance automatically. Schema version 7 adds private account
match aliases, so an official statement and an operation-list export can resolve
to one canonical account without storing the bank account number.

CLI imports can be bounded without editing the source export:

`python scripts/import_budget_csv.py statement.csv --from-date 2026-01-01`

Filtered rows are counted separately from invalid rows and are never inserted.
Bank categories and a small set of conservative description patterns map to
the canonical taxonomy with `imported_raw` provenance. Transfers to/from the
own `Cele` account are excluded from income and spending; outgoing automatic
round-ups on the spending account remain `saving` transactions.

Cross-format dedupe first uses the exact fingerprint and occurrence ordinal.
When mBank changes both wording and posting date between export types, a second
conservative match uses canonical account, signed amount, currency, banking
operation family, an unused occurrence in the current batch, and at most two
calendar days of date tolerance. Merchant hints are accepted only from
purchase/refund statement rows. Known chains receive a canonical merchant,
merchant type, and safe category; unknown purchase labels remain separate
merchants without a guessed category.

## Dedupe policy

The base identity is normalized account + transaction date + signed amount in
minor units + currency + normalized raw description. Bank category and balance
are excluded because exports can revise them. User annotations (`merchant`,
`merchantType`, `userCategory`, `note`) are also excluded and remain attached
to the immutable database transaction ID.

An occurrence ordinal is appended before hashing. This preserves two otherwise
identical payments from one export while making exact reimports and overlapping
exports idempotent. If a later export contains only one of multiple completely
identical same-day events, the bank data contains no stable discriminator; the
first ordinal is matched. This ambiguity is intentionally documented rather
than silently collapsing all same-amount transactions.

`transaction_imports` is a many-to-many provenance table. Rollback removes a
transaction only when the selected batch created it and no other completed
batch references it.

## Transitional compatibility

The API still emits the existing Budget page/widget JSON shape. Raw imported
facts and user annotations are separate columns in SQLite, but annotation
columns remain on `transactions` until a later classification-model pack.
Arbitrary browser replacement of the finance snapshot is disabled.
