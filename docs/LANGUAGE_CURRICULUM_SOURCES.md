# Language curriculum source decisions

Audit date: 2026-09-17

This document records the Phase 7.8 source and rights decisions. A source being authoritative for terminology does not automatically make it a learner curriculum. Membership must be source-defined or explicitly human-reviewed, licensed for the stored use, versionable, and mappable without pretending that ambiguity is a match.

## Accepted for active packs

### Los 3.0 — Digitaliseringsdirektoratet

- Official catalog: <https://data.norge.no/en/datasets/c479c6db-af9d-4467-a238-f30480d153e9/los-felles-terminologi-for-offentlige-tjenester>
- Documentation/version policy: <https://data.norge.no/guide/los-dokumentasjon>
- Pinned RDF artifact: <https://psi.norge.no/los/all.rdf>
- License: CC0 1.0, as declared by the official catalog.
- Audited artifact metadata: `Last-Modified: 2023-03-01T13:09:58Z`; SHA-256 `e6f3266e404aa91d73e31cec0f211814f2fe9a6daadbc1864478287239ba837f`.
- Membership semantics: recursive leaf SKOS concepts below one official top-level theme. Intermediate grouping concepts are excluded. Source membership is not inferred from frequency or generated text.
- Accepted themes: Work, Housing and property, Health and care, Traffic and transport, and Tax and duties.
- Pedagogic limitation: Los is a public-service terminology hierarchy, not a full everyday-language or workplace-communication syllabus. All items therefore use equal `USEFUL` priority; no unsupported source ranking is invented.

The offline builder verifies the exact source checksum before producing manifests. Each manifest pins the Los snapshot, mapping policy, reference schema/fingerprint, release date, stable membership IDs, mapping outcome, and semantic pack fingerprint. Rebuilding the five manifests from the audited artifact is byte-deterministic.

## Audited but deferred

### SNORRE terminology database — National Library of Norway / Språkbanken

- Official resource page: <https://www.nb.no/sprakbanken/en/resource-catalogue/oai-nb-no-sbr-43/>
- The official page exposes a CC0 terminology export with Norwegian Bokmål/Nynorsk/English terms.
- Deferred because the corpus is specialist terminology, not a source-defined practical learner curriculum. It may be useful in a future domain-specific pack only after a domain and learner-scope review.

### Norwegian public-data catalog and concept catalog

- Catalog: <https://data.norge.no/>
- The catalog is an authoritative discovery surface, but licenses and membership semantics belong to each dataset. It is not accepted wholesale as one curriculum source.
- NLOD terms were reviewed at <https://data.norge.no/nlod/no>; datasets using NLOD can permit reuse with attribution and non-misleading presentation, but that does not itself define learner membership.

### Arbeidstilsynet guidance and regulations

- Official information pages are authoritative guidance, but ordinary page prose does not provide a stable, licensed, source-defined vocabulary membership list.
- Workplace Safety and construction/tool packs remain unavailable rather than turning scraped page words into an authoritative curriculum.

### NTNU and other web word lists

- Candidate educational lists were discoverable, but redistribution/storage rights and stable versioned membership were not clear enough for ingestion.
- Deferred pending a specific rights review and reviewer-approved manifest.

## Explicitly unavailable in Phase 7.8

Norway Essentials, Everyday Norwegian, Work Basics, Warehouse, Construction & Tools, Workplace Safety, Shopping, Job Interview, and Football are cataloged as `UNAVAILABLE` with an honest reason. KELLY rank, word frequency, arbitrary web pages, model suggestions, and the existing reference lexicon are not substitutes for reviewed membership.

## Mapping and denominator policy

- Mapping is an exact normalized lookup against the pinned production reference snapshot `sha256:5395a0d1aa2c300f956e04ff69af338463d923d04a14b25bdeffacd416f781e9`.
- One candidate is `MAPPED`; multiple candidates are `AMBIGUOUS`; no candidate is `UNRESOLVED`; policy/review removal is `EXCLUDED`.
- Only `APPROVED + MAPPED` items enter the completion denominator.
- `UNSEEN` means no canonical user lemma exists. `NEW` means a canonical user lemma exists with `LemmaKnowledge.NEW`.
- Only `KNOWN` and `MASTERED` count as acquired, and those states remain separate in all detailed counts.
- Browsing/searching/opening a pack or item is read-only and creates no lemma, knowledge, exposure, XP, achievement, Anki, Topic, or phrasebook state.

## Reproduction and validation

```powershell
python scripts/build_language_curricula.py --source .firecrawl/los-all.rdf
python scripts/validate_language_curricula.py --json
```

The source artifact is intentionally not committed; the tracked manifests are the runtime artifacts. The builder requires the audited checksum and the configured production reference database. A source update must create a new reviewed source/pack version; it must not silently rewrite an existing version.
