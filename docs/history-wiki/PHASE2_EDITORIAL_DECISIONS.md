# History Wiki Phase 2 — editorial decisions

Date: 2026-09-23

## Source boundary

The canonical source is exclusively `ChatGPT/processed/batches/data/` together
with raw `batch_000.jsonl` through `batch_031.jsonl` (2,875 conversations).
`ChatGPT/processed/batches/history_archive/` is a historical snapshot ending at
batch 007 and is explicitly excluded from normalization.

Phase 1 was checkpointed under `_history_wiki_checkpoints/phase1/` before Phase
2 outputs were generated. No file under `ChatGPT/processed/` was modified.

## Human-confirmed merge decisions

| Candidates | Decision | Normalized relation |
| --- | --- | --- |
| T001.5 / T026 | Do not merge | T001.5 remains a method/tag; T026 is the concrete household application. |
| P001 / P027 | Do not merge | `P001 implemented_as P027`; Personal Dashboard is a descendant implementation. |
| P007 / P034 | Do not merge | `P007 specialized_as P034`; SynchroBook is a specialized descendant. |
| P008 / P027 (BM365) | Do not merge parent projects | Shared feature identity `F001` connects cultural-project and dashboard contexts. |
| P017 / P019 | Do not merge | Related scopes with separate privacy boundaries. |
| P002 / P035 | Do not merge | `P002 branched_into P035`; the manual/work-abroad path is not a linear replacement. |

The reversible records are in `normalized/merge_ledger.jsonl`; aliases and the
BM365 shared identity are in `normalized/aliases.json`.

## Classification cleanup

- Three blank summaries were filled conservatively. Two image-only records say
  that exported user text is unavailable; the assistant-only World Cup briefing
  is explicitly marked as an exception.
- Four fully unclassified conversations were reviewed. Topic-only transient
  requests remain topic-only; relationship history was assigned to P017 and
  privacy-escalated; Vinted received workflow topics.
- Eleven high-value underclassified conversations were reviewed. The land
  search remains topic-only rather than receiving a forced project; the CO2
  conversation is linked to P025.
- All 108 `legacy_classification` records have bounded review entries. The
  ledger contains 113 rows because several targeted non-legacy records are also
  included.

Canonical IDs and schemas were retained. Corrections exist only in the
rebuildable normalized layer.

## Conservative interpretation rules

- Later same-project events in idea archaeology are context candidates, not
  automatic proof of implementation or completion.
- Missing later evidence never means `abandoned`.
- Era names avoid exposing the most sensitive event in navigation titles.
- Journal prose cannot introduce facts from assistant responses.

