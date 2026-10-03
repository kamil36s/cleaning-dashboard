# Language Learning Phase 2 results

Status: COMPLETE  
Date verified: 2026-09-16  
Database schema version: 2  
Export contract: `language-learning-export/v2`

## 1. Outcome

Phase 2 adds backend-only, persisted Norwegian Bokmål analysis. Exact drafts are queued outside HTTP request threads, analyzed by the frozen Stanza adapter, enriched with provenance-bearing `wordfreq` Zipf scores, and committed transactionally into the shared Phase 1 vocabulary model. The same backend returns versioned token and unique-lemma coverage.

There is no Language page, CSS, client module, widget, navigation entry, Reader activity flow, Anki integration, AI generation, Cloze, Listening, Grammar, Topics, Goals, or statistics implementation.

## 2. Schema migration

Migration 2 is additive and keeps migration 1 unchanged. Schema v2 has 15 tables total.

Added tables:

| Table | Purpose |
| --- | --- |
| `language_jobs` | durable analyze, reanalysis-preview, and reanalysis-commit queue rows |
| `lemma_frequency` | Zipf score plus lookup/match/provider/version/retrieval/observation provenance |

Added `text_tokens` fields: `resolution_state`, `confidence_basis`, and `provenance`.

Added `analysis_runs` fields: `job_id`, `analysis_fingerprint`, `analysis_policy_version`, `frequency_provider_id`, `frequency_provider_version`, and `coverage_policy_version`.

Added indexes cover job queue order, text history, fingerprints, one active duplicate fingerprint, frequency lookup, and analysis-run fingerprints. No Phase 3+ tables were added.

The schema-v1 migration test creates real v1 structures and data, applies v2 in place, and verifies the original profile/text plus both migration ledger rows and zero foreign-key violations. The canonical v1 pre-migration backup remains `data/backups/language-learning-v1-20260916T093345000262Z.sqlite`. The verified post-migration backup is `data/backups/language-learning-v2-20260916T104336935060Z.sqlite`.

## 3. Analyzer registry and Stanza lifecycle

`AnalyzerRegistry` explicitly registers a stable analyzer ID/version with a factory. It constructs one adapter only on the first claimed analysis job and returns the same instance thereafter. The Bokmål adapter constructs its Stanza pipeline lazily and caches it on that instance.

Normal module import, Language initialization/profile seed, health, and an idle worker start do not import `stanza` or create a pipeline. Health distinguishes `LAZY_NOT_CREATED`, `INSTANCE_CREATED_PIPELINE_LAZY`, and `PIPELINE_READY` without returning a model directory. Pipeline creation continues to force `DownloadMethod.NONE`. Tests block `stanza.download`, Stanza resource/model download helpers, and network connection creation.

The generic job flow uses registry metadata and profile analyzer settings; it does not import or construct Stanza in an HTTP handler and does not create an adapter per job.

## 4. Durable job manager

`LanguageJobManager` owns one stoppable daemon worker and a bounded default of 100 pending/running jobs. A job row is committed before the worker is notified. Claiming is atomic and increments `attempt_count`.

States are `QUEUED`, `RUNNING`, `COMPLETED`, `FAILED`, and `CANCELLED`. `CANCELLING` is a stage on a still-running cooperative job, not a false claim that the model thread was interrupted.

Startup recovery is deterministic:

- `QUEUED` remains eligible;
- stale `RUNNING` with cancellation requested becomes `CANCELLED`;
- stale `RUNNING` below three attempts returns to `QUEUED`;
- stale `RUNNING` at three attempts becomes `FAILED` with `language_job_recovery_exhausted`;
- `COMPLETED`, `FAILED`, and `CANCELLED` never restart automatically.

Shutdown never kills a Stanza thread. If stop is requested during analysis, the worker does not commit when the model returns and leaves the durable row `RUNNING`; the next startup applies the recovery rule. Queued cancellation is immediate. Running cancellation is cooperative and prevents final persistence.

User-facing errors contain stable codes/messages only. Analyzer-unavailable failures do not expose model paths, stack traces, environment values, or database paths. A failed job is retryable through a new persisted job; failed rows are not reused as successful duplicates.

