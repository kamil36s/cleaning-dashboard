# Language Phase 11 — Core Grammar A1–B1

Status: **COMPLETE (2026-09-24)**. Scope: Phase 11 only. All applicable Phase 11 acceptance criteria pass; none remain unmet. Next phase is **Phase 11.5 — Progress Benchmarks + lightweight Norway Preparation**; it has not started.

## Delivered behavior

An analyzed canonical Reader text has an explicit **Analyze Grammar** action. The existing LanguageJobManager runs the optional dependency pipeline, exactly maps its output to existing canonical sentences/tokens, runs the Bokmål registry, and atomically saves inspectable occurrence evidence. `#grammar` groups all 21 candidates into practical A1/A2/B1 buckets. Pattern detail shows real source sentences, exact highlighted spans and role tokens, parser/analyzer/source provenance, detector versions, limitations, and detector-quality CONFIRM/REJECT controls. Examples reopen and focus the original Reader sentence.

No runtime model download, AI/provider call, generated Grammar example, practice engine, mastery metric, reward, mistake diagnosis, or downstream learning mutation is introduced. Normal Reader analysis still uses only tokenize/POS/lemma. Statistics and Overview were left unchanged; the navigation entry and small Reader controls provide access.

## Files created in this task

- `language_learning/grammar.py`
- `language_learning/grammar_parser.py`
- `language_learning/grammar_nb.py`
- `js/language/views/grammar.js`
- `tests/test_language_grammar.py`
- `tests/language-grammar.test.js`
- `tests/fixtures/language/nb/grammar_cases.json`
- `tests/fixtures/language/nb/grammar_parses.json`
- `tests/fixtures/language/phase11-browser-smoke.html`
- `scripts/benchmark_language_grammar.py`
- `scripts/smoke_language_grammar.py`
- `scripts/language_grammar_edge.mjs`
- `docs/LANGUAGE_PHASE11_RESULTS.md`
- `docs/LANGUAGE_GRAMMAR_PATTERNS.md`
- `docs/LANGUAGE_GRAMMAR_SETUP.md`

## Files modified in this task

- `language_learning/migrations.py`
- `language_learning/store.py`
- `language_learning/service.py`
- `language_learning/jobs.py`
- `language_learning/content_inbox.py`
- `server.py`
- `js/language/api.js`
- `js/language/router.js`
- `js/language/app.js`
- `js/language/views/reader.js`
- `language.html`
- `language.css`
- `tests/test_language_api.py`
- `tests/test_language_store.py`
- `tests/test_language_dictionary_phrasebook.py`
- `tests/test_language_gamification.py`
- `tests/test_language_listening.py`
- `tests/language-reader.test.js`
- `docs/LANGUAGE_IMPLEMENTATION_PLAN.md`
- `docs/LANGUAGE_RUN_PROGRESS.md`

Existing dirty/untracked work was preserved. No branch change, Git backup script/tag change, Finance fix, reference rebuild or Tier 3 ingestion occurred.

## Parser audit and exact resources

Installed Stanza and resources: **1.14.0**, CPU. Canonical Reader processors remain `tokenize=bokmaal`, `pos=bokmaal_charlm`, `lemma=bokmaal_nocharlm` with the three `conll17` dependencies. Initially no local dependency model existed. An explicit developer-only Stanza provisioning command added `depparse=bokmaal_charlm`, separately from all runtime paths. See [setup](LANGUAGE_GRAMMAR_SETUP.md).

Audited directory: `C:\Users\kamil\AppData\Local\StanfordNLP\stanza\Cache\1.14.0\resources`.

| Local resource | Bytes |
| --- | ---: |
| `nb/tokenize/bokmaal.pt` | 633,702 |
| `nb/pos/bokmaal_charlm.pt` | 34,924,024 |
| `nb/lemma/bokmaal_nocharlm.pt` | 2,368,893 |
| `nb/depparse/bokmaal_charlm.pt` | 132,806,828 |
| `nb/pretrain/conll17.pt` | 107,106,063 |
| `nb/forward_charlm/conll17.pt` | 20,374,451 |
| `nb/backward_charlm/conll17.pt` | 20,374,452 |

The additional processor is dependency parsing; no MWT model is requested. Health inspects local resources without importing Stanza/PyTorch or loading a pipeline. `AVAILABLE` means files are provisioned, and `loadVerified` distinguishes actual initialization. Missing models report `UNAVAILABLE / MODEL_NOT_PROVISIONED`; initialization failure and malformed manifests are separate explicit states. Every pipeline constructor uses `DownloadMethod.NONE`. Real parsing and benchmarks passed with socket connections blocked. Runtime code contains no downloader.

