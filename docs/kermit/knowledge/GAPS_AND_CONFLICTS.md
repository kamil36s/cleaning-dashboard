# L1 pilot gaps and conflicts

Status: source-review register, 2026-09-24. Findings describe the working tree, not private runtime state. Allowed type vocabulary follows the Phase 2 request. A **No** in the final column means future Phase 3 metadata can retain the uncertainty/conflict with provenance; it does not approve Phase 3 implementation.

## Q-01

- **Subsystem:** Quote
- **Type:** missing test coverage
- **Description:** No focused test of the active provider order, title-case rejection, retry bounds, fallback selection, concurrent refresh guard, or `quote:ready` timing was found.
- **Evidence:** `js/widget-quote.js::PROVIDERS,isTitleCaseQuote,loadQuote`; `tests/dashboard-settings.test.js` covers generic widget settings; no `tests/*quote*.test.js` in source inventory.
- **Impact on future Kermit answers:** L1 can describe the code, but tests do not establish regression protection for external failures or layout timing.
- **Recommended investigation:** Add a focused fake-fetch/DOM test when this widget is next changed; verify provider failure and all-local-fallback cases.
- **Blocks Phase 3?** No

## W-01

- **Subsystem:** Weather
- **Type:** missing test coverage
- **Description:** No focused test of Open-Meteo response fallback, hourly cutoff, null/malformed response behavior, interval/error state, Celsius/chart transformation, or icon preference was found.
- **Evidence:** `js/api/openMeteo.js::fetchWeather`; `js/main_weather.js::loadWeather`; `js/ui/render_weather_api.js::renderNow,renderNext`; `tests/dashboard-settings.test.js` covers settings only.
- **Impact on future Kermit answers:** Precise forecast boundary and degraded behavior are source-verified but not protected by feature tests.
- **Recommended investigation:** Add adapter tests with fixed timestamps around midnight/DST and missing fields, plus focused render/error tests when weather code next changes.
- **Blocks Phase 3?** No

## W-02

- **Subsystem:** Weather
- **Type:** unclear calculation
- **Description:** Renderer converts several response values with `Number(value)`; an explicit provider `null` converts to 0, while `undefined` becomes nonfinite and displays as unknown. Temperature and hourly charts can therefore show a zero for a missing/null provider value.
- **Evidence:** `js/ui/render_weather_api.js::renderNow,renderNext`; `js/api/openMeteo.js::fetchWeather` (**verified implementation**).
- **Impact on future Kermit answers:** A zero on the weather card cannot be assumed to be an observed zero if the provider returned null; Kermit should state this limitation when explaining missing data.
- **Recommended investigation:** Add a fixed-response test for null current/hourly fields and decide whether validation should preserve null as unknown in a later weather change.
- **Blocks Phase 3?** No

## F-01

- **Subsystem:** Finance / Budget
- **Type:** code/documentation discrepancy
- **Description:** `PROJECT_MAP.md` says Finance CSV imports preserve source evidence privately before normalization. The active `/api/budget/import-csv` path decodes request bytes and `FinanceService.import_csv` persists parsed transaction/import-batch/link provenance, but the reviewed active path does not write the exact original CSV bytes to `data/finance-imports/` or another source archive. The static deny rules mention that path, while receipt originals have a separate preservation path. The two claims must remain distinct.
- **Evidence:** Documentation: `PROJECT_MAP.md::Reusable Architecture Patterns / Raw source preservation` (**documented current contract**). Implementation: `server.py::import_budget_csv_from_payload`, `finance_service.py::FinanceService.import_csv`, `finance_repository.py::create_batch,associate_import` (**verified implementation**); static deny: `server.py`, `vite.config.js::FINANCE_PRIVATE_PATH`.
- **Impact on future Kermit answers:** Kermit must not claim a recoverable byte-exact CSV archive exists for an import solely because parsed provenance or a denied directory exists.
- **Recommended investigation:** Decide and document whether exact CSV retention is intended; inspect only code/tests for any other active import entry point before revising L0. Do not inspect private CSV files for this documentation task.
- **Blocks Phase 3?** No

## F-02

- **Subsystem:** Finance / Budget
- **Type:** unclear calculation
- **Description:** Date defaults are not globally uniform: `FinancePeriodService._parse_date` falls back to current UTC date; several `FinancePlanningService` methods use `date.today()` when no reference is supplied. Near local/UTC midnight, independently requested period analytics and planning projections may use different calendar days.
- **Evidence:** `finance_analytics.py::_parse_date,FinancePeriodService.resolve`; `finance_planning.py::FinancePlanningService.safe_to_spend,report,overview` (**verified implementation**).
- **Impact on future Kermit answers:** A statement that every Finance metric uses one default day or one timezone would be false; date-sensitive explanations should name the owner and `referenceDate` when available.
- **Recommended investigation:** Decide an explicit shared date contract and add a boundary test if changing calculations; until then, cite each method's date semantics.
- **Blocks Phase 3?** No

