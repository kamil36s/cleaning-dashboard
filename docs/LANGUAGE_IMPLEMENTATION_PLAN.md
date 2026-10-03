# Language Learning Dashboard implementation plan

Status: The active Language roadmap, Phases 0 through 12, is complete, including the intentionally pulled-forward Phase 9A Cloze MVP. Optional future extensions remain unscheduled and require separate authorization. Main schema is v16; reference schema is v3 read-only.  
Architecture reference: [`LANGUAGE_ARCHITECTURE.md`](./LANGUAGE_ARCHITECTURE.md)

## 1. Delivery rules

Every phase below is a releasable checkpoint. At the end of each phase:

- the existing dashboard and all existing pages must still build and run;
- only the sections supported by the current backend should be enabled in the Language page;
- database changes must be forward-only, migration-tested, and backed up when upgrading real data;
- new deterministic behavior must have focused tests;
- provider tests use fakes or synthetic fixtures, never paid/live services by default;
- no phase may introduce a second vocabulary store;
- `VocabularyLemma.id` remains the common key across every added module;
- existing IDs, `data-widget` keys, localStorage keys, API paths, and unrelated schemas remain unchanged.

Suggested verification after any phase that touches the production entry points:

```powershell
npm run test:run -- tests/language-*.test.js
python -m unittest tests/test_language_store.py tests/test_language_api.py
npm run build
```

The exact focused test list should grow with the phase; do not run or read generated coverage/report directories as part of ordinary work.

## 2. Phase dependency map

```text
0 contracts/Norwegian spike
        |
1 shared store + service + API foundation
        |
2 analysis + text ingestion jobs
        |
3 page shell + vocabulary management
        |
4 Reader + real exposure tracking
        |
5 topics + statistics + goals + overview/widget
        |
6 Anki integration
        |
7 adaptive generator with manual provider workflow
        |
7.5A reference source audit + isolated reference architecture
        |
7.5B reproducible reference ingestion
        |
9A pulled-forward Cloze Fast Track MVP (narrow reference access only)
        |
7.5C read-only Reader/generator reference integration
        |
7.6 evidence-driven gamification, completion + campaigns
        |
7.7 dictionary, meanings, translations + personal phrasebook
        |
7.8 curated practical vocabulary curricula + Norway packs
        |
8 configured AI provider + automatic revision loop
        |
9 full Reviews + Cloze from shared contexts
        |
9.5 mistake intelligence + targeted remediation
        |
10 listening foundation with Bokmål browser TTS
        |
10.5 authentic content inbox + audio/transcripts/aligned listening
        |
11 Core Grammar A1–B1
        |
11.5 Progress Benchmarks + lightweight Norway Preparation
        |
11.6 Study Session Builder
        |
12 Operational Hardening
```

Phase 9A occurred early as a deliberately narrow usability slice and is already complete; it is historical context, not a step to execute again. All active work through Phase 12 is complete. There is no active Phase 11.7 or next implementation batch.

Full Bokmål Tier-3 `n=2..6` ingestion remains optional reference enrichment under separate authorization. It is not an active dependency or a subsystem-completion requirement.

## Phase 0 — Freeze contracts and prove the Norwegian toolchain

Phase status: **COMPLETE (2026-09-15)**. Evidence and measured limitations are recorded in [`LANGUAGE_PHASE0_RESULTS.md`](./LANGUAGE_PHASE0_RESULTS.md); the reference-data policy is frozen in [`LANGUAGE_DATA_SOURCES.md`](./LANGUAGE_DATA_SOURCES.md).

### Outcome

A small, non-UI technical spike selects the canonical Bokmål analysis path and freezes the first domain/API contracts before durable user data exists.

### Work

- Turn the architecture's core types into versioned Python/JSON contract fixtures: analysis document, lemma/form mapping, coverage report, knowledge command, and error envelope.
- Create synthetic Bokmål fixtures covering `jobb/jobben/jobber/jobbene`, verb/adjective inflection, `æ/ø/å`, punctuation, names, URLs, numbers, ambiguity, and sentence boundaries.
- Benchmark candidate analyzers on correctness, cold start, warm latency, memory, exact character offsets, POS/morphology, and offline behavior.
- Prefer Stanza `nb` only if the fixture contract is met. Evaluate Simplemma only as an explicitly lower-confidence fallback; do not combine outputs without a written precedence rule.
- Verify the installed `wordfreq` version handles `nb`, and decide whether it supplies only scores or also the initial ranked bands.
- Probe a local AnkiConnect test installation for version/capabilities without creating or changing notes.
- Define provider health states and environment variable names.
- Add a diagnostic script that reports missing models/configuration without downloading anything.

### Likely files

- `requirements-language.txt` (new)
- `language_learning/schemas.py` (new)
- `language_learning/analysis/base.py` (new)
- `language_learning/analysis/norwegian_bokmal.py` (new, spike implementation only)
- `scripts/diagnose_language_env.py` (new)
- `tests/fixtures/language/nb/*` (new)
- `tests/test_language_analysis.py` (new)
- `.env.example` only for documented non-secret setting names

### Verification

- Run the analyzer test against committed fixtures with network disabled.
- Run the diagnostic script in both configured and missing-model states.
- Record cold/warm benchmark results in a short appendix or test fixture, not a generated report directory.

### Acceptance criteria

- [x] Every output token has exact, non-overlapping Unicode-code-point source offsets and the original text can be reconstructed around tokens (197/197 measured tokens, including a token after an emoji).
- [x] The target noun forms `jobb`, `jobben`, `jobber`, and `jobbene` resolve to lemma `jobb` with noun POS in the fixture.
- [x] Norwegian letters are preserved in display and normalized lookup values.
- [x] Ambiguous/unknown analysis is represented explicitly; Stanza model hypotheses expose `NOT_REPORTED` ambiguity, `NOT_ASSESSED` lexical status, and nullable confidence rather than claiming lexical certainty.
- [x] Analyzer ID, adapter/package/resource version, processor packages, manifest fingerprint, and explicit confidence basis are present in the contract.
- [x] Missing analyzer models produce a clear health state and no download; pipeline construction forces `DownloadMethod.NONE`.
- [x] No database, page, widget, API route, or navigation entry is added.

### Deliberately postponed

- Persistent vocabulary/text storage.
- Reader UI.
- Dictionary/translation choice.
- AI, Anki writes, TTS, topics, and grammar detection.

## Phase 1 — Shared database, migrations, domain service, and API foundation

Phase status: **COMPLETE (2026-09-15; re-verified after repository recovery on 2026-09-16)**. Implementation and verification evidence are recorded in [`LANGUAGE_PHASE1_RESULTS.md`](./LANGUAGE_PHASE1_RESULTS.md).

### Outcome

One canonical SQLite database can safely store language profiles, lemmas, surface forms, knowledge state/history, texts/tokens, study sessions, and exposures. It has health and export APIs but no production UI.

### Work

- Add `LanguageStore` with ordered checksumed migrations, WAL, foreign keys, busy timeout, operation-scoped connections, and temporary-path injection for tests.
- Add the first core tables only: profiles/settings, lemmas, forms, form/lemma links, knowledge snapshots/events, text drafts/sentences/tokens, analysis/import runs, sessions, and exposures.
- Add `LanguageService` methods for profile creation, lemma/form upsert, manual knowledge update, manual mapping lock, lemma merge/redirect, and idempotent activity recording.
- Define stable error codes and consistent `{ok,data}` / `{ok:false,error,code,details}` envelopes.
- Add thin server initialization and routes for health, profiles, lemma CRUD/search, and export.
- Enforce payload sizes and existing same-origin write authorization.
- Add versioned JSON export and an internal SQLite backup operation using SQLite's backup API. Restore remains separate.
- Initialize one Bokmål profile explicitly through a seed/service command, not an implicit assumption in every query.

### Likely files

- `language_learning/__init__.py`, `errors.py`, `migrations.py`, `store.py`, `service.py`, `validation.py`, `schemas.py` (new)
- `server.py` (thin import, initialization, shutdown, and route branches)
- `tests/test_language_store.py`, `tests/test_language_services.py`, `tests/test_language_api.py` (new)

### Verification

- Initialize a fresh temporary DB twice and assert an identical schema/migration ledger.
- Migrate an explicit version-0/partial fixture forward.
- Exercise the new routes against `DashboardHTTPServer` on an ephemeral port.
- Test transaction rollback, foreign keys, idempotency keys, and export from synthetic data.
- Run existing server-startup tests plus focused language tests.

### Acceptance criteria

- [x] There is exactly one durable source for vocabulary knowledge: `data/language-learning.sqlite`.
- [x] Four forms can link to one lemma without producing four knowledge records.
- [x] A form can have multiple candidate lemmas and a token can select one candidate.
- [x] A manual mapping/status is marked and protected from automated overwrite.
- [x] Lemma merge updates/redirects every core foreign-key reference transactionally and is audit logged.
- [x] Repeating the same activity command cannot double-count exposures.
- [x] Health reports schema version without leaking paths/secrets.
- [x] JSON export includes a schema version and round-trips synthetic core data.
- [x] Existing dashboard/page behavior is unchanged.

### Deliberately postponed

- Analyzer execution and text analysis jobs.
- All Language UI/navigation.
- Definitions/translations, topics/goals, Anki, AI, cloze, listening, and grammar.
- Import restore/overwrite UI.

## Phase 2 — Canonical Bokmål analysis and text-ingestion jobs

Phase status: **COMPLETE (2026-09-16)**. Implementation, migration, lifecycle, performance, and regression evidence are recorded in [`LANGUAGE_PHASE2_RESULTS.md`](./LANGUAGE_PHASE2_RESULTS.md).

### Outcome

The backend can accept a pasted/imported Bokmål draft, analyze it in a persisted job, resolve tokens to the shared vocabulary model, attach frequency provenance, and return a coverage-ready reader payload.

### Work

- Add the analyzer registry and the selected Bokmål adapter from Phase 0.
- Add a `FrequencyProvider` interface and versioned `wordfreq` adapter.
- Add persisted language jobs with stages, progress, error, cancellation where safe, and startup recovery.
- Add text draft, analyze/reanalyze-preview, text detail, job status, and text-history endpoints.
- Fingerprint raw content plus analyzer/policy versions so accidental duplicate analysis is idempotent.
- In one service transaction, upsert forms/lemmas/links and persist sentence/token analysis.
- Keep ambiguous tokens unresolved and expose candidates.
- Add `CoverageService` and the frozen coverage report contract, although no Reader UI consumes it yet.
- Add reanalysis preview showing proposed changes; commit only unlocked changes after explicit confirmation.

### Likely files

- `language_learning/analysis/*` (new/expanded)
- `language_learning/providers/frequency.py` (new)
- `language_learning/jobs.py`, `coverage.py` (new)
- `language_learning/store.py`, `service.py`, `migrations.py` (expanded)
- `server.py` (thin text/job route branches and worker lifecycle)
- `tests/test_language_analysis.py`, `test_language_coverage.py`, `test_language_jobs.py`, `test_language_api.py` (new/expanded)

### Verification

- Analyze all committed Bokmål fixtures offline.
- Restart the job manager with queued/running synthetic jobs and verify documented recovery behavior.
- Import the same content twice with the same idempotency key.
- Compare coverage raw counts to hand-calculated fixture values.
- Test analyzer unavailable, malformed text, oversized text, cancellation, ambiguity, and rollback after a simulated failure.

