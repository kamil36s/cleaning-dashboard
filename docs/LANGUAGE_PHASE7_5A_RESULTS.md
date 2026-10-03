# Language Dashboard Phase 7.5A results

Status: **COMPLETE**  
Date: 2026-09-16  
Scope: reference data source audit and isolated intelligent-lexicon architecture only

Phase 7.5B, Phase 7.5C, and Phase 8 are **NOT STARTED**. No production reference corpus was ingested and no reference feature was connected to the Language API, Reader, generator, or UI.

## 1. Outcome

Phase 7.5A freezes a strict boundary between the existing user-learning database and a rebuildable reference-data database:

- `data/language-learning.sqlite` remains the canonical user database at schema-ledger version 6. Existing `VocabularyLemma` remains the canonical user word identity.
- The proposed reference database defaults to `data/reference/language-reference-nb.sqlite`, is configurable with `LANGUAGE_REFERENCE_DB`, and has independent schema version 1.
- The reference spike contains no import from `LanguageStore`, no main-database migration, no API or UI activation, and no automatic initialization from `server.py`.
- A tiny synthetic fixture proves identity, provenance, forms, source-specific frequency/rank, CEFR evidence/distribution, MWE, idiom, collocation, association, and resolver semantics without copying a production corpus.
- Raw source archives, processed data, and generated SQLite files are ignored by Git. Only manifests, bounded fixtures, code, and audit documents are tracked.

The architecture and decisions are specified in:

- [`LANGUAGE_REFERENCE_ARCHITECTURE.md`](./LANGUAGE_REFERENCE_ARCHITECTURE.md)
- [`LANGUAGE_REFERENCE_SOURCES.md`](./LANGUAGE_REFERENCE_SOURCES.md)
- [`LANGUAGE_REFERENCE_INGESTION_PLAN.md`](./LANGUAGE_REFERENCE_INGESTION_PLAN.md)

## 2. Files created

- `language_learning/reference_core/__init__.py`
- `language_learning/reference_core/config.py`
- `language_learning/reference_core/models.py`
- `language_learning/reference_core/schema.py`
- `language_learning/reference_core/store.py`
- `language_learning/reference_core/resolver.py`
- `language_learning/reference_core/fixture_importer.py`
- `language_learning/reference_core/manifests/manifest.schema.json`
- five accepted-source manifests under `language_learning/reference_core/manifests/`
- `scripts/diagnose_language_reference.py`
- `tests/test_language_reference.py`
- `tests/fixtures/language/reference/reference_v1.json`
- the three reference design/audit/ingestion documents listed above
- this results document

Files modified for Phase 7.5A are `.gitignore`, `.env.example`, `docs/LANGUAGE_IMPLEMENTATION_PLAN.md`, and `docs/LANGUAGE_RUN_PROGRESS.md`.

## 3. Implemented schema-v1 spike

Independent tables cover:

- source registry and import runs;
- typed lexical units (`LEMMA`, `PHRASE`, `IDIOM`, `COLLOCATION`, `FORMULA`) and source links;
- forms and source-local form links;
- source-specific raw or derived frequency observations, including exact rank, metric name, derivation method/version, and corpus metadata;
- sourced CEFR evidence with evidence type, confidence, and A1-C2 distribution rather than a forced scalar;
- ordered MWE components and expression variants;
- association evidence with corpus/window/direction/tokenization/metric version;
- reference domains/registers with provenance, separate from user Topics.

Stable IDs derive from the inspectable `reference-key/v1` normalized identity tuple. Unicode is NFC-normalized and casefolded. Language, lexical-unit type, spelling, and POS preserve same-spelling/different-POS identities. Collisions are detected by a unique identity constraint rather than silently merged.

`ReferenceResolver` is exact and read-only. It uses language + normalized lemma + POS first, then documented null-POS fallbacks. It never fuzzy-matches and returns `MATCHED`, `AMBIGUOUS`, or `UNMATCHED` with candidates, match basis, and `reference-resolver/v1`.

## 4. Source audit conclusions

### Accepted for a future Phase 7.5B

