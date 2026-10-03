# Phase 6: claim grounding and final answer contract

Status: COMPLETE for the scoped static four-pilot prototype. The 15-case saved-real-draft replay passed after reviewed side binding. Phase 5 remains the `qwen3.5:4b` interactive draft baseline. A later Phase 7 live regression exposed a comparison-list gap described below.

## Boundary and contract

`kermit_grounding.ask_grounded` runs Phase 4 retrieval, Phase 5 `generate_draft`, then `ground`. The Phase 5 model sees only its fixed bounded EvidencePack projection and has no tools or retrieval callback. Phase 6 makes no model call, source read, database query, or application mutation. `kermit_grounding/grounded-answer.schema.json` versions the output as `GroundedAnswer` version 1. The local CLI is `python -B -m kermit_grounding ask ...` or `eval`; it is not a dashboard or HTTP service.

`GroundedAnswer` contains readable `answer`, `claims[]`, service-owned `citations[]`, `uncertainty[]`, `conflicts[]`, `groundingStatus`, and `evidenceAsOf`. A `Claim` has `claimId`, atomic `text`, `type`, `evidenceIds[]`, `supportStatus`, `supportReason`, and `conflictIds[]`. The implementation also reports draft and grounding latency. Claim types reuse the Phase 4 claim type where possible and distinguish integration/provider, storage, calculation, limitation, and historical/proposed wording. The five support statuses are `supported`, `partially_supported`, `contradicted`, `conflicted`, and `unsupported`. The conservative current classifier emits supported, contradicted, conflicted, or unsupported; it reserves partial for a future rule that can identify and safely qualify a separable supported clause.

## Claim extraction and support

`extract_claims` is deterministic. It removes headings and pure insufficiency wording, splits bounded sentences and selected independent clauses, and never exposes a chain of thought. A draft remains untrusted even if its envelope contains valid IDs. For each claim, Phase 6 compares its words, polarity, provider relationship, SQLite path, numbers, status, and storage role against selected Phase 4 evidence. The service binds candidates to the selected pack, checks the draft's cited IDs for positive support, and also checks other selected items for contradiction. An unrelated model citation cannot prove a claim. An unknown draft ID raises an error; an inline unknown ID or action claim is discarded. Exact canonical SQLite path declarations and direct source text can be supported. Explicit opposite provider/request polarity, contradictory numbers in a matching source sentence, noncanonical storage metadata, and proposal-to-current upgrades are rejected. Ambiguous paraphrases remain unsupported. This is a deliberately narrow semantic checker, not a general entailment engine.

Source authority follows `SOURCE_POLICY.md`: verified current implementation and active schema govern current behavior; current docs govern declared architecture within scope; canonical runtime values require an authorized runtime adapter, which this phase does not have. Generated, cached, raw, backup, legacy, proposed, and historical material cannot silently become current canonical truth. Items marked stale by Phase 4 are withheld from final source excerpts. The same source policy applies regardless of reasoning profile.

## Repair, synthesis, and citations

Supported draft claims may be retained. Contradicted and unsupported draft claims are omitted, with an uncertainty count. Conflicted claims are represented by registered findings and their selected evidence context, rather than flattened into one side. If no draft wording passes and selected current evidence is relevant, a bounded deterministic fallback selects exact reviewed source sentences or table cells from the Phase 4 pack. Each displayed fallback sentence has a supported source claim record. This is source attribution, not a model rewrite. There is no iterative repair loop or final synthesis model call. If neither draft nor selected evidence supports an answer, the final answer states insufficiency without a citation.

The service creates citation objects only from exact `selectedEvidence` IDs, repository paths, locators, source hashes, fact status, storage role, and freshness. Model-provided IDs are candidates, never rendered as citation objects by themselves. A displayed factual sentence carries an inline `[E#]` marker and a matching `citations[]` record. `displayedClaimIds` maps every final sentence to an approved claim or explicit uncertainty. Finding categories, descriptions, and exact side spans come from reviewed deterministic metadata in `kermit_index/finding_sides.json`, copied into the validated Phase 3 index. Phase 4 selects only admitted, current, hash-matching spans. Phase 6 independently checks each selected side ID against its reviewed path, hash, locator, and anchor. The register remains a separate discovery citation. `independently_cited` requires both primary sides for a documentation drift or factual conflict; `not_a_two_sided_conflict` preserves gaps and scoped behavior differences; `register_summary_only` and `insufficient_primary_evidence` explicitly flag missing selected primary sides. The model does not choose side mappings or resolve findings.

## Reviewed finding audit

