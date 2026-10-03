# Journal pilot migration and recovery

## Before and after

Before: published journal/poem records are canonical in `data/journal.sqlite`, table `journal_entries`. IDs are UUID hex; content/provenance and UTC timestamps already exist. Browser storage owns unsaved drafts and view preferences, not published entries. There is no content relocation or seed import in this migration.

After: same file/table, same IDs and original fields. One `sync_version` column starts at 1. Schema version 1 creates `sync_schema`, `sync_changes`, `sync_tombstones`, `sync_receipts`, `sync_devices` and journal triggers. Existing rows produce baseline create references in ID order. No deleted historical identities can be inferred before tracking began; only future deletes are tombstoned.

`JournalStore.initialize` backs up an existing pre-Sync database before schema changes and runs only a missing Sync migration. Migration uses the existing SQLite store, a single transaction, version marker and before/after hash over **every original field of every row ordered by ID**. Original timestamp values and provenance are included. A second initialization must not reset versions or add change references. Existing store initialization's historical title normalization remains unchanged.

## Backup

```powershell
python scripts/backup-sync-data.py
python scripts/migrate-sync-pilot.py
```

The first command is independently usable after migration too. `--database` and `--destination` support disposable fixtures/custom locations. The migration verification command compares original fields/counts, integrity, version distribution, tombstones and cursor stability across a second initialization; its private report is `data/backups/dashboard-sync-api/migration-verification.json`.

Backups live under `data/backups/dashboard-sync-api/<UTC timestamp>/journal.sqlite` with adjacent `manifest.json`. Manifest fields: timestamp, schemaVersion, source, backupPath, size, SHA-256 of the backup file, journal count/content hash and integrityCheck. SQLite's online backup API includes committed WAL data consistently; copying only the main DB file is unsafe. A writer pause is unnecessary for backup consistency. For an exact before/after migration comparison, run without editing the journal concurrently; if it changes, inspect the report rather than claiming byte equality.

The initial verified task backup was created at `20261002T211848.470928Z`: 63,705,088 bytes, 443 records, schemaVersion 0; SQLite integrity_check returned `ok`. Full paths/checksums and subsequent migration verification remain in ignored manifests. Private database content is not committed, printed or placed in source documentation. The additive migration also creates its own fresh automatic pre-migration backup.

Executed migration verification: 443 before / 443 after, identical original-field SHA-256 `845fbecf0a43be568e364c69d421e677f04ee607cc78931ade94ad24787aa2a7`, all 443 at version 1, zero duplicate IDs, zero lost records and zero newly deleted records. Sync schema is 1; the second migration run left the cursor at sequence 443. The automatic pre-migration backup is in `20261002T213859.167842Z`. The supervised central API was restarted and its live journal read returned all 443 records with version metadata.

## Restore rehearsal / actual recovery

Tests restore into a new temporary database, verify original-field hashes, initialize it twice and check versions/cursors/receipts. The real process restart HTTP test preserves tombstones and accepted receipts. No destructive test targets live user data.

For actual restore:

1. Stop **all** processes that can write this journal: central API and its automatic supervisor, importers and any tools holding the DB. Do not stop the independent workout runtime just to restore the journal. Close/reload journal browser tabs to preserve their local drafts and prevent writes during maintenance.
2. Back up the current database using the command above, even if damaged logically. Keep both current and chosen restore snapshots. Verify the selected manifest SHA-256 and SQLite integrity_check on a disposable copy first.
3. Preserve the current DB plus any `-wal` / `-shm` sidecars in a separate recovery directory while every writer is stopped. Do not mix old sidecars with a restored main file. Use native file operations on checked absolute paths; never delete the only copy.
4. Restore the selected backup to a **new** database with `sqlite3.Connection.backup`, check its integrity and original-field counts/hash, then place that verified file at the canonical path with the old file already preserved. A pre-Sync backup will migrate on the next initialization; a schema-1 backup already includes versions, journal, receipts and tombstones.
5. A restore can rewind history. Before exposing a restored schema-1 database, replace `sync_schema.epoch` with a fresh UUID in a transaction. All replicas must clear/rebuild their **server mirror and cursor** from `0`; separately preserve and review pending outboxes/drafts. Old operations created after the selected backup may no longer have receipts: do not replay them automatically. A pre-Sync backup naturally receives a new epoch on migration.
6. Restart the central API, check `/api/sync/status` and current journal UI, and reconcile client drafts/outboxes explicitly. Never point both original and disposable test servers at the live journal.

## Code rollback

The migration is additive, so old journal code can read the domain table while triggers keep recording writes. Old code has no optimistic concurrency; disable common Sync/LAN clients during rollback. Do not drop metadata or downgrade the DB as a side effect of a Git checkout. Returning to a truly pre-Sync database requires the explicit data restore procedure and loses later writes unless separately reconciled. Git `build-*` tags protect source only.

## Scope limits

Only journalEntry is enabled. No Todo, voice, HTR, reading, finance, habit, workout or other domain schema/data is migrated. Todo backlog completion is a separate narrowly targeted settings update after acceptance, never a replacement seed or a migration of Todo storage. No Android app, external sync service or public exposure is installed.
