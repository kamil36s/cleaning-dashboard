# Phase 12 — Operational Hardening results

Status: **COMPLETE (2026-09-25)**. Internal 12A backup/restore, 12B measured performance, and 12C security/degraded operation are complete. Main schema/export remain v16; the reference schema remains read-only v3. No migration or Tier 3 ingestion occurred. The recovery commands and durable-resource inventory are in [LANGUAGE_OPERATIONS.md](./LANGUAGE_OPERATIONS.md).

## 12A — Recovery contract and rehearsal

`language-backup/v1` packages use the SQLite backup API against a read-only live connection, including committed WAL state. The fixed `language-learning.sqlite` snapshot is checked with `PRAGMA integrity_check`, `foreign_key_check`, schema v16, size and SHA-256. The manifest records the export version, creation time, DB digest, each DB-owned Inbox artifact ID/name/size/digest, the reference v3 source fingerprint, Stanza package/resource contract, and hashes of the benchmark answer key and all curriculum manifests. The package copies only referenced files under `data/language-learning/media/`; transcripts, cues, alignments, knowledge, goals, gamification, listening, grammar, benchmark responses, and Anki state are SQLite rows. It excludes the 4.2 GB reference DB, acquired reference sources, Stanza models, generated audio caches, external URLs, and credentials. These excluded resources have explicit reprovisioning or regeneration policies in the operations guide.

Validation is read-only, opens the package DB with SQLite `immutable=1`, rejects unsupported formats/schemas, corruption, missing/tampered media, DB/manifest disagreement, unsafe or duplicate paths, symlinks and changed pinned static contracts. An optional dependency mismatch or unreferenced extra file produces `VALID_WITH_WARNINGS`; missing required media is `INVALID`. Duplicate bytes under different valid artifact IDs are permitted. Checksums detect accidental damage but do not authenticate a package against an attacker who can replace every file and its manifest. Preview reports the planned operations and refuses a nonempty target without changing it. Restore validates, stages beside the target, copies and rechecks the DB/media, initializes the normal v16 store, then publishes to an empty destination. No production overwrite command or in-place backup migration exists. The existing JSON export and DB-only backup endpoint remain distinct from the operational package.

The isolated recovery test kept a write in WAL, backed up a source with Vocabulary, knowledge, Topics, a Goal, Phrasebook, a campaign, a benchmark response, and owned audio with transcript/cue/alignment. The source export was unchanged after backup; package files and filenames were unchanged after repeated validation; restored export data matched exactly, media resolved by artifact ID, and the restored DB passed integrity/FK checks. The expanded synthetic performance fixture additionally restored **every exported durable table** byte-for-byte at the logical row level, including Reader, Listening, Grammar, benchmark history, campaign, and Inbox metadata. Its managed WAV was reconciled. Production-source packages created in the system temp directory and in the normal `data/backups/` directory both validated `VALID` with main v16, reference v3 fingerprint `15ee689730746379d171e55ac45f51f44e4daee8da7fcefce1dc497e383f5c03`, Stanza 1.14.0, and zero owned media artifacts. The retained local package is `data/backups/language-20260924T221904600655Z-cfbcb30e/`. No production restore was attempted.

## 12B — Measurements and changes

The reproducible command is `python scripts/benchmark_language_operations.py`. The final temporary fixture had 2,000 lemmas, 6,000 knowledge events, 100 Reader texts/sentences, 2,000 tokens, 100 Reader sessions, 1,000 exposures, 30 Listening sessions/events, 40 Grammar occurrences, 100 Phrasebook entries, 51 Inbox items including one owned WAV, one campaign, 50 prior Cloze attempts, 321 derived XP awards, and 40 completed benchmark runs with 640 responses. It used the real read-only v3 reference DB for indexed lookups. No private user content was put in the fixture. Results below are local in-process wall times in milliseconds, three samples per read unless marked once; they are not browser/network latency promises. The script records median and maximum for each read.

