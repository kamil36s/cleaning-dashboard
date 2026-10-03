# Diet

## Identity and verification

- Stable ID: `diet`; current `data-widget="diet"` flow, reviewed 2026-10-01 on dirty `main`. L0: `PROJECT_MAP.md` Diet widget/API/storage rows.
- Kermit explains contracts only. It has no meal-history, calorie, weight or step runtime reader.

## Purpose and boundaries

Diet owns meal entries, daily calorie goals, saved estimates and ignore-day choices in `data/diet/diet.json`. Weight and steps remain owned by their telemetry subsystems and are read only as context for an optional estimate. `js/widget-diet.js` also derives suggestions from historical meals for display; a suggestion is not a newly stored meal. The app records kcal per meal, not a verified nutrient/macro breakdown; no macro totals are established by these routes.

## Frontend, API and flow

| Surface or route | Owner and behavior |
| --- | --- |
| `index.html` `data-widget="diet"` | `js/widget-diet.js` loads `/api/diet/days` and `/history`, draws daily/period charts, offers meal entry, estimate/ignore actions, suggestions and daily reports. Browser `todayIso()` is local. |
| GET `/api/diet/days`, `/history` | `server.py::read_diet_days` returns actual stored days normalized; `read_diet_history` returns a requested calendar range through server-local today, including missing days. |
| POST `/api/diet/meals/upsert`, `/delete` | `upsert_diet_meal` and `delete_diet_meal` write normalized meal ID/name/kcal in canonical JSON. Adding a meal clears estimate and ignore state for that day. |
| POST `/api/diet/estimates/upsert`, `/delete`; `/api/diet/days/ignore` | Server saves/removes provided estimates or marks days ignored. Existing manual meal days or ignored days are skipped by estimate upsert; manual meal days are skipped by ignore. |
| TXT daily/combined report | `js/daily-report.js` reads diet, weight and steps routes and labels estimates separately from manual meals. Downloaded reports are generated presentation output. |

Server `normalize_diet_day` validates ISO dates; `normalize_diet_kcal` rounds numeric kcal to integer and floors at zero. `normalize_diet_meal` limits IDs to 80 characters and lowercase normalized names to 180. `read_diet_store` falls back to empty/default goal on missing, invalid or unreadable JSON; this is a degraded read, not evidence that a user's history never existed. Writes use `rewrite_json_file` replacement; API errors surface as HTTP 400/500. No durable background estimate job exists.

## Persistence and calculations

| State | Authority and rule |
| --- | --- |
| `data/diet/diet.json` `goal_kcal`, `days[ISO day].meals` | **Canonical diet state**. Each meal has ID, name and integer kcal. The default goal is 2200 kcal; a per-day goal can override it. Meal upsert replaces the same ID or appends. |
| `days[day].estimated_kcal`, source/confidence/reason/components/time | **Persisted estimate**, explicitly labelled `estimated`; it is not a measured or manually logged meal. Components can include baseline calories, weight and step adjustments, trend and known step days. |
| `days[day].calories_source="ignored"`, `ignored_at` | **Canonical ignore-day decision**, separate from zero intake; manual meals take precedence. |
| `total_kcal`, `remaining_kcal`, history rows | **Derived read model** from `normalize_diet_day_row`: manual total = sum meal kcal; if no meals, positive estimate may supply total; ignored/missing return zero with explicit source label. Remaining = goal − selected total. `filled` on history is true for every nonmanual day. |
| Meal autocomplete and top-up combinations | **Suggestions** computed by `buildMealSuggestions`/`buildCalorieTopUpSuggestions` from existing logged meals. Name normalization, frequency and recency rank autocomplete; top-up combinations score closeness to remaining calories, frequency, recency and time-of-day. They are not written until the user explicitly saves a meal. |

`js/diet-estimation.js::estimateMissingCalories` groups consecutive missing days before today, excluding manual/ignored days. For each block it chooses median manually logged kcal in the preceding 14 days if at least five rows, else 30 days, else goal/default. It optionally adds `clamp(2000 × (observed weight after − expected weight), -1500, 5000)` and `clamp((known steps − baseline steps × block days) × 0.045, -800, 1200)`. It divides the block total by days, clamps each estimate to 800–6000 kcal and rounds. Step context is usable only with a baseline from at least five positive days and known steps for at least half the block. Confidence is high/medium/low from block length and available context, not medical validity. Missing context contributes no adjustment; missing steps are `null`, never known zero (`tests/diet-estimation.test.js`). The widget explicitly POSTs generated estimates; only then do they become persisted **estimates**, never meal facts.

`js/widget-diet.js` computes local top-up suggestions using local browser hour and historical meal patterns. The local date used for selected day and suggestions can differ from `server.py::read_diet_history`'s server-local end day. `js/diet-estimation.js` uses local noon for day arithmetic but defaults `today` via UTC ISO if the caller omits it; the widget passes browser-local `todayIso()`. Report dates use browser-local today; server returns requested ISO date rows. No shared universal timezone is established.

## Dependencies, failure, privacy and evidence

The estimate fetches `/api/weight/history` and `/api/steps/history`; a failure rejects the generation action and does not create an estimate. Missing weight/step values reduce context and confidence, rather than becoming observed zero. Existing meal/ignore state blocks estimate overwrite. Diet does not own step history or scale measurements. `data/diet/diet.json`, runtime backups, downloaded personal reports and any actual meal values are **excluded** from Kermit admission. `js/widget-diet.js` and `js/diet-estimation.js` have reviewed contracts but hardcode calorie target/baseline values, so they and their calorie/meal test fixtures are not admitted. The shared `server.py` and safe `js/daily-report.js` metadata remain admitted.

Focused evidence: `tests/diet-estimation.test.js`, `tests/widget-diet-suggestions.test.js`. There is no dedicated Diet backend route test in the reviewed focused set; record D4-01 in `GAPS_AND_CONFLICTS.md`.

## Checked implementation references

| Admitted source | Checked marker |
| --- | --- |
| `server.py` | `def normalize_diet_day_row` |
| `js/daily-report.js` | `export async function generateDietDailyReport` |
