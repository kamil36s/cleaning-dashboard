# Budget Pack C.6 review intelligence

Review uses three explicit units: a transaction is one immutable bank row, an
issue is one unresolved classification field, and a review group is a
deterministic set that one decision can safely address. The normal UI and its
navigation badge use groups and affected transactions; issue counts remain
diagnostic details.

The navigation badge always means open review groups in the complete history.
The Review header labels that scope explicitly. The page toggle switches the
cards between the selected calendar month and all history without changing the
badge's meaning.

## Category requirement

Only semantic expenses require a consumption category. Transfer, saving,
salary, income, refund, cash, and other operations may remain uncategorized.
Review derives semantic kind conservatively from exact bank-operation rails as
well as the stored kind. This prevents historical incoming/outgoing transfers,
P2P transfers, goal movements, cash operations, salary, and refunds from
creating artificial category work. It does not rewrite their stored history.

The primary category-quality percentage is:

`categorized semantic expenses / all semantic expenses`

Raw all-transaction category coverage remains available as a clearly labelled
diagnostic figure.

## Grouping and evidence

Grouping never uses amount. It prefers canonical merchant, then an exact known
alias, then a stable normalized description plus banking-operation family and
kind. Known mBank card/BLIK boilerplate is removed from the grouping text while
the raw description remains unchanged. An unambiguous historical merchant for
that normalized text may connect unresolved rows to the canonical merchant.
Different transfer/person descriptions remain distinct.

Evidence uses the full history and returns literal category, merchant,
merchant-type, and kind distributions. `exact` means exact alias/default,
exact bank semantics, or at least three fully consistent historical examples.
`strong` requires at least three observations and an 80% or greater dominant
literal ratio. `mixed` exposes disagreement. `unknown` has insufficient usable
evidence. Quick Clean includes only exact/strong groups whose suggestions cover
every open field.

Mixed retailers retain `Zakupy codzienne → Zakupy mieszane`; bank data alone
never produces a product-specific category.

## Applying and remembering

Every group action is preview-first. It reports affected transactions and
fields, confirms that manual values and amounts are untouched, and requires an
explicit confirmation. Application fills null fields only. The selected scope
also defines the write scope.

“Zastosuj + zapamiętaj na przyszłość” chooses the smallest safe mechanism:

- when a canonical merchant is known, it adds exact aliases as needed and uses
  a merchant default category (only when no conflicting default exists);
- without a resolvable merchant, a future rule is created only when the group
  has one exact raw description.

Each bulk action stores its timestamp, scope, affected rows, prior values,
applied values, and remembered mechanism in `review_bulk_actions`. Undo restores
only fields that still equal the applied values, preserving later manual edits.
