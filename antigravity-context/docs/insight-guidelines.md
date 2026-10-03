# Insight guidelines

Find meaningful patterns instead of narrating every value.

Prioritize:

- material change versus the previous comparable window;
- sustained trends rather than one isolated observation;
- unusual values or threshold crossings;
- cross-domain relationships where dates and windows genuinely align;
- overdue, time-sensitive, or actionable issues;
- data freshness problems that limit confidence.

Ignore stable or low-signal metrics unless they provide important context. “Temperature is 23.2 °C” and “four tasks were completed” are observations, not insights by themselves.

A useful insight states the evidence, comparison window, magnitude, and uncertainty. For example: “Average activity decreased 18% from the previous seven days while training frequency was unchanged; the reduction is concentrated outside recorded workouts.” The first clauses must be supported directly by exported facts; the final clause is an interpretation and must be labeled or phrased with appropriate uncertainty.

Never:

- invent causes, goals, diagnoses, identities, or missing measurements;
- turn correlation into causation;
- treat an unavailable value as zero;
- infer private details from opaque IDs;
- recommend medical, financial, or other high-stakes action from these summaries alone;
- request access outside this directory.

Recommendations should be specific, proportionate, and traceable to a documented fact. If evidence is weak or stale, say so and recommend collecting better data rather than guessing.
