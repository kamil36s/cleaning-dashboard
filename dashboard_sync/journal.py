"""Domain adapter: reuse JournalStore validation and writes on the caller transaction."""
from contextlib import nullcontext

from .core import SyncError


class JournalAdapter:
    entity_type = 'journalEntry'

    def __init__(self, store):
        self.store = store

    def get(self, conn, entity_id):
        row = conn.execute('SELECT * FROM journal_entries WHERE id=?', (entity_id,)).fetchone()
        if row:
            return self.store._row_to_entry(row)
        row = conn.execute("SELECT * FROM sync_tombstones WHERE entity_type=? AND entity_id=?", (self.entity_type, entity_id)).fetchone()
        if row:
            return {'id': row['entity_id'], 'version': row['version'], 'createdAt': row['created_at'],
                    'updatedAt': row['deleted_at'], 'deletedAt': row['deleted_at']}
        return None

    def apply(self, conn, operation):
        # Borrow a transaction without changing the process-wide store or opening a second writer.
        from journal_store import JournalStore, JournalError, MUTABLE_FIELDS
        class TransactionStore(JournalStore):
            def initialize(self):
                pass

            def _connect(self):
                return nullcontext(conn)

        store = TransactionStore(self.store.db_path)
        payload = operation.get('payload', {})
        if not isinstance(payload, dict) or set(payload) - MUTABLE_FIELDS:
            raise SyncError('VALIDATION_ERROR', 'Invalid journal fields')
        for key, value in payload.items():
            if key == 'tags':
                if not isinstance(value, list) or len(value) > 20 or any(not isinstance(tag, str) for tag in value):
                    raise SyncError('VALIDATION_ERROR', 'tags must contain up to 20 strings')
            elif not isinstance(value, str):
                raise SyncError('VALIDATION_ERROR', f'{key} must be a string')
        try:
            if operation['operation'] == 'create':
                store.create(payload, _entry_id=operation['id'])
            elif operation['operation'] == 'update':
                store.update(operation['id'], payload)
            else:
                if payload:
                    raise SyncError('VALIDATION_ERROR', 'delete does not accept fields')
                store.delete(operation['id'])
        except JournalError as exc:
            raise SyncError('VALIDATION_ERROR', str(exc)) from exc
