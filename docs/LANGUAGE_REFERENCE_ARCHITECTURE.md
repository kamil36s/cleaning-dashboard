# Language Reference architecture

Status: **Phase 7.5A frozen design plus isolated schema-v1 spike**  
Date: 2026-09-16  
Scope: Norwegian Bokmål reference facts; no normal Language runtime integration

## 1. Non-negotiable boundary

Two domains exist and neither owns the other:

| Domain | Database | Identity | May contain |
| --- | --- | --- | --- |
| User learning | `data/language-learning.sqlite` | existing `VocabularyLemma` | knowledge state, scores, exposures, Reader, Anki, user Topics, goals, generation |
| Language reference | configurable; default `data/reference/language-reference-nb.sqlite` | `ReferenceLexicalUnit` | lexicon/forms, corpus observations, ranks, CEFR evidence, MWEs, idioms, collocations, domains, source/import provenance |

Reference rows never imply knowledge, create exposure, change recognition/recall/production, seed user vocabulary, or become user Topics. `VocabularyLemma` remains the only user word identity. The reference spike does not import `LanguageStore`, does not add a main-database migration, and is not initialized by `server.py`.

The path is resolved server-side from `LANGUAGE_REFERENCE_DB`; raw source storage is resolved from `LANGUAGE_REFERENCE_SOURCE_DIR`. Defaults are project-relative, never drive-specific. These paths must not appear in future public health payloads.

## 2. Reference identity

`ReferenceLexicalUnit` supports `LEMMA`, `PHRASE`, `IDIOM`, `COLLOCATION`, and `FORMULA`. It stores original canonical form and a separately derived NFC/casefold lookup form. Norwegian `æ`, `ø`, and `å`, word boundaries, and display case are never stripped or rewritten.

The deterministic key contract is `reference-key/v1` over:

```text
language | unit type | normalized canonical form | POS | identity qualifier
```

Components are percent-escaped. SQLite row IDs are deterministic hashes of this stable key and are not themselves the identity contract. POS distinguishes ordinary homographs. If one source has multiple same-spelling/same-POS units, the importer must preserve them with an explicit stable `identity_qualifier`; it must never collapse them silently. Cross-source reconciliation of such qualified units is reviewable and provenance-bearing.

Reference forms are separate from user `SurfaceForm`. A shared reference form can link to several lexical units with source, source-local ID, morphology, form type, orthographic status, and import run. Reference forms are never copied automatically into user vocabulary.

## 3. Independent schema v1

The implemented schema is in `language_learning/reference_core/schema.py` and has its own checksumed ledger, `reference_schema_migrations`. It is unrelated to main Language schema v6.

| Table | Responsibility |
| --- | --- |
| `reference_sources` | canonical source registry, version, landing/download metadata, verified license and attribution |
| `reference_import_runs` | importer/version/checksum/status/counts/warnings/errors/schema provenance |
| `reference_lexical_units` | source-neutral lemma/expression identity |
| `reference_source_links` | source-local records and raw-entry provenance linked to reference units |
| `reference_forms`, `reference_form_links` | display/lookup forms and source-scoped morphology links |
| `reference_frequency_observations` | source-scoped raw or derived count/rank/per-million/Zipf/document-frequency/dispersion evidence |
| `reference_cefr_evidence` | evidence type, confidence, best level and optional A1-C2 distribution |
| `reference_mwe_components` | ordered token/lemma/POS constraints for phrases, idioms, collocations and formulae |
| `reference_expression_variants` | source-attributed expression variants |
| `reference_association_evidence` | versioned collocation metrics and raw counts |
| `reference_domain_evidence` | source/method/version-aware domain or register evidence |

There is no EAV facts table and no all-purpose 70-column lexical table. Nullable metric columns exist only where audited sources genuinely differ. Every imported observation has a source; derived observations additionally require method/version and preserve their raw inputs.

## 4. Frequency is a family of observations

There is no magic frequency field. Valid metric labels include:

