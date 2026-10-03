# Language Learning Phase 7 results

Status: **COMPLETE**  
Date verified: 2026-09-16  
Database schema version: 6  
Frontend page: `language.html#generate`

## 1. Outcome

Phase 7 adds a complete manual external-LLM workflow. It deterministically selects bounded focus vocabulary from a frozen canonical snapshot, builds a versioned privacy-bounded context pack, accepts manually pasted output, validates it, analyzes it with the same canonical Stanza adapter and cached pipeline, measures coverage against the frozen snapshot, verifies focus-word use locally, retains candidate attempts, builds manual revision prompts, and creates a normal Reader document only after explicit acceptance.

There are no provider calls, provider keys, automatic revisions, cost claims, exposure writes, knowledge-score/status changes, Anki writes, Cloze, Listening, Grammar, or second-language work.

## 2. Files

Created:

- `language_learning/generation.py`
- `js/language/views/generate.js`
- `tests/test_language_generation.py`
- `tests/language-generation.test.js`
- `docs/LANGUAGE_PHASE7_RESULTS.md`

Modified:

- `language_learning/migrations.py`, `store.py`, `service.py`, `jobs.py`
- `server.py`
- `language.html`, `language.css`
- `js/language/api.js`, `app.js`, `router.js`, `state.js`
- `js/language/views/overview.js`
- `tests/test_language_store.py`, `tests/test_language_api.py`
- `docs/LANGUAGE_IMPLEMENTATION_PLAN.md`, `docs/LANGUAGE_RUN_PROGRESS.md`

Unrelated dirty-worktree changes were preserved.

## 3. Schema, migration, and export

The additive v6 migration adds exactly two tables:

- `generation_requests`: immutable request settings, frozen lexical/target snapshots, rule/prompt/coverage versions and fingerprints, and the named virtual-file context bundle;
- `generation_candidates`: ordered manual attempts, provider/model labels, raw and extracted response, validation/status history, durable analysis attempts/results, rejection state, and accepted Reader document/job identities.

Candidate rows are also the durable queue records. The existing `LanguageJobManager` remains the only worker and polls existing analysis jobs before generation candidates. Startup recovery requeues interrupted candidate analysis with the existing bounded retry policy. No second worker or duplicate job table was created.

Export advances to `language-learning-export/v6` and includes both generation tables. Ordinary request/candidate responses omit the full frozen lexical snapshot and context pack; the dedicated context-pack endpoint owns that payload.

The pre-migration v5 backup is `data/backups/language-learning-v5-phase7-20260916T145637203107Z.sqlite`. The verified post-migration backup is `data/backups/language-learning-v6-20260916T150120159938Z.sqlite`. All common v5 table row counts are unchanged after migration.

## 4. Request model, deterministic targets, and budgets

Requests store profile/topic/custom-topic, requested length, preset/coverage, explicit target IDs, grammar/style, frozen snapshots and fingerprints, context pack, and versions. Presets are Very Easy 99%, Easy 97%, Normal 95%, and Challenge 90%, with a validated custom 50–100% override.

The selection rule is `language-generation-targets/v1`. Priority is explicit input order, weak, underexposed, recent, then manually mapped topic vocabulary. Within derived pools, ordering is exposure count ascending, Zipf score descending, normalized lemma, then stable ID. Every selected item exposes category and reasons. Caps are 5 targets through 250 words, 8 through 500, and 12 above 500. Anki evidence is not used because Phase 6 currently provides no defensible per-lemma due/review signal for ranking.

The approximate uncovered-token budget is `ceil(length × (100 − coverage) / 100)`. Acceptance tolerance is `max(1 percentage point, 100 / eligible tokens)`, making short-text granularity explicit. Token coverage is primary; unique-lemma coverage is also reported.

## 5. Frozen snapshot and context pack

