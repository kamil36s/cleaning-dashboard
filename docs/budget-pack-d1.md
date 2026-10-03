# Finance Pack D.1 — receipt runtime repair

Pack D.1 repairs image-only receipt ingestion without changing the rule that bank transactions are the only cash-flow facts.

Android document scans now keep ordered JPEG pages as the OCR representation and retain the scanner PDF as an archive. Bundled ML Kit Text Recognition may attach on-device text evidence; the Android app does not parse receipt semantics. The backend remains the only merchant, date, total, item, product, validation, and transaction-matching parser.

The backend records explicit processing states and privacy-safe diagnostics. Local Tesseract discovery supports `TESSERACT_CMD`, `PATH`, and common Windows locations, and checks for Polish language data. See [receipt-ocr-windows.md](receipt-ocr-windows.md) for setup and the readiness command.

Reprocessing reuses stored sources and preserves receipt IDs, hashes, source files, manual metadata, guided/manual item decisions, and manual transaction links. A failed retry updates diagnostics without erasing previously parsed facts. Reprocessing never inserts or changes a bank transaction.

Receipt originals remain outside static serving. The Finance browser uses a receipt/source-scoped same-origin route with integrity verification, no-store caching, content sniffing disabled, and sandboxed PDF rendering. Companion bearer tokens do not grant preview access.

The receipt list and detail view use human status labels, retain unknown totals as unknown, support source preview, retry, minimal manual metadata, deterministic candidates, and arbitrary recent-transaction search. Processing health reports desktop OCR, Polish data, PDF extraction, Android evidence support, and private receipt storage.