| Operation | Final median ms | Operation | Final median ms |
| --- | ---: | --- | ---: |
| Vocabulary search | 5.80 | Lemma detail | 2.36 |
| Reader library | 18.76 | Reader text | 5.92 |
| Reader progress/history | 2.68 | Cloze tracks | 375.29 |
| Listening library | 6.89 | Listening progress / detail | 2.17 / 5.85 |
| Inbox landing / detail | 4.15 / 25.59 | Owned media metadata | 2.34 |
| Grammar landing / pattern | 13.64 / 12.55 | Benchmarks landing / results | 4.48 / 2.02 |
| Norway preparation | 4.56 | Statistics / Overview | 152.29 / 310.78 |
| Goals | 1.98 | Gamification / Progress | 736.72 |
| Curriculum landing / detail | 3.16 / 2.52 | Phrasebook | 3.21 |
| Anki local status / snapshot | 4.03 / 2.00 | Study Session 10 / 20 / 30 min | 159.08 / 158.22 / 152.98 |
| Reference targets / sentence batch | 12.46 / 62.30 | Shared Review 50 | 110.87 |
| Fast Track 50 | 3,020.01 | Backup / validate / restore, once | 195.88 / 78.79 / 768.97 |

The old Fast Track 50 versus shared Review 50 discrepancy remains measurable: 3,020 versus 111 ms in the final repeat-session fixture. A controlled old/new code comparison on separate fresh databases gave Fast Track 50 **4,993 ms before** (4,807 and 5,179 ms) and **4,403 ms after** (4,339 and 4,468 ms). We found 50 repeated SQLite suppression reads and repeated known-key construction during sentence selection; both now happen once per session. The same deterministic 50 items were selected in the comparison, and the new query-budget test requires one suppression read. The residual cost is reference sentence/occurrence selection and bounded distractor construction over the large reference store; it remains a measured latency limit. We did not add a persistent cache, rollup, index, reference mutation, or altered scoring without a safe measured case.

The Reader library formerly made one coverage read per text. Batching page coverage reduced the 100-text median from 127.5 to 16.4 ms on the initial paired fixture; the expanded final fixture measured 18.76 ms. The Progress collections path scanned all five reference bands separately. Sharing one ranked-target and playable-target scan reduced its paired median from 1,531 to 625 ms; the expanded final fixture with Cloze/XP history measured 736.72 ms. Query-budget tests lock down these changes and compare Reader coverage values. Study Session, Statistics, Overview, Grammar, benchmark history, and reference lookup costs were measured, with no speculative changes. All page reads stay bounded by their existing owner limits. Grammar dependency parsing is intentionally lazy and carries the largest optional model memory cost; ordinary navigation did not initialize it in the existing lazy-registry/parser tests. No reliable process peak-memory benchmark was collected, so memory figures are not claimed.

## 12C — Failures, boundaries, and usability

| Failure or audit area | Verified behavior and evidence |
| --- | --- |
| Canonical analyzer, Grammar parser, interrupted jobs | Existing analyzer/Grammar/job tests cover missing models, no runtime download, queued/running restart recovery, cancellation, stale-preview rejection, failed commits and no fabricated analysis/evidence. The new degraded test confirms Grammar unavailable while Reader/lemma/Study Session remain readable. |
| Gemini absent, quota/rate/network/provider error | Existing provider/automatic-loop tests cover explicit states, bounded retries, no false accepted content, and redacted health. Local content remains stored and readable. |
| Dictionary and Anki unavailable | Existing provider/Anki tests cover explicit failures, local knowledge ownership and loopback-only Anki configuration. The degraded test confirms Anki `NOT_CONFIGURED` while local study still works. |
| Browser and Google TTS unavailable | Existing Reader/Listening/Cloze frontend and Cloud TTS tests cover unavailable voice/provider states, preserved text/session state, and no false listening evidence; missing generated cache can regenerate on an explicit request. |
| Reference missing, wrong version, corrupt | New tests independently confirm local Reader/Vocabulary survive and Cloze reports unavailable/unsupported. The Cloze v3 health check now rejects a future schema instead of treating it as ready. No reference file is created on a missing read. |
| Owned media missing, bad artifact and backup input | A missing owned file produces an explicit media error while another Inbox item and Reader work. Existing Inbox tests reject invalid external sources. New package tests reject missing/tampered media, path traversal, absolute paths, duplicate entries, unsafe DB metadata, unsupported versions, and nonempty restore destinations. |
| API writes, raw static paths and secrets | Nine representative writes across knowledge, Reader, Cloze, Listening, uploads, Grammar, benchmarks, Anki, and backup API reject a foreign Origin. Python and Vite dev/preview block DBs and sidecars, backups/manifest, reference files, owned/generated audio roots, answer keys, Python and env files. Secrets are absent from tested health/export payloads; provider keys/config remain server-side. Existing API tests cover payload limits and error redaction. |
| User/provider HTML and privacy | Existing Reader, dictionary, Phrasebook, Inbox, Grammar, benchmark and Study Session rendering tests use text-safe rendering and hostile-string cases. The operations guide records local data and explicit outbound provider payload boundaries; the package contains private state and must be stored privately. |

