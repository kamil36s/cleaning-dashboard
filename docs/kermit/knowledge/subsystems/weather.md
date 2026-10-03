# Weather dashboard widget

## Identity and verification

- ID: `weather`; display: Weather; domain: dashboard weather.
- Status: current browser integration. Reviewed 2026-09-24 at HEAD `294c1925f387` plus dirty working-tree source. L0: `PROJECT_MAP.md` Widgets / External Integrations.
- Claims below are **verified implementation** unless marked otherwise.

## Purpose and boundaries

Shows present conditions and an hourly forecast for configured coordinates. The browser owns provider requests, transformation, rendering, refresh, and icon preference. The central Python backend owns **none** of this Open-Meteo flow. AQI and sensor widgets are separate subsystems.

## Frontend

| Surface | Entry/identifier | Loading, empty, error, review |
| --- | --- | --- |
| Dashboard | `index.html::data-widget="weather"`, `#now`, `#next`, `#wx-temp`, `#wx-icon`, `#wx-cond`, `#wx-updated` | Priority-loaded by `js/dashboard-widget-loader.js::widgetLoaders.weather`; settings control visibility. |
| Controller | `js/main_weather.js::loadWeather` | Checks mounts and `busy`; sets loading status; on success renders and timestamps; on error shows translated error text, leaving earlier displayed conditions in place. |
| View | `js/ui/render_weather_api.js::renderNow,renderNext` | Empty hourly array produces an em dash; undefined/nonfinite values usually do too, while explicit `null` may coerce to zero (W-02). Icon click cycles style. No review state. |

No weather form or application mutation action. Icon style click mutates only browser preference `wx-icon-style`. Chart arrows, hover/focus auto scroll, and drag are browser UI actions; `renderNext` disposes prior scroll listeners/timer before rebuilding.

## Backend and API

Application backend route/service/repository: **None**. `js/api/openMeteo.js::fetchWeather` sends browser GET to `https://api.open-meteo.com/v1/forecast` with current and hourly fields, configured latitude/longitude, `current_weather=true`, and `Europe/Warsaw` timezone. `js/config.js::COORDS` uses `VITE_WEATHER_LATITUDE` / `VITE_WEATHER_LONGITUDE` or Kraków defaults 50.0614 / 19.9366. These are public configuration coordinates, not credentials.

## Persistence and source of truth

Canonical dashboard state, server cache, generated state, raw archive, backup, migration input, and legacy state: **None**. Open-Meteo is the external source for forecast values; the browser holds the latest response in rendered DOM only. `fetchWeather` uses `cache: 'no-store'`. Browser-only `localStorage["wx-icon-style"]` stores visual icon style; it is not weather data.

## Data flow

1. `ready` runs `loadWeather` after DOM readiness. If `#now` and `#next` are present, it schedules another read every `REFRESH_MS=300000` ms. Concurrent reads are skipped.
2. The adapter checks HTTP status, parses JSON, chooses current time from `current.time`, then `current_weather.time`, then first hourly time. `floorHourIndex` selects the last hourly timestamp no later than current time, defaulting to index 0.
3. Present values prefer `current`; selected fields fall back to `current_weather` or same-index hourly values. Hourly output starts at the chosen index and ends at 06:00 on the day after current time (local `Date` operations), including points at the boundary. The adapter does not perform schema validation beyond accessed fields.
4. `renderNow` maps condition code to Polish label/icon, rounds Celsius to whole degrees, displays wind/gust in km/h, precipitation to one decimal mm/h, humidity/cloud as rounded percentages, and colors temperature via `js/temp-scale.js::tempColor`. `renderNext` draws temperature, precipitation, and wind trend SVGs; chart min/max use finite converted values. Several conversions use `Number(value)`, so explicit `null` becomes zero rather than unknown (W-02).
5. Success status includes provider time and measured load duration. A thrown fetch, JSON, or transformation/render error updates status; no alternate weather provider or offline data fallback is implemented.

## Metrics and calculations

| Value | Input/window | Rule, units, unknown handling | Evidence |
| --- | --- | --- | --- |
| Current temperature / accent | `now.temp` | `Number` then `Math.round` Celsius; `tempColor` interpolates configured stops, clamping beyond endpoints; nonfinite -> em dash/transparent, explicit null -> zero | `renderNow`, `temp-scale.js::tempColor`; W-02 |
| Wind label | `now.wind`, `now.gust` | `windLabel` picks first Beaufort-style configured max threshold in km/h | `render_weather_api.js::BFT,windLabel` |
| Hourly chart ranges | `nextHours` through next-day 06:00 | `buildMetricChart` uses finite min/max; precipitation/wind rounded labels deduplicate runs | `openMeteo.js::fetchWeather`, `render_weather_api.js::buildMetricChart` |

No metric result is persisted; no focused weather calculation tests were found.

## Jobs, integrations, dependencies, failure and recovery

The periodic browser interval is a page-lifetime refresh timer, not a durable job. Queue, retries, backoff, cancellation, concurrency across tabs, and startup recovery: **None**; a reload starts a fresh request. Integration direction is browser -> Open-Meteo; no credential boundary. Rate limiting: **Unknown/provider controlled**; code has no 429 handling. If required mounts are absent, nothing loads or schedules. Existing rendered values may remain when a later refresh fails, with an error status; there is no stale age badge.

## Privacy and security

Only configured coordinates and normal browser request metadata go to Open-Meteo. There is no browser-to-Python weather call. `wx-icon-style` is a local visual preference. No private runtime source was read.

## Tests and evidence

- Focused Open-Meteo adapter/render/controller test: **None found**. `tests/dashboard-settings.test.js` checks generic widget visibility/header settings, not weather transformation. See W-01.
- Verified source: `index.html::data-widget="weather"`; `js/dashboard-widget-loader.js::PRIORITY_WIDGETS,widgetLoaders.weather`; `js/main_weather.js::loadWeather`; `js/api/openMeteo.js::fetchWeather,floorHourIndex`; `js/ui/render_weather_api.js::renderNow,renderNext,buildMetricChart`; `js/config.js::COORDS,TIMEZONE,REFRESH_MS,TEMP_STOPS`; `js/temp-scale.js::tempColor`.
- Conflicts: **None identified**. Gap: W-02. Verification: source-only review 2026-09-24; tests not run; no private runtime data read.
