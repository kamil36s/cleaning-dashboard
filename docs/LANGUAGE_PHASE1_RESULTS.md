# Language Learning Phase 1 results

Status: COMPLETE  
Date originally verified: 2026-09-15  
Recovery reconciliation verified: 2026-09-16  
Database schema version: 1  
Export contract: `language-learning-export/v1`

## 1. Outcome

Phase 1 adds one canonical Language Learning database at `data/language-learning.sqlite`, an explicit migration ledger, a focused store/service boundary, thin routes in the existing dashboard server, a versioned JSON export, and WAL-safe SQLite backup.

No Language UI, navigation, analyzer execution, NLP job worker, external lexical import, AI, Anki write, Cloze, Listening, Grammar, Topics, Goals, or statistics implementation was added.

The schema is deliberately limited to 13 tables total: one migration ledger plus the 12 domain tables required by the initial slice. No speculative tables for later phases were created.

## 2. Migration strategy

`language_schema_migrations` records ordered versions with UTC application time and a SHA-256 checksum of the exact migration SQL. Initialization:

1. creates only the database parent directory;
2. opens an operation-scoped connection with foreign keys, a 15-second busy timeout, WAL, and normal synchronous mode;
3. validates recorded migration versions and checksums;
4. applies each missing migration in `BEGIN IMMEDIATE` / `COMMIT` as one transaction;
5. rolls back the migration on any SQLite error;
6. validates the required table set and current version.

Repeated initialization does not change the ledger. Unknown future versions and checksum mismatches fail without destructive recreation. The explicit version-0 fixture is a database with an empty migration ledger plus preserved unrelated marker data; it migrates forward without deleting that data. A deliberately failing DDL migration proved that both its created table and ledger row roll back.

## 3. Tables created

| Table | Phase 1 purpose |
| --- | --- |
| `language_schema_migrations` | ordered version/checksum ledger |
| `language_profiles` | target language, locale, analyzer and reference-provider configuration status |
| `vocabulary_lemmas` | canonical lexeme identity and merge redirect |
| `surface_forms` | normalized/display surface forms without duplicated knowledge |
| `form_lemma_links` | many-to-many candidate mappings, provider evidence, nullable confidence, ambiguity/lexical state, manual lock |
| `lemma_knowledge` | exactly one current user-learning snapshot per lemma |
| `knowledge_events` | append-only explanation/history of snapshot-changing commands and merges |
| `text_documents` | exact raw draft, fingerprint, source, state, and offset unit |
| `text_sentences` | exact code-point spans for later analyzed structures |
| `text_tokens` | exact token spans and nullable form/selected-lemma/provider evidence |
| `analysis_runs` | basic analyzer/contract/provenance history only; no job queue or worker |
| `study_sessions` | durable session core |
| `exposure_events` | aggregated, idempotent lemma exposures |

No settings, sense, translation, frequency-band, CEFR, topic, goal, statistics, activity-rollup, Anki, generation, job, cloze, grammar, or audio table exists in schema v1.

## 4. Important constraints and invariants

- Composite foreign keys enforce that form/lemma links, selected token lemmas/forms, document structures, sessions, and exposures remain inside one language profile.
- Lemma identity is `profile + normalized lemma + nullable POS`; morphology is not part of the key.
- A lemma cannot redirect to itself, and the redirect target must be in the same profile.
- A surface form can retain multiple lemma candidates.
- `lemma_knowledge.lemma_id` is the primary key, so forms never produce extra knowledge rows.
- Knowledge scores are nullable integers from 0 through 5; status and disposition are checked enums.
- Manual mapping locks require explicit `MANUAL` provenance and a manual provenance value.
- Automated mapping refresh cannot overwrite an existing manual lock.
- Automated knowledge updates cannot overwrite manually overridden status/disposition or scores.
- `knowledge_events` has database triggers rejecting update and delete.
- Exposure idempotency is unique per `(language_profile_id, idempotency_key)` and snapshot/event updates share the same transaction.
- Text, sentence, and token offset units are constrained to `UNICODE_CODE_POINT`.
- Confidence remains nullable; default analyzer evidence uses `NOT_REPORTED` ambiguity and `NOT_ASSESSED` lexical status.

## 5. Lemma merge behavior

`LanguageService.merge_lemmas` validates distinct, existing lemmas in the same profile and delegates one SQLite transaction that:

- moves or de-duplicates form mappings while preserving the stronger manual lock;
- repoints selected token lemmas and exposure rows;
- combines the two current knowledge snapshots without double-counting the same row;
- preserves manual flags, scores, exposure totals, and user notes;
- removes only the obsolete source snapshot, not the source lemma;
- marks the source lemma with `merged_into_id`;
- appends a `LEMMA_MERGED` audit event on the target.

