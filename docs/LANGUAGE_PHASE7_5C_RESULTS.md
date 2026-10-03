# Language Phase 7.5C results — read-only reference integration

Verified: 2026-09-17  
Status: **COMPLETE**

## Scope and authoritative baseline

Phase 7.5C integrates the independent Bokmål reference database into Vocabulary, Reader, and the manual Generate workflow. Reference facts remain read-only and remain separate from user knowledge, coverage, exposures, Anki, Topics, Cloze attempts, and generation history.

The task brief described main schema v7 and reference schema v2. Repository-authoritative Phase 9A follow-up work had already advanced those databases to main schema v8 and reference schema v3 before this phase began. Phase 7.5C adds no migration, preserves v8/v3, and does not rebuild or reimport either database.

No Phase 7.6, Phase 7.7, Phase 7.8, Phase 8, full Phase 9, Listening, Grammar, Tier-3, dictionary-provider, direct-AI-provider, or second-language work is included.

## Runtime reference boundary

`ReferenceLexiconService` is the application boundary for reference intelligence.

- It accepts the existing `LANGUAGE_REFERENCE_DB` configuration and opens SQLite using URI `mode=ro`, `query_only=ON`, operation-scoped closing connections, foreign-key checking, and the existing timeout policy.
- Construction and normal server startup are lazy. They do not initialize schemas, rebuild data, import sources, download corpora, or initialize Stanza.
- Health is cached by file size/mtime signature and returned as a defensive copy. A missing or changed database invalidates the cache.
- Public health is path-free and bounded. It reports service/schema versions, a source-snapshot fingerprint, bounded source metadata, row/capability flags, and truthful CEFR/Tier-3 availability.
- Missing databases, unsupported schemas, and SQLite/OS failures produce explicit unavailable states without breaking the main Language service.
- `ReferenceStore` also supports explicit read-only construction; exact resolver semantics remain owned by `ReferenceResolver`.

The production health result is available at schema v3 with fingerprint `sha256:5395a0d1aa2c300f956e04ff69af338463d923d04a14b25bdeffacd416f781e9`. It truthfully reports CEFR unavailable and Tier-3 unavailable. No filesystem or source-archive path is returned.

## Resolution and payload ownership

The service reuses `reference-resolver/v1` for single and batched exact resolution. Batch lookup is chunked and retains the same rules:

- language + normalized lemma + POS exact match;
- the existing null-POS unique/ambiguous fallback;
- explicit `MATCHED`, `AMBIGUOUS`, `UNMATCHED`, or runtime `UNAVAILABLE` states;
- bounded candidates with match basis and stable reference identity;
- no edit-distance, embedding, substring, or opaque fuzzy selection.

Lemma API composition returns explicit sibling `user`, `reference`, and `resolution` objects. Reference fields are not copied into `VocabularyLemma` or `LemmaKnowledge`.

## Frequency, morphology, and provenance

Reference detail keeps evidence source-specific:

| Metric | UI label | Scope |
| --- | --- | --- |
| `SOURCE_LEARNER_RANK` | Learner rank | reference unit |
| `SOURCE_FORM_RANK` | Source form rank | source surface form |
| `DERIVED_LEMMA_RANK` | Derived lemma rank | derived lemma |
| `SOURCE_NGRAM_FREQUENCY` | Raw corpus count | reference unit/source observation |
| `ZIPF_FREQUENCY` | Zipf estimate | reference unit |

Rows retain source ID/name/provider/version and method/method-version where applicable. KELLY is not presented as a universal rank, CLARINO surface rank is not presented as a lemma rank, and Zipf is not presented as an exact rank. Morphological forms, linked idioms/MWEs, and bounded license/attribution metadata are exposed separately. CEFR is `Not available` when no actual evidence row exists; it is never inferred.

## Vocabulary and Reader

The shared lemma detail now has visibly separate `USER KNOWLEDGE` and `REFERENCE · READ ONLY` sections. It handles matched, ambiguous, unmatched, and unavailable states, shows source-specific rank/frequency evidence, forms, linked expressions, bounded sources, and truthful missing CEFR. Existing knowledge editing, exposures, notes, Anki, events, form mapping, and merge behavior stay in the user section.

