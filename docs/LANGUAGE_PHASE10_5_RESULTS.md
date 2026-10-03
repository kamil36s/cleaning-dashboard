# Language Dashboard Phase 10.5 results

Status: **COMPLETE**  
Verified: 2026-09-18  
Next roadmap phase: **Phase 11 — Grammar mining from real reading** (not started)

## Delivered architecture

One `#inbox` intake surface stores source/rights metadata in `content_items`, routes canonical text/transcript projections to the existing Reader, and routes managed audio plus current sentence alignments to the existing Listening session/event/progress architecture. It creates no second analyzer, vocabulary store, worker, scheduler, exposure system, goal system, or playback coordinator.

Supported local sources are `PASTED_TEXT`, `LOCAL_AUDIO`, `LOCAL_TRANSCRIPT`, `LOCAL_AUDIO_PLUS_TRANSCRIPT`, `SRT`, and `VTT`. `ARTICLE_REFERENCE`, `PODCAST_REFERENCE`, `VIDEO_REFERENCE`, and official-host `NRK_REFERENCE` are metadata-only `REFERENCE_ONLY` records with `STORAGE_NOT_AUTHORIZED`. Unknown sources fail closed. Full decisions are in [`LANGUAGE_CONTENT_SOURCES.md`](./LANGUAGE_CONTENT_SOURCES.md).

Policies are `language.content-rights/v1`, `language.content-ingestion/v1`, `language.transcript-segmentation/v1`, `language.transcript-alignment/v1`, `language.listening-activity/v2`, `language.listening-exposure/v2`, and preserved `language.listening-completion/v1`.

## Content, media, transcripts, and alignment

`ContentItem` owns source, rights, retention, fingerprints, routing links, and readiness. Existing `TextDocument` remains the canonical analyzed text owner. Pasted text and transcript revisions create source-attributed `TextDocument` projections, enqueue the existing `LanguageJobManager`, and reuse canonical Stanza analysis, CoverageService, reference profile/idiom/MWE enrichment, and Reader.

Local audio supports byte-sniffed MP3, M4A/MP4 audio, WAV, and OGG. Uploads are limited to 64 MiB, use SHA-256 identity and generated filenames, and live under ignored `data/language-learning/media/`; SQLite contains no media BLOB or client path. Transcript input is limited to 2 MiB, 20,000 cues, and 24-hour timestamps. SRT/VTT preserve multiline Unicode, identifiers, source order, cue offsets, overlaps, and gaps; malformed, empty, out-of-order, oversized, and out-of-range data fail explicitly.

Transcript revisions append immutable version rows and new canonical text projections. Cue character spans map deterministically to canonical Stanza sentences. One cue can split proportionally over sentences; one sentence can span cues. Missing overlap creates no timestamp. Methods are disclosed as `IMPORTED_SRT`/`IMPORTED_VTT`; confidence is `null` and `CONFIDENCE_NOT_REPORTED`. Manual correction appends `USER_CORRECTED`, supersedes the prior row, and serialized idempotent refresh never overwrites it.

Forced alignment is explicitly **DEFERRED**. No credible accuracy claim was possible without an installed aligner and reviewed Norwegian gold fixture. WhisperX, MFA, aeneas, and installed Whisper were evaluated in [`LANGUAGE_ALIGNMENT_DECISION.md`](./LANGUAGE_ALIGNMENT_DECISION.md).

## Authentic Listening semantics

HTML Audio runs under the existing playback coordinator with play/pause/resume/stop/replay, sentence jump, aligned seek, rate, highlighting, Listening Only/reveal, and exact-sentence Phrasebook saving with content/transcript/alignment/timestamp provenance. Transcript rendering is windowed to at most 201 sentences, including a tested 5,000-sentence payload.

`AUTHENTIC_MEDIA` is an explicit playback source. Actual active wall time is distinct from the union of non-seeked played intervals (`coverage_ms`). Server qualification uses current-alignment duration and requires natural `ENDED` plus at least 80% coverage. Pauses, stalls, waiting, errors, cancellation, inactive gaps, and seek gaps do not fabricate coverage. Import, analysis, preview, reveal, alignment, and Phrasebook saving create no evidence.

Only a current managed-media alignment can authenticate an event. A qualified event remains activity-only when `exposure_eligible=0`. Eligible events reuse canonical transcript sentence tokens, existing daily replay bounds, and `source_type=LISTENING`; Reader evidence remains distinct. Statistics adds `byPlaybackSource` without double-counting. Existing Goals, Campaigns, and bounded XP reuse the same events with no authenticity bonus. Mistake Intelligence and Cloze gain no replay/reveal error or uncontrolled transcript bank. Phrasebook saving creates no mastery.

## Schema, migration, export, and recovery

