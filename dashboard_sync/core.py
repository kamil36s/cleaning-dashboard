"""Small shared protocol primitives, independent of the pilot's content schema."""
import json
import re
import uuid
from datetime import datetime, timezone

PROTOCOL_VERSION = 1
MAX_BATCH = 100
MAX_PAGE = 100


class SyncError(ValueError):
    def __init__(self, code, message, status=400, **details):
        super().__init__(message)
        self.code, self.status, self.details = code, status, details

    def payload(self):
        return {'error': {'code': self.code, 'message': str(self), 'details': self.details}}


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def require_version(value):
    if type(value) is not int or value != PROTOCOL_VERSION:
        raise SyncError('UNSUPPORTED_PROTOCOL_VERSION', 'protocolVersion must be 1')


def uuid_id(value, field):
    if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{32}|[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}', value):
        raise SyncError('VALIDATION_ERROR', f'{field} must be a lowercase UUID')
    return uuid.UUID(value).hex


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
