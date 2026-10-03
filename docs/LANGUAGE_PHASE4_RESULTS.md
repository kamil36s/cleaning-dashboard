# Language Learning Phase 4 results

Status: **COMPLETE**  
Date verified: 2026-09-16  
Database schema version: 3  
Frontend page: `language.html`

## 1. Outcome

Phase 4 completes the Reader vertical slice over the existing Phase 1-3 language core. A user can paste and save a text, start and monitor the existing durable analysis job, open an analyzed document, read the exact source with canonical vocabulary states, inspect and edit the shared lemma, see canonical coverage, explicitly start a conservative reading session, persist semantic progress, complete the text, and reopen it from history.

The implementation preserves the single canonical vocabulary model, the existing analysis worker, manual mapping locks, and the Phase 2 preview/commit machinery. Import, analysis, rendering, and reopening alone record no exposure. Phase 5 functionality was not started.

## 2. Files created

- `js/language/views/reader.js`
- `tests/language-reader.test.js`
- `docs/LANGUAGE_PHASE4_RESULTS.md`

## 3. Files modified

- `language.html`
- `language.css`
- `js/language/app.js`
- `js/language/api.js`
- `js/language/router.js`
- `js/language/state.js`
- `js/language/views/overview.js`
- `language_learning/migrations.py`
- `language_learning/store.py`
- `language_learning/service.py`
- `server.py`
- `tests/language-api.test.js`
- `tests/language-router.test.js`
- `tests/language-page.test.js`
- `tests/test_language_store.py`
- `tests/test_language_services.py`
- `tests/test_language_api.py`
- `docs/LANGUAGE_IMPLEMENTATION_PLAN.md`
- `docs/LANGUAGE_RUN_PROGRESS.md`

No dashboard widget, dashboard registry, Phase 5 view, second vocabulary store, duplicate job table, duplicate analyzer registry, or second worker was added.

## 4. Schema version and migration

Schema v3 is a forward-only additive migration from v2:

- `study_sessions` gains `activity_state`, `last_heartbeat_at`, `last_active_at`, and `last_command_id`;
- `exposure_events` gains `batch_idempotency_key` and an index supporting retry lookup;
- `text_reading_progress` stores one profile/text reading state, semantic code-point source offset, sentence reference, timestamps, completion coverage snapshot, and analysis-run reference.

The total is 16 Language tables. Existing Phase 1/2 data and schema objects remain intact. Export format advances to `language-learning-export/v3` and includes reading progress. Controlled canonical backups bracket the migration:

- pre-migration: `language-learning-v2-20260916T113319714899Z.sqlite`
- post-migration: `language-learning-v3-20260916T120016123345Z.sqlite`

## 5. Reader routes

The reload-safe hash router now supports:

- `#reader` — text library and paste/import surface;
- `#reader/text/<textId>` — draft, analysis-job, failure, and analyzed Reader states.

The persistent application shell remains mounted across Overview, Vocabulary, Reader, and Settings. Direct loading, refresh, back, and forward resolve from the hash.

The Reader uses the existing text/job routes plus these thin Phase 4 commands:

- `POST /api/language/study-sessions`
- `PATCH /api/language/study-sessions/{sessionId}`
- `POST /api/language/study-sessions/{sessionId}/exposures`
- `PATCH /api/language/texts/{textId}/reading-progress`

Existing create/detail/history, analyze, job status/cancel, and reanalysis preview/commit routes were reused.

## 6. Import, save, and analyze flow

Paste/save persists the exact source document and creates no study session or exposure. The user explicitly starts the existing persisted analysis job. The Reader displays queued/running stage, progress, failure detail, cancel, and retry states, and polls the durable job instead of running analysis in the browser.

Analysis remains on the single Phase 2 worker and reusable `AnalyzerRegistry`. Restart recovery, cooperative cancellation, atomic commit, preview-only runs, Stanza pipeline reuse, and no-download behavior remain tested. Import and analysis do not mutate exposure or knowledge state.

## 7. Exact rendering and offsets

The stored source is canonical. The Reader groups stored tokens by sentence, converts stored Unicode code-point ranges through the Phase 3 `codePointRangeToUtf16Range` boundary, and reconstructs gaps and tokens from slices of the original source. Whitespace, multiple spaces, newlines, punctuation, Norwegian characters, emoji, and non-BMP boundaries therefore remain exact.

Source and lexical values are inserted with DOM nodes and text content. Production Language code contains no `innerHTML` or `outerHTML`; literal HTML-like source cannot create or execute markup. A single delegated token-click listener serves all rendered tokens.

## 8. Word-state design and shared lemma interaction

