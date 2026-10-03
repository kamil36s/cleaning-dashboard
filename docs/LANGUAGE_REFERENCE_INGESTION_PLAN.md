# Language Reference Phase 7.5B ingestion plan

Status: **Phase 7.5B executed and verified 2026-09-16**  
Inputs: versioned manifests under `language_learning/reference_core/manifests/`

## 1. Phase 7.5B boundary

7.5B builds a reproducible, read-only Norwegian reference DB from accepted archives. It does not connect Reader/Generate UI, write the user Language DB, create `VocabularyLemma` rows, infer user knowledge, or perform Phase 7.5C occurrence matching.

Default 7.5B executes Tiers 1 and 2 only. Tier 3 requires a separate explicit opt-in after disk/time benchmarks.

## 2. Streaming importer contract

Every production importer must:

1. validate manifest version, source version, expected filename/size and SHA-256 before commit;
2. stream compressed members where possible; extraction is allowed only when the format requires seek/random access;
3. keep bounded memory independent of source size;
4. normalize deterministically while retaining original display/raw evidence;
5. insert in configurable batches (initial target 5,000-25,000 rows) inside short transactions;
6. report bytes/rows, accepted/rejected counts and current member/stage;
7. write one `reference_import_runs` row with importer/schema/checksum/counts/warnings/errors;
8. store rejects in a bounded sidecar report keyed by source row/member, never silently discard them;
9. checkpoint only at safe deterministic boundaries (archive member, byte offset for seekable files, or source-local ID); resume verifies the same checksum/importer version;
10. defer expensive secondary indexes until after the largest bulk stage when benchmarks justify it;
11. run source-specific verification plus SQLite integrity/FK checks before marking complete;
12. never require loading a 20 GB source into RAM.

Operational context rule: Codex inspects only docs, headers and tiny samples. Full sources are processed by Python importers; corpus bodies are never pasted/read wholesale into model context.

## 3. Source tiers and exact importers

### Tier 1 — small and highest value

#### 1. Norsk ordbank 2022-02-01

- Download: 15,288,065-byte `tar.gz`; verify a manifest-populated SHA-256.
- Temporary disk: stream members where practical; allow ~150 MB extracted audit staging only if the parser needs coordinated joins.
- Parser: `norsk-ordbank-nob/1.0.0`, Latin-1 tabular members.
- Normalize: retain `GRUNNFORM`, source `LEMMA_ID`, raw tags/norming/dates; derive NFC/casefold lookup and a versioned POS-tag mapping.
- Target: sources/import run, lexical units/source links, forms/form links; optional compound segmentation as raw source metadata, not guessed units.
- Scale measured: 154,824 lemmas; 1,143,887 full-form rows; 617,139 distinct normalized forms; 554 whitespace headwords.
- Index after load: exact unit lookup, form lookup/form-to-unit.
- Checks: exact source counts, source-local-ID uniqueness, POS/tag distribution, 3,688 homograph spellings retained, Norwegian diacritics, no orphan forms, two missing-POS cases rejected or retained with explicit null warning.
- Priority: first; establishes all crosswalk targets.

#### 2. Norwegian KELLY refined JSON

- Download: ~420 KB JSON; checksum.
- Temporary disk: <5 MB; streaming JSON parser optional at this size.
- Parser: `norwegian-kelly-json/1.0.0`.
- Normalize: retain word/rank/POS/English values; map POS without destroying combined tags; resolve to Ordbank only through exact language+lemma+POS rules.
- Target: source links and `SOURCE_LEARNER_RANK`; unmatched/ambiguous rows stay source records/reject-review entries. English values, if imported, are labeled KELLY translations, not senses.
- Scale: 5,953 rows, ranks 1-6000 with gaps.
- Checks: rank uniqueness/gaps reported, match-basis counts, zero CEFR rows created.
- Priority: second.

#### 3. CLARINO Bokmål newspaper top 10,000

- Download: 141,382-byte TSV; checksum.
- Temporary disk: <2 MB.
- Parser: `clarino-newspaper-surface-frequency/1.0.0`, streaming line reader.
- Normalize: retain count, row rank, exact case-sensitive token and punctuation; derive lookup separately.
- Target: raw `SOURCE_FORM_RANK`/count observations. Form-to-lemma resolution is a separately versioned derived stage.
- Scale: the frozen Phase 7.5B artifact contains exactly 9,999 data rows plus one header, despite the header declaring `count: 10000`; this observed off-by-one is retained as a documented source deviation.
- Checks: descending counts, rank=row position, punctuation/proper-name/case statistics, no raw rank overwritten by derived rank.
- Priority: third.

#### 4. Official Norwegian idioms

- Download: 267,999-byte ZIP plus documentation; checksum.
- Temporary disk: <5 MB.
- Parser: `nb-norwegian-idioms/1.0.0`, streaming JSONL/dictionaries.
- Normalize: respect `nob`, `nno`, `both`; preserve expression/completion case and variants.
- Target: `IDIOM` units, source links, ordered components/variants and raw source count. No meanings.
- Scale: 3,537 frequency expressions; 3,245 completion prompts.
- Checks: 3,455 Bokmål, 88 Nynorsk, 6 shared; 156 multi-completion prompts; no Nynorsk-only row imported into the Bokmål lookup without an explicit language link.
- Priority: fourth.

### Tier 2 — medium enrichment

#### 5. Bokmål-specific n-gram unigrams

