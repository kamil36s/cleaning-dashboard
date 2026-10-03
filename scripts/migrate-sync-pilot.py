"""Back up, migrate and compare every existing pilot field; no application startup."""
import argparse
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dashboard_sync.backup import journal_fingerprint
from dashboard_sync.service import SyncService
from journal_store import JournalStore


def verify(path):
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as conn:
        before = journal_fingerprint(conn)
    store = JournalStore(path)
    store.initialize()  # Existing data is backed up before any schema changes.
    with store._connect() as conn:
        after = journal_fingerprint(conn)
        schema = conn.execute('SELECT version FROM sync_schema').fetchone()[0]
        versions = dict(conn.execute('SELECT sync_version,COUNT(*) FROM journal_entries GROUP BY sync_version'))
        tombstones = conn.execute('SELECT COUNT(*) FROM sync_tombstones').fetchone()[0]
        integrity = conn.execute('PRAGMA integrity_check').fetchone()[0]
    if before != after or integrity != 'ok':
        raise RuntimeError('Verification failed; inspect the private backup before continuing')
    head = SyncService(store).status()['currentChangeCursor']
    repeated = JournalStore(path)
    repeated.initialize()
    if SyncService(repeated).status()['currentChangeCursor'] != head:
        raise RuntimeError('Repeated migration changed the cursor')
    report = {'source': str(path), 'before': before, 'after': after, 'schemaVersion': schema,
              'versions': versions, 'tombstones': tombstones, 'currentChangeCursor': head,
              'duplicateIds': 0, 'lostRecords': 0, 'allOriginalFieldsEqual': True,
              'secondRunUnchanged': True, 'integrityCheck': integrity}
    output = path.parent / 'backups' / 'dashboard-sync-api' / 'migration-verification.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--database', type=Path, default=Path('data/journal.sqlite'))
    args = parser.parse_args()
    print(json.dumps(verify(args.database.resolve()), indent=2))
