# Budget Pack C.7 guided classification

The Financial Akinator is a deterministic decision layer above Pack C.6 Review.
It does not write classifications directly. It produces canonical
`merchantId`, `categoryId`, `merchantTypeId`, and `transactionKind` proposals,
then uses the existing Review preview, fill-only application, memory, audit,
and undo operations.

## Guided model

`js/finance-guided-review.js` owns the reusable interview model. A session has
a domain, immutable input context, and an answer history. State is derived by
replaying answers, which makes Back and Restart safe and avoids stale branch
state. Questions contain normal-language choices and semantic effects; category
effects resolve against the runtime C.5 dictionary instead of defining a
second taxonomy.

Question selection checks reliable C.6 evidence first. Exact and strong,
complete suggestions receive a single confirmation. Mixed evidence falls back
to semantic questions. Known transaction kinds skip the root question. The
interview stops as soon as a safe canonical result exists, or immediately when
the user chooses an unknown/skip answer. Unknown answers never manufacture a
kind or category.

The module accepts a `domain` and external dictionaries. Pack D can add a
receipt-item question registry and context while retaining session replay,
navigation, result summaries, and the dialog shell.

## Application and audit

`FinanceReviewService.preview` accepts an optional `targetTransactionId` that
must belong to the selected Review group. This enables the guided dialog's
single-transaction scope without adding a second mutation path. Group and
remember scopes remain unchanged. All scopes protect existing values, never
change amounts, and are recorded in `review_bulk_actions`; guided actions add
`origin: guided_review` inside existing audit metadata. Existing C.6 undo is
authoritative.

Remembering still selects the smallest C.6 mechanism: merchant default and
exact aliases for a known merchant, otherwise a strict exact-description rule
when safe. The guided dialog only explains that behavior in plain language.

## Mascot

The decorative image hook is `assets/finance/financial-akinator.png`. The
dialog uses an empty alt value and `aria-hidden` container. A missing asset is
hidden cleanly and replaced by a compact text mark; no image is regenerated.