### Acceptance criteria

- [x] Exact source text and offsets survive save/analyze/load without normalization damage.
- [x] Persisted tokens refer to shared lemma IDs or carry an explicit unresolved state.
- [x] Analyzer/frequency provider versions are stored.
- [x] Importing/analyzing text does not create exposures or mark words learned.
- [x] Coverage reports separate known, learning, unknown, ignored, excluded, ambiguous, and non-lexical counts.
- [x] Reanalysis never overwrites a manually locked mapping.
- [x] A failed analysis leaves the previous committed analysis intact or the draft in a clear recoverable state.

### Deliberately postponed

- Production page and Reader interaction.
- Dictionary definitions/translations.
- Background parallel job lanes or SSE.
- AI generation and grammar dependency parsing.

## Phase 3 — Language page shell, routing, Vocabulary, and Settings

Phase status: **COMPLETE (2026-09-16)**. Implementation, API, accessibility, visual, build, and regression evidence are recorded in [`LANGUAGE_PHASE3_RESULTS.md`](./LANGUAGE_PHASE3_RESULTS.md).

### Outcome

The user can open an integrated Language Learning page, navigate reload-safe hash routes, search/filter vocabulary, inspect/edit the shared lemma/form state, resolve ambiguities, and view provider health/settings.

### Work

- Add `language.html` as a Vite entry and `language.css` scoped under `.language-page`.
- Build persistent sidebar/topbar/page mount following the compact Music page pattern, using global dashboard tokens and native controls.
- Add pure hash route parsing for Overview, Vocabulary, lemma detail, and Settings. Show unsupported future sections as disabled or “not available yet”; do not render fake metrics.
- Add `js/language/api.js` and a page-local state/controller.
- Build paginated searchable Vocabulary and a native `<dialog>` or routed detail panel.
- Support knowledge status/disposition and recognition/recall/production edits, form corrections/locks, notes, and lemma merge preview.
- Build Language Settings for profile, analyzer health, translation locale, and frequency provenance. Secrets are status-only.
- Add a dashboard side shortcut under the existing `Czytanie` group. Do not add the compact widget yet.
- Add loading, empty, offline, validation, and conflict states.

### Likely files

- `language.html`, `language.css` (new)
- `js/language/app.js`, `api.js`, `router.js`, `state.js`, `model.js` (new)
- `js/language/components/dialog.js`, `filters.js`, `status-control.js` (new as needed)
- `js/language/views/overview.js`, `vocabulary.js`, `settings.js` (new; Overview is a truthful minimal state)
- `vite.config.js`, `index.html` (small existing-file edits)
- `tests/language-router.test.js`, `language-model.test.js`, `language-page.test.js` (new)

### Verification

- Focused Vitest tests for route parsing, API errors, view models, forms, and keyboard-accessible dialog behavior.
- `npm run build` to verify the new HTML entry and relative assets.
- Manual desktop/mobile check against the existing dark dashboard.
- Reload every supported hash route directly.

### Acceptance criteria

- [x] The new page looks like part of the existing dashboard and does not introduce a second visual system.
- [x] `#vocabulary` and `#vocabulary/lemma/<id>` survive reload/back/forward navigation.
- [x] Search/filter is server-paginated and does not load the full vocabulary into the DOM.
- [x] Editing a surface form/status changes the same lemma state returned by the API.
- [x] Ambiguous analysis can be corrected and locked.
- [x] All imported/provider text is safely rendered/escaped.
- [x] No vocabulary state is stored in localStorage.
- [x] The main dashboard shortcut works and unrelated layout remains unchanged.

### Deliberately postponed

- Full Reader interaction/history.
- Compact dashboard language widget.
- Rich definitions/translations unless manually entered fields are needed.
- Topics, goals, Anki, AI, cloze, listening, and grammar.

## Phase 4 — Reader vertical slice and trustworthy exposure tracking

**Status: COMPLETE (verified 2026-09-16).** See [`LANGUAGE_PHASE4_RESULTS.md`](./LANGUAGE_PHASE4_RESULTS.md) for the schema-v3, Reader, session/exposure, visual, regression, and database evidence.

### Outcome

The Reader is useful end to end: paste/import, analyze, read with status coloring, inspect/edit a word, see actual coverage, and record a real reading session/exposures/history.

### Work

- Add Reader library/import and text-detail hash routes.
- Render exact source text from token offsets; window/lazy-render long documents by sentence/paragraph.
- Map shared knowledge states to compact colors plus non-color indicators and a legend.
- Open the same lemma detail component used by Vocabulary.
- Add mark `LEARNING`/`KNOWN`/`IGNORED`/`EXCLUDED`, correct lemma, add note/context, and queue-for-Anki intent (intent only until Phase 6).
- Display token and unique-lemma coverage with raw counts and policy definition.
- Record active reading sessions conservatively, pause on hidden/inactive state, and submit idempotent sentence/lemma exposure batches.
- Store reading history and coverage-at-completion snapshots.
- Select useful real sentence contexts without duplicating sentence text unnecessarily.

### Likely files

- `js/language/views/reader.js` (new)
- `js/language/coverage.js`, `components/status-control.js`, `model.js`, `app.js` (expanded)
- `language.css` (Reader-specific styles)
- `language_learning/service.py`, `store.py`, `coverage.py`, `migrations.py` (expanded)
- `server.py` (thin session/exposure route branches)
- `tests/language-coverage.test.js`, `language-page.test.js`, `test_language_services.py`, `test_language_api.py` (expanded)

### Verification

- Render fixtures containing punctuation, repeated forms, ambiguity, and unsafe HTML-like text.
- Simulate session start/pause/resume/complete and network retry.
- Verify a repeated word creates the correct occurrence count under one shared lemma.
- Verify import/generation preview alone produces zero exposure.
- Test large-document windowing with a synthetic text, not personal data.

### Acceptance criteria

- [x] Original whitespace/punctuation is preserved and unsafe text cannot inject markup.
- [x] `jobb`, `jobben`, `jobber`, and `jobbene` share color/state through lemma `jobb`.
- [x] Clicking any linked form opens the same lemma detail.
- [x] Coverage changes immediately and consistently after a knowledge edit.
- [x] Reading a sentence records exposures by shared lemma and source type exactly once per idempotent event.
- [x] Hidden-tab/wall-clock time is not counted as active reading time.
- [x] Reading history can reopen the same text and shows the stored completion coverage.
- [x] Long text does not create one DOM node for the entire vocabulary history or freeze normal page navigation.

### Deliberately postponed

- Automatic definitions/translations if no provider has been selected.
- Anki card creation.
- Generated texts, cloze scoring, listening exposures, and grammar overlays.

## Phase 5 — Topics, statistics, goals, overview, and compact dashboard widget

Phase status: **COMPLETE (2026-09-16)**. Classifier/statistics/goal/plan policies, schema v4, visual checks, and regression evidence are recorded in [`LANGUAGE_PHASE5_RESULTS.md`](./LANGUAGE_PHASE5_RESULTS.md).

### Outcome

The Language Overview becomes a dense, truthful personal analytics dashboard built from Reader/knowledge events. Topics and goals are backed by real data, and the main dashboard gains a compact opt-in summary card.

### Work

- Add topic CRUD with weighted manual lemma membership and source-aware persistence; defer actual imports until a verified dataset/review flow exists.
- Add goal definitions and progress derived from sessions/activity events.
- Implement statistics queries and pure series builders for vocabulary over time, state transitions, exposures, study time, streaks, reading coverage, frequency bands, and topic mastery.
- Define/version passive, active, mastered, weak, recent, and underexposed classifiers.
- Add `LearningPlanService` for today's actions and “words to recycle”.
- Build Overview, Topics, Statistics, and Goals views with accessible compact SVG/DOM charts.
- Return a small summary endpoint for the dashboard widget.
- Add the widget card/module/loader/settings/order registry entries using one stable `data-widget="language-learning"` key.
- Provide an Anki status placeholder only as “not configured/not implemented”; do not invent review numbers.

### Likely files

- `language_learning/statistics.py`, `learning_plan.py` (new)
- `language_learning/store.py`, `service.py`, `migrations.py` (expanded)
- `js/language/charts.js` (new)
- `js/language/views/overview.js`, `statistics.js`, `goals.js`, `topics.js` (new/expanded)
- `js/widget-language-learning.js` (new)
- `index.html`, `styles.css`, `js/dashboard-widget-loader.js`, `js/dashboard-settings.js`, `data/widget-order.json` (small registry/markup/style edits)
- `tests/language-statistics.test.js`, `widget-language-learning.test.js`, `test_language_statistics.py`, `test_language_api.py` (new/expanded)

### Verification

- Hand-calculate synthetic time series, weekly boundaries, streaks, goal progress, and weighted topic mastery; verify that unavailable ranked-frequency bands remain undisplayed.
- Test Europe/Warsaw DST/week-start edges.
- Test missing frequency/topic data and show denominator quality.
- Run dashboard settings/widget focused tests and build.
- Manually verify 2/3/4-column dashboard layouts and compact card overflow.

### Acceptance criteria

- [x] Overview numbers reconcile with Vocabulary and Reader facts.
- [x] Vocabulary-over-time comes from transition events, not today's state applied retroactively.
- [x] Exact Top 500/1000/2000/5000 coverage is withheld with a sourced `NOT_CONFIGURED` explanation because no ranked dataset is selected; Zipf is never presented as rank.
- [x] Topic mastery changes only when linked vocabulary knowledge/weights change and always discloses its partial user-mapped denominator.
- [x] Goal progress comes from qualifying study events and uses the configured local week.
- [x] Today's plan is deterministic for the same snapshot/rule version.
- [x] The widget can be hidden/reordered/resized through existing dashboard settings.
- [x] Hiding the widget prevents its module/API load in the normal lazy-loader flow.

### Deliberately postponed

- Anki-driven weak/due data.
- AI generation.
- Cloze/listening/grammar metrics.
- Materialized statistics tables unless profiling proves they are necessary.

## Phase 6 — Safe AnkiConnect linking and synchronization

**Status: COMPLETE (verified 2026-09-16).** See [`LANGUAGE_PHASE6_RESULTS.md`](./LANGUAGE_PHASE6_RESULTS.md) for schema-v5, adapter/security, preview/idempotency/conflict, UI, regression, visual, and database evidence.

### Outcome

The user can configure Anki, preview card creation/update, link vocabulary to existing notes without duplicates, create cards from real Reader contexts, and pull card/review metadata without replacing Anki scheduling.

### Work

- Add backend `AnkiAdapter` with fixed/allowlisted local base URL, timeouts, optional server-side API key, and capability probing.
- Add note-link, card-snapshot, sync-run, hash/conflict, and Anki-intent migrations.
- Add settings/status, dry-run preview, explicit commit, pull-metadata, and sync-history endpoints.
- Configure deck/model/field mappings and a stable dashboard lemma field/tag.
- Resolve local link first, then stable Anki ID/tag search, then duplicate preflight.
- Create notes from selected lemma plus a real pinned sentence/context and source attribution.
- Pull card scheduling metadata; import review aggregates only if supported and contract-tested.
- Feed review evidence through `LanguageService`; never let the adapter edit knowledge directly.
- Add Reviews/Anki panels and overview/widget status.

