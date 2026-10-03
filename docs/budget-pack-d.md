# Finance Pack D — receipts, products, and Android Companion

## Scope and invariants

Pack D adds private receipt evidence and a local product dictionary to Finance. `data/finance.sqlite` remains canonical. Bank transactions remain the only cash-flow facts: importing or linking a receipt never inserts a transaction or changes its amount. A validated linked receipt may replace one broad transaction category with item-level composition in category analytics, but both representations are never counted together.

OpenFoodFacts, nutrition, pantry, diet, shopping-list automation, AI/LLM parsing, and investments are deliberately outside this pack.

## Receipt architecture and schema

Schema migration 9 adds:

- `receipts`, `receipt_sources`, `receipt_items`, and `receipt_adjustments`;
- `products`, `product_barcodes`, `product_categories`, and `retailer_product_aliases`;
- `retailer_profiles`, `receipt_item_bulk_actions`, and `finance_companion_devices`.

`finance_receipts.py` owns format detection, canonical parsing, validation, deterministic transaction matching, product resolution, review actions, item-split analytics, and device pairing. All input adapters produce one `ReceiptCandidate` shape. The browser and Android app both use this backend; Android does not implement a second parser.

Receipt originals are stored under ignored `data/finance-receipts/<receipt-id>/` using generated source names. SHA-256 source hashes provide exact re-import detection. The Python static server and Vite development/preview middleware return 404 for this directory. Source bytes and extracted/OCR text are not returned by the receipt APIs.

## Inputs, adapters, and source priority

Detection uses file signatures first, then declared MIME type and extension. Supported input types are JSON, PDF, JPEG, PNG, and WebP.

- Biedronka JSON: verified against the supplied private sample. The adapter reads the observed `protoVersion`/`header`/`body` structure, including sale lines, discounts, packages/deposits, totals, and fiscal footer. It does not invent fields.
- Biedronka PDF: the supplied PDF is image-only. It follows the PDF OCR fallback and remains reviewable when local OCR is unavailable.
- Żabka PDF: verified against the supplied private text-layer sample. Text is extracted directly; OCR is not used for a usable text layer. Item discounts and deposit adjustments reconcile the amount due.
- Żabka JSON: no verified sample was supplied. Unknown JSON, including an unverified Żabka wrapper, is rejected rather than silently accepted. A versioned `finance-receipt-*` JSON schema exists for controlled imports and synthetic tests.
- Paper/image/PDF OCR: the original Pack D runtime used local Tesseract only. Pack D.1 adds explicit availability diagnostics and Android ML Kit text evidence while keeping the backend parser canonical; see `budget-pack-d1.md`. No receipt is sent to a cloud service by the backend.

Canonical parsed fields use this priority:

1. structured JSON;
2. text-layer PDF;
3. local OCR image/PDF;
4. low-confidence or pending OCR.

The same fiscal identity can attach several sources to one receipt. Weaker sources never overwrite higher-priority canonical fields.

## Validation, duplication, and matching

Validation compares item line totals after item discounts plus receipt adjustments with the receipt total. A difference of at most one grosz is valid; adjustments produce `valid_with_adjustments`. Small non-zero differences become `needs_review`; larger differences become `invalid`. Raw evidence is retained for discounts, quantities, returns, deposits, and OCR interpretation.

Exact duplicates use the source hash. Cross-representation duplicates use a deterministic identity based on fiscal identifier, or on the best available receipt identifier/date/amount facts. A duplicate source never inserts a second item set.

The matcher considers exact amount, currency, purchase date proximity, and deterministic retailer evidence. Results are `exact`, `strong`, `ambiguous`, `none`, or `manual`. Automatic linking occurs only for a unique exact/strong candidate. Candidate cards expose date, merchant label, amount, and evidence—not account details. A transaction can have at most one linked canonical receipt.

## Products, aliases, and guided review

