# Language Dashboard Phase 7.5B results

Status: **COMPLETE**  
Date: 2026-09-16  
Scope: reproducible Bokmål Tier 1+2 reference ingestion only

Phase 7.5C, Tier 3 `n=2..6`, and Phase 8 are **NOT STARTED**. No frontend/server reference integration was added. Production CEFR evidence is intentionally empty and is a successful expected result.

## 1. Outcome

The independent production reference database was built twice from the same frozen artifacts, validated, logically compared, and atomically published.

- Config/default: `LANGUAGE_REFERENCE_DB`, default `data/reference/language-reference-nb.sqlite`.
- Raw-source config/default: `LANGUAGE_REFERENCE_SOURCE_DIR`, default ignored `data/reference/sources/`.
- Reference schema: **v1**.
- Final size: **4,157,272,064 bytes** (about 3.872 GiB).
- Logical fingerprint: `5369f342a9c2ec094ca8dbfe9b1d3d2716bdc9a4aa39ab022a40b104f410a88b` in both builds.
- Integrity: `ok`; foreign-key violations: **0**.
- Completed import runs: **5/5**; failed/running published runs: **0**.
- Production CEFR rows: **0**.
- Domain rows: **0**.
- Association/Tier-3 rows: **0**.
- Main `language-learning.sqlite`: schema **v6**, 24 tables, identical before/after row counts, `integrity_check=ok`, zero FK violations, zero vocabulary/knowledge/exposure/Anki/generation mutations.

## 2. Files created

Implementation:

- `language_learning/reference_core/artifacts.py`
- `language_learning/reference_core/build.py`
- `language_learning/reference_core/manifest.py`
- `language_learning/reference_core/pos_mapping.py`
- `language_learning/reference_core/production_importer.py`
- `scripts/build_language_reference.py`
- `tests/test_language_reference_ingestion.py`
- tiny importer fixtures under `tests/fixtures/language/reference/production/`
- [`LANGUAGE_REFERENCE_IMPORT_OPERATIONS.md`](./LANGUAGE_REFERENCE_IMPORT_OPERATIONS.md)
- [`LANGUAGE_REFERENCE_DERIVED_METRICS.md`](./LANGUAGE_REFERENCE_DERIVED_METRICS.md)
- this results document

Generated and ignored:

- production `data/reference/language-reference-nb.sqlite`
- exact artifacts under `data/reference/sources/`
- `data/reference/reports/language-reference-attribution.json`
- `data/reference/reports/language-reference-quality.json`
- `data/reference/reports/language-reference-quality.md`

## 3. Files modified

- `.gitignore`
- `language_learning/reference_core/schema.py`
- `language_learning/reference_core/store.py`
- `language_learning/reference_core/manifests/manifest.schema.json`
- all five accepted source manifests
- `scripts/diagnose_language_reference.py`
- [`LANGUAGE_REFERENCE_SOURCES.md`](./LANGUAGE_REFERENCE_SOURCES.md)
- [`LANGUAGE_REFERENCE_INGESTION_PLAN.md`](./LANGUAGE_REFERENCE_INGESTION_PLAN.md)
- [`LANGUAGE_IMPLEMENTATION_PLAN.md`](./LANGUAGE_IMPLEMENTATION_PLAN.md)
- [`LANGUAGE_RUN_PROGRESS.md`](./LANGUAGE_RUN_PROGRESS.md)

No server route, frontend module, main Language migration, Reader behavior, generation version, or user-data model changed.

## 4. Frozen artifacts

Licenses were rechecked against current authoritative landing metadata: Ordbank CC BY 4.0, CLARINO CC BY 3.0, KELLY CC BY-SA 4.0, idioms CC0, and Bokmål n-grams CC0.

| Source | Artifact | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| Norsk ordbank | `20220201_norsk_ordbank_nob_2005.tar.gz` | 15,288,065 | `57d91cb3f17b85befa50a3b56fcaed9800ca665b39486fe97b668add914d5f60` |
| Norsk ordbank | `norsk_ordbank.pdf` | 593,084 | `c4235c6b0242938112d6cc3882a7319197d30ce2acabbd6392dd0b157787f602` |
| KELLY | `Norwegian-KELLY-Contributions-Shu-Wang.json` | 419,961 | `71d9fdc2280bd7d2b9dd0eba394a716551552fde356dc2fce57796da784f9a7f` |
| CLARINO | `frekvensordliste-aviskorpus-nob.tsv` | 141,382 | `0da16866e64ad609f15eb99d102285c5e9310287ce09112eb734f0f9842d4ad3` |
| Norske idiomer | `norske_idiom.zip` | 267,999 | `4385ed9fd4ffb2b3299ed5fb87df407a1a56775e2db87e77ad64387f5c149b7e` |
| Norske idiomer | `norske_idiom.pdf` | 109,089 | `ec4297e54decbfd62b6ee6dff08d557961594d7d31c6a844963800b1ae6747c2` |
| Bokmål unigram | `1gram_nob_f1_freq.zip` | 15,198,030 | `cda1477a11fc98bcf61e8152fe1a09a4d5f9ae04b16c4ed9dc86ee224c2284e3` |
| Bokmål unigram | `ngram_nob.pdf` | 302,361 | `7121a602fe82eca98bec1410ebbcded1917ccf57faaaea21cbba1e3bb9138f5c` |

