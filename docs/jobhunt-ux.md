# Job Hunt product interface

Status: implemented on 2026-09-24. This document describes the current browser information architecture. The Pack and persistence details remain in `docs/jobhunt-roadmap.md`.

## Product structure

`jobhunt.html` is a routed application shell. It renders one workspace at a time:

| Workspace | User purpose |
| --- | --- |
| Home | Current opportunities, human-attention counts, Track pulse, application momentum, actionable source degradation, and a compact Pack M evidence/experiment pulse |
| Jobs | Filter current or historical jobs, select a Track, inspect categorical Evaluation signals, and open one job detail |
| Tracks | Maintain search strategies and move between Overview, Analytics, Jobs, Skills, Search, and Policy |
| Applications | Review the current Application pipeline and scheduled follow-ups |
| Profile | Edit Basics, Experience, Education, Certifications, Languages, Preferences, Dealbreakers, and Profile history in focused sections; Assessments are a Profile subsection |
| Skills | Maintain Profile skill evidence and inspect Track-specific market signals |
| Insights | Inspect Market, Sources, Applications, 2-5 Track trade-offs, Career Intelligence, and Career Experiments without a global score |
| Sources | Understand, enable, pause, sync, and inspect NAV, Pracuj JobAlert, and Jobbnorge independently |
| Review | Resolve job-data issues and duplicate candidates through one filtered inbox |
| Advanced | Inspect evidence/imports, worker and archive diagnostics, merge/Evaluation/policy history, and legacy compatibility |

The legacy aggregate match score is preserved only under `Advanced -> Legacy compatibility`. Current Home, Jobs, Tracks, and the dashboard widget use Track-specific categorical Evaluation results: blockers, supported requirements, gaps, and unknowns. Unknown remains distinct from both a blocker and a gap.

## Routes

The URL hash is the durable browser view state:

- `#home`, `#jobs`, `#tracks`, `#applications`, `#profile`, `#skills`, `#insights/market`, `#sources`, `#review`, and `#advanced`
- `#jobs/<job-id>` opens a selected Job Detail; the old `#job/<job-id>` form is accepted as an alias.
- `#track/<track-id>/<overview|analytics|jobs|skills|search|policy>` opens a Track and tab.
- `#insights/<market|sources|applications|tracks|career|experiments>` opens one bounded Insights section.
- `#profile/assessments`, `#review/<all|job-data|duplicates|sources>`, and `#advanced/<section>` open subsections.

Unknown routes fall back to Home. Hash changes support refresh, bookmarks, and browser back/forward without adding a routing dependency.

## Loading and failure boundaries

With established SQLite authority, initial page load requests only `/api/jobhunt/health` and `/api/jobhunt/overview`. A browser performing its one-time cutover sends the existing bounded migration request instead of the health check, then loads the same overview. Jobs, Profile, Track intelligence, sources, review queues, raw facts, extraction operations, worker state, and legacy settings load when their workspace or disclosure is opened. The shell and each workspace have intentional loading, empty, and retry/error states.

Sources are isolated from one another. The Sources loader first reads the durable source registry, calls a status route only for registered sources, and settles each optional status independently. A missing Jobbnorge definition therefore no longer triggers `/sources/jobbnorge/status` and cannot collapse the entire workspace into a generic `Not found` response. A registered but degraded source keeps the other cards usable and shows its own error. Insights loads only its selected tab; market/source/application/Track windows are explicit and invalid free-form query syntax is rejected.

## Editing model

Profile collections render saved records first. Add and Edit open a focused drawer, while Cancel returns to the record list. Common work-model, schedule, relocation, and hard-constraint choices use guided controls. The generic key/JSON path is retained only inside an Advanced custom-field disclosure. No migration or schema change was needed; the controls write the existing Profile payloads.

Manual job entry remains a normal top-level action. Exact advertisement ingestion and evidence preservation live under Advanced. Imported user text is escaped before HTML rendering, and original-source links are emitted only for HTTP(S) URLs.

## Insights and experiment interaction

- Market separates observed-window Canonical Jobs from the current active
  snapshot. Coverage cards always show known, unknown, and denominator. Salary
  rows are separated by currency/period/tax type and say `insufficient salary
  evidence` below the three-job minimum. Pack K remains the detailed skill view.
- Sources shows Source Listings, Canonical Jobs contributed, unique contribution,
  within-source duplicate consolidation, cross-source overlap, review burden,
  request failures, and current health. Application funnels show their submitted
  Application denominator, event-derived response/timing evidence, censored
  cases, and captured Track/discovery-source attribution.
- Track trade-offs require 2-5 selected Tracks. Rows show facts and explicit
  scenario assumptions; no column is styled as a winner and no aggregate score
  is calculated. Economic editors create new immutable versions. Blank costs
  remain unknown. Manual net and FX values require visible source/date/model
  context and are labelled scenario estimates, never guarantees or tax advice.
- Career Intelligence cards are deterministic hypotheses. Cards cite recurring
  current jobs, Profile evidence, sources/geography, and current Pack J gaps or
  unknowns. Assessments/preferences are supporting context only. Save, dismiss,
  and accept are explicit; only accept creates a Track through the normal Track
  service.
- Experiments are planned before they are started. The area exposes planned,
  active, completed, and abandoned records, task versions, time, ratings, notes,
  and provenance. Completion ratings are immutable; reinterpretation notes are
  append-only. A separate checked confirmation is required before a completed
  result adds a skill/preference Profile record with `career_experiment` origin.
  No assessment or Profile record changes silently.
- Empty states explain insufficient evidence instead of treating a zero or
  missing value as a conclusion. Wide matrices/tables scroll horizontally and
  cards/forms collapse to one column on narrow screens.

## Data and compatibility

SQLite, localStorage authority keys, existing JSON schemas, immutable Evaluation policies/results, source evidence, merge history, and legacy recovery data remain authoritative. `/api/jobhunt/overview` retains the existing `summary` object and bounded `home` read model, now with compact `insights` signals used by Home/widget. Migration 13 adds only application attribution, economic-scenario history/current pointers, proposal decisions/events, and Career Experiments/events. Rebuildable analytics remain live read models. No new source, destructive cleanup, external model, live FX/tax feed, automatic application, or global career score was introduced.

## Focused coverage

`tests/jobhunt-pack-m.test.js` covers Insights routing, Market/Sources/Applications/Track Analytics, the trade-off matrix, Career Intelligence, Experiments, responsive-safe render structure, API paths, controller actions, empty states, and escaping. `tests/test_jobhunt_pack_m.py` and `tests/test_jobhunt_pack_m_http.py` cover metric/population contracts, salary comparability, source overlap, application attribution/timing, scenario versions, deterministic adjacency/proposals, experiment immutability and reviewed Profile updates, performance, and routes. Existing Career, Track, Evaluation, Skill Intelligence, ingestion, dedupe, API, UX, store, and widget suites continue to cover their domain behavior.
