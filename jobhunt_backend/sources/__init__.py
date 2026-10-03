"""Isolated external-source adapters for Job Hunt live collection."""

from .nav import NavSourceAdapter, NavSourceError
from .jobbnorge import JobbnorgeSourceAdapter, JobbnorgeSourceError
from .email_transport import ImapMailboxTransport, MailTransportError
from .pracuj import PracujJobAlertAdapter

__all__ = [
    "ImapMailboxTransport",
    "MailTransportError",
    "NavSourceAdapter",
    "NavSourceError",
    "JobbnorgeSourceAdapter",
    "JobbnorgeSourceError",
    "PracujJobAlertAdapter",
]
