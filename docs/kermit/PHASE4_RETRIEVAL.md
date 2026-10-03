# Phase 4: read-only retrieval

Status: implemented as an offline, deterministic CLI and Python package for the four Phase 3 pilots. No model, serving API, dashboard integration, runtime adapter, or automatic index rebuild exists.

## Contracts and boundary

`kermit_retrieval/query.schema.json` and `evidence-pack.schema.json` are version 1. A request has `contractVersion: 1`, a nonempty UTF-8 `question` of at most 500 characters, and optional `optionalContext` with only `subsystemId`, `pageId`, `widgetId`, `route`, or `entityType`. Entity identifiers and routes must already exist in the index. Unknown fields or identifiers fail closed. Context changes ranking only. The CLI fixes the repository root; neither the question nor context can select a root, path, URL, command, SQL statement, tool, provider, or admission override.

The result is an **evidence pack**, not an answer. It contains the normalized question, resolved context, claim type, candidate subsystems and scores, selected evidence, registered conflicts, limitations, withheld stale source IDs, budget omissions, index build fingerprint, and bounded diagnostics. Each evidence item has an ID, layer, source and entity IDs, authority/fact status, subsystem, repository path, heading/symbol/route/line locator, SHA-256 source fingerprint, privacy class, storage role when known, selection reason, score components, conflict references, and truncation flag. L1/L3 items have excerpts; L2 items have structured metadata. Citations `E1`, `E2`, ... are assigned after selection, in returned order. A citation is valid only if its ID occurs in that pack's `selectedEvidence`; a future answer service must enforce that binding.

## Ranking and layers

Queries receive Unicode NFKC normalization, case folding, whitespace collapse, punctuation-safe tokenization, a small stop-word list, and conservative plural `s` removal. No open-ended language expansion occurs. Pilot topic terms and finding terms are fixed, reviewed hints drawn from the four packs and findings register. Unknown claim types retain mixed evidence and an explicit limitation.

The claim classifier uses bounded literal terms: design/proposal, ownership/storage, calculation, implementation, or behavior. Question-specific authority is applied as follows:

- L0: explicit pilot names and reviewed topic terms identify likely ownership. Broad questions can compare all four pilots.
- L1: current pilot packs are favored for explanation, `PROJECT_MAP.md` for ownership, and Kermit design docs only for Kermit proposal questions. Heading matches score 7 per distinct term; content matches 2 per distinct term, capped at 12. A pilot pack adds 12 for behavior/ownership/unknown or 8 for calculation/implementation. The original claim-type heading preference adds 8; a bounded query-to-heading section-intent match adds 28 more. Candidate subsystem adds 3; an explicitly requested finding adds 25. Cross-pilot property questions reserve one matching reviewed pack section per selected subsystem before normal-score fill, subject to the four-document limit. Subsystems without a matching property section do not receive a reserved slot.
- L2: indexed entity name terms score 5 each, exact nontrivial name/ID 10, indexed alias terms 4, route terms 3, candidate subsystem 2, typed context 3, and canonical/store ownership signals 9. Top entity matches seed a bounded relationship walk. At most two hops, eight edges per node, and 24 followed relationships are allowed. Cycles and stale endpoints are skipped. L2 evidence carries up to four followed relationship records when applicable; diagnostics show the full bounded walk. No absent edge is inferred.
- L3: implementation and calculation questions may include exact indexed symbol spans. A symbol needs score at least 10. L3 is added before broader L2 metadata, so a code question can retain exact source evidence. Ordinary “what does this widget do?” questions use L1/L2 without source excerpts.

These scores are ranking signals, not confidence or proof that a claim is true. Stable IDs break ties. The pack exposes score components. A doc unit needs lexical overlap or a bounded section-intent heading match; unused capacity is left empty rather than filled with unrelated material.

### Bounded section-intent map

The query terms below are compared with normalized tokens. The heading families are matched only against already indexed L1 headings. A matching heading receives the 28-point bonus; no new source, synonym service, or model is consulted.

| Intent | Query terms | Reviewed heading family |
| --- | --- | --- |
| `jobs_recovery` | job, worker, queue, retry/retries, restart, recovery/recover, interruption/interrupted, resume, cancellation/cancel, attempt, backoff | job, recovery, worker, queue |
| `integrations_providers` | integration, provider, external, dependency/depend, API | integration, dependencies, provider, external |
| `storage_ownership` | canonical, store, storage, ownership, persistence, database, SQLite | persistence, source of truth, storage, ownership |
| `metrics_calculations` | metric, calculation/calculate, formula, threshold, temperature | metric, calculation |
| `failure_degraded` | fail, failure, degraded, offline, unavailable | failure, degraded, recovery |
| `data_flow` | flow, transformation/transform, pipeline | data flow, transformation |
| `frontend` | frontend, UI, display, render | frontend |
| `backend_api` | backend, route, endpoint, API | backend, API |

