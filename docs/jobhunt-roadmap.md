# Job Hunt architecture and implementation roadmap

Status: Packs A-E implemented on 2026-09-18. Packs F-J implemented on 2026-09-23. Pack K, Pack L1, and Pack M implemented on 2026-09-24. The current routed product interface is documented in `docs/jobhunt-ux.md`.

## Implemented Pack A boundary

The durable runtime path is now:

```text
jobhunt.html + dashboard widget
              |
              v
js/jobhunt-api.js
              |
              v
/api/jobhunt/*
              |
              v
jobhunt_backend/{models,migrations,store,service}.py
              |
              v
data/jobhunt.sqlite
```

The initial schema contains only `canonical_jobs`, `applications`, append-only
`application_events`, `legacy_evaluation_snapshots`, `compatibility_settings`,
`local_storage_migrations`, `local_storage_migration_items`, and the checksummed
schema-migration ledger. Private recovery snapshots and content-hashed branding
files live under `data/jobhunt/`; the Python static-file policy denies the whole
directory.

The client submits a bounded version-1 localStorage snapshot. The server computes
the authoritative SHA-256 fingerprint, writes and verifies a private recovery
copy, imports all canonical rows in one transaction, verifies mappings/counts,
and reuses the successful result for the same fingerprint. Existing browser IDs
are unique `legacy_id` values. The full exact submitted offer remains in the
private recovery snapshot; bounded per-job compatibility JSON retains the legacy
shape but replaces logo data URLs with migration evidence so binary data is not
duplicated in SQLite. Imported match analysis/CV advice is explicitly stored as
`legacy_imported` rather than calculated truth. Valid bounded logo data is decoded
into private hash-named files; invalid logo data produces a warning and does not
abort the offer, while its exact source remains in the recovery snapshot.

`expired` maps to source-expiration compatibility state plus a non-expired
Application projection (`to_review` when no earlier application state can be
recovered). API responses retain the legacy display status while also exposing
`applicationStatus` and `sourceExpired`. Apply, follow-up, archive, edit, and soft
delete operations update the current projection and append events atomically.

The browser never deletes or rewrites the legacy offers/settings keys during
migration. After a verified result it records `dashboard.jobhunt.authority` and
uses SQLite exclusively. The old offers/settings remain recovery input, and
`dashboard.jobhunt.theme` remains a browser UI preference. A later API outage is
shown as unavailable; it does not reactivate writable localStorage. If migration
has never succeeded, the existing legacy mode can still operate.

`js/jobhunt-store.js` remains the compatibility/pure-view layer for enums,
normalization of old browser records, filtering, date/expiration formatting, and
pre-cutover legacy operation. Backend IDs, request validation, URL/logo handling,
migration/idempotency, durable settings, soft deletion, and all Application plus
ApplicationEvent transitions are now server-owned rules in `jobhunt_backend`.

Pack A did not add Career Profile or assessments at the time it was delivered.
Those capabilities are now supplied by Pack B, while Pack C supplies Tracks and
Search Profiles. The source-ingestion, extraction, normalization, deduplication,
Evaluation, Skill Intelligence, and analytics capabilities that were outside Pack
A are supplied by the later implemented packs documented below.

## Implemented Pack B boundary

Pack B extends the Pack A runtime without changing the authority or legacy
recovery rules:

```text
jobhunt.html + js/jobhunt-career.js
              |
              v
js/jobhunt-api.js
              |
              v
/api/jobhunt/profile/* + /api/jobhunt/assessments/*
              |
              v
jobhunt_backend/{service,store,migrations}.py
              |                         |
              v                         v
data/jobhunt.sqlite       immutable assessment manifests
```

The schema-version-2 migration adds a single-user Career Profile with separate
experience, education, certification, language, skill, preference, constraint,
evidence, and revision rows. Every explicit profile mutation creates a complete
revision snapshot and SHA-256 fingerprint. Missing and nullable values remain
unknown rather than becoming negative facts. Profile truth is never inferred
from assessment scores.

Assessment definitions are immutable, locally validated JSON manifests with a
canonical definition hash. The implemented catalog contains:

- the exact English 60-item O*NET Interest Profiler Short Form, versioned as
  `2018-05`, redistributed verbatim with its required CC BY-ND 4.0 attribution;
- the exact public-domain IPIP 50-item Big-Five Factor Markers inventory,
  versioned as `1.0.0`, including its reverse-keyed items;
- a project-authored 31-item Career Work Preferences questionnaire, versioned
  as `1.0.0` and explicitly labelled non-validated and non-diagnostic.

Draft runs autosave and resume. Completion requires every response, calculates
deterministic dimension totals and normalized 0-100 scores, and freezes the
instrument version, definition hash, scoring version, responses, and scores.
Application checks and SQLite triggers both prevent completed-run mutation. A
retake always creates a new run, and abandoned drafts remain read-only history.
Results are displayed as separate dimensions and evidence for exploration; they
do not write to the Career Profile, jobs, applications, or legacy settings.

The Career Profile, Skills, and Assessments views are available inside the
existing Job Hunt page. The assessment runner uses five-question pages,
keyboard-accessible native controls, saved progress, explicit completion, run
history, retakes, and clear unavailable/error states. Backend, HTTP, API-client,
and DOM tests cover migration from Pack A, profile revisions, manifest
validation, deterministic/reverse scoring, draft resumption, immutability,
history, navigation, and results. Pack B does not implement Tracks, live source
collection, parsing, matching, or market analytics.

## Implemented Pack C boundary

Pack C adds explicit user-managed search strategies without introducing source
collection or candidate evaluation:

```text
jobhunt.html + js/jobhunt-tracks.js
              |
              v
js/jobhunt-api.js
              |
              v
/api/jobhunt/tracks/* + /api/jobhunt/search-profiles/*
              |        + /api/jobhunt/jobs/{id}/tracks
              v
jobhunt_backend/{service,store,migrations}.py
              |
              v
data/jobhunt.sqlite
```

Migration `4` adds `career_tracks`, `track_search_profiles`, and
`track_job_assignments`. A Track is a career/search strategy with a stable ID
and slug, purpose, `exploring`/`active`/`paused`/`archived` lifecycle,
lightweight geography/economic context, optional rationale/notes, and a nullable
`evaluation_policy_version` seam reserved for Pack J. Status changes are
non-destructive: Search Profiles and assignment history remain intact.

Initialization idempotently seeds these explicit user-selected hypotheses, all
with status `exploring`: `QA Poland`, `Kraków Weekend Work`, `Norway Physical
Work`, `Norway QA`, and `Iceland Physical Work`. Their 25 concise starter Search
Profiles use stable seed keys and `INSERT OR IGNORE`; startup never resets a
user-edited seed name, purpose, status, geography, or profile.

A Search Profile belongs to exactly one Track and stores an enabled/paused/
archived state, include and exclude terms, free-text role intent, country and
city/region criteria, work-model/schedule/contract/language/seniority hints,
notes, and `planned_source_keys`. Missing arrays mean no restriction, while
nullable Track booleans remain unknown rather than false. The temporary source
keys are validated textual planning hints (`pracuj`, `nofluffjobs`, `olx`,
`nav`, `finn`, `alfred`, `jobbnorge`, `company_sites`, `email_alerts`). They do
not create SourceDefinition/SourcePolicy records or trigger HTTP, email, jobs,
workers, or scraping; Pack D or later may resolve the keys to real definitions.

`track_job_assignments` is a durable many-to-many relevance link between a
Canonical Job and zero or more Tracks. It stores `manual`, `seed`, or
`legacy_reviewed` origin, an optional note, active/removed state, and timestamps.
The current UI writes only `manual`. Repeating the same assignment is idempotent;
removal deactivates rather than deletes the row. Pausing or archiving a Track
does not remove existing history, while a new assignment to an already archived
Track is rejected. Assignment means only that a job is relevant for analysis
under a Track; it never changes job facts, Application/ApplicationEvent, Career
Profile, assessments, or legacy QA settings and never calculates fit.

The API exposes `GET/POST /api/jobhunt/tracks`, `GET/PATCH
/api/jobhunt/tracks/{id}`, `GET/POST
/api/jobhunt/tracks/{id}/search-profiles`, `PATCH
/api/jobhunt/search-profiles/{id}`, and `GET/POST
/api/jobhunt/jobs/{id}/tracks`. `js/jobhunt-api.js` remains the only browser
server adapter. The Job Hunt page has a dedicated Tracks list/detail editor,
Search Profile forms, clearly inactive future-source selections, assigned-job
list, lifecycle controls, and multi-Track checkboxes in existing job details.

Focused coverage lives in `tests/test_jobhunt_pack_c.py`,
`tests/test_jobhunt_pack_c_http.py`, `tests/jobhunt-tracks.test.js`, and the
extended API-client suite. It verifies migration/checksums, seed idempotency and
edit preservation, lifecycle and unknown semantics, structured filters/source
hints, ownership validation, many-to-many assignment/deactivation and domain
separation, HTTP routes, rendering, editors, assignment controls, and errors.

Pack C deliberately does not implement SourceDefinition, SourcePolicy, live
sources, ingestion, scraping, workers, AI parsing, normalization, deduplication,
matching, skill intelligence, market analytics, or Career Experiments.

## Implemented Pack D boundary

Pack D adds the durable, source-neutral observation chain without interpreting
advertisement facts:

```text
SourceDefinition + SourcePolicy
              |
              v
        SourceListing
              |
              v
  immutable RawCapture -> SHA-256 raw blob
```

Migration `5` adds `source_definitions`, `source_policies`,
`search_profile_sources`, `source_listings`, discovery-context link tables,
`raw_blobs`, and immutable `raw_captures`. The stable sources are `manual`,
`pracuj`, `nofluffjobs`, `olx`, `nav`, `finn`, `alfred`, `jobbnorge`,
`company_sites`, and `email_alerts`. Only `manual` has an implemented adapter;
its policy is `manual_only`. Every external source is `planned`, disabled, has
an unverified/`unknown` access method, and performs no collection. Source
identity, adapter availability, and mutable operational policy are exposed as
separate concepts.

Pack C `planned_source_keys` remain stored unchanged. Initialization
idempotently resolves known keys into foreign-keyed `search_profile_sources`
bindings, while API responses report unresolved legacy keys instead of
discarding them. A binding never enables collection.

`SourceListing` preserves a source-local external identity, canonicalized and
observed URLs, non-canonical title/company/location hints, explicit lifecycle
state, first/last seen times, optional Canonical Job seam, and many-to-many
Track/Search Profile discovery context. Identity prefers explicit external ID,
then canonical URL, then exact content hash; an explicit new-listing option is
available. Exact repeated button submissions return the existing capture,
while changed bytes append history. No title-only or cross-source deduplication
is attempted.

`ManualImportAdapter` accepts paste text, HTML, JSON, and bounded UTF-8
`.txt`/`.html`/`.htm`/`.json` uploads. Paste strings are archived as their exact
UTF-8 encoding without trimming, prettifying, HTML stripping, or JSON
rewriting; file bytes are preserved exactly after type, UTF-8, and 1 MiB bounds
validation. URLs are length/scheme/parse validated and canonicalized only for
listing identity; they are never fetched. JSON is syntax-validated but not
interpreted as job facts.

Raw bytes live privately under
`data/jobhunt/raw/sha256/ab/cd/<full-sha256>.<safe-ext>`. Writes use a same-
directory temporary file, flush/fsync, pre-rename verification, atomic replace,
and final hash/size verification before database references are committed.
Several captures can reuse one blob while retaining observation-specific MIME
metadata. A database failure can leave an unreferenced safe blob; the storage-
health API reports that orphan rather than deleting evidence. Missing files,
size/hash corruption, unique/reused counts, and total bytes are also reported.
Raw paths are never returned by the API and the existing Python/Vite private
path rules deny the complete `data/jobhunt/` tree.

The API now exposes source/listing/capture reads, synchronous manual import,
and explicit storage-health checks. The Job Hunt page has an Import / Ingestion
workspace with optional source, URL, hints, Track/Search Profile context,
TXT/HTML/JSON paste or file input, source operational status, listing history,
byte-change indicators, archive health, and escaped inert raw previews.

Pack D deliberately adds no external HTTP/email adapter, worker, scheduler,
extraction run, deterministic/JSON-LD/schema.org parser, AI provider,
normalization, review queue, Canonical Job deduplication, matching, skill
intelligence, or analytics. Pack A legacy `originalText` remains unchanged and
is not falsely backfilled as a RawCapture.

## Implemented Pack E boundary

Pack E adds a local-only deterministic evidence pipeline on top of Pack D:

```text
verified RawCapture
    -> versioned deterministic ExtractionRun
    -> immutable hybrid ExtractedFact rows + evidence locators
    -> exact normalization mappings
    -> provenance-backed Canonical Job projection
    -> Review Item when identity, structure, or facts need attention
    -> optional Human Override with projection precedence
```