Tokens receive restrained, accessible treatments for known, learning, new, ignored, excluded, and unresolved states. A legend and a “Show vocabulary colors” control accompany the text, and state is not communicated only by color.

All linked surface forms use the canonical lemma identity. The fixtures `jobb`, `jobben`, `jobber`, and `jobbene` therefore share one state. Clicking any linked occurrence opens the same Phase 3 lemma dialog with the current sentence context. An accepted knowledge edit refetches text detail, updating every linked occurrence and coverage without a page reload; it edits the same record shown by Vocabulary.

## 9. Coverage behavior

The displayed token and unique-lemma coverage comes from the backend `CoverageService`, with raw numerator/denominator counts, percentages, policy version, and unresolved/excluded denominator context. Missing evidence is shown as unknown rather than invented.

After a lemma edit, the Reader refetches the canonical text detail and coverage. Explicit completion freezes the then-current canonical backend coverage snapshot and analysis-run reference in reading progress. History shows current coverage alongside the stored completion snapshot.

## 10. Study-session design

Opening or rendering a text does not begin study. The user must select Start/Continue. A client session ID makes start retries idempotent. Commands use stable command IDs and support `HEARTBEAT`, `PAUSE`, `RESUME`, and `COMPLETE`; duplicate command delivery does not double-apply state.

The browser pauses on hidden/inactive visibility and resumes only the explicit session when visible again. Route teardown stops observers/timers and safely ignores late responses, preventing a completed route transition from resurrecting a session.

## 11. Exact exposure policy and idempotency

An exposure is eligible only while the explicit session is active and at least 60% of a sentence has remained visible continuously for two seconds. The browser batches the sentence's linked lemma occurrence counts and uses the stable event key `<clientSessionId>:<sentenceId>`. A sentence is submitted at most once in that explicit client session; merely restoring scroll/progress does not submit it.

The backend does not trust arbitrary counts. It derives the canonical linked-lemma counts from the stored analyzed sentence and requires the submitted sentence ID and complete lemma-count map to match exactly. Inflated, omitted, cross-text, or otherwise inconsistent claims are rejected atomically. The accepted batch writes one aggregate exposure row per lemma, updates exposure totals and first/last-seen evidence, and records the corresponding knowledge event. It never automatically marks a lemma learned, known, or mastered.

The batch idempotency key and transaction make retry/timeout replay return the existing result without double-counting. Reopening a text alone creates neither a new session nor duplicate exposures. A later, separately started reading session may legitimately count the sentence again.

## 12. Active-time policy

The server owns accumulated active seconds. It measures only intervals while a session is `ACTIVE`, closes them on heartbeat/pause/complete, and caps any one reported interval at 30 seconds. The browser sends a heartbeat every 10 seconds while visible. Hidden-tab intervals and time after explicit pause are excluded; tests cover 30 seconds active, 60 seconds hidden, then 20 seconds active yielding exactly 50 active seconds.

## 13. Reading progress, completion, and history

Progress stores a semantic Unicode code-point source offset and sentence ID rather than a viewport pixel position. Reload/reopen restores the associated source location without manufacturing an exposure. States are `NOT_STARTED`, `IN_PROGRESS`, and `COMPLETED`, with last-read and completion timestamps.

Completion is an explicit user action. It closes the active session, persists `COMPLETED`, and stores canonical completion coverage. Text history includes analysis/job state and error, token and unique-lemma counts, current canonical coverage, progress, last-read/completion facts, completion snapshot, and active seconds. Text detail includes the latest job, reading progress, and recent Reader sessions.

## 14. Studied-document reanalysis safety

Preview reanalysis remains available because it does not mutate the committed token graph. Committed reanalysis is rejected with `studied_text_reanalysis_blocked` once the document has reading progress, active-time/session activity, or exposure evidence. The worker repeats the guard immediately before commit, closing the enqueue/commit race. Historical exposures therefore cannot silently point at a replaced analysis. Existing manual mapping locks retain their precedence.

## 15. Performance observations

A synthetic 3,500-token document rendered and remained interactive with the one delegated listener. Focused happy-dom observations were approximately 427–529 ms; under the parallel full suite the same assertion was approximately 1,079 ms. These are development-test observations, not production benchmarks.

The document is sentence-grouped and avoids one listener per token, repeated linear token lookup, and vocabulary-history expansion. Normal navigation remained responsive. Full virtualization was not added because the required synthetic scale passed without it.

## 16. Visual and responsive verification

Real Edge headless rendering was inspected at 1440 × 1000 for the Reader library and populated analyzed Reader, and at 430 × 900 for the narrow analyzed Reader. Exact literal `<script>` source remained inert and visible, coverage/state styling was coherent, the prose width remained readable, controls wrapped compactly, and the final narrow layout had no horizontal clipping.

