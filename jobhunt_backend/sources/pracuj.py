"""Deterministic, inert parser for official Pracuj.pl JobAlert messages."""

from __future__ import annotations

from dataclasses import dataclass
from email import policy
from email.message import Message
from email.parser import BytesParser
from email.utils import parseaddr, parsedate_to_datetime
from html.parser import HTMLParser
import re
from typing import Any, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .email_transport import MailTransportError


PRACUJ_SOURCE_ID = "source_pracuj"
PRACUJ_ADAPTER_KEY = "pracuj_jobalert"
PRACUJ_ADAPTER_VERSION = "1"
PRACUJ_PARSER_VERSION = "pracuj_jobalert@1"
MAX_MESSAGE_BYTES = 2 * 1024 * 1024
MAX_PARTS = 64
MAX_DEPTH = 8
MAX_DECODED_BYTES = 1024 * 1024
MAX_ITEMS = 100
TRACKING_PARAMETERS = {"gclid", "fbclid", "mc_cid", "mc_eid"}
SUBJECT_MARKERS = ("jobalert", "oferty pracy", "nowe oferty", "zapisane wyszukiwanie")
BODY_MARKERS = ("jobalert", "zapisane wyszukiwanie", "wyłącz powiadomienie", "nowe oferty")
BLOCK_TAGS = {"article", "li", "tr", "section", "div"}


def _official_domain(value: str | None) -> bool:
    host = str(value or "").strip().casefold().strip("<>")
    return host == "pracuj.pl" or host.endswith(".pracuj.pl")


def _address_domain(value: str | None) -> str:
    address = parseaddr(str(value or ""))[1]
    return address.rsplit("@", 1)[-1].casefold() if "@" in address else ""


def _message_id_domain(value: str | None) -> str:
    match = re.search(r"@([^>\s]+)", str(value or ""))
    return match.group(1).casefold() if match else ""


def normalize_pracuj_url(value: str) -> str | None:
    try:
        parsed = urlsplit(value.strip())
        host = (parsed.hostname or "").casefold()
        port = parsed.port
    except ValueError:
        return None
    if parsed.scheme.casefold() not in {"http", "https"} or not _official_domain(host):
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    if port not in (None, 80, 443):
        return None
    path = parsed.path or "/"
    if not (re.search(r"/(?:praca|oferta|oferty)/", path, flags=re.I) or "/praca/" in path.casefold()):
        return None
    query = [
        (key, item) for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.casefold().startswith("utm_") and key.casefold() not in TRACKING_PARAMETERS
    ]
    return urlunsplit(("https", host, path, urlencode(query, doseq=True), ""))


