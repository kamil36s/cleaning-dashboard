# Language full Phase 9 — Reviews and Cloze from shared contexts

Status: **COMPLETE (2026-09-17)**. The intentionally pulled-forward Phase 9A Fast Track remains **INTENTIONALLY PULLED FORWARD / COMPLETE** and was extended, not rebuilt. Phase 9.5, Phase 10, Listening, Grammar, CEFR, and Tier 3 were not started.

## Delivered architecture

Full Phase 9 adds shared-context `REVIEW` and `CURRICULUM` practice to the existing `FAST_TRACK` and `RECYCLE_MISTAKES` paths. The same Cloze session, attempt, evidence, suppression, audio, gamification, goal/statistics, and lexical-detail boundaries are reused. There is no second SRS: Anki remains the only due-date/interval/ease owner, while dashboard queues are deterministic recommendations and practice.

Candidate contexts are frozen into compact item snapshots with the exact original sentence, Unicode-code-point blank span, exact expected surface, canonical target lemma, source type/entity/context IDs, analyzer/source provenance, applicable license/attribution, curriculum identity, accepted answers, morphology, question type, and every policy version. Later Reader edits, reanalysis, provider changes, or reference rebuilds therefore cannot rewrite a historical exercise.

Supported sources and eligibility:

- `TATOEBA`: unchanged Phase 9A translated, licensed reference sentences for Fast Track and safe curriculum fallback.
- `READER`: an `ANALYZED` document, exact analyzed sentence/token span, canonical selected lemma, and non-ambiguous/non-unresolved mapping. Broken spans, control/unsafe markup, and ambiguous mappings fail closed.
- `PHRASEBOOK`: a canonical `LEMMA` link plus a single-token expression occurring exactly once at token boundaries in preserved source context. Saving remains zero-credit and never implies known/mastered/due.
- `GENERATED`: only an accepted generation candidate’s `ANALYZED` Reader document. Raw, rejected, failed, and otherwise unaccepted Gemini output is excluded. Candidate/request and analyzer provenance are retained.
- `CURRICULUM_TARGET`: an approved/mapped item from the exact selected pack version. The pack ID, version, name, and fingerprint are frozen. A reference-only target is materialized as a user lemma only when it is actually selected into a safe exercise; missing-context targets are skipped and never mass-created.

Source ranking is deterministic under `language.cloze-context-selection/v1`: real Reader, exact Phrasebook, accepted generated Reader, then Tatoeba curriculum fallback. Stable seeded hashes and source/context IDs break ties. Shared target selection is `language.cloze-target-selection/v2`; it prioritizes prior incorrect/revealed evidence, LEARNING/weak/underexposed targets, negative history, fewer attempts, normalized lemma identity, and stable ID. Phase 9A continues to use its unchanged `language.cloze-target-selection/v1` contract.

## Questions, grading, and distractors

Existing multiple-choice remains supported. Shared multiple-choice uses `language.cloze-distractors/v2`: same POS is required when known, exact/leading morphology tags are preferred, the target lemma and all its forms are excluded, and normalized forms are unique. Three safe distractors are required; otherwise the item deterministically falls back to typed mode. Fast Track retains `language.cloze-distractors/v1` and its original four-option snapshots.

Typed Cloze stores the exact expected source surface and an explicit accepted-answer list. `language.cloze-answer-normalization/v1` performs only trim, Unicode NFC, and case-folding. It does not strip diacritics, punctuation, or inflection, so `æ/ø/å` remain distinct from ASCII and a wrong inflection remains incorrect. Alternatives require explicit snapshot evidence; the current policies accept only the exact snapshotted surface after normalization. Answer length is capped at 200 characters. No LLM grades answers.

Attempts remain one row per session item with global idempotency keys. They now retain question type, source-context type, normalization version, raw user answer, and normalized answer. A retry returns the existing attempt. The canonical `CLOZE_*` knowledge event and existing capped gamification reconciliation also remain idempotent. `knowledgeMutation` is explicitly `NONE`: one success does not set scores, KNOWN, or MASTERED. Goals and LearningPlan continue to derive from canonical attempts; campaign opening or practice alone creates no progress.

Bad-question reports support wrong answer, ambiguity, multiple valid answers, unnatural/bad sentences, distractors, mapping, generated context, and other. Suppression remains a local target/source/context tuple and records its source type; it never deletes or edits Reader, Phrasebook, generated, curriculum, or reference data.

## Reviews and UI

Reviews now presents five visibly owned queues: `ANKI_DUE`, `CLOZE_PRACTICE`, `CLOZE_RECYCLE`, `READER_REVISIT`, and `CURRICULUM_PRACTICE`. Anki is labeled as the external scheduler; every other card is a dashboard queue with no due-date claim. LearningPlan’s existing review/recycle kinds now link to `#cloze` with the same ownership language.

The Cloze landing preserves Fast Track and adds Review and versioned Curriculum starts, 10/20/50 bounds, typed/multiple-choice selection, per-source availability, and resume. Typed input autofocuses, Enter submits, empty answers are blocked, status is announced, and Next receives focus after feedback. Feedback shows outcome, expected/user answer, lemma, shared lexical-detail link, source, optional translation, and existing sentence audio. Completion reports correct/incorrect/revealed/skipped, scored accuracy, source count, and targets practiced without proficiency claims. Reader/Phrasebook/Generated missing translations remain missing; Gemini is not translation or dictionary truth.

