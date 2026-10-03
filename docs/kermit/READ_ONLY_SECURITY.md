# Kermit read-only security contract

Status: mandatory architectural contract; the local static service exists through Phase 7.1, while runtime adapters and LAN exposure remain unimplemented

## 1. Security objective

Kermit's safety cannot depend on a prompt that asks a model to behave. Read-only behavior must be enforced by process capabilities, operating-system permissions, network policy, API design, storage access, and tests.

> Kermit may know, read and explain. Kermit may not act.

The model is treated as an untrusted text generator. It does not receive tools and cannot acquire capabilities by emitting a command, URL, SQL statement, code block, or persuasive instruction.

## 2. Protected assets

The contract protects:

- application source and documentation;
- canonical stores and user records;
- caches, generated files, raw archives, migration inputs, and backups;
- settings and runtime configuration;
- secrets, OAuth state, tokens, account keys, and credentials;
- external integrations and their remote data;
- Git history, branches, tags, working tree, and hooks;
- host processes, services, devices, files, and operating-system configuration;
- availability and correctness of the dashboard.

Read-only does not mean non-sensitive. A read can still disclose private journal entries, health data, financial data, raw imports, media, or credentials. Content access therefore requires both a read-only capability and an explicit information policy.

## 3. Prohibited capabilities

Kermit must have no mechanism for any of the following:

- filesystem creation, modification, rename, deletion, permission change, or writable mount;
- source-code or documentation modification;
- shell execution, including PowerShell, `cmd`, POSIX shells, or shell-equivalent interpreters;
- arbitrary subprocess creation, process control, service control, or scheduled tasks;
- arbitrary script, executable, macro, notebook, build, test, importer, or migration execution;
- Git mutations, including commit, checkout, reset, merge, rebase, tag, stash, push, clean, hook execution, or write access to `.git`;
- database `INSERT`, `UPDATE`, `DELETE`, `REPLACE`, DDL, pragmas that mutate state, vacuum, attach, extension loading, or schema migration;
- generic SQL accepted from a user, model, or frontend;
- application mutation APIs, even if they exist on localhost or the same host;
- external API mutations, messages, uploads, sync, purchases, calendar changes, or account operations;
- arbitrary HTTP requests, redirects, webhooks, URL fetching, or model-selected endpoints;
- credential discovery or access beyond strictly required read-only service configuration;
- autonomous background actions, periodic tasks, proactive messages, or work resumed after restart;
- dynamic plugin/tool installation or model-requested capability expansion.

Explaining that an operation exists does not authorize Kermit to perform it.

## 4. Allowed capability model

Kermit starts with static, prebuilt documentation only. Later phases may add narrowly allowlisted reads one capability at a time.

An allowed read capability must be:

1. named and purpose-specific;
2. implemented outside the model;
3. bound to fixed roots, resource identifiers, operations, and response schemas;
4. denied by default for every unlisted path, field, operation, and destination;
5. bounded by bytes, rows, duration, frequency, and concurrency;
6. provenance-bearing and observable without logging private content;
7. independently removable without affecting the dashboard;
8. tested for both permitted reads and prohibited mutations.

The browser and model cannot expand allowlists. A question cannot supply a path, SQL fragment, hostname, URL, executable, or adapter name that bypasses catalog resolution.

## 5. Structural enforcement

### 5.1 Process and filesystem

The future Kermit service should run under a dedicated low-privilege identity. Static repository material should be supplied through an explicit read-only snapshot or read-only mount containing only admitted files. Do not mount the entire user profile or dashboard runtime directory merely for convenience.

The process should have no write permission to the repository, `.git`, dashboard data directories, configuration directories, or operating-system locations. If the service needs ephemeral provider/index working space, it must be isolated from protected assets, size-bounded, and disposable. An index builder, if introduced, is a separate offline process with a narrow output target; the serving process does not rebuild indexes on model instruction.

### 5.2 No execution surface

The serving process must not expose shell wrappers, command runners, code interpreters, dynamic module loading from retrieved content, or “run this to verify” functions. Source retrieval reads text; it does not import or execute repository modules. File formats that can execute active content are parsed as inert data or excluded.

### 5.3 Database reads

If runtime database adapters are ever approved, prefer immutable snapshots or OS-level read-only copies. Otherwise open databases with enforced read-only mode and a purpose-built query API whose SQL is fixed in code. Use a database identity that lacks write and migration privileges where the engine supports it.

Do not expose a generic query endpoint. Do not follow user-controlled database paths, attach other databases, load extensions, write temporary tables into the source database, or depend on a writable WAL/SHM side effect. SQLite access needs specific validation because apparently read-oriented operations can still create sidecar or temporary files.

### 5.4 Network

Default network policy is deny. The service may contact only its configured model endpoint and explicitly approved read adapters. Destinations are fixed by trusted deployment configuration, not request data or indexed text. Redirects, DNS rebinding, loopback metadata access, and access to unrelated dashboard endpoints must be considered in implementation tests.

The model itself receives no HTTP client. Existing dashboard API clients and integration credentials must not be imported wholesale into Kermit.

### 5.5 Credentials

The model, evidence pack, response, citations, and ordinary logs must never contain credentials. The serving process should receive only the minimum secret needed for its own configured provider or authentication boundary. Repository indexing excludes `.env*` other than deliberately public templates, OAuth state, account keys, token caches, and credential-bearing settings.

### 5.6 API boundary

The Kermit API accepts questions and a small typed context envelope. It must reject fields that resemble executable operations, retrieval roots, arbitrary URLs, SQL, or capability lists. The response is explanatory text plus metadata; it has no action descriptor that another component executes automatically.

