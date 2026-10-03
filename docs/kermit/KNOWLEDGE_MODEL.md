# Kermit knowledge model

Status: conceptual model; Phase 3 L2 index, Phase 4 retrieval, Phase 6 grounding, and Phase 7 local service/UI exist. Phase 8 expands static L1 coverage; Phase 9 page context remains unimplemented.

## 1. Goal

Kermit should understand the dashboard as a set of owned subsystems, contracts, transformations, and evidence sources rather than as an undifferentiated directory of files. Knowledge is layered so common architectural questions can be answered from concise curated material while precise implementation questions can retrieve selected source evidence.

The model must not receive the entire repository in every prompt. The eventual retrieval layer selects only the smallest relevant evidence pack within explicit item, byte, and token budgets.

## 2. Knowledge layers

### L0 — high-level inventory

Primary source: `PROJECT_MAP.md`.

L0 answers orientation questions:

- Which pages, widgets, services, stores, workers, integrations, and tests exist?
- Which subsystem appears to own a route or database?
- Which areas are fragile or privacy-sensitive?
- Which repository patterns should detailed documentation reuse?

L0 is authoritative for the current high-level inventory, not every implementation detail. It should route retrieval to a subsystem rather than be expanded into a duplicate Kermit inventory.

### L1 — detailed subsystem documentation

L1 contains curated, current knowledge packs for individual subsystems or bounded cross-cutting mechanisms. It explains responsibilities, flow, ownership, formulas, recovery, and relevant source locations in human-readable form.

L1 should answer most “how does this work?” questions without source-code retrieval. It must distinguish current facts, intended contracts, known exceptions, and future proposals. Each pack follows the field contract below and links back to L0 identifiers.

### L2 — machine-readable indexes and metadata

L2 makes known relationships deterministic and searchable. Possible records include:

- subsystem/page/widget/module identifiers and aliases;
- source files, symbols, imports, and ownership;
- frontend entry points and `data-widget` registrations;
- API routes, methods, handlers, clients, and response ownership;
- stores, schema versions, storage roles, and owning services;
- workers/jobs, queues, triggers, restart policies, and artifacts;
- metrics, rule versions, formulas, units, and input fields;
- integrations, direction, credentials boundary, and failure mode;
- tests linked to contracts and source symbols;
- document status, source class, fingerprints, and supersession/conflict links.

L2 is generated or curated metadata, not a new source of implementation truth. It must carry provenance back to L0/L1/source evidence and be rebuildable.

### L3 — selected source-code retrieval

L3 provides bounded excerpts from allowlisted current source code, configuration contracts, schemas, and focused tests. It is used when L1 lacks precision, when the question asks for relevant source files, or when a claim needs verification.

Retrieval should target symbols, route branches, definitions, or short spans—not whole large files. Source comments and literals are untrusted content. Source retrieval never imports or executes code.

L3 can verify implementation truth but does not automatically explain intent or runtime state. Tests can support behavior claims while their coverage limits remain visible.

### L4 — optional controlled runtime read-only data

L4 is absent initially. It may later provide narrowly defined, privacy-reviewed observations through purpose-built read adapters—for example, a bounded health/status summary or provenance for one explicitly identified record.

L4 answers “what is true now for this allowed runtime value?” It does not replace code as the authority for calculations or L1 as the authority for intended ownership. Every observation includes adapter ID, operation, storage role, timestamp, limits, and redaction status.

There is no generic runtime file, SQL, or API layer. Each L4 capability is separately authorized and independently removable.

## 3. Layer selection

The retrieval strategy should begin with the least detailed sufficient layer:

1. Use L0 to identify likely subsystem ownership and terminology.
2. Use L1 for the detailed explanatory path and declared contracts.
3. Use L2 to resolve identifiers and relationships and to locate evidence.
4. Use L3 only for precise behavior, verification, conflicts, or source references.
5. Use L4 only when the question genuinely asks for approved current state and the adapter is authorized.

Higher layer numbers do not universally outrank lower ones. Authority depends on the claim type as defined in `SOURCE_POLICY.md`.

## 4. Detailed subsystem documentation contract

Each L1 knowledge pack should contain the following fields. A field may say “none,” “not implemented,” or “unknown”; it should not be silently omitted when the distinction matters.

### Identity and status

- stable subsystem ID and display name;
- document status and last verification date/revision;
- current, proposed, historical, legacy, or mixed status;
- owning feature/domain and related L0 entry;
- concise purpose and non-goals.

### Responsibilities and boundaries

- responsibilities owned by the subsystem;
- responsibilities explicitly owned elsewhere;
- public contracts and architectural invariants;
- trust, privacy, and authorization boundaries.

### Frontend

- page and widget entry points;
- `data-widget`, IDs, routes, and lazy-loading registration where applicable;
- controllers, view modules, API clients, browser stores, and relevant localStorage keys;
- loading, empty, error, review, stale, and compact-card behavior;
- user actions and which ones are read versus mutation.

### Backend and APIs

- backend entry points, services, repositories/stores, and handler boundaries;
- exact API routes and methods;
- request/response ownership and important schema/version contracts;
- authentication/origin/privacy controls and payload limits;
- external service boundaries.

### Persistence and storage roles

- canonical storage and owner;
- schema/migration/version mechanism;
- caches and generated state;
- raw archives and preserved source evidence;
- backups and migration/recovery inputs;
- legacy compatibility sources;
- browser-only state and synchronization semantics;
- explicit source of truth for each important entity.

### Inputs, transformations, and outputs

