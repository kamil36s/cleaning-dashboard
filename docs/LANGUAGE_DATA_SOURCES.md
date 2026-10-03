# Language Learning data sources

Status: Phase 0 source policy  
Date: 2026-09-15  
Results: [`LANGUAGE_PHASE0_RESULTS.md`](./LANGUAGE_PHASE0_RESULTS.md)

This document is a guardrail for future Language Learning work. Language reference data and user learning data are separate systems. A future task must not fill an unselected reference-data field with generated, guessed, or unattributed content.

## 1. Hard source boundary

### Language reference data

Reference data may include surface forms, lemmas, POS, morphology, frequency scores/ranks, dictionary senses, definitions, translations, CEFR metadata, and lexical relations. Each result must retain a source ID, source version, retrieval/import version, relevant license/attribution, and confidence where the provider supplies one.

Reference data comes from a verified external provider or versioned imported dataset. Codex/LLM output is not a lexical reference source.

### User language knowledge

Knowledge state, exposures, recognition/recall/production, dates, contexts, notes, topics, Anki links, review evidence, and reading history belong to the Language Dashboard. They must not be written into or confused with provider reference records.

Phase 0 implements no user-learning persistence and creates no database.

## 2. Currently selected

### Canonical Bokmål analyzer: Stanza

| Property | Selected value |
| --- | --- |
| Analyzer ID | `stanza-nb-bokmaal` |
| Adapter version | `1.0.0` |
| Python package | `stanza` `>=1.14,<1.15`; tested `1.14.0` |
| Resource/model version | `stanza-resources-1.14.0` |
| Language code | `nb` |
| Processors | `tokenize`, `pos`, `lemma` |
| Packages | `tokenize=bokmaal`, `pos=bokmaal_charlm`, `lemma=bokmaal_nocharlm` |
| Dependencies | `pretrain=conll17`, `forward_charlm=conll17`, `backward_charlm=conll17` |
| Resource-manifest fingerprint | `sha256:d9eb7b2961c646c44f6ea3d968e34c6e4b3e36c400f891076c5fc50e100f6b69` |
| Runtime network policy | Offline only; `DownloadMethod.NONE` is mandatory |

