# Language Learning Phase 8 results

Status: **COMPLETE**  
Date verified: 2026-09-17  
Main database schema: **11**  
Reference database schema: **3 (unchanged)**

## Outcome and scope

Phase 8 adds the one authorized automatic text provider, a closed persisted generate → validate → canonical analyze → coverage → bounded revise loop, and on-demand Google Cloud `nb-NO` sentence audio for explicitly accepted generated Reader texts. Manual Phase 7 generation remains first-class. No Listening lesson/service, speech recognition, pronunciation scoring, autoplay, automatic acceptance, knowledge mutation, exposure, Anki write, XP, curriculum generation, later-phase scaffold, or second provider was added.

The selected provider is Google Gemini through the direct `generateContent` REST API, fixed to stable GA `gemini-3.8-flash`, adapter `google-gemini-generate-content/v1`, and policy `FREE_ONLY`. The selection was verified on 2026-09-17 against Google's current [models overview](https://ai.google.dev/gemini-api/docs/models), [Gemini 3.8 Flash model page](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash), [GenerateContent reference](https://ai.google.dev/api/generate-content), [structured-output guide](https://ai.google.dev/gemini-api/docs/structured-output), [pricing](https://ai.google.dev/gemini-api/docs/pricing), [rate-limit guide](https://ai.google.dev/gemini-api/docs/rate-limits), and [API error guide](https://ai.google.dev/gemini-api/docs/api-errors).

## Provider, safety, and privacy

`GeminiGenerationProvider` uses a fixed HTTPS endpoint, server-side `x-goog-api-key`, JSON Schema output for exactly `title` and `text`, a 128 KiB prompt bound, 512 KiB response bound, 45-second default timeout, and 256–8192 output-token clamp. It records the safe request ID, model version, finish reason, allowlisted usage counters, provider latency, transport attempts, status, and error class. Sampling knobs deprecated for the selected generation are omitted.

The server recognizes `NOT_CONFIGURED`, `CONFIGURED`, `AVAILABLE`, `FREE_QUOTA_EXHAUSTED`, `RATE_LIMITED`, `AUTH_ERROR`, `MODEL_UNAVAILABLE`, `NETWORK_ERROR`, and `PROVIDER_ERROR`. Health is local/redacted and performs no API call. The API key never enters frontend code, health, errors, database rows/exports, prompt/context, or logs.

FREE_ONLY protections are explicit: exact model allowlist, one provider, no paid/model/provider fallback, no retry for HTTP 429, and immediate loop termination for auth, model, quota, rate, and terminal provider failures. Only timeout/network/408/5xx transport failures receive one bounded retry (two transport attempts total inside one provider attempt). Account-level billing is controlled by Google and remains external; Phase 8 cannot guarantee or alter that setting.

## Automatic request and revision lifecycle

Schema v11 additively extends Phase 7 request/candidate rows with frozen generation mode/provider/adapter/model/policy/attempt ceiling, durable automatic status/stage/progress/cancellation/best-candidate/error/usage/timing, and per-attempt request/model/finish/usage/latency/transport/error/revision provenance. The existing single `LanguageJobManager` owns the queue; there is no second worker.

Automatic is explicit in the UI. Creating an AUTOMATIC request freezes the same v1 or reference-aware v2 context and then queues it. Stages include context preparation, Gemini attempt N/3, Bokmål analysis, measured coverage, revision preparation, and a terminal READY, OUT_OF_TOLERANCE, FAILED, or CANCELLED state. Restart recovery requeues an interrupted request; cancellation is immediate while queued and cooperative between bounded remote/local steps while running.

Every valid output becomes a separate retained candidate. Canonical analysis and `CoverageService` run after each actual text. Provider claims such as `coverage` or `usedTargets` are ignored. An automatic candidate passes only when the existing Phase 7 token-coverage tolerance passes and every frozen required target is found locally. Manual candidates preserve Phase 7 tolerance behavior.

The loop has exactly three total provider attempts. A miss produces a deterministic revision prompt containing requested/actual/gap/tolerance, word-count miss, missing targets, bounded problematic/unresolved words, safe frozen known-vocabulary hints, and the exact preceding candidate. The natural-language policy requires contemporary Norwegian Bokmål, forbids Nynorsk, English calques, forced targets, unsupported dialect, archaic/rare wording, and uses fictional/generic situations while excluding invented law/tax/benefit/government/health-rule/history/current-event/real-person/company claims.

If all valid candidates miss, `language-generation-best-candidate/v1` ranks: all targets satisfied first, then smallest absolute coverage miss, smallest word-count miss, fewer unresolved tokens, and lower attempt number. The selected row remains honestly `OUT_OF_TOLERANCE`. Nothing is auto-accepted. Explicit acceptance creates `GENERATED_GEMINI` and enters the unchanged Reader analysis path. Current-vocabulary re-score remains unimplemented and is not conflated with frozen generation-time coverage.

## Accepted generated Reader audio

`GeneratedTextAudioService` accepts only empty option payloads plus a 32-hex accepted generated document ID and sentence ID. It loads exact authoritative `text_sentences.exact_text`, requires `GENERATED_*` plus `ANALYZED`, and delegates to the existing `ClozeAudioService`. Thus provider `GOOGLE_CLOUD_TEXT_TO_SPEECH`, language `nb-NO`, configured Chirp 3 HD voice, MP3 encoding, credentials, error semantics, lock, atomic write, cache key, metadata, and cache-hit behavior are identical.

