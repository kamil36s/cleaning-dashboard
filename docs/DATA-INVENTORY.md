# Data inventory

Source audit started from build-0001 and regenerated from the task working tree; Sync pilot changes are detailed in SYNC-ARCHITECTURE.md. No private payloads are included.

## Storage and authority

SQLite, JSON, JSONL, CSV, raw filesystem archives, browser localStorage/sessionStorage and native Android Room/preferences are present. No browser IndexedDB implementation was found. SQLite is not automatically authoritative: reference DBs and metadata caches are rebuildable.

Roles: CANONICAL = durable owner; CACHE = replaceable mirror; DERIVED = rebuildable output; CLIENT-ONLY = browser/native state; LEGACY = recovery/import only; UNKNOWN = authority not established. Raw originals are CANONICAL evidence, even when their parsed projections are derived.

The following feature-local authority map is cross-referenced by the executable source evidence below. Mixed roles belong to distinct files within a domain, not interchangeable writers.

| Module | Data | Storage | Current source of truth | API | Sync candidate | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| Dashboard/settings | server JSON is writable state | `data/settings/*.json`, `data/widget-order.json`, browser preferences | **CANONICAL + defaults/mirrors** | Domain routes in API-INVENTORY; no exact file match | Deferred; not migrated | server JSON is writable state; `data/widget-order.json` supplies defaults; some UI-only preferences remain in `localStorage` |
| Cleaning | old `data/settings/cleaning*.json` and Google rows are migration/recovery input only | `data/cleaning.sqlite` | **CANONICAL** | `/api/cleaning/*` | Deferred; not migrated | old `data/settings/cleaning*.json` and Google rows are migration/recovery input only |
| Reading | old settings/history JSON and Google data are import/migration inputs | `data/reading.sqlite` | **CANONICAL** | `/api/reading/*` | Deferred; not migrated | old settings/history JSON and Google data are import/migration inputs |
| Finance/Bills | transactions, classification, obligations, occurrences, goals, plans, receipts, review audit | `data/finance.sqlite` | **CANONICAL** | `/api/budget/*` | Deferred; not migrated | transactions, classification, obligations, occurrences, goals, plans, receipts, review audit; `data/budget.json` and `data/settings/bills.json` are migration/recovery only |
| Finance source material | private paths are denied by both Python and Vite serving policies | `data/finance-receipts/`, `data/budget-backups/`, `data/.finance-account-key` | **CANONICAL evidence / BACKUP / SECRET RUNTIME** | Domain routes in API-INVENTORY; no exact file match | Deferred; not migrated | private paths are denied by both Python and Vite serving policies |
| Todo | generic file-settings adapter keeps browser and local API synchronized | `data/settings/todo.json`, `localStorage: todo-items-v1` | **CANONICAL file + working mirror/fallback** | Domain routes in API-INVENTORY; no exact file match | Deferred; not migrated | generic file-settings adapter keeps browser and local API synchronized |
| Job Hunt | SQLite owns source/listing/capture/mail-cursor metadata plus immutable deterministic/AI extraction runs and facts, AI attempt/usage provenance, mappings, projection history, reviews, overrides, duplicate decisions, reversible merge audit, immutable Track policy/Evaluation history, per-pair current pointers, application attribution, economic-scenario history/current pointers, Track-proposal decisions/events, and Career Experiments/events | `data/jobhunt.sqlite`; private `data/jobhunt/{raw,backups,assets}/`; legacy `dashboard.jobhunt.*` keys | **CANONICAL SQLite + CANONICAL evidence after verified cutover** | `/api/jobhunt/*` | Deferred; not migrated | SQLite owns source/listing/capture/mail-cursor metadata plus immutable deterministic/AI extraction runs and facts, AI attempt/usage provenance, mappings, projection history, reviews, overrides, duplicate decisions, reversible merge audit, immutable Track policy/Evaluation history, per-pair current pointers, application attribution, economic-scenario history/current pointers, Track-proposal decisions/events, and Career Experiments/events; Pack K and Pack M metrics read these records live and add no aggregate tables; exact manual TXT/HTML/JSON and recognized Pracuj RFC822 bytes are SHA-256-addressed below `raw/sha256/`; offers/settings migrate through a bounded fingerprinted snapshot, legacy scores/settings stay separate compatibility data, and `dashboard.jobhunt.authority` records verified cutover |
| Habits app | change cursor and idempotent mutation log support dashboard/Android-style sync | `data/habits.sqlite` | **CANONICAL** | `/api/habits/*` | Deferred; not migrated | change cursor and idempotent mutation log support dashboard/Android-style sync; supplement catalog, dated products/regimens, slots, and notification claims share this file |
| Legacy habits views | built from raw Loop Habit DB/CSV imports | `data/habit-data.json`, `js/habit-data.js`, `public/data/habits.json`, `data/report.*` | **LEGACY + DERIVED** | Domain routes in API-INVENTORY; no exact file match | Deferred; not migrated | built from raw Loop Habit DB/CSV imports; not equal to the canonical Habits app DB |
| Journals | voice job rows/performance share the voice DB | `data/journal.sqlite`, `data/voice-journal.sqlite` | **CANONICAL** | `/api/journal/*`, `/api/sync/*`, `/api/voice-journal/*` | Selected written entry only | voice job rows/performance share the voice DB; raw audio/job files are private source/runtime artifacts |
| Journal HTR | SQLite owns workflow/evidence | `data/journal-htr/journal-htr.sqlite`, originals/working/thumbnails/model files | **CANONICAL + CANONICAL evidence + DERIVED** | `/api/journal-htr/*` | Deferred; not migrated | SQLite owns workflow/evidence; originals are preserved, working copies/thumbnails are derived |
| Timeline | manual categories/items | `data/timeline.sqlite` | **CANONICAL** | `/api/timeline/*` | Deferred; not migrated | manual categories/items; connected activity is queried from source feature stores |
| Timeline activity | self-care is append/update data | `data/timeline-activity/self-care.jsonl`, `data/timeline-activity/emotions.json` | **CANONICAL PRIVATE IMPORT/CAPTURE** | Domain routes in API-INVENTORY; no exact file match | Deferred; not migrated | self-care is append/update data; How We Feel is imported evidence |
| Language user state | profiles, texts/tokens, reading series and episode links, knowledge, Anki links, Reader sentence translations, contextual glosses and grammar notes, jobs including word-audio queue, generation requests/candidates, Cloze, curriculum progress, benchmark runs/responses (v22) | `data/language-learning.sqlite` | **CANONICAL** | Domain routes in API-INVENTORY; no exact file match | Deferred; not migrated | profiles, texts/tokens, reading series and episode links, knowledge, Anki links, Reader sentence translations, contextual glosses and grammar notes, jobs including word-audio queue, generation requests/candidates, Cloze, curriculum progress, benchmark runs/responses (v22) |
| Language reference | isolated from user state | `data/reference/language-reference-nb.sqlite` | **DERIVED / REBUILDABLE** | Domain routes in API-INVENTORY; no exact file match | Deferred; not migrated | isolated from user state; rebuilt from versioned manifests/artifacts/importers |
| Language audio | content-addressed Google Cloud TTS sentence and single-word MP3 output | `data/audio/language-learning/` | **CACHE / DERIVED** | Domain routes in API-INVENTORY; no exact file match | Deferred; not migrated | content-addressed Google Cloud TTS sentence and single-word MP3 output |
| Synchrobook | book catalog, jobs, progress, Reading Guide metadata | `data/synchrobook/library.db` | **CANONICAL** | `/api/synchrobook/*` | Deferred; not migrated | book catalog, jobs, progress, Reading Guide metadata |
| Synchrobook books/artifacts | uploaded EPUB/PDF/MOBI/audio are source material | `data/synchrobook/books/` | **CANONICAL evidence + DERIVED CACHE** | Domain routes in API-INVENTORY; no exact file match | Deferred; not migrated | uploaded EPUB/PDF/MOBI/audio are source material; extracted text, merged audio, transcripts, alignment are rebuildable |
| Live Workout / Strength | runtime-owned sessions, progressive HR samples, active checkpoints and virtual-walk outbox are durable in WAL-mode workout SQLite | `data/live-workout.sqlite`, `data/strength.sqlite`, `data/live-workout-plan.json`, `data/settings/live-workout-plan.json` | **CANONICAL** | `/api/live-workout/*`, `/api/strength/*` | Deferred; not migrated | runtime-owned sessions, progressive HR samples, active checkpoints and virtual-walk outbox are durable in WAL-mode workout SQLite; prescribed plan/page tracking remain separate JSON state |
| Weight/steps | normalized history is retained | `data/scale/scale_measurements.jsonl`, `data/scale/scale_measurements.csv`, `data/scale/steps.json`, `data/scale/latest.json`, `data/scale/signal.json`, `data/scale/scale_raw.jsonl` | **CANONICAL LOG + CACHE + CANONICAL evidence** | Domain routes in API-INVENTORY; no exact file match | Deferred; not migrated | normalized history is retained; latest/signal are replaceable snapshots; raw BLE advertisements are evidence |
| Health Connect/sleep | uploaded by Android steps-sync | `data/health-connect/snapshots.jsonl`, `data/health-connect/latest.json` | **CANONICAL INGESTED HISTORY + CACHE** | Domain routes in API-INVENTORY; no exact file match | Deferred; not migrated | uploaded by Android steps-sync; sleep page derives analysis at read time |
| Sensors | written by the BLE collector | `data/sensor/readings.jsonl`, `data/sensor/latest.json` | **CANONICAL HISTORY + CACHE** | Domain routes in API-INVENTORY; no exact file match | Deferred; not migrated | written by the BLE collector |
| Diet | meal, estimate, ignore-day state | `data/diet/diet.json` | **CANONICAL** | `/api/diet/*` | Deferred; not migrated | meal, estimate, ignore-day state |
| Ring | BLE/phone ingest, measurements, capabilities, diagnostics | `data/ring.sqlite` | **CANONICAL** | `/api/ring/*` | Deferred; not migrated | BLE/phone ingest, measurements, capabilities, diagnostics; `data/ring-mock.sqlite` is test/dev data |
| AI Usage | observations/sessions derived from Codex and Antigravity local services | `data/ai-usage.sqlite` | **CANONICAL LOCAL TELEMETRY HISTORY** | `/api/ai-usage` | Deferred; not migrated | observations/sessions derived from Codex and Antigravity local services; historical rows are not regenerated |
| Network monitor | SQLite owns scans/presence/profile state | `data/network-monitor.sqlite`, `data/network-known-devices.json` | **CANONICAL HISTORY + COMPATIBILITY MIRROR** | `/api/network/*` | Deferred; not migrated | SQLite owns scans/presence/profile state; JSON profiles are read and maintained for compatibility |
| Phone telemetry | widget parses exported Android bundles | `data/phone-telemetry/*.json` | **RAW/IMPORTED SNAPSHOTS** | Domain routes in API-INVENTORY; no exact file match | Deferred; not migrated | widget parses exported Android bundles; no backend database |
| Phone Activity | paired device credentials (hashes only), raw events, app registry/icons, sync receipts, rules, external conditions, place labels, and retention settings | `data/phone-tracker.sqlite` | **CANONICAL PRIVATE SQLITE** | `/api/phone-tracker/*` | Deferred; not migrated | paired device credentials (hashes only), raw events, app registry/icons, sync receipts, rules, external conditions, place labels, and retention settings; never serve directly |
| Events | local events and countdown preferences/categories | `data/events.json`, `data/settings/events.json` | **CANONICAL LOCAL STATE** | Domain routes in API-INVENTORY; no exact file match | Deferred; not migrated | local events and countdown preferences/categories |
| Google Calendar/Tasks | external events are rebuildable | `data/google-calendar/events-cache.json`, `data/google-calendar/state.json`, `data/google-calendar/overrides.json` | **CACHE + CANONICAL OVERRIDES/OAUTH STATE** | Domain routes in API-INVENTORY; no exact file match | Deferred; not migrated | external events are rebuildable; dashboard overrides and OAuth/sync state are local state |
| Films/Oscars | `data/films/library.json` is generated | `watchlist.sqlite` | **CANONICAL** | `/api/films/*`, `/api/oscars/*` | Deferred; not migrated | `data/films/library.json` is generated; Oscar year JSON/CSV and posters are seeds/caches |
| Classical Library | progress/catalog state, preserved RYM HTML uploads, composer image assets | `data/classical-library/` | **CANONICAL JSON + CANONICAL evidence + DERIVED MEDIA** | Domain routes in API-INVENTORY; no exact file match | Deferred; not migrated | progress/catalog state, preserved RYM HTML uploads, composer image assets |
| Music | catalog, releases, genres, lists, ratings, rankings, import staging, legacy links | `data/music.sqlite` | **CANONICAL** | `/api/music/*` | Deferred; not migrated | catalog, releases, genres, lists, ratings, rankings, import staging, legacy links |
| Music imports | content-addressed saved HTML retained for deterministic reparsing | `data/music-imports/*.html` | **CANONICAL evidence** | Domain routes in API-INVENTORY; no exact file match | Deferred; not migrated | content-addressed saved HTML retained for deterministic reparsing |
| Last.fm | synchronized scrobbles and derived summaries used by Music and Timeline | `data/lastfm.sqlite` | **CACHE / DERIVED** | `/api/lastfm/*` | Deferred; not migrated | synchronized scrobbles and derived summaries used by Music and Timeline |
| BM365 | albums, listening/rating state, release years, descriptions, and durable Sheets push queue | `data/bm365.sqlite` | **CANONICAL** | Domain routes in API-INVENTORY; no exact file match | Deferred; not migrated | albums, listening/rating state, release years, descriptions, and durable Sheets push queue |
| BM365 metadata | enrichment and cover artifacts | `data/bm365-metadata.sqlite`, `covers/` | **CACHE / DERIVED MEDIA** | Domain routes in API-INVENTORY; no exact file match | Deferred; not migrated | enrichment and cover artifacts |
| Brutal Assault / RYM Top 100 | ratings/progress are SQLite | `data/brutal-assault-2027.sqlite`, `data/rym-polish-black-metal-top-100.sqlite`, `data/rym-polish-black-metal-top-100.json` | **CANONICAL USER STATE + SEED** | Domain routes in API-INVENTORY; no exact file match | Deferred; not migrated | ratings/progress are SQLite; the RYM JSON is immutable seed input |
| Brutal Assault official monitor | independent official lineup/news baselines and bounded events | `data/brutal-assault-2027-monitor.json` | **CACHE observations + CANONICAL history** | `/api/brutal-assault-2027/*` | Deferred; not migrated | independent official lineup/news baselines and bounded events; news detail is retained for 30 days, IDs remain for deduplication; checked at backend startup and every six hours |
| Kitchen | live sports/weather responses are refreshed | `data/kitchen-settings.json`, `data/kitchen-scores.json`, `data/kitchen-leagues.json`, `data/kitchen-team-crests.json`, `data/polish-namedays.json` | **CANONICAL SETTINGS + CACHE** | Domain routes in API-INVENTORY; no exact file match | Deferred; not migrated | live sports/weather responses are refreshed; curated settings/catalog and annual namedays remain local state |
| Spotify/screensavers | media/facts can be refreshed | `data/spotify/state.json`, `data/spotify/screensaver-settings.json`, artist facts/media dirs | **CANONICAL OAUTH/SETTINGS + CACHE** | Domain routes in API-INVENTORY; no exact file match | Deferred; not migrated | media/facts can be refreshed; tokens/state are private runtime data |
| Blood pressure / breathwork | no server synchronization | feature `localStorage` keys | **CANONICAL CLIENT-ONLY** | Domain routes in API-INVENTORY; no exact file match | Deferred; not migrated | no server synchronization |
| Antigravity context export | privacy-filtered derivative produced by `scripts/export_antigravity_context.py` | `antigravity-context/snapshots/`, `summaries/`, schemas | **DERIVED** | Domain routes in API-INVENTORY; no exact file match | Deferred; not migrated | privacy-filtered derivative produced by `scripts/export_antigravity_context.py` |

