# Language Learning Dashboard architecture

Status: architecture record; active roadmap complete  
Date: 2026-09-15; operational scope updated 2026-09-25  
Initial target language: Norwegian Bokmål (`nb`, locale `nb-NO`)

This document describes how a complete language-learning subsystem should fit into the existing Personal Dashboard. It does not authorize or contain a production implementation.

## 1. Executive decisions

1. The feature should be one subsystem, not a collection of independent Reader, Anki, Cloze, and Statistics stores.
2. A `VocabularyLemma` record is the shared identity used by every module. Surface forms, text tokens, exposures, knowledge, topics, cloze attempts, Anki links, generated texts, and statistics all refer to that identity.
3. Durable language data should live in one new SQLite database, `data/language-learning.sqlite`. Browser storage may hold disposable UI preferences only; it must not become a second vocabulary database.
4. The user-facing application should be a new Vite multi-page entry, `language.html`, with hash-based views inside the page. A compact main-dashboard widget can be added after the overview API exists.
5. Frontend code should be plain ES modules under `js/language/`, following the existing Synchrobook and phone-telemetry feature-folder pattern. No framework or global state library should be introduced.
6. Backend domain, persistence, statistics, and provider logic should live in a feature package under `language_learning/`. `server.py` should contain only initialization and thin `/api/language/*` dispatch branches.
7. Norwegian tokenization and lemmatization must be behind a language adapter. The first production analyzer should be evaluated against Bokmål fixtures before it is selected; Stanza's Norwegian pipeline is the leading candidate because it can provide tokenization, POS, morphology, and lemmas together.
8. Anki, generative AI, frequency data, dictionaries, and TTS must each sit behind a narrow adapter. Provider identifiers and versions must be stored with derived data.
9. AI difficulty is measured after generation by the same analyzer and coverage service used by Reader. Prompt compliance alone is never accepted as proof of difficulty.
10. Anki remains the owner of card scheduling. The dashboard owns vocabulary and learning context; it should create/link cards and import useful card/review metadata without implementing another Anki scheduler.
11. Deterministic domain rules belong in testable modules. UI modules should render data and dispatch commands rather than contain vocabulary scoring or coverage rules.
12. The implementation shipped in vertical, reversible phases. The active roadmap through Study Session Builder and Phase 12 Operational Hardening is complete. Optional provider, active-skill, integration, and second-language work requires separate authorization and is not a completion gate.

## 2. Relevant current repository architecture

The repository was inspected from the current working tree, including the newer uncommitted modules described in `PROJECT_MAP.md`. The following are the patterns that matter to this feature.

| Concern | Current repository pattern | Consequence for Language Learning |
| --- | --- | --- |
| Frontend | Static HTML plus native ES modules; no SPA framework. `index.html` loads dashboard widgets dynamically through `js/dashboard-widget-loader.js`. | Use a normal HTML entry and ES modules. Do not introduce React/Vue or a separate dev server. |
| Navigation/routing | Vite builds many HTML entry points. The dashboard links to them with relative URLs. Rich pages such as Music use an in-page hash and `hashchange` to select sections. | Add `language.html` to Vite inputs, link it from the dashboard, and use hash routes inside the page. |
| Page convention | Focused pages generally have one page HTML, one page controller module, and optional page CSS. Larger features use folders (`js/synchrobook/`, `js/phone-telemetry/`). | Use `language.html`, `language.css`, and a `js/language/` folder because this feature is too large for one controller file. |
| Dashboard widgets | A card in `index.html` has a stable `data-widget` key. Its module is registered in `dashboard-widget-loader.js`; ordering, visibility, span, and labels are registered in `dashboard-settings.js` and `data/widget-order.json`. | Add the compact language widget only when its summary API exists, and register the same stable key everywhere. |
| CSS/design | Global dark tokens are in `styles.css`: `--bg`, `--panel`, `--card`, `--border`, `--text`, `--muted`, status colors, card/tile radii, and padding. Large pages often define scoped page tokens while inheriting the global palette. `styles.css` is large and fragile. | Put page styles in `language.css`, scoped under `.language-page`. Reuse global tokens and compact card density. Keep only compact widget styles near other widget CSS in `styles.css`. |
| Client state | There is no universal state store. Pages use a module-local `state` object and rerender selected mounts. `js/state.js` is a small legacy in-memory store for cleaning. | Use a page-local store/controller. Do not expand `js/state.js` into an application-wide store. |
| Browser persistence | `localStorage` is widely used for UI state, caches, and legacy stores. Newer durable domains such as Reading, Music, Timeline, Habits, and Synchrobook use server-side storage. `js/file-settings.js` mirrors selected settings between localStorage and the local API. | Durable language knowledge belongs in SQLite. localStorage is allowed only for view, filter, panel, voice, and draft preferences that can be lost safely. |
| Backend | `server.py` is a local `ThreadingHTTPServer`/`SimpleHTTPRequestHandler` with explicit method dispatch and feature services imported from separate files. Vite proxies `/api` to `127.0.0.1:8000`. | Add a feature service and thin handler branches; do not refactor the whole server or run a parallel language server. |
| API security | API writes use same-origin/referer checks for local use, optional allowed LAN origins, and bearer-token exceptions for selected remote writers. Static `.sqlite`, `.db`, `.py`, and secret files are blocked. | Language writes should use the existing authorization path. Remote/mobile writes should not be enabled until a concrete client and token policy exist. |
| Databases | Feature-scoped SQLite stores use row factories, foreign keys, busy timeouts, WAL where appropriate, transactions, validation errors, and idempotent initialization. Complex schemas use migration tables or `PRAGMA user_version`. | Use one language SQLite DB with explicit ordered migrations and transactional service methods. |
| Build | Vite 5 multi-page build with `base: '/cleaning-dashboard/'`. Production output is static; the local Python API is separate. | Register `language.html` in `vite.config.js`; use relative asset URLs and `/api/language` for local API calls. |
| JavaScript tests | Vitest 2 with `happy-dom`, files under `tests/**/*.test.js`. Pure models and UI modules are tested by dependency injection and synthetic DOM. | Put tokenizer-independent coverage, routing, view-model, and chart logic in pure JS modules with focused Vitest tests. |
| Python tests | `unittest` with temporary directories/databases. API tests replace the global store/service, start `DashboardHTTPServer` on an ephemeral port, and send real HTTP requests. | Test migrations and services against temporary SQLite files, adapters with fakes, and routes with the existing local HTTP test harness. |
| Charts/statistics UI | No general chart library is installed. Existing pages render accessible SVG, DOM bars, or canvas directly; chart transformation logic is kept in JS helpers in the better-tested modules. | Use small SVG/DOM charts and pure series builders. Do not add a chart dependency initially. |
| Dialogs/forms | Native `<dialog>` is used in Music, Synchrobook, Timeline, Cleaning, and Live Workout. Settings uses tab-like section buttons with ARIA and ordinary inputs/selects. | Prefer native dialogs for lemma details and confirmations, with normal semantic forms and delegated events. |
| Settings | Global dashboard settings govern layout and cross-dashboard integrations. Feature-specific settings often live in the feature page and feature store. | Put language profile, analyzer, Anki, AI, TTS, coverage, and goal settings in Language `#settings`. The global settings page only needs widget-level controls supplied by its registry. |
| AI | Cleaning has a browser call to a hard-coded Cloudflare AI proxy. Synchrobook Reading Guide builds prompts, fingerprints source data, validates structured manual LLM output, then imports it. AI Usage monitors local tool quotas. Whisper integrations are local speech-to-text, not generative-text services. | Do not reuse the cleaning proxy contract. Reuse the Reading Guide principles: versioned prompts, source fingerprints, structured validation, provenance, and no trust in model output. |
| Background work/sync | Synchrobook and Voice Journal use persisted jobs plus daemon workers and client polling. BM365 uses a durable sync queue with retries/backoff. Last.fm and AI Usage use stoppable background pollers. SSE is used only where live telemetry justifies it. | Use persisted jobs and polling for analysis/generation/bulk sync. Use explicit Anki sync and retryable records. Do not add SSE until polling is demonstrably inadequate. |

