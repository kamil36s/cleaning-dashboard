# Language Learning

## Identity and verification

- ID: `language-learning`; display: Language Learning (current Norwegian Bokmål focus); domain: language study.
- Status: current SQLite-backed feature with offline deterministic NLP, optional generative AI, external Anki and TTS, and a durable worker. Reviewed 2026-09-24 at HEAD `294c1925f387` plus dirty working-tree source. L0: `PROJECT_MAP.md` Language Learning, Workers, AI/ML, Persistence.
- Current behavior claims below are **verified implementation** unless marked otherwise. No user DB/reference corpus/audio content was opened.

## Purpose and boundaries

The subsystem owns profile-scoped vocabulary identity, texts and exact token evidence, user knowledge/progress, Reader/Listening/Cloze/Curriculum/Grammar/Statistics/Benchmarks, generation requests and candidates, and language jobs. `LanguageService` is the mutation/validation boundary; `LanguageStore` owns canonical SQL and migrations. Anki owns its scheduler and card due state; the dashboard stores links and observed metadata. Reference data gives external lexical evidence and never creates user knowledge or exposures. Generated audio is a cache, not the source of text or progress. Generative AI can propose text; deterministic analysis and user acceptance decide whether it enters Reader.

## Frontend

| Surface | Entry / owner | State and actions |
| --- | --- | --- |
| Full page | `language.html` -> `js/language/app.js`, `router.js`, `state.js`, `views/*` | Hash routes include overview/progress/benchmarks/study-session/curriculum/inbox/reader/listening/vocabulary/phrasebook/topics/reviews/cloze/generate/grammar/statistics/goals/settings. `js/language/api.js::createLanguageApi` owns JSON requests/errors. Views render loading, empty, unavailable, and review states for their own contracts. |
| Dashboard | `index.html::data-widget="language-learning"` -> `js/dashboard-widget-loader.js::widgetLoaders["language-learning"]` -> `js/widget-language-learning.js` | Starts hidden by dashboard visibility; `initLanguageLearningWidget` loads profiles, picks `nb/nb-NO`, else active/first, then `widget-summary`. Busy attribute, no-profile and API-error text are explicit. Links navigate to the page. |

The widget is read-only. Page reads include browsing texts/lemmas/analytics, previews, and health; mutations include profile/text/knowledge edits, analysis enqueue/cancel, study events, Anki commit/pull/link, Cloze attempts, generation accept/reject, curriculum/study/benchmark responses, and audio generation. `js/language/app.js` uses browser-only keys `language.generation.active-request.v1` (resume UI selection), `language.cloze.preferences.v1`, and `language.listening.preferences.v1`; these are not the knowledge database. `js/language/router.js::parseLanguageRoute` validates known hash routes/IDs.

## Backend and API

At server startup, `server.py` constructs `LANGUAGE_STORE=LanguageStore(data/language-learning.sqlite)`, `LANGUAGE_SERVICE=LanguageService`, a separate reference lexicon service, Cloze services, generated audio service, and `LANGUAGE_JOBS=LanguageJobManager`. Startup calls `LANGUAGE_SERVICE.initialize()` and `LANGUAGE_JOBS.start()`; shutdown calls `stop()`. `server.py` handles the `/api/language/*` route branches. `LanguageService._response` owns the standard `{ok:true,data:...}` envelope; `js/language/api.js::request` checks HTTP and envelope status and turns failures into `LanguageApiError`.

| Methods + representative routes | Owner / capability |
| --- | --- |
| GET `/api/language/health`, `/reference/health`, `/generation/provider-health`, `/profiles`, `/profiles/{id}/overview`, `/widget-summary`, `/statistics`, `/texts`, `/lemmas/{id}`, `/jobs/{id}` | Read through `LanguageService`; profile ID and query validation precede store access. |
| GET `/api/language/profiles/{id}/curriculum`, `/benchmarks`, `/cloze/tracks`, `/listening`, `/grammar`; GET `/generation-requests/{id}/context-pack`, `/candidates`; GET `/audio/{hash}.mp3` and `/cloze/audio/{hash}.mp3` | Read projections or controlled cached audio file responses. |
| POST `/api/language/profiles`, `/texts`, `/texts/{id}/analyze`, `/jobs/{id}/cancel`, `/generation-requests`, `/generation-requests/{id}/automatic|cancel`, `/generation-candidates/{id}/analyze|accept|reject` | Mutations through service/store; analysis and generation are queued or reviewed, not accepted implicitly. |
| POST `/api/language/profiles/{id}/anki/*`, `/cloze/sessions`, `/cloze/sessions/{id}/attempts`, `/benchmarks/{id}/responses|complete`, `/texts/{id}/listening-sessions`, `/content/*` | Profile-scoped user mutations and external adapter actions. Exact method/shape is set by `server.py` branches and `js/language/api.js`. |

