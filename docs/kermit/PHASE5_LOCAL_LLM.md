# Phase 5: local LLM prototype

Status: COMPLETE AS LOCAL MODEL PROTOTYPE / MODEL BAKE-OFF. The selected interactive baseline is `qwen3.5:4b`. Its measured 15/15 valid envelopes and 14/15 manually grounded drafts include one known factual inversion, so raw draft text is untrusted and cannot be displayed as a grounded answer. Phase 6 owns final claim and citation enforcement. No dashboard UI, HTTP service, runtime adapter, or persona exists.

The controlled cross-model results and current acceptance decision are in [PHASE5_MODEL_BAKEOFF.md](PHASE5_MODEL_BAKEOFF.md).

## Boundary

`kermit_model.service.ask` invokes Phase 4 retrieval with the fixed version 1 question contract, then passes its EvidencePack to `generate_draft`. The model provider receives only two role/content messages. It receives no repository root, source reader, retrieval callback, path resolver, SQL adapter, application client, tools, or URL field. Phase 4 alone selects evidence. The provider cannot ask it for another item or change its admission policy. The fake provider and Ollama adapter share the same `Provider.generate(messages, config) -> ModelResult` boundary.

The CLI is for local testing. It is not a production capability or security sandbox. For deployment, the Phase 1 read-only process, filesystem, and network controls still need implementation.

## Providers and configuration

The deterministic fake provider parses the already serialized evidence and emits a conservative JSON draft with up to three valid evidence IDs, subsystem labels, and surfaced finding IDs. An explicit “never indexed” fixture returns insufficiency. It does not perform model reasoning or claim answer quality. Tests inject alternate fake responses and failures to exercise validation.

The Ollama adapter sends one nonstreaming, native JSON-schema `/api/chat` request to the configured endpoint and fixed `/api/tags` and `/api/ps` health endpoints. It uses direct HTTP connections without redirects or proxies. No request, question, evidence item, or model output can set the destination. The base URL comes only from trusted local environment configuration. Use a trusted Ollama host for future LAN deployment; the prototype does not itself enforce an operating-system network allowlist or authenticate a LAN endpoint.

| Environment variable | Default | Meaning |
| --- | --- | --- |
| `KERMIT_LLM_PROVIDER` | `fake` | `fake` or `ollama` |
| `KERMIT_LLM_BASE_URL` | `http://127.0.0.1:11434` | Trusted Ollama origin; scheme, host, and explicit port only |
| `KERMIT_LLM_MODEL` | `qwen3.5:4b` | Default configured model tag; availability must be checked |
| `KERMIT_LLM_MODEL_QUICK/NORMAL/DEEP/MAX` | unset | Optional per-profile override |
| `KERMIT_LLM_KEEP_ALIVE` | `2m` | Ollama model residency request; accepted units `s`, `m`, `h` |

Model chooses weights. Reasoning profile chooses response and model-facing evidence budgets and a low/medium/high answer-effort hint; presentation profile chooses `neutral` or `concise` wording. These are separate from evidence and permissions. All profiles use the same Phase 4 retrieval and the same security system instruction. The default model is qwen3.5:4b for all four, including Max. For that known thinking-capable tag, `think=false` is sent; for tested models without a thinking capability, the field is omitted. `temperature=0` is sent for every model. The response budgets are Quick 512, Normal 768, Deep 1200, and Max 1600 tokens. Model-facing evidence targets are 4, 6, 8, and 12 items respectively. A required finding can exceed a target. Trusted local `KERMIT_LLM_OUTPUT_TOKENS_<PROFILE>` and `KERMIT_LLM_EVIDENCE_LIMIT_<PROFILE>` values permit bounded experiments (128-2048 tokens and 1-12 items). The neutral technical presentation is the default; the character/persona phase is deferred.

## Prompt and draft

The compact system instruction keeps evidence as data, bans tool use, actions and live inspection, requires supplied evidence IDs, and asks for conflicts, status distinctions, and explicit insufficiency. The user message contains the question, a short answer length hint, and delimited `<untrusted_evidence_json>`. This model-facing JSON retains evidence ID, subsystem, fact status, storage role, useful path/locator, excerpt or structured facts, conflict references, freshness, selected conflict descriptions and retrieval uncertainty. It excludes ranking reasons, source hashes, layer/source-class bookkeeping, stale-source counts, and budget omission counts. Phase 4's EvidencePack remains unchanged.

