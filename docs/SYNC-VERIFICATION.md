# Sync acceptance verification

## Result

Implemented the shared protocol and exactly one existing entity, journalEntry. Live migration preserved all 443 records and every original field (IDs, timestamps, content and provenance). NO USER DATA LOST in the verified pilot comparison. All destructive create/update/conflict/delete/restore acceptance scenarios used disposable databases. The central API's existing supervisor restarted its verified child; the independent workout runtime was not restarted.

## Validation

Final focused suite: **108 / 108 PASS**, no remaining failed tests.

```powershell
python -m unittest tests.test_dashboard_sync tests.test_dashboard_sync_http tests.test_journal_store tests.test_journal_context tests.test_voice_journal_store tests.test_journal_htr
npm run test:run -- tests/journal.test.js tests/journal-api.test.js tests/widget-journal.test.js tests/journal-rich-text.test.js tests/todo-store.test.js tests/file-settings.test.js tests/vite-finance-privacy.test.js tests/voice-journal-api.test.js tests/journal-htr-api.test.js
```

Python: 62 tests. JavaScript: 46 tests across 9 files. This is a focused regression/acceptance run, not a claim that the entire dashboard suite was executed. No separate visual redesign/build was needed.

Covered: status; create/read/update/delete; version increments; stale conflicts including server record; no resurrection; cursor ordering/increment/pagination; batch limits/partial success; exact idempotent retries and ID reuse rejection; invalid entity/version/ID/cursor/protocol; concurrent writers; rollback if receipt insertion fails; two clients; process restart with durable tombstones/receipts; migration once/twice; pre/post-Sync backup restore; legacy CRUD; imports/voice/HTR publications; draft baseVersion retention after conflict; scoped non-pilot regressions; static privacy; Origin, Host, prefixed-route and LAN token boundaries.

HTTP Sync tests copy Python source and required static manifests into a temporary tree, then launch the actual dashboard Handler in a subprocess. They never run their test server against the live journal. The real process restart test terminates/restarts that fixture and retries an accepted deletion. Existing voice/HTR suites likewise use fixture stores for their writes.

Initial testing exposed SQLite connections retained after exceptions on Windows; explicit connection closure fixed it. A fixture's empty title invoked pre-existing title normalization; the migration fixture now uses a stable pre-existing title. The disposable HTTP source copy was extended with required benchmark manifests. All resulting suites passed after these corrections.

## Live verification and private artifacts

- Initial backup: `data/backups/dashboard-sync-api/20261002T211848.470928Z/journal.sqlite`, 63,705,088 bytes; verified SHA-256 and integrity_check.
- Automatic migration backup: `data/backups/dashboard-sync-api/20261002T213859.167842Z/journal.sqlite` with manifest.
- Before/after report: `data/backups/dashboard-sync-api/migration-verification.json`: 443 -> 443, all original fields equal, schema 1, no duplicates/loss, repeat unchanged.
- Live GET `/api/sync/status`: protocolVersion 1, schemaVersion 1, backendStatus ok, only journalEntry, cursor sequence 443 preserved across the actual central API restart.
- Live GET `/api/journal/entries`: 443 records, all version 1, all active.
- Runtime already listened on `0.0.0.0:8000` before this task; bind was not changed. Sync and journal use the stricter scoped Origin/Host/token policy. Vite preserves the incoming Host (`changeOrigin:false`), so its proxy does not silently turn a LAN Host into a trusted loopback Host.
- Restart refreshed two tracked festival-monitor check timestamps. After verifying no other monitor fields changed, that observation was preserved privately in `data/backups/dashboard-sync-api/restart-monitor-observation.json` and the incidental tracked timestamp edits were restored. No unrelated runtime snapshot is included in the task commits.

## Backlog

Updated only project `dashboard-sync-api` through existing `/api/settings/todo`, after acceptance. Its 12 foundation subtasks are complete; the mobile/offline subtasks explicitly describe the implemented server contract and two-client simulation, not an Android application. The project description records that boundary. A read-after-write comparison verified the other **78 items unchanged** and total count **79 -> 79**.

The exact pre-update settings copy and verification report are ignored private files in `data/backups/dashboard-sync-api/20261002T214529.277679Z/`. Seeds were not edited.

## Review and limitations

Branch: `ai/astra/dashboard-sync-api`; checkpoint `build-0002` contains implementation and tests. Final review is performed with `scripts/finish-ai-task.ps1` without `-Merge`; no push or promotion to dev/main is authorized here.

Only one SQLite feed/adapter is enabled. No mobile app, browser outbox, multi-store global cursor, automatic conflict merge, tombstone/receipt compaction, historical full-content event archive, public sync, accounts or OAuth. Legacy writes without expectedVersion retain old behavior; current PC editor and common protocol use preconditions. A backup restore requires re-bootstrap with a new epoch and explicit pending-outbox reconciliation. Inventory route patterns and source-linked contracts are an audit, not exhaustive runtime tests of every existing endpoint.

Next candidates, not implemented: Todo/Projects after replacing whole-list fallback writes safely; Reading progress after auditing companion writers; Feelings check-ins after auditing the existing native queue and imports.

## Integration review ? 2026-10-03

Reviewed both implementation checkpoints (`48b3af5` / build-0002 and `99a1f11` / build-0003) against the user's integration Definition of Done. Starting branch: `ai/astra/dashboard-sync-api`, clean, two commits ahead of dev (`67931c3`). Dev is an ancestor, so integration has no divergent changes. The user's follow-up explicitly authorizes merge into dev after acceptance; the earlier no-merge restriction above describes the original implementation task only. Main and remote push remain out of scope.

