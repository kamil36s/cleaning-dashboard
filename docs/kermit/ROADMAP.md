# Kermit implementation roadmap

Status: Phases 0–7 complete within their documented pilot scope; Phase 1 contracts documented; Phase 7.1 automatic local service startup complete; Phase 8 knowledge expansion in progress; Phase 9 and later product phases not implemented.

## Roadmap principles

- Every phase is independently reviewable, removable, and useful without assuming later phases.
- A phase grants only the capabilities listed in that phase.
- Read-only enforcement precedes model or runtime access.
- Interfaces are versioned before deployment topology changes.
- Derived indexes are rebuildable and are never a source of truth.
- Current implementation facts, future design, runtime observations, and persona are kept separate.

## Phase 0 — Repository discovery / PROJECT_MAP

**Status:** COMPLETE

**Objective:** Establish a current high-level inventory of the dashboard without creating Kermit runtime behavior.

**Deliverables:** `PROJECT_MAP.md` covering pages/widgets, backend domains, persistence, workers, AI/ML, imports, integrations, tests, patterns, and fragile areas.

**Prerequisites:** Repository access and existing project instructions.

**Explicit non-goals:** Detailed Kermit design, exhaustive per-subsystem documentation, retrieval, indexing, model integration, UI, or runtime access.

**Acceptance criteria:** The map can route a reader to major owners and clearly distinguishes canonical, generated, cached, raw, backup, migration, and legacy material.

**Risks:** Inventory drift and mistaking high-level documentation for exact implementation truth.

**Rollback/removal:** The map remains useful project documentation even if Kermit is abandoned; no runtime component exists to remove.

## Phase 1 — Kermit architecture and contracts

**Status:** DOCUMENTED BY THIS FOUNDATION; NOT IMPLEMENTED

**Objective:** Define Kermit's scope, component boundaries, knowledge layers, source authority, read-only security contract, and phased delivery plan.

**Deliverables:** The six documents under `docs/kermit/`.

**Prerequisites:** Phase 0 and review of relevant current architecture/privacy precedents.

**Explicit non-goals:** LLM/provider selection, embeddings, vector search, API, UI, database, service, packages, indexes, or runtime data access.

**Acceptance criteria:** Documents consistently state that Kermit is a system explainer, define all required components and deployment stages, structurally prohibit mutation, and separate current facts from future design.

**Risks:** Paper controls may be mistaken for implemented controls; premature technology choices may constrain later phases.

**Rollback/removal:** Delete `docs/kermit/`; dashboard behavior and data remain unchanged.

## Phase 2 — Detailed subsystem knowledge documentation

**Objective:** Create reviewed L1 knowledge packs for a small representative set of subsystems before designing automated retrieval.

**Status:** COMPLETE FOR FOUR L1 PILOTS; NO RUNTIME IMPLEMENTATION

**Deliverables:** A documentation template based on `KNOWLEDGE_MODEL.md`; pilot packs covering at least one widget-only flow, one canonical SQLite-backed feature, one worker/job flow, and one external integration; a gaps/conflicts register.

**Prerequisites:** Phase 1 contracts and named subsystem owners/scopes from L0.

**Explicit non-goals:** Whole-repository redocumentation, generated indexes, model calls, live runtime reads, or source/data changes.

**Acceptance criteria:** Each pilot documents ownership, routes, storage roles, transformations, metrics, jobs/restart semantics, privacy, tests, and source references; sampled claims are verified against current code.

**Risks:** Documentation becomes stale, duplicates L0, or records aspirations as facts.

**Rollback/removal:** Packs can be removed independently; retain the template and gaps register if useful. No application rollback is needed.

## Phase 3 — Machine-readable system indexes

**Status:** COMPLETE FOR FOUR PILOTS; OFFLINE DERIVED ARTIFACTS ONLY

**Objective:** Build reproducible L2 metadata that connects known entities and evidence without exposing private or generated repository content.

**Deliverables:** Versioned index schemas; positive admission manifest; parsers for approved documents/source metadata; relationship records; source fingerprints; deterministic build and validation reports; tiny synthetic fixtures.

**Prerequisites:** Phase 1 source/security policies and enough Phase 2 packs to validate the model.