Additional constraints:

- The existing `wordfreq` dependency is already used by Synchrobook and supports Bokmål under `nb`; Language Learning should still declare its own dependency in `requirements-language.txt` rather than relying on another feature's installation side effect.
- `js/i18n.js` is a limited Polish/English UI translation helper used mainly by weather/AQI. A language profile's target language is domain data, not the dashboard UI locale. The first Language page may follow the repository's current mixed Polish/English convention, but all domain codes should be standards-based.
- SQLite files are ignored by Git, while the repository's save scripts are Git-based. A language export/backup path is therefore a functional requirement, not an optional polish item.
- `Synchrobook` and the existing Reading Dashboard should remain separate products. Synchrobook integration is an optional future extension under separate authorization; if later approved, it must use explicit source adapters or APIs, never direct SQLite access.

## 3. Proposed system shape

```text
index.html compact widget / language.html hash views
                         |
                         v
                js/language/api.js
                         |
                  /api/language/*
                         |
                 LanguageService
       +-----------------+------------------+
       |                 |                  |
       v                 v                  v
 LanguageStore      Coverage/Stats      LanguageJobManager
       |                                    |
       v                       +------------+-------------+
 data/language-learning.sqlite |            |             |
                               v            v             v
                         AnalyzerRegistry  AI adapter   Anki adapter
                               |
                               v
                    Norwegian Bokmål adapter

Browser-only TTS adapter <----- Listening view/session service
Existing Cloud audio path ----> generated Reader/Cloze cached MP3
```

The service layer, rather than a UI view or provider, owns every mutation. For example, the Anki adapter may report a review, but `LanguageService.record_anki_review(...)` decides how that evidence affects the shared knowledge snapshot and event log.

### Source-of-truth ownership

| Data | Owner | Notes |
| --- | --- | --- |
| Lemma identity, forms, senses, translations, contexts, topics, notes | Language database | Anki fields are projections, not canonical copies. |
| Knowledge status and recognition/recall/production estimates | Language database | Updated through versioned evidence rules; user overrides are preserved. |
| Texts, sentences, tokens, reading/listening/cloze activity | Language database | All learning events point to shared lemma IDs. |
| Anki scheduling, queues, due dates, intervals, lapses | Anki | Read into snapshots when supported; never overwritten by default. |
| Anki link IDs and last-synced hashes | Language database | Used for duplicate prevention and conflict detection. |
| Generated text and generation provenance | Language database plus optional artifact files | Generation is not an exposure until the user studies it. |
| Page filters, selected panel, playback rate/voice | Browser or language settings | Browser-only values must be safe to lose. |
| Aggregated charts and mastery percentages | Derived from canonical facts | Cache/materialize later if performance requires it. |

## 4. Domain model

### 4.1 LanguageProfile

Represents one target-language learning space.

- `id`: stable internal public ID.
- `languageCode`: ISO 639 code, initially `nb`.
- `locale`: BCP 47 locale, initially `nb-NO`.
- `displayName`: `Norwegian Bokmål`.
- `translationLocales`: ordered preferences such as `pl-PL`, `en-GB`.
- `analyzerId`, `frequencySourceId`, `dictionarySourceIds`.
- status and created/updated timestamps.

One profile can be active initially, but IDs and foreign keys must be present from the first migration so a second language does not require rewriting every table.

### 4.2 VocabularyLemma

The central vocabulary record. It represents a lexeme: a normalized lemma plus part of speech when known. Two senses of the same lexeme can be child records; noun `jobb` and a hypothetical verb with the same spelling need not be collapsed merely because the characters match.

Core fields:

- `id`, `languageProfileId`.
- `lemmaDisplay`, `lemmaNormalized`.
- `partOfSpeech` (nullable during analysis).
- `canonicalKey` and `mergedIntoId` for safe deduplication/merging.
- frequency value/rank and source/version provenance.
- optional CEFR value plus source/version; never infer CEFR from frequency without labeling it as an estimate.
- user notes and created/updated timestamps.

Capabilities such as definitions, translations, senses, topics, contexts, and Anki links should be normalized child records instead of an ever-growing JSON blob on this table.

### 4.3 SurfaceForm and form-to-lemma links

A form is not a second vocabulary item. The model needs:

- `SurfaceForm`: original/display form, normalized form, language profile.
- `FormLemmaLink`: form ID, lemma ID, morphological features, analyzer/provider, analyzer version, confidence, and whether the mapping is manually locked.

The link is many-to-many because a surface form can be ambiguous in context. A persisted text token stores the chosen link/lemma for that occurrence. A manual correction affects the current token and can optionally create a locked general mapping; it must not blindly rewrite all historical homographs.

Example target behavior:

```text
jobb     ----+
jobben   ----+--> VocabularyLemma("jobb", POS=NOUN)
jobber   ----+
jobbene  ----+
```

