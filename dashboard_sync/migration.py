"""Additive journal migration. Content, IDs and original timestamps are untouched."""
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path

from .backup import backup_database, journal_fingerprint

SCHEMA_VERSION = 1


def needs_migration(path):
    path = Path(path)
    if not path.exists():
        return True
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='sync_schema'").fetchone():
            return True
        version = conn.execute('SELECT version FROM sync_schema').fetchone()[0]
        if version != SCHEMA_VERSION:
            raise RuntimeError(f'Unsupported sync schema {version}')
        return False


def backup_before_migration(path):
    if Path(path).exists() and needs_migration(path):
        return backup_database(path)
    return None


def migrate(conn):
    """Caller owns transaction; no executescript (which commits implicitly)."""
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='sync_schema'").fetchone():
        if conn.execute('SELECT version FROM sync_schema').fetchone()[0] != SCHEMA_VERSION:
            raise RuntimeError('Unsupported sync schema')
        return
    before = journal_fingerprint(conn)
    statements = [
        'CREATE TABLE sync_schema (version INTEGER NOT NULL, epoch TEXT NOT NULL)',
        'ALTER TABLE journal_entries ADD COLUMN sync_version INTEGER NOT NULL DEFAULT 1',
        '''CREATE TABLE sync_changes (change_id INTEGER PRIMARY KEY AUTOINCREMENT,
           entity_type TEXT NOT NULL, entity_id TEXT NOT NULL, operation TEXT NOT NULL,
           entity_version INTEGER NOT NULL, changed_at TEXT NOT NULL)''',
        '''CREATE TABLE sync_tombstones (entity_type TEXT NOT NULL, entity_id TEXT NOT NULL,
           version INTEGER NOT NULL, created_at TEXT NOT NULL, deleted_at TEXT NOT NULL,
           PRIMARY KEY(entity_type, entity_id))''',
        '''CREATE TABLE sync_receipts (device_id TEXT NOT NULL, operation_id TEXT NOT NULL,
           fingerprint TEXT NOT NULL, result_json TEXT NOT NULL, accepted_at TEXT NOT NULL,
           PRIMARY KEY(device_id, operation_id))''',
        '''CREATE TABLE sync_devices (device_id TEXT PRIMARY KEY, display_name TEXT NOT NULL DEFAULT '',
           client_type TEXT NOT NULL DEFAULT '', last_seen TEXT NOT NULL,
           push_count INTEGER NOT NULL DEFAULT 0, pull_count INTEGER NOT NULL DEFAULT 0,
           conflict_count INTEGER NOT NULL DEFAULT 0, failure_count INTEGER NOT NULL DEFAULT 0)''',
        '''CREATE TRIGGER sync_journal_prevent_resurrection BEFORE INSERT ON journal_entries
           WHEN EXISTS(SELECT 1 FROM sync_tombstones WHERE entity_type='journalEntry' AND entity_id=NEW.id)
           BEGIN SELECT RAISE(ABORT, 'sync tombstone forbids resurrection'); END''',
        '''CREATE TRIGGER sync_journal_create AFTER INSERT ON journal_entries BEGIN
           INSERT INTO sync_changes(entity_type,entity_id,operation,entity_version,changed_at)
           VALUES('journalEntry',NEW.id,'create',NEW.sync_version,strftime('%Y-%m-%dT%H:%M:%fZ','now')); END''',
        '''CREATE TRIGGER sync_journal_update AFTER UPDATE OF title,content,content_format,entry_date,
           entry_kind,tags_json,location,illustration_data_url,illustration_alt,source_type,
           source_external_id,source_voice_journal_entry_id,source_metadata_json,published_at,created_at,updated_at
           ON journal_entries BEGIN
           UPDATE journal_entries SET sync_version=OLD.sync_version+1 WHERE id=NEW.id;
           INSERT INTO sync_changes(entity_type,entity_id,operation,entity_version,changed_at)
           VALUES('journalEntry',NEW.id,'update',OLD.sync_version+1,strftime('%Y-%m-%dT%H:%M:%fZ','now')); END''',
        '''CREATE TRIGGER sync_journal_delete AFTER DELETE ON journal_entries BEGIN
           INSERT INTO sync_tombstones VALUES('journalEntry',OLD.id,OLD.sync_version+1,
             OLD.created_at,strftime('%Y-%m-%dT%H:%M:%fZ','now'));
           INSERT INTO sync_changes(entity_type,entity_id,operation,entity_version,changed_at)
           VALUES('journalEntry',OLD.id,'delete',OLD.sync_version+1,strftime('%Y-%m-%dT%H:%M:%fZ','now')); END''',
    ]
    for sql in statements:
        conn.execute(sql)
    conn.execute('INSERT INTO sync_schema VALUES(?,?)', (SCHEMA_VERSION, uuid.uuid4().hex))
    conn.execute('''INSERT INTO sync_changes(entity_type,entity_id,operation,entity_version,changed_at)
                    SELECT 'journalEntry',id,'create',1,updated_at FROM journal_entries ORDER BY id''')
    if journal_fingerprint(conn) != before:
        raise RuntimeError('Migration changed journal content; rolling back')