**Explicit non-goals:** Semantic/vector search, model integration, arbitrary repository crawl, runtime database indexing, or serving API.

**Acceptance criteria:** Rebuilding the same revision is deterministic; every record has provenance; denied paths and seeded fake secrets are absent; stale fingerprints are detectable; indexes can be deleted and rebuilt.

**Risks:** Over-broad admission, parser drift, false relationships, large-file bloat, or derived metadata being treated as truth.

**Rollback/removal:** Delete generated indexes and disable the builder. Source documentation/code remain untouched.

## Phase 4 — Read-only retrieval layer

**Status:** COMPLETE FOR FOUR PILOTS; OFFLINE RETRIEVAL ONLY

**Objective:** Retrieve bounded evidence from L0–L3 under deterministic policy, before adding a model.

**Deliverables:** Query contract; metadata/text retrieval implementation; evidence-pack schema; citation IDs/locators; conflict and freshness handling; path and content limits; adversarial and privacy tests.

**Prerequisites:** Validated Phase 3 indexes, allowlist, and structural controls from `READ_ONLY_SECURITY.md`.

**Explicit non-goals:** LLM answers, chat UI, runtime data, shell/file browsing, arbitrary SQL/HTTP, or model-selected tools.

**Acceptance criteria:** A test harness returns relevant evidence for representative questions; all results belong to the admission manifest; traversal/injection/secret tests fail closed; retrieval makes no source changes.

**Risks:** Poor relevance, missing conflict evidence, prompt-injection content, or policy bypass through paths/links.

**Rollback/removal:** Remove the retrieval service/artifacts and keep static docs/index schemas. No dashboard dependency exists.

## Phase 5 — Local LLM prototype

**Status:** COMPLETE AS LOCAL MODEL PROTOTYPE / MODEL BAKE-OFF. `qwen3.5:4b` is the selected interactive draft baseline: 15/15 valid envelopes and 14/15 manually grounded raw answers. The cross-system answer inverted Quote's external-provider relationship despite citing supplied evidence. Raw drafts are untrusted and require Phase 6 before display; Gemma, Phi, and Mistral remain benchmark artifacts.

**Objective:** Evaluate whether a locally hosted model can explain bounded evidence through a provider-neutral service boundary.

**Deliverables:** Model-provider interface; one local provider adapter; deterministic fake provider; bounded prompt/envelope; timeouts and size limits; offline evaluation set; CLI or test-harness prototype outside the dashboard UI.

**Prerequisites:** Phase 4 evidence packs and security review confirming the model has no tools or direct data access.

**Explicit non-goals:** Production service availability, dashboard UI, embeddings by default, persona customization, runtime adapters, autonomous behavior, or mutation.

**Acceptance criteria:** Prototype answers representative questions using supplied evidence, returns provider metadata, cannot access files/network/tools beyond its configured inference endpoint, and degrades safely on timeout or invalid output.

**Risks:** Hallucinations, context overflow, weak local-model quality, hardware latency, provider lock-in, or accidental prompt disclosure.

**Rollback/removal:** Remove the provider adapter/model files and retain fake-provider evaluations and retrieval. No frontend contract depends on the model yet.

## Phase 6 — Grounding, citations, uncertainty handling

**Status:** COMPLETE for the scoped static four-pilot prototype. The 15-case saved-real-draft replay passes; Quote inversion stays blocked. Reviewed finding metadata binds independent documentation/code sides for F-01 and L-01, and correctly types the other six findings. No direct finding query remains register-summary-only.

**Objective:** Make answer claims traceable and make missing, stale, conflicting, historical, or proposed evidence visible.

**Deliverables:** Versioned GroundedAnswer and atomic Claim schema; deterministic claim extraction and support checks; service-bound citations; claim/evidence semantic evaluation set; conflict rendering rules; uncertainty/status vocabulary; stale-index behavior; hallucinated-citation rejection.

**Prerequisites:** Phase 5 prototype and source-status/provenance metadata from Phases 2–4.

**Explicit non-goals:** UI polish, live runtime facts, persona, automated doc correction, or claims unsupported by retrieved evidence.

