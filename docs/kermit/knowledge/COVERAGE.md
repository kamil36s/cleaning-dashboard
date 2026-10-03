# Kermit static knowledge coverage

Reviewed 2026-10-03 against task branch `ai/codex/kermit-b5`, `PROJECT_MAP.md`, direct `index.html` `data-widget` registrations, the loader, current source, the positive manifest, and Kermit tests. This is a **Phase 8 work inventory**, not evidence that Kermit can read live user data. A name in L0 or a shared admitted file does not count as covered.

## Scope and counting rule

The inventory has **54 bounded coverage units**: 34 page/app rows from the current Project Map, 16 additional dashboard-only widget flows, and four shared infrastructure units. Related surfaces that share one canonical owner are one unit: Finance includes Bills, Music includes Last.fm, Films includes Oscars, Live Workout includes Strength, and Events and Event Countdowns are distinct because the latter has a separate settings/notification flow. Android companions are documented with their owning feature. This grouping avoids duplicate packs while retaining every active surface and backend relationship.

The current map has **34 page/app rows** and **36 backend-domain rows** (some rows contain multiple API prefixes). AST inspection of literal route paths in `server.py`, `training_runtime.py`, and `network_monitor/api.py` identifies **45 implemented `/api/<domain>` prefixes** across central, training and network services, including the Sync pilot. This excludes `/api/token` and `/api/v1` substrings in external provider URLs. The Project Map includes the confirmed `feelings` widget and `/api/dashboard`, `/api/phone-tracker`, `/api/phone-todo`, `/api/mental-health`, `/api/feelings`, and `/api/football` rows; those later feature domains are not validated merely by appearing in inventory. Todo uses `/api/settings/todo` and its companion uses `/api/phone-todo`, not a dedicated `/api/todo` route. `index.html` and `js/dashboard-widget-loader.js` register **34 distinct direct widget keys**; 13 are hidden in shipped defaults. Inactive `js/widget-*.js` files are excluded until registered. `404.html` is a static fallback, not a feature unit. The four infrastructure units are central API/static security, local process lifecycle, BLE collection, and Kermit's own static pipeline.

The four pilots (`quote`, `finance`, `language-learning`, `weather`), B1 (`cleaning`, `reading`, `todo`), B2 (Dashboard, Settings, central API/static security), B3 (Habits App, legacy summary, timeline, Self-care), B4A (Weight/steps, Diet, Sleep), and B4B (Mental Health, Sensors, BLE collector) remain validated. B5 adds Live Workout/Strength, Heart-rate history, Ring and local process lifecycle: **24/54 units are now fully validated, 30 remain**. The explicit manifest admits 201 files. Admission of shared `index.html` or `server.py` never implies that every widget or route in those files is admitted as a feature subsystem. The other 30 have no validated L1-to-grounding chain even when L0 or feature docs exist.

Status vocabulary: `NOT_STARTED`, `IN_PROGRESS`, `DOCUMENTED`, `INDEXED`, `VALIDATED`, `NEEDS_REVIEW`, `STALE`. Each axis is separate. Documentation means a reviewed L1 pack; admission means a positive manifest entry for its selected safe sources; indexing means current deterministic artifacts; retrieval and grounding require focused regressions. `VALIDATED` is used only after the corresponding test/check passes. A source edit after this review can move admission/indexing/retrieval to `STALE`; a pack requiring human resolution becomes `NEEDS_REVIEW`. `DOCUMENTED` or `INDEXED` alone never means complete.

## API domain inventory

This is a route-prefix drift baseline, **not** feature validation. The read-only checker compares it with literal implementation paths in the three owning services.