### Likely files

- `language_learning/providers/anki.py`, `language_learning/anki_sync.py` (new)
- `language_learning/store.py`, `service.py`, `migrations.py`, `jobs.py` (expanded)
- `js/language/views/settings.js`, `reviews.js`, `vocabulary.js`, `overview.js` (expanded/new)
- `.env.example` (documented Anki setting names; no secret values)
- `server.py` (thin Anki route branches)
- `tests/test_language_providers.py`, `test_language_anki.py`, `test_language_api.py`, `language-page.test.js` (new/expanded)

### Verification

- Use a fake Anki server/adapter for offline, version mismatch, model/deck missing, duplicate, stale note ID, conflict, partial batch, and success responses.
- Run a manual smoke test against a disposable Anki profile/deck only after automated tests pass.
- Repeat the same committed sync twice.
- Modify both local projection and fake Anki fields and verify conflict behavior.

### Acceptance criteria

- [x] No note is created during status, discovery, or dry-run.
- [x] Repeating sync does not duplicate a note for the same lemma/template purpose.
- [x] Existing linked notes are found by stable ID/tag/field, not visible front text alone.
- [x] A conflict is shown and neither side is overwritten silently.
- [x] Anki unavailable leaves Reader/Vocabulary/Overview usable.
- [x] The dashboard never writes scheduling values or automatically runs AnkiWeb sync.
- [x] Created notes contain a real context linked to the shared lemma.
- [x] Pulled Anki evidence is attributable in knowledge history.

### Deliberately postponed

- Automatic periodic push/pull.
- Destructive note/card cleanup.
- Custom Anki scheduling or answering cards from the dashboard.
- Media/audio attachment unless separately designed and tested.

## Phase 7 — Adaptive generation with a manual provider workflow

### Outcome

The deterministic adaptive engine can choose target vocabulary, build a versioned prompt, accept a manually pasted structured response, analyze actual coverage, and save only validated text. This is useful without committing to a paid/provider API.

### Work

- Add generation request/candidate migrations and durable candidate status history on the existing single worker.
- Implement deterministic frontier scoring: explicit targets, weak Anki words, recent words, underexposed words, and selected topic vocabulary.
- Convert target length and desired coverage into a lexical budget/repetition plan.
- Freeze the knowledge/target/rule snapshot and content fingerprint.
- Build a provider-neutral structured prompt and JSON schema.
- Implement the manual provider: copy prompt, paste response, validate, analyze, show coverage and unsuitable words, then accept/reject.
- Save accepted candidates as normal generated `TextDocument` rows with provenance.
- Add Generate UI and quick actions from Overview/Reader.
- Keep generation and reading events strictly separate.

### Likely files

- `language_learning/generation.py`, `schemas.py` (new/expanded)
- `language_learning/providers/generation.py` (new manual/fake providers)
- `language_learning/store.py`, `service.py`, `migrations.py`, `jobs.py`, `learning_plan.py` (expanded)
- `js/language/views/generate.js`, `overview.js` (new/expanded)
- `tests/test_language_generation.py`, `test_language_jobs.py`, `language-generation.test.js`, `language-page.test.js` (new/expanded)

### Verification

- Test target ranking and unknown-token budgets against hand-built snapshots.
- Import valid, malformed, oversized, wrong-profile, and stale-snapshot responses.
- Test 99/97/95/90% targets on short and long fixtures.
- Verify accepting a candidate produces a text but zero exposures.

### Acceptance criteria

- [x] The same input snapshot/rules produce the same target selection and prompt fingerprint.
- [x] Selected weak/recent/underexposed words are visible before generation.
- [x] Pasted model output is schema-validated and analyzed by the canonical Bokmål adapter.
- [x] Requested and actual token/lemma coverage plus raw unknown/ambiguous words are shown.
- [x] Out-of-tolerance text cannot be labeled as meeting the target.
- [x] Accepted text enters the normal Reader and gains exposures only when studied.
- [x] Personal notes/unrelated history are absent from the generated prompt by default.

### Deliberately postponed

- Direct AI API calls and automatic revision.
- Multiple candidates in parallel.
- AI definitions, grammar explanations, and cloze generation.
- Cost forecasting beyond stored manual/provider metadata.

## Phase 7.5A — Reference source audit and intelligent lexicon architecture

Phase status: **COMPLETE (2026-09-16)**. Source evidence, schema design, measured samples and acceptance results are recorded in [`LANGUAGE_PHASE7_5A_RESULTS.md`](./LANGUAGE_PHASE7_5A_RESULTS.md), [`LANGUAGE_REFERENCE_ARCHITECTURE.md`](./LANGUAGE_REFERENCE_ARCHITECTURE.md), [`LANGUAGE_REFERENCE_SOURCES.md`](./LANGUAGE_REFERENCE_SOURCES.md), and [`LANGUAGE_REFERENCE_INGESTION_PLAN.md`](./LANGUAGE_REFERENCE_INGESTION_PLAN.md).

### Outcome

The dashboard has a licensed, source-aware plan for a separate rebuildable Bokmål reference lexicon and a tiny tested schema-v1 spike. User `VocabularyLemma` identity and main schema v6 remain unchanged. No production corpus, normal API/UI integration, user-vocabulary import or knowledge mutation occurs.

### Acceptance boundary

- Keep reference facts in a separately configured SQLite database with independent migrations/source/import provenance.
- Preserve raw/source-specific frequency, rank and CEFR evidence; version every derived metric.
- Represent phrases, idioms and collocations as true reference units.
- Resolve user lemmas through inspectable `MATCHED`/`AMBIGUOUS`/`UNMATCHED` rules.
- Commit code/manifests/tiny fixtures only; ignore raw corpora and generated databases.
- Do not modify Phase 7 semantic versions or runtime behavior.

## Phase 7.5B — Reproducible reference ingestion

Phase status: **COMPLETE (2026-09-16)**. Frozen artifacts, measured ingestion/mapping/storage results, deterministic rebuild evidence, performance, isolation, and regression totals are recorded in [`LANGUAGE_PHASE7_5B_RESULTS.md`](./LANGUAGE_PHASE7_5B_RESULTS.md), with operations and metric policies in [`LANGUAGE_REFERENCE_IMPORT_OPERATIONS.md`](./LANGUAGE_REFERENCE_IMPORT_OPERATIONS.md) and [`LANGUAGE_REFERENCE_DERIVED_METRICS.md`](./LANGUAGE_REFERENCE_DERIVED_METRICS.md).

### Outcome

The independent Bokmål reference database is reproducibly built from checksumed accepted sources using bounded streaming importers: Norsk ordbank, KELLY rank evidence, the CLARINO surface-frequency list, official idioms and Bokmål unigram evidence. Production CEFR and domain evidence remain correctly empty.

### Acceptance boundary

- Follow the exact tiered plan in [`LANGUAGE_REFERENCE_INGESTION_PLAN.md`](./LANGUAGE_REFERENCE_INGESTION_PLAN.md).
- Rebuild the same source snapshot deterministically from an empty configured path.
- Publish source/import counts, rejects, mapping coverage, integrity and query benchmarks.
- Do not ingest the 26.6 GB n-gram archive or NBdigital without separate explicit Tier-3 authorization.
- Do not expose reference data to Reader/Generate or mutate the user DB.

## Phase 9A — Cloze Fast Track MVP (intentionally pulled forward)

Phase status: **COMPLETE (2026-09-16)**. Source, schema, coverage, behavior, verification, and limitations are recorded in [`LANGUAGE_PHASE9A_CLOZE_MVP_RESULTS.md`](./LANGUAGE_PHASE9A_CLOZE_MVP_RESULTS.md).

### Outcome

The dedicated `#cloze` route provides deterministic 10/20/50-question Norwegian multiple-choice practice. Five versioned Fast Track bands use KELLY `SOURCE_LEARNER_RANK`; licensed Tatoeba Bokmål sentences and exact Ordbank form mappings remain in the read-only reference domain. User-local sessions, attempts, compact snapshots, evidence, and bad-item suppressions are additive main-schema-v7 data. Reviews keeps Anki scheduling distinct from dashboard Cloze practice.

### Acceptance boundary

- This checkpoint is a narrow usability slice, not completion of full Phase 9.
- Runtime reference access is limited to indexed Cloze target/sentence/form queries; Reader, Vocabulary, and Generate receive no broad Phase 7.5C enrichment.
- Anki remains the only SRS. Cloze adds no due dates and does not auto-change canonical knowledge status or scores.
- No direct AI provider, generated sentence bank, listening/TTS, grammar mining, idiom curriculum, or Tier-3 ingestion is included.
- The dedicated Tatoeba CC0 export is imported first. Its measured five rows are retained; the official broader CC BY 2.0 FR export is added only with per-item source/license attribution because CC0 alone cannot provide a ten-item session.
- At this historical checkpoint, full Phase 9 was **NOT COMPLETE**; it is now complete in the dedicated Phase 9 section below.

## Phase 7.5C — Read-only reference integration

Phase status: **COMPLETE** (verified 2026-09-17). See [`LANGUAGE_PHASE7_5C_RESULTS.md`](./LANGUAGE_PHASE7_5C_RESULTS.md) for the read-only service, payload ownership, expression detector, generator-v2, performance, regression, browser, and database evidence.

### Outcome

Reader, Vocabulary, and Generate gain source-aware reference intelligence over the verified Phase 7.5B database while user knowledge, coverage, and exposure semantics remain unchanged. The integration is read-only with respect to user learning truth.

### Work

- Add a read-only `ReferenceLexiconService` with bounded lookup methods and a safe health/version surface that discloses source/import versions and logical fingerprints but no filesystem paths.
- Return explicit sibling `user`, `reference`, and `resolution` payloads; never merge reference facts into `VocabularyLemma` or `LemmaKnowledge` fields.
- Resolve lemmas/forms through the inspectable resolver and expose `MATCHED`, `AMBIGUOUS`, and `UNMATCHED` states with match basis, candidates, provenance, source version, and unresolved evidence.
- Show source-specific frequency and learner-rank observations without blending KELLY, CLARINO, unigram, or `wordfreq` into a universal rank.
- Annotate official idioms and detect MWE occurrences with a versioned longest-match policy, exact token spans, retained overlaps/ambiguity, and source provenance; authoritative detection must not use raw substring matching.
- Add reference detail to Reader and Vocabulary, and add independent frequency/rank/idiom/MWE profiles to analyzed texts without changing canonical coverage.
- Introduce `language-generation-targets/v2`, `language-generation-context/v2`, and `language-generation-prompt/v2` only for reference-aware generation; freeze the reference DB/source fingerprint in each request.
- Keep Tier-3 `n=2..6` absent unless it receives separate authorization; missing collocation evidence must degrade to an explicit unavailable state.

### Likely files

- `language_learning/reference_core/service.py`, resolver/query helpers, and reference models (new/expanded)
- `language_learning/service.py`, `generation.py`, `schemas.py` (payload composition/versioned context only)
- `server.py` (thin read-only reference routes)
- `js/language/views/reader.js`, `vocabulary.js`, `generate.js`, shared lemma detail (expanded)
- focused reference-service, payload-separation, MWE-span, generation-version, API, and UI tests

### Verification