- Download: 14.5 MB frequency-sorted or 14.0 MB alphabetic filtered unigram archive plus docs; exact bytes/checksum captured at acquisition.
- Temporary disk: allow 0.25-0.5 GB.
- Parser: `nb-bokmal-ngram/1.0.0`, compressed streaming.
- Normalize: preserve raw token/count; identify boundaries/punctuation; derive lexical matching separately.
- Target: raw source unigram observations; later derived form/lemma frequency with method/version.
- Scale: verify from archive during preflight; do not trust an estimate as a record count.
- Checks: source-total consistency where documented, sortedness, reject accounting, exact raw vs derived separation.
- Priority: fifth.

### Tier 3 — large, optional, separately authorized

#### 6. Bokmål n=2..6 archive

- Download: 26.6 GB compressed.
- Temporary disk: plan 80-150 GB depending member compression; stream members and never unpack the whole archive by default.
- Parser: extend `nb-bokmal-ngram`, one n/member at a time.
- Target: phrase candidates, raw n-gram counts and selected association inputs; do not indiscriminately create a lexical unit for every n-gram.
- Derived metrics: raw count plus `logDice/v1`; optional `npmi/v1` after minimum-count filtering. Store corpus/window/tokenization versions.
- Verification: per-member counts, sortedness, sample recomputation, no duplicate sequence/source key, bounded RSS benchmark.
- Priority: opt-in after Tier 1/2 value and query benchmarks.

NBdigital 2022 is **not** in the normal 7.5B execution. A later opt-in may start with the 1,015.9 MB book unigram file filtered to Bokmål. Newspaper files cannot be treated as Bokmål because they lack language classification.

## 4. Derived lemma-frequency job

Run only after raw Ordbank and unigram/form observations are committed.

1. map exact normalized surface forms to Ordbank form links;
2. preserve punctuation/proper-name/case variants and exclude them only through a published rule;
3. split unambiguous form counts across one lemma; keep ambiguous counts unresolved by default;
4. optionally resolve only measured contextual samples with Stanza—never silently apply context-free guesses;
5. sum accepted form counts into `DERIVED_LEMMA_FREQUENCY` with method `ordbank-form-sum/v1`;
6. rank derived totals as `DERIVED_LEMMA_RANK` within the same source snapshot;
7. store coverage: total raw mass, mapped mass, ambiguous mass, rejected mass, lemma count and rule checksum.

This output is not the original CLARINO/source rank.

## 5. Disk plan

Approximate planning figures; 7.5B records exact bytes after download.

| Scope | Raw compressed | Temporary/extracted | SQLite + indexes | Recommended free-space headroom |
| --- | ---: | ---: | ---: | ---: |
| Tier 1 | ~17 MB | ~0.16 GB | ~0.4-0.9 GB | 3 GB |
| Tier 1 + Tier 2 unigram | ~32 MB | ~0.4-0.7 GB | ~0.7-1.5 GB | 5 GB |
| plus Tier 3 Bokmål n=2..6 | ~26.6 GB | ~80-150 GB if not fully streamed | estimated 40-100+ GB depending filtering/indexes | 200-250 GB |
| deferred NBdigital all listed n-grams | >45 GB | plausibly >150 GB | plausibly 100-250+ GB | not authorized; re-estimate first |

The practical default final reference DB after Tier 1+2 is expected to remain roughly **0.7-1.5 GB**. This is an estimate until importer prototypes measure page counts/index amplification. Storage location remains configurable.

## 6. Index/build order

1. create schema/PK/unique constraints;
2. load source registry and import run;
3. bulk-load units and forms;
4. build/verify form lookup and unit lookup;
5. bulk-load observations;
6. build source/rank and association indexes;
7. run `ANALYZE`, `PRAGMA optimize`, `integrity_check`, and `foreign_key_check`;
8. benchmark exact lemma+POS, surface, prefix, source/rank, CEFR, MWE first-token, idiom and top-collocation queries.

No FTS engine is introduced unless measured prefix/expression workloads fail explicit budgets.

## 7. Exact 7.5B execution sequence

1. Freeze manifests and acquire missing SHA-256 values using a download-only command.
2. Verify license/attribution snapshot and available disk before any import.
3. Create a new empty reference schema-v1 DB at the configured path; never overwrite an existing DB in place.
4. Import Ordbank and pass all count/homograph/form checks.
5. Import KELLY as rank/POS evidence; assert zero CEFR rows.
6. Import CLARINO as raw surface ranks/counts.
7. Import official idioms as expression units/count evidence.
8. Import the Bokmål unigram subset.
9. Run the separately labeled `ordbank-form-sum/v1` derived-frequency preview; publish mapping/reject statistics before committing.
10. Build secondary indexes, optimize and benchmark.
11. Verify source/import provenance, checksums, licenses, integrity, FK state and reproducibility from an empty path.
12. Produce Phase 7.5B results and stop. Do not activate Reader/generator integration; that belongs to 7.5C.

## 8. Executed result

All Tier 1+2 steps above completed. The production DB is schema v1, 4,157,272,064 bytes, integrity-clean, indexed, and logically reproducible across two empty builds. Production CEFR/domain/association evidence is zero; Tier 3 was not ingested. The CLARINO file's observed 9,999 data rows and the higher-than-estimated final storage are documented deviations. Exact results and the recommendation boundary are in [`LANGUAGE_PHASE7_5B_RESULTS.md`](./LANGUAGE_PHASE7_5B_RESULTS.md).
