# Project Map

## Purpose

Personal, local-first, multi-page dashboard covering household tasks, health and training, reading and language learning, journals, finance, events, media, network/device monitoring, and kitchen/status displays. The browser application is a Vite multi-page app built from ES modules. Writable and integration-heavy features use local Python services; Spotify screensavers also have an alternate Node/Express server.

This map describes the current implementation only. Runtime databases, private imports, caches, and media are intentionally not repository documentation sources.

## High-Level Architecture

- `index.html` is the main dashboard. Its direct `data-widget` children are discovered by `js/dashboard-widget-loader.js`, which lazy-loads the matching widget module. `js/widget-order.js`, `js/dashboard-settings.js`, `js/dashboard-widget-visibility.js`, `data/widget-order.json`, and `data/settings/dashboard.json` control order, visibility, sizing, and headers.
- Standalone root `*.html` files are page entry points. `vite.config.js` declares the current multi-page build inputs and proxies `/api` to the Python API on `127.0.0.1:8000`; AQI uses a separate `/gios` proxy. `films.html`, `oscars.html`, `bm365.html`, and `oddychaj.html` exist and are served as root pages but are not currently explicit Rollup inputs.
- `server.py` is the central `ThreadingHTTPServer` API/static server. It owns many `/api/*` domains and composes feature-specific stores/services rather than using a web framework or generic router.
- `training_runtime.py` is the independent Live Workout runtime on port `8766`. It owns active workout lifecycle, the authoritative clock, telemetry ingest, progressive checkpoints and SSE. Current workout frontends call it directly through `js/live-workout-runtime-api.js`; restarting `server.py` or Vite does not stop or reset an active workout. See `docs/training-runtime.md`.
- `run_network_monitor.py` is a separate Flask service on port `8765`. `js/network-monitor-api.js` calls it directly on localhost (or through `VITE_NETWORK_API_BASE`).
- `scripts/scan_ble.py` is a separate long-running BLE collector for Mi Scale and environmental-sensor advertisements. `start-dev.cmd` launches it with the central API and network monitor before starting Vite.
- `scripts/dev-service.js` supervises ordinary local development processes. It auto-restarts only the central API; the network and BLE services exit without automatic restart. The training runtime is deliberately outside this supervisor and ordinary cleanup. `start-dev.cmd` only ensures that its independently detached process is ready.
- The main Status tab in `settings.html` uses `js/settings-runtime-status.js` and `/api/dashboard/runtime-status`. When launching Vite, `scripts/dev-service.js` records the main dashboard start under ignored `data/settings/`; `dashboard_runtime_status.py` combines that marker with OS boot time. The tab is informational and does not control service restarts.
- Persistence is deliberately feature-local: SQLite for transactional domains, JSON/JSONL/CSV for settings and telemetry, files for raw imports/media, and `localStorage` for browser-only or offline-mirror state. There is no IndexedDB usage in the current repository.
- External integrations are called either by browser adapters, `server.py`, the network/BLE services, Android companions, or `spotify-dashboard-server.js`. Secrets and OAuth state are local environment/runtime data.

## Folder Structure

- `index.html`, `styles.css` - main dashboard markup and the large shared stylesheet.
- Root `*.html`, feature `*.css` - standalone pages and page-specific presentation.
- `js/` - page controllers, dashboard widgets, API clients, browser stores, and shared helpers.
- `js/api/` - browser adapters for Open-Meteo and GIOS; `js/*-api.js` contains feature API clients.
- `js/language/`, `js/synchrobook/`, `js/phone-telemetry/`, `js/classical-library/` - feature-specific frontend modules.
- `server.py` - central API, static-file policy, integration adapters, and startup/shutdown orchestration; very large and fragile.
- Root `*_store.py`, `finance_*.py`, `journal_htr_*.py`, `voice_journal_*.py`, `ring_*.py` - feature-specific persistence, services, parsers, and workers.
- `language_learning/` - language store, migrations, services, Stanza analysis, generation, Anki, Cloze, curricula, and rebuildable reference-corpus infrastructure.
- `synchrobook_backend/` - book/audio extraction, alignment, Reading Guide, media processing, SQLite job service.
- `network_monitor/` - LAN scanning, Flask API, and SQLite persistence.
- `android/steps-sync/` - Health Connect snapshot/step uploader using Android WorkManager.
- `android/dashboard-companion/` - receipt document importer with ML Kit OCR, pairing-token authentication, and a durable upload queue.
- `android/phone-tracker/` - native Room collector for usage, notifications, low-power supporting samples, WorkManager LAN sync, and optional Accessibility blocker.
- `android/how-i-feel/` - native How I Feel check-in companion with the canonical 12x12 emotion map, encrypted bearer-token configuration, direct PC history, and a durable offline write queue.
- `android/todo-pocket/` - minimal native Android task/shopping companion with a home-screen widget; reads and updates the existing todo settings file through token-protected `/api/phone-todo`.
- `data/` - private runtime state, databases, source archives, caches, generated reports, and backups. Do not treat all files here as equivalent sources of truth.
- `public/` - Vite-copied static/generated data and public media; `public/data/habits.json` is a generated legacy habits view.
- `assets/`, `covers/`, `public/assets/`, `public/posters/` - media and downloaded/generated artwork.
- `apps/history-wiki/` - static, offline-capable personal-history wiki built from a generated privacy-filtered presentation snapshot; source archive remains read-only under ignored `ChatGPT/`.
- `scripts/` - importers, builders, diagnostics, isolated workers, BLE collector, and dev/backup orchestration.
- `tests/` - Vitest/happy-dom tests and Python `unittest` suites with temporary databases and fixtures.
- `docs/` - implementation and integration notes. Some documents are historical phase reports, not runtime truth.
- `antigravity-context/` - generated, privacy-filtered schemas/snapshots for external context export; not canonical application state.
- `dist/`, `reports/`, `node_modules/`, `.tmp-*`, logs, caches, large media, and raw databases - generated/heavy areas to avoid unless directly relevant.

## Entry Points / Feature Pages

