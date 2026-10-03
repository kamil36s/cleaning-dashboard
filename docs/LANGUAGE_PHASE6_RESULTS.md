# Language Learning Phase 6 results

Status: **COMPLETE**  
Date verified: 2026-09-16  
Database schema version: 5  
Frontend page: `language.html`

## 1. Outcome

Phase 6 adds a bounded local AnkiConnect integration without creating a second scheduler or vocabulary store. Users can configure a loopback endpoint, inspect capabilities/decks/models/fields, preview exact note projections, explicitly create/update/link notes, resolve supported field conflicts, and explicitly pull supported card aggregates. Anki remains authoritative for scheduling and answering.

The adapter never writes Language domain state. `AnkiSyncService` orchestrates the wire adapter and store, while all knowledge evidence enters through `LanguageService`. Discovery and previews are read-only; remote mutation always requires a separate explicit confirmation.

No Phase 7 generation, AI-provider, Cloze, Listening, Grammar, media, AnkiWeb sync, automatic periodic sync, destructive cleanup, or dashboard SRS behavior was added.

## 2. Files created

- `language_learning/providers/anki.py`
- `language_learning/anki_sync.py`
- `js/language/views/reviews.js`
- `tests/test_language_anki.py`
- `tests/test_language_providers.py`
- `tests/language-anki.test.js`
- `docs/LANGUAGE_PHASE6_RESULTS.md`

## 3. Files modified

- `language_learning/migrations.py`, `store.py`, `service.py`, `learning_plan.py`
- `server.py`, `.env.example`
- `language.html`, `language.css`
- `js/language/api.js`, `app.js`, `router.js`, `state.js`
- `js/language/components/lemma-detail.js`
- `js/language/views/settings.js`, `overview.js`
- `js/widget-language-learning.js`
- `tests/test_language_store.py`, `tests/test_language_api.py`
- `tests/language-api.test.js`, `tests/language-page.test.js`
- `docs/LANGUAGE_IMPLEMENTATION_PLAN.md`, `docs/LANGUAGE_RUN_PROGRESS.md`

Unrelated dirty-worktree changes were preserved.

## 4. Schema v5 and migration

The additive v5 migration adds `anki_config_json` to `language_profiles` and exactly three tables:

- `anki_note_links`: one profile/lemma/template-purpose link with remote note identity, stable dashboard identity, projection hashes, conflict state, and optional source context;
- `anki_card_snapshots`: supported observed card aggregates and scheduling metadata, with no dashboard-owned scheduling state;
- `anki_sync_runs`: explicit TEST/PUSH/PULL/LINK run state, counts, bounded error detail, and timestamps.

The database advances from 19 to 22 Language tables. Export advances to `language-learning-export/v5` and includes safe Anki configuration/link/snapshot/run data.

Controlled migration backups:

- pre-migration v4: `data/backups/language-learning-v4-20260916T134241896712Z.sqlite`;
- post-migration v5: `data/backups/language-learning-v5-20260916T134247456973Z.sqlite`.

The canonical database and both backups pass `integrity_check = ok` with zero foreign-key violations. All common v4 table row counts, excluding the migration ledger, are identical before and after migration.

## 5. Adapter and network security

`AnkiAdapter` is a wire-only `urllib` adapter. It accepts only literal loopback HTTP endpoints at `127.0.0.1` or `[::1]` with an explicit port. It rejects HTTPS, hostnames including `localhost`, remote addresses, credentials, paths, query strings, fragments, redirects, oversized responses, invalid JSON, unsupported response shapes, and actions outside its allowlist.

Read actions are limited to capability/discovery/note/card lookup and duplicate preflight. Write actions are limited to `addNote`, `updateNoteFields`, and `addTags`. Delete, scheduling, answer, and AnkiWeb `sync` actions are not available. Calls use bounded timeouts and normalized unavailable/HTTP/version error states.

The optional API key is read only from `LANGUAGE_ANKI_CONNECT_API_KEY`. It is added to the wire request when configured, is never persisted, returned by an API, logged, or exported. Public configuration exposes only `apiKeyConfigured`.

## 6. Configuration, capability, and discovery