Responsive rules stack typed/shared controls and action rows at the established 700/460 px breakpoints. Real Edge checks at 1440×1000, 430×900, and 390×844 reported no horizontal overflow.

## Schema, migration, and export

Main schema advances additively from v11 to **v12**. The migration adds practice/question/policy/curriculum session metadata; question/source/normalization/raw/normalized attempt fields; source type on suppressions; and bounded lookup indexes. The suppression table is rebuilt transactionally only to expand its checked reason enum while copying every Phase 9A row. Historical session `practice_mode` is copied from its existing mode, preserving recycle identity. Existing item/attempt JSON is not rewritten.

Export advances to `language-learning-export/v12`. The independent reference database stays read-only at schema **v3**; no source import or rebuild occurred.

Required pre-migration backup: `data/backups/language-learning-v11-pre-phase9-20260917T160558Z.sqlite`. It is schema v11, `integrity_check = ok`, and has zero foreign-key violations. The migrated canonical database is schema v12, `integrity_check = ok`, and has zero foreign-key violations. The 4,222,840,832-byte reference database is schema v3, `integrity_check = ok`, and has zero foreign-key violations.

## Bounded queries and measurements

Shared review fetches at most 500 canonical targets, Reader contexts in 250-ID batches (maximum 4,000 rows), and Phrasebook contexts in 250-ID batches (maximum 1,000 rows) using the existing target-lemma and link-value indexes. Curriculum Tatoeba sentences, surrounding tokens/translations, morphology, and Phase 9A distractors use bounded batch queries. Session construction performs no per-target source/reference lookup.

On the isolated 60-target/50-item fixture used for verification:

- Review typed 50-item construction: **31.12 ms**, one Reader-context batch call and one Phrasebook-context batch call.
- Fast Track 50-item construction: **2,504.40 ms**, one sentence batch call, one morphology batch call, and one distractor batch call.

These are local synthetic wall-clock measurements, not production latency guarantees.

## Tests and verification

New backend coverage is in `tests/test_language_phase9.py` (7 tests):

1. exact typed normalization, NFC, `æ/ø/å`, punctuation, whitespace, wrong inflection, duplicate submit, frozen history, one evidence/XP event, and no mastery;
2. Reader exact/repeated span plus ambiguous, unresolved, unsafe, and mismatched-span rejection;
3. exact linked Phrasebook eligibility, source preservation, suppression, source survival, and no mastery;
4. analyzed generated document exclusion before acceptance, failed-candidate exclusion, accepted eligibility, and candidate provenance;
5. same-POS/morphology/unique distractors and insufficient-set typed fallback;
6. curriculum pack-version freezing and selected-only lemma materialization;
7. honest no-safe-context curriculum failure with zero lemma creation.

`tests/test_language_store.py::test_schema_v11_cloze_history_migrates_additively_to_v12` adds the historical migration fixture. Existing Fast Track HTTP/service tests answer and render legacy snapshots on v12.

New frontend coverage adds two Cloze tests (shared Review/Curriculum starts; typed Enter/feedback/source/focus/lexical detail) and one Reviews ownership test. `tests/fixtures/language/phase9-browser-smoke.html` adds 15 production-view assertions covering Fast Track, Review, curriculum, Reader incorrect feedback, Phrasebook correct feedback, Generated and curriculum source labels, reporting, summary, Reviews ownership, keyboard focus, and overflow.

Final verification:

- Full Phase 9 + Cloze/audio focused backend: **27 passed**.
- Phase 8 generation/provider/jobs regression: **38 passed**.
- Curriculum/dictionary/Phrasebook/gamification/reference/Anki focused backend: **43 passed**.
- Focused frontend regressions: **42 passed**.
- Complete Language backend: **207 passed** (included cleanly in the broad run).
- Complete Language frontend/widget: **106 passed**.
- Broad backend: **652 passed, 1 skipped**.
- Broad frontend: **796 passed, 2 skipped**.
- Python compilation and changed-JavaScript syntax: **PASS**.
- Production Vite build: **PASS**, 272 modules transformed; only the repository’s existing non-module/chunk-size warnings remain.
- Real Edge: **15/15** at desktop, 430 px, and 390 px.

## Limitations and deviations

- Phrasebook context eligibility is intentionally conservative: one linked single-token expression with one exact boundary-delimited occurrence. Multiword answer spans need a future separately versioned policy.
- Shared Reader/Phrasebook contexts have no invented English translation. Existing Tatoeba translations continue to work.
- Explicit accepted-answer evidence currently contains the exact source surface only; no synonym, paraphrase, or free-production grading is inferred.
- Curriculum mode uses safe Reader/Phrasebook/accepted-generated context when the target already has a canonical user lemma, otherwise safe reference Tatoeba context. Items with no safe context are unavailable.
- The Edge smoke uses isolated synthetic state and production view modules; backend source policies are covered independently by service/HTTP/regression tests.
- No live Gemini, Google TTS, or Anki mutation was needed or performed. Their existing adapters and regression suites remained green.

There are no unmet full Phase 9 acceptance criteria. The exact next separately authorized roadmap phase is **Phase 9.5 — Mistake Intelligence and targeted remediation**. It was not started.