Reader word clicks still open the canonical user lemma. Reference detail is additive. An analyzed text also receives an independent reference profile containing:

- batched unique-lemma resolution counts;
- source-specific frequency evidence and KELLY learner-rank distribution;
- detected idiom/MWE occurrences;
- truthful CEFR capability state.

The panel is explicitly labelled `REFERENCE PROFILE · NOT USER COVERAGE`. `language.coverage-policy/v1` and accepted-generation coverage remain unchanged.

## Expression detector

The detector contract is `language.reference-expression-detection/v1`.

- It starts from analyzed word tokens and the indexed first MWE component, rather than scanning every expression or authoritatively matching raw substrings.
- Surface, lemma, POS, optional-token, and inflection behavior comes only from explicit stored component constraints.
- Matching is case-normalized while exact original source text and Unicode-code-point spans are retained.
- Sentence/token boundaries and punctuation are respected.
- Every occurrence returns the reference lexical-unit key/ID, unit type, sentence ID, first/last token IDs and orders, exact source span, surface text, match basis, ambiguity, detector version, selection state, and source provenance.
- Overlapping/nested evidence is retained. The longest overlapping occurrence is labelled `LONGEST_PREFERRED`; shorter retained evidence is labelled `OVERLAP_RETAINED`.
- Same-span alternatives and ambiguous analyzed tokens remain explicit.

Synthetic fixtures cover simple/source-supported expressions, an official idiom, case difference, an explicitly inflected component, overlapping and longest matches, punctuation blocking, ambiguous alternatives, exact spans, no match, and multiple sentence/token contexts. Detection creates no phrase vocabulary, phrase mastery, exposure, knowledge event, Anki record, Cloze attempt, or Topic membership. No definition, translation, or meaning is invented for official idioms.

## Thin API surface

Only the required read-only routes were added:

- `GET /api/language/reference/health`
- `GET /api/language/lemmas/{id}/reference`
- `GET /api/language/texts/{id}/reference-profile`

They use the normal Language response envelope. They expose no arbitrary search/SQL surface, environment values, secrets, or filesystem paths.

## Reference-aware generation v2

Phase 7 v1 remains the default compatibility contract when enrichment is not requested or the reference service is unavailable. Existing stored v1 requests/candidates are neither migrated nor rewritten.

Opt-in reference-aware requests use:

- `language-generation-targets/v2`
- `language-generation-context/v2`
- `language-generation-prompt/v2`
- bounded `language-generation-reference-facts/v1`

The original user-knowledge targeting priority remains authoritative. Only the selected target lemmas are reference-enriched, capped at 12 by the generator (service hard maximum 20). The frozen metadata includes reference schema version, source/import fingerprint, service version, and resolver version. The prompt names source-specific learner/frequency evidence and still requires local analysis of the pasted result. It contains no reference-database dump, personal notes, full history, unrelated dashboard data, or provider secret. A source snapshot change changes the reference and prompt fingerprints; identical frozen semantic inputs remain deterministic.

The manual workflow remains: copy prompt/context, use an external model manually, paste candidate, analyze locally with the canonical analyzer/CoverageService, then explicitly accept. Phase 8 is not required or implemented.

## Performance and query plans

Measurements used the production 4,222,840,832-byte reference database after one warm health call. Values are median wall-clock times on this machine:

| Operation | Median |
| --- | ---: |
| Cached safe health | 0.067 ms |
| One exact lemma resolution | 6.664 ms |
| One reference-detail fetch | 13.614 ms |
| Batch resolution, 30 lemmas | 6.938 ms |
| Indexed MWE first-component candidates | 7.185 ms |
| One Reader sentence expression match | 8.068 ms |
| Generator lookup, 12 targets | 14.096 ms |
| Reference profile, 200 analyzed tokens | 57.814 ms |
| Reference profile, 5,000 analyzed tokens | 254.570 ms |

