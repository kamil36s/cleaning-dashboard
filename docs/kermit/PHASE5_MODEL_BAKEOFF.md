# Phase 5 local model bake-off (2026-09-29)

This is the completed controlled comparison for Kermit's **interactive** local model prototype. It establishes the `qwen3.5:4b` draft baseline with a known semantic limitation; Phase 6 grounding is required before display. Overnight analysis has not begun. All runs use the same Phase 4 index, retrieval and source admission, model-facing evidence projection, `DraftAnswer` schema, local validator, and fixed 15 questions. The baseline and new candidates use Quick's 4-item/512-token settings. The 15-case set and lexical probes remain in `kermit_model/evaluation.py`; `scripts/kermit_model_bakeoff.py` only selects Tier A or the full set, captures diagnostic measurements, and stops at a blocked Resource Gate. Lexical probes help review; manual grounding is the acceptance criterion.

## Candidates and compatibility

| Tag | Why tested | Ollama disk bytes | Reported capabilities | `think` request |
| --- | --- | ---: | --- | --- |
| `qwen3.5:4b` | Existing local baseline | 3,389,983,735 | completion, vision, tools, thinking | `false` |
| `gemma3:4b` | Similar size, different model family | 3,338,801,804 | completion, vision | omitted |
| `phi4-mini:3.8b` | Smaller CPU candidate | 2,491,876,774 | completion, tools | omitted |
| `mistral:7b` | Optional larger quality candidate after smaller screens | 4,372,824,384 | completion, tools | omitted |

The capability lists come from this machine's Ollama `/api/show` responses. Kermit never sends a tool declaration to any model, even when Ollama reports a model's tool capability. All attempted models receive native JSON-schema `format`, `temperature=0`, and `num_predict=512`. Schema support is established by complete responses, then independently checked by local validation. Ollama 0.34.4 is running on CPU AVX2; the GTX 1050 2 GB is not used for useful offload. The machine has 16,308 MiB physical RAM.

## Resource admission

All numbers are available **physical** MiB before a call. Below minimum is RED and blocked; between minimum and recommended is YELLOW and needs an explicit override; at or above recommended is GREEN. No threshold was lowered to finish a run. The new per-tag profiles began as conservative estimates from disk size and the earlier Qwen CPU measurement, then retained or increased those margins after observation. Ollama models were stopped through its normal unload command between candidates; no application process was killed.

| Model | Cold min / recommended | Resident min / recommended | Safety margin | CPU runner observation |
| --- | --- | --- | ---: | --- |
| Qwen | 5,200 / 6,600 | 1,200 / 2,000 | 1,500 | Earlier run: ~3,700 working set, 4,400â€“5,100 private |
| Gemma | 5,500 / 7,000 | 1,400 / 2,300 | 1,600 | ~4,257 working set, ~4,619 private MiB snapshot |
| Phi | 5,000 / 6,500 | 1,400 / 2,300 | 1,600 | Up to ~3,403 working set, ~3,443 private MiB in four after-call samples |
| Mistral | 6,400 / 8,200 | 1,700 / 2,600 | 1,800 | Up to ~5,300 working set, ~5,358 private MiB in four after-call samples |

These are local provisional gates, not certified requirements. A runner snapshot does not guarantee a true process peak, and memory can change after preflight. Each candidate's cold load began only after a GREEN preflight. After the Gemma and Phi screens, Ollama reported no resident models and available RAM recovered to roughly 9,000 and 8,389 MiB respectively.

## Tier A: five discriminating cases

Tier A uses Quote widget, Language job recovery, external-provider comparison, W-02, and private/unindexed journal. The journal is deliberately answered by deterministic insufficiency before model invocation. A structurally valid envelope can still be factually wrong.

| Model | Structure | Manual grounding | External-provider comparison | Decision |
| --- | --- | --- | --- | --- |
| Qwen baseline | 5/5 | 4/5 | Incorrectly denies Quote external dependency because local fallback exists | Existing full suite retained |
| Gemma | 4/5 | 3/5 | Omits Quote and incorrectly treats local Finance OCR evidence as external dependency | Full suite skipped |
| Phi | 2/5 | 1/5 | Omits Quote; only one of four model calls validates | Full suite skipped |
| Mistral | 2/5 | 1/5 | Invalid draft with unknown conflict ID | Full suite skipped |

Gemma's W-02 draft had an unknown evidence ID. Phi's Quote and Language recovery drafts had unknown conflict IDs; its W-02 draft had an unknown evidence ID. Mistral's Quote, Language recovery, and external-provider drafts had unknown conflict IDs. Mistral returned a valid W-02 envelope but only said W-02 is a weather-system issue; it did not describe the null-to-zero disagreement. These are local validator rejections or manual factual failures, not accepted answers. No new candidate had malformed JSON, truncation, a timeout, or a Resource Gate block in Tier A. The external-provider question's selected Quote evidence explicitly says there are external requests and a local fallback; the fallback does not negate the external dependency. Finance's selected section instead describes local Tesseract and Android ML Kit inputs with no direct bank API. The existing lexical probe detects missing words but cannot prove these distinctions.