Migration `6` adds `extraction_runs`, `extracted_facts`,
`normalization_concepts`, `fact_normalizations`,
`canonical_job_projections`, `review_items`, and `human_overrides`. The chosen
generic fact representation is the roadmap's recommended hybrid: common typed
columns hold text/number/boolean values, units, currency, periods, state,
preference, confidence, validation, and normalization state, while bounded JSON
holds complex/open values and evidence locators. Completed runs, facts, and
projection records are immutable. Override history is append-only except for
the explicit active-to-retired transition.

The implemented extractors are `manual_hints@1`, `json_structured@1`,
`json_ld_jobposting@1`, and `html_metadata@1`, all producing
`jobhunt-facts@1`. HTML uses Python's inert parser, never executes scripts,
loads resources, follows links, or performs network access. JSON and JSON-LD
use conservative known-key mappings and bounded traversal. Advertisement prose
is not parsed semantically. Exact reruns reuse the unique completed run for
`(capture, extractor kind, extractor version, input hash)`; changed captures or
material parser-version changes retain new history.

Facts retain the source wording separately from typed values. Evidence uses
JSON Pointer, JSON-LD script index plus pointer, inert HTML selector metadata,
or named submitted fields. Missing fields create no fact and therefore remain
UNKNOWN. Structured `false` and explicit `required: false` claims are preserved
as `explicit_negative`; they are not conflated with absence. Confidence means
extraction/mapping reliability only. Required, preferred, optional, and unknown
preference states remain distinct.

Normalization is a separate `normalization@1` exact-rule layer. Its deliberately
small seed taxonomy covers the observed SQL/API-testing, Postman/Jira/
Playwright/Selenium, Python/JavaScript, English/Polish/Norwegian, work-model,
and contract concepts. Mapping rows reference source fact and concept IDs;
source wording never changes.

`projection@1` selects supported current facts, records selected fact IDs and
active override IDs, and appends a fingerprinted version only when the factual
snapshot or its selected-fact/override provenance changes. A Source Listing without a supported title remains unlinked
and creates an `insufficient_identity` review instead of a fake job. A newly
projected job receives a separate default Application; later reprocessing
updates factual columns and never changes Application events, Career Profile,
assessments, or Track assignments. Conflicting facts remain stored and create
review items. Active local-user Human Overrides take projection precedence and
survive reruns without editing any fact.

The API exposes capture extraction/runs, run and job facts, Review Queue detail
and resolution/dismissal, and bounded canonical-field overrides. The Import /
Ingestion UI can run/re-run extraction and inspect value, state, confidence,
source wording, evidence, extractor, validation, and normalization. The Review
UI displays evidence/candidates and supports resolve, dismiss, and applicable
Human Override decisions. Canonical job details expose the latest projection
and source facts.

Focused coverage lives in `tests/test_jobhunt_pack_e.py`,
`tests/test_jobhunt_pack_e_http.py`, `tests/jobhunt-extraction.test.js`, and the
extended Job Hunt API/ingestion suites. Fixtures cover direct structured JSON,
schema.org JobPosting JSON/JSON-LD, multiple and malformed HTML JSON-LD blocks,
inert script-shaped text, open fields, explicit negative claims, salary/location
changes, evidence, exact rerun idempotency, immutable facts, normalization,
review, override precedence, and preservation of Packs A-D domains.

Pack E adds no AI/LLM provider, embedding, live source request, browser
automation, worker/scheduler, deduplication engine, candidate matching, skill
intelligence, or analytics.

## Implemented Pack F boundary

Pack F adds optional, synchronous AI factual enrichment without replacing the
Pack E deterministic pipeline:

```text
verified RawCapture
    -> deterministic ExtractionRun(s)
    -> optional versioned AI ExtractionRun
    -> strict local response/evidence validation
    -> existing ExtractedFact + normalization + projection + Review Queue
```

Migration `7` extends the common `extraction_runs` table with nullable generic
provider/model/prompt/schema/request/response/usage/cost/validation metadata and
adds `ai_extraction_attempts` for bounded transport-attempt history. It does not
add AI-specific job, fact, or canonical-projection tables. Existing deterministic
runs and facts are preserved by the migration and retain their immutability
triggers. AI exact-run identity covers capture hash, provider, adapter, model,
prompt ID/version/fingerprint, and response-schema version. A completed/default
exact run is reused; explicit `force=true` appends a new historical run and facts.

The provider-neutral contract lives under `jobhunt_backend/extraction/ai/`.
`FakeAIExtractionProvider` supplies deterministic scripted outcomes for tests.
`GeminiAIExtractionProvider` is the real optional adapter: it uses a fixed Google
Gemini endpoint, a fixed model allowlist, backend-only `GEMINI_API_KEY`, bounded
prompt/response sizes, a configured timeout, and one transport attempt per
service attempt. The service owns at most zero-to-two configured retries and
persists every attempt. It retries only provider errors classified as transient,
timeout, network, or rate-limit; authentication, unsupported model, malformed
output, and local validation failures are not retried. There is no provider or
paid-model fallback.

Runtime configuration is opt-in through `JOBHUNT_AI_ENABLED`,
`JOBHUNT_AI_PROVIDER`, `JOBHUNT_AI_MODEL`, `JOBHUNT_AI_TIMEOUT_SECONDS`,
`JOBHUNT_AI_MAX_SOURCE_CHARS`, `JOBHUNT_AI_MAX_CONTEXT_FACTS`,
`JOBHUNT_AI_MAX_OUTPUT_TOKENS`, `JOBHUNT_AI_MAX_RETRIES`, and optional daily
call/token limits. Optional versioned cost metadata uses the
`JOBHUNT_AI_*_USD_PER_MILLION_TOKENS` variables shown in `.env.example`. The
safe config-summary API returns states and limits, never values of secret keys.

The prompt is `jobhunt-factual-extraction@1.0.0`; its exact SHA-256 fingerprint
includes the system instructions and `jobhunt-ai-response@1` response schema.
The prompt treats advertisement text as untrusted delimited JSON data, prohibits
candidate evaluation and mutations, preserves explicit negatives and supported
required/preferred/optional wording, and requires exact source wording plus a
bounded evidence quote. Text is sent as decoded text, HTML as inert visible text,
and JSON as a bounded stable representation. Deterministic source facts may be
included as bounded context. Career Profile, assessments, Applications, Track
preferences, recruiter details, and unrelated dashboard data are never included.

Provider output is untrusted. Local validation rejects unknown response keys,
invalid types/states/preferences, UNKNOWN sentinel facts, unsupported typed fact
families, non-finite/negative salary values, mismatched typed-value fields, and
claims whose exact evidence/source wording cannot be found. Scalar values also
need local evidence consistency (for example, a salary number must occur in its
evidence). Rejected claims create Review Items and do not become ExtractedFacts.
Accepted AI confidence is `min(provider confidence, 0.95)` after schema/evidence
gates; it is an extraction-reliability signal, not a calibrated probability.
Low-confidence accepted facts remain labelled and enter the existing Review
Queue. Open facts use the existing `other` fact type plus namespace/label/value
and evidence, so housing, rotation, overtime, transport, and similar observations
do not create speculative canonical columns.

Projection policy becomes `projection@2-ai-precedence` when AI facts participate:
active Human Overrides remain first, strong deterministic structured/manual facts
precede validated AI facts, and weak HTML metadata follows. Deterministic-versus-
AI disagreement creates Review Items; neither source fact is deleted. AI reruns
cannot replace an active override and do not change existing Application events,
Career Profile, assessment runs, or Track assignments.

The API adds `GET /api/jobhunt/ai/status`, `GET
/api/jobhunt/ai/config-summary`, and `POST
/api/jobhunt/captures/{id}/ai-extract`; normal browser requests can send only a
boolean `force`, never a provider URL, key, or model. Existing run/fact routes
return safe AI provenance and attempt detail. The Import / Ingestion UI shows
deterministic and AI states separately, provider/model/prompt/usage/latency,
DETERMINISTIC/AI fact badges, evidence, historical reruns, loading/failure states,
an explicit unavailable message, and the external-provider privacy disclosure.
Deterministic extraction remains fully usable when AI is disabled.

Local configuration supports source/prompt/output bounds, timeout, retries, and
optional daily call/token limits. Token usage is always retained when supplied.
Estimated USD cost is stored only when explicit versioned local input/output
price metadata is configured; otherwise the UI reports tokens without inventing
a monetary estimate. Raw structured provider output is bounded and stored for
debugging/reprocessing but never treated as canonical truth.

Focused coverage lives in `tests/test_jobhunt_pack_f.py`,
`tests/test_jobhunt_pack_f_http.py`, `tests/test_jobhunt_ai_provider.py`, and
`tests/jobhunt-pack-f.test.js`, plus extended API tests. Synthetic fixtures cover
QA prose, Norway housing/rotation/overtime/transport, no salary, explicit
negative language requirements, prompt-injection-shaped source text, unsupported
claims/evidence, conflicts, malformed/incomplete output, retries, exact reuse,
forced history, usage/cost metadata, provider unavailability, domain separation,
and escaped UI output. Tests use fake/mocked providers and require no paid API.

Pack F itself added no worker/scheduler, live source, external collection,
scraping, deduplication, embeddings, matching, Track scoring, skill intelligence,
or analytics. Pack G now supplies the first two boundaries and Pack H supplies
deterministic deduplication; later capabilities remain deferred to Packs I-M.

## Implemented Pack G boundary

Pack G implements one live source only: NAV / Arbeidsplassen through the current
official `pam-stilling-feed`. Implementation-time verification used NAV's
official feed documentation (`https://navikt.github.io/pam-stilling-feed/`),
production host (`https://pam-stilling-feed.nav.no`), API terms
(`https://arbeidsplassen.nav.no/vilkar-api`), and maintained source repository
(`https://github.com/navikt/pam-stilling-feed`). The old `pam-public-feed` is
deprecated and is not called. The implemented endpoints are `/api/v1/feed`,
`/api/v1/feed/{feedPageId}`, and `/api/v1/feedentry/{entryId}` on that exact HTTPS
host. Requests use a backend-only Bearer token from `JOBHUNT_NAV_TOKEN`.

The implementation does not fetch, embed, or commit NAV's rotating public test
token and does not automate consumer registration. A private consumer token must
be arranged with NAV and stored in a local environment file. Collection is off
after migration and requires a configured token plus explicit enablement through
the UI/API or `JOBHUNT_NAV_ENABLED=true`. The remaining controls are
`JOBHUNT_NAV_TIMEOUT_SECONDS`, `JOBHUNT_NAV_POLL_SECONDS`,
`JOBHUNT_NAV_BOOTSTRAP_DAYS`, `JOBHUNT_NAV_DETAIL_BUDGET`, and the separately
opt-in `JOBHUNT_NAV_AUTO_AI`; automatic AI is false by default.

Migration `8` preserves the stable `source_nav` definition, permits immutable
`nav_api` Raw Captures, and adds `worker_jobs`, `source_sync_state`, and bounded
`source_request_observations`. The single in-process daemon claims work under
`BEGIN IMMEDIATE`, records attempts and leases, renews leases at stage boundaries,
recovers expired leases on startup, persists exponential backoff with deterministic
jitter, honors `Retry-After`, supports cooperative cancellation, and bounds queue
size, attempts, response bytes, timeouts, JSON depth, and feed items. Jobs are
`nav_feed_poll`, `nav_fetch_listing`, `extract_capture`, and optional
`ai_extract_capture`. Their active idempotency keys prevent duplicate queued,
running, or retrying work. A future separate process can reuse the same store and
service boundary; Pack G deliberately uses one daemon and source concurrency one.

NAV URLs are fixed-host and fixed-path allowlisted after decoding; redirects,
credentials, non-HTTPS URLs, unexpected ports/paths, and arbitrary `next_url`
values are rejected. Feed cursor/page IDs, ETag, Last-Modified, a 185-day default
bootstrap horizon, poll timestamps, counters, and last health error persist.
HTTP 304 is a successful unchanged poll. Authentication/authorization failures
stop that job, 429 and transient network/server failures retry with persisted
backoff, and failures visibly degrade Source Policy health. Request observations
retain only operational metadata, never Authorization headers or bodies.

Enabled Search Profiles bound to NAV drive local two-stage discovery. The header
prefilter uses title/company/municipality and favors recall when a header cannot
support a safe negative decision. The full detail filter applies include/exclude,
country/region, work-model, contract, schedule, language, and seniority hints.
ANY include keyword can qualify; one vacancy can retain several Search Profile
and Track discovery links. These links mean discovery context, not fit, matching,
or evaluation.

NAV vacancy UUID is the stable source-local identity. ACTIVE events can schedule
detail work; known INACTIVE events mark the Source Listing removed and update the
derived source-expired view without deleting the listing, captures, canonical
job, Application/events, Track history, Profile, or Overrides. Unknown inactive
events do not trigger detail fetches. Cross-source deduplication was deferred at
Pack G delivery and is now supplied by Pack H.