Stanza is selected because the committed oracle measured exact source spans plus contextual tokenization, sentence boundaries, lemma, POS, and morphology in one pipeline. The [official Stanza pipeline documentation](https://stanfordnlp.github.io/stanza/pipeline.html) describes these processors; selection here is based on the local Phase 0 benchmark rather than feature claims alone.

The `nb` resource manifest has no MWT model. An explicit attempt to request `mwt` failed because Stanza 1.14.0 tried the nonexistent combination `mwt=default`. Therefore MWT is not configured for Bokmål Phase 0. Dependency parsing is deliberately excluded.

Offsets use the explicit contract unit `UNICODE_CODE_POINT`, matching Python slicing and Stanza's character offsets. A future browser client must convert these offsets before applying them to JavaScript's UTF-16 string indices, or render backend-provided exact spans; it must not assume the units are identical around non-BMP characters such as emoji.

Stanza does not provide alternate lemma candidates, lexical membership, or a calibrated per-token lemma/POS probability through this pipeline. The contract records:

- contextual output as `MODEL_SELECTED`, not a user-verified fact;
- `ambiguityState=NOT_REPORTED`;
- `lexicalStatus=NOT_ASSESSED`;
- `confidence=null` with an explicit reason.

This prevents invented and foreign-looking words from being labeled as verified dictionary entries merely because the statistical model emits a lemma.

#### Explicit model provisioning

Installing Python packages does not provision a model:

```powershell
python -m pip install -r requirements-language.txt
python -c "import stanza; stanza.download('nb', processors='tokenize,pos,lemma', package='default')"
python scripts/diagnose_language_env.py
```

The download command is a deliberate developer/user operation. Neither the analyzer nor any future HTTP route may call it. A custom pre-provisioned location can be selected with the non-secret `LANGUAGE_STANZA_MODEL_DIR` environment variable.

### Frequency scores: wordfreq, limited use only

| Property | Selected value |
| --- | --- |
| Package | `wordfreq` `>=3.1,<4`; tested `3.1.1` |
| Language code | `nb` |
| Allowed Phase 0/initial role | Runtime Zipf frequency score lookup |
| Forbidden inference | Zipf score → Top 500/1000/2000/5000 lemma rank |

The [official wordfreq repository](https://github.com/rspeer/wordfreq) identifies `nb` as Norwegian Bokmål. The installed package exposes `zipf_frequency`, and local probes returned nonzero scores for the committed Bokmål examples.

Although wordfreq also exposes ordered word-list helpers, those lists are word/form frequency estimates rather than a selected, licensed canonical lemma-band dataset for this dashboard. No Top-N lemma bands are authorized from them. Current decision: **external ranked frequency dataset required**.

### Simplemma: evaluated, not selected

Simplemma 2.0.0 was evaluated on the same hand-authored oracle. It is fast and offline, and its [official documentation](https://github.com/adbar/simplemma) lists Bokmål `nb`. It missed 4 of 37 expected lemmas locally and has no contextual POS/morphology analysis. In particular, it mapped noun `jobber` to verb `jobbe` and past-tense `så` to `så` rather than contextual lemma `se`.

Decision: **Stanza is canonical; Simplemma is not safe as a fallback.** It remains a Phase 0 comparison dependency only. No runtime adapter may silently substitute Simplemma output for Stanza.

## 3. Planned external data — all unselected

No dataset in this section is approved for download, runtime use, bulk import, or redistribution. Selection requires a separate source and license review.

| Category | Information needed | Expected provider/import interface | Likely access pattern | License requirement | Status |
| --- | --- | --- | --- | --- | --- |
| Exact ranked frequency | Versioned Bokmål lemma ranks/bands, corpus/method notes, POS where available | `FrequencyProvider` or validated local import returning lemma, optional POS, exact rank/band, source metadata | Prefer a local versioned import for reproducibility | Verify use, modification, attribution, and redistribution before import | **UNSELECTED** |
| Dictionary and senses | Lemma, POS, sense IDs/order, definitions, inflection references, attribution | `DictionaryProvider.lookup(...)` returning source-attributed sense candidates | Runtime lookup with bounded cache or licensed local import; decide after source review | Verify API terms, caching, display, and redistribution | **UNSELECTED** |
| Translations | Sense-aware translation, target locale, usage notes, confidence | `DictionaryProvider` result or a separately identified translation provider with source metadata | Runtime lookup or licensed local import | Verify storage/display/redistribution and attribution | **UNSELECTED** |
| CEFR metadata | Explicit CEFR level, unit being rated, methodology, source version | `LexicalReferenceProvider` or validated local import | Prefer versioned local import if licensed | Verify that levels may be stored and displayed; never infer silently from frequency | **UNSELECTED** |
| Lexical relations | Synonyms, antonyms, derivations, compounds/phrases, stable relation IDs | `LexicalReferenceProvider.lookup(...)` returning typed relations and provenance | Runtime or imported dataset depending licensing/size | Verify derivative-data and redistribution rights | **UNSELECTED** |

The Phase 0 interfaces live in `language_learning/reference.py`. They carry provider provenance but contain no knowledge status, exposures, Anki state, or other user-learning fields.

## 4. Import rules for a later phase

Before any provider or dataset is selected:

1. Record source owner, URL, exact release/version, retrieval date, license, attribution text, and allowed storage/redistribution.
2. Keep the raw provider result separate from user edits and user knowledge.
3. Validate language code, encoding, lemma/POS semantics, duplicates, coverage, and update strategy on a small preview.
4. Store import/retrieval provenance with every accepted record.
5. Never make a source refresh overwrite a manual correction silently.
6. Never fill gaps with generated frequency ranks, definitions, translations, declension tables, or CEFR labels.

The Norwegian UD Treebank may remain a test/evaluation reference, but it is not selected here as an application frequency/dictionary dataset. Its [official National Library catalogue entry](https://www.nb.no/sprakbanken/en/resource-catalogue/oai-nb-no-sbr-83/) must be revisited with its exact release/license if a later task proposes importing it.
