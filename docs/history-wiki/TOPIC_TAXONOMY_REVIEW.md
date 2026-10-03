# History Wiki Phase 2 — topic taxonomy review

Date: 2026-09-23

All 177 canonical topic IDs remain unchanged. Phase 2 adds presentation roles:

| Role | Count | Meaning |
| --- | ---: | --- |
| `section` | 25 | Broad navigation root. |
| `topic` | 126 | Browsable subject with enough scope to stand alone. |
| `tag` | 26 | Narrow method, workflow or low-volume filter. |

## Assignment rule

Top-level nodes default to sections. Child nodes with no more than two combined
conversation/idea uses default to tags; other child nodes default to topics.
Human review overrides this deterministic rule.

Explicit overrides include:

- T001.5 is a `tag`: a reusable gamification/household method.
- T026 is a `topic`: the concrete household-gamification application.
- T020, T029, T031, T032, T033, T034 and T035 stay browsable topics rather
  than being promoted to global sections solely because they are top-level.

The complete role and usage mapping is in
`normalized/topic_navigation.json`. Roles affect navigation only, never
canonical identity or parent links.