For a matched ACTIVE detail, the exact bounded JSON response is archived under
the existing SHA-256 content-addressed RawCapture store with safe adapter/feed/
UUID/request provenance. Identical bytes reuse the capture and schedule no new
extraction. Changed bytes append a new capture and automatically run
`nav_structured@1`, which maps NAV title/employer/location/publication/expiry/
engagement/extent/start and retains UUID, application URLs/deadline, occupation,
sector, and position-count observations. It then uses Pack E's existing facts,
normalization, projection, Review, and Human Override precedence. If optional AI
is invoked, contact lists and common contact/email/phone fields are removed from
the prepared NAV JSON first.

The narrow API adds worker status/list/detail/cancel and NAV status/enable/pause/
sync/feed-state routes. Sync-now only enqueues durable work. The Sources &
Ingestion UI reports token presence as yes/no, source/worker state, feed position,
last poll/error/backoff, observed/active/matched/capture counts, recent queue
states, and cancellation controls. It never receives the token. FINN and every
other planned source still report that no adapter is implemented.

Pack G tests are fully offline through injected adapters and cover migration,
transactional competing claims, leases/recovery, idempotency, cancellation,
retry/backoff/degradation, fixed-host validation, conditionals/304, 401/403/429/
timeout/5xx, response bounds, filtering/recall, multiple matches, end-to-end
capture/extraction/projection, unchanged/changed details, inactive preservation,
contact minimization, HTTP routes, token non-disclosure, and escaped UI output.
No normal test makes a real NAV request.

Pack G did not implement a second source or merging/deduplication at delivery.
Pack H now supplies the latter without adding candidate matching or scoring,
skill intelligence, or market analytics.

## Implemented Pack H boundary

Pack H adds a source-neutral deterministic identity layer after factual
projection:

```text
Source Listing -> Capture -> Extraction -> Projection
                                      -> dedupe_scan_job
                                      -> DuplicateCandidate
                                      -> reviewed/automatic merge or persistent rejection
```

Checksummed migration `9` adds indexed `dedupe_job_keys` and `dedupe_job_urls`,
durable `duplicate_candidates` plus append-only candidate events, audited
`canonical_job_merges` plus append-only merge events, and an explicit
`merged_into_job_id` alias on absorbed Canonical Jobs. It also extends the Pack G
worker constraint with `dedupe_scan_job`. Source Listings, Raw Captures,
Extraction Runs, Extracted Facts, Applications, Application Events, discovery
links, and Human Overrides are not deleted or rewritten by merge/unmerge.

The versioned policy is `dedupe@1` with `dedupe-normalization@1`. URL identity
normalizes scheme/host/default ports/fragments and only documented tracking
parameters while preserving other query parameters. Company, title, and
location normalization is conservative and lexical; seniority words remain
significant. Indexed blocking first uses exact normalized URLs, then normalized
company plus a 60-day publication window. Work per scan is bounded to 50 URL
and 150 company candidates. Comparison records same-company/title/location,
publication/expiration deltas, salary compatibility, and bounded deterministic
lexical description similarity (20,000 characters/2,000 tokens). Missing values
remain unknown rather than conflicts.

Startup backfills only the derived blocking keys for pre-Pack-H active jobs; it
does not compare historical jobs or make merge decisions. Detailed pair
comparison still occurs only inside the indexed per-job bounds above.

Hard contradictions include different known employers, incompatible non-remote
countries, distinct external IDs from the same authoritative source, publication
windows over 60 days, and materially different titles at the same employer.
They remain visible and prevent automatic or manual merge. Only an exact shared
normalized URL with no contradiction, merge-safe Applications, no unsafe active
Override transfer, and no unchanged prior rejection can auto-merge. Company,
title, location, salary, or description similarity alone always waits for review.

Survivor choice is deterministic: meaningful Application history first, then
the only active-Override side, then oldest stable Canonical Job ID. Two meaningful
Applications block merging. An absorbed meaningful Application or active Override
that would lose precedence also blocks the operation. Applications/events and
Overrides stay attached to their original auditable identities. Active Track
assignments are unioned on the survivor without deleting absorbed assignment
history; Source Listing Track/Search Profile discovery context never moves.

Merge is a single `BEGIN IMMEDIATE` relationship/audit transaction. All absorbed
Source Listings resolve to the survivor, the absorbed job becomes a resolvable
alias, and ordinary jobs/overview/export reads exclude it. Projection then uses
all listings linked to the survivor and keeps selected fact IDs, overrides, and
cross-source conflicts visible. Unmerge atomically restores recorded listing
ownership, alias state, and merge-affected Track state, marks the audit reverted,
persists a not-duplicate suppression, and reprojects both identities from current
preserved evidence. Later captures remain attached to their Source Listing and
therefore survive reversal.

The API exposes duplicate list/detail/merge/not-duplicate/dismiss, merge
list/detail/unmerge, explicit per-job scan, and operational summary routes.
`jobhunt.html` has a Duplicates section with evidence components, side-by-side
source/Application/Track/Override safety review, explicit confirmation, summary
counts, merge history, and unmerge. Automatic policy cannot be requested by the
browser.

```text
GET  /api/jobhunt/duplicates
GET  /api/jobhunt/duplicates/{id}
POST /api/jobhunt/duplicates/{id}/merge
POST /api/jobhunt/duplicates/{id}/not-duplicate
POST /api/jobhunt/duplicates/{id}/dismiss
GET  /api/jobhunt/dedupe/merges
GET  /api/jobhunt/dedupe/merges/{id}
POST /api/jobhunt/dedupe/merges/{id}/unmerge
POST /api/jobhunt/jobs/{id}/dedupe-scan
GET  /api/jobhunt/dedupe/summary
```

Candidate states are `open`, `merged`, `not_duplicate`, `dismissed`, and
`stale`. An unchanged reviewed pair stays suppressed across scans. A materially
changed evidence fingerprint reopens it and appends an event; an explicit manual
scan may also reopen a dismissed/rejected pair. Unmerge records a rejection so
the unchanged pair is not immediately auto-merged again. New or changed factual
projections schedule stable-idempotency `dedupe_scan_job` work when the worker is
attached; synchronous manual/test operation uses the same scan service boundary.

Metric denominators are explicit: Source Listing count means independent source
advertisements, Canonical Job count means active deduplicated opportunity
identities, and Raw Capture count means immutable observations over time. These
counts are not interchangeable.

Focused coverage lives in `tests/test_jobhunt_pack_h.py`,
`tests/test_jobhunt_pack_h_http.py`, and `tests/jobhunt-dedupe.test.js`. It covers
candidate rules/evidence/idempotency, UNKNOWN handling, hard contradictions,
persistent review decisions, exact automatic merge, Application/Track/Override
safety, preservation counts, alias/current counts, post-merge captures, unmerge,
worker integration, API boundaries, UI history/actions, privacy, and escaping.
Pack H adds no second source, embeddings/LLM dedupe, matching, Track fit, skill
intelligence, or market analytics.

## Implemented Pack J boundary

Pack J adds a local deterministic evaluation layer after Canonical Job factual
projection and deduplication:

```text
Career Profile revision + Canonical Job projection + Track context/policy
                                |
                                v
                    evaluator@1 (no network/model)
                                |
                                v
              immutable Evaluation + dimensions + findings
                                |
                                v
                    per-Job/per-Track current pointer
```

Checksummed migration `11` adds immutable `track_evaluation_policies`,
`evaluations`, `evaluation_dimensions`, `evaluation_findings`, and the mutable
`evaluation_current` pointer. It extends the existing worker constraint with
`evaluation_recompute`; there is no second queue or worker. Historical policy
and Evaluation rows are protected by database triggers. Every Evaluation stores
the Profile revision/fingerprint, Job projection identity/version/fingerprint,
Track policy identity/version/fingerprint, Track-context fingerprint,
`evaluator@1`, `jobhunt-evaluation@1`, eligibility basis, and a combined input
fingerprint. Unchanged input fingerprints reuse the immutable result.

Every Track receives an idempotent conservative `track-evaluation-policy@1`
seed. Startup creates only missing seeds and never resets the current pointer or
user-edited versions. The bounded declarative policy controls enabled dimensions,
presentation importance, explicit blocker categories, and skill thresholds. It
requires `unknownHandling: preserve` and `aggregate: none`; unknown fields,
arbitrary expressions, invalid dimensions, and invalid thresholds are rejected.
Editing creates or reselects an immutable fingerprinted version and queues Track
recomputation.

`evaluator@1` emits independent categorical dimensions for skills, experience,
compensation, geography, and preferences/work conditions. Finding states are
`supported`, `partial`, `gap`, `blocker`, `unknown`, and `not_applicable`.
Missing Career Profile evidence is UNKNOWN, never an inferred deficiency.
Gaps require explicit lower/conflicting evidence; blockers additionally require
an explicit hard constraint and an enabled policy category. Skill comparison is
exact normalized/concept-key only, language uses structured CEFR when both sides
provide it, experience duration derives only from comparable dated Profile
records, and salary compares only matching currency/period/gross-net evidence.
No fuzzy semantic matching, embeddings, FX conversion, assessment-derived fit,
or aggregate percentage exists.

Findings retain required/preferred/optional/unknown requirement class and cite
Job fact/projection evidence, Career Profile record/evidence IDs, and the exact
Track policy path/version. Display summaries are persisted parameters derived
from those values rather than opaque prose. A required and preferred gap remain
distinguishable; preferred gaps do not become blockers automatically.

Profile edits, factual Job/projection/override changes, Track context changes,
policy changes, assignment changes, merge, and unmerge schedule stable,
idempotent recomputation. Application workflow changes do not. The existing
worker processes bounded batches of 50 eligible Job/Track pairs and chains a
follow-up cursor when necessary; restart recovery and lease rules are inherited
from Pack G. Exploring/active Tracks auto-evaluate. Paused/archived Tracks retain
history but are skipped by automatic recompute; an explicit user request may
still evaluate them. Current pointers that lose every assignment/discovery basis
are removed without deleting history.

Evaluation operates only on active deduplicated Canonical Jobs. Absorbed aliases
resolve to the survivor, Track assignments are evaluated once on the survivor,
and unmerge re-evaluates restored identities. Historical pre-merge Evaluations
remain addressable. Legacy `legacy_imported` match scores/settings remain
separate compatibility data and are visibly labelled in the UI; they are not
translated into Track policy or Pack J truth.

The API exposes Evaluation detail, Job and Track Evaluation lists, explicit
Job/Track evaluation, active policy, policy history, and immutable policy-write
routes. Job details render categorical dimension/finding cards with prominent
blockers, visually distinct unknowns, evidence expansion, history, and no
percentage. Track detail adds the bounded policy editor/history, newest-first
evaluated jobs, and transparent blocker/unknown/skill-gap/current filters.

Focused coverage lives in `tests/test_jobhunt_pack_j.py`,
`tests/test_jobhunt_pack_j_http.py`, and `tests/jobhunt-evaluations.test.js`, with
adapter/Track integration in the existing frontend suites. It covers bounded
policy validation/versioning/immutability, UNKNOWN/GAP/BLOCKER semantics,
required/preferred skills, CEFR, salary safety, geography, work conditions,
version/currentness, Profile/Job/policy recomputation, Track status,
merge/unmerge, worker behavior, routes, evidence UI, history, filters, no magic
score, and legacy separation. Pack K consumes only current Pack J findings for
user-relative analysis; Pack L1 adds Jobbnorge independently; Pack M now reads
the same current findings for Track analytics and career hypotheses. Remaining
Pack L sources remain deferred.

## Implemented Pack K boundary

Pack K is a bounded live read model over existing Pack E facts/mappings,
canonical projections, Pack H deduplication state, Career Profile evidence, and
current Pack J findings. It adds no migration, stored aggregate, queue stage,
model call, or background rebuild. The implementation is versioned as
`skill-intelligence@1`, caps every population at 2,000 Canonical Jobs, and
publishes the population, window, coverage, source mix, fingerprints, and
calculation rules with every response.

Current populations contain active, non-archived, non-expired, non-merged Jobs
relevant through explicit Track assignment, Source Listing Track context, or a
Track Search Profile. Historical 30/90/180-day populations use the Job's
publication date, otherwise first Source Listing observation, otherwise Job
creation time; they retain inactive/archived evidence but still exclude deleted
and absorbed aliases. Demand counts distinct Canonical Jobs, never mentions or
Source Listings. Requirement-class rates use all populated Jobs as their stated
denominator, while unknown requirement-class evidence remains separately visible.

Only supported Pack E `skill`, `tool`, `language`, and `certification` facts from
the latest successful Extraction Run per Source Listing enter the calculation.
Manual mappings take precedence over deterministic mappings. Conflicting known
mappings remain ambiguous and therefore unmapped/reviewable. Original terms,
mapping versions/methods/confidence, evidence IDs, and contributing Job/source
counts remain drillable. A legacy canonical-projection fallback is exposed as
unmapped source wording instead of inventing a normalized concept.