Phase 4 allows at most 12 evidence items, 12,000 selected-evidence bytes, 30,000 total pack bytes and 500 question characters. Phase 5 additionally rejects serialized evidence above 22,000 bytes or full prompt messages above 25,000 bytes. Its selected subset preserves directly requested finding evidence, both selected sides of known discrepancies, and explicitly marked critical evidence before filling remaining slots by Phase 4 rank. `--explain` shows only prompt structure, byte/token estimate, IDs, generation options, provider/profile, latency, finish reason, and validation status. It does not print prompt text or credentials. The `DraftAnswer` JSON has `answer`, `citedEvidenceIds`, `uncertainty`, `conflictsMentioned`. Ollama receives that schema in `format`, with four required fields, correct types, `additionalProperties=false`, an answer length bound, and bounded arrays. Local validation still rejects malformed JSON, extra fields, unknown or duplicate evidence IDs, unknown conflict IDs, oversize answers, and first-person action claims. The declaration in `citedEvidenceIds` is sufficient; inline `[E1]` text is not required. This is envelope validation, not Phase 6 claim-level factual proof.

An empty evidence pack returns an explicit insufficiency result without calling a model. A provider failure returns `unavailable`; invalid output returns `invalid` and no factual draft. The action-claim check is intentionally targeted at first-person Kermit actions such as “I ran” and “I opened”; it permits ordinary descriptions such as “the importer updates”. It cannot detect every unsupported factual statement.

## Time, resources, and health

The adapter retains a 3-second connection timeout, 90-second generation read timeout, 16,000-byte response cap, and at most one retry for transient transport failures or HTTP 429/502/503/504. A measured timeout is not retried; malformed/unsupported drafts are not retried. Health uses a 3-second read timeout and a 32,000-byte cap. The prototype permits one concurrent generation per process; excess requests fail. There is no background retry or resident agent. `keep_alive` defaults to two minutes, so Ollama may unload the model afterward.

Health exposes `unavailable` when the provider or configured model cannot be used, `sleeping` when the configured model is installed but absent from `/api/ps`, and `ready` when it is resident. Generation may load a sleeping model, then returns latency and Ollama `load_duration` when supplied. `loading` and `generating` are conceptual in-flight states for a future UI; this CLI has no concurrent status surface for them. Health does not pull, delete, or list model names to the user.

## Resource Gate

The trusted `kermit_model.resources` module admits an Ollama generation after Phase 4 retrieval and immediately before `/api/chat`. It calls the existing Ollama health layer to determine whether the configured model is resident, reads physical RAM, then returns a structured decision. On Windows the read-only `GlobalMemoryStatusEx` call supplies total and available **physical** bytes; values are floored to MiB (named `Mb` in the JSON for consistency with the CLI contract). The module never inspects processes. If observation fails, the model is unavailable, or its resource profile is unknown, generation fails closed. The fake provider never uses the gate. No background polling occurs.

This machine's qwen3.5:4b CPU runner used approximately 3.6-3.7 GB working set and 4.4-5.1 GB private memory during measurement; available RAM fell to about 2.46 GB. These are local observations, not universal model requirements. The initial **cold-load** minimum is 5,200 MiB, just above the observed 5,100 MiB peak private memory. The recommended amount is 6,600 MiB: the observed peak plus a rounded 1,500 MiB safety margin. Below 5,200 MiB is **RED** and no generation starts, even with `--allow-memory-pressure`. From 5,200 through 6,599 MiB is **YELLOW** and needs that explicit CLI flag. At 6,600 MiB or above is **GREEN** and generation starts normally. Thresholds apply to available physical RAM before loading, not total installed RAM or pagefile capacity. Because measurements vary by context length, model build, Ollama version, and desktop load, these are deliberately conservative starting values, not a guarantee against paging.