Schema v11 adds only a join/provenance table from accepted generated sentence to the existing `cloze_sentence_audio` cache row. Identical exact sentences reuse the same MP3 even across Cloze and Reader. The UI can play the complete text sequentially or one explicitly selected sentence, offers Play/Pause/Resume/Stop controls, highlights the exact playing sentence with visible and `aria-current` state, and appears only for generated analyzed Reader texts. TTS failure leaves the accepted text intact. Failed/unaccepted candidates have no Reader sentence IDs and therefore cannot request this audio. Listening records no learning evidence or rewards.

## Routes and configuration

New thin routes:

- `GET /api/language/generation/provider-health`
- `POST /api/language/generation-requests/{id}/automatic`
- `POST /api/language/generation-requests/{id}/cancel`
- `POST /api/language/texts/{textId}/sentences/{sentenceId}/audio`
- `GET /api/language/audio/{cacheKey}.mp3`

Configuration names (never values): `LANGUAGE_GEMINI_ENABLED`, `LANGUAGE_GEMINI_MODE`, `LANGUAGE_GEMINI_MODEL`, `GEMINI_API_KEY`, plus existing `GOOGLE_CLOUD_PROJECT`, `GOOGLE_APPLICATION_CREDENTIALS`, and `NORWEGIAN_TTS_VOICE`. Setup and recovery guidance is in [`LANGUAGE_PHASE8_SETUP.md`](./LANGUAGE_PHASE8_SETUP.md).

## Migration and database verification

The canonical database was backed up before Phase 8 implementation at `data/backups/language-learning-v10-20260917T144425738660Z.sqlite`. A post-migration snapshot is `data/backups/language-learning-v11-20260917T151259573486Z.sqlite`. Migration 11 preserved the 305 domain rows present immediately before application, produced 35 non-ledger tables, and passes `integrity_check = ok` with zero foreign-key violations. The independent 4+ GB reference database remains schema 3, passes full `integrity_check = ok` plus `quick_check = ok`, and has zero foreign-key violations.

## Performance and live smoke

Local measurements on this machine, with remote time kept separate:

| Measurement | Median / result |
| --- | ---: |
| frozen context preparation | 20.392 ms |
| deterministic fake-provider adapter | 0.011 ms |
| warm canonical Stanza analysis, about 200 words | 314.961 ms |
| `CoverageService`, 200 tokens | 0.178 ms |
| deterministic revision preparation | 0.035 ms |
| fake TTS synthesis plus atomic persistence | 27.541 ms |
| cached sentence-audio lookup | 2.591 ms |

Gemini and Google ADC configuration were absent in the verification process, so no paid/remote call was attempted and no live text/audio quality claim is made. Fake-provider output verifies orchestration but cannot establish native Bokmål quality. Remaining quality risks are provider phrasing/calques, named-entity or factual mistakes, and local analyzer ambiguity; explicit review, conservative prompts, canonical measurement, and no auto-accept are the mitigations.

## Verification summary

Dedicated Phase 8 backend/provider/loop/TTS tests pass, including first-pass, miss→pass, three misses, deterministic best choice, target enforcement, explicit acceptance, cancellation, malformed output ceiling, auth stop, 429 quota/rate distinction, timeout retry ceiling, refusal, secret redaction, generated-only authoritative TTS, Cloze cache reuse, TTS failure preservation, and HTTP streaming. Focused Phase 8 frontend tests pass for automatic/manual controls, durable progress, attempt/best labels, API mapping, audio controls, highlighting, non-generated absence, and listening-evidence wording.

| Check | Result |
| --- | --- |
| complete Language backend | 199 passed, 0 failed |
| complete Language frontend/widget | 103 passed, 0 failed |
| broad Python backend | 626 passed, 1 skipped, 0 failed |
| broad Vitest frontend | 787 passed, 2 skipped, 0 failed |
| production build | passed; 271 modules transformed |
| Python compilation | passed |
| changed Language JavaScript syntax | passed |
| canonical main DB | schema 11; `integrity_check=ok`; 0 FK violations |
| production reference DB | schema 3; full `integrity_check=ok`; `quick_check=ok`; 0 FK violations |
| real Edge desktop smoke | 11/11 passed at 1440×1000, including sequential whole-text audio advancement |
| real Edge narrow smoke | 11/11 passed at 390×844; no horizontal overflow |

The checked-in smoke fixture covers automatic/FREE_ONLY labeling, persisted progress, honest failed-best state, cancellation, generated sentence audio controls, accessible highlighting, listening boundaries, ordinary Reader isolation, and responsive overflow. The only pre-existing runtime warning observed is the repository's installed `requests` dependency-version warning; it does not fail the suite.

## Files and limitations

Created: `language_learning/providers/generation.py`, `language_learning/generated_audio.py`, `tests/test_language_generation_provider.py`, `tests/fixtures/language/phase8-browser-smoke.html`, this result document, and the setup guide.

Modified: `.env.example`, `language_learning/migrations.py`, `store.py`, `generation.py`, `jobs.py`, `service.py`, `cloze_audio.py`, `server.py`, `js/language/api.js`, `state.js`, `app.js`, `cloze-audio.js`, Generate/Reader/Settings views, `language.css`, focused backend/frontend tests, implementation plan, and run progress.

Known intentional limitations: Google billing policy cannot be enforced by an API payload; live Gemini/TTS smoke requires user-provided configuration; only the most recent active request is restored by the existing localStorage key; current-vocabulary re-score is not implemented; cancellation cannot abort a transport already inside the bounded HTTP call; accepted audio is sentence-level only; no Listening module exists.

The next roadmap work still requires separate authorization. Phase 9A remains historical complete work and was not rerun as a new implementation phase.
