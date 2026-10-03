"""Bounded push/pull with SQLite transactions and durable accepted-operation receipts."""
import hashlib
import json
import re

from .core import MAX_BATCH, MAX_PAGE, PROTOCOL_VERSION, SyncError, encoded, require_version, utc_now, uuid_id
from .journal import JournalAdapter


class SyncService:
    def __init__(self, store):
        self.store = store
        self.adapters = {'journalEntry': JournalAdapter(store)}

    def connect(self):
        self.store.initialize()
        return self.store._connect()

    def adapter(self, entity_type):
        if not isinstance(entity_type, str) or entity_type not in self.adapters:
            raise SyncError('UNKNOWN_ENTITY', 'Unsupported entity type')
        return self.adapters[entity_type]

    @staticmethod
    def cursor(conn, sequence=None):
        epoch = conn.execute('SELECT epoch FROM sync_schema').fetchone()[0]
        if sequence is None:
            sequence = conn.execute('SELECT COALESCE(MAX(change_id),0) FROM sync_changes').fetchone()[0]
        return f'{epoch}:{sequence}'

    def status(self):
        with self.connect() as conn:
            return {'protocolVersion': PROTOCOL_VERSION, 'schemaVersion': 1, 'serverTime': utc_now(),
                    'currentChangeCursor': self.cursor(conn), 'backendStatus': 'ok',
                    'entityTypes': list(self.adapters), 'maxBatchSize': MAX_BATCH, 'maxPageSize': MAX_PAGE,
                    'devices': [dict(row) for row in conn.execute('SELECT * FROM sync_devices ORDER BY device_id')]}

    def read(self, entity_type, entity_id):
        adapter = self.adapter(entity_type)
        entity_id = uuid_id(entity_id, 'id')
        with self.connect() as conn:
            record = adapter.get(conn, entity_id)
        if record is None:
            raise SyncError('NOT_FOUND', 'Record not found', 404)
        return {'protocolVersion': PROTOCOL_VERSION, 'entityType': entity_type, 'record': record}

    @staticmethod
    def track(conn, device, *, push=0, pull=0, conflicts=0, failures=0, display='', client=''):
        conn.execute('''INSERT INTO sync_devices(device_id,display_name,client_type,last_seen,push_count,pull_count,conflict_count,failure_count)
            VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(device_id) DO UPDATE SET last_seen=excluded.last_seen,
            display_name=CASE WHEN excluded.display_name='' THEN display_name ELSE excluded.display_name END,
            client_type=CASE WHEN excluded.client_type='' THEN client_type ELSE excluded.client_type END,
            push_count=push_count+excluded.push_count,pull_count=pull_count+excluded.pull_count,
            conflict_count=conflict_count+excluded.conflict_count,failure_count=failure_count+excluded.failure_count''',
            (device, display, client, utc_now(), push, pull, conflicts, failures))

    def changes(self, *, protocol_version, device_id, cursor='0', limit=100):
        require_version(protocol_version)
        device_id = uuid_id(device_id, 'deviceId')
        if type(limit) is not int or not 1 <= limit <= MAX_PAGE:
            raise SyncError('VALIDATION_ERROR', f'limit must be 1..{MAX_PAGE}')
        with self.connect() as conn:
            # One snapshot includes journal references and canonical records. Short write transaction
            # also persists diagnostic counters without upgrading a stale WAL read transaction.
            conn.execute('BEGIN IMMEDIATE')
            head = self.cursor(conn)
            epoch, maximum = head.split(':')
            if cursor == '0':
                sequence = 0
            elif isinstance(cursor, str) and re.fullmatch(re.escape(epoch) + r':(?:0|[1-9][0-9]{0,18})', cursor):
                sequence = int(cursor.split(':')[1])
                if sequence > int(maximum):
                    raise SyncError('INVALID_CURSOR', 'Cursor is ahead of this database')
            else:
                raise SyncError('INVALID_CURSOR', 'Cursor is malformed or belongs to another database')
            rows = conn.execute('SELECT * FROM sync_changes WHERE change_id>? ORDER BY change_id LIMIT ?', (sequence, limit + 1)).fetchall()
            changes = []
            response_bytes = 0
            for row in rows[:limit]:
                change = {'changeId': row['change_id'], 'entityType': row['entity_type'],
                    'id': row['entity_id'], 'operation': row['operation'], 'entityVersion': row['entity_version'],
                    'changedAt': row['changed_at'], 'record': self.adapter(row['entity_type']).get(conn, row['entity_id'])}
                size = len(encoded(change).encode('utf-8'))
                if changes and response_bytes + size > 8 * 1024 * 1024:
                    break
                changes.append(change)
                response_bytes += size
            next_sequence = changes[-1]['changeId'] if changes else sequence
            self.track(conn, device_id, pull=len(changes))
            return {'protocolVersion': PROTOCOL_VERSION, 'changes': changes,
                    'nextCursor': self.cursor(conn, next_sequence), 'hasMore': len(rows) > len(changes)}

    def batch(self, request):
        if not isinstance(request, dict):
            raise SyncError('VALIDATION_ERROR', 'Request must be an object')
        require_version(request.get('protocolVersion'))
        device = uuid_id(request.get('deviceId'), 'deviceId')
        operations = request.get('operations')
        if not isinstance(operations, list) or not 1 <= len(operations) <= MAX_BATCH:
            raise SyncError('VALIDATION_ERROR', f'operations must contain 1..{MAX_BATCH} items')
        display, client = request.get('displayName', ''), request.get('clientType', '')
        if any(not isinstance(value, str) or len(value) > 100 for value in (display, client)):
            raise SyncError('VALIDATION_ERROR', 'Invalid device metadata')
        results = []
        for index, operation in enumerate(operations):
            try:
                result = self.mutate(device, operation)
            except SyncError as exc:
                result = {'status': 'conflict' if exc.code == 'VERSION_CONFLICT' else 'rejected', **exc.payload()}
            except Exception:
                # Do not disclose private SQL/payloads. Failure is isolated to this operation.
                result = {'status': 'rejected', **SyncError('INTERNAL_ERROR', 'Operation failed', 500).payload()}
            results.append({'index': index, **result})
        with self.connect() as conn:
            self.track(conn, device, push=len(operations), display=display, client=client,
                       conflicts=sum(r['status'] == 'conflict' for r in results),
                       failures=sum(r['status'] == 'rejected' for r in results))
        return {'protocolVersion': PROTOCOL_VERSION, 'results': results}

    def mutate(self, device, operation):
        if not isinstance(operation, dict):
            raise SyncError('VALIDATION_ERROR', 'Operation must be an object')
        if set(operation) - {'operationId', 'entityType', 'id', 'operation', 'expectedVersion', 'payload'}:
            raise SyncError('VALIDATION_ERROR', 'Unknown operation fields')
        adapter = self.adapter(operation.get('entityType'))
        operation_id = uuid_id(operation.get('operationId'), 'operationId')
        entity_id = uuid_id(operation.get('id'), 'id')
        action, expected = operation.get('operation'), operation.get('expectedVersion')
        if action not in ('create', 'update', 'delete'):
            raise SyncError('VALIDATION_ERROR', 'Invalid operation')
        if type(expected) is not int or not 0 <= expected <= 9007199254740991 or (action == 'create' and expected != 0) or (action != 'create' and expected == 0):
            raise SyncError('VALIDATION_ERROR', 'Invalid expectedVersion')
        try:
            fingerprint = hashlib.sha256(encoded(operation).encode('utf-8')).hexdigest()
        except (ValueError, TypeError):
            raise SyncError('VALIDATION_ERROR', 'Payload must be finite JSON')
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            receipt = conn.execute('SELECT * FROM sync_receipts WHERE device_id=? AND operation_id=?', (device, operation_id)).fetchone()
            if receipt:
                if receipt['fingerprint'] != fingerprint:
                    raise SyncError('VALIDATION_ERROR', 'operationId was already used for different content')
                return json.loads(receipt['result_json'])
            current = adapter.get(conn, entity_id)
            if current and (action == 'create' or current['version'] != expected or current.get('deletedAt')):
                raise SyncError('VERSION_CONFLICT', 'Record changed; resolve explicitly', 409,
                    entityType=adapter.entity_type, id=entity_id, clientVersion=expected,
                    serverVersion=current['version'], serverRecord=current)
            if current is None and action != 'create':
                raise SyncError('NOT_FOUND', 'Record not found', 404)
            adapter.apply(conn, {**operation, 'id': entity_id})
            record = adapter.get(conn, entity_id)
            result = {'status': 'accepted', 'operationId': operation_id, 'entityType': adapter.entity_type,
                      'id': entity_id, 'version': record['version'], 'cursor': self.cursor(conn)}
            conn.execute('INSERT INTO sync_receipts VALUES(?,?,?,?,?)',
                (device, operation_id, fingerprint, encoded(result), utc_now()))
            return result
