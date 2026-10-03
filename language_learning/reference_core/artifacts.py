"""Acquisition and checksum verification for manifest-approved artifacts only."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import shutil
import time
from typing import Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .manifest import ArtifactManifest, SourceManifest


CHUNK_SIZE = 1024 * 1024
USER_AGENT = "cleaning-dashboard-language-reference/7.5B"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class VerifiedArtifact:
    source_id: str
    manifest: ArtifactManifest
    path: Path
    size_bytes: int
    sha256: str
    retrieved_at: str
    http_metadata: dict[str, str]


def sha256_file(path: str | Path) -> tuple[int, str]:
    total = 0
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while True:
            chunk = stream.read(CHUNK_SIZE)
            if not chunk:
                break
            total += len(chunk)
            digest.update(chunk)
    return total, digest.hexdigest()


def require_free_space(paths: Iterable[str | Path], *, minimum_bytes: int) -> dict[str, int]:
    checked: dict[str, int] = {}
    for raw_path in paths:
        path = Path(raw_path).resolve()
        probe = path
        while not probe.exists() and probe.parent != probe:
            probe = probe.parent
        free = shutil.disk_usage(probe).free
        anchor = str(probe.anchor or probe)
        checked[anchor] = min(checked.get(anchor, free), free)
        if free < minimum_bytes:
            raise RuntimeError(
                f"reference build disk gate failed: {free} bytes free at configured destination; "
                f"{minimum_bytes} required"
            )
    return checked


def _verify_frozen(path: Path, artifact: ArtifactManifest, *, allow_unfrozen: bool) -> tuple[int, str]:
    size, checksum = sha256_file(path)
    if artifact.size_bytes is None or artifact.sha256 is None:
        if not allow_unfrozen:
            raise RuntimeError(f"required artifact is not frozen in its manifest: {artifact.name}")
        return size, checksum
    if size != artifact.size_bytes:
        raise RuntimeError(f"size mismatch for {artifact.name}: expected {artifact.size_bytes}, observed {size}")
    if checksum != artifact.sha256:
        raise RuntimeError(f"SHA-256 mismatch for {artifact.name}: expected {artifact.sha256}, observed {checksum}")
    return size, checksum


def acquire_artifact(
    source_id: str,
    artifact: ArtifactManifest,
    destination: str | Path,
    *,
    allow_unfrozen: bool = False,
    retries: int = 3,
    timeout_seconds: int = 60,
    progress: Callable[[str], None] | None = None,
) -> VerifiedArtifact:
    destination_path = Path(destination)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    if destination_path.exists():
        size, checksum = _verify_frozen(destination_path, artifact, allow_unfrozen=allow_unfrozen)
        return VerifiedArtifact(
            source_id, artifact, destination_path, size, checksum,
            artifact.retrieved_at or utc_now(), artifact.http_metadata,
        )

    part = destination_path.with_name(destination_path.name + ".part")
    headers: dict[str, str] = {}
    retrieved_at = utc_now()
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            request = Request(artifact.url, headers={"User-Agent": USER_AGENT})
            with urlopen(request, timeout=timeout_seconds) as response, part.open("wb") as output:
                headers = {
                    key: value for key, value in {
                        "contentType": response.headers.get("Content-Type"),
                        "contentLength": response.headers.get("Content-Length"),
                        "lastModified": response.headers.get("Last-Modified"),
                        "etag": response.headers.get("ETag"),
                        "finalUrl": response.geturl(),
                    }.items() if value
                }
                while True:
                    chunk = response.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    output.write(chunk)
            size, checksum = _verify_frozen(part, artifact, allow_unfrozen=allow_unfrozen)
            os.replace(part, destination_path)
            if progress:
                progress(f"downloaded {source_id}/{artifact.name}: {size} bytes")
            return VerifiedArtifact(
                source_id, artifact, destination_path, size, checksum, retrieved_at, headers
            )
        except (HTTPError, URLError, TimeoutError, OSError, RuntimeError) as exc:
            last_error = exc
            if part.exists():
                part.unlink()
            if attempt < retries:
                time.sleep(min(2 ** (attempt - 1), 4))
    raise RuntimeError(f"failed to acquire {source_id}/{artifact.name}: {last_error}") from last_error


def acquire_sources(
    manifests: Iterable[SourceManifest],
    source_directory: str | Path,
    *,
    allow_unfrozen: bool = False,
    progress: Callable[[str], None] | None = None,
) -> dict[str, tuple[VerifiedArtifact, ...]]:
    root = Path(source_directory)
    result: dict[str, tuple[VerifiedArtifact, ...]] = {}
    for manifest in manifests:
        artifacts = tuple(
            acquire_artifact(
                manifest.source_id,
                artifact,
                root / manifest.source_id / artifact.name,
                allow_unfrozen=allow_unfrozen,
                progress=progress,
            )
            for artifact in manifest.required_artifacts
        )
        result[manifest.source_id] = artifacts
    return result


__all__ = [
    "VerifiedArtifact",
    "acquire_artifact",
    "acquire_sources",
    "require_free_space",
    "sha256_file",
]