| Page / app | Main frontend | Backend, routes, and storage |
| --- | --- | --- |
| Main dashboard | `index.html`, `styles.css`, `js/dashboard-widget-loader.js`, `js/widget-order.js` | Widget-specific APIs/stores; dashboard preferences through `/api/settings/dashboard`, `data/settings/dashboard.json`, and default `data/widget-order.json` |
| Calendar | `calendar.html`, `calendar.css`, `js/calendar.js`, `js/calendar-data.js`, `js/calendar-model.js` | Weekly time grid and agenda combining existing Events/Google Calendar, timeline history, How I Feel, cleaning/reading forecasts, Anki, phone, BM365, todo deadlines, bills, workout runtime and habit reminders; current weather via existing adapter. Creates events using existing local/Google APIs. No duplicate store; only source visibility in `dashboard.calendar.filters.v1`. Google cache v4 preserves original start/end in external metadata for multi-day events. |
| Settings | `settings.html`, `js/settings.js`, `js/dashboard-settings.js`, `js/network-notification-settings.js` | `/api/settings/*`; JSON settings under `data/settings/` |
| Today display (experimental) | `today-display.html`, `today-display.css`, `js/today-display.js` | Read-only view of existing daily achievements, cleaning, steps, weight, reading, Anki, workout, BM365, and habits/supplements sources; linked from Settings |
| Developer docs | `developer-docs.html`, `js/docs/projectDocsPage.js` | Static project documentation browser; no feature database |
| Cleaning | `cleaning.html`, `js/main.js`, `js/render.js`, `js/cleaning-*.js` | `/api/cleaning/*`, `cleaning_store.py`, canonical `data/cleaning.sqlite` |
| Finance / Budget | `budget.html`, `js/finance-page.js`, `js/budget-api.js`, `js/finance-*.js` | `/api/budget/*`; `finance_repository.py`, `finance_service.py`, `finance_importer.py`, `finance_classification.py`, `finance_operations.py`, `finance_planning.py`, `finance_review.py`, `finance_receipts.py`; canonical `data/finance.sqlite` |
| Reading | `reading.html`, `reading.css`, `js/reading.js`, `js/reading-*.js` | `/api/reading/*`, `reading_store.py`, canonical `data/reading.sqlite` |
| Synchrobook | `synchrobook.html`, `synchrobook.css`, `js/synchrobook/app.js` and supporting modules | `/api/synchrobook/*`, `synchrobook_backend/*`, `scripts/synchrobook_transcribe_worker.py`, canonical `data/synchrobook/library.db` plus book sources/artifacts |
| Voice journal | `voice-journal.html`, `js/widget-voice-journal.js`, `js/voice-journal-api.js` | `/api/voice-journal/*`, `voice_journal.py`, `voice_journal_store.py`, `voice_journal_jobs.py`, `voice_journal_engines.py`, `scripts/voice_journal_worker.py`, canonical `data/voice-journal.sqlite` |
| Written journal | `journal.html`, `js/journal.js`, `js/journal-api.js` | `/api/journal/*`, `journal_store.py`, `journal_context.py`, canonical `data/journal.sqlite` |
| Journal OCR / HTR | `journal-ocr.html`, `journal-ocr.css`, `js/journal-ocr.js`, `js/journal-htr-*.js` | `/api/journal-htr/*`, `journal_htr_service.py`, `journal_htr_provider.py`, `journal_htr_runtime.py`, `journal_htr_core.py`; `data/journal-htr/journal-htr.sqlite` and private page/model files |
| Great Timeline | `timeline.html`, `timeline.css`, `js/timeline.js`, `js/timeline-model.js`, `js/timeline-api.js`, `js/timeline-activity-api.js`, `js/timeline-activity-*.js` | `/api/timeline/*`, `timeline_store.py`, `timeline_activity.py`, canonical `data/timeline.sqlite`, private activity imports under `data/timeline-activity/` |
| History Wiki | `apps/history-wiki/index.html`, `apps/history-wiki/history-wiki.js`, `apps/history-wiki/history-wiki.css` | Static generated snapshot from local read-only `ChatGPT/processed/batches/`; rebuilt by `scripts/build-history-wiki-data.mjs`; no runtime API |
| Todo board | `todo.html`, `js/todo.js`, `js/todo-store.js` | `/api/settings/todo`; canonical file-backed `data/settings/todo.json` with `localStorage` working mirror/fallback |
| Todo Pocket (Android) | `android/todo-pocket/` | `/api/phone-todo` projects only open `now` and `shopping` entries and atomically applies add/complete actions to `data/settings/todo.json`; dedicated `DASHBOARD_TODO_TOKEN` or `DASHBOARD_WRITE_TOKEN` |
| Job Hunt | `jobhunt.html`, `jobhunt.css`, `js/jobhunt.js`, `js/jobhunt-router.js`, `js/jobhunt-home.js`, `js/jobhunt-jobs-view.js`, `js/jobhunt-workspaces.js`, `js/jobhunt-career.js`, `js/jobhunt-tracks.js`, `js/jobhunt-ingestion.js`, `js/jobhunt-extraction.js`, `js/jobhunt-dedupe.js`, `js/jobhunt-evaluations.js`, `js/jobhunt-skill-intelligence.js`, `js/jobhunt-insights.js`, `js/jobhunt-api.js`, `js/jobhunt-store.js`; UX map in `docs/jobhunt-ux.md` | `/api/jobhunt/*`, `jobhunt_backend/*`, immutable manifests under `jobhunt_backend/assessments/`, canonical `data/jobhunt.sqlite`; routed Home/Jobs/Tracks/Applications/Profile/Skills/Insights/Sources/Review/Advanced workspaces compose the existing domain capabilities; Packs B-C add Career Profile/assessments and Tracks/Search Profiles, Pack D adds durable source definitions/policies/listings and exact private raw captures, Pack E adds local deterministic extraction/review/projection, Pack F adds optional versioned AI factual enrichment, Pack G adds the explicitly enabled official NAV `pam-stilling-feed` adapter plus a persisted single-daemon worker/queue, Pack H adds deterministic duplicate candidates plus audited merge/unmerge, Pack I adds an independently pausable TLS/read-only Pracuj JobAlert email adapter, Pack J adds immutable explainable Career Profile x Canonical Job x Track Evaluations with versioned policies and no aggregate score, Pack K adds bounded live per-Track Skill Intelligence, Pack L1 adds Jobbnorge official Public API v1 collection, and Pack M adds versioned live market/source/application/Track analytics, manual versioned economic scenarios and 2-5 Track trade-offs, deterministic adjacent-career hypotheses with explicit proposal decisions, and durable Career Experiments; legacy offers/settings remain untouched recovery input |
| AI Usage | `ai-usage.html`, `ai-usage.css`, `js/ai-usage-page.js`, `js/ai-usage-api.js` | `/api/ai-usage`, `ai_usage.py`, `data/ai-usage.sqlite` |
| Phone Activity | `phone-activity.html`, `phone-activity.css`, `js/phone-activity-page.js`, `js/phone-tracker-api.js` | `/api/phone-tracker/*`, `phone_tracker.py`, `phone_tracker_rules.py`, `phone_tracker_insights.py`, canonical `data/phone-tracker.sqlite`; paired native Android app under `android/phone-tracker/` |
| Language Learning | `language.html`, `language.css`, `js/language/app.js` and `js/language/*`; Today, grouped navigation, shared lexical inspector | `/api/language/*` including Anki deck insights, Reader sentence translation and study packs with contextual word glosses, reading series and staged story decks, word pronunciation audio, `language_learning/*`, canonical `data/language-learning.sqlite` (v22), rebuildable `data/reference/language-reference-nb.sqlite` (v3), generated audio cache; see `docs/LANGUAGE_UX_PRODUCTIZATION_RESULTS.md` |
| Music hub | `music.html`, `music.css`, `js/music.js`, `js/music-api.js` | `/api/music/*` and `/api/lastfm/*`; `music_store.py`, `music_enrichment.py`, `music_importers.py`, `music_legacy_adapters.py`, `lastfm_store.py`; canonical `data/music.sqlite`, local artwork in `covers/`, and Last.fm mirror `data/lastfm.sqlite` |
| Films / Oscars | `films.html`, `js/films.js`, `js/films-*.js`; `oscars.html`, `js/oscars*.js`, `js/oscars-api.js` | `/api/films/*`, `/api/oscars/*`; shared canonical `watchlist.sqlite`, generated `data/films/library.json`, Oscar source/cache files under `data/oscars/` |
| Classical Library | `classical-library.html`, `js/classical-library.js`, `js/classical-library/*`, `js/classical-library-api.js` | `/api/classical-library/*`; JSON state/raw uploads under `data/classical-library/`, public/local composer images |
| BM365 | `bm365.html`, `js/bm365-page-v2.js`, `js/bm365.js`, `js/bm365-api.js` | `/api/bm365/*`; `bm365_store.py`, `bm365_metadata_store.py`, `bm365_sheets_syncer.py`; `data/bm365.sqlite`, metadata cache DB, `covers/` |
| Brutal Assault 2027 | `brutal-assault-2027.html`, shared `js/bm365-page-v2.js`, `js/widget-brutal-assault-2027.js` | `/api/brutal-assault-2027/*`; `brutal_assault_store.py`, `brutal_assault_ratings.py`; `data/brutal-assault-2027.sqlite` |
| Top 100 RYM Polish BM | `rym-polish-black-metal-top-100.html`, shared `js/bm365-page-v2.js`, `js/widget-rym-polish-black-metal.js` | `/api/rym-polish-black-metal/*`; `rym_polish_black_metal_store.py`; seed JSON plus canonical rating SQLite |
| Live Workout / Strength | `live-workout.html`, `live-workout.css`, `js/live-workout-page.js`, `js/widget-live-workout.js`, `js/live-workout-runtime-api.js`, `js/live-workout-journey-page.js`, `js/live-workout-*.js`, `js/strength-api.js`, `js/strength-*.js`; developer-only journey geometry map in `santiago-route-qa.html`, `js/santiago-route-qa.js` | Independent `training_runtime.py` on `8766` owns `/api/live-workout/*` live lifecycle/SSE, `data/live-workout.sqlite`, and private postcard media through `journey_postcards.py`; central `/api/strength/*` and `strength_store.py` retain strength analytics/history support; cached journey geometry/QA remains static under `data/journeys/santiago/` with public runtime/map copies |
| Heart-rate history | `heart-rate-history.html`, `heart-rate-history.css`, `js/heart-rate-history.js` | Live Workout history/SSE routes plus merged smartwatch/Health Connect/ring history |
| Sleep | `sleep.html`, `sleep.css`, `js/sleep-page.js`, `js/sleep-api.js`, `js/sleep-analysis.js` | `/api/health-connect/history`; deterministic analysis over Health Connect snapshots |
| Mental Health | `mental-health.html`, `mental-health.css`, `js/mental-health-page.js`, `js/mental-health-api.js`, `mental_health_registry.py`, optional authorised packs under `mental_health_questionnaires/<instrument>/<language>.json` | `/api/mental-health/*`, `mental_health_store.py`, canonical private `data/mental-health.sqlite`; versioned assessments/item responses, schedules, check-ins, context events, custom trackers, export/import |
| COLMI ring | `ring.html`, `ring.css`, `js/ring-app.js`, `js/ring-api.js`, `js/ring-view.js` | `/api/ring/*`; `ring_store.py`, `ring_collector.py`, `ring_protocol.py`, `ring_phone_bridge.py`, `ring_wear.py`; canonical `data/ring.sqlite` |
| Blood pressure | `blood-pressure.html`, `js/widget-blood-pressure.js` | Browser-only `localStorage`; no backend/API |
| Breathwork | `oddychaj.html`, `breathwork.css`, `js/breathwork.js`, `js/breathwork-protocols.js` | Browser-only settings/session history in `localStorage`; no backend/API |
| Sensors | `sensors.html`, `sensors.css`, `js/sensors-page.js` | `/api/sensor/latest`, `/api/sensor/history`; BLE collector writes `data/sensor/latest.json` and `data/sensor/readings.jsonl` |
| Kitchen / Hitchen | `kitchen.html`, `hitchen.html`, `kitchen.css`, `js/kitchen.js`, `js/kitchen-today.js`, `js/kitchen-namedays.js`, `js/kitchen-recipe.js` | `/api/kitchen/*`, `/api/settings/dashboard`, read-only Today goal sources; offline annual namedays in `data/polish-namedays.json`; JSON configuration/cache in `data/kitchen-*.json` and external sports/weather/AQI sources |
| Football Hub | `football.html`, `football.css`, `js/football.js`, `football_service.py`, `football_store.py`, `data/football-knowledge.json` | Existing Kitchen score/live/table refresh plus historical `data/football.sqlite` (v2) and lazy cached club/player/squad/stadium profiles; additive `/api/football/entity`, `/search`, `/learn`, `/refresh`; `/api/football/settings` preserves tablet presentation; see `docs/FOOTBALL-HUB.md` and `docs/FOOTBALL-HUB-AUDIT.md` |
| Spotify screensavers | `spotify-screensaver.html`, `artist-facts-screensaver.html`, related CSS/JS | `/api/spotify/*`, `/api/screensaver-config`, `/api/screensaver-status`, `/api/artist-facts`; implemented by `server.py` and duplicated in alternate `spotify-dashboard-server.js`; state/cache under `data/spotify/` |