- Exercise matched, ambiguous, unmatched, same-spelling/different-POS, idiom, overlapping MWE, longest-match, and missing-reference-DB fixtures.
- Prove that lookup, import, render, reopen, and generator-context construction create no knowledge event, exposure, topic membership, phrase mastery, or user vocabulary row.
- Verify every displayed reference metric and annotation carries source/method/version provenance and that paths remain private.
- Compare Phase 7 coverage and accepted-generation semantics before and after enabling reference enrichment.

### Acceptance criteria

- [x] `ReferenceLexiconService` is read-only, bounded, independently versioned, and unavailable without breaking Reader/Vocabulary/Generate.
- [x] Combined responses visibly separate user evidence, reference facts, and resolution status.
- [x] Frequency/rank values retain their exact source/metric identity; KELLY remains learner rank and production CEFR remains empty.
- [x] Idiom/MWE matches return exact spans, ambiguity, detector version, and provenance using the documented longest-match policy.
- [x] Reader, Vocabulary, and Generate expose useful reference intelligence without changing user coverage, knowledge, exposures, or IDs.
- [x] Generator v1 history is preserved; reference-aware requests use v2 contracts plus a frozen reference fingerprint.
- [x] No phrase knowledge/mastery store is introduced.

### Deliberately postponed

- Full Tier-3 `n=2..6` ingestion and derived collocation ranking.
- Dictionary senses, translations, and learner-facing definitions.
- Phrase mastery or a generalized user lexical-identity migration.
- Automatic domain-to-Topic assignment or any reference-driven knowledge mutation.

## Phase 7.6 — Evidence-driven gamification, completion, and campaigns

Phase status: **COMPLETE**. Implementation evidence: [`LANGUAGE_PHASE7_6_RESULTS.md`](./LANGUAGE_PHASE7_6_RESULTS.md).

### Outcome

A deterministic gamification overlay makes real study motivating and completion-oriented without redefining language truth. XP, levels, achievements, collections, quests, missions, milestones, and campaigns derive from canonical learning evidence and can never mutate it.

### Work

- Treat `VocabularyLemma`, `LemmaKnowledge`, `KnowledgeEvent`, `StudySession`, `ExposureEvent`, text progress, `ClozeAttempt`, Anki evidence, Goals, Topics, LearningPlan, Fast Track evidence, reference evidence, and later Listening/Grammar activity as canonical inputs. `+10 XP` does not mean `KNOWN`; an achievement cannot set `MASTERED`; collection completion cannot alter Topic mastery; and a Fast Track badge cannot rewrite Cloze attempts.
- Add a backend `GamificationService` (or equivalent domain service) that derives reward-eligible events, idempotent XP awards, lifetime XP, account level, achievement progress/unlocks, collection completion, daily quests, weekly missions, campaign progress, Overview summary, and compact-widget summary.
- Define a versioned XP policy such as `language.gamification-xp/v1`. Eligible sources may include real Reader activity/completion, Cloze activity and difficult/recycled successes, defensible Anki evidence, goal completion, and meaningful milestones. Never reward page opens, refresh, analysis/import, reference import, unstudied generated text, or arbitrary button clicks.
- Store a durable XP ledger keyed by source event/entity and reward rule/version, with amount and timestamp. Retrying one underlying event must not award twice.
- Add bounded/diminishing anti-farming rules for trivial repetition, replay, reveals, and duplicate submissions. Mistakes never create negative XP.
- Derive a global label such as `Norwegian Level 18` from lifetime XP with a versioned curve: frequent early levels, gradually slower progression, no extreme exponential wall, and no drifting stored level when it can be derived. Account level is never named A1-C2.
- Define deterministic, versioned achievements across Vocabulary, Reader, Cloze, Anki, Fast Track, Topics, consistency, idioms/MWEs, generated reading, campaigns, and later module categories. Preserve original unlock time and rule version; later rule changes must not rewrite history.
- Build an achievement gallery with Unlocked, Locked, recent unlocks, category completion, and explainable overall visible completion. Secret achievements may not prevent visible 100% completion.
- Define versioned collections such as Fast Track 1-5, Everyday, Work, Warehouse, Construction, Safety, Housing, Transport, Shopping, Bureaucracy, Healthcare, Football, Reader milestones, idioms, and later MWE/Grammar/Listening collections.
- Require every collection response to disclose denominator source/version, mapped items, unresolved items, excluded items, and completion-rule version. Existing Topics remain labeled partial/user-mapped.
- Consume existing Phase 9A KELLY ranks without redefining them. Versioned Fast Track gamification states may include `ENCOUNTERED`, `PRACTICED`, and `RELIABLE`; one correct answer is never mastery.
- Support optional Bronze/Silver/Gold/Complete collection milestones as rewards only. Reference idioms/MWEs may be `DISCOVERED` or `ENCOUNTERED` from real occurrence evidence, never `MASTERED` before a phrase-learning model exists.
- Produce approximately three concise deterministic daily quests from LearningPlan, Goals, weak/recycle vocabulary, unfinished Reader texts, Cloze mistakes, and real Anki due evidence. Same date, snapshot, and rules produce the same quests.
- Build weekly missions over existing Goals rather than creating a competing goal system. Reuse canonical streak semantics; expose current/best streak and 7/30-day study days without removing earned progress after a missed day.
- Keep Cloze combos session-local: a wrong answer may reset the combo, but no permanent progress is lost and combo state is not knowledge evidence.
- Add checkpoint challenges whose learning result remains distinct from their badge/reward.
- Add generic, user-defined `CampaignDefinition` concepts (name, target date, enabled state, focus dimensions, milestones). A `Norway Spring 2027` campaign is an example, not a hard-coded domain singleton.
- Make a Norway campaign answer what practical capabilities remain across Everyday, Work, Warehouse, Construction, Safety, Housing, Transport, Reading, and Listening, rather than reducing readiness to XP.
- Explicitly prohibit loot boxes, gambling, paid randomized rewards, negative XP, loss of earned level, shame mechanics, artificial scarcity, and fake urgency/deadline pressure.

### Likely files

- `language_learning/gamification.py`, policy definitions, migrations/store/service/statistics/learning-plan extensions
- thin `/api/language/*` gamification, achievement, collection, quest, mission, and campaign routes
- `js/language/views/overview.js`, achievements/collections/campaign views, and compact widget integration
- focused ledger-idempotency, level-curve, achievement-history, denominator, quest/mission, campaign, anti-farming, API, and UI tests

### Verification

- Replay every eligible command, HTTP retry, and duplicate client submission and prove one ledger award per source/rule version.
- Hand-calculate XP, levels, achievement progress/history, collection denominators, Fast Track states, quests, missions, streak reuse, and campaign dimensions from synthetic canonical events.
- Prove reward calculations never update `LemmaKnowledge`, Topics, Cloze attempts, Anki scheduling, goals, or reference rows.
- Test policy upgrades against historical unlock timestamps and ledger provenance.
- Exercise farming attempts, reveal/replay behavior, missing providers/data, inaccessible collections, and visible 100% completion semantics.

### Acceptance criteria

- [x] Gamification is derived from canonical facts through deterministic, versioned backend rules; frontend components contain no reward truth.
- [x] XP awards are durable, attributable, idempotent, non-negative, and protected by bounded anti-farming rules.
- [x] Account level is derived from lifetime XP and is visibly distinct from CEFR/proficiency.
- [x] Achievements unlock idempotently, preserve historical time/rule version, and expose explainable progress.
- [x] Every completion percentage has a versioned, inspectable denominator with mapped/unresolved/excluded counts.
- [x] Fast Track badges consume existing KELLY/Cloze evidence without changing KELLY rank, attempts, or vocabulary knowledge.
- [x] Daily quests are small and deterministic; weekly missions extend Goals; canonical streak semantics are reused.
- [x] Campaigns are generic and readiness remains multidimensional.
- [x] No dark-pattern mechanic or permanent penalty exists.

### Deliberately postponed

- Paid/social/competitive mechanics, leaderboards, random rewards, or scarcity systems.
- Grammar, listening, and assessment achievements until those modules produce canonical evidence.
- Phrase mastery and MWE completion beyond discovered/encountered evidence.
- A single synthetic Norway-readiness score.

## Phase 7.7 — Dictionary, meanings, translations, and personal phrasebook

Phase status: **COMPLETE**. Source decisions and verification are recorded in [`LANGUAGE_DICTIONARY_SOURCES.md`](./LANGUAGE_DICTIONARY_SOURCES.md) and [`LANGUAGE_PHASE7_7_RESULTS.md`](./LANGUAGE_PHASE7_7_RESULTS.md).

### Outcome

Learners can understand words and save useful expressions through legally usable, source-attributed dictionary senses and translations while user notes/knowledge remain separate from reference facts.

### Work

- Begin implementation with a source/license audit; do not select a provider in this planning phase and never scrape restricted/commercial dictionary bodies.
- Accept only sources that permit the intended local storage/cache/display and attribution, cover Norwegian Bokmål, and expose version/retrieval metadata and stable sense IDs where available.
- Implement `LemmaSense` and `LemmaTranslation` (or equivalent architecture concepts) with sense order, POS, definition, translation locale/value, source/version, supplied confidence, user-edited flag, and legally available usage/register notes.
- Prioritize Polish and English translation support as source availability allows. Preserve machine/user translations as explicitly different evidence; do not promote KELLY glosses into authoritative senses.
- Compose lexical detail as explicit USER data (knowledge, scores, exposures, Anki, notes) beside REFERENCE data (forms, morphology, frequency/ranks, senses, translations, idioms/MWEs, provenance).
- Add lightweight `Save expression` phrasebook entries from Reader, Tatoeba Cloze, generated texts, and future transcripts. Retain exact phrase, source context/provenance, optional note/translation, and target lemma/reference-unit links.
- Keep phrasebook saving a bookmark/collection event. It creates no phrase mastery, knowledge promotion, exposure, or automatic Anki card.

### Likely files

- dictionary/provider audit documentation and source manifests
- `language_learning/providers/dictionary.py`, lexical detail/phrasebook services, migrations/store/schemas
- thin lexical-detail and phrasebook API routes
- shared Reader/Vocabulary/Cloze/Generate detail and save-expression UI
- provider-contract, provenance, user-edit preservation, phrasebook-idempotency, API, and UI tests

### Verification

- Test multiple senses/POS, source versions, missing translations, Polish/English ordering, user edits, unsafe provider text, provider outage, and source refresh.
- Prove a provider refresh cannot overwrite user-edited content and that KELLY glosses remain labeled raw evidence.
- Save the same expression from each supported source, reopen it with exact context/provenance, and prove saving creates no mastery or exposure.
- Review storage/display/attribution behavior against the selected source licenses before import or activation.

### Acceptance criteria

- [x] A completed source/license audit authorizes every stored/displayed dictionary body and its attribution requirements.
- [x] Senses/translations are ordered, source/version attributed, safely rendered, and preserve user edits.
- [x] USER and REFERENCE ownership is explicit in service payloads and UI.
- [x] Polish/English values disclose provider, confidence/method, and machine/user status where relevant.
- [x] KELLY glosses are never presented as authoritative dictionary senses.
- [x] Saved expressions preserve exact source context/provenance and optional learner annotations.
- [x] Saving an expression alone changes no knowledge/mastery state.

### Deliberately postponed