**Acceptance criteria:** Every displayed factual sentence maps to supported evidence or explicit conflict/uncertainty; citations reference only relevant retrieved evidence IDs; documented discrepancies retain independent primary side citations; test gaps and scoped semantics are not forced into factual conflicts; unsupported questions yield explicit limits; proposed/historical content is never presented as current implementation. The local 15-case final factual gate passes.

**Risks:** Superficial citations that do not support claims, overconfident synthesis, or excessive refusal despite adequate evidence.

**Rollback/removal:** Fall back to the Phase 4 evidence viewer/test harness; remove model answer generation without losing indexes.

## Phase 7 — Dashboard chat UI

**Status:** COMPLETE for the scoped local static-evidence chat. The 2026-09-29 provider regression was traced to comparison-list claim extraction and broad provider matching, corrected generically, and verified through real Quick and Normal browser-panel calls on 2026-09-30. The unrelated Normal citations were removed from model-facing projection without relaxing validation. See `PHASE7_CHAT_UI.md`.

**Objective:** Add an optional dashboard interface using a stable, versioned Kermit API contract.

**Deliverables:** Chat panel/page; provider-neutral frontend client; configured service endpoint; loading/error/unavailable states; citation and conflict display; accessible keyboard/focus behavior; content-safety rendering; feature flag/removal path.

**Prerequisites:** Phase 6 answer contract, frontend privacy review, and an endpoint configuration design.

**Explicit non-goals:** Direct model/browser connection, feature mutation controls, silent background conversations, page-context capture, or LAN migration.

**Acceptance criteria:** Dashboard works unchanged when Kermit is disabled/unavailable; UI sends only the question, selected profile, and explicit YELLOW confirmation; output is rendered as untrusted content; no answer can trigger an application action.

**Risks:** XSS/link abuse, UI coupling, accidental question logging, endpoint misconfiguration, or users mistaking explanations for executed actions.

**Rollback/removal:** Disable/remove the isolated UI and client registration; Kermit service remains independently testable and dashboard features remain intact.

## Phase 7.1 — Automatic local service startup

**Status:** COMPLETE for the normal local Windows dashboard launch paths. See `PHASE7_1_STARTUP.md`.

**Objective:** Make the lightweight loopback Kermit HTTP service available when the dashboard starts, without loading the model or requiring a separate terminal.

**Deliverables:** A bounded status/identity probe and readiness check in the trusted launcher; reuse of a healthy instance; optional `KERMIT_AUTOSTART`; conflict and failure diagnostics; isolated failure behavior.

**Prerequisites:** Phase 7 service status contract and normal dashboard launchers.

**Explicit non-goals:** Model warmup, index rebuild, runtime data access, LAN exposure, dashboard feature changes, or changing the independent Live Workout runtime.

**Acceptance criteria:** Repeated launches reuse a healthy Kermit service; an unrelated port occupant is left alone; the dashboard loads if Kermit cannot start; status exposes sleeping/unavailable model and current/stale index; no launcher cleanup kills manual or automatically started Kermit processes.

**Risks:** A stale index still requires a deliberate trusted rebuild; a process already on port 8767 may be unidentifiable; detached local service lifetime requires explicit administration.

**Rollback/removal:** Set `KERMIT_AUTOSTART=false` or remove the isolated launcher hook. The independent service and dashboard continue to work separately.

## Phase 8 — Incremental knowledge expansion

**Focused approved usability addition:** Unified intelligent conversation is implemented as a server-routed `/api/kermit/v1/chat` endpoint and one browser conversation. It adds bounded in-memory continuity, general chat, grounded follow-ups, clarification, and hypothetical project discussion without expanding source admission or private runtime access. The original knowledge expansion and `knowledge/COVERAGE.md` ledger remain in progress. See `UNIFIED_CHAT_ROUTING.md`.

**Status:** IN PROGRESS; first batch and remaining scope are tracked in `knowledge/COVERAGE.md`.

**Objective:** Extend reviewed, detailed static knowledge beyond the four pilot packs (Quote, Finance, Language Learning, Weather) toward coverage of the implemented dashboard.

