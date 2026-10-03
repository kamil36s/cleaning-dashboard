# Language Phase 7.7 — Dictionary, meanings, translations, and personal phrasebook

Status: **COMPLETE** on 2026-09-17. Phase 7.8 and every later uncompleted roadmap phase remain not started.

## Delivered scope

Phase 7.7 adds source-attributed live Bokmålsordboka lexical detail, existing KELLY English learner-gloss evidence, separate user translations, and a durable personal Phrasebook. Vocabulary and Reader open the same lexical-detail service; Reader, Cloze and Generate can save exact expressions with context and provenance. The provider and Phrasebook paths cannot write knowledge, exposure, Anki, XP, achievement, campaign or reference state.

The binding source decision record is [`LANGUAGE_DICTIONARY_SOURCES.md`](./LANGUAGE_DICTIONARY_SOURCES.md). No commercial/restricted dictionary was scraped, no Polish or machine translation was invented, no Tier 3 import occurred, and no Phase 7.8/8/full-9/Listening/Grammar work began.

## Storage and identity

Main schema advances additively from v9 to **v10** with:

- `user_lemma_translations`: one user-owned value per canonical lemma and target locale; the value and timestamps are independent of provider facts.
- `phrasebook_entries`: exact expression, normalized search identity, source type (`READER`, `CLOZE`, `GENERATED`, `MANUAL`), source entity, exact context, bounded provenance JSON, stable SHA-256 source fingerprint, optional note/translation and timestamps.
- `phrasebook_entry_links`: optional many-to-one `LEMMA`, `REFERENCE_UNIT` or `TOKEN_SPAN` links with bounded metadata.

A duplicate is the same profile + normalized expression + source type + source fingerprint. Retrying that save reuses the row; the same expression in materially different context/provenance creates a distinct row. Phrasebook edits deliberately change only the learner note and learner translation, preserving expression and source snapshot.

Reference schema remains **v3**. No reference rows, migrations, manifests, artifacts or fingerprints changed. The runtime service reads existing KELLY raw observations using source ID `uio-norwegian-kelly-shu-wang`; the production check for `jobb` returns `job / work` as `SOURCE_GLOSS` with its original CC-BY-SA-4.0 metadata.

## Dictionary and translation behavior

`OrdbokeneDictionaryProvider` is a bounded, read-only runtime adapter over fixed official Display API origins. It has no database/store handle. An explicit lemma open triggers one exact Bokmål search and up to six article reads; responses are not cached. Limits are 3 seconds, 768 KiB per response, six articles, sixteen senses, five examples per sense and sixteen relations. Caller input is URL-encoded, origins are fixed, strings are bounded and output is rendered as text.

Article IDs and definition-local IDs stay distinct: a sense ID is `<articleId>:<sourceLocalDefinitionId>`. Multiple articles/senses are preserved and marked ambiguous; requested POS filters compatible articles, while a same-spelling/different-POS result becomes explicit `POS_MISMATCH`. Definitions, examples, source-provided usage labels, article-reference relations, morphology and pronunciation are emitted only when supplied. Browser TTS is not labeled as source pronunciation.

The official dictionary does not provide an English/Polish value through this adapter. English KELLY text is displayed separately as lemma-level `SOURCE_GLOSS`, never inside the senses array. Polish provider translation is truthfully unavailable. Personal translations may coexist for any locale and are never replaced by a live refresh.

Provider outage, invalid JSON, timeout or oversized responses degrade only the lexical-reference section to `PROVIDER_UNAVAILABLE`; canonical lemma/user detail, KELLY when locally available, personal translations and the rest of Language remain usable.

## Product integration

- **Vocabulary:** opening a canonical lemma lazily loads source lexical detail, provider attribution, multiple senses, examples, labels, relations, supplied pronunciation, KELLY glosses, Polish-unavailable disclosure and personal translation controls.
- **Reader:** opening a token's canonical lemma uses the same service/component. A selection can be saved only when both selection endpoints belong to the same sentence; its exact text, sentence context, text ID and token-span provenance are retained.
- **Cloze:** the current item exposes `Save sentence`; it retains the unclozed sentence and canonical item/source/license attribution without changing the Phase 9A answer/session model.
- **Generate:** the learner explicitly enters the exact useful expression to save; the accepted/analyzed generated text and candidate provenance provide bounded context. Generation v1/v2 behavior is unchanged.
- **Phrasebook:** reload-safe `#phrasebook` supports bounded search, source filtering, safe list rendering, edit of user note/translation, source opening where applicable and delete.
- **Anki:** unchanged. Saving/opening lexical detail creates no note, preview or sync; existing preview/conflict-safe behavior remains authoritative.
- **Gamification:** unchanged. There is no phrasebook reward or XP route; saves and lookups create zero ledger rows/unlocks/campaign changes.