Analyzer provenance makes it possible to re-analyze unlocked mappings later. Manually locked mappings always win over a new analyzer version.

### 4.4 LemmaKnowledge

Current state and evidence history are separate.

Current snapshot:

- `knowledgeStatus`: `NEW`, `LEARNING`, `KNOWN`, or `MASTERED`.
- `disposition`: `TRACKED`, `IGNORED`, or `EXCLUDED`.
- `recognition`, `recall`, `production`: nullable bounded scores, initially an integer 0–5.
- `totalExposures`, first/last-seen timestamps, last-review timestamp.
- `manualOverride` flags and rule version.

Append-only `KnowledgeEvent` rows record why the snapshot changed: manual status edit, Reader exposure, cloze result, Anki review, import, merge, or recalculation. This supports vocabulary-over-time and status-transition statistics without trying to reconstruct history from the latest row.

`active`, `passive`, `weak`, `recent`, and `mastered` should be named derived classifiers, not independent booleans that drift out of sync. Their threshold rules must be versioned and tested. A practical first definition is:

- passive: adequate recognition but recall/production below the active threshold;
- active: recall or production meets the active threshold;
- mastered: explicit `MASTERED` status or a conservative rule using repeated success and recency;
- weak: learning/known item with recent failures, lapses, or overdue recycling evidence;
- recent: first learned or materially advanced within the configured window.

User-set status/disposition must not be silently downgraded by a heuristic.

### 4.5 Text, Sentence, TokenOccurrence, and Context

- `TextDocument`: imported, pasted, or generated source; title, raw text, source type, source reference, language profile, processing state, and content fingerprint.
- `TextSentence`: stable order, exact text, character offsets, and normalized fingerprint.
- `TextToken`: exact surface text, offsets, token kind, form ID, selected lemma ID, POS/morphology, analyzer provenance, and ambiguity state.
- `LemmaContext`: a pinned or automatically selected sentence linked to a lemma and source sentence. It may carry a quality/ranking score and user note.

Exact original text and character offsets are canonical for rendering. Normalized text is search/analysis data and must never replace the original.

### 4.6 Exposure and study activity

An exposure is evidence that study actually happened, not merely that content was imported or generated.

- `StudySession`: Reader, generated Reader, listening, cloze, manual study, or imported Anki activity; start/end, active seconds, language profile, and optional text/job reference.
- `ExposureEvent`: lemma, optional form/sentence/token, source type, occurrence count, timestamp, and session ID.
- `ActivityEvent`: higher-level facts such as text completed, listening minutes, cloze attempted/correct, Anki reviews imported, or status changed.

Client event IDs/idempotency keys prevent a page retry from double-counting. A session can record several aggregated lemma/form exposures rather than one row for every repeated token, while still retaining a sentence reference for context.

### 4.7 Senses, translations, definitions, and notes

Add these as child records when the Vocabulary detail flow exists:

- `LemmaSense`: sense label/order, POS, definition, source, source version, user-edited flag.
- `LemmaTranslation`: sense/lemma, translation locale, value, source, confidence, user-edited flag.
- `LemmaContext`: described above.
- tags through a normalized tag/link table.

Provider text must be escaped in the UI. User edits should be distinguished from provider cache data so refreshes cannot overwrite them.

### 4.8 Topics

- `Topic`: language profile, stable slug, display name, description, parent topic, and archived flag.
- `TopicLemma`: lemma, relevance/weight, provenance, and whether membership is manual or imported.

Topic mastery is computed from the weighted knowledge of linked lemmas. It is not a stored arbitrary completion percentage. Every displayed mastery value should include denominator quality: number of mapped lemmas, number with frequency data, and number unresolved.

### 4.9 Goals and learning plan

- `GoalDefinition`: metric, period (`DAY`, `WEEK`, `MONTH`), target, unit, active dates, and week-start/time-zone settings.
- progress is derived from `ActivityEvent`/`StudySession` facts.
- `LearningPlanService` produces today's deterministic recommendations from goal gaps, weak/recent/underexposed words, Anki due metadata, and available text. A saved plan snapshot may support UI continuity, but it must reference the facts/rule version used.

### 4.10 Anki records

- `AnkiNoteLink`: lemma, template purpose, note ID, deck/model names, stable dashboard key/tag, last pushed/pulled hashes, dirty/conflict state, timestamps.
- `AnkiCardSnapshot`: card ID, note link, deck, queue/type, due, interval, ease, reviews, lapses, and observed timestamp when available.
- `AnkiSyncRun`: mode, status, counts, warnings/errors, capability/version snapshot, started/completed timestamps.

There should be a unique local link for `(lemmaId, templatePurpose)` and a unique external note ID. Card IDs belong to Anki and may be replaced if note templates change.

### 4.11 Cloze and grammar

- `ClozeExercise`: lemma, source sentence, exact target token/range, accepted answer snapshot, generation source/version, and status.
- `ClozeAttempt`: exercise, session, answer, correctness, response time, hint/reveal use, timestamp.
- `GrammarPattern`: language-specific pattern key, label, explanation status, detector/version.
- `GrammarOccurrence`: pattern, source sentence/token span, confidence, reviewed flag.

Grammar examples must point to exact canonical source sentences and disclose authentic, Reader, transcript, or already-generated provenance. Active Phase 11 does not generate new grammar examples with AI; any future generated-example workflow requires separate authorization and canonical post-analysis.

## 5. Storage strategy

### 5.1 Database and files

- Database: `data/language-learning.sqlite`.
- Provider/generated audio and large artifacts: `data/language-learning/artifacts/`, referenced by relative paths and never stored as large SQLite BLOBs.
- SQLite settings: foreign keys on, busy timeout, WAL, normal synchronous mode, connections scoped to operations.
- Timestamps: store UTC ISO timestamps. Derive local study dates using the profile time zone (defaulting to the existing `Europe/Warsaw` convention).
- IDs: stable lowercase UUID hex strings, matching other feature packages, unless a benchmark demonstrates a concrete need for integer-only internal keys.
- API JSON: camelCase; SQLite/Python internals: snake_case.

### 5.2 Migration strategy

Use a `language_schema_migrations(version, applied_at, checksum)` table and ordered Python migration functions. Initialization should:

1. create the database directory;
2. acquire an initialization lock;
3. open a transaction;
4. apply each missing migration once;
5. validate required tables/indexes;
6. commit or roll back the entire migration;
7. expose schema/analyzer health through `/api/language/health`.

