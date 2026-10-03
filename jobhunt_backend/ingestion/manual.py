"""Synchronous Pack D manual adapter; it never performs network access or parsing."""

from __future__ import annotations

import hashlib
from typing import Any

from .archive import RawArchive, StoredBlob


class ManualImportAdapter:
    key = "manual"
    version = "1.0.0"

    def __init__(self, store: Any, archive: RawArchive) -> None:
        self.store = store
        self.archive = archive

    def ingest(
        self,
        *,
        content: bytes,
        mime_type: str,
        extension: str,
        listing: dict[str, Any],
        capture: dict[str, Any],
        track_id: str | None,
        search_profile_id: str | None,
        observed_at: str,
    ) -> dict[str, Any]:
        digest = hashlib.sha256(content).hexdigest()
        existing = self.store.get_raw_blob(digest)
        if existing:
            self.archive.read_verified(
                relative_path=existing["relative_path"], expected_hash=digest,
                expected_size=int(existing["byte_size"]),
            )
            blob = StoredBlob(
                sha256=digest,
                byte_size=int(existing["byte_size"]),
                mime_type=existing["mime_type"],
                file_extension=existing["file_extension"],
                relative_path=existing["relative_path"],
                created=False,
            )
        else:
            blob = self.archive.store(content, mime_type=mime_type, extension=extension)
        result = self.store.save_manual_capture(
            listing=listing,
            blob={
                "sha256": blob.sha256,
                "byte_size": blob.byte_size,
                "mime_type": blob.mime_type,
                "file_extension": blob.file_extension,
                "relative_path": blob.relative_path,
            },
            capture={**capture, "mime_type": mime_type, "file_extension": extension},
            track_id=track_id,
            search_profile_id=search_profile_id,
            observed_at=observed_at,
        )
        result["blob_created"] = blob.created
        return result
