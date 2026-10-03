# Language benchmark content v1

Status: **INTERNAL_SYNTHETIC**. These tasks are project-owned examples, not CEFR calibrated, certified, externally normed, or statistically equated. They are not an examination or a global language level.

The frozen source is `language_learning/benchmark_content/v1.json`. It has family `norwegian-practical-receptive`, benchmark version `1`, scoring version `benchmark-scoring/v1`, two forms (`FORM_A`, `FORM_B`), and an SHA-256 fingerprint of canonical JSON. Each form contains 16 items: six vocabulary recognition, four Cloze, three reading comprehension, and three listening comprehension. A complete run is intended as a short personal check, approximately 15–30 minutes depending on reading and playback pace. Forms share counts and task types; there is **no claim of statistical equivalence**.

Vocabulary and comprehension questions use fixed options with one stored answer. Cloze accepts trim + Unicode NFC + casefold only; Norwegian diacritics and inflection remain meaningful. The server chooses the form, validates offered responses, stores actual responses, and scores each dimension separately as correct/total/percent. The browser never receives `answer` fields. Active-run payloads include listening speech text because browser speech synthesis requires it; the UI does not display that transcript. A technically inclined user can inspect that text, so the listening items are not tamper-proof. Source JSON is denied by both the Python static server and Vite's development file server, and it is not bundled into the production frontend.

The first completed run is `BASELINE`; later runs are `CHECKPOINT`. An active run resumes after reload. Form A and B alternate on completed-run count. Runs pin family, version, form, scoring version, fingerprint, selected item IDs, timestamps, scores, comparison policy, and responses. Item IDs and their timestamps remain available for repeat audits. A content fingerprint mismatch blocks continuing an active run; completed results remain viewable. No item-level answer key is returned after completion.

Comparison policy `benchmark-comparison/v1`:

- No completed baseline: `NO_BASELINE`.
- Different forms, benchmark versions, scoring versions, or content fingerprints: `NOT_COMPARABLE`, without a percentage-point delta.
- Same form, benchmark/scoring versions, and fingerprint: `REPEAT_INFLUENCED`. Per-dimension score differences may be shown as **observed** percentage-point changes with an explicit repeat warning. These changes are not attributed to learning.

There is no unqualified `COMPARABLE` state in v1. Two forms help avoid immediate exact-item reuse but cannot by themselves support an unbiased progress inference. New content requires a new version/fingerprint and an explicit future comparison rule; existing versioned material must remain available while active runs reference it.

Listening uses the existing browser Bokmål voice selection and fixed 1.0 speech rate. A compatible voice is device dependent. When unavailable, each listening item is recorded as unavailable and the dimension shows `UNAVAILABLE`, never zero percent. Stored environment metadata includes capability, selected voice ID, locale, and rate. Playback and submission never enter canonical Listening, Reader, Cloze, Grammar, knowledge, exposure, Goals, Anki, or XP paths.

Norway Preparation v1 is a read-only composition of the five active, source-defined Phase 7.8 Los public-service curriculum packs (work, housing, healthcare, transport, tax) and the latest completed Reading and Listening benchmark scores. Curriculum counts come from the existing curriculum bulk knowledge snapshot and `KNOWN`/`MASTERED` rule. The summary does not create an Everyday denominator or a composite readiness score.

A partly available Listening section reports `PARTIAL`, its scored denominator, and the number of unavailable items.