## Additional domains and pilot decision

| Module | Data | Storage / current source of truth | API | Sync candidate | Notes |
| --- | --- | --- | --- | --- | --- |
| Todo / Projects / Shopping | Tasks, nested subtasks, backlog | CANONICAL `data/settings/todo.json`; CLIENT-ONLY recovery copy `todo-items-v1` | `/api/settings/todo`, `/api/phone-todo` | Later | Whole-list writes and fire-and-forget fallback can overwrite remote edits; seed deletion markers are meaningful. Do not migrate first. |
| Written journal | Entries, poems, provenance | CANONICAL `data/journal.sqlite`; CLIENT-ONLY unsaved drafts and view preferences | `/api/journal/entries` | **Selected: journalEntry only** | UUID hex IDs, one store, no published-entry localStorage fallback; imports and voice/HTR publication converge on same SQL table. Preserve drafts. |
| Feelings | Check-ins, tags, emotions | CANONICAL `data/feelings.sqlite` | `/api/feelings/*` | Later | Existing Android queue, imports and reference taxonomy require separate audit. |
| Mental health | Assessments, trackers, schedules | CANONICAL `data/mental-health.sqlite` | `/api/mental-health/*` | Later | Multi-entity dependencies. |
| Football | Historical observations | CANONICAL `data/football.sqlite`; CACHE Kitchen snapshots | `/api/football*` | Low | Mostly externally derived reads. |
| Self care | Browser history plus imported timeline capture | CLIENT-ONLY browser state; CANONICAL capture JSONL; equivalence UNKNOWN | `/api/timeline/activity/*` | Defer | Do not infer that capture supersedes all browser history. |
| Kermit | Derived index, temporary conversations | DERIVED filesystem index; CLIENT-ONLY/in-memory chat session | `/api/kermit/v1/*` | No | Does not own dashboard domain records. |

## Risks / hard gate

Published journal entries have an unambiguous canonical owner (`JournalStore`). Existing imports call that store; SQL triggers can track every insert/update/delete atomically, including older running processes. No relocation of content or ID conversion is needed. Back up the SQLite database with the SQLite backup API before adding metadata/triggers. Browser drafts remain unsaved user data, never a server fallback. Pilot gate: PASS.