**Deliverables:** Complete current-implementation coverage inventory and independently reviewable batches; L1 packs for selected subsystems; corresponding explicit Phase 3 admissions; Phase 4 retrieval and Phase 6 grounding regressions; deterministic maintenance checks for newly uncovered features, changed admitted sources, stale packs, missing references, and outdated dependencies. Reviewed documentation and index rebuilding remain deliberate operations, separate from serving.

**Prerequisites:** Existing L1 template, Phase 3 positive admission, Phase 4 retrieval, and Phase 6 grounding. Each pack must first be verified against current implementation. Page/component context is not required.

**Explicit non-goals:** Bulk repository indexing, automatic admission expansion, private runtime data as ordinary static knowledge, retraining the model, or undocumented behavior treated as implemented.

**Acceptance criteria:** Each batch is independently reviewable. Each added pack documents ownership, routes, storage roles, transformations, jobs, privacy, tests, and source evidence; admission stays narrow; index and retrieval are validated after deliberate rebuild; grounding regressions pass; stale or conflicting sources fail closed. The phase remains open until planned coverage is documented, indexed, and validated.

**Risks:** Documentation drift, overly broad source admission, source conflicts, and confusing planned features with implemented features.

**Rollback/removal:** Remove a pack and its admission entries, then explicitly rebuild and validate the derived index. Existing pilot knowledge remains usable.

## Phase 9 — Page and component context awareness

**Objective:** Improve retrieval with minimal typed context about the page or component the user is viewing.

**Status:** PLANNED; NOT IMPLEMENTED.

**Deliverables:** Versioned context envelope for current page, active widget, and supported component identifier; stable page/widget/component identifier registry; sanitization and minimization rules; context-aware retrieval tests; UI disclosure of shared context.

**Prerequisites:** Phase 7.1 startup, Phase 7 UI, Phase 3 entity identifiers, sufficient validated Phase 8 knowledge coverage for each supported page and widget, and a privacy review of every context field. Unsupported pages remain question-only.

**Explicit non-goals:** Arbitrary DOM capture, screenshots, form contents, private records, credentials, personal data harvesting, automatic questions, or context as factual authority or permission.

**Acceptance criteria:** Context improves benchmark relevance for pages/widgets whose knowledge is covered; only allowlisted identifiers are transmitted; removing context yields normal question-only operation; forged context cannot expand access.

**Risks:** Sensitive entity IDs, unstable DOM coupling, cross-page leakage, or ranking bias toward an irrelevant current page.

**Rollback/removal:** Stop sending the optional context envelope; the Phase 7 contract continues to work.

## Phase 10 — Persona and Kermit visual design

**Status:** PLANNED; NOT IMPLEMENTED.

**Objective:** Add the intended local Kermit the Frog mascot and adjustable response presentation after factual behavior is stable.

**Deliverables:** Bottom-right avatar with sleeping, loading, thinking/generating, ready, resource-pressure, and error/unavailable states; animations and accessible reduced-motion behavior; typed personality, verbosity, and technical-depth settings; prompt separation tests; reset/default behavior and accessibility review.

**Prerequisites:** Stable factual behavior and citation enforcement from Phase 6, the Phase 7 UI, and review of mascot artwork and usage rights before distribution.

**Explicit non-goals:** User-authored system prompts, capability grants, source-policy overrides, fabricated identity/history, persona-controlled retrieval, or new model capabilities.

**Acceptance criteria:** The same evidence yields factually equivalent claims and identical citation bindings across presentation settings; malicious persona text cannot alter security rules; all visual states map to actual service/resource states; defaults work without customization.

**Risks:** Persona instructions weakening uncertainty language, hiding conflicts, increasing prompt-injection surface, confusing style with knowledge, or inaccessible animation.

**Rollback/removal:** Remove customization and avatar assets; the neutral Phase 7 panel, knowledge, service, grounding, and security contracts remain intact.

## Phase 11 — Weekly Analyst (separate batch workload)

**Status:** PLANNED; NOT IMPLEMENTED.

**Objective:** Produce scheduled, evidence-grounded weekly insights as `workloadClass = batch`, independent of interactive Quick/Normal requests and their model/resource settings.

