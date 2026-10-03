import concurrent.futures
import hashlib
import gc
import json
import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

from dashboard_sync.backup import backup_database, journal_fingerprint
from dashboard_sync.core import SyncError
from dashboard_sync.migration import migrate
from dashboard_sync.service import SyncService
from journal_store import JournalStore


def uid():
    return uuid.uuid4().hex


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'journal.sqlite'
        self.store = JournalStore(self.path)
        self.sync = SyncService(self.store)
        self.a, self.b = uid(), uid()

    def tearDown(self):
        gc.collect()
        self.temp.cleanup()

    def operation(self, action='create', entity_id=None, version=0, **payload):
        return {'operationId': uid(), 'entityType': 'journalEntry', 'id': entity_id or uid(),
                'operation': action, 'expectedVersion': version,
                'payload': payload or ({'content': 'Fixture entry'} if action == 'create' else {})}

    def push(self, *ops, device=None):
        return self.sync.batch({'protocolVersion': 1, 'deviceId': device or self.a, 'operations': list(ops)})['results']

    def pull(self, cursor='0', limit=100):
        return self.sync.changes(protocol_version=1, device_id=self.b, cursor=cursor, limit=limit)

    def test_status(self):
        status = self.sync.status()
        self.assertEqual((status['protocolVersion'], status['schemaVersion'], status['backendStatus']), (1, 1, 'ok'))
        self.assertTrue(status['currentChangeCursor'].endswith(':0'))

    def test_create_read_update_version(self):
        op = self.operation()
        self.assertEqual(self.push(op)[0]['version'], 1)
        entry = self.sync.read('journalEntry', op['id'])['record']
        self.assertEqual(entry['content'], 'Fixture entry')
        self.assertTrue(entry['createdAt'].endswith('Z'))
        self.assertEqual(self.push(self.operation('update', op['id'], 1, title='new'))[0]['version'], 2)
        self.assertEqual(self.store.get(op['id'])['title'], 'new')

    def test_stale_conflict_contains_server_record(self):
        op = self.operation()
        self.push(op)
        self.push(self.operation('update', op['id'], 1, title='A'))
        result = self.push(self.operation('update', op['id'], 1, title='B'), device=self.b)[0]
        self.assertEqual(result['status'], 'conflict')
        self.assertEqual(result['error']['details']['serverRecord']['title'], 'A')
        self.assertEqual(self.store.get(op['id'])['version'], 2)

    def test_tombstone_and_no_resurrection(self):
        op = self.operation()
        self.push(op)
        self.push(self.operation('delete', op['id'], 1))
        tombstone = self.sync.read('journalEntry', op['id'])['record']
        self.assertEqual(tombstone['version'], 2)
        self.assertIsNotNone(tombstone['deletedAt'])
        self.assertEqual(self.store.list(), [])
        for action, version in [('create', 0), ('update', 1), ('update', 2), ('delete', 2)]:
            self.assertEqual(self.push(self.operation(action, op['id'], version, content='stale'))[0]['status'], 'conflict')

    def test_sql_insert_cannot_reuse_tombstoned_id(self):
        op = self.operation()
        self.push(op)
        self.store.delete(op['id'])
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.create({'content': 'old'}, _entry_id=op['id'])

    def test_incremental_order_and_pagination(self):
        first = self.operation()
        self.push(first)
        cursor = self.pull()['nextCursor']
        self.push(self.operation('update', first['id'], 1, title='second'), self.operation())
        page = self.pull(cursor, 1)
        self.assertTrue(page['hasMore'])
        self.assertEqual([c['changeId'] for c in page['changes']], [2])
        last = self.pull(page['nextCursor'], 1)
        self.assertFalse(last['hasMore'])
        self.assertEqual(last['changes'][0]['changeId'], 3)
        self.assertEqual(self.pull(last['nextCursor'])['changes'], [])

    def test_feed_is_reference_to_latest_canonical_record(self):
        op = self.operation()
        self.push(op)
        self.store.update(op['id'], {'title': 'new'})
        page = self.pull(limit=1)
        self.assertEqual(page['changes'][0]['entityVersion'], 1)
        self.assertEqual(page['changes'][0]['record']['version'], 2)

    def test_partial_batch_is_ordered_and_isolated(self):
        op = self.operation()
        bad = self.operation()
        bad['payload'] = {'content': 42}
        result = self.push(op, bad, self.operation('update', op['id'], 1, title='second'))
        self.assertEqual([r['status'] for r in result], ['accepted', 'rejected', 'accepted'])
        self.assertEqual(len(self.pull()['changes']), 2)

    def test_lost_response_retry_is_exact(self):
        op = self.operation()
        first = self.push(op)
        self.assertEqual(self.push(op), first)
        self.assertEqual(len(self.pull()['changes']), 1)
        op['payload']['content'] = 'different'
        self.assertEqual(self.push(op)[0]['error']['code'], 'VALIDATION_ERROR')

    def test_retry_after_later_update_does_not_reapply(self):
        op = self.operation()
        first = self.push(op)
        self.store.update(op['id'], {'title': 'second'})
        self.assertEqual(self.push(op), first)
        self.assertEqual(self.store.get(op['id'])['version'], 2)

    def test_invalid_entity(self):
        for entity in ['todo', None, []]:
            op = self.operation()
            op['entityType'] = entity
            self.assertEqual(self.push(op)[0]['error']['code'], 'UNKNOWN_ENTITY')

    def test_invalid_version(self):
        for version in [True, None, '0', -1, 1, 1.2]:
            op = self.operation()
            op['expectedVersion'] = version
            self.assertEqual(self.push(op)[0]['error']['code'], 'VALIDATION_ERROR')

    def test_invalid_ids_operation_payload(self):
        for key, value in [('id', 'x'), ('operationId', 'x'), ('operation', 'upsert'), ('payload', []), ('payload', {'content': []}), ('payload', {'content': 'ok', 'tags': [1]})]:
            op = self.operation()
            op[key] = value
            self.assertEqual(self.push(op)[0]['status'], 'rejected')

    def test_invalid_cursor(self):
        for cursor in ['-1', 'abc', 3, None, uid() + ':0', self.sync.status()['currentChangeCursor'].split(':')[0] + ':999']:
            with self.assertRaises(SyncError) as error:
                self.pull(cursor)
            self.assertEqual(error.exception.code, 'INVALID_CURSOR')

    def test_unsupported_protocol(self):
        for version in [2, None, True, '1']:
            with self.assertRaises(SyncError) as error:
                self.sync.batch({'protocolVersion': version, 'deviceId': self.a, 'operations': [self.operation()]})
            self.assertEqual(error.exception.code, 'UNSUPPORTED_PROTOCOL_VERSION')

    def test_batch_and_page_limits(self):
        for operations in [[], [self.operation()] * 101, {}]:
            with self.assertRaises(SyncError):
                self.sync.batch({'protocolVersion': 1, 'deviceId': self.a, 'operations': operations})
        for limit in [0, 101, True, '10']:
            with self.assertRaises(SyncError):
                self.pull(limit=limit)

    def test_not_found(self):
        self.assertEqual(self.push(self.operation('delete', uid(), 1))[0]['error']['code'], 'NOT_FOUND')
        with self.assertRaises(SyncError):
            self.sync.read('journalEntry', uid())

    def test_restart_preserves_cursor_tombstone_receipt(self):
        op = self.operation()
        self.push(op)
        deletion = self.operation('delete', op['id'], 1)
        result = self.push(deletion)
        head = self.sync.status()['currentChangeCursor']
        self.store = JournalStore(self.path)
        self.sync = SyncService(self.store)
        self.assertEqual(self.sync.status()['currentChangeCursor'], head)
        self.assertEqual(self.push(deletion), result)
        self.assertIsNotNone(self.sync.read('journalEntry', op['id'])['record']['deletedAt'])

    def test_transaction_rolls_back_record_and_change_on_receipt_failure(self):
        self.sync.status()
        with self.store._connect() as conn:
            conn.execute("CREATE TRIGGER fail_receipt BEFORE INSERT ON sync_receipts BEGIN SELECT RAISE(ABORT,'fixture'); END")
        self.assertEqual(self.push(self.operation())[0]['error']['code'], 'INTERNAL_ERROR')
        self.assertEqual(self.store.list(), [])
        self.assertEqual(self.pull()['changes'], [])

    def test_concurrent_writers_only_one_wins(self):
        op = self.operation()
        self.push(op)
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda title: self.push(self.operation('update', op['id'], 1, title=title))[0]['status'], ['A', 'B']))
        self.assertCountEqual(results, ['accepted', 'conflict'])

    def test_legacy_crud_records_all_changes(self):
        entry = self.store.create({'content': 'PC', 'entryDate': '2026-01-01'})
        self.store.update(entry['id'], {'title': 'PC edit'}, expected_version=1)
        with self.assertRaises(SyncError):
            self.store.delete(entry['id'], expected_version=1)
        self.store.delete(entry['id'], expected_version=2)
        self.assertEqual([row['operation'] for row in self.pull()['changes']], ['create', 'update', 'delete'])

    def test_publication_and_import_use_same_journal(self):
        voice = {'id': uid(), 'transcript': 'voice', 'recordedAt': '2026-01-01T00:00:00Z'}
        self.store.publish_voice_entry(voice)
        self.store.publish_voice_entry({**voice, 'transcript': 'revised'})
        self.store.publish_htr_entry({'content': 'HTR', 'sourceMetadata': {}})
        self.store.import_external_entry({'content': 'import', 'entryDate': '2026-01-01', 'sourceType': 'fixture', 'sourceExternalId': 'a'})
        self.assertEqual(len(self.pull()['changes']), 4)

    def test_device_diagnostics_without_payloads(self):
        op = self.operation()
        self.push(op)
        self.push(self.operation('update', op['id'], 99, title='stale'))
        self.pull()
        devices = self.sync.status()['devices']
        self.assertEqual(sum(d['conflict_count'] for d in devices), 1)
        self.assertNotIn('Fixture entry', json.dumps(devices))

    def test_two_clients_all_acceptance_scenarios(self):
        op = self.operation()
        accepted = self.push(op)
        page = self.pull()
        self.assertEqual(page['changes'][0]['record']['id'], op['id'])
        self.push(self.operation('update', op['id'], 1, content='A version 2'))
        self.assertEqual(self.push(self.operation('update', op['id'], 1, content='B stale'), device=self.b)[0]['status'], 'conflict')
        self.push(self.operation('delete', op['id'], 2))
        self.assertEqual(self.push(self.operation('update', op['id'], 1, content='offline'), device=self.b)[0]['status'], 'conflict')
        self.assertEqual(self.push(op), accepted)
        self.assertEqual([row['changeId'] for row in self.pull(page['nextCursor'])['changes']], [2, 3])

    def test_migration_backup_restore_and_second_run(self):
        # Build a true pre-Sync fixture using the original initializer with migration disabled.
        with mock.patch('journal_store.migrate'), mock.patch('journal_store.backup_before_migration'):
            self.store.initialize()
        with sqlite3.connect(self.path) as conn:
            conn.execute("INSERT INTO journal_entries(id,title,content,entry_date,created_at,updated_at) VALUES(?,?,?,?,?,?)", (uid(), 'Original title', 'original', '2020-01-01', '2020-01-01T00:00:00Z', '2020-01-02T00:00:00Z'))
            before = journal_fingerprint(conn)
        self.store = JournalStore(self.path)
        self.store.initialize()
        self.sync = SyncService(self.store)
        with self.store._connect() as conn:
            self.assertEqual(journal_fingerprint(conn), before)
        manifests = list(Path(self.temp.name).glob('backups/dashboard-sync-api/*/manifest.json'))
        self.assertEqual(len(manifests), 1)
        manifest = json.loads(manifests[0].read_text())
        backup = Path(manifest['backupPath'])
        self.assertEqual(hashlib.sha256(backup.read_bytes()).hexdigest(), manifest['sha256'])
        self.assertEqual(manifest['journal'], before)
        entry = self.store.list()[0]
        self.store.update(entry['id'], {'title': 'after'})
        head = self.sync.status()['currentChangeCursor']
        JournalStore(self.path).initialize()
        self.assertEqual(self.sync.status()['currentChangeCursor'], head)
        self.assertEqual(self.store.get(entry['id'])['version'], 2)
        self.assertEqual(len(list(Path(self.temp.name).glob('backups/dashboard-sync-api/*/manifest.json'))), 1)
        restored = Path(self.temp.name) / 'restored.sqlite'
        with sqlite3.connect(backup) as src, sqlite3.connect(restored) as dst:
            src.backup(dst)
            self.assertEqual(journal_fingerprint(dst), before)
        restored_store = JournalStore(restored)
        self.assertEqual(restored_store.list()[0]['version'], 1)

    def test_backup_of_migrated_state(self):
        op = self.operation()
        self.push(op)
        deletion = self.operation('delete', op['id'], 1)
        receipt = self.push(deletion)
        manifest = backup_database(self.path)
        self.assertEqual(manifest['schemaVersion'], 1)
        self.assertEqual(manifest['journal']['count'], 0)
        restored = Path(self.temp.name) / 'post-sync-restored.sqlite'
        with sqlite3.connect(manifest['backupPath']) as src, sqlite3.connect(restored) as dst:
            src.backup(dst)
        restored_sync = SyncService(JournalStore(restored))
        self.assertEqual(restored_sync.batch({'protocolVersion': 1, 'deviceId': self.a, 'operations': [deletion]})['results'], receipt)
        self.assertTrue(restored_sync.read('journalEntry', op['id'])['record']['deletedAt'])

    def test_migration_does_not_touch_other_tables_or_files(self):
        other = Path(self.temp.name) / 'todo.json'
        other.write_text('[{"id":"preserve"}]')
        with mock.patch('journal_store.migrate'), mock.patch('journal_store.backup_before_migration'):
            self.store.initialize()
        with sqlite3.connect(self.path) as conn:
            conn.execute('CREATE TABLE unrelated (value TEXT)')
            conn.execute("INSERT INTO unrelated VALUES('preserve')")
        JournalStore(self.path).initialize()
        self.assertEqual(other.read_text(), '[{"id":"preserve"}]')
        with sqlite3.connect(self.path) as conn:
            self.assertEqual(conn.execute('SELECT value FROM unrelated').fetchone()[0], 'preserve')


if __name__ == '__main__':
    unittest.main()
