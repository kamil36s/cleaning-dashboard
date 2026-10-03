"""SQLite online backups with private verification manifests (no record payloads)."""
import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


def journal_fingerprint(connection):
    columns = [row[1] for row in connection.execute('PRAGMA table_info(journal_entries)') if row[1] != 'sync_version']
    if not columns:
        return {'count': 0, 'sha256': None}
    digest = hashlib.sha256()
    count = 0
    for row in connection.execute('SELECT ' + ','.join(columns) + ' FROM journal_entries ORDER BY id'):
        digest.update(json.dumps(tuple(row), ensure_ascii=False, separators=(',', ':')).encode('utf-8'))
        digest.update(b'\n')
        count += 1
    return {'count': count, 'sha256': digest.hexdigest()}


def backup_database(source, destination_root=None):
    source = Path(source).resolve()
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    root = Path(destination_root) if destination_root else source.parent / 'backups' / 'dashboard-sync-api'
    directory = root / timestamp
    directory.mkdir(parents=True, exist_ok=False)
    target = directory / source.name
    with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as original:
        with closing(sqlite3.connect(target)) as backup:
            original.backup(backup)
            if backup.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise RuntimeError('Backup integrity check failed')
            fingerprint = journal_fingerprint(backup)
            tables = {row[0] for row in backup.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            schema = backup.execute('SELECT version FROM sync_schema').fetchone()[0] if 'sync_schema' in tables else 0
    manifest = {
        'timestamp': timestamp, 'schemaVersion': schema, 'source': str(source),
        'backupPath': str(target), 'size': target.stat().st_size,
        'sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
        'journal': fingerprint, 'integrityCheck': 'ok',
    }
    (directory / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return manifest
