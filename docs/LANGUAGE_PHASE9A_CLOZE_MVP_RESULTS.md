# Language Phase 9A — Cloze Fast Track MVP results

Status: **COMPLETE (2026-09-16)** as an intentionally pulled-forward MVP. Phase 7.5C and Phase 8 remain **NOT STARTED**; full Phase 9 remains **NOT COMPLETE**. Full Listening practice, grammar mining, broad Reader/Vocabulary/Generate reference integration, direct AI providers, idiom curriculum, and Tier-3 ingestion are outside this checkpoint. Cloze includes narrow, on-demand cached Google Chirp 3 HD sentence audio.

## Translation, answer-presentation, and TTS follow-up

The same Phase 9A slice now includes the requested usability follow-up:

- Choices display only numeric shortcuts `1`–`4`; the duplicate A/B/C/D labels and shortcuts are removed.
- The missing span is a single styled blank rather than underscore characters.
- Option presentation normalizes the first letter of every choice together. At sentence start all four choices are capitalized, so capitalization cannot reveal the answer. Frozen source forms remain unchanged for scoring and evidence.
- Direct English translations can be shown before answering, after answering (default), or never. The choice is stored in `language.cloze.preferences.v1` in browser local storage.
- Manual sentence playback uses server-side Google Cloud TTS with `nb-NO` and configurable default voice `nb-NO-Chirp3-HD-Kore`. The first request stores a local MP3 and schema-v8 provenance; matching later requests use the local file. There is no voice selector, automatic playback, bulk generation, or full Listening phase.
- Reference schema v3 adds provenance-preserving sentence translations. The 2026-09-12 official direct `nob-eng` link export plus the English sentence export produced 14,687 direct translation rows covering 13,729 Norwegian source sentences; 9 eligible links lacked an English row. New sentence selection prefers a translated candidate while retaining deterministic quality and seed ordering.

Translation artifacts:

| Artifact | Bytes | SHA256 |
| --- | ---: | --- |
| `nob-eng_links.tsv.bz2` | 89,936 | `fe13d89c08566599a85351a0021f09babe54847aef722a612d9adb2147a3bad4` |
| `eng_sentences.tsv.bz2` | 24,873,473 | `7c46287a9146d8090ea26b6b2eaadc759b92a550e865e32388077806f584ee62` |

## Delivered slice

- A dedicated, reload-safe `#cloze` view with five KELLY learner-rank tracks, real encountered/playable counts, 10/20/50-question sessions, deterministic numbered options, keyboard input, immediate feedback, reveal, skip, completion, resume, and bad-question reporting.
- Narrow read-only runtime access to the reference database. Cloze does not initialize, rebuild, or mutate that database and does not broaden reference integration into Reader, Vocabulary, or Generate.
- Additive main schema v8 persistence for sessions, compact frozen item snapshots, idempotent attempts, user-local target/sentence suppressions, and deterministic sentence-audio cache metadata.
- Reference schema v3 sentence/occurrence/translation storage with independent migrations, import provenance, source/license retention, exact Unicode-code-point offsets, deterministic form resolution, quality facts, and targeted indexes.
- Reviews keeps `ANKI SCHEDULED` separate from `DASHBOARD CLOZE PRACTICE`; Statistics adds a compact attempt/outcome/accuracy section; learning-plan v3 adds a deterministic `CLOZE_MISTAKES` action only when real mistakes exist.

## Tatoeba source decision and artifacts

