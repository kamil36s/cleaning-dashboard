# Language Learning Phase 0 results

Status: COMPLETE with documented analyzer limitations  
Date tested: 2026-09-15  
Benchmark: `language-phase0-benchmark/v1`  
Fixture: `nb-phase0-v1`

## 1. Environment tested

| Item | Measured value |
| --- | --- |
| OS | Windows 10 `10.0.19045`, AMD64 |
| Python | CPython 3.10.2, 64-bit |
| PyTorch | 2.5.1, CPU execution selected |
| Stanza | 1.14.0 |
| Stanza resources | 1.14.0 |
| Simplemma | 2.0.0 |
| wordfreq | 3.1.1 |

The environment emitted an existing `requests` compatibility warning because installed `chardet` 7.4.3 is outside the range recognized by `requests` 2.32.3. It did not prevent explicit provisioning, offline model load, analysis, or tests. No package was removed to “fix” this unrelated shared-environment condition.

## 2. Candidates tested

1. Stanza `nb`, with explicit packages `tokenize=bokmaal`, `pos=bokmaal_charlm`, and `lemma=bokmaal_nocharlm`; dependencies were the published `conll17` pretrain and forward/backward character language models.
2. Simplemma 2.0.0 using `lemmatize(surface, lang="nb")` against the same expected lemma checks.
3. wordfreq 3.1.1 for `nb` capability and Zipf score lookup only.
4. AnkiConnect at the default loopback URL using only the read-only `version` action; this was non-blocking.

No LLM supplied fixture answers, lexical facts, ranks, dictionary entries, translations, morphology tables, or CEFR labels.

## 3. Fixture summary

The committed oracle is `tests/fixtures/language/nb/phase0_bokmal_cases.json`. It is hand-authored and records its expected properties independently of analyzer output.

It contains 10 focused cases, 858 Python Unicode code points, and 197 analyzed tokens covering:

- `jobb`, `jobben`, `jobber`, `jobbene` plus `bok` and `hus` noun patterns;
- infinitive, present, past, and participle verb forms;
- adjective gender/number/definiteness;
- pronouns, determiners, auxiliaries, prepositions, and conjunctions;
- contextual ambiguity for `så`, `norsk`, and `om`;
- an invented item, proper names, an abbreviation, and a foreign word;
- intact compounds;
- `æ`, `ø`, `å`, case, ASCII/typographic quotation marks, parentheses, apostrophe, hyphen, repeated spaces, newline, number/date, URL, emoji, and sentence punctuation.

## 4. Stanza results

Measured with:

```powershell
python scripts/benchmark_language_analyzers.py --repetitions 5 --json
```

| Oracle dimension | Correct | Total | Result |
| --- | ---: | ---: | ---: |
| Exact token/source offsets | 197 | 197 | 100% |
| Explicit sentence expectations | 8 | 8 | 100% |
| Expected token found | 57 | 57 | 100% |
| Token kind | 57 | 57 | 100% |
| Normalized lookup | 6 | 6 | 100% |
| Lemma | 37 | 37 | 100% |
| POS | 42 | 42 | 100% |
| Expected morphology fields | 21 | 22 | 95.45% |

All four required `jobb` noun forms resolved to lemma `jobb` and POS `NOUN`. Context changed the selected analysis correctly for the fixture uses of `så`, `norsk`, and `om`.

The generic output contains analyzer/adapter/package/model identity, selected processor packages, resource-manifest fingerprint, exact source fingerprint, sentence/token offsets plus their `UNICODE_CODE_POINT` unit, normalized lookup metadata, lemma candidates, selected model lemma, POS, morphology, confidence basis, lexical status, and ambiguity state. No Stanza object crosses the adapter boundary.

## 5. Simplemma results

Simplemma returned 33 of 37 expected lemmas (89.19%). Its measured import/startup plus fixture comparison took 0.5137 seconds and added approximately 53.80 MiB RSS in the benchmark process.

Observed misses:

| Surface/context | Expected | Simplemma |
| --- | --- | --- |
| noun plural `jobber` | `jobb` | `jobbe` |
| definite plural `Bøkene` | `bok` | `bøk` |
| present `arbeider` | `arbeide` | `arbeider` |
| past verb `så` in “Jeg så filmen.” | `se` | `så` |

Simplemma has no contextual POS or morphology in this comparison. Its lower resource cost is real, but it cannot safely stand in for the canonical contract on these core cases.

## 6. Correctness failures and analyzer limits

Stanza's one oracle mismatch was morphological: `Jobbene` was labeled `Gender=Neut`; the manually expected noun gender is `Masc`. Its lemma `jobb`, POS `NOUN`, definiteness, number, and source span were correct. Phase 1 must treat morphology as provider evidence, not an unquestionable identity key.

Stanza returns a single contextual analysis and does not expose alternate candidates, lexicon membership, or calibrated token confidence through the selected pipeline. The adapter therefore does not claim these exist:

- ambiguity is `NOT_REPORTED`, even when the context-selected analysis is stored;
- invented/foreign tokens are `NOT_ASSESSED`, not lexically `KNOWN`;
- confidence is `null` with `stanza_does_not_expose_token_probability`;
- an `X`/missing analysis remains unresolved.

The schema independently supports zero, one, or multiple lemma candidates and explicit `AMBIGUOUS`/`UNRESOLVED` states. A later lexical provider or user correction may add evidence; the Stanza adapter does not invent it.

## 7. Offset behavior

Every measured token satisfied:

```python
original_text[token.start:token.end] == token.surface
```

Every analysis document also reconstructed byte-for-byte equivalent Python text by combining untouched source gaps with token surfaces. Original repeated spaces, newline, case, punctuation, `æ/ø/å`, URL, and emoji survived, including a lexical token after the emoji. Offsets are explicitly `UNICODE_CODE_POINT` so a future JavaScript Reader must convert them from code points to UTF-16 indices or consume exact backend spans. Normalization exists only in `normalizedLookup`/`normalizedLemma` metadata.

## 8. Performance observations

One repeatable measurement run on the environment above produced:

| Measurement | Result |
| --- | ---: |
| Cold import + Stanza pipeline initialization | 4.4370 s |
| Warm full 10-case corpus, five runs | 0.7824, 0.7584, 0.7495, 0.8159, 0.8490 s |
| Warm corpus median | 0.7824 s |
| Approximate RSS delta after model load | 484.80 MiB |
| Approximate RSS delta after fixture analysis | 478.09 MiB |
| Selected model files on disk | 177.18 MiB |

These are workstation observations, not production service-level guarantees. They support the existing design decision to run text analysis as bounded background work rather than initialize the model in an HTTP request. GPU behavior was not measured.

## 9. Offline and model provisioning behavior

- Stanza 1.14.0 defaults to a resource-download mode. The adapter overrides this with `DownloadMethod.NONE` on every pipeline construction.
- Tests used an empty temporary model directory while patching Stanza download entry points and verified an explicit `UNAVAILABLE` health/error state with zero downloader calls.
- A provisioned pipeline completed analysis while Stanza download functions and socket connection creation were blocked.
- The first explicit provisioning attempt requested `mwt` and failed because the `nb` 1.14.0 manifest contains no MWT model. No runtime code requests it.
- The second explicit provisioning operation downloaded only `tokenize,pos,lemma` plus their published dependencies and succeeded.
- Missing models never produce a fake analysis result.

The explicit setup command is documented in [`LANGUAGE_DATA_SOURCES.md`](./LANGUAGE_DATA_SOURCES.md). No HTTP/API language route exists in Phase 0, so no request can initiate model provisioning.

## 10. wordfreq findings

`nb` is present in the installed package's available languages. Measured Zipf scores were:

| Word | Zipf score |
| --- | ---: |
| `jobb` | 5.56 |
| `jobben` | 5.24 |
| `jobber` | 5.41 |
| `jobbene` | 3.95 |
| `ærlig` | 4.95 |
| `øl` | 4.85 |

These results prove useful score lookup only. No Top 500/1000/2000/5000 lemma rank was inferred or created. Decision: **external ranked frequency dataset required**.

## 11. Canonical analyzer decision

Decision **B** from the Phase 0 brief:

> Stanza is canonical; Simplemma is NOT safe as fallback.

Canonical configuration is `stanza-nb-bokmaal` adapter 1.0.0 with Stanza/resource 1.14.0 and `tokenize,pos,lemma`. The choice is based on the committed oracle and measured source fidelity/contextual analysis.

## 12. Fallback decision

There is no automatic fallback. When Stanza/package/models cannot load, analysis returns an explicit unavailable state and guidance. It must not silently lower-case forms, use Simplemma, or persist substitute lemmas as though they came from the canonical analyzer.

Simplemma remains useful only as a separately labeled diagnostic comparison. Any future reconsideration requires a new fixture/decision version and must expose lower capability/provenance to consumers.

## 13. Other observations and unresolved risks

- AnkiConnect did not answer successfully at `http://127.0.0.1:8765`; the read-only `version` probe received HTTP 404. It remains non-blocking and no Anki mutation was attempted.
- The fixture is deliberately small. More genres, dialectal spellings, named entities, malformed input, very long texts, and additional compounds need evaluation before bulk ingestion.
- Morphology is useful but imperfect; do not make destructive merges from it.
- Model-selected lemmas lack calibrated confidence and alternate candidates.
- Stanza's roughly 486 MiB measured load delta requires lifecycle/concurrency limits.
- The shared Python environment's `requests`/`chardet` warning should be investigated separately before relying on outbound provider HTTP, without changing Phase 0 analyzer behavior.
- Exact ranked frequency, dictionary/senses, translations, CEFR, and lexical relations remain **UNSELECTED** pending license/source review.

## 14. Exact recommendation for Phase 1

Proceed to Phase 1's database/service foundation using the frozen `language.analysis/v1` contract, but do not execute Stanza from an HTTP request yet—that belongs to Phase 2's persisted analysis jobs.

Phase 1 should:

1. store reference provenance separately from user knowledge;
2. persist exact source text and offsets without reconstruction;
3. preserve `UNICODE_CODE_POINT` as the stored offset unit and convert explicitly at any JavaScript boundary;
4. treat `MODEL_SELECTED` as versioned analyzer evidence, not a manual lock;
5. allow multiple candidates and unresolved mappings even though Stanza itself reports one hypothesis;
6. retain `NOT_REPORTED` ambiguity, `NOT_ASSESSED` lexical status, and nullable confidence;
7. never use morphology alone for destructive identity merging;
8. preserve the explicit missing-analyzer health state and no-download policy;
9. keep exact rank/dictionary/translation/CEFR fields nullable until a source is selected.

Phase 0 added no database, migrations, API route, page, widget, navigation entry, Anki write, AI generation, TTS, Cloze, or Grammar implementation.

## Verification commands and results

| Command | Result |
| --- | --- |
| `python -m unittest tests.test_language_analysis tests.test_language_diagnostics -v` | 20 tests, all passed |
| `python -m unittest tests.test_synchrobook_epub -v` | 4 existing wordfreq-adjacent tests, all passed |
| `python scripts/diagnose_language_env.py` | exit 0, `READY`; Anki unavailable remained non-blocking |
| diagnostic with `LANGUAGE_STANZA_MODEL_DIR` pointed at an intentionally absent directory | expected exit 1, `INCOMPLETE`, explicit provisioning guidance, no download |
| `python scripts/benchmark_language_analyzers.py --repetitions 5 --json` | exit 0; measurements recorded above |
| `python -m compileall -q language_learning scripts/diagnose_language_env.py scripts/benchmark_language_analyzers.py` | passed |