The central API is the sole browser mutation path; frontend components do not connect to SQLite, Stanza, Gemini, AnkiConnect, or Google TTS directly. Private DB/reference/audio paths and benchmark answer material have direct static serving denies in `server.py`/`vite.config.js`. Route existence is not Kermit authorization for runtime reads.

## Persistence and source of truth

| Artifact/entity | Owner | Role |
| --- | --- | --- |
| `data/language-learning.sqlite` | `LanguageStore` | **Canonical user state:** profiles, lemma/form links, knowledge snapshots/events, texts/sentences/tokens, progress/exposures/sessions, Anki links/snapshots, Cloze, generation requests/candidates, jobs, curriculum/benchmark evidence. `language_learning/migrations.py::SCHEMA_VERSION=16`; ordered migration SQL carries SHA-256 checksums in `language_schema_migrations`. |
| `data/reference/language-reference-nb.sqlite` (configurable by `LANGUAGE_REFERENCE_DB`) | `reference_core` build/store | **Generated/rebuildable reference data**, schema version 3. Independent from user DB; lexical/corpus/CEFR evidence with source/import provenance. No user knowledge state. |
| `data/reference/sources/`, external corpus artifacts/manifests | Offline reference builders | **Raw source / build input**, private and excluded from Kermit static knowledge. `reference_core.build::build_staging_database,validate_reference_database,publish_atomically` validates a staging DB and atomically replaces production. |
| `data/audio/language-learning/` | Cloze/generated-audio services | **Generated cache** MP3; hash-addressed response routes. Text and listening progress remain canonical SQLite facts. |
| `data/backups/` language copies | `LanguageStore.backup_database` and operations | **Backup** recovery points, not current state. |
| Three `language.*.v1` localStorage keys | `js/language/app.js` | **Browser-only** preferences/active request pointer, safely disposable relative to canonical DB. |

Legacy and migration input outside ordered SQLite migrations: **None identified in this pilot**. The current source of truth for a user's lemma/status/progress is the user SQLite DB; for reference lexicon facts, the rebuilt reference DB with manifests; for Anki scheduling, Anki itself. Generated text is a candidate until explicit acceptance; generation does not itself create exposure.

## Data flow and transformations

**Deterministic NLP.** A user creates/imports text under a profile. `LanguageService` validates the request and queues a versioned analysis job. `language_learning/analysis/norwegian_bokmal.py::NorwegianBokmalStanzaAnalyzer` loads only locally provisioned `nb` Stanza `tokenize`, `pos`, and `lemma` processors using `DownloadMethod.NONE`; absent packages/models are an explicit unavailable state. It preserves exact source offsets and original text, classifies nonlexical tokens, normalizes lookup without stripping Norwegian letters, records POS/morphology, candidate/resolution/ambiguity status and analyzer/model fingerprint. Proper names and abbreviations preserve display form; unresolved mappings remain unresolved. `LanguageStore.commit_analysis_job` atomically persists sentences/tokens/form-lemma evidence and frequency enrichment; it does not mark unseen words known. Reanalysis preview is nonmutating; commit respects manual locks and rejects stale previews (`tests/test_language_jobs.py`).

**User learning.** Manual status edits, Reader exposures, study sessions, Cloze attempts, listening events, Anki observations, and benchmark responses enter service validation then canonical tables/events. `vocabulary_lemmas` is the shared identity; `form_lemma_links` carry analyzer/manual provenance and morphology; `lemma_knowledge` and append-only `knowledge_events` distinguish current status from how it changed. Statistics and planning derive from these facts. `language_learning/coverage.py` computes text coverage against a knowledge snapshot, not from a generative claim. Rejected/unknown analysis stays draft/reviewable instead of inventing a lemma or proficiency.