Historical knowledge events remain attached to their original lemma and are not mutated. They continue to resolve through the retained source lemma redirect. A synthetic trigger failure during token repointing proved complete rollback of links, tokens, knowledge, redirect, and audit insertion.

## 6. Service operations implemented

- initialize the store and explicitly/idempotently ensure the Norwegian Bokmål profile;
- create/list/get/update language profiles;
- create/upsert canonical lemmas and surface forms;
- create/update candidate mappings and manually lock a mapping;
- manually update knowledge status, disposition, recognition, recall, and production;
- protect manual mapping and knowledge evidence from automated refresh hooks;
- get lemma detail and server-paginated profile vocabulary search by lemma/form, status, and disposition;
- transactionally merge lemmas;
- create/get an exact text draft without analysis;
- persist already-produced synthetic/analyzer sentence/token/history structures at the store boundary without invoking an analyzer;
- create idempotent study-session core records and idempotent aggregated exposures;
- produce the versioned export and internal SQLite backup;
- report safe health metadata.

Only the service is wired to HTTP as the public mutation boundary.

## 7. API routes implemented

All responses use either `{ "ok": true, "data": ... }` or `{ "ok": false, "error": ..., "code": ..., "details": [...] }`. Existing same-origin/write authorization is reused, and Language authorization failures use the same feature envelope.

| Method | Route | Behavior |
| --- | --- | --- |
| `GET` | `/api/language/health` | safe schema/analyzer/reference-provider summary; no model load |
| `GET`, `POST` | `/api/language/profiles` | list/create profiles |
| `GET`, `PATCH` | `/api/language/profiles/{id}` | profile detail and Phase-1-safe edits |
| `GET` | `/api/language/profiles/{id}/vocabulary` | bounded deterministic search/filter/pagination |
| `GET`, `PATCH` | `/api/language/lemmas/{id}` | detail and controlled lemma/knowledge edits |
| `POST` | `/api/language/lemmas/merge` | transactional manual merge |
| `POST` | `/api/language/texts` | save an exact draft only, with request and raw-text size limits |
| `GET` | `/api/language/texts/{id}` | draft plus any stored structural/history rows |
| `GET` | `/api/language/export` | versioned Language-only JSON export |
| `POST` | `/api/language/backup` | internal controlled SQLite backup; client paths rejected |

No analyze, job, generate, Anki, Cloze, Listening, Grammar, Topic, Goal, or statistics route exists.

## 8. Backup and export

The JSON export contains schema/export versions, generation timestamp, the offset unit, and all 12 Phase 1 domain tables in stable ID order. It preserves profile relationships, canonical IDs, reference provenance, exact Unicode source text, knowledge history, and idempotency keys. Restore/import is intentionally absent.

The backup operation uses Python's SQLite backup API against the live WAL database, writes only to the store-controlled `data/backups/` directory, uses a schema-versioned timestamped filename, and runs `PRAGMA integrity_check` before reporting success. The API returns only the filename, schema version, and timestamp; it never returns a filesystem path or accepts a destination.

## 9. Frozen Phase 0 behavior

The canonical analyzer remains `stanza-nb-bokmaal`, adapter `1.0.0`, Stanza/resources `1.14.0`, processors `tokenize,pos,lemma`. Health reports this configuration as `NOT_CHECKED_PHASE_1`; it does not instantiate Stanza or check/download a model.

Normal Phase 1 server import/startup, health, profile, vocabulary, lemma, text, export, and backup paths do not import the `stanza` package or instantiate the adapter. Text save/load performs no analysis. Simplemma is not used as fallback.

Exact ranked frequency, dictionary/senses, translations, CEFR, and lexical relations remain unselected and have no populated schema fields or imported data. No Zipf score was converted into a rank.

## 10. Verification results

| Command/check | Exact result |
| --- | --- |
| `python -m unittest tests.test_language_store tests.test_language_services tests.test_language_api -v` | 30 tests passed, 0 failed |
| `python -m unittest tests.test_language_analysis tests.test_language_diagnostics -v` | 20 Phase 0 tests passed, 0 failed |
| `python -m unittest tests.test_reading_api tests.test_server_startup -v` | 26 existing regression tests passed, 0 failed |
| production-path import + Language initialization/seed with `sys.modules` assertion | passed; `stanza` was not imported |
| explicit seed `python scripts/seed_language_profile.py` | passed idempotently; one `nb` / `nb-NO` profile |
| canonical DB `PRAGMA integrity_check` | `ok`; 13 tables; one profile |
| Python compilation for `server.py`, `language_learning/`, and seed script | passed |
| static scope check | no `language.html`, `language.css`, `js/language/`, language widget, or navigation addition |

The existing environment still emits the documented Phase 0 `requests` dependency warning during the real Stanza test. It does not affect Phase 1.