- Selecting a dictionary/translation provider before the license audit.
- Automatic phrase mastery or a parallel phrase SRS.
- Bulk scraping, redistribution without permission, or silent machine-translation truth.
- Automatic Anki/listening/generated exercises from phrasebook entries; later phases may consume them explicitly.

## Phase 7.8 — Curated vocabulary curricula and Norway practical packs

Phase status: **COMPLETE** (2026-09-17). Exact source decisions and evidence are in [`LANGUAGE_CURRICULUM_SOURCES.md`](./LANGUAGE_CURRICULUM_SOURCES.md) and [`LANGUAGE_PHASE7_8_RESULTS.md`](./LANGUAGE_PHASE7_8_RESULTS.md).

### Outcome

Versioned, reviewed vocabulary packs provide trustworthy denominators for practical curricula and Norway preparation instead of treating partial user Topics or fabricated lists as complete domains.

### Work

- Define a pack contract with stable pack ID, version, language, name, description, source/provenance, included lexical units, optional weights, review state, external license, and mapped/unresolved counts.
- Audit and curate practical packs such as Norway Essentials, Everyday Norwegian, Work Basics, Warehouse, Construction, Tools, Workplace Safety, Housing, Transport, Shopping, Healthcare, Public Services, Tax/Bureaucracy, Job Interview, and Football.
- Permit verified published lists, human-curated dashboard packs, reviewed imports, and explicitly labeled generated suggestions awaiting human review. Never let an LLM silently invent an authoritative pack.
- Resolve pack units to canonical user/reference identities through inspectable mappings; retain unresolved/excluded rows rather than shrinking denominators invisibly.
- Feed the Phase 7.6 collection system with real versioned denominators, e.g. `142 / 180 reliable`, while keeping pack completion distinct from Topic mastery and CEFR.
- Let generic Norway campaigns select pack dimensions such as Work Basics, Safety, Warehouse, and Housing without hard-coding one campaign or one composite score.

### Likely files

- reviewed pack manifests/data and source/license/review documentation
- `language_learning/curricula.py`, mapping/import validation, store/service/schema extensions
- thin pack/curriculum API routes and Topics/Collections/Campaign UI integration
- manifest, mapping, denominator, review-state, provenance, API, and UI tests

### Verification

- Rebuild each accepted pack from its reviewed manifest and compare stable IDs/version/content fingerprints.
- Test one-to-one, ambiguous, unresolved, excluded, weighted, and source-version-change mappings.
- Hand-calculate pack completion and verify the displayed numerator/denominator and reliability rule.
- Prove generated suggestions remain unreviewed and absent from authoritative completion until explicitly approved.

### Acceptance criteria

- [x] Every active pack has a stable/versioned contract, source/license/review provenance, and inspectable lexical membership.
- [x] Mapped, unresolved, and excluded counts are visible and denominator changes require a new pack version.
- [x] No LLM-generated membership is authoritative without review.
- [x] Pack completion derives from canonical evidence and cannot mutate knowledge.
- [x] Topic mastery, pack completion, gamification tiers, and CEFR remain distinct concepts.
- [x] Norway campaigns can compose practical packs as separate readiness dimensions.

### Deliberately postponed

- A universal Norway-readiness percentage without a transparent versioned weighting decision.
- Automatic pack generation/publication by AI.
- Phrase/MWE mastery curricula remain outside the active roadmap and require separate authorization.
- Broad community sharing, marketplace, or social comparison.

## Phase 8 — Configured AI provider and closed automatic revision loop

Phase status: **COMPLETE (verified 2026-09-17)**. Exact provider/API evidence, schema v11 migration, FREE_ONLY and retry policies, automatic-loop/TTS contracts, measurements, tests and limitations are recorded in [`LANGUAGE_PHASE8_RESULTS.md`](./LANGUAGE_PHASE8_RESULTS.md); setup is in [`LANGUAGE_PHASE8_SETUP.md`](./LANGUAGE_PHASE8_SETUP.md).

### Outcome

A configured backend AI provider can generate and revise text asynchronously. The system automatically measures coverage after every attempt and either accepts an in-tolerance candidate or returns the best candidate with an honest warning.

### Work

- Finalize the `GenerationProvider` interface and add one configured provider plus deterministic fake.
- Keep credentials and allowed base URL server-side; expose redacted health only.
- Add request/response size limits, timeouts, retry classes, cancellation, provenance, prompt/model versions, and optional usage/cost fields.
- Run generate → validate → analyze → coverage → bounded revise in a persisted job.
- Allow the provider workflow to consume frozen Phase 7.5C reference frequency/rank, source-attributed dictionary context, and reviewed Phase 7.8 curriculum targets through the versioned v2 context contract.
- Revision prompts include measured unknown/ambiguous items and safe replacement candidates from the frozen known vocabulary.
- Select the best candidate deterministically if no attempt meets tolerance.
- Add regeneration/revision controls and attempt comparison UI.
- Re-check the knowledge snapshot when opening an old candidate; label a current re-score separately from generation-time coverage.
- Keep provider output as a candidate, never lexical/reference truth. Analyze every actual generated text through the canonical analyzer; only canonical `CoverageService` output determines measured coverage.

### Likely files

- `language_learning/providers/generation.py`, `generation.py`, `jobs.py` (expanded)
- `language_learning/schemas.py`, `coverage.py`, `service.py` (expanded)
- `server.py`, `.env.example` (thin routes/config names)
- `js/language/views/generate.js`, `api.js` (expanded)
- `tests/test_language_generation.py`, `test_language_providers.py`, `test_language_jobs.py`, `language-generation.test.js` (expanded)

### Verification

- Fake-provider sequences: first-pass success, malformed then success, two coverage misses then success, all misses, timeout, refusal, retryable error, terminal error, cancellation.
- Assert the analyzer runs after every attempt.
- Assert secrets never appear in health/errors/stored client payloads.
- Compare generation-time frozen coverage with a later current re-score.

### Acceptance criteria

- [x] No candidate is accepted based on prompt/LLM self-report alone.
- [x] Every attempt stores provider/model/prompt/analyzer/coverage versions.
- [x] Revision is bounded and cannot loop indefinitely or silently spend unbounded quota.
- [x] A successful revision meets the configured tolerance using actual coverage.
- [x] Exhausted attempts return the best analyzed text with a warning and exact miss.
- [x] Provider outage does not affect Reader/Vocabulary or manual generation workflow.
- [x] Generated content is escaped, size-limited, and never mutates knowledge automatically.
- [x] Reference/dictionary/curriculum inputs preserve source/version fingerprints and provider output cannot create senses, pack membership, or knowledge facts.

### Deliberately postponed

- Automatic generation schedules.
- Sending full personal contexts/history.
- AI-generated grammar curriculum or pronunciation evaluation.
- Provider-specific UI outside generic health/model selection.

## Phase 9 — Reviews and Cloze from shared contexts

Phase status: **COMPLETE (2026-09-17)**. Phase 9A above remains the intentionally pulled-forward Fast Track MVP; full Phase 9 extends it with shared-context Review and Curriculum practice. Exact architecture and evidence are in [`LANGUAGE_PHASE9_RESULTS.md`](./LANGUAGE_PHASE9_RESULTS.md).

### Outcome

The already-complete Phase 9A Fast Track remains intact while full Reviews and Cloze deepen practice through shared Reader, phrasebook, curriculum, and optional generated contexts. Reviews orchestrates evidence-backed work without becoming another scheduler.

### Work

- Preserve Phase 9A routes, KELLY Fast Track definitions, Tatoeba/reference imports, A/B/C/D outcome semantics, persisted sessions/attempts/suppressions, and current evidence contracts; do not rebuild or rerun the MVP.
- Extend the existing Cloze service with deterministic candidate ranking from learning/weak/underexposed vocabulary, goal/curriculum gaps, phrasebook targets, and prior mistakes.
- Add Reader-context Cloze using real analyzed sentences, exact target spans, shared lemma IDs, and source provenance; improve sentence selection without silently replacing historical snapshots.
- Improve distractor quality with versioned morphology, frequency, lexical, and contextual rules while keeping low-quality/ambiguous items skippable and reportable.
- Define accepted-answer normalization for capitalization, punctuation, inflection, and Norwegian diacritics; preserve exact expected forms and rule versions in snapshots.
- Reuse shared contexts across Reader, Cloze, Anki projections, and later Listening without duplicating ownership.
- Deepen Reviews as an orchestrator: Anki due summary, dashboard Cloze recycling, rereading, future listening, goal/campaign gaps, and LearningPlan suggestions remain visibly distinct.
- Feed canonical attempts and goal progress idempotently; add no dashboard SRS due dates and never equate one success with mastery.
- Optionally create generated contexts behind an explicit switch, canonical post-analysis, source labeling, bounded validation, and provider-failure fallback.

### Likely files

- `language_learning/cloze.py`, `store.py`, `service.py`, `learning_plan.py` (expanded; migrations only if new durable facts require them)
- `js/language/views/cloze.js`, `reviews.js` (new/expanded)
- `language.css` (exercise states)
- `tests/test_language_cloze.py`, `language-cloze.test.js`, `test_language_services.py`, `test_language_api.py` (new/expanded)

### Verification

- Hand-built sentences with repeated words, inflection, punctuation, capitalization, and ambiguity.
- Correct/incorrect/reveal/skip/retry/idempotency tests.
- Regression-test all Phase 9A Fast Track routes/history before and after the full-Phase additions; do not rerun reference ingestion.
- Verify evidence updates the target lemma only under explicit versioned evidence policy and no independent SRS due date is created.
- Keyboard and screen-reader status smoke tests.

### Acceptance criteria

- [x] Every cloze exercise references one shared lemma and one exact source/generated sentence.
- [x] Existing Phase 9A sessions, attempts, KELLY tracks, Tatoeba attribution, and user suppressions remain valid and unchanged.
- [x] Inflected target forms do not create duplicate vocabulary records.
- [x] Answer normalization preserves Norwegian diacritic correctness under the documented policy.
- [x] Attempts append canonical evidence/history and derived goal progress exactly once without mutating recall scores.
- [x] Reveal/skip are not counted as correct.
- [x] Reviews clearly distinguishes Anki-scheduled work from dashboard recycling suggestions.
- [x] No Anki scheduling algorithm is reimplemented.
- [x] Reader-context, phrasebook, curriculum, and accepted-generated exercises disclose their source and quality policy.

### Deliberately postponed

- Full sentence production grading.
- Speech answers/pronunciation scoring.
- A separate dashboard spaced-repetition scheduler.
- Broad AI-generated exercise banks.

Phase 9A is **INTENTIONALLY PULLED FORWARD / COMPLETE** and is not part of the remaining execution work for this phase. Full Phase 9 completes and deepens the surrounding Reviews/Cloze system; it does not recreate Fast Track, the Tatoeba corpus, its routes, or its persisted attempts.

## Phase 9.5 — Mistake Intelligence and targeted remediation

Phase status: **COMPLETE (2026-09-18)**. Exact policies, architecture, measurements, regressions, browser evidence, and limitations are recorded in [`LANGUAGE_PHASE9_5_RESULTS.md`](./LANGUAGE_PHASE9_5_RESULTS.md).

### Outcome

Repeated difficulty becomes inspectable, deterministic remediation input across vocabulary and Cloze, with later extension points for grammar and listening. It does not become a competing scheduler or silently rewrite knowledge.