## F-03

- **Subsystem:** Finance / Budget
- **Type:** unclear calculation
- **Description:** Two Finance freshness labels use different age thresholds and names. Planning overview is `fresh` through day 3, `aging` through day 14, then `stale`; period analytics freshness is `current` through day 1, then `stale`. Both are current code, scoped to separate responses.
- **Evidence:** `finance_planning.py::FinancePlanningService._freshness,overview`; `finance_analytics.py::FinancePeriodService.freshness,resolve` (**verified implementation**).
- **Impact on future Kermit answers:** A generic "Finance data is stale after N days" answer would hide which screen/response supplies the status.
- **Recommended investigation:** Name the statuses per endpoint in UI/docs and test both boundary sets if unified semantics are desired.
- **Blocks Phase 3?** No

## F-04

- **Subsystem:** Finance / Budget
- **Type:** unclear calculation
- **Description:** `GET /api/budget/analytics/categories` uses eligible receipt item splits to replace one transaction category amount, while `FinancePlanningService.report` top categories aggregate transaction category IDs without receipt splits. Both are current calculations and may show different category allocations for the same month.
- **Evidence:** `finance_service.py::FinanceService.analytics_payload("categories")`; `finance_receipts.py::FinanceReceiptService.analytics_category_breakdown`; `finance_planning.py::FinancePlanningService.report` (**verified implementation**).
- **Impact on future Kermit answers:** A category total must be attributed to its endpoint and rule; an answer cannot treat report top categories and analytics category breakdown as the same series.
- **Recommended investigation:** Decide whether the two screens intentionally use different allocation rules; label that difference in UI/docs and add a cross-endpoint test if it is contractual.
- **Blocks Phase 3?** No

## L-01

- **Subsystem:** Language Learning
- **Type:** stale documentation
- **Description:** L0 says the Gemini call does not send a provider `responseSchema` field. Current code indeed does not use that literal key, but it does send `generationConfig.responseJsonSchema` with required string `title` and `text` fields, as well as JSON MIME type. The frozen context-pack `responseSchema` declaration is an additional, separate field. L0 wording is stale for answering whether any provider schema is sent.
- **Evidence:** Documentation: `PROJECT_MAP.md::AI/ML and Model Boundaries` (**documented current contract**). Implementation: `language_learning/providers/generation.py::GeminiGenerationProvider._request_once`; `language_learning/generation.py::GenerationService` context construction (**verified implementation**); `tests/test_language_generation_provider.py::test_fixed_endpoint_structured_payload_and_redacted_health`.
- **Impact on future Kermit answers:** Kermit should report the discrepancy and describe current provider request shape from code, without suggesting schema validation depends only on prompt text.
- **Recommended investigation:** Refresh L0 wording during its next inventory update to name the exact `responseJsonSchema` key and retain the distinction between provider schema, prompt context declaration, and local validation.
- **Blocks Phase 3?** No

No unresolved ownership or storage-role finding was identified for the scoped Quote, Weather, and Language flows. This register is not a claim of exhaustive repository coverage.

## Phase 8 B1 review notes (not additional two-sided indexed findings)

- **C-01 — scoped day-boundary semantics, Cleaning:** `cleaning_store.py::CleaningStore.get_history` uses Warsaw midnight boundaries; `count_actions_for_day` defaults to a 06:00 Warsaw rollover for the phone-cleaning goal; `get_state.doneToday` starts at Warsaw midnight but ends 24 elapsed UTC hours later, so DST-transition days can include or omit one local hour. These are verified code rules. Kermit must name the metric/consumer rather than assert one universal Cleaning day boundary. See `docs/kermit/knowledge/subsystems/cleaning.md`.
- **R-01 — unverified external fee policy, Reading:** `js/widget-reading.js` has a local overdue-fee display constant. No reviewed source proves that this estimate matches the actual lender's policy. Kermit may explain the UI calculation as an estimate, not a real owed charge. Concurrent multi-browser history/settings conflict resolution was not established by the reviewed source. See `docs/kermit/knowledge/subsystems/reading.md`.
- **T-01 — best-effort persistence, Todo:** `js/file-settings.js::saveFileBackedSetting` writes localStorage first and suppresses asynchronous server-save errors. `data/settings/todo.json` is the canonical file when the API is available, but a failed POST can leave a local mirror ahead of it. No durable retry or user-visible write confirmation is established. See `docs/kermit/knowledge/subsystems/todo.md`.
- **MAP-01 — resolved inventory drift (2026-09-30):** `PROJECT_MAP.md` now lists the registered `feelings` card and `/api/phone-tracker`, `/api/mental-health`, `/api/feelings`, `/api/football`, and `/api/dashboard` prefixes. B2 recounted 34 direct registered widget keys and 43 implementation route domains. These inventory corrections do not validate those feature packs or admit private records.

