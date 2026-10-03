# Mental Health questionnaire language packs

Only wording verified against an authoritative source and cleared for this use belongs here. Missing, ambiguous, licensed, or incomplete instruments remain `external-score`; the loader never fabricates or translates items.

Install a pack as `mental_health_questionnaires/<instrument-id>/<language>.json`. Before switching an instrument to `native`, the loader validates schema, instrument/scoring versions, ISO language tag, exact question count and IDs, response values, reverse keys, subscale membership, optional gates/conditional questions, interpretation metadata, source provenance, and licence status. A failure is logged with the file and exact reason and leaves the instrument external.

Minimal shape (placeholder text is illustrative only and must not be used as a real questionnaire):

```json
{
  "schemaVersion": "1.0",
  "instrumentId": "phq9",
  "instrumentVersion": "1.0",
  "scoringVersion": "immutable-scoring-id",
  "language": "pl-PL",
  "questionTextStatus": "official_translation",
  "title": "OFFICIAL TITLE",
  "questionCount": 1,
  "scoredItemCount": 1,
  "source": { "title": "authoritative source", "url": "https://example.test/source" },
  "license": { "status": "verified status", "notice": "required notice" },
  "questions": [
    { "id": "1", "text": "EXACT AUTHORISED ITEM TEXT", "required": true }
  ],
  "responseOptions": [
    { "value": 0, "label": "EXACT AUTHORISED RESPONSE LABEL" },
    { "value": 1, "label": "EXACT AUTHORISED RESPONSE LABEL" }
  ],
  "scoring": {
    "type": "sum",
    "itemIds": ["1"],
    "allowedValues": [0, 1],
    "reverseItemIds": [],
    "subscales": {}
  },
  "interpretationBands": []
}
```

Questions may override `responseOptions`, declare `reverseScored`, and use validated `visibleWhen`/`visibleWhenAny` conditions. Gated definitions may declare `scoring.gate`. A derived difference such as SPANE-B is declared in `scoring.derivedSubscales` with explicit `minuend` and `subtrahend` base subscales. Do not mark machine-translated or paraphrased wording as `official_translation`. Every scoring change requires a new immutable `scoringVersion` and a deterministic fixture test before use.