User evidence is exact, type-safe Profile evidence: absent Profile evidence is
UNKNOWN rather than a GAP. Pack J remains authoritative for job-relative
required/preferred gaps, blockers, and unknowns. Stale Evaluations are excluded
from user-relative counts until normal Pack J recomputation makes them current;
market demand itself remains available. Strict jobs-unlocked are Jobs where the
selected skill is the only current required skill gap and there is no unrelated
blocker. Potential unlocks retain Jobs with this gap plus unknowns; multi-gap
Jobs are reported separately and never claimed as unlocked.

Learning priority is an explainable category, not an aggregate score. The exact
`skill-intelligence@1` policy first requires at least five Jobs, 40% usable-skill
coverage, and 40% current-Evaluation coverage. Below any threshold the result is
INSUFFICIENT EVIDENCE. HIGH then requires at least two required gaps plus either
two strict unlocks, or five required-demand Jobs and three required gaps. MEDIUM
requires at least two required-demand Jobs plus a gap/blocker, or at least one
strict/potential unlock. LOW requires another explicit gap/blocker, or two
preferred-demand Jobs plus a preferred gap. Remaining sufficiently evidenced
concepts are MONITOR. Components, thresholds, reasons, strengths, unknown
Profile areas, and unmapped terms are all returned directly. Pack M now owns
separate conservative salary groups and links back to Pack K for detailed skill
demand rather than changing this model.

The Track workspace exposes window, filter, and sort controls; the demand table;
Profile evidence; required gaps and UNKNOWN counts; strict/potential/multi-gap
unlock counts; priority explanations; strengths; unknown Profile areas; unmapped
terms; source-term drill-down; and provenance. Routes live below
`/api/jobhunt/tracks/{trackId}/skills/` for intelligence, concept detail,
unmapped terms, and metadata. Focused backend, HTTP, API-client, controller, and
DOM tests cover distinct-Job denominators, repeated mentions, manual mapping
precedence, ambiguity, Profile and Evaluation refresh, merge/unmerge,
current/historical populations, strict/potential unlocks, escaping, filters,
sorts, windows, empty state, and insufficient-data behavior.

## Implemented Pack L1 boundary

Pack L1 implements one additional source only: Jobbnorge through its official,
unauthenticated Public API v1. It does not fetch Jobbnorge vacancy pages, use the
separate Integration API, or add FINN, Alfred, OLX, No Fluff Jobs, company-site,
or generic email collection.

Implementation-time verification on 2026-09-24 used the official Swagger UI at
`https://publicapi.jobbnorge.no/swagger/index.html` and its v1 OpenAPI document
at `https://publicapi.jobbnorge.no/swagger/v1/swagger.json`. The selected route
is `GET https://publicapi.jobbnorge.no/v1/Jobs`. The documented controls are
county, municipality, category, employer, department, free-text term, order,
period, result count, page, abroad, and language. The schema exposes a stable
numeric job ID plus title, employer, location, summary, scope, duration,
deadline, public link, postcode, listing/promoted/internal flags, logo, and
position count. It does not expose a v1 single-vacancy route, publication time,
full description, requirements, skills, or contacts. The specification declares
no authentication scheme, rate-limit contract, ETag, or Last-Modified support.
A single bounded verification request for two results returned HTTP 200 without
conditional or rate-limit headers. That response advertised API versions 1,
2.0, and 3.0 in a response header; Pack L1 deliberately pins the inspected,
published v1 contract instead of guessing at a newer schema. The privacy reference remains
`https://www.jobbnorge.no/personvern`.

FINN was reviewed separately at `https://www.finn.no/api/`; its published APIs
are for advertisers/business partners with a business relationship and terms.
There is no documented public job-search API for this local personal use case,
so `source_finn` remains disabled and visibly unavailable. No workaround,
page scraping, browser automation, proxy rotation, or access-control bypass was
added.

Checksummed migration `12` permits the explicit `jobbnorge_api_derived` item
capture method and adds immutable generic collection-response captures,
listing-to-collection evidence links, persistent generic query/page cycle state,
and `jobbnorge_poll` to the existing worker constraint. Exact HTTP response
bytes are archived once as collection evidence. Because the API returns arrays
and offers no item endpoint, a matched item is also serialized into a clearly
labelled derived JSON capture. Its metadata links the collection capture hash,
array index, JSON Pointer, adapter/matcher versions, and stable source job ID;
the UI and API never mislabel those derived bytes as an exact HTTP response.

The adapter permits HTTPS requests only to `publicapi.jobbnorge.no/v1/Jobs`,
rejects redirects and unknown query keys, sends no credentials, and bounds
timeouts, response bytes, JSON depth/string/object/array sizes, page count,
jobs, requests, and per-cycle bytes. Default cadence is 30 minutes, concurrency
is one, request budget is 12, page size is 50, and at most three pages are read
per query. `403` stops permanently; `429`, timeout/network failures, and bounded
server errors use the existing persisted retry/backoff worker semantics and
honour `Retry-After`. Malformed bounded bodies are archived before the failure
is surfaced. The source is disabled by default and can be enabled, synced, or
paused independently from NAV and Pracuj.

Every observed result is a stable Jobbnorge Source Listing keyed by the official
numeric ID. Only listings conservatively matched to enabled Jobbnorge-bound
Search Profiles receive derived item captures and extraction work; uncertain
missing fields do not reject a candidate. One listing may retain several Search
Profile/Track discovery links. Deadline evidence can mark a listing expired;
absence from a bounded result page never implies removal. Deterministic
`jobbnorge_structured@1` extraction feeds the existing projection, dedupe,
Evaluation, and Skill Intelligence pipelines without source-specific workflow
fields. The official result schema contains no contacts, so no personal contact
data is collected by this adapter.

Operational routes expose status, query state, request observations, and narrow
enable/pause/sync commands. The Ingestion workspace shows authentication status,
adapter/policy version, cursor, last attempt/success, backoff, listing/match/item
capture counts, and exact-versus-derived provenance. Search Profile source hints
now distinguish available NAV, Pracuj, and Jobbnorge adapters from independently
unimplemented or unavailable sources.

Focused coverage lives in `tests/test_jobhunt_pack_l1.py`,
`tests/test_jobhunt_pack_l1_http.py`, `tests/jobhunt-pack-l1.test.js`, and the
synthetic `tests/fixtures/jobhunt/pack-l1-*.json` fixtures. Tests use injected
fake adapters only and cover schema/source defaults, host/query allowlists,
no-auth requests, pagination/bounds, exact collection bytes, derived evidence,
multi-profile matching, unmatched and expired listings, stable identity,
changed captures, malformed-body preservation, error/retry classification,
HTTP commands, status UI, escaping, and source availability. Live API access is
not part of automated tests.

## 1. Pre-Pack-A state

The verified implementation is a browser-only tracker:

```text
jobhunt.html
    |
    v
js/jobhunt.js
    |
    v
js/jobhunt-store.js
    |
    v
browser localStorage

index.html data-widget="jobhunt"
    |
    v
js/widget-jobhunt.js
    |
    +-- reads the same localStorage offers
```

The current storage keys are:

- `dashboard.jobhunt.offers`: canonical storage for the prototype's complete `JobOffer[]` array.
- `dashboard.jobhunt.matchSettings`: ten QA-oriented weighting settings.
- `dashboard.jobhunt.theme`: page-only light/dark preference.

There is no Job Hunt backend route, database, source collector, parser, AI integration, Career Profile, Track model, durable application-event history, or calculated matching engine. The current imported `match.score`, fit reasons, skill gaps, and CV advice are accepted as input and displayed; changing match settings does not recalculate them.

The page's displayed name/title ("Kamil" / "QA Tester") and greeting are hardcoded presentation, not stored Career Profile evidence, and must not be silently migrated as user answers.

### Existing behavior worth preserving

- Full page and compact dashboard summary widget.
- Manual offer creation, editing, deletion, and company-logo attachment.
- Standardized JSON import, validation warnings, duplicate hints, and JSON export.
- Search and filters for status, priority, and work model.
- Expiration dates, automatic expiration of non-terminal offers, and deadline presentation.
- Statuses, priorities, next actions, notes, recruiter details, application date, and follow-up date.
- One-click "applied" and follow-up actions.
- Best-match, pipeline, follow-up, next-action, and skill-gap summaries.
- Preservation and display of imported requirements, original advertisement text, imported match analysis, and CV suggestions.

`tests/jobhunt-store.test.js` verifies normalization, required-field validation, duplicate warnings, localStorage persistence, logos, expiration behavior, summaries, recommendation exclusion for expired offers, and the seven-day follow-up created on application.

### Current coupling to remove carefully

The prototype's single `JobOffer` object combines four different kinds of data:

1. external job facts (`company`, `role`, location, salary, requirements, original text),
2. user workflow (`status`, priority, follow-up, recruiter, notes),
3. candidate evaluation (`match`, flags, skill gaps), and
4. advice (`cv`).

It also uses strings such as `"unknown"`, default `0` scores, and `salary.isKnown` in ways that cannot reliably distinguish absent evidence from an explicit negative fact. Those shapes must remain readable during migration, but they must not become the long-term canonical domain model.

## 2. Product goals and non-goals

Job Hunt should become a personal career and labour-market intelligence system that can:

- describe the user's experience, skills, preferences, constraints, and assessment evidence;
- support several fundamentally different career strategies through Tracks;
- collect durable historical observations from independent sources conservatively;
- preserve and reprocess raw advertisements;
- extract facts without conflating them with candidate suitability;
- explain fit, blockers, unknowns, and skill gaps per Track;
- retain application history and measure outcomes;
- derive market, skill, source, Track, and application analytics from historical data;
- support career exploration and experiments without presenting personality results as destiny.

The architecture is not intended to:

- produce one opaque global score for incomparable career paths;
- scrape aggressively or bypass access controls;
- let an AI model invent missing facts or become the only parser;
- make one job board, one provider, or one model critical infrastructure;
- finalize a universal taxonomy before real data demonstrates the need;
- implement analytics before reliable historical data exists.

## 3. Domain boundaries

| Domain | Owns | Must not own |
| --- | --- | --- |
| Career Intelligence | Career Profile, skills, preferences, constraints, assessment runs, experiment evidence | Source advertisements or job-specific match results |
| Tracks | Career/search strategies, Track state, geography, relevant fields, evaluation policy references | Source-specific request mechanics |
| Search Profiles | Queries and filters used to discover jobs, plus source bindings | User personality or application history |
| Market Ingestion | Sources, Source Policies, Source Listings, Raw Captures, collection jobs | Candidate fit or CV advice |
| Extraction | Versioned Extraction Runs and source-grounded facts | User suitability decisions |
| Normalization | Canonical concepts and mappings while retaining source wording | Destructive rewriting of extracted evidence |
| Canonical Jobs | The best current factual representation of an opportunity | User score, gaps, preferences, or application stage |
| Evaluation | Career Profile x Canonical Job x Track results | Mutation of source facts or profile facts |
| Applications | Current stage, immutable events, contacts, follow-ups, notes, outcomes | Source parsing or Track policy |
| Review | Ambiguities, conflicts, proposed corrections, human overrides, audit trail | Silent automated replacement of confirmed values |
| Analytics | Derived, reproducible aggregates over historical data | Canonical truth edited by dashboards |

Core relationships are:

```text
Career Profile ----+                         +---- Source Definition
                   |                         |          |
Assessment Runs ---+--> Career Track         |     Source Policy
                          |                  |          |
                          +-- Search Profile +--> Source Listing
                          |                             |
                          |                         Raw Capture
                          |                             |
                          |                       Extraction Run
                          |                             |
                          |                        Extracted Facts
                          |                             |
                          |                        Normalization
                          |                             |
                          +----------------------> Canonical Job
                                                        |
Career Profile x Career Track x Canonical Job ----------+--> Evaluation
                                                        |
                                                        +--> Application
                                                               |
                                                               +--> Application Events
```

One Canonical Job may be associated with several Tracks. Several Source Listings may resolve to one Canonical Job. Neither relationship implies that one cross-Track percentage is meaningful.

## 4. Target architecture

The recommended layout follows the repository's feature-local database and complex-feature package conventions. `jobhunt_backend` avoids a Python name collision with the existing frontend naming and resembles `synchrobook_backend` and `language_learning` more closely than adding more domain logic to `server.py`.

```text
jobhunt.html + dashboard widget
              |
              v
js/jobhunt-api.js
              |
              v
/api/jobhunt/*
              |
              v
jobhunt_backend/
    service.py              orchestration and validation
    store.py                SQLite persistence boundary
    migrations.py           ordered, checksummed migrations
    models.py               domain DTOs/enums, not ORM entities
    jobs.py                 durable feature-local worker
    assessments/            immutable instrument manifests/scoring adapters
    ingestion/              source policy, discovery/fetch orchestration
    parsers/                deterministic and AI extraction adapters
    normalization/          evolving taxonomies and mappings
    sources/                one isolated adapter per external source

data/jobhunt.sqlite         mutable canonical/user state and run metadata
data/jobhunt/raw/           content-addressed source captures
data/jobhunt/assets/        bounded imported branding or future user assets
data/jobhunt/backups/       verified pre-migration/recovery backups
```

