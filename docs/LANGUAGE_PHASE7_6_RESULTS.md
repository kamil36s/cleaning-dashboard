# Language Phase 7.6 — Evidence-driven gamification, completion, and campaigns

Status: **COMPLETE** on 2026-09-17. Phase 7.7 and every later phase remain not started.

## Scope and ownership

Phase 7.6 adds a deterministic reward overlay over canonical Language evidence. `GamificationService` may create its own awards, unlocks, quest snapshots, and campaign definitions, but cannot write vocabulary knowledge, Topics, exposures, Reader progress, Cloze attempts, Anki scheduling, Goals, KELLY/reference ranks, or reference rows. There is no manual XP route and GET/page-load operations do not award XP.

No CEFR estimate, dictionary/phrasebook work, curated practical pack, direct AI provider, Listening, Grammar, full Phase 9, social mechanic, random reward, negative XP, loss of level, shame, scarcity, or fake urgency was added.

## Versioned policies

- XP: `language.gamification-xp/v1`.
- account levels: `language.gamification-levels/v1`.
- achievements: `language.gamification-achievements/v1`.
- collections: `language.gamification-collections/v1`.
- Fast Track states: `language.gamification-fast-track-state/v1`.
- collection tiers: `language.gamification-collection-tiers/v1`.
- daily quests/weekly missions: `language.gamification-quests/v1`.
- campaigns: `language.gamification-campaigns/v1`.

## XP and anti-farming contract

| Canonical evidence | XP | Bound |
| --- | ---: | --- |
| complete Reader active minute | 2 | first 30 complete minutes per session |
| explicit Reader text completion | 20 | once per text completion source/rule |
| canonical Reader exposure event | 1 | first 20 events per Europe/Warsaw day; occurrence count does not multiply XP |
| Cloze `CORRECT` | 5 | first three scored attempts per target/day |
| Cloze `INCORRECT` | 2 | first three scored attempts per target/day |
| Cloze recovery (`CORRECT` after earlier `INCORRECT`/`REVEALED`) | +3 | first recovery per target/day |
| `REVEALED` or `SKIPPED` | 0 | never treated as correct |
| current supported weekly Goal completion | 15 | once per Goal/week |
| daily quest completion | 5 | once per snapshotted quest/day; at most three quests |

The durable `gamification_awards` ledger has a unique identity over profile, source type, source ID, reward key, and rule version. Each row stores its amount, timestamp, rule version, and inspectable metadata. Reconciliation can safely replay canonical history: duplicates become no-ops. Amounts are non-negative; no reward changes canonical evidence. Current mutable Goal storage cannot reconstruct every historical Goal definition/week, so Goal backfill is limited to a supported Goal completed in the current evaluated week.

Production reconciliation yielded **29 awards / 130 lifetime XP / 2 achievement unlocks**. The immediate repeat yielded **0 awards / 0 XP / 0 unlocks**. Lifetime XP is `SUM(gamification_awards.xp_amount)`; level is derived and not stored.

## Account levels

The cumulative floor is `25 × (level - 1) × level`: Level 1 = 0 XP, Level 2 = 50, Level 3 = 150, Level 4 = 300, Level 5 = 500, Level 6 = 750. The formula is monotonic, gives frequent early levels, and grows quadratically without an extreme exponential wall. The UI label is `Norwegian Level N` and explicitly says it is a motivation layer, not CEFR or proficiency.

## Achievements

The visible v1 catalogue contains 17 achievements:

1. `FIRST_STUDY`
2. `READER_FIRST_COMPLETION`
3. `READER_5_COMPLETIONS`
4. `READER_100_EXPOSURES`
5. `READER_1000_EXPOSURES`
6. `CLOZE_FIRST_SESSION`
7. `CLOZE_100_ATTEMPTS`
8. `CLOZE_500_ATTEMPTS`
9. `CLOZE_FIRST_RECOVERY`
10. `VOCABULARY_100_TRACKED`
11. `VOCABULARY_500_TRACKED`
12. `FAST_TRACK_1_RELIABLE_25`
13. `CONSISTENCY_7_DAYS`
14. `CONSISTENCY_30_DAYS`
15. `ANKI_FIRST_LINK`
16. `GENERATED_FIRST_STUDIED`
17. `GOAL_FIRST_COMPLETION`

