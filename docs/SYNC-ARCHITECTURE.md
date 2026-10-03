# Dashboard Sync architecture

## Audit and scope

See [DATA-INVENTORY](DATA-INVENTORY.md) and [API-INVENTORY](API-INVENTORY.md). The application is a Vite multi-page frontend and a Python `ThreadingHTTPServer`, with feature-local SQLite/JSON stores, browser-only state, and independent workout/network services. Habits already demonstrates revision/cursor/receipt tables; its existing protocol is preserved. A new framework or central content database would add risk.

The sole pilot entity is **journalEntry**, including the existing journal/poem variants of that same table. Published content has one owner, `JournalStore` / `data/journal.sqlite`. Todo was considered but rejected for this first pilot: its whole-list settings writes and localStorage fallback require a more involved compatibility migration. Journal has an established CRUD UI, offline-capable UUID identities and one concrete relational model.

```
PC journal UI                  Future phone / tablet
  | existing journal API         | durable local DB + outbox
  | expectedVersion              | protocolVersion 1 / push / pull
  +------------------------------+
                 |
       server.py: auth + thin routes
                 |
       dashboard_sync: shared protocol
                 |
       JournalAdapter / JournalStore
                 |
       data/journal.sqlite (one transaction)
       + journal_entries: canonical content + sync_version
       + sync_changes: monotonic references
       + sync_tombstones: durable deleted identities
       + sync_receipts: accepted-operation metadata
       + sync_devices: counters and last contact
       + sync_schema: version and cursor namespace
```

## Authority and compatibility

| Storage | Role | Rule |
| --- | --- | --- |
| `journal_entries` in `data/journal.sqlite` | CANONICAL | Existing IDs, content, provenance and timestamps remain in place. |
| `sync_*` tables in that same database | CANONICAL synchronization metadata | Must be backed up/restored with content. |
| Journal browser drafts | CLIENT-ONLY unsaved user data | Never upload automatically, erase on conflict, or treat as published content. Drafts retain their baseVersion. Older drafts use migration baseline version 1. |
| Loaded journal list in browser memory | CACHE | Refetched through existing API. |
| Voice / HTR source stores | CANONICAL for their own domains | Publication is a deliberate copy into the written journal with provenance; neither source is migrated. |
| Legacy published-entry fallback | None | No seed/JSON/localStorage fallback competes with SQLite. |
| SQLite backups | Recovery snapshots | Never selected by the application as a writable fallback. |

The existing URLs and record fields remain. Records gain `version` and `deletedAt`; the PC editor sends expectedVersion and preserves local content on conflict. Old direct API clients without a precondition retain legacy behavior; they are not safe multi-device sync clients. Trusted import and explicit re-publication workflows remain authoritative domain writes. Their SQL is tracked too. A deleted ID cannot be reinserted, but deliberate re-publication can produce a **new** UUID: it is not a resurrection of the old identity.

## Shared conventions and transactions

- Canonical IDs are lowercase UUID hex (32 characters), matching journal's existing IDs and routes. Sync accepts standard dashed lowercase UUID input and normalizes it to hex. Clients generate UUIDs offline. Existing IDs are not rewritten.
- Server timestamps are UTC ISO-8601 with `Z`. Existing createdAt/updatedAt are preserved during migration. Domain entryDate can intentionally be a date without a time; it is not a sync clock.
- Create uses expectedVersion 0 and starts at version 1. Updates and deletes require the exact positive current integer version; every mutation advances it once. Client clocks never decide conflicts.
- SQLite `BEGIN IMMEDIATE` serializes competing writers. SQL triggers on the domain table capture create/update/delete, including import, voice and HTR publication and older running processes. Entity update, version increment, journal event and accepted receipt commit together. An exception rolls back all four.
- `sync_changes.change_id INTEGER PRIMARY KEY AUTOINCREMENT` is an indexed monotonically increasing sequence. The journal stores small references, not duplicated entry text/images. Existing records receive baseline create events in deterministic ID order.
- Cursors are opaque persisted `databaseEpoch:sequence` strings. `0` bootstraps a replica. Wrong namespace, malformed, negative or ahead-of-database cursors fail explicitly. This is one transactional store/feed today, **not** a fabricated global sequence across unrelated databases.
- Pull returns ordered event references plus the **latest canonical record at the pull transaction snapshot**. `entityVersion` identifies the event; `record.version` can be newer. Clients apply only greater record versions and honor deletedAt even if the reference event says create. This is a state replication feed, not an immutable historical-content export.
- Pages are bounded by 100 references and approximately 8 MiB of records (one large valid record is still returned). The cursor advances only through returned events. No journal compaction currently occurs.
- Deletes remove domain content and retain an indefinite tombstone (identity, createdAt, deletion time and incremented version). An offline update, create with the same ID, or repeated deletion under a new operation ID cannot undo it.
- Batch operations commit separately, sequentially, with an ordered result per input index. Validation/conflict failure of one item does not undo accepted siblings. This is intentional partial success.
- `(deviceId,operationId)` is a durable receipt key. Accepted retries return the original metadata result without reapplying content, even after later changes or restart. Reusing the ID with different JSON content fails. Fingerprints are SHA-256 of canonical JSON, receipts contain no content text. Rejected operations are not receipted; a corrected/resolved change should use a new operationId.

