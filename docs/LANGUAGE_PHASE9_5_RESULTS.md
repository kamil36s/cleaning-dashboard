# Language Phase 9.5 results — Mistake Intelligence and targeted remediation

Verified: 2026-09-18  
Status: **COMPLETE**

## Delivered architecture

`MistakeIntelligenceService` is a backend-owned, read-only diagnostic layer over canonical Cloze attempts. It reads attempts and exact local form mappings in two batched queries, optionally uses the existing read-only reference resolver for unresolved forms, derives clusters in memory, and returns one shared remediation stream. It creates no scheduler, goal, knowledge, exposure, reward, or reference fact.

The service is consumed by `LearningPlanService`, existing Cloze `RECYCLE_MISTAKES`, Reviews, Statistics, and the compact Overview summary. Cloze still owns attempts and practice delivery; LearningPlan still owns next-action orchestration; Anki remains the only SRS owner. Daily Quest semantics and snapshots were deliberately not changed, so no quest-policy migration or reward duplication was introduced.

## Versioned policies and evidence

- Observation: `language.mistakes-observation/v1`.
- Clustering: `language.mistakes-clustering/v1`.
- Confusable pairs: `language.mistakes-confusable/v1`.
- Severity: `language.mistakes-severity/v1`.
- Remediation: `language.mistakes-remediation/v1`.
- Qualifying negative evidence: canonical `INCORRECT` and `REVEALED` Cloze attempts. Exact attempt IDs are deduplicated. `SKIPPED` does not count.
- Preserved typed evidence: submitted and normalized answer, expected surface, question type, context/source identity, timestamp, outcome, and frozen item fingerprint.
- Multiple choice evidence counts only when the learner actually selects the wrong resolved option. Merely showing a distractor never establishes a confusion.
- Individual Anki review/lapse history is `NOT_SUPPORTED`: current card aggregates cannot prove individual mistake events. Grammar and Listening evidence are `UNAVAILABLE` until their future phases exist.

## Clusters and thresholds

All established categories require at least two qualifying failures:

- `TARGET_LEMMA_DIFFICULTY`: at least two incorrect/revealed attempts for the same target lemma.
- `DIRECTIONAL_CONFUSION`: at least two direct expected A → supplied B answers resolving safely to another lemma. Direction is retained and the only claim is learner-response confusion, never synonymy or antonymy.
- `INFLECTION_CONFUSION`: the exact wrong form resolves uniquely to the target lemma, has analyzer provenance, and its morphology differs from the expected form.
- `UNRESOLVED_FORM_DIFFICULTY`: the same unresolved normalized answer repeats. It explicitly reports no lemma relationship, protecting ordinary typos from fabricated lexical links.
- `CONTEXT_DIFFICULTY`: at least two failures in one exact frozen source context and at least two correct attempts for the target in other contexts.

One-off errors remain historical evidence but do not create an established cluster. No opaque model, fuzzy spelling inference, semantic embedding, or uninspectable score is used.

## Severity, recency, and recovery

Recency windows are explicit: 7 days for recent evidence and 30 days for current evidence, evaluated using `Europe/Warsaw` study dates. The explainable integer priority uses incorrect count, reveal count, 7/30-day recency, source-context diversity, and correct attempts after the latest failure. Returned reasons expose those exact inputs. Severity bands are `HIGH` (score at least 10), `MEDIUM` (at least 6), and `LOW` (below 6).

Cluster states are `ACTIVE`, `WATCH`, `IMPROVING`, and `RECOVERED`. Recovery requires at least two later correct attempts on two distinct Warsaw-local dates. It lowers priority and removes the cluster from active remediation without deleting historical evidence or changing `NEW`/`LEARNING`/`KNOWN`/`MASTERED`. Mistake computation has zero durable writes.

## Bounded remediation and UI

Summary output is capped at 10 problems by default, shared remediation at 5 actions, and cluster detail at 50 attributable evidence rows. Remediation kinds are `RECYCLE_RECENT_FAILURE`, `PRACTICE_TYPED_FORM`, `REVIEW_LEXICAL_DETAIL`, and `REVISIT_READER_CONTEXT`. At most one action per target lemma is selected deterministically.

LearningPlan consumes that output once and does not re-rank mistakes. Existing Cloze recycle first tries the same remediation target IDs in the Phase 9 shared-context engine and safely falls back to the preserved Phase 9A recycle path when no eligible shared context exists. No second exercise engine was added.