`404.html` is a static fallback page. Dashboard-only features without a standalone page include weather, AQI, self-care, weight/steps, diet, events/countdowns, phone telemetry, habits, quote, Cinema City, and network monitoring.

## Main Dashboard Widgets

These are the current direct `data-widget` registrations in `index.html`. The lazy-loader registry is in `js/dashboard-widget-loader.js`; `habits-timeline` uses the loader's special multi-module branch.

| `data-widget` / widget | Main frontend | Backend / data | Representative tests |
| --- | --- | --- | --- |
| `weather` / Weather | `js/main_weather.js`, `js/ui/render_weather_api.js`, `js/api/openMeteo.js`, `js/temp-scale.js` | Open-Meteo; browser configuration in `js/config.js` | `tests/temp-scale.test.js` |
| `aqi` / Air quality | `js/init-aqi.js`, `js/aqi.js`, `js/api/gios.js` | GIOS API through Vite `/gios` or configured worker fallback | API adapter coverage is limited |
| `cleaning` | `js/widget-cleaning.js`, `js/cleaning-api.js` | `/api/cleaning/*`, `cleaning_store.py`, `data/cleaning.sqlite` | `tests/widget-cleaning.test.js`, `tests/test_cleaning_store.py` |
| `self-care` | `js/widget-self-care.js` | `/api/timeline/activity/self-care`, `timeline_activity.py`, `data/timeline-activity/self-care.jsonl` | timeline activity tests |
| `feelings` | `js/widget-feelings.js`, `js/feelings-api.js` | `/api/feelings/*`, `feelings_store.py`, private `data/feelings.sqlite`; paired How I Feel companion | `tests/widget-feelings.test.js`, `tests/test_feelings_http.py` |
| `reading` | `js/widget-reading.js`, `js/reading-*.js` | `/api/reading/*`, `reading_store.py`, `data/reading.sqlite` | reading JS/Python suites |
| `language-learning` | `js/widget-language-learning.js`, `js/language/api.js` | `/api/language/profiles/*/widget-summary` (shared Today snapshot, persisted Anki state), `language_learning/*` | `tests/widget-language-learning.test.js`, language suites |
| `phone-telemetry` | `js/widget-phone-telemetry.js`, `js/phone-telemetry/*` | Static/exported JSON bundles under `data/phone-telemetry/`; Android reference implementation is under `docs/phone-telemetry-android/` | phone telemetry parser/analytics tests |
| `phone-activity` | `js/widget-phone-activity.js`, `js/phone-tracker-api.js` | Live `/api/phone-tracker/*` read model over `data/phone-tracker.sqlite`; detail page `phone-activity.html` | `tests/widget-phone-activity.test.js`, `tests/phone-activity-page.test.js`, `tests/test_phone_tracker.py`, `tests/test_phone_tracker_http.py`, `tests/test_phone_tracker_insights.py` |
| `todo` | `js/widget-todo.js`, `js/todo-store.js`, `js/todo-animations.js` | `/api/settings/todo`, `data/settings/todo.json`, `localStorage` mirror | todo store/page/widget tests |
| `bills` | `js/widget-bills.js`, `js/bills-store.js` | Canonical Finance obligations/occurrences through `/api/budget/*`; `localStorage` is a UI mirror | bills and Finance planning tests |
| `budget` / Finance | `js/widget-budget.js`, `js/budget-api.js` | `/api/budget/*`, Finance services, `data/finance.sqlite` | budget/Finance JS and Python suites |
| `weight-cut` / Weight and steps | `js/widget-weight-cut.js`, `js/daily-report.js` | `/api/weight/*`, `/api/steps/*`, `/api/health-connect/*`; scale and Health Connect files | weight/statistics and health-history tests |
| `live-workout` | `js/widget-live-workout.js`, `js/live-workout-runtime-api.js`, workout engine/calibration/optimizer/transfer modules | Direct runtime `http://<dashboard-host>:8766/api/live-workout/*`, `training_runtime.py`, `live_workout_store.py`, `data/live-workout.sqlite` | live-workout engine/store/page and runtime lifecycle/process-isolation tests |
| `diet` | `js/widget-diet.js`, `js/daily-report.js` | `/api/diet/*`, canonical `data/diet/diet.json`; weight/steps context | `tests/widget-diet-suggestions.test.js` |
| `journal-htr` | `js/widget-journal-htr.js`, `js/journal-htr-api.js` | `/api/journal-htr/*`, HTR service/runtime/store | HTR widget/API/Python suites |
| `jobhunt` | `js/widget-jobhunt.js`, `js/jobhunt-api.js`, `js/jobhunt-store.js` compatibility helpers | `/api/jobhunt/overview`, `jobhunt_backend/*`, `data/jobhunt.sqlite`; full page `jobhunt.html` includes Pack J Evaluation, Pack K Skill Intelligence, Pack L1 Jobbnorge operations, and Pack M Insights/Experiments | `tests/jobhunt-store.test.js`, `tests/jobhunt-api.test.js`, `tests/jobhunt-evaluations.test.js`, `tests/jobhunt-skill-intelligence.test.js`, `tests/jobhunt-pack-l1.test.js`, `tests/jobhunt-pack-m.test.js`, `tests/widget-jobhunt.test.js`, `tests/test_jobhunt_backend.py`, `tests/test_jobhunt_pack_j.py`, `tests/test_jobhunt_pack_k.py`, `tests/test_jobhunt_pack_l1.py`, `tests/test_jobhunt_pack_m.py`, `tests/test_jobhunt_pack_m_http.py` |
| `ai-usage` | `js/widget-ai-usage.js`, `js/ai-usage-api.js` | `/api/ai-usage`, `ai_usage.py`, `data/ai-usage.sqlite` | AI usage widget/analytics/Python tests |
| `mental-health` | `js/widget-mental-health.js`, `js/mental-health-api.js`; full page `mental-health.html` | `/api/mental-health/*`, `mental_health_store.py`, `mental_health_registry.py`, private `data/mental-health.sqlite` | `tests/widget-mental-health.test.js`, `tests/mental-health-api.test.js`, `tests/test_mental_health.py` |
| `weekly-insights` | `js/widget-weekly-insights.js` | Existing cleaning, reading, Job Hunt, AI Usage, steps, and Health Connect APIs; no separate persistence | `tests/widget-weekly-insights.test.js` |
| `quote` | `js/widget-quote.js` | External quote APIs; card starts hidden until content is ready | limited direct coverage |
| `films` | `js/widget-films.js`, `js/films-shared.js`, `js/films-library-api.js` | `/api/films/*`, `watchlist.sqlite`, generated film snapshot | films helper/library tests |
| `cinema-city` | `js/widget-cinema-city.js`, `js/cinema-city.js`, `js/cinema-city-stats-adapter.js` | `/api/cinema-city/*`, Google Calendar/Sheets-derived data and repertoire adapter | Cinema City JS/Python tests |
| `classical-library` | `js/widget-classical-library.js`, `js/classical-library-api.js` | `/api/classical-library/*`, `data/classical-library/` | classical library tests |
| `network-monitor` | `js/widget-network.js`, `js/network-monitor-api.js`, notification settings | Separate Flask `/api/network/*`, `network_monitor/*`, `data/network-monitor.sqlite` | network settings plus Python monitor tests |
| `bm365` | `js/bm365.js`, `js/bm365-api.js` | `/api/bm365/*`, BM365 stores and durable Sheets queue | BM365 widget/store/metadata tests |
| `brutal-assault-2027` | `js/widget-brutal-assault-2027.js` | `/api/brutal-assault-2027/*`, canonical event SQLite, separate official-site monitor JSON | BA store/ratings/cross-list/monitor tests |
| `rym-polish-black-metal-top-100` | `js/widget-rym-polish-black-metal.js` | `/api/rym-polish-black-metal/*`, seed JSON and canonical rating SQLite | RYM store/cross-list tests |
| `habits` / Summary | `js/habits.js`, `js/habits-app-model.js` | Generated `public/data/habits.json` plus live preview mutations from the canonical Habits app | sobriety and habits model tests |
| `events` | `js/widget-events.js`, `js/events-api.js`, `js/events-*.js` | `/api/events*`, `/api/google-calendar/*`, local events and Google cache/overrides | events sources/insights/widget tests |
| `event-countdowns` | `js/widget-event-countdowns.js`, shared event helpers, notification store | Same event backend plus `data/settings/events.json` and public cover assets | countdown JS/Python tests |
| `sensors` | `js/widget-sensors.js` | `/api/sensor/*`, BLE collector JSON/JSONL | sensor widget/page/API tests |
| `habits-app` | `js/widget-habits-app.js`, `js/habits-app-api.js`, `js/habits-app-model.js`, `js/supplement-panel.js`, `js/habits-reminder-schedule.js`, `js/habits-reminder-execution.js` | `/api/habits/snapshot`, `/api/habits/sync`, `/api/habits/reminders/*`, `/api/habits/supplements*`, `habits_store.py`, `supplements_store.py`, canonical `data/habits.sqlite`; supplement product/regimen history and two slot claims share the same database | habits app, reminder, and supplement JS/Python tests |
| `habits-timeline` | `js/habit-data.js`, `js/habit-timelines.js`, `js/habit-upload.js` | Generated legacy dataset and `/api/habits/upload-db`; full-width card | habits parsing/timeline coverage |