`/api/ai-usage` `/api/artist-facts` `/api/bm365` `/api/brutal-assault-2027` `/api/budget` `/api/cinema-city` `/api/classical-library` `/api/cleaning` `/api/dashboard` `/api/diet` `/api/events` `/api/feelings` `/api/films` `/api/football` `/api/google-calendar` `/api/habits` `/api/health-connect` `/api/jobhunt` `/api/journal` `/api/journal-htr` `/api/kitchen` `/api/language` `/api/lastfm` `/api/live-workout` `/api/mental-health` `/api/music` `/api/network` `/api/oscars` `/api/phone-todo` `/api/phone-tracker` `/api/reading` `/api/ring` `/api/rym-polish-black-metal` `/api/screensaver-config` `/api/screensaver-status` `/api/sensor` `/api/settings` `/api/spotify` `/api/steps` `/api/strength` `/api/sync` `/api/synchrobook` `/api/timeline` `/api/voice-journal` `/api/weight`

## Coverage ledger

| Unit / current surface | Batch | Documentation | Source admission | Indexing | Retrieval validation | Grounding validation |
| --- | --- | --- | --- | --- | --- | --- |
| Main dashboard / widget loader, ordering, settings composition | B2 | VALIDATED | VALIDATED | VALIDATED | VALIDATED | VALIDATED |
| Settings page / `/api/settings/*` | B2 | VALIDATED | VALIDATED | VALIDATED | VALIDATED | VALIDATED |
| Developer docs page | B7 | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED |
| Cleaning page + `cleaning` widget / `/api/cleaning/*` | B1 | VALIDATED | VALIDATED | VALIDATED | VALIDATED | VALIDATED |
| Finance / Budget page + `budget`,`bills` / `/api/budget/*` | Pilot | VALIDATED | VALIDATED | VALIDATED | VALIDATED | VALIDATED |
| Reading page + `reading` widget / `/api/reading/*` | B1 | VALIDATED | VALIDATED | VALIDATED | VALIDATED | VALIDATED |
| Synchrobook page / `/api/synchrobook/*` | B7 | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED |
| Voice journal page / `/api/voice-journal/*` | B6 | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED |
| Written journal page / `/api/journal/*` | B6 | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED |
| Journal OCR/HTR page + `journal-htr` / `/api/journal-htr/*` | B6 | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED |
| Great Timeline page / `/api/timeline/*` | B6 | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED |
| History Wiki app | B7 | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED |
| Todo board + `todo` widget / `/api/settings/todo` | B1 | VALIDATED | VALIDATED | VALIDATED | VALIDATED | VALIDATED |
| Job Hunt page + `jobhunt` / `/api/jobhunt/*` | B8 | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED |
| AI Usage page + `ai-usage` / `/api/ai-usage` | B8 | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED |
| Phone Activity page + `phone-activity` / `/api/phone-tracker/*` | B8 | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED |
| Language Learning page + `language-learning` / `/api/language/*` | Pilot | VALIDATED | VALIDATED | VALIDATED | VALIDATED | VALIDATED |
| Music hub / `/api/music/*`,`/api/lastfm/*` | B9 | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED |
| Films and Oscars pages + `films` / `/api/films/*`,`/api/oscars/*` | B9 | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED |
| Classical Library page + `classical-library` widget / `/api/classical-library/*` | B9 | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED |
| BM365 page + `bm365` widget / `/api/bm365/*` | B9 | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED |
| Brutal Assault 2027 page + `brutal-assault-2027` widget / `/api/brutal-assault-2027/*` | B9 | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED |
| RYM Polish BM Top 100 page + `rym-polish-black-metal-top-100` widget / `/api/rym-polish-black-metal/*` | B9 | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED |
| Live Workout / Strength page + `live-workout` / runtime and `/api/strength/*` | B5 | VALIDATED | VALIDATED | VALIDATED | VALIDATED | VALIDATED |
| Heart-rate history page / runtime and Health Connect | B5 | VALIDATED | VALIDATED | VALIDATED | VALIDATED | VALIDATED |
| Sleep page / Health Connect read model | B4A | VALIDATED | VALIDATED | VALIDATED | VALIDATED | VALIDATED |
| Mental Health page + `mental-health` / `/api/mental-health/*` | B4B | VALIDATED | VALIDATED | VALIDATED | VALIDATED | VALIDATED |
| COLMI ring page / `/api/ring/*` | B5 | VALIDATED | VALIDATED | VALIDATED | VALIDATED | VALIDATED |
| Blood pressure page / localStorage | B11 | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED |
| Breathwork page / localStorage | B11 | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED |
| Sensors page + `sensors` / `/api/sensor/*` | B4B | VALIDATED | VALIDATED | VALIDATED | VALIDATED | VALIDATED |
| Kitchen / Hitchen pages / `/api/kitchen/*` | B10 | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED |
| Football Dashboard page / `/api/football*` | B10 | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED |
| Spotify screensavers / `/api/spotify/*` and screensaver routes | B11 | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED |
| `weather` widget / Open-Meteo browser API | Pilot | VALIDATED | VALIDATED | VALIDATED | VALIDATED | VALIDATED |
| `aqi` widget / GIOS | B11 | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED |
| `self-care` widget / external task source plus Timeline activity | B3 | VALIDATED | VALIDATED | VALIDATED | VALIDATED | VALIDATED |
| `phone-telemetry` widget / exported snapshots | B8 | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED |
| `weight-cut` widget / weight, steps, Health Connect | B4A | VALIDATED | VALIDATED | VALIDATED | VALIDATED | VALIDATED |
| `diet` widget / `/api/diet/*` | B4A | VALIDATED | VALIDATED | VALIDATED | VALIDATED | VALIDATED |
| `weekly-insights` widget / cross-feature APIs | B11 | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED |
| `quote` widget / external providers | Pilot | VALIDATED | VALIDATED | VALIDATED | VALIDATED | VALIDATED |
| `cinema-city` widget / `/api/cinema-city/*` | B10 | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED |
| `network-monitor` widget / separate `/api/network/*` | B10 | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED |
| `habits` summary widget / modern preview or generated legacy view | B3 | VALIDATED | VALIDATED | VALIDATED | VALIDATED | VALIDATED |
| `events` widget / local and Google Calendar | B10 | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED |
| `event-countdowns` widget / event settings and notifications | B10 | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED |
| `habits-app` widget / `/api/habits/*` | B3 | VALIDATED | VALIDATED | VALIDATED | VALIDATED | VALIDATED |
| `habits-timeline` widget / legacy generated view and upload | B3 | VALIDATED | VALIDATED | VALIDATED | VALIDATED | VALIDATED |
| `feelings` widget / How I Feel companion and `/api/feelings/*` | B8 | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED |
| Central API, static privacy and route ownership | B2 | VALIDATED | VALIDATED | VALIDATED | VALIDATED | VALIDATED |
| Local process lifecycle / Vite, central API, training, network | B5 | VALIDATED | VALIDATED | VALIDATED | VALIDATED | VALIDATED |
| BLE collector / scale and environment ingest | B4B | VALIDATED | VALIDATED | VALIDATED | VALIDATED | VALIDATED |
| Kermit static index/retrieval/grounding/service pipeline | B11 | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED |

## Independently reviewable batches

Each later batch starts by rechecking `PROJECT_MAP.md`, current page/widget registrations, routes, sources, schemas and tests. It finishes only with reviewed packs, exact safe admissions, a deliberate deterministic rebuild, retrieval questions, grounding regressions, and freshness checks. Batch labels specify review scope, not a commitment to implement every listed item in one execution.

| Batch | Units | Dependency and reason |
| --- | --- | --- |
| **B1 complete** | Cleaning, Reading, Todo (3) | Active page/card pairs with immediate daily value; compare SQLite task/action and book/log stores with a file-backed browser mirror. Tests and symbols are small enough for one source review. |
| **B2 complete** | Dashboard, Settings, central API/static boundary (3) | Reviewed shared ownership and privacy rules with targeted `server.py` inspection, exact admission, deterministic indexing, retrieval and grounding regression. |
| **B3 complete** | Habits app, legacy summary, habits timeline, self-care (4) | Reviewed canonical habits SQLite versus generated legacy views, external Self-care task ownership and Timeline activity. B2 dependency was verified first. |
| **B4A complete** | Weight/steps, Diet, Sleep (3) | Reviewed normalized versus raw/cache telemetry, source precedence, diet estimates and suggestions, and derived sleep analysis. B1–B3 dependencies verified first. |
| **B4B complete** | Mental health, sensors, BLE collector (3) | Reviewed private SQLite assessments versus questionnaire definitions, normalized sensor history versus latest cache, and the separate collector lifecycle. The collector source remains excluded because it embeds device identifiers. |
| B5 | Live Workout/Strength, heart-rate history, ring, process lifecycle (4) | Independent runtime port and SSE, cross-device heart data, durable checkpoints, service restart ownership. Depends on B2 and relevant B4 telemetry facts. |
| B6 | Written journal, voice journal, HTR, Timeline (4) | Privacy-sensitive source/derived/workflow boundaries and cross-feature activity composition. Depends on B2; avoid indexing original pages/audio. |
| B7 | Synchrobook, developer docs, History Wiki (3) | Raw book/history input versus generated artifacts and static presentation. Depends on B2; History Wiki archive remains excluded. |
| B8 | Job Hunt, AI Usage, Phone Activity, Phone Telemetry, Feelings (5) | Distinguish durable private evidence from mirrors, exported snapshots, and companion queues. Depends on B2; Job Hunt may need its own sub-batches. |
| B9 | Music/Last.fm, Films/Oscars, Classical Library, BM365, Brutal Assault, RYM Top 100 (6) | Cross-list media imports and caches versus canonical ratings; divide into two executions if needed. Depends on B2. |
| B10 | Events, Event Countdowns, Cinema City, Kitchen/Hitchen, Football, Network Monitor (6) | External integration/cache relationships and separate network service. Depends on B2. |
| B11 | AQI, weekly insights, blood pressure, breathwork, Spotify screensavers, Kermit pipeline (6) | Browser-only and cross-feature explanations plus final self-documentation. Weekly insights depends on B1/B3/B4/B8; AQI and Spotify depend on B2/B10 provider boundaries. |