- inputs and their provenance;
- validation, normalization, identity/deduplication, enrichment, and review stages;
- outputs and consumers;
- rejected/quarantined data behavior;
- an ordered data-flow narrative.

### Formulas and metrics

- metric name, purpose, units, and display formatting;
- exact formula or algorithm;
- input fields and source owners;
- grouping, filtering, time zone, date boundaries, and null/unknown handling;
- rule/source/model version;
- cache/materialization behavior;
- edge cases and focused tests.

“Calculated by the backend” is not sufficient documentation for a metric.

### Jobs and integrations

- job/worker name and trigger;
- queue/lease/idempotency model where present;
- attempts, timeouts, backoff, cancellation, and concurrency;
- artifacts and state transitions;
- startup recovery, interrupted-work behavior, and restart semantics;
- external provider, direction of data flow, credentials boundary, and rate/failure handling.

### Dependencies and failure behavior

- upstream and downstream subsystem dependencies;
- expected degraded modes;
- common failure modes and observable symptoms;
- stale/partial/inconsistent state behavior;
- recovery responsibility and whether recovery is automatic, manual, or intentionally absent.

### Evidence

- relevant source files and symbols/routes;
- tests and what contract each test covers;
- related current documentation;
- known documentation/code conflicts or unresolved questions.

## 5. Core conceptual entities

L2 should use explicit entity types rather than relying only on chunks:

| Entity | Meaning |
| --- | --- |
| Subsystem | Bounded feature or cross-cutting mechanism with an owner |
| Page | Standalone frontend entry point |
| Widget | Dashboard component, usually identified by `data-widget` |
| Module/Symbol | Source file and optional named implementation unit |
| API operation | Method + route + handler/client relationship |
| Store | Persistence component with an explicit storage role |
| Data artifact | File/table/snapshot/archive/cache with provenance and role |
| Transformation | Validation, parsing, calculation, mapping, or projection step |
| Metric | Named calculation with inputs, units, rules, and version |
| Job/Worker | Deferred/background processing and its lifecycle |
| Integration | Boundary with another service/device/application |
| Test contract | Evidence that a behavior or boundary is covered |
| Document | Curated evidence with scope and status |
| Conflict | Two evidence items making incompatible claims |

Relationships should be directional and typed: “owns,” “calls,” “reads,” “writes,” “generates,” “caches,” “imports,” “processes,” “renders,” “tests,” “supersedes,” and “conflicts with.” A relationship includes its evidence source.

## 6. Storage-role vocabulary

Kermit must represent storage roles explicitly:

- **canonical:** current owned runtime truth;
- **cache:** disposable acceleration or remote mirror;
- **generated:** reproducible projection/report/index;
- **raw archive:** preserved input or source capture;
- **backup:** recovery point, not active state;
- **migration input:** transitional material used to establish current state;
- **legacy:** compatibility or historical source outside current ownership;
- **browser-only:** state whose authoritative scope is the browser unless documented otherwise.

One artifact may have a role relative to a specific subsystem; that context should be recorded. Kermit must not flatten all files under `data/` into equivalent evidence.

## 7. Fact status and uncertainty

Each claim should be traceable to evidence and classified where useful:

- **verified implementation:** supported by current source and, ideally, tests;
- **documented current contract:** stated by current documentation but not source-verified for this answer;
- **runtime observation:** returned by an approved adapter at a timestamp;
- **proposed:** future design, not implemented;
- **historical/legacy:** previously true or retained for compatibility;
- **inferred:** reasoned from evidence but not stated directly;
- **unknown/conflicted:** insufficient or contradictory evidence.

The answer generator should not upgrade documented, inferred, or proposed claims to verified implementation. Missing values remain missing; Kermit does not guess formulas, ownership, confidence, or recovery behavior.

## 8. Retrieval units and context limits

Knowledge should be split on meaningful boundaries such as a document section, symbol, route, metric definition, job lifecycle, or data-flow step. Fixed-size text chunks may be a fallback but should retain their parent entity and locator.

An evidence pack should:

- include only sources relevant to the question and context;
- prefer authoritative and current material for the claim type;
- include both sides of known conflicts;
- include adjacent context needed to avoid misleading excerpts;
- cap repetitions and large-file dominance;
- reserve room for citation metadata and uncertainty;
- never include denied sources simply to fill context.

Page/component context improves ranking but does not filter out other evidence when a question crosses subsystem boundaries.

## 9. Example reasoning path

For “Where does the number in the Finance widget come from?” a future flow could be:

1. L0 maps the widget to its frontend module, Finance API, services, and canonical Finance SQLite store.
2. L1 supplies the widget's data flow and the metric's documented definition.
3. L2 resolves the exact widget renderer, client operation, route, service method, metric entity, and tests.
4. L3 retrieves only those source spans to verify the current calculation and formatting.
5. L4 is unnecessary unless the user asks for their current numeric value and an approved Finance adapter exists.

The answer cites each transformation and labels the SQLite store canonical. It does not inspect receipts, imports, backups, or the live database merely because they are nearby.

## 10. Maintenance model

L0 and L1 are reviewed documentation. L2/L3 indexes are rebuildable derivatives with source fingerprints and indexer versions. Staleness checks compare admitted sources to indexed revisions. L4 observations are never persisted as timeless knowledge without a separate, approved retention design.

A subsystem change should update its owning code/tests and relevant current documentation through the normal development workflow. Kermit may report suspected staleness but never edits or regenerates authoritative sources autonomously.
