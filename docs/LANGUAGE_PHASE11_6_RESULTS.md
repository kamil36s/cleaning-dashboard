# Language Phase 11.6 results

Status: **COMPLETE (2026-09-24)**. Scope is the deterministic Study Session Builder only. Phase 12 remains unstarted.

## Contract and ownership

The read-only `GET /api/language/profiles/{profileId}/study-session?minutes=10|20|30` returns a derived preview. The profile and duration are the only client inputs. `#study-session` is reload-safe; the page offers a native duration selector, Build Session, the requested/planned minute summary, ordered segments, source labels, reasons, and real owner links. Start session opens the first segment. It creates no canonical study session or completion record. No migration or plan history was needed: the same canonical snapshot can be rebuilt, and owner modules continue to record actual learning.

Policy and estimation ID: **`language.study-session-builder/v1`**. The local date uses the existing `Europe/Warsaw` semantics; owner time windows are evaluated at the end of that local date so requests made at different times on the same day use the same temporal boundary. Response metadata includes the policy, estimation version, local date, timezone, requested/planned minutes, segment count, source availability, unavailable sources, and a SHA-256 fingerprint of the profile ID, date, duration, normalized eligible candidates, availability failures, and policy. The fingerprint is a reproducibility aid, not a secret or permanent plan ID. A changed owner snapshot may change it during the day.

Each segment has `segmentId`, `segmentType`, `sourceOwner`, `title`, `reason`, `estimatedMinutes`, `destinationRoute`, `sourceReference`, `selectionRule`, and `prioritySummary`. Reasons identify real owner evidence. No score or benchmark answer is exposed. Only `#` routes supported by the Language router are emitted.

## Source adapters and eligibility

| Source owner | Eligible work and handoff |
| --- | --- |
| Anki | Same-local-day persisted Anki sync with configured integration and positive due count; `#reviews`. The reason says this is stored sync metadata and the live queue must be checked in Anki. `status(probe=False)` makes no AnkiConnect request. |
| Mistake Intelligence | The bounded remediation list already embedded in `LearningPlanService` output; current Cloze mistake work opens `#cloze`. Recovered work is excluded by the owner. |
| LearningPlan / Goals | Reuses existing next-action items and active Goal gap facts. A Goal segment is eligible only when an existing Reader or Listening action provides a real destination. Weak/underexposed vocabulary opens Cloze. |
| Reader | Reuses the LearningPlan continuation, or an analyzed, non-completed text from the existing Reader listing; opens `#reader/text/{id}`. Completed text is suppressed. |
| Listening | Reuses the LearningPlan continuation, or an analyzed, non-completed item from the bounded existing Listening listing; opens `#listening/text/{id}`. |
| Curriculum | Existing active reviewed packs and their eligible-denominator progress. A gap requires meaningful profile context or some pack progress; a pristine profile is not filled with every untouched pack. Opens the real versioned pack route. |
| Grammar | Only an `ENCOUNTERED` supported pattern with authoritative examples; opens its pattern route. This means review of examples, never weakness, mastery, or due work. |
| Benchmarks | Latest completed run may add only **+2** to an already eligible Reader or Listening candidate when both dimensions have numeric scores and one is lower. It cannot create a segment or claim proficiency. Repeat-influenced results add an explicit familiarity warning to the reason. |

Owner failures are caught independently and listed in `unavailableSources`; other segments remain usable. Missing material yields `NO_ELIGIBLE_WORK`. The response's `sourceAvailability` distinguishes eligible work, no eligible work, and unavailable owners. No Gemini, Google TTS, dictionary, AnkiConnect, or web request is issued by the builder. It invokes persisted/local owner reads only.

## Selection rules

Base priority weights: Anki due 100, current mistake remediation 95, Goal gap 80, Reader/Listening continuation 75, weak vocabulary 70, underexposed vocabulary 65, curriculum gap 60, encountered Grammar examples 50, new Reader/Listening material 45. A completed benchmark may add +2 to eligible Reader/Listening work. Candidate ties break by stable segment ID. A mode already selected takes a 12-point diversity discount; urgent work still outranks near-tie diversity. Duplicate destinations are never selected twice. There is no random choice, XP/level/quest signal, or new scheduler.

Estimated blocks are fixed and approximate: Anki/Cloze/Goal/curriculum 5 minutes, Reader/Listening 7 minutes, Grammar example review 3 minutes. The planner never exceeds the requested 10/20/30-minute budget, never adds filler, and returns up to 3/4/5 segments respectively. It may return fewer minutes or no segments. The cooldown rule suppresses completed Reader and Listening material using their canonical progress. No separate recommendation-history store exists.

## Verification and limits

- New backend: seven policy/integration tests in `tests/test_language_study_session.py` plus one HTTP route test in `tests/test_language_study_session_http.py`. They cover determinism, budget/segment caps, priority/diversity, empty and partial plans, invalid minutes, same-day snapshot, zero exported canonical writes, owner failure, benchmark tie break, completed same-day Anki sync without a live probe, completed Reader/Listening cooldown, DISCOVERED Grammar exclusion, unstarted curriculum exclusion, and HTTP validation/profile ownership.
- New frontend: four tests in `tests/language-study-session.test.js` cover route reload, 10/20/30 form requests, ordered safe rendering, explanations, duration/source/handoff, empty state, and API failure; one test in `tests/language-page.test.js` covers route teardown and stale responses.
- Complete Language regression: **260 backend passed; 150 frontend/widget passed**. Broad backend: **938 run, 932 passed, 6 skipped, zero failures**; two final focused builder boundary tests were added afterward and pass separately. Broad frontend: **1,033 passed, 2 skipped, one unchanged Finance D.2 failure** in `tests/finance-pack-d2.test.js:108`. Finance was not modified.
- Production build passed with **325 modules**. Python compilation and changed JavaScript syntax passed.
- Isolated real Edge smoke in `scripts/smoke_language_study_session_edge.py` and its CDP driver passed at **1440×1000, 430×900, and 390×844** for both empty and synthetic populated plans. It exercised direct route load, all durations, source/reason/duration rendering, first-segment handoff, return, and element/document horizontal bounds. The populated browser fixture composes synthetic owner candidates and does not write the production DB.
- Isolated empty-profile preview timings on this workstation: 10 min **72.66 ms**, 20 min **46.28 ms**, 30 min **41.80 ms**. A synthetic 100-distinct-candidate pure composition took **0.97/1.00/1.08 ms** for 10/20/30 minutes. These are observations, not latency guarantees. Owner reads are bounded; Listening fallback inspects at most three materials and Reader fallback at most twenty listing entries.
- Main schema remains **v16**; reference schema remains **v3 read-only**. Final read-only `integrity_check` is `ok` on both, and both have **zero foreign-key violations**. No migration, backup, provider operation, study event, XP, Goal progress, Grammar/benchmark mutation, or reference write was required.

Limits: Anki due work requires a same-day stored sync and can become stale after that sync; the live queue remains Anki's authority. Fixed minutes are estimates, not measured completion times. Grammar offers example review only. Benchmark selection is a small modality tie break, not a diagnosis. A newly empty profile receives an empty plan until useful owned work exists.