Unlocks are stored once in `achievement_unlocks` with the original evidence threshold time, definition version, and snapshot. Reconciliation does not rewrite the timestamp. The gallery shows Locked/Unlocked state, categories, visible `unlocked / 17` completion, progress, and recent unlocks. There are no secret achievements, so hidden items cannot block visible completion. Achievements award no XP in v1.

## Collections and completion truth

Available collections are Fast Track 1–5, Reader 10 completed texts, Cloze 1,000 answers, and one partial collection for each user Topic. Every item exposes policy/denominator version, denominator source, total eligible, mapped, unresolved, excluded, completed, completion-rule version, percentage, and tier. Topic collections are explicitly partial user-mapped domains.

Fast Track denominators are KELLY `SOURCE_LEARNER_RANK` bands intersected with translated/playable Phase 9A targets. States are `UNSEEN`, `ENCOUNTERED`, `PRACTICED`, and `RELIABLE`. Reliable requires at least three `CORRECT` attempts across at least two Europe/Warsaw dates; reveal/skip never qualify and one correct answer is not mastery. Bronze/Silver/Gold/Complete thresholds are 25/50/75/100 percent and remain reward labels only.

Phase 7.5C idiom/MWE detection remains annotation-only. Phase 7.6 makes no phrase mastery or whole-database completion claim.

## Quests, missions, streaks, combos, and checkpoints

Approximately three daily quests are selected deterministically from real Cloze mistakes, unfinished Reader work, supported Goal gaps, and bounded fallback activities. The chosen list is snapshotted by Europe/Warsaw study date, timezone, policy version, and canonical fingerprint; progress stays derived from that day's canonical evidence. DST rollover is tested. Missed days cause no penalty.

Weekly missions are projections of existing enabled Goals and preserve their rule, period, target, and unit. No competing goal system exists. Current/best streak and 7/30-day study-day counts reuse canonical Reader semantics. No permanent progress is removed after a missed day.

Session-local combo and checkpoint features were optional in this slice and were deliberately not implemented; inventing a second attempt/result model would weaken the canonical-evidence boundary.

## Campaigns

`campaign_definitions` stores a generic user-owned name, description, target date, enabled state, milestone JSON, policy version, and timestamps. Supported current dimensions are Fast Track Reliable, Reader texts completed, Cloze attempts, study days, user-Topic known/mastered lemmas, and linked Anki notes. Campaigns expose separate milestone progress and never synthesize a universal readiness score.

The UI offers `Norway Spring 2027` only as an editable example. Future practical dimensions such as Work, Warehouse, Safety, Housing, Listening, or Grammar return `campaign_dimension_unavailable` until their owning phases provide authoritative denominators/evidence. A past target date is descriptive, not punitive; campaigns can be edited or disabled.

## UI, API, export, and storage

- `#progress` is reload-safe and renders account level/XP, Today's quests, consistency, inspectable collections, a locked/unlocked achievement gallery, and campaign create/edit/disable controls.
- Overview adds a compact motivation card and remains separate from proficiency.
- The opt-in lazy dashboard widget adds level, XP to next level, one quest, and the next campaign milestone without changing its hidden-by-default behavior.
- Thin reads: `GET /gamification`, `/achievements`, `/collections`, `/quests`, and `/campaigns` under a profile. Thin writes: create a profile campaign and patch a campaign. There is no client-trusted award endpoint.
- export v9 adds `gamificationAwards`, `achievementUnlocks`, `gamificationQuestSnapshots`, and `campaignDefinitions`; derived lifetime XP/level/percentages are not exported as competing truth.