Temporary visual data used an isolated schema-v3 database and offline fake analyzer. It did not mutate canonical personal text data; the temporary server was stopped after inspection.

## 17. Norwegian flag

The persistent profile identity now places a compact inline SVG Norwegian flag immediately left of the two-line language text. It uses the real 22:16 construction and official red/blue values (`#BA0C2F`, `#00205B`) with the white cross, displays at approximately 26 × 18.9 px, has a 2 px radius and subtle 1 px neutral border, and has no emoji, glow, heavy shadow, pill, or enclosing identity background.

The language name remains primary and the language code/locale remains smaller and muted. The flag is vertically centered and appears consistently on Overview, Vocabulary, Reader, and Settings, including the compact narrow layout.

## 18. Tests and build

New Phase 4 frontend tests:

| Change | New tests |
| --- | ---: |
| `tests/language-reader.test.js` | 5 |
| `tests/language-router.test.js` | 1 |
| `tests/language-api.test.js` | 1 |
| `tests/language-page.test.js` | 4 |
| **Exact new Phase 4 frontend total** | **11** |

New Phase 4 backend tests:

| Area | New tests |
| --- | ---: |
| v1-through-v3 additive migration preservation | 1 |
| session, exposure, active-time, progress, and reanalysis services | 3 |
| HTTP vertical slice | 1 |
| **Exact new Phase 4 backend total** | **5** |

Final verification:

| Command/check | Exact result |
| --- | --- |
| complete Language frontend suite | 47 passed, 0 failed |
| complete Language backend suite | 83 passed, 0 failed |
| real persisted Stanza integration | passed; provisioned offline pipeline reused and model download/network paths blocked |
| focused dashboard regressions | 34 passed, 0 failed |
| `npm run test:run` | 675 passed, 2 skipped, 0 failed across 106 files |
| `python -m unittest discover -s tests -p "test_*.py" -v` | 431 passed, 1 skipped, 0 failed |
| `npm run build` | passed; `dist/language.html` present; existing warnings only |
| Language JavaScript syntax | 11 files passed |
| Python compilation | passed |
| canonical database | schema v3; 16 tables; migrations 1/2/3; `integrity_check = ok`; zero FK violations |
| canonical analyzer side effect | Stanza remained unimported during migration/backup checks |

No analysis or Reader operation automatically changed a lemma's learned/known/mastered state. The existing non-failing Stanza-adjacent dependency warning, Vite large-chunk/non-module warnings, and expected connection-refused stderr in an isolated Event Countdown notification test remain unchanged.

## 19. Deviations and known limitations

- The implementation plan suggested window/lazy rendering. The acceptance-scale 3,500-token fixture remained usable with sentence-grouped full rendering, delegated interaction, and indexed grouping, so virtualization was not added without profiling evidence.
- The older plan mentioned a queue-for-Anki intent, but the authoritative Phase 4 request explicitly excluded Anki/Phase 6 work. No Anki persistence or UI was added.
- Automatic sentence encounters require `IntersectionObserver`. A browser without it can still read, save progress, and complete, but does not automatically record sentence exposure. The supported Edge visual target provides it.
- Heartbeat accounting is deliberately conservative: it uses a 10-second client heartbeat and 30-second server cap, so sub-heartbeat activity lost to abrupt process/tab termination is not backfilled.
- A sentence is counted once per explicit session, not once forever. A new explicit reading session can create new evidence for rereading.
- Long documents are not virtualized yet; revisit only if real profiling exceeds the tested scale or navigation budget.
- Reader exposes analysis retry/cancel but no prominent committed-reanalysis control. The backend preview/commit API and studied-document block remain authoritative.
- Completion coverage is a frozen snapshot, not silently rescored; history also returns current coverage so the distinction remains visible.
- Definitions, translations, topics, statistics, goals, dashboard widget, AI generation, Cloze, Listening, Grammar, and Anki remain outside Phase 4.

## 20. Acceptance and exact Phase 5 recommendation

All 41 Phase 4 acceptance criteria pass. There are no unmet Phase 4 criteria. Phase 4 is complete.

Proceed with **Phase 5 only** when explicitly authorized: build topics, truthful event-derived statistics, versioned goals and deterministic learning-plan rules over the canonical Phase 1-4 evidence, then add the compact opt-in dashboard widget through the existing registry/settings/order mechanisms. Preserve `VocabularyLemma.id`, the schema-v3 session/exposure/progress semantics, immutable completion snapshots, and the studied-document reanalysis guard. Do not add Anki, AI generation, Cloze, Listening, or Grammar as part of Phase 5.