`server.py` should construct the service/worker, manage their lifecycle, enforce request-size/auth/origin rules, and translate narrow HTTP routes. It should not contain extraction, matching, dedupe, assessment scoring, or source-specific logic. Because `server.py` is already very large and uses explicit method branches rather than a framework, Pack A should add small Job Hunt dispatch helpers instead of either scattering many new branches or introducing a repository-wide router refactor.

### Repository patterns to reuse

- Finance: feature-local SQLite, transactional changes, pre-migration backups verified by hash, migration verification metrics, explicit review decisions, evidence-bearing suggestions, and manual source markers.
- Language Learning: ordered checksummed migrations; version/fingerprint metadata; persisted bounded jobs; transactional claiming; restart recovery; cancellation; provider adapters; prompt/model/usage provenance; explicit acceptance of generated candidates.
- Music: side-effect-free parsers; content-addressed raw files; import batches; staged rows; source observations separate from canonical entities; ambiguous matching that requires review; immutable historical snapshots.
- Synchrobook: feature-local worker lifecycle, resumable durable stages, progress visibility, and preservation of readable artifacts when later processing fails.
- BM365: durable outbound tasks and retry accounting. Job Hunt should improve on its in-memory retry timer by persisting `next_attempt_at` so backoff survives restart.
- Frontend API clients: one feature-local adapter with a fixed base URL, encoded IDs/query parameters, no-store reads, bounded JSON writes, and normalized error envelopes.

## 5. Data flows

### Manual import first

```text
Paste/upload advertisement
    -> ManualImportAdapter
    -> SourceListing (manual source identity)
    -> RawCapture (exact bytes/text, hashed)
    -> deterministic ExtractionRun
    -> extracted facts + evidence
    -> validation/normalization
    -> Canonical Job or Review Item
```

Manual import is the first ingestion adapter because it validates preservation, versioning, extraction, and review without external access risk.

### Live collection

```text
Scheduler
    -> persisted discover job
    -> Source Policy gate
    -> adapter.discover(SearchProfile)
    -> SourceListing upsert
    -> persisted fetch job
    -> Source Policy gate + conditional/cached request
    -> RawCapture
       -> unchanged hash: stop
       -> new hash: extraction pipeline
```

### Extraction and canonicalization

```text
RawCapture
    -> deterministic runs (API fields, JSON-LD, schema.org, source fields)
    -> optional AI enrichment run for unresolved unstructured content
    -> immutable extracted facts
    -> validation
    -> normalization mappings
    -> canonical projection
    -> review when ambiguity/conflict crosses policy thresholds
```

Extraction Runs and facts are append-only. The canonical projection may change, but the evidence that produced earlier projections remains available.

### Evaluation

```text
Career Profile version
        x
Canonical Job fact projection
        x
Track evaluation-policy version
        |
        v
Evaluation
  - skill fit
  - experience fit
  - preference fit
  - salary fit
  - geography fit
  - hard blockers
  - missing requirements
  - unknown requirements
  - explanations/evidence references
```

Profile changes enqueue evaluation recomputation only. They do not reparse advertisements. Extraction changes may invalidate job evaluations but never application history.

### Application history

```text
Command (apply, schedule follow-up, interview, reject, withdraw...)
    -> validate transition
    -> append ApplicationEvent
    -> update current Application projection in the same transaction
    -> refresh page/widget summaries
```

## 6. Career Profile architecture

Career Profile is versionable user state, independent of jobs and assessments. It should support:

- career facts: current title, experience records, domains, education, certifications, languages, and optional current/target compensation;
- skills: canonical concept, display wording, self-assessed level, interest in developing, confidence, timestamps, and evidence references;
- preferences: typed dimensions with value, importance, confidence, origin, and timestamps;
- constraints/dealbreakers: salary floor, geography, contract/schedule/work-model restrictions, relocation, and language constraints;
- evidence: manual statements, assessment results, application/experiment observations, and later imported records.

The initial schema should use typed core rows plus bounded JSON for low-maturity preference detail. It should not create a column for every conceivable preference. A profile revision or `updated_at`/fingerprint must be recorded in each Evaluation so results remain reproducible.

Unknown profile values remain unknown. A missing salary floor is not zero; a missing relocation preference is not refusal. Hard blockers require explicit user configuration or evidence, not an absent value.

## 7. Assessment architecture

Assessments are Pack B work and must be completed before live source collection. Definitions are versioned reference data; responses and results are mutable user data with immutable completed runs.

Recommended reference structure:

```text
jobhunt_backend/assessments/
    manifests/
        riasec/<instrument-id>/<version>.json
        ipip/<instrument-id>/<version>.json
        work-preferences/<instrument-id>/<version>.json
    schema.json
    scoring.py
```

Each instrument manifest should freeze:

- instrument ID/version and definition hash;
- title, purpose, locale, source URL/reference, license, attribution, and required notices;
- immutable question IDs/text/order, answer scale, reverse-keying, dimension mapping, and scoring version;
- validation rules and interpretation limits.

User persistence should represent `AssessmentRun`, `AssessmentResponse`, and `AssessmentScore` separately. Draft runs may be resumed. Completion freezes the instrument version, definition hash, responses, scores, scoring version, and completion timestamp. A retake creates a new run; it never overwrites a completed run.

Planned instruments:

- RIASEC: O*NET Interest Profiler or another authoritative instrument only after the exact form, distribution terms, attribution, and scoring rights are verified.
- Big Five: a specifically identified public-domain IPIP inventory. Proprietary NEO content is excluded.
- Career Work Preferences: a clearly labeled dashboard-native, non-diagnostic questionnaire with a versioned local definition.

Assessment results are evidence for exploration. UI and services may say that a result supports or conflicts with a Track hypothesis; they must not deterministically prescribe an occupation.

## 8. Career Tracks and Search Profiles

### Career Track

A Track is a user strategy, not a profession category. It owns:

- stable ID, name, purpose, status (`exploring`, `active`, `paused`, `archived`);
- geography/economic context;
- relevant field namespaces;
- an evaluation-policy reference/version;
- timestamps and optional user rationale.

The supplied initial concepts (`QA Poland`, `Kraków Weekend Work`, `Norway Physical Work`, `Norway QA`, `Iceland Physical Work`) are candidate seeds for user confirmation, not inferred answers.

### Search Profile

A Search Profile describes discovery intent: keywords, role families, exclusions, geography, work model, schedule, languages, contract hints, and source bindings. One Track has many Search Profiles. A Search Profile may be executed by several compatible source adapters. Source-specific pagination tokens and cursors belong to the adapter/binding state, not to the Track.

Example:

```text
Track: Norway Physical Work
    +-- warehouse Norway
    +-- production Norway
    +-- fish processing Norway
    +-- hotel Norway
    +-- cleaning Norway
    +-- construction helper Norway
```

Jobs may belong to multiple Tracks through explicit or rule-supported Track-job assignments. Track policies can emphasize different facts and produce separate trade-off views. An optional within-Track priority may be introduced later, but its components and policy version must remain visible.

## 9. Job-market ingestion architecture

### Source Adapter contract

The minimal conceptual contract is:

```text
discover(search_profile, cursor, policy_context)
    -> listing identities + hints + next cursor + request metadata

fetch(source_listing, policy_context)
    -> response metadata + exact content bytes + MIME type
```

Adapters do not create Canonical Jobs or Evaluations. They translate source mechanics into source-neutral discovery/fetch results. Adapter errors use a common classification such as authentication, rate limit, forbidden, robots/terms stop, CAPTCHA/WAF, transient network, malformed response, or permanent removal.

### SourceDefinition and SourcePolicy

`SourceDefinition` identifies a stable source and adapter/version. `SourcePolicy` is separately mutable operational state containing:

- access method and evidence that it is permitted;
- enabled/degraded/paused state;
- polling cadence, request budget, concurrency, cache/conditional-request rules;
- last attempt/success, failure counters, `backoff_until`, and last error class;
- terms and robots review timestamps/notes;
- source-specific retention or attribution requirements.

### SourceListing

SourceListing means "source X published listing Y". It retains the source listing ID, canonicalized and observed URLs, discovery hints, first/last seen timestamps, source activity/expiration state, and discovery Search Profile(s). It is never deleted merely because it was deduplicated or expired.

### RawCapture

RawCapture is one immutable observation of a SourceListing. SQLite stores hash, byte size, MIME type, retrieval/status metadata, source URL, timestamps, headers safe to retain, and relative raw path. Exact bytes live under a content-addressed path such as:

```text
data/jobhunt/raw/sha256/ab/cd/<full-hash>.html
```

The file is written safely, hashed again, and then referenced transactionally. Identical content reuses the blob and creates no unnecessary extraction work. Changed content creates a new capture and preserves all earlier captures. HTML, JSON, text, and email payloads are supported; extracted visible text can be a derived artifact linked to its source capture.

Retention and compression remain policy decisions, but database records must never point to a silently missing blob. Storage health should report missing/corrupt files.

### Source access policy

Use this hierarchy:

1. official API/feed,
2. official alert/email mechanism,
3. permitted public HTML,
4. browser automation only where appropriate and allowed.

Collection is low-volume, cached, and source-policy-aware. Start with concurrency one per source and conditional requests where supported. On `403`, `429`, CAPTCHA, WAF, or a terms/robots uncertainty, stop or sharply reduce that source, persist degraded/backoff state, and surface a review item. Do not rotate proxies, bypass CAPTCHA, evade blocks, or add stealth behavior.

NAV/Arbeidsplassen was selected for Pack G after re-verifying its current
`pam-stilling-feed`, terms, Bearer authentication, and recommended two-minute
tail cadence. A second source remains deferred until the same review at Pack I.

### Dedicated Job Hunt worker

Future ingestion uses a persisted `WorkerJob` queue with:

- type, payload/version, idempotency key, priority, status, stage/progress;
- attempt/max-attempt counts, `next_attempt_at`, error class/message;
- lease owner/expiry or equivalent crash-recovery state;
- cancellation request, parent/dependency reference where needed;
- created/started/completed/updated timestamps.

Start with one worker and bounded per-source concurrency. Claim work transactionally (`BEGIN IMMEDIATE` is an established local pattern). Startup recovery requeues expired leases below the attempt limit and fails exhausted jobs visibly. Retries use persisted exponential backoff with jitter and Source Policy limits. Cancellation is cooperative between network/model stages. Status is queryable through the service/API. The queue may run discovery, fetch, extraction, AI enrichment, normalization, dedupe, and reprocessing jobs, but is not implemented before its pack.

## 10. Parsing, AI, facts, and normalization

### ExtractionRun

Every parse attempt is an explicit immutable run linked to one RawCapture. Common fields include extractor kind/version, input hash, timestamps, state, validation result, error information, and output schema version. AI runs additionally record provider, adapter, model/version, prompt ID/version/fingerprint, request ID where safe, token/usage metadata, latency, and bounded attempt information.

Deterministic extraction precedes AI:

1. official API/feed fields,
2. JSON-LD and schema.org `JobPosting`,
3. structured metadata/source fields,
4. source-specific deterministic parsing,
5. AI enrichment for unresolved unstructured facts.

An AI provider adapter must return schema-constrained data, enforce input/output size and timeout limits, classify provider errors, and support a fake deterministic provider in tests. Provider output is untrusted until local validation completes. No automatic paid or alternate-provider fallback should occur without explicit configuration.

The primary AI instruction is factual: extract every supported fact in the advertisement, do not evaluate the candidate, and do not invent missing information. Canonical fact families should cover at least title, company, industry/domain, geography, salary range/currency/period/gross-net-unknown state, contract, employment fraction, schedule, shift work, work model, experience, education, languages, skills, tools, certifications, responsibilities, required versus preferred requirements, benefits, recruitment process, start date, and expiration date.

### Extracted facts and open facts

Facts are not flattened immediately into one job row. A fact can retain:

- type and optional normalized concept;
- source wording and typed value/unit/currency/period;
- polarity/state (`explicit_positive`, `explicit_negative`, `inferred`, `derived`);
- evidence reference (capture plus JSON pointer/DOM/text span or bounded excerpt);
- extraction method/run and confidence;
- validation and supersession status.

Recurring concepts get typed projections for querying. Track-specific concepts such as accommodation, rotation, overtime, travel reimbursement, PPE, car/licence requirements, or language sufficiency live in typed fact families or namespaced extensible facts, not dozens of nullable columns on `canonical_jobs`.

Unknown is represented by the absence of supported evidence or an explicit `unknown` projection state. It is never converted to `false`, `0`, an empty requirement, or "not required." "No Norwegian required" is explicit negative evidence; no mention of Norwegian remains unknown.