## Important dependencies and current gaps

- `server.py` is already admitted as **shared metadata only**; that does not establish implementation ownership for new routes. Each batch must name exact handlers and source modules. The generic settings API is Todo's backend, not a dedicated `/api/todo` service.
- `js/todo-projects-backlog-seed.js`, `js/reading-history.js`, and `js/cleaning-dependencies.js` are referenced for ownership/migration/dependency context but intentionally **not admitted**: the first carries source-seeded project content, the second includes title-specific legacy fixes, and the third embeds a specific Todo identity. The B1 index uses the store/API and selected UI modules instead; these are deliberate excluded references, not missing source files.
- B3 excludes `habits_store.py`, `supplements_store.py`, `js/habits-app-model.js`, `js/habits-app-api.js`, `js/widget-habits-app.js`, `js/habits.js` and `js/habit-timelines.js` because they contain embedded personal medication/product names. It also excludes generated `js/habit-data.js`, `public/data/habits.json`, runtime SQLite, Timeline JSONL, raw Loop Habit DB/CSV and reports. Reviewed L1 packs cite their contract while exact safe schedule, uploader, builder, Self-care and Timeline source metadata is admitted. Excluded implementation changes require manual pack review.
- B4A excludes all `data/scale/*`, `data/health-connect/*`, `data/diet/diet.json`, ring runtime stores, personal reports/exports, raw advertisements, logs and backups. `scripts/scan_ble.py` embeds device addresses; `js/widget-weight-cut.js` and `js/weight-ma-stats.js` embed personal weight/goal defaults; `js/widget-diet.js` and `js/diet-estimation.js` hardcode calorie target/baseline values. Their contracts were reviewed but their files were not admitted. B4A health and meal test fixtures were run but not admitted. Exact safe Sleep/report modules and three reviewed packs were added.
- B4B excludes `data/mental-health.sqlite` and sidecars, personal assessment/check-in exports and answers, questionnaire JSON item text, `data/sensor/*`, `data/scale/*`, raw BLE evidence, logs and backups. `scripts/scan_ble.py` retains fixed local MAC addresses and remains excluded; Sensors UI source includes a fixed local sensor/location label and is reviewed but excluded. B4B admits three packs, the questionnaire contract README, safe Mental Health source modules and the launcher mapping. Admission is implementation metadata, not private runtime access.
- B5 excludes workout, strength and ring SQLite stores, Health Connect snapshots, plan/settings JSON, watch/ring samples, sensor packets, device identifiers, postcards and logs. The large workout widget/page modules and startup scripts were reviewed for contracts but are not admitted. Safe implementation metadata and four reviewed packs establish ownership, not access to a live session or service status.
- `/api/phone-todo` is an implemented Todo Pocket companion route in the existing Todo domain and Project Map; this inventory entry corrects a pre-existing route-prefix checker finding. Its separate companion behavior was not reviewed as part of B4B or silently treated as a newly validated subsystem.
- Cleaning history uses Warsaw-midnight days, its state uses a 24-hour UTC end after a Warsaw-midnight start, and the phone goal/widget uses a 06:00 Warsaw rollover; the state rule can differ on DST days. The widget's Todo mop dependency and forecast goal are derived presentation state. Reading's browser guards and display fee estimate are not canonical pages or real library charges. Todo's asynchronous file save can leave its local mirror ahead of server state. These distinctions are in the three packs and `GAPS_AND_CONFLICTS.md`.
- `PROJECT_MAP.md` now includes `feelings` and the five missing backend-domain rows found in B1/B2. Their owning feature packs remain unvalidated; an inventory correction is not source admission.
- The current L2 builder and Phase 4 ranker began as four-pilot implementations. B1 extends only their reviewed IDs/aliases and exact admissions. A future batch must explicitly add its IDs and focused tests; a pack file alone does not make it retrievable.
- No Phase 9 context is needed for Phase 8. Page-aware browser payloads and DOM capture remain out of scope.

