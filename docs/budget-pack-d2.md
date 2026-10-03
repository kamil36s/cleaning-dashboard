# Finance Pack D.2 — receipt intelligence

Pack D.2 adds deterministic Polish fiscal-receipt intelligence without changing the Finance cash-flow model. Bank transactions remain the only cash-flow facts; receipts remain private evidence and item composition.

Android ML Kit now sends flat text plus page dimensions, line/block order, normalized line and element boxes, and page numbers. The durable queue preserves this JSON until upload. Android does not infer merchant, total, date, or products. The canonical backend validates and stores the geometry in `receipt_sources.ocr_structure_json`.

`finance_receipt_parser.py` is the reusable normalization and grammar layer. It preserves raw OCR, records context-supported token corrections, recognizes Polish fiscal anchors, assigns header/items/tax/total/payment/footer zones, extracts date/total/item candidates, handles VAT suffixes, multiline names, quantities, deposits and discounts, and uses deterministic reconciliation. Parsed fields expose exact/strong/weak/manual/unknown evidence and compact diagnostics; uncertain fields remain reviewable.

Manual and guided receipt corrections are audited. Repeated, consistent merchant-header corrections may add a non-executable header alias to `retailer_profiles`; one ambiguous correction never creates a broad rule. Confirmed product corrections continue to use retailer-specific aliases.

The shared guided-review engine now supports `receipt_parse` as well as `receipt_item`. Receipt repair presents deterministic total/date/item candidates. Product review is restricted to credible product-line evidence and shows retailer, price, source line, and—when geometry exists—a same-origin item crop. Crop coordinates come only from stored OCR evidence.

Receipt detail is a responsive two-column desktop view with source controls for fit width, fit page, zoom, and a larger preview. Finance date controls and displays use `DD/MM/YYYY`; API and database values remain ISO dates.

Production reprocessing is selective: only sources with usable Android OCR evidence are rerun. Manual metadata, manual links, receipt IDs, source hashes, product aliases, and bank facts are preserved. Image-only legacy PDFs remain in their explicit OCR-unavailable state until local OCR becomes available.