## Phase 8 B2 review notes (not additional two-sided indexed findings)

- **D-01 — registration versus execution:** All 34 direct `data-widget` keys have loader registrations, but 13 are hidden in shipped defaults and unregistered `widget-*.js` files are inactive. Persisted visibility can change which registered modules execute; a static file list cannot establish user-visible state.
- **S-01 — asynchronous settings divergence:** `js/dashboard-settings.js` and `js/file-settings.js` maintain localStorage mirrors and issue best-effort asynchronous server POSTs. A failed POST can leave local state ahead of the canonical JSON file; `js/network-notification-settings.js` is browser-only. No universal SQLite or localStorage canonical rule applies.
- **A-01 — route-specific security:** `server.py::authorize_api_request` has local-client and authenticated companion exceptions in addition to Origin/Referer/Host checks. Static private path denial and API authorization are separate controls; do not generalize one route's body limit or token rule to all domains. Kermit does not receive application write tools.
- **A-02 — collector source excluded:** `scripts/scan_ble.py` contains fixed local device MAC addresses. B2 documents the collector's separate lifecycle via `PROJECT_MAP.md` and does not admit the collector source to Kermit's static index.

These notes are source-review limitations. The Phase 3 `conflicts.jsonl` still carries the original eight reviewed pilot findings and their explicit side metadata. B1 grounding tests exercise the new limitations as supported/unsupported claims without pretending that a note has independently reviewed opposing factual sides. Promote a note to a machine-indexed finding only after side classification and bounded source spans are reviewed.

## Phase 8 B3 review notes (not additional two-sided indexed findings)

- **H-01 — mixed modern/legacy ownership:** `data/habits.sqlite` is canonical for modern Habits App; the `habits` summary can display a modern live/preview model or generated `public/data/habits.json`, and `habits-timeline`/Timeline activity consume legacy `habit-data` exports. These paths are not automatically synchronized. The generated fallback can be stale; `js/habits.js` has no dedicated full behavior regression. Rebuild generated files only from retained original imports, never from guesses about current SQLite state.
- **H-02 — scoped day boundaries:** Browser habit dates and reminder due times use the browser's local calendar, supplement default snapshot day uses server-local `date.today()`, the legacy builder defaults CSV dates to Europe/Warsaw, and the HabitsStore one-time seed maps timestamps to UTC dates. A cross-timezone or midnight comparison can differ. No single global Habits day rule is established; add boundary tests if reconciliation is changed.
- **H-03 — claim versus outcome:** Browser reminder execution claims a due occurrence before trying to display a notification, with a five-minute ordinary grace; a closed browser has no durable worker and an accepted claim is not proof of display or habit completion. Supplement slot claims are day/slot deduplication, separate from regimen state and intake check-ins. Do not infer adherence from notification state.
- **H-04 — self-care dual write and deduplication:** `js/widget-self-care.js` writes task completion through the shared external Google Apps Script task endpoint and best-effort activity through Timeline. Timeline failures may leave completed tasks without captured activity until a later history sync; its date/title hash coalesces same-title events on one day. Self-care task state is neither Habits App state nor Timeline JSONL alone. A focused widget regression is missing.
- **H-05 — static admission limit:** Several active Habits source modules embed private medication/product literals, and the generated timeline JS contains personal point history. These were reviewed only for contract boundaries and excluded from Kermit's positive manifest. The admitted safe schedule, builder, uploader, Timeline and Self-care sources participate in fingerprint drift checks; changes to excluded implementation files require manual review of these packs.
- **H-06 — running service can lag a knowledge/routing update:** The compatibility status uses the unified chat API build/capability, not a fingerprint of Kermit's routing code or newly admitted B3 knowledge. During B3 review the existing listener still passed `probeKermit` as healthy while its live `/chat` treated the Habits App/Timeline comparison as ungrounded; the newly loaded code answered it with B3 evidence. A deliberate verified restart is needed to bring that listener up to date. Do not stop an unverified process or bypass the existing ownership checks.

## Phase 8 B4A review notes (not additional two-sided indexed findings)