Main schema v9 adds only `gamification_awards`, `achievement_unlocks`, `gamification_quest_snapshots`, and `campaign_definitions`. Reference schema remains v3 and was neither migrated nor mutated.

## Production migration and performance

The v8 production main DB was first backed up to `data/backups/language-learning-v8-pre-phase76-20260917-1122.sqlite`. The backup is 790,528 bytes, opens as v8, has `integrity_check = ok`, and has zero foreign-key violations. The additive v8→v9 migration completed; the v9 main DB is 864,256 bytes, has `integrity_check = ok`, and has zero foreign-key violations. The 4,222,840,832-byte reference v3 DB also has full `integrity_check = ok` and zero foreign-key violations.

Measured against production personal-scale data after migration:

| Operation | Time |
| --- | ---: |
| existing Overview 7-day statistics input | 16.890 ms |
| compact gamification summary reusing those statistics | 17.255 ms |
| quests | 6.372 ms |
| campaigns with no definitions | 2.167 ms |
| achievements | 225.953 ms |
| collections including production Fast Track denominators | 1,226.200 ms |
| complete Progress/gamification response | 1,469.954 ms |

Overview/widget summary reuses already-calculated Overview statistics, uses bounded same-day quest reads, skips historical campaign facts when no campaign exists, and only loads Fast Track collections when a campaign actually has a Fast Track milestone.

## Verification evidence

- New backend coverage: **10 tests** — eight in `test_language_gamification.py`, additive v8→v9 coverage in `test_language_store.py`, and thin HTTP/manual-XP rejection coverage in `test_language_api.py`.
- New frontend coverage: **5 tests** in `language-gamification.test.js`; the existing widget suite was extended with new compact-summary assertions.
- Focused gamification backend: **8 passed**.
- Dedicated reference: **15 passed**.
- Complete Language backend: **166 passed**.
- Complete Language frontend/widget: **93 passed**.
- Explicit Phase 9A backend/audio: **16 passed**.
- Explicit Phase 9A frontend/audio: **9 passed**.
- Broad backend: **540 passed, 1 skipped**.
- Broad frontend: **731 passed, 2 skipped**.
- Python compilation: **PASS**.
- changed-JavaScript syntax: **PASS**.
- production build: **PASS**, 265 modules transformed; existing non-module/chunk-size warnings only.

The checked-in isolated fixture `tests/fixtures/language/phase76-browser-smoke.html` passes **13/13** real Microsoft Edge assertions at desktop and 390px widths. It covers once-only persisted Cloze XP, level/XP, three quests, the 17-item locked/unlocked gallery, denominator disclosure, non-proficiency labeling, campaign create/edit/disable, compact-widget level/quest/campaign content, and no horizontal overflow. Desktop and narrow screenshots were visually inspected; no production API or user evidence was mutated.

## Deviations and limitations

- No combo or checkpoint was added; both were optional and require a future bounded design over canonical attempt evidence.
- No curated Everyday/Work/Warehouse/etc. collection is claimed because Phase 7.8 has not supplied reviewed manifests and denominators.
- No idiom/MWE completion is claimed because phrase knowledge does not yet exist.
- Historical Goal rewards/unlocks cannot be exhaustively reconstructed from mutable current Goal definitions; current supported period completion is reconciled honestly.
- The Progress response intentionally performs reference-backed collection computation and measures about 1.47 seconds on the production data set; compact Overview/widget paths do not perform that work unless an enabled campaign needs it.
- XP v1 has no direct Anki-review reward because the current canonical integration owns links/snapshots, not individual trustworthy review events.

All nine roadmap acceptance criteria and all 95 task acceptance checks are met; the combo/checkpoint clauses are explicitly conditional and those features were not implemented. The exact next separately authorized roadmap phase is **Phase 7.7 — Dictionary, meanings, translations, and personal phrasebook**.