## Devices, diagnostics and offline workflow

A client creates one stable UUID deviceId per installation and persists it. Optional displayName/clientType (up to 100 characters) are labels, never credentials. Device counters record operations submitted, changes returned, conflicts, failures and lastSeen. Status exposes these metadata only, not tokens or entry payloads. Accepted retries count as requests in diagnostics but not as new changes. Counter updates are best effort relative to a crash after the mutation commit; receipts and domain correctness are transactional. No payload run logs or background worker are introduced.

1. Offline client edits its local record and atomically appends an outbox operation with UUID operationId and the version it actually read. Multiple queued edits to one record must account for preceding accepted versions or be coalesced before sending.
2. On reconnect, push at most 100 operations. A dropped response is retried with the exact same deviceId, operationId and body.
3. Accepted items leave the outbox. Conflict items retain local content and the returned serverRecord for explicit user resolution. Rejected items remain visible for correction; do not silently discard.
4. Pull from the last persisted cursor until hasMore is false. Apply the page and its nextCursor in one local transaction. Never use the batch receipt cursor to skip pulling other clients' changes.
5. Persist tombstones and compare record versions. Do not infer deletion from absence in a paginated result.
6. For a manual conflict resolution, use the displayed current server version and a **new** operationId. There is no automatic merge, force-write or undelete endpoint.

This task supplies and tests the server contract; it does not implement an Android application, a browser offline outbox, CRDTs, accounts, OAuth, cloud hosting, SSE or push delivery.

## Security and operations

The existing bind remains `DASHBOARD_HOST` (default `127.0.0.1`), central port 8000. No service is published publicly. The new Sync routes and journal API require either a loopback peer **and** loopback Host, or explicit LAN enablement plus a bearer token. Browser Origins must match `DASHBOARD_ALLOWED_ORIGINS` (existing default local origins); no wildcard CORS. The prefixed `/cleaning-dashboard/api/...` read alias is checked too.

To pair a future native LAN client, generate a private random token outside the repository (e.g. Python `secrets.token_urlsafe(32)`), provide `DASHBOARD_SYNC_TOKEN` to the server environment and store it in the client's secure storage. Set `DASHBOARD_SYNC_LAN=1` and choose a LAN bind with `DASHBOARD_HOST`; never embed the token in JS or commit it. Non-private remote addresses are refused. HTTP on trusted local Wi-Fi is supported; public internet/TLS termination is outside this task. Device IDs do not authorize requests. Revoke pairing by rotating the token. Existing domain auth is otherwise unchanged.

SQLite files/sidecars and `data/backups/` are already denied by central static serving and Vite's privacy plugin. Tests verify those boundaries. Backups use the SQLite online backup API, include a manifest with time, schema, source, target, size and hashes, and pass integrity_check. See [SYNC-MIGRATION](SYNC-MIGRATION.md) for restore and rollback.

## ADDING A NEW SYNCABLE MODULE

1. Identify canonical data and every writer; mark cache, derived, client-only and legacy copies explicitly. Stop if authority is unknown.
2. Define a domain schema, keeping content in typed domain tables rather than an all-purpose JSON entity table.
3. Retain stable legacy IDs; define offline UUID generation and serialization for new IDs.
4. Preserve createdAt and define server-owned updatedAt in UTC; keep domain dates separate.
5. Add a positive version and expectedVersion checks.
6. Reuse domain validation and bound payloads, types and batches.
7. Keep persistence feature-local. **Do not write another database from a sync transaction.** If adding another store, design an explicit feed scope/cursor namespace or a reviewed atomic storage arrangement first; current v1 advertises only journalEntry.
8. Integrate every write with one SQLite transaction, including legacy/import/background paths.
9. Add indexed monotonic change references without copying large content into the journal.
10. Retain tombstones and forbid reusing deleted identities.
11. Implement the adapter's get/apply contract; serialize current record versions separately from event versions.
12. Version the additive migration and prove a second run leaves versions/cursors/content unchanged.
13. Back up with a verified manifest before schema changes; rehearse restore on a disposable copy.
14. Test the API, limits, errors, auth/static privacy, atomic rollback, retries and restart.
15. Run the two-client stale-write/lost-response/deletion/pagination scenarios.
16. Update the existing frontend adapter with preconditions and draft protection; prove current UI compatibility and update the inventories/protocol/entityTypes documentation.