No application code change was needed. Review corrections clarify that the generated API inventory's extracted snippets are heuristic navigation evidence, correct the domain count to 44 including Sync, describe structured journal conflicts, and remove an extra trailing blank line. The generator preserves these documentation corrections.

### Acceptance matrix

| Definition of Done | Result | Evidence |
| --- | --- | --- |
| DATA-INVENTORY | PASS | Canonical ownership, storage mechanisms, pilot decision and deferred domains documented. |
| API-INVENTORY | PASS | Source route index and domain owners; heuristic limitations explicit; exact Sync contract separately reviewed. |
| SYNC-ARCHITECTURE | PASS | Single JournalStore owner, transactional adapter, security and extension rules match implementation. |
| SYNC-PROTOCOL | PASS | Four endpoints, protocol 1, validation, partial batches and latest-record feed semantics match code/tests. |
| SYNC-MIGRATION | PASS | Additive schema, independent backup, restore/epoch reset and client reconciliation documented. |
| Runtime backup | PASS | Both original pre-migration backups independently rehashed and checked with SQLite integrity_check. |
| Stable IDs | PASS | Existing UUID hex IDs retained; offline UUID inputs normalized. |
| Versioning | PASS | Create 1; SQL-triggered update/delete increments. |
| Conflict detection | PASS | Transactional expectedVersion checks; HTTP 409 and per-operation batch conflicts. |
| Tombstones | PASS | Durable identity, version and deletion timestamp. |
| No resurrection | PASS | Stale updates/create rejected; SQL INSERT guard tested. |
| Change journal | PASS | Transactional references for legacy CRUD, import, voice and HTR publication. |
| Cursor | PASS | Epoch-scoped sequence, ordered incremental pages, invalid/ahead/foreign cursors rejected. |
| Batch push | PASS | Bounded, ordered partial success; invalid sibling does not undo accepted mutation. |
| Idempotency | PASS | Durable receipt and request fingerprint; exact retry including after later writes/restart. |
| Diagnostics | PASS | Device ID, last contact and counters; no content in diagnostics. |
| Pilot | PASS | Only journalEntry enabled; canonical data/journal.sqlite retained. |
| Migration idempotency | PASS | First/second initialization and backups tested on disposable databases. |
| Restart persistence | PASS | Real Handler subprocess restarted; cursor/tombstone/receipt preserved. |
| Two clients | PASS | A creates/B pulls; stale B conflicts; deletion cannot resurrect; lost-response retry adds no duplicate. |
| Existing pilot UI | PASS | 46 frontend/regression tests plus actual Chromium acceptance flow below. |
| No user data loss | PASS | Live 443 records and original-field hash equal both pre-migration backup evidence and migration report. |

### Re-executed validation

The two commands in the Validation section passed again: **62/62 Python and 46/46 JavaScript (108/108)**. This includes the complete Sync unit/HTTP suites and existing journal, context, voice publication, HTR, Todo/settings and static privacy regressions.

An additional actual Chromium acceptance flow used a disposable copy of the real Handler, journal.html, styles and JS, a temporary journal database, and a fresh browser context. Checked page load, creation, editing/version increment, a concurrent remote edit returning 409, draft retention, draft recovery after page reload, deletion and the resulting tombstone. All passed, with no page errors. The fixture's ephemeral origin was explicitly allowed only in its temporary server configuration. Initial harness attempts needed the installed Chromium executable and the correct fixture Origin/selector; these were test-environment issues, not application changes. No browser writes targeted the user's journal. This was automated interaction in a real browser, not a human visual/layout sign-off.

Reverified backup paths:

- `data/backups/dashboard-sync-api/20261002T211848.470928Z/journal.sqlite` ? 2026-10-02 21:18:48.470928 UTC.
- `data/backups/dashboard-sync-api/20261002T213859.167842Z/journal.sqlite` ? 2026-10-02 21:38:59.167842 UTC.

Each contains all 443 original records, schema 0; SHA-256 matches its manifest and integrity_check returns ok. Current live original-field SHA-256 is still `845fbecf0a43be568e364c69d421e677f04ee607cc78931ade94ad24787aa2a7`, equal to migration evidence. Restore steps are in SYNC-MIGRATION.md: stop journal writers, preserve current DB/sidecars, restore a verified copy using SQLite backup, migrate if needed, use a new epoch and reconcile replica outboxes. No runtime migration or restore was repeated against the live database during this review.

### Files in the reviewed task

Created: `dashboard_sync/{__init__,backup,core,http,journal,migration,service}.py`; `docs/{API-INVENTORY,DATA-INVENTORY,SYNC-ARCHITECTURE,SYNC-MIGRATION,SYNC-PROTOCOL,SYNC-VERIFICATION}.md`; `scripts/{backup-sync-data,build-sync-inventory,migrate-sync-pilot}.py`; `tests/{sync_server_fixture,test_dashboard_sync,test_dashboard_sync_http}.py`.

Modified: `CHANGELOG-AUTO.md`, `PROJECT_MAP.md`, `journal_store.py`, `js/journal-api.js`, `js/journal.js`, `server.py`, `tests/journal-api.test.js`, `tests/journal.test.js`.

Review changes are confined to the two inventories, their generator, this verification document and the generated checkpoint changelog. No new domains or large features; Media/Oscar has not started. The existing scope limits above remain applicable. Post-merge tests and final Git state are reported in the integration response.