The pipeline is lazy, separate and reused by the existing worker. It does not replace or mutate the canonical analyzer registry. Model/parser provenance retains processor/package identities, manifest checksums, resource/package versions, adapter version and manifest fingerprint. No parser probability is invented.

## Measurements

`python scripts/benchmark_language_grammar.py` blocks network access and uses synthetic Norwegian only. Measurements on this Windows workstation during broader verification (not latency guarantees):

| Operation | Milliseconds |
| --- | ---: |
| Grammar cold import/model initialization, empty input | 8,852.489 |
| Grammar warm initialization/use, empty input | 15.899 |
| Reader initialization plus small sentence, Stanza already imported | 1,932.786 |
| Grammar 13 words | 333.855 |
| Reader 13 words | 124.967 |
| Grammar 195 words | 1,399.667 |
| Reader 195 words | 639.863 |
| Grammar 1,950 words | 7,106.266 |
| Reader 1,950 words | 3,788.845 |
| Detector pass, 13 / 195 / 1,950 words | 0.051 / 0.379 / 4.978 |

Approximate Grammar cold RSS increase: **677.29 MiB**. An earlier less-contended run measured cold initialization plus a small sentence at 5,039.306 ms and 695.07 MiB, and 13/182/1,820-word Grammar parsing at 136.227/622.767/5,314.736 ms. The separation from normal Reader is justified by both latency and retained model memory. Reader's initialization number above is not a fresh-process import comparison.

Production service queries on the isolated real-parser Edge fixture, 20 iterations:

| Query | Median / maximum ms |
| --- | ---: |
| Grammar landing | 10.333 / 34.905 |
| Pattern detail | 9.328 / 23.724 |
| Reader payload without Grammar | 5.402 / 21.599 |

Landing and detail use batched CTE queries for latest runs, latest compatible review, exact study evidence, sources and sentences. Detail uses three SELECT/WITH statements including profile validation, independent of occurrence count. Landing uses the same query budget with bounded per-pattern previews. Detail returns at most 200 examples with an explicit `hasMore`; aggregate counts include all occurrences. There is no per-occurrence token/source/review query. Reader's normal payload does not request Grammar and cannot initialize its parser; the small optional Reader Grammar-status request also does not parse.

## Canonical mapping and occurrence contract

The entire dependency document must match canonical sentence count, ordering, exact source bounds/text, token count, exact Unicode code-point token bounds/surfaces, and one-to-one word order. Dependency heads must identify a valid local word/root. Multiple parser words per canonical token, sentence/token divergence, changed source, invalid heads or missing identity fail closed with `TOKEN_MAPPING_DIVERGED`. No partial authoritative occurrence is saved.

Grammar does not write canonical text, tokens, selected lemma IDs, manual locks, POS/morphology, forms, vocabulary or knowledge. A new normal reanalysis cannot delete canonical sentences that have Grammar history; the transaction returns `grammar_text_reanalysis_blocked`, preserving that history. Import a new text revision if canonical retokenization is needed. This is separate from detector re-runs, which reuse the same tokens.

Each occurrence stores ID, profile, text, sentence, pattern/version, detector/version, support/evidence status, source character span, canonical role token IDs/orders/bounds, POS/morphology, dependency relation and canonical head token ID, semantic identity, run identity and creation time. The immutable run stores canonical analysis-run identity, parser and analyzer provenance, source provenance, registry snapshot and policy version. Sentence/token text is not duplicated in Grammar storage; examples join the canonical owner.

Confidence is categorical `SUPPORTED_RULE_MATCH` or `EXPERIMENTAL_RULE_MATCH`, never a numerical linguistic probability.

## Catalogue

There are 40 independent hand-authored expected cases, checked against captured real Stanza output. Every supported detector has at least two positives and two hard negatives; no corpus-wide precision estimate is claimed.

All pattern semantic versions and detector versions are **1.0.0**. Stable detector IDs are `nb.` plus the lower-case pattern ID. [The complete catalogue](LANGUAGE_GRAMMAR_PATTERNS.md) records every candidate, explanation, rule, positive/negative fixtures and limitations.

SUPPORTED (7):