| Finding | Category | Side A primary source | Side B primary source or gap | Final status for direct query |
| --- | --- | --- | --- | --- |
| Q-01 | `TEST_COVERAGE_GAP` | `js/widget-quote.js` provider/fallback declarations | No focused Quote test in the reviewed inventory; register records the coverage gap, not an opposing claim | `not_a_two_sided_conflict` |
| W-01 | `TEST_COVERAGE_GAP` | `js/api/openMeteo.js::fetchWeather` | No focused Weather test in the reviewed inventory; register records the coverage gap, not an opposing claim | `not_a_two_sided_conflict` |
| W-02 | `DISPLAY_OR_IMPLEMENTATION_QUIRK` | `js/api/openMeteo.js::fetchWeather` copies hourly values directly | `js/ui/render_weather_api.js::renderNext` converts those values with `Number`; explicit `null` becomes zero | `not_a_two_sided_conflict`; both implementation spans cited |
| F-01 | `DOCUMENTATION_DRIFT` | `PROJECT_MAP.md` says CSV source evidence is preserved before normalization | `finance_service.py::FinanceService.import_csv` parses raw bytes; `tests/test_finance_import.py` observes no CSV source file in the service directory in a focused import | `independently_cited` |
| F-02 | `AMBIGUOUS_SEMANTICS` | `finance_analytics.py::_parse_date` defaults to UTC date | `finance_planning.py::FinancePlanningService.overview` defaults to local `date.today()` | `not_a_two_sided_conflict`; both scoped defaults cited |
| F-03 | `AMBIGUOUS_SEMANTICS` | `finance_planning.py::_freshness` uses fresh through day 3, aging through day 14 | `finance_analytics.py::FinancePeriodService.freshness` uses current through day 1 | `not_a_two_sided_conflict`; both endpoint rules cited |
| F-04 | `AMBIGUOUS_SEMANTICS` | `finance_receipts.py::analytics_category_breakdown` can allocate eligible receipt items | `finance_planning.py::report` groups expense transaction categories | `not_a_two_sided_conflict`; both endpoint rules cited |
| L-01 | `DOCUMENTATION_DRIFT` | `PROJECT_MAP.md` denies a literal provider `responseSchema` key | `language_learning/providers/generation.py::_request_once` sends `responseJsonSchema` and JSON MIME; both statements are literally true but the high-level wording omits the active schema key | `independently_cited` |

No finding asserts two incompatible facts about the same current endpoint. F-01 and L-01 are the two documentation-versus-implementation discrepancies with independently cited sides. The other four two-source findings describe scoped implementation differences, and Q-01/W-01 describe missing verification. The reviewed register is an inventory of these findings, not an independent primary source for either code side.

## Known Quote regression

The selected Quote evidence states that external requests exist and that a local fallback exists. These facts are compatible. The raw Qwen draft in the cross-system provider case denied Quote's external dependency because of the fallback. Phase 6 checks the relationship, omits the inverted claim, and cites the Quote evidence in the final answer. The rule tests external-request polarity generally; it contains no Quote-specific answer string.

### Live comparison-list regression (2026-09-30)

The saved replay asked "Which pilots depend on external providers?" and the raw draft put the false Quote assertion in its own sentence without citing Quote. The Phase 7 browser asked "Which external providers do the pilot subsystems use?" Quick returned one comma-separated sentence listing all four pilots, including "quote uses no direct provider". `extract_claims` treated the whole list as one claim. `_provider_fact` found the positive "external providers" introduction and missed the negative relationship inside the Quote member. `_check_against` then accepted the aggregate on broad provider-word overlap with Quote evidence. The final composer displayed that entire model sentence with `[E1]`. This was a checker defect, not merely a model error or a stale index.

Grounding now splits comparison lists at the selected subsystem names before checking support, recognizes scoped provider negation including direct requests, and avoids treating an unrelated negation in a neighboring source clause as opposition. The exact live Quick wording is a deterministic regression: its Quote member is `contradicted` and omitted. Synthetic cases cover external requests with local fallback, genuine absence, browser requests without a backend integration, and `directly`, `only`, `never`, and `always`. An opt-in local CLI (`KERMIT_DEV_TRACE=1 python -B -m kermit_grounding.trace "..."`) prints a bounded in-memory trace of retrieved/model-facing evidence, raw structured draft, claim bindings, decisions, and final response; it is not an HTTP route or persistent conversation log.

## Evaluation and limits