Migrations must be additive whenever possible. Renames or rewrites require a SQLite backup first and a tested data-copy migration. Analyzer changes are data migrations, not schema migrations: store analyzer version and offer preview/reanalysis for unlocked tokens/forms.

### 5.3 Initial versus deferred tables

The first persistent slice should create only what the core Reader needs:

- schema migrations;
- language profiles/settings;
- lemmas, forms, form/lemma links, lemma knowledge, knowledge events;
- texts, sentences, tokens, import/analysis runs;
- study sessions and exposure events.

Later migrations add senses/translations, topics, goals, Anki records, jobs/generation, cloze, grammar, and server-audio artifacts. This preserves extension points without requiring every long-term property in migration 1.

### 5.4 Backup/export

Git backup tags do not contain ignored SQLite databases. Before meaningful study data accumulates, provide:

- a read-only, versioned JSON export containing profiles, vocabulary, forms, knowledge history, texts/contexts metadata, topics/goals, and external links;
- a server-side SQLite backup using SQLite's backup API to `data/backups/` while WAL is active;
- restore/import as a separate, explicit, previewable operation with schema validation and no overwrite by default.

No implementation phase should modify the existing Git backup scripts unless separately requested.

Phase 12 adds a separate `language-backup/v1` operational package: a verified SQLite backup-API snapshot plus only DB-owned Content Inbox media, with an untrusted-input manifest, read-only validation, restore preview, and staged clean restore. Reference facts, Stanza models, and generated audio remain reprovisionable dependencies. The exact inventory and commands are in [`LANGUAGE_OPERATIONS.md`](./LANGUAGE_OPERATIONS.md).

## 6. Service boundaries

### LanguageStore

Owns SQL, migrations, row mapping, transactions, constraints, and low-level queries. It does not call Anki, AI, dictionaries, or TTS.

### LanguageService

The only public domain mutation boundary. It validates commands, resolves/merges lemmas, records knowledge/activity events, coordinates transactions, and returns API-ready models.

### AnalyzerRegistry and LanguageAnalyzer

Select an analyzer by language profile. Contract:

```python
analyze(text, *, language_code, options) -> AnalysisDocument
```

`AnalysisDocument` contains sentences and tokens with exact offsets, token kind, normalized form, lemma candidates, selected lemma, POS, morphology, confidence, and analyzer ID/version. Generic services consume only this contract.

### CoverageService

Computes Reader and generated-text coverage using the same knowledge snapshot and versioned policy. It returns raw counts, classifications, unresolved/ambiguous items, and derived percentages.

### StatisticsService

Builds overview, time series, frequency-band coverage, topic mastery, transition counts, streaks, and goal progress. It may gain rollup tables later, but initial results come from canonical facts.

### LearningPlanService

Ranks actionable work deterministically: due/weak items, recent words needing reuse, low-exposure items, goal gaps, and available content. The AI generator consumes its target selection; it does not own the selection algorithm.

### AnkiAdapter / AnkiSyncService

The adapter knows the AnkiConnect wire protocol. The sync service knows local ownership, link hashes, duplicate prevention, conflict rules, and how imported review/card evidence becomes domain events.

### GenerationProvider / GenerationService

The provider sends a structured request to a configured model. The service builds a lexical snapshot, versions/fingerprints the prompt, validates returned JSON/text, invokes the analyzer and coverage service, and decides accept/revise/warn.

### DictionaryProvider and FrequencyProvider

Return source-attributed candidates only. User-edited data remains separate. Cache entries include provider and version/observed date.

### TtsAdapter

Frontend browser speech and backend audio providers share a conceptual contract: supported locale/voice, play or speak one sentence, cancel, and report lifecycle capability. A shared frontend playback coordinator guarantees a single active owner across browser speech and the existing generated Reader/Cloze Google Cloud cached-MP3 players. Study-session tracking remains in the domain service.

### LanguageJobManager

Persists jobs for analysis, generation/revision, bulk Anki sync, and future server TTS. Follow existing worker patterns: stoppable daemon thread, startup recovery, stage/progress/error fields, cancellation where safe, and polling endpoints. Start with one personal-dashboard worker; split job lanes only after measured contention.

## 7. Proposed file and directory structure

```text
language.html
language.css
requirements-language.txt

js/
  widget-language-learning.js
  language/
    app.js
    api.js
    router.js
    state.js
    model.js
    coverage.js
    charts.js
    audio/
      browser-speech.js
    components/
      dialog.js
      filters.js
      status-control.js
    views/
      overview.js
      reader.js
      vocabulary.js
      reviews.js
      generate.js
      cloze.js
      listening.js
      grammar.js
      statistics.js
      goals.js
      settings.js

language_learning/
  __init__.py
  errors.py
  migrations.py
  store.py
  service.py
  validation.py
  coverage.py
  statistics.py
  learning_plan.py
  jobs.py
  schemas.py
  analysis/
    __init__.py
    base.py
    registry.py
    norwegian_bokmal.py
  providers/
    __init__.py
    anki.py
    generation.py
    dictionary.py
    frequency.py
    tts.py

scripts/
  diagnose_language_env.py
  import_language_vocabulary.py

tests/
  fixtures/language/nb/*.json
  language-model.test.js
  language-coverage.test.js
  language-router.test.js
  language-page.test.js
  widget-language-learning.test.js
  test_language_store.py
  test_language_analysis.py
  test_language_coverage.py
  test_language_services.py
  test_language_providers.py
  test_language_jobs.py
  test_language_api.py
```

Files should be added only in the phase that uses them. Empty future view/provider modules should not be scaffolded merely to match this tree.

Existing files eventually affected are limited to `vite.config.js`, `index.html`, `styles.css` for the compact widget, `js/dashboard-widget-loader.js`, `js/dashboard-settings.js`, `data/widget-order.json`, `server.py`, and `.env.example`. This is not a reason to refactor any of them.

## 8. Navigation and API routing

### 8.1 Page routes

Use one page and hash routes:

```text
language.html#overview
language.html#reader
language.html#reader/text/<textId>
language.html#vocabulary
language.html#vocabulary/lemma/<lemmaId>
language.html#reviews
language.html#generate
language.html#cloze
language.html#listening
language.html#grammar
language.html#statistics
language.html#goals
language.html#settings
```

The router should be a pure parser/formatter plus one `hashchange` listener. Unsupported routes return to Overview with a visible notice. The page shell and sidebar remain mounted while the active view mount changes. Current filter state can use URL query parameters only when a shareable/reloadable state is useful; transient dialog state stays in page state.