Main schema/export advance from v13 to **v14**. Reference schema remains read-only **v3**; no Tier 3 data was ingested. Migration 14 adds `content_items`, `content_artifacts`, `transcripts`, `transcript_cues`, and `sentence_alignments`. SQLite requires a data-preserving rebuild of `listening_sentence_events` to widen its source check and add `coverage_ms`/`alignment_id`; every v13 row is copied with prior `active_ms` as legacy coverage. This is additive in data semantics—no v13 fact or ID is removed.

The verified pre-migration snapshot is `data/backups/language-learning-v13-pre-phase10_5-20260918T085543Z.sqlite`: schema v13, integrity `ok`, zero FK violations. Main v14 is integrity `ok`, zero FK violations. The 4,222,840,832-byte reference v3 database completed a read-only 506.733-second full integrity check with zero FK violations.

`language-learning-export/v14` includes content/transcript/alignment/media metadata but no media bytes. Complete recovery must pair SQLite with the managed media directory. Automatic orphan deletion/restore was deliberately not added.

## Measured performance

An isolated v14 DB, fake offline canonical analyzer, one managed WAV/SRT item, and 100 warm iterations produced these median / p95 service times (ms):

| Operation | Median | p95 |
|---|---:|---:|
| Inbox landing | 2.075 | 3.240 |
| Content detail | 7.905 | 23.809 |
| Coverage preview | 4.948 | 17.078 |
| Transcript load through detail | 7.367 | 20.467 |
| Alignment DB lookup | 1.905 | 6.539 |
| Authentic Listening open | 9.288 | 23.016 |
| Sentence seek in preloaded map | <0.001 | <0.001 |
| Media metadata/file lookup | 2.166 | 4.375 |

A 5,000-cue, 133,892-character synthetic Norwegian SRT parsed in 42.005 ms median / 54.082 ms p95 over ten iterations. Playback loads one bounded alignment map and performs no DB query on timer ticks.

## Verification

Eight new backend tests pass: pasted-text canonical/idempotent intake; audio/SRT/alignment/manual revision/authentic exposure; reference rights/no-fetch/SSRF; Unicode SRT/VTT overlaps/gaps/rejections; media sniffing; cue split/merge/no-invention mapping; size/path/arbitrary-artifact security; and HTTP POST/GET/PATCH/range/origin behavior.

Nine new frontend assertions/tests pass: intake/statuses; coverage/no-CEFR/manual correction; authentic controls/Listening Only/Phrasebook; 5,000-sentence bounded DOM; seek-gap evidence; interval de-duplication; resume/replay start identity; raw/JSON API routes; and route round trips.

- Focused Phase 10.5 + Listening backend: **11/11 passed**.
- Complete Language backend: **227/227 passed**.
- Complete Language frontend/widget: **128/128 passed** across 19 files.
- Phase 10 Listening/browser speech/Cloud audio, Phase 9.5, full Phase 9, Phase 8 generation, Phrasebook/dictionary, curriculum, gamification, reference, and Anki regressions: passed inside the complete suites.
- Broad backend: **715 passed, 1 skipped**, no failures.
- Broad frontend: **868 passed, 2 skipped; 1 unrelated known Finance D.2 assertion failed**. All Language tests passed; Finance was not changed.
- Python compilation, changed-JavaScript syntax, and production Vite build passed; **282 modules transformed**. Existing non-module/chunk warnings remain.
- Main v14, v13 backup, and read-only reference v3: integrity `ok`, zero FK violations.
- Real Edge synthetic assertion smoke: **14/14 passed** at 1440×1000, 430×900, and 390×844, including rights/readiness, Reader/Listening routing, coverage/no CEFR, alignment disclosure, highlight/jump, Listening Only/reveal, Phrasebook, pause/resume, seek-gap evidence, active time, and no overflow.

## Deviations and known limitations

- Forced alignment is the permitted `DEFERRED` outcome. Untimestamped audio remains `NEEDS_TRANSCRIPT`/`NEEDS_ALIGNMENT`; no timing is invented.
- References are intentionally never fetched. NRK/article/podcast/video references require separately supplied authorized local material for Reader/Listening.
- No licensed external storage adapter, paid transcription, or source-transcript retrieval was selected.
- Media deletion/orphan reclamation and packaged media backup/restore remain future reference-aware lifecycle work.
- Edge uses permitted synthetic content and a deterministic fake media element; canonical persistence/exposure is proven at service/HTTP levels.
- The unrelated Finance D.2 assertion remains unchanged.

All applicable Phase 10.5 acceptance criteria pass with documented forced-alignment deferral. Phase 11, CEFR/proficiency, adaptive planning, speaking/writing, pronunciation, dictation, shadowing, and Tier 3 were not started.
