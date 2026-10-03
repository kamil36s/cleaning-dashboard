# Phase 7: local service and dashboard chat

Phase 7 exposes the existing static retrieval → local draft → deterministic grounding pipeline. It adds no knowledge source, tool, runtime adapter, page context, action, or memory.

## Start and configuration

From the repository root, deliberately rebuild the admitted static index when its sources change. For a standalone service start, run:

```text
python -B -m kermit_service
```

The service defaults to `127.0.0.1:8767`, uses Ollama and the configured model (normally `qwen3.5:4b`), and remains independent of `server.py`. Since Phase 7.1, normal local dashboard startup starts or reuses it by default; see `PHASE7_1_STARTUP.md`. This does not rebuild the index or load the model. The frontend calls this fixed loopback service. The dashboard remains usable when the service is offline. A dashboard opened on another device cannot use this loopback-only deployment.

Trusted service process settings are `KERMIT_SERVICE_HOST` (loopback only), `KERMIT_SERVICE_PORT`, `KERMIT_SERVICE_ORIGINS` (exact comma-separated loopback HTTP origins), and `KERMIT_SERVICE_PROVIDER`. The frontend endpoint is fixed in `js/kermit-config.js`. Model tags come from trusted `KERMIT_LLM_MODEL` or per-profile variants. Quick and Normal use the same model by default, with different output/evidence budgets. Deep and Max are not offered.

## HTTP contract

`POST /api/kermit/v1/ask` accepts JSON only, up to 2048 bytes:

```json
{"contractVersion":1,"question":"What does the Quote widget do?","profile":"normal"}
```

The question must be valid UTF-8, nonempty, and at most 500 characters. Profiles are `quick` and `normal`. The optional Boolean `allowMemoryPressure` works only after the same question/profile has received a YELLOW `confirmation_required`; the UI sends it after a separate Start anyway click. RED cannot be overridden. Unknown fields, including paths, URLs, source IDs, provider choices, models, SQL, capability flags, and context, are rejected. No chat history is sent.

Successful responses contain `contractVersion`, `status`, Phase 6 `answer`, `claims`, `citations`, `uncertainty`, `conflicts`, `groundingStatus`, `evidenceAsOf`, configured `model` and `profile`, plus bounded `timing` and `resource`. Prompt text, full evidence packs, provider diagnostics, process details, and credentials are excluded. A second in-flight ask receives HTTP 409 `busy`; prompts are not queued. Gate blocks return `waiting_for_memory`, `confirmation_required`, or `unavailable` with only RAM numbers. The Phase 5 model layer repeats preflight before generation, so a worsening reading can still block it.

`GET /api/kermit/v1/status` returns service/provider availability, configured model, profiles, `modelState`, Resource Gate state and numbers, and static index freshness/build fingerprint. States are `sleeping`, `loading`, `ready`, `generating`, `resource_pressure`, `waiting_for_memory`, and `unavailable`. A nonresident request starts as loading; an active status check changes it to generating when Ollama reports the model resident. A resident model starts at generating. After completion, status derives ready or sleeping from Ollama health. Status checks never load the model.

The service binds loopback and accepts exact configured loopback origins. Ask requires an Origin header; all requests require an exact local Host. CORS reflects only an allowed Origin and allows only ask POST preflight. It never proxies browser-chosen URLs. The service does not log questions or responses.

## Dashboard UI

The bottom-right Kermit button opens an isolated panel with in-memory messages, service-driven Quick/Normal selector, model state, index freshness/build prefix, composer, expandable sources, and evidence notes. One nonblocking status check runs when the panel mounts and another on open or Check again; checks every two seconds occur only while an open panel has an active request. The button and status checks do not load the model. RED displays available/minimum/recommended RAM and Check again. YELLOW displays Start anyway and Cancel. The UI never closes applications or retries while idle.