## Deterministic maintenance workflow

1. **Detect scope changes:** run `python -B -m kermit_index coverage-check`. It reports new direct widgets absent from this ledger, new implementation API domains absent from the inventory above, changed/missing admitted sources, missing checked pack paths/markers and changed validated-pack fingerprints. Compare root page entries and `vite.config.js` with the 34 page groups separately. New keys/domains are `NOT_STARTED` until reviewed. Treat inactive modules separately.
2. **Detect source drift:** run `python -B -m kermit_index validate`. Its fingerprint and artifact comparison fails on a changed/missing admitted source; mark affected unit axes `STALE`. The coverage check reports detail without rebuilding or writing. Use `git diff --name-only` and manifest entries to identify owners. A changed source does not authorize a replacement admission.
3. **Review pack references and dependencies:** for each affected pack, check that cited paths, symbols, routes, tests, storage roles, and dependency statements still exist in current source. Record ambiguity as `NEEDS_REVIEW` in the ledger/register. Never rewrite authoritative prose automatically.
4. **Update deliberately:** revise the bounded pack and gap record, review each new source path under `SOURCE_POLICY.md`, edit only explicit manifest entries, run focused feature tests, then run `python -B -m kermit_index build` and `validate`. The builder remains separate from the serving process and dashboard startup.
5. **Prove retrieval and grounding:** run new per-unit and cross-unit retrieval questions plus deterministic grounding/security regressions. Withhold stale evidence and reject unsupported claims. Only then mark all five axes `VALIDATED` and record the reviewed source date. A full real-model bake-off is not required for each pack; targeted smoke tests depend on safe resource availability.

Never admit `data/` runtime databases/JSON, personal records, raw archives, backups, secrets, generated snapshots, `ChatGPT/`, caches, logs, model assets, or broad directories. A validation failure is a maintenance signal, not permission for automatic repair or startup rebuilding.
