# Language Phase 7.8 results — curated vocabulary curricula

Completed: 2026-09-17

## Outcome

Phase 7.8 adds fixed, source-defined, versioned Bokmål curriculum packs without adding a second learning store. Five active Los 3.0 public-service packs are available at `#curriculum`; nine requested but unsupported practical packs remain visibly unavailable rather than fabricated.

The implementation adds manifest validation/fingerprinting, deterministic offline rebuild tooling, a read-only `CurriculumService`, exact canonical `LemmaKnowledge` progress, transparent denominator quality, three thin GET routes, shared lexical/reference item detail, safe responsive UI, Phase 7.6 Collection integration, and the generic `CURRICULUM_PACK_PROGRESS` campaign milestone pinned to pack ID, version, and fingerprint.

No main or reference database migration was required. Main schema remains v10; reference schema remains v3 and is read-only.

## Released pack inventory

| Pack | Source | Mapped / ambiguous / unresolved | Eligible |
| --- | ---: | ---: | ---: |
| Work and employment services | 34 | 22 / 2 / 10 | 22 |
| Housing and property services | 43 | 19 / 1 / 23 | 19 |
| Health and care services | 77 | 42 / 1 / 34 | 42 |
| Traffic and transport services | 56 | 29 / 0 / 27 | 29 |
| Tax and duties services | 11 | 5 / 1 / 5 | 5 |
| **Total** | **221** | **117 / 5 / 99** | **117** |

All 221 source memberships are explicitly approved in v1; there are no hidden draft, rejected, or excluded production rows. Ambiguous and unresolved rows stay inspectable and never enter the 117-item denominator.

## Contracts and ownership

- Manifests are immutable versioned artifacts under `language_learning/curriculum_packs/` with stable source membership IDs and SHA-256 semantic fingerprints.
- `CurriculumService` loads manifests lazily and derives user state through one bounded indexed batch query. It never writes user tables.
- Canonical learning truth remains `VocabularyLemma` plus `LemmaKnowledge`; `UNSEEN` is absence, while `NEW`, `LEARNING`, `KNOWN`, and `MASTERED` retain their established meanings.
- `KNOWN_OR_MASTERED` is the only pack completion rule. Pack progress is not CEFR, proficiency, or a universal Norway-readiness score.
- Topics remain mutable partial user groups; curricula are fixed reviewed versions. Phrasebook saves remain expressions/bookmarks. Anki remains the only SRS.
- Collection tier presentation reuses Phase 7.6 thresholds but adds no XP, achievement, quest, penalty, or new mastery state.
- A campaign can select only an active pack, then stores the exact pack version and fingerprint. Later campaign reads resolve that exact historical version even if another version becomes active.

## API and UI

Read-only routes:

- `GET /api/language/profiles/{profileId}/curriculum`
- `GET /api/language/profiles/{profileId}/curriculum/{packId}/versions/{version}`
- `GET /api/language/profiles/{profileId}/curriculum/{packId}/versions/{version}/items/{membershipId}`

The landing page shows provenance, source version/license, full quality counts, eligible denominator, acquired count, and progress. Pack detail adds search and `UNSEEN`/`NEW`/`LEARNING`/`KNOWN`/`MASTERED` filters. Item detail reuses the Phase 7.7 dictionary and Phase 7.5C reference presentation without materializing an absent lemma. All curriculum-controlled strings render through text nodes.

## Validation evidence

- Manifest validator: 5/5 active manifests valid; deterministic rebuild reproduced byte-identical files.
- New Phase 7.8 backend tests: 6/6 pass (5 curriculum-domain tests plus 1 thin HTTP/API test).
- Complete Language backend: 181/181 pass after the thin HTTP route test was added.
- Complete Language frontend/widget: 99/99 pass.
- Broad backend: 595 pass, 1 skipped.
- Broad frontend: 779 pass, 2 skipped.
- Python compilation and changed JavaScript syntax checks pass.
- Vite production build passes with 270 modules transformed and includes `dist/language.html`.
- Real Edge landing-page smoke passes on the current API at desktop and narrow layouts; safe-DOM behavior and state filtering also have focused DOM tests.
- Main v10 database: `integrity_check = ok`, zero foreign-key violations.
- Temporary SQLite backup/restore dry run: 35-table row-count map identical, restored `integrity_check = ok`, zero foreign-key violations.
- Unchanged 4.22 GB reference v3 database: read-only `integrity_check = ok`, zero foreign-key violations (346,369.7 ms).

Performance fixture: with 20,000 canonical user lemmas, the five-pack landing uses one indexed SELECT and measured 2.344 ms median / 2.679 ms p95 over 30 runs. The 77-source-item healthcare detail also uses one SELECT and measured 2.651 ms median / 3.441 ms p95. Manifest parsing is lazy and cached; there is no item-by-item database query.

## Deviations and limitations

- The recommended Firecrawl plugin was present but not authenticated in this environment, so the live audit used direct official pages and pinned downloads. The accepted source decision is documented with authoritative URLs, declared rights, artifact checksum, and version metadata.
- The five active packs are public-service terminology curricula, not a complete relocation, everyday, safety, warehouse, interview, shopping, football, or job-language syllabus.
- Los provides neither pedagogic ordering nor difficulty. The UI does not invent those claims; all current items have equal `USEFUL` weight.
- Dictionary item detail remains live/no-cache under the Phase 7.7 provider contract. Provider failure degrades that section without affecting local curriculum/progress.
- No CEFR/readiness aggregation, automatic vocabulary import, bulk Anki operation, dashboard SRS, Tier-3 enrichment, or later phase was implemented.
