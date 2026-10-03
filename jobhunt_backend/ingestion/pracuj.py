"""Pracuj JobAlert mailbox polling and source-neutral ingestion orchestration."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
from typing import Any, Callable, Mapping

from .archive import RawArchive, StoredBlob
from ..sources.email_transport import MailTransportError
from ..sources.pracuj import (
    MAX_MESSAGE_BYTES,
    PRACUJ_ADAPTER_VERSION,
    PRACUJ_PARSER_VERSION,
    PRACUJ_SOURCE_ID,
    PracujJobAlertAdapter,
)


PRACUJ_DEFAULT_POLL_SECONDS = 300
PRACUJ_DEFAULT_BOOTSTRAP_DAYS = 30
PRACUJ_DEFAULT_BOOTSTRAP_MESSAGES = 500


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _after(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=max(0, seconds))).isoformat(
        timespec="seconds"
    )


class PracujMailCoordinator:
    def __init__(
        self,
        *,
        store: Any,
        archive: RawArchive,
        transport: Any,
        adapter: PracujJobAlertAdapter | None = None,
        bootstrap_days: int = PRACUJ_DEFAULT_BOOTSTRAP_DAYS,
        bootstrap_messages: int = PRACUJ_DEFAULT_BOOTSTRAP_MESSAGES,
    ) -> None:
        self.store = store
        self.archive = archive
        self.transport = transport
        self.adapter = adapter or PracujJobAlertAdapter()
        self.bootstrap_days = max(1, min(90, int(bootstrap_days)))
        self.bootstrap_messages = max(1, min(500, int(bootstrap_messages)))

    def _policy(self) -> dict[str, Any]:
        source = self.store.get_source(PRACUJ_SOURCE_ID)
        if not source:
            raise MailTransportError("Pracuj source definition is missing.", classification="internal")
        if not source.get("enabled") or source.get("operational_state") == "paused":
            raise MailTransportError("Pracuj collection is paused.", classification="policy_stop")
        if not self.transport.configured:
            raise MailTransportError("Pracuj mailbox is not configured.", classification="authentication")
        backoff = source.get("backoff_until")
        if backoff and str(backoff) > _now():
            error = MailTransportError(
                "Pracuj source is in persisted backoff.", classification="network", retryable=True
            )
            try:
                target = datetime.fromisoformat(str(backoff).replace("Z", "+00:00"))
                error.retry_after_seconds = max(
                    1.0, (target - datetime.now(timezone.utc)).total_seconds()
                )
            except ValueError:
                pass
            raise error
        return source

    @staticmethod
    def _poll_followup(*, delay: int) -> dict[str, Any]:
        return {
            "job_type": "pracuj_mail_poll",
            "payload": {"source": "pracuj"},
            "idempotency_key": "pracuj-mail-poll",
            "priority": 0,
            "max_attempts": 8,
            "next_attempt_at": _after(delay),
        }

    def poll_mail(
        self,
        payload: Mapping[str, Any],
        *,
        cancelled: Callable[[], bool],
        progress: Callable[[str, float | None], None],
    ) -> dict[str, Any]:
        del payload
        source = self._policy()
        state = self.store.get_mail_sync_state(PRACUJ_SOURCE_ID) or {}
        now = _now()
        self.store.record_source_attempt(PRACUJ_SOURCE_ID, now=now)
        progress("opening_mailbox_readonly", 0.05)
        with self.transport.open() as session:
            uidvalidity = str(session.uidvalidity or "")
            persisted_uidvalidity = str(state.get("uidvalidity") or "")
            if persisted_uidvalidity and uidvalidity != persisted_uidvalidity:
                self.store.update_mail_sync_state(
                    PRACUJ_SOURCE_ID,
                    {
                        "last_poll_at": now,
                        "last_error_class": "uid_reset",
                        "last_error_message": "Mailbox UIDVALIDITY changed; explicit review is required before rebootstrap.",
                    },
                    now=now,
                )
                raise MailTransportError(
                    "Mailbox UIDVALIDITY changed; collection stopped for safe review.",
                    classification="uid_reset",
                    retryable=False,
                )
            bootstrap = not bool(state.get("bootstrap_completed_at"))
            since = (
                datetime.now(timezone.utc) - timedelta(days=int(state.get("bootstrap_days") or self.bootstrap_days))
                if bootstrap else None
            )
            maximum = min(
                self.bootstrap_messages,
                int(state.get("bootstrap_max_messages") or self.bootstrap_messages),
            )
            uids = session.search_uids(
                after_uid=0 if bootstrap else int(state.get("last_processed_uid") or 0),
                since=since,
                maximum=maximum,
            )
            inspected = 0
            recognized = 0
            archived = 0
            followups: list[dict[str, Any]] = []
            highest = int(state.get("highest_observed_uid") or 0)
            last_message_at = state.get("last_successful_message_at")
            for index, uid in enumerate(uids):
                if cancelled():
                    raise MailTransportError("Pracuj mail poll was cancelled.", classification="cancelled")
                highest = max(highest, int(uid))
                headers = session.fetch_headers(uid)
                inspected += 1
                if not self.adapter.header_candidate(headers):
                    continue
                raw = session.fetch_message(uid, maximum_bytes=MAX_MESSAGE_BYTES)
                parsed = self.adapter.parse(raw)
                if not parsed.recognized:
                    if parsed.trust_state != "uncertain":
                        raise MailTransportError(
                            "An official-looking Pracuj JobAlert no longer matches the versioned parser.",
                            classification="parser_failure",
                            retryable=False,
                        )
                    continue
                recognized += 1
                existing_blob = self.store.get_raw_blob(hashlib.sha256(raw).hexdigest())
                if existing_blob:
                    self.archive.read_verified(
                        relative_path=existing_blob["relative_path"],
                        expected_hash=existing_blob["sha256"],
                        expected_size=int(existing_blob["byte_size"]),
                    )
                    blob = StoredBlob(
                        sha256=existing_blob["sha256"],
                        byte_size=int(existing_blob["byte_size"]),
                        mime_type=existing_blob["mime_type"],
                        file_extension=existing_blob["file_extension"],
                        relative_path=existing_blob["relative_path"],
                        created=False,
                    )
                else:
                    blob = self.archive.store(raw, mime_type="message/rfc822", extension=".eml")
                self.store.ensure_raw_blob({
                    "sha256": blob.sha256,
                    "byte_size": blob.byte_size,
                    "mime_type": "message/rfc822",
                    "file_extension": ".eml",
                    "relative_path": blob.relative_path,
                }, now=now)
                message, reused = self.store.save_source_email_message({
                    "source_id": PRACUJ_SOURCE_ID,
                    "mailbox": self.transport.mailbox,
                    "uidvalidity": uidvalidity,
                    "uid": uid,
                    "message_id": parsed.message_id,
                    "raw_blob_sha256": blob.sha256,
                    "received_at": parsed.received_at,
                    "sender": parsed.sender,
                    "subject": parsed.subject,
                    "trust_state": parsed.trust_state,
                    "parser_version": PRACUJ_PARSER_VERSION,
                }, now=now)
                if not reused or message.get("processing_state") in {"pending", "failed"}:
                    followups.append({
                        "job_type": "pracuj_process_message",
                        "payload": {"source": "pracuj", "messageId": message["id"]},
                        "idempotency_key": f"pracuj-process:{message['id']}:{PRACUJ_PARSER_VERSION}",
                        "priority": 10,
                        "max_attempts": 3,
                        "next_attempt_at": now,
                    })
                if blob.created:
                    archived += 1
                last_message_at = parsed.received_at or now
                progress("inspecting_jobalerts", min(0.85, 0.1 + (index + 1) / max(1, len(uids)) * 0.75))

        cadence = int(source.get("polling_cadence_seconds") or PRACUJ_DEFAULT_POLL_SECONDS)
        followups.append(self._poll_followup(delay=cadence))
        self.store.update_mail_sync_state(
            PRACUJ_SOURCE_ID,
            {
                "adapter_version": PRACUJ_PARSER_VERSION,
                "mailbox": self.transport.mailbox,
                "uidvalidity": uidvalidity,
                "last_processed_uid": max([int(state.get("last_processed_uid") or 0), *uids]),
                "highest_observed_uid": highest,
                "bootstrap_started_at": state.get("bootstrap_started_at") or now,
                "bootstrap_completed_at": state.get("bootstrap_completed_at") or now,
                "last_poll_at": now,
                "last_success_at": now,
                "last_successful_message_at": last_message_at,
                "messages_inspected": int(state.get("messages_inspected") or 0) + inspected,
                "alerts_recognized": int(state.get("alerts_recognized") or 0) + recognized,
                "last_error_class": None,
                "last_error_message": None,
            },
            now=now,
        )
        self.store.record_source_success(PRACUJ_SOURCE_ID, now=now)
        progress("mail_poll_complete", 0.95)
        return {
            "messagesInspected": inspected,
            "alertsRecognized": recognized,
            "newMimeBlobs": archived,
            "processJobsScheduled": len(followups) - 1,
            "followups": followups,
        }

    def process_message(
        self,
        payload: Mapping[str, Any],
        *,
        cancelled: Callable[[], bool],
        progress: Callable[[str, float | None], None],
    ) -> dict[str, Any]:
        self._policy()
        message_id = str(payload.get("messageId") or "")
        message = self.store.get_source_email_message(message_id)
        if not message:
            raise MailTransportError("Archived Pracuj email message was not found.", classification="internal")
        if message["processing_state"] == "processed":
            return {"messageId": message_id, "reused": True, "followups": []}
        now = _now()
        self.store.update_source_email_message(message_id, processing_state="processing", now=now)
        try:
            raw = self.archive.read_verified(
                relative_path=message["relative_path"],
                expected_hash=message["raw_blob_sha256"],
                expected_size=int(message["byte_size"]),
            )
            parsed = self.adapter.parse(raw)
            if not parsed.recognized:
                raise MailTransportError(
                    "Archived message no longer passes the versioned Pracuj recognition policy.",
                    classification="parser_failure",
                )
            bindings = self.store.list_pracuj_bindings()
            subject = (parsed.subject or "").casefold()
            profile_ids = [
                row["search_profile_id"] for row in bindings
                if row["enabled"] and (
                    not row.get("subject_matcher")
                    or str(row["subject_matcher"]).casefold() in subject
                )
            ]
            followups: list[dict[str, Any]] = []
            created_listings = 0
            created_captures = 0
            for item in parsed.items:
                if cancelled():
                    raise MailTransportError("Pracuj message processing was cancelled.", classification="cancelled")
                identity_value = item.external_id or item.url
                identity_prefix = "external" if item.external_id else "url"
                listing_result = self.store.upsert_source_listing(
                    listing={
                        "source_id": PRACUJ_SOURCE_ID,
                        "identity_key": identity_prefix + ":" + hashlib.sha256(identity_value.encode("utf-8")).hexdigest(),
                        "external_id": item.external_id,
                        "canonical_url": item.url,
                        "observed_url": item.url,
                        "title_hint": item.title,
                        "company_hint": item.company,
                        "location_hint": item.location,
                        "lifecycle_state": "active",
                        "source_ended_at": None,
                        "notes": f"Observed in official JobAlert email by {PRACUJ_PARSER_VERSION}.",
                    },
                    search_profile_ids=profile_ids,
                    observed_at=message.get("received_at") or now,
                )
                created_listings += int(listing_result["created"])
                capture_result = self.store.save_source_capture(
                    listing_id=listing_result["listing_id"],
                    blob={
                        "sha256": message["raw_blob_sha256"],
                        "byte_size": int(message["byte_size"]),
                        "mime_type": "message/rfc822",
                        "file_extension": ".eml",
                        "relative_path": message["relative_path"],
                    },
                    capture={
                        "mime_type": "message/rfc822",
                        "file_extension": ".eml",
                        "input_method": "pracuj_jobalert",
                        "source_url": item.url,
                        "http_status": None,
                        "safe_metadata": {
                            "adapterKey": self.adapter.key,
                            "adapterVersion": self.adapter.version,
                            "parserVersion": self.adapter.parser_version,
                            "source": "pracuj",
                            "messageRecordId": message_id,
                            "uidvalidity": message["uidvalidity"],
                            "uid": int(message["uid"]),
                            "messageId": message.get("message_id"),
                            "mimePart": item.mime_part,
                            "itemIndex": item.index,
                            "pracujUrl": item.url,
                            "trustState": parsed.trust_state,
                            "receivedAt": message.get("received_at"),
                            "searchProfileIds": profile_ids,
                            "itemSourceWording": item.source_wording[:8000],
                        },
                    },
                    search_profile_ids=profile_ids,
                    observed_at=message.get("received_at") or now,
                )
                if not capture_result["capture_reused"]:
                    created_captures += 1
                    capture_id = capture_result["capture"]["id"]
                    followups.append({
                        "job_type": "extract_capture",
                        "payload": {"source": "pracuj", "captureId": capture_id},
                        "idempotency_key": f"extract:{capture_id}:{PRACUJ_PARSER_VERSION}",
                        "priority": 5,
                        "max_attempts": 3,
                        "next_attempt_at": now,
                    })
            state = self.store.get_mail_sync_state(PRACUJ_SOURCE_ID) or {}
            self.store.update_mail_sync_state(
                PRACUJ_SOURCE_ID,
                {
                    "listings_discovered": int(state.get("listings_discovered") or 0) + created_listings,
                    "captures_created": int(state.get("captures_created") or 0) + created_captures,
                    "last_successful_message_at": message.get("received_at") or now,
                    "last_error_class": None,
                    "last_error_message": None,
                },
                now=now,
            )
            self.store.update_source_email_message(
                message_id,
                processing_state="processed",
                item_count=len(parsed.items),
                processed_at=now,
                now=now,
            )
            self.store.record_source_success(PRACUJ_SOURCE_ID, now=now)
            progress("jobalert_processed", 0.95)
            return {
                "messageId": message_id,
                "itemCount": len(parsed.items),
                "listingsCreated": created_listings,
                "capturesCreated": created_captures,
                "matchedProfileIds": profile_ids,
                "followups": followups,
            }
        except Exception as exc:
            self.store.update_source_email_message(
                message_id,
                processing_state="failed",
                error_class=str(getattr(exc, "classification", "parser_failure"))[:100],
                error_message=str(exc)[:1000],
                now=_now(),
            )
            raise


__all__ = [
    "PRACUJ_DEFAULT_BOOTSTRAP_DAYS",
    "PRACUJ_DEFAULT_BOOTSTRAP_MESSAGES",
    "PRACUJ_DEFAULT_POLL_SECONDS",
    "PracujMailCoordinator",
]
