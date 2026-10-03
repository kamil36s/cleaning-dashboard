# Sleep

## Identity and verification

- Stable ID: `sleep`; current `sleep.html` page, reviewed 2026-10-01 on dirty `main`. L0: `PROJECT_MAP.md` Sleep and Health Connect rows.
- Kermit has no authorized reader for last night's sleep or other personal Health Connect/ring records.

## Purpose and boundaries

`sleep.html` and `js/sleep-page.js` display deterministic analysis from private device data. The page **does not ingest** Health Connect or write canonical measurements. Android steps-sync gathers Health Connect sessions/heart rate, POSTs `/api/health-connect/snapshot`; `server.py::write_health_snapshot` owns append history plus replaceable latest. The COLMI ring service owns its separate history. Sleep's browser API normalizes and merges these sources for a read-time view. Health Connect uploads never overwrite normalized scale history.

## Frontend and source flow

| Stage | Current owner and behavior |
| --- | --- |
| Android ingest | `HealthSnapshotRepository.readTodaySnapshot` uses device `LocalDate` and system `ZoneId`, from local midnight to now/tomorrow midnight; sleep sessions/stages use instant timestamps. Companion upload passes a `day`, timezone and source payload. |
| Server ingest/read | POST `/api/health-connect/snapshot` writes `data/health-connect/snapshots.jsonl` and replaces `latest.json`, stamping server-local naive `received_at`. GET `/api/health-connect/history` uses `read_health_sleep_history`: one richest snapshot per **captured day**, ranked by valid sleep duration, valid session count, sample count, then receipt time. It returns `latestReceivedAt` and bounded sleep/heart-rate fields; GET `/latest` supplies fallback. This is snapshot selection, not clinical sleep analysis. |
| Browser source adapter | `js/sleep-api.js::loadSleepHistoryData` fetches ring history and Health Connect history concurrently; if history request fails, it tries Health Connect latest. It accepts either source alone, throws only when no usable nights remain, and exposes last sync separately from the selected night. |
| Normalization/merge | `createWatchSleepDatasets` accepts valid start/end sessions of at least 30 minutes, deduplicates by Warsaw wake-night key and prefers longer session, then more heart samples, then newer receipt. `createRingSleepDatasets` normalizes legacy shifted windows and selects one ring candidate per night. `mergeSleepDatasets` uses the watch session/window when present, with ring heart rate only if watch samples are absent. Stages are retained for source display/movement proxy; they are not stored as a new Sleep record. |
| Analysis/display | `js/sleep-analysis.js::analyzeSleepData` computes a night on demand; `analyzeSleepHistory` computes aggregates. `js/sleep-page.js` shows selected night, duration, RHR, chart and history plus a last-sync warning after 48 hours. Refresh reloads and aborts the prior request. No analysis persistence route exists. |

## Persistence and calculation semantics

`data/health-connect/snapshots.jsonl` is **private external ingest history**, while `data/health-connect/latest.json` is a **replaceable cache**. Raw Health Connect sessions/stages are source evidence in those payloads; `js/sleep-api.js` builds normalized browser datasets without mutating them. Ring history belongs to the ring subsystem and stays private. `js/sleep-analysis.js` outputs **derived metrics**, never canonical sleep facts. There is no Sleep-owned store, backup, job, or browser localStorage key in this page flow.

`sleepNightKey` groups by **Europe/Warsaw wake day**: a start at/after 18:00 uses start + 12 hours to place a pre-midnight partial record with the next morning; earlier starts use end day. This differs from server snapshot grouping by uploaded device `day`, which may use another zone. `normalizeRingSleepWindow` may shift legacy records 24 hours backward if created-time or cross-midnight evidence indicates a known older parser offset. Device session start/end remain instants; duration uses source `totalMinutes` when valid and otherwise rounds elapsed minutes. Watch sessions shorter than 30 minutes are omitted. The server's richest-snapshot choice can discard a shorter session in the same captured day; the browser separately picks a night winner.

`normalizeSleepSamples` drops invalid timestamp/BPM/movement (BPM must be 30–240, movement nonnegative), keeps the last duplicate timestamp and sorts. With a trusted device window, `analyzeSleepData` keeps that window even with no heart samples; `hasSleep` requires at least 30 minutes, RHR stays null without samples. Without a trusted window, at least three samples are required; onset needs BPM below sample average and low movement sustained ten minutes, and wake uses BPM spike (15%) plus movement after at least 30 minutes, else final sample. RHR is the lowest mean 15-minute window with at least 80% time coverage, or an explicitly marked lowest-sample fallback. History summaries round mean duration and RHR, calculate target share in the 7–9 h range, medians of Warsaw clock times, and a recent-versus-prior duration trend only with at least three nights in each group. No sleep score is stored or calculated by this reviewed page.

## Failure, privacy and evidence

An incomplete watch snapshot may still provide a trusted sleep window and null RHR; ring heart rate can fill missing watch samples for the same night. Missing source data does not mean zero sleep. `latest.json` or `latestReceivedAt` can be stale; page sync status uses a 48-hour warning, not guaranteed freshness. `sleep-page.js` reports empty/error states. No raw Health Connect row, ring row, private export or cache is admitted to Kermit. Source metadata admission is limited to the page, API and deterministic analysis modules. Focused evidence: `tests/test_health_connect_history.py`, `tests/sleep-api.test.js`, `tests/sleep-analysis.test.js`. Gaps S4-01 and S4-02 in `GAPS_AND_CONFLICTS.md`.

## Checked implementation references

| Admitted source | Checked marker |
| --- | --- |
| `server.py` | `def read_health_sleep_history` |
| `js/sleep-api.js` | `export function sleepNightKey` |
| `js/sleep-analysis.js` | `export function analyzeSleepHistory` |
| `js/sleep-page.js` | `export async function loadSleepPage` |