**Generative AI.** `GenerationService` freezes knowledge snapshot, target/focus vocabulary, prompt/context versions, hashes/fingerprints, response shape, and provider/model policy in the request. Manual external-response import and optional automatic Gemini enter the same candidate path. The fixed server-side `GeminiGenerationProvider` requires `LANGUAGE_GEMINI_ENABLED`, `FREE_ONLY`, allowlisted model, and `GEMINI_API_KEY`; it sends a bounded JSON request with `responseMimeType: application/json` and `responseJsonSchema` requiring string `title/text` fields, then validates nonempty content locally. It records response, finish/usage/latency/attempt metadata. Candidate text is then analyzed by the **same deterministic Stanza analyzer** and coverage/target checks; failures may be revised within bounded attempts. Only explicit accept creates a Reader text. Gemini is not the lemma engine, source of knowledge state, or authority for measured difficulty. `PROJECT_MAP.md` says the provider lacks a literal `responseSchema` field; that remains literally true, but its wording omits the active `responseJsonSchema` field (L-01).

**Anki, Cloze, curricula, TTS/reference.** `language_learning/anki_sync.py` and `providers/anki.py` isolate AnkiConnect; local link/hash/conflict records protect owned vocabulary while Anki owns due/scheduling. `cloze.py` selects/grades sentence gaps and stores attempts; `cloze_audio.py` and `generated_audio.py` cache generated MP3 while `js/language/audio/browser-speech.js` offers browser speech for ordinary Reader text. `curricula.py` loads versioned source packs and maps to shared lemmas; `reference.py` performs read-only lexical lookup against the separate reference DB. Reference builders use manifests, source licenses/checksums, parser versions, row reject counts, deterministic IDs, validation, and staging promotion. External source content is not a user learning fact.

## Metrics and calculations

| Metric | Inputs/filter/date/rule | Null/units/version/test |
| --- | --- | --- |
| Widget Known and streak | `LanguageService.widget_summary` takes `overview.statistics.vocabulary.knowledgeCounts.known` and `statistics.streak.currentDays`; profile choice is `nb/nb-NO` then active/first. | Counts/days, 0 display fallback; `tests/widget-language-learning.test.js`, `tests/test_language_statistics.py`. |
| Widget active minutes 7d | `widget_summary` displays `statistics.reading.activeMinutes` from `LanguageService.overview`, which explicitly calls `StatisticsService.calculate(range_name="7d")`; calculation sums `active_seconds` of READER sessions in range and divides by 60, rounded 1 decimal. | Minutes, zero if no sessions. `tests/test_language_statistics.py`. |
| Knowledge counts | `StatisticsService.calculate` classifies profile lemmas, excludes `EXCLUDED` disposition, counts status `NEW/LEARNING/KNOWN/MASTERED`; `classify_lemma` also produces weak/recent/underexposed flags. | Counts; unknown status is not promoted to known. `tests/test_language_statistics.py`. |
| Reader exposure and time | `calculate` filters READER exposures and sessions by UTC event timestamp within selected `7d/30d/90d/all` bounds; local study days use configured `ZoneInfo` (default Europe/Warsaw). Occurrences sum `occurrence_count`, active minutes = summed active seconds / 60. | Counts/minutes; `modalitySumSeconds` is reader seconds + listening milliseconds/1000 and is explicitly nonunique when modes overlap. `tests/test_language_statistics.py`. |
| Topic mastery | `statistics.py::topic_mastery`: for each mapped lemma, multiply its topic weight by status factor NEW=0, LEARNING=0.35, KNOWN=0.75, MASTERED=1; percent = sum(weight * factor) / sum(weights) * 100. | Null when total weight 0; 1 decimal, `TOPIC_MASTERY_POLICY_VERSION`. `tests/test_language_statistics.py`. |
| Weekly goal | `StatisticsService.goal_progress` computes current by goal type/window, remaining=max(0,target-current), percentage=min(100,current/target*100). | Percent 1 decimal; exact goal-type inputs are in `goal_progress` and tests. `tests/test_language_statistics.py`. |
| Level | `gamification.py::level_from_xp,level_floor` map lifetime XP to versioned level thresholds; widget displays XP into current level and needed for next. | XP count; `tests/test_language_gamification.py`. |

These are derived read projections, not a second canonical metric store. A future answer about a specific metric subtype should retrieve its named calculation symbol; this pack does not flatten all curriculum, benchmark, grammar, and gamification rules into one formula.

