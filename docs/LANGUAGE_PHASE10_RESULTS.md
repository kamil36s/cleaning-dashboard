# Language Dashboard Phase 10 results

Date: 2026-09-18  
Status: **COMPLETE**  
Scope: Listening foundation only. Phase 10.5, Grammar, proficiency/readiness estimation, speaking, and Tier 3 were not started.

## Outcome

Phase 10 adds canonical Listening study for existing analyzed text without replacing either audio system that already existed:

- ordinary Reader text uses device-local browser speech;
- accepted generated Reader text keeps the Phase 8 server-generated, deterministically cached Google Cloud `nb-NO` MP3 path;
- Cloze keeps the Phase 9A Google Cloud path;
- a shared frontend playback coordinator permits only one active browser-speech or Cloud-audio owner.

Listening reuses canonical text sentences, tokens, selected lemma identities, generic `study_sessions`, and generic `exposure_events`. It does not create a second vocabulary store, goal engine, scheduler, or browser audio cache.

## Browser speech adapter

`js/language/audio/browser-speech.js` is dependency-injected for `speechSynthesis`, `SpeechSynthesisUtterance`, and the playback coordinator. Its explicit capability states are:

- `AVAILABLE`;
- `NO_BOKMAL_VOICE`;
- `SPEECH_SYNTHESIS_UNSUPPORTED`;
- `VOICE_LOADING`;
- `ERROR`.

Voice discovery is asynchronous through `voiceschanged`. Selection accepts exact `nb-NO` first and `nb` as a deterministic fallback. It never falls back to Nynorsk (`nn`), Danish, Swedish, or English. A saved compatible voice ID wins; an unavailable preference falls back to the first deterministic compatible voice.

Speech rate is device-local browser state under `language.listening.preferences.v1`, clamped to `0.6`–`1.4` in `0.1` steps. The saved preferences are voice ID, rate, default `READ_LISTEN`/`LISTENING_ONLY` mode, and current-sentence reveal preference. Browser-generated audio is ephemeral and is never uploaded or persisted.

## Playback and modes

The `#listening` library lists analyzed texts and their independent Listening progress. `#listening/text/{id}` provides Play, Pause, Resume, Stop, Replay sentence, Previous, Next, rate, voice, and mode controls. The current sentence has `aria-current`; playback state is announced in a live status region.

`LISTENING_ONLY` keeps controls and status available while suppressing transcript sentences. The learner may reveal only the current sentence; reveal is diagnostic UI metadata and is not a mistake or comprehension result.

`js/language/audio/playback-coordinator.js` coordinates these owners:

- `cloze-cloud`;
- `reader-cloud`;
- `listening-cloud`;
- `listening-browser`.

Activating one cancels the previous owner. Existing generated Reader and Cloze players still use the Phase 8/9A Cloud cache and APIs.

## Canonical activity policy

Policy: `language.listening-activity/v1`.

- Opening a page, choosing Play, requesting Cloud audio, or calling `speechSynthesis.speak()` creates no study evidence.
- A Listening session begins only on the actual browser utterance `start` event or Cloud audio `play()` resolution/playing callback.
- Active milliseconds accumulate only while playback is actually active; explicit pause time is excluded.
- Blur or hidden-tab transitions conservatively cancel active playback.
- A lifecycle produces exactly one `ENDED`, `CANCELLED`, or `ERROR` sentence event, protected by a session-scoped idempotency key.
- Failure before audible start creates neither a Listening session nor an activity event.
- One event is capped at 600,000 active milliseconds; the server rejects invalid types, negative values, pathological duration, cross-profile/text/sentence relationships, closed sessions, and a playback source that does not match the text source.
- The client cannot submit lemma IDs. The server derives any exposure only from the authoritative sentence tokens.

Browser natural end uses actual active time as its observed duration, yielding a complete lifecycle ratio. Cloud audio uses the media duration when available. Cancel and error events have no planned/full duration and can never qualify as complete exposure.

## Exposure policy

Policy: `language.listening-exposure/v1`. Qualification threshold: exactly `0.8`.

An event qualifies only when `outcome=ENDED` and `activeMs / durationMs >= 0.8`. Cancel, error, page open, request start, pause, and replay click do not qualify by themselves.

