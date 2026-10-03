# Phase 10.5 forced-alignment decision

Decision date: 2026-09-18  
Decision: **DEFERRED — `NO_DEFENSIBLE_LOCAL_PROVIDER_SELECTED`**  
Implemented alignment policy: `language.transcript-alignment/v1`  
Implemented segmentation policy: `language.transcript-segmentation/v1`

Phase 10.5 implements source-timestamp and manual sentence alignment. It does not label source timestamps as forced alignment and does not invent timings for untimestamped transcripts.

## Local environment audit

- FFmpeg is installed (`N-117760-gfe18ed3f2a-20241112`) and usable for media decoding.
- OpenAI Whisper `20240930` is installed. Whisper is an ASR/transcription tool; its segment timestamps do not, by themselves, align a supplied canonical transcript defensibly.
- WhisperX, Montreal Forced Aligner (MFA), and aeneas are not installed.
- No locally installed Norwegian speech synthesis voice or checked-in, rights-cleared Norwegian alignment benchmark was available for a repeatable candidate comparison.
- No large model/toolchain was installed merely to satisfy this phase.

## Candidate evaluation

| Candidate | Bokmål path | Offline / Windows | Timing and confidence | Operational/licence assessment | Result |
|---|---|---|---|---|---|
| WhisperX | Its maintained alignment map names `NbAiLab/nb-wav2vec2-1b-bokmaal-v2` for language `no`; aligns a known transcript through a Wav2Vec2 CTC model | Can run locally, but WhisperX and the model are absent; PyTorch/Transformers model footprint and download are substantial | Word/character timings and model scores are possible, but quality still needs a rights-cleared Norwegian benchmark, mismatch tests, CPU latency and confidence calibration | WhisperX project code plus separate model licence/dependency review would be required | Most plausible future spike, not production-selected |
| Montreal Forced Aligner | Can align speech corpora with Kaldi when compatible acoustic model, dictionary/G2P and normalization are available | Local CLI; currently absent; conda/Kaldi/Pynini/OpenFST dependency surface is much heavier than this dashboard | Mature phone/word alignment, adaptable models; confidence/exposure threshold would need local calibration | MFA is MIT, but Norwegian model/dictionary availability and licences were not established for this deployment | Deferred |
| aeneas | Language-independent MFCC/DTW synchronization can align text fragments to narration | Local, but absent; requires FFmpeg plus eSpeak and native components | Designed for fragment synchronization; its own documentation warns that mismatched/spurious audio/text can produce wrong maps and that word alignment may be inferior to ASR aligners | AGPL-3.0 and an older 1.7.3 release increase integration/maintenance risk | Rejected for this production path |
| Installed Whisper alone | Norwegian ASR is available through multilingual models | Installed and offline after model availability | Produces ASR segments, not a trustworthy mapping of the learner's supplied transcript to canonical Stanza sentence boundaries | MIT code, but no calibrated transcript-forcing layer | Not a forced aligner; rejected as a shortcut |

Primary technical sources: [WhisperX alignment implementation and Norwegian model mapping](https://github.com/m-bain/whisperX/blob/main/whisperx/alignment.py), [MFA repository and installation contract](https://github.com/MontrealCorpusTools/Montreal-Forced-Aligner), and [aeneas README, limitations and licence](https://github.com/readbeyond/aeneas/blob/master/README.md).

## Measured result and threshold

No candidate runtime benchmark is claimed. A realistic Norwegian audio/transcript gold fixture was unavailable, and three of the candidate aligners were not installed. Reporting accuracy from synthetic tones, Whisper ASR segment boundaries, or unreviewed media would be misleading. Therefore the forced-alignment result is explicitly **DEFERRED**, which is the allowed Phase 10.5 outcome.

The implemented deterministic source-cue mapper is separately tested for one-cue-to-many-sentences, many-cues-to-one-sentence, Unicode, multiline cues, overlaps, gaps, malformed timestamps, source order, and unaligned sentences. Missing source timestamps produce no alignment row.

## Implemented semantics

- `IMPORTED_SRT` and `IMPORTED_VTT` retain cue IDs and source times.
- Canonical Stanza sentence character spans are intersected with cue text spans. A sentence occupying part of one cue receives a proportional interval; a sentence spanning cues uses the minimum mapped start and maximum mapped end. Gaps and overlaps are retained.
- Confidence is `null` with `CONFIDENCE_NOT_REPORTED`; it is never fabricated.
- `USER_CORRECTED` appends a new alignment version and supersedes the old row. Serialized idempotent refresh does not overwrite it.
- Only current managed-media alignments can back `AUTHENTIC_MEDIA` events. The explicit `exposure_eligible` gate must also pass before canonical `LISTENING` lexical exposure is created.
- Plain transcripts remain Reader-ready/Needs alignment; the UI reports forced alignment as deferred.

## Future selection gate

A future phase may spike WhisperX only after adding a redistributable Norwegian benchmark with reviewed sentence gold times, testing clean speech/noise/music/code-switching/transcript mismatch, measuring CPU/GPU latency and model size on this Windows host, reviewing all model licences, and calibrating a conservative sentence-level confidence threshold. That work is not Phase 11 and was not started here.
