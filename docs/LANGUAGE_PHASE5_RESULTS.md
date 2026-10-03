# Language Learning Phase 5 results

Status: **COMPLETE**  
Date verified: 2026-09-16  
Database schema version: 4  
Frontend page: `language.html`

## 1. Outcome

Phase 5 turns the existing Reader and canonical Vocabulary into a truthful personal analytics dashboard. It adds deterministic classifiers, event-derived statistics, manual source-aware Topics, versioned weekly Goals, a bounded deterministic learning plan, words to recycle, the completed Overview/Statistics/Goals/Topics views, and a compact opt-in main-dashboard widget.

All values come from canonical Language facts. No aggregate counter is manually incremented, no ranked-frequency band is inferred from `wordfreq`, and no Anki/AI/Cloze/Listening/Grammar capability was added.

## 2. Files created

- `language_learning/statistics.py`
- `language_learning/learning_plan.py`
- `js/language/charts.js`
- `js/language/views/statistics.js`
- `js/language/views/goals.js`
- `js/language/views/topics.js`
- `js/widget-language-learning.js`
- `js/dashboard-widget-visibility.js`
- `tests/test_language_statistics.py`
- `tests/language-statistics.test.js`
- `tests/widget-language-learning.test.js`
- `docs/LANGUAGE_PHASE5_RESULTS.md`

## 3. Files modified

- `language_learning/migrations.py`, `store.py`, `service.py`
- `server.py`
- `language.html`, `language.css`
- `js/language/api.js`, `app.js`, `router.js`, `state.js`
- `js/language/views/overview.js`
- `index.html`, `styles.css`
- `js/dashboard-widget-loader.js`, `js/dashboard-settings.js`
- `data/widget-order.json`
- `tests/test_language_store.py`, `tests/test_language_api.py`
- `tests/language-api.test.js`, `tests/language-page.test.js`, `tests/language-router.test.js`
- `docs/LANGUAGE_IMPLEMENTATION_PLAN.md`, `docs/LANGUAGE_RUN_PROGRESS.md`

Unrelated dirty-worktree changes were preserved.

## 4. Schema v4 and migration

The forward-only additive v4 migration adds exactly three tables:

- `topics`: profile-scoped slug/name/description, optional same-profile parent, archive flag, timestamps;
- `topic_lemmas`: topic/lemma/profile identity, weight `(0,10]`, `MANUAL|IMPORT` provenance, `MANUAL|IMPORTED` state, optional source reference, timestamps, and same-profile foreign keys;
- `goal_definitions`: supported metric, weekly period, positive target, matching unit, optional active dates, week start, timezone, enabled state, rule version, and timestamps.

There are no statistics rollup, saved-plan, Anki, AI, Cloze, Listening, or Grammar tables. The database now has 19 Language tables. Export advances to `language-learning-export/v4` and includes Topics, memberships, and goal definitions.

Controlled canonical backups bracket the migration:

- pre-migration v3: `language-learning-v3-20260916T121250830961Z.sqlite`;
- post-migration v4: `language-learning-v4-20260916T124137355812Z.sqlite`.

Both backups and the canonical v4 database passed integrity and foreign-key checks.

## 5. Classifier policy

Policy version: `language.classifiers/v1`. Classifiers are computed from `LemmaKnowledge`, `KnowledgeEvent`, and real exposure evidence; no classifier is a stored boolean.

- **PASSIVE**: tracked, explicit `KNOWN`, and below the active threshold.
- **ACTIVE**: tracked, explicit `KNOWN`, with recall at least 4 or production at least 3. Exposure alone never proves active use.
- **MASTERED**: tracked and explicitly `MASTERED`. Exposure count never promotes mastery.
- **WEAK**: tracked and `LEARNING`, or `KNOWN` with any supplied recognition/recall/production score at most 2. No nonexistent Anki failure signal is used.
- **RECENT**: tracked and first meaningfully advanced (falling back to first seen) less than 14 days before the calculation instant.
- **UNDEREXPOSED**: tracked `LEARNING` or `KNOWN` with fewer than 3 canonical Reader exposures.

Boundary behavior, excluded items, exposure-only evidence, and deterministic reasons are tested.

## 6. Topics and mastery

Topics are user-created; no starter-topic vocabulary membership is seeded. Phase 5 accepts manual membership only through the public service and UI. The schema remains ready to preserve a later verified import with explicit provenance, but unreviewed import assignment is rejected now.

Topic mastery policy is `language.topic-mastery/v1`. Each linked lemma contributes its relevance weight multiplied by a status factor:

- `NEW = 0`
- `LEARNING = 0.35`
- `KNOWN = 0.75`
- `MASTERED = 1.0`

Weighted mastery is the weighted sum divided by total mapped weight. The response also includes mapped count, weight, status counts, defensible passive/active/mastered counts, provenance, and frequency availability. Every response states `USER_MAPPED_LEMMAS_ONLY`, `completeTopicDomain: false`, and explains that the percentage is a partial user-mapped denominator.