Total required artifact bytes: **32,319,971**. Retrieval timestamps and HTTP `Last-Modified`/ETag metadata are frozen in manifests where supplied. No upstream official checksum was published in the audited metadata, so no official checksum was invented.

## 5. Storage and staging

| Measure | Observed |
| --- | ---: |
| pre-build free space | 170,256,400,384 bytes |
| required-artifact bytes | 32,319,971 |
| temporary extraction | 0 bytes; all large archive members streamed |
| first staging DB | 4,157,272,064 bytes |
| comparison DB | 4,157,272,064 bytes |
| measured two-build peak estimate | 8,346,864,099 bytes |
| final published DB | 4,157,272,064 bytes |
| free pages after finalization | 0 bytes |

SQLite `dbstat` index/table byte attribution was unavailable in this build, so no index contribution was fabricated. The final DB is materially above the Phase 7.5A 0.7-1.5 GB estimate (about 2.77 times its upper bound), primarily because 3.31 million raw unigram observations, inspectable mapping candidates, and lossless 1.14 million morphology links are retained. This is an operational constraint for any Tier-3 authorization.

## 6. Norsk ordbank lexical spine

| Measure | Result |
| --- | ---: |
| lemma rows read / units created | 154,824 / 154,824 |
| full-form rows read | 1,143,887 |
| accepted form links | 1,143,502 |
| distinct display forms | 618,728 |
| orphan form rows rejected | 385 across 359 absent lemma IDs |
| compound rows accepted | 180,366 |
| same-spelling homograph groups | 3,688 |
| multiword lemma units | 554 |
| mapped normalized POS | 154,657 |
| explicit null/unmapped POS | 167 |

Every Ordbank source lemma ID becomes a distinct stable unit qualifier, so same-spelling/different-POS and same-spelling/same-POS source identities are not merged. Every accepted morphology row retains raw tag, paradigm ID, inflection number, dates, norming, and source-local row ID. Compound analyses retain source-local structure.

POS method `ordbank-pos/v1` chooses the most frequent raw full-form tag family per source lemma with deterministic lexical tie-breaking. Mapped totals include 122,914 NOUN, 20,185 ADJ, 8,539 VERB, 1,168 ADV, and documented function/abbreviation/symbol families. Unmapped totals are 161 raw `i`, two `prep+subst`, one `adj+prep`, one `det+subst`, plus two lemmas with no full-form POS evidence. None was guessed.

## 7. KELLY learner-rank evidence

- Rows read/accepted/rejected: **5,953 / 5,953 / 0**.
- Rank range: **1-6000**, with source gaps preserved.
- Resolution: **5,434 MATCHED**, **343 AMBIGUOUS**, **176 UNMATCHED**.
- Matched source links/rank observations: **5,434**.
- POS mapping: `kelly-pos/v1`; combined tags yield candidate POS sets rather than a guessed single POS.
- English strings are retained only in raw evidence as `KELLY_TRANSLATION_NOT_DICTIONARY_SENSE`.
- CEFR rows created: **0**.

KELLY rank remains `SOURCE_LEARNER_RANK`. It is not CEFR and is not merged with corpus rank.

## 8. CLARINO raw and derived evidence

The frozen file contains **9,999** data rows plus one header, although that header declares `count: 10000`. The first production attempt stopped safely at this deviation. Bounded inspection confirmed all 9,999 data rows were valid; the manifest, invariant, and documentation now record the exact off-by-one instead of forcing a row.

- Raw `SOURCE_FORM_RANK`: **9,999**, rejected **0**.
- Resolution: **5,984 MATCHED**, **2,627 AMBIGUOUS**, **1,041 UNMATCHED**, **347 EXCLUDED_NONLEXICAL**.
- Total raw mass: **1,809,522,460**.
- Unique mapped mass: **539,127,676 (29.793920%)**.
- Ambiguous mass: **876,048,811**.
- Unmatched mass: **40,586,763**.
- Excluded nonlexical mass: **353,759,210**.
- `clarino-derived-lemma-frequency/v1`: **3,835 lemmas**, **7,670 frequency/rank observations**.