`tests/test_kermit_grounding.py` covers atomic extraction, the Quote inversion, unknown and unrelated citations, canonical SQLite support, proposed/cache status, adversarial claims, registered findings, insufficiency, and source/index immutability. `kermit_grounding.evaluation` runs the existing 15 questions and reports raw versus final results with explicit semantic assertions and forbidden claims. The fake provider is a structural fixture. A real `qwen3.5:4b` run still requires manual review of every final factual sentence and case completeness; the automatic checks do not certify semantic grounding.

The deterministic checker deliberately declines many correct paraphrases, so fallback source text can be more technical than a polished answer. It cannot infer every implicit fact, prove absence from incomplete evidence, or resolve a finding that lacks both primary source sides in the pack. Phase 1 operating-system isolation and a Phase 7 UI are separate work. Quick uses the current Qwen draft baseline; Normal is provisionally Qwen plus this grounding gate. Deep has no accepted larger model and Max is unavailable. A future batch workload may reuse the contract without sharing this interactive model selection.

## Benchmark result

The existing 15 questions ran through real Phase 4 retrieval and 14 `qwen3.5:4b` Quick draft calls, then deterministic Phase 6 grounding; the private journal case called no model. Eight model calls completed in the first final run; six later case attempts were RED-blocked with zero chat requests. The six were rerun after the model naturally unloaded and memory recovered, without changing thresholds. Saved drafts and exact cited IDs were replayed through the final deterministic grounding revision with `python -B -m kermit_grounding.replay` so no second model sampling was confused with a verifier.

| Case | Raw draft review | Final output |
| --- | --- | --- |
| Quote widget | Grounded | Grounded |
| Quote provider fallback | Grounded, but conservative claim matcher declined wording | Grounded behavior; Q-01 details uncertain |
| Finance canonical store | Grounded | Grounded |
| Finance review | Grounded for stated controls | Grounded excerpts |
| Language job recovery | Grounded | Grounded excerpts |
| Language reference data | Grounded | Grounded excerpts |
| Weather source | Grounded | Grounded |
| Cross-system providers | **Failed:** Quote external dependency inverted; Finance dependency unqualified | Quote inversion removed; four pilots described from their selected evidence |
| W-02 | Grounded | Adapter and renderer spans independently cited; display quirk typed |
| F-01 | Grounded | Documentation and import code independently cited |
| F-02 | Grounded | Both scoped date defaults cited |
| F-03 | Grounded | Both scoped freshness rules cited |
| F-04 | Grounded | Both category allocation rules cited |
| L-01 | Grounded | Documentation and provider request code independently cited |
| Private unindexed journal | Deterministic insufficiency | Deterministic insufficiency, zero citations |

Manual raw factual review was 14/15 cases, with two misleading assertions in the one cross-system answer. Manual final review found zero unsupported accepted factual claims across 15 cases; the explicit uncertainty on summary-only conflicts is part of that result. The current deterministic classifier accepted one draft claim, marked one contradicted (the Quote inversion), and withheld 14 more as unsupported, including some correct paraphrases. Those 14 are verifier false negatives or unresolved wording, not 14 raw factual errors. Source-owned fallback excerpts kept the final answer factual. All 15 automated semantic/citation checks passed, including a Finance-specific assertion that an unrelated Reading store cannot appear. Across the 14 model calls, mean draft latency was 32.4 seconds. A 150-call deterministic replay measured mean grounding time 1.99 ms, median 1.67 ms, maximum 5.8 ms; these timings exclude retrieval and Resource Gate waiting. The fake 15-case suite also passed all checks.

The mandatory Quote regression passes: the raw draft denies Quote external providers; the final answer names Quote external requests, and the inverted claim is classified `contradicted` when checked against selected Quote evidence. Directly requested W-02, F-01, F-02, F-03, F-04, and L-01 all remain visible with separate primary side IDs. Q-01 and W-01 remain visible as test gaps without fabricated opposite sides. Source/index/runtime immutability is checked in the focused suite; no model verifier or synthesis model was needed.

**Acceptance decision:** Phase 6 passes the scoped static-evidence gate: both documentation drifts have distinct primary side citations, all other registered findings retain their actual type, and direct queries retain the register plus available primary spans. No direct finding query remains `register_summary_only`. This does not authorize Phase 7 work in this pass.

After updating the admitted `ROADMAP.md` and `PROJECT_MAP.md`, the derived Phase 3 index was rebuilt and validated with 102 admitted sources, eight findings, and zero stale or missing sources. Replaying the saved real drafts against that refreshed index still passed all 15 semantic checks. Query execution itself did not change the index, admitted sources, or representative runtime databases.