For a qualifying sentence, the server groups authoritative `WORD` tokens by non-null `selected_lemma_id` and writes generic `exposure_events` with `source_type=LISTENING`. Unresolved/ambiguous tokens with no selected canonical lemma are omitted. Reader exposure rows and counters remain source-filtered as `READER`.

The exposure award is bounded to one per `(profile, text, sentence, Europe/Warsaw local date)`. Replays still create lifecycle events and active time, but cannot farm same-sentence lemma exposure on that date. The bound is enforced by both transactional lookup and a partial unique index.

## Progress and completion

Policy: `language.listening-completion/v1`.

Listening progress is independent from `text_reading_progress`. A sentence is complete after at least one qualifying Listening event. A text is complete after every canonical sentence has qualified at least once. Completion is monotonic, stores its completion timestamp, and resumes from the last meaningful sentence. Completing Listening never completes Reader and vice versa.

In the dedicated Listening route, `READ_LISTEN` means visible transcript plus Listening playback; it records Listening activity only. Navigating away from Reader pauses Reader activity. Statistics expose Reader and Listening times separately. Their displayed modality sum is explicitly labeled non-unique because other future/read-along arrangements may overlap wall-clock time.

Minutes listened are never displayed as comprehension, skill, CEFR, or proficiency.

## Statistics, Goals, Gamification, and campaigns

Statistics policy is `language.statistics/v2`. It exposes actual active milliseconds/seconds/minutes, sessions with activity, distinct qualified sentences, Listening-completed texts, study days, and Listening exposure rows/occurrences. `comprehensionClaim` is always `NONE`.

Goals policy is `language.goals/v2`; the existing Warsaw-local weekly engine now supports:

- `LISTENING_ACTIVE_MINUTES`;
- `LISTENING_SESSIONS`;
- `LISTENING_TEXTS_COMPLETED`.

Page open cannot progress a goal. Existing DST/week behavior is unchanged.

Historical `language.gamification-xp/v1`, the 17-item achievement catalogue, and frozen quest snapshots were not rewritten. Listening uses the separate prospective extension `language.gamification-listening-xp/v1`: 2 XP per completed active minute, capped at the first 20 Listening minutes per Europe/Warsaw day. Stable day/minute award keys make reconciliation idempotent. Replay can contribute actual active time only until the daily cap; cancel/error never earns a completion bonus and there is no negative XP.

Campaign policy `language.gamification-campaigns/v2` adds generic `LISTENING_ACTIVE_MINUTES` and `LISTENING_TEXTS_COMPLETED` milestones. It adds no readiness score. Listening achievements and Listening daily quests were deliberately deferred to avoid rewriting historical catalogues/snapshots.

## LearningPlan, Reviews, Mistake Intelligence, and Anki

LearningPlan policy `language.learning-plan/v6` may add at most one `CONTINUE_LISTENING` item from real unfinished progress. Reviews exposes `LISTENING_PRACTICE` as a dashboard recommendation, explicitly not SRS due work.

Playback, replay, pause, reveal, cancel, and error create no Mistake Intelligence cluster. Phase 10 has activity evidence, not comprehension assessment. Anki scheduling and all Anki evidence are unchanged.

## Settings capability truth

Settings shows browser Bokmål voice, rate, and default mode as **this-browser/device** capability. It does not present browser voice availability as server-global or as Google Cloud status. Existing Google Cloud Reader TTS status remains in the separate server-managed provider card.

## Schema, backup, and export

The additive main schema advances from v12 to v13 and export from `language-learning-export/v12` to `/v13`.

New tables:

- `listening_sessions`, extending canonical `study_sessions` with mode and three policy versions;
- `listening_sentence_events`, storing bounded authoritative lifecycle evidence and qualification outcome;
- `listening_progress`, storing independent, monotonic text progress.

Migration 13 rebuilds only `goal_definitions` to admit the three Listening metrics/`SESSIONS` unit while copying every prior row and retaining historical rule versions. Export/import ordering includes all three Listening tables. No browser audio bytes are stored.