Todo local-first fallback, generated habits views versus Habits DB, alternate Spotify servers, central versus independent workout handlers, and direct import scripts are authority boundaries; they remain unchanged. Client wall clocks and timestamp-only cursors are unsuitable for shared synchronization.

## Source evidence by mechanism

### Persistence / browser stores

| Source | Matching lines |
| --- | --- |
| [ai_usage.py:649](../ai_usage.py#L649) | 649 |
| [android/dashboard-companion/app/src/main/java/com/cleaningdashboard/companion/CompanionConfig.kt:35](../android/dashboard-companion/app/src/main/java/com/cleaningdashboard/companion/CompanionConfig.kt#L35) | 35, 41, 48 |
| [android/how-i-feel/app/src/main/java/com/cleaningdashboard/howifeel/AppConfig.kt:35](../android/how-i-feel/app/src/main/java/com/cleaningdashboard/howifeel/AppConfig.kt#L35) | 35, 41 |
| [android/how-i-feel/app/src/main/java/com/cleaningdashboard/howifeel/FeelingsClient.kt:63](../android/how-i-feel/app/src/main/java/com/cleaningdashboard/howifeel/FeelingsClient.kt#L63) | 63, 105, 112 |
| [android/how-i-feel/app/src/main/java/com/cleaningdashboard/howifeel/ReminderScheduler.kt:42](../android/how-i-feel/app/src/main/java/com/cleaningdashboard/howifeel/ReminderScheduler.kt#L42) | 42, 46, 54 |
| [android/phone-tracker/app/src/main/java/com/cleaningdashboard/phonetracker/BlockerHealth.kt:12](../android/phone-tracker/app/src/main/java/com/cleaningdashboard/phonetracker/BlockerHealth.kt#L12) | 12, 17, 27 |
| [android/phone-tracker/app/src/main/java/com/cleaningdashboard/phonetracker/ManagedShortcuts.kt:74](../android/phone-tracker/app/src/main/java/com/cleaningdashboard/phonetracker/ManagedShortcuts.kt#L74) | 74 |
| [android/phone-tracker/app/src/main/java/com/cleaningdashboard/phonetracker/RewardNotifier.kt:36](../android/phone-tracker/app/src/main/java/com/cleaningdashboard/phonetracker/RewardNotifier.kt#L36) | 36, 72 |
| [android/phone-tracker/app/src/main/java/com/cleaningdashboard/phonetracker/RuleEngine.kt:19](../android/phone-tracker/app/src/main/java/com/cleaningdashboard/phonetracker/RuleEngine.kt#L19) | 19, 22, 24, 26, 43, 50 |
| [android/phone-tracker/app/src/main/java/com/cleaningdashboard/phonetracker/SupportingCollectors.kt:51](../android/phone-tracker/app/src/main/java/com/cleaningdashboard/phonetracker/SupportingCollectors.kt#L51) | 51 |
| [android/phone-tracker/app/src/main/java/com/cleaningdashboard/phonetracker/TrackerConfig.kt:54](../android/phone-tracker/app/src/main/java/com/cleaningdashboard/phonetracker/TrackerConfig.kt#L54) | 54, 62, 78, 81, 85 |
| [android/phone-tracker/app/src/main/java/com/cleaningdashboard/phonetracker/TrackerDatabase.kt:107](../android/phone-tracker/app/src/main/java/com/cleaningdashboard/phonetracker/TrackerDatabase.kt#L107) | 107 |
| [android/phone-tracker/app/src/main/java/com/cleaningdashboard/phonetracker/UsageCollector.kt:24](../android/phone-tracker/app/src/main/java/com/cleaningdashboard/phonetracker/UsageCollector.kt#L24) | 24 |
| [android/steps-sync/app/src/main/java/com/cleaningdashboard/stepssync/DashboardConfig.kt:36](../android/steps-sync/app/src/main/java/com/cleaningdashboard/stepssync/DashboardConfig.kt#L36) | 36 |
| [bm365_metadata_store.py:27](../bm365_metadata_store.py#L27) | 27 |
| [bm365_store.py:48](../bm365_store.py#L48) | 48 |
| [brutal_assault_store.py:28](../brutal_assault_store.py#L28) | 28 |
| [cleaning_store.py:96](../cleaning_store.py#L96) | 96 |
| [dashboard_sync/backup.py:30](../dashboard_sync/backup.py#L30) | 30, 31 |
| [dashboard_sync/migration.py:16](../dashboard_sync/migration.py#L16) | 16 |
| [docs/phone-telemetry-android/app/src/main/java/com/cleaningdashboard/phonetelemetry/data/local/TelemetryDatabase.kt:26](../docs/phone-telemetry-android/app/src/main/java/com/cleaningdashboard/phonetelemetry/data/local/TelemetryDatabase.kt#L26) | 26 |
| [feelings_store.py:239](../feelings_store.py#L239) | 239 |
| [finance_repository.py:760](../finance_repository.py#L760) | 760, 847 |
| [finance_service.py:1004](../finance_service.py#L1004) | 1004 |
| [football_store.py:52](../football_store.py#L52) | 52 |
| [habits_store.py:88](../habits_store.py#L88) | 88 |
| [jobhunt_backend/migrations.py:2005](../jobhunt_backend/migrations.py#L2005) | 2005, 2016 |
| [jobhunt_backend/store.py:207](../jobhunt_backend/store.py#L207) | 207 |
| [journal_htr_service.py:217](../journal_htr_service.py#L217) | 217 |
| [journal_store.py:177](../journal_store.py#L177) | 177 |
| [js/aqi.js:176](../js/aqi.js#L176) | 176, 185 |
| [js/bills-store.js:292](../js/bills-store.js#L292) | 292, 300, 309 |
| [js/bm365-page-v2.js:234](../js/bm365-page-v2.js#L234) | 234, 242, 250, 259, 2415 |
| [js/bm365-page.js:296](../js/bm365-page.js#L296) | 296, 304, 376, 385, 937 |
| [js/bm365.js:16](../js/bm365.js#L16) | 16, 240, 247, 273, 347, 353, 362, 395, 397, 427, 428, 704, 708, 716, 729, 741 |
| [js/breathwork.js:11](../js/breathwork.js#L11) | 11, 19 |
| [js/budget-page.js:95](../js/budget-page.js#L95) | 95, 150, 155, 1086, 1098 |
| [js/calendar.js:23](../js/calendar.js#L23) | 23, 29 |
| [js/cleaning-apartments.js:23](../js/cleaning-apartments.js#L23) | 23, 28, 40, 65 |
| [js/cleaning-history.js:116](../js/cleaning-history.js#L116) | 116, 119, 122, 226, 262, 283, 297, 810 |
| [js/dashboard-notifications-store.js:8](../js/dashboard-notifications-store.js#L8) | 8, 37, 50, 69 |
| [js/dashboard-settings.js:406](../js/dashboard-settings.js#L406) | 406, 587, 595, 613, 637, 653 |
| [js/docs/projectDocsData.js:112](../js/docs/projectDocsData.js#L112) | 112, 128, 129, 131 |
| [js/file-settings.js:4](../js/file-settings.js#L4) | 4, 26, 37, 39 |
| [js/films-shared.js:64](../js/films-shared.js#L64) | 64, 65 |
| [js/finance-page.js:310](../js/finance-page.js#L310) | 310, 1187, 1192 |
| [js/habits-app-api.js:222](../js/habits-app-api.js#L222) | 222 |
| [js/habits-app-model.js:108](../js/habits-app-model.js#L108) | 108, 118 |
| [js/i18n.js:91](../js/i18n.js#L91) | 91, 100 |
| [js/jobhunt-api.js:71](../js/jobhunt-api.js#L71) | 71, 91, 104, 122, 438 |
| [js/jobhunt-store.js:60](../js/jobhunt-store.js#L60) | 60, 71, 82 |
| [js/jobhunt.js:121](../js/jobhunt.js#L121) | 121, 128 |
| [js/journal.js:201](../js/journal.js#L201) | 201 |
| [js/kitchen.js:1549](../js/kitchen.js#L1549) | 1549, 1564, 1579, 1581, 1702, 1711 |
| [js/language/app.js:94](../js/language/app.js#L94) | 94, 105, 1523, 2084, 2188, 2286, 2296 |
| [js/language/views/overview.js:70](../js/language/views/overview.js#L70) | 70, 83 |
| [js/live-workout-adaptive-calibration.js:175](../js/live-workout-adaptive-calibration.js#L175) | 175, 186, 228 |
| [js/live-workout-calibration.js:404](../js/live-workout-calibration.js#L404) | 404, 413, 422 |
| [js/live-workout-csc.js:202](../js/live-workout-csc.js#L202) | 202 |
| [js/live-workout-page.js:125](../js/live-workout-page.js#L125) | 125, 131, 504, 604, 605, 616 |
| [js/live-workout-runtime-api.js:8](../js/live-workout-runtime-api.js#L8) | 8 |
| [js/live-workout-strength.js:56](../js/live-workout-strength.js#L56) | 56, 177, 188, 189, 486, 616 |
| [js/live-workout-transfer.js:49](../js/live-workout-transfer.js#L49) | 49, 62, 68, 71, 74 |
| [js/moving-checklist-store.js:475](../js/moving-checklist-store.js#L475) | 475, 486, 494 |
| [js/music.js:17](../js/music.js#L17) | 17, 41 |
| [js/network-notification-settings.js:6](../js/network-notification-settings.js#L6) | 6, 12, 23 |
| [js/nobel.js:4](../js/nobel.js#L4) | 4, 145, 149, 158 |
| [js/oscars-data.js:78](../js/oscars-data.js#L78) | 78, 91, 111, 120, 140, 153 |
| [js/oscars-store.js:46](../js/oscars-store.js#L46) | 46, 58 |
| [js/oscars.js:102](../js/oscars.js#L102) | 102, 133, 151 |
| [js/phone-activity-display.js:26](../js/phone-activity-display.js#L26) | 26, 36 |
| [js/phone-cleaning-gate.js:25](../js/phone-cleaning-gate.js#L25) | 25 |
| [js/reading-books.js:39](../js/reading-books.js#L39) | 39, 45, 79, 81, 91, 119, 121 |
| [js/reading-covers.js:25](../js/reading-covers.js#L25) | 25, 31, 41, 43 |
| [js/reading-history.js:33](../js/reading-history.js#L33) | 33, 802, 804, 811, 820, 822, 827, 830, 839, 841, 842, 850, 853, 953, 954, 955, 966, 967, 968, 1025, 1027, 1029, 1032, 1034, 1093 |
| [js/reading-settings-store.js:16](../js/reading-settings-store.js#L16) | 16, 21, 32, 34, 90 |
| [js/reading.js:159](../js/reading.js#L159) | 159, 915, 924, 947, 965, 973, 984 |
| [js/render.js:30](../js/render.js#L30) | 30, 34, 50 |
| [js/strength-app.js:47](../js/strength-app.js#L47) | 47, 78, 79 |
| [js/synchrobook/page-progress.js:17](../js/synchrobook/page-progress.js#L17) | 17, 32 |
| [js/synchrobook/settings.js:32](../js/synchrobook/settings.js#L32) | 32, 44 |
| [js/timeline.js:276](../js/timeline.js#L276) | 276, 284, 292, 303 |
| [js/today-display.js:319](../js/today-display.js#L319) | 319 |
| [js/todo-store.js:197](../js/todo-store.js#L197) | 197, 199, 209, 215, 249, 251, 261, 263, 270, 272 |
| [js/todo.js:56](../js/todo.js#L56) | 56, 58, 68, 70 |
| [js/ui/render_weather_api.js:89](../js/ui/render_weather_api.js#L89) | 89, 92 |
| [js/voice-journal-settings.js:60](../js/voice-journal-settings.js#L60) | 60, 64 |
| [js/widget-ai-usage.js:84](../js/widget-ai-usage.js#L84) | 84, 120 |
| [js/widget-bills.js:570](../js/widget-bills.js#L570) | 570, 579 |
| [js/widget-blood-pressure.js:397](../js/widget-blood-pressure.js#L397) | 397, 407 |
| [js/widget-brutal-assault-2027.js:38](../js/widget-brutal-assault-2027.js#L38) | 38, 71, 211, 220 |
| [js/widget-cleaning.js:230](../js/widget-cleaning.js#L230) | 230, 236, 248, 253, 310, 317, 329, 337, 341, 739 |
| [js/widget-event-countdowns.js:349](../js/widget-event-countdowns.js#L349) | 349, 1189, 1190, 1306, 1315, 1513, 1521, 1525, 1534 |
| [js/widget-events.js:243](../js/widget-events.js#L243) | 243, 259, 828, 829, 842, 1009, 1017 |
| [js/widget-flat-hunt.js:90](../js/widget-flat-hunt.js#L90) | 90, 106 |
| [js/widget-live-workout.js:530](../js/widget-live-workout.js#L530) | 530, 531, 544, 545, 975, 976, 981, 1219, 1273, 1291, 2452, 2455, 2728, 3027, 3037, 3118, 3135, 3463, 3469, 3665, 3671 |
| [js/widget-moving-checklist.js:543](../js/widget-moving-checklist.js#L543) | 543 |
| [js/widget-network.js:115](../js/widget-network.js#L115) | 115, 121, 137 |
| [js/widget-order.js:278](../js/widget-order.js#L278) | 278, 286 |
| [js/widget-reading.js:566](../js/widget-reading.js#L566) | 566 |
| [js/widget-voice-journal.js:386](../js/widget-voice-journal.js#L386) | 386 |
| [js/widget-weight-cut.js:141](../js/widget-weight-cut.js#L141) | 141, 152, 169, 179, 199, 208 |
| [language_learning/backup.py:79](../language_learning/backup.py#L79) | 79, 176 |
| [language_learning/cloze.py:94](../language_learning/cloze.py#L94) | 94 |
| [language_learning/reference_core/build.py:29](../language_learning/reference_core/build.py#L29) | 29, 31 |
| [language_learning/reference_core/service.py:67](../language_learning/reference_core/service.py#L67) | 67 |
| [language_learning/reference_core/store.py:63](../language_learning/reference_core/store.py#L63) | 63 |
| [language_learning/store.py:112](../language_learning/store.py#L112) | 112, 4432 |
| [lastfm_store.py:79](../lastfm_store.py#L79) | 79 |
| [live_workout_store.py:456](../live_workout_store.py#L456) | 456 |
| [mental_health_store.py:155](../mental_health_store.py#L155) | 155 |
| [music_store.py:392](../music_store.py#L392) | 392 |
| [network_monitor/persistence.py:35](../network_monitor/persistence.py#L35) | 35 |
| [phone_tracker.py:336](../phone_tracker.py#L336) | 336 |
| [reading_store.py:126](../reading_store.py#L126) | 126 |
| [ring_store.py:31](../ring_store.py#L31) | 31 |
| [scripts/build-habits.py:113](../scripts/build-habits.py#L113) | 113 |
| [scripts/build-sync-inventory.py:46](../scripts/build-sync-inventory.py#L46) | 46, 53, 64, 128 |
| [scripts/build_language_curricula.py:108](../scripts/build_language_curricula.py#L108) | 108 |
| [scripts/diagnose_language_reference.py:39](../scripts/diagnose_language_reference.py#L39) | 39 |
| [scripts/export_antigravity_context.py:115](../scripts/export_antigravity_context.py#L115) | 115 |
| [scripts/import_bm365_initial.py:47](../scripts/import_bm365_initial.py#L47) | 47, 72 |
| [scripts/import_rym_collection.py:51](../scripts/import_rym_collection.py#L51) | 51 |
| [scripts/import_tumblr_poems.py:209](../scripts/import_tumblr_poems.py#L209) | 209 |
| [scripts/inspect-phone-tracker-device.py:36](../scripts/inspect-phone-tracker-device.py#L36) | 36, 44 |
| [scripts/migrate-sync-pilot.py:16](../scripts/migrate-sync-pilot.py#L16) | 16 |
| [server.py:5406](../server.py#L5406) | 5406, 5484, 5522, 5660, 5759, 6401, 6421, 13493, 13551, 13642, 13761, 13779, 13854, 13938, 13985, 20748 |
| [strength_store.py:268](../strength_store.py#L268) | 268 |
| [synchrobook_backend/reading_guide.py:147](../synchrobook_backend/reading_guide.py#L147) | 147 |
| [synchrobook_backend/service.py:73](../synchrobook_backend/service.py#L73) | 73 |
| [timeline_store.py:259](../timeline_store.py#L259) | 259 |
| [voice_journal_jobs.py:95](../voice_journal_jobs.py#L95) | 95 |
| [voice_journal_store.py:141](../voice_journal_store.py#L141) | 141 |

### File writes / settings / import-export / backups

| Source | Matching lines |
| --- | --- |
| [brutal_assault_monitor.py:194](../brutal_assault_monitor.py#L194) | 194, 195 |
| [cleaning_store.py:711](../cleaning_store.py#L711) | 711 |
| [dashboard_sync/backup.py:23](../dashboard_sync/backup.py#L23) | 23, 32, 44 |
| [dashboard_sync/migration.py:25](../dashboard_sync/migration.py#L25) | 25 |
| [feelings_store.py:357](../feelings_store.py#L357) | 357, 537, 766, 773, 781 |
| [finance_classification.py:163](../finance_classification.py#L163) | 163, 224 |
| [finance_operations.py:562](../finance_operations.py#L562) | 562 |
| [finance_planning.py:227](../finance_planning.py#L227) | 227 |
| [finance_receipts.py:855](../finance_receipts.py#L855) | 855, 865, 982, 1365, 1381 |
| [finance_repository.py:849](../finance_repository.py#L849) | 849, 1296, 1537 |
| [finance_service.py:161](../finance_service.py#L161) | 161, 257, 593, 971, 995, 999, 1020 |
| [football_service.py:191](../football_service.py#L191) | 191, 192 |
| [jobhunt_backend/ingestion/archive.py:96](../jobhunt_backend/ingestion/archive.py#L96) | 96 |
| [jobhunt_backend/migrations.py:1996](../jobhunt_backend/migrations.py#L1996) | 1996, 2007 |
| [jobhunt_backend/service.py:2851](../jobhunt_backend/service.py#L2851) | 2851, 4240, 4248, 5199, 5203 |
| [jobhunt_backend/store.py:683](../jobhunt_backend/store.py#L683) | 683 |
| [journal_htr_provider.py:104](../journal_htr_provider.py#L104) | 104, 495, 667 |
| [journal_htr_service.py:1768](../journal_htr_service.py#L1768) | 1768, 2049, 2946 |
| [journal_store.py:451](../journal_store.py#L451) | 451, 509 |
| [journey_postcards.py:38](../journey_postcards.py#L38) | 38, 39, 91, 92 |
| [kermit_grounding/replay.py:66](../kermit_grounding/replay.py#L66) | 66 |
| [kermit_index/builder.py:471](../kermit_index/builder.py#L471) | 471, 472, 473, 475 |
| [language_learning/backup.py:163](../language_learning/backup.py#L163) | 163, 177, 213, 223, 329, 358 |
| [language_learning/cloze_audio.py:326](../language_learning/cloze_audio.py#L326) | 326 |
| [language_learning/content_inbox.py:347](../language_learning/content_inbox.py#L347) | 347, 368 |
| [language_learning/generation.py:462](../language_learning/generation.py#L462) | 462 |
| [language_learning/reference_core/artifacts.py:124](../language_learning/reference_core/artifacts.py#L124) | 124 |
| [language_learning/reference_core/build.py:364](../language_learning/reference_core/build.py#L364) | 364, 365, 389, 442 |
| [language_learning/reference_core/fixture_importer.py:18](../language_learning/reference_core/fixture_importer.py#L18) | 18 |
| [language_learning/reference_core/production_importer.py:190](../language_learning/reference_core/production_importer.py#L190) | 190, 235, 510, 560, 658, 719, 920 |
| [language_learning/reference_core/store.py:141](../language_learning/reference_core/store.py#L141) | 141, 154 |
| [language_learning/reference_core/tatoeba_importer.py:205](../language_learning/reference_core/tatoeba_importer.py#L205) | 205, 311 |
| [language_learning/service.py:1032](../language_learning/service.py#L1032) | 1032, 1868, 2832, 2853, 2859 |
| [language_learning/store.py:104](../language_learning/store.py#L104) | 104, 748, 4384, 4425, 4433 |
| [lastfm_store.py:187](../lastfm_store.py#L187) | 187 |
| [live_workout_store.py:1244](../live_workout_store.py#L1244) | 1244 |
| [mental_health_store.py:823](../mental_health_store.py#L823) | 823, 828 |
| [music_enrichment.py:538](../music_enrichment.py#L538) | 538 |
| [music_store.py:540](../music_store.py#L540) | 540, 599, 622, 671, 735, 892, 1120 |
| [network_monitor/persistence.py:807](../network_monitor/persistence.py#L807) | 807 |
| [reading_store.py:686](../reading_store.py#L686) | 686 |
| [scripts/audit_santiago_route.py:34](../scripts/audit_santiago_route.py#L34) | 34, 676 |
| [scripts/benchmark_language_grammar.py:47](../scripts/benchmark_language_grammar.py#L47) | 47 |
| [scripts/benchmark_language_operations.py:193](../scripts/benchmark_language_operations.py#L193) | 193 |
| [scripts/build-habits.py:621](../scripts/build-habits.py#L621) | 621, 626, 631, 663 |
| [scripts/build-sync-inventory.py:65](../scripts/build-sync-inventory.py#L65) | 65, 76, 153 |
| [scripts/build_language_curricula.py:178](../scripts/build_language_curricula.py#L178) | 178 |
| [scripts/enrich_santiago_checkpoints.py:93](../scripts/enrich_santiago_checkpoints.py#L93) | 93 |
| [scripts/export_antigravity_context.py:138](../scripts/export_antigravity_context.py#L138) | 138, 139 |
| [scripts/import_body_csv.py:125](../scripts/import_body_csv.py#L125) | 125, 136, 139 |
| [scripts/import_cleaning_initial.py:50](../scripts/import_cleaning_initial.py#L50) | 50, 97 |
| [scripts/import_language_tatoeba.py:79](../scripts/import_language_tatoeba.py#L79) | 79 |
| [scripts/import_language_tatoeba_translations.py:61](../scripts/import_language_tatoeba_translations.py#L61) | 61 |
| [scripts/import_reading_initial.py:65](../scripts/import_reading_initial.py#L65) | 65 |
| [scripts/import_rym_collection.py:47](../scripts/import_rym_collection.py#L47) | 47, 52, 55, 180 |
| [scripts/import_tumblr_poems.py:202](../scripts/import_tumblr_poems.py#L202) | 202, 210 |
| [scripts/inspect-phone-tracker-device.py:24](../scripts/inspect-phone-tracker-device.py#L24) | 24 |
| [scripts/journal_htr_bootstrap.py:82](../scripts/journal_htr_bootstrap.py#L82) | 82, 485, 562 |
| [scripts/migrate-sync-pilot.py:39](../scripts/migrate-sync-pilot.py#L39) | 39 |
| [scripts/review_santiago_checkpoint_order.py:97](../scripts/review_santiago_checkpoint_order.py#L97) | 97, 321 |
| [scripts/scan_ble.py:137](../scripts/scan_ble.py#L137) | 137, 141, 377, 378, 393, 394 |
| [scripts/smoke_language_grammar.py:59](../scripts/smoke_language_grammar.py#L59) | 59 |
| [scripts/synchrobook_transcribe_worker.py:54](../scripts/synchrobook_transcribe_worker.py#L54) | 54, 69 |
| [scripts/verify_santiago_route_tags.py:35](../scripts/verify_santiago_route_tags.py#L35) | 35 |
| [scripts/voice_journal_worker.py:77](../scripts/voice_journal_worker.py#L77) | 77, 78 |
| [server.py:2747](../server.py#L2747) | 2747, 2763, 2796, 3348, 3371, 3479, 3791, 3825, 4316, 4483, 4565, 4567, 5715, 6162, 6164, 6208, 6229, 11701, 13155, 13488, 14053, 14057, 14062, 14090, 14110, 14135 |
| [strength_store.py:898](../strength_store.py#L898) | 898, 917 |
| [synchrobook_backend/epub.py:278](../synchrobook_backend/epub.py#L278) | 278, 393, 394 |
| [synchrobook_backend/media.py:100](../synchrobook_backend/media.py#L100) | 100, 173, 232 |
| [synchrobook_backend/reading_guide.py:932](../synchrobook_backend/reading_guide.py#L932) | 932 |
| [synchrobook_backend/service.py:48](../synchrobook_backend/service.py#L48) | 48, 49, 204, 729, 779 |
| [timeline_activity.py:494](../timeline_activity.py#L494) | 494, 605 |
| [timeline_store.py:446](../timeline_store.py#L446) | 446 |
| [todo_phone.py:60](../todo_phone.py#L60) | 60 |
| [voice_journal.py:450](../voice_journal.py#L450) | 450, 484 |
| [voice_journal_jobs.py:273](../voice_journal_jobs.py#L273) | 273, 507 |
| [voice_journal_store.py:329](../voice_journal_store.py#L329) | 329, 331 |

### Transports / polling / jobs

| Source | Matching lines |
| --- | --- |
| [ai_usage.py:380](../ai_usage.py#L380) | 380, 382, 653, 716 |
| [android/dashboard-companion/app/src/main/java/com/cleaningdashboard/companion/ReceiptUploadWorker.kt:14](../android/dashboard-companion/app/src/main/java/com/cleaningdashboard/companion/ReceiptUploadWorker.kt#L14) | 14 |
| [android/how-i-feel/app/src/main/java/com/cleaningdashboard/howifeel/ReminderScheduler.kt:114](../android/how-i-feel/app/src/main/java/com/cleaningdashboard/howifeel/ReminderScheduler.kt#L114) | 114 |
| [android/phone-tracker/app/src/main/java/com/cleaningdashboard/phonetracker/RewardNotifier.kt:169](../android/phone-tracker/app/src/main/java/com/cleaningdashboard/phonetracker/RewardNotifier.kt#L169) | 169 |
| [android/phone-tracker/app/src/main/java/com/cleaningdashboard/phonetracker/SyncWorker.kt:49](../android/phone-tracker/app/src/main/java/com/cleaningdashboard/phonetracker/SyncWorker.kt#L49) | 49, 65 |
| [android/steps-sync/app/src/main/java/com/cleaningdashboard/stepssync/DashboardStepsSyncWorker.kt:9](../android/steps-sync/app/src/main/java/com/cleaningdashboard/stepssync/DashboardStepsSyncWorker.kt#L9) | 9, 12 |
| [bm365_sheets_syncer.py:25](../bm365_sheets_syncer.py#L25) | 25 |
| [bm365_store.py:587](../bm365_store.py#L587) | 587, 598, 621 |
| [brutal_assault_monitor.py:178](../brutal_assault_monitor.py#L178) | 178, 242, 260, 289 |
| [brutal_assault_ratings.py:119](../brutal_assault_ratings.py#L119) | 119, 123 |
| [docs/health-connect-steps-android/DashboardStepsSyncWorker.kt:12](../docs/health-connect-steps-android/DashboardStepsSyncWorker.kt#L12) | 12, 15 |
| [docs/phone-telemetry-android/app/src/main/java/com/cleaningdashboard/phonetelemetry/export/ExportWorker.kt:13](../docs/phone-telemetry-android/app/src/main/java/com/cleaningdashboard/phonetelemetry/export/ExportWorker.kt#L13) | 13, 16 |
| [feelings_store.py:339](../feelings_store.py#L339) | 339 |
| [football_service.py:47](../football_service.py#L47) | 47, 66, 170 |
| [habits_store.py:733](../habits_store.py#L733) | 733 |
| [jobhunt_backend/jobs.py:62](../jobhunt_backend/jobs.py#L62) | 62 |
| [jobhunt_backend/service.py:1627](../jobhunt_backend/service.py#L1627) | 1627, 2111, 2128, 2134, 2151, 2157, 2191, 2241, 2316, 2372, 2530, 2551, 2611 |
| [jobhunt_backend/store.py:1287](../jobhunt_backend/store.py#L1287) | 1287, 1294, 1322, 1329, 1828, 1832, 1839, 1900, 1907, 1962, 1991, 2020, 2034, 2045, 2098, 2130, 2135, 2144, 2164, 2171, 4060 |
| [journal_htr_runtime.py:98](../journal_htr_runtime.py#L98) | 98, 113 |
| [journal_htr_service.py:1474](../journal_htr_service.py#L1474) | 1474, 1506, 2710, 2713 |
| [js/ai-usage-page.js:646](../js/ai-usage-page.js#L646) | 646 |
| [js/api/gios.js:53](../js/api/gios.js#L53) | 53 |
| [js/api/openMeteo.js:39](../js/api/openMeteo.js#L39) | 39 |
| [js/artist-facts-screensaver.js:43](../js/artist-facts-screensaver.js#L43) | 43, 49, 70, 83 |
| [js/bm365-api.js:9](../js/bm365-api.js#L9) | 9 |
| [js/bm365-page-v2.js:295](../js/bm365-page-v2.js#L295) | 295, 318, 324, 553, 1765, 1773, 2091, 2184, 2439 |
| [js/bm365-page.js:330](../js/bm365-page.js#L330) | 330, 354, 360, 527, 962 |
| [js/bm365.js:302](../js/bm365.js#L302) | 302, 434, 1298 |
| [js/breathwork.js:58](../js/breathwork.js#L58) | 58, 190 |
| [js/budget-api.js:16](../js/budget-api.js#L16) | 16, 27, 41, 59, 80, 241, 248 |
| [js/calendar-data.js:21](../js/calendar-data.js#L21) | 21 |
| [js/calendar.js:176](../js/calendar.js#L176) | 176, 178 |
| [js/cinema-city-repertoire-adapter.js:4](../js/cinema-city-repertoire-adapter.js#L4) | 4 |
| [js/cinema-city-stats-adapter.js:23](../js/cinema-city-stats-adapter.js#L23) | 23 |
| [js/classical-library-api.js:29](../js/classical-library-api.js#L29) | 29, 35, 47 |
| [js/cleaning-api.js:6](../js/cleaning-api.js#L6) | 6 |
| [js/daily-anki-achievement.js:42](../js/daily-anki-achievement.js#L42) | 42 |
| [js/daily-report.js:76](../js/daily-report.js#L76) | 76 |
| [js/dashboard-settings.js:568](../js/dashboard-settings.js#L568) | 568 |
| [js/docs/projectDocsData.js:113](../js/docs/projectDocsData.js#L113) | 113 |
| [js/events-api.js:198](../js/events-api.js#L198) | 198, 230 |
| [js/feelings-api.js:4](../js/feelings-api.js#L4) | 4 |
| [js/file-settings.js:46](../js/file-settings.js#L46) | 46, 56 |
| [js/films-library-api.js:29](../js/films-library-api.js#L29) | 29, 38, 53 |
| [js/finance-page.js:1289](../js/finance-page.js#L1289) | 1289 |
| [js/football.js:32](../js/football.js#L32) | 32, 37, 183, 198, 213 |
| [js/habit-upload.js:61](../js/habit-upload.js#L61) | 61 |
| [js/habits.js:17](../js/habits.js#L17) | 17 |
| [js/heart-rate-history.js:728](../js/heart-rate-history.js#L728) | 728, 1391, 1440, 1446, 1467, 1556 |
| [js/heroClock.js:39](../js/heroClock.js#L39) | 39 |
| [js/i18n.js:23](../js/i18n.js#L23) | 23 |
| [js/journal-ocr.js:1012](../js/journal-ocr.js#L1012) | 1012 |
| [js/kermit-chat.js:219](../js/kermit-chat.js#L219) | 219 |
| [js/kermit-client.js:15](../js/kermit-client.js#L15) | 15 |
| [js/kitchen-today.js:108](../js/kitchen-today.js#L108) | 108 |
| [js/kitchen.js:308](../js/kitchen.js#L308) | 308, 859, 1456, 1478, 1557, 1588, 1716, 1759, 1763, 1773 |
| [js/language/app.js:2606](../js/language/app.js#L2606) | 2606 |
| [js/language/views/reader.js:225](../js/language/views/reader.js#L225) | 225 |
| [js/lastfm-stats.js:42](../js/lastfm-stats.js#L42) | 42 |
| [js/live-workout-journey-api.js:16](../js/live-workout-journey-api.js#L16) | 16, 20, 41 |
| [js/live-workout-journey-page.js:202](../js/live-workout-journey-page.js#L202) | 202 |
| [js/live-workout-page.js:488](../js/live-workout-page.js#L488) | 488, 489, 490, 548, 561, 613, 624 |
| [js/live-workout-strength.js:198](../js/live-workout-strength.js#L198) | 198, 241, 255, 256, 257, 279, 653, 654, 664 |
| [js/main.js:392](../js/main.js#L392) | 392 |
| [js/main_weather.js:90](../js/main_weather.js#L90) | 90 |
| [js/music-api.js:22](../js/music-api.js#L22) | 22, 28 |
| [js/network-monitor-api.js:39](../js/network-monitor-api.js#L39) | 39, 49 |
| [js/oscars-api.js:58](../js/oscars-api.js#L58) | 58, 69, 83, 97, 111, 125, 139 |
| [js/oscars-data.js:163](../js/oscars-data.js#L163) | 163, 199, 361 |
| [js/phone-cleaning-gate.js:14](../js/phone-cleaning-gate.js#L14) | 14 |
| [js/phone-tracker-api.js:4](../js/phone-tracker-api.js#L4) | 4 |
| [js/reading-api.js:19](../js/reading-api.js#L19) | 19 |
| [js/reading-covers.js:106](../js/reading-covers.js#L106) | 106, 111, 170, 397, 422 |
| [js/reading.js:2837](../js/reading.js#L2837) | 2837 |
| [js/ring-api.js:4](../js/ring-api.js#L4) | 4 |
| [js/ring-app.js:702](../js/ring-app.js#L702) | 702 |
| [js/santiago-route-qa.js:55](../js/santiago-route-qa.js#L55) | 55, 56, 57 |
| [js/sensors-page.js:187](../js/sensors-page.js#L187) | 187, 402 |
| [js/settings-runtime-status.js:32](../js/settings-runtime-status.js#L32) | 32, 62 |
| [js/settings.js:516](../js/settings.js#L516) | 516, 525, 539, 548, 563, 586, 600 |
| [js/sleep-api.js:307](../js/sleep-api.js#L307) | 307 |
| [js/spotify-screensaver.js:133](../js/spotify-screensaver.js#L133) | 133, 139, 183, 209, 219, 398 |
| [js/strength-api.js:2](../js/strength-api.js#L2) | 2 |
| [js/strength-app.js:350](../js/strength-app.js#L350) | 350 |
| [js/synchrobook/api.js:4](../js/synchrobook/api.js#L4) | 4 |
| [js/synchrobook/app.js:305](../js/synchrobook/app.js#L305) | 305, 580 |
| [js/timeline.js:1274](../js/timeline.js#L1274) | 1274 |
| [js/today-display.js:87](../js/today-display.js#L87) | 87, 398, 399 |
| [js/ui/render_weather_api.js:514](../js/ui/render_weather_api.js#L514) | 514 |
| [js/widget-ai-usage.js:79](../js/widget-ai-usage.js#L79) | 79 |
| [js/widget-blood-pressure.js:953](../js/widget-blood-pressure.js#L953) | 953 |
| [js/widget-brutal-assault-2027.js:116](../js/widget-brutal-assault-2027.js#L116) | 116, 240, 254, 299, 487, 501 |
| [js/widget-cinema-city.js:70](../js/widget-cinema-city.js#L70) | 70, 256 |
| [js/widget-diet.js:455](../js/widget-diet.js#L455) | 455, 1582, 1598, 1612, 1635, 1636, 1678, 1702, 1722 |
| [js/widget-event-countdowns.js:148](../js/widget-event-countdowns.js#L148) | 148, 149 |
| [js/widget-events.js:455](../js/widget-events.js#L455) | 455 |
| [js/widget-habits-app.js:1452](../js/widget-habits-app.js#L1452) | 1452, 1453, 1454 |
| [js/widget-language-learning.js:347](../js/widget-language-learning.js#L347) | 347 |
| [js/widget-live-workout.js:1680](../js/widget-live-workout.js#L1680) | 1680, 2508, 2568, 2692, 3014, 3015, 3063, 3222, 3223, 3224, 3225, 3404, 3408, 3440, 3455, 3816, 3818 |
| [js/widget-moving-countdown.js:157](../js/widget-moving-countdown.js#L157) | 157 |
| [js/widget-network.js:2601](../js/widget-network.js#L2601) | 2601 |
| [js/widget-order.js:291](../js/widget-order.js#L291) | 291, 332 |
| [js/widget-phone-activity.js:56](../js/widget-phone-activity.js#L56) | 56 |
| [js/widget-phone-telemetry.js:312](../js/widget-phone-telemetry.js#L312) | 312 |
| [js/widget-quote.js:119](../js/widget-quote.js#L119) | 119 |
| [js/widget-reading.js:1307](../js/widget-reading.js#L1307) | 1307 |
| [js/widget-rym-polish-black-metal.js:98](../js/widget-rym-polish-black-metal.js#L98) | 98, 121, 285 |
| [js/widget-self-care.js:136](../js/widget-self-care.js#L136) | 136, 146, 158, 180 |
| [js/widget-sensors.js:31](../js/widget-sensors.js#L31) | 31, 212 |
| [js/widget-todo.js:426](../js/widget-todo.js#L426) | 426 |
| [js/widget-voice-journal.js:380](../js/widget-voice-journal.js#L380) | 380 |
| [js/widget-weekly-insights.js:347](../js/widget-weekly-insights.js#L347) | 347, 486 |
| [js/widget-weight-cut.js:2563](../js/widget-weight-cut.js#L2563) | 2563, 2621, 2647, 2666, 2693, 2715, 2739, 2750, 2780, 2811, 2833, 2863, 2865, 2963, 2992, 2993, 3010, 3035, 3056 |
| [js/worker.js:2](../js/worker.js#L2) | 2, 7 |
| [language_learning/anki_sync.py:306](../language_learning/anki_sync.py#L306) | 306, 975 |
| [language_learning/jobs.py:72](../language_learning/jobs.py#L72) | 72 |
| [language_learning/providers/anki.py:186](../language_learning/providers/anki.py#L186) | 186 |
| [language_learning/service.py:2527](../language_learning/service.py#L2527) | 2527, 2685 |
| [language_learning/store.py:2895](../language_learning/store.py#L2895) | 2895, 2907, 2923 |
| [lastfm_store.py:390](../lastfm_store.py#L390) | 390, 474, 526, 531, 543, 546 |
| [music_enrichment.py:316](../music_enrichment.py#L316) | 316 |
| [music_store.py:836](../music_store.py#L836) | 836, 950, 1082 |
| [network_monitor/persistence.py:172](../network_monitor/persistence.py#L172) | 172 |
| [network_monitor/scanning.py:586](../network_monitor/scanning.py#L586) | 586 |
| [ring_collector.py:152](../ring_collector.py#L152) | 152, 575, 578, 610 |
| [ring_store.py:369](../ring_store.py#L369) | 369, 382, 410 |
| [scripts/build-sync-inventory.py:66](../scripts/build-sync-inventory.py#L66) | 66 |
| [scripts/kermit_model_bakeoff.py:59](../scripts/kermit_model_bakeoff.py#L59) | 59 |
| [scripts/smoke_language_grammar.py:39](../scripts/smoke_language_grammar.py#L39) | 39 |
| [server.py:388](../server.py#L388) | 388, 3960, 4025, 4210, 4218, 5403, 6719, 10746, 10753, 11962, 12314, 12390, 12500 |
| [spotify-dashboard-server.js:174](../spotify-dashboard-server.js#L174) | 174, 249, 313, 399 |
| [synchrobook_backend/service.py:53](../synchrobook_backend/service.py#L53) | 53, 151, 360, 605, 665 |
| [training_runtime.py:134](../training_runtime.py#L134) | 134 |
| [voice_journal_engines.py:154](../voice_journal_engines.py#L154) | 154 |
| [voice_journal_jobs.py:205](../voice_journal_jobs.py#L205) | 205, 403 |

### Identity / timestamps / revisions / deletion

| Source | Matching lines |
| --- | --- |
| [ai_usage.py:164](../ai_usage.py#L164) | 164, 217, 658, 676, 683, 779, 824, 915, 953, 955 |
| [android/dashboard-companion/app/src/main/java/com/cleaningdashboard/companion/ReceiptQueue.kt:23](../android/dashboard-companion/app/src/main/java/com/cleaningdashboard/companion/ReceiptQueue.kt#L23) | 23, 135, 147, 156, 227 |
| [android/how-i-feel/app/src/main/java/com/cleaningdashboard/howifeel/MainActivity.kt:386](../android/how-i-feel/app/src/main/java/com/cleaningdashboard/howifeel/MainActivity.kt#L386) | 386 |
| [android/phone-tracker/app/src/main/java/com/cleaningdashboard/phonetracker/BlockerService.kt:68](../android/phone-tracker/app/src/main/java/com/cleaningdashboard/phonetracker/BlockerService.kt#L68) | 68, 168 |
| [android/phone-tracker/app/src/main/java/com/cleaningdashboard/phonetracker/NotificationCollector.kt:72](../android/phone-tracker/app/src/main/java/com/cleaningdashboard/phonetracker/NotificationCollector.kt#L72) | 72 |
| [android/phone-tracker/app/src/main/java/com/cleaningdashboard/phonetracker/SupportingCollectors.kt:101](../android/phone-tracker/app/src/main/java/com/cleaningdashboard/phonetracker/SupportingCollectors.kt#L101) | 101 |
| [android/phone-tracker/app/src/main/java/com/cleaningdashboard/phonetracker/SyncWorker.kt:82](../android/phone-tracker/app/src/main/java/com/cleaningdashboard/phonetracker/SyncWorker.kt#L82) | 82 |
| [bm365_metadata_store.py:103](../bm365_metadata_store.py#L103) | 103 |
| [bm365_store.py:86](../bm365_store.py#L86) | 86, 107, 220, 221, 394, 564 |
| [brutal_assault_store.py:45](../brutal_assault_store.py#L45) | 45, 206, 207 |
| [cleaning_store.py:129](../cleaning_store.py#L129) | 129, 146 |
| [dashboard_sync/journal.py:19](../dashboard_sync/journal.py#L19) | 19, 20 |
| [dashboard_sync/migration.py:41](../dashboard_sync/migration.py#L41) | 41, 75 |
| [dashboard_sync/service.py:123](../dashboard_sync/service.py#L123) | 123, 128, 132, 145 |
| [docs/phone-telemetry-android/app/src/main/java/com/cleaningdashboard/phonetelemetry/notifications/NotificationCaptureService.kt:42](../docs/phone-telemetry-android/app/src/main/java/com/cleaningdashboard/phonetelemetry/notifications/NotificationCaptureService.kt#L42) | 42 |
| [feelings_store.py:543](../feelings_store.py#L543) | 543, 567, 624 |
| [finance_planning.py:114](../finance_planning.py#L114) | 114 |
| [finance_receipts.py:76](../finance_receipts.py#L76) | 76, 1149, 1362, 2217, 2232 |
| [finance_repository.py:45](../finance_repository.py#L45) | 45, 127, 139, 148, 159, 168, 178, 188, 319, 437, 555, 872, 1297, 1388, 1503 |
| [finance_review.py:475](../finance_review.py#L475) | 475 |
| [football_service.py:241](../football_service.py#L241) | 241, 291, 294, 304, 334 |
| [habits_store.py:117](../habits_store.py#L117) | 117, 180, 223, 224, 246, 247, 261, 289, 314, 325, 326, 379, 470, 500, 515, 518, 552, 630, 768, 776, 786, 829, 834, 836 |
| [jobhunt_backend/jobs.py:41](../jobhunt_backend/jobs.py#L41) | 41 |
| [jobhunt_backend/service.py:210](../jobhunt_backend/service.py#L210) | 210, 647, 666, 667, 736, 839, 873, 962, 1146, 1148, 1157, 1185, 1188, 1199, 1206, 1212, 1596, 1612, 1773, 1979, 2074, 2120, 2121, 2294, 2326, 2422, 2452, 2453, 2693, 2735, 2892, 2965, 3030, 3395, 3411, 3743, 3755, 3818, 3875, 3877, 3888, 3889, 4059, 4239, 4400, 4401, 4402, 4629, 4630, 4667, 4913, 4983, 5059, 5198 |
| [jobhunt_backend/skill_intelligence.py:796](../jobhunt_backend/skill_intelligence.py#L796) | 796 |
| [jobhunt_backend/store.py:189](../jobhunt_backend/store.py#L189) | 189, 262, 4989, 5060, 5145 |
| [journal_htr_provider.py:108](../journal_htr_provider.py#L108) | 108 |
| [journal_htr_service.py:401](../journal_htr_service.py#L401) | 401, 402, 423, 424, 448, 449, 463, 486, 504, 567, 724, 957, 1018, 1090, 1119, 1137, 1191, 1315, 1764, 1974, 2557 |
| [journal_store.py:278](../journal_store.py#L278) | 278, 279, 281, 304, 338, 390, 485, 536, 616, 618 |
| [js/ai-usage-analytics.js:169](../js/ai-usage-analytics.js#L169) | 169, 196 |
| [js/ai-usage-page.js:174](../js/ai-usage-page.js#L174) | 174, 447 |
| [js/bills-store.js:465](../js/bills-store.js#L465) | 465 |
| [js/calendar.js:162](../js/calendar.js#L162) | 162 |
| [js/cinema-city.js:184](../js/cinema-city.js#L184) | 184 |
| [js/classical-library-api.js:74](../js/classical-library-api.js#L74) | 74 |
| [js/dashboard-notifications-store.js:32](../js/dashboard-notifications-store.js#L32) | 32 |
| [js/football.js:41](../js/football.js#L41) | 41, 147 |
| [js/habits-app-api.js:64](../js/habits-app-api.js#L64) | 64, 76, 77, 90, 105, 118, 131, 133, 137, 138, 176, 189, 225, 244, 245, 252 |
| [js/habits-app-model.js:128](../js/habits-app-model.js#L128) | 128, 134, 135 |
| [js/jobhunt-evaluations.js:57](../js/jobhunt-evaluations.js#L57) | 57, 74, 119 |
| [js/jobhunt-extraction.js:49](../js/jobhunt-extraction.js#L49) | 49 |
| [js/jobhunt-insights.js:106](../js/jobhunt-insights.js#L106) | 106, 109, 115, 264, 267, 269, 270, 271 |
| [js/jobhunt-store.js:205](../js/jobhunt-store.js#L205) | 205, 206, 272, 273, 393, 421, 476, 485, 498 |
| [js/jobhunt-tracks.js:60](../js/jobhunt-tracks.js#L60) | 60 |
| [js/jobhunt.js:196](../js/jobhunt.js#L196) | 196 |
| [js/journal-api.js:52](../js/journal-api.js#L52) | 52, 53 |
| [js/journal-ocr.js:211](../js/journal-ocr.js#L211) | 211, 339 |
| [js/journal.js:902](../js/journal.js#L902) | 902 |
| [js/language/app.js:1530](../js/language/app.js#L1530) | 1530, 1944 |
| [js/language/components/lemma-detail.js:557](../js/language/components/lemma-detail.js#L557) | 557 |
| [js/language/views/generate.js:250](../js/language/views/generate.js#L250) | 250 |
| [js/language/views/reader.js:509](../js/language/views/reader.js#L509) | 509 |
| [js/live-workout-strength-engine.js:71](../js/live-workout-strength-engine.js#L71) | 71, 121 |
| [js/live-workout-strength.js:239](../js/live-workout-strength.js#L239) | 239, 284 |
| [js/mental-health-page.js:200](../js/mental-health-page.js#L200) | 200 |
| [js/moving-checklist-store.js:20](../js/moving-checklist-store.js#L20) | 20, 21, 82, 83, 97, 98, 537, 845, 846 |
| [js/reading-settings-store.js:67](../js/reading-settings-store.js#L67) | 67, 77, 86, 115, 134, 137 |
| [js/ring-view.js:60](../js/ring-view.js#L60) | 60 |
| [js/sleep-api.js:105](../js/sleep-api.js#L105) | 105, 135, 136, 182 |
| [js/strength-app.js:31](../js/strength-app.js#L31) | 31 |
| [js/synchrobook/reading-guide/ui.js:8](../js/synchrobook/reading-guide/ui.js#L8) | 8 |
| [js/synchrobook/utils.js:89](../js/synchrobook/utils.js#L89) | 89, 109 |
| [js/timeline-activity-model.js:361](../js/timeline-activity-model.js#L361) | 361 |
| [js/timeline-model.js:26](../js/timeline-model.js#L26) | 26, 512, 518, 524, 526, 527, 528, 529, 530, 563, 568 |
| [js/timeline.js:395](../js/timeline.js#L395) | 395, 827 |
| [js/todo-projects-backlog-seed.js:106](../js/todo-projects-backlog-seed.js#L106) | 106 |
| [js/todo-store.js:58](../js/todo-store.js#L58) | 58, 59, 81, 82, 89, 90, 146, 147, 154, 163, 164, 179, 231, 232, 335, 336, 361, 444, 453, 485, 486, 490, 520, 521, 538, 539, 555, 584, 595, 603 |
| [js/widget-ai-usage.js:105](../js/widget-ai-usage.js#L105) | 105, 112 |
| [js/widget-blood-pressure.js:167](../js/widget-blood-pressure.js#L167) | 167, 391, 914, 919 |
| [js/widget-brutal-assault-2027.js:55](../js/widget-brutal-assault-2027.js#L55) | 55, 64 |
| [js/widget-flat-hunt.js:67](../js/widget-flat-hunt.js#L67) | 67, 115, 545, 580 |
| [js/widget-live-workout.js:1174](../js/widget-live-workout.js#L1174) | 1174, 2559 |
| [js/widget-timeline.js:22](../js/widget-timeline.js#L22) | 22 |
| [js/widget-weekly-insights.js:133](../js/widget-weekly-insights.js#L133) | 133, 168 |
| [kermit_service/app.py:9](../kermit_service/app.py#L9) | 9, 37 |
| [language_learning/backup.py:171](../language_learning/backup.py#L171) | 171, 204 |
| [language_learning/cloze_audio.py:319](../language_learning/cloze_audio.py#L319) | 319 |
| [language_learning/generation.py:267](../language_learning/generation.py#L267) | 267, 289 |
| [language_learning/service.py:1304](../language_learning/service.py#L1304) | 1304 |
| [language_learning/store.py:30](../language_learning/store.py#L30) | 30, 4446 |
| [lastfm_store.py:90](../lastfm_store.py#L90) | 90 |
| [live_workout_store.py:487](../live_workout_store.py#L487) | 487, 514, 1055, 1425 |
| [mental_health_store.py:326](../mental_health_store.py#L326) | 326, 390, 510, 645, 655, 664, 684, 689, 694, 702, 711, 713 |
| [music_store.py:49](../music_store.py#L49) | 49, 56, 88, 100, 134, 146, 158, 179, 193, 204, 217, 243, 259, 283, 315, 1042 |
| [network_monitor/persistence.py:67](../network_monitor/persistence.py#L67) | 67, 86, 96 |
| [phone_tracker.py:416](../phone_tracker.py#L416) | 416, 442 |
| [phone_tracker_access.py:70](../phone_tracker_access.py#L70) | 70, 272 |
| [reading_store.py:83](../reading_store.py#L83) | 83, 163, 235, 236, 479 |
| [ring_store.py:78](../ring_store.py#L78) | 78, 94, 107, 125, 142, 158, 178, 205, 221, 370, 751, 812, 822 |
| [ring_wear.py:150](../ring_wear.py#L150) | 150 |
| [scripts/build-sync-inventory.py:67](../scripts/build-sync-inventory.py#L67) | 67 |
| [scripts/build_language_reference.py:40](../scripts/build_language_reference.py#L40) | 40 |
| [scripts/importers/import-rym-works.js:388](../scripts/importers/import-rym-works.js#L388) | 388, 391 |
| [scripts/journal_htr_bootstrap.py:495](../scripts/journal_htr_bootstrap.py#L495) | 495, 567 |
| [scripts/synchrobook_transcribe_worker.py:77](../scripts/synchrobook_transcribe_worker.py#L77) | 77 |
| [server.py:173](../server.py#L173) | 173, 207, 2809, 4628, 5040, 5064, 5081, 6038, 6085, 6109, 6176, 6312, 6373, 6374, 6386, 7060, 7073, 7338, 7356, 7362, 7364, 7382, 9205, 9222, 9228, 9246, 10255, 10283, 10405, 10418, 10434, 10451, 10478, 10586, 10587, 10778, 10792, 10824, 11272, 11578, 11891, 11920, 12302, 20500, 20501, 20502, 20710, 20714 |
| [spotify-dashboard-server.js:474](../spotify-dashboard-server.js#L474) | 474, 500, 631 |
| [strength_store.py:519](../strength_store.py#L519) | 519, 574, 873, 966 |
| [synchrobook_backend/reading_guide.py:379](../synchrobook_backend/reading_guide.py#L379) | 379, 414, 418, 1108 |
| [synchrobook_backend/service.py:237](../synchrobook_backend/service.py#L237) | 237, 351, 406, 455, 520, 693 |
| [timeline_activity.py:599](../timeline_activity.py#L599) | 599 |
| [timeline_store.py:74](../timeline_store.py#L74) | 74, 206, 207, 236, 237, 248, 249, 289, 310, 314, 357, 398, 421, 422, 427, 428 |
| [todo_phone.py:36](../todo_phone.py#L36) | 36, 38, 46 |
| [training_runtime.py:259](../training_runtime.py#L259) | 259 |
| [voice_journal.py:481](../voice_journal.py#L481) | 481 |
| [voice_journal_jobs.py:149](../voice_journal_jobs.py#L149) | 149, 269, 356 |
| [voice_journal_store.py:258](../voice_journal_store.py#L258) | 258, 259, 319, 320 |
