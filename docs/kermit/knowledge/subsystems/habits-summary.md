# Legacy Habits summary

## Identity and verification

- Stable ID: `habits-summary`; active `index.html::data-widget="habits"`; reviewed 2026-09-30 on dirty `main` against `js/habits.js`, `js/habits-app-model.js`, loader, generated-view builder and tests.
- Purpose: display daily counts, categories and sobriety achievement. It is a **presentation view**, not a database.

## Ownership and data precedence

`js/habits.js` fetches `./data/habits.json` (the generated `public/data/habits.json` static view). If `window.HABITS_APP_LIVE_DATA.habits` is present, it renders `summarizeHabitsForDashboard` from the current modern snapshot plus `habits.app.preview-mutations.v1`; a `habits-app:data-updated` event refreshes that live view. It also listens for browser storage changes to preview mutations. If there is no live snapshot, it uses generated JSON. A successful generated fetch does not override an available live view; if generated fetch fails, a live view can still render. Both views can therefore have different freshness and calculation paths.

The summary's sobriety display first uses modern live habits or the legacy `window.HABIT_DB` and preview mutations through `js/sobriety-streak.js`; only when that is unavailable does it use generated JSON `sobrietyDays` and a named legacy habit. This is an additional precedence path, not proof that every displayed value came from `habits.sqlite`. A missing source can show an error or unavailable achievement. The card is hidden in shipped widget defaults, but its loader may still import it for the sobriety achievement.

## Persistence and calculations

`public/data/habits.json` is a **generated legacy view** assembled from old Loop Habit material by the export flow; `data/habit-data.json`, `js/habit-data.js` and original DB/CSV are **legacy migration input / generated exports**, not current Habits App authority. `scripts/build-habits.py` rebuilds the latter pair and reports, not the canonical SQLite store. Browser preview mutations are **pending sync metadata**, not persisted completion. `summarizeHabitsForDashboard` excludes archived modern habits, counts completed entries using binary >0 or numeric >0 and >= target, and treats missing today as incomplete for display; it does not create a missed entry. Generated JSON supplies its own precomputed `stats`/habit fields and generation timestamp. Do not equate these metric implementations or assume generated totals are current.

The modern model's `dateKey` uses browser-local calendar dates for timestamps and fixed calendar keys as given. The legacy builder defaults CSV dates to Europe/Warsaw; legacy point conversion and generated summary may use other assumptions. This unit has no single authoritative day-boundary rule across fallback and live paths.

## API, security and recovery

The summary has no write API of its own. It reads a static generated file and in-memory event/preview state. A generated file can be rebuilt from its original private imports; pending browser edits must be synchronized with `HabitsStore` to become canonical. Kermit cannot load the generated JSON or the browser's live state. Static fetch failure or missing modern snapshot can degrade the card; rebuilding old files is not a repair for current SQLite state.

`js/habits.js` and `js/habits-app-model.js` embed named medication/routine examples, so they were reviewed but **not admitted**. Private `public/data/habits.json`, `data/habit-data.json`, `js/habit-data.js`, raw Loop Habit exports and reports are excluded. `index.html` and the shared loader identify the active surface; the reviewed pack carries its ownership contract. Focused checks: `tests/habits-app-model.test.js`, `tests/widget-habits-app.test.js`. There is no dedicated complete legacy summary test; see gap register.

## Checked implementation references

| Admitted source | Checked marker |
| --- | --- |
| `index.html` | `data-widget="habits"` |
| `js/dashboard-widget-loader.js` | `habits: () => import` |