The official [Tatoeba downloads page](https://tatoeba.org/en/downloads) and per-language export infrastructure were used; no sentence webpage was scraped. Both files were streamed from BZip2 TSV by Python. Full corpora were never passed through model context.

| Import order | Source/artifact | License | Bytes | SHA256 | Rows / usable |
| --- | --- | --- | ---: | --- | ---: |
| 1 | `https://downloads.tatoeba.org/exports/per_language/nob/nob_sentences_CC0.tsv.bz2` | CC0-1.0 | 326 | `23c9f2a2bc900afb04c805521ef16a194bd779f72008512655f48d841d7b46eb` | 5 / 5 |
| 2 | `https://downloads.tatoeba.org/exports/per_language/nob/nob_sentences.tsv.bz2` | CC BY 2.0 FR | 237,135 | `29a20c79c4124ce858575dc89a0de304983410bbdac75a78feda6fc6d7ee0997` | 18,383 read; 18,378 accepted; 17,412 usable |

Retrievals occurred at `2026-09-16T17:53:08Z` and `2026-09-16T17:53:36Z`. The official export last-modified values were `2026-09-12 12:39:13 GMT` and `2026-09-12 12:39:11 GMT`. Exact HTTP metadata lives in the two accepted source manifests.

The dedicated CC0 export measured only five Bokmål sentences, which cannot supply one ten-question session. That insufficiency was measured before fallback. The broader authoritative export was therefore explicitly authorized under the task's fallback rule. Every item retains the Tatoeba source ID, sentence ID, source URL, `CC-BY-2.0-FR` license label, and attribution in both the UI payload and historical item snapshot. The five duplicate IDs in the broad export did not replace the already-imported CC0 rows.

## Import and coverage

Import/parser version is `tatoeba-nob-sentences/1.0.0`; form mapping is `language.reference-sentence-mapping/v1`; import quality is `language.cloze-sentence-quality/v1`.

- 18,383 stored Bokmål sentence rows; 17,417 usable.
- 122,042 occurrence mappings: 43,827 matched, 76,369 ambiguous, and 1,846 unmatched.
- 5,722 unique reference lexical units have at least one matched sentence occurrence.
- Runtime target eligibility requires one exact, unambiguous occurrence of the selected lexical unit in a usable sentence with a direct English translation.
- HTML-looking text is retained as text and flagged; malformed/overlong rows become unusable. Duplicate sentence IDs are deterministic.

| Track | KELLY `SOURCE_LEARNER_RANK` | Ranked targets | Runtime playable (translated) | ≥3 base candidates | Playable coverage |
| --- | ---: | ---: | ---: | ---: | ---: |
| `FAST_TRACK_1` | 1–500 | 420 | 300 translation-ready | 280 | 71.43% |
| `FAST_TRACK_2` | 501–1000 | 427 | 292 translation-ready | 233 | 68.38% |
| `FAST_TRACK_3` | 1001–2000 | 914 | 503 translation-ready | 360 | 55.03% |
| `FAST_TRACK_4` | 2001–4000 | 1,842 | 663 translation-ready | 336 | 35.99% |
| `FAST_TRACK_5` | 4001–6000 | 1,830 | 460 translation-ready | 168 | 25.14% |

Track definition is `language.cloze-fast-track/v1`. These are KELLY learner-oriented source ranks, not CEFR and not a universal Norwegian frequency rank. Production CEFR reference rows remain zero. Targets without a suitable sentence or three safe distractors are skipped and do not block a track.

## Deterministic selection and distractors

Target selection (`language.cloze-target-selection/v1`) prioritizes never attempted, recent incorrect, LEARNING, weak-score, underexposed, lower exposure/attempt counts, better KELLY rank, and stable reference key. `RECYCLE_MISTAKES` orders recent incorrect targets first. There are no SRS due dates.

Sentence selection (`language.cloze-sentence-selection/v2`) starts from indexed target-to-sentence occurrences, requires one unambiguous target occurrence plus a direct English translation, honors local suppressions, and orders by importer quality plus surrounding user-known/ignored vocabulary, unresolved/unknown context, stable seeded order, and stable ID. The importer rewards practical 5–18-token, mostly resolvable sentences and penalizes fragments, very long or malformed text, URLs, excessive punctuation/numbers/proper-name patterns, repeats, and unresolved density. Selection does not change knowledge.

Distractors (`language.cloze-distractors/v1`) are local and deterministic: same normalized POS is mandatory; exact Ordbank `rawTag` is preferred, then compatible leading morphology tag; nearby KELLY rank follows. Canonical lemma and normalized surface form are unique. Three distractors plus the exact expected source form are stably shuffled from session/item seed. An item is skipped when three safe choices are unavailable. AI and bulk Stanza are not used.

Production read-only benchmark medians on the 4.2 GB reference database were 0.009 ms for source-ID lookup, 0.012 ms for sentence-occurrence lookup, 0.762 ms for a target candidate lookup, and 314 ms for all five playable-track aggregates. An isolated cold ten-question session took 2,139 ms. Runtime uses indexed SQL and only bounded candidate lists; it does not scan millions of rows in Python per item.

## Persistence and evidence semantics

Main schema v7 added `cloze_sessions`, `cloze_attempts`, and `cloze_item_suppressions`; schema v8 adds only `cloze_sentence_audio`. A session stores profile, mode, track key/version, requested size, seed, compact item snapshots, status, and timestamps. Each attempt stores session/item identity, user lemma ID, stable reference target/sentence keys, item fingerprint/snapshot, expected and chosen forms, four options, distinct `CORRECT`/`INCORRECT`/`REVEALED`/`SKIPPED` outcome, bounded response time, idempotency key, timestamp, and rule versions. Audio rows store source identity, full text, local relative path, language, provider, voice, encoding, text hash, settings, and timestamp.

The compact snapshot preserves sentence text, blank span, exact expected form, options, target display, KELLY metadata, source/license/attribution, morphology, and versions so history survives a reference rebuild. Retrying the same command returns the existing attempt; reusing an idempotency key for another item is a conflict.

Only targets selected into a real study session are ensured in user Vocabulary through existing `LanguageService` lemma/form invariants. Reference import creates no user vocabulary. Attempts call `LanguageService.record_cloze_evidence`, producing attributable `CLOZE_CORRECT`, `CLOZE_INCORRECT`, `CLOZE_REVEALED`, or `CLOZE_SKIPPED` events under `language.cloze-evidence/v1`. They create no Reader exposure or Anki note/card/schedule and do not modify recognition/recall/production scores, disposition, or canonical knowledge status. Correct once means evidence, not mastery.

## Migrations, backup, and integrity

- Main database: schema v8, 28 application tables, migrations 1–8.
- Pre-migration SQLite backup: `data/backups/language-learning-v6-pre-phase9a-20260916T180510692742Z.sqlite` (schema v6, integrity `ok`, zero FK violations).
- Pre-audio-migration SQLite backup: `data/backups/language-learning-v7-pre-cloze-audio-20260916T200600743750Z.sqlite` (schema v7, integrity `ok`, zero FK violations).
- Reference database: independent schema v3 and remains rebuildable.
- Post-migration main `PRAGMA integrity_check` is `ok`, has zero `foreign_key_check` rows, and starts with zero audio metadata rows; audio remains on-demand.

## Tests and smoke evidence

Backend coverage includes ten Phase 9A tests in `tests/test_language_cloze.py` plus the explicit v6→v7 additive migration test in `tests/test_language_store.py`. It covers streamed Bokmål/`æøå` import, direct translation import/provenance, CC0 provenance, duplicate IDs, matched/ambiguous/repeated occurrences, HTML-looking and malformed text, schema/coverage determinism, capitalization-neutral presentation, compatibility enrichment of legacy active sessions, rank boundaries and priority/tie rules, missing-sentence and insufficient-distractor skipping, 10/20/50 sizes, deterministic order/shuffle, same-POS/morphology choices, all outcomes, response time, idempotency, completion, recycle, suppression, domain invariants, no mass vocabulary creation, and the real HTTP tracks/start/attempt/reload/report slice.

The frontend Cloze tests cover route/API paths, start and track selection, 10/20/50 controls, safe numbered rendering, attribution, number/Enter keyboard flow, translation timing, cached-audio controls/states/playback, feedback/next, reveal, skip, resume, report, completion, and Reviews navigation. Backend audio tests cover full unclozed text, Google REST payload, cache miss/hit, missing-file recovery, metadata persistence, local streaming, failure isolation, and same-key concurrency without paid calls.

- Dedicated reference suite: 9 passed.
- Complete Language backend after the audio follow-up: 148 passed.
- Complete Language frontend plus its dashboard widget after the follow-up: 80 passed.
- Broad backend: 488 passed, 1 skipped.
- Broad frontend: 708 passed, 2 skipped.
- Production Vite build: passed (264 modules transformed). Python compilation and focused JavaScript syntax checks passed.

The production reference DB passed `PRAGMA quick_check` and has zero foreign-key violations. An isolated production-reference session produced ten translation-bearing questions. A read-only headless Edge visual check of the existing active session confirmed the styled single blank, numeric-only options, TTS control, compact preferences, and no horizontal overflow; it did not submit an answer or mutate user progress.

A real headless Microsoft Edge flow used an isolated synthetic reference/user database and the real HTTP server/UI: open `#cloze`, start Track 1 ×10, produce `CORRECT`, `INCORRECT`, `REVEALED`, and `SKIPPED`, finish, reload, open Reviews, and verify both Anki and Cloze cards. It passed with four correct, four incorrect, one reveal, one skip, persisted ten attempts, and no horizontal overflow. No canonical user or Anki data was mutated.

## Read-only Anki diagnostic

No Anki process was running. Port `127.0.0.1:8765` was listening, but its owner was PID 23464, `python.exe -u run_network_monitor.py`; both GET and AnkiConnect `POST {"action":"version","version":6}` returned HTTP 404. Therefore AnkiConnect is not reachable at the configured endpoint and likely cannot bind its default port while the network monitor owns 8765. No add-on was installed and no deck/note mutation was attempted. Resolve the port collision or configure AnkiConnect and the dashboard to a matching free loopback port, then repeat the version probe.

## Files

Created for the audio follow-up: `language_learning/cloze_audio.py`, `js/language/cloze-audio.js`, `tests/test_language_cloze_audio.py`, `tests/language-cloze-audio.test.js`, and `docs/LANGUAGE_CLOZE_AUDIO.md`.

Modified for the audio follow-up: `.env.example`, `.gitignore`, `requirements-language.txt`, `language_learning/migrations.py`, `store.py`, `service.py`, `server.py`, `language.css`, Language state/API/app/Cloze view, `tests/test_language_store.py`, `tests/test_language_api.py`, `tests/language-cloze.test.js`, this result document, and run progress. The former browser-only `cloze-tts.js` and its test were replaced by the local-audio player.

## Deviations and limitations

- CC0-only was preferred but unusable at five rows. The documented, attributed CC BY 2.0 FR fallback is the one intentional source deviation and follows the task's explicit fallback policy.
- Same-session delayed resurfacing was optional and is not implemented; mistakes recycle across sessions and receive higher future priority.
- Stanza confirmation is optional and omitted; exact reference form/POS/morphology matching keeps the basic flow fast and offline.
- Goals were not expanded because it was not trivial or necessary for today's usable slice.
- Translation-ready track coverage decreases to 25.14% by ranks 4001–6000; unavailable targets are honestly skipped. There is no Track 6, fabricated CEFR, semantic guarantee for every distractor, machine-translated fallback, or generated fallback sentence.
- Bad reports suppress a target/sentence pair locally; they do not delete reference data or globally curate Tatoeba.

## Recommendation

Use the MVP and review real bad-question reports first. Tomorrow's highest-value bounded follow-up is improving sentence/distractor quality rules from those reports and resolving the AnkiConnect/port-8765 collision. Keep Phase 7.5C, Phase 8, full Phase 9, Listening, and Grammar behind separate authorization.