- **W4-01 — scoped day boundaries:** The BLE collector stamps server-local naive timestamps and weight history slices their first ten characters. Browser weight/step `today` uses browser-local dates. Steps ingest uses submitted ISO days, Android Health Connect uses device-local `LocalDate`, and Live Workout exclusions use configured `DASHBOARD_TIMEZONE`/`TZ` (default Warsaw). Server history defaults use server-local `date.today()`. Cross-zone midnight can put related observations on different days; no universal conversion is established.
- **W4-02 — source precedence and duplicate limits:** Scale JSONL is normalized history, CSV is a fallback/parallel history, raw advertisements are evidence, and latest/signal are replaceable caches. Step manual and automatic candidates are alternatives selected by `normal_mode`, while virtual walks are additive. Automatic updates with active workouts or uncovered exclusion intervals are ignored. `tests/test_server_startup.py::StepsSourceAggregationTests` covers those step transitions with temporary files. Event dedupe uses timestamp, rounded weight, type and raw hex; it cannot prove two differently encoded packets are one event.
- **W4-03 — null/zero and freshness:** `/api/steps/history` emits `steps=0, filled=true` for missing days, so consumers must retain `filled`; `/api/weight/history?fill=1` can interpolate or carry nearby weights with `count=0`. A cached scale or Health Connect latest snapshot is not guaranteed current. Weight server moving averages use observed daily points, whereas browser MA7 interpolates all internal missing days before its seven-day window; they answer different questions.
- **D4-01 — estimated versus observed diet state:** Diet saves generated calorie estimates only after explicit POST; an estimate, ignored day, top-up suggestion, and logged meal have different status. Missing weight/step context reduces estimate confidence or omits an adjustment; it is not observed zero. Browser local today and server local history end may differ. The reviewed focused set has deterministic estimation/suggestion tests but no dedicated backend route regression for estimate/ignore precedence.
- **S4-01 — captured day versus sleep night:** Server Health Connect history picks one richest snapshot per uploaded device day; browser Sleep groups by Warsaw wake-night and picks a watch/ring candidate per night. These can disagree across midnight, DST or device zones. The richest-snapshot ranking can favor a longer valid session over a more recent partial upload; last receipt time alone is not completeness.
- **S4-02 — incomplete nights and cache freshness:** A trusted device window can yield duration with null RHR when heart samples are absent; the ring can supply heart rate for the same watch-owned night. Missing nights are not zero sleep. The page warns after 48 hours since Health Connect receipt, but `latest.json` itself has no freshness guarantee. Sleep analysis is computed in the browser and is not persisted by Sleep.

These are scoped implementation findings, not invented opposing-source conflicts. The B4A collector dependency was reviewed without admitting its source, which contains device addresses. B4B review notes follow.

## Phase 8 B4B review notes (not additional two-sided indexed findings)

- **MH4-01 — UTC schedule versus local display:** `mental_health_store.py::calculate_schedule_status` compares UTC calendar dates and adds elapsed-day cadences to stored UTC completion instants. `js/mental-health-page.js` accepts `datetime-local` and displays browser-local dates. `analytics` joins assessments/check-ins by UTC date string. Around midnight or DST a displayed local day may differ from the schedule/analytics day. Retest warnings are elapsed-time warnings, not a save prohibition.
- **MH4-02 — versioned history versus import recomputation:** `create_assessment` stores instrument/scoring versions and a definition snapshot. `import_data` recreates assessments through the current registry/scoring path and skips duplicate IDs; it does not directly restore old computed scores or definition snapshots. A later pack change may therefore change imported derived values. Authorised language packs are validated and invalid packs remain external-score. Questionnaire JSON item wording is not admitted to the static index.
- **MH4-03 — route regression limit:** The reviewed focused set tests store/registry scoring and the browser API/page/widget, but has no dedicated synthetic HTTP regression for every `/api/mental-health/*` dispatch branch, import failure, or delete authorization outcome. The L1 route descriptions are source-verified; the listed test coverage is narrower.
- **SE4-01 — latest/history and freshness:** `data/sensor/latest.json` is replaced per accepted reading while `readings.jsonl` appends at most once per minute. The page can merge an as-yet-unappended latest point into a chart. A fresh HTTP response does not establish a fresh measurement; the UI's 150-second state is a timestamp-age presentation rule. Missing or unreadable history returns `[]`, not a recorded zero.
- **SE4-02 — scoped local time and partial test coverage:** The collector writes server-local naive ISO timestamps; server history filters in server-local naive time, while browser controls use browser-local day/month boundaries. There is no explicit cross-zone/DST reconciliation. Focused tests cover API windows and browser chart normalization, but not cross-host timezones or real BLE availability.
- **BC4-01 — collector privacy and retry limit:** `scripts/scan_ble.py` still embeds fixed local MAC addresses and a local sensor identifier and remains excluded. Its 65-second session/five-second retry loop handles scanner failures but does not itself restart a terminated process or prove hardware reconnection. Synthetic tests cover parsing and writes, not adapter recovery.

These notes are scoped implementation limits; no opposing authoritative source pair was established. B5 remains NOT_STARTED.