### Work

- Derive versioned mistake observations from Cloze incorrect/reveal outcomes, defensible Anki lapse aggregates, repeated weak vocabulary, and later grammar/listening failures.
- Add deterministic categories such as repeated vocabulary confusion, frequently failed target lemma, similar-word confusion, morphological confusion, and context-dependent confusion. Later grammar categories may include V2, subordinate negation, tense, and determiner/agreement failures.
- Support evidence-backed confusable pairs/groups (for example `kjenne/vite` or `tro/synes`) only after repeated qualifying evidence; two options appearing together once is insufficient.
- Preserve occurrence provenance, source module, rule version, severity/recency inputs, and resolution/recovery evidence.
- Produce bounded targeted-remediation suggestions for LearningPlan, Cloze recycling, Daily Quests, and the later Study Session Builder.
- Keep Anki as the SRS owner and Goals as target owner; Mistake Intelligence supplies diagnostic facts/priorities only.

### Likely files

- `language_learning/mistakes.py`, store/service/statistics/learning-plan extensions
- Cloze and Anki evidence adapters plus later Grammar/Listening adapters
- thin mistake-summary/remediation API routes
- Reviews/Overview/Statistics mistake panels
- clustering, threshold, provenance, idempotency, recovery, API, and UI tests

### Verification

- Hand-build repeated-failure, isolated-error, reveal, recovery, Anki-aggregate, morphology, context, and false-confusable fixtures.
- Verify one-off option co-occurrence cannot create a semantic confusion claim.
- Replay source events and prove clusters/remediation are deterministic and idempotent.
- Prove recommendations do not create due dates, mutate knowledge, or bypass LearningPlan/Goals ownership.

### Acceptance criteria

- [x] Every mistake cluster is explainable from attributable canonical evidence and a versioned rule.
- [x] One-off mistakes and distractor co-occurrence do not create false confusable relationships.
- [x] Recovery evidence can reduce current remediation priority without deleting history.
- [x] LearningPlan and Cloze consume one shared remediation output; Daily Quests were intentionally unchanged and the future Study Planner has not started.
- [x] No independent SRS, goal system, or knowledge mutation is introduced.
- [x] Missing Anki/Grammar/Listening evidence degrades to unavailable rather than being invented.

### Deliberately postponed

- Grammar-specific diagnoses until Phase 11 detectors exist.
- Listening-specific diagnoses until real listening assessment exists.
- Opaque ML clustering or semantic embeddings without inspectable evidence.
- Automatic knowledge demotion or punitive rewards.

## Phase 10 — Listening with browser TTS

Phase status: **COMPLETE (2026-09-18)**. Exact policies, coexistence with Phase 8 Google Cloud audio, schema/API changes, measurements, tests, browser evidence, and limitations are recorded in [`LANGUAGE_PHASE10_RESULTS.md`](./LANGUAGE_PHASE10_RESULTS.md).

### Outcome

Existing Reader/generated texts support read+listen and listening-only study with sentence replay, conservative activity tracking, and shared lemma exposures.

### Work

- Add a dependency-injected browser speech adapter with `nb-NO` voice discovery, rate, play/pause/cancel, and lifecycle events.
- Add Listening route/view and Reader controls.
- Highlight/replay the active sentence where browser events allow it.
- Record canonical active listening sessions and sentence/lemma exposure batches according to an explicit setting before any reward calculation.
- Add TTS capability/voice settings and graceful no-voice behavior.
- Store no audio in the database for browser speech.
- Extend Statistics, Goals, Campaign dimensions, and `GamificationService` from real listening activity. Listening XP must be derived second and never exist without a qualifying listening event.

### Likely files

- `js/language/audio/browser-speech.js` (new)
- `js/language/views/listening.js`, `reader.js`, `settings.js` (new/expanded)
- `language_learning/service.py`, `store.py`, `statistics.py` (activity support)
- `language.css`
- `tests/language-audio.test.js`, `language-page.test.js`, `test_language_services.py` (new/expanded)

### Verification

- Fake `speechSynthesis`/utterance tests for supported, missing voice, start/end/error/cancel, replay, and tab hide.
- Verify listening-only mode hides text without removing accessible controls/status.
- Verify canceled/failed utterances do not count full planned duration.
- Manual smoke test on each intended browser/device.

### Acceptance criteria

- [x] The app requests/selects a Bokmål-compatible voice and reports when none exists.
- [x] Read+listen, listening-only, pause/cancel, and sentence replay work without leaving overlapping utterances.
- [x] Listening time uses actual lifecycle/active time rather than text length alone.
- [x] Listening exposures reference the same text tokens/lemmas and use source `LISTENING`.
- [x] Listening statistics/goals update without altering Reader exposure counts.
- [x] Campaign and gamification progress derive idempotently from canonical listening activity and cannot fabricate listening time.
- [x] Reader remains usable when browser TTS is unsupported.

### Deliberately postponed

- Any new/replacement server TTS system. Phase 8 generated Reader and Phase 9A Cloze keep their existing shared Google Cloud `nb-NO` cached-MP3 path unchanged.
- Word-level timestamps when the browser cannot provide them reliably.
- Dictation, shadowing, microphone capture, and pronunciation scoring.

## Phase 10.5 — Authentic content inbox, audio, transcripts, and aligned listening

Phase status: **COMPLETE (2026-09-18)**. Exact implementation, rights decisions, alignment deferral, measurements, migrations, and verification are recorded in [`LANGUAGE_PHASE10_5_RESULTS.md`](./LANGUAGE_PHASE10_5_RESULTS.md), [`LANGUAGE_CONTENT_SOURCES.md`](./LANGUAGE_CONTENT_SOURCES.md), and [`LANGUAGE_ALIGNMENT_DECISION.md`](./LANGUAGE_ALIGNMENT_DECISION.md).

### Outcome

A common Content Inbox safely accepts real-world study material and routes it into Reader or authentic listening. Native audio and transcripts support sentence-level study beyond browser TTS while licensing, provenance, and comprehension remain explicit.

### Work

- Add one intake surface for pasted articles, permitted NRK article references, podcast episodes, user audio files, video/subtitle transcripts, Tatoeba sentences, and generated texts.
- Make Inbox answer: what is this, may it be ingested/stored, how difficult is it for this learner, which targets/idioms/MWEs it contains, and where it should be studied. Reader remains the reading environment; Inbox does not replace it.
- Require a source adapter/access/license decision per content type. Do not scrape arbitrary copyrighted sites or download/cache audio without permission; retain references/links when storage rights are unclear.
- For text/transcripts, show personal vocabulary coverage, unknown/learning items, targets, length, source-aware frequency profile, and MWE/idiom presence. Label this personal comprehensibility, not CEFR.
- Support real audio with transcript sentences, sentence-level timestamps, play/pause/replay/jump, listening-only mode, and show/hide transcript.
- Preserve source and content fingerprints, attribution/license/retention metadata, transcript source/version, and alignment method/confidence.
- Where timestamps are absent, evaluate a dedicated forced-alignment pipeline. Never infer accurate external-audio timing from browser `speechSynthesis` events.
- Record authentic listening activity first. Apply an explicit policy before turning transcript/audio study into sentence/vocabulary exposures.
- Feed Goals, Statistics, Campaigns, future Mistake Intelligence, and future Progress Benchmarks from canonical activity/assessment facts.

### Likely files

- `language_learning/content_inbox.py`, media/transcript/alignment provider interfaces, store/service/jobs/schema extensions
- media artifact metadata under an explicitly managed ignored data area
- thin content-intake, transcript, playback-state, and activity API routes
- `js/language/views/inbox.js`, authentic-listening view/player, Reader handoff
- adapter/license, transcript/timestamp, alignment, activity/exposure, accessibility, API, and UI tests

### Verification

- Exercise pasted text, references, permitted local audio, subtitle/transcript imports, unsupported rights, missing timestamps, failed alignment, and provider outage.
- Verify source text/audio/transcript attribution and licensing decisions survive export/reopen.
- Test play/pause/replay/jump/listening-only/transcript visibility and active-time idempotency against a fake media adapter.
- Prove personal difficulty is calculated from the learner snapshot and never displayed as CEFR or comprehension.
- Prove listening minutes/exposures and later rewards are not recorded from import, preview, failed playback, or inactive wall time.

### Acceptance criteria

- [x] Content Inbox is the common intake/router while Reader remains the reading workspace.
- [x] Every content/audio/transcript item has explicit source, storage-rights, attribution, and version/fingerprint metadata.
- [x] Personal difficulty previews disclose their canonical learner snapshot/policies and make no CEFR claim.
- [x] Authentic audio supports accessible sentence-level transcript navigation where timestamps exist.
- [x] Alignment output discloses method/version/confidence and cannot pretend browser TTS timing applies to external audio.
- [x] Canonical listening activity precedes exposures, goals, campaign progress, gamification, and assessment use.
- [x] Missing rights, adapters, transcripts, or alignment degrade safely without breaking Reader or TTS Listening.

### Deliberately postponed

- Automatic scraping/downloading of arbitrary copyrighted publishers or media.
- Word-level alignment unless measured accuracy and use justify it.
- Pronunciation grading, open-ended speaking, and shadowing assessment remain optional future extensions under separate authorization.
- Certified proficiency claims from content difficulty or listening time.

## Phase 11 — Core Grammar A1–B1

Phase status: **COMPLETE (2026-09-24)**. Seven narrow supported detectors and fourteen explicitly deferred candidates ship with exact canonical evidence, offline optional parsing, quality review, and versioned DISCOVERED/ENCOUNTERED semantics. Main schema/export are v15; reference remains read-only v3. Exact scope, measurements, migration, tests and limitations are in [`LANGUAGE_PHASE11_RESULTS.md`](./LANGUAGE_PHASE11_RESULTS.md), the [`catalogue`](./LANGUAGE_GRAMMAR_PATTERNS.md), and [`parser setup`](./LANGUAGE_GRAMMAR_SETUP.md).

### Outcome

The system mines a small, practical catalogue of reviewed Bokmål grammar patterns broadly useful through approximately A1/A2/B1. These are learner-oriented scope buckets, not official or certified CEFR grammar classifications.

### Work

- Keep dependency parsing optional and deferred-cost. Grammar analysis must be separately requested from normal Reader analysis, and no runtime path may download a model.
- Map every grammar occurrence back to canonical tokens and exact source spans. Mapping divergence fails closed rather than attaching a pattern to uncertain text.
- Add grammar pattern/occurrence persistence and a Bokmål-specific detector registry outside generic services. Store exact detector, analyzer, rule, and source provenance.
- Classify every candidate detector as `SUPPORTED`, `EXPERIMENTAL`, or `DEFERRED`. Ship only detectors whose positive and hard-negative fixtures support their claims.
- Report parser and detector availability truthfully; an unavailable parser or deferred detector must never appear as a successful empty result.
- Focus the initial candidate catalogue on practical, reliably detectable content:
  - A1-oriented: basic main-clause word order; yes/no and wh-questions; noun indefinite/definite forms and number; present and simple past tense; basic possessives; basic adjective agreement.
  - A2-oriented: V2 with fronted sentence elements; basic subordinate clauses; negation placement; present perfect; modal constructions; comparison; adjective definiteness/agreement.
  - B1-oriented: more varied subordinate clauses; relative clauses; conditional structures; passive constructions only when detector evidence is defensible; and more complex but reliably detectable word-order constructions.