The request freezes the Phase 5 classifier output and only lexical fields required for generation/validation: canonical display/normalized lemma, POS, knowledge/disposition, scores, exposures, frequency score, classifier reasons, and relevant timestamps. Notes, events, sessions, reading history, goals, calendar/project context, paths, environment, and secrets are excluded.

Covered vocabulary is TRACKED KNOWN/MASTERED plus IGNORED; EXCLUDED is outside the denominator/export. The context-optimized known file is deterministically frequency-first and capped at 1,000 canonical lemmas; the copy-complete prompt embeds at most the first 600 so it remains standalone and bounded. The full frozen snapshot remains server-side for later local validation.

The bundle format is `language-generation-context/v1` and contains:

- `prompt.md`
- `generation-spec.json`
- `known-vocabulary.txt`
- `focus-vocabulary.json`
- `metadata.json`

The prompt version is `language-generation-prompt/v1`. Its fingerprint excludes the creation timestamp, so identical frozen semantic inputs produce the same fingerprint. Metadata reports safe profile/rule provenance, snapshot time/fingerprint, known/focus counts, truncation, and pack character estimate. The browser downloads one JSON bundle with named virtual files; no ZIP dependency was added.

## 6. Manual import, analysis, and coverage

Structured import accepts a JSON object with required non-empty `title` and `text`, optional matching `requestId`, and optional notes. It rejects malformed/object-shape/wrong-request/empty/oversized responses. The raw limit is 256 KiB. JSON-looking malformed input is never silently treated as prose. Plain text requires `treatAsPlainText: true` and gets a deterministic attempt title. HTML-looking input remains inert text.

Every attempt uses source `MANUAL_EXTERNAL_LLM` and retains optional provider/model labels without implying a provider call. Attempts are numbered and never overwrite one another.

Candidate analysis is asynchronous on the one durable worker and uses the shared `AnalyzerRegistry`. It does not persist analyzer-discovered lemmas/forms/frequency/knowledge while the candidate is unaccepted. Canonical token evidence is matched in memory to the frozen snapshot by normalized lemma plus POS, with normalized-only fallback only when unique.

`CoverageService` calculates frozen-snapshot token and unique-lemma coverage. Results also include requested/actual/difference/tolerance, eligible and actual word counts, problematic word counts/Zipf/unresolved/target flags, locally verified target occurrences and surface forms, analyzer provenance, policy versions, and an explicit `IN_TOLERANCE` or `OUT_OF_TOLERANCE` state. Out-of-tolerance work can be explicitly accepted but is never labeled as meeting the target.

## 7. Revision, acceptance, and Reader ownership

Revision prompts are generated locally and include measured coverage/gap, problematic items, known-vocabulary replacement guidance, missing required targets, desired length/coverage, and the structured response contract. Copying one makes no network call; a manually revised response imports as the next separate attempt.

Acceptance is explicit and idempotent. It atomically creates one normal `TextDocument` with source `GENERATED_MANUAL_LLM`, a structured source reference containing request/candidate/provider/model/snapshot/prompt provenance, and one normal analysis job. That job reuses the already validated candidate `AnalysisDocument` and then runs the existing transactional Reader commit path. Repeated acceptance returns the same document/job.

Import, analysis, revision, rejection, acceptance, and save produce zero Reader exposures and zero study sessions. They do not alter knowledge status or recognition/recall/production, and perform no Anki write. Newly encountered lexical identities may be created only by the normal accepted-text analysis commit, with default NEW state, exactly as for an ordinary Reader text. Real exposures begin only through the unchanged explicit Reader study flow.

## 8. UI and routes

Generate is enabled in the persistent Language navigation. The responsive view includes settings/presets, frozen focus reasons, pack counts/timestamp, prompt/known/focus copy actions, JSON-bundle export, structured paste plus explicit plain fallback, validation feedback, durable attempt history, queue state, requested-versus-actual coverage, unknown/unresolved lists, target-use results, manual revision copy, reject, explicit accept, and Read now.