Reviews now separates “Needs attention” from recent recoveries, shows severity/state and source limitations, links practice to existing Cloze, and loads bounded evidence detail on demand. Statistics separates historical incorrect attempts from active/new/recovered clusters. Overview shows only a compact count/top-target summary. Cards wrap safely on desktop and narrow layouts and keep text labels in addition to color.

## Read-only API

- `GET /api/language/profiles/{profileId}/mistakes`
- `GET /api/language/profiles/{profileId}/mistakes/{clusterId}`
- `GET /api/language/profiles/{profileId}/remediation`

Limits and optional `asOf` are server-validated. There is no create/update endpoint for client-trusted diagnosis; POST to the collection remains unavailable.

## Persistence and performance

No migration was required. Main schema remains v12 and the read-only reference schema remains v3; therefore no Phase 9.5 backup was created. Derived output is cacheable by profile, Warsaw date, and a cheap attempt-history signature. A cache miss uses one aggregate signature query plus two batched input queries; clustering and details do not issue per-cluster queries.

Measured on the canonical profile with 40 Cloze attempts and 7 qualifying observations:

- cold mistake summary: 42.224 ms;
- unchanged warm summary: median 7.707 ms, max 19.989 ms;
- remediation: median 3.060 ms, max 6.933 ms;
- full Statistics response with Mistake Intelligence: median 25.313 ms, max 39.482 ms;
- LearningPlan integration: median 28.543 ms, max 46.863 ms;
- synthetic established-cluster detail: median 1.788 ms, max 3.301 ms.

The observed Phase 9A Fast Track 50-question build of about 2.5 s, versus about 31 ms for Phase 9 Review 50, is recorded as a future performance-audit/hardening candidate. It is not caused by 9.5 and was intentionally not changed in this phase.

## Tests and verification

New backend coverage adds 7 tests: 5 Mistake Intelligence service fixtures, 1 Cloze shared-remediation integration test, and 1 read-only HTTP route test. They cover isolated errors, repeated target failures, Reveal, recovery/idempotent recomputation and no mutation, direct A → B confusion, no distractor-only/symmetric claim, typo isolation, analyzer-backed morphology, exact-context difficulty, LearningPlan reuse, Anki unavailability, bounded detail, and historical Phase 9 attempts.

New frontend coverage adds 4 tests: 2 mistake UI/statistics/Overview tests, 1 API-client route test, and 1 Reviews detail/recovery test.

- Complete Language backend: **214/214 passed**.
- Complete Language frontend/widget: **110/110 passed** across 16 files.
- Full Phase 9/Cloze, generation/provider/audio, curriculum, dictionary/Phrasebook, gamification, reference, and Anki regressions are included in and pass the complete Language suites. Focused Phase 9.5 plus surrounding backend run: **110/110 passed**; focused frontend run: **51/51 passed**.
- Broad backend: **666 passed, 1 skipped**.
- Broad frontend: **819 passed, 2 skipped, 1 unrelated existing Finance assertion failed**. `tests/finance-pack-d2.test.js` still expects a synchronous two-call refresh string while the already-dirty Finance implementation performs a background three-call refresh. No Language test failed and Phase 9.5 did not touch that feature.
- Production build: passed, **273 modules transformed** (existing bundle-size and non-module script warnings only).
- Python compilation and changed-JavaScript syntax: passed.
- Main v12 database: `integrity_check = ok`, 0 FK violations.
- Read-only 4,222,840,832-byte reference v3 database: `integrity_check = ok`, 0 FK violations; full scan 318.330 s.
- Real Edge synthetic smoke: **9/9 checks** at 1440×1000, 430×900, and 390×844; no horizontal overflow. It verifies repeated difficulty, directional confusion, no one-off confusion claim, evidence detail, recovery distinction, existing Cloze CTA, Anki unavailability, and historical/current statistics.

## Deviations and limitations

- Daily Quests were not changed. The phase made no new quest or XP promise, preserving existing versioned snapshots and reward invariants.
- Individual Anki review mistakes cannot be derived from available canonical data and are reported unsupported.
- Context diagnosis is deliberately exact and conservative; it does not generalize semantically related sentences.
- User dismissal/snooze was optional and not added, so no durable state or migration was justified.
- The only unmet repository-wide check is the unrelated pre-existing Finance frontend assertion described above. All applicable Phase 9.5 acceptance criteria and all Language-specific checks pass.

The exact next roadmap phase is **Phase 10 — Listening foundation with Bokmål browser TTS**. It is not started.
