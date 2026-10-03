# Language reference derived metrics

Status: **Phase 7.5B frozen registry**  
Rule: raw source observations remain authoritative and are never overwritten.

## Shared mapping policy

Both Phase 7.5B lemma-frequency derivations use exact NFC + casefold surface lookup against Norsk ordbank forms.

- Original source form, case, count, rank, and raw metadata remain in `reference_raw_observations`.
- Rows without a Unicode letter and explicit sentence-boundary markers are `EXCLUDED_NONLEXICAL` for derivation, but remain stored.
- Proper nouns are neither guessed nor categorically removed. Casefold lookup may resolve them; multiple candidates stay ambiguous.
- A surface with exactly one distinct Ordbank lexical-unit candidate is `MATCHED`.
- One-to-many mappings are `AMBIGUOUS`; no count is split and no homograph is selected.
- Zero-candidate rows are `UNMATCHED`.
- Matched form counts are summed by stable Ordbank lexical-unit identity.
- `DERIVED_LEMMA_RANK` orders descending derived count. Equal counts share a SQL `RANK` value and subsequent ranks have gaps.
- Failure leaves raw observations intact and prevents publication.

## `clarino-derived-lemma-frequency/v1`

Input: frozen CLARINO `SOURCE_FORM_RANK` rows and raw counts.  
Policy checksum: `sha256:f41d46f85206a764a36ed2a72f4e485c35513c6afdd67a9cfd6f223115a950f6`.

Observed result:

| Measure | Value |
| --- | ---: |
| raw rows | 9,999 |
| matched rows | 5,984 |
| ambiguous rows | 2,627 |
| unmatched rows | 1,041 |
| excluded nonlexical rows | 347 |
| total source mass | 1,809,522,460 |
| uniquely mapped mass | 539,127,676 (29.793920%) |
| ambiguous mass | 876,048,811 |
| unmatched mass | 40,586,763 |
| excluded nonlexical mass | 353,759,210 |
| derived lemmas | 3,835 |
| derived observations | 7,670 (frequency + rank) |

The 29.79% uniquely mapped mass is deliberately not presented as complete corpus coverage. High-frequency function-form homography accounts for much of the ambiguous mass. Raw case-sensitive rank is still `SOURCE_FORM_RANK`, never a lemma rank.

## `bokmal-unigram-derived-lemma-frequency/v1`

Input: frozen Bokmål unigram `SOURCE_NGRAM_FREQUENCY` rows and raw counts.  
Policy checksum: `sha256:f636adc6565e881a39e60c5231c7c0044a3898239718677eccce84296c12f164`.

Observed result:

| Measure | Value |
| --- | ---: |
| raw rows | 3,307,461 |
| matched rows | 433,357 |
| ambiguous rows | 33,886 |
| unmatched rows | 2,744,197 |
| excluded nonlexical rows | 96,021 |
| total source mass | 1,456,290,754 |
| uniquely mapped mass | 453,214,139 (31.121130%) |
| ambiguous mass | 614,986,226 |
| unmatched mass | 73,925,199 |
| excluded nonlexical mass | 314,165,190 |
| derived lemmas | 120,749 |
| derived observations | 241,498 (frequency + rank) |

The unigram and CLARINO totals remain separate source observations. They are not blended into a universal rank.

## Explicit non-metrics

- KELLY rank is stored as exact source-specific `SOURCE_LEARNER_RANK`; it is not derived CEFR.
- Production CEFR evidence is empty. Frequency is never converted to A1-C2.
- No domain/register evidence is inferred.
- No logDice, nPMI, dispersion, document frequency, phrase, or collocation metric is computed in Phase 7.5B.
- `PHRASE`, `IDIOM`, `COLLOCATION`, and `FORMULA` schema support remains available; only official `IDIOM` units are populated here.