- A1: `A1_NOUN_DEFINITENESS`, `A1_NOUN_NUMBER`, `A1_PRESENT_TENSE`, `A1_SIMPLE_PAST`.
- A2: `A2_PRESENT_PERFECT`, `A2_MODAL_CONSTRUCTION`.
- B1: `B1_RELATIVE_CLAUSE` (explicit `som`, lexical finite relative verb, noun antecedent only).

EXPERIMENTAL: **none**. The contract/test path explicitly prevents an experimental match, even confirmed, from entering authoritative evidence.

DEFERRED (14):

- A1: `A1_BASIC_MAIN_CLAUSE_ORDER`, `A1_YES_NO_QUESTION`, `A1_WH_QUESTION`, `A1_BASIC_POSSESSIVE`, `A1_BASIC_ADJECTIVE_AGREEMENT`.
- A2: `A2_V2_FRONTED_ELEMENT`, `A2_BASIC_SUBORDINATE_CLAUSE`, `A2_SUBORDINATE_NEGATION`, `A2_COMPARISON`, `A2_ADJECTIVE_DEFINITENESS_AGREEMENT`.
- B1: `B1_VARIED_SUBORDINATE_CLAUSE`, `B1_CONDITIONAL`, `B1_PASSIVE`, `B1_COMPLEX_WORD_ORDER`.

Candidate coverage is A1 9/9 classified (4 supported), A2 7/7 (2 supported), B1 5/5 (1 supported). Deferred rules are visibly unavailable, not silent zero-result detectors. Broad clause order/agreement/passive semantics were not promoted from suggestive features without validated boundary rules. No B2/C1/C2 expansion or certified CEFR claim is present.

Forty committed real offline parse fixtures test independent expected positives/hard negatives for every supported rule, including Unicode, punctuation, proper names, fragments, incomplete text, pronoun/noun contexts, questions, embedding, coordination, negation, auxiliary chains, and participle/past distinctions. Additional mutations test ambiguous morphology and wrong dependency links. Noun-form detection can legitimately identify noun morphology in fragments; it does not certify that the fragment is a well-formed sentence.

## Jobs, sources and reviews

Migration 15 adds `analysis_domain=TEXT|GRAMMAR` to the existing Language jobs. Grammar uses the existing `ANALYZE` operation with domain `GRAMMAR` and `language.grammar-job/v1`, avoiding a worker/queue rebuild. Reader and Content Inbox latest-job lookups explicitly select domain TEXT. Existing queue limits, atomic claim, bounded restart recovery, cancellation, polling, state/error/timestamps and one worker are retained.

Stages: `QUEUED`, `STARTING`, `PARSING_DEPENDENCIES`, `MAPPING_TOKENS`, `RUNNING_DETECTORS`, `PERSISTING`, `COMPLETED`, or existing FAILED/CANCELLED outcomes. Failure never appends a canonical analysis failure or changes Reader's ANALYZED state. A cancelled/stale run cannot publish occurrences. Successful identical requests reuse the existing job; failed work can be retried. Compatible registry/parser changes create a new fingerprint/run without rewriting old provenance.

Eligible input is an existing ANALYZED canonical document with a completed canonical analysis: Reader/imported, Content Inbox pasted text, transcript projection, or accepted generated Reader text. Unaccepted `GENERATED*` documents are rejected. Actual content/transcript/accepted-candidate records determine source kind; generated material remains GENERATED. Stored source evidence includes original source type/reference, content/rights metadata, transcript identity/version/fingerprint and generation request/candidate identity as applicable.

Review decisions are append-only `UNREVIEWED`, `CONFIRMED`, `REJECTED` with timestamp and originating occurrence. They assess detector correctness only. Current examples derive the latest compatible review via a semantic key over canonical sentence, pattern semantic version and complete role/span/structure evidence. Detector implementation-version changes preserve review only when that semantic identity is unchanged. Pattern-meaning, span, role, morphology or dependency-structure changes cannot inherit it. Prior runs and reviews remain exported.

## Evidence policy and ownership

Policy: **`language.grammar-evidence/v1`**.

- DISCOVERED: at least one current SUPPORTED occurrence not rejected by the user.
- ENCOUNTERED: such an occurrence's exact canonical sentence has real canonical Reader or eligible Listening exposure tied to a study session and an authoritative batch key. Earlier legitimate study of the same stable sentence also qualifies.
- Analysis, page open, review clicks, session creation, partial/failed Listening and unrelated-text study cannot advance the state.
- Experimental and rejected occurrences remain inspectable but are not authoritative.
- There is no mastery, percentage, RELIABLE threshold, due date or grammar practice model.