Products are a user-local dictionary. They retain canonical name, optional brand/barcode/package facts, status, and a broad product category. The initial taxonomy covers food (with useful subcategories), household chemicals, hygiene, cosmetics, alcohol, home, pets, and other. Product categories can map to existing Finance categories for split analytics.

Resolution order is retailer code, retailer exact alias, retailer normalized alias, then confirmed global barcode. Retailer aliases are isolated by retailer key. Confirming a repeated receipt item can create a canonical product, classify every currently unresolved occurrence in the group, and persist the retailer mapping for future imports.

Receipt-item classification uses the existing guided-review engine with the `receipt_item` domain and the same dialog shell. Bulk changes are preview-first, protect bank facts and previously resolved items, are audited in `receipt_item_bulk_actions`, and support safe latest-action undo.

## Split analytics, coverage, and price history

Item splitting is eligible only when the receipt is linked, validated, fully mapped to Finance categories, and both receipt total and item composition reconcile with the bank amount. Eligible transactions contribute item/adjustment buckets instead of the transaction category. Ineligible or incomplete receipts leave the transaction category unchanged.

Data Quality reports receipt imports, matches, receipts needing a match, parsed/classified items, unknown products, match/classification rates, and mixed-retailer spending covered or uncovered by validated receipts.

Product detail shows retailer aliases, purchase count, last purchase, last/effective price, minimum/maximum observed effective line price, and raw price history. Each observation keeps retailer, date, quantity, unit, unit price, line price, and discount-derived effective line price. The system does not normalize unlike packages or weighted quantities into misleading comparisons.

## API and privacy

The browser uses narrow routes under `/api/budget`, including receipts, matching, receipt-item review, product categories/details, and barcode lookup. Import payloads contain a safe filename, MIME type, and base64 bytes; no arbitrary server path is accepted.

Companion pairing, device listing, and revocation are localhost-only. Pairing returns a one-time bearer token; only its SHA-256 hash is stored. Remote receipt upload, receipt state, receipt-item actions, barcode lookup/pending save, and companion status require a valid non-revoked token. Tokens are never included in server logs. Regular local Finance behavior and same-origin protections remain intact.

## Android Dashboard Companion

`android/dashboard-companion/` is an independent Android Studio project following the existing repository convention. It has no hard-coded LAN address and stores its pairing token encrypted with Android Keystore AES/GCM.

The app provides:

- Google ML Kit document scanning with crop/rotation UI, gallery import, JPEG/PDF output, and up to eight pages;
- Android Open/Share handling for PDF, JSON, JPEG, PNG, and WebP content URIs;
- an app-private durable SQLite upload queue with `pending`, `uploading`, `uploaded`, and `failed` states, WorkManager network constraints, and retries;
- EAN-13, EAN-8, UPC-A, and UPC-E scanning through Google code scanner, local Dashboard lookup, known/unknown display, pending product save, and rescan;
- server-address and pairing-token configuration, connection state, queue history, manual retry, preview/share, and reset/revocation-compatible local state.

The scanner dependencies run on device. The app requests network access but no camera permission because the Google scanner UI owns capture. Pack D.1 retains ordered JPEG pages plus an optional archival PDF, stores optional ML Kit OCR evidence and a server result summary in the private queue, and never copies the Finance database.

## Extension points and remaining limitations

The adapter boundary can accept a verified Żabka JSON adapter without changing the canonical schema. OCR preprocessing is intentionally replaceable. Desktop reprocessing uses a locally installed Tesseract executable with Polish data; new Android scans can provide lower-priority ML Kit text evidence when Tesseract is absent. Image-only imports without either source remain safely stored for preview and later reprocessing.

`product_barcodes` and the local lookup route leave a clean future provider boundary for OpenFoodFacts, but Pack D performs no external lookup. Product quantity/unit and raw evidence are sufficient future inputs for pantry or diet features; neither workflow is implemented here.