Answer text, citation paths and locators, uncertainty, and conflict descriptions use text nodes. Inline `[E…]` markers appear only for service-owned citations. Sources are repository-relative display text; they do not open files. `TEST_COVERAGE_GAP` and `UNKNOWN_BEHAVIOR` are labeled separately from factual conflicts. Model HTML, links, images, scripts, and dashboard actions do not execute.

Set `KERMIT_ENABLED = false` in `js/kermit-config.js` to disable the panel. Remove its script and stylesheet links from `index.html` to remove it entirely; widgets do not import it. Chat history lives only in the open browser session. Every question is independent.

There is no Phase 8 page/component context, Phase 14 LAN deployment, Phase 12 runtime or history adapter, or Phase 10 persona. Service requests do not write sources, indexes, or runtime state. Rebuild the derived index deliberately after admitted source edits.

## Live acceptance attempt — 2026-09-29

**Result: Phase 7 is not yet complete.** The real dashboard panel reached Ollama `qwen3.5:4b` through the service and displayed grounded answers, but the provider regression gate failed. Do not treat this attempt as authorization to begin Phase 8.

- Before the run, index validation found all 102 admitted sources current. Ollama was reachable with the model installed and sleeping. Cold-load Resource Gate was GREEN: 7,820 MiB available, 5,200 MiB minimum, 6,600 MiB recommended. No thresholds were changed.
- The browser showed the bottom-right control, opened and closed the panel, offered service-supplied Quick and Normal profiles, and sent only `contractVersion`, `question`, and `profile` in each observed ask. No page, widget, DOM, URL context, or screenshot field was sent.
- “What does the Quote widget do?” produced a real grounded Quick answer citing Quote evidence (`E4`). The visible model sequence was sleeping → loading → generating → ready. A concurrent second ask received HTTP 409 `busy` while the first completed.
- “Which external providers do the pilot subsystems use?” failed the required regression: the Quick **final** answer falsely said Quote had no direct provider and cited Quote evidence (`E1`). A Normal run produced `groundingStatus: invalid` with “cited evidence is unrelated to the request.” Raw model text is intentionally absent from the public service contract, so the exact raw draft from the UI request was not captured. Retrieval, model, and grounding logic were left unchanged as required for this acceptance-only pass.
- “What is F-02?” preserved the scoped UTC-versus-local-date ambiguity and displayed the finding register plus both source sides (`E1`, `E4`, `E5`) with uncertainty notes. The private unindexed journal request returned deterministic insufficiency with zero citations. A later cold request had `draftMs: 0` and left the model sleeping, confirming no model generation.
- GREEN generation was observed. YELLOW and RED remained covered by deterministic tests; memory was not deliberately exhausted. The model unloaded through its existing two-minute keep-alive: status changed ready → sleeping and available RAM rose from about 2,928 to 7,061 MiB. No background model request followed.
- With Kermit stopped, the dashboard still displayed its 34 widgets and the panel reported unavailable. It made one status request on opening and no idle retry over the following six seconds. After restarting the service, the next bounded check showed sleeping.
- Before and after querying, the index build fingerprint and all 102 source freshness checks matched. Size and modification times of representative cleaning, finance, and reading SQLite files were unchanged. No migration or application mutation was observed; no ChatGPT history adapter was present.
- The live test exposed one Phase 7 UI bug: an `invalid` GroundedAnswer was replaced with a generic outage message. The panel now renders the final answer and uncertainty while retaining the actual service/model state. Focused Python and JS tests passed after this fix.

## Focused live-grounding investigation — 2026-09-30

**Status: Phase 7 acceptance passed for the scoped local static-evidence deployment.** The central `server.py`/Vite restart did not start Kermit: it is an independent loopback process. The service was absent on port 8767, then started separately with `python -B -m kermit_service`; its status returned `serviceAvailable: true`, `qwen3.5:4b`, GREEN, and an index with 102 current sources and zero stale or missing sources. The fixed frontend address and service origin policy were unchanged.