## Jobs and recovery

`LanguageJobManager` runs one daemon worker, default `max_pending_jobs=100`, `max_recovery_attempts=3`, idle poll 0.25 s. It claims analysis first, then automatic generation requests, then candidate analysis. Analysis jobs have persisted QUEUED/RUNNING/stage/progress/attempt/cancel fields; claiming increments attempt. Cancellation is cooperative before commit. A stop during model analysis leaves RUNNING for next startup. `initialize` requeues interrupted RUNNING work below attempt limit, cancels work already flagged, and fails exhausted work; generation candidate and automatic request recovery are separate store methods. Candidate analysis is bounded to three recovery attempts; automatic generation interrupted requests are requeued/cancelled per stored state. No generic exponential job backoff is visible in `jobs.py`; Gemini transport retries at most twice for defined transient errors, while quota/auth/429 states stop. `tests/test_language_jobs.py::test_restart_recovery_requeues_cancels_and_bounds_retries` and `test_worker_stop_leaves_running_job_for_restart_recovery` cover the lifecycle.

## Integrations, failure and privacy

| Boundary | Direction / credential owner | Degraded behavior |
| --- | --- | --- |
| Offline Stanza Bokmål | Python analyzer reads locally provisioned model files; no runtime download | Missing package/model returns unavailable and leaves draft/recoverable job. |
| Gemini | Server -> fixed Google endpoint; `GEMINI_API_KEY` stays server-side | Disabled/missing/free-policy mismatch explicit; bounded prompt/response/time/attempts, no paid fallback. |
| AnkiConnect | Server-side adapter -> local Anki; Anki owns scheduling | Offline Anki is a status, not global Language failure; conflicts require resolution. |
| Google Cloud TTS and browser speech | Server generated/cached audio or browser speech, respectively | Missing provider/audio does not rewrite text/progress; browser speech is not stored. |
| Reference sources | Offline build -> separate reference DB; runtime read-only lexicon service | Missing reference DB limits enrichment, not canonical user knowledge. |

User texts, study history, generated prompt/context/response, Anki metadata, audio and reference source artifacts are private; Kermit did not inspect them. API route presence does not grant Kermit runtime access. The frontend API uses `cache: no-store`; direct private file serving is denied. No static L1 source should contain a real profile, prompt, token, text, or provider key.

## Tests and evidence

Focused contracts: `tests/test_language_store.py` and `test_language_backup.py` (user DB/migrations/backup); `test_language_analysis.py` and `test_language_jobs.py` (offline Stanza, offsets, unresolved states, atomic commit/recovery); `test_language_generation.py` and `test_language_generation_provider.py` (frozen request, provider bounds, candidate analysis/acceptance); `test_language_reference_ingestion.py` and `test_language_reference_service.py` (rebuild/provenance/isolation); `test_language_anki.py`, `test_language_cloze.py`, `test_language_curricula.py`, `test_language_statistics.py`; JS `tests/language-api.test.js`, `language-page.test.js`, `widget-language-learning.test.js`. No tests were executed because application logic was untouched.

Implementation locators: `server.py::LANGUAGE_SERVICE,LANGUAGE_JOBS,/api/language/*`; `language_learning/service.py::LanguageService.overview,widget_summary`; `language_learning/store.py::LanguageStore.initialize,commit_analysis_job,recover_analysis_jobs,recover_generation_candidates`; `language_learning/migrations.py::SCHEMA_VERSION,apply_migrations`; `language_learning/jobs.py::LanguageJobManager._run,initialize`; `language_learning/analysis/norwegian_bokmal.py::NorwegianBokmalStanzaAnalyzer`; `language_learning/generation.py::GenerationService`; `language_learning/providers/generation.py::GeminiGenerationProvider._request_once`; `language_learning/reference_core/build.py::build_staging_database,publish_atomically`; `language_learning/statistics.py::StatisticsService.calculate`; `js/language/api.js::createLanguageApi`; `js/widget-language-learning.js`. Current scoped docs: `docs/LANGUAGE_ARCHITECTURE.md`, `docs/LANGUAGE_REFERENCE_ARCHITECTURE.md` (intent and boundary; current code governs behavior). Known conflict/gap: L-01. Verification: 2026-09-24 working tree, source-only, no private data read.