def offer_identifier(url: str) -> str | None:
    parsed = urlsplit(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    for key in ("offerId", "offerid", "id", "jobId", "jobid"):
        value = str(query.get(key) or "").strip()
        if re.fullmatch(r"[A-Za-z0-9_-]{5,100}", value):
            return value
    match = re.search(r",([A-Za-z0-9_-]{6,100})(?:/)?$", parsed.path)
    return match.group(1) if match else None


def _clean(value: Any, *, limit: int = 1000) -> str | None:
    text = re.sub(r"\s+", " ", str(value or "")).strip(" \t\r\n-|•")
    return text[:limit] if text else None


@dataclass(frozen=True)
class PracujJobItem:
    index: int
    url: str
    external_id: str | None
    title: str | None
    company: str | None
    location: str | None
    salary: str | None
    source_wording: str
    mime_part: str


@dataclass(frozen=True)
class ParsedPracujAlert:
    recognized: bool
    trust_state: str
    sender: str | None
    subject: str | None
    message_id: str | None
    received_at: str | None
    items: tuple[PracujJobItem, ...]
    warnings: tuple[str, ...]


class _InertHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.blocks: list[dict[str, Any]] = []
        self.stack: list[dict[str, Any]] = []
        self.anchor: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        self.depth += 1
        if tag in BLOCK_TAGS:
            self.stack.append({"tag": tag, "depth": self.depth, "text": [], "links": []})
        if tag == "a":
            href = dict(attrs).get("href") or ""
            self.anchor = {"href": href, "text": []}

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag == "a" and self.anchor is not None:
            link = {"href": self.anchor["href"], "text": _clean(" ".join(self.anchor["text"])) or ""}
            for block in self.stack:
                block["links"].append(link)
            self.anchor = None
        if tag in BLOCK_TAGS:
            for index in range(len(self.stack) - 1, -1, -1):
                if self.stack[index]["tag"] == tag:
                    block = self.stack.pop(index)
                    self.blocks.append(block)
                    break
        self.depth = max(0, self.depth - 1)

    def handle_data(self, data: str) -> None:
        if self.anchor is not None:
            self.anchor["text"].append(data)
        for block in self.stack:
            block["text"].append(data)


def _label(text: str, names: tuple[str, ...]) -> str | None:
    alternatives = "|".join(re.escape(name) for name in names)
    match = re.search(
        rf"(?:^|[\n|•])\s*(?:{alternatives})\s*[:\-]\s*([^\n|•]{{1,500}})",
        text,
        flags=re.I,
    )
    return _clean(match.group(1), limit=500) if match else None


def _item(
    *, index: int, url: str, anchor_text: str | None, wording: str, mime_part: str
) -> PracujJobItem:
    normalized = normalize_pracuj_url(url)
    if not normalized:
        raise ValueError("not a supported Pracuj job URL")
    title = _label(wording, ("stanowisko", "oferta", "job", "position"))
    generic = {"zobacz ofertę", "sprawdź", "aplikuj", "więcej", "view job", "apply"}
    anchor = _clean(anchor_text, limit=500)
    if not title and anchor and anchor.casefold() not in generic:
        title = anchor
    return PracujJobItem(
        index=index,
        url=normalized,
        external_id=offer_identifier(normalized),
        title=title,
        company=_label(wording, ("firma", "pracodawca", "company")),
        location=_label(wording, ("lokalizacja", "miejsce pracy", "location")),
        salary=_label(wording, ("wynagrodzenie", "zarobki", "salary")),
        source_wording=_clean(wording, limit=8000) or (anchor or normalized),
        mime_part=mime_part,
    )


def _html_items(content: str, *, start_index: int) -> list[PracujJobItem]:
    parser = _InertHTML()
    parser.feed(content)
    candidates: dict[str, tuple[str, str]] = {}
    for block in sorted(parser.blocks, key=lambda item: len(" ".join(item["text"]))):
        wording = "\n".join(part.strip() for part in block["text"] if part.strip())
        for link in block["links"]:
            normalized = normalize_pracuj_url(str(link.get("href") or ""))
            if normalized and normalized not in candidates:
                candidates[normalized] = (str(link.get("text") or ""), wording)
    items: list[PracujJobItem] = []
    for offset, (url, (anchor, wording)) in enumerate(candidates.items()):
        try:
            items.append(_item(
                index=start_index + offset, url=url, anchor_text=anchor,
                wording=wording, mime_part="text/html",
            ))
        except ValueError:
            continue
    return items


def _plain_items(content: str, *, start_index: int) -> list[PracujJobItem]:
    lines = content.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    items: list[PracujJobItem] = []
    seen: set[str] = set()
    url_pattern = re.compile(r"https?://[^\s<>\]\[\)\(\"']+", flags=re.I)
    for line_index, line in enumerate(lines):
        for match in url_pattern.finditer(line):
            url = normalize_pracuj_url(match.group(0).rstrip(".,;"))
            if not url or url in seen:
                continue
            seen.add(url)
            start = line_index
            while start > 0 and lines[start - 1].strip() and line_index - start < 6:
                start -= 1
            end = line_index + 1
            while end < len(lines) and lines[end].strip() and end - line_index < 6:
                end += 1
            wording = "\n".join(lines[start:end])
            items.append(_item(
                index=start_index + len(items), url=url, anchor_text=None,
                wording=wording, mime_part="text/plain",
            ))
    return items


def _message_depth(message: Message, depth: int = 0) -> tuple[int, int]:
    maximum, count = depth, 1
    if message.is_multipart():
        for part in message.iter_parts():
            child_depth, child_count = _message_depth(part, depth + 1)
            maximum, count = max(maximum, child_depth), count + child_count
    return maximum, count


class PracujJobAlertAdapter:
    key = PRACUJ_ADAPTER_KEY
    version = PRACUJ_ADAPTER_VERSION
    parser_version = PRACUJ_PARSER_VERSION

    @staticmethod
    def header_candidate(headers: Mapping[str, str]) -> bool:
        subject = str(headers.get("Subject") or "").casefold()
        return _official_domain(_address_domain(headers.get("From"))) and any(
            marker in subject for marker in SUBJECT_MARKERS
        )

    @staticmethod
    def parse(raw: bytes) -> ParsedPracujAlert:
        if not raw:
            raise MailTransportError("Email message is empty.", classification="malformed_message")
        if len(raw) > MAX_MESSAGE_BYTES:
            raise MailTransportError(
                "Email message exceeds the parser safety limit.", classification="malformed_message"
            )
        try:
            message = BytesParser(policy=policy.default).parsebytes(raw)
        except Exception as exc:
            raise MailTransportError("Email MIME structure is malformed.", classification="malformed_message") from exc
        depth, part_count = _message_depth(message)
        if depth > MAX_DEPTH or part_count > MAX_PARTS:
            raise MailTransportError("Email MIME structure exceeds parser bounds.", classification="malformed_message")

        sender = str(message.get("From") or "") or None
        subject = str(message.get("Subject") or "") or None
        message_id = str(message.get("Message-ID") or "").strip() or None
        evidence = 0
        if _official_domain(_address_domain(sender)):
            evidence += 1
        if _official_domain(_address_domain(message.get("Return-Path"))):
            evidence += 1
        if _official_domain(_message_id_domain(message_id)):
            evidence += 1
        authentication = str(message.get("Authentication-Results") or "").casefold()
        authenticated = bool(
            re.search(r"(?:dkim|spf)\s*=\s*pass", authentication)
            and re.search(r"(?:header\.d|smtp\.mailfrom)\s*=\s*[^;\s]*pracuj\.pl", authentication)
        )
        if authenticated:
            evidence += 2

        warnings: list[str] = []
        decoded_bytes = 0
        plain_parts: list[str] = []
        html_parts: list[str] = []
        for part in message.walk():
            if part.is_multipart() or part.get_content_disposition() == "attachment":
                continue
            content_type = part.get_content_type().casefold()
            if content_type not in {"text/plain", "text/html"}:
                continue
            try:
                payload = part.get_payload(decode=True) or b""
                decoded_bytes += len(payload)
                if decoded_bytes > MAX_DECODED_BYTES:
                    raise MailTransportError(
                        "Decoded email body exceeds parser bounds.", classification="malformed_message"
                    )
                charset = part.get_content_charset() or "utf-8"
                text = payload.decode(charset, errors="replace")
            except MailTransportError:
                raise
            except (LookupError, UnicodeError, TypeError) as exc:
                warnings.append(f"A {content_type} MIME part could not be decoded: {type(exc).__name__}.")
                continue
            (plain_parts if content_type == "text/plain" else html_parts).append(text)

        items: list[PracujJobItem] = []
        for content in html_parts:
            for item in _html_items(content, start_index=len(items)):
                if item.url not in {known.url for known in items}:
                    items.append(item)
                if len(items) >= MAX_ITEMS:
                    break
        for content in plain_parts:
            for item in _plain_items(content, start_index=len(items)):
                if item.url not in {known.url for known in items}:
                    items.append(item)
                if len(items) >= MAX_ITEMS:
                    break

        corpus = " ".join([subject or "", *plain_parts, *html_parts]).casefold()
        template_marker = any(marker in corpus for marker in BODY_MARKERS)
        recognized = evidence >= 2 and template_marker and bool(items)
        trust_state = "verified_transport_metadata" if authenticated else (
            "recognized" if evidence >= 2 else "uncertain"
        )
        received_at = None
        try:
            parsed_date = parsedate_to_datetime(str(message.get("Date") or ""))
            received_at = parsed_date.isoformat() if parsed_date else None
        except (TypeError, ValueError):
            warnings.append("Message Date header was not parseable.")
        return ParsedPracujAlert(
            recognized=recognized,
            trust_state=trust_state,
            sender=sender,
            subject=subject,
            message_id=message_id,
            received_at=received_at,
            items=tuple(items[:MAX_ITEMS]),
            warnings=tuple(warnings),
        )


__all__ = [
    "MAX_MESSAGE_BYTES",
    "PRACUJ_ADAPTER_KEY",
    "PRACUJ_ADAPTER_VERSION",
    "PRACUJ_PARSER_VERSION",
    "PRACUJ_SOURCE_ID",
    "ParsedPracujAlert",
    "PracujJobAlertAdapter",
    "PracujJobItem",
    "normalize_pracuj_url",
    "offer_identifier",
]