An open-fact shape preserves unexpected information:

```json
{
  "namespace": "source",
  "type": "other",
  "label": "Company transport",
  "value": "Bus from Bergen every Monday",
  "state": "explicit_positive",
  "confidence": 0.97,
  "evidenceRef": "..."
}
```

This is an extension seam, not a dumping ground. Review analytics should identify recurring open facts that deserve a typed concept.

### Normalization

Extraction preserves source wording; normalization maps it separately. For example, `REST`, `RESTful API`, `API testing`, and `Postman/API testing` may map to concepts related to `API_TESTING` while every original fact remains intact.

Taxonomies for skills, tools, programming languages, spoken languages, certifications, industries, role families, contracts, work models, and benefits start small. Each mapping records rule/version, confidence, source fact, and manual status. Human-approved mappings outrank automated mappings. Taxonomies grow from observed data and review needs, not an up-front attempt to model every occupation.

## 11. Provenance, review, correction, and deduplication

### Provenance

Important canonical fields must be explainable back to source evidence or an explicit derivation. A canonical projection records the selected fact(s), projection rule/version, and time. Conflicting facts remain stored; selection does not erase them.

Derived facts (for example annualized salary) reference their inputs and formula version. Inferred facts are visibly different from explicit claims. Confidence describes extraction reliability, not candidate fit.

### Review Queue

Review Items are first-class records with type, severity, entity references, evidence, candidate resolutions, state, assignment/timestamps, and resolution. Reasons include low confidence, salary conflict, location mismatch, duplicate uncertainty, unexpected fact, normalization ambiguity, source disagreement, corrupt/missing raw data, and source-policy degradation.

Human corrections are stored as explicit overrides with before/after values, reason, author (`local_user`), evidence/note, and timestamp. They do not rewrite immutable extraction output. Canonical projection checks active human overrides first. Reprocessing may propose a different value but cannot displace an active correction until the user intentionally changes or retires it.

### Staged deduplication

1. Exact `(source_id, source_listing_id)` identity.
2. Exact normalized URL/known external identity.
3. Deterministic company + title + location/time-window candidates.
4. Salary/date and normalized-description similarity.
5. Later semantic similarity only when enough labelled outcomes justify it.

An exact source identity is automatic. Strong cross-source matches may be automatic only under a versioned conservative rule. Ambiguous candidates create Review Items. Linking several Source Listings to one Canonical Job never deletes the listings/captures. Incorrect merges must be reversible and audited.

## 12. Applications

Application is separate from Canonical Job and carries the convenient current workflow state. ApplicationEvent is the append-only history used to reconstruct and audit that state.

Recommended stages include `discovered`, `saved`, `shortlisted`, `applied`, `screening`, `interview`, `technical`, `final`, `offer`, `rejected`, `withdrawn`, and `archived`. Pack A should publish an explicit mapping from every legacy status, including `to_review`, `worth_applying`, `follow_up`, and `expired`; source expiration and application outcome must not be conflated.

Events include stage changes, application sent, follow-up scheduled/sent, recruiter/contact changes, notes, interview scheduling, rejection reason, withdrawal, offer details, and archival. Current state and a new event are updated in one transaction. Follow-up projections can remain convenient, while the underlying scheduling/completion events are durable.

Deleting or expiring a Source Listing never destroys its Application. Reprocessing a Canonical Job never changes an Application or its events.

## 13. Job x user evaluation and skill intelligence

Evaluation is a versioned snapshot of Career Profile x Canonical Job x Track. It exposes independently inspectable dimensions, blockers, missing requirements, and unknown requirements. Each result records the profile fingerprint, job projection version, Track policy version, evaluator version, and explanations/evidence references.

There is no mandatory cross-Track score. Pack J requires every current policy to use `aggregate: none`; the UI sorts and filters only by transparent states/findings. Any future within-Track aggregate would require a separate explicitly approved design with visible components. International Track comparisons show a trade-off matrix (gross/net estimates, housing, food, transport, relocation, accommodation, savings potential, uncertainty) rather than naming an automatic winner.

Skill Intelligence is derived only after enough canonical jobs exist. Pack K now calculates per-Track demand frequency, explicit denominators/unknown rates, the user's current evidence, Pack J gap/unknown state, strict and potential jobs unlocked, and categorical learning priority. Original source terms and normalized concept mappings remain inspectable. Recommendations cite observed market demand, current findings, and uncertainty rather than generic advice. Pack M now provides salary association only within conservative currency, pay-period, and tax-type groups.

## 14. Analytics and career intelligence

Analytics are read models derived from durable records, not additional mutable truth.

- Market: listings/jobs over time, salary distributions, skills, work models, geography, companies, and language requirements.
- Source quality: discovered listings, fetch/extraction failures, duplicate rate, update rate, stale/expired rate, and review burden.
- Track: relevant supply, salary/economic dimensions, requirements, unknown rates, gaps, and evaluation distributions.
- Application: submissions, response/interview/offer rates, time to response, rejection reasons, source effectiveness, and Track effectiveness.

Every metric declares its population, time window, Track/source filters, unknown handling, and version where material. Source Listings and Canonical Jobs must not be double-counted accidentally.

Later Career Intelligence may suggest adjacent occupations, transferable skills, new Tracks, and Career Experiments using several evidence types: profile facts, skills, preferences, constraints, assessments, market demand, salary, learning effort, and experiment feedback. Personality alone is insufficient.

Career Experiments are later user-evidence records with hypothesis/Track, task definition/version, time spent, interest, difficulty, frustration, desire to continue, notes, and timestamps. Examples include a Playwright automation task, SQL analysis, or requirements specification exercise.

## 15. Persistence strategy

Use one feature-local canonical database: `data/jobhunt.sqlite`. Enable foreign keys, WAL, a busy timeout, bounded transactions, and explicit backups. Use ordered checksummed migrations like Language Learning, with pre-migration SQLite backups for destructive/high-risk changes and verification metrics like Finance.

Do not store arbitrarily large raw bodies in SQLite. Store immutable blobs content-addressed under `data/jobhunt/raw/`; keep hashes and metadata in SQLite. Do not store secrets, API keys, or unrestricted browser cookies in the database or frontend.

Conceptual entity ownership by pack:

| Entity family | First owning pack | Notes |
| --- | --- | --- |
| CanonicalJob, legacy payload/mapping | A | Minimal durable job facts and lossless prototype compatibility |
| Application, ApplicationEvent | A | Current projection plus immutable history |
| LegacyEvaluationSnapshot, compatibility settings | A | Preserves imported scores/gaps/advice without calling them calculated truth |
| CareerProfile, CareerSkill, preference/constraint evidence | B | Independent user domain |
| AssessmentInstrument metadata, Run, Response, Score | B | Definitions remain immutable reference manifests |
| Track, SearchProfile, Track-job assignment | C | Search intent and evaluation policy remain distinct |
| SourceDefinition, SourcePolicy, SourceListing, RawCapture | D | ManualImportAdapter only initially |
| ExtractionRun (deterministic), ExtractedFact, evidence, normalization mapping, ReviewItem, HumanOverride | E | AI-specific run metadata is added in F |
| AI extraction attempt/provider usage | F | Extends common ExtractionRun; does not fork canonical facts |
| Live source cursor/state and collection WorkerJobs | G onward | Same generic ingestion/worker model |
| DuplicateCandidate/merge audit | H | Source Listings remain intact |
| Evaluation | J (implemented) | Recomputable snapshots, separate from job/profile/application |
| Derived skill/analytics read models | K/M | Rebuildable from canonical history |
| CareerExperiment | M | Additional user evidence |

This is a boundary map, not final table-by-table SQL. Exact decomposition is decided immediately before the owning pack, against real queries and fixtures.

## 16. Backend, API, frontend, and legacy migration

### API boundary

Pack A should expose a narrow `/api/jobhunt/*` surface, for example:

```text
GET  /api/jobhunt/overview
GET  /api/jobhunt/jobs
GET  /api/jobhunt/jobs/{id}
POST /api/jobhunt/jobs
PATCH /api/jobhunt/jobs/{id}
GET  /api/jobhunt/applications/{id}
POST /api/jobhunt/applications/{id}/events
POST /api/jobhunt/migrations/local-storage
GET  /api/jobhunt/migrations/{id}
```

The exact resource list is finalized in Pack A. Commands that append events are preferred over accepting arbitrary replacement snapshots. Reads use stable envelopes and bounded pagination; writes validate size and unknown fields. Future packs add separate routes for profiles, assessments, Tracks, sources, review, worker jobs, and evaluations rather than one oversized payload.

`js/jobhunt-api.js` becomes the sole server adapter. Page and widget share it. `js/jobhunt-store.js` temporarily keeps pure formatting/compatibility and legacy migration readers, then loses canonical persistence responsibility. Avoid permanent dual-write: after a verified cutover, SQLite is authoritative and localStorage is recovery material, not a competing database.

### Idempotent localStorage migration

Pack A migration sequence:

1. Read but do not mutate the three known localStorage keys.
2. Validate and normalize a copy using a versioned legacy schema reader; retain unsupported fields in the raw legacy payload.
3. Compute a deterministic source fingerprint over the submitted offers/settings snapshot and include a client-generated idempotency key.
4. Send the bounded snapshot to the migration endpoint.
5. Before importing, the server stores a private, hash-verified recovery copy and records the migration fingerprint.
6. In one transaction, create minimal Canonical Jobs, Applications/events, legacy evaluation snapshots, settings compatibility rows, and legacy-ID mappings. Preserve legacy IDs where safe; otherwise retain them as unique external IDs.
7. Verify item counts, key field counts, IDs, hashes, and mappings. Return a per-item result and durable migration status.
8. Repeating the same request returns the recorded result. A changed payload is a new migration attempt and upserts only through explicit legacy identities/idempotency rules.
9. The client switches to API authority only after verification succeeds. It does not delete offers or match settings automatically. An explicit later cleanup/export action may retire recovery data.

Legacy mapping rules:

- job facts become the minimal Canonical Job projection;
- `originalText` and the entire original object remain recoverable even before Pack D;
- status, dates, recruiter data, follow-ups, and notes seed Application plus explicit migration events;
- imported/manual match score, flags, skill gaps, and CV advice become labelled `legacy_imported` evaluation/advice snapshots, never claimed as newly calculated results;
- match settings are preserved as compatibility configuration until Packs B/C/J offer a reviewed translation;
- bounded, valid logo data URLs are decoded to hash-named Job Hunt branding assets and linked from compatibility/canonical presentation data; invalid assets remain visible in the lossless migration report/raw payload rather than aborting unrelated records;
- `dashboard.jobhunt.theme` remains a browser UI preference and keeps its existing key.

Before migration or API availability, the legacy path remains operational. During cutover, the UI must show which authority is active. After cutover, an API outage should show a clear unavailable/stale state; it must not silently resume writable localStorage and create divergent histories. A read-only cached view is acceptable if clearly labelled.

## 17. Implementation packs

Packs are deliberately vertical and independently testable. No pack starts automatically after this design task.

### Pack A - Durable Job Hunt Core (implemented)

Deliver ordered migrations, verified backups, store/service, thin routes, frontend API adapter, minimal Canonical Job, Application/ApplicationEvent, legacy evaluation compatibility, and the idempotent migration above. Keep the existing page/widget behavior operational against the selected authority. Add focused Python/JS migration, route, store, application-event, and compatibility tests.

Acceptance: a copied legacy snapshot can be migrated repeatedly without duplication or loss; counts/hashes/mappings verify; current UI behaviors work from SQLite; application transitions append events; localStorage recovery remains untouched.

Excludes: assessments, Tracks, source ingestion, scraping, AI, live sources, new matching, and analytics.

### Pack B - Career Profile and Assessments (implemented)

Add Career Profile, skills, preferences, constraints, evidence, immutable instrument manifests, versioned assessment runs/responses/scores, history/retakes, and UI. Gate RIASEC/IPIP content on source/license verification. Implement dashboard-native work preferences as non-diagnostic.

Acceptance: completed runs cannot be edited or overwritten; retakes create history; exact definition/scoring versions reproduce scores; profile values preserve unknowns; results are presented as evidence, not prescriptions.

Implemented acceptance evidence: schema migration `2`, immutable checksummed
manifests, application- and database-level completion guards, revision snapshots,
resumable drafts, historical retakes, deterministic scoring tests, HTTP lifecycle
tests, and frontend interaction/error-state tests all pass. Source/license review
selected the verbatim O*NET 60-item Short Form and the public-domain IPIP-50;
proprietary NEO content is not included.

Excludes: Tracks, live market data, and job matching.

### Pack C - Career Tracks and Search Profiles (implemented)

Add Track lifecycle, user-confirmed seed Tracks, Track-specific field/evaluation policy references, Search Profiles, source-neutral query criteria, source bindings, Track-job assignments, and management UI.