- Offline saved replay and live execution used different question wording and model samples. The saved question was "Which pilots depend on external providers?"; its bad Quote statement was a separate sentence with no Quote citation. The live question was "Which external providers do the pilot subsystems use?"; Quick generated one comma-separated four-pilot sentence with "quote uses no direct provider" and cited `E1` through `E4`. The old claim extractor kept the list as one claim; the provider check read the positive introduction instead of the negative Quote member. The final answer wrongly accepted that entire sentence with Quote citation `E1`. The live question used build fingerprint `fc241b3a205b6b3710f0858e9d1586611e0dc6e5517c8728b152edd30c6fdd5c`, four reviewed integration sections `E1`–`E4`, Quick 512 output tokens, and the same `qwen3.5:4b` model as the saved replay.
- Normal used 768 output tokens and projected `E1`–`E6`. `E5` and `E6` were lexical `bills-store`/`widget-bills` metadata without integration-section relevance. The raw Normal draft cited both, so Phase 5 correctly rejected it as unrelated. The broad integration projection now exposes only the four matching reviewed sections to both profiles. The citation validator still rejects unrelated IDs.
- The system prompt now distinguishes an external request from a local fallback and browser-side from backend requests. Comparison lists are checked member by member. The exact bad Quick draft and generic synthetic relationship cases are in the grounding suite. Invalid drafts are replaced with a fixed verification-limitation answer at the public service boundary and in the UI; the validator reason remains in uncertainty. No rejected factual draft or citation is displayed.
- After the fix, live service-to-Ollama calls with the dashboard Origin returned `status: ok` and `groundingStatus: grounded` for both Quick and Normal on the external-provider question. Both final answers cited `E1`–`E4` and stated Quote has external requests; neither repeated the inversion. Quick reported one omitted unsupported draft claim; Normal reported four. The ordinary Quote question, Quote provider-failure question, and private unindexed journal question behaved correctly. The private-journal case had zero citations and `draftMs: 0`.
- The first F-02 rerun exposed a separate structural model error: `conflict:F-02` appeared in `citedEvidenceIds`. A second run omitted it from `conflictsMentioned`. Both invalid outputs displayed only the safe limitation text with a validator reason. The prompt now lists required requested-finding IDs separately from E-number citation IDs. A subsequent live F-02 call returned the register `E1` and independent UTC/local source sides `E4` and `E5`.
- Focused Python suites passed 78 tests with one pre-existing skip; the Kermit chat suite passed seven tests. Index validation reported 102 current sources, zero stale/missing, and zero errors. `git diff --check` returned exit code 0. The opt-in terminal-only trace uses no browser API field and retains no conversation artifacts.
- A headless Edge run of the full dashboard was stopped before generation when loading the browser pushed cold-start available RAM into YELLOW (5,362 MiB available; 5,200 MiB minimum, 6,600 MiB recommended). No override was sent and no user applications were closed. After RAM naturally recovered to GREEN, a minimal local page loaded the unchanged production Kermit panel module in Edge. Its Quick and Normal browser requests both reached the service and Ollama, displayed the correct Quote relationship and four bound sources, and showed the current index. The model-resident gate remained GREEN after both. The earlier full-dashboard live acceptance had already verified the panel's layout and request contract.
- A repeated live Quick service request was bracketed by SHA-256 checks of all 102 admitted source files and seven core index files plus size/mtime checks of three representative runtime databases. No watched source, index file, or runtime database changed, and the reply used the same validated build fingerprint. Phase 8 has not begun.
- Updating the admitted `docs/kermit/ROADMAP.md` deliberately changed one source after the comparison. The derived index was then explicitly rebuilt and validated: 102 current sources, zero stale/missing, build fingerprint `d4df0c9de5714c8ee99de66ee9ea99266125e0246d188014b29382c1311b7f30`. A second real Edge-panel Quick and Normal run on that final revision again displayed the correct Quote relationship with four bound sources. Phase 7 is complete within this local static-evidence scope; Phase 8 still requires a separate decision.