Profile configuration stores enabled state, loopback endpoint, target deck, note model, and mappings for target, lemma, context, translation, definition, notes, source, topic, and stable dashboard key. Settings exposes save, read-only connection test, and explicit deck/model/field discovery.

Capability status is truthful: `CONNECTED`, `UNAVAILABLE`, `HTTP_ERROR`, `VERSION_UNSUPPORTED`, `NOT_CONFIGURED`, or `PARTIALLY_CONFIGURED`. Discovery performs no remote writes.

## 7. Stable identity and duplicate prevention

The primary stable identity is `language-dashboard:<profile-id>:<lemma-id>:vocabulary`, stored in a configured dashboard-key field when available and always added as a stable tag fallback. Visible front text is projection content, never identity.

Resolution order is local link, stable external key/tag lookup, explicit selected note, then duplicate preflight. The local uniqueness constraint prevents more than one link for a lemma/template purpose. Repeated create is a no-op, stale local links reconcile through stable discovery, and a timeout after successful remote creation is reconciled by stable lookup before retrying. Tests prove these paths do not duplicate notes.

## 8. Preview, create, update, and link

Preview validates capability, deck, model, and mapped fields, then returns the exact proposed deck/model/fields/tags/context and a fingerprint. It performs zero remote writes. Missing translations and definitions remain blank.

Commit requires `confirm: true` and the exact preview fingerprint. Create/update/link results are recorded only after confirmed remote state. Explicit existing-note linking is also preview-first and confirm-only; the stable identity is added through the configured field or tag before the durable link is stored.

Reader-selected sentence context is preferred. Otherwise the service uses the latest real persisted sentence for the lemma. The stored link retains the source text/sentence reference.

## 9. Conflict semantics

Projection hashes distinguish `NONE`, `LOCAL_CHANGED`, `REMOTE_CHANGED`, and `BOTH_CHANGED`. Field-level conflict output shows last-synced, dashboard-proposed, and current Anki values. No conflict path silently chooses a winner.

Explicit `DASHBOARD_WINS` writes the supported projected fields to Anki. Explicit `ANKI_WINS` accepts the remote projection as the new baseline without changing the canonical lemma/knowledge record. Both paths require a current preview fingerprint.

## 10. Metadata pull and evidence

Pull is manual. It observes linked cards through `findCards`/`cardsInfo` and stores only supported real aggregates: card/note/deck identity, queue/type, due, interval, ease factor, repetitions, and lapses. It does not fabricate review history or claim per-review events.

Snapshot evidence enters through `LanguageService` as an idempotent `ANKI_CARD_SNAPSHOT` knowledge event under `language.anki-evidence/v1`, with `knowledgeMutation: NONE` and `historyCapability: AGGREGATES_ONLY`. It cannot change knowledge status, scores, mastery, or Anki scheduling.

Partial card failures produce `PARTIAL` runs with succeeded/failed counts and item errors. A retry safely upserts snapshots/evidence and does not duplicate canonical events. Top-level pull failure is recorded as `FAILED`.

## 11. Learning plan and UI

Learning-plan policy advances to `language.learning-plan/v2`. A genuinely connected, observed positive due count adds an `ANKI_DUE` action while explicitly saying that scheduling and answering remain in Anki. With no observed count, no due value is invented.

- Overview reports connection, due, linked, conflict, and last-sync state truthfully and can show the due-plan action.
- Reviews is an orchestration/status page with due/link/conflict counts, manual metadata pull, and recent sync runs; it is not a second review scheduler.
- Reader and Vocabulary share the same lemma-detail Anki panel for exact preview, create/update, link, linked state, conflict rows, and explicit resolution.
- Settings provides safe configuration and discovery with server-side secret status only.
- The compact dashboard widget shows an Anki due indicator only when a genuine integer due count exists.

The Reviews route is enabled; Phase 7+ navigation remains disabled.

## 12. Thin API routes

Added reads:

- `GET /api/language/profiles/{id}/anki/status`
- `GET /api/language/profiles/{id}/anki/config`
- `GET /api/language/profiles/{id}/anki/decks`
- `GET /api/language/profiles/{id}/anki/models`
- `GET /api/language/profiles/{id}/anki/models/{model}/fields`
- `GET /api/language/profiles/{id}/anki/sync-runs`
- `GET /api/language/lemmas/{id}/anki`