- Use exact examples from canonical user texts and distinguish authentic, Reader, transcript, and generated source provenance. Phase 11 does not generate new grammar examples with AI.
- Add the `#grammar` route, pattern detail, Reader sentence links, and user detector-quality decisions `CONFIRM` / `REJECT`.
- Use `DISCOVERED` and `ENCOUNTERED` as the primary learner-facing evidence states. Existing canonical activity may supply other defensible internal practice evidence, but `PRACTICED` or `RELIABLE` is not a Phase 11 completion requirement.
- Keep grammar observations read-only with respect to canonical vocabulary, knowledge, Mistake Intelligence, XP, achievements, and rewards.

### Likely files

- `language_learning/grammar.py` (new)
- `language_learning/analysis/norwegian_bokmal.py`, `migrations.py`, `store.py`, `service.py`, `jobs.py` (expanded)
- `js/language/views/grammar.js` (new)
- `tests/test_language_grammar.py`, `language-grammar.test.js`, analysis fixtures (new/expanded)

### Verification

- Positive and hard-negative fixtures for every shipped detector, including representative A1/A2/B1 constructions and near misses.
- Analyzer/detector-version, canonical span-mapping, divergence-fail-closed, and user-review preservation tests.
- Availability tests for missing parser/model states, proving normal Reader analysis remains usable and no runtime download occurs.
- Performance comparison between normal Reader analysis and separately requested Grammar analysis.
- Source-provenance checks across authentic, Reader, transcript, and already-existing generated texts.

### Acceptance criteria

- [x] Generic services contain no hard-coded Bokmål grammar rules; detectors live in the language-specific registry.
- [x] Every occurrence points to exact canonical source spans and records detector/analyzer/rule provenance.
- [x] Every detector is explicitly `SUPPORTED`, `EXPERIMENTAL`, or `DEFERRED`; weak detectors do not ship as supported behavior.
- [x] Mapping divergence and unavailable parsing fail closed without changing normal Reader output.
- [x] Rejected/confirmed user detector-quality decisions survive detector upgrades.
- [x] Grammar examples disclose whether they came from authentic content, Reader, transcripts, or existing generated text.
- [x] Learner-facing evidence uses `DISCOVERED` and `ENCOUNTERED` without arbitrary mastery percentages.
- [x] Grammar mining can be disabled without changing Reader tokens, vocabulary knowledge, Mistake Intelligence, XP, or rewards.

### Deliberately postponed

- Grammar mastery, arbitrary grammar percentages, and a `RELIABLE` completion state.
- A complex Grammar practice engine, Grammar-specific XP/rewards, Grammar achievements, and automatic Grammar-to-Mistake-Intelligence diagnosis.
- AI-generated grammar examples and broad/exhaustive Bokmål coverage.
- B2/C1/C2 patterns and deeper practice/diagnostics; these belong to the optional Advanced Grammar Expansion.

## Phase 11.5 — Progress Benchmarks

Phase status: **COMPLETE (2026-09-24)**. See [`LANGUAGE_PHASE11_5_RESULTS.md`](./LANGUAGE_PHASE11_5_RESULTS.md) and [`LANGUAGE_BENCHMARK_CONTENT.md`](./LANGUAGE_BENCHMARK_CONTENT.md).

### Outcome

Versioned baseline and repeat checkpoints measure practical progress through transparent tasks and saved responses without presenting the dashboard as a certified language examination. A small Norway Preparation summary reuses existing evidence without creating a readiness score.

### Work

- Add a baseline and repeatable, versioned checkpoints for vocabulary recognition, Cloze, unseen reading comprehension, and unseen listening comprehension.
- Store actual responses, item/content version, benchmark date, scoring method/version, and repeat/leakage controls. Keep benchmark items out of ordinary practice where feasible.
- Report clear raw counts and percentages for each dimension, plus trend since baseline in percentage points where versions remain comparable.
- Keep Reading and Listening results separate. Reading coverage is not reading comprehension, and listening time is not listening comprehension.
- Do not create or promote canonical knowledge/mastery from benchmark performance.
- Keep output descriptive: for example vocabulary recognition 82%, Cloze 71%, Reading comprehension 74%, Listening comprehension 58%, trend since baseline +12 pp.
- Add a small Norway Preparation summary with separate dimensions such as Everyday, Work, Housing, Transport, Public Services, Reading, and Listening.
- Derive that summary only from existing inspectable evidence such as curriculum completion, campaign dimensions, Reader activity, Listening activity, and benchmark results. Prefer counts and named states, for example `Work vocabulary: 21 / 40` and `Listening benchmark: 58%`.
- Do not calculate or display a universal Norway-readiness percentage.

### Likely files

- `language_learning/assessment.py`, benchmark content contracts, and minimal store/service/schema extensions
- thin benchmark/history and Norway-summary API routes
- benchmark runner/history plus a compact Norway Preparation summary
- scoring, leakage/repeat, comparability, no-knowledge-mutation, summary-evidence, API, and UI tests

### Verification

- Hand-score vocabulary recognition, Cloze, unseen Reading, and unseen Listening fixtures and verify raw counts/percentages.
- Compare baseline and checkpoint trends only when item/scoring versions are compatible; show an explicit non-comparable state otherwise.
- Test unseen-item restrictions, repeats, leakage, partial completion, missing modalities, and stale content versions.
- Prove benchmark submission cannot create knowledge, mastery, exposures, due dates, goals, or XP.
- Reconcile every Norway Preparation dimension to its named canonical source and verify there is no hidden composite score.

### Acceptance criteria

- [x] Baseline and repeat checkpoints persist real responses, content/item versions, scoring versions, and leakage controls.
- [x] Vocabulary recognition, Cloze, Reading comprehension, and Listening comprehension show clear raw results and percentages.
- [x] Reading and Listening remain separate from coverage, exposure, activity time, account level, and rewards.
- [x] Trend since baseline is shown only for matching-form/scoring versions with repeat influence disclosed; other pairs show an explicit non-comparable state.
- [x] Benchmark performance creates no knowledge or mastery automatically.
- [x] Norway Preparation shows separate practical dimensions backed by existing evidence and never a universal readiness percentage.
- [x] The benchmark system is useful without estimated CEFR, a proficiency-confidence engine, a skill tree, or phrase/idiom identity changes.

### Deliberately postponed

- Estimated CEFR, A1/A2/B1/B2 proficiency inference, a proficiency-confidence engine, and a global proficiency level.
- Complex CEFR calibration and the Skill Tree; both require separate future authorization.
- Phrase/idiom lexical-identity architecture changes.
- A universal Norway-readiness score.

## Phase 11.6 — Study Session Builder

Phase status: **COMPLETE (2026-09-24)**. See [`LANGUAGE_PHASE11_6_RESULTS.md`](./LANGUAGE_PHASE11_6_RESULTS.md).

### Outcome

The learner can choose 10, 20, or 30 minutes and receive one small, deterministic, explainable study session composed from work already owned by existing modules.

### Work

- Consume only existing owned outputs: Anki due metadata, Mistake Intelligence remediation, LearningPlan, Goals, unfinished Reader content, Listening needs/progress, curriculum gaps, available Core Grammar evidence, and defensible weak benchmark dimensions.
- Produce a strict duration-bounded session, for example: 5 minutes Cloze mistakes, 7 minutes Continue Reader, 5 minutes Listening, and 3 minutes Work vocabulary.
- Keep Anki responsible for SRS scheduling, Goals responsible for targets, and LearningPlan responsible for next-action facts. The Study Session Builder only composes and sequences those outputs.
- Use a small deterministic priority/scoring model with versioned weights, eligibility, time estimates, diversity/cooldown, and module-availability rules.
- Make identical snapshot, available time, date, and rule version yield the same bounded plan and explanation for every segment.
- Show a small actionable session rather than the whole backlog; provide honest partial or empty plans when the time budget or modules are unavailable.
- Creating or viewing a plan creates no knowledge, exposure, attempt, goal progress, due date, or XP. Only normal completed module activity may create its existing canonical evidence.

### Likely files

- `language_learning/study_session_builder.py`, bounded adapters over existing module outputs, and optional plan snapshots
- thin plan preview/start/status API routes
- Overview/Reviews/session-builder UI and module handoffs
- deterministic weighting, time-budget, overload, missing-mode, explanation, API, and UI tests

### Verification

- Hand-calculate 10/20/30-minute plans from identical and varied snapshots.
- Test overdue Anki, severe mistakes, unfinished Reader work, curriculum gaps, weak benchmark dimensions, repeated recent modes, unavailable Listening/Grammar/Anki, empty profiles, and impossible time budgets.
- Verify plan order/time never exceeds the budget beyond a documented rounding policy and that the backlog is bounded.
- Generate/reopen/retry plans and prove no knowledge, exposure, scheduling, goal, or XP mutation occurs until real study activity is recorded.

### Acceptance criteria

- [x] The same snapshot/time/date/rule version produces the same bounded session and explanation.
- [x] Plans compose existing module outputs without owning Anki scheduling, Goals, LearningPlan facts, knowledge, attempts, or benchmarks.
- [x] Sessions are intentionally small, respect availability, and never dump the full backlog.
- [x] Each segment identifies its source need, expected duration, destination module, and selection rule.
- [x] Creating/viewing a plan awards no XP and creates no learning evidence.
- [x] Provider/module failures yield a smaller honest plan rather than blocking unrelated study.

### Deliberately postponed

- AI/ML recommendation, autonomous agents, complex optimization, or an opaque planner.
- A new scheduler, goal system, quest system, or replacement for LearningPlan.
- Automatic paid provider calls merely to fill a session.
- Unbounded or autonomous study execution.

## Phase 12 — Operational Hardening

Phase status: **COMPLETE (2026-09-25)**. Recovery, measured performance, security and degraded-operation evidence are in [`LANGUAGE_PHASE12_RESULTS.md`](./LANGUAGE_PHASE12_RESULTS.md); the operational procedure is in [`LANGUAGE_OPERATIONS.md`](./LANGUAGE_OPERATIONS.md).

### Outcome

The mature personal Bokmål subsystem is independently recoverable, measured at realistic personal scale, secure, and safely usable when optional providers or data sources fail.

### Work

#### 12A — Backup / restore

- Provide verified SQLite backup plus versioned export/restore validation, integrity checks, and version-compatibility rules.
- Rehearse restore into a clean environment and document the exact recovery procedure independently of Git.
- Recover managed media directories together with transcript/content metadata.
- Verify recovery of canonical vocabulary/knowledge plus Phrasebook, Goals, Gamification, Listening, Grammar, Benchmarks, and Study Session Builder data.

#### 12B — Performance hardening

- Measure realistic larger synthetic and personal-scale datasets before optimizing.
- Profile Vocabulary search, Reader, Cloze, Fast Track, Listening, Content Inbox, Grammar, benchmark history, Study Session Builder, Statistics, Gamification, and the large reference database.
- Add only measured indexes, bounded caches, or rebuildable rollups.
- Recheck the known Fast Track approximately 2.5 s versus shared Review approximately 31 ms discrepancy and investigate it only if it still exists.

#### 12C — Security and degraded operation

