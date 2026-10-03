# Canonical L1 subsystem pack template

Copy this file for one bounded subsystem. Replace every bracketed prompt. Keep meaningful fields: write **None**, **Not applicable**, **Not implemented**, or **Unknown**, with a reason where useful. Cite repository-relative source paths and named symbols/routes/tests. Do not use runtime/private data to fill gaps. Follow `KNOWLEDGE_MODEL.md` and `SOURCE_POLICY.md`.

## Identity and verification

- Stable subsystem ID: [ID also used by L0 where available]
- Display name / owning domain: [name / domain]
- Current implementation status: [current / mixed / legacy / proposed]
- Document status: [reviewed / draft]
- Verified: [YYYY-MM-DD; Git revision or working-tree status]
- L0 locator: [`PROJECT_MAP.md` section]

## Purpose and boundaries

- Purpose: [user need].
- Non-goals: [explicitly outside scope].
- Owns: [behavior and contracts].
- Owned elsewhere: [adjacent UI/service/store/integration responsibilities].
- Invariants and trust/authorization boundary: [including read versus mutation capability].

## Frontend

| Surface | Entry/identifier | Controller, store, API client | Loading, empty, error, review/stale behavior |
| --- | --- | --- | --- |
| Page/widget | [path, route, `data-widget`, stable IDs] | [symbols] | [states] |

- User actions: [action -> read or mutation -> call/owner].
- Browser-only state and exact localStorage keys: [or None].
- Compact/hidden/lazy-load behavior: [or Not applicable].

## Backend and API

| Method + route | Handler and service | Request/response owner; validation/limits | Read or mutation |
| --- | --- | --- | --- |
| [GET/POST/... path] | [symbol] | [contract] | [read/mutation] |

- Entry/service/repository/handler boundaries: [or None].
- External service boundary: [or None].
- Origin/auth/privacy boundary: [specific control or Unknown].

## Persistence and source of truth

| Artifact/entity | Owner | Role | Schema/migration/version and retention |
| --- | --- | --- | --- |
| [artifact] | [symbol] | [canonical/cache/generated/raw archive/backup/migration input/legacy/browser-only] | [details] |

Explicitly account for canonical state, cache, generated state, raw archive, backup, migration input, legacy state, and browser-only state. State each important entity's current source of truth. If absent, say None; never equate a cache or source capture with canonical state.

## Data flow

1. [Input and provenance].
2. [Validation and rejection/quarantine].
3. [Normalization, identity/deduplication, enrichment].
4. [Transformation/review; exact owner].
5. [Output and consumer].

State what happens to failed, ambiguous, or unreviewed inputs.

## Metrics and calculations

| Metric | Meaning, inputs, filter/group/window/date semantics | Exact formula/rule and units/format/null handling | Version, owner, focused test |
| --- | --- | --- | --- |
| [name] | [fields and owner] | [algorithm] | [symbols/tests or gap ID] |

Include any cache/materialization role. A statement such as "calculated by backend" is insufficient.

## Jobs and workers

| Trigger and queue | State, attempts/retries/backoff/cancellation/concurrency | Startup and interrupted-work recovery | Evidence |
| --- | --- | --- | --- |
| [job or None] | [details] | [details] | [symbols/tests] |

## Integrations

| Provider | Data direction and credential boundary | Failure, rate limit, retry | Evidence |
| --- | --- | --- | --- |
| [provider or None] | [details] | [details] | [symbols] |

## Dependencies, failure and recovery

- Upstream/downstream dependencies: [specific].
- Degraded states and observable symptoms: [specific].
- Stale/partial/inconsistent data handling: [specific or Unknown].
- Restart/recovery owner and manual action, if any: [specific or None].

## Privacy and security

- Private inputs/outputs and server/browser exposure: [specific].
- Secrets and provider credentials: [boundary or None].
- Source policy exclusions relevant here: [paths by role only, never contents].

## Tests and evidence

| Contract | Current test | Limit |
| --- | --- | --- |
| [behavior] | [`tests/...::test_name`] | [what remains uncovered] |

- **Verified implementation sources:** [repository-relative path::symbol, route, schema].
- **Documented current contracts:** [current docs, if used].
- **Historical/proposed sources:** [if cited, with status].
- **Conflicts:** [ID in `GAPS_AND_CONFLICTS.md` or None].
- **Known gaps:** [ID(s) or None].
- **Verification metadata:** [date, revision/dirty state, reviewed surfaces, tests run/not run, private-data exclusion].
