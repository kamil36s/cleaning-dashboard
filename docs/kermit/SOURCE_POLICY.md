# Kermit source policy

Status: source-authority and indexing contract; Phase 3 offline index exists

## 1. Purpose

This policy defines which evidence Kermit may use, how sources are classified, how conflicts are reported, and which repository material is excluded by default. It applies to future documentation retrieval, machine-readable indexes, source-code retrieval, and optional runtime reads.

Repository presence is not permission to index. Git tracking is not permission to disclose. A readable file is not necessarily authoritative.

Existing `.gitignore`, central-server static-file protection, and Vite development-server deny rules serve different repository/runtime purposes and are not a complete Kermit admission policy. Kermit must not derive its index allowlist from any one of them.

## 2. Authority is question-specific

There is no single hierarchy that makes one source authoritative for every question. Kermit must first identify the kind of claim, then use the matching authority.

### Implementation truth

For “what does the current software do?” questions, current executable source code, active schemas/migrations, route definitions, configuration contracts, and focused tests are primary evidence. Tests demonstrate intended and covered behavior but do not override code actually deployed. Generated bundles and dependencies are not implementation sources when original project files exist.

### Documentation truth

For architecture intent, ownership rules, operating procedures, invariants, and accepted terminology, current documentation is authoritative within its declared scope. `PROJECT_MAP.md` is the authoritative high-level inventory. Detailed current subsystem docs refine it. Kermit design documents describe future Kermit contracts, not implemented runtime behavior.

Documentation with roadmap, proposal, phase result, audit date, historical, or backup status must retain that label. An unimplemented proposal is not current application truth.

### Canonical runtime state

For “what is the current stored value?” questions, the feature's documented canonical store is authoritative, subject to transaction timing and observation time. Canonical state does not establish how the application calculates or displays a value; code and metric definitions establish that behavior.

Canonical stores are not indexed by default. Access, if ever approved, occurs only through controlled read-only adapters with an explicit schema and privacy policy.

### Generated and cache data

Generated snapshots, public reports, materialized analytics, downloaded metadata, caches, and projections are secondary evidence. They may be stale, partial, or rebuildable. Kermit may use an admitted generated artifact only when its producing process, source revision, generation time, and storage role are known. It must never relabel derived data as canonical.

### Raw archives and imports

Raw captures and imports are evidence of what entered a pipeline. They are authoritative for the captured source bytes, not for normalized application state, later corrections, or current runtime behavior. They are private and excluded by default.

### Backups and migration/recovery inputs

Backups represent recovery points. Migration inputs and compatibility snapshots represent historical or transitional state. They are not current truth and are excluded by default. If explicitly admitted for a bounded forensic question, Kermit must label the artifact date, purpose, and non-current status.

### Legacy and historical sources

Legacy adapters, old localStorage formats, retired files, phase reports, and historical docs explain provenance or compatibility. They do not override current owners. Kermit must clearly say when a source is historical, read-only compatibility material, or no longer on the active path.

Exported ChatGPT conversations, if separately authorized for a future bounded read-only history question, are **private project history/personal context**. They may evidence what was discussed or considered, never what current code implements. They are excluded from ordinary static admission and automatic retrieval even if present in the repository. Current executable source remains the authority for current behavior.

## 3. Claim-to-source matrix

| Question | Preferred evidence | Supporting evidence | Commonly misleading evidence |
| --- | --- | --- | --- |
| What is implemented? | Current entry points, service/store code, route definitions | Focused tests, current subsystem docs, `PROJECT_MAP.md` | Roadmaps, old phase reports, generated bundles |
| What is the intended boundary? | Current architecture/policy docs | Code organization and contract tests | Incidental implementation shortcuts |
| Where is current state owned? | `PROJECT_MAP.md`, current store/service code, schema | API client and focused tests | Cache, export, backup, public snapshot |
| How is a metric calculated? | Current calculation code and versioned definition | Tests and detailed docs | Display label, cached aggregate without provenance |
| What happened to one item? | Explicitly approved canonical/runtime adapter plus audit/provenance records | Pipeline code and job docs | Raw input alone or a stale cache |
| What happens after restart? | Startup/recovery code and worker/store contracts | Recovery tests and operations docs | Desired roadmap behavior |

## 4. Conflict handling

When sources disagree, Kermit must not silently choose a convenient interpretation.

The answer should:

1. state the disputed claim;
2. cite each relevant source and its class/status;
3. state which source normally governs that kind of claim;
4. explain the observed difference without inventing a reconciliation;
5. identify evidence age or revision where available;
6. say what remains uncertain.

For current behavior, verified current code normally outranks prose. Kermit should phrase this as a discrepancy: for example, “The documentation says X, while the current handler implements Y.” It should not rewrite the documentation, infer that code is correct by intent, or hide the stale document.

For architectural intent, an explicit current contract can govern even when current code has a known transitional exception. The answer must name both the intended rule and actual behavior.

Conflicting runtime observations should include timestamps and storage roles. A newer cache does not automatically outrank an older canonical record; the ownership contract matters.

## 5. Status and provenance metadata

Every indexed source should carry as much of the following as is available:

- stable source ID;
- repository-relative path or runtime adapter ID;
- source class;
- status: current, proposed, historical, generated, raw, backup, legacy, or runtime observation;
- scope and owning subsystem;
- revision/fingerprint and indexed time;
- document date or runtime observation time;
- canonical/cache/generated/raw/backup/migration/legacy role;
- relevant symbols, routes, sections, or line spans;
- privacy classification;
- generator/importer/rule version for derived artifacts;
- known supersession or conflict links.

Missing metadata should reduce confidence. It must not be guessed by the model.

## 6. Positive admission policy

Initial static indexing should admit only an explicit manifest of:

- `PROJECT_MAP.md`;
- the current Kermit documents under `docs/kermit/`;
- reviewed current subsystem documentation needed for the first knowledge packs;
- reviewed project-owned source files and tests referenced by those packs;
- small, non-secret configuration templates only when needed to explain a contract.

New directories are not automatically inherited. Machine-readable indexes should contain metadata and bounded excerpts, not copies of entire private or generated trees.

Source-code retrieval should prefer project-authored source over bundled/minified output and should retrieve the smallest relevant symbol or span rather than a full large file. Large files such as `server.py`, `styles.css`, and `index.html` require symbol/route/selector-level retrieval limits.

## 7. Default exclusions

The following must not be indexed by default, even if locally readable or accidentally committed.

### Secrets and credentials

- `.env*`, except a specifically reviewed public template such as `.env.example`;
- OAuth tokens/state, API keys, cookies, sessions, account keys, pairing tokens, credential stores, private settings, and provider configuration containing secrets;
- `.git/` internals, hooks, credential helpers, and local tool state.

### Private runtime and user data

- canonical databases and database contents;
- SQLite `-wal`, `-shm`, and journal sidecars;
- raw finance imports and receipts, private Job Hunt state, journal and voice-journal content, HTR page/model data, health/scale/ring/sensor data, phone telemetry, calendar caches, diet/events state, and other personal records;
- raw private imports, uploaded documents, private media, audio, images, scans, covers, posters, and event assets;
- runtime settings and device/network inventories.

Representative denied areas include `data/raw/`, `data/finance-imports/`, `data/finance-receipts/`, `data/backups/`, `data/budget-backups/`, `data/jobhunt/`, `data/journal-htr/`, `data/synchrobook/`, `data/voice-journal*`, `data/health-connect/`, `data/scale/`, `data/sensor/`, `data/google-calendar/`, `data/spotify/`, `data/timeline-activity/`, `covers/`, and private media trees. This list is illustrative; admission remains allowlist-based.

### Generated, dependency, and heavy artifacts

- `node_modules/`, virtual environments, package caches, build outputs, `dist/`, `build/`, `out/`, `.vite/`, `.vitest/`, coverage, and `reports/`;
- `antigravity-context/` generated snapshots unless a future design explicitly admits a privacy-reviewed schema rather than existing outputs;
- generated public snapshots, compiled/minified bundles, downloaded datasets, reference corpora, processed source trees, and large data snapshots;
- model binaries, weights, tokenizer caches, HTR bootstrap/models, local LLM files, and generated audio;
- language reference source archives and generated reference databases.

### Operational and temporary artifacts

- logs, including `server.log` and log directories;
- temporary files/directories such as `.tmp-*`, `tmp/`, editor swaps, OS metadata, crash dumps, lock files, PID files, and test scratch data;
- caches of any kind;
- backups such as `*.bak`, database copies, exports, recovery snapshots, and `save-*`/`auto-*` artifacts unless explicitly authorized for one forensic task.

### Active or ambiguous content

- archives and container images unless a bounded, inert parser and explicit manifest are approved;
- files whose parser can execute macros, scripts, network requests, or external references;
- symlinks/junctions that resolve outside allowed roots;
- unknown binary formats and files above configured limits.

## 8. Privacy classifications

A future manifest should distinguish at least:

- **Public project knowledge:** safe architecture and code facts intended for Kermit.
- **Internal implementation:** project code/details safe only within the trusted deployment.
- **Private user data:** personal runtime content; denied unless an adapter is specifically approved.
- **Secret:** credentials or security material; never supplied to retrieval or the model.

Classification is independent of Git status. A tracked file can still be private; an ignored file is not automatically secret, but remains denied until admitted.

## 9. Freshness and rebuilding

Indexes are derived artifacts, never sources of truth. They should be reproducible from an admission manifest, parser/indexer version, source fingerprints, and build time. Rebuilds must not mutate source files.

Kermit should expose evidence age when it matters. If an indexed fingerprint no longer matches the current admitted source, that item is stale and should be withheld or labeled stale according to a documented policy. Runtime observations always include observation time.

## 10. Citation requirements

Answers about implementation should cite repository-relative paths plus a stable locator such as section, symbol, route, or line span tied to an indexed revision. Runtime claims cite the adapter, operation, storage role, and observation time rather than pretending they came from a source file.

The model must not invent a citation. The Kermit service should bind response citations only to evidence IDs actually present in the evidence pack and reject unknown IDs.

## 11. Exceptions

An exclusion can be relaxed only for a documented, bounded purpose with user authorization, privacy review, a minimized representation, expiration/removal conditions, and tests. Bulk admission of an excluded directory is not an acceptable exception mechanism.
