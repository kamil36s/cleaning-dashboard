# Quote widget

## Identity and verification

- ID: `quote`; display: Random Quote; domain: dashboard presentation.
- Status: current browser widget. Reviewed 2026-09-24 at HEAD `294c1925f387` plus dirty working-tree source. L0: `PROJECT_MAP.md` Widgets / External Integrations.
- Claims below are **verified implementation** unless marked otherwise.

## Purpose and boundaries

Shows one random English quote with an author and source label. Owns browser fetching, provider fallback, a simple text filter, and local fallback copy. It does not own quote history, a backend route, account data, or a durable quote store. Dashboard loader/settings/order code owns visibility and layout.

## Frontend

| Surface | Entry/identifier | Loading, empty, error, review |
| --- | --- | --- |
| Dashboard | `index.html::data-widget="quote"`, `#quote-card`, `#quote-text`, `#quote-author`, `#quote-status`, `#quote-refresh` | HTML starts `hidden`; loader visibility settings and `js/widget-order.js::placeQuoteInGap` control display. |
| Module | `js/dashboard-widget-loader.js::widgetLoaders.quote` imports `js/widget-quote.js` in deferred wave | `startQuote` waits for `dashboard:stable`, with a window-load 1500 ms fallback and one-start guard. |

`initQuoteWidget` returns if required DOM nodes are missing. `loadQuote` runs once at start and on the **New** button (read-only external GET). It prevents concurrent requests, adds `loading`, disables refresh, sets a loading label, then clears those states. Success or local fallback marks `data-ready=true` and emits `quote:ready`; `js/widget-order.js` uses that event to schedule masonry resize. Text and author use `textContent`, trimmed strings, surrounding quote/author punctuation, and `-` for missing values. There is no review action.

## Backend and API

Backend entry points, services, repositories, and application routes: **None**. Browser `fetch` calls provider URLs directly. Request/response transformation belongs to `js/widget-quote.js::PROVIDERS` and `loadQuote`. No application mutation action exists.

## Persistence and source of truth

Canonical user state, cache, generated state, raw archive, backup, migration input, legacy state, and browser-only durable state: **None** in this widget. The current in-memory displayed quote is ephemeral. Fetch uses `cache: "no-store"`; no localStorage key is used. Provider response is external, not dashboard canonical state.

## Data flow

1. On start or refresh, `loadQuote` tries **DummyJSON**, **Quotable**, then **RandomQuotes**, at most two attempts per provider and six total. The first provider returns `quote/author`, the second maps `content/author`, the third `quote/author`.
2. A network/HTTP/JSON failure or missing quote stops attempts for that provider and advances to the next. A valid quote where every matched English word is title case (at least three words) is rejected and retried within that provider's budget; `isTitleCaseQuote` uses ASCII letter matching.
3. The first accepted quote is rendered with provider name. If all fail, one of three hard-coded `FALLBACK_QUOTES` is chosen uniformly by `Math.random`, rendered, and labeled as local/offline.
4. There is no quarantine or deduplication across refreshes. An author may be absent; quote text is required for provider acceptance.

## Metrics and calculations

No user metric. Retry limits are fixed constants `MAX_ATTEMPTS_PER_PROVIDER=2`, `MAX_ATTEMPTS_TOTAL=6`; they count attempted fetches, not a performance rate. Fallback choice is a random array index. No calendar, currency, or unit semantics.

## Jobs, integrations, dependencies, failure and recovery

Jobs/queue/retries/backoff/startup recovery: **None**. Provider order is sequential; there is no delay/backoff or timeout in this module. External requests carry no credential. The browser requires provider CORS/network availability; local fallback makes a failure visible as a local quote. After reload, the module fetches again; it cannot restore an earlier quote. Dashboard visibility can hide the card independently of quote success.

## Privacy and security

No private dashboard data is sent. Provider GET requests expose ordinary browser network metadata to those external services. Text is rendered inert with `textContent`. No private source was examined.

## Tests and evidence

- Focused Quote behavior test: **None found** under `tests/`; `tests/dashboard-settings.test.js` covers generic visibility settings, not provider order, fallback, filter, or ready event. See gap Q-01.
- Verified source: `index.html::data-widget="quote"`; `js/dashboard-widget-loader.js::widgetLoaders.quote,startDashboard`; `js/widget-quote.js::PROVIDERS,isTitleCaseQuote,initQuoteWidget,startQuote`; `js/widget-order.js::placeQuoteInGap`; `js/dashboard-settings.js::DEFAULT_* quote entries`.
- Current documentation: `PROJECT_MAP.md` (L0 orientation). Conflicts: **None identified**. Verification: source-only review 2026-09-24; tests not run; no private runtime data read.