If `/api/ps` reports the model already resident, its weights are already accounted for in current available RAM. The incremental resident minimum is 1,200 MiB and recommendation is 2,000 MiB. The same RED/YELLOW/GREEN rules then apply. Failure to read residency is treated as a cold load. The existing `keep_alive=2m` request remains intact; Ollama may unload after inactivity. A later request then sees `sleeping` and must pass a fresh cold-load preflight. A resident model under 1,200 MiB available is still blocked. Resource checks do not unload a model or control Ollama processes.

`python -B -m kermit_model resources --format json` explicitly rechecks memory and residency once; run it again after freeing RAM. The command defaults to the Ollama provider. `ask --provider ollama` returns a deterministic `waiting_for_memory` result with the exact `availableMb`, `minimumMb`, `recommendedMb`, `deficitToMinimumMb`, and `deficitToRecommendedMb` values when memory is RED. YELLOW returns `confirmation_required` and the same fields. In text mode the CLI prints the deterministic message; JSON mode exposes the full result. RED exits with code 3, YELLOW with code 4, and GREEN with code 0. `--allow-memory-pressure` permits YELLOW only. No model writes these messages or chooses the resource state.

The resource result also includes `modelResident`, `providerState`, `modelState`, `nextGenerationState`, utilization, the selected profile, and a `RESOURCE_GATE_BLOCKED` event payload for RED. `modelState` can be `sleeping`, `ready`, `resource_pressure`, `waiting_for_memory`, or `unavailable`; `nextGenerationState` describes the future transient `loading` or `generating` state when admission is possible. These are data contracts for a future notification or Phase 7 UI; this phase does not send a Windows notification or build dashboard UI. A completed Ollama call adds `availableAfterMb`, provider `loadDurationNs` when reported, and `generationDurationMs` to safe diagnostics. No evidence, question, secret, process arguments, or command lines are recorded there.

Built-in resource profiles are keyed by model tag, not Quick/Normal/Deep/Max label. All four default to qwen3.5:4b and share its thresholds; Gemma, Phi, and Mistral have distinct measured profiles listed in the bake-off report. Trusted local process configuration can set `KERMIT_RESOURCE_PROFILES_JSON` to a JSON object keyed by model tag. Each entry may override a built-in profile or fully define a new one using `minimum_available_before_load_mb`, `recommended_available_before_load_mb`, `minimum_available_resident_mb`, `recommended_available_resident_mb`, and `safety_margin_mb`. Optional calibration metadata are `observed_working_set_mb`, `observed_private_mb`, `observed_peak_private_mb`, `sample_count`, and `last_calibrated_at`. For example:

```powershell
$env:KERMIT_RESOURCE_PROFILES_JSON='{"qwen3.5:4b":{"minimum_available_before_load_mb":5400,"recommended_available_before_load_mb":6900,"safety_margin_mb":1800}}'
python -B -m kermit_model resources --format json
python -B -m kermit_model ask --provider ollama --profile normal "How does Finance review work?"
python -B -m kermit_model ask --provider ollama --allow-memory-pressure "How does Finance review work?"
```

Malformed profiles fail configuration validation; unknown models fail closed until a complete trusted profile is supplied. Browser content, question text, evidence, and model output cannot alter thresholds. Long-term calibration is deferred; the metadata fields permit replacing the initial measurements with audited local observations later. Process-memory listing is also deferred because it would add process inspection and dependencies without improving admission. Kermit never closes, kills, suspends, or cleans up applications. The model receives no RAM observation, resource decision, process-control tool, shell, or command execution capability. This gate does not reserve RAM and cannot prevent other applications from consuming memory after admission.

## CLI and evaluation

```powershell
python -B -m kermit_model health --provider ollama --format json
python -B -m kermit_model resources --format json
python -B -m kermit_model ask --provider fake "What does the Quote widget do?"
python -B -m kermit_model ask --provider ollama --profile normal --format json --explain "How does Finance review work?"
python -B -m kermit_model eval --provider fake
python -B -m unittest tests.test_kermit_model
```

The 15-case Phase 5 set adapts Phase 4 benchmark questions across Quote, Finance, Language Learning, Weather, cross-system, insufficient/private-evidence wording, and W-02/F-01/F-02/F-03/F-04/L-01 findings. It checks observable envelope properties: valid status, bounded answer, allowed evidence IDs, subsystem/finding mention, and action-claim rejection. Real-provider reports additionally check required concepts and forbidden claims in representative answers, including current Finance source semantics and canonical versus rebuildable Language state. Resource-blocked cases are reported separately from model failures. Fake-provider tests are deterministic gates. A real-model run produces a report for review and may fail these checks without failing the test suite. Content quality and claim support still require human review and Phase 6 grounding.