## API and export

Thin endpoints add lexical detail plus create/delete personal lemma translation, and list/create/get/update/delete Phrasebook entries. All writes reuse the existing same-origin policy and bounded Language validation. Main export v10 includes the three user-owned tables; it does not export a live provider body or create a competing derived truth.

## Production migration and integrity

Before migration, canonical schema v9 was backed up to `data/backups/language-learning-v9-20260917T095543036990Z.sqlite` (864,256 bytes). The backup opens as v9, has `integrity_check = ok` and zero foreign-key violations. It contained zero Phase 7.7 user rows, as expected.

The additive v9→v10 migration completed on the canonical main database. The resulting file measured 913,408 bytes and has `integrity_check = ok` with zero foreign-key violations. The production reference database remains schema v3 at 4,222,840,832 bytes; full `integrity_check = ok` and zero foreign-key violations completed in 347,016.2 ms. No reference staging/backup was needed because it was neither migrated nor mutated.

## Performance measurements

Measured production/local operations after migration:

| Operation | Result |
| --- | ---: |
| Live Ordbøkene `data` / requested `NOUN` | 418.7 ms; 2 articles, 4 senses |
| Live Ordbøkene `gå` / requested `VERB` | 468.8 ms; 1 article, bounded to 16 senses |
| Ambiguous local reference resolution for `så` | 627.0 ms; 6 candidates, `AMBIGUOUS` |
| Empty Phrasebook list | 2.4 ms |
| Empty Phrasebook search | 2.7 ms |

All new dictionary work is lazy on explicit lemma opening. Nothing was added to Overview, the dashboard widget, `#progress` or Phase 7.6 collections; their previously measured ~1.47 s / ~1.23 s cost is unchanged and remains a later profiling concern.

## Verification evidence

- New backend coverage: **9 tests** — seven provider/Phrasebook/ownership/export tests in `test_language_dictionary_phrasebook.py`, one additive v9→v10 migration test in `test_language_store.py`, and one thin HTTP flow test in `test_language_api.py`.
- New frontend coverage: **3 tests** — two safe rendering/edit/empty-state Phrasebook tests and one thin Phase 7.7 API test; existing route assertions were extended for `#phrasebook`.
- Focused final provider/reference run: **13 passed**.
- Focused Reader regression after same-sentence selection enforcement: **5 passed**.
- Dedicated reference suite: **15 passed**.
- Complete Language backend: **175 passed**.
- Complete Language frontend/widget: **96 passed**.
- Explicit Phase 9A regression: **16 backend/audio passed** and **9 frontend/audio passed**.
- Phase 7.6 regression: existing gamification coverage remains green in the complete suites.
- Broad frontend: **735 passed, 2 skipped** across 118 files.
- Broad backend: **560 passed, 1 skipped**.
- Python compilation and changed-JavaScript syntax checks: **PASS**.
- Production build: **PASS**, 266 modules transformed; only the repository's existing non-module/chunk-size warnings remain.

The checked-in isolated fixture `tests/fixtures/language/phase77-browser-smoke.html` passes **11/11** assertions in real Microsoft Edge at desktop and emulated 390×844 narrow width; narrow `scrollWidth` is 390. It covers shared source detail, multiple senses/attribution, user translation separation, safe hostile-text rendering, save/retry/edit/delete flows from supported sources, outage state and no horizontal overflow. No screenshot artifact was retained and no canonical user learning evidence was mutated.

## Deviations, limitations, and acceptance

- No accepted Polish provider was found; the result is an explicit unavailable state plus personal translation support.
- Ordbøkene is live/no-cache, so first-open latency and temporary network outage are visible. This is intentional and no offline dictionary body is claimed.
- KELLY glosses are lemma-level evidence and may be coarse; they are never sense-aligned.
- Semantic relations are limited to source-supplied article references. Norsk ordvev ingestion is deferred.
- Pronunciation is displayed only if the article supplies metadata; Phase 7.7 adds no audio pronunciation source.
- Phrasebook v1 is a bookmark/annotation collection, not phrase identity, mastery, SRS or automatic Anki input.
- The browser fixture is an assertion smoke rather than retained screenshot evidence.

All 84 Phase 7.7 acceptance checks are met. There are **no unmet acceptance criteria**. The exact next separately authorized roadmap phase is **Phase 7.8 — Curated vocabulary curricula and Norway practical packs**; it was not started.
