# History Wiki — Phase 2 report

Date: 2026-09-23  
Outcome: **Phase 2 complete; stopped before full Journal and final synthesis**

## Result

History Wiki now has a rebuildable normalized V2 layer sourced only from all 32
canonical batches. The stale nested `history_archive` snapshot is explicitly
excluded. Phase 1 is preserved in `_history_wiki_checkpoints/phase1/`.

Normalized coverage remains complete:

- 2,875 conversations;
- 35 projects;
- 177 topics;
- 303 ideas;
- 199 events;
- 117 relations;
- 104 insights;
- 308 evidence records.

## Semantic cleanup

- all three missing summaries resolved;
- four fully unclassified and eleven high-value underclassified conversations
  reviewed;
- 108 legacy classifications recorded in a bounded review pass;
- privacy completed for P001–P012;
- six human merge decisions stored as reversible `do_not_merge` records;
- all topics assigned `section`, `topic`, or `tag` roles.

## Genealogies and archaeology

V2 contains 13 typed genealogy edges, including P001 → P027, P007 → P034 and
P002 → P035. BM365 has shared feature identity F001 without merging P008 and
P027. Twenty-four selected ideas have conservative archaeology records, and six
unfinished threads retain evidence and an explicit next question.

## Journal pilot

Phase 1's conversation-creation-date method produced 731 candidate dates.
Grouping individual user messages in `Europe/Warsaw` produces **767** candidate
dates. This is now the only Journal grouping method.

The pilot contains:

- 14 days across 2023–2026;
- 60 claims;
- 53 factual sentences;
- 32 privacy-segmented sections;
- 0 unsupported sentences;
- 0 assistant-sourced claims;
- 0 timezone mismatches;
- 5 claims whose UTC calendar date differs from the Warsaw local date.

The prose intentionally keeps ordinary errands, project work, profanity,
relationship context and severe emotional material without turning the days
into generic therapeutic summaries. It is labeled `AI-reconstructed diary
entry`; it is not presented as a contemporaneous diary.

## History Wiki V2

The offline static app now exposes reading paths, draft eras, project
genealogies, idea archaeology, normalized conversation provenance, the merge
ledger and Journal pilot routes. Sensitive Journal sections require explicit
privacy-layer reveal and hidden prose is not inserted into the DOM. Global
search follows the currently enabled layers.

## Deliberate stop boundary

Phase 2 did **not** generate the other candidate days, final eras, a final
personal synthesis, or a final public/release build. The next decision is human:
review the era boundaries and the actual tone of several pilot days before
authorizing Phase 3.