The HTTP audit found established bounded JSON parsing: Grammar review and benchmark responses are each limited to 4 KiB; generation and bulk routes have their existing route-specific limits; Inbox audio is limited to 64 MiB and transcripts to 2 MiB in the owner service. No limit was relaxed. The backup CLI has no HTTP restore endpoint. Main DB/open or migration failures remain explicit errors with no destructive auto-repair; recovery is a validated clean restore. The inherited job and provider tests cover the applicable restart and failure behavior, while the new tests focus on cross-feature isolation and the new package/static boundaries.

Real headless Edge against an isolated Python API and synthetic state rendered Overview, Reader, Vocabulary, Reviews, Cloze, Listening, Inbox, Grammar, Benchmarks and Study Session at **1440×1000, 430×900 and 390×844**. Each route had content and no horizontal overflow; a sidebar link received keyboard focus with reduced-motion media enabled. Cloze was deliberately unavailable in this fixture (HTTP 409) and its route still rendered. Existing Language frontend tests cover native controls, unavailable/status text, unsafe text, and stale UI responses. This is a bounded accessibility smoke, not a full assistive-technology audit.

## Verification

| Gate | Result |
| --- | --- |
| New focused backend | 13 tests passed, 1 skipped (Windows file symlink creation unavailable); includes backup, performance, security, degraded operation. |
| New Vite privacy frontend | 11 tests passed; existing Finance privacy tests also passed. |
| Complete Language backend | Final uncontended run: 274 tests, 273 passed, 1 skipped. |
| Complete Language frontend/widget | 161 passed across 23 files. |
| Broad backend | 952 run: 945 passed, 7 skipped, before the final two focused backend cases. |
| Broad frontend | 1,045 passed, 2 skipped, 1 unchanged Finance D.2 failure in `tests/finance-pack-d2.test.js:108`; no Language failure and no Finance edit. |
| Build and syntax | 325-module production build passed; changed Python compiled and changed JS passed `node --check`. |
| Production data | Main v16 `integrity_check=ok`, zero FK violations; reference v3 `integrity_check=ok`, zero FK violations (4,222,840,832 bytes, full read-only scan ~414 seconds). |
| Recovery and performance | Retained local production-source backup `VALID`; isolated owned-media restore `RESTORED` with exact logical export equality; expanded performance smoke completed with all named surfaces. |
| Edge | Ten routes passed at each of the three viewport sizes with synthetic data. |

The final two backend cases (unsafe DB media metadata/occupied target and future/corrupt reference) were added after the broad run and passed both focused and in the final complete Language run. A concurrent verification attempt timed out in a Cloze HTTP test while the real-reference performance benchmark was running; the uncontended rerun above passed. No optional future extension was started. The remaining measured limit is Fast Track latency; the only broad-suite failure is the pre-existing unrelated Finance assertion.
