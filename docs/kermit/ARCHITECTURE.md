# Kermit architecture

Status: target architecture; the Phase 7 local static service/UI and Phase 7.1 automatic startup are implemented. Runtime adapters and remote deployment remain future work.

## 1. Architectural intent

Kermit is a read-only explanatory subsystem adjacent to the dashboard. It can eventually answer questions from curated documentation, machine-readable indexes, selected source code, and narrowly allowlisted runtime readers. It is not part of any feature's write path and is not an operational control plane.

The design has four invariants:

1. The dashboard remains fully usable without Kermit.
2. Kermit has no mutation capability, even if a model asks for one.
3. The frontend speaks one stable Kermit API contract regardless of deployment location or model provider.
4. Evidence, source authority, citations, and implementation status are preserved across every layer.

## 2. Component boundaries

### A. Dashboard application

The existing Vite frontend, Python services, feature stores, workers, and integrations remain the system being explained. They own all feature behavior and state. Existing application APIs are not automatically Kermit APIs.

The dashboard may provide the Kermit UI with a minimal context envelope containing identifiers such as page, `data-widget`, visible route, and selected entity type. It must not pass arbitrary DOM text, credentials, form contents, personal records, or mutation tokens by default.

### B. Kermit frontend/chat UI

The future chat UI collects questions and displays answers, citations, uncertainty, evidence age, and service status. It communicates only with the Kermit API through a versioned client adapter.

It must not:

- call the model provider directly;
- read repository files or databases;
- call dashboard mutation endpoints;
- derive permissions from model output;
- treat current-page context as factual evidence.

### C. Kermit API/service

The Kermit service is the policy and orchestration boundary. It validates requests, normalizes page context, requests evidence from retrieval, constructs bounded prompts, invokes the configured model provider, validates the response envelope, and returns citations and diagnostics.

Its public contract should be provider-neutral and transport-neutral. A minimal future request/response shape might contain:

```text
QuestionRequest
  contractVersion
  question
  context? { pageId, widgetId, route, entityType, entityId? }

AnswerResponse
  contractVersion
  answer
  implementationStatus
  citations[] { sourceId, path, locator, sourceClass, revision? }
  uncertainty[]
  conflicts[]
  evidenceAsOf
```

This is a conceptual contract, not an implemented route or final schema. Entity identifiers require privacy review before inclusion.

### D. Retrieval layer

Retrieval accepts a question plus sanitized context and returns a bounded evidence pack. It enforces allowlisted roots, file types, source classes, result limits, and redaction rules before content reaches the model.

Retrieval is not a general file browser. It must produce stable source identifiers and locators, record why each item was selected, and keep static knowledge separate from optional runtime observations.

The detailed ranking technology is deliberately undecided. Initial retrieval may be deterministic metadata and text search. Embeddings or vector search are not architectural requirements.

### E. Static knowledge/documentation

Static knowledge consists of `PROJECT_MAP.md`, future detailed subsystem documents, Kermit policies, and other explicitly admitted current documentation. Documents carry source class, scope, status, revision/fingerprint, and relevant implementation references.

Historical plans and phase reports may be discoverable but must be labeled as historical or proposed. They cannot silently override current implementation evidence.

### F. Source-code index/retrieval

The source-code path contains a generated, rebuildable index of allowlisted code and configuration metadata, plus bounded excerpts retrieved on demand. It supports questions that detailed documentation cannot answer precisely.

The index should identify symbols, routes, imports/dependencies, relevant line spans, and file fingerprints where practical. It must exclude secrets, private state, generated artifacts, dependencies, large data, and denied roots. Indexed text is untrusted evidence, not instructions.

### G. Optional future runtime read adapters

Runtime adapters are separate, explicit adapters for narrowly defined read questions that static sources cannot answer, such as a service health state or a user-authorized current record summary. They are absent from the initial system.

Every adapter must have:

- a named purpose and data owner;
- an exact allowlisted operation and bounded result schema;
- read-only credentials or an immutable snapshot source where possible;
- row, byte, time, and frequency limits;
- field-level privacy and redaction rules;
- provenance, observation timestamp, and failure semantics;
- tests proving that no write or arbitrary query path exists.

Adapters do not expose generic SQL, arbitrary filesystem paths, arbitrary URLs, or existing application API clients wholesale.

### H. Local LLM provider

The model provider receives a bounded system contract, question, presentation settings, and evidence pack. It returns text or a structured answer envelope. It has no direct access to the filesystem, shell, databases, dashboard APIs, external integrations, or credentials.

Provider base URLs are configuration allowlisted by the Kermit service rather than supplied by a browser request. Model choice, hosting technology, and hardware are deferred until the prototype phase.

### I. Persona/presentation layer

The persona layer controls tone, verbosity, name, and presentation preferences after factual grounding rules are fixed. It cannot add facts, suppress conflicts, change citations, request broader evidence, or grant capabilities. Kermit's initial factual behavior must work without any custom persona.

## 3. Logical flow