Widget modules present but not currently registered by `index.html` include `js/widget-blood-pressure.js`, `js/widget-flat-hunt.js`, `js/widget-journal.js`, `js/widget-moving-checklist.js`, `js/widget-moving-countdown.js`, `js/widget-oscars.js`, `js/widget-timeline.js`, `js/widget-voice-journal.js`, and `js/widget-voice-journal-compact.js`. Their existence does not make them active dashboard cards.

## Backend / API Domains

| API domain | Backend implementation | Persistence / notes |
| --- | --- | --- |
| `/api/settings/*` | handlers in `server.py` | allowlisted JSON under `data/settings/`; used by dashboard, todo, events, and workout tracking |
| `/api/dashboard/*` | runtime-status handler in `server.py` | read-only dashboard/Windows start metadata; no settings mutation |
| `/api/cleaning/*` | `cleaning_store.py` | `data/cleaning.sqlite` |
| `/api/reading/*` | `reading_store.py` | `data/reading.sqlite` and cover proxy/cache behavior |
| `/api/budget/*` | `finance_service.py` over repository/import/classification/operations/planning/review/receipt modules | `data/finance.sqlite`; private backups, raw imports, and receipt originals |
| `/api/jobhunt/*` | `jobhunt_backend/service.py`, `jobhunt_backend/store.py`, `jobhunt_backend/dedupe.py`, `jobhunt_backend/evaluation.py`, `jobhunt_backend/skill_intelligence.py`, `jobhunt_backend/analytics.py`, `jobhunt_backend/career_intelligence.py`, ordered migrations, `jobhunt_backend/assessments/{loader,scoring}.py`, `jobhunt_backend/ingestion/{archive,manual}.py`, `jobhunt_backend/extraction/{deterministic,normalization}.py` | `data/jobhunt.sqlite`; profile/assessment/Track state, ingestion metadata, versioned Extraction Runs, hybrid typed/open facts, normalization mappings, canonical projection history, Review Items, Human Overrides, deterministic Duplicate Candidates, merge/unmerge audit, immutable Track Evaluation policies/results/findings, current Evaluation pointers, application-time attribution, versioned manual economic scenarios, proposal decisions, and Career Experiments/events; Pack K and Pack M analytics remain bounded rebuildable live read models; exact hash-addressed raw bytes, Pack A recovery snapshots, and branding assets remain private under `data/jobhunt/` |
| `/api/phone-tracker/*` | `server.py`, `phone_tracker.py`, `phone_tracker_rules.py`, `phone_tracker_insights.py` | private `data/phone-tracker.sqlite`; paired phone authentication for sync |
| `/api/mental-health/*` | `server.py`, `mental_health_store.py`, `mental_health_registry.py` | private `data/mental-health.sqlite`; assessments, check-ins, schedules and exports |
| `/api/feelings/*` | `server.py`, `feelings_store.py` | private `data/feelings.sqlite`; check-ins and companion token boundary |
| `/api/habits/*` | `habits_store.py`, `supplements_store.py`; upload/build handlers in `server.py` | canonical `data/habits.sqlite`; additive supplement product/regimen history; legacy import/build outputs remain separate |
| `/api/timeline/*` | `timeline_store.py`, `timeline_activity.py` | `data/timeline.sqlite` plus activity source files and linked feature stores |
| `/api/journal/*` | `journal_store.py`, `journal_context.py` | `data/journal.sqlite`; can publish voice-journal entries |
| `/api/sync/*` | `dashboard_sync/{http,service,core,journal,migration,backup}.py` | Protocol v1; sole pilot `journalEntry` stays in `data/journal.sqlite` with transactional versions, SQL-triggered change references, tombstones, receipts and device counters; see `docs/SYNC-ARCHITECTURE.md`, `docs/SYNC-PROTOCOL.md`, `docs/SYNC-MIGRATION.md` |
| `/api/voice-journal/*` | `voice_journal*.py` | shared `data/voice-journal.sqlite`, raw audio/job files |
| `/api/journal-htr/*` | `journal_htr_service.py`, provider/runtime/core modules | `data/journal-htr/journal-htr.sqlite`, originals/working images/models; eScriptorium provider |
| `/api/synchrobook/*` | `synchrobook_backend/service.py`, `synchrobook_backend/reading_guide.py` | `data/synchrobook/library.db`, source books/audio, generated artifacts |
| `/api/language/*` | `language_learning/service.py` and subordinate services/providers | user DB, reference DB, curricula, generated audio; reading series CRUD/episode assignment and frozen continuation prompts; durable jobs share the user DB |
| `/api/live-workout/*` | independent `training_runtime.py` using `live_workout_store.py` and `live_workout_plan.py`; legacy central handlers remain for old clients | `data/live-workout.sqlite` in WAL mode; durable active clock/checkpoints/samples/outbox, idempotent lifecycle, reconnectable SSE; runtime port `8766` |
| `/api/strength/*` | `strength_store.py` | `data/strength.sqlite`; initialized from/migrates relevant workout history |
| `/api/ring/*` | ring collector/store/protocol/phone bridge | `data/ring.sqlite`; BLE and optional phone ingest |
| `/api/weight/*`, `/api/steps/*`, `/api/health-connect/*` | telemetry helpers in `server.py` | scale CSV/JSONL, manual step JSON, Health Connect JSON/JSONL |
| `/api/diet/*` | deterministic JSON operations in `server.py` | `data/diet/diet.json` |
| `/api/sensor/*` | read/history handlers in `server.py` | BLE collector's latest JSON and JSONL history |
| `/api/ai-usage` | `ai_usage.py` | `data/ai-usage.sqlite`; quota/session telemetry, not an LLM inference API |
| `/api/events*`, `/api/google-calendar/*` | event and Google OAuth/Calendar/Tasks adapters in `server.py` | local event JSON, countdown settings, Google cache/state/overrides |
| `/api/films/*`, `/api/oscars/*` | film/Oscar handlers in `server.py` | shared `watchlist.sqlite`, Oscar source cache, generated film JSON/posters |
| `/api/classical-library/*` | handlers/parsers in `server.py` | JSON state, preserved RYM uploads, generated/public images |
| `/api/music/*` | `music_store.py`, `music_importers.py`, `music_legacy_adapters.py` | canonical `data/music.sqlite`, content-addressed raw HTML imports |
| `/api/lastfm/*` | `lastfm_store.py` | synchronized `data/lastfm.sqlite` mirror |
| `/api/bm365/*` | BM365 stores and Sheets syncer | canonical BM365 DB, metadata cache, covers, durable outbound queue |
| `/api/brutal-assault-2027/*` | BA store, ratings enricher, official lineup/news monitor | event album/rating SQLite, separate `data/brutal-assault-2027-monitor.json`, and downloaded covers |
| `/api/rym-polish-black-metal/*` | RYM store | seed catalog plus rating SQLite |
| `/api/kitchen/*` | sports/weather/image adapters in `server.py` | kitchen settings/scores/league/crest JSON caches |
| `/api/football*` | `server.py`, `football_service.py`, `football_store.py` | snapshot/history, shared Kitchen refresh, lazy entity profiles/cache, local search, sourced learning cards, presentation settings and private `data/football.sqlite` |
| `/api/cinema-city/*` | `cinema_city_repertoire.py` plus server handlers | parsed repertoire and monthly statistics from configured sources |
| `/api/spotify/*`, `/api/screensaver-config`, `/api/screensaver-status`, `/api/artist-facts` | `server.py`; alternate duplicate implementation in `spotify-dashboard-server.js` | OAuth/player state, settings, artist facts/media cache |
| `/api/network/*` | separate `network_monitor/api.py` Flask service | `data/network-monitor.sqlite`, compatibility/profile JSON; normally port `8765` |