- Exercise independent failures: canonical analyzer unavailable; Grammar parser unavailable; Gemini unavailable or quota-exhausted; dictionary unavailable; Anki unavailable; browser TTS unavailable; Google Cloud TTS unavailable; reference DB missing or corrupt; managed media missing; interrupted jobs; restart during work; and corrupt or invalid external artifacts.
- Ensure an optional provider/module failure cannot block unrelated local study.
- Review API authorization, static-file protection, secrets, media paths, provider errors, backup integrity, privacy, and accessibility.
- Verify interrupted work and restart recovery are diagnosable and do not fabricate learning evidence.

### Likely files

- backup/restore tooling and `docs/LANGUAGE_OPERATIONS.md`
- narrowly measured indexes, bounded caches, or rebuildable rollups only where profiling justifies them
- generated synthetic performance fixtures and integrity/recovery tests
- focused security, authorization, artifact-path, restart, and degraded-operation tests

### Verification

- Restore SQLite, exported data, and managed media into a temporary clean environment; compare canonical counts, fingerprints, paths, and integrity.
- Exercise supported version compatibility and reject incompatible restore inputs safely.
- Run realistic synthetic performance budgets across every named Phase 12B surface and record before/after evidence for any optimization.
- Simulate each named provider/module/data failure independently, including interrupted jobs and process restart.
- Complete API authorization, static-file protection, secrets, media-path, privacy, backup-integrity, and accessibility checks.

### Acceptance criteria

- [x] Verified backup/restore recovers canonical user data, Phrasebook, Goals, Gamification, Listening, Grammar, Benchmarks, Study Session Builder source state, transcript/content metadata, and managed media. Study Session plans remain ephemeral.
- [x] A documented clean-environment rehearsal passes integrity, version-compatibility, and exact logical-state comparison independently of Git.
- [x] Every named Phase 12B workflow has a recorded realistic performance measurement; optimizations were limited to measured hot paths.
- [x] The Fast Track versus shared Review discrepancy was remeasured and reduced; the residual reference-selection latency is documented.
- [x] Named provider/module/data failures were exercised with focused and inherited tests; unrelated local study remains usable and durable work remains diagnosable/recoverable.
- [x] The local API blocks database, secret, and provider-artifact paths from static serving and enforces its authorization boundary.
- [x] Privacy, media paths, provider errors, backup integrity, and a bounded accessibility review cover mature workflows.

### Deliberately postponed

- Speculative optimization without measurements.
- Multi-user accounts, cloud synchronization, native mobile/offline-first sync, and social/competitive sharing.
- Automatic cross-feature data sharing without explicit contracts and consent.
- Second-language proof and Synchrobook integration; both are outside active Phase 12.

## Optional Future Extensions

Status: **NOT SCHEDULED / SEPARATE AUTHORIZATION**. These items are not active dependencies and are not required for subsystem completion. The former active Phase 11.7 has been removed.

1. **Advanced Grammar Expansion** — B2+ patterns, deeper Grammar practice, and possible Grammar diagnostics.
2. **Estimated CEFR** — only if later evidence and calibration justify it.
3. **Skill Tree** — only if later desired.
4. **Writing Practice**.
5. **Speaking Practice**.
6. **Shadowing**.
7. **Pronunciation technology/scoring**.
8. **Mandarin Chinese** — the possible future actual second language; it requires a separate architecture spike based on real Mandarin needs rather than a random abstraction test.
9. **Synchrobook integration**.
10. **Forced alignment** — already deferred in Phase 10.5.
11. **Tier 3 n-grams** — optional reference enrichment.

## 3. Roadmap status registry

This registry must stay aligned with [`LANGUAGE_RUN_PROGRESS.md`](./LANGUAGE_RUN_PROGRESS.md):

- Phase 0: **COMPLETE**
- Phase 1: **COMPLETE**
- Phase 2: **COMPLETE**
- Phase 3: **COMPLETE**
- Phase 4: **COMPLETE**
- Phase 5: **COMPLETE**
- Phase 6: **COMPLETE**
- Phase 7: **COMPLETE**
- Phase 7.5A: **COMPLETE**
- Phase 7.5B: **COMPLETE**
- Phase 9A Cloze Fast Track MVP: **INTENTIONALLY PULLED FORWARD / COMPLETE**
- Phase 7.5C: **COMPLETE**
- Phase 7.6: **COMPLETE**
- Phase 7.7: **COMPLETE**
- Phase 7.8: **COMPLETE**
- Phase 8: **COMPLETE**
- Phase 9 full: **COMPLETE**
- Phase 9.5: **COMPLETE**
- Phase 10: **COMPLETE**
- Phase 10.5: **COMPLETE**
- Phase 11 Core Grammar A1–B1: **COMPLETE**
- Phase 11.5 Progress Benchmarks: **COMPLETE**
- Phase 11.6 Study Session Builder: **COMPLETE**
- Phase 12 Operational Hardening: **COMPLETE**
- Optional Future Extensions: **NOT SCHEDULED / SEPARATE AUTHORIZATION**

Phase 9A is complete historical work. It is not queued again between Phase 8 and full Phase 9.

## 4. Final learning loop and ownership

```text
AUTHENTIC / GENERATED CONTENT
              |
              v
REFERENCE INTELLIGENCE
forms | frequency/rank | meanings/translations | idioms/MWEs
              |
              v
READER / LISTENING / CLOZE
              |
              v
CANONICAL USER EVIDENCE
knowledge | exposure | attempts | mistakes | Anki | grammar | comprehension
              |
              v
LEARNING PLAN
              |
              +--------------------+
              v                    v
GAMIFICATION                STUDY SESSION BUILDER
XP | achievements           bounded session composition
quests | campaigns                 |
              +--------------------+
              |
              v
          MORE STUDY
```

Gamification consumes evidence from this loop; it cannot control or rewrite learning truth. The Study Session Builder composes module-owned work into a bounded session. Neither owns Anki scheduling, Goals, LearningPlan facts, knowledge, benchmark results, or source facts.

| Concern | Owner |
| --- | --- |
| User lemma identity, knowledge, exposures, activity | main Language database through `LanguageService` |
| Linguistic forms, ranks, idioms/MWEs, reference provenance | independent read-only reference database |
| Dictionary senses/translations | selected licensed source plus preserved user edits |
| User-defined targets | Goals |
| Deterministic next actions | `LearningPlanService` |
| Bounded multi-module session composition | Study Session Builder |
| Card scheduling/due dates | Anki |
| Cloze attempts | Cloze |
| Listening activity | Listening services |
| Grammar occurrences | grammar detector registry |
| Benchmark responses, scoring, and history | benchmark assessment service |
| XP, achievements, collections, quests, campaigns | `GamificationService` as a derived overlay |

Saved phrasebook expressions may later feed Cloze, Anki, Listening, generated practice, or campaign vocabulary, but saving alone is never mastery. Content Inbox is the common intake/router for real-world material; Reader remains the reading environment.

## 5. Active roadmap status

The active roadmap is complete through Phase 12. There is no next authorized implementation batch. Optional future extensions, providers, and data imports remain unscheduled and require separate authorization. Phase 9A remains complete historical work and must not be rerun.

## 6. Decisions resolved from implementation evidence

The following questions were resolved within their respective phases. Their decisions and limitations are recorded in the phase results documents, including [`LANGUAGE_PHASE12_RESULTS.md`](./LANGUAGE_PHASE12_RESULTS.md) for recovery, performance, and degraded operation:

1. Which A1/A2/B1 grammar detectors have enough positive and hard-negative evidence to be `SUPPORTED`, and which remain `EXPERIMENTAL` or `DEFERRED`.
2. The separate Grammar parser resource budget, provisioning, availability contract, and canonical span-mapping failure threshold.
3. Benchmark content/source licensing, item versions, scoring versions, unseen-item policy, repeat/leakage controls, and comparability rules.
4. The exact existing evidence and display rules for each lightweight Norway Preparation dimension, without a composite readiness score.
5. Study Session Builder priorities, duration estimates, diversity/cooldown, module availability, explanation format, and strict rounding/budget policy.
6. Backup schedule, retention, restore authority/location outside Git, version compatibility, and paired managed-media recovery.
7. Realistic performance budgets and the measured threshold for adding an index, bounded cache, or rebuildable rollup, including the Fast Track discrepancy.
8. Recovery behavior for interrupted jobs/restarts and each independently unavailable or corrupt provider/module/data source.
9. Final API authorization, static-file protection, secrets, media-path, privacy, backup-integrity, and accessibility checklists.

## 7. Major future risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Weak or over-broad grammar detectors | Require positive and hard-negative fixtures; classify detectors as `SUPPORTED`, `EXPERIMENTAL`, or `DEFERRED`. |
| Grammar span divergence or parser failure | Map only to canonical token spans, fail closed, and keep normal Reader analysis independent. |
| Benchmark leakage/repeated-test inflation | Reserve/version unseen items, detect repeats, and separate practice from checkpoints. |
| Reading coverage mistaken for comprehension | Require unseen reading questions and report coverage/exposure separately. |
| Listening time mistaken for comprehension | Require unseen listening questions; minutes remain activity, not benchmark performance. |
| Benchmark results mutating knowledge | Keep benchmark responses/scoring separate and prohibit automatic knowledge/mastery updates. |
| Norway Preparation becoming a fake readiness score | Show separate named dimensions with inspectable counts/states and no universal composite percentage. |
| Planner becoming opaque | Version weights/rules and expose why each segment was selected. |
| Planner duplicating module ownership | Compose Anki, Goals, LearningPlan, Mistake Intelligence, Reader, Listening, curriculum, Grammar, and benchmark outputs without replacing them. |
| Planner overloading the learner | Honor strict 10/20/30-minute budgets and show only a small bounded session. |
| SQLite/media recovery gap | Rehearse clean-environment restore of both canonical metadata and managed media independently of Git. |
| Speculative optimization | Measure realistic scale first; add only justified indexes, bounded caches, or rebuildable rollups. |
| Provider/data failure blocking study | Preserve manual/local fallbacks and degrade optional modules independently. |
| Secrets or private artifacts exposed | Recheck authorization, static-file blocking, secret handling, and managed-media paths. |

## 8. Completion definition for the full subsystem

The mature personal Bokmål subsystem is complete after Phase 12 when:

- canonical Bokmål vocabulary and knowledge remain intact;
- Reader works;
- Cloze works;
- Anki integration works while Anki remains the SRS owner;
- generation works;
- Listening works;
- Content Inbox and authentic media work with source-aware metadata;
- practical Core Grammar A1–B1 works with defensible detectors and canonical spans;
- versioned benchmark/checkpoint progress works with separate Reading and Listening results;
- the bounded, deterministic, explainable Study Session Builder works by composing existing owners;
- backup/restore, including managed media and content/transcript metadata, is verified in a clean environment;
- performance is measured and hardened only where evidence justifies it;
- provider, parser, media, reference-data, and job failures degrade safely without blocking unrelated local study;
- data and deterministic policies remain source-aware, versioned, and tested;
- the existing dashboard remains functional, accessible, secure, and visually consistent.

Completion does **not** require estimated CEFR, a Skill Tree, advanced B2+ grammar, Writing Practice, Speaking Practice, pronunciation scoring, Mandarin Chinese, Synchrobook integration, Tier 3 n-grams, or forced alignment. Those items remain optional and separately authorized.