On the main dashboard, add a Language Learning shortcut under the existing `Czytanie` group. The compact widget is a later enhancement and should link to the same page.

### 8.2 API contract

Use `/api/language` with consistent success/error envelopes within this feature:

```json
{ "ok": true, "data": {} }
```

```json
{ "ok": false, "error": "Human-readable message", "code": "stable_code", "details": [] }
```

Representative route groups, introduced incrementally:

| Route | Purpose |
| --- | --- |
| `GET /api/language/health` | schema, analyzer, configured provider, Anki reachability summaries; no secrets |
| `GET/POST /api/language/profiles` | list/create language profiles |
| `GET/PATCH /api/language/profiles/{id}` | profile and settings |
| `GET /api/language/profiles/{id}/overview` | compact overview/today plan payload |
| `GET /api/language/profiles/{id}/vocabulary` | cursor-paginated search/filter/sort |
| `GET/PATCH /api/language/lemmas/{id}` | detail and controlled edits |
| `POST /api/language/lemmas/bulk` | validated bulk status/topic operations |
| `POST /api/language/texts` | save an imported/pasted draft with size limits |
| `POST /api/language/texts/{id}/analyze` | enqueue/version text analysis |
| `GET /api/language/texts/{id}` | document, processing state, and reader payload |
| `POST/PATCH /api/language/study-sessions...` | idempotent activity/progress/exposure commands |
| `GET /api/language/profiles/{id}/statistics` | versioned statistics query |
| `GET/POST/PATCH /api/language/.../topics` | topic definitions and lemma links |
| `GET/POST/PATCH /api/language/.../goals` | goal definitions/progress |
| `POST /api/language/generation-jobs` | adaptive generation request |
| `GET /api/language/jobs/{id}` | persisted job polling |
| `GET/POST /api/language/cloze...` | exercise selection and attempts |
| `GET /api/language/anki/status` | AnkiConnect capabilities/configuration |
| `POST /api/language/anki/sync` | explicit dry-run or committed sync |
| `GET /api/language/export` | versioned JSON export |

List endpoints should be cursor-paginated before the vocabulary becomes large. Writes must validate payload sizes, enum values, ownership/profile IDs, and idempotency keys. Bulk/destructive actions require a preview/count and explicit confirmation.

## 9. Language abstraction and Norwegian strategy

### 9.1 Generic language contract

Generic application code may assume only:

- a language/profile ID;
- display-preserving tokens with character offsets;
- normalized forms;
- zero or more lemma candidates;
- optional POS/morphology/confidence;
- provider/version provenance;
- a coverage policy;
- locale preferences for dictionary/TTS.

It may not contain rules such as Norwegian definite noun endings, English apostrophe splitting, or Polish diacritic removal.

### 9.2 Normalization

For Norwegian Bokmål:

- preserve the exact source for display;
- normalize lookup keys with Unicode NFC plus locale-independent `casefold()`;
- preserve `æ`, `ø`, and `å`; never strip diacritics as Synchrobook's alignment-only normalizer does;
- normalize typographic apostrophes/hyphens only in lookup keys, not display text;
- classify punctuation, numbers, emoji, URLs, and lexical tokens separately;
- preserve start/end character offsets so the Reader can render the original text without rebuilding it from normalized tokens.

Compound words should remain intact unless the selected analyzer explicitly identifies a supported split. A guessed compound decomposition must never create canonical lemmas automatically.

### 9.3 Tokenization and lemmatization

Recommended production path:

1. Evaluate Stanza's `nb` model with `tokenize`, applicable MWT processing, `pos`, and `lemma` against a committed Bokmål fixture set. Defer dependency parsing until grammar mining.
2. Provision models explicitly with a setup/diagnostic script. An HTTP request must never trigger a surprise model download.
3. Store analyzer/model/package version with every analysis run and token mapping.
4. Reject or keep a text in `ANALYZER_UNAVAILABLE`/draft state if the canonical analyzer is missing. Do not silently persist lowercased surface forms as lemmas.
5. Consider Simplemma only as an explicitly lower-confidence fallback after a fixture benchmark; its published Bokmål result is useful for a baseline but not strong enough to make unreviewed mappings authoritative.
6. Provide manual token-to-lemma correction and lemma merge tools before bulk imports are encouraged.

Norwegian-specific fixtures must cover at least:

- `jobb`, `jobben`, `jobber`, `jobbene` mapping to the noun lemma `jobb`;
- verbs across infinitive/present/past/participle forms;
- adjective agreement/definiteness;
- common Bokmål pronouns and function words;
- punctuation, quotes, hyphens, URLs, names, numbers, and `æ/ø/å`;
- ambiguous homographs and incorrect-analyzer correction;
- sentence boundary edge cases.

### 9.4 Frequency and optional CEFR metadata

Use a `FrequencyProvider` contract. `wordfreq` is a pragmatic first source because the repository already depends on it and its upstream data uses `nb` specifically for Bokmål. Store both a score (for example Zipf frequency) and source/version. If Top 500/1000/2000/5000 views require exact ranks, import a versioned ranked list through the same provider rather than pretending a Zipf score is a rank.

Frequency matching should be lemma-first with a documented fallback to surface form. The UI must report how many items in a band could not be mapped. Estimated CEFR is not part of the active roadmap or completion gate; the existing metadata field remains nullable unless a separately authorized, licensed, versioned source is later selected.

Dictionary providers return candidate senses/translations with attribution and caching. Licensing and redistribution must be checked before importing any full frequency or dictionary dataset.

## 10. Coverage and adaptive difficulty

Coverage is token-weighted because comprehensibility is affected by repeated occurrences, but unique-lemma coverage should also be displayed for diagnostic value.

Version 1 policy should report, separately:

- eligible lexical token count;
- covered token count (`KNOWN`/`MASTERED`, plus an explicit policy for `IGNORED`);
- learning token count;
- unknown token count;
- ambiguous/unresolved token count;
- excluded punctuation/number/proper-name count;
- token coverage percentage;
- unique-lemma coverage percentage;
- policy version and knowledge snapshot timestamp.

`EXCLUDED` items leave the denominator. `IGNORED` items should count as covered only if the user intentionally marked them as not requiring study; the raw ignored count remains visible. Unresolved lexical tokens should be uncovered, not silently omitted.

Initial requested targets:

| Difficulty | Target token coverage |
| --- | ---: |
| Very Easy | about 99% |
| Easy | about 97% |
| Normal | about 95% |
| Challenge | about 90% |

For short texts, one token can exceed a whole percentage point. Acceptance therefore uses a documented tolerance such as `max(1 percentage point, 100 / eligibleTokenCount)`, while still showing exact counts.

### Closed generation loop

1. Snapshot the user's covered vocabulary and rule versions.
2. Deterministically rank frontier words: explicit targets first, then weak Anki-linked words, recent learning words, low-exposure words, and topic vocabulary.
3. Convert target length/coverage into a maximum unknown-token budget and target repetition plan.
4. Build a structured, versioned prompt containing only the necessary lexical data.
5. Store provider/model/prompt version, request fingerprint, target snapshot, and raw response.
6. Validate response shape and safety/length constraints.
7. Analyze the actual text using the canonical language analyzer.
8. Compute coverage with `CoverageService` against the frozen snapshot.
9. If outside tolerance, request a bounded revision with the measured unsuitable words and suggested replacements. Reanalyze every revision.
10. After the maximum attempts, keep the best candidate with a visible warning instead of claiming it met the target.
11. Save an accepted candidate as a normal `TextDocument` with generation provenance.
12. Record exposures only when the user actually reads/listens/completes exercises from it.

The generator cannot directly set a word to known, create Anki cards, or increment exposures.

## 11. Reader data flow

```text
paste/import text
  -> save exact draft + fingerprint
  -> analysis job
  -> sentence/token offsets + lemma candidates
  -> resolve existing forms/lemmas
  -> create only missing canonical records
  -> compute coverage
  -> Reader renders colors from LemmaKnowledge
  -> click token opens the shared lemma detail
  -> status/form/lemma correction goes through LanguageService
  -> reading session completion records idempotent exposures/activity
  -> overview, goals, cloze, generator, and statistics see the same events
```

Color is a presentation mapping, not stored on vocabulary. The Reader should offer a legend and not rely on color alone. A reanalysis preview must show token/lemma changes before it rewrites unlocked mappings.

## 12. Anki integration strategy

AnkiConnect runs a local HTTP server (normally on `127.0.0.1:8765`) while the Anki desktop app is open. Call it from the Python backend, not directly from browser code. This avoids browser CORS differences, keeps an optional API key out of client JavaScript, and centralizes timeouts/error handling.

### Capability-first adapter

The adapter should probe `version` and supported behavior rather than hard-code assumptions. The official API provides note creation, candidate preflight, note search/detail/update, tags, and card metadata operations such as `addNote`/`addNotes`, `canAddNotes`, `findNotes`, `notesInfo`, `updateNoteFields`, `addTags`, and `cardsInfo`. Review-history import should be enabled only when the connected version exposes a tested action.

### Duplicate prevention

1. Configure a dedicated deck/model and map required fields in Language Settings.
2. Put a stable local key such as `dashboard_language_lemma_id` in a dedicated note field when possible and a namespaced tag as fallback.
3. Check the existing local link, then `notesInfo`; if broken, search by stable field/tag with `findNotes`.
4. Preflight new notes with `canAddNotes`.
5. Keep a unique local `(lemmaId, templatePurpose)` link and never infer identity from the visible front text alone.
6. Store a field hash. If both local projection and Anki changed, mark a conflict instead of overwriting either side automatically.

### Sync policy

- Manual preview/dry-run first; explicit commit second.
- Local database owns lemma/context/translation content.
- Anki owns scheduling and card state.
- Pull card snapshots and useful review aggregates; feed them into knowledge evidence conservatively.
- Do not call AnkiWeb `sync` automatically. If added later, expose it as a separately confirmed action because Anki may be editing or syncing elsewhere.
- A missing/offline Anki instance is a normal status, not an application failure.

## 13. AI integration strategy

Define a backend `GenerationProvider` protocol and at least a deterministic fake for tests. A configured provider receives a typed request and returns text plus provider metadata; it cannot write domain state.

Provider configuration belongs in environment variables and language settings:

- provider ID and model ID;
- secret/API key in `.env.development` or the provider's local runtime, never in SQLite responses or browser storage;
- base URL only from a server allowlist/environment, not an arbitrary request URL;
- connect/read timeouts, maximum response bytes, retry policy, and optional cost metadata.

The first implementation may support the Synchrobook-style manual workflow (copy prompt, paste structured response) as a safe fallback, but the architecture must also support a direct configured provider. Both paths run identical schema validation and post-generation analysis.

Store prompt/coverage policy/analyzer versions and content fingerprints. Do not send personal notes, full histories, or unrelated contexts by default. Escape generated content during rendering and impose length limits.

## 14. Listening and TTS strategy

Phase 10 uses a language-specific browser speech adapter modeled after the dependency-injected `AudioNotifier` pattern, but does not reuse that class because it hard-codes Polish workout behavior.

- request a `nb-NO` voice and expose available voice/rate selection;
- show an unsupported/no-Bokmål-voice state;
- support read+listen, listening-only, current-sentence highlight, replay, pause, and cancellation;
- record actual active listening milliseconds and sentence/lemma exposures through the shared service and canonical `study_sessions`/`exposure_events` facts;
- do not infer that audio played merely because `speak()` was called; use start/end/cancel events where supported.

Phase 8 already supplies server-generated, deterministically cached Google Cloud `nb-NO` MP3 for accepted generated Reader sentences, reused from the Cloze audio path. Phase 10 preserves that path and uses browser speech only for ordinary analyzed Reader text. Browser-generated audio is never stored. Listening activity/progress remain separate from Reader activity/progress; a displayed modality sum is explicitly non-unique because Read + Listen can overlap. Phase 11.5 adds fixed Listening benchmark tasks in a separate assessment domain; dictation and Shadowing remain optional future extensions, and activity time never becomes a proficiency claim.

## 15. Cloze, reviews, and grammar flows

### Cloze

Start deterministically from real Reader sentences. Rank learning/weak/underexposed lemmas, select a sentence with enough surrounding known vocabulary, mask an exact token span, and snapshot accepted answers. The attempt updates recall evidence for the same lemma. AI-generated alternatives are optional and always marked/analyzed.

### Reviews

The Reviews view is an orchestrator, not a second scheduler. It shows Anki due status when available and dashboard recycling suggestions (cloze, reread, listen) from `LearningPlanService`. No independent SM-2/FSRS implementation should be added initially.

### Grammar mining