## 7. StatisticsService

Policy version: `language.statistics/v1`. Queries read canonical facts directly; no drifting aggregate or materialized rollup exists.

Implemented analytics include:

- 7/30/90-day and all-time ranges using Warsaw-local calendar starts;
- historical learning/known/mastered/tracked series reconstructed from lemma creation and append-only knowledge transitions;
- Reader exposure occurrences, daily series, unique lemmas, distribution, most-exposed lemmas, and underexposed items from `ExposureEvent` only;
- Reader active seconds/minutes from server-authoritative `StudySession.active_seconds`;
- started/completed texts and analyzed token counts from persisted progress/documents;
- recent reading history;
- a real activity streak;
- immutable completion-coverage history and average-at-completion coverage;
- topic progress;
- an explicit `NOT_CONFIGURED` exact ranked-frequency state.

Today's state is never projected backward. Historical completion snapshots are never rescored.

## 8. Streak, timezone, and weekly boundaries

The canonical timezone is `Europe/Warsaw`, with ISO week start Monday unless a goal specifies another valid ISO weekday. A qualifying streak day requires at least one real Reader active second, accepted Reader exposure, or explicit text completion. Importing, analyzing, or opening a page does not qualify.

Weekly bounds are built as timezone-aware local midnights and then converted to UTC. Tests cover local midnight, ordinary week boundaries, the 167-hour spring-forward week, and the 169-hour fall-back week.

## 9. Goals

Goal policy is `language.goals/v1`. Supported combinations are:

- `NEW_WORDS / WORDS`
- `ACTIVE_READING_MINUTES / MINUTES`
- `TEXTS_COMPLETED / TEXTS`
- `READER_EXPOSURES / EXPOSURES`

Only `WEEK` is currently supported. Targets must be positive; metric/unit, weekday, timezone, and ISO active-date ranges are validated. Progress is recomputed from qualifying knowledge transitions, Reader active seconds, explicit completions, or Reader exposure occurrences. Stored goal state never contains authoritative progress.

Responses include current, target, remaining, capped percentage, completed, active-now, and UTC instants corresponding to the configured local period. The UI formats the period in Europe/Warsaw and supports create, edit, enable/disable, target, and optional active dates.

## 10. LearningPlanService and Words to Recycle

Plan rule version: `language.learning-plan/v1`. The fixed priority is:

1. continue the most recently touched unfinished analyzed Reader text;
2. address the largest supported enabled/active weekly goal gap;
3. review weak vocabulary;
4. recycle underexposed vocabulary;
5. read the latest analyzed text, or add/analyze a text when none exists.

Results sort deterministically and are capped at five actions. The same facts, calculation instant, and rule version produce the same result. Empty profiles receive only the truthful add/analyze action. Anki is explicitly `NOT_IMPLEMENTED` with zero recommendations.

Recycle rule version: `language.recycle/v1`. Candidates are Weak, Recent, or Underexposed. Weak candidates sort first, then recent, then underexposed; ties use fewer exposures, higher available Zipf score, normalized lemma, and stable ID. The default list is capped at eight and reports categories plus reasons such as `learning`, `recently added`, or `2 exposures`.

## 11. Language Overview

`#overview` now contains:

- real study streak, seven-day active study time, tracked vocabulary, and Reader exposure summary;
- conservative Passive/Active/Mastered counts and definitions;
- an accessible event-derived vocabulary line chart;
- Today's Plan and Words to Recycle;
- topic mastery with partial-denominator disclosure;
- current supported weekly goal;
- recent canonical Reader history;
- truthful ranked-frequency `Not configured` and Anki `Not implemented yet` states.

Empty sections render explicit actions or no-evidence messages. They do not synthesize values or graph series.

## 12. Statistics, Goals, and Topics UI

- `#statistics` provides range controls, vocabulary growth/state, exposure series/distribution/ranking, active reading/streak, frozen coverage history, topic progress, and ranked-frequency unavailability.
- `#goals` provides compact create/edit/enable controls and event-derived progress.
- `#topics` provides create, list, inspect, rename/edit, archive, canonical vocabulary search, assign, and remove. Membership labels preserve provenance and the mastery denominator warning is always visible.

All displayed user/server strings are inserted through DOM text nodes. Phase 5 charts are accessible SVG/DOM elements with no general chart dependency or canvas.

## 13. Main-dashboard widget

The compact opt-in card uses stable key `data-widget="language-learning"` and the existing dashboard registry/settings/order system. It shows the local SVG Norwegian flag, streak, known/mastered counts, seven-day active minutes, one weekly goal, and one next action. It does not reproduce Overview or show Anki data.

The default is hidden. The lazy loader filters hidden keys before dynamic import, and the pure filter is tested. When shown, existing settings provide hide/show, numeric ordering, and span/resize behavior. A narrow four-column rail-overlap adjustment remains scoped to this widget.

## 14. Thin API routes

Added reads:

- `GET /api/language/profiles/{id}/overview`
- `GET /api/language/profiles/{id}/statistics`
- `GET /api/language/profiles/{id}/learning-plan`
- `GET /api/language/profiles/{id}/widget-summary`
- `GET /api/language/profiles/{id}/topics`
- `GET /api/language/topics/{id}`
- `GET /api/language/profiles/{id}/goals`

Added writes:

- `POST /api/language/profiles/{id}/topics`
- `PATCH /api/language/topics/{id}`
- `POST /api/language/topics/{id}/lemmas`
- `DELETE /api/language/topics/{id}/lemmas/{lemmaId}`
- `POST /api/language/profiles/{id}/goals`
- `PATCH /api/language/goals/{id}`

`server.py` only parses bounded requests and delegates to `LanguageService`.

## 15. Tests

Exact new Phase 5 backend tests: **14**.

| Area | New tests |
| --- | ---: |
| v3-to-v4 migration preservation | 1 |
| classifiers/statistics/topics/goals/plan/timezone fixtures | 12 |
| Phase 5 HTTP vertical slice | 1 |

Exact new Phase 5 frontend tests: **12**.

| Area | New tests |
| --- | ---: |
| thin API routes | 1 |
| Overview/Statistics/Goals/Topics page flows | 3 |
| chart helpers/accessibility/empty states | 3 |
| dashboard widget/profile/render/lazy visibility | 5 |

Existing router assertions were expanded for Phase 5 routes without increasing that file's test count.

## 16. Final verification

| Command/check | Exact result |
| --- | --- |
| complete Language backend suite | 97 passed, 0 failed |
| complete Language frontend suite | 59 passed, 0 failed |
| real Stanza fixtures | 2 passed; downloads blocked and one persisted pipeline reused |
| broad backend suite | 445 passed, 1 skipped, 0 failed |
| broad frontend suite | 687 passed, 2 skipped, 0 failed |
| `npm run build` | passed; existing non-module/large-chunk warnings only |
| Python compilation | passed |
| changed JavaScript syntax checks | passed |
| canonical database | schema v4; 19 tables; `integrity_check = ok`; zero FK violations |

The non-failing Python dependency warning and existing Happy DOM connection-refused diagnostics remain baseline noise and did not create failures.

## 17. Performance observations

Statistics, goal progress, topic mastery, and plan generation use bounded direct SQLite queries over current personal-scale canonical facts. No profiling result justified materialized rollups. The real-browser views and API responses remained responsive with the synthetic Phase 5 fixture. If future data volume grows materially, profile these exact queries before introducing cache invalidation or rollups.

## 18. Visual verification

Real headless Edge rendering was inspected with an isolated synthetic schema-v4 database at 1440 × 1000 for Overview, Statistics, Goals, Topics, and topic detail; at 430 × 900 for Overview, Statistics, Goals, and Topics; and in representative 2-, 3-, and 4-column main-dashboard layouts for the widget.

Density, hierarchy, labels, controls, charts, empty states, the persistent Norwegian identity, wrapping, and overflow passed. Inspection found and corrected Topic form/metadata overflow, Warsaw period formatting, and four-column side-rail overlap. The isolated server was stopped and canonical personal learning content was not populated for screenshots.

## 19. Dashboard recovery verification

Changes to `index.html`, `styles.css`, the widget loader, settings, and widget-order JSON are narrow and keyed only to `language-learning` (plus the small reusable visibility filter). Full frontend tests pass across Todo, Temperature helpers, Habits, AI Usage, Event Countdown, and Kitchen. Real 2/3/4-column screenshots visibly retained Temperature, Cleaning, Self-care/Habits surfaces, Reading, AI Usage, and neighboring cards while the Language widget rendered.

## 20. Deviations, limitations, and acceptance

- Exact lemma ranks remain unselected. Top-500/1000/2000/5000 coverage is deliberately absent; `wordfreq` continues to supply Zipf scores only.
- No topic definitions or memberships are seeded. This is stricter than the optional starter-topic suggestion and avoids fabricated taxonomy/membership.
- Import provenance exists in the schema, but Phase 5 public commands accept manual membership only until a verified dataset/review workflow exists.
- Active vocabulary is intentionally conservative because Phase 4 has no independent production-test stream.
- Reading seconds are attributed to the session start day because the canonical session currently stores aggregate active seconds rather than interval slices.
- Historical knowledge accuracy begins with available creation/events; older semantics cannot be reconstructed beyond recorded events.
- There are no materialized statistics, saved plans, badges, XP, AI advice, or Phase 6+ features.

All 46 Phase 5 acceptance criteria pass. There are no unmet Phase 5 criteria.

The exact next recommendation is **Phase 6 only**: add a fixed/allowlisted local AnkiConnect adapter, explicit capability/status handling, preview/dry-run before writes, stable lemma-to-note/card links and conflict/idempotency protection, then pull only supported scheduling/review evidence through `LanguageService`. Preserve all Phase 5 classifier/statistics semantics and do not begin AI generation, Cloze, Listening, Grammar, or a second language as part of Phase 6.
