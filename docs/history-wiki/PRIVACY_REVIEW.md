# History Wiki Phase 2 — privacy review

Date: 2026-09-23

The twelve legacy projects without source privacy were reviewed before wider
V2 rendering. Uncertainty was resolved conservatively; no existing sensitive
or third-party-sensitive value was downgraded.

| Project | Decision | Rationale |
| --- | --- | --- |
| P001 | private | Personal routines, task state and executive-function support. |
| P002 | private | Career history, work state and job-search material. |
| P003 | private | Personal travel plans and budgets. |
| P004 | private | Diet and daily-routine history. |
| P005 | private | Personal learning history and progress. |
| P006 | third_party_sensitive | Teaching materials can contain student or colleague context. |
| P007 | private | Personal reading history and annotations. |
| P008 | private | Personal media taste and listening history. |
| P009 | private | Personal extraction sources and archive workflows. |
| P010 | private | Conservative decision for mixed personal source material. |
| P011 | private | Personal creative work and fictional-world development. |
| P012 | private | Reflective tarot use and personal interpretation history. |

## Editorial escalations

The normalized layer may increase privacy for a specific conversation or
Journal claim when the user-message content requires it. Examples include:

- relationship material as `third_party_sensitive`;
- mental-health and medication material as `sensitive`;
- work messages naming colleagues as `third_party_sensitive`;
- genealogy involving living family context as `third_party_sensitive`.

These are presentation and synthesis safeguards. They do not rewrite canonical
privacy values under `ChatGPT/processed/`.

## UI rule

Journal sections are privacy-segmented. If a layer is not enabled, its prose is
not inserted into the DOM; the page shows a gated placeholder and requires an
explicit change of the global privacy selector. Search indexes only currently
enabled sections.