Run dependency parsing only as a separately requested Grammar analysis after measuring its cost; normal Reader analysis remains independent and no runtime model download is allowed. Bokmål-specific detectors emit versioned candidates mapped to exact canonical spans, fail closed on divergence, and are classified `SUPPORTED`, `EXPERIMENTAL`, or `DEFERRED` using positive and hard-negative fixtures. The user can `CONFIRM` or `REJECT` detector quality. Active Phase 11 uses `DISCOVERED` and `ENCOUNTERED`; grammar mastery, deeper practice/diagnostics, and B2+ expansion are optional future work.

## 16. Statistics strategy

All metrics must publish a definition and rule/source version.

- Total lemmas: count non-merged, non-excluded vocabulary records by state.
- New vocabulary over time: knowledge transition events, not current `firstSeen` guesses.
- Exposures: summed `ExposureEvent.occurrenceCount`, grouped by source.
- Reading/listening time: active duration from study sessions, not wall-clock time while a tab is idle.
- Streak: distinct local study dates with qualifying activity, using the configured time zone.
- Retention/review performance: cloze attempt results plus Anki review aggregates, shown separately and combined only under an explicit rule.
- Top-N coverage: known weighted/unique lemmas over the versioned frequency band's mapped denominator, with unresolved counts.
- Topic mastery: weighted knowledge of `TopicLemma` rows.
- Reading coverage trend: coverage snapshot at session completion, not re-evaluated with today's knowledge unless labeled “current re-score”.
- Status movements: append-only knowledge events.

Start with direct SQL queries and tested pure aggregation helpers. Add daily rollup tables only after profiling. Rollups are rebuildable caches with a rule version, never the sole copy of facts.

Charts should follow existing SVG/DOM patterns: compact labels, tabular numbers, tooltips/focus targets, an empty state, and a textual summary for accessibility.

## 17. Settings architecture

Language `#settings` should own:

- active language profile and translation locale;
- analyzer health/version and model provisioning status;
- knowledge/coverage policy version and visible legend;
- frequency and dictionary source selection/provenance;
- Anki URL status, optional key (server environment), deck/model/field mapping, and sync controls;
- AI provider/model availability, privacy summary, and generation defaults;
- TTS voice/rate and whether listening counts as vocabulary exposure;
- goal week start/time zone;
- export/backup actions.

Settings stored in SQLite should be typed and normalized by the service. Secrets remain server-side. Avoid adding all of these to the already duplicated dashboard Settings page/modal.

## 18. Testing strategy

### Deterministic unit tests

- Unicode/display normalization and exact offsets.
- Norwegian fixture tokenization, POS, lemmas, morphology, ambiguity, and manual locks.
- lemma/form upsert, merge, redirect, and collision behavior.
- knowledge transition rules and protection of manual overrides.
- coverage classification, ignored/excluded policy, short-text tolerance, and target budgets.
- target-word ranking and today's plan.
- cloze selection/answer normalization.
- statistics, streaks, frequency bands, topic mastery, and time-zone edges.
- hash route parsing/formatting and client view models.

### Store/migration tests

- initialize every supported schema version into a temporary DB;
- migrate representative old fixtures forward without data loss;
- verify foreign keys, unique constraints, transaction rollback, and idempotency;
- merge a lemma and confirm all forms, tokens, exposures, topics, contexts, cloze, and Anki links still resolve;
- concurrent read plus serialized write smoke test under WAL;
- versioned JSON export round trip.

### Adapter contract tests

- fake analyzer, AI, dictionary, frequency, TTS, and Anki adapters;
- recorded/synthetic AnkiConnect responses for offline, error, old capability, duplicate, conflict, and success states;
- AI malformed JSON, prompt refusal, timeout, oversized text, coverage miss, successful revision, and exhausted-revision warning;
- no network calls in ordinary unit tests.

### API and UI tests

- ephemeral `DashboardHTTPServer` route tests using a temporary Language service;
- origin/write authorization and payload-limit tests;
- `happy-dom` tests for view navigation, accessible status controls/dialogs, filters, Reader token actions, and loading/error/empty states;
- build smoke test for `language.html` and main dashboard lazy loading;
- manual checks at dashboard mobile/desktop breakpoints and with reduced motion.

## 19. Migration and backward compatibility

There is no existing canonical language vocabulary store to migrate. That simplifies database creation but does not remove integration risks.

- Keep existing Reading, Synchrobook, Kitchen Clozemaster URL, and Anki data untouched.
- Do not reinterpret the existing `kitchen.clozemasterUrl` setting as language progress. It may remain a shortcut or later link into Language Cloze.
- Anki import must be preview-only first and must not update/delete existing notes during discovery.
- If importing a CSV/JSON/Anki deck, write an `ImportRun` with source hash, mapping/version, counts, warnings, and rollback boundary.
- Never make analyzer upgrades automatic. Reanalysis is previewable and skips manually locked mappings.
- Once the dashboard widget is added, preserve its `data-widget` key and default visibility/order behavior.
- Preserve existing API routes, localStorage keys, and database schemas outside this feature.
- Keep Synchrobook integration outside the active roadmap. If separately authorized later, use an adapter/API contract with stable external references and never attach to its internal tables/files.

## 20. Major risks and unknowns