The low unique-mass coverage is explicit. Raw surface rank/count remains intact and is never labeled as a canonical lemma rank.

## 9. Official idioms and variants

- Frequency rows: **3,455 Bokmål**, **88 Nynorsk-only**, **6 shared**.
- Completion prompts: **3,151 Bokmål**, **88 Nynorsk-only**, **6 shared**.
- Multi-completion prompts: **156**.
- Bokmål/shared idiom units: **3,481** (including 20 completion-only full variants).
- Source completion variants: **3,461**.
- Nynorsk-only units imported into Bokmål: **0**.
- Fabricated definitions: **0**.
- Rows read/accepted/rejected: **6,794 / 6,794 / 0**.

Prompt, completion, language label, full reconstructed expression, and source-local provenance remain inspectable.

## 10. Tier-2 Bokmål unigram evidence

- Raw `SOURCE_NGRAM_FREQUENCY` rows: **3,307,461**, rejected **0**.
- Resolution: **433,357 MATCHED**, **33,886 AMBIGUOUS**, **2,744,197 UNMATCHED**, **96,021 EXCLUDED_NONLEXICAL**.
- Total raw mass: **1,456,290,754**.
- Unique mapped mass: **453,214,139 (31.121130%)**.
- Ambiguous mass: **614,986,226**.
- Unmatched mass: **73,925,199**.
- Excluded nonlexical mass: **314,165,190**.
- `bokmal-unigram-derived-lemma-frequency/v1`: **120,749 lemmas**, **241,498 frequency/rank observations**.

The unigram and CLARINO derivations stay independent. No `n=2..6` member, NBdigital file, or full newspaper corpus was downloaded or ingested.

## 11. Published row scale and import provenance

| Table/fact | Rows |
| --- | ---: |
| lexical units | 158,305 |
| forms | 618,728 |
| form links | 1,143,502 |
| compound analyses | 180,366 |
| raw observations | 3,327,050 |
| observation candidates | 530,089 |
| frequency observations | 258,063 |
| idiom variants | 3,461 |
| MWE components | 14,025 |

| Source | Parser | Read | Accepted | Rejected | Combined required-artifact checksum |
| --- | --- | ---: | ---: | ---: | --- |
| Ordbank | `norsk-ordbank-nob/1.0.0` | 1,479,077 | 1,478,692 | 385 | `sha256:6893bdfa8e850e00932986628f043d5d4249c14e6f1716d3cfed97a6aabf3ded` |
| KELLY | `norwegian-kelly-json/1.0.0` | 5,953 | 5,953 | 0 | `sha256:9925188acbf972d7b0b03cd56ddb80950793cddd39355170a2eed63f6dd58580` |
| CLARINO | `clarino-newspaper-surface-frequency/1.0.0` | 9,999 | 9,999 | 0 | `sha256:ba8a9d5d295b24a93c6ca19eb7380defdac827d937db61bb60e746255cf97204` |
| Idioms | `nb-norwegian-idioms/1.0.0` | 6,794 | 6,794 | 0 | `sha256:afde028312349fe5c09dde4e84d00f2cfc571e35373b2e6837b45ceac7426f68` |
| Unigrams | `nb-bokmal-ngram/1.0.0` | 3,307,461 | 3,307,461 | 0 | `sha256:a46e464ee860c6fce2fafaf3eb3019a5d1ff0d367b1fe241648303302e3312c7` |

Reject/warning detail is bounded. The only production rejects were the 385 Ordbank full-form rows referencing absent lemma IDs. Two Ordbank lemma rows had no form-derived POS; 165 more had deliberately unmapped dominant tag families. All other raw rows parsed successfully; ambiguous/unmatched mapping is quality evidence, not rejection.

## 12. Resolver and bounded production sanity

`ReferenceResolver` over three user-independent samples produced:

- `jobb` + NOUN: **MATCHED**, one candidate, `LANGUAGE_LEMMA_POS`.
- `så` + null POS: **AMBIGUOUS**, six candidates, POS required.
- `xylophonisk` + ADJ: **UNMATCHED**, zero candidates.

Bounded production lookups also found source-backed noun, verb, adjective, homograph, multiword lemma, idiom, and common frequency observations. No personal `VocabularyLemma` rows were resolved or crosswalked.

## 13. Query benchmarks and plans

Nine warm repetitions were measured after `ANALYZE`; values below are medians.