**Deliverables:** User-configurable weekly schedule, batch model, permitted duration, approved data domains, and report structure; narrowly scoped user-authorized read-only snapshot producers for only the approved domains and fields; minimized, immutable, versioned snapshots; deterministic analytics; domain analyses; cross-domain grounded synthesis; factual verification; uncertainty and data-quality reporting. A trusted deterministic scheduler may launch the preconfigured job; the LLM cannot choose schedules, run commands, fetch additional data, or write results itself.

**Prerequisites:** Phase 6 grounding and continuous security controls. The approved snapshot readers are a prerequisite *within this phase*; broader Phase 12 private context is not required. Select the batch model and resource policy through benchmarks on the actual host, not an assumption that a 16 GB desktop can run any large model.

**Explicit non-goals:** Generic SQL, arbitrary filesystem or application API access, interactive-profile coupling, model-directed jobs, unrestricted personal-data ingestion, or mandatory second-computer execution.

**Acceptance criteria:** A configured Sunday-night job can collect approved weekly snapshots, compute deterministic metrics, perform bounded grounded synthesis, verify factual claims, and deliver a Monday report; missing/poor data and unsupported claims remain visible. The workload can run for several hours within its configured limit without blocking interactive Kermit or ordinary dashboard features.

**Optional experiment:** Compare desktop alone against desktop plus laptop as independent batch workers. Measure total elapsed time, per-worker throughput, network overhead, memory pressure, practical power consumption, and report quality. Parallel workers are adopted only if a controlled benchmark shows a benefit; distributed inference is not part of this phase's required path.

**Risks:** Excessive memory/time use, scheduler overlap, stale or sensitive snapshots, cross-domain inference, model hallucinations, and a report that appears more certain than the evidence.

**Rollback/removal:** Disable the schedule and snapshot producers, revoke their read permissions, and remove retained batch artifacts according to policy. Interactive Kermit and the dashboard remain usable.

## Phase 12 — Expanded private and runtime context

**Status:** PLANNED; NOT IMPLEMENTED.

**Objective:** Add only separately authorized, purpose-built L4 readers for broader explanatory questions and optional private project history, beyond the narrow Weekly Analyst snapshot producers.

**Deliverables:** Per-adapter threat model and privacy contract; fixed operation/response schema; read-only credentials or immutable snapshots; field redaction and row/byte/time limits; observation timestamps and storage roles; privacy-safe audit metadata; negative mutation tests; kill switch.

**Prerequisites:** Mature Phase 6 grounding, deployed security controls, and a concrete user-approved question for each adapter. Weekly Analyst's approved snapshots do not implicitly authorize any broader reader.

**Explicit non-goals:** Generic filesystem/database/API access, credentials in prompts, write endpoints, autonomous monitoring, bulk personal-data indexing, or implicit access to all feature stores.

**Acceptance criteria:** Each adapter answers only its named questions; mutations and arbitrary queries are structurally impossible; private fields are minimized; source hashes/state are unchanged after adversarial tests; disabling an adapter removes access cleanly.

**Optional future private history source:** A locally exported ChatGPT conversation archive may, after separate explicit user authorization and privacy review, support bounded read-only questions about project origins, earlier alternatives, discussions, and evolution. It is private, disabled by default, excluded from static L0–L3 knowledge and automatic indexing, and contextually/historically authoritative only. Current source code governs claims about current implementation. This plan grants no present archive access, parsing, indexing, or adapter.

**Risks:** Privacy disclosure, SQLite side effects, stale observations, inference across datasets, over-broad schemas, or read credentials that secretly allow writes.

**Rollback/removal:** Revoke adapter credentials, unmount snapshots, disable registration, and remove retained derived observations according to policy. Static Kermit remains functional.

## Phase 13 — Security, maintenance, and observability

**Status:** CONTINUOUS from the first implemented code; formal production-readiness gates planned.

**Objective:** Maintain production-quality safety, quality measurement, operations, and knowledge freshness across every selected phase without creating autonomous model actions.

**Deliverables:** Threat-model review; capability and adversarial suites; retrieval/answer regression benchmarks; dependency/security review; structured privacy-safe metrics; index freshness diagnostics; backup/removal runbooks; version compatibility policy; maintenance ownership and review cadence. Apply controls continuously, then require formal gates before sustained or broadened deployment.