## 5. Analysis and persistence flow

1. Save exact `raw_text`, including whitespace and Unicode, as a draft.
2. Validate size/content/profile/analyzer configuration.
3. Fingerprint content, profile, analyzer settings/version, contract/policy/provider versions, and manual-lock snapshot.
4. Persist or reuse the durable job and return immediately.
5. Claim in the single background worker and obtain the cached analyzer.
6. Validate source fingerprint, language, analyzer ID/version, and analysis contract.
7. Look up Zipf scores lemma-first, with a documented surface fallback.
8. In one SQLite transaction, replace current sentence/token structure, reuse/upsert shared forms and lemmas, preserve mappings/manual locks, persist frequency and analyzer evidence, append an analysis run, set the document state, and complete the job.

`jobb`, `jobben`, `jobber`, and `jobbene` resolve to one `jobb / NOUN` lemma and one knowledge row. Ambiguous forms retain multiple candidates; unresolved words have no selected lemma and an explicit state. Analysis creates knowledge rows only in default `NEW` state. It creates no knowledge event, exposure, study session, Anki card, or learned/mastered state.

Failures before or inside the transaction leave no partial lexical/document result. Synthetic failures after analyzer output, during token insertion, and during the final job update were tested. Reanalysis failures preserve the prior committed token IDs/result and keep the document `ANALYZED`.

## 6. Frequency provider

`WordfreqFrequencyProvider` uses `wordfreq` 3.1.x with language code `nb`. It returns `ZIPF_FREQUENCY`, score, lookup term, provider ID/version, and retrieval version. Matching is lemma-first and falls back to the surface only when the lemma score is absent/non-positive.

No exact rank column exists in `lemma_frequency`; provider results with a non-null rank are rejected by the service. No Top 500/1000/2000/5000 band is inferred.

## 7. Coverage policy

`CoverageService` implements `language.coverage-policy/v1` and returns the frozen `language.coverage/v1` fields plus explicit diagnostic counts and denominator rules.

- `KNOWN` and `MASTERED`: covered;
- `LEARNING`: separate and uncovered;
- `IGNORED`: intentionally covered, while `ignoredTokens` remains visible;
- `EXCLUDED`: outside the denominator;
- ambiguous/unresolved lexical tokens: eligible and uncovered;
- punctuation and other non-lexical tokens: outside the denominator.

The primary percentage is token-weighted. Unique-lemma coverage is also returned. Reports include eligible, covered, learning, unknown, ignored, excluded, ambiguous, and non-lexical counts, plus the latest relevant knowledge snapshot timestamp. Hand-calculated all-known, all-unknown, mixed, repeated, ignored, excluded, unresolved, non-lexical, and empty cases pass.

## 8. Reanalysis

Reanalysis preview is a persisted job. It reports tokenization, lemma, POS, morphology, resolution, and protected manual-lock conflicts without mutating current sentences, tokens, analysis runs, or knowledge.

The full proposed analysis document remains internal in the preview job; public job responses remove it. Commit requires the completed preview ID, the same text, the same current base analysis run, and the same manual-lock fingerprint. A stale preview is rejected. Commit uses the stored preview output and does not run Stanza again.

Manual form-to-lemma locks are never overwritten. A locked selection records `selectionProvenance=MANUAL_LOCK`, `effectiveResolution=MANUAL_SELECTED`, the manual lemma ID, and whether the analyzer disagreed. The frozen database resolution enum has no `MANUAL_SELECTED` value, so the permitted selected-occurrence state remains `MODEL_SELECTED` while the effective/manual provenance is explicit in mapping evidence and token provenance. This is the smallest backward-compatible representation without changing the frozen Phase 0 analysis contract or the already-applied migration.

## 9. API routes added

All routes reuse existing authorization, bounded JSON reads, and Language error envelopes.

