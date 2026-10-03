# Language Phase 11.5 results

Status: **COMPLETE (2026-09-24)**. Scope is Progress Benchmarks and a lightweight Norway Preparation summary. The next phase is **11.6 Study Session Builder**, unstarted.

## Delivered contract

`language_learning/benchmark_content/v1.json` is fixed project-owned `INTERNAL_SYNTHETIC` content: family `norwegian-practical-receptive`, benchmark version 1, forms A/B, 16 items per form (six vocabulary recognition, four Cloze, three reading, three listening), item version 1, scoring version `benchmark-scoring/v1`, and a canonical SHA-256 content fingerprint. Forms share a blueprint but are not statistically equated. No CEFR, global proficiency, exam certification, or overall score is inferred. See [`LANGUAGE_BENCHMARK_CONTENT.md`](./LANGUAGE_BENCHMARK_CONTENT.md).

The server chooses and scores items. Multiple-choice answers stay in private static content; the browser gets options without `answer`. Cloze uses trim/NFC/casefold, preserving Norwegian diacritics and inflection. Reading passages never enter Reader. Listening uses the existing browser Bokmål voice at fixed rate 1.0 without cloud TTS; speech text is omitted from the DOM but is necessarily sent to browser speech synthesis. Device capability, voice ID, locale, and rate are stored with listening responses. No compatible voice yields an unavailable dimension with null percent, rather than a zero.

First completed run becomes the baseline; later runs become checkpoints. Partial responses persist and direct `#benchmarks/run/<id>` reloads. A run pins profile, selected item IDs, form, family/content/scoring versions, fingerprint, timestamps, responses, four scores, and comparison/repeat metadata. Prior item exposure records the first seen timestamp. A content fingerprint drift blocks continuing an active run. Results show correct/total/percent per dimension and no answer key.

Comparison policy `benchmark-comparison/v1` marks different forms/versions/fingerprints `NOT_COMPARABLE` with no percentage-point change. The same form and scoring contract is `REPEAT_INFLUENCED`; it may show an observed percentage-point difference with an explicit repeat warning, never as proof of learning. V1 has no unbiased `COMPARABLE` state; two short synthetic forms cannot establish statistical equivalence. This is the main interpretation limit.

Norway Preparation reads the existing five active Los public-service curriculum packs: Work and employment services (`nb.public-services.work`), Housing and property (`nb.public-services.housing`), Health and care (`nb.public-services.healthcare`), Traffic and transport (`nb.public-services.transport`), and Tax and duties (`nb.public-services.tax`). Each displays its existing `KNOWN`/`MASTERED` acquired count over the pack's eligible denominator and source/version. Latest completed Reading and Listening benchmark scores appear separately. There is no invented Everyday denominator or composite Norway-readiness percentage.

## Persistence and API

Migration 16 adds only `benchmark_runs` and `benchmark_responses` plus a profile history index. The main export advances to `language-learning-export/v16` and includes runs/responses/scores/versions/comparison metadata without answer keys. Profile-scoped routes provide list/start/get/respond/complete and `norway-preparation`. Existing same-origin write protection applies; cross-profile run access returns 404. Python and Vite static routes deny direct access to the benchmark source JSON. There is no provider call.

Verified pre-migration backup: `data/backups/language-learning-v15-pre-phase11-5-20260924T133745Z.sqlite` (integrity `ok`, zero FK violations). Main production DB migrated v15→v16 and has integrity `ok`, zero FK violations. Reference DB remains read-only schema v3 with full integrity `ok`, zero FK violations. The main DB contains no synthetic smoke runs; tests and Edge smoke used temporary databases.

## Verification

- New backend: `tests/test_language_benchmarks.py` (6 tests) and `tests/test_language_benchmarks_http.py` (1 test). They cover fingerprint/answer exclusion, partial resume, four scores, baseline/checkpoint/repeat, unavailable listening, zero writes to knowledge/exposure/Cloze/Listening/Grammar/XP tables, curriculum reconciliation, no composite, export, content drift, authorization, cross-profile rejection, and Python static denial.
- New frontend: `tests/language-benchmarks.test.js` (5 tests) covers reload-safe routes, history/Norway display, listening unavailable and transcript omission from DOM, separate results/repeat disclosure, and Vite source denial.
- Complete Language backend: **252 passed**. Complete Language frontend/widget: **145 passed**.
- Broad backend: **932 run, 926 passed, 6 skipped**. Broad frontend: **1,028 passed, 2 skipped, 1 failed**. The sole failure is the unchanged pre-existing Finance D.2 assertion in `tests/finance-pack-d2.test.js:108`; Finance code was not changed.
- Production build: pass, 324 transformed modules. Python compilation and changed JavaScript syntax checks: pass.
- Isolated headless Edge: landing and direct active-run routes at 1440×1000 and 390×844; narrow Listening capability branch; completed four-dimension result; UI-driven 16-item baseline, history, and FORM_B checkpoint at 390×844. Landing, runner, and result did not overflow horizontally. On this device the smoke accepts either compatible voice playback or the explicit unavailable state; it does not validate speech audio acoustics.
- The managed local API process was restarted after migration. Live health reports schema v16; read-only production benchmark history and Norway Preparation routes return successfully, with zero production benchmark runs and five active curriculum packs.
- Isolated one-run timings (milliseconds, single workstation, not latency guarantees): landing 2.60, start 25.66, response 22.72, resume 3.04, completion 26.32, history 4.26, Norway summary 25.43. Completion reads responses in one query; curriculum uses its existing bulk knowledge snapshot.

Benchmark actions write only benchmark rows. No canonical VocabularyLemma, LemmaKnowledge, KnowledgeEvent, ExposureEvent, Reader/Listening progress, ClozeAttempt, Mistake Intelligence, Anki, Goals, XP, Achievements, Quests, or Grammar evidence code path is called. Table-count assertions before/after a complete synthetic run verify representative mutation boundaries; the other boundaries follow the isolated service/store call graph.

## Limits

The content is small and synthetic. A person can memorize repeated items; `REPEAT_INFLUENCED` discloses this, and v1 does not claim an unbiased learning trend. Browser speech synthesis requires the text in a client payload, so someone inspecting network traffic can read the listening transcript even though the UI hides it. Voice quality and availability vary by device. No production user timed the run; the 15–30 minute target is an estimate from its 16 tasks, not a measured completion time. Headless Edge exercised the interface and capability branch, but a human listening-quality check remains useful.
