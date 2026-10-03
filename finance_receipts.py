"""Private receipt, product, and companion-device domain for Finance Pack D.

Bank transactions remain the only cash-flow facts.  This module stores receipt
evidence and item composition without inserting or changing transactions.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import importlib.util
import json
import mimetypes
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import unicodedata
import uuid
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from finance_repository import FinanceError, FinanceNotFoundError, FinanceRepository, normalize_entity_name, utc_now
from finance_receipt_parser import parse_polish_receipt, sanitize_ocr_structure


PARSER_VERSION = "pack-d2-1"
MAX_RECEIPT_BYTES = 24 * 1024 * 1024
SOURCE_PRIORITIES = {
    "structured_json": 400,
    "text_pdf": 300,
    "server_ocr": 250,
    "android_ocr": 225,
    "ocr_image": 250,
    "ocr_low": 100,
}
ALLOWED_MIME_TYPES = {
    "application/json": "json",
    "text/json": "json",
    "text/plain": "json",
    "application/pdf": "pdf",
    "image/jpeg": "image",
    "image/png": "image",
    "image/webp": "image",
}
BARCODE_RE = re.compile(r"^(?:\d{8}|\d{12}|\d{13})$")


def _parsed_receipt_score(parsed: dict[str, Any], text_length: int = 0) -> float:
    diagnostics = parsed.get("diagnostics") or {}
    items = parsed.get("items") or []
    reconciliation = diagnostics.get("reconciliation") or {}
    return (
        35 * int(parsed.get("total_minor") is not None)
        + 30 * int(bool(parsed.get("purchase_date")))
        + 20 * min(len(items), 12)
        + 10 * int(bool(parsed.get("store_name")))
        + 4 * min(int(diagnostics.get("fiscalAnchors") or 0), 8)
        + 15 * int(reconciliation.get("state") == "exact")
        + min(text_length, 2000) / 200
    )


class ReceiptValidationError(FinanceError):
    pass


def _identifier(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _normalized(value: Any) -> str:
    text = " ".join(str(value or "").strip().split()).casefold()
    return "".join(
        character for character in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(character)
    )


def _safe_filename(value: Any) -> str:
    name = Path(str(value or "receipt")).name
    cleaned = re.sub(r"[^A-Za-z0-9._ -]+", "_", name).strip(" .")
    return (cleaned or "receipt")[:120]


def _decimal_text(value: Any, default: str = "1") -> str:
    text = str(value if value not in (None, "") else default).strip().replace(",", ".")
    try:
        parsed = Decimal(text)
    except InvalidOperation:
        return default
    return format(parsed.normalize(), "f")


def _minor(value: Any) -> int:
    if isinstance(value, int):
        return value
    try:
        return int((Decimal(str(value).replace(",", ".")) * 100).quantize(Decimal("1")))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ReceiptValidationError("Invalid receipt amount.") from exc


def _date_parts(value: Any) -> tuple[str | None, str | None]:
    text = str(value or "").strip()
    if not text:
        return None, None
    text = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
        return parsed.date().isoformat(), parsed.time().replace(microsecond=0, tzinfo=None).isoformat()
    except ValueError:
        pass
    for pattern in ("%Y-%m-%d", "%d.%m.%Y", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text[:10], pattern).date().isoformat(), None
        except ValueError:
            continue
    return None, None


def _retailer_key(value: Any) -> str:
    normalized = _normalized(value)
    for known in (
        "biedronka", "zabka", "lidl", "carrefour", "auchan", "kaufland", "aldi", "netto",
        "pepco", "reserved", "sinsay", "h&m", "c&a", "tk maxx",
    ):
        if known in normalized:
            return known
    return normalized[:120]


def _empty_candidate(source_type: str, source_format: str) -> dict[str, Any]:
    return {
        "recognized": False,
        "source_type": source_type,
        "source_format": source_format,
        "source_priority": SOURCE_PRIORITIES["ocr_low"],
        "retailer_key": "",
        "store_name": "",
        "purchase_date": None,
        "purchase_time": None,
        "total_minor": None,
        "currency": "PLN",
        "external_receipt_id": None,
        "fiscal_identifier": None,
        "store_location": None,
        "items": [],
        "adjustments": [],
        "extracted_text": None,
        "raw_ocr_text": None,
        "ocr_provenance": None,
        "processing_state": "source_received",
        "processing_code": None,
        "processing_message": None,
        "diagnostics": {},
        "field_evidence": {},
        "parse_review": {},
        "ocr_structure": {"pages": []},
    }


class LocalTesseractOcr:
    """Discover and run local Tesseract while returning explicit diagnostics."""

    @staticmethod
    def _receipt_text_score(text: str) -> float:
        """Rank OCR layouts by receipt facts, not by raw character count."""
        try:
            parsed = parse_polish_receipt(text, source_type="image", source_format="ocr_candidate")
        except (TypeError, ValueError):
            return min(len(text), 2000) / 200
        return _parsed_receipt_score(parsed, len(text))

    def _command_candidates(self) -> list[tuple[str, str]]:
        candidates: list[tuple[str, str]] = []
        configured = str(os.environ.get("TESSERACT_CMD") or "").strip().strip('"')
        if configured:
            candidates.append((configured, "environment"))
        path_command = shutil.which("tesseract")
        if path_command:
            candidates.append((path_command, "path"))
        if os.name == "nt":
            roots = [
                os.environ.get("ProgramFiles"),
                os.environ.get("ProgramFiles(x86)"),
                os.environ.get("LOCALAPPDATA"),
            ]
            for root in roots:
                if not root:
                    continue
                base = Path(root)
                paths = [base / "Tesseract-OCR" / "tesseract.exe"]
                if root == os.environ.get("LOCALAPPDATA"):
                    paths.append(base / "Programs" / "Tesseract-OCR" / "tesseract.exe")
                candidates.extend((str(path), "common_windows_location") for path in paths)
        unique: list[tuple[str, str]] = []
        seen: set[str] = set()
        for command, source in candidates:
            resolved = shutil.which(command) or (str(Path(command)) if Path(command).is_file() else None)
            if resolved and resolved.casefold() not in seen:
                seen.add(resolved.casefold())
                unique.append((resolved, source))
        return unique

    def health(self) -> dict[str, Any]:
        candidates = self._command_candidates()
        if not candidates:
            return {
                "available": False,
                "polishAvailable": False,
                "code": "tesseract_missing",
                "message": "Tesseract OCR is not installed or configured.",
                "commandSource": None,
                "languages": [],
            }
        command, source = candidates[0]
        try:
            result = subprocess.run(
                [command, "--list-langs"], capture_output=True, check=False, timeout=15,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return {
                "available": False,
                "polishAvailable": False,
                "code": "tesseract_unusable",
                "message": "Tesseract was found but could not be executed.",
                "commandSource": source,
                "languages": [],
                "errorType": type(exc).__name__,
            }
        output = (result.stdout + b"\n" + result.stderr).decode("utf-8", errors="replace")
        languages = sorted({line.strip() for line in output.splitlines() if re.fullmatch(r"[a-zA-Z_]+", line.strip())})
        polish = "pol" in languages
        if result.returncode != 0:
            return {
                "available": False,
                "polishAvailable": False,
                "code": "tesseract_unusable",
                "message": "Tesseract was found but language discovery failed.",
                "commandSource": source,
                "languages": languages,
                "exitCode": result.returncode,
            }
        return {
            "available": True,
            "polishAvailable": polish,
            "code": None if polish else "polish_language_missing",
            "message": None if polish else "Tesseract is available, but Polish language data is missing.",
            "commandSource": source,
            "languages": languages,
            "command": command,
        }

    def recognize(self, content: bytes) -> dict[str, Any]:
        health = self.health()
        public_health = {key: value for key, value in health.items() if key != "command"}
        if not health["available"]:
            return {"ok": False, "text": None, "state": "ocr_unavailable", **public_health}
        if not health["polishAvailable"]:
            return {"ok": False, "text": None, "state": "ocr_unavailable", **public_health}
        try:
            from PIL import Image, ImageOps
            from io import BytesIO
            image = ImageOps.exif_transpose(Image.open(BytesIO(content)))
            image = ImageOps.autocontrast(ImageOps.grayscale(image))
            with tempfile.TemporaryDirectory(prefix="finance-receipt-ocr-") as directory:
                source = Path(directory) / "receipt.png"
                image.save(source)
                languages = "pol+eng" if "eng" in health["languages"] else "pol"
                attempts = []
                for page_segmentation_mode in (4, 6):
                    result = subprocess.run(
                        [health["command"], str(source), "stdout", "-l", languages,
                         "--oem", "1", "--psm", str(page_segmentation_mode),
                         "-c", "preserve_interword_spaces=1"],
                        capture_output=True, check=False, timeout=90,
                    )
                    text = result.stdout.decode("utf-8", errors="replace").strip()
                    attempts.append({
                        "result": result, "text": text, "psm": page_segmentation_mode,
                        "score": self._receipt_text_score(text) if result.returncode == 0 else -1,
                    })
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            return {
                **public_health, "ok": False, "text": None, "state": "ocr_failed", "code": "ocr_execution_failed",
                "message": "Tesseract failed while processing the receipt image.",
                "errorType": type(exc).__name__,
            }
        successful = [attempt for attempt in attempts if attempt["result"].returncode == 0]
        if not successful:
            result = attempts[-1]["result"]
            return {
                **public_health, "ok": False, "text": None, "state": "ocr_failed", "code": "ocr_execution_failed",
                "message": "Tesseract returned an error while processing the receipt image.",
                "exitCode": result.returncode,
            }
        selected = max(successful, key=lambda attempt: (attempt["score"], len(attempt["text"])))
        text = selected["text"]
        useful_length = len(re.sub(r"\W", "", text, flags=re.UNICODE))
        if useful_length < 12:
            return {
                **public_health, "ok": False, "text": text or None, "state": "ocr_failed", "code": "ocr_empty",
                "message": "Tesseract ran but returned no useful receipt text.",
                "textLength": len(text),
            }
        return {
            **public_health, "ok": True, "text": text, "state": "parsed", "code": None, "message": None,
            "textLength": len(text), "provenance": "server_tesseract",
            "pageSegmentationMode": selected["psm"],
            "candidateScores": {str(attempt["psm"]): round(float(attempt["score"]), 2) for attempt in successful},
        }


class ReceiptImporter:
    """Format detection and adapters producing one canonical candidate shape."""

    def __init__(self, ocr_engine: Any | None = None):
        self.ocr_engine = ocr_engine or LocalTesseractOcr()

    def detect(self, filename: str, mime_type: str, content: bytes) -> tuple[str, str]:
        mime = str(mime_type or "").split(";", 1)[0].strip().lower()
        extension = Path(filename).suffix.lower()
        if content.startswith(b"%PDF-"):
            return "pdf", "pdf"
        if content[:12].startswith((b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n", b"RIFF")):
            return "image", extension.removeprefix(".") or "image"
        if mime in {"application/json", "text/json"} or extension in {".json", ".txt"}:
            return "json", "json"
        if mime in ALLOWED_MIME_TYPES:
            return ALLOWED_MIME_TYPES[mime], mime
        raise ReceiptValidationError("Unsupported receipt file type.")

    def parse(
        self, filename: str, mime_type: str, content: bytes,
        provided_ocr_text: str | None = None, ocr_provenance: str | None = None,
        provided_ocr_structure: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        source_type, detected = self.detect(filename, mime_type, content)
        if source_type == "json":
            return self._parse_json(content)
        if source_type == "pdf":
            return self._parse_pdf(content, provided_ocr_text, ocr_provenance, provided_ocr_structure)
        if source_type == "image":
            return self._parse_image(content, detected, provided_ocr_text, ocr_provenance, provided_ocr_structure)
        raise ReceiptValidationError("Unsupported receipt source.")

    def _parse_json(self, content: bytes) -> dict[str, Any]:
        try:
            payload = json.loads(content.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ReceiptValidationError("The JSON receipt is not valid UTF-8 JSON.") from exc
        if not isinstance(payload, dict):
            raise ReceiptValidationError("Unsupported JSON receipt schema.")
        body = payload.get("body")
        if payload.get("protoVersion") is not None and isinstance(body, list) and any("sellLine" in row for row in body if isinstance(row, dict)):
            return self._parse_biedronka_json(payload)
        root = payload.get("receipt") if isinstance(payload.get("receipt"), dict) else payload
        schema = str(payload.get("schemaVersion") or payload.get("schema_version") or root.get("schemaVersion") or "")
        if schema.startswith("finance-receipt-") and isinstance(root.get("items"), list):
            return self._parse_generic_json(root)
        if "zabka" in _normalized(json.dumps(list(payload.keys()), ensure_ascii=False)):
            raise ReceiptValidationError("Żabka JSON schema is not verified by the supplied sample.")
        raise ReceiptValidationError("Unsupported JSON receipt schema; the source was preserved only after a recognized adapter succeeds.")

    def _parse_biedronka_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        candidate = _empty_candidate("json", "biedronka_eparagon_json_v1")
        candidate.update({
            "recognized": True,
            "source_priority": SOURCE_PRIORITIES["structured_json"],
            "retailer_key": "biedronka",
            "store_name": "Biedronka",
            "processing_state": "parsed",
        })
        header_data: dict[str, Any] = {}
        header_text = ""
        for row in payload.get("header") or []:
            if not isinstance(row, dict):
                continue
            if isinstance(row.get("headerData"), dict):
                header_data = row["headerData"]
            if isinstance(row.get("headerText"), dict):
                header_text += " " + html.unescape(re.sub(r"<[^>]+>", " ", str(row["headerText"].get("headerTextLines") or "")))
        candidate["store_location"] = " ".join(header_text.split())[:500] or None
        candidate["purchase_date"], candidate["purchase_time"] = _date_parts(header_data.get("date"))
        current_item: dict[str, Any] | None = None
        for position, wrapper in enumerate(payload.get("body") or [], start=1):
            if not isinstance(wrapper, dict):
                continue
            if isinstance(wrapper.get("sellLine"), dict):
                line = wrapper["sellLine"]
                raw_name = str(line.get("name") or "").strip()
                amount = int(line.get("total") or 0)
                if bool(line.get("isStorno")) and amount > 0:
                    amount = -amount
                current_item = {
                    "line_number": position,
                    "raw_name": raw_name,
                    "interpreted_name": raw_name,
                    "raw_product_code": str(line.get("code") or line.get("sku") or "").strip() or None,
                    "barcode": str(line.get("barcode") or "").strip() or None,
                    "quantity": _decimal_text(line.get("quantity")),
                    "unit": str(line.get("unit") or "source_unit"),
                    "unit_price_minor": int(line["price"]) if line.get("price") is not None else None,
                    "total_price_minor": amount,
                    "discount_minor": 0,
                    "confidence_state": "exact",
                    "raw_evidence": {"vatId": line.get("vatId"), "isStorno": bool(line.get("isStorno"))},
                }
                candidate["items"].append(current_item)
            elif isinstance(wrapper.get("discountLine"), dict):
                discount = wrapper["discountLine"]
                value = abs(int(discount.get("value") or 0))
                if current_item is not None and bool(discount.get("isDiscount", True)):
                    current_item["discount_minor"] += value
                    current_item["raw_evidence"].setdefault("discounts", []).append(discount)
                else:
                    candidate["adjustments"].append({"line_number": position, "kind": "discount", "label": "Rabat", "amount_minor": -value, "raw_evidence": discount})
            elif isinstance(wrapper.get("pack"), dict):
                pack = wrapper["pack"]
                amount = int(pack.get("total") or 0)
                if bool(pack.get("isNegative")) and amount > 0:
                    amount = -amount
                candidate["adjustments"].append({"line_number": position, "kind": "deposit", "label": str(pack.get("name") or "Kaucja"), "amount_minor": amount, "raw_evidence": pack})
            elif isinstance(wrapper.get("sumInCurrency"), dict):
                total = wrapper["sumInCurrency"]
                candidate["total_minor"] = int(total.get("totalWithPacks") if total.get("totalWithPacks") is not None else total.get("fiscalTotal"))
                candidate["currency"] = str(total.get("currency") or "PLN")
            elif isinstance(wrapper.get("fiscalFooter"), dict):
                footer = wrapper["fiscalFooter"]
                candidate["external_receipt_id"] = str(footer.get("billNumber") or "").strip() or None
                candidate["fiscal_identifier"] = str(footer.get("uniqueNumber") or "").strip() or None
                parsed_date, parsed_time = _date_parts(footer.get("date"))
                candidate["purchase_date"] = parsed_date or candidate["purchase_date"]
                candidate["purchase_time"] = parsed_time or candidate["purchase_time"]
        if candidate["total_minor"] is None:
            raise ReceiptValidationError("Biedronka JSON does not contain a receipt total.")
        return candidate

    def _parse_generic_json(self, root: dict[str, Any]) -> dict[str, Any]:
        retailer = str(root.get("retailer") or root.get("storeName") or root.get("store_name") or "").strip()
        purchase_date, purchase_time = _date_parts(root.get("purchasedAt") or root.get("purchaseDate") or root.get("purchase_date"))
        candidate = _empty_candidate("json", "generic_polish_receipt_json_v1")
        candidate.update({
            "recognized": True,
            "source_priority": SOURCE_PRIORITIES["structured_json"],
            "retailer_key": _retailer_key(retailer),
            "store_name": retailer,
            "store_location": root.get("storeLocation") or root.get("store_location"),
            "purchase_date": purchase_date,
            "purchase_time": str(root.get("purchaseTime") or purchase_time or "") or None,
            "total_minor": int(root["totalMinor"]) if root.get("totalMinor") is not None else _minor(root.get("total")),
            "currency": str(root.get("currency") or "PLN"),
            "external_receipt_id": str(root.get("externalReceiptId") or "").strip() or None,
            "fiscal_identifier": str(root.get("fiscalIdentifier") or "").strip() or None,
            "processing_state": "parsed",
        })
        for index, line in enumerate(root.get("items") or [], start=1):
            if not isinstance(line, dict) or not str(line.get("name") or line.get("rawName") or "").strip():
                continue
            raw_name = str(line.get("rawName") or line.get("name")).strip()
            total = int(line["totalMinor"]) if line.get("totalMinor") is not None else _minor(line.get("total"))
            candidate["items"].append({
                "line_number": int(line.get("lineNumber") or index), "raw_name": raw_name,
                "interpreted_name": str(line.get("name") or raw_name),
                "raw_product_code": str(line.get("productCode") or "").strip() or None,
                "barcode": str(line.get("barcode") or "").strip() or None,
                "quantity": _decimal_text(line.get("quantity")), "unit": str(line.get("unit") or "szt"),
                "unit_price_minor": int(line["unitPriceMinor"]) if line.get("unitPriceMinor") is not None else None,
                "total_price_minor": total, "discount_minor": abs(int(line.get("discountMinor") or 0)),
                "confidence_state": str(line.get("confidence") or "exact"), "raw_evidence": line,
            })
        for index, adjustment in enumerate(root.get("adjustments") or [], start=1):
            if not isinstance(adjustment, dict):
                continue
            candidate["adjustments"].append({
                "line_number": int(adjustment.get("lineNumber") or (10000 + index)),
                "kind": str(adjustment.get("kind") or "other"),
                "label": str(adjustment.get("label") or ""),
                "amount_minor": int(adjustment.get("amountMinor") or 0),
                "raw_evidence": adjustment,
            })
        return candidate

    def _extract_pdf_text(self, content: bytes) -> tuple[str, int]:
        try:
            import pymupdf  # type: ignore
        except ImportError:
            try:
                import fitz as pymupdf  # type: ignore
            except ImportError:
                return "", 0
        document = pymupdf.open(stream=content, filetype="pdf")
        try:
            return "\n".join(page.get_text("text") for page in document), len(document)
        finally:
            document.close()

    def _candidate_from_ocr_text(
        self, text: str, source_type: str, source_format: str, priority: int, provenance: str,
        structure: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        useful = len(re.sub(r"\W", "", str(text or ""), flags=re.UNICODE))
        if useful < 12:
            candidate = _empty_candidate(source_type, source_format)
            candidate.update({
                "processing_state": "ocr_failed", "processing_code": "ocr_empty",
                "processing_message": "OCR returned no useful receipt text.",
                "ocr_provenance": provenance, "raw_ocr_text": text or None,
                "diagnostics": {"ocrTextLength": len(text or "")},
            })
            return candidate
        candidate = self._parse_receipt_text(
            text, source_type=source_type, source_format=source_format, ocr_structure=structure,
        )
        candidate["source_priority"] = priority
        candidate["raw_ocr_text"] = text
        candidate["ocr_provenance"] = provenance
        candidate["ocr_structure"] = sanitize_ocr_structure(structure)
        candidate["processing_state"] = "parsed" if candidate["recognized"] else "needs_review"
        candidate["processing_code"] = None if candidate["recognized"] else "ocr_parse_incomplete"
        candidate["processing_message"] = None if candidate["recognized"] else "OCR text was extracted, but receipt fields remain incomplete."
        candidate["diagnostics"].update({"ocrTextLength": len(text), "ocrProvenance": provenance})
        return candidate

    def _parse_pdf(
        self, content: bytes, provided_ocr_text: str | None = None, ocr_provenance: str | None = None,
        provided_ocr_structure: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        text, page_count = self._extract_pdf_text(content)
        useful = len(re.sub(r"\W", "", text, flags=re.UNICODE)) >= 80
        if useful:
            candidate = self._parse_receipt_text(text, source_type="pdf", source_format="polish_text_pdf_v1")
            candidate["source_priority"] = SOURCE_PRIORITIES["text_pdf"]
            candidate["extracted_text"] = text
            candidate["page_count"] = page_count
            candidate["processing_state"] = "parsed" if candidate["recognized"] else "needs_review"
            candidate["processing_code"] = None if candidate["recognized"] else "pdf_text_parse_incomplete"
            candidate["processing_message"] = None if candidate["recognized"] else "PDF text was extracted, but receipt fields remain incomplete."
            candidate["diagnostics"] = {"pdfPageCount": page_count, "pdfTextLength": len(text), "hasTextLayer": True}
            return candidate
        ocr = self._ocr_pdf(content)
        if ocr.get("ok"):
            candidate = self._candidate_from_ocr_text(
                str(ocr["text"]), "pdf", "pdf_tesseract_ocr_v2", SOURCE_PRIORITIES["server_ocr"], "server_tesseract",
            )
            candidate["page_count"] = page_count
            candidate["diagnostics"].update({"pdfPageCount": page_count, "hasTextLayer": False})
            return candidate
        if provided_ocr_text:
            candidate = self._candidate_from_ocr_text(
                provided_ocr_text, "pdf", "android_mlkit_ocr_v1", SOURCE_PRIORITIES["android_ocr"],
                ocr_provenance or "android_mlkit", provided_ocr_structure,
            )
            candidate["page_count"] = page_count
            candidate["diagnostics"].update({"pdfPageCount": page_count, "hasTextLayer": False, "serverOcrCode": ocr.get("code")})
            return candidate
        source_format = "pdf_ocr_unavailable" if ocr.get("state") == "ocr_unavailable" else "pdf_ocr_failed"
        candidate = _empty_candidate("pdf", source_format)
        candidate["page_count"] = page_count
        candidate["processing_state"] = ocr.get("state") or "ocr_required"
        candidate["processing_code"] = ocr.get("code") or "ocr_required"
        candidate["processing_message"] = ocr.get("message") or "This image-only PDF requires OCR."
        candidate["diagnostics"] = {
            "pdfPageCount": page_count, "pdfTextLength": len(text), "hasTextLayer": False,
            "ocrAttempted": bool(ocr.get("available") and ocr.get("polishAvailable")),
            "ocrTextLength": len(ocr.get("text") or ""), "ocrCode": ocr.get("code"),
        }
        return candidate

    def _parse_image(
        self, content: bytes, detected: str, provided_ocr_text: str | None = None, ocr_provenance: str | None = None,
        provided_ocr_structure: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ocr = self._ocr_image(content)
        candidates: list[tuple[str, float, dict[str, Any]]] = []
        if ocr.get("ok"):
            server_candidate = self._candidate_from_ocr_text(
                str(ocr["text"]), "image", "paper_receipt_tesseract_ocr_v2",
                SOURCE_PRIORITIES["server_ocr"], "server_tesseract",
            )
            server_candidate["diagnostics"].update({
                "tesseractPsm": ocr.get("pageSegmentationMode"),
                "tesseractCandidateScores": ocr.get("candidateScores") or {},
            })
            candidates.append((
                "server_tesseract", LocalTesseractOcr._receipt_text_score(str(ocr["text"])), server_candidate,
            ))
        if provided_ocr_text:
            android_candidate = self._candidate_from_ocr_text(
                provided_ocr_text, "image", "android_mlkit_ocr_v1", SOURCE_PRIORITIES["android_ocr"],
                ocr_provenance or "android_mlkit", provided_ocr_structure,
            )
            candidates.append((
                ocr_provenance or "android_mlkit",
                LocalTesseractOcr._receipt_text_score(provided_ocr_text), android_candidate,
            ))
        if candidates:
            # Structured phone OCR wins an exact tie because its line geometry is useful for review crops.
            selected_name, _, candidate = max(
                candidates,
                key=lambda item: (item[1], int(item[0] != "server_tesseract")),
            )
            candidate["diagnostics"].update({
                "selectedOcr": selected_name,
                "ocrCandidateScores": {name: round(score, 2) for name, score, _ in candidates},
                "serverOcrCode": ocr.get("code"),
            })
            return candidate
        source_format = f"{detected}_ocr_unavailable" if ocr.get("state") == "ocr_unavailable" else f"{detected}_ocr_failed"
        candidate = _empty_candidate("image", source_format)
        candidate["processing_state"] = ocr.get("state") or "ocr_required"
        candidate["processing_code"] = ocr.get("code") or "ocr_required"
        candidate["processing_message"] = ocr.get("message") or "This receipt image requires OCR."
        candidate["diagnostics"] = {
            "ocrAttempted": bool(ocr.get("available") and ocr.get("polishAvailable")),
            "ocrTextLength": len(ocr.get("text") or ""), "ocrCode": ocr.get("code"),
        }
        return candidate

    def _ocr_image(self, content: bytes) -> dict[str, Any]:
        return self.ocr_engine.recognize(content)

    def _ocr_pdf(self, content: bytes) -> dict[str, Any]:
        health = self.ocr_engine.health()
        if not health.get("available") or not health.get("polishAvailable"):
            return {
                "ok": False, "text": None, "state": "ocr_unavailable",
                "code": health.get("code") or "tesseract_missing",
                "message": health.get("message") or "OCR is unavailable.",
                "available": health.get("available", False),
                "polishAvailable": health.get("polishAvailable", False),
            }
        try:
            import pymupdf  # type: ignore
        except ImportError:
            try:
                import fitz as pymupdf  # type: ignore
            except ImportError:
                return {"ok": False, "text": None, "state": "ocr_failed", "code": "pdf_renderer_missing", "message": "PDF rendering support is unavailable."}
        document = pymupdf.open(stream=content, filetype="pdf")
        texts: list[str] = []
        try:
            for page in document:
                pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
                result = self._ocr_image(pixmap.tobytes("png"))
                if not result.get("ok"):
                    return result
                texts.append(str(result.get("text") or ""))
        finally:
            document.close()
        combined = "\n".join(texts).strip()
        return {
            "ok": bool(combined), "text": combined or None,
            "state": "parsed" if combined else "ocr_failed",
            "code": None if combined else "ocr_empty",
            "message": None if combined else "OCR returned no useful receipt text.",
            "available": True, "polishAvailable": True,
        }

    def _parse_receipt_text(
        self, raw_text: str, source_type: str, source_format: str,
        ocr_structure: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        candidate = _empty_candidate(source_type, source_format)
        parsed = parse_polish_receipt(
            raw_text, source_type=source_type, source_format=source_format,
            ocr_structure=ocr_structure,
        )
        candidate.update(parsed)
        candidate["retailer_key"] = _retailer_key(candidate.get("store_name"))
        return candidate


class FinanceReceiptService:
    def __init__(self, repository: FinanceRepository, storage_directory: Path | str | None = None):
        self.repository = repository
        self.storage_directory = Path(storage_directory or (repository.database_path.parent / "finance-receipts"))
        self.importer = ReceiptImporter()

    def initialize(self) -> None:
        self.storage_directory.mkdir(parents=True, exist_ok=True)
        self._seed_taxonomy()

    def _seed_taxonomy(self) -> None:
        taxonomy: tuple[tuple[str, tuple[str, ...]], ...] = (
            ("Żywność", ("Pieczywo", "Nabiał", "Mięso i ryby", "Warzywa i owoce", "Słodycze", "Napoje", "Pozostała żywność")),
            ("Chemia domowa", ()),
            ("Higiena", ()),
            ("Kosmetyki", ()),
            ("Zdrowie i leki", ()),
            ("Alkohol", ()),
            ("Tytoń i nikotyna", ()),
            ("Dom", ()),
            ("Elektronika i AGD", ()),
            ("Odzież i obuwie", ()),
            ("Zwierzęta", ()),
            ("Motoryzacja", ()),
            ("Ogród i rośliny", ()),
            ("Sport i rekreacja", ()),
            ("Książki i papiernicze", ()),
            ("Narzędzia i remont", ()),
            ("Zabawki i gry", ()),
            ("Usługi", ()),
            ("Inne", ()),
        )
        finance_targets = {
            "zywnosc": ("zakupy codzienne", "spozywcze"),
            "alkohol": ("zakupy codzienne", "uzywki"),
            "tyton i nikotyna": ("zakupy codzienne", "uzywki"),
            "chemia domowa": ("mieszkanie", "chemia domowa"),
            "higiena": (None, "higiena i uroda"),
            "kosmetyki": (None, "higiena i uroda"),
            "zdrowie i leki": ("zdrowie", "apteka"),
            "dom": ("zakupy", "dom"),
            "elektronika i agd": ("zakupy", "elektronika"),
            "odziez i obuwie": ("zakupy", "odziez"),
            "motoryzacja": ("transport", "inny transport"),
            "sport i rekreacja": ("rozrywka", "hobby"),
            "ksiazki i papiernicze": (None, "edukacja"),
            "zabawki i gry": ("rozrywka", "gry"),
            "uslugi": ("uslugi i subskrypcje", "inne uslugi"),
        }
        now = utc_now()
        with self.repository.transaction() as connection:
            finance_rows = connection.execute(
                """SELECT child.id, parent.normalized_name parent_name, child.normalized_name child_name
                   FROM categories child LEFT JOIN categories parent ON parent.id=child.parent_id"""
            ).fetchall()
            finance_map = {(row["parent_name"], row["child_name"]): row["id"] for row in finance_rows}
            for order, (name, children) in enumerate(taxonomy):
                normalized = _normalized(name)
                target = finance_targets.get(normalized)
                finance_id = finance_map.get(target) if target else None
                connection.execute(
                    """INSERT INTO product_categories(name,normalized_name,parent_id,finance_category_id,sort_order,created_at,updated_at)
                       VALUES (?,?,?,?,?,?,?) ON CONFLICT(normalized_name) DO UPDATE SET
                       finance_category_id=COALESCE(product_categories.finance_category_id,excluded.finance_category_id),
                       sort_order=excluded.sort_order,is_active=1,updated_at=excluded.updated_at""",
                    (name, normalized, None, finance_id, order * 100, now, now),
                )
                parent_id = connection.execute("SELECT id FROM product_categories WHERE normalized_name=?", (normalized,)).fetchone()[0]
                for child_order, child in enumerate(children, start=1):
                    connection.execute(
                        """INSERT INTO product_categories(name,normalized_name,parent_id,finance_category_id,sort_order,created_at,updated_at)
                           VALUES (?,?,?,?,?,?,?) ON CONFLICT(normalized_name) DO UPDATE SET
                           parent_id=excluded.parent_id,
                           finance_category_id=COALESCE(product_categories.finance_category_id,excluded.finance_category_id),
                           sort_order=excluded.sort_order,is_active=1,updated_at=excluded.updated_at""",
                        (child, _normalized(child), parent_id, finance_id, order * 100 + child_order, now, now),
                    )
            connection.execute(
                "UPDATE product_categories SET is_active=0,updated_at=? WHERE normalized_name=?",
                (now, _normalized("Dzieci i niemowlęta")),
            )

    def _merchant_id(self, connection: Any, retailer_key: str) -> int | None:
        if not retailer_key:
            return None
        row = connection.execute(
            """SELECT m.id FROM merchants m LEFT JOIN merchant_aliases a ON a.merchant_id=m.id
               WHERE m.normalized_name=? OR a.normalized_alias=? ORDER BY m.id LIMIT 1""",
            (retailer_key, retailer_key),
        ).fetchone()
        return int(row[0]) if row else None

    def _canonicalize_retailer(self, candidate: dict[str, Any]) -> dict[str, Any]:
        header = _normalized(candidate.get("store_name"))
        if not header:
            return candidate
        with self.repository.read_connection() as connection:
            rows = connection.execute(
                """SELECT m.id,m.canonical_name,m.normalized_name,a.normalized_alias
                   FROM merchants m LEFT JOIN merchant_aliases a ON a.merchant_id=m.id
                   ORDER BY LENGTH(COALESCE(a.normalized_alias,m.normalized_name)) DESC,m.id"""
            ).fetchall()
            profiles = connection.execute(
                """SELECT rp.retailer_key,rp.knowledge_json,m.canonical_name,m.normalized_name
                   FROM retailer_profiles rp LEFT JOIN merchants m ON m.id=rp.retailer_id"""
            ).fetchall()
        matched = next((row for row in rows if (
            row["normalized_name"] == header
            or len(str(row["normalized_name"] or "")) >= 3 and str(row["normalized_name"]) in header
            or len(str(row["normalized_alias"] or "")) >= 3 and str(row["normalized_alias"]) in header
        )), None)
        if matched:
            candidate["store_name"] = str(matched["canonical_name"])
            candidate["retailer_key"] = str(matched["normalized_name"])
            candidate.setdefault("field_evidence", {}).setdefault("merchant", {}).update({
                "confidence": "exact", "source": "finance_merchant_alias",
            })
            return candidate
        for profile in profiles:
            try:
                knowledge = json.loads(profile["knowledge_json"] or "{}")
            except json.JSONDecodeError:
                continue
            aliases = [_normalized(value) for value in knowledge.get("headerAliases") or []]
            if not any(len(alias) >= 3 and alias in header for alias in aliases):
                continue
            candidate["store_name"] = str(profile["canonical_name"] or profile["retailer_key"])
            candidate["retailer_key"] = str(profile["normalized_name"] or profile["retailer_key"])
            candidate.setdefault("field_evidence", {}).setdefault("merchant", {}).update({
                "confidence": "strong", "source": "retailer_profile",
            })
            break
        return candidate

    def _identity_hash(self, candidate: dict[str, Any]) -> str | None:
        if candidate.get("fiscal_identifier"):
            key = f"fiscal|{candidate['retailer_key']}|{candidate['fiscal_identifier']}"
        elif candidate.get("external_receipt_id") and candidate.get("purchase_date") and candidate.get("total_minor") is not None:
            key = f"external|{candidate['retailer_key']}|{candidate['external_receipt_id']}|{candidate['purchase_date']}|{candidate['total_minor']}"
        elif candidate.get("retailer_key") and candidate.get("purchase_date") and candidate.get("purchase_time") and candidate.get("total_minor") is not None:
            key = f"facts|{candidate['retailer_key']}|{candidate['purchase_date']}|{candidate['purchase_time']}|{candidate['total_minor']}|{candidate.get('currency') or 'PLN'}"
        else:
            return None
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    @staticmethod
    def _validation(candidate: dict[str, Any]) -> tuple[str, int | None]:
        total = candidate.get("total_minor")
        if total is None or not candidate.get("items"):
            return "needs_review", None
        computed = sum(int(item["total_price_minor"]) - abs(int(item.get("discount_minor") or 0)) for item in candidate["items"])
        computed += sum(int(item.get("amount_minor") or 0) for item in candidate.get("adjustments") or [])
        difference = int(total) - computed
        if abs(difference) <= 1:
            has_adjustments = bool(candidate.get("adjustments")) or any(int(item.get("discount_minor") or 0) for item in candidate["items"])
            return ("valid_with_adjustments" if has_adjustments else "valid"), difference
        if abs(difference) <= 5:
            return "needs_review", difference
        item_confidence = (candidate.get("field_evidence") or {}).get("items", {}).get("confidence")
        reconciliation = (candidate.get("diagnostics") or {}).get("reconciliation", {}).get("state")
        if candidate.get("source_type") in {"image", "pdf"} and (item_confidence != "exact" or reconciliation == "mismatch"):
            return "needs_review", difference
        return "invalid", difference

    def _store_source(self, receipt_id: str, source_id: str, filename: str, content: bytes) -> str:
        receipt_directory = self.storage_directory / receipt_id
        receipt_directory.mkdir(parents=True, exist_ok=True)
        extension = Path(filename).suffix.lower()[:10]
        storage_name = f"{source_id}{extension}"
        target = receipt_directory / storage_name
        with tempfile.NamedTemporaryFile(prefix="receipt-", dir=receipt_directory, delete=False) as handle:
            handle.write(content)
            temporary = Path(handle.name)
        os.replace(temporary, target)
        return f"{receipt_id}/{storage_name}"

    @staticmethod
    def _decode_base64(value: Any, label: str) -> bytes:
        try:
            return base64.b64decode(str(value or ""), validate=True)
        except ValueError as exc:
            raise ReceiptValidationError(f"{label} is not valid base64.") from exc

    def import_base64(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ReceiptValidationError("Receipt import payload is required.")
        content = self._decode_base64(payload.get("contentBase64"), "Receipt content")
        evidence = payload.get("ocrEvidence") if isinstance(payload.get("ocrEvidence"), dict) else {}
        provided_ocr_text = str(evidence.get("text") or payload.get("ocrText") or "").strip() or None
        ocr_provenance = str(evidence.get("provider") or payload.get("ocrProvenance") or "").strip() or None
        provided_ocr_structure = sanitize_ocr_structure(evidence)
        extra_sources: list[dict[str, Any]] = []
        attachments = payload.get("attachments") if isinstance(payload.get("attachments"), list) else []
        if len(attachments) > 10:
            raise ReceiptValidationError("Too many receipt attachments.")
        total_bytes = len(content)
        for index, attachment in enumerate(attachments, start=1):
            if not isinstance(attachment, dict):
                raise ReceiptValidationError("Receipt attachment is invalid.")
            attachment_content = self._decode_base64(attachment.get("contentBase64"), f"Receipt attachment {index}")
            total_bytes += len(attachment_content)
            extra_sources.append({
                "filename": str(attachment.get("filename") or f"attachment-{index}"),
                "mime_type": str(attachment.get("mimeType") or ""),
                "content": attachment_content,
                "source_role": str(attachment.get("sourceRole") or "attachment")[:40],
                "page_number": int(attachment["pageNumber"]) if attachment.get("pageNumber") is not None else None,
            })
            self.importer.detect(
                extra_sources[-1]["filename"], extra_sources[-1]["mime_type"], extra_sources[-1]["content"]
            )
        if total_bytes > MAX_RECEIPT_BYTES:
            raise ReceiptValidationError("Receipt upload bundle is too large.")
        return self.import_bytes(
            str(payload.get("filename") or "receipt"), str(payload.get("mimeType") or ""), content,
            provided_ocr_text=provided_ocr_text, ocr_provenance=ocr_provenance,
            provided_ocr_structure=provided_ocr_structure,
            source_role=str(payload.get("sourceRole") or "primary")[:40],
            page_number=int(payload["pageNumber"]) if payload.get("pageNumber") is not None else None,
            extra_sources=extra_sources,
        )

    def _insert_candidate_lines(
        self, connection: Any, receipt_id: str, candidate: dict[str, Any], now: str,
        preserved: dict[tuple[int, str], dict[str, Any]] | None = None,
    ) -> None:
        preserved = preserved or {}
        for item in candidate["items"]:
            key = (int(item["line_number"]), _normalized(item["raw_name"]))
            previous = preserved.get(key)
            if previous and previous.get("classification_source") in {"manual", "guided_review"}:
                product_id = previous.get("product_id")
                product_category_id = previous.get("product_category_id")
                classification_source = previous.get("classification_source")
                review_state = previous.get("review_state") or "resolved"
            else:
                product_id, product_category_id, classification_source = self._resolve_product(connection, candidate["retailer_key"], item)
                review_state = "resolved" if product_id or product_category_id else "unresolved"
            confidence = str(item.get("confidence_state") or "review")
            stored_confidence = "exact" if confidence in {"exact", "strong", "manual"} else "review" if confidence == "weak" else confidence
            raw_evidence = dict(item.get("raw_evidence") or {})
            raw_evidence.setdefault("parserConfidence", confidence)
            if confidence == "exact" and candidate.get("source_type") == "json":
                raw_evidence.setdefault("credibleProductLine", True)
            connection.execute(
                """INSERT INTO receipt_items(
                   id,receipt_id,line_number,raw_name,normalized_name,interpreted_name,raw_product_code,barcode,
                   quantity,unit,unit_price_minor,total_price_minor,discount_minor,product_id,product_category_id,
                   classification_source,review_state,confidence_state,raw_evidence_json,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (_identifier("ritm"), receipt_id, item["line_number"], item["raw_name"], _normalized(item["raw_name"]),
                 item.get("interpreted_name"), item.get("raw_product_code"), item.get("barcode"), item.get("quantity") or "1",
                 item.get("unit") or "unknown", item.get("unit_price_minor"), item["total_price_minor"],
                 abs(int(item.get("discount_minor") or 0)), product_id, product_category_id, classification_source,
                 review_state, stored_confidence, json.dumps(raw_evidence, ensure_ascii=False), now, now),
            )
        for adjustment in candidate.get("adjustments") or []:
            connection.execute(
                """INSERT INTO receipt_adjustments(id,receipt_id,line_number,kind,label,amount_minor,raw_evidence_json,created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (_identifier("radj"), receipt_id, adjustment.get("line_number"), adjustment.get("kind") or "other",
                 adjustment.get("label") or "", int(adjustment.get("amount_minor") or 0),
                 json.dumps(adjustment.get("raw_evidence") or {}, ensure_ascii=False), now),
            )

    def _attach_source(
        self, receipt_id: str, filename: str, mime_type: str, content: bytes,
        *, source_role: str, page_number: int | None, source_format: str, source_type: str,
        source_priority: int = 100, candidate: dict[str, Any] | None = None,
        provided_ocr_text: str | None = None, ocr_provenance: str | None = None,
        provided_ocr_structure: dict[str, Any] | None = None,
    ) -> bool:
        digest = hashlib.sha256(content).hexdigest()
        with self.repository.read_connection() as connection:
            if connection.execute("SELECT 1 FROM receipt_sources WHERE source_sha256=?", (digest,)).fetchone():
                return False
        source_id = _identifier("rsrc")
        storage_name = self._store_source(receipt_id, source_id, _safe_filename(filename), content)
        candidate = candidate or _empty_candidate(source_type, source_format)
        try:
            with self.repository.transaction() as connection:
                connection.execute(
                    """INSERT INTO receipt_sources(
                       id,receipt_id,source_sha256,storage_name,original_filename,mime_type,source_type,source_format,
                       source_priority,parser_version,extracted_text,raw_ocr_text,imported_at,source_role,page_number,
                       ocr_provenance,processing_state,processing_code,diagnostics_json,provided_ocr_text,ocr_structure_json)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (source_id, receipt_id, digest, storage_name, _safe_filename(filename),
                     mime_type or mimetypes.guess_type(filename)[0] or "application/octet-stream",
                     source_type, source_format, source_priority, PARSER_VERSION,
                     candidate.get("extracted_text"), candidate.get("raw_ocr_text"), utc_now(), source_role, page_number,
                     ocr_provenance or candidate.get("ocr_provenance"), candidate.get("processing_state") or "source_received",
                     candidate.get("processing_code"), json.dumps(candidate.get("diagnostics") or {}), provided_ocr_text,
                     json.dumps(sanitize_ocr_structure(provided_ocr_structure or candidate.get("ocr_structure")), ensure_ascii=False)),
                )
        except Exception:
            (self.storage_directory / storage_name).unlink(missing_ok=True)
            raise
        return True

    def import_bytes(
        self, filename: str, mime_type: str, content: bytes, *,
        provided_ocr_text: str | None = None, ocr_provenance: str | None = None,
        provided_ocr_structure: dict[str, Any] | None = None,
        source_role: str = "primary", page_number: int | None = None,
        extra_sources: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if not content:
            raise ReceiptValidationError("Receipt file is empty.")
        if len(content) > MAX_RECEIPT_BYTES:
            raise ReceiptValidationError("Receipt file is too large.")
        safe_filename = _safe_filename(filename)
        digest = hashlib.sha256(content).hexdigest()
        with self.repository.read_connection() as connection:
            duplicate = connection.execute("SELECT id,receipt_id FROM receipt_sources WHERE source_sha256=?", (digest,)).fetchone()
        if duplicate:
            receipt_id = str(duplicate["receipt_id"])
            if provided_ocr_text:
                with self.repository.transaction() as connection:
                    connection.execute(
                        "UPDATE receipt_sources SET provided_ocr_text=?,ocr_provenance=?,ocr_structure_json=? WHERE id=?",
                        (provided_ocr_text, ocr_provenance or "android_mlkit",
                         json.dumps(sanitize_ocr_structure(provided_ocr_structure), ensure_ascii=False), duplicate["id"]),
                    )
            for attachment in extra_sources or []:
                detected_type, _ = self.importer.detect(attachment["filename"], attachment["mime_type"], attachment["content"])
                self._attach_source(
                    receipt_id, attachment["filename"], attachment["mime_type"], attachment["content"],
                    source_role=attachment["source_role"], page_number=attachment["page_number"],
                    source_format=f"android_scan_{attachment['source_role']}", source_type=detected_type,
                )
            result = self.reprocess_receipt(receipt_id) if provided_ocr_text or extra_sources else self.get_receipt(receipt_id)
            result.update({"duplicate": True, "sourceHash": digest})
            return result

        candidate = self.importer.parse(
            safe_filename, mime_type, content, provided_ocr_text, ocr_provenance, provided_ocr_structure,
        )
        candidate = self._canonicalize_retailer(candidate)
        validation_state, difference = self._validation(candidate)
        identity_hash = self._identity_hash(candidate)
        now = utc_now()
        with self.repository.transaction() as connection:
            existing = connection.execute("SELECT * FROM receipts WHERE identity_hash=?", (identity_hash,)).fetchone() if identity_hash else None
            if existing:
                receipt_id = str(existing["id"])
                replace_canonical = int(candidate["source_priority"]) > int(existing["source_priority"])
                preserved = {
                    (int(item["line_number"]), str(item["normalized_name"])): dict(item)
                    for item in connection.execute("SELECT * FROM receipt_items WHERE receipt_id=?", (receipt_id,)).fetchall()
                }
                if existing["merchant_source"] == "manual":
                    candidate["retailer_key"] = existing["retailer_key"]
                    candidate["store_name"] = existing["store_name"]
                if existing["purchase_date_source"] == "manual":
                    candidate["purchase_date"] = existing["purchase_date"]
                    candidate["purchase_time"] = existing["purchase_time"]
                if existing["total_source"] == "manual":
                    candidate["total_minor"] = existing["total_minor"]
                    candidate["currency"] = existing["currency"]
                validation_state, difference = self._validation(candidate)
            else:
                receipt_id = _identifier("rcpt")
                preserved = {}
                status = "needs_review" if validation_state in {"needs_review", "invalid"} else "inbox"
                connection.execute(
                    """INSERT INTO receipts(
                       id,retailer_id,retailer_key,source_type,source_format,external_receipt_id,purchase_date,purchase_time,
                       total_minor,currency,store_name,store_location,fiscal_identifier,parser_version,source_priority,
                       identity_hash,validation_state,validation_difference_minor,match_state,status,created_at,updated_at,
                       processing_state,processing_code,processing_message,field_evidence_json,parse_review_json,
                       parser_diagnostics_json)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (receipt_id, self._merchant_id(connection, candidate["retailer_key"]), candidate["retailer_key"],
                     candidate["source_type"], candidate["source_format"], candidate.get("external_receipt_id"),
                     candidate.get("purchase_date"), candidate.get("purchase_time"), candidate.get("total_minor"),
                     candidate.get("currency") or "PLN", candidate.get("store_name") or "", candidate.get("store_location"),
                     candidate.get("fiscal_identifier"), PARSER_VERSION, candidate["source_priority"], identity_hash,
                     validation_state, difference, "none", status, now, now, candidate.get("processing_state") or "needs_review",
                     candidate.get("processing_code"), candidate.get("processing_message"),
                     json.dumps(candidate.get("field_evidence") or {}, ensure_ascii=False),
                     json.dumps(candidate.get("parse_review") or {}, ensure_ascii=False),
                     json.dumps(candidate.get("diagnostics") or {}, ensure_ascii=False)),
                )
                replace_canonical = True
            if replace_canonical:
                connection.execute("DELETE FROM receipt_adjustments WHERE receipt_id=?", (receipt_id,))
                connection.execute("DELETE FROM receipt_items WHERE receipt_id=?", (receipt_id,))
                connection.execute(
                    """UPDATE receipts SET retailer_id=?,retailer_key=?,source_type=?,source_format=?,external_receipt_id=?,
                       purchase_date=?,purchase_time=?,total_minor=?,currency=?,store_name=?,store_location=?,fiscal_identifier=?,
                       parser_version=?,source_priority=?,identity_hash=COALESCE(identity_hash,?),validation_state=?,
                       validation_difference_minor=?,processing_state=?,processing_code=?,processing_message=?,
                       field_evidence_json=?,parse_review_json=?,parser_diagnostics_json=?,updated_at=? WHERE id=?""",
                    (self._merchant_id(connection, candidate["retailer_key"]), candidate["retailer_key"], candidate["source_type"],
                     candidate["source_format"], candidate.get("external_receipt_id"), candidate.get("purchase_date"),
                     candidate.get("purchase_time"), candidate.get("total_minor"), candidate.get("currency") or "PLN",
                     candidate.get("store_name") or "", candidate.get("store_location"), candidate.get("fiscal_identifier"),
                     PARSER_VERSION, candidate["source_priority"], identity_hash, validation_state, difference,
                     candidate.get("processing_state") or "needs_review", candidate.get("processing_code"),
                     candidate.get("processing_message"),
                     json.dumps(candidate.get("field_evidence") or {}, ensure_ascii=False),
                     json.dumps(candidate.get("parse_review") or {}, ensure_ascii=False),
                     json.dumps(candidate.get("diagnostics") or {}, ensure_ascii=False), now, receipt_id),
                )
                self._insert_candidate_lines(connection, receipt_id, candidate, now, preserved)

        self._attach_source(
            receipt_id, safe_filename, mime_type, content, source_role=source_role, page_number=page_number,
            source_format=candidate["source_format"], source_type=candidate["source_type"],
            source_priority=candidate["source_priority"], candidate=candidate,
            provided_ocr_text=provided_ocr_text, ocr_provenance=ocr_provenance,
            provided_ocr_structure=provided_ocr_structure,
        )
        for attachment in extra_sources or []:
            detected_type, _ = self.importer.detect(attachment["filename"], attachment["mime_type"], attachment["content"])
            self._attach_source(
                receipt_id, attachment["filename"], attachment["mime_type"], attachment["content"],
                source_role=attachment["source_role"], page_number=attachment["page_number"],
                source_format=f"android_scan_{attachment['source_role']}", source_type=detected_type,
            )
        match = self.match_receipt(receipt_id, auto_link=True)
        result = self.get_receipt(receipt_id)
        result.update({"duplicate": bool(existing), "sourceHash": digest, "match": match})
        return result

    def _resolve_product(self, connection: Any, retailer_key: str, item: dict[str, Any]) -> tuple[str | None, int | None, str]:
        code = str(item.get("raw_product_code") or "").strip()
        raw_name = str(item.get("raw_name") or "").strip()
        normalized = _normalized(raw_name)
        rows = connection.execute(
            """SELECT a.product_id,p.product_category_id,a.raw_name,a.normalized_name,a.retailer_code
               FROM retailer_product_aliases a JOIN products p ON p.id=a.product_id
               WHERE a.retailer_key=? AND a.confirmed=1 AND (
                 (?<>'' AND a.retailer_code=?) OR a.raw_name=? OR a.normalized_name=?)
               ORDER BY CASE WHEN ?<>'' AND a.retailer_code=? THEN 0 WHEN a.raw_name=? THEN 1 ELSE 2 END, a.id LIMIT 1""",
            (retailer_key, code, code, raw_name, normalized, code, code, raw_name),
        ).fetchone()
        if rows:
            return str(rows["product_id"]), rows["product_category_id"], "retailer_alias"
        barcode = str(item.get("barcode") or "").strip()
        if barcode:
            row = connection.execute(
                """SELECT p.id,p.product_category_id FROM product_barcodes b JOIN products p ON p.id=b.product_id
                   WHERE b.barcode=? AND b.confirmed=1""", (barcode,),
            ).fetchone()
            if row:
                return str(row["id"]), row["product_category_id"], "barcode"
        return None, None, "unresolved"

    def _receipt_row(self, row: Any) -> dict[str, Any]:
        return {
            "id": row["id"], "retailer": row["store_name"] or row["retailer_key"] or "Nierozpoznany sprzedawca",
            "retailerKey": row["retailer_key"], "date": row["purchase_date"], "time": row["purchase_time"],
            "total": row["total_minor"] / 100 if row["total_minor"] is not None else None, "currency": row["currency"],
            "sourceType": row["source_type"], "sourceFormat": row["source_format"],
            "validationState": row["validation_state"],
            "validationDifference": row["validation_difference_minor"] / 100 if row["validation_difference_minor"] is not None else None,
            "matchState": row["match_state"], "transactionId": row["transaction_id"], "status": row["status"],
            "processingState": row["processing_state"], "processingCode": row["processing_code"],
            "processingMessage": row["processing_message"],
            "fieldSources": {
                "merchant": row["merchant_source"], "purchaseDate": row["purchase_date_source"],
                "total": row["total_source"],
            },
            "itemCount": int(row["item_count"] if "item_count" in row.keys() else 0),
            "unresolvedItems": int(row["unresolved_items"] if "unresolved_items" in row.keys() else 0),
            "createdAt": row["created_at"], "updatedAt": row["updated_at"],
        }

    def list_receipts(self, status: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        params: list[Any] = []
        where = ""
        if status:
            where = "WHERE r.status=?"
            params.append(status)
        params.append(max(1, min(int(limit), 500)))
        with self.repository.read_connection() as connection:
            rows = connection.execute(
                f"""SELECT r.*,COUNT(i.id) item_count,
                    SUM(CASE WHEN i.review_state='unresolved' THEN 1 ELSE 0 END) unresolved_items
                    FROM receipts r LEFT JOIN receipt_items i ON i.receipt_id=r.id {where}
                    GROUP BY r.id ORDER BY COALESCE(r.purchase_date,r.created_at) DESC,r.created_at DESC LIMIT ?""", params,
            ).fetchall()
        return [self._receipt_row(row) for row in rows]

    def get_receipt(self, receipt_id: str) -> dict[str, Any]:
        with self.repository.read_connection() as connection:
            row = connection.execute(
                """SELECT r.*,COUNT(i.id) item_count,SUM(CASE WHEN i.review_state='unresolved' THEN 1 ELSE 0 END) unresolved_items
                   FROM receipts r LEFT JOIN receipt_items i ON i.receipt_id=r.id WHERE r.id=? GROUP BY r.id""", (receipt_id,),
            ).fetchone()
            if not row:
                raise FinanceNotFoundError("Receipt was not found.")
            items = connection.execute(
                """SELECT i.*,p.canonical_name product_name,pc.name category_name
                   FROM receipt_items i LEFT JOIN products p ON p.id=i.product_id
                   LEFT JOIN product_categories pc ON pc.id=i.product_category_id
                   WHERE i.receipt_id=? ORDER BY i.line_number""", (receipt_id,),
            ).fetchall()
            adjustments = connection.execute(
                "SELECT id,line_number,kind,label,amount_minor FROM receipt_adjustments WHERE receipt_id=? ORDER BY COALESCE(line_number,999999),id", (receipt_id,),
            ).fetchall()
            source_count = connection.execute("SELECT COUNT(*) FROM receipt_sources WHERE receipt_id=?", (receipt_id,)).fetchone()[0]
            review_group_counts = {
                str(group["normalized_name"]): int(group["item_count"])
                for group in connection.execute(
                    """SELECT i.normalized_name,COUNT(*) item_count
                       FROM receipt_items i JOIN receipts grouped_receipt ON grouped_receipt.id=i.receipt_id
                       WHERE grouped_receipt.retailer_key=? AND i.review_state='unresolved'
                         AND (json_extract(i.raw_evidence_json,'$.credibleProductLine')=1 OR i.confidence_state='exact')
                       GROUP BY i.normalized_name""",
                    (row["retailer_key"],),
                ).fetchall()
            }
        result = self._receipt_row(row)
        result_items = []
        for item in items:
            try:
                evidence = json.loads(item["raw_evidence_json"] or "{}")
            except json.JSONDecodeError:
                evidence = {}
            has_crop = bool(evidence.get("box") and evidence.get("page"))
            is_reviewable = item["review_state"] == "unresolved" and (
                bool(evidence.get("credibleProductLine")) or item["confidence_state"] == "exact"
            )
            review_group_id = hashlib.sha256(
                f"{row['retailer_key']}|{item['normalized_name']}".encode()
            ).hexdigest()[:24] if is_reviewable else None
            result_items.append({
                "id": item["id"], "lineNumber": item["line_number"], "rawName": item["raw_name"],
                "interpretedName": item["interpreted_name"], "productCode": item["raw_product_code"], "barcode": item["barcode"],
                "quantity": item["quantity"], "unit": item["unit"],
                "unitPrice": item["unit_price_minor"] / 100 if item["unit_price_minor"] is not None else None,
                "totalPrice": item["total_price_minor"] / 100, "discount": item["discount_minor"] / 100,
                "effectivePrice": (item["total_price_minor"] - item["discount_minor"]) / 100,
                "productId": item["product_id"], "productName": item["product_name"],
                "productCategoryId": item["product_category_id"], "productCategory": item["category_name"],
                "classificationSource": item["classification_source"], "reviewState": item["review_state"],
                "confidenceState": evidence.get("parserConfidence") or item["confidence_state"],
                "sourceLine": evidence.get("sourceLine"),
                "credibleProductLine": bool(evidence.get("credibleProductLine")),
                "cropUrl": f"/api/budget/receipt-items/{item['id']}/crop" if has_crop else None,
                "reviewGroupId": review_group_id,
                "reviewGroupItemCount": review_group_counts.get(str(item["normalized_name"]), 0),
                "nameConfidence": "strong" if len(re.sub(r"[^A-Za-zÀ-ž]", "", item["raw_name"])) >= 4
                                  and not re.search(r"\d", item["raw_name"]) else "weak",
            })
        result["items"] = result_items
        result["adjustments"] = [{"id": item["id"], "lineNumber": item["line_number"], "kind": item["kind"], "label": item["label"], "amount": item["amount_minor"] / 100} for item in adjustments]
        result["sourceCount"] = int(source_count)
        for source_key, target_key in (
            ("field_evidence_json", "fieldEvidence"),
            ("parse_review_json", "parseReview"),
            ("parser_diagnostics_json", "parserDiagnostics"),
        ):
            try:
                result[target_key] = json.loads(row[source_key] or "{}")
            except json.JSONDecodeError:
                result[target_key] = {}
        if isinstance(result.get("parseReview"), dict):
            result["parseReview"]["itemCandidates"] = [{
                "itemId": item["id"], "name": item["interpretedName"] or item["rawName"],
                "priceLabel": f"{item['effectivePrice']:.2f} {result['currency']}",
            } for item in result_items if item["confidenceState"] in {"weak", "review", "uncertain"} and item["credibleProductLine"]]
        return result

    def item_crop(self, item_id: str) -> dict[str, Any]:
        from io import BytesIO
        from PIL import Image, ImageOps

        with self.repository.read_connection() as connection:
            item = connection.execute(
                "SELECT receipt_id,raw_evidence_json FROM receipt_items WHERE id=?", (item_id,),
            ).fetchone()
            if not item:
                raise FinanceNotFoundError("Receipt item was not found.")
            try:
                evidence = json.loads(item["raw_evidence_json"] or "{}")
            except json.JSONDecodeError:
                evidence = {}
            box = evidence.get("box") if isinstance(evidence.get("box"), dict) else None
            page_number = int(evidence.get("page") or 1)
            if not box:
                raise FinanceNotFoundError("Receipt item has no source crop.")
            source = connection.execute(
                """SELECT * FROM receipt_sources WHERE receipt_id=? AND mime_type LIKE 'image/%'
                   ORDER BY CASE WHEN page_number=? THEN 0 WHEN source_role='primary' THEN 1 ELSE 2 END,
                            imported_at,id LIMIT 1""",
                (item["receipt_id"], page_number),
            ).fetchone()
        if not source:
            raise FinanceNotFoundError("Receipt item image source was not found.")
        content = self._read_source_for_reprocess(source)
        try:
            image = ImageOps.exif_transpose(Image.open(BytesIO(content))).convert("RGB")
            left = max(0, int(float(box["x"]) * image.width))
            top = max(0, int(float(box["y"]) * image.height))
            right = min(image.width, int((float(box["x"]) + float(box["width"])) * image.width))
            bottom = min(image.height, int((float(box["y"]) + float(box["height"])) * image.height))
            if right <= left or bottom <= top:
                raise ValueError("empty crop")
            cropped = image.crop((left, top, right, bottom))
            cropped.thumbnail((1400, 700))
            output = BytesIO()
            cropped.save(output, format="JPEG", quality=88, optimize=True)
        except (OSError, KeyError, TypeError, ValueError) as exc:
            raise ReceiptValidationError("Receipt item crop could not be generated.") from exc
        return {"content": output.getvalue(), "mimeType": "image/jpeg", "filename": f"{item_id}.jpg"}

    def list_sources(self, receipt_id: str) -> list[dict[str, Any]]:
        with self.repository.read_connection() as connection:
            if not connection.execute("SELECT 1 FROM receipts WHERE id=?", (receipt_id,)).fetchone():
                raise FinanceNotFoundError("Receipt was not found.")
            rows = connection.execute(
                """SELECT id,original_filename,mime_type,source_type,source_format,source_role,page_number,
                   source_priority,ocr_provenance,processing_state,processing_code,diagnostics_json,imported_at
                   FROM receipt_sources WHERE receipt_id=?
                   ORDER BY CASE source_role WHEN 'primary' THEN 0 WHEN 'page' THEN 1 ELSE 2 END,
                            COALESCE(page_number,999999),imported_at,id""",
                (receipt_id,),
            ).fetchall()
        sources = []
        for row in rows:
            try:
                diagnostics = json.loads(row["diagnostics_json"] or "{}")
            except json.JSONDecodeError:
                diagnostics = {}
            sources.append({
                "id": row["id"], "filename": row["original_filename"], "mimeType": row["mime_type"],
                "sourceType": row["source_type"], "sourceFormat": row["source_format"],
                "sourceRole": row["source_role"], "pageNumber": row["page_number"],
                "sourcePriority": row["source_priority"], "ocrProvenance": row["ocr_provenance"],
                "processingState": row["processing_state"], "processingCode": row["processing_code"],
                "diagnostics": diagnostics, "importedAt": row["imported_at"],
                "contentUrl": f"/api/budget/receipts/{receipt_id}/sources/{row['id']}/content",
            })
        return sources

    def _source_path(self, storage_name: str) -> Path:
        base = self.storage_directory.resolve()
        path = (base / str(storage_name)).resolve()
        if not path.is_relative_to(base):
            raise FinanceNotFoundError("Receipt source was not found.")
        return path

    def source_content(self, receipt_id: str, source_id: str) -> dict[str, Any]:
        with self.repository.read_connection() as connection:
            source = connection.execute(
                """SELECT storage_name,original_filename,mime_type,source_sha256
                   FROM receipt_sources WHERE id=? AND receipt_id=?""", (source_id, receipt_id),
            ).fetchone()
        if not source:
            raise FinanceNotFoundError("Receipt source was not found.")
        path = self._source_path(source["storage_name"])
        if not path.is_file():
            raise FinanceNotFoundError("Receipt source file was not found.")
        content = path.read_bytes()
        if not hmac.compare_digest(hashlib.sha256(content).hexdigest(), source["source_sha256"]):
            raise ReceiptValidationError("Receipt source integrity check failed.")
        return {
            "content": content, "mimeType": source["mime_type"],
            "filename": source["original_filename"],
        }

    def delete_receipt(self, receipt_id: str) -> dict[str, Any]:
        base = self.storage_directory.resolve()
        receipt_directory = (base / receipt_id).resolve()
        if receipt_directory.parent != base:
            raise FinanceNotFoundError("Receipt was not found.")

        staging_root = (base / ".delete-staging").resolve()
        if not staging_root.is_relative_to(base):
            raise FinanceError("Receipt deletion staging path is invalid.")

        staged_directory: Path | None = None
        if receipt_directory.exists():
            if not receipt_directory.is_dir():
                raise FinanceError("Receipt source storage is invalid.")
            staging_root.mkdir(parents=True, exist_ok=True)
            staged_directory = (staging_root / f"{receipt_id}-{uuid.uuid4().hex}").resolve()
            if staged_directory.parent != staging_root:
                raise FinanceError("Receipt deletion staging path is invalid.")
            os.replace(receipt_directory, staged_directory)

        try:
            with self.repository.transaction() as connection:
                receipt = connection.execute(
                    "SELECT transaction_id FROM receipts WHERE id=?", (receipt_id,),
                ).fetchone()
                if not receipt:
                    raise FinanceNotFoundError("Receipt was not found.")
                source_count = int(connection.execute(
                    "SELECT COUNT(*) FROM receipt_sources WHERE receipt_id=?", (receipt_id,),
                ).fetchone()[0])
                connection.execute("DELETE FROM receipts WHERE id=?", (receipt_id,))
                linked_transaction_preserved = receipt["transaction_id"] is not None
        except Exception:
            if staged_directory and staged_directory.exists() and not receipt_directory.exists():
                os.replace(staged_directory, receipt_directory)
            raise

        if staged_directory and staged_directory.exists():
            shutil.rmtree(staged_directory)
        try:
            staging_root.rmdir()
        except OSError:
            pass
        return {
            "receiptId": receipt_id,
            "deleted": True,
            "sourceCount": source_count,
            "transactionPreserved": True,
            "hadLinkedTransaction": linked_transaction_preserved,
        }

    def processing_health(self) -> dict[str, Any]:
        ocr = self.importer.ocr_engine.health()
        public_ocr = {key: value for key, value in ocr.items() if key != "command"}
        with self.repository.read_connection() as connection:
            rows = connection.execute(
                "SELECT processing_state,COUNT(*) count FROM receipts GROUP BY processing_state ORDER BY processing_state"
            ).fetchall()
            pending = connection.execute(
                """SELECT COUNT(*) FROM receipts
                   WHERE processing_state IN ('ocr_required','ocr_unavailable','ocr_failed','needs_review')"""
            ).fetchone()[0]
        return {
            "serverOcr": public_ocr,
            "androidOcrEvidence": {
                "supported": True,
                "provider": "Android ML Kit",
                "role": "text_extraction_only",
                "structuredGeometry": True,
            },
            "pdfTextExtraction": {"available": bool(importlib.util.find_spec("pymupdf") or importlib.util.find_spec("fitz"))},
            "receiptStorage": {
                "available": self.storage_directory.is_dir(),
                "writable": self.storage_directory.is_dir() and os.access(self.storage_directory, os.W_OK),
            },
            "receiptStates": {str(row["processing_state"]): int(row["count"]) for row in rows},
            "receiptsNeedingAttention": int(pending),
        }

    def _read_source_for_reprocess(self, source: Any) -> bytes:
        path = self._source_path(source["storage_name"])
        if not path.is_file():
            raise ReceiptValidationError("A stored receipt source is missing.")
        content = path.read_bytes()
        if not hmac.compare_digest(hashlib.sha256(content).hexdigest(), source["source_sha256"]):
            raise ReceiptValidationError("A stored receipt source failed its integrity check.")
        return content

    def reprocess_receipt(self, receipt_id: str) -> dict[str, Any]:
        with self.repository.read_connection() as connection:
            receipt = connection.execute("SELECT * FROM receipts WHERE id=?", (receipt_id,)).fetchone()
            if not receipt:
                raise FinanceNotFoundError("Receipt was not found.")
            sources = connection.execute(
                """SELECT * FROM receipt_sources WHERE receipt_id=?
                   ORDER BY CASE source_role WHEN 'primary' THEN 0 WHEN 'page' THEN 1 ELSE 2 END,
                            COALESCE(page_number,999999),imported_at,id""", (receipt_id,),
            ).fetchall()
            old_items = connection.execute("SELECT * FROM receipt_items WHERE receipt_id=?", (receipt_id,)).fetchall()
        if not sources:
            raise ReceiptValidationError("Receipt has no stored source to reprocess.")

        candidates: list[tuple[Any, dict[str, Any], dict[str, Any]]] = []
        for source in sources:
            content = self._read_source_for_reprocess(source)
            try:
                try:
                    structure = json.loads(source["ocr_structure_json"] or "{}")
                except json.JSONDecodeError:
                    structure = {}
                candidate = self.importer.parse(
                    source["original_filename"], source["mime_type"], content,
                    source["provided_ocr_text"], source["ocr_provenance"], structure,
                )
                candidate = self._canonicalize_retailer(candidate)
            except ReceiptValidationError as exc:
                candidate = _empty_candidate(source["source_type"], source["source_format"])
                candidate.update({
                    "processing_state": "needs_review", "processing_code": "source_parse_rejected",
                    "processing_message": str(exc), "diagnostics": {"parserRejected": True},
                })
            candidates.append((source, candidate, structure))

        _, best, _ = max(candidates, key=lambda pair: (
            _parsed_receipt_score(
                pair[1], len(str(pair[1].get("raw_ocr_text") or pair[1].get("extracted_text") or "")),
            ),
            int(pair[1].get("source_priority") or 0),
        ))
        has_existing_facts = bool(receipt["purchase_date"] or receipt["total_minor"] is not None or old_items)
        replace_facts = bool(best.get("recognized") or best.get("items") or not has_existing_facts)
        preserved = {
            (int(item["line_number"]), str(item["normalized_name"])): dict(item)
            for item in old_items
        }
        now = utc_now()
        if replace_facts:
            if receipt["merchant_source"] == "manual":
                best["retailer_key"] = receipt["retailer_key"]
                best["store_name"] = receipt["store_name"]
            if receipt["purchase_date_source"] == "manual":
                best["purchase_date"] = receipt["purchase_date"]
                best["purchase_time"] = receipt["purchase_time"]
            if receipt["total_source"] == "manual":
                best["total_minor"] = receipt["total_minor"]
                best["currency"] = receipt["currency"]
            validation_state, difference = self._validation(best)
        else:
            validation_state, difference = receipt["validation_state"], receipt["validation_difference_minor"]

        with self.repository.transaction() as connection:
            for source, candidate, structure in candidates:
                connection.execute(
                    """UPDATE receipt_sources SET source_type=?,source_format=?,source_priority=?,parser_version=?,
                       extracted_text=?,raw_ocr_text=?,ocr_provenance=COALESCE(?,ocr_provenance),processing_state=?,
                       processing_code=?,diagnostics_json=?,ocr_structure_json=? WHERE id=?""",
                    (candidate["source_type"], candidate["source_format"], candidate["source_priority"], PARSER_VERSION,
                     candidate.get("extracted_text"), candidate.get("raw_ocr_text"), candidate.get("ocr_provenance"),
                     candidate.get("processing_state") or "needs_review", candidate.get("processing_code"),
                     json.dumps(candidate.get("diagnostics") or {}, ensure_ascii=False),
                     json.dumps(sanitize_ocr_structure(candidate.get("ocr_structure") or structure), ensure_ascii=False), source["id"]),
                )
            if replace_facts:
                connection.execute("DELETE FROM receipt_adjustments WHERE receipt_id=?", (receipt_id,))
                connection.execute("DELETE FROM receipt_items WHERE receipt_id=?", (receipt_id,))
                status = receipt["status"] if receipt["match_state"] == "manual" or receipt["transaction_id"] else (
                    "needs_review" if validation_state in {"needs_review", "invalid"} else "inbox"
                )
                connection.execute(
                    """UPDATE receipts SET retailer_id=?,retailer_key=?,source_type=?,source_format=?,external_receipt_id=?,
                       purchase_date=?,purchase_time=?,total_minor=?,currency=?,store_name=?,store_location=?,
                       fiscal_identifier=?,parser_version=?,source_priority=?,validation_state=?,validation_difference_minor=?,
                       processing_state=?,processing_code=?,processing_message=?,field_evidence_json=?,parse_review_json=?,
                       parser_diagnostics_json=?,status=?,updated_at=? WHERE id=?""",
                    (self._merchant_id(connection, best["retailer_key"]), best["retailer_key"], best["source_type"],
                     best["source_format"], best.get("external_receipt_id"), best.get("purchase_date"),
                     best.get("purchase_time"), best.get("total_minor"), best.get("currency") or "PLN",
                     best.get("store_name") or "", best.get("store_location"), best.get("fiscal_identifier"),
                     PARSER_VERSION, best["source_priority"], validation_state, difference,
                     best.get("processing_state") or "needs_review", best.get("processing_code"),
                     best.get("processing_message"),
                     json.dumps(best.get("field_evidence") or {}, ensure_ascii=False),
                     json.dumps(best.get("parse_review") or {}, ensure_ascii=False),
                     json.dumps(best.get("diagnostics") or {}, ensure_ascii=False), status, now, receipt_id),
                )
                self._insert_candidate_lines(connection, receipt_id, best, now, preserved)
            else:
                connection.execute(
                    """UPDATE receipts SET parser_version=?,processing_state=?,processing_code=?,processing_message=?,
                       field_evidence_json=?,parse_review_json=?,parser_diagnostics_json=?,updated_at=?
                       WHERE id=?""",
                    (PARSER_VERSION, best.get("processing_state") or "needs_review", best.get("processing_code"),
                     best.get("processing_message"), json.dumps(best.get("field_evidence") or {}, ensure_ascii=False),
                     json.dumps(best.get("parse_review") or {}, ensure_ascii=False),
                     json.dumps(best.get("diagnostics") or {}, ensure_ascii=False), now, receipt_id),
                )

        if receipt["match_state"] != "manual" and not receipt["transaction_id"] and replace_facts:
            self.match_receipt(receipt_id, auto_link=True)
        result = self.get_receipt(receipt_id)
        result["reprocessed"] = True
        result["sources"] = self.list_sources(receipt_id)
        return result

    def reprocess_needing_ocr(self) -> dict[str, Any]:
        with self.repository.read_connection() as connection:
            ids = [row["id"] for row in connection.execute(
                """SELECT id FROM receipts WHERE processing_state IN
                   ('ocr_required','ocr_unavailable','ocr_failed','needs_review') ORDER BY created_at,id"""
            ).fetchall()]
        results = [self.reprocess_receipt(str(receipt_id)) for receipt_id in ids]
        return {"count": len(results), "receipts": results}

    def _refresh_review_state(self, connection: Any, receipt_ids: list[str]) -> None:
        for receipt_id in sorted(set(receipt_ids)):
            row = connection.execute(
                """SELECT r.*,COUNT(i.id) item_count,
                   SUM(CASE WHEN i.review_state='unresolved' THEN 1 ELSE 0 END) unresolved_items
                   FROM receipts r LEFT JOIN receipt_items i ON i.receipt_id=r.id
                   WHERE r.id=? GROUP BY r.id""",
                (receipt_id,),
            ).fetchone()
            if not row:
                continue
            try:
                review = json.loads(row["parse_review_json"] or "{}")
            except json.JSONDecodeError:
                review = {}
            unresolved = [
                value for value in review.get("unresolved", [])
                if value not in {"total", "purchase_date", "items"}
            ]
            if row["total_minor"] is None:
                unresolved.append("total")
            if not row["purchase_date"]:
                unresolved.append("purchase_date")
            if not int(row["item_count"] or 0) or int(row["unresolved_items"] or 0):
                unresolved.append("items")
            review["unresolved"] = list(dict.fromkeys(unresolved))
            complete = bool(
                row["retailer_key"] and row["purchase_date"] and row["total_minor"] is not None
                and int(row["item_count"] or 0) > 0 and not int(row["unresolved_items"] or 0)
                and row["validation_state"] in {"valid", "valid_with_adjustments"}
            )
            processing_state = "parsed" if complete else "needs_review"
            processing_code = None if complete else "manual_review_pending"
            status = row["status"] if row["status"] == "archived" else (
                "matched" if row["transaction_id"] else "inbox" if complete else "needs_review"
            )
            connection.execute(
                """UPDATE receipts SET parse_review_json=?,processing_state=?,processing_code=?,
                   processing_message=?,status=?,updated_at=? WHERE id=?""",
                (json.dumps(review, ensure_ascii=False), processing_state, processing_code,
                 None if complete else row["processing_message"], status, utc_now(), receipt_id),
            )

    def update_metadata(self, receipt_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        correction_source = str(payload.get("_correctionSource") or "manual")
        if correction_source not in {"manual", "guided_review"}:
            correction_source = "manual"
        updates: list[str] = []
        values: list[Any] = []
        if "merchant" in payload and str(payload.get("merchant") or "").strip():
            merchant = " ".join(str(payload.get("merchant") or "").split())[:200]
            updates.extend(["store_name=?", "retailer_key=?", "merchant_source='manual'"])
            values.extend([merchant, _retailer_key(merchant)])
        if "purchaseDate" in payload and str(payload.get("purchaseDate") or "").strip():
            purchase_date, _ = _date_parts(payload.get("purchaseDate"))
            if payload.get("purchaseDate") and not purchase_date:
                raise ReceiptValidationError("Purchase date is invalid.")
            updates.extend(["purchase_date=?", "purchase_date_source='manual'"])
            values.append(purchase_date)
        if "total" in payload and payload.get("total") not in (None, ""):
            total = _minor(payload.get("total"))
            if total is not None and total < 0:
                raise ReceiptValidationError("Receipt total cannot be negative.")
            updates.extend(["total_minor=?", "total_source='manual'"])
            values.append(total)
        if not updates:
            raise ReceiptValidationError("At least one receipt field is required.")
        with self.repository.transaction() as connection:
            row = connection.execute("SELECT * FROM receipts WHERE id=?", (receipt_id,)).fetchone()
            if not row:
                raise FinanceNotFoundError("Receipt was not found.")
            if "merchant" in payload and str(payload.get("merchant") or "").strip():
                merchant_key = _retailer_key(payload.get("merchant"))
                updates.append("retailer_id=?")
                values.append(self._merchant_id(connection, merchant_key))
            updates.extend(["processing_state='needs_review'", "processing_code='manual_metadata'", "updated_at=?"])
            values.extend([utc_now(), receipt_id])
            connection.execute(f"UPDATE receipts SET {','.join(updates)} WHERE id=?", values)
            changed_fields: list[tuple[str, Any, Any]] = []
            if "merchant" in payload and str(payload.get("merchant") or "").strip():
                changed_fields.append(("merchant", {"storeName": row["store_name"], "retailerKey": row["retailer_key"]},
                                       {"storeName": str(payload["merchant"]).strip(), "retailerKey": _retailer_key(payload["merchant"])}))
            if "purchaseDate" in payload and str(payload.get("purchaseDate") or "").strip():
                changed_fields.append(("purchase_date", {"value": row["purchase_date"]}, {"value": purchase_date}))
            if "total" in payload and payload.get("total") not in (None, ""):
                changed_fields.append(("total", {"valueMinor": row["total_minor"]}, {"valueMinor": total}))
            for field_name, previous, applied in changed_fields:
                connection.execute(
                    """INSERT INTO receipt_parse_corrections(id,receipt_id,field_name,previous_json,applied_json,source,created_at)
                       VALUES (?,?,?,?,?,?,?)""",
                    (_identifier("rcorr"), receipt_id, field_name, json.dumps(previous, ensure_ascii=False),
                     json.dumps(applied, ensure_ascii=False), correction_source, utc_now()),
                )
            try:
                evidence = json.loads(row["field_evidence_json"] or "{}")
                review = json.loads(row["parse_review_json"] or "{}")
            except json.JSONDecodeError:
                evidence, review = {}, {}
            field_map = {"merchant": "merchant", "purchaseDate": "purchaseDate", "total": "total"}
            for payload_key, evidence_key in field_map.items():
                if payload_key in payload and payload.get(payload_key) not in (None, ""):
                    evidence[evidence_key] = {"confidence": "manual", "source": correction_source}
                    review["unresolved"] = [value for value in review.get("unresolved", []) if value not in {evidence_key, "purchase_date" if evidence_key == "purchaseDate" else evidence_key}]
            connection.execute(
                "UPDATE receipts SET field_evidence_json=?,parse_review_json=? WHERE id=?",
                (json.dumps(evidence, ensure_ascii=False), json.dumps(review, ensure_ascii=False), receipt_id),
            )
            current = connection.execute("SELECT total_minor FROM receipts WHERE id=?", (receipt_id,)).fetchone()
            item_row = connection.execute(
                """SELECT COUNT(*) count,COALESCE(SUM(total_price_minor-discount_minor),0) total
                   FROM receipt_items WHERE receipt_id=?""", (receipt_id,),
            ).fetchone()
            adjustment_total = connection.execute(
                "SELECT COALESCE(SUM(amount_minor),0) FROM receipt_adjustments WHERE receipt_id=?", (receipt_id,),
            ).fetchone()[0]
            if current["total_minor"] is None or not int(item_row["count"]):
                validation_state, difference = "needs_review", None
            else:
                difference = int(current["total_minor"]) - int(item_row["total"]) - int(adjustment_total)
                validation_state = "valid" if abs(difference) <= 1 else "needs_review" if abs(difference) <= 5 else "invalid"
            connection.execute(
                "UPDATE receipts SET validation_state=?,validation_difference_minor=? WHERE id=?",
                (validation_state, difference, receipt_id),
            )
            self._refresh_review_state(connection, [receipt_id])
        if row["match_state"] != "manual" and not row["transaction_id"]:
            self.match_receipt(receipt_id, auto_link=True)
        if "merchant" in payload:
            self._learn_retailer_header_alias(receipt_id)
        return self.get_receipt(receipt_id)

    def _learn_retailer_header_alias(self, receipt_id: str) -> None:
        """Learn only after the same deterministic mapping was confirmed twice."""
        with self.repository.read_connection() as connection:
            current = connection.execute("SELECT retailer_key,retailer_id FROM receipts WHERE id=?", (receipt_id,)).fetchone()
            rows = connection.execute(
                "SELECT receipt_id,previous_json,applied_json FROM receipt_parse_corrections WHERE field_name='merchant' ORDER BY created_at",
            ).fetchall()
        if not current or not current["retailer_key"]:
            return
        mappings: dict[str, set[str]] = defaultdict(set)
        for row in rows:
            try:
                previous, applied = json.loads(row["previous_json"]), json.loads(row["applied_json"])
            except json.JSONDecodeError:
                continue
            if _retailer_key(applied.get("retailerKey")) != current["retailer_key"]:
                continue
            alias = _normalized(previous.get("storeName"))
            if len(alias) >= 3:
                mappings[alias].add(str(row["receipt_id"]))
        confirmed = sorted(alias for alias, receipts in mappings.items() if len(receipts) >= 2)
        if not confirmed:
            return
        now = utc_now()
        with self.repository.transaction() as connection:
            existing = connection.execute("SELECT knowledge_json FROM retailer_profiles WHERE retailer_key=?", (current["retailer_key"],)).fetchone()
            try:
                knowledge = json.loads(existing["knowledge_json"] or "{}") if existing else {}
            except json.JSONDecodeError:
                knowledge = {}
            knowledge["headerAliases"] = sorted(set(knowledge.get("headerAliases") or []) | set(confirmed))
            connection.execute(
                """INSERT INTO retailer_profiles(retailer_key,retailer_id,adapter_name,knowledge_json,created_at,updated_at)
                   VALUES (?,?,?,?,?,?) ON CONFLICT(retailer_key) DO UPDATE SET
                   retailer_id=excluded.retailer_id,knowledge_json=excluded.knowledge_json,updated_at=excluded.updated_at""",
                (current["retailer_key"], current["retailer_id"], "polish_fiscal_v2",
                 json.dumps(knowledge, ensure_ascii=False), now, now),
            )

    def apply_parse_review(self, receipt_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        field = str(payload.get("field") or "")
        if field == "total":
            value = payload.get("valueMinor")
            if value is None:
                raise ReceiptValidationError("A total candidate is required.")
            return self.update_metadata(receipt_id, {"total": int(value) / 100, "_correctionSource": "guided_review"})
        if field == "purchase_date":
            return self.update_metadata(receipt_id, {"purchaseDate": payload.get("value"), "_correctionSource": "guided_review"})
        if field == "item":
            item_id = str(payload.get("itemId") or "")
            accepted = payload.get("accepted")
            with self.repository.transaction() as connection:
                item = connection.execute(
                    "SELECT * FROM receipt_items WHERE id=? AND receipt_id=?", (item_id, receipt_id),
                ).fetchone()
                if not item:
                    raise FinanceNotFoundError("Receipt item was not found.")
                if accepted is False:
                    connection.execute("DELETE FROM receipt_items WHERE id=?", (item_id,))
                else:
                    evidence = json.loads(item["raw_evidence_json"] or "{}")
                    evidence["userConfirmedProductLine"] = True
                    connection.execute(
                        "UPDATE receipt_items SET raw_evidence_json=?,confidence_state='exact',updated_at=? WHERE id=?",
                        (json.dumps(evidence, ensure_ascii=False), utc_now(), item_id),
                    )
                connection.execute(
                    """INSERT INTO receipt_parse_corrections(id,receipt_id,field_name,previous_json,applied_json,source,created_at)
                       VALUES (?,?,?,?,?,'guided_review',?)""",
                    (_identifier("rcorr"), receipt_id, "item", json.dumps({"itemId": item_id}),
                     json.dumps({"accepted": bool(accepted)}), utc_now()),
                )
                totals = connection.execute(
                    """SELECT r.total_minor,COUNT(i.id) item_count,
                       COALESCE(SUM(i.total_price_minor-i.discount_minor),0) item_total
                       FROM receipts r LEFT JOIN receipt_items i ON i.receipt_id=r.id
                       WHERE r.id=? GROUP BY r.id""", (receipt_id,),
                ).fetchone()
                adjustments = connection.execute(
                    "SELECT COALESCE(SUM(amount_minor),0) FROM receipt_adjustments WHERE receipt_id=?", (receipt_id,),
                ).fetchone()[0]
                difference = None if totals["total_minor"] is None or not totals["item_count"] else int(totals["total_minor"]) - int(totals["item_total"]) - int(adjustments)
                validation = "needs_review" if difference is None else "valid" if abs(difference) <= 1 else "needs_review" if abs(difference) <= 5 else "invalid"
                connection.execute(
                    "UPDATE receipts SET validation_state=?,validation_difference_minor=?,updated_at=? WHERE id=?",
                    (validation, difference, utc_now(), receipt_id),
                )
                self._refresh_review_state(connection, [receipt_id])
            return self.get_receipt(receipt_id)
        raise ReceiptValidationError("Unsupported receipt review field.")

    def _match_candidates(self, receipt_id: str) -> tuple[Any, list[dict[str, Any]]]:
        with self.repository.read_connection() as connection:
            receipt = connection.execute("SELECT * FROM receipts WHERE id=?", (receipt_id,)).fetchone()
            if not receipt:
                raise FinanceNotFoundError("Receipt was not found.")
            if receipt["total_minor"] is None or not receipt["purchase_date"]:
                return receipt, []
            purchase = date.fromisoformat(receipt["purchase_date"])
            rows = connection.execute(
                """SELECT t.id,t.transaction_date,t.amount_minor,t.currency,t.raw_description,m.canonical_name merchant_name
                   FROM transactions t LEFT JOIN merchants m ON m.id=t.merchant_id
                   WHERE t.amount_minor=? AND t.currency=? AND t.transaction_date BETWEEN ? AND ?
                   ORDER BY ABS(julianday(t.transaction_date)-julianday(?)),t.id""",
                (-abs(int(receipt["total_minor"])), receipt["currency"], (purchase - timedelta(days=2)).isoformat(),
                 (purchase + timedelta(days=2)).isoformat(), purchase.isoformat()),
            ).fetchall()
        candidates = []
        for row in rows:
            same_date = row["transaction_date"] == receipt["purchase_date"]
            haystack = _normalized(f"{row['merchant_name'] or ''} {row['raw_description']}")
            merchant_match = bool(receipt["retailer_key"] and receipt["retailer_key"] in haystack)
            evidence = ["amount_exact"]
            if same_date:
                evidence.append("date_exact")
            else:
                evidence.append("date_near")
            if merchant_match:
                evidence.append("retailer_exact")
            score = (4 if same_date else 2) + (4 if merchant_match else 0)
            candidates.append({
                "transactionId": row["id"], "date": row["transaction_date"],
                "merchant": row["merchant_name"] or row["raw_description"],
                "amount": row["amount_minor"] / 100, "currency": row["currency"],
                "evidence": evidence, "score": score,
            })
        return receipt, candidates

    def match_receipt(self, receipt_id: str, transaction_id: str | None = None, auto_link: bool = False) -> dict[str, Any]:
        receipt, candidates = self._match_candidates(receipt_id)
        if transaction_id:
            selected = next((item for item in candidates if item["transactionId"] == transaction_id), None)
            if not selected:
                with self.repository.read_connection() as connection:
                    exists = connection.execute("SELECT id FROM transactions WHERE id=?", (transaction_id,)).fetchone()
                if not exists:
                    raise FinanceNotFoundError("Transaction was not found.")
            self._link(receipt_id, transaction_id, "manual")
            return {"state": "manual", "linked": True, "transactionId": transaction_id, "candidates": candidates}
        if not candidates:
            self._set_match_state(receipt_id, "none")
            return {"state": "none", "linked": False, "candidates": []}
        top_score = max(item["score"] for item in candidates)
        top = [item for item in candidates if item["score"] == top_score]
        if len(top) != 1:
            self._set_match_state(receipt_id, "ambiguous")
            return {"state": "ambiguous", "linked": False, "candidates": candidates}
        best = top[0]
        if "date_exact" in best["evidence"] and "retailer_exact" in best["evidence"]:
            state = "exact"
        elif "retailer_exact" in best["evidence"] and len(candidates) == 1:
            state = "strong"
        else:
            state = "ambiguous" if len(candidates) > 1 else "none"
        if auto_link and state in {"exact", "strong"}:
            self._link(receipt_id, best["transactionId"], state)
            return {"state": state, "linked": True, "transactionId": best["transactionId"], "candidates": candidates}
        self._set_match_state(receipt_id, state)
        return {"state": state, "linked": False, "candidates": candidates}

    def _set_match_state(self, receipt_id: str, state: str) -> None:
        with self.repository.transaction() as connection:
            connection.execute("UPDATE receipts SET match_state=?,updated_at=? WHERE id=?", (state, utc_now(), receipt_id))

    def _link(self, receipt_id: str, transaction_id: str, state: str) -> None:
        try:
            with self.repository.transaction() as connection:
                connection.execute(
                    "UPDATE receipts SET transaction_id=?,match_state=?,status='matched',updated_at=? WHERE id=?",
                    (transaction_id, state, utc_now(), receipt_id),
                )
        except Exception as exc:
            if "UNIQUE constraint failed" in str(exc):
                raise ReceiptValidationError("That transaction already has a linked receipt.") from exc
            raise

    def transaction_indicators(self, transaction_ids: list[str]) -> dict[str, dict[str, Any]]:
        if not transaction_ids:
            return {}
        placeholders = ",".join("?" for _ in transaction_ids)
        with self.repository.read_connection() as connection:
            rows = connection.execute(
                f"SELECT transaction_id,id,validation_state FROM receipts WHERE transaction_id IN ({placeholders})", transaction_ids,
            ).fetchall()
        return {row["transaction_id"]: {"id": row["id"], "validationState": row["validation_state"]} for row in rows}

    def product_categories(self) -> list[dict[str, Any]]:
        with self.repository.read_connection() as connection:
            rows = connection.execute(
                """SELECT c.*,p.name parent_name,fc.name finance_name,fp.name finance_parent
                   FROM product_categories c LEFT JOIN product_categories p ON p.id=c.parent_id
                   LEFT JOIN categories fc ON fc.id=c.finance_category_id LEFT JOIN categories fp ON fp.id=fc.parent_id
                   WHERE c.is_active=1 ORDER BY c.sort_order,c.name"""
            ).fetchall()
        return [{"id": row["id"], "name": row["name"], "parentId": row["parent_id"], "parentName": row["parent_name"],
                 "financeCategoryId": row["finance_category_id"], "financeCategory": " → ".join(part for part in (row["finance_parent"], row["finance_name"]) if part)} for row in rows]

    def create_product(self, payload: dict[str, Any], status: str = "active") -> dict[str, Any]:
        name = " ".join(str(payload.get("name") or payload.get("canonicalName") or "").split())
        if not name:
            raise ReceiptValidationError("Product name is required.")
        barcode = str(payload.get("barcode") or "").strip() or None
        if barcode and not BARCODE_RE.fullmatch(barcode):
            raise ReceiptValidationError("Barcode must be EAN-8, UPC-A, UPC-E, or EAN-13 digits.")
        product_id = _identifier("prod")
        now = utc_now()
        category_id = int(payload["productCategoryId"]) if payload.get("productCategoryId") else None
        with self.repository.transaction() as connection:
            connection.execute(
                """INSERT INTO products(id,canonical_name,normalized_name,brand,canonical_barcode,package_quantity,package_unit,
                   product_category_id,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (product_id, name, _normalized(name), str(payload.get("brand") or "").strip() or None, barcode,
                 str(payload.get("packageQuantity") or "").strip() or None, str(payload.get("packageUnit") or "").strip() or None,
                 category_id, status, now, now),
            )
            if barcode:
                connection.execute("INSERT INTO product_barcodes(barcode,product_id,source,confirmed,created_at) VALUES (?,?,?,1,?)", (barcode, product_id, "manual", now))
        return self.product_detail(product_id)

    def lookup_barcode(self, barcode: str) -> dict[str, Any]:
        barcode = str(barcode or "").strip()
        if not BARCODE_RE.fullmatch(barcode):
            raise ReceiptValidationError("Unsupported barcode format.")
        with self.repository.read_connection() as connection:
            row = connection.execute("SELECT product_id FROM product_barcodes WHERE barcode=?", (barcode,)).fetchone()
        return {"barcode": barcode, "known": bool(row), "product": self.product_detail(str(row["product_id"])) if row else None}

    def save_pending_barcode(self, payload: dict[str, Any]) -> dict[str, Any]:
        barcode = str(payload.get("barcode") or "").strip()
        known = self.lookup_barcode(barcode)
        if known["known"]:
            return known
        name = str(payload.get("name") or f"Produkt {barcode}").strip()
        product = self.create_product({"name": name, "barcode": barcode}, status="pending")
        return {"barcode": barcode, "known": False, "pending": True, "product": product}

    def product_detail(self, product_id: str) -> dict[str, Any]:
        with self.repository.read_connection() as connection:
            row = connection.execute(
                """SELECT p.*,c.name category_name FROM products p LEFT JOIN product_categories c ON c.id=p.product_category_id WHERE p.id=?""",
                (product_id,),
            ).fetchone()
            if not row:
                raise FinanceNotFoundError("Product was not found.")
            aliases = connection.execute(
                "SELECT retailer_key,raw_name,retailer_code,source,confirmed FROM retailer_product_aliases WHERE product_id=? ORDER BY retailer_key,raw_name", (product_id,),
            ).fetchall()
            history = connection.execute(
                """SELECT r.purchase_date,r.retailer_key,i.quantity,i.unit,i.unit_price_minor,i.total_price_minor,i.discount_minor
                   FROM receipt_items i JOIN receipts r ON r.id=i.receipt_id
                   WHERE i.product_id=? AND r.purchase_date IS NOT NULL ORDER BY r.purchase_date DESC,i.id DESC""", (product_id,),
            ).fetchall()
        prices = [{"date": item["purchase_date"], "retailer": item["retailer_key"], "quantity": item["quantity"], "unit": item["unit"],
                   "unitPrice": item["unit_price_minor"] / 100 if item["unit_price_minor"] is not None else None,
                   "linePrice": item["total_price_minor"] / 100, "effectivePrice": (item["total_price_minor"] - item["discount_minor"]) / 100} for item in history]
        effective = [item["effectivePrice"] for item in prices]
        return {
            "id": row["id"], "canonicalName": row["canonical_name"], "brand": row["brand"], "barcode": row["canonical_barcode"],
            "packageQuantity": row["package_quantity"], "packageUnit": row["package_unit"],
            "productCategoryId": row["product_category_id"], "productCategory": row["category_name"], "status": row["status"],
            "retailerAliases": [dict(item) for item in aliases], "purchaseCount": len(prices),
            "lastPurchase": prices[0]["date"] if prices else None, "lastPrice": effective[0] if effective else None,
            "lowestPrice": min(effective) if effective else None, "highestPrice": max(effective) if effective else None,
            "priceHistory": prices,
        }

    def review_groups(self) -> list[dict[str, Any]]:
        with self.repository.read_connection() as connection:
            rows = connection.execute(
                """SELECT r.retailer_key,i.normalized_name,MIN(i.raw_name) raw_name,MIN(i.id) sample_item_id,
                   MIN(i.total_price_minor-i.discount_minor) sample_price_minor,COUNT(*) item_count,
                   CASE WHEN COUNT(DISTINCT NULLIF(i.raw_product_code,''))=1
                        THEN MIN(NULLIF(i.raw_product_code,'')) END retailer_code,
                   CASE WHEN COUNT(DISTINCT NULLIF(i.barcode,''))=1
                        THEN MIN(NULLIF(i.barcode,'')) END barcode,
                   SUM(ABS(i.total_price_minor-i.discount_minor)) impact_minor,MAX(r.purchase_date) newest
                   FROM receipt_items i JOIN receipts r ON r.id=i.receipt_id
                   WHERE i.review_state='unresolved'
                     AND (json_extract(i.raw_evidence_json,'$.credibleProductLine')=1 OR i.confidence_state='exact')
                   GROUP BY r.retailer_key,i.normalized_name ORDER BY impact_minor DESC,item_count DESC"""
            ).fetchall()
        groups = []
        for row in rows:
            group_id = hashlib.sha256(f"{row['retailer_key']}|{row['normalized_name']}".encode()).hexdigest()[:24]
            with self.repository.read_connection() as connection:
                sample = connection.execute(
                    "SELECT raw_evidence_json FROM receipt_items WHERE id=?", (row["sample_item_id"],),
                ).fetchone()
            try:
                evidence = json.loads(sample["raw_evidence_json"] or "{}") if sample else {}
            except json.JSONDecodeError:
                evidence = {}
            groups.append({"id": group_id, "retailerKey": row["retailer_key"], "rawName": row["raw_name"],
                           "retailerCode": row["retailer_code"], "barcode": row["barcode"],
                           "normalizedName": row["normalized_name"], "itemCount": row["item_count"],
                           "impact": row["impact_minor"] / 100, "newest": row["newest"],
                           "sampleItemId": row["sample_item_id"], "samplePrice": row["sample_price_minor"] / 100,
                           "sourceLine": evidence.get("sourceLine"),
                           "cropUrl": f"/api/budget/receipt-items/{row['sample_item_id']}/crop" if evidence.get("box") else None,
                           "nameConfidence": "strong" if len(re.sub(r"[^A-Za-zÀ-ž]", "", row["raw_name"])) >= 4 and not re.search(r"\d", row["raw_name"]) else "weak"})
        return groups

    def _group(self, group_id: str) -> dict[str, Any]:
        group = next((item for item in self.review_groups() if item["id"] == group_id), None)
        if not group:
            raise FinanceNotFoundError("Receipt-item review group was not found.")
        return group

    def review_preview(self, group_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        group = self._group(group_id)
        product_id = str(payload.get("productId") or "") or None
        category_id = int(payload["productCategoryId"]) if payload.get("productCategoryId") else None
        if not product_id and not category_id and not str(payload.get("canonicalName") or "").strip():
            raise ReceiptValidationError("Product, product name, or item category is required.")
        return {"group": group, "changes": {"items": group["itemCount"], "rememberAlias": bool(payload.get("remember"))},
                "protected": ["transaction amounts", "bank facts", "already resolved receipt items"]}

    def review_apply(self, group_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        preview = self.review_preview(group_id, payload)
        group = preview["group"]
        product_id = str(payload.get("productId") or "") or None
        if not product_id and str(payload.get("canonicalName") or "").strip():
            product_payload = dict(payload)
            if group.get("barcode") and not product_payload.get("barcode"):
                product_payload["barcode"] = group["barcode"]
            product_id = self.create_product(product_payload)["id"]
        category_id = int(payload["productCategoryId"]) if payload.get("productCategoryId") else None
        now = utc_now()
        action_id = _identifier("ribulk")
        with self.repository.transaction() as connection:
            if product_id:
                product = connection.execute("SELECT product_category_id FROM products WHERE id=?", (product_id,)).fetchone()
                if not product:
                    raise FinanceNotFoundError("Product was not found.")
                category_id = category_id or product["product_category_id"]
            rows = connection.execute(
                """SELECT i.id,i.receipt_id,i.product_id,i.product_category_id,i.review_state FROM receipt_items i JOIN receipts r ON r.id=i.receipt_id
                   WHERE r.retailer_key=? AND i.normalized_name=? AND i.review_state='unresolved'""",
                (group["retailerKey"], group["normalizedName"]),
            ).fetchall()
            previous = [dict(row) for row in rows]
            ids = [row["id"] for row in rows]
            for item_id in ids:
                connection.execute(
                    """UPDATE receipt_items SET product_id=?,product_category_id=?,classification_source='guided_review',
                       review_state='resolved',updated_at=? WHERE id=? AND review_state='unresolved'""",
                    (product_id, category_id, now, item_id),
                )
            alias_id = None
            if payload.get("remember") and product_id:
                retailer_code = str(group.get("retailerCode") or "") or None
                alias_key = hashlib.sha256(f"{group['retailerKey']}|{retailer_code or ''}|{group['normalizedName']}".encode()).hexdigest()
                connection.execute(
                    """INSERT INTO retailer_product_aliases(retailer_key,raw_name,normalized_name,retailer_code,alias_key,
                       product_id,source,confirmed,created_at,updated_at) VALUES (?,?,?,?,?,?,?,1,?,?)
                       ON CONFLICT(alias_key) DO UPDATE SET product_id=excluded.product_id,source=excluded.source,
                       confirmed=1,updated_at=excluded.updated_at""",
                    (group["retailerKey"], group["rawName"], group["normalizedName"], retailer_code, alias_key, product_id, "guided_review", now, now),
                )
                alias_id = connection.execute("SELECT id FROM retailer_product_aliases WHERE alias_key=?", (alias_key,)).fetchone()[0]
            applied = {"product_id": product_id, "product_category_id": category_id, "review_state": "resolved", "item_ids": ids}
            connection.execute(
                """INSERT INTO receipt_item_bulk_actions(id,group_id,item_count,previous_json,applied_json,alias_id,created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (action_id, group_id, len(ids), json.dumps(previous), json.dumps(applied), alias_id, now),
            )
            self._refresh_review_state(connection, [str(row["receipt_id"]) for row in rows])
        return {"actionId": action_id, "updated": len(ids), "remembered": bool(alias_id), "preview": preview}

    def classify_item(self, item_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self.repository.read_connection() as connection:
            row = connection.execute(
                """SELECT r.retailer_key,i.normalized_name FROM receipt_items i
                   JOIN receipts r ON r.id=i.receipt_id WHERE i.id=?""", (item_id,),
            ).fetchone()
        if not row:
            raise FinanceNotFoundError("Receipt item was not found.")
        group_id = hashlib.sha256(f"{row['retailer_key']}|{row['normalized_name']}".encode()).hexdigest()[:24]
        return self.review_apply(group_id, payload)

    def undo_latest_review(self) -> dict[str, Any]:
        now = utc_now()
        with self.repository.transaction() as connection:
            action = connection.execute("SELECT * FROM receipt_item_bulk_actions WHERE undone_at IS NULL ORDER BY created_at DESC,id DESC LIMIT 1").fetchone()
            if not action:
                raise FinanceNotFoundError("There is no receipt-item bulk action to undo.")
            applied = json.loads(action["applied_json"])
            restored = 0
            for previous in json.loads(action["previous_json"]):
                current = connection.execute("SELECT product_id,product_category_id,review_state FROM receipt_items WHERE id=?", (previous["id"],)).fetchone()
                if not current:
                    continue
                if current["product_id"] == applied.get("product_id") and current["product_category_id"] == applied.get("product_category_id") and current["review_state"] == "resolved":
                    connection.execute(
                        "UPDATE receipt_items SET product_id=?,product_category_id=?,review_state=?,classification_source='unresolved',updated_at=? WHERE id=?",
                        (previous["product_id"], previous["product_category_id"], previous["review_state"], now, previous["id"]),
                    )
                    restored += 1
            if action["alias_id"]:
                connection.execute("DELETE FROM retailer_product_aliases WHERE id=? AND source='guided_review'", (action["alias_id"],))
            connection.execute("UPDATE receipt_item_bulk_actions SET undone_at=? WHERE id=?", (now, action["id"]))
        return {"actionId": action["id"], "restored": restored}

    def data_quality(self) -> dict[str, Any]:
        with self.repository.read_connection() as connection:
            row = connection.execute(
                """SELECT COUNT(*) receipts,
                   SUM(CASE WHEN transaction_id IS NOT NULL THEN 1 ELSE 0 END) matched,
                   SUM(CASE WHEN transaction_id IS NULL THEN 1 ELSE 0 END) needs_match
                   FROM receipts"""
            ).fetchone()
            items = connection.execute(
                """SELECT COUNT(*) items,SUM(CASE WHEN review_state='resolved' THEN 1 ELSE 0 END) classified,
                   SUM(CASE WHEN product_id IS NULL THEN 1 ELSE 0 END) unknown_products FROM receipt_items"""
            ).fetchone()
            mixed = connection.execute(
                """SELECT COALESCE(SUM(ABS(t.amount_minor)),0) total,
                   COALESCE(SUM(CASE WHEN r.id IS NOT NULL THEN ABS(t.amount_minor) ELSE 0 END),0) covered
                   FROM transactions t LEFT JOIN merchants m ON m.id=t.merchant_id
                   LEFT JOIN receipts r ON r.transaction_id=t.id AND r.validation_state IN ('valid','valid_with_adjustments')
                   WHERE t.transaction_kind='expense' AND (m.normalized_name IN ('biedronka','zabka','lidl','carrefour','auchan','kaufland','aldi','netto')
                     OR lower(t.raw_description) LIKE '%biedronka%' OR lower(t.raw_description) LIKE '%zabka%')"""
            ).fetchone()
        total = int(mixed["total"] or 0); covered = int(mixed["covered"] or 0); item_total = int(items["items"] or 0); classified = int(items["classified"] or 0)
        receipts = int(row["receipts"] or 0); matched = int(row["matched"] or 0)
        return {
            "receiptsImported": receipts, "matchedToTransactions": matched, "needsMatch": int(row["needs_match"] or 0),
            "itemsParsed": item_total, "itemsClassified": classified, "unknownProducts": int(items["unknown_products"] or 0),
            "receiptMatchRate": round(matched * 100 / receipts, 1) if receipts else 0,
            "itemClassificationCoverage": round(classified * 100 / item_total, 1) if item_total else 0,
            "mixedRetailerSpend": total / 100, "mixedRetailerSpendCovered": covered / 100,
            "mixedRetailerSpendUncovered": (total - covered) / 100,
            "mixedRetailerCoveragePercent": round(covered * 100 / total, 1) if total else 0,
        }

    def analytics_category_breakdown(self, period: dict[str, Any]) -> list[dict[str, Any]]:
        """Return one category representation per expense, using safe receipt splits when complete."""
        date_from = period.get("dateFrom") or period.get("periodStart") or period.get("period_start")
        date_to = period.get("dateTo") or period.get("periodEnd") or period.get("period_end")
        with self.repository.read_connection() as connection:
            transactions = connection.execute(
                """SELECT t.id,ABS(t.amount_minor) amount_minor,t.category_id,c.name category_name,
                   p.id parent_id,p.name parent_name,r.id receipt_id,r.total_minor,r.validation_state
                   FROM transactions t LEFT JOIN categories c ON c.id=t.category_id
                   LEFT JOIN categories p ON p.id=c.parent_id
                   LEFT JOIN receipts r ON r.transaction_id=t.id
                   WHERE t.transaction_kind='expense' AND t.transaction_date BETWEEN ? AND ?""",
                (date_from, date_to),
            ).fetchall()
            receipt_ids = [row["receipt_id"] for row in transactions if row["receipt_id"]]
            items_by_receipt: dict[str, list[Any]] = defaultdict(list)
            adjustments_by_receipt: dict[str, list[Any]] = defaultdict(list)
            if receipt_ids:
                placeholders = ",".join("?" for _ in receipt_ids)
                for row in connection.execute(
                    f"""SELECT i.receipt_id,i.total_price_minor-i.discount_minor effective_minor,
                        pc.finance_category_id,c.name category_name,p.id parent_id,p.name parent_name
                        FROM receipt_items i LEFT JOIN product_categories pc ON pc.id=i.product_category_id
                        LEFT JOIN categories c ON c.id=pc.finance_category_id LEFT JOIN categories p ON p.id=c.parent_id
                        WHERE i.receipt_id IN ({placeholders})""", receipt_ids,
                ).fetchall():
                    items_by_receipt[row["receipt_id"]].append(row)
                for row in connection.execute(
                    f"SELECT receipt_id,kind,amount_minor FROM receipt_adjustments WHERE receipt_id IN ({placeholders})",
                    receipt_ids,
                ).fetchall():
                    adjustments_by_receipt[row["receipt_id"]].append(row)

        buckets: dict[str, dict[str, Any]] = {}

        def add(key: str, category_id: Any, name: str, parent_id: Any, parent_name: str | None,
                amount_minor: int, transaction_id: str, source: str) -> None:
            entry = buckets.setdefault(key, {
                "id": category_id, "name": name, "parentId": parent_id, "parentName": parent_name,
                "amountMinor": 0, "transactionIds": set(), "source": source,
            })
            entry["amountMinor"] += amount_minor
            entry["transactionIds"].add(transaction_id)
            if entry["source"] != source:
                entry["source"] = "transaction_and_receipt"

        adjustment_names = {
            "deposit": "Kaucje i opakowania", "rounding": "Zaokrąglenia", "coupon": "Kupony",
            "discount": "Rabaty ogólne", "return": "Zwroty pozycji", "other": "Inne korekty paragonu",
        }
        for transaction in transactions:
            receipt_id = transaction["receipt_id"]
            items = items_by_receipt.get(receipt_id, []) if receipt_id else []
            adjustments = adjustments_by_receipt.get(receipt_id, []) if receipt_id else []
            composition_total = sum(int(item["effective_minor"]) for item in items) + sum(int(item["amount_minor"]) for item in adjustments)
            eligible = bool(
                receipt_id and transaction["validation_state"] in {"valid", "valid_with_adjustments"}
                and items and all(item["finance_category_id"] is not None for item in items)
                and transaction["total_minor"] is not None
                and abs(int(transaction["amount_minor"]) - int(transaction["total_minor"])) <= 1
                and abs(int(transaction["amount_minor"]) - composition_total) <= 1
            )
            if not eligible:
                category_id = transaction["category_id"]
                add(f"category:{category_id}", category_id, transaction["category_name"] or "Unclassified",
                    transaction["parent_id"], transaction["parent_name"], int(transaction["amount_minor"]), transaction["id"], "transaction")
                continue
            for item in items:
                category_id = item["finance_category_id"]
                add(f"category:{category_id}", category_id, item["category_name"] or "Unclassified",
                    item["parent_id"], item["parent_name"], int(item["effective_minor"]), transaction["id"], "receipt_items")
            for adjustment in adjustments:
                kind = str(adjustment["kind"] or "other")
                add(f"receipt-adjustment:{kind}", f"receipt-adjustment:{kind}", adjustment_names.get(kind, adjustment_names["other"]),
                    None, "Paragon", int(adjustment["amount_minor"]), transaction["id"], "receipt_adjustments")
        return sorted(({
            "id": entry["id"], "name": entry["name"], "parentId": entry["parentId"],
            "parentName": entry["parentName"], "amount": entry["amountMinor"] / 100,
            "transactionCount": len(entry["transactionIds"]), "source": entry["source"],
        } for entry in buckets.values()), key=lambda item: (-item["amount"], item["name"]))

    def pair_device(self, name: str) -> dict[str, Any]:
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        device_id = _identifier("device")
        now = utc_now()
        with self.repository.transaction() as connection:
            connection.execute(
                "INSERT INTO finance_companion_devices(id,name,token_hash,created_at) VALUES (?,?,?,?)",
                (device_id, " ".join(str(name or "Dashboard Companion").split())[:80], token_hash, now),
            )
        return {"id": device_id, "name": name or "Dashboard Companion", "token": token, "createdAt": now}

    def validate_device_token(self, token: str, touch: bool = True) -> bool:
        supplied = hashlib.sha256(str(token or "").encode()).hexdigest()
        with self.repository.read_connection() as connection:
            rows = connection.execute("SELECT id,token_hash FROM finance_companion_devices WHERE revoked_at IS NULL").fetchall()
        matched = next((row for row in rows if hmac.compare_digest(supplied, row["token_hash"])), None)
        if matched and touch:
            with self.repository.transaction() as connection:
                connection.execute("UPDATE finance_companion_devices SET last_used_at=? WHERE id=?", (utc_now(), matched["id"]))
        return bool(matched)

    def devices(self) -> list[dict[str, Any]]:
        with self.repository.read_connection() as connection:
            rows = connection.execute("SELECT id,name,created_at,last_used_at,revoked_at FROM finance_companion_devices ORDER BY created_at DESC").fetchall()
        return [{"id": row["id"], "name": row["name"], "createdAt": row["created_at"], "lastUsedAt": row["last_used_at"], "revokedAt": row["revoked_at"]} for row in rows]

    def revoke_device(self, device_id: str) -> dict[str, Any]:
        with self.repository.transaction() as connection:
            changed = connection.execute("UPDATE finance_companion_devices SET revoked_at=? WHERE id=? AND revoked_at IS NULL", (utc_now(), device_id)).rowcount
        if not changed:
            raise FinanceNotFoundError("Active companion device was not found.")
        return {"id": device_id, "revoked": True}