The Language interruption benchmark now selects the reviewed `Jobs and recovery` section first. Provider, canonical-store, and worker comparisons start with one property-matched L1 section for each relevant pilot. `reasonSelected`, `relevanceSignals`, `diagnostics.sectionIntents`, and `balancedEvidenceIds` expose these deterministic choices. The signals are trusted ranking/validation metadata, not model-created evidence.

If no pilot/topic score, explicit finding, registered finding, or selected section-intent match supports a request, `diagnostics.supportStatus` is `none` and `selectedEvidence` is empty. This conservatively short-circuits requests such as private unindexed material outside the positive admission set. It can also withhold an unusual broad question lacking a reviewed intent mapping; that is an explicit coverage limitation, not proof that the subject does not exist.

## Source reader and freshness

Ordinary L3 excerpts require a Phase 3 indexed `symbol` entity. The finding-side exception uses only exact reviewed source or test spans embedded in the validated conflict artifact; callers cannot supply a path or span. Both readers verify positive admission, source class, bounded line/byte limits, safe path, and current SHA-256 before returning text. Phase 4 treats `metadata_only` as permission for these bounded, on-demand excerpts, not general source-body indexing. It rejects missing/unsafe paths, symlink or junction escapes, over-limit files, binary/invalid UTF-8, and changed fingerprints. It never imports or executes repository source.

All six core index artifacts are checked against `build.json` hashes and checked for admitted source/provenance consistency before query use. A malformed or modified artifact rejects the query. The service checks fingerprints of all 102 admitted sources but does not rebuild them. Changed, missing, or unsafe sources are listed in `staleSources`. Their L1/L2 records are withheld. L3 fails closed and rechecks the source hash at excerpt read time. Thus a pack may visibly degrade when the working tree changes, but never labels stale material current. A user must invoke Phase 3's build separately to refresh a snapshot.

## Budgets and conflicts

Maximums are 12 evidence items, four L1 document units, two L3 excerpts, 24 lines and 1,600 UTF-8 bytes per source excerpt, 12,000 bytes of selected evidence, approximately 3,000 evidence tokens (byte count divided by four), 30,000 bytes for the complete pack, two graph hops, 24 followed relationships, and 500 question characters. L1 text is clipped to 900 characters per unit. `omittedDueToBudget` and per-item `truncated` flags expose reductions. If the total pack cap is exceeded, retrieval rejects the result.

The eight Phase 2 findings remain separate objects with their original source provenance. Exact finding IDs or relevant topic terms surface them; a broad findings question returns all eight. Reviewed `kermit_index/finding_sides.json` metadata gives each finding a category and exact source spans for available sides. Those spans must already belong to the positive admission manifest. The index builder verifies their line bounds, anchor text, byte limit, and source hashes. Phase 4 rechecks freshness and source hashes, then reserves bounded slots for the register and both sides on direct finding queries. It records `registerEvidenceId`, each side's `expectedSourceRefs`, `requiredRefCount`, `selectedEvidenceIds`, and an evidence status. A compound side is complete only when every reviewed span is selected. A broad findings query retains all register objects within the existing pack budget; it may omit side spans and labels that limitation. Retrieval never resolves a finding or substitutes a nearby excerpt for a reviewed side.

## CLI and evaluation

```powershell
python -B -m kermit_retrieval query "What does the Quote widget do?"
python -B -m kermit_retrieval query --format json --explain "How is safe to spend per day calculated?"
python -B -m kermit_retrieval query --widget-id widget:quote "Which providers does Quote use?"
python -B -m unittest tests.test_kermit_retrieval
```

The deterministic evaluation covers 31 questions across Quote, Finance, Language Learning, Weather, and cross-system comparisons. Assertions check subsystem selection, required evidence paths/entities, known conflicts, valid citation binding, authority/layer choices, limits, and no invented Weather API operation. Eleven adversarial questions exercise path, private data, command, URL, and policy-override wording. Isolated snapshot tests cover stale/missing sources, changed artifacts, forged symbol spans, symlink rejection where supported by the OS, and synthetic prompt-injection text inside an admitted document. The injected instruction is returned only as inert evidence; it cannot cause another file to be opened. An immutability test compares hashes of index artifacts and selected sources before and after queries.

## Limits

Retrieval is lexical and may miss a relevant section when wording differs from indexed names or reviewed hints. Phase 3 source extraction is intentionally partial; an absent symbol or relationship is not proof of absent behavior. The current index covers only four pilots, and the snapshot reflects a source revision rather than live application state. Source excerpts are code text, not executed behavior. No LLM, natural-language answer, embeddings, vector store, HTTP API, UI, model-selected tools, runtime database read, external call, or ChatGPT-history access is part of this phase.
