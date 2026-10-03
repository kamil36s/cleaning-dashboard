# Self-care

## Identity and verification

- Stable ID: `self-care`; current `index.html::data-widget="self-care"`; reviewed 2026-09-30 on dirty `main` against widget, shared Google Apps Script task integration and Timeline activity code/tests.
- Purpose: display and mark self-care tasks, plus capture their history for Timeline. It does not write Habits App check-ins.

## Ownership and read/write flow

`js/widget-self-care.js` uses the shared Google Apps Script URL from `js/config.js::API` with `apartment=self-care` and `sheet=emotional_tracker` to load task rows. It filters blank tasks or nonpositive frequency, displays status and a six-item actionable/idea list. The user mark-done action sends `action=done` and the configured `WRITE_TOKEN` to that external endpoint after a four-second undo window. If that write succeeds, it best-effort POSTs `/api/timeline/activity/self-care` with title/category/current ISO time, then refreshes tasks. On every successful refresh it also best-effort syncs historic `lastDone` task values to the same endpoint. Timeline capture failure is deliberately swallowed, so successful task state does **not** guarantee a Timeline event. These are distinct writes and owners.

`timeline_activity.py::TimelineActivity.record_self_care` appends deduplicated events to **private Timeline-owned** `data/timeline-activity/self-care.jsonl`; it accepts a single event or at most 500 events, validates title/date, and uses a hash of calendar date plus title as ID. `_self_care` reads that file into private Timeline events. The Timeline API is an activity projection/history feed, not the canonical self-care task schedule. The external Google Apps Script task source owns current task metadata and completion; Timeline owns its own captured activity file. Neither is stored as a normal `HabitsStore` entry.

## Calculations and time

`getSelfCareStatus` uses the browser's local day for recent completion. Idea categories are `RECENTLY DONE` when days since `lastDone` are within `min(freq,7)` and otherwise `IDEA`; other categories are `TO DO` when overdue or next-due is zero, else `DONE`. Missing lastDone gives infinity. The progress bar is rounded `DONE/(TO DO+DONE)*100`, or zero for an empty denominator; idea/recent categories are excluded. Today's log compares `lastDone` to the browser's local date. Timeline writes receive a browser ISO timestamp; if absent, the server uses current Warsaw time. Event day extraction in Timeline is scoped to `_iso_day`, not the widget's browser-local comparison, so edge days can differ.

## Failure, privacy and evidence

The widget shows a sync error when external task load or write fails. Timeline POST is best effort and has no repair queue beyond history sync on a later successful refresh. A Timeline event deduplicated by day and title cannot represent multiple same-title completions on one day. The private JSONL, external task rows, write token and user titles are excluded from Kermit's index. Kermit may explain the contract but cannot inspect or mark actual tasks.

Reviewed sources: `js/widget-self-care.js::getSelfCareStatus,markSelfCareDone,recordSelfCareTimelineEvent,syncSelfCareTimelineHistory`; `timeline_activity.py::record_self_care,_self_care`; `server.py::POST /api/timeline/activity/self-care`; `tests/test_timeline_activity.py`. No dedicated self-care widget behavior test was found; static review does not prove the external Cleaning task source's live state.

## Checked implementation references

| Admitted source | Checked marker |
| --- | --- |
| `js/widget-self-care.js` | `async function markSelfCareDone` |
| `timeline_activity.py` | `def record_self_care` |
| `server.py` | `/api/timeline/activity/self-care` |
| `index.html` | `data-widget="self-care"` |