Acceptance: a Track has several Search Profiles; one job may belong to several Tracks; pausing a Track does not delete history; no sophisticated fit score is introduced.

Implemented acceptance evidence: additive checksummed migration `4`, stable and
non-destructive seeds, validated lifecycle/criteria/source-hint APIs, durable
active/removed many-to-many assignments, centralized frontend adapter and
management UI, and focused backend/HTTP/DOM tests. Assignment is explicitly
relevance-only; no evaluation policy weights or matching engine exist.

### Pack D - Ingestion Core (implemented)

Add SourceDefinition/SourcePolicy, SourceListing, RawCapture, content-addressed archive/health checks, capture versioning, and `ManualImportAdapter`. Preserve exact input before parsing.

Acceptance: identical content is safely reused, changed content creates a new capture, blobs verify by hash, historical captures remain accessible, and no network source is used.

Implemented acceptance evidence: additive checksummed migration `5`, stable
source/policy seeds, non-destructive Pack C hint bindings, bounded synchronous
manual TXT/HTML/JSON ingestion, verified content-addressed private storage,
immutable capture history, explicit exact-repeat idempotency, health metrics,
local API/UI inspection, inert previews, and focused backend/HTTP/DOM/privacy
tests. Only the manual adapter exists and no external source is contacted.

### Pack E - Deterministic Extraction and Review (implemented)

Add the common deterministic ExtractionRun abstraction, API/JSON-LD/schema.org/source-field parsing, typed/open facts, evidence, explicit-negative/unknown semantics, validation, normalization foundations, Review Items, and Human Overrides.

Acceptance: fixtures prove deterministic facts and evidence, missing fields remain unknown, human corrections survive reprocessing, unexpected information is retained, and canonical projections are explainable.

Implemented acceptance evidence: additive checksummed migration `6`, four
versioned local deterministic extractors, hybrid immutable facts with stable
evidence, exact normalization mappings, fingerprinted projection history,
Review Items, active/retired Human Overrides, synchronous reprocessing and
idempotent exact reruns, narrow APIs, inspection/review UI, and focused Python/
JavaScript regression suites. No Pack F provider or later-pack capability was
introduced.

### Pack F - AI Job Parser (implemented)

Extend ExtractionRun with AI provider/model/prompt/usage metadata. Add schema-constrained factual extraction, bounded retries/cost controls, open facts, reprocessing, local validation, and review integration. Test first against manually imported real advertisements and deterministic fake providers.

Acceptance: AI never writes Evaluation/Application/Profile data; every run is versioned; invalid/missing claims do not become facts; old runs remain comparable; no model/provider is required for deterministic parsing.

Implemented acceptance evidence: additive checksummed migration `7`, a common
AI ExtractionRun extension plus attempt history, provider-neutral/fake/fixed
Gemini adapters, versioned prompt/schema fingerprints, strict evidence and typed
value validation, bounded retries/input/response/usage/cost controls, explicit
deterministic precedence and Review integration, Human Override preservation,
safe status/extraction APIs, privacy-labelled UI/history, and focused mocked
Python/HTTP/DOM tests. No worker or external job source was introduced.

### Pack G - First Live Source (implemented)

Add the durable Job Hunt worker/queue and one conservative official source adapter, preferably NAV/Arbeidsplassen after implementation-time access verification. Validate discover -> listing -> fetch -> capture -> extraction -> canonical projection end to end.

Acceptance: persisted cadence/backoff, bounded concurrency, crash recovery, cancellation/status, unchanged-hash short circuit, and degraded-source behavior are tested. No access-control bypass exists.

Implemented acceptance evidence: additive checksummed migration `8`, persisted
single-daemon queue with transactional claims/leases/recovery/idempotency/backoff,
the exact-host NAV `pam-stilling-feed` adapter, backend-only explicit token and
enablement gates, conditional resumable feed state, two-stage Search Profile
filtering, UUID identity and inactive preservation, exact Raw Captures,
automatic `nav_structured@1` extraction through Pack E projection/review,
source/worker APIs and UI, and offline fake-adapter Python/HTTP/DOM tests. No
second source, cross-source dedupe, matching, skills, or analytics was added.

### Pack H - Deduplication (implemented)

Add staged exact/deterministic candidate generation, duplicate review, audited merge/unmerge, and conservative automatic thresholds.

Acceptance: duplicate Source Listings are retained, ambiguous cases wait for review, wrong merges are reversible, and analytics has a documented SourceListing-versus-CanonicalJob denominator.

Implemented acceptance evidence: additive checksummed migration `9`, versioned
bounded exact/deterministic policy, durable candidates and decisions, conservative
audited automatic merges, transactional manual merge, resolvable absorbed aliases,
Application/Track/Override safety, reversible current-evidence reprojection,
post-projection worker scans, narrow API/UI, explicit denominator semantics, and
focused backend/HTTP/frontend regression coverage. No Pack I or later capability
was introduced.

### Pack I - Second Source (implemented)

Select NoFluffJobs or Pracuj only after access/terms review. Implement it as an independent adapter using the same contracts, raw archive, extraction, policy, worker, and dedupe flow.

Acceptance: disabling either source leaves the system functional; cross-source observations can resolve to one Canonical Job; no source-specific fields leak into global workflow logic.