The direct dashboard markup and loader currently agree on **34 registered widget keys**; the shipped `data/widget-order.json` defaults hide 13. Targeted route inspection finds **44 implemented `/api/<domain>` prefixes**, including Sync, across the central API, independent Live Workout runtime and Network Monitor, counting a prefix once when multiple processes expose it. This inventory count does not validate every domain for Phase 8.

Blood pressure and breathwork intentionally have no backend routes. The legacy Phone Telemetry widget reads exported files; the new Phone Activity domain uses paired LAN sync and SQLite. Todo persists through the generic settings API rather than a dedicated `/api/todo` domain.

## Persistence / Data Stores

| Feature | Storage | Role | Notes |
| --- | --- | --- | --- |
| Dashboard/settings | `data/settings/*.json`, `data/widget-order.json`, browser preferences | **CANONICAL + defaults/mirrors** | server JSON is writable state; `data/widget-order.json` supplies defaults; some UI-only preferences remain in `localStorage` |
| Cleaning | `data/cleaning.sqlite` | **CANONICAL** | old `data/settings/cleaning*.json` and Google rows are migration/recovery input only |
| Reading | `data/reading.sqlite` | **CANONICAL** | old settings/history JSON and Google data are import/migration inputs |
| Finance/Bills | `data/finance.sqlite` | **CANONICAL** | transactions, classification, obligations, occurrences, goals, plans, receipts, review audit; `data/budget.json` and `data/settings/bills.json` are migration/recovery only |
| Finance source material | `data/finance-receipts/`, `data/budget-backups/`, `data/.finance-account-key` | **RAW ARCHIVE / BACKUP / SECRET RUNTIME** | private paths are denied by both Python and Vite serving policies |
| Todo | `data/settings/todo.json`, `localStorage: todo-items-v1` | **CANONICAL file + working mirror/fallback** | generic file-settings adapter keeps browser and local API synchronized |
| Job Hunt | `data/jobhunt.sqlite`; private `data/jobhunt/{raw,backups,assets}/`; legacy `dashboard.jobhunt.*` keys | **CANONICAL SQLite + RAW ARCHIVE after verified cutover** | SQLite owns source/listing/capture/mail-cursor metadata plus immutable deterministic/AI extraction runs and facts, AI attempt/usage provenance, mappings, projection history, reviews, overrides, duplicate decisions, reversible merge audit, immutable Track policy/Evaluation history, per-pair current pointers, application attribution, economic-scenario history/current pointers, Track-proposal decisions/events, and Career Experiments/events; Pack K and Pack M metrics read these records live and add no aggregate tables; exact manual TXT/HTML/JSON and recognized Pracuj RFC822 bytes are SHA-256-addressed below `raw/sha256/`; offers/settings migrate through a bounded fingerprinted snapshot, legacy scores/settings stay separate compatibility data, and `dashboard.jobhunt.authority` records verified cutover |
| Habits app | `data/habits.sqlite` | **CANONICAL** | change cursor and idempotent mutation log support dashboard/Android-style sync; supplement catalog, dated products/regimens, slots, and notification claims share this file |
| Legacy habits views | `data/habit-data.json`, `js/habit-data.js`, `public/data/habits.json`, `data/report.*` | **MIGRATION/SEED + GENERATED** | built from raw Loop Habit DB/CSV imports; not equal to the canonical Habits app DB |
| Journals | `data/journal.sqlite`, `data/voice-journal.sqlite` | **CANONICAL** | voice job rows/performance share the voice DB; raw audio/job files are private source/runtime artifacts |
| Journal HTR | `data/journal-htr/journal-htr.sqlite`, originals/working/thumbnails/model files | **CANONICAL + RAW ARCHIVE + GENERATED** | SQLite owns workflow/evidence; originals are preserved, working copies/thumbnails are derived |
| Timeline | `data/timeline.sqlite` | **CANONICAL** | manual categories/items; connected activity is queried from source feature stores |
| Timeline activity | `data/timeline-activity/self-care.jsonl`, `data/timeline-activity/emotions.json` | **CANONICAL PRIVATE IMPORT/CAPTURE** | self-care is append/update data; How We Feel is imported evidence |
| Language user state | `data/language-learning.sqlite` | **CANONICAL** | profiles, texts/tokens, reading series and episode links, knowledge, Anki links, Reader sentence translations, contextual glosses and grammar notes, jobs including word-audio queue, generation requests/candidates, Cloze, curriculum progress, benchmark runs/responses (v22) |
| Language reference | `data/reference/language-reference-nb.sqlite` | **GENERATED / REBUILDABLE** | isolated from user state; rebuilt from versioned manifests/artifacts/importers |
| Language audio | `data/audio/language-learning/` | **CACHE / GENERATED** | content-addressed Google Cloud TTS sentence and single-word MP3 output |
| Synchrobook | `data/synchrobook/library.db` | **CANONICAL** | book catalog, jobs, progress, Reading Guide metadata |
| Synchrobook books/artifacts | `data/synchrobook/books/` | **RAW ARCHIVE + GENERATED CACHE** | uploaded EPUB/PDF/MOBI/audio are source material; extracted text, merged audio, transcripts, alignment are rebuildable |
| Live Workout / Strength | `data/live-workout.sqlite`, `data/strength.sqlite`, `data/live-workout-plan.json`, `data/settings/live-workout-plan.json` | **CANONICAL** | runtime-owned sessions, progressive HR samples, active checkpoints and virtual-walk outbox are durable in WAL-mode workout SQLite; prescribed plan/page tracking remain separate JSON state |
| Weight/steps | `data/scale/scale_measurements.jsonl`, `data/scale/scale_measurements.csv`, `data/scale/steps.json`, `data/scale/latest.json`, `data/scale/signal.json`, `data/scale/scale_raw.jsonl` | **CANONICAL LOG + CACHE + RAW ARCHIVE** | normalized history is retained; latest/signal are replaceable snapshots; raw BLE advertisements are evidence |
| Health Connect/sleep | `data/health-connect/snapshots.jsonl`, `data/health-connect/latest.json` | **CANONICAL INGESTED HISTORY + CACHE** | uploaded by Android steps-sync; sleep page derives analysis at read time |
| Sensors | `data/sensor/readings.jsonl`, `data/sensor/latest.json` | **CANONICAL HISTORY + CACHE** | written by the BLE collector |
| Diet | `data/diet/diet.json` | **CANONICAL** | meal, estimate, ignore-day state |
| Ring | `data/ring.sqlite` | **CANONICAL** | BLE/phone ingest, measurements, capabilities, diagnostics; `data/ring-mock.sqlite` is test/dev data |
| AI Usage | `data/ai-usage.sqlite` | **CANONICAL LOCAL TELEMETRY HISTORY** | observations/sessions derived from Codex and Antigravity local services; historical rows are not regenerated |
| Network monitor | `data/network-monitor.sqlite`, `data/network-known-devices.json` | **CANONICAL HISTORY + COMPATIBILITY MIRROR** | SQLite owns scans/presence/profile state; JSON profiles are read and maintained for compatibility |
| Phone telemetry | `data/phone-telemetry/*.json` | **RAW/IMPORTED SNAPSHOTS** | widget parses exported Android bundles; no backend database |
| Phone Activity | `data/phone-tracker.sqlite` | **CANONICAL PRIVATE SQLITE** | paired device credentials (hashes only), raw events, app registry/icons, sync receipts, rules, external conditions, place labels, and retention settings; never serve directly |
| Events | `data/events.json`, `data/settings/events.json` | **CANONICAL LOCAL STATE** | local events and countdown preferences/categories |
| Google Calendar/Tasks | `data/google-calendar/events-cache.json`, `data/google-calendar/state.json`, `data/google-calendar/overrides.json` | **CACHE + CANONICAL OVERRIDES/OAUTH STATE** | external events are rebuildable; dashboard overrides and OAuth/sync state are local state |
| Films/Oscars | `watchlist.sqlite` | **CANONICAL** | `data/films/library.json` is generated; Oscar year JSON/CSV and posters are seeds/caches |
| Classical Library | `data/classical-library/` | **CANONICAL JSON + RAW ARCHIVE + GENERATED MEDIA** | progress/catalog state, preserved RYM HTML uploads, composer image assets |
| Music | `data/music.sqlite` | **CANONICAL** | catalog, releases, genres, lists, ratings, rankings, import staging, legacy links |
| Music imports | `data/music-imports/*.html` | **RAW ARCHIVE** | content-addressed saved HTML retained for deterministic reparsing |
| Last.fm | `data/lastfm.sqlite` | **EXTERNAL MIRROR / ANALYTICS SOURCE** | synchronized scrobbles and derived summaries used by Music and Timeline |
| BM365 | `data/bm365.sqlite` | **CANONICAL** | albums, listening/rating state, release years, descriptions, and durable Sheets push queue |
| BM365 metadata | `data/bm365-metadata.sqlite`, `covers/` | **CACHE / GENERATED MEDIA** | enrichment and cover artifacts |
| Brutal Assault / RYM Top 100 | `data/brutal-assault-2027.sqlite`, `data/rym-polish-black-metal-top-100.sqlite`, `data/rym-polish-black-metal-top-100.json` | **CANONICAL USER STATE + SEED** | ratings/progress are SQLite; the RYM JSON is immutable seed input |
| Brutal Assault official monitor | `data/brutal-assault-2027-monitor.json` | **EXTERNAL OBSERVATION + EVENT HISTORY** | independent official lineup/news baselines and bounded events; news detail is retained for 30 days, IDs remain for deduplication; checked at backend startup and every six hours |
| Kitchen | `data/kitchen-settings.json`, `data/kitchen-scores.json`, `data/kitchen-leagues.json`, `data/kitchen-team-crests.json`, `data/polish-namedays.json` | **CANONICAL SETTINGS + CACHE** | live sports/weather responses are refreshed; curated settings/catalog and annual namedays remain local state |
| Spotify/screensavers | `data/spotify/state.json`, `data/spotify/screensaver-settings.json`, artist facts/media dirs | **CANONICAL OAUTH/SETTINGS + CACHE** | media/facts can be refreshed; tokens/state are private runtime data |
| Blood pressure / breathwork | feature `localStorage` keys | **CANONICAL browser-only** | no server synchronization |
| Antigravity context export | `antigravity-context/snapshots/`, `summaries/`, schemas | **GENERATED** | privacy-filtered derivative produced by `scripts/export_antigravity_context.py` |

