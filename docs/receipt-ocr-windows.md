# Receipt OCR on Windows

Finance keeps every receipt source even when OCR is unavailable. Android scans can supply ML Kit text evidence, but installing local Tesseract lets the desktop reprocess image-only PDFs and images independently.

1. Install a trusted Windows build of Tesseract. Do not run installers supplied by this project; it does not download or execute third-party installers.
2. Include Polish language data (`pol.traineddata`). English data is optional but useful for mixed receipt text.
3. Put `tesseract.exe` on `PATH`, or set `TESSERACT_CMD` to its full path. The runtime also checks the usual `Program Files\Tesseract-OCR` and per-user `Programs\Tesseract-OCR` locations.
4. From the repository root, run:

   ```powershell
   python scripts\check_receipt_ocr.py
   ```

   A ready installation reports both `available: true` and `polishAvailable: true`. The check never reads receipt files.
5. Restart `start-dev.cmd` so the server receives any new environment variable.
6. Open Finance → Receipts or Finance → Settings. “Receipt processing” shows Tesseract, Polish OCR, PDF extraction, Android evidence support, and private-storage health.
7. Use “Ponów wymagające OCR” or “Przetwórz ponownie” on an individual receipt.

The diagnostics distinguish a missing executable, missing Polish data, execution failure, and OCR with no useful text. Originals remain private under `data/finance-receipts`; they are served only through the same-origin preview route.