| Query | Median | Rows | Plan summary |
| --- | ---: | ---: | --- |
| exact lemma + POS | 0.0443 ms | 1 | `idx_reference_units_lookup` |
| surface lookup | 0.0439 ms | 1 | `idx_reference_forms_lookup` + form-link PK |
| homograph lookup | 0.0448 ms | 3 | `idx_reference_units_kind` |
| frequency evidence | 0.0439 ms | 2 | `idx_reference_frequency_unit` |
| top derived lemma rank | 0.0815 ms | 100 | `idx_reference_frequency_source_rank` |
| idiom lookup | 0.0432 ms | 1 | `idx_reference_units_kind` |
| lemma prefix range | 0.0929 ms | 100 | `idx_reference_units_prefix` |
| surface prefix range | 0.0894 ms | 100 | `idx_reference_forms_lookup` |
| source provenance | 0.0831 ms | 100 | `idx_reference_source_links_local` |

All requested lookup families use indexes. CEFR/collocation structural indexes remain present but production rows are zero. `ANALYZE` statistics are included in the published DB; no blind `VACUUM` was run.

## 14. Determinism, publication, and isolation

Two new empty staging paths were built from the same artifacts. Canonical hashes cover schema, sources/artifacts/imports, units, source links, forms/morphology links, compounds, raw observations, candidates, derived frequency, MWE components, variants, and method policies. Both produced exactly:

`5369f342a9c2ec094ca8dbfe9b1d3d2716bdc9a4aa39ab022a40b104f410a88b`

The comparison DB was deleted only after equality. The first validated DB was atomically moved into the configured production path. A deliberately failed earlier CLARINO staging build never replaced production and was removed after its diagnostic evidence was recorded.

Main DB before/after: schema v6, 24 tables, one profile, zero vocabulary lemmas/forms/knowledge/events/exposures/Anki/generation records, identical row-count map, integrity `ok`, zero FK violations.

## 15. Tests and regression

New importer tests cover valid/malformed rows, Latin-1/UTF-8 Norwegian `æøå`, homographs, multiword units, unknown POS, duplicate source identity through schema constraints, one form to several lemmas, punctuation/case, idiom language filtering and multiple completions, unigram frequency, checksum drift rejection, parser-version provenance, and deterministic canonical rebuild.

| Verification | Result |
| --- | --- |
| reference tests | **9 passed** (5 prior + 4 new) |
| Language backend | **130 passed** |
| Language frontend | **71 passed** |
| broad backend | **479 passed, 1 skipped** |
| broad frontend | **703 passed, 2 skipped** |
| Python compilation | **passed** |
| production build | **passed**; existing non-module/chunk-size warnings only |

The frontend suite emitted its known mocked localhost connection-refused/abort stderr; no failure was suppressed.

## 16. Deviations and limitations

- CLARINO contains 9,999 data rows rather than the header/audit claim of 10,000. The source was stopped, inspected, and the exact deviation documented.
- The final DB is 4.16 GB, substantially above the 0.7-1.5 GB planning estimate. Raw evidence/candidates and lossless morphology account for the larger measured scale.
- CLARINO and unigram unique mapped frequency mass are about 29.79% and 31.12%. Ambiguous/unmatched mass remains explicit; derived ranks are not complete lexical rankings.
- Ordbank is the 2022 snapshot and contains rare/theoretical forms; it is not a meaning, CEFR, or modern-neologism source.
- KELLY glosses are source translations, not dictionary senses.
- Resume is restart-from-empty-staging rather than mid-source checkpoint resume. Resume never crosses a checksum/parser version.
- Index byte attribution was not measurable with the available SQLite `dbstat`; it is reported as unavailable, not estimated.
- Production CEFR and domains are empty by design.

## 17. Tier 3 / Phase 7.5C recommendation

**Tier 1+2 health gate: PASS.** The database is reproducible, source-complete for the authorized scope, indexed, fast for planned lookups, integrity-clean, source-aware, and isolated. It is technically healthy enough to serve as the foundation for a separately authorized Tier-3 MWE/collocation ingestion phase before Phase 7.5C.

**Exact sequencing recommendation:** do **not** begin Tier 3 automatically. Phase 7.5C can safely proceed on this Tier 1+2 database without Tier 3; official idioms and schema support already permit reference lookup/MWE plumbing. If collocation profiles are required before 7.5C, first authorize a dedicated Tier-3 preflight/prototype with a renewed 200-250 GB disk gate and storage/index design review, because Tier 1+2 alone measured 4.16 GB. Do not authorize the full 26.6 GB archive on the old size estimate.

No Phase 7.5C or Phase 8 implementation was started.