No IndexedDB API or wrapper was found. Browser storage is plain `localStorage` (and occasional in-memory caches).

## Background Jobs / Workers

| Mechanism | Implementation and durability | Restart / retry behavior |
| --- | --- | --- |
| Dev process supervisor | `scripts/dev-service.js`, `start-dev.cmd` | central API restarts after 1.5 seconds; Vite, network, and scale processes are ordinary dev lifecycle; detached `training_runtime.py` is ensured at startup but explicitly not stopped/restarted with them |
| Training runtime | `training_runtime.py`, `start-training-runtime.ps1`, `start-dashboard.ps1`, `start-all.ps1` | separate process on `8766`; active session and samples recover from WAL SQLite; main dashboard restarts have no lifecycle authority over it |
| Language analysis/generation/audio queue | `language_learning/jobs.py`, `language_learning/word_audio.py` with rows in `data/language-learning.sqlite` | single daemon worker; interrupted analysis/candidate and word-audio rows are requeued up to three attempts, then failed; automatic generation rows are also recovered; existing vocabulary and new text words are enqueued for cached Google Cloud TTS |
| Synchrobook processing | `synchrobook_backend/service.py`, durable jobs in `library.db`, isolated `scripts/synchrobook_transcribe_worker.py` | active pipeline states return to `QUEUED` on startup; readable artifacts and transcript/checkpoint files are reused; an existing live transcription process can be reattached; manual resume/priority is supported |
| Voice-journal transcription | `voice_journal_jobs.py`, isolated `scripts/voice_journal_worker.py`, durable rows in voice DB | one worker; queued/running/cancelling jobs are marked `interrupted` and temp files removed after backend restart; no automatic retry |
| Journal HTR | `journal_htr_service.py` in-process queue plus remote eScriptorium task polling/reconciliation | worker starts with the HTR runtime; persisted `pending` jobs are enqueued, provider models/training state are reconciled; no generic exponential retry framework |
| AI usage poller | `ai_usage.py` | daemon poller writes SQLite observations/sessions; per-provider in-memory exponential backoff, reset after success |
| Last.fm sync | `lastfm_store.py` | initial/manual sync plus fixed-interval daemon sync into SQLite; errors are recorded/logged, with no separate durable job queue |
| BM365 Sheets push | `bm365_sheets_syncer.py`, queue rows in `data/bm365.sqlite` | durable pending/failed tasks are revisited; failures use in-memory exponential backoff capped at 300 seconds |
| COLMI ring collector | `ring_collector.py` | daemon async BLE loop writes SQLite; reconnect retry grows from 5 to 300 seconds; scheduled history/live-HR sync |
| LAN scanner | `network_monitor/scanning.py`, launched by `run_network_monitor.py` | fixed-interval daemon scans persist to SQLite; scan exceptions are skipped until the next interval, no durable task queue |
| BLE scale/sensor collector | `scripts/scan_ble.py` | long-running scan sessions with fixed retry delay; append-only raw/normalized logs and atomic latest snapshots survive restart |
| Android workers | `android/steps-sync/`, `android/dashboard-companion/`, `android/how-i-feel/` | WorkManager schedules Health Connect sync and durable receipt uploads; How I Feel retries its app-private check-in queue on connection; Android handles queue persistence independently of Python workers |

The repository has several purpose-built queues and pollers, not one shared background-job framework.

## AI / ML Infrastructure

- Language analysis uses an explicitly offline Norwegian Bokmal Stanza pipeline in `language_learning/analysis/norwegian_bokmal.py` for tokenization, POS, lemmatization, and morphology. The adapter records package/model versions and a resource fingerprint, never downloads models at runtime, and records that Stanza exposes no token probability rather than inventing confidence.
- Language text generation uses the bounded Gemini adapter in `language_learning/providers/generation.py`. It is allowlisted to the configured `FREE_ONLY` model, requests JSON MIME output, validates a strict `{title, text}` object locally, retries retryable transport failures at most twice, and has a scripted fake provider for tests. Requests/candidates persist prompt versions and fingerprints, frozen knowledge/context snapshots, raw responses, provider/model/request metadata, finish reason, latency, attempt counts, and token usage metadata. The prompt context carries a response-shape declaration; the Gemini API call does not currently send a provider `responseSchema` field.
- Job Hunt factual enrichment uses the separate provider-neutral boundary under `jobhunt_backend/extraction/ai/`. Its optional Gemini adapter uses a fixed endpoint/model allowlist, sends a strict response schema, and persists bounded prompt/provider/model/attempt/usage provenance on the common ExtractionRun. Exact evidence and value support are checked locally before facts enter the existing projection/review path; a deterministic fake provider drives tests. It remains optional and disabled by default; Pack G worker AI follow-up is separately opt-in and contact fields are removed from NAV JSON before any AI request.
- Voice Journal supports local OpenAI Whisper and Faster-Whisper through `voice_journal_engines.py` and an isolated subprocess worker. It stores segment/timing/model/performance metadata and exposes health/model-cache checks.
- Synchrobook reuses locally cached Whisper/Faster-Whisper models through its isolated resumable transcription worker, then applies deterministic sentence alignment. Reading Guide schemas and validation live in `synchrobook_backend/reading_guide*.py`.
- Journal HTR integrates eScriptorium 26.04/Kraken 7 through `journal_htr_provider.py` and `docker-compose.htr.yml`. The local store preserves line geometry, predicted/corrected text, confidence, revision history, review state, dataset splits, CER/WER metrics, model versions, and training jobs.
- Finance receipt OCR uses local Tesseract in `finance_receipts.py` and Android ML Kit structured OCR from `android/dashboard-companion/`. `finance_receipt_parser.py` is deterministic post-processing, not an AI model: it preserves line/box evidence, normalization corrections, parser confidence, reconciliation, and review reasons.
- The cleaning page has an optional AI-tips action that sends a bounded visible-task payload to the configured Cloudflare `OPENAI_PROXY`; no local generation job or response history is stored.
- `ai_usage.py` observes quotas/sessions from local Codex and Antigravity services. It is telemetry infrastructure, not an LLM provider used to generate application content.
- Kermit uses `kermit_index/`, `kermit_retrieval/`, `kermit_model/`, and `kermit_grounding/` for the static grounded pipeline. `kermit_service/` exposes `/api/kermit/v1/ask` as a grounded compatibility endpoint and `/api/kermit/v1/chat` as a unified server-routed conversation endpoint through a loopback-only HTTP API; `js/kermit-chat.js` and `kermit-chat.css` provide one optional bottom-right dashboard panel. Phase 3 admits project sources into a derived index; Phase 4 returns bounded EvidencePacks; Phase 5 uses `qwen3.5:4b` as the local draft baseline; Phase 6 binds service-owned citations and composes final text. The focused Phase 8 conversation addition provides bounded memory-only history, general chat, grounded follow-ups, and clarification without runtime data adapters, page context, or actions. See `docs/kermit/PHASE7_CHAT_UI.md` and `docs/kermit/UNIFIED_CHAT_ROUTING.md`.
- Deterministic Finance insights, legacy Job Hunt scores, Pack J Track Evaluations, Pack K Skill Intelligence, Pack M analytics/adjacency, sleep analysis, workout planning, receipt grammar, and import classifiers are not described as AI. Job Hunt Pack F AI extracts advertisement facts only; it does not evaluate candidate fit. Pack J consumes validated facts through local `evaluator@1`; Pack K and Pack M derive local bounded read models from persisted facts, mappings, Profile evidence, current Evaluations, applications/events, and source metadata; legacy match scores/analysis remain separately labelled imported or manually entered compatibility data.
- No embeddings, vector database, or implemented semantic-search index was found.

