"""Print a privacy-safe readiness check for local receipt OCR."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from finance_receipts import LocalTesseractOcr  # noqa: E402


def main() -> int:
    health = LocalTesseractOcr().health()
    public = {key: value for key, value in health.items() if key != "command"}
    print(json.dumps(public, ensure_ascii=False, indent=2))
    if public.get("available") and public.get("polishAvailable"):
        print("Receipt OCR is ready for Polish receipts.")
        return 0
    print("Receipt OCR is not ready. See docs/receipt-ocr-windows.md.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