- `ZIPF_FREQUENCY` for existing wordfreq evidence;
- `SOURCE_FORM_RANK` for an exact case-sensitive source row;
- `SOURCE_NGRAM_FREQUENCY` for raw n-gram counts;
- `DERIVED_LEMMA_FREQUENCY` and `DERIVED_LEMMA_RANK` only for explicitly versioned aggregation.

An exact rank always belongs to a named corpus/source. The CLARINO surface row rank is not a lemma rank. wordfreq remains a Zipf estimate and never becomes an exact rank.

A future derived lemma frequency may aggregate source-form counts after mapping forms through Norsk ordbank, with Stanza used only for unresolved contextual samples. The method must define treatment of case, punctuation, proper nouns, homographs, alternate norms and unmapped forms; it must retain all source-form observations and publish a new method version. The derived rank is labeled as derived, never as the source's original rank.

Audited sources supply no defensible general document-frequency/dispersion field. NBdigital supplies year-frequency dictionaries, not document frequency; the Bokmål n-gram and CLARINO lists supply counts/ranks. `document_frequency` and `dispersion` therefore stay null unless a later source directly supplies them or a versioned importer derives them from document-level evidence.

## 5. CEFR evidence without frequency leakage

CEFR evidence type and confidence are independent:

- types: `SOURCE_LABEL`, `LEARNER_CORPUS_DISTRIBUTION`, `TEXTBOOK_DISTRIBUTION`, `EXPERT`, `ESTIMATED`;
- confidence: `HIGH`, `MEDIUM`, `LOW`, `ESTIMATED`.

The model supports one best level and/or six non-negative A1-C2 values. Values may be normalized shares, per-million frequencies, or source scores, but the method and source define which. `ESTIMATED + HIGH model probability` is still estimated; the UI must not render it as `SOURCE_LABEL + HIGH`.

Frequency may become one input to a future estimator, but frequency never automatically becomes canonical CEFR. Current Norwegian KELLY files have no CEFR column, and current CEFRLex has no Norwegian resource. No production Norwegian CEFR source is accepted in Phase 7.5A.

## 6. MWEs, idioms and collocations

Expressions are lexical units, not annotations on one component lemma. `på grunn av` can exist independently of `på`, `grunn`, and `av`. Ordered components can constrain surface, lemma and POS and can mark optional/variant metadata.

Future Phase 7.5C matching contract:

1. produce surface- and lemma-pattern candidates from analyzed sentence tokens;
2. preserve punctuation boundaries unless a source pattern explicitly permits them;
3. match case through normalized lookup while retaining original spans;
4. prefer the longest source-supported match;
5. retain overlapping/nested candidates and resolve them with a versioned precedence rule rather than deleting evidence;
6. treat optional tokens and inflection only through explicit component rules;
7. return ambiguous candidates when lemma/POS constraints do not select one unit;
8. never use raw substring matching as the authoritative detector.

An `IDIOM` may have variants and source frequency, but no meaning is stored when the source supplies none. The official idiom source audited here supplies expressions/completions/counts, not definitions.

For collocations, retain raw count plus **logDice** as the primary ranking metric: it is symmetric, comparatively interpretable across frequency ranges, and less dominated by rare pairs than PMI. Retain **normalized PMI** only as a secondary diagnostic for unusually exclusive associations, always with minimum-count filtering. Do not calculate a metric merely because a column exists; each calculation records corpus, window/direction, tokenization and metric version.

## 7. Domains and user Topics

Reference domains/registers are linguistic evidence (`WORK`, `BUSINESS`, `EVERYDAY`) with source, method, version, confidence and weight. User Topics are learner-curated groups in the main database. A reference domain can support a future Topic suggestion but never creates or edits membership automatically. LLM-generated domains are not allowed in Phase 7.5A/7.5B.

## 8. Resolver contract

`ReferenceResolver` accepts only a `VocabularyLemmaIdentity` projection and performs read-only reference lookup.