Added writes:

- `PATCH /api/language/profiles/{id}/anki/config`
- `POST /api/language/profiles/{id}/anki/test`
- `POST /api/language/profiles/{id}/anki/pull`
- `POST /api/language/lemmas/{id}/anki/preview`
- `POST /api/language/lemmas/{id}/anki/commit`
- `POST /api/language/lemmas/{id}/anki/link`
- `POST /api/language/lemmas/{id}/anki/resolve`

`server.py` performs bounded parsing and delegates all behavior to `LanguageService`.

## 13. Tests

Exact new Phase 6 backend tests: **15**.

| Area | New tests |
| --- | ---: |
| v4-to-v5 migration preservation | 1 |
| deterministic Anki service/fake integration | 8 |
| wire adapter/provider safety | 5 |
| Phase 6 HTTP vertical slice | 1 |

Exact new Phase 6 frontend tests: **6**.

| Area | New tests |
| --- | ---: |
| Settings/discovery, preview/conflict, linked metadata, Reviews | 4 |
| thin frontend API routes | 1 |
| enabled Reviews page route | 1 |

## 14. Final verification

| Command/check | Exact result |
| --- | --- |
| complete Language backend suite | 112 passed, 0 failed |
| complete Language frontend suite | 65 passed, 0 failed |
| real Stanza fixtures | passed; downloads blocked and provisioned pipeline reused |
| broad backend suite | 460 passed, 1 skipped, 0 failed |
| broad frontend suite | 693 passed, 2 skipped, 0 failed |
| `npm run build` | passed; existing non-module/large-chunk warnings only |
| Python compilation | passed |
| changed JavaScript syntax checks | passed |
| canonical database | schema v5; 22 tables; `integrity_check = ok`; zero FK violations |
| export sentinel check | API-key sentinel absent; no `apiKey` field present |

The existing non-failing Python dependency warning and Happy DOM connection-refused/abort diagnostics remain baseline noise and created no failures.

## 15. Real Anki smoke status

A read-only AnkiConnect `version` probe to `http://127.0.0.1:8765` returned HTTP 404. No live collection mutation was attempted. The real Anki smoke test is therefore **NOT PERFORMED**, as allowed by the acceptance contract; all adapter/service/write/idempotency cases passed against the deterministic fake.

## 16. Visual verification

Real headless Edge rendering was inspected against an isolated schema-v5/fake-Anki server at 1440 x 1000 for Settings Anki mappings, Vocabulary linked state, Reader source-context Anki action, Reviews, Overview due/status, and the field-level conflict panel with both explicit resolution buttons. Narrow rendering was inspected for Reader and Settings at the requested narrow breakpoint; browser metrics reported page width equal to viewport width with no horizontal document overflow.

Inspection found and corrected malformed separators in Reviews, responsive Anki action wrapping, and a safe optional Reader draft-state method call. Mapping forms, conflict rows, controls, status hierarchy, context attribution, and compact navigation passed. The isolated server was stopped and no canonical personal content or live Anki data was mutated.

## 17. Acceptance, deviations, and limitations

All 45 Phase 6 acceptance criteria pass. There are no unmet criteria.

Documented deviations/limitations:

- Real Anki mutation was not performed because the local read-only capability probe returned HTTP 404; deterministic fake coverage is complete.
- AnkiConnect exposes current card aggregates, not a reliable full review-event history through this contract, so Phase 6 stores aggregate snapshots and makes no review-history claim.
- Sync remains explicit/manual. No background timer, destructive cleanup, answering UI, dashboard scheduler, or AnkiWeb sync exists.
- Only one vocabulary template purpose is implemented; the schema identity supports additional explicitly designed purposes later.

The exact next recommendation is **Phase 7 only**: implement adaptive generation with a deterministic, versioned manual-provider workflow (target selection, prompt construction, pasted structured response validation, actual coverage analysis, and explicit save), while preserving the canonical Vocabulary/Reader/Anki ownership boundaries and without adding automatic paid-provider calls.
