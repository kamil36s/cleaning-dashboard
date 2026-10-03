"""Deterministic, evidence-preserving parser for Polish fiscal receipts.

The parser deliberately keeps OCR interpretation separate from storage and from
cash-flow facts.  It accepts either flat OCR text or ML Kit line geometry and
returns canonical candidates, traceable evidence, and compact diagnostics.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any


CONFIDENCE = {"exact", "strong", "weak", "manual", "unknown"}
MONEY_RE = re.compile(
    r"(?<![\w,.])(?P<sign>[-−]?)\s*(?P<whole>[0-9OIl]{1,6})\s*[,.]\s*(?P<cents>[0-9OIl]{2})(?:\s*(?P<tax>[A-F]))?(?![\d,.])",
    re.IGNORECASE,
)
DATE_PATTERNS = (
    re.compile(r"(?<!\d)(20\d{2})[-./](\d{1,2})[-./](\d{1,2})(?!\d)"),
    re.compile(r"(?<!\d)(\d{1,2})[-./](\d{1,2})[-./](20\d{2})(?!\d)"),
)
TIME_RE = re.compile(r"(?<!\d)([01]?\d|2[0-3])[:.]([0-5]\d)(?::([0-5]\d))?(?!\d)")
QUANTITY_RE = re.compile(
    r"(?P<quantity>\d+(?:[,.]\d{1,3})?)\s*(?P<unit>szt\.?|kg|g|l|ml)?\s*[xX*]\s*"
    r"(?P<unit_price>[0-9OIl]{1,6}\s*[,.]\s*[0-9OIl]{2})(?:\s*[A-F])?"
    r"(?:\s+(?P<line_total>[0-9OIl]{1,6}\s*[,.]\s*[0-9OIl]{2})\s*(?P<tax>[A-F])?)?",
    re.IGNORECASE,
)
LOOSE_QUANTITY_RE = re.compile(
    r"^(?P<prefix>.*?)\b(?P<quantity>\d+(?:[,.]\d{1,3})?)\s*(?P<unit>szt\.?|kg|g|l|ml)?\s*(?:[xX*]\s*)?"
    r"(?P<unit_price>[0-9OIl]{1,6}\s*[,.]\s*[0-9OIl]{2})(?:\s*[A-F])?\s+"
    r"(?P<line_total>[0-9OIl]{1,6}\s*[,.]\s*[0-9OIl]{2})\s*(?P<tax>[A-F])?\s*$",
    re.IGNORECASE,
)


def fold(value: Any) -> str:
    text = " ".join(str(value or "").replace("\u00a0", " ").split()).casefold()
    text = text.translate(str.maketrans({"ł": "l", "đ": "d", "ø": "o"}))
    return "".join(
        character for character in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(character)
    )


def _minor(value: str) -> int | None:
    normalized = value.replace(" ", "").replace("−", "-")
    normalized = re.sub(r"(?<=\d)[Oo](?=\d|[,.])|(?<=[,.])[Oo](?=\d)", "0", normalized)
    normalized = re.sub(r"(?<=\d)[Il](?=\d|[,.])|(?<=[,.])[Il](?=\d)", "1", normalized)
    try:
        return int((Decimal(normalized.replace(",", ".")) * 100).quantize(Decimal("1")))
    except (InvalidOperation, ValueError):
        return None


def _box(value: Any) -> dict[str, float] | None:
    if not isinstance(value, dict):
        return None
    try:
        result = {key: max(0.0, min(1.0, float(value[key]))) for key in ("x", "y", "width", "height")}
    except (KeyError, TypeError, ValueError):
        return None
    if result["width"] <= 0 or result["height"] <= 0:
        return None
    result["width"] = min(result["width"], 1.0 - result["x"])
    result["height"] = min(result["height"], 1.0 - result["y"])
    return result


def sanitize_ocr_structure(value: Any, *, max_pages: int = 20, max_lines: int = 2500) -> dict[str, Any]:
    """Validate the non-executable subset of Android OCR geometry we persist."""
    pages = value.get("pages") if isinstance(value, dict) else None
    if not isinstance(pages, list):
        return {"pages": []}
    clean_pages: list[dict[str, Any]] = []
    remaining = max_lines
    for page_index, page in enumerate(pages[:max_pages], start=1):
        if not isinstance(page, dict) or remaining <= 0:
            continue
        try:
            width = max(1, min(20000, int(page.get("width") or 1)))
            height = max(1, min(40000, int(page.get("height") or 1)))
        except (TypeError, ValueError):
            width, height = 1, 1
        clean_lines = []
        for line in (page.get("lines") if isinstance(page.get("lines"), list) else [])[:remaining]:
            if not isinstance(line, dict):
                continue
            text = str(line.get("text") or "")[:1000]
            if not text.strip():
                continue
            elements = []
            for element in (line.get("elements") if isinstance(line.get("elements"), list) else [])[:100]:
                if not isinstance(element, dict) or not str(element.get("text") or "").strip():
                    continue
                elements.append({"text": str(element.get("text"))[:250], "box": _box(element.get("box"))})
            clean_lines.append({
                "text": text,
                "box": _box(line.get("box")),
                "block": max(0, min(10000, int(line.get("block") or 0))),
                "elements": elements,
            })
        remaining -= len(clean_lines)
        clean_pages.append({
            "pageNumber": max(1, int(page.get("pageNumber") or page_index)),
            "width": width,
            "height": height,
            "lines": clean_lines,
        })
    return {"pages": clean_pages}


def _normalize_numeric_context(raw: str) -> tuple[str, list[dict[str, str]]]:
    corrected = raw.replace("\u00a0", " ")
    corrections: list[dict[str, str]] = []

    def replace_money(match: re.Match[str]) -> str:
        original = match.group(0)
        if re.search(r"[Il]$", original) and raw[match.end():match.end() + 1] == "-":
            return original
        whole = match.group("whole").translate(str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1"}))
        cents = match.group("cents").translate(str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1"}))
        normalized = f"{'-' if match.group('sign') else ''}{whole},{cents}{(match.group('tax') or '').upper()}"
        if normalized != "".join(original.split()):
            corrections.append({"raw": original, "normalized": normalized, "reason": "numeric_context"})
        return normalized

    corrected = MONEY_RE.sub(replace_money, corrected)
    currency = re.sub(r"\bPL[HNM]\b", "PLN", corrected, flags=re.IGNORECASE)
    if currency != corrected:
        corrections.append({"raw": corrected, "normalized": currency, "reason": "currency_context"})
        corrected = currency
    corrected = re.sub(r"([,.])\1+", r"\1", corrected)
    return " ".join(corrected.split()), corrections


def normalize_ocr(raw_text: str, structure: Any = None) -> dict[str, Any]:
    clean_structure = sanitize_ocr_structure(structure)
    lines: list[dict[str, Any]] = []
    if clean_structure["pages"]:
        for page in clean_structure["pages"]:
            ordered = sorted(
                enumerate(page["lines"]),
                key=lambda pair: (
                    pair[1]["box"]["y"] if pair[1].get("box") else pair[0] / max(1, len(page["lines"])),
                    pair[1]["box"]["x"] if pair[1].get("box") else 0,
                ),
            )
            for original_index, line in ordered:
                normalized, corrections = _normalize_numeric_context(line["text"])
                lines.append({
                    "raw": line["text"], "text": normalized, "folded": fold(normalized),
                    "page": page["pageNumber"], "box": line.get("box"), "elements": line.get("elements") or [],
                    "sourceIndex": original_index, "corrections": corrections,
                })
    else:
        for index, raw in enumerate(str(raw_text or "").splitlines()):
            if not raw.strip():
                continue
            normalized, corrections = _normalize_numeric_context(raw)
            lines.append({
                "raw": raw, "text": normalized, "folded": fold(normalized), "page": 1,
                "box": None, "elements": [], "sourceIndex": index, "corrections": corrections,
            })
    for index, line in enumerate(lines):
        line["index"] = index
    return {"lines": lines, "structure": clean_structure, "hasGeometry": any(line.get("box") for line in lines)}


def _anchor(line: dict[str, Any]) -> str | None:
    text = line["folded"]
    compact = re.sub(r"[^a-z0-9]", "", text)
    if (("paragon" in text or "paragow" in text) and ("fiskal" in text or "fiska" in text)) or "paragonfiskalny" in compact:
        return "fiscal"
    if "do zap" in text and ("lat" in text or "iat" in text):
        return "total_due"
    if re.search(r"\b(?:suma|suha)\s+pl[nmh]\b", text) or any(marker in compact for marker in ("sumapln", "sumaplh", "suhapln")):
        return "total_sum"
    if "suma ptu" in text or "sprzed" in text and "opod" in text:
        return "tax"
    if re.search(r"\bptu\b", text) and any(character in text for character in "%abcdef"):
        return "tax"
    if "rozliczenie" in text and "plat" in text:
        return "payment"
    if re.match(r"^(platnosc|karta|gotowka|wplacono razem)\b", text):
        return "payment"
    if any(marker in text for marker in (
        "numer transakcji", "autoryzac", "zapraszamy", "dziekujemy", "polityka zwrot",
        "zwrot towar", "www.", "facebook", "regulamin", "reklamac",
    )):
        return "footer"
    return None


def detect_sections(lines: list[dict[str, Any]]) -> dict[str, Any]:
    anchors: list[dict[str, Any]] = []
    for line in lines:
        kind = _anchor(line)
        line["anchor"] = kind
        if kind:
            anchors.append({"kind": kind, "line": line["index"], "page": line["page"], "box": line.get("box")})
    fiscal = next((entry["line"] for entry in anchors if entry["kind"] == "fiscal"), None)
    hard_end = next((entry["line"] for entry in anchors if entry["kind"] in {"tax", "total_due", "total_sum", "payment"} and (fiscal is None or entry["line"] > fiscal)), None)
    footer = next((entry["line"] for entry in anchors if entry["kind"] == "footer" and (hard_end is None or entry["line"] > hard_end)), None)
    if fiscal is not None and hard_end is not None and hard_end > fiscal + 1:
        item_range = (fiscal + 1, hard_end)
    else:
        item_range = (0, hard_end if hard_end is not None else footer if footer is not None else len(lines))
    for line in lines:
        index = line["index"]
        if fiscal is not None and index <= fiscal:
            line["zone"] = "header"
        elif item_range[0] <= index < item_range[1]:
            line["zone"] = "items"
        elif line.get("anchor") == "tax" or (hard_end is not None and index >= hard_end and "ptu" in line["folded"]):
            line["zone"] = "tax"
        elif line.get("anchor") in {"total_due", "total_sum"}:
            line["zone"] = "total"
        elif line.get("anchor") == "payment":
            line["zone"] = "payment"
        elif footer is not None and index >= footer:
            line["zone"] = "footer"
        elif hard_end is not None and index >= hard_end:
            line["zone"] = "summary"
        else:
            line["zone"] = "header"
    return {"anchors": anchors, "itemRange": item_range, "hasFiscalAnchor": fiscal is not None}


def _amounts(line: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for match in MONEY_RE.finditer(line["text"]):
        value = _minor(match.group(0).rstrip("ABCDEFabcdef "))
        if value is None:
            continue
        result.append({
            "minor": value, "raw": match.group(0), "taxGroup": (match.group("tax") or "").upper() or None,
            "line": line["index"], "page": line["page"], "box": line.get("box"),
        })
    return result


def _valid_date(year: int, month: int, day: int) -> str | None:
    try:
        parsed = date(year, month, day)
    except ValueError:
        return None
    if parsed < date(2000, 1, 1) or parsed > date.today() + timedelta(days=2):
        return None
    return parsed.isoformat()


def extract_dates(lines: list[dict[str, Any]]) -> tuple[str | None, str | None, dict[str, Any], list[dict[str, Any]]]:
    candidates: list[dict[str, Any]] = []
    for line in lines:
        for index, pattern in enumerate(DATE_PATTERNS):
            for match in pattern.finditer(line["text"]):
                if index == 0:
                    parsed = _valid_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
                else:
                    parsed = _valid_date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
                if parsed:
                    candidates.append({"value": parsed, "raw": match.group(0), "line": line["index"], "zone": line["zone"], "page": line["page"]})
    unique = list(dict.fromkeys(candidate["value"] for candidate in candidates))
    chosen = candidates[0] if candidates else None
    if candidates:
        chosen = sorted(candidates, key=lambda item: (item["zone"] not in {"items", "tax", "total", "payment", "summary"}, item["line"]))[0]
    time_value = None
    if chosen:
        vicinity = [line for line in lines if abs(line["index"] - chosen["line"]) <= 2]
        match = next((TIME_RE.search(line["text"]) for line in vicinity if TIME_RE.search(line["text"])), None)
        if match:
            time_value = f"{int(match.group(1)):02d}:{int(match.group(2)):02d}:{int(match.group(3) or 0):02d}"
    confidence = "strong" if chosen and len(unique) == 1 else "weak" if chosen else "unknown"
    evidence = {
        "confidence": confidence,
        "source": "exact_date_pattern" if chosen else "not_found",
        "line": chosen["line"] if chosen else None,
        "candidateCount": len(unique),
    }
    public_candidates = [{"value": value, "label": datetime.strptime(value, "%Y-%m-%d").strftime("%d/%m/%Y")} for value in unique[:8]]
    return chosen["value"] if chosen else None, time_value, evidence, public_candidates


def _candidate_total(lines: list[dict[str, Any]], sections: dict[str, Any]) -> tuple[int | None, dict[str, Any], list[dict[str, Any]], int | None]:
    totals: list[dict[str, Any]] = []
    payments: list[dict[str, Any]] = []
    for line in lines:
        anchor = line.get("anchor")
        target = totals if anchor in {"total_due", "total_sum"} else payments if anchor == "payment" else None
        if target is None:
            continue
        nearby = [line]
        nearby.extend(candidate for candidate in lines if 0 < candidate["index"] - line["index"] <= 3 and candidate["page"] == line["page"])
        line_amounts = []
        for candidate_line in nearby:
            line_amounts.extend(_amounts(candidate_line))
            if line_amounts:
                break
        if line_amounts:
            picked = line_amounts[-1]
            target.append({**picked, "anchor": anchor, "strength": 4 if anchor == "total_due" else 3 if anchor == "total_sum" else 2})
    # A payment line can be split from its label in flat OCR; look one line farther.
    payment_values = {item["minor"] for item in payments if item["minor"] >= 0}
    flat_summary_values: list[dict[str, Any]] = []
    summary_start = next((line["index"] for line in lines if line.get("anchor") in {"total_due", "total_sum", "payment"}), None)
    if summary_start is not None and not sections.get("hasGeometry"):
        for candidate_line in lines[summary_start + 1:]:
            if candidate_line.get("anchor") == "tax":
                continue
            flat_summary_values.extend(amount for amount in _amounts(candidate_line) if amount["minor"] >= 0)
        frequencies: dict[int, int] = {}
        for item in flat_summary_values:
            frequencies[item["minor"]] = frequencies.get(item["minor"], 0) + 1
        repeated = [(value, count) for value, count in frequencies.items() if count >= 2]
        if repeated:
            # Repeated settlement values survive ML Kit block reordering better
            # than adjacency; ties prefer the larger final amount.
            for value, count in repeated:
                representative = next(item for item in reversed(flat_summary_values) if item["minor"] == value)
                totals.append({**representative, "anchor": "flat_repeated_settlement", "strength": 5, "repeatCount": count})
    for total in totals:
        total["agreement"] = total["minor"] in payment_values
        total["score"] = total["strength"] + (3 if total["agreement"] else 0)
    unique = sorted({item["minor"] for item in totals if item["minor"] >= 0})
    chosen = sorted(totals, key=lambda item: (-item["score"], -int(item.get("repeatCount") or 0), -item["minor"], item["line"]))[0] if totals else None
    disagreement = len(unique) > 1 and not chosen.get("agreement", False) if chosen else False
    confidence = "exact" if chosen and chosen["agreement"] and not disagreement else "strong" if chosen and not disagreement else "weak" if chosen else "unknown"
    evidence = {
        "confidence": confidence,
        "source": chosen["anchor"] if chosen else "not_found",
        "line": chosen["line"] if chosen else None,
        "paymentAgreement": bool(chosen and chosen["agreement"]),
        "candidateCount": len(unique),
    }
    candidates = [{"valueMinor": value, "value": value / 100, "label": f"{value / 100:.2f}".replace(".", ",")} for value in unique[:10]]
    payment = next((item["minor"] for item in payments if chosen and item["minor"] == chosen["minor"]), payments[0]["minor"] if payments else None)
    return chosen["minor"] if chosen else None, evidence, candidates, payment


def _credible_name(value: str) -> bool:
    normalized = fold(value)
    letters = re.sub(r"[^a-ząćęłńóśźż]", "", normalized)
    if len(letters) < 3 or MONEY_RE.fullmatch(value.strip()):
        return False
    forbidden = (
        "paragon", "fiskal", "suma", "platn", "karta", "gotowka", "ptu", "sprzed opod",
        "nip", "numer transakcji", "autoryzac", "zapraszamy", "dziekujemy", "rabat", "opust",
    )
    return not any(marker in normalized for marker in forbidden)


def _name_before(lines: list[dict[str, Any]], index: int, lower_bound: int) -> tuple[str | None, list[dict[str, Any]]]:
    selected: list[dict[str, Any]] = []
    for candidate in reversed(lines[max(lower_bound, index - 3):index]):
        if candidate.get("anchor") or candidate["zone"] in {"tax", "total", "payment", "footer"}:
            break
        package_measure = re.search(r"\d+[,.]\d{1,3}\s*(?:kg|g|l|ml)(?:-|\s|$)", candidate["text"], re.IGNORECASE)
        if (_amounts(candidate) and not package_measure) or QUANTITY_RE.search(candidate["text"]):
            if selected:
                break
            continue
        if re.match(r"^(opis|kod)\s*:", candidate["folded"]):
            selected.append(candidate)
            continue
        if _credible_name(candidate["text"]):
            selected.append(candidate)
            # One continuation plus one base line is enough and prevents footer merging.
            if len(selected) >= 2:
                break
        elif selected:
            break
    selected.reverse()
    if not selected:
        return None, []
    parts = [re.sub(r"^(?:opis|kod)\s*:\s*", "", line["text"], flags=re.IGNORECASE) for line in selected]
    return " ".join(parts).strip(), selected


def _union_box(lines: list[dict[str, Any]]) -> dict[str, float] | None:
    boxes = [line.get("box") for line in lines if line.get("box")]
    if not boxes:
        return None
    left, top = min(box["x"] for box in boxes), min(box["y"] for box in boxes)
    right = max(box["x"] + box["width"] for box in boxes)
    bottom = max(box["y"] + box["height"] for box in boxes)
    pad_x, pad_y = 0.02, 0.01
    x, y = max(0.0, left - pad_x), max(0.0, top - pad_y)
    return {"x": x, "y": y, "width": min(1.0 - x, right - x + pad_x), "height": min(1.0 - y, bottom - y + pad_y)}


def extract_items(lines: list[dict[str, Any]], sections: dict[str, Any], total_minor: int | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    lower, upper = sections["itemRange"]
    # With flat OCR, ML Kit block ordering may be wrong. Quantity-pattern rows are
    # still eligible outside the nominal zone, but anchor/footer lines never are.
    items: list[dict[str, Any]] = []
    adjustments: list[dict[str, Any]] = []
    sequential_names: list[tuple[str, list[dict[str, Any]]]] = []
    if not sections.get("hasGeometry"):
        for candidate in lines:
            coded = re.match(r"^\s*\d{5,}\s+(.+)$", candidate["text"])
            if coded and _credible_name(coded.group(1)):
                sequential_names.append((coded.group(1).strip(), [candidate]))
                continue
            if lower <= candidate["index"] < upper and _credible_name(candidate["text"]) and not _amounts(candidate):
                if re.search(r"\b(sprzedaz|sales|towar|ilos[cć])\b", candidate["folded"]):
                    continue
                if re.match(r"^(opis|pis)\s*:", candidate["folded"]):
                    if sequential_names:
                        name, evidence_lines = sequential_names[-1]
                        continuation = re.sub(r"^(?:opis|pis)\s*:\s*", "", candidate["text"], flags=re.IGNORECASE)
                        sequential_names[-1] = (f"{name} {continuation}".strip(), [*evidence_lines, candidate])
                    continue
                sequential_names.append((candidate["text"], [candidate]))
    sequential_index = 0
    for line in lines:
        match = QUANTITY_RE.search(line["text"]) or LOOSE_QUANTITY_RE.search(line["text"])
        if not match:
            continue
        if line.get("anchor") or line["zone"] in {"tax", "total", "payment"}:
            continue
        if sections.get("hasGeometry") and line["zone"] in {"summary", "footer", "header"}:
            continue
        inline_name = (match.groupdict().get("prefix") or line["text"][:match.start()]).strip(" -:|")
        source_name_lines: list[dict[str, Any]] = []
        name = inline_name if _credible_name(inline_name) else None
        if not name and not sections.get("hasGeometry") and not (lower <= line["index"] < upper) and sequential_index < len(sequential_names):
            name, source_name_lines = sequential_names[sequential_index]
            sequential_index += 1
        if not name:
            name, source_name_lines = _name_before(lines, line["index"], lower if lower <= line["index"] < upper else 0)
        if (not name or not _credible_name(name)) and sequential_index < len(sequential_names):
            name, source_name_lines = sequential_names[sequential_index]
            sequential_index += 1
        if not name or not _credible_name(name):
            continue
        unit_price = _minor(match.group("unit_price"))
        quantity_text = match.group("quantity").replace(",", ".")
        try:
            computed = int((Decimal(quantity_text) * Decimal(unit_price or 0)).quantize(Decimal("1")))
        except InvalidOperation:
            computed = unit_price
        line_total = _minor(match.group("line_total")) if match.group("line_total") else computed
        if line_total is None or line_total < 0:
            continue
        raw_lines = [*source_name_lines, line]
        item = {
            "line_number": len(items) + 1,
            "raw_name": name,
            "interpreted_name": " ".join(name.split()),
            "raw_product_code": None,
            "barcode": None,
            "quantity": quantity_text,
            "unit": (match.group("unit") or "szt").lower().rstrip("."),
            "unit_price_minor": unit_price,
            "total_price_minor": line_total,
            "discount_minor": 0,
            "confidence_state": "strong" if lower <= line["index"] < upper else "review",
            "raw_evidence": {
                "sourceLines": [entry["raw"] for entry in raw_lines],
                "normalizedLines": [entry["text"] for entry in raw_lines],
                "sourceLine": line["raw"], "lineIndex": line["index"], "page": line["page"],
                "box": _union_box(raw_lines), "taxGroup": (match.group("tax") or "").upper() or None,
                "pattern": "quantity_unit_price_total", "credibleProductLine": True,
                "corrections": [correction for entry in raw_lines for correction in entry["corrections"]],
            },
        }
        # A following discount amount belongs to this item only when explicitly labelled.
        nearby = lines[line["index"] + 1:line["index"] + 4]
        for offset, discount_line in enumerate(nearby):
            label_line = line if offset == 0 else nearby[offset - 1]
            if not re.search(r"\b(rabat|opust|promocj)\b", label_line["folded"]):
                continue
            negative = [amount for amount in _amounts(discount_line) if amount["minor"] < 0]
            if negative:
                item["discount_minor"] += abs(negative[-1]["minor"])
                item["raw_evidence"]["discountLine"] = discount_line["raw"]
                break
        items.append(item)

    for line in lines:
        if not (line["folded"].startswith("kaucja") or line["folded"].startswith("opakowania zwrotne")):
            continue
        nearby = [line, *lines[line["index"] + 1:line["index"] + 3]]
        amount = next((amount for candidate in nearby for amount in _amounts(candidate) if amount["minor"] >= 0), None)
        if amount:
            adjustments.append({
                "line_number": 1000 + line["index"], "kind": "deposit", "label": line["text"],
                "amount_minor": amount["minor"], "raw_evidence": {"sourceLine": line["raw"], "page": line["page"], "box": line.get("box")},
            })

    computed = sum(item["total_price_minor"] - item["discount_minor"] for item in items)
    computed += sum(adjustment["amount_minor"] for adjustment in adjustments)
    difference = total_minor - computed if total_minor is not None and items else None
    reconciled = difference is not None and abs(difference) <= 1
    if reconciled:
        for item in items:
            item["confidence_state"] = "strong"
            item["raw_evidence"]["reconciled"] = True
    diagnostics = {
        "computedItemsMinor": computed,
        "differenceMinor": difference,
        "state": "exact" if reconciled else "mismatch" if difference is not None else "unavailable",
    }
    return items, adjustments, diagnostics


def _merchant(lines: list[dict[str, Any]], sections: dict[str, Any], profile: dict[str, Any] | None) -> tuple[str, dict[str, Any]]:
    candidates = [line for line in lines[:12] if line["zone"] == "header" and _credible_name(line["text"])]
    known = (profile or {}).get("headerAliases") if isinstance((profile or {}).get("headerAliases"), list) else []
    known_brands = ("biedronka", "zabka", "lidl", "carrefour", "auchan", "kaufland", "aldi", "netto", "pepco", "reserved", "sinsay", "h&m", "c&a", "tk maxx")
    chosen = next((line for line in candidates if any(alias in line["folded"] for alias in [*known_brands, *map(fold, known)])), candidates[0] if candidates else None)
    return (chosen["text"][:200] if chosen else ""), {
        "confidence": "strong" if chosen and any(brand in chosen["folded"] for brand in known_brands) else "weak" if chosen else "unknown",
        "source": "header_line" if chosen else "not_found", "line": chosen["index"] if chosen else None,
    }


def parse_polish_receipt(
    raw_text: str,
    *,
    source_type: str,
    source_format: str,
    ocr_structure: Any = None,
    retailer_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = normalize_ocr(raw_text, ocr_structure)
    lines = normalized["lines"]
    sections = detect_sections(lines)
    sections["hasGeometry"] = normalized["hasGeometry"]
    merchant, merchant_evidence = _merchant(lines, sections, retailer_profile)
    purchase_date, purchase_time, date_evidence, date_candidates = extract_dates(lines)
    total_minor, total_evidence, total_candidates, payment_minor = _candidate_total(lines, sections)
    items, adjustments, reconciliation = extract_items(lines, sections, total_minor)

    # Reconciliation may disambiguate totals even when OCR presented several.
    if items and total_candidates and reconciliation["state"] != "exact":
        computed = reconciliation["computedItemsMinor"]
        match = next((candidate for candidate in total_candidates if abs(candidate["valueMinor"] - computed) <= 1), None)
        if match:
            total_minor = match["valueMinor"]
            reconciliation["differenceMinor"] = total_minor - computed
            reconciliation["state"] = "exact"
            total_evidence.update({"confidence": "strong", "source": "anchor_plus_reconciliation"})
            for item in items:
                item["confidence_state"] = "strong"
                item["raw_evidence"]["reconciled"] = True

    fiscal_match = None
    joined = "\n".join(line["text"] for line in lines)
    for pattern in (
        r"\b(EAZ[A-Z0-9]{6,})\b",
        r"\b(?:nr|numer)\s+(?:paragonu|wydruku)\s*[:#]?\s*([A-Z0-9/-]{4,})",
    ):
        found = re.search(pattern, joined, re.IGNORECASE)
        if found:
            fiscal_match = found.group(1)
            break

    corrected_tokens = sum(len(line["corrections"]) for line in lines)
    strong_items = sum(item["confidence_state"] == "strong" for item in items)
    weak_items = len(items) - strong_items
    field_evidence = {
        "merchant": merchant_evidence,
        "purchaseDate": date_evidence,
        "total": total_evidence,
        "items": {"confidence": "strong" if strong_items and not weak_items else "weak" if items else "unknown", "source": "items_zone_patterns", "strong": strong_items, "weak": weak_items},
    }
    unresolved = []
    if total_minor is None or total_evidence["confidence"] == "weak":
        unresolved.append("total")
    if purchase_date is None or date_evidence["confidence"] == "weak" and len(date_candidates) > 1:
        unresolved.append("purchase_date")
    if not items or weak_items:
        unresolved.append("items")
    parse_review = {
        "unresolved": unresolved,
        "totalCandidates": total_candidates,
        "dateCandidates": date_candidates,
        "itemCandidates": [],
    }
    diagnostics = {
        "ocrLines": len(lines), "hasGeometry": normalized["hasGeometry"],
        "fiscalAnchors": len(sections["anchors"]), "anchorKinds": sorted({item["kind"] for item in sections["anchors"]}),
        "normalizationCorrections": corrected_tokens,
        "itemsStrong": strong_items, "itemsWeak": weak_items,
        "totalConfidence": total_evidence["confidence"],
        "reconciliation": reconciliation,
        "paymentMinor": payment_minor,
        "zones": {zone: sum(line["zone"] == zone for line in lines) for zone in {line["zone"] for line in lines}},
    }
    return {
        "store_name": merchant,
        "purchase_date": purchase_date,
        "purchase_time": purchase_time,
        "total_minor": total_minor,
        "currency": "PLN",
        "fiscal_identifier": fiscal_match,
        "items": items,
        "adjustments": adjustments,
        "field_evidence": field_evidence,
        "parse_review": parse_review,
        "diagnostics": diagnostics,
        "recognized": bool(total_minor is not None and purchase_date and (items or merchant)),
        "normalized_line_count": len(lines),
        "source_type": source_type,
        "source_format": source_format,
    }