| Model | Cold total / Ollama load | Warm range / mean / median | Mean generation speed | Lowest observed available RAM | Gate blocks |
| --- | --- | --- | ---: | ---: | ---: |
| Gemma | 27.7 / 5.6 s | 22.3â€“33.1 / 28.0 / 28.5 s | 8.3 tokens/s | 3,995 MiB | 0 |
| Phi | 32.3 / 4.6 s | 16.0â€“43.6 / 29.9 / 30.0 s | 8.1 tokens/s | 4,778 MiB | 0 |
| Mistral | 58.6 / 5.0 s | 39.5â€“65.0 / 55.9 / 63.1 s | 5.2 tokens/s | 3,487 MiB | 0 |

## Full acceptance and profile decision

The established single-revision Qwen run remains the baseline: **15/15 valid envelopes and 14/15 manually grounded**, with the external-provider comparison as its one factual failure. Fourteen model calls took 26.5â€“38.8 s warm (mean 32.2 s, median 32.0 s); the deterministic journal case took 0 s. Its cold Quote call took 36.1 s total. Generation ran roughly 6.6â€“7.3 tokens/s. It had zero malformed/truncated responses, unknown IDs, action claims, and timeouts. The same run encountered 11 RED preflights, waited for natural unload or RAM recovery, and used explicit YELLOW overrides for admitted YELLOW calls. This result does not satisfy the final Normal grounding criterion.

Only Qwen's full run covered Finance canonical/cache distinctions, rebuildable Language reference versus canonical user state, and F-01 through L-01 finding preservation; those cases passed its earlier manual review. The new candidates did not qualify to test these full-suite distinctions. All four models used the same deterministic insufficiency path for the private journal case, with no model call or unsupported citation.

No new candidate met the Tier A threshold for a full 15-case acceptance run. Thus there is **no new full-suite result**: Gemma, Phi, and Mistral are respectively 4/5, 2/5, and 2/5 structurally valid in Tier A (including deterministic journal insufficiency), and 3/5, 1/5, and 1/5 manually grounded. Across all new model calls, local validation caught the unknown IDs and accepted no tool/action claim. All calls completed under the 90-second timeout. The 7B model is physically loadable on this desktop, but is much slower and did not demonstrate better quality. In this configuration, none of the new models is suitable for Kermit's chat role.

| Interactive profile | Recommendation now | Reason |
| --- | --- | --- |
| Quick | `qwen3.5:4b` draft prototype | Best measured latency/grounding combination; its known provider-comparison error remains |
| Normal | `qwen3.5:4b` plus Phase 6 grounding | The same draft model needs claim-level verification before final display |
| Deep | Unassigned | A larger model did not improve this evidence task; no accepted quality gain |
| Max | Unavailable on this desktop | No demonstrated high-quality model/profile at this resource level |

The profile variables can already express `interactive.quick`, `.normal`, `.deep`, and `.max` through deterministic per-profile model tags. These are provisional recommendations, not a claim that a production-ready Normal profile exists. **Phase 5 is complete as a local model prototype with known model limitations.** The raw model is not required to reach 15/15; Phase 6 evaluates and filters its draft claims. No unauthorized model was downloaded, and no tested model was deleted. Installed tags at the end: Qwen, Gemma, Phi, and Mistral.

## Verification

The four focused Kermit suites passed **53 tests**, with one existing symlink-related skip. During the Mistral run, SHA-256 of 108 files (six Phase 3 core artifacts and 102 admitted source paths) and size/mtime metadata of two representative runtime DBs matched before and after. The earlier Gemma and Phi calls likewise used only the read-only model boundary, but that specific before/after snapshot began before Mistral. No source, index, runtime database, Phase 4 retrieval/admission rule, benchmark answer, or JSON contract was edited for a model. `git diff --check` returned clean for tracked changes. Kermit's files were already untracked in this workspace, so a separate trailing-whitespace scan of the edited Kermit files also returned clean.

## Future workload classes

Current Kermit is `workload_class="interactive"`: Quick, Normal, Deep, and Max are user-controlled configuration profiles over one fixed retrieval and security boundary. The configuration rejects `batch` for now. A future `batch.weekly` or `batch.deep_analysis` class may use a larger, slower model on other hardware for overnight work, while sharing the same evidence authority and read-only boundary. This bake-off adds no scheduler, weekly job, runtime adapter, dashboard insight pipeline, or automatic model router.