## External Integrations

- Google: Calendar OAuth/sync/write controls, Tasks status, Sheets/BM365 write-through and Cinema City data, Google Cloud Text-to-Speech for language audio, and one-time Google-backed cleaning/reading import scripts.
- Spotify: OAuth, current playback, queue and player control, screensaver state; Python and alternate Node implementations.
- Weather/environment: Open-Meteo, GIOS air quality, local BLE environmental sensor.
- Sports/kitchen: TheSportsDB, ESPN, API-Football, plus Wikipedia/Commons-hosted badges where configured.
- Cinema/media: Cinema City repertoire sources, TMDB and OMDb, IMDb links, Oscar winner CSV from Hugging Face, Open Library covers.
- Festival: the official Brutal Assault lineup and first news page are checked by `brutal_assault_monitor.py` at startup and every six hours; observations never edit listening albums.
- Music metadata: Last.fm, MusicBrainz, Cover Art Archive, iTunes Search, Wikipedia/Wikidata/Commons, BBC/Wikipedia artist information, Rate Your Music saved HTML/imports.
- Language: Gemini, offline Stanza, wordfreq, Ordbokene Display API, Tatoeba imports, AnkiConnect, Google Cloud TTS, Clozemaster links.
- Job Hunt: optional backend-only Gemini factual extraction, an explicitly enabled backend-only NAV `pam-stilling-feed` integration, and independently enabled Pracuj.pl JobAlert and Jobbnorge Public API integrations. Pracuj uses verified TLS, read-only IMAP selection, UID/`PEEK` reads, and exact RFC822 preservation; no Pracuj offer pages are fetched. NAV tokens and IMAP credentials are never exposed to browser APIs. Pack J Evaluation, Pack K Skill Intelligence, and Pack M analytics/adjacency/experiments are fully local and make no network or model calls. Pack M has no live FX, tax, or cost-of-living dependency; those scenario values are explicit manual records with source/date.
- Devices: Android Health Connect, Android ML Kit receipt OCR, Bluetooth Mi Scale/environment sensor, COLMI ring BLE/phone bridge, Garmin/TCX imports.
- HTR/transcription: local eScriptorium/Kraken, OpenAI Whisper, Faster-Whisper, FFmpeg/FFprobe, PyMuPDF/Pillow where installed.
- Quote widget: Quotable, DummyJSON, and a secondary random-quotes API fallback.
- Local AI tooling: Codex app-server and Antigravity hub are polled only for usage/quota telemetry.

All integrations are optional/configuration-dependent. Environment files, OAuth tokens, API keys, local model caches, and live service availability are runtime concerns.

## Import / Parsing Patterns

- Finance CSV ingestion (`finance_importer.py`, `finance_service.py`) performs bounded decoding, header/row validation, normalization, masked accounts, keyed account matching, deterministic transaction fingerprints, staged import records, deduplication, verification, rollback, and safety backups.
- Finance receipts preserve private originals and source rows, hash content, record parser/source versions and OCR provenance, keep structured geometry/evidence, separate parsing from transaction matching, and route ambiguity through guided review/audit tables.
- Music imports (`music_importers.py`, `music_store.py`) retain content-addressed saved HTML in `data/music-imports/`, stage parsed records in SQLite, preserve source identities/snapshots, and keep legacy adapters read-only.
- Language reference builds (`language_learning/reference_core/*`) use frozen manifests, artifact checksums, parser/importer versions, source/license records, import-run counters/rejects, deterministic IDs, evidence tables, and a staging database that is atomically promoted. User data remains isolated from the rebuildable reference DB.
- Language generation freezes the knowledge snapshot/context pack and prompt fingerprint before either manual external-LLM import or automatic Gemini generation; candidates are analyzed locally before acceptance.
- Language benchmarks use fixed internal synthetic content in `language_learning/benchmark_content/v1.json`, isolated server-side answer keys, and v16 run/response tables. `#benchmarks` and profile-scoped API routes expose baseline/checkpoint history; `norway-preparation` composes existing curricula and benchmark results without a composite score.
- Habits legacy import (`scripts/build-habits.py`) preserves Loop Habit DB/CSV inputs under `data/raw/` and generates JSON/JS reports. The newer `habits_store.py` seeds once into canonical SQLite and uses revision/cursor/idempotency records for sync.
- Cleaning and Reading import scripts write to feature stores with deterministic legacy identifiers/fingerprints and backups; runtime no longer reads Google as the primary source.
- Classical Library stores uploaded RYM HTML under `data/classical-library/raw/rym/uploads/` and parses it into bounded JSON state rather than making RYM the runtime source.
- Timeline activity imports Loop Habit and How We Feel data into private source files and composes daily reports from multiple canonical feature stores without duplicating them into `data/timeline.sqlite`.
- Synchrobook preserves uploaded documents/audio, writes versioned extraction/transcription/alignment artifacts atomically, and can rebuild later pipeline stages from those artifacts.
- Job Hunt accepts standardized canonical-job JSON separately from Pack D's `ManualImportAdapter`. The adapter synchronously preserves bounded UTF-8 TXT/HTML/JSON as exact bytes, creates source-neutral Source Listings, reuses SHA-256 blobs, and retains capture history before parsing. Pack E processes captures with versioned deterministic extractors; Pack F optionally follows with validated `ai_factual@1`. Pack G upgrades only the existing stable NAV source: local Search Profiles prefilter feed entries and filter full details, NAV UUID is the source-local identity, exact changed detail bytes become `nav_api` Raw Captures, and new captures automatically run `nav_structured@1` through the existing projection/review path. The persisted worker owns feed/fetch/extraction/dedupe/evaluation work, leases, recovery, cancellation, retries, request observations, cursor/conditional state, and backoff. Pack H `dedupe@1` uses indexed URL and company/time blocking, conservative lexical evidence, and hard contradictions; only exact safe identity auto-merges, while ambiguous pairs wait for review. Merge relinks but never deletes Source Listings/evidence, keeps absorbed IDs as aliases, unions active Track assignments, audits every transition, and supports unmerge with current-evidence reprojection. Pack I adds the source-neutral `pracuj_jobalert` adapter: the worker polls a dedicated mailbox read-only, filters headers before bounded full-message reads, archives only conservatively recognized official alerts as exact RFC822, parses per-listing evidence with `pracuj_jobalert@1`, and routes it through the same Source Listing, capture, extraction, projection, and dedupe contracts. Optional subject bindings attach Search Profile discovery context. Pack J `evaluator@1` compares eligible active Canonical Jobs against Profile evidence and each Track's immutable policy, emitting categorical dimensions/findings with explicit provenance and no global score. Pack K `skill-intelligence@1` derives per-Track current or historical distinct-Job demand, mapping transparency, Profile evidence, current gap/UNKNOWN counts, strict/potential unlock sets, and categorical priority live from those durable records. Other external sources remain metadata-only/planned.

## Testing