Mining/review/query invariant tests compare all pre-existing exported tables before and after Grammar work: no lexical, knowledge-event, knowledge-score, exposure, Cloze-attempt, Anki, Topics, Goals, gamification or other domain change. Grammar has no reference DB handle and cannot write reference facts. Legitimate subsequent Reader/Listening study retains its existing evidence/XP policy; Grammar reads that evidence without adding rewards.

Mistake Intelligence remains explicitly unavailable for Grammar diagnosis. Detector rejection is not learner failure, and exposure is not a mistake. There are no Grammar XP, achievements or quest rules. No Gemini call or generated Grammar example exists.

## API and UI

- `GET /api/language/profiles/{profileId}/grammar`
- `GET /api/language/profiles/{profileId}/grammar/patterns/{patternId}`
- `GET /api/language/texts/{textId}/grammar?profileId=...`
- `POST /api/language/texts/{textId}/grammar-analysis` with `languageProfileId` only
- `PATCH /api/language/grammar/occurrences/{occurrenceId}/review` with profile and decision
- Existing job GET/cancel APIs.

Routes are thin LanguageService dispatch under existing origin authorization. Invalid IDs, unknown patterns, extra detector-truth fields and cross-profile relationships are rejected. Clients cannot create occurrences. Pattern/source routes survive reload; exact Reader sentence routing is additive to existing text routes.

Reader controls show availability/job state, explicit analysis and a collapsed evidence summary. Pattern annotations do not cover the Reader. Pending jobs poll; failure/unavailable Grammar does not replace or disable Reader. Pattern detail uses safe text nodes, native links/buttons/details, live review status and Unicode code-point slicing. Sidebar Grammar is enabled and its old Later placeholder removed.

The real browser smoke exposed an existing Reader observer gap: a sentence already visible before Start had no new intersection notification. A minimal start/resume re-observe fixes that path while preserving the full two-second dwell, visibility threshold, per-session de-duplication and pause cancellation. It has a dedicated regression test; no exposure threshold was relaxed.

## Schema, backup and export

Main schema/export: **v15**, `language-learning-export/v15`. Migration 15 adds `grammar_analysis_runs`, `grammar_occurrences`, `grammar_occurrence_reviews`, their lookup indexes and the additive job-domain column. Existing migration checksums, IDs, routes and persisted schemas remain unchanged. Export ordering includes the three new tables. The reference database remains **read-only v3**, without rebuild or import.

Verified pre-migration backup: **`data/backups/language-learning-v14-pre-phase11-20260924T123707Z.sqlite`**. The backup is schema v14, integrity `ok`, zero FK violations. Migrated main v15 is integrity `ok`, zero FK violations. Production Grammar run count remains zero: browser/benchmark/test texts were isolated.

A live common-table comparison found 42 of 43 pre-existing canonical domain tables identical to the backup; `gamification_quest_snapshots` changed during the broader verification window. It was not reverted. Grammar's isolated whole-table no-mutation invariant passes, and the canonical DB has no Grammar runs; the comparison is not evidence of a Grammar reward write.

## Verification

The full read-only reference scan completed in 1,120.15 seconds: integrity_check=ok and zero FK violations. Complete Language backend: **245 passed**. Broad backend: **919 passed, six skipped, zero failures** (925 collected, 505.877 seconds). The production build passes (323 modules); Python compilation and changed-JavaScript syntax pass. Complete Language frontend/widget: **140 passed** across 20 files. Broad frontend: **1,023 passed, two skipped, one unchanged Finance D.2 assertion failure** across 160 files. Finance was not modified.

The query-budget test initially counted a concurrent worker poll. It now stops the already-idle test worker before tracing the request; the fixed three-query assertion and both complete backend reruns pass. Three older export assertions were updated from v14 to v15. No production query or domain behavior was changed to satisfy those assertions.

Regression coverage passes for Content Inbox/authentic transcripts (Phase 10.5), Listening (10), Mistake Intelligence (9.5), shared-context Cloze (9), generation/provider/audio (8), dictionary/Phrasebook, learning plan/curriculum, gamification, reference ingestion/resolution and Anki. These are included in the complete Language runs; no provider or paid smoke was requested.