Implementation-time access review selected Pracuj.pl's user-requested JobAlert
email as the permitted collection boundary. The official
[saved-search help](https://pomoc.pracuj.pl/hc/pl/articles/221006447-Co-to-jest-zapisane-wyszukiwanie)
documents email notifications and their frequency. The current
[Pracuj terms](https://grupapracuj.pl/file/754f924c-62f3-47ba-8717-d7fbaddf06af)
and [privacy hub](https://grupapracuj.pl/prywatnosc) were reviewed through the
official Grupa Pracuj sites, but no clear permission for automated offer-page
retrieval was identified. No Fluff Jobs was rejected for this pack because its
[published terms](https://nofluffjobs.com/wp-content/uploads/2019/10/2019_09_20_Terms_and_Conditions-HU-EN-PL.docx.pdf)
prohibit repeated or systematic downloading of job advertisements. Pack I therefore performs no
Pracuj web search, crawl, page fetch, click-through automation, or No Fluff Jobs
collection.

Implemented acceptance evidence: additive checksummed migration `10`; the
independent `pracuj_jobalert` source adapter and `pracuj_jobalert@1` deterministic
parser; backend-only TLS IMAP configuration; read-only mailbox selection and UID
`PEEK` operations; a bounded 30-day/500-message bootstrap; persisted
UIDVALIDITY/cursor/counters/errors; headers-first filtering; conservative sender,
return-path/message-ID/authentication metadata checks; exact private RFC822
archive blobs; stable Pracuj listing identity; repeated-message idempotency and
capture history; optional subject-to-Search-Profile bindings; and automatic use
of the existing extraction, projection, review, dedupe, merge, and unmerge flow.
The source is disabled by default, password values never enter browser responses,
and template drift, UIDVALIDITY changes, TLS/authentication, timeout, and mailbox
failures stop or back off visibly. Synthetic fixtures cover plain, HTML,
multipart, quoted-printable, base64, multi-job, repeated, unrelated, spoofed,
missing-Message-ID, changed-template, oversized, tracking-URL, and NAV/Pracuj
cross-source cases. At the completion of Pack I, Pack J had not yet started.

### Pack J - Explainable Track Evaluation Engine (implemented)

Create versioned, explainable Career Profile x Canonical Job x Track Evaluations with independent dimensions, blockers, gaps, unknowns, and within-Track policy. Keep legacy imported scores as separately labelled historical compatibility snapshots.

Acceptance: profile changes recompute evaluations without reparsing; job reprocessing does not touch applications; different Tracks can evaluate the same job differently; no mandatory global magic score exists.

Implemented acceptance evidence: additive checksummed migration `11`; immutable
versioned Track policies, Evaluations, dimensions, findings, and history;
fingerprinted currentness; `evaluator@1` deterministic rule modules; explicit
UNKNOWN/GAP/BLOCKER semantics; exact skill and CEFR handling; conservative
experience, salary, geography, work-model, contract, schedule, and relocation
comparisons; evidence references; bounded idempotent work on the Pack G queue;
Profile/Job/Track/merge/unmerge hooks; safe APIs; Job and Track Evaluation UI;
policy editor/history; legacy-score separation; and focused backend/HTTP/DOM
regression coverage. No aggregate score, AI matching, skill-market intelligence, new
source, FX/economic comparison, or application automation was introduced.

### Pack K - Skill Intelligence (implemented)

Add per-Track skill demand, source-term-to-concept transparency, user gaps, unknown-aware denominators, learning priority, and estimated jobs unlocked.

Acceptance: every statistic has a population/window, mappings are reviewable/versioned, and learning priorities trace to observed jobs rather than generic advice.

Implemented acceptance evidence: bounded versioned live read model
`skill-intelligence@1`; current and historical 30/90/180-day Track populations;
distinct Canonical Job denominators; source-mix and fact/requirement coverage;
manual-over-deterministic mapping precedence with ambiguous and unmapped terms
preserved; exact type-safe Career Profile evidence; current Pack J finding reuse;
UNKNOWN distinct from GAP; strict, potential, and multi-gap unlock sets; categorical
HIGH/MEDIUM/LOW/INSUFFICIENT DATA priorities with visible components/reasons;
strengths and unknown Profile areas; narrow APIs and Track workspace drill-down;
and focused backend/HTTP/DOM regression coverage. No schema migration, persisted
aggregate, worker rebuild, AI inference, salary association, source adapter,
cross-Track score, or Pack L/M functionality was introduced.

### Pack L - Additional Sources (partially implemented: L1 Jobbnorge)

Add OLX, FINN, Alfred, Jobbnorge, company sites, or email alerts one adapter at a time, each with an approved Source Policy and operational tests.

Acceptance: each source can be enabled, degraded, paused, and removed independently; source health and cost/review burden are visible.

Pack L1 implements Jobbnorge only through the official Public API v1, with
exact collection-response evidence, derived item provenance, conservative
Search Profile matching, bounded persistent polling, and independent controls.
The other listed adapters remain unimplemented. FINN is currently marked
unavailable because the reviewed official API program requires a business
relationship and does not document public job-search access.

### Pack M - Analytics and Career Intelligence (implemented)

Add market/salary/application/source/Track analytics, international economic trade-offs, adjacent-career suggestions, Career Experiments, and evidence-backed Track proposals.

Acceptance: metrics are reproducible and unknown-aware; comparisons show trade-offs; suggestions cite multiple evidence types; experiments add evidence without rewriting assessments/profile history.

Implementation boundary:

- `jobhunt_backend/analytics.py` owns rebuildable `market-analytics@1`,
  `salary-analytics@1`, `source-analytics@1`, `application-analytics@1`,
  `track-analytics@1`, and `track-tradeoff@1` read models. Windows are exactly
  30/90/180/365 days or all retained history. Queries are bounded at 5,000
  Canonical Jobs and 10,000 Source Listings. Pack M does not persist these metrics.
- Market flow uses distinct deduplicated `CanonicalJob` identities and reports
  observed-window and current-snapshot populations separately. Coverage reports
  known, unknown, and denominator for salary, work model, location, language,
  experience, certification, education, schedule, and driving licence. Detailed
  skill/tool demand remains Pack K-owned and is linked rather than duplicated.
- Salary groups are comparable only by currency, period, and gross/net/unknown
  tax type. Three observations are required before medians are presented; five
  are required for quartiles. Bounds/midpoints are never currency-converted and
  no outlier is silently removed.
- Source analytics count `SourceListing` discovery, linked Canonical Jobs,
  within-source duplicate consolidation, unique contribution, cross-source
  overlap, request/extraction failures, latency, health, and review burden.
  Overlap is not labelled waste. Application analytics use the submitted
  application population, captured-at-application Track/discovery-source
  attribution where available, ApplicationEvent evidence for response/stage
  timing, explicit censored counts, and a five-application low-sample flag.
- Migration 13 persists only durable user state: application attribution,
  immutable/versioned manual `economic-scenario@1` values with current pointers,
  explicit Track-proposal decisions/events, and Career Experiments/events.
  Economic assumptions require field provenance. Net values are always labelled
  estimates with model/year/jurisdiction/deductions/source/date; FX is manual and
  dated. Partial scenarios retain unknown costs. There is no live FX/tax/cost API.
- Track trade-offs compare 2-5 Tracks row-by-row. They expose current/observed
  supply, salary samples, scenario net/cost/remainder, language evidence,
  Evaluation gaps/unknowns, application funnels, relocation, and uncertainty.
  `winner` is deliberately `null`; no aggregate career score exists.
- `career-adjacency@1` groups current roles deterministically by normalized title
  family. It requires at least three recurring jobs plus explicit Profile
  skill/language/certification overlap, cites Canonical Jobs, concepts, sources,
  geography, current Pack J gaps/unknowns, and never uses assessments or
  preferences to generate/rank a direction. `career-intelligence@1` creates a
  stable proposal hypothesis only with at least three evidence types and never
  creates a Track until explicit acceptance through the existing Track service.
- Career Experiments support manual, Track, proposal, template, and Pack K skill
  origins; planned/active/completed/abandoned states; task-definition versions;
  planned/actual time; ratings; notes; and provenance. Completion observations
  are immutable. Later interpretation is append-only. Profile changes require a
  separate confirmed action, are limited to reviewed skill/preference records,
  and record `career_experiment` origin. Assessments are never rewritten.
- API routes cover market/source/application/trade-off and per-Track analytics,
  scenario history/writes, adjacency/proposals, experiment templates/CRUD and
  narrow transitions. The routed `Insights` workspace has Market, Sources,
  Applications, Track trade-offs, Career Intelligence, and Experiments; every
  Track has an Analytics tab. Home/widget receive only compact signals.
- Focused backend, HTTP, DOM, route, API, Track, UX, and widget tests cover Pack M
  contracts, including empty/insufficient states and escaping. Representative
  tests keep the live-query design; materialization was not justified.

Explicit exclusions remain: no new job source, scraping, embedding, external
LLM, automatic application/CV submission, generic course search, political
recommendation, personality-only career advice, global score, or Track winner.

### Compact roadmap

| Pack | Outcome | Depends on | Explicitly not included |
| --- | --- | --- | --- |
| A | Durable core, migration, applications/events | This design | Assessment, ingestion, AI |
| B | Career Profile and assessments | A | Tracks, matching |
| C (implemented) | Tracks and Search Profiles | B | Sophisticated matching |
| D (implemented) | Manual ingestion and raw preservation | A | Live scraping |
| E (implemented) | Deterministic facts, provenance, normalization, review | D | AI parser |
| F (implemented) | Versioned AI factual enrichment | E | Candidate evaluation |
| G (implemented) | First conservative live source and worker | C, F | Multiple sources |
| H (implemented) | Reversible staged dedupe | G | Premature semantic-only merge |
| I (implemented) | Independent Pracuj JobAlert email source | H | Broad source rollout and job-page retrieval |
| J (implemented) | Explainable Track-specific evaluation | B, C, canonical jobs | Global magic score |
| K (implemented) | Market-driven skill intelligence | J, sufficient market data | Generic learning advice |
| L1 (implemented) | Jobbnorge official Public API v1 adapter | I, source policy evidence | Job pages, Integration API, or another source |
| L2+ | Remaining independent adapters | L1, separate source policy evidence | Access-control bypass |
| M (implemented) | Analytics, comparisons, discovery, experiments | Accumulated B-L history | Unsupported prescriptions |

## 18. Dependency graph

```text
                         +--> B Career Profile + Assessments --> C Tracks/Search Profiles --+
                         |                                                              |
A Durable Core ----------+                                                              +--> G First Live Source
                         |                                                              |           |
                         +--> D Ingestion --> E Deterministic/Review --> F AI Parser ----+           v
                                                                                                  H Dedupe
                                                                                                     |
                                                                                                     v
                                                                                                  I Second Source --> L More Sources

B + C + canonical jobs from E/G/I
                |
                v
          J Evaluation Engine
                |
                v
       K Skill Intelligence

A application history + B/C/J/K + accumulated market/source history
                |
                v
      M Analytics + Career Intelligence
```

The intended delivery order remains A through M. The graph identifies logical prerequisites, not permission to overlap implementation without an explicit pack request.

## 19. Architectural invariants

1. Raw source material is preserved.
2. No important source information is discarded merely because the current schema lacks a field.
3. UNKNOWN is different from FALSE.
4. Job facts are separate from candidate evaluation.
5. Career Profile is separate from jobs.
6. Application history is separate from job facts.
7. Extraction runs are versioned.
8. Automated facts should remain traceable to evidence where feasible.
9. Sources are isolated adapters.
10. Tracks may use different evaluation policies.
11. One job may belong to multiple Tracks.
12. Human corrections override automated interpretation.
13. Historical expired jobs remain useful data.
14. The system must not depend critically on one job board.
15. The system must not depend critically on one AI provider/model.
16. Live collection must remain conservative and source-policy-aware.
17. AI parsers must not invent missing facts.
18. Career assessments support exploration but do not dictate career decisions.
19. Reprocessing jobs must not alter application history.
20. Changing Career Profile must not require reparsing source advertisements.

## 20. Risks and mitigation direction

| Risk | Mitigation direction |
| --- | --- |
| localStorage migration loses or duplicates user data | Preserve raw snapshot, hash-verified backup, idempotency key/fingerprint, legacy IDs, transactional import, per-item mapping, before/after verification, and no automatic deletion |
| Prototype semantics cannot map cleanly | Store lossless legacy payload and labelled compatibility snapshots; require explicit mapping tables and review rather than guessing |
| `server.py` grows further | Keep domain logic in `jobhunt_backend`; add bounded dispatch helpers only; no repository-wide router refactor inside a Job Hunt pack |
| Raw archive grows without bound | Content addressing, byte counters/health, optional compression, configurable retention after evidence requirements are understood; never prune referenced last copies silently |
| Source HTML/API changes | Version adapters/parsers, fixtures from retained captures, validation thresholds, failure/degraded state, and reprocessing from raw |
| Anti-bot restrictions or source ToS changes | Official-source preference, reviewed Source Policies, low cadence/concurrency, stop/backoff on block signals, periodic terms/robots review, no bypass tooling |
| API rate limits | Persist request budgets/backoff/next-attempt state, cache and conditional requests, source-specific scheduling, visible health |
| AI hallucination or malformed output | Fact-only prompt, schema-constrained output, deterministic-first extraction, local validation, evidence requirement, unknown preservation, review thresholds |
| AI/API cost grows | Manual/deterministic first, explicit provider policy, per-run usage, daily/monthly budgets, bounded retries, cached/reusable results, no automatic paid fallback |
| Normalization drift | Version mappings/taxonomies, retain source wording, regression fixtures, reindex without reparsing, human overrides |
| Taxonomy explosion | Start from observed facts, promote recurring open facts, governance/review metrics, avoid speculative global vocabularies |
| False dedupe merges unrelated jobs | Staged conservative rules, source records retained, ambiguous review, merge audit and reversible unmerge |
| Duplicates fragment analytics | Exact identifiers first, duplicate-candidate queue, explicitly defined metric denominators, later semantic aids only with labelled data |
| Stale/expired jobs distort current views | Separate source lifecycle from historical retention; use first/last seen and explicit activity state; time-window every current-market metric |
| Assessment licensing/attribution is wrong | Pack B gate requires exact instrument/version/source/license review; keep manifests and attribution; exclude proprietary NEO material |
| Worker crashes or duplicate execution | Durable states, transactional claim, idempotency keys, persisted lease/backoff, bounded attempts, startup recovery, stage visibility |
| Schema evolution breaks evidence | Ordered checksummed migrations, backups, foreign keys, compatibility readers, migration tests, append-only runs/events |
| Human correction is overwritten | Separate active override layer with audit; projection precedence tests; reprocessing only proposes conflicts |
| Overengineering before real data | Manual imports and minimal taxonomies first; pack acceptance gates; defer semantic dedupe, broad sources, and materialized analytics until data volume justifies them |

## 21. Open decisions

These are genuine later choices; everything else above is the recommended default.

| Decision | Recommended default | Alternatives/trade-off | Decide by |
| --- | --- | --- | --- |
| Exact SQLite table decomposition | Split durable identities/history (jobs, listings, captures, runs, facts, applications/events) and use JSON only for bounded low-maturity details | Fewer JSON-heavy tables are faster initially but weaken constraints/queryability; highly normalized tables cost migration effort | Detailed design for each owning pack, starting A |
| Generic facts representation (resolved) | Hybrid: typed fact row with typed scalar columns plus bounded JSON payload for complex/open values and evidence | JSON-only would weaken validation/queryability; per-fact-type tables would cause taxonomy/schema churn | Resolved in Pack E |
| Raw archive compression/retention | Keep deduplicated originals uncompressed initially; add measured compression and never delete the last referenced capture | Immediate compression saves space but complicates inspection/recovery; timed deletion reduces evidence | Pack D after representative imports |
| IPIP inventory length (resolved) | Exact public-domain IPIP 50-item Big-Five Factor Markers inventory, local version `1.0.0` | A longer inventory may improve reliability but increases abandonment; changing instruments requires a new immutable manifest/version | Resolved in Pack B |
| RIASEC instrument (resolved) | Exact English O*NET Interest Profiler Short Form, 60 items, version `2018-05`, verbatim under CC BY-ND 4.0 with required attribution | Any adaptation or translation would require separate rights review and a new version; none is included | Resolved in Pack B |
| Track evaluation-policy representation (resolved) | Bounded versioned declarative dimensions/blockers/thresholds with code-owned `evaluator@1` semantics; no generic rule language | Fully hardcoded policies would be harder to inspect; a generic rule language would add unsafe complexity | Resolved in Pack J |
| Legacy match-settings translation (resolved for Pack J) | Preserve unchanged as labelled compatibility settings; never translate automatically | A later explicit reviewed migration could create a `legacy_reviewed` policy version, but Pack J does not invent that mapping | Resolved in Pack J; revisit only on explicit request |
| Semantic dedupe threshold/model | Do not enable initially; add only after reviewed duplicate/non-duplicate examples exist | Embeddings may catch cross-source rewrites but add cost, opacity, and false merges | Pack H or later, based on labelled volume |
| First live-source cadence (resolved) | NAV defaults to 120 seconds at the feed tail, immediate persisted traversal between existing pages, concurrency 1, conditional requests, a 100-detail per-page budget, and persisted backoff | Operators can set a slower cadence and smaller bounded budget through backend environment configuration | Resolved in Pack G after official NAV documentation/terms review |
| Second live source (resolved) | Pracuj.pl official user-requested JobAlert email only; no offer-page retrieval | Email templates can drift and email coverage follows the user's saved alerts, but the boundary is explicit, low-frequency, and avoids prohibited bulk page retrieval | Resolved in Pack I after access/terms review |
| Pack L1 source (resolved) | Jobbnorge official unauthenticated Public API v1 `GET /v1/Jobs`; exact array responses plus derived item evidence | The public result schema is intentionally shallow and has no single-item route, so full advertisement details are not invented or fetched from pages | Resolved in Pack L1 after official Swagger/privacy review |
| FINN access (resolved for Pack L1) | Keep disabled and unavailable; do not implement against partner APIs or pages | Official API access is for business partners and no public job-search API was documented for this use case | Re-review only if FINN publishes suitable official access |
| Worker process boundary (resolved) | In-process single daemon worker with persisted leases/idempotency and a source-neutral service/store boundary | A separate process remains possible if AI/network work later harms API responsiveness | Resolved in Pack G; revisit only with operational evidence |
| Evaluation aggregate (resolved) | `aggregate: none`; sort/filter only by transparent findings, blocker/gap/unknown counts, or individual dimensions | A future aggregate requires a separate explicitly approved design because one number hides unknowns and invites invalid cross-Track comparison | Resolved in Pack J |
| Analytics materialization (resolved for Packs K/M) | Pack K and Pack M compute bounded live read models over indexed canonical state; representative Pack M tests do not justify materialization | Early materialization improves speed but creates invalidation/version burdens | Resolved for Pack M; revisit only with measured production evidence |

## 22. Delivery and integrity checks for this roadmap

- Current page, store, widget, and Job Hunt tests were inspected.
- All three localStorage keys and the prototype's combined data model were verified.
- Finance migration/evidence/review, Language migration/job/Gemini, Music raw-source/versioning, Synchrobook worker, BM365 retry, frontend API client, and `server.py` route/lifecycle patterns were inspected.
- Career Profile, assessments, Tracks, Search Profiles, Source Listings, Canonical Jobs, Raw Captures, Extraction Runs, facts, evaluations, and applications have explicit boundaries.
- Deterministic parsing precedes AI; unknown/false, provenance, normalization, dedupe, review, source policy, and durable work are explicit.
- Packs A through M have scopes, dependencies, acceptance direction, and exclusions.
- The original roadmap task created documentation only. Packs A-K, L1, and M now supply the durable database, migration/API cutover, Career Profile, versioned assessments, Career Tracks, Search Profiles, manual job assignments, durable source metadata, Source Listings, immutable raw captures, ManualImportAdapter UI, deterministic Extraction Runs/facts/evidence, exact normalization, canonical projections, Review Items, Human Overrides, optional versioned AI factual enrichment, the durable worker, the explicitly enabled NAV live-source pipeline, reversible deterministic deduplication, the independently pausable Pracuj JobAlert email pipeline, immutable explainable Track-specific Evaluations, bounded market-driven Skill Intelligence, the independently pausable Jobbnorge official Public API pipeline, and Pack M analytics/economic scenarios/career hypotheses/proposals/experiments. Remaining Pack L2+ sources remain unimplemented.