| Risk/unknown | Impact | Mitigation |
| --- | --- | --- |
| Bokmål lemmatizer errors and homographs | Wrong merges corrupt every downstream module. | Fixture benchmark, analyzer provenance/confidence, ambiguity state, manual locks, merge/undo tools, no silent fallback. |
| Norwegian compounds/multi-word expressions | Lemma-only metrics can misrepresent what the user knows. | Preserve compounds, postpone guessed splitting, allow later phrase records alongside lemmas. |
| Frequency/CEFR/dictionary licensing and versioning | Data may be unusable or misleading. | Provider contracts, source attribution, nullable fields, license review before bulk import. |
| “Known” and coverage definitions | Difficulty numbers can look precise while meaning different things. | Versioned policy, raw counts, frozen generation snapshot, visible definition. |
| LLM prompt noncompliance | Generated text misses target coverage or invents data. | Structured validation, canonical reanalysis, bounded revision, warnings, no automatic knowledge mutation. |
| Anki availability and schema diversity | Anki must be open; user decks/models/fields differ. | Capability probe, configurable mapping, dry-run, stable IDs/tags, conflict state, explicit sync. |
| Dual ownership with Anki | Content or scheduling may be overwritten. | Written ownership matrix, hashes, no automatic scheduling writes, no automatic AnkiWeb sync. |
| `server.py` size/fragility | Many new inline routes would worsen maintenance. | Feature package with thin explicit handler branches; no unrelated server refactor. |
| SQLite backup gap | Git save tags do not protect study history. | JSON export and SQLite backup in the foundation phases; document restore. |
| Long NLP/AI work in request threads | UI timeouts and blocked server threads. | Persistent jobs, bounded payloads/timeouts, polling, startup recovery/cancel states. |
| Browser TTS variance | No `nb-NO` voice or unreliable timing on some devices. | Capability UI, selectable voice, conservative tracking, future server TTS adapter. |
| Event double counting | Refresh/retry inflates exposures and goal progress. | Client event IDs and database uniqueness/idempotency tests. |
| Large text/token volume | Slow reader payloads and statistics. | Store offsets, paginate vocabulary/history, lazy sentence windows, indexes, profile before rollups. |
| Privacy/cost | Personal contexts may leave the machine; generation can consume paid quota. | Server-only secrets, minimal prompt data, explicit provider/privacy display, request limits and provenance. |
| Multi-language abstraction overdesign | Delays a useful Bokmål system. | Preserve the existing generic contract and real Bokmål adapter; do not require a second-language proof for current completion. If Mandarin is later authorized, run a separate architecture spike against its actual needs. |

## 21. What should not be implemented yet

- No production page, widget, API, database, or provider code during this design phase.
- No broad `server.py`, `styles.css`, settings, or navigation refactor.
- No duplicate Reader-only or Anki-only vocabulary store.
- No dashboard SRS intended to replace Anki scheduling.
- No automatic AnkiWeb sync, destructive note cleanup, or silent update of user-edited Anki fields.
- No unreviewed bulk vocabulary import that treats each surface form as a lemma.
- No automatic model downloads triggered by an HTTP request.
- No direct browser exposure of AI/Anki secrets.
- No AI result accepted without schema validation and actual coverage analysis.
- No generated-text exposure count before a real study session.
- No guessed compound splitting, CEFR inference presented as fact, or arbitrary topic percentages.
- No grammar mastery system in the active roadmap; Phase 11 is limited to defensible `DISCOVERED` and `ENCOUNTERED` evidence.
- No new server TTS, dictation, Shadowing, Pronunciation technology/scoring, social features, or mobile sync as active remaining-roadmap work unless separately authorized.
- No second target language in the active roadmap. Mandarin Chinese is the possible future language and requires its own separately authorized architecture spike; it is not a completion requirement.

## 22. Primary external references used for provider decisions

- [AnkiConnect official repository and API documentation](https://github.com/amikey/anki-connect)
- [Stanza available models and processors](https://stanfordnlp.github.io/stanza/available_models.html)
- [Stanza pipeline/processor contract](https://stanfordnlp.github.io/stanza/pipeline.html)
- [Norwegian UD Treebank at the National Library of Norway](https://www.nb.no/sprakbanken/en/resource-catalogue/oai-nb-no-sbr-83/)
- [wordfreq official repository](https://github.com/rspeer/wordfreq)
- [Simplemma official repository](https://github.com/adbar/simplemma) (fallback candidate only)

## 23. Phase 7.8 curriculum boundary

Curated curricula are immutable, reference-like manifest artifacts, not user learning rows. Each pack identity is `(pack_id, version)` and includes a semantic fingerprint, language, status, source/version/license/attribution, membership rule, mapping snapshot, per-item review/mapping state, stable membership IDs, and optional priority/weight. Existing versions remain addressable; a denominator or membership change requires a new version.

Runtime ownership is deliberately narrow:

- `CurriculumService` owns manifest validation, pack lookup, transparent quality counts, and derived progress.
- `VocabularyLemma` and `LemmaKnowledge` remain the only canonical user lexical state. Curriculum browsing performs exact bounded reads and never materializes an absent lemma.
- `UNSEEN` is absence of a user lemma; `NEW` is an existing lemma with canonical `NEW` knowledge. `KNOWN` and `MASTERED` are separate states but both satisfy the versioned `KNOWN_OR_MASTERED` acquisition rule.
- Only `APPROVED + MAPPED` membership enters the eligible denominator. `AMBIGUOUS`, `UNRESOLVED`, `EXCLUDED`, draft, and rejected counts remain visible.
- Reference lexical units help resolve identity and present read-only evidence; they are not user knowledge and are not curriculum membership by themselves.
- Phase 7.6 Collections may present the same derived pack progress and tier. Campaign milestones pin pack ID/version/fingerprint and read that historical version. They cannot write knowledge or create a composite readiness claim.
- Topics remain mutable partial user groupings, Phrasebook remains saved expression context, and Anki remains the sole scheduler/SRS.

The source/manifests are tracked outside both SQLite domains, so Phase 7.8 requires no migration or backup of a changed schema. Production contracts, exact policies, and recovery/validation commands are documented in `LANGUAGE_CURRICULUM_SOURCES.md` and `LANGUAGE_PHASE7_8_RESULTS.md`.

## 24. Current future-planning and completion boundary

This section updates future scope only. The implemented architecture and ownership above remain authoritative: `VocabularyLemma` is canonical user lexical identity, `LanguageService` is the mutation boundary, Anki owns SRS scheduling, Reader/Listening/Cloze retain their evidence, and the reference database remains separate and read-only.

The active remaining dependency chain is:

```text
Phase 10.5 COMPLETE
        |
        v
Phase 11 — Core Grammar A1–B1
        |
        v
Phase 11.5 — Progress Benchmarks
              + lightweight Norway Preparation
        |
        v
Phase 11.6 — Study Session Builder
        |
        v
Phase 12 — Operational Hardening
```

Phase 12 completed verified backup/restore, measured performance hardening, and security/degraded operation. It did not add a second-language proof or Synchrobook integration. Evidence is in [`LANGUAGE_PHASE12_RESULTS.md`](./LANGUAGE_PHASE12_RESULTS.md).

The subsystem completion gate requires practical Core Grammar, versioned raw benchmark progress, a bounded deterministic Study Session Builder, verified recovery, measured performance, safe degraded operation, and source-aware/versioned/tested data. Estimated CEFR, a Skill Tree, Advanced Grammar Expansion, Writing Practice, Speaking Practice, Shadowing, Pronunciation technology/scoring, Mandarin Chinese, Synchrobook integration, forced alignment, and Tier 3 n-grams remain optional, unscheduled, and separately authorized.