### Recovery reconciliation (2026-09-16)

After the unrelated repository recovery, the surviving `language_learning/` implementation and the current recovered `server.py` were compared against this result document. The complete thin Phase 1 integration had survived: imports, store/service construction, Language error envelopes and authorization responses, all documented GET/POST/PATCH routes, and startup initialization plus the explicit Bokmal seed. No Language application or server code needed restoration.

Current verification results:

| Command/check | Exact result |
| --- | --- |
| `python -m unittest tests.test_language_store tests.test_language_services -v` | 21 tests passed, 0 failed |
| `python -m unittest tests.test_language_api -v` | 9 tests passed, 0 failed |
| `python -m unittest tests.test_language_analysis tests.test_language_diagnostics -v` | 20 Phase 0 tests passed, 0 failed |
| `python -m unittest tests.test_reading_api tests.test_server_startup -v` | 26 existing regression tests passed, 0 failed |
| `python -m unittest discover -s tests -p "test_*.py" -v` | 395 backend tests passed, 1 skipped, 0 failed |
| `npm run test:run` | 623 frontend tests passed, 2 skipped, 0 failed |
| `npm run build` | passed |
| Python compilation plus `server` import | passed |
| JavaScript syntax check | 326 files passed |
| canonical database verification | schema v1; 13 tables; migration ledger version 1; `integrity_check = ok`; zero foreign-key violations; one `nb` / `nb-NO` profile |
| production-path import, initialization, health, export, and backup with `sys.modules` assertion | passed; `stanza` was not imported |
| versioned export JSON round trip | passed; `language-learning-export/v1` with 12 domain table collections |
| controlled SQLite backup open/integrity/FK verification | passed; `language-learning-v1-20260916T093345000262Z.sqlite`, `integrity_check = ok`, zero foreign-key violations |
| static scope check | no `language.html`, `language.css`, `js/language/`, language widget, navigation addition, analysis route, or Phase 2 worker |

The recovery request's pre-checkpoint summary referred to 8 Language API tests and a 394-test backend baseline. The surviving/current suites contain one additional Language API test, so the reconciled counts are 9 API tests, 30 total Phase 1 tests, and 395 backend tests. This is a verification-count update, not a scope or behavior deviation.

## 11. Deviations from the architecture

- The architecture's conceptual “profiles/settings” slice is represented by typed profile columns plus two small configuration JSON objects. A separate settings table was intentionally not added before settings behavior exists.
- Schema v1 does not add nullable frequency rank, dictionary, translation, or CEFR columns merely as placeholders. Those fields should arrive with the selected provider and migration in the phase that uses them; provider status remains explicit and unselected.
- There is one `analysis_runs` history table rather than separate analysis-job and import-run tables. Phase 1 has no jobs/import execution, so additional tables would be speculative.
- Session and exposure mutations exist in the service/store but are not exposed as HTTP routes yet. The implementation plan assigns interactive session/exposure routes to Phase 4; exposing them without a Reader client would expand Phase 1 unnecessarily.

These are scope reductions, not changes to the shared identity, source-boundary, offset, or analyzer contracts.

## 12. Known limitations

- There is no production restore/import. JSON export and SQLite backup are recovery artifacts only until a previewable restore flow is designed.
- Search uses a bounded offset cursor encoded as a decimal string. It is deterministic but may later move to a keyset cursor after real-volume profiling.
- Basic analysis history and analyzed structures can be stored only from trusted backend/store code; no Phase 1 HTTP route produces them.
- No reference provider is selected for exact ranks, dictionary content, translations, CEFR, or lexical relations.
- Knowledge rules beyond manual state/scores and exposure totals are postponed; there are no derived weak/recent/passive/active flags or rollups.
- Backup retention/cleanup policy is postponed. Phase 1 creates backups only on explicit request.

## 13. Acceptance criteria

All 16 Phase 1 acceptance criteria in the implementation request passed. In particular, four Bokmål forms point to one lemma/knowledge row, ambiguous candidates coexist, manual overrides survive refresh, merge rolls back atomically, retries do not double-count exposure, exact Unicode/code-point spans survive, Stanza is absent from Phase 1 runtime paths, export/backup are valid, and no UI or external lexical data was added.

## 14. Exact recommendation for Phase 2

Proceed with Phase 2 only: persisted Bokmål analysis/text-ingestion jobs using the frozen `language.analysis/v1` contract and the existing schema v1 identities. Add an analyzer registry and selected `wordfreq` Zipf provider behind explicit provenance, analyze drafts outside HTTP request threads, persist sentence/token results transactionally, keep ambiguity and manual locks intact, and add reanalysis preview before committing changes. Do not start the Language UI, Reader, Anki, AI generation, Cloze, Listening, Grammar, Topics, Goals, or statistics during Phase 2.