```text
User
  -> Kermit chat UI
  -> Kermit API/service (request validation and policy)
  -> Retrieval coordinator
       -> static knowledge index
       -> allowlisted source-code index/excerpts
       -> optional runtime read adapters (future, separately authorized)
  -> Evidence pack with provenance and limits
  -> Local LLM provider
  -> Response validation and citation binding
  -> Kermit chat UI
```

No arrow in this flow points to a mutation interface. The model never selects or invokes tools. Retrieval and runtime reads are performed by deterministic service code under predefined policy.

## 4. Evidence pack contract

The retrieval-to-service boundary should use typed evidence items rather than concatenated anonymous text. Each item should include, where applicable:

- stable source ID;
- source class and authority role;
- repository-relative path or adapter ID;
- section, symbol, route, or line locator;
- content excerpt or structured observation;
- file revision/fingerprint or runtime observation time;
- implemented, proposed, historical, generated, or runtime status;
- canonical/cache/generated/raw/backup/legacy storage role when relevant;
- privacy classification and applied redactions;
- detected conflicts or staleness indicators.

The service should enforce total item, byte, and token budgets. Truncation must be visible to answer generation and diagnostics.

## 5. Frontend contract and endpoint configuration

The chat UI should depend on a small client abstraction, not a hard-coded host. Configuration must support an origin or base URL and explicit availability state. The same request and response versions should work in each deployment stage.

The service endpoint must be selected from trusted deployment configuration. It must not be accepted as an arbitrary URL in each chat request. LAN deployments require an explicit origin policy, authentication decision, TLS/reverse-proxy decision, and network exposure review before implementation.

Moving the service must not require changes to question semantics, citations, context identifiers, or answer rendering. Provider-specific fields stay behind the service boundary.

## 6. Deployment progression

The local desktop stage is current. The laptop and home-server stages are optional alternatives reserved for the final Phase 14 in `ROADMAP.md`; no intervening product phase requires migration.

### Stage 1: current desktop

The dashboard, Kermit service, retrieval indexes, and local model run on the current desktop. They may be separate processes, but process boundaries and ports are configuration, not frontend assumptions.

Trust boundary: browser-to-local-service requests still require origin checks, request limits, and no ambient access to unrelated local files.

### Stage 2: Kermit service and model on another LAN laptop

The dashboard UI uses the same API contract through a configured LAN endpoint. Static indexes may be built on the Kermit host from an explicitly synchronized, read-only repository snapshot. Private runtime data remains unavailable unless a separately designed runtime adapter is intentionally deployed near the data owner.

Trust boundary: LAN traffic is not inherently trusted. Authentication, permitted origins, host firewall rules, endpoint identity, and encryption must be decided before this stage. The remote host must not receive repository secrets or private state merely because it hosts the model.

### Stage 3: dedicated home server

The dashboard and Kermit may move to one home server while remaining logically isolated. Separate service identities, filesystem permissions, network routes, and read-only mounts preserve the boundary even when processes share a machine.

Trust boundary: co-location does not justify shared credentials, writable mounts, direct database connections, or internal bypasses of the Kermit API contract.

## 7. Trust boundaries

### Browser to Kermit service

Treat the question and context as untrusted input. Enforce size limits, schema validation, supported contract versions, rate limits, and origin/authentication policy. Do not accept filesystem paths, SQL, shell text to execute, provider URLs, or retrieval policy overrides.

### Kermit service to retrieval

The service may request semantic topics and known identifiers, not arbitrary host paths. Retrieval resolves only catalogued source IDs within allowlisted roots and returns bounded data.

### Indexed material to model

All indexed material is untrusted data. Source comments, documents, imported text, and generated content can contain prompt injection. They must be delimited as evidence and cannot override system policy.

### Kermit service to model provider

The provider receives only the minimum evidence needed for the question. It receives no tools or reusable credentials. Requests use fixed configuration, timeouts, size limits, and bounded retries.

### Optional runtime adapters

Runtime state may be sensitive even when read-only. Each adapter is an independent privacy and authorization boundary. An adapter failure must degrade to “runtime evidence unavailable,” not fall back to broader access.

## 8. Failure behavior

- If Kermit is unavailable, dashboard features continue normally.
- If retrieval has no evidence, Kermit says it cannot verify the answer.
- If code and documentation conflict, Kermit reports both with their status and citations.
- If a source is stale, the answer identifies its revision or observation time.
- If a provider times out or produces an invalid envelope, the service returns a bounded error without retrying indefinitely.
- If a runtime adapter fails, static explanation remains available and runtime claims are omitted.
- After restart, the service reloads only rebuildable indexes and configuration. It does not resume autonomous actions because none exist.

## 9. Deliberately deferred decisions

This foundation does not choose:

- a model, model size, or model server;
- embeddings, a vector database, or a ranking algorithm;
- an API framework or process supervisor;
- an index storage engine;
- a chat UI layout;
- an authentication mechanism for LAN use;
- which, if any, runtime adapters are justified.

Those decisions belong to the roadmap phase where requirements can be measured without weakening the read-only contract.
