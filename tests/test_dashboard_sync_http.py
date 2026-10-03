"""Real Handler and real process restarts, running from a disposable source copy."""
import http.client
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from dashboard_sync.core import SyncError
from dashboard_sync.http import authorize

ROOT = Path(__file__).resolve().parents[1]


class SyncHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='dashboard-sync-http-')
        cls.root = Path(cls.temp.name)
        cls.addClassCleanup(cls.temp.cleanup)
        cls.addClassCleanup(cls.stop_server)
        sources = subprocess.check_output(['git', 'ls-files', '*.py'], cwd=ROOT, text=True).splitlines()
        sources += subprocess.check_output(['git', 'ls-files', 'language_learning/*.json', 'jobhunt_backend/*.json', 'mental_health_questionnaires/*.json'], cwd=ROOT, text=True).splitlines()
        sources += [str(path.relative_to(ROOT)) for path in (ROOT / 'dashboard_sync').glob('*.py')]
        sources += ['tests/sync_server_fixture.py']
        for name in sources:
            if name.startswith(('data/', 'public/', 'antigravity-context/')):
                continue
            target = cls.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
        cls.db = cls.root / 'data' / 'test-journal.sqlite'
        cls.process = None
        cls.start_server()

    @classmethod
    def start_server(cls):
        env = {k: v for k, v in os.environ.items() if not k.startswith(('DASHBOARD_', 'CLEANING_', 'RING_'))}
        env['PYTHONUNBUFFERED'] = '1'
        cls.process = subprocess.Popen([sys.executable, 'tests/sync_server_fixture.py', str(cls.db)],
            cwd=cls.root, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace')
        lines = []
        while True:
            line = cls.process.stdout.readline()
            if line.startswith('SYNC_TEST_PORT='):
                cls.port = int(line.split('=')[1])
                break
            lines.append(line)
            if not line:
                raise RuntimeError('Fixture server failed: ' + ''.join(lines)[-4000:])

    @classmethod
    def stop_server(cls):
        if cls.process:
            cls.process.terminate()
            cls.process.wait(timeout=10)
            cls.process.stdout.close()
            cls.process = None

    @classmethod
    def tearDownClass(cls):
        cls.stop_server()
        cls.temp.cleanup()

    def request(self, method, path, payload=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        body = json.dumps(payload) if payload is not None else None
        conn.request(method, path, body, {'Content-Type': 'application/json', **(headers or {})})
        response = conn.getresponse()
        raw = response.read().decode()
        conn.close()
        return response.status, json.loads(raw)

    def test_status_endpoint(self):
        status, body = self.request('GET', '/api/sync/status')
        self.assertEqual(status, 200)
        self.assertEqual(body['protocolVersion'], 1)

    def test_legacy_ui_crud_and_feed(self):
        status, entry = self.request('POST', '/api/journal/entries', {'content': 'HTTP fixture'})
        self.assertEqual(status, 201)
        path = '/api/journal/entries/' + entry['id']
        self.assertEqual(self.request('GET', path)[1]['version'], 1)
        self.assertEqual(self.request('PATCH', path, {'title': 'invalid', 'expectedVersion': None})[0], 400)
        self.assertEqual(self.request('DELETE', path + '?expectedVersion=')[0], 400)
        self.assertEqual(self.request('PATCH', path, {'title': 'second', 'expectedVersion': 1})[1]['version'], 2)
        status, conflict = self.request('PATCH', path, {'title': 'stale', 'expectedVersion': 1})
        self.assertEqual(status, 409)
        self.assertEqual(conflict['error']['code'], 'VERSION_CONFLICT')
        self.assertEqual(self.request('DELETE', path + '?expectedVersion=1')[0], 409)
        self.assertEqual(self.request('DELETE', path + '?expectedVersion=2')[0], 200)
        status, page = self.request('GET', '/api/sync/changes?protocolVersion=1&deviceId=' + uuid.uuid4().hex)
        self.assertEqual(status, 200)
        events = [row for row in page['changes'] if row['id'] == entry['id']]
        self.assertEqual([row['operation'] for row in events], ['create', 'update', 'delete'])
        self.assertTrue(all(row['record']['deletedAt'] for row in events))

    def test_batch_read_and_real_process_restart(self):
        device, entity, operation = [uuid.uuid4().hex for _ in range(3)]
        body = {'protocolVersion': 1, 'deviceId': device, 'operations': [{
            'entityType': 'journalEntry', 'id': entity, 'operationId': operation,
            'operation': 'create', 'expectedVersion': 0, 'payload': {'content': 'Restart fixture'}}]}
        status, accepted = self.request('POST', '/api/sync/batch', body)
        self.assertEqual((status, accepted['results'][0]['status']), (200, 'accepted'))
        self.assertEqual(self.request('GET', f'/api/sync/entities/journalEntry/{entity}?protocolVersion=1')[1]['record']['version'], 1)
        body['operations'] = [{**body['operations'][0], 'operationId': uuid.uuid4().hex, 'operation': 'delete', 'expectedVersion': 1, 'payload': {}}]
        accepted = self.request('POST', '/api/sync/batch', body)[1]
        cursor = self.request('GET', '/api/sync/status')[1]['currentChangeCursor']
        self.stop_server()
        self.start_server()
        self.assertEqual(self.request('GET', '/api/sync/status')[1]['currentChangeCursor'], cursor)
        self.assertEqual(self.request('POST', '/api/sync/batch', body)[1], accepted)
        self.assertTrue(self.request('GET', f'/api/sync/entities/journalEntry/{entity}?protocolVersion=1')[1]['record']['deletedAt'])

    def test_protocol_and_invalid_cursor_errors(self):
        status, body = self.request('POST', '/api/sync/batch', {'protocolVersion': 9})
        self.assertEqual((status, body['error']['code']), (400, 'UNSUPPORTED_PROTOCOL_VERSION'))
        status, body = self.request('GET', '/api/sync/changes?protocolVersion=1&deviceId=' + uuid.uuid4().hex + '&cursor=bad')
        self.assertEqual((status, body['error']['code']), (400, 'INVALID_CURSOR'))

    def test_browser_origin_and_dns_rebinding_rejected(self):
        self.assertEqual(self.request('GET', '/api/sync/status', headers={'Origin': 'https://evil.example'})[0], 403)
        self.assertEqual(self.request('GET', '/api/sync/status', headers={'Host': 'evil.example'})[0], 403)
        self.assertEqual(self.request('GET', '/cleaning-dashboard/api/sync/status', headers={'Host': 'evil.example'})[0], 403)
        self.assertEqual(self.request('GET', '/cleaning-dashboard/api/journal/entries', headers={'Host': 'evil.example'})[0], 403)

    def test_private_database_and_backups_not_static(self):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        for path in ['/data/test-journal.sqlite', '/data/backups/dashboard-sync-api/manifest.json']:
            conn.request('GET', path)
            response = conn.getresponse()
            self.assertEqual(response.status, 404)
            response.read()
        conn.close()


class SyncAuthTests(unittest.TestCase):
    def handler(self, address='192.168.1.10', **headers):
        return SimpleNamespace(client_address=(address, 1), headers={'Host': '192.168.1.1:8000', **headers})

    def test_lan_disabled_by_default(self):
        with mock.patch.dict(os.environ, {}, clear=True), self.assertRaises(SyncError):
            authorize(self.handler(), set())

    def test_lan_requires_token_and_explicit_enable(self):
        with mock.patch.dict(os.environ, {'DASHBOARD_SYNC_LAN': '1', 'DASHBOARD_SYNC_TOKEN': 'fixture-token'}, clear=True):
            with self.assertRaises(SyncError):
                authorize(self.handler(), set())
            authorize(self.handler(Authorization='Bearer fixture-token'), set())
            with self.assertRaises(SyncError):
                authorize(self.handler('8.8.8.8', Authorization='Bearer fixture-token'), set())


if __name__ == '__main__':
    unittest.main()