`EXPLAIN QUERY PLAN` confirms `idx_reference_units_kind`, `idx_reference_frequency_unit`, and `idx_reference_mwe_sequence` are used for the resolver, frequency rows, and first-component MWE candidates respectively. No new index was needed. Reader resolution is based on unique selected lemmas and chunked queries, not one connection/query per token.

## Production database verification

Read-only diagnostics against the canonical databases produced:

| Database | Schema | Size | Integrity | Foreign keys |
| --- | ---: | ---: | --- | ---: |
| `data/language-learning.sqlite` | v8 | 716,800 bytes | `ok` | 0 violations |
| configured production reference DB | v3 | 4,222,840,832 bytes | `ok` | 0 violations |

The reference diagnostic also confirms 158,305 lexical units, 618,728 forms, 1,143,502 source links, 258,063 derived/reference frequency observations, 3,327,050 raw observations, 3,461 variants, zero CEFR rows, zero association rows, zero domain rows, and Tier-3 absent. Phase 9A sentence/occurrence/translation tables remain present under schema v3.

## Verification results

New backend coverage is 8 tests: six `ReferenceLexiconService` tests plus one generator-v2 test and one API/invariant test. New frontend coverage is 8 Vitest cases (five named cases, including a three-state matched/ambiguous/unmatched/unavailable table).

- Focused reference integration: **15 passed**.
- Complete Language backend: **156 passed**.
- Complete Language frontend plus widget: **88 passed**.
- Explicit Phase 9A Cloze backend/audio: **16 passed**.
- Explicit Phase 9A Cloze frontend/audio: **9 passed**.
- Broad backend: **505 passed, 1 skipped**.
- Broad frontend: **720 passed, 2 skipped**.
- Python compilation: **PASS**.
- Changed-JavaScript syntax checks: **PASS**.
- Production Vite build: **PASS**, 264 modules transformed; existing non-module/chunk-size warnings only.

The backend invariant test snapshots main-domain row counts and proves the new health, lemma, and text-profile reads create no vocabulary, knowledge, event, exposure, Anki, Cloze, Topic, or Goal writes. Generator tests prove v1 compatibility, bounded v2 context, deterministic fingerprints, and fingerprint change after a committed source-version change.

## Real-browser smoke

The checked-in synthetic fixture `tests/fixtures/language/reference/phase75c-browser-smoke.html` was run in real Microsoft Edge 153 with no production API or user data. It passes **15/15** DOM/interaction assertions covering:

- Vocabulary user/reference separation and source-specific learner rank;
- canonical Reader lemma click and inspectable idiom annotation;
- exact original Reader text;
- checked reference-aware Generate control, v2 fingerprint summary, bounded reference-facts copy, and manual import control;
- explicit reference-outage fallback while user knowledge still renders;
- unchanged synthetic Phase 9A Fast Track start action.

Fresh 1440 px and 390/430 px screenshots were visually reviewed. Reference panels collapse to one column, long reference/source values wrap, and expression styling remains a subtle underline distinct from knowledge coloring. The browser smoke exposed an unchecked-property issue in the new Generate control; the control now assigns the native `checked` property explicitly and has a regression assertion.

## Fallbacks and limitations

- A missing/unsupported/unreadable reference DB leaves Vocabulary, Reader, manual Generate v1, Anki, Statistics, and all main-domain state usable. Existing Cloze dependency fallback remains unchanged.
- Reference schema v3 currently has no production CEFR, Tier-3 n-gram, association, or domain evidence. The UI says unavailable and does not infer values.
- Official idioms provide identities and source attribution, not definitions or translations.
- Expression matching is intentionally limited to constraints encoded in current source rows. No fuzzy or semantic paraphrase matching exists.
- No persistent manual reference crosswalk or phrase-knowledge model was added.
- The reference service is local/process-scoped; its file-signature health cache is not a distributed invalidation protocol.

All Phase 7.5C acceptance criteria are met. The next separately authorized roadmap phase is **Phase 7.6 — evidence-driven gamification, completion, and campaigns**. It was not started.
