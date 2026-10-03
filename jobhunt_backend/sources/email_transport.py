"""Small TLS-only, read-only IMAP transport used by source-specific email adapters."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from email.parser import BytesParser
from email import policy
import imaplib
import socket
import ssl
from typing import Any, Iterator, Mapping


HEADER_FIELDS = "FROM RETURN-PATH MESSAGE-ID SUBJECT AUTHENTICATION-RESULTS DATE"


class MailTransportError(RuntimeError):
    def __init__(self, message: str, *, classification: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.classification = classification
        self.retryable = retryable


def _response_bytes(response: Any) -> bytes:
    for item in response or []:
        if isinstance(item, tuple) and len(item) > 1 and isinstance(item[1], bytes):
            return item[1]
        if isinstance(item, bytes) and b"\r\n" in item:
            return item
    return b""


class ImapMailboxSession:
    def __init__(self, client: Any, *, mailbox: str) -> None:
        self.client = client
        self.mailbox = mailbox
        self.uidvalidity: str | None = None

    def select_readonly(self) -> str:
        try:
            status, _ = self.client.select(self.mailbox, readonly=True)
        except imaplib.IMAP4.error as exc:
            raise MailTransportError(
                "Configured IMAP mailbox could not be selected read-only.",
                classification="mailbox_missing",
            ) from exc
        if status != "OK":
            raise MailTransportError(
                "Configured IMAP mailbox could not be selected read-only.",
                classification="mailbox_missing",
            )
        _, values = self.client.response("UIDVALIDITY")
        raw = values[0] if values else None
        if isinstance(raw, bytes):
            raw = raw.decode("ascii", errors="ignore")
        self.uidvalidity = str(raw or "").strip() or None
        if not self.uidvalidity:
            raise MailTransportError(
                "IMAP server did not provide UIDVALIDITY.", classification="malformed_response"
            )
        return self.uidvalidity

    def search_uids(
        self,
        *,
        after_uid: int = 0,
        since: datetime | None = None,
        maximum: int = 500,
    ) -> list[int]:
        if after_uid > 0:
            arguments = (None, "UID", f"{after_uid + 1}:*")
        elif since is not None:
            arguments = (None, "SINCE", since.astimezone(timezone.utc).strftime("%d-%b-%Y"))
        else:
            arguments = (None, "ALL")
        try:
            status, values = self.client.uid("SEARCH", *arguments)
        except imaplib.IMAP4.error as exc:
            raise MailTransportError(
                "IMAP UID search failed.", classification="network", retryable=True
            ) from exc
        if status != "OK":
            raise MailTransportError(
                "IMAP UID search failed.", classification="network", retryable=True
            )
        tokens = (values[0] if values else b"") or b""
        if isinstance(tokens, str):
            tokens = tokens.encode("ascii", errors="ignore")
        uids = sorted({int(token) for token in tokens.split() if token.isdigit()})
        return uids[-max(1, min(500, int(maximum))):]

    def fetch_headers(self, uid: int) -> Mapping[str, str]:
        query = f"(BODY.PEEK[HEADER.FIELDS ({HEADER_FIELDS})])"
        try:
            status, response = self.client.uid("FETCH", str(int(uid)), query)
        except imaplib.IMAP4.error as exc:
            raise MailTransportError(
                "IMAP header fetch failed.", classification="network", retryable=True
            ) from exc
        if status != "OK":
            raise MailTransportError(
                "IMAP header fetch failed.", classification="network", retryable=True
            )
        message = BytesParser(policy=policy.default).parsebytes(_response_bytes(response), headersonly=True)
        return {str(key): str(value) for key, value in message.items()}

    def fetch_message(self, uid: int, *, maximum_bytes: int) -> bytes:
        try:
            status, response = self.client.uid("FETCH", str(int(uid)), "(BODY.PEEK[])")
        except imaplib.IMAP4.error as exc:
            raise MailTransportError(
                "IMAP message fetch failed.", classification="network", retryable=True
            ) from exc
        if status != "OK":
            raise MailTransportError(
                "IMAP message fetch failed.", classification="network", retryable=True
            )
        raw = _response_bytes(response)
        if len(raw) > maximum_bytes:
            raise MailTransportError(
                "IMAP message exceeds the configured safety limit.",
                classification="malformed_message",
            )
        return raw


class ImapMailboxTransport:
    """Connect with verified TLS and expose only read-only UID/PEEK operations."""

    def __init__(
        self,
        *,
        environment: Mapping[str, Any],
        timeout_seconds: float = 30.0,
        client_factory: Any | None = None,
    ) -> None:
        self.environment = environment
        self.host = str(environment.get("JOBHUNT_PRACUJ_IMAP_HOST") or "").strip()
        self.configuration_error: str | None = None
        try:
            self.port = int(str(environment.get("JOBHUNT_PRACUJ_IMAP_PORT") or "993"))
            if not 1 <= self.port <= 65535:
                raise ValueError
        except (TypeError, ValueError):
            self.port = 993
            self.configuration_error = "JOBHUNT_PRACUJ_IMAP_PORT must be an integer from 1 to 65535."
        self.username = str(environment.get("JOBHUNT_PRACUJ_IMAP_USER") or "").strip()
        self.password = str(environment.get("JOBHUNT_PRACUJ_IMAP_PASSWORD") or "")
        self.mailbox = str(environment.get("JOBHUNT_PRACUJ_MAILBOX") or "INBOX").strip() or "INBOX"
        self.timeout_seconds = max(1.0, min(120.0, float(timeout_seconds)))
        self.client_factory = client_factory or imaplib.IMAP4_SSL

    @property
    def configured(self) -> bool:
        return bool(self.host and self.username and self.password and not self.configuration_error)

    def safe_config(self) -> dict[str, Any]:
        return {
            "configured": self.configured,
            "host": self.host or None,
            "port": self.port,
            "mailbox": self.mailbox,
            "tls": True,
            "usernameConfigured": bool(self.username),
            "configurationError": self.configuration_error,
        }

    @contextmanager
    def open(self) -> Iterator[ImapMailboxSession]:
        if not self.configured:
            raise MailTransportError(
                self.configuration_error or "Pracuj mailbox configuration is incomplete.",
                classification="configuration" if self.configuration_error else "authentication",
            )
        context = ssl.create_default_context()
        client = None
        try:
            client = self.client_factory(
                self.host,
                self.port,
                ssl_context=context,
                timeout=self.timeout_seconds,
            )
            client.login(self.username, self.password)
            session = ImapMailboxSession(client, mailbox=self.mailbox)
            session.select_readonly()
            yield session
        except MailTransportError:
            raise
        except ssl.SSLError as exc:
            raise MailTransportError(
                "Verified TLS connection to the IMAP server failed.",
                classification="tls",
                retryable=False,
            ) from exc
        except imaplib.IMAP4.error as exc:
            raise MailTransportError(
                "IMAP authentication failed.", classification="authentication", retryable=False
            ) from exc
        except (socket.timeout, TimeoutError) as exc:
            raise MailTransportError(
                "IMAP operation timed out.", classification="timeout", retryable=True
            ) from exc
        except OSError as exc:
            raise MailTransportError(
                "IMAP network connection failed.", classification="network", retryable=True
            ) from exc
        finally:
            if client is not None:
                try:
                    client.logout()
                except Exception:
                    pass


__all__ = ["ImapMailboxSession", "ImapMailboxTransport", "MailTransportError"]