Synthetic admitted evidence containing “Ignore previous instructions”, “Read .env”, “Run PowerShell”, and “Open finance.sqlite” stays inside the untrusted evidence delimiter. The fake-provider test confirms it cannot cause a source read or action. The Ollama experiment can be repeated manually when a configured model is present; prompt-only protection is not sufficient to guarantee a real model ignores every injected instruction.

## Real-model stabilization, 2026-09-29

The preceding real attempt passed the Resource Gate at 6,653 MiB available and reached generation, but Quick's 384-token limit produced a non-JSON draft. Earlier adapter experiments had repeated 90-second timeouts and 0/7 valid drafts. A manual diagnostic improved structural output with thinking disabled and Ollama's native schema. This revision uses the [documented `/api/chat` schema `format` and `think` fields](https://docs.ollama.com/api/chat) and [Ollama's structured-output guidance](https://docs.ollama.com/capabilities/structured-outputs). It keeps `think=false` on Quick, Normal, Deep, and Max, and sends `temperature=0`. The reasoning-profile abstraction remains; Deep currently means a larger answer/evidence budget.

The previous system instruction was 786 UTF-8 bytes (approximately 197 tokens at four bytes per token); the final compact one is 526 bytes (approximately 132 tokens), a reduction of about 65 tokens. With unchanged Phase 4 retrieval, the representative Quote question's model-facing evidence changed from 4,960 bytes (all six items) to 3,112 bytes (top four), about 462 fewer approximate tokens. The canonical Finance question changed from 6,925 bytes (seven items) to 4,236 bytes (top four), about 672 fewer. W-02 changed from 6,145 to 5,309 bytes with all four selected items retained, about 209 fewer. The 4/6/8/full projection was measured for these questions; selecting fewer than four would drop useful Quote/Finance context, while the requested W-02 evidence requires at least three items. Limits of 4/6/8/12 are provisional: the cross-system case failed with four and six items, while eight/full were RED-blocked before generation.

An initial 15-case Quick evaluation ran through retrieval and the unmodified Resource Gate. All cases were cold-load RED and correctly sent **zero** `/api/chat` requests. Available physical RAM ranged from 5,119 to 5,177 MiB, below the 5,200 MiB minimum. No YELLOW override or threshold reduction was used. Every row therefore had `RESOURCE_BLOCKED`, zero generation latency, no finish reason beyond `resource_gate`, and no measured structural/grounding result. The table records the per-case available RAM and model-facing evidence size. All used the provisional 512-token Quick output budget; prompt estimates and other fields remain in the CLI's JSON report.

| Case | Available MiB | Evidence items | Evidence bytes | Result |
| --- | ---: | ---: | ---: | --- |
| Quote widget | 5,168 | 4 | 3,112 | RESOURCE_BLOCKED |
| Quote provider fallback | 5,166 | 4 | 3,599 | RESOURCE_BLOCKED |
| Finance canonical store | 5,159 | 4 | 4,236 | RESOURCE_BLOCKED |
| Finance review | 5,161 | 4 | 4,681 | RESOURCE_BLOCKED |
| Language job recovery | 5,142 | 4 | 4,786 | RESOURCE_BLOCKED |
| Language reference data | 5,155 | 4 | 4,683 | RESOURCE_BLOCKED |
| Weather source | 5,177 | 4 | 3,365 | RESOURCE_BLOCKED |
| Cross-system providers | 5,142 | 4 | 4,391 | RESOURCE_BLOCKED |
| W-02 | 5,141 | 4 | 5,309 | RESOURCE_BLOCKED |
| F-01 | 5,119 | 3 | 4,494 | RESOURCE_BLOCKED |
| F-02 | 5,138 | 3 | 4,300 | RESOURCE_BLOCKED |
| F-03 | 5,132 | 3 | 4,108 | RESOURCE_BLOCKED |
| F-04 | 5,132 | 3 | 4,253 | RESOURCE_BLOCKED |
| L-01 | 5,128 | 3 | 4,303 | RESOURCE_BLOCKED |
| Private unindexed journal | 5,124 | 4 | 4,758 | RESOURCE_BLOCKED |

RAM later rose above the cold recommendation. A cold 384-token Quote title-case trial returned a complete envelope and correctly stated that an all-title-case valid quote is rejected and retried (35.8 s total; 13.2 s model load; 7.0 tokens/s). This confirms the selected top-four pack includes the explicit rule and the model did not invert it in that trial.

The admitted 15-case work used controlled passes and targeted continuation, all through retrieval and a fresh Resource Gate preflight. The first pass used Quick 384 without override: seven GREEN drafts, then eight YELLOW blocks. The continuation used Quick 512: cross-system and W-02 were GREEN; W-02 was rerun after a generic prompt/validator fix with an **explicit YELLOW override**; F-01 through F-04 also used that explicit controlled override. L-01 and the private journal case reached RED at 1,072 and 1,090 MiB resident and sent no chat request, then naturally unloaded under `keep_alive=2m` and were rerun after a GREEN cold-load preflight. No RED override, RAM threshold change, or process cleanup occurred. The final observed status for each case is below; `G`/`Y` denote Resource Gate state, `S` means complete structured envelope, and bytes/tokens are model-facing evidence/prompt estimate.

| Case | Budget | Gate/MiB | Items; bytes; prompt est. | Latency; tokens/s | Result |
| --- | ---: | --- | --- | --- | --- |
| Quote widget | 384 | G/3,191 warm | 4; 3,112; 978 | 24.4 s; 7.0 | S, grounded |
| Quote fallback | 384 | G/3,018 warm | 4; 3,599; 1,110 | 23.9 s; 7.1 | S, grounded |
| Finance canonical store | 384 | G/2,751 warm | 4; 4,236; 1,261 | 27.9 s; 7.0 | S, grounded |
| Finance review | 384 | G/2,644 warm | 4; 4,681; 1,371 | 33.5 s; 7.0 | S, broad answer; completeness unverified |
| Language job recovery | 384 | G/2,404 warm | 4; 4,786; 1,405 | 29.0 s; 7.1 | S, **wrong recovery behavior** |
| Language reference | 384 | G/2,250 warm | 4; 4,683; 1,371 | 28.7 s; 7.1 | S, grounded |
| Weather source | 384 | G/2,084 warm | 4; 3,365; 1,042 | 24.8 s; 7.2 | S, grounded |
| Cross-system providers | 512 | G/2,263 warm | 4; 4,391; 1,301 | 30.4 s; 7.2 | S, **falsely says none** |
| W-02 | 512 | Y/1,926 warm, explicit override | 4; 5,309; 1,545 | 36.8 s; 7.1 | S, finding declared and grounded |
| F-01 | 512 | Y/1,948 warm, explicit override | 3; 4,494; 1,328 | 32.6 s; 7.3 | S, finding declared and grounded |
| F-02 | 512 | Y/1,743 warm, explicit override | 3; 4,300; 1,281 | 32.8 s; 7.0 | S, finding declared and grounded |
| F-03 | 512 | Y/1,492 warm, explicit override | 3; 4,108; 1,235 | 31.8 s; 7.2 | S, finding declared and grounded |
| F-04 | 512 | Y/1,371 warm, explicit override | 3; 4,253; 1,269 | 30.7 s; 7.0 | S, finding declared and grounded |
| L-01 | 512 | G/7,111 cold | 3; 4,303; 1,279 | 43.8 s; 6.6 | S, finding declared and grounded |
| Private unindexed journal | 512 | G/2,577 warm | 4; 4,758; 1,412 | 37.4 s; 6.8 | S, says insufficient but cites unrelated evidence |

The first W-02 512-token draft stated the null-to-zero behavior but left `conflictsMentioned` empty. Phase 5 now instructs the model to declare discussed finding IDs and locally rejects an omitted directly requested finding ID. The subsequent W-02 trial passed. All 15 final-case responses ended with `stop`; 15/15 were structurally complete, with zero malformed/truncated output, fabricated evidence/conflict IDs, action claims, or timeouts. Warm latency ranged 23.9-37.4 s (mean 30.3 s, median 30.5 s); cold L-01 took 43.8 s, and the separate cold Quote regression took 35.8 s. Generation speed was about 6.6-7.3 tokens/s. These are mixed-budget and mixed-prompt case results assembled across admitted passes, not a single-profile acceptance run.

The Language recovery failure is partly an evidence-selection limitation: Phase 4 selected Backend/API, Data flow, Frontend, and Integrations excerpts, but not the document's directly relevant **Jobs and recovery** section. Phase 5 cannot retrieve an absent section. The model then conflated missing Stanza packages/models with interruption recovery, saying work remains draft/recoverable instead of describing startup requeue, cancellation, and bounded attempts. The cross-system case contained an explicit Quote external-provider fact, yet the model said the evidence mentioned none. A six-item cross-system trial also denied that fact. The private-journal case said evidence was missing but cited four unrelated items; after a generic prompt clarification, a repeat asserted without support that no journal entry was ever indexed and again cited irrelevant items. The final prompt additionally names candidate subsystems and requires direct citation support; its eight-item trial was RED-blocked before generation. That last prompt revision has not passed a 15-case model run.

The 384/512/640/768 Quick budget comparison and 4/6/8/full real answer-quality comparison remain incomplete; 384 completed its seven admitted cases, and the shorter answer instruction plus schema avoided the earlier Quick truncation in those cases. The smallest reliable Quick budget is therefore **undetermined**; 512 is a provisional setting. The 90-second read timeout remains unchanged. The following grounding pass supersedes this earlier mixed-revision assessment.

Diagnostics classify provider timeout, malformed provider/draft JSON, schema violation, output truncation, unknown evidence ID, unknown conflict ID, action claim, and oversized response without logging private prompts. Factual quality checks in the evaluation are separate from draft-envelope validation.

## Grounding reliability and final single-revision run, 2026-09-29

The Language recovery miss came from Phase 4 ranking broad Backend/API, Data flow, Frontend, and Integrations sections above the reviewed `Jobs and recovery` section. Phase 4 now uses the bounded query-term/heading map and 28-point section-intent bonus documented in `PHASE4_RETRIEVAL.md`. The recovery benchmark selects `Jobs and recovery` as E1; the real answer describes requeueing interrupted RUNNING work, cancelling flagged work, and failing exhausted work after three attempts. The eight intent families are jobs/recovery, integrations/providers, storage/ownership, metrics/calculations, failure/degraded behavior, data flow, frontend, and backend/API. Ranking still uses only admitted indexed headings and content.

Cross-system property questions reserve one L1 section-intent match per candidate pilot before ordinary score order fills remaining slots. The rule keeps selected findings and exposes `reasonSelected`, trusted `relevanceSignals`, and `diagnostics.balancedEvidenceIds`. For the provider benchmark, the four model-facing sections are Quote, Finance, Language Learning, and Weather, in that order. Phase 5 projects verbatim provider-related sentences from those reviewed L1 excerpts or preserves a reviewed table. This makes Quote's external-request and local-fallback facts visible, but the small model still reverses their relationship. A focused trial substituting Quote's explicit provider-name Data flow text also made the same error. A stronger generic comparison prompt was tried and abandoned after it caused unknown evidence IDs on W-02 and F-01; the final run uses the shorter prompt and original 512-token Quick configuration.

For a broad property question, coarse citation validation requires a trusted section-intent or finding match when no subsystem is named. It rejects a cited item that is merely present in the pack but unrelated to the requested property. This is a relevance check, not claim-level fact verification: a model can still cite a related section and state the opposite of its text. An unsupported request with no pilot/topic/finding/section-intent support yields an empty Phase 4 selection and `supportStatus=none`. Phase 5 returns explicit insufficiency with an empty citation list before Resource Gate preflight or model generation; it makes no claim about whether private material ever existed.

The final table is one complete Quick/512 run on one retrieval, projection, prompt, validator, and profile revision. Every model call used a fresh Resource Gate preflight. `G` and `Y` are GREEN and YELLOW; YELLOW used the explicit controlled override. Eleven RED preflights across cases 1, 12, and 13 sent no chat request; the runner waited until RAM recovered or Ollama naturally unloaded, then retried. No threshold changed and RED was not overridden. Evidence bytes are model-facing serialized bytes.

| Case | Gate / available MiB | Items / bytes | Latency | Manual grounding |
| --- | --- | ---: | ---: | --- |
| Quote widget | G / 6,742 cold | 4 / 3,112 | 36.1 s | Pass |
| Quote fallback | G / 3,162 | 4 / 4,526 | 31.7 s | Pass |
| Finance canonical store | G / 2,679 | 4 / 4,312 | 30.9 s | Pass |
| Finance review | G / 2,431 | 4 / 4,681 | 33.3 s | Pass for stated controls; not a completeness proof |
| Language job recovery | G / 2,164 | 4 / 3,866 | 28.7 s | Pass |
| Language reference data | G / 2,040 | 4 / 4,683 | 31.9 s | Pass |
| Weather source | Y / 1,970 | 4 / 3,365 | 26.5 s | Pass |
| Cross-system providers | Y / 1,923 | 4 / 2,829 | 26.5 s | **Fail: denies Quote external providers because a local fallback exists; gives an unqualified Finance dependency despite the local OCR/Android evidence boundary** |
| W-02 | Y / 1,622 | 4 / 5,309 | 38.8 s | Pass; `conflict:W-02` |
| F-01 | Y / 1,376 | 3 / 4,494 | 35.0 s | Pass; `conflict:F-01` |
| F-02 | Y / 1,405 | 3 / 4,300 | 34.8 s | Pass; `conflict:F-02` |
| F-03 | Y / 1,249 | 3 / 4,108 | 31.7 s | Pass; `conflict:F-03` |
| F-04 | Y / 1,581 | 3 / 4,253 | 32.2 s | Pass; `conflict:F-04` |
| L-01 | Y / 1,520 | 3 / 4,303 | 33.3 s | Pass; `conflict:L-01` |
| Private unindexed journal | No preflight | 0 / 238 | 0 s | Pass; explicit insufficiency, no citation, no model call |

All 15 cases passed envelope validation: no malformed/truncated output, unknown evidence/conflict IDs, false first-person action claims, or model timeouts. The lexical content probes also passed 15/15, but manual factual review passed **14/15**. The cross-system probe's word-presence checks missed the explicit Quote inversion, so they cannot be treated as grounding proof. Across 14 model calls, latency was 26.5-38.8 s (mean 32.2 s, median 32.0 s), below the configured 90-second timeout. A separate same-revision Quote title-case regression correctly said an all-title-case valid quote is rejected and retried within the provider budget (YELLOW with explicit override, 25.5 s). The 49 deterministic Kermit index/retrieval/model/resource tests passed with one symlink test skipped because symlinks were unavailable. Phase 5 grounding is **not complete** and Phase 6 remains blocked by the provider-comparison failure.

## Manual local model setup

If Ollama is unavailable, install it separately, start its local service, and make one chosen compatible model available locally. For the default configuration, run `ollama pull qwen3.5:4b` explicitly, then run `health` and the Ollama `ask`/`eval` commands above. The [official Ollama model page](https://ollama.com/library/qwen3.5:4b) confirms the tag. No model is installed or downloaded by Kermit. If using another local tag, set `KERMIT_LLM_MODEL` (or per-profile variables) first. On a different host, set `KERMIT_LLM_BASE_URL` to the trusted Ollama origin; protect that host and connection before LAN use.

## Immutability and limitations

Model calls do not rebuild Phase 3, mutate source, open runtime DBs, run migrations, start workers, change dashboard configuration, or access ChatGPT history. Tests compare all six core Phase 3 artifact hashes, all admitted source hashes, and representative runtime database file metadata around fake evaluation. The model layer has no application file writer or runtime adapter. Ollama may change its own model residency state.

Only four pilot subsystems are indexed. Lexical retrieval can miss useful material; fake answers are structural fixtures; a local 4B model may hallucinate. The measured Quote provider inversion proves that a citation can accompany a false claim. The Phase 5 `DraftAnswer` remains an untrusted intermediate result; use the separate Phase 6 grounding path before any display. The prototype still has no UI, service identity, LAN authentication, or persona.