| Method | Route | Behavior |
| --- | --- | --- |
| `POST` | `/api/language/texts/{textId}/analyze` | persist/reuse job and return without waiting for NLP |
| `GET` | `/api/language/jobs/{jobId}` | poll safe state/stage/progress/result/error/timestamps |
| `POST` | `/api/language/jobs/{jobId}/cancel` | immediate queued or cooperative running cancellation |
| `GET` | `/api/language/profiles/{profileId}/texts` | bounded text history with latest job/analysis metadata |
| `POST` | `/api/language/texts/{textId}/reanalyze/preview` | queue non-mutating diff preview |
| `POST` | `/api/language/texts/{textId}/reanalyze/commit` | queue explicit commit from a valid preview |

Existing text detail now includes frequencies and current coverage. Health reports schema/provider/worker/lazy analyzer state. Export is `language-learning-export/v2` and includes the two new domain tables.

## 10. Verification results

| Command/check | Exact result |
| --- | --- |
| complete Language suite | 76 passed, 0 failed |
| Phase 0 suite (`test_language_analysis`, `test_language_diagnostics`) | 20 passed, 0 failed |
| Phase 1/2 store/service/coverage/job/API suites | 56 passed, 0 failed |
| real persisted Stanza job integration | passed; two jobs, one pipeline object, network/download helpers blocked |
| Reading/server startup regressions | 26 passed, 0 failed |
| `python -m unittest discover -s tests -p "test_*.py" -v` | 424 passed, 1 skipped, 0 failed |
| `npm run test:run` | 628 passed, 2 skipped, 0 failed |
| `npm run build` | passed; existing Vite warnings only |
| Python compilation for Language package/server/focused tests | passed |
| fresh production-path import/init/idle worker | passed; `stanza` absent from `sys.modules` |
| canonical database | schema v2; 15 tables; migration versions 1 and 2; 0 jobs |
| canonical `PRAGMA integrity_check` | `ok` |
| canonical `PRAGMA foreign_key_check` | zero violations |
| v1 and v2 controlled backups | both open; integrity `ok`; zero FK violations |
| export JSON round trip | v2; schema 2; 14 domain collections |
| static scope | no `language.html`, `language.css`, `js/language/`, widget, or navigation entry |

The known environment-level `requests` dependency warning still appears when Stanza imports, as documented in Phase 0. It did not cause a failure.

## 11. Measured worker/Stanza observations

Measured on this dashboard machine with a fresh temporary database, one worker, and network/download paths blocked:

| Observation | Result |
| --- | ---: |
| analyzer loaded before first job | no |
| cold small persisted job | 3.4442 s |
| warm small persisted job | 0.3504 s |
| warm moderate job | 1.2652 s for 3,499 characters |
| pipeline reused across all jobs | yes, identical object |
| process working set before | 23.93 MiB |
| after cold job | 556.09 MiB |
| after all three jobs | 665.01 MiB |
| approximate cold RSS delta | 532.16 MiB |
| approximate total RSS delta | 641.08 MiB |

These are observations, not performance promises. They support the one-worker, lazy, reused-pipeline design.

## 12. Deviations and known limitations

- `CANCELLING` is a stage rather than another persisted state because unsafe thread termination is not implemented.
- Recovery is capped at three claims rather than retrying indefinitely.
- Manual effective selection is explicit in mapping evidence/provenance because the frozen resolution enum has no manual-selected member.
- Preview token diffs are positional; a large tokenization shift can produce a deliberately conservative/noisy diff.
- Preview payloads persist the proposed analysis internally until a future retention policy exists.
- There is one analysis lane and no SSE; clients poll jobs.
- `wordfreq` supplies Zipf scores only. Exact ranks, dictionary senses, translations, and CEFR remain unselected.
- Reanalysis of a future Reader document with exposure rows referencing old token IDs will safely roll back under current foreign keys. Phase 4 must define historical occurrence preservation before exposing such reanalysis in the Reader.
- The existing Stanza/`requests` package warning remains external to this phase.

## 13. Acceptance and recommendation

All 30 Phase 2 acceptance criteria passed. Phase 2 is complete.

Proceed with Phase 3 only: the Language page shell, reload-safe routing, shared Vocabulary management, and truthful analyzer/provider Settings over these APIs. Do not start Reader exposure tracking (Phase 4), widget/statistics, Anki, AI generation, Cloze, Listening, or Grammar as part of Phase 3.
