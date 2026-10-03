# Dashboard Sync wire protocol v1

Base: existing central API, normally `http://127.0.0.1:8000`. Content-Type: `application/json`. All responses are no-store. Native LAN callers require `Authorization: Bearer <private pairing token>` with LAN explicitly enabled; see [architecture](SYNC-ARCHITECTURE.md).

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/sync/status` | Server time, versions, cursor, limits, entity types and device counters |
| GET | `/api/sync/entities/{entityType}/{id}?protocolVersion=1` | Current canonical record or tombstone |
| GET | `/api/sync/changes?protocolVersion=1&deviceId=...&cursor=0&limit=100` | Incremental state replication |
| POST | `/api/sync/batch` | Ordered partial-success mutation batch |

Only `entityType: "journalEntry"` is enabled. New IDs/device IDs/operation IDs are lowercase UUIDs; canonical responses use hex without dashes. GET protocolVersion must be decimal `1`; POST protocolVersion must be integer `1` (not a string or boolean). Status has no required version input and advertises the supported version. Unknown endpoints/methods return NOT_FOUND.

## Status and reads

```json
{"protocolVersion":1,"schemaVersion":1,"serverTime":"2026-10-02T21:00:00.000Z","currentChangeCursor":"0123456789abcdef0123456789abcdef:443","backendStatus":"ok","entityTypes":["journalEntry"],"maxBatchSize":100,"maxPageSize":100,"devices":[]}
```

Device rows use database field names: device_id, display_name, client_type, last_seen, push_count, pull_count, conflict_count, failure_count. Counts are diagnostic requests/results, not exactly-once business totals. A read returns `{protocolVersion:1,entityType:"journalEntry",record:{...}}`; missing IDs yield HTTP 404. Tombstones are successful reads, not 404.

Live records retain existing journal fields: id, title, content, contentFormat, entryDate, entryKind, tags, location, illustration, illustrationAlt, sourceType, sourceExternalId, sourceVoiceJournalEntryId, sourceMetadata, publishedAt, createdAt, updatedAt, plus version and deletedAt (null).

Tombstones contain only id, version, createdAt, updatedAt and deletedAt. The last two timestamps equal deletion time.

## Push

```json
{
  "protocolVersion": 1,
  "deviceId": "11111111111141118111111111111111",
  "displayName": "Private phone",
  "clientType": "android",
  "operations": [{
    "operationId": "22222222222242228222222222222222",
    "entityType": "journalEntry",
    "id": "33333333333343338333333333333333",
    "operation": "create",
    "expectedVersion": 0,
    "payload": {"content":"Example entry","entryDate":"2026-10-02","title":"Example"}
  }]
}
```

Maximum: 100 operations, 8 MiB HTTP request. Envelope validation rejects the entire request before mutation. Otherwise each operation has an independent transaction and result at its input index. HTTP 200 means the batch was processed; **inspect every result**.

```json
{"protocolVersion":1,"results":[{"index":0,"status":"accepted","operationId":"22222222222242228222222222222222","entityType":"journalEntry","id":"33333333333343338333333333333333","version":1,"cursor":"0123456789abcdef0123456789abcdef:444"}]}
```

Accepted receipts contain metadata, not duplicate entry content. Fetch/pull the canonical record to see normalized fields. Retrying the identical operation returns the exact receipt, even if its version is now old. Never advance the local pull cursor from an accepted receipt.

- create: expectedVersion 0, unused ID. Existing record/tombstone -> conflict.
- update: exact positive expectedVersion, payload is a nonempty patch. No upsert.
- delete: exact positive expectedVersion, payload omitted or `{}`. No undelete.
- Payload fields: title, content, contentFormat (`text`/`html`), entryDate (valid ISO date/date-time), entryKind (`journal`/`poem`), tags (up to 20 strings), location, illustration (valid supported base64 image data URL), illustrationAlt. All fields other than tags are strings. At least content or illustration must remain nonempty. Server owns IDs/timestamps/provenance/version; these are not writable payload fields.
- Domain limits are reused: title/location 160 characters, content 1,000,000 characters, illustrationAlt 240, tags 40 characters each, image decoded size 2 MiB. UTC conversion follows JournalStore; timezone-free domain input is interpreted as UTC. Prefer explicit offsets or date-only entryDate.
- operationId is scoped to deviceId and must not be reused for different JSON content. Keep the exact retry body. Rejected/conflicting operations have no durable success receipt.

## Conflict and error contract

```json
{"index":1,"status":"conflict","error":{"code":"VERSION_CONFLICT","message":"Record changed; resolve explicitly","details":{"entityType":"journalEntry","id":"33333333333343338333333333333333","clientVersion":1,"serverVersion":2,"serverRecord":{"id":"33333333333343338333333333333333","version":2,"createdAt":"2026-10-02T21:00:00.000Z","updatedAt":"2026-10-02T21:02:00.000Z","deletedAt":"2026-10-02T21:02:00.000Z"}}}}
```

`status:"rejected"` uses the same error shape. Batch conflicts are the explicit equivalent of HTTP 409 per operation. Existing journal PATCH/DELETE precondition conflicts return actual HTTP 409 with `{error:{code,message,details}}`.

| Code | HTTP outside batch | Meaning |
| --- | --- | --- |
| VALIDATION_ERROR | 400 (413 oversized body) | Bad ID, expectedVersion, operation, type, field, body, query, limit or reused operationId |
| VERSION_CONFLICT | 409 | Stale version, existing create ID, or retained tombstone |
| UNKNOWN_ENTITY | 400 | Adapter not enabled |
| NOT_FOUND | 404 | Missing record or route |
| INVALID_CURSOR | 400 | Malformed, foreign epoch or ahead of database |
| UNSUPPORTED_PROTOCOL_VERSION | 400 | Unsupported protocol |
| FORBIDDEN | 403 | Origin/Host/LAN boundary |
| UNAUTHORIZED | 401 | Missing/wrong LAN bearer token |
| INTERNAL_ERROR | 500 | Generic failure without SQL/private payload disclosure |

## Pull and pagination

Initial request uses cursor `0`; later requests use the exact previous nextCursor. deviceId is required. limit defaults to 100 and accepts 1..100. Duplicate query parameters are rejected.

```json
{"protocolVersion":1,"changes":[{"changeId":444,"entityType":"journalEntry","id":"33333333333343338333333333333333","operation":"create","entityVersion":1,"changedAt":"2026-10-02T21:00:00.000Z","record":{"id":"33333333333343338333333333333333","version":2,"createdAt":"2026-10-02T21:00:00.000Z","updatedAt":"2026-10-02T21:02:00.000Z","deletedAt":"2026-10-02T21:02:00.000Z"}}],"nextCursor":"0123456789abcdef0123456789abcdef:444","hasMore":true}
```

This example deliberately pairs an earlier create reference with the latest tombstone. **Apply record.version/deletedAt, not the event operation, to local state.** Skip lower/equal record versions. References are ordered by changeId; records can therefore repeat across pages. The server takes one SQLite snapshot per page. At approximately 8 MiB a page can stop before limit. Persist page changes and nextCursor together; retrying a page is safe. An empty page preserves its input sequence. A newer write after hasMore=false is returned on the next poll.

Journal references, receipts and tombstones are currently retained indefinitely. A backup restore requires a new replica namespace/re-bootstrap procedure; see migration docs. No automatic cursor expiry or full snapshot shortcut exists.

## Existing PC compatibility

`GET /api/journal/entries` and item reads still work. POST creates a domain entry. PATCH accepts the old fields plus optional expectedVersion, extracted before domain validation. DELETE accepts optional `?expectedVersion=N`. Current UI sends the observed version for edits/deletes and persists it in drafts. Direct old clients without preconditions retain their previous semantics; only clients using the common protocol receive its full retry/conflict guarantees.