New backend: 17 tests in `tests/test_language_grammar.py`, plus one Grammar HTTP integration test in `tests/test_language_api.py` (18 total). Existing schema/table-count/export assertions were advanced to v15, preserving their domain assertions.


Exact new Grammar backend test names:

- `test_every_candidate_has_explicit_status_and_supported_positive_hard_negatives`
- `test_ambiguous_morphology_and_broken_auxiliary_structure_are_not_matches`
- `test_mapping_unicode_offsets_punctuation_and_divergence`
- `test_missing_model_no_download_and_failed_initialization`
- `test_pipeline_always_none_and_is_reused`
- `test_job_discovered_review_reload_and_no_other_mutation`
- `test_exact_sentence_study_required_and_other_text_does_not_count`
- `test_failure_and_divergence_leave_reader_and_occurrences_untouched`
- `test_compatible_upgrade_preserves_review_but_changed_structure_does_not`
- `test_experimental_cannot_be_authoritative_even_if_confirmed`
- `test_cross_profile_invalid_ids_and_client_detector_truth_rejected`
- `test_restart_recovery_and_cancellation_use_existing_queue`
- `test_additive_v14_migration_preserves_rows_and_export`
- `test_queries_are_batched_and_no_parser_runs_on_reads`
- `test_listening_qualification_required_for_encountered`
- `test_inbox_transcript_and_generated_provenance_and_eligibility`
- `test_reanalysis_cannot_delete_grammar_history`
- `test_grammar_routes_jobs_reviews_ownership_and_authorization` (HTTP integration)

New frontend: 11 in `tests/language-grammar.test.js`, plus one already-visible-sentence Reader observer regression (12 total).

Exact new frontend test cases:

- `supports catalogue, pattern and exact Reader sentence routes`
- `groups all practical buckets and shows truthful deferred and unavailable states`
- `renders exact Unicode evidence safely and provides source navigation`
- `confirms and rejects detector quality with semantic buttons and live status`
- `Reader grammar is explicit, polls pending jobs and displays failure`
- `disables unavailable parser and ignores late work after route teardown`
- `uses profile scoped HTTP routes and only backend detector commands`
- `retains READER source label`
- `retains AUTHENTIC source label`
- `retains TRANSCRIPT source label`
- `retains GENERATED source label`
- `rechecks an already visible sentence when study starts, retaining the full dwell requirement`

Final real Edge result: **17/17 checks at each of 1440×1000, 430×900, and 390×844**. Artifacts: `C:/Users/kamil/AppData/Local/Temp/language-phase11-edge-nwxy2ef5` (results JSON, DOM and PNG per viewport). The final 390 px screenshot was visually inspected. Earlier repeat runs hit headless timing stalls; the test driver now disables background timer/renderer throttling, and the complete rerun passes.

Real Edge uses the production `language.html`, production JS/API, real installed Stanza, existing job manager and a separate temporary DB for each viewport. It checks explicit analysis completion, practical catalogue/statuses, exact evidence/source spans, persisted confirm/reject, source-sentence focus, detection-only DISCOVERED, actual Reader dwell ENCOUNTERED, missing-parser degradation, preserved Reader, keyboard-native controls, and actual content bounds. CDP device metrics enforce exactly 1440×1000, 430×900 and 390×844; the iframe content is slightly narrower due to normal scrollbars. No hidden-overflow-only assertion is used: card/prose/evidence element bounds are checked too.

## Deviations and limits

- Seven narrow supported detectors are intentionally shipped; fourteen candidates remain visible and deferred. No experimental detector is claimed ready.
- No numerical confidence or corpus-wide precision claim is made. Stanza hypotheses can be wrong; exact evidence and quality review remain visible.
- Dependency parsing retains a second optional pipeline with a material memory cost. There is one worker, and Grammar blocks its lane while a model call is running; cancellation is cooperative.
- Detail is capped at 200 examples with explicit truncation; no pagination UI or grammar practice engine was added.
- Canonical reanalysis after Grammar history is blocked to preserve stable source identity; new source revisions can be imported.
- Model provisioning was explicit developer setup, not runtime download. Tests and the browser smoke make no paid/provider calls.
- No Statistics/Overview integration was needed.
- The Reader start/resume observer correction is the only adjacent behavior fix, required by exact-sentence study acceptance.
- The known unrelated Finance D.2 assertion is preserved.

Phase 11.5 and all optional advanced/proficiency/production-language features remain unstarted.