| Tier | Source | Intended evidence |
|---|---|---|
| 1 | Norsk ordbank, Bokmål 2022-02-01 | primary lexical spine, POS, paradigms, forms, compound segmentation |
| 1 | Norwegian KELLY refined JSON | learner-oriented exact source rank and POS; explicitly not CEFR |
| 1 | CLARINO Bokmål newspaper frequency list, generated 2025-08-25 | exact case-sensitive surface-form counts and source ranks |
| 1 | NB/Språkbanken Norske idiomer | idiom units, variants/completions, source frequencies; no invented definitions |
| 2 | NB/Språkbanken Bokmål unigrams | broader raw frequency evidence |
| 3, opt-in only | Bokmål n=2..6 archive | raw MWE/collocation counts and versioned association metrics |

Norsk ordbank is the recommended full lexical/morphological spine. The measured 2022 dump contains 154,824 lemma rows, 150,517 distinct casefold spellings, 3,688 homograph spellings spanning 7,995 lemma rows, 554 multiword lemma rows, 1,143,887 full-form rows, and 617,139 distinct casefold forms. It is not a complete modern-usage, meaning, CEFR, or collocation source.

The CLARINO list supplies an exact source rank for 10,000 surface tokens, not a clean lemma rank. KELLY supplies a different exact learner-oriented source rank. `wordfreq` Zipf remains a separately named, separately sourced metric and is never presented as exact corpus rank.

The first n-gram choice is the smaller explicitly Bokmål corpus. Keep raw counts. Use `logDice/v1` as the primary product-ranking association metric and filtered `npmi/v1` as a secondary diagnostic. The audited n-gram distributions do not supply document frequency or dispersion, so neither may be fabricated.

No verified open Norwegian A1-C2 lexical resource was found. Current CEFRLex does not include Norwegian, public Norwegian KELLY artifacts contain no CEFR field, ASK was not verified as an open complete lexical source, and TRAWL's small Norwegian school-writing subset is not such a source. Phase 7.5B must therefore leave production CEFR empty. Schema v1 can later retain independently sourced labels/distributions, evidence type, confidence, and provenance; an estimate must remain explicitly `ESTIMATED` and can never be promoted from frequency alone.

### Deferred or rejected

- Full Bokmål n=2..6 is deferred to explicit Tier-3 authorization because the archive is 26.6 GB compressed.
- NBdigital 2022 is deferred: listed n-gram files exceed 45 GB compressed, newspaper rows lack a language field, and the material is OCR/diachronic-heavy.
- Full Norsk aviskorpus is deferred due scale and CC BY-NC restrictions.
- Norsk ordvev is a useful later semantic/sense source, not required for the first reference build.
- CEFRLex for Norwegian, KELLY-as-CEFR, and TRAWL-as-CEFR are rejected for the claimed role. ASK remains unverified/deferred.

The exact source/license/attribution matrix is in [`LANGUAGE_REFERENCE_SOURCES.md`](./LANGUAGE_REFERENCE_SOURCES.md). No missing license was guessed.

## 5. Raw, derived, and user evidence

Every observation retains its source and import run. Exact rank is source-local. Raw counts are immutable evidence. Derived lemma counts/ranks aggregate only explicitly mapped forms and record derivation ID, version, inputs, tie policy, and failures; they never overwrite raw form evidence. CEFR, association, domain, and resolver outputs follow the same raw-versus-derived separation.

Reference MWEs are typed lexical units with ordered components, variants, canonical text, source identity, and match policy. Idioms are `IDIOM` units, not ordinary lemmas. The future recommendation is to attach read-only reference annotations in Phase 7.5C; do not create a second user phrase-knowledge store. Generalizing user lexical identity can be evaluated only after real MWE occurrence evidence exists. `VocabularyLemma` remains canonical and word-only now.

## 6. Storage, ingestion, and performance plan

The source manifest format records versioned source ID, provider, landing URL, release/version, language, resource type, verified license, attribution, expected files, expected byte size/checksum, parser ID/version, decision, tier, and notes. Checksums are intentionally `null` until Phase 7.5B computes them from the exact downloaded artifacts.

Future importers must stream bounded batches, stage into a new database, verify byte size/checksum/schema/counts/rejects/integrity, build expensive indexes after bulk load where measured beneficial, then atomically publish. Resume state is source/parser/checksum specific. Full files must never be loaded into RAM or pasted into Codex context.

Planning estimates:

- Tier 1: about 17 MB download, about 0.16 GB temporary extraction, about 0.4-0.9 GB final DB, 3 GB free-space gate.
- Tier 1 + Tier 2 unigram: about 32 MB download, 0.4-0.7 GB temporary, about 0.7-1.5 GB final DB, 5 GB gate.
- Optional Tier 3 n=2..6: about 26.6 GB download, potentially 80-150 GB staging and 40-100+ GB DB; require 200-250 GB and separate authorization.

Schema-v1 indexes cover exact lemma+POS, normalized unit/form lookup and prefixes, type, source/rank, CEFR level/type, first MWE component, variants, domains, and top association scores. Phase 7.5B must validate query plans and index amplification against real row counts.

## 7. Verification

| Check | Result |
|---|---|
| New reference tests | 5 passed |
| Complete Language backend, including new tests | 126 passed |
| Existing Language backend baseline | 121 passed within the 126 |
| Language frontend | 71 passed |
| Broad backend | 474 passed, 1 skipped |
| Broad frontend | 699 passed, 2 skipped |
| Production build | passed; existing non-module/chunk-size warnings only |
| Python compile check | passed |
| Diagnostic default behavior | passed; reports absent DB and does not initialize it |
| Main DB read-only inspection | schema ledger 6, integrity `ok`, 0 foreign-key violations, 0 reference tables |
| Production reference DB | absent |

The frontend suite emitted its existing localhost connection-refused/abort stderr during mocked event tests but completed successfully. No test failure was suppressed.

## 8. Acceptance checklist

All Phase 7.5A criteria are satisfied:

1. Reference and user knowledge domains are explicit and separate.
2. `VocabularyLemma` remains canonical user identity.
3. A separate reference DB architecture is defined.
4. It has independent schema versioning.
5. Its DB and source paths are configurable.
6. A versioned source-manifest format exists.
7. Source provenance is modeled.
8. Import-run provenance is modeled.
9. Norsk ordbank is audited as the full Bokmål candidate.
10. Its form/morphology coverage is measured.
11. CLARINO and KELLY exact source ranks are audited.
12. Bokmål n-grams and NBdigital are audited.
13. The official idiom source is audited.
14. CEFRLex, KELLY, ASK, and TRAWL learner evidence is audited.
15. Unsupported CEFR claims are rejected.
16. Frequency is not CEFR.
17. CEFR provenance, evidence type, and confidence are modeled.
18. CEFR distributions are modeled.
19. Frequency observations stay source-specific.
20. Exact ranks stay source-specific.
21. `wordfreq` Zipf remains distinct.
22. Raw and derived metrics are distinct.
23. Derived lemma-rank versioning is specified.
24. Document frequency/dispersion availability is recorded as absent where absent.
25. Typed MWE lexical units are defined.
26. Idioms are modeled explicitly.
27. Collocation evidence is modeled.
28. `logDice` plus filtered nPMI is recommended.
29. Reference domains are separate from user Topics.
30. Resolver result semantics are defined and tested.
31. Same spelling/different POS is representable and tested.
32. Verified source licenses are recorded.
33. Attribution requirements are recorded.
34. No license is invented.
35. Large raw data is ignored by Git.
36. Generated reference databases are ignored by Git.
37. Streaming ingestion is specified.
38. Large-file model-context safety is specified.
39. Raw/processed/fixture policy is specified.
40. Phase 7.5B tiers are specified.
41. Download, staging, DB, and free-space estimates are specified.
42. The importer sequence is specified exactly.
43. Reader/reference integration is designed but inactive.
44. Generator enrichment is designed but inactive.
45. MWE user-knowledge options and recommendation are explicit.
46. No mass user-vocabulary import occurred.
47. The canonical user DB remains schema v6 and unchanged by reference work.
48. No giant corpus was ingested.
49. All prior Language and broad regressions pass.
50. The production build passes.

## 9. Exact next phase, not executed

Phase 7.5B must execute only the 12 ordered steps in [`LANGUAGE_REFERENCE_INGESTION_PLAN.md`](./LANGUAGE_REFERENCE_INGESTION_PLAN.md#7-exact-75b-execution-sequence): freeze manifests/checksums; verify licenses/disk; implement staged import CLI; import Ordbank; import KELLY with zero CEFR rows; import CLARINO surface evidence; import idioms; import Tier-2 unigrams; derive versioned mappings/ranks; create/analyze indexes and benchmarks; validate/rebuild/publish atomically; produce Phase 7.5B results and stop. Full n=2..6 remains opt-in and Reader/generator integration remains Phase 7.5C.