1. exact language + normalized lemma + POS;
2. if user POS is absent, a single normalized candidate may match; multiple candidates are `AMBIGUOUS`;
3. if reference POS is absent, one normalized candidate may match with an explicit fallback basis;
4. a non-null POS mismatch is `UNMATCHED`, with normalized candidates returned only for review;
5. no edit distance, embedding or opaque fuzzy auto-selection.

Results are `MATCHED`, `AMBIGUOUS`, or `UNMATCHED`, include candidates and match basis, and publish `reference-resolver/v1`. A future manual override belongs in an inspectable crosswalk, not in either lexical identity and not as a silent overwrite.

## 9. Read-only service and future payload

A future `ReferenceLexiconService` may expose read-only `lookup_lemma`, `lookup_surface`, `get_unit`, `frequency_evidence`, `cefr_evidence`, `mwe_evidence`, `idiom_evidence`, `collocations`, `source_provenance`, and `health/version`. Normal Language mutations remain in `LanguageService`.

A combined UI response must have explicit sibling objects:

```json
{
  "reference": {"unit": {}, "frequency": [], "cefr": [], "domains": [], "expressions": [], "sources": []},
  "user": {"vocabularyLemmaId": "...", "knowledge": {}, "exposures": 7, "anki": {}},
  "resolution": {"status": "MATCHED", "ruleVersion": "reference-resolver/v1"}
}
```

Phrase payloads can omit `user` until a user-knowledge model is deliberately introduced. Missing reference fields remain absent/null, not guessed.

## 10. MWE user-knowledge decision

Three options were evaluated:

- **A — add linked `LexicalUnitKnowledge` later:** expressive, but creates a second knowledge abstraction and a difficult merge/statistics/migration boundary.
- **B — generalize current user vocabulary identity:** ultimately coherent, but risks every current lemma/form/token/Anki/generation foreign key and violates the inserted phase's no-risk-migration boundary.
- **C — reference annotations first:** no schema risk and lets Reader matching quality be measured, but cannot yet claim phrase mastery.

Recommendation: **C for Phase 7.5C**, then design a carefully migrated generalized user lexical identity only after real MWE occurrence evidence exists. Do not add a parallel phrase knowledge store. Existing `VocabularyLemma` remains canonical and word-only now.

## 11. Reader, generation and coverage integration boundaries

Phase 7.5C may annotate Reader tokens with reference matches, but import/render/reopen still create zero user evidence. MWE occurrences need exact token spans and detector/source versions.

Phase 7 generation remains unchanged. Future enrichment requires new semantic versions rather than changing v1 meanings in place:

- `language-generation-targets/v2` for reference-aware target/avoidance rules;
- `language-generation-context/v2` for frequency/CEFR/MWE reference files;
- `language-generation-prompt/v2` for the corresponding instructions;
- a new frozen reference DB/source fingerprint in each request.

User knowledge coverage remains `language.coverage-policy/v1`. Future independent analyses are user token coverage, user lemma coverage, reference CEFR distribution, frequency profile, MWE profile and idiom profile. None replaces or changes the existing coverage denominator.

## 12. Index and performance plan

Schema v1 indexes exact lemma+POS, normalized surface, prefix-friendly normalized unit/form order, unit type, source/rank, CEFR level/type, MWE first components, expression variants, domain, and top association score. Phase 7.5B must measure query plans after each tier and run `ANALYZE` only after bulk load. Create secondary indexes after the largest batch when that materially reduces insert time. SQLite remains appropriate for a local read-mostly lexicon; no FTS engine is justified until measured prefix/subsequence queries fail budgets.

## 13. Rebuildability and operations

The reference DB is disposable and reproducible from versioned manifests, source archives, checksums and importer versions. It must never become a hand-edited sole source of truth. Source archives and large databases are ignored by Git. Only code, manifests, schemas, tiny synthetic fixtures, tests and documentation are committed.

Large datasets must never be pasted or read wholesale into Codex context. Importer work inspects only documentation, headers and tiny bounded samples; Python streams the full files outside model context.
