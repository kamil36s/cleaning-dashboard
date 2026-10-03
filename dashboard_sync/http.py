"""Thin integration with the existing HTTP server; no second server or framework."""
import hmac
import ipaddress
import json
import os
import re
from urllib.parse import parse_qs, urlsplit

from .core import SyncError, require_version
from .service import SyncService

MAX_BODY = 8 * 1024 * 1024


def authorize(handler, allowed_origins):
    origin = str(handler.headers.get('Origin') or '')
    if origin and origin not in allowed_origins:
        raise SyncError('FORBIDDEN', 'Origin is not allowed', 403)
    try:
        address = ipaddress.ip_address(handler.client_address[0])
        host = urlsplit('http://' + str(handler.headers.get('Host') or '')).hostname
    except ValueError:
        raise SyncError('FORBIDDEN', 'Invalid client or Host', 403)
    if address.is_loopback and host in {'127.0.0.1', 'localhost', '::1'}:
        handler._cors_origin = origin or None
        return
    token = os.environ.get('DASHBOARD_SYNC_TOKEN', '').strip()
    supplied = handler.headers.get('Authorization', '')
    if os.environ.get('DASHBOARD_SYNC_LAN') != '1' or not address.is_private:
        raise SyncError('FORBIDDEN', 'Sync LAN access is disabled', 403)
    if not token or not hmac.compare_digest(supplied.encode('utf-8'), ('Bearer ' + token).encode('utf-8')):
        raise SyncError('UNAUTHORIZED', 'A valid sync pairing token is required', 401)
    handler._cors_origin = origin or None


def query_int(query, key, default=None):
    value = query.get(key, [default])
    if len(value) != 1 or value[0] is None or not re.fullmatch(r'[0-9]{1,9}', str(value[0])):
        raise SyncError('VALIDATION_ERROR', f'Invalid {key}')
    return int(value[0])


def dispatch(handler, store):
    parsed = urlsplit(handler.path)
    if not (parsed.path == '/api/sync' or parsed.path.startswith('/api/sync/')):
        return False
    try:
        service = SyncService(store)
        query = parse_qs(parsed.query, keep_blank_values=True)
        if any(len(values) != 1 for values in query.values()):
            raise SyncError('VALIDATION_ERROR', 'Duplicate query parameters')
        if handler.command == 'GET' and parsed.path == '/api/sync/status':
            result = service.status()
        elif handler.command == 'GET' and parsed.path == '/api/sync/changes':
            result = service.changes(protocol_version=query_int(query, 'protocolVersion'),
                device_id=query.get('deviceId', [None])[0], cursor=query.get('cursor', ['0'])[0],
                limit=query_int(query, 'limit', '100'))
        elif handler.command == 'GET' and (match := re.fullmatch(r'/api/sync/entities/([^/]+)/([^/]+)', parsed.path)):
            require_version(query_int(query, 'protocolVersion'))
            result = service.read(*match.groups())
        elif handler.command == 'POST' and parsed.path == '/api/sync/batch':
            try:
                length = int(handler.headers.get('Content-Length', ''))
            except ValueError:
                raise SyncError('VALIDATION_ERROR', 'Content-Length is required')
            if not 0 < length <= MAX_BODY:
                raise SyncError('VALIDATION_ERROR', 'Invalid body size', 413)
            raw = handler.rfile.read(length)
            if len(raw) != length:
                raise SyncError('VALIDATION_ERROR', 'Incomplete body')
            try:
                request = json.loads(raw.decode('utf-8'), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
            except (ValueError, UnicodeError):
                raise SyncError('VALIDATION_ERROR', 'Invalid finite JSON')
            result = service.batch(request)
        else:
            raise SyncError('NOT_FOUND', 'Unknown Sync endpoint or method', 404)
        handler.send_json(result)
    except SyncError as exc:
        handler.send_json(exc.payload(), status=exc.status)
    except Exception:
        handler.send_json(SyncError('INTERNAL_ERROR', 'Sync request failed', 500).payload(), status=500)
    return True
