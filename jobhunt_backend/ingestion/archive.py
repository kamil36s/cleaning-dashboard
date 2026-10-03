"""Private content-addressed archive for immutable Job Hunt captures."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import tempfile
from typing import Iterable

from ..models import JobhuntError


CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class StoredBlob:
    sha256: str
    byte_size: int
    mime_type: str
    file_extension: str
    relative_path: str
    created: bool


def hash_file(path: Path) -> tuple[int, str]:
    size = 0
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(CHUNK_SIZE)
            if not chunk:
                break
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


class RawArchive:
    """Write and verify hash-named blobs below one fixed private root."""

    def __init__(self, private_root: str | Path) -> None:
        self.private_root = Path(private_root)
        self.raw_root = self.private_root / "raw" / "sha256"

    @staticmethod
    def relative_path(digest: str, extension: str) -> Path:
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError("Invalid SHA-256 digest")
        if extension not in {".txt", ".html", ".json", ".eml"}:
            raise ValueError("Unsafe raw-capture extension")
        return Path("raw") / "sha256" / digest[:2] / digest[2:4] / f"{digest}{extension}"

    def resolve(self, relative_path: str) -> Path:
        target = (self.private_root / relative_path).resolve()
        root = self.raw_root.resolve()
        if target != root and root not in target.parents:
            raise JobhuntError(
                "Raw capture path is invalid", status=500, code="raw_capture_path_invalid"
            )
        return target

    def store(self, content: bytes, *, mime_type: str, extension: str) -> StoredBlob:
        digest = hashlib.sha256(content).hexdigest()
        relative = self.relative_path(digest, extension)
        target = self.resolve(relative.as_posix())
        target.parent.mkdir(parents=True, exist_ok=True)
        created = False
        if target.exists():
            size, observed = hash_file(target)
            if size != len(content) or observed != digest:
                raise JobhuntError(
                    "Existing raw blob failed integrity verification",
                    status=500,
                    code="raw_blob_integrity_failed",
                )
        else:
            temporary: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    prefix=f".{digest}.", suffix=".tmp", dir=target.parent, delete=False
                ) as handle:
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
                    temporary = Path(handle.name)
                size, observed = hash_file(temporary)
                if size != len(content) or observed != digest:
                    raise JobhuntError(
                        "Raw blob write verification failed",
                        status=500,
                        code="raw_blob_write_failed",
                    )
                os.replace(temporary, target)
                temporary = None
                size, observed = hash_file(target)
                if size != len(content) or observed != digest:
                    raise JobhuntError(
                        "Raw blob final verification failed",
                        status=500,
                        code="raw_blob_write_failed",
                    )
                created = True
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        return StoredBlob(
            sha256=digest,
            byte_size=len(content),
            mime_type=mime_type,
            file_extension=extension,
            relative_path=relative.as_posix(),
            created=created,
        )

    def read_verified(self, *, relative_path: str, expected_hash: str, expected_size: int) -> bytes:
        target = self.resolve(relative_path)
        if not target.is_file():
            raise JobhuntError("Raw capture file is missing", status=409, code="raw_blob_missing")
        size, digest = hash_file(target)
        if size != expected_size or digest != expected_hash:
            raise JobhuntError("Raw capture file is corrupt", status=409, code="raw_blob_corrupt")
        return target.read_bytes()

    def blob_files(self, *, limit: int = 10000) -> Iterable[Path]:
        if not self.raw_root.exists():
            return []
        files: list[Path] = []
        for path in self.raw_root.rglob("*"):
            if path.is_file() and not path.name.startswith("."):
                files.append(path)
                if len(files) >= limit:
                    break
        return files