Before migration, the canonical v12 database was backed up to `data/backups/language-learning-v12-20260917T224344878416Z.sqlite`: 1,052,672 bytes, schema 12, `integrity_check=ok`, zero FK violations. A copy migration preserved the sampled common-table row-count map exactly. The canonical database then migrated to schema 13: 39 tables, 1 profile, 40 lemmas, 39 historical gamification awards, `integrity_check=ok`, and zero FK violations.

## API surface

- `GET /api/language/profiles/{profileId}/listening`
- `GET /api/language/texts/{textId}/listening-progress?profileId=...`
- `POST /api/language/texts/{textId}/listening-sessions`
- `POST /api/language/listening-sessions/{sessionId}/sentence-events`
- `PATCH /api/language/listening-sessions/{sessionId}`

All branches are thin dispatch into `LanguageService`. Event writes are one bounded sentence request, not per-token HTTP calls.

## Performance

Warm synthetic medians on the local Windows/Python environment, ten operations each unless the operation necessarily created a fresh row:

| Operation | Median |
|---|---:|
| Listening landing | 2.168 ms |
| Text detail/load | 4.377 ms |
| Session start | 20.223 ms |
| Sentence-event persistence, including reconciliation | 49.255 ms |
| Progress read | 1.924 ms |
| Statistics with Listening | 12.449 ms |
| LearningPlan with Listening | 16.864 ms |
| Gamification summary | 30.905 ms |

Browser speech creates no backend synthesis/storage load. Google Cloud behavior remains only on the pre-existing generated Reader/Cloze paths.

## Tests and browser verification

Five new backend tests cover the HTTP surface plus session/event idempotency, exact 80% qualification, partial/cancel/error behavior, source spoof rejection, daily replay bound, ambiguous-token exclusion, completion/resume facts, Reader separation/read+listen disclosure, Listening Goals, and the 20-minute XP anti-farming cap.

Nine new frontend tests cover unsupported/loading/no-Bokmål states, exact/fallback voice selection, rate bounds, utterance lifecycle, Cloud/browser mutual exclusion, Listening library/detail UI, listening-only/reveal/accessibility, generated Cloud labeling, lazy session start, hidden-tab cancellation, and Listening routes.

Complete Language verification passes 219 backend tests and 119 frontend/widget tests. The focused generated Reader/Cloze Cloud-audio, Phase 9/9.5, generation, curriculum, dictionary/Phrasebook, gamification, reference, and Anki suites remain green. Python compilation, changed-JavaScript syntax, production build, main/reference integrity, and FK checks pass.

Broad backend verification passes 694 tests with 1 skip. Broad frontend verification passes 837 tests with 2 skips and retains one unrelated pre-existing Finance D.2 source-string assertion; all 119 Language frontend/widget tests pass.

Real Microsoft Edge used an isolated synthetic database and disposable browser profile. Edge discovered two genuine `nb-NO` voices, rendered the Listening library/detail, highlighted the current sentence, performed Play/Pause/Resume, completed 2/2 sentences through continuous playback, replayed and stopped a sentence, persisted canonical progress/exposures, and completed a Listening goal. Listening-only reveal worked, and 430 px plus 390 px had no horizontal overflow. Temporary test data/profile were removed.

## Preserved Cloud TTS behavior

Phase 10 does not replace `GeneratedTextAudioService` or `ClozeAudioService`, change Google credentials/configuration, change deterministic cache identity, or synthesize ordinary Reader text on the server. Accepted generated Reader text continues to use the Phase 8 Cloud sentence endpoint/cache. Cloze continues to use its Phase 9A endpoint/cache. The only cross-cutting change is playback coordination so a Cloud player and browser utterance cannot speak simultaneously.

## Limitations and next phase

- Browser voice inventory and speech lifecycle quality are device/browser capabilities; another device may expose different `nb-NO` voices or none.
- Browser speech provides no durable audio artifact or trustworthy word-level timestamps.
- Activity and completion do not measure comprehension.
- Phase 10 has no authentic podcast/audio ingestion, transcripts, forced alignment, dictation, pronunciation, speaking, or Listening mistake assessment.
- Listening achievements and daily quests are deferred to avoid historical policy mutation.

The next roadmap phase is Phase 10.5: authentic content inbox, audio, transcripts, and aligned listening. It was not started.
