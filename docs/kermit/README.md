# Kermit

Status: Phase 7 local service and dashboard chat plus Phase 7.1 automatic local startup over the Phase 6 grounded static pipeline; Phase 8 knowledge expansion is in progress.
Current implementation: offline index builder, read-only retrieval, grounded-answer CLI, and loopback chat service/UI. See [Phase 7](PHASE7_CHAT_UI.md) and [Phase 7.1](PHASE7_1_STARTUP.md).

Kermit is the planned read-only system explainer for this dashboard. Its purpose is to help a user understand the implemented application: its architecture, modules, ownership boundaries, data flows, persistence, integrations, calculations, metrics, jobs, APIs, UI behavior, and relevant source files.

Kermit is not an autonomous agent. It must never modify the dashboard, source code, databases, runtime data, configuration, integrations, or host operating system. Its governing rule is:

> Kermit may know, read and explain. Kermit may not act.

The documents in this directory define the current static prototype and future boundaries. The Phase 7.1 trusted dashboard launcher now starts or reuses the independent local service by default; it never warms the model.

## Purpose

Kermit should eventually answer implementation questions such as:

- What does this widget do?
- Where does this value come from?
- How is this statistic calculated?
- Which component owns this data?
- What is the source of truth?
- What happens after this import?
- Which worker processes this?
- Why is this item in review?
- Which source files implement this behavior?
- How do these modules interact?
- What happens after restart?
- Is this data canonical, cached, generated, raw, backup, or legacy?

Answers should be grounded in repository documentation and selected source code, cite their evidence, state uncertainty, and preserve the storage-role terminology established by `PROJECT_MAP.md`.

## Non-goals

Kermit is not intended to:

- edit code, settings, data, or documentation;
- call application mutation APIs or external mutation APIs;
- execute shell commands, scripts, jobs, imports, migrations, or Git operations;
- administer, repair, optimize, or operate the dashboard;
- make decisions or take actions on the user's behalf;
- become a general-purpose desktop assistant;
- silently infer undocumented behavior or present planned behavior as implemented;
- receive the entire repository, private runtime state, or secrets in every prompt.

If a question requests an action, Kermit may explain how the relevant mechanism works or identify the responsible component. It must not perform the action or convert the request into a tool call.

## Intended user experience

The flow below describes later phases. Phase 7 sends only the question and selected profile, without page or component context.

The eventual UI should feel like a contextual documentation conversation:

1. The user asks about a page, widget, value, workflow, or subsystem.
2. Kermit uses the current page/component context only as a retrieval hint, never as authority.
3. The retrieval layer selects the smallest relevant set of documentation, index records, and allowlisted source excerpts.
4. Kermit answers in plain language, with source citations and implementation status.
5. When evidence conflicts or is incomplete, the answer names the conflict or uncertainty instead of hiding it.

The user should be able to distinguish facts verified in current code, facts documented at a higher level, observations from optional runtime read adapters, and future design proposals.

## Eventual relationship to the dashboard

Kermit remains a separate subsystem with a narrow, versioned, read-only frontend contract. The current dashboard hosts a chat panel without page context. A later phase may pass non-sensitive page context, but the dashboard application remains the owner of every feature and every mutation. Kermit does not become a shared domain service, database owner, worker supervisor, or integration broker.

This isolation supports three deployment stages without changing the frontend contract:

1. dashboard, Kermit service, retrieval, and local model on the current desktop;
2. dashboard on the desktop while the Kermit service and model run on another LAN machine;
3. dashboard and Kermit hosted on a dedicated home server.

Endpoints must therefore be configurable and must not embed a permanent `localhost` assumption.

## Conceptual components

These terms are separate and must not be used interchangeably:

| Component | Responsibility | Does not own |
| --- | --- | --- |
| Model | Produces language from a bounded prompt and retrieved evidence | Repository truth, permissions, retrieval policy, or persona facts |
| Persona | Controls presentation style, tone, name, and optional user preferences | Technical facts or source authority |
| Retrieval | Selects relevant, allowlisted evidence for a question | Mutation, broad filesystem access, or truth by itself |
| Knowledge base | Curated documentation and machine-readable metadata about the system | Live application state unless explicitly represented by a read adapter |
| Runtime context | Minimal request-time context such as current page/component and optional allowlisted read-only observations | Persistent authority, secrets, or write access |
| UI | Collects questions, displays answers, citations, status, and uncertainty | Direct model access, repository access, or application mutation |

The persona may change how an answer is expressed. It must never change what counts as evidence, which capabilities are available, or whether an action is permitted.

## Documentation set

- `ROADMAP.md` defines independently deliverable phases.
- `ARCHITECTURE.md` defines components, contracts, deployment progression, trust boundaries, and data flows.
- `READ_ONLY_SECURITY.md` defines the non-mutation capability contract and its testability.
- `KNOWLEDGE_MODEL.md` defines knowledge layers and the subsystem documentation schema.
- `SOURCE_POLICY.md` defines source authority, conflicts, provenance, and default indexing exclusions.
- `knowledge/` contains the L1 template, four historical pilot packs, the first three Phase 8 packs, the coverage ledger, and the gaps/conflicts register.

`PROJECT_MAP.md` remains the authoritative high-level inventory of the currently implemented dashboard. Kermit-specific detailed documentation and indexes should build on it rather than duplicate it. `PHASE4_RETRIEVAL.md` and `PHASE5_LOCAL_LLM.md` document the offline prototypes.

## Current boundary

Phases 3–7 provide an allowlist-only static index, read-only retrieval, a local model draft, deterministic grounding, a loopback service, and a dashboard panel. Phase 7.1 adds trusted startup of that service. Phase 8 B1 adds reviewed Cleaning, Reading, and Todo static knowledge; `knowledge/COVERAGE.md` tracks the remaining units. There is no runtime adapter, Phase 9 page context, persona implementation, Kermit database, LAN binding, or model-controlled action. Draft answers remain untrusted until Phase 6 grounding.
