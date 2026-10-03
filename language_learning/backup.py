"""Versioned, offline disaster recovery for the Language user store.

The package contains a SQLite backup-API snapshot and only DB-owned Content
Inbox media. Reference facts, model files and generated audio are dependencies,
not user-state backup payloads.
"""

from __future__ import annotations

from datetime import datetime, timezone
from contextlib import closing
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import tempfile
import uuid

from .migrations import SCHEMA_VERSION
from .store import EXPORT_VERSION, LanguageStore
from .reference_core.schema import REFERENCE_SCHEMA_VERSION


FORMAT = "language-backup/v1"
DB_NAME = "language-learning.sqlite"
MANIFEST_NAME = "manifest.json"
STATIC_FILES = {
    "benchmarkContent": Path("language_learning/benchmark_content/v1.json"),
}


class BackupError(ValueError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _artifact_digest(path: Path) -> str:
    return "sha256:" + _sha256(path)


def _safe_relative(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise BackupError("Unsafe backup relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in (".", "..", "") for part in value.split("/")):
        raise BackupError("Unsafe backup relative path")
    if path.as_posix() != value:
        raise BackupError("Noncanonical backup relative path")
    return value


def _file_beneath(root: Path, relative: str) -> Path:
    parts = PurePosixPath(_safe_relative(relative)).parts
    current = root
    if current.is_symlink():
        raise BackupError("Symlink backup root is unsupported")
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise BackupError("Symlink in backup path")
    if not current.resolve().is_relative_to(root.resolve()):
        raise BackupError("Backup path escapes its root")
    return current


def _db_connection(path: Path, *, immutable: bool = False) -> sqlite3.Connection:
    if not path.is_file() or path.is_symlink():
        raise BackupError("Language database is missing or unsafe")
    connection = sqlite3.connect(path.resolve().as_uri() +
                                 ("?mode=ro&immutable=1" if immutable else "?mode=ro"), uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _db_facts(path: Path) -> tuple[int, list[dict]]:
    try:
        with closing(_db_connection(path, immutable=True)) as connection:
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise BackupError("SQLite integrity_check failed")
            if connection.execute("PRAGMA foreign_key_check").fetchone():
                raise BackupError("SQLite foreign_key_check failed")
            version = int(connection.execute(
                "SELECT COALESCE(MAX(version),0) FROM language_schema_migrations"
            ).fetchone()[0])
            rows = [dict(row) for row in connection.execute(
                "SELECT id,managed_relpath,byte_size,checksum FROM content_artifacts ORDER BY id"
            )]
            return version, rows
    except sqlite3.Error as exc:
        raise BackupError("Language database cannot be validated") from exc


def _artifact_path(row: dict) -> str:
    artifact_id = row["id"]
    rel = _safe_relative(row["managed_relpath"])
    if not isinstance(artifact_id, str) or not artifact_id or "/" in rel:
        raise BackupError("Unsafe managed artifact metadata")
    if not rel.startswith(artifact_id + ".") or Path(rel).suffix.lower() not in (".mp3", ".wav", ".ogg", ".m4a"):
        raise BackupError("Managed artifact name does not match its ID")
    return "artifacts/" + rel


def _reference_dependency(path: Path) -> dict:
    if not path.is_file():
        return {"schemaVersion": REFERENCE_SCHEMA_VERSION, "sourceFingerprint": None,
                "state": "UNAVAILABLE"}
    try:
        with closing(_db_connection(path)) as connection:
            version = int(connection.execute(
                "SELECT COALESCE(MAX(version),0) FROM reference_schema_migrations"
            ).fetchone()[0])
            source_rows = [tuple(row) for row in connection.execute(
                "SELECT source_id,version FROM reference_sources ORDER BY source_id"
            )]
            artifact_rows = [tuple(row) for row in connection.execute(
                "SELECT source_id,filename,sha256,parser_id,parser_version "
                "FROM reference_source_artifacts ORDER BY source_id,filename"
            )]
            ledger = [tuple(row) for row in connection.execute(
                "SELECT version,checksum FROM reference_schema_migrations ORDER BY version"
            )]
        payload = json.dumps([ledger, source_rows, artifact_rows], ensure_ascii=False,
                             separators=(",", ":"))
        return {"schemaVersion": version,
                "sourceFingerprint": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
                "state": "AVAILABLE"}
    except (sqlite3.Error, BackupError):
        return {"schemaVersion": REFERENCE_SCHEMA_VERSION, "sourceFingerprint": None,
                "state": "UNAVAILABLE"}


def _static_contracts(project_root: Path) -> dict:
    result = {key: _sha256(project_root / relative) for key, relative in STATIC_FILES.items()}
    for path in sorted((project_root / "language_learning/curriculum_packs").glob("*.json")):
        result[f"curriculum/{path.name}"] = _sha256(path)
    return result


def _stanza_dependency() -> dict:
    try:
        package = importlib.metadata.version("stanza")
    except importlib.metadata.PackageNotFoundError:
        package = None
    return {"packageVersion": package, "resourceVersion": "1.14.0",
            "language": "nb", "processors": ["tokenize", "pos", "lemma", "depparse"]}


def _stanza_provisioned() -> bool:
    from .grammar_parser import GrammarParser
    return GrammarParser().health().get("state") == "AVAILABLE"


def create_backup(database: Path, destination_root: Path, *, project_root: Path,
                  reference_db: Path | None = None) -> Path:
    """Create a uniquely named package without writing canonical learning data."""
    database, destination_root = Path(database), Path(destination_root)
    project_root = Path(project_root)
    if not database.is_file():
        raise BackupError("Language database does not exist")
    destination_root.mkdir(parents=True, exist_ok=True)
    name = datetime.now(timezone.utc).strftime("language-%Y%m%dT%H%M%S%fZ-") + uuid.uuid4().hex[:8]
    package = destination_root / name
    package.mkdir(exist_ok=False)
    try:
        snapshot = package / DB_NAME
        with closing(_db_connection(database)) as source, closing(sqlite3.connect(snapshot)) as target:
            source.backup(target)
        version, rows = _db_facts(snapshot)
        if version != SCHEMA_VERSION:
            raise BackupError(f"Unsupported source schema v{version}; expected v{SCHEMA_VERSION}")
        media_root = database.parent / "language-learning" / "media"
        artifacts = []
        seen = set()
        for row in rows:
            relative = _artifact_path(row)
            if relative in seen:
                raise BackupError("Duplicate managed artifact path")
            seen.add(relative)
            source_file = _file_beneath(media_root, row["managed_relpath"])
            if not source_file.is_file():
                raise BackupError(f"Required managed artifact is missing: {row['id']}")
            if source_file.stat().st_size != row["byte_size"] or _artifact_digest(source_file) != row["checksum"]:
                raise BackupError(f"Managed artifact does not match SQLite: {row['id']}")
            target_file = _file_beneath(package, relative)
            target_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_file, target_file)
            if target_file.stat().st_size != row["byte_size"] or _artifact_digest(target_file) != row["checksum"]:
                raise BackupError("Managed artifact changed during backup")
            artifacts.append({"id": row["id"], "path": relative,
                              "size": row["byte_size"], "sha256": row["checksum"]})
        reference_db = Path(reference_db) if reference_db else project_root / "data/reference/language-reference-nb.sqlite"
        manifest = {
            "backupFormatVersion": FORMAT,
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "mainSchemaVersion": version, "languageExportVersion": EXPORT_VERSION,
            "mainDb": {"path": DB_NAME, "size": snapshot.stat().st_size,
                       "sha256": _sha256(snapshot)},
            "managedArtifacts": artifacts,
            "reference": _reference_dependency(reference_db),
            "analyzer": _stanza_dependency(),
            "staticContracts": _static_contracts(project_root),
        }
        (package / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        result = validate_backup(package, project_root=project_root, reference_db=reference_db)
        if result["status"] == "INVALID":
            raise BackupError("New backup failed validation: " + "; ".join(result["errors"]))
        return package
    except Exception:
        shutil.rmtree(package)
        raise


def validate_backup(package: Path, *, project_root: Path,
                    reference_db: Path | None = None) -> dict:
    """Read-only validation; never initializes or migrates the source package."""
    package, project_root = Path(package), Path(project_root)
    errors: list[str] = []
    warnings: list[str] = []
    manifest: dict = {}
    try:
        manifest_file = _file_beneath(package, MANIFEST_NAME)
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or manifest.get("backupFormatVersion") != FORMAT:
            raise BackupError("Unsupported backup format")
        if manifest.get("mainSchemaVersion") != SCHEMA_VERSION or manifest.get("languageExportVersion") != EXPORT_VERSION:
            raise BackupError("Unsupported main schema/export version")
        db_info = manifest.get("mainDb")
        if not isinstance(db_info, dict) or db_info.get("path") != DB_NAME:
            raise BackupError("Invalid main database manifest entry")
        db = _file_beneath(package, db_info["path"])
        if db.stat().st_size != db_info.get("size") or _sha256(db) != db_info.get("sha256"):
            raise BackupError("Main database size/hash mismatch")
        version, rows = _db_facts(db)
        if version != manifest["mainSchemaVersion"]:
            raise BackupError("Main database schema mismatch")
        expected = {}
        for row in rows:
            relative = _artifact_path(row)
            if relative in expected:
                raise BackupError("Duplicate SQLite managed artifact path")
            expected[relative] = (row["id"], row["byte_size"], row["checksum"])
        entries = manifest.get("managedArtifacts")
        if not isinstance(entries, list):
            raise BackupError("Invalid managed artifact inventory")
        seen = set()
        for entry in entries:
            if not isinstance(entry, dict):
                raise BackupError("Invalid managed artifact entry")
            relative = _safe_relative(entry.get("path"))
            if relative in seen or relative not in expected:
                raise BackupError("Duplicate or orphan manifest artifact")
            seen.add(relative)
            if (entry.get("id"), entry.get("size"), entry.get("sha256")) != expected[relative]:
                raise BackupError("Managed artifact manifest does not match SQLite")
            file = _file_beneath(package, relative)
            if file.stat().st_size != entry["size"] or _artifact_digest(file) != entry["sha256"]:
                raise BackupError("Managed artifact size/hash mismatch")
        if seen != set(expected):
            raise BackupError("Required managed artifact is missing from manifest")
        actual = set()
        for file in package.rglob("*"):
            if file.is_symlink():
                raise BackupError("Symlink in backup package")
            if file.is_file():
                actual.add(file.relative_to(package).as_posix())
        extra = actual - {MANIFEST_NAME, DB_NAME} - seen
        if extra:
            warnings.append(f"Unreferenced package files: {len(extra)}")
        static = manifest.get("staticContracts")
        if not isinstance(static, dict) or static != _static_contracts(project_root):
            raise BackupError("Static content contract mismatch")
        analyzer = manifest.get("analyzer")
        if not isinstance(analyzer, dict) or analyzer.get("resourceVersion") != "1.14.0":
            raise BackupError("Unsupported analyzer resource contract")
        installed_package = _stanza_dependency()["packageVersion"]
        if installed_package != analyzer.get("packageVersion"):
            warnings.append("Installed Stanza package differs from backup dependency")
        if not _stanza_provisioned():
            warnings.append("Bokmal Stanza resources require explicit provisioning")
        reference = manifest.get("reference")
        if not isinstance(reference, dict) or reference.get("schemaVersion") != REFERENCE_SCHEMA_VERSION:
            raise BackupError("Unsupported reference schema contract")
        reference_db = Path(reference_db) if reference_db else project_root / "data/reference/language-reference-nb.sqlite"
        current = _reference_dependency(reference_db)
        if current["state"] != "AVAILABLE":
            warnings.append("Reference DB unavailable; reference-dependent features require reprovisioning")
        elif current["schemaVersion"] != reference["schemaVersion"]:
            warnings.append("Reference DB schema differs from backup dependency")
        elif reference.get("sourceFingerprint") and current["sourceFingerprint"] != reference["sourceFingerprint"]:
            warnings.append("Reference source fingerprint differs from backup")
        if reference.get("state") != "AVAILABLE":
            warnings.append("Source reference DB was unavailable when backup was created")
    except (BackupError, OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
        errors.append(str(exc) or type(exc).__name__)
    return {"status": "INVALID" if errors else "VALID_WITH_WARNINGS" if warnings else "VALID",
            "errors": errors, "warnings": warnings,
            "backupFormatVersion": manifest.get("backupFormatVersion"),
            "mainSchemaVersion": manifest.get("mainSchemaVersion"),
            "artifactCount": len(manifest.get("managedArtifacts", [])) if isinstance(manifest.get("managedArtifacts"), list) else 0,
            "reference": manifest.get("reference"), "analyzer": manifest.get("analyzer")}


def preview_restore(package: Path, target: Path, *, project_root: Path,
                    reference_db: Path | None = None) -> dict:
    result = validate_backup(package, project_root=project_root, reference_db=reference_db)
    target = Path(target)
    result["targetEmpty"] = not target.is_symlink() and (
        not target.exists() or (target.is_dir() and not any(target.iterdir()))
    )
    result["operations"] = ["create staged destination", "copy SQLite snapshot",
                            "copy managed Inbox artifacts", "validate staged store",
                            "publish clean destination"] if result["status"] != "INVALID" else []
    if not result["targetEmpty"]:
        result["errors"].append("Target is not empty")
        result["status"] = "INVALID"
    return result


def restore_backup(package: Path, target: Path, *, project_root: Path,
                   reference_db: Path | None = None) -> dict:
    result = preview_restore(package, target, project_root=project_root, reference_db=reference_db)
    if result["status"] == "INVALID":
        raise BackupError("Restore refused: " + "; ".join(result["errors"]))
    package, target = Path(package), Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".language-restore-", dir=target.parent))
    try:
        data = staging / "data"
        media = data / "language-learning" / "media"
        media.mkdir(parents=True)
        manifest = json.loads(_file_beneath(package, MANIFEST_NAME).read_text(encoding="utf-8"))
        shutil.copyfile(_file_beneath(package, DB_NAME), data / DB_NAME)
        if _sha256(data / DB_NAME) != manifest["mainDb"]["sha256"]:
            raise BackupError("SQLite snapshot changed during restore")
        for entry in manifest["managedArtifacts"]:
            source = _file_beneath(package, entry["path"])
            destination = _file_beneath(media, PurePosixPath(entry["path"]).name)
            shutil.copyfile(source, destination)
        if _db_facts(data / DB_NAME)[0] != SCHEMA_VERSION:
            raise BackupError("Restored database schema mismatch")
        for row in _db_facts(data / DB_NAME)[1]:
            file = _file_beneath(media, row["managed_relpath"])
            if file.stat().st_size != row["byte_size"] or _artifact_digest(file) != row["checksum"]:
                raise BackupError("Restored managed artifact mismatch")
        LanguageStore(data / DB_NAME).initialize()
        if target.exists():
            target.rmdir()  # only an empty destination is accepted
        os.replace(staging, target)
        return {"status": "RESTORED", "target": str(target),
                "schemaVersion": SCHEMA_VERSION, "artifactCount": result["artifactCount"],
                "warnings": result["warnings"]}
    except Exception:
        shutil.rmtree(staging)
        raise