The dashboard must render answers as untrusted content. Code blocks, links, and suggested commands remain inert. Model output cannot trigger navigation to privileged custom schemes, automatic downloads, API requests, or DOM event handlers.

## 6. Threat and failure cases

### Prompt injection in indexed files

Source files, comments, documentation, generated text, and imported artifacts may say “ignore prior instructions,” request secrets, or contain tool-like syntax. Retrieval labels them as untrusted evidence and delimits content from system policy. Policy is defined in service code/configuration outside the indexed corpus. Injection-like content should be detectable and covered by adversarial tests, but filtering alone is not the security boundary.

### Malicious or accidental instructions in source text

Instructions found in evidence are facts to quote or explain, not commands to follow. The service must never interpret retrieved text as configuration, code, a URL to fetch, or a new source path.

### Hallucinated tool calls

The model may output a fictional call or claim an action succeeded. There is no tool dispatcher, so the call has no effect. Response validation should reject or clearly label unsupported claims of actions, mutations, live inspection, or commands executed.

### Secret exposure

Index admission rules deny secrets and private state before chunking. Redaction is defense in depth, not the primary control. Tests should seed recognizable fake credentials in denied locations and confirm they cannot be searched, retrieved, logged, cited, or returned.

### Private runtime files indexed accidentally

The indexer uses positive allowlists and a generated manifest. Repository presence, Git tracking, or a text extension is not enough for admission. Default exclusions from `SOURCE_POLICY.md` apply before content parsing. Builds should fail closed if a resolved path leaves an allowlisted root or matches a denied class.

### Stale documentation

Every indexed item carries a revision/fingerprint and status. Conflicts between documentation and current source are returned explicitly. Stale knowledge affects answer quality and must be observable, but it must never prompt Kermit to edit documentation automatically.

### Unsafe path traversal

Resolve paths canonically, reject absolute/user-relative paths and symlink/junction escapes, and verify the final target remains under an allowlisted root. Apply the check before opening a file and after resolving links. Archive members require the same rules and should normally be excluded.

### Over-broad runtime adapters

An adapter that accepts arbitrary SQL, URLs, routes, paths, or field selections is prohibited even if documented as read-only. Failure or an unsupported question must return unavailable/unsupported, not fall back to a more powerful interface.

### Cross-origin or LAN abuse

A LAN deployment can expose private architecture or runtime observations to other devices. Origin checks, authentication, host firewall rules, rate limits, request limits, and transport security must be selected before LAN exposure. “Local network” is not an authorization policy.

### Denial of service and data exfiltration through prompts

Bound question length, evidence count, source excerpt size, model context, response size, concurrency, timeouts, and retries. Do not echo entire files on demand. Logs should contain identifiers and metrics rather than full questions or evidence when those may be private.

## 7. Storage-role preservation

Kermit must retain the distinctions defined by `PROJECT_MAP.md`:

- canonical state is the current owned source of runtime truth;
- caches and generated outputs are derived and may be stale or rebuildable;
- raw archives preserve source evidence but are not normalized runtime truth;
- backups are recovery artifacts, not active state;
- migration inputs support transition/recovery and may not match current schemas;
- legacy adapters or snapshots may exist for compatibility without being writable owners.

Read-only runtime answers must name the role of the observed source. A cache hit cannot be described as a canonical database value, and a backup cannot be used to claim current state.

## 8. Testability requirements

Security acceptance must include automated negative tests, not only happy-path tests.

### Static and build-time checks

- Manifest contains only allowlisted roots, extensions, and source classes.
- Denied patterns, secrets, private imports, databases, sidecars, logs, backups, generated outputs, and dependencies are absent.
- Every indexed path resolves inside an allowed root with no symlink/junction escape.
- The serving artifact contains no command runner, generic SQL endpoint, generic file endpoint, or dashboard mutation client.

### Filesystem tests

- Service identity can read approved snapshots but cannot create, modify, rename, or delete protected files.
- Attempts to open denied paths, parent traversals, absolute paths, alternate separators, encoded traversal, links, and archive escapes fail closed.
- Restart leaves repository and runtime data hashes unchanged.

### Database tests

- All adapter operations use fixed read schemas and reject arbitrary SQL.
- `INSERT`, `UPDATE`, `DELETE`, DDL, mutation pragmas, attach, and extension loading fail.
- Test database and sidecar hashes remain unchanged after reads and failures.
- Limits prevent unbounded rows, blobs, scans, and query duration.

### Network tests

- Only configured destinations are reachable.
- User/model-provided URLs, redirects to denied hosts, dashboard mutation routes, metadata endpoints, and arbitrary external hosts fail.
- Provider failures do not cause fallback to an unrestricted client.

### Model/adversarial tests

- Prompt injections in docs, comments, filenames, and source literals cannot change policy or retrieve denied content.
- Requests to edit, run, import, migrate, sync, send, or delete receive an explanatory refusal and no side effect.
- Hallucinated action claims and fake citations are rejected or flagged.
- Conflicting and missing evidence yield explicit uncertainty.

### End-to-end invariant test

Before and after a representative adversarial question suite, compare protected repository files, Git metadata, canonical stores, runtime directories, configuration, and recorded external mutation calls. There must be no changes and zero external mutations.

## 9. Capability change process

Any new read adapter or data class requires its own design review, threat model, privacy classification, allowlist change, tests, and removal plan. “The model needs it” is not sufficient justification. No phase in the roadmap implicitly grants a capability planned for a later phase.