**Prerequisites:** Only the phases actually selected for long-term use; hardening scope matches deployed capabilities. This work runs alongside Phases 7.1–12 and is not postponed until they finish.

**Explicit non-goals:** Self-modification, automatic source/doc edits, autonomous remediation, uncontrolled telemetry, public exposure, or silent capability expansion.

**Acceptance criteria:** Security invariant suite passes; protected assets remain unchanged end to end; citations and retrieval meet agreed benchmarks; stale/failed components are visible; upgrades and rollback are rehearsed; logs contain no secrets/private evidence.

**Risks:** Maintenance burden, dependency vulnerabilities, evaluation drift, sensitive logging, operational complacency, or tests that verify prompts instead of capabilities.

**Rollback/removal:** Maintain component-level kill switches and a documented uninstall order: private adapters, batch readers/jobs, persona, UI, model, retrieval service, indexes. Static documentation can remain or be removed independently.

## Phase 14 — OPTIONAL final laptop/home-server migration

**Status:** OPTIONAL; NOT COMMITTED OR IMPLEMENTED. Last phase only if a measured need justifies it; no hardware purchase is assumed.

**Objective:** If chosen, move Kermit service/model from the current desktop to an HP EliteBook laptop or dedicated home server without changing frontend semantics or the provider-neutral service contract.

**Deliverables:** Configurable service base URL; approved repository snapshot/index synchronization; authentication and origin policy; network isolation and firewall guidance; TLS/transport decision; health/version diagnostics; migration and fallback runbook.

**Prerequisites:** Stable service API, measured resource needs, formal production-readiness gates, and LAN threat review. No earlier product phase depends on migration.

**Explicit non-goals:** Public internet exposure, shared writable repository mounts, copying private runtime data by default, changing dashboard feature ownership, or enabling LAN binding as part of Phase 7.1.

**Acceptance criteria:** The same API works locally and remotely; only approved static snapshots/indexes reach the remote host; unauthorized LAN clients are rejected; reverting the endpoint restores the desktop deployment while source admission, grounding, read-only security, and authentication remain intact.

**Risks:** LAN eavesdropping, host compromise, stale synchronized indexes, CORS/auth errors, endpoint spoofing, or service discovery complexity.

**Rollback/removal:** Restore the previous configured endpoint and remove remote snapshots/model artifacts. Indexes remain rebuildable; no application data migration is required.

## Dependency summary

The local product sequence is cumulative. Security work applies continuously; remote deployment is a last, optional decision:

```text
Phase 0 -> Phase 1 -> Phase 2 -> Phase 3 -> Phase 4 -> Phase 5 -> Phase 6
    -> Phase 7 -> Phase 7.1 -> Phase 8 -> Phase 9 -> Phase 10 -> Phase 11
    -> Phase 12 (separate authorization) -> Phase 14 (OPTIONAL migration)

Phase 13 security, maintenance, and observability: continuous across all phases,
with formal production-readiness gates before broadened or remote deployment.
```

Phase 11 includes only the approved read-only snapshots needed for weekly reports and does not require Phase 12's broader private context. Phase 10 presentation cannot change evidence or capabilities. Phase 14 is optional and last; none of Phases 8–13 requires moving Kermit to another computer.

## Decisions intentionally deferred

- Which Phase 8 batches after the first should be scheduled next, as tracked in `knowledge/COVERAGE.md`?
- What latency and hardware budget should select the first local model?
- Is deterministic lexical/metadata retrieval sufficient before embeddings are considered?
- If migration is ever chosen, what authentication and transport policy should protect a LAN-hosted Kermit endpoint?
- Once Phase 8 coverage is sufficient, which current page/component identifiers are useful without disclosing personal state in Phase 9?
- Which runtime questions, if any, justify a Phase 12 adapter beyond Weekly Analyst's approved snapshots?
- Does a controlled desktop-versus-desktop-plus-laptop batch experiment improve weekly elapsed time and report quality enough to justify the added complexity?
- What retention policy, if any, should apply to questions, answers, and diagnostics?
