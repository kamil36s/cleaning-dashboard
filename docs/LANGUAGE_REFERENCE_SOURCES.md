# Norwegian Bokmål reference-source audit

Status: **Phase 7.5A complete audit**  
Verified: 2026-09-16  
Rule: a missing license or field remains unverified; frequency is not CEFR.

## Decision matrix

| Source ID | Source / provider | Type and coverage | Size / format | License / attribution | Freshness and limitations | Planned use | Decision |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `nb-norsk-ordbank-nob-2022-02-01` | [Norsk ordbank – bokmål 2005](https://www.nb.no/sprakbanken/ressurskatalog/oai-nb-no-sbr-5/), NB/Språkbanken; UiB/Språkrådet | lexical spine, POS/morphology/full forms/compound segmentation | 14.6 MB archive; 7 Latin-1 tabular source tables plus docs | [CC BY 4.0](https://data.norge.no/en/datasets/f0db926d-a154-3a12-82b8-6573b57f6dbb/norsk-ordbank-norwegian-bokmal-2005); attribute provider/creators/release | 2022-02-01 dump; continuously updated UiB service is newer; generated forms include rare/theoretical forms | primary reference lemmas, POS, forms and source-local identity | **ACCEPT_PHASE_7_5B / Tier 1** |
| `clarino-norsk-aviskorpus-nob-frequency-2025-08-25` | [Bokmål newspaper frequency list](https://repo.clarino.uib.no/xmlui/handle/11509/157), CLARINO Bergen/UiB | frozen artifact has 9,999 case-sensitive surface rows plus one header from 11 newspapers, 1998-2022; the header itself declares `count: 10000` | 141,382-byte TSV; count + token, sorted descending | CC BY 3.0; attribute CLARINO Bergen and Gunn Inger Lyse Samdal | generated 2025-08-25; documented header/data off-by-one, punctuation, case splits, `VG`, `Foto`; genre-specific, not clean lemmas | exact `SOURCE_FORM_RANK` and raw counts | **ACCEPT_PHASE_7_5B / Tier 1** |
| `uio-norwegian-kelly-shu-wang` | [Norwegian KELLY](https://www.hf.uio.no/iln/english/about/organisation/text-laboratory/services/kelly.html), UiO/KELLY/Shu Wang | learner-oriented ranked Norwegian words with corrected POS and English glosses | 410 KB UTF-8 JSON; 5,953 rows, ranks 1-6000 | CC BY-SA 4.0; credit KELLY, UiO Text Laboratory, Shu Wang; cite Kilgarriff et al. | no CEFR field; rank gaps; old project corpus/method; translation is not a dictionary sense | exact learner-oriented rank/POS evidence, optional separately labeled gloss | **ACCEPT_PHASE_7_5B / Tier 1**, **REJECT as CEFR** |
| `nb-norwegian-idioms-2024-10-10` | [Norske idiomer](https://www.nb.no/sprakbanken/ressurskatalog/oai-nb-no-sbr-96/), NB/Språkbanken | idioms/phrases occurring >100 times in Nettbiblioteket | 261.7 KB ZIP JSON/JSONL plus docs | [CC0](https://data.norge.no/en/datasets/d9899e0a-c9f4-3dbb-81c5-a46944b585f2/norwegian-idioms); preserve provenance | 3,537 frequency entries: 3,455 Bokmål, 88 Nynorsk, 6 shared; completion prompts have variants; no meanings | `IDIOM` units, variants/completions and raw source frequency | **ACCEPT_PHASE_7_5B / Tier 1** |
| `nb-bokmal-ngram-2012` | [N-gram – bokmål](https://www.nb.no/sprakbanken/ressurskatalog/oai-nb-no-sbr-12/), NB/Språkbanken | n=1..6 from 24 online newspapers + NST news; 1.175B tokens | 14-32.6 MB unigram files; 26.6 GB full archive; count + sequence | [CC0](https://data.norge.no/en/datasets/dfa529e9-4726-3c3e-8c28-ab827e217fb5/n-gram-norwegian-bokmal); preserve provenance | 2012 release; news genre; no document frequency/dispersion | unigram evidence first; later MWE/collocation counts | **ACCEPT_PHASE_7_5B / Tier 2; full n=2..6 Tier 3 opt-in** |
| `nbdigital-ngram-2022` | [N-grams from NBdigital 2022](https://www.nb.no/sprakbanken/ressurskatalog/oai-nb-no-sbr-76/), NB/Språkbanken | uni/bi/trigrams from ~610k books and 4m newspaper issues; 138.5B tokens | 45+ GB compressed for n-grams; UTF-8 CSV.gz with tokens, language, total count and per-year JSON | [CC0](https://data.norge.no/nb/datasets/9e7a8dc9-2c74-3fab-a502-d9363a5fc738/n-grammer-fra-nbdigital-2022) | book rows have language; newspaper rows do **not**. OCR/diachronic noise; year counts are not document frequency | optional Bokmål-filtered book/diachronic enrichment only | **DEFER** |
| `norsk-aviskorpus-full` | [Norsk aviskorpus](https://data.norge.no/nb/datasets/50245b01-99a2-3fd0-b288-bdfd91ebf57c/norsk-aviskorpus), UiB/NB | full newspaper text, ~1.68B Bokmål words through 2019 | large yearly archives | CC BY-NC 4.0 | restricted non-commercial license; much larger than needed for initial exact rank | possible later document/dispersion study after legal/technical review | **DEFER** |
| `norsk-ordvev-nob-1.1.2` | [Norsk ordvev – bokmål](https://www.nb.no/sprakbanken/ressurskatalog/oai-nb-no-sbr-27/), NB/Språkbanken | semantic synsets/relations; ~305k synsets, ~250k names | 17.6 MB ZIP | [CC BY 4.0](https://data.norge.no/nb/datasets/f479d8ff-03aa-3af5-a8d5-03854a9ba190/norsk-ordvev-bokmal) | v1.1.2, 2013-era; translated from DanNet then corrected; names dominate | future senses/semantic relations/disambiguation | **DEFER / accept later** |
| `wordfreq` | [wordfreq](https://github.com/rspeer/wordfreq) | runtime Bokmål Zipf estimate | installed package | package/data licensing stays with existing provider declaration | not exact rank; form/phrase estimate | coexist as `ZIPF_FREQUENCY` | **KEEP CURRENT** |
| `cefrlex` | [CEFRLex](https://cental.uclouvain.be/cefrlex/) | CEFR distributions from graded L2 materials | average ~13k entries per supported language | per-resource terms | currently French, Swedish, English, Dutch, Spanish, German; **not Norwegian** | none for Norwegian | **REJECT for nb until an official Norwegian resource exists** |
| `kelly-as-cefr` | Norwegian KELLY public artifacts | ranked learner vocabulary | measured current JSON/XLS artifacts | CC BY-SA 4.0 | no CEFR field/distribution | none | **REJECT as sourced CEFR** |
| `ask-norwegian-l2` | ASK Norwegian Second Language Corpus | learner essays and test metadata | controlled/search access; no accepted downloadable lexical list verified | license/use conditions need project-specific verification | useful research corpus, but not a ready A1-C2 lexical resource; older test bands and personal-data controls require care | possible future distribution study | **NEEDS_VERIFICATION / DEFER** |
| `trawl` | [TRAWL](https://tekstlab.uio.no/trawl/) | multilingual school writing; first release 1,664 texts; Norwegian subset 134 texts from 10 students | access by application | research access, not open lexical import verified | Norwegian subset is ordinary school writing, not a complete Norwegian L2 A1-C2 graded lexicon | none for current CEFR objective | **REJECT for 7.5B CEFR** |

## Measured Norsk ordbank sample/full-archive audit

The 14.6 MB official archive was inspected locally; no production reference DB was built.

| Measure | Result |
| --- | ---: |
| lemma rows | 154,824 |
| casefold-distinct spellings | 150,517 |
| spellings with multiple lemma IDs | 3,688 |
| lemma rows under those homographs | 7,995 |
| lemma rows containing whitespace | 554 |
| full-form rows | 1,143,887 |
| casefold-distinct full forms | 617,139 |
| extracted source-table bytes | 140,444,477 |

POS evidence is carried in the full-form tags, not directly in `lemma.txt`. Dominant lemma/tag assignments measured were 122,941 `subst`, 28,623 `adj`, 8,545 `verb`, 1,174 `adv`, plus function-word, abbreviation, symbol and compound tag families. Two lemma IDs had no full-form tag in the measured join. Import must translate tags with a versioned mapping and retain raw tags.

Conclusion: Norsk ordbank is sufficient as the **base lexical/morphological spine**, but not as a complete modern usage, learner-difficulty, sense/definition or collocation source. Supplement it with KELLY and corpus observations, and later consider current UiB deltas or another licensed modern-neologism source. It is not sufficient alone for CEFR or meaning.

## Ranked-frequency findings

The CLARINO file header declares corpus, `word` attribute, frequency sort and 10,000 rows, but the frozen artifact contains 9,999 data rows plus that header. Each data row is raw count + case-sensitive surface. Rank is row order after the header. It contains punctuation and corpus artifacts exactly as its landing page warns. Therefore:

- store raw row, count, surface and `SOURCE_FORM_RANK`;
- never claim it is lemma rank;
- only later emit `DERIVED_LEMMA_FREQUENCY/RANK` from a versioned, inspectable aggregation;
- retain KELLY rank as a different source/corpus and wordfreq Zipf as a different metric.

No audited initial frequency source directly supplies general document frequency or a 0-1 dispersion score. NBdigital supplies per-year counts and can support diachronic profiles, not document dispersion. Any future dispersion needs document-level denominators and a published formula/version.

## N-gram and collocation findings

The Bokmål-specific source is preferred over NBdigital for the first collocation work because its language boundary is explicit and it is much smaller. Import raw unigram counts in the normal 7.5B run. Full 2-6-gram ingestion is a separate Tier-3 opt-in because the archive is 26.6 GB compressed.

NBdigital adds extraordinary historical breadth and per-year counts. Its books can be filtered by language, but newspapers currently have no language classification. It therefore cannot be treated wholesale as Bokmål. Defer it until the smaller source is measured and a book-only Bokmål business case exists.

Recommended association evidence: retain raw count; use logDice for product ranking; optionally expose normalized PMI after minimum-count filtering. Record corpus, direction/window, tokenization and metric versions.

## Idiom findings

The archive contains full-expression frequency dictionaries and a completion-task JSONL. Measured counts agree with the catalogue frequency dictionaries: 3,537 total expressions, 3,455 Bokmål, 88 Nynorsk and 6 shared. The prompt file has 3,245 starts and 156 rows with multiple completions. Language labels must be respected; the importer must reconstruct full expressions from start+completion only for prompt variants and must not invent definitions.

## CEFR conclusion

No open, ready-to-ingest Norwegian A1-C2 lexical truth source was verified.

- CEFRLex explicitly omits Norwegian today.
- Public Norwegian KELLY data offers a useful learner-oriented rank, POS and translations but no CEFR labels.
- ASK could support a later, ethically/licensably reviewed learner-corpus distribution, but no import-ready complete A1-C2 lexicon was verified.
- TRAWL does not fit the target Norwegian L2 A1-C2 lexical role.

Schema v1 nevertheless supports sourced labels, learner/textbook distributions, expert evidence and clearly marked estimates. Phase 7.5B must leave production CEFR empty rather than infer levels from frequency.

## Dictionary/semantic conclusion

Definitions and translations are outside this phase. Do not scrape commercial dictionaries or copy dictionary bodies. Norsk ordvev is legally and technically promising for later semantic relations/sense disambiguation, but its age and name-heavy inventory make it a deferred enrichment, not the lexical spine.

## Audit data policy

Only the official small artifacts required to inspect fields were downloaded during Phase 7.5A, totaling under 17 MB compressed/source downloads (plus small documentation). They live under ignored `.firecrawl/`. No 26.6 GB n-gram archive, NBdigital corpus, full newspaper corpus, production reference DB, or user-vocabulary import was created.

## Phase 7.5B freeze

Phase 7.5B reverified the five accepted license records and froze eight required data/documentation artifacts totaling 32,319,971 bytes. Exact per-file SHA-256 values are in the tracked manifests and [`LANGUAGE_PHASE7_5B_RESULTS.md`](./LANGUAGE_PHASE7_5B_RESULTS.md). The authorized production build includes only Ordbank, KELLY, the 9,999-row frozen CLARINO artifact, official idioms, and the Bokmål unigram archive. Full `n=2..6`, NBdigital, full Norsk aviskorpus, Norsk ordvev, ASK and CEFR inference remain un-ingested.