The active request ID is retained in local storage so its request/context/candidate history restores after reload. Overview adds a compact length/difficulty launcher and does not embed the full workflow.

Thin routes:

- `POST /api/language/profiles/{id}/generation-requests`
- `GET /api/language/generation-requests/{id}`
- `GET /api/language/generation-requests/{id}/context-pack`
- `POST|GET /api/language/generation-requests/{id}/candidates`
- `GET /api/language/generation-candidates/{id}`
- `POST /api/language/generation-candidates/{id}/analyze`
- `POST /api/language/generation-candidates/{id}/accept`
- `POST /api/language/generation-candidates/{id}/reject`
- `GET /api/language/generation-candidates/{id}/revision-prompt`

## 9. Tests and verification

Exact new Phase 7 backend tests: **9** (six deterministic workflow tests, one real Stanza candidate/pipeline fixture, one HTTP vertical slice, and one v5→v6 migration-preservation test).

Exact new Phase 7 frontend tests: **6** (form/presets, context copy/export, explicit plain fallback, measured result/target/unknown rendering, accepted Read now, and all thin client routes).

| Command/check | Exact result |
| --- | --- |
| complete Language backend suite | 121 passed, 0 failed |
| complete Language frontend suite including widget | 71 passed, 0 failed |
| real Stanza Phase 7 fixture | passed; two persisted candidates, network/download blocked, one pipeline reused |
| broad backend suite | 469 passed, 1 skipped, 0 failed |
| broad frontend suite | 699 passed, 2 skipped, 0 failed |
| `npm run build` | passed; existing non-module/large-chunk warnings only |
| canonical database | schema v6; 24 tables; `integrity_check = ok`; zero FK violations |
| migration preservation | no common-table row-count changes from the verified v5 snapshot |
| export | v6; requests and candidates present |

## 10. Visual verification

Real headless Edge rendering used an isolated synthetic Phase 7 page backed by the production view module and CSS. Form, context-pack/import, and analyzed out-of-tolerance candidate states were inspected at 1440×1000; the analyzed candidate was also inspected at an emulated 430×900 viewport. Browser metrics reported `innerWidth = clientWidth = scrollWidth` at both widths and all buttons/links within the viewport. Hierarchy, wrapping, navigation, copy/export controls, coverage metrics, unknown/unresolved words, target misses, revision, accept warning, reject, and the persistent Norwegian identity passed. The temporary fixture/server/browser were removed or stopped.

## 11. Acceptance, deviations, and limitations

All 56 Phase 7 acceptance criteria pass. There are no unmet criteria.

Intentional implementation choices:

- generation candidates themselves are durable queue records instead of adding a third table or overloading the existing text-bound `language_jobs` constraint;
- the single existing worker services both queues, and accepted Reader commit reuses the candidate analysis rather than running Stanza twice;
- the bundle is one downloadable JSON object with named virtual files rather than ZIP;
- Anki is omitted from target ranking until a real per-lemma signal can be defended;
- current-vocabulary re-scoring is not implemented; all displayed generation coverage is clearly frozen-snapshot coverage;
- the optional Reader “generate like this” shortcut is not added because Phase 7 has no truthful stored similarity parameters; Overview provides the required compact launcher.

Operational limitation: the UI restores the most recently active request per browser/profile; older requests remain addressable by stable backend ID and are fully preserved/exported, but there is no global request-browser page in Phase 7.

The exact next recommendation is **Phase 8 only**: add one explicitly configured server-side generation provider behind the existing request/context/candidate contracts, with server-only secrets, bounded persisted attempts/retries/cancellation and cost provenance, canonical analysis after every attempt, a strictly bounded automatic revision loop, deterministic best-candidate fallback, and a separately labeled current-vocabulary re-score—while preserving the complete manual workflow and adding no Cloze, Listening, Grammar, or second-language scope.
