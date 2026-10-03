"""Server-side paths for the independent reference-data domain."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class ReferencePaths:
    database: Path
    source_directory: Path


def resolve_reference_paths(
    *,
    environment: Mapping[str, str] | None = None,
    project_root: str | Path | None = None,
) -> ReferencePaths:
    values = os.environ if environment is None else environment
    root = Path(project_root) if project_root is not None else Path(__file__).resolve().parents[2]
    default_root = root / "data" / "reference"
    database = Path(values.get("LANGUAGE_REFERENCE_DB") or default_root / "language-reference-nb.sqlite")
    source_directory = Path(values.get("LANGUAGE_REFERENCE_SOURCE_DIR") or default_root / "sources")
    return ReferencePaths(database=database.expanduser(), source_directory=source_directory.expanduser())


__all__ = ["ReferencePaths", "resolve_reference_paths"]