- JavaScript uses Vitest 2 with `happy-dom`; configuration is in `vitest.config.js`, tests are `tests/**/*.test.js`, and V8 coverage writes under `reports/vitest/`.
- Python uses standard-library `unittest` modules named `tests/test_*.py`, normally runnable directly or with `python -m unittest`. Tests commonly use temporary directories/databases, fake providers/openers, and handler/service calls rather than a shared pytest configuration.
- Current coverage is broad: dashboard ordering/settings; cleaning, reading, todo, habits, events, widgets; Finance packs/imports/receipts/privacy; language analysis/reference/generation/jobs/Anki/Cloze/curricula; Music/Last.fm; Live Workout/Strength/ring/health; Synchrobook; journals/HTR/voice jobs; BM365/BA/RYM; network/sensor and Cinema City adapters.
- Job Hunt keeps `tests/jobhunt-store.test.js` for legacy compatibility/pure helpers. Packs A-L1 retain focused backend/HTTP/frontend coverage. Pack M coverage in `tests/test_jobhunt_pack_m.py`, `tests/test_jobhunt_pack_m_http.py`, and `tests/jobhunt-pack-m.test.js`, plus API/Track/UX/widget suites, verifies distinct populations/windows/denominators, salary comparability and small samples, source contribution/overlap/review burden, application attribution/funnels/timing, no-winner Track trade-offs, versioned manual scenarios, deterministic adjacency and explicit proposal decisions, durable immutable experiment completion, append-only notes, reviewed Profile updates, route/UI escaping, empty states, and bounded live-query performance.
- Use focused commands such as `npm run test:run -- tests/<feature>.test.js` and `python -m unittest tests.test_<feature>` when changing tested logic.

## Reusable Architecture Patterns

### SQLite / migrations / backups

- `finance_repository.py` is the strongest example for explicit schema versions, transactional migrations, private backups, foreign-keyed domain tables, and auditability.
- `language_learning/migrations.py` plus `LanguageStore` demonstrate append-only migration checksums, automatic safety backups, and a large typed domain isolated in one user-state DB.
- `cleaning_store.py`, `reading_store.py`, `habits_store.py`, and `timeline_store.py` are smaller patterns for feature-local SQLite and idempotent legacy import.

### Raw source preservation / import staging

- Finance receipts and CSV imports preserve source evidence privately before normalization.
- Music stores content-addressed raw HTML alongside SQLite staging/import records.
- Language reference importers record source manifests, artifact hashes, licenses, parser versions, import runs, reject counts, and atomically promote a staged DB.
- Synchrobook keeps original documents/audio separate from rebuildable extraction/transcription/alignment outputs.

### Evidence / confidence / review

- `finance_receipt_parser.py`, `finance_receipts.py`, and `finance_review.py` preserve raw evidence, confidence/reconciliation states, grouped review decisions, undo, and audit rows.
- Journal HTR stores model/version, geometry, predictions, confidence, corrections, revisions, review status, and training eligibility.
- Language token/reference models store analyzer provenance, ambiguity/resolution state, mapping evidence, model fingerprints, and explicit missing-confidence reasons.

### Durable jobs / restart recovery

- Language jobs are the clearest bounded-attempt SQLite queue with startup recovery.
- Synchrobook combines durable jobs, reusable stage artifacts, checkpointed external transcription, and manual resume/priority.
- Voice Journal is the counterexample for safety: interrupted work is explicitly marked and cleaned rather than silently replayed.
- BM365 demonstrates a durable outbound integration queue with backoff; HTR demonstrates local/remote task reconciliation.

### Structured LLM output

- Language generation is the reusable precedent: frozen context packs, prompt versions/fingerprints, bounded provider calls, JSON MIME output, strict local shape validation, provider/usage metadata, deterministic post-analysis, candidate review, and fake-provider tests.

### Frontend API client conventions

- `js/budget-api.js`, `js/reading-api.js`, `js/language/api.js`, `js/synchrobook/api.js`, and `js/voice-journal-api.js` centralize paths, request serialization, and error decoding.
- `js/file-settings.js` is the pattern for server-backed JSON settings with a `localStorage` mirror/fallback.
- `js/network-monitor-api.js` shows how to isolate an independently hosted local service and configurable base URL.

### Analytics / snapshots

- `timeline_activity.py` composes multi-source daily reporting without making the timeline DB own copied source facts.
- `finance_analytics.py`, `music_store.py` ranking snapshots, and `lastfm_store.py` derived summaries keep analytics close to canonical stores.
- `jobhunt_backend/skill_intelligence.py` is a bounded versioned live read model over canonical Job Hunt records; it publishes populations, denominators, coverage, fingerprints, and rules rather than persisting a second source of truth.
- `jobhunt_backend/analytics.py` owns Pack M market/source/application/Track/trade-off metric contracts. `jobhunt_backend/career_intelligence.py` owns deterministic adjacent-role hypotheses and bounded experiment templates. Neither persists rebuildable metrics; migration 13 persists only attribution, user scenarios, proposal decisions, and experiment evidence/events.
- `scripts/export_antigravity_context.py` is the precedent for schema-versioned, privacy-filtered, generated cross-feature snapshots.

## Fragile Areas

- `server.py` (~780 KB) mixes routing, static-file privacy, integrations, caches, SSE, and startup lifecycle. Use route-prefix searches and narrow reads; edits in shared request/auth/static helpers can affect unrelated domains.
- `styles.css` (~846 KB) and `index.html` (~140 KB) are global and ID-sensitive. Widget layout also depends on loader/order/settings/visibility code and two dashboard JSON files.
- `js/widget-weight-cut.js`, `js/widget-live-workout.js`, `js/widget-diet.js`, `js/widget-events.js`, `js/widget-reading.js`, `js/widget-network.js`, and `js/finance-page.js` are large stateful UI modules.
- `finance_receipts.py`, `journal_htr_service.py`, `music_store.py`, `language_learning/store.py`, and the Language reference database/builders are large, migration/evidence-sensitive areas.
- Multiple services share lifecycle assumptions: central API port `8000`, network monitor `8765`, Vite proxying, BLE collector files, optional HTR containers, and Android LAN callbacks.
- `films.html`, `oscars.html`, `bm365.html`, and `oddychaj.html` are current pages but are not explicit Vite Rollup inputs; verify build behavior before changing page registration.
- Browser-only stores (blood pressure, breathwork, and several view preferences) can be lost with browser storage. Job Hunt is durable in SQLite after verified cutover; its old localStorage offers/settings remain recovery material rather than a synchronized writable store.
- `data/` mixes canonical databases, private originals, caches, generated files, backups, and migration inputs. Never bulk-edit or expose it; Finance private paths have explicit deny rules that must remain aligned in `server.py` and `vite.config.js`.
- `watchlist.sqlite`, ignored SQLite DBs, WAL/SHM files, raw imports, OAuth state, model caches, logs, covers/posters, and `antigravity-context` snapshots should not be hand-edited.
- Many UI modules render imported/user text with `innerHTML`; preserve escaping at trust boundaries.

## Rules For Future Codex Changes

- Read `AGENTS.md` and this map first. Then inspect the page/widget entry, its API client/store, the relevant route prefix/service, and nearby tests before touching global files.
- Follow `docs/GIT-WORKFLOW.md`: protected `main`, integration `dev`, and `ai/<agent>/<task>` task branches. `scripts/save.ps1` creates numbered build tags and `CHANGELOG-AUTO.md`; `scripts/restore.ps1` creates a recovery branch without resetting history. Worktree helpers share a repository-wide lock. Do not modify Git helpers or historical `save-*` / `auto-*` / `build-*` tags without explicit permission.
- Preserve HTML IDs, `data-widget` keys, localStorage keys, API paths, JSON shapes, database filenames, and migration history unless the task explicitly changes a contract.
- Treat storage roles precisely: canonical SQLite/JSON is not interchangeable with caches, generated snapshots, raw archives, backups, or migration-only inputs.
- Keep edits surgical. Do not use a widget task to refactor `server.py`, `styles.css`, or unrelated modules.
- For a new/changed widget, update `index.html`, `js/dashboard-widget-loader.js`, order/visibility/settings defaults, and focused tests together.
- For API changes, keep frontend clients and backend routes in sync; protect private paths and use feature-store transactions/atomic file writes.
- Reuse existing precedents instead of inventing another framework: feature-local SQLite/migrations, preserved raw sources, evidence/review records, durable jobs with explicit recovery, bounded API adapters, and centralized frontend clients.
- Avoid `node_modules/`, `dist/`, `reports/`, `server.log`, `.tmp-*`, `covers/`, posters, raw DB contents, caches, and large snapshots unless the task directly requires them.
- Run focused Vitest or Python `unittest` suites for changed logic. For UI work, verify compact-card overflow and dashboard order/visibility behavior.
- Update this map when adding/removing a major page, active `data-widget`, API domain, canonical store, worker, external provider, or AI/ML subsystem.
