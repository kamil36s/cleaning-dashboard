# Cleaning Dashboard (multi-file)

## Dev quick start
Open `src/index.html` via a local server (for ES Modules):

- Node: `npx http-server src -p 5173` or `npx serve src`
- Python: `python -m http.server 5173 -d src`

Then open http://localhost:5173

## Where things live
- **styles.css** — all styles and design tokens
- **js/config.js** — API base URL and write token
- **js/icons.js** — inline SVG for categories + `iconFor()`
- **js/utils.js** — `fmtDate()` and `bust()` anti-cache helper
- **js/state.js** — shared in-memory `DATA` + setter
- **js/api.js** — `fetchData()`, `markDone()` and boot debug
- **js/render.js** — KPI calc, card templating, and diff-render loop
- **js/main.js** — wire-up events and kick-off