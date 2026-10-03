# Mental Health

## Identity and verification

- Stable ID: `mental-health`; `mental-health.html`, dashboard `data-widget="mental-health"`, and `/api/mental-health/*`. Reviewed 2026-10-02 at revision `67931c3`.
- Kermit explains static implementation only. It cannot read assessments, answers, check-ins, or the private database. A score is an application screening/trend value, **not a diagnosis**.

## Ownership and flow

`mental_health_store.py::MentalHealthStore` owns private `data/mental-health.sqlite` (schema version 1, SQLite WAL). Tables hold schedules, assessments, per-item responses, check-ins, context events, drafts, settings and user-created definitions. An assessment stores instrument/language/scoring versions, completed and created times, raw/normalized/subscale scores, interpretation, response and context JSON, source notes, a definition snapshot, and baseline flag. Responses also have per-item rows with cascading deletion. The first assessment becomes baseline unless explicitly changed; deletion of a baseline assigns the oldest remaining assessment. Neither the registry nor a questionnaire file is a user's answer.

`mental_health_registry.py` owns built-in instrument metadata and scoring. Reviewed language packs under `mental_health_questionnaires/<instrument>/<language>.json` supply authorised item text, response options, score rules, provenance and licence metadata. `_validate_language_pack` checks schema, IDs, version, required items, options, reverse keys, subscales, gates and provenance. Any invalid pack leaves that instrument in `external-score` mode and logs a validation error. `get_registry` prefers a Polish pack when available; it does not translate absent wording. As reviewed, PHQ-9, GAD-7, WHO-5, PCL-5, PC-PTSD-5, RSES, SWLS, Flourishing, SPANE, Mini-IPIP20 and IPIP-BFM50 have validated native packs; other licensed/incomplete instruments remain external-score, apart from two built-in personal trackers. User-created definitions are private SQLite state, separate from shipped definitions.

`server.py::dispatch_mental_health_get/post/delete` exposes health, overview, registry, assessments, analytics and export reads; POST creates assessments, check-ins, events, custom questionnaires and drafts, updates schedules/settings, imports data and sets a baseline; DELETE removes assessments/check-ins/events or all data with explicit confirmation. POST reads at most 5 MiB. `js/mental-health-api.js` owns browser request formatting. `js/mental-health-page.js` presents library, due list, draft/resume, assessment history and score trends, check-ins, context, settings and export/import controls; `js/widget-mental-health.js` presents a compact overview. Browser rendering and CSV/JSON downloads are presentation/export, not separate canonical stores. Failed API calls show page/widget error states. No sensor ingestion or sensor-based automatic Mental Health calculation is present in this path.

## Scoring and time rules

Native completion requires all active required/scored responses. Validated pack rules sum or sum subscales, apply declared reverse keys, gates and conditional visibility; WHO-5 also multiplies raw score by four. `score_instrument` rejects a scoring override for validated native packs. Custom trackers require every item and use `custom-sum@1`, optional reverse and subscales. External-score mode accepts a bounded manual total or required subscales without fabricating item answers. `interpretation_for` attaches non-diagnostic bands/notices. A PHQ-9 item response can attach a separate safety notice; this is not a calculated diagnosis or risk score. `analytics` derives recent descriptive scores, changes, and exploratory Spearman correlations only after ten matched assessment/check-in pairs; it is a read model, not stored analysis. Tests: `tests/test_mental_health.py` scoring, pack validation, completeness, version retention, scheduling, drafts, analytics and export/import.

`parse_datetime` normalizes supplied instants to UTC and treats timezone-free inputs as UTC; `iso` writes `Z`. The page turns `datetime-local` assessment entries into ISO instants and formats them in the browser's local zone. `calculate_schedule_status` adds cadence days to the latest completion instant, compares UTC calendar dates for `completed_today`, `due` and `overdue`, and marks the next seven elapsed days `due_soon`. Baseline-only schedules have no next due after completion. Pause/disable suppress due status. A future `snoozedUntil` changes not-started/due/overdue to due-soon until that instant, without editing completion history. `early_retest_warning` compares the elapsed minimum-retest interval; it warns but does not block save. Initial schedule rows can contain startup delay/snooze values. Analytics pairs check-ins and assessments by the first ten characters of stored UTC timestamps, whereas the page displays local dates. These clocks need not show the same day around midnight.

`export_data` emits a private, time-stamped JSON export with records and version metadata; the page also builds CSV downloads. `import_data` checks export schema version and recreates records through current create methods, skipping duplicate IDs. It does not restore every historical score and definition field byte-for-byte; version drift can affect recomputation. Exports, imports, actual answers, notes and runtime SQLite are excluded from static admission.

## Privacy, limits and checked references

Admitted metadata is limited to safe store/registry/API/UI source and this pack. Questionnaire JSON contains authorised item wording and is reviewed for its contract but is not admitted by the static index's source format policy. `data/mental-health.sqlite`, WAL/SHM files, assessment/check-in exports and personal questionnaire answers are excluded. Relevant limits are MH4-01 to MH4-03 in `GAPS_AND_CONFLICTS.md`; the reviewed set lacks a dedicated backend HTTP route regression.

| Admitted source | Checked marker |
| --- | --- |
| `mental_health_store.py` | `def calculate_schedule_status` |
| `mental_health_store.py` | `def create_assessment` |
| `mental_health_registry.py` | `def _validate_language_pack` |
| `mental_health_registry.py` | `def score_instrument` |
| `js/mental-health-page.js` | `async function refresh` |
| `server.py` | `def dispatch_mental_health_get` |
