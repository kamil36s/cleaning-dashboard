# Language Learning operations

This guide covers the local personal Bokmål subsystem at main schema v17 and read-only reference schema v3. Run commands from the repository root. Stop the local API before replacing any production files. The Phase 12 package is an **operational SQLite and media recovery package**; `GET /api/language/export` is a portable logical JSON export and does not contain media bytes.

## System data inventory

| Resource and owner | Actual path | User-critical | Rebuildable | Ordinary package | Restore and validation |
| --- | --- | --- | --- | --- | --- |
| Main `LanguageStore` | `data/language-learning.sqlite` (WAL/SHM sidecars at runtime) | Yes | No | SQLite backup API snapshot | Restore as `data/language-learning.sqlite`; check schema, integrity, foreign keys, and service reads. Includes VocabularyLemma/forms, knowledge/events, Reader, Topics, Goals, Anki links/snapshots/sync, generation, Cloze/mistakes, XP/achievements/campaigns/quests, dictionary edits, Phrasebook, Listening, Inbox metadata/transcripts/cues/alignments, Grammar and Benchmarks. |
| Content Inbox managed audio, `ContentInboxService` | `data/language-learning/media/<artifact-id>.<audio-extension>` | Yes | No | DB-referenced files only | Restore at the same relative names; reconcile `content_artifacts` ID, size, and `sha256:` checksum; resolve via `/api/language/content/media/{id}`. |
| Cloud-generated Cloze/Reader MP3, `ClozeAudioService` | `data/audio/language-learning/nb/cloze/` and `nb/generated/` | No | Yes, if Cloud TTS can be reprovisioned | No | Existing `cloze_sentence_audio.audio_path` metadata may point to absent cache. A later explicit audio request regenerates it if Google TTS is available. Missing cache is an unavailable audio state, not a study event. |
| Reference facts, `ReferenceStore` | `data/reference/language-reference-nb.sqlite`; override `LANGUAGE_REFERENCE_DB` | No | Yes, from frozen source manifests and acquired source artifacts | No | Rebuild with `scripts/build_language_reference.py`; verify schema v3 and source fingerprint. Reference-dependent Cloze, dictionary/curriculum enrichment can be unavailable while local knowledge remains readable. |
| Acquired reference source artifacts and build outputs | `data/reference/sources/`, `processed/`, `reports/` | No | Yes, subject to source availability/licensing | No | Reacquire/rebuild using frozen manifests and `scripts/build_language_reference.py`; inspect source license and artifact checksums. |
| Stanza canonical and optional dependency models | `LANGUAGE_STANZA_MODEL_DIR` or `STANZA_RESOURCES_DIR`, otherwise Stanza's versioned user cache outside the repo | No | Yes | No | Explicitly provision `nb` tokenize/pos/lemma and optional `depparse`; run `scripts/diagnose_language_env.py` and the Grammar setup check. Runtime never downloads models. |
| Static benchmark answer key | `language_learning/benchmark_content/v1.json` | No | Tracked with code | Hash only | Preserve the exact version/fingerprint needed by active/historical benchmark runs; never serve directly to browser. |
| Curriculum manifests/catalog | `language_learning/curriculum_packs/*.json` | No | Tracked with code | Hash only | Restore compatible repository version; validate with `scripts/validate_language_curricula.py`. |
| Migration snapshots / old DB-only backup endpoint | `data/backups/language-learning-*.sqlite` | Safety copies | No for those snapshots | No | Preserve separately. They lack Inbox media and are not a complete Phase 12 recovery package. |

Original arbitrary client filesystem paths and external reference URLs are metadata, never copied. Study Session Builder has no durable plan history. Content Inbox transcripts, transcript cues, alignments, provider generation candidates, and benchmark responses are SQLite rows, not separate files.

## Backup, validation, and preview

```powershell
python scripts/language_backup.py backup
python scripts/language_backup.py validate data/backups/<package-directory>
python scripts/language_backup.py preview data/backups/<package-directory> C:/safe/empty-language-restore
```

`backup` creates a unique `language-<UTC timestamp>-<random>` directory under `data/backups/` by default. `--db`, `--output`, `--project-root`, and `--reference-db` support isolated recovery checks. It refuses source schema other than v17 and does not overwrite another package. It reads the live SQLite source using the backup API, so committed WAL state is included. It checks `PRAGMA integrity_check`, `PRAGMA foreign_key_check`, and migration version on the snapshot. It copies only `content_artifacts` rows under the owned media root, rejects escaping symlinks and malformed paths, checks each source and copied file against DB size/checksum, and validates the finished package. Failed creation removes its own incomplete directory.

Operational cadence is explicit: make and validate a package before any future migration, bulk import, or risky maintenance and at least weekly during active study. Retain at least four recent weekly packages and three monthly checkpoints in a private location outside the web root, with one independent copy outside this computer. Review old packages manually before removal; the CLI never rotates or deletes completed packages. Store credentials for reprovisioning separately from the backup. A package is only a usable recovery point after `validate` passes and its dependency warnings are understood.

The `language-backup/v1` manifest records creation time, v17 main schema, `language-learning-export/v17`, fixed DB filename/size/SHA-256, each managed artifact ID/path/size/SHA-256, reference schema v3 and source fingerprint, installed Stanza package and required resource version/processors, and hashes of benchmark plus every curriculum JSON. The manifest contains no provider key, credentials path, or source filesystem path. A backup with no Inbox audio has an empty artifact list. The 4.2 GB reference DB and Stanza models are not duplicated.

`validate` is read-only. Packaged SQLite is opened with `immutable=1`, so validation creates no WAL/SHM files. It rejects unsupported format/schema, missing/tampered DB or required media, unsafe/duplicate paths, DB/manifest mismatch, broken integrity/FKs, static contract mismatch, and symlinks. `VALID_WITH_WARNINGS` means optional reference or Stanza provisioning is missing/different, or extra unreferenced files are present. Duplicate content hashes under different valid artifact IDs are allowed; identity is the artifact ID and relative filename. Extra files are warned about and never copied. A changed manifest is detected when it conflicts with the DB, artifact hashes, format, or static contracts; the package has checksums for accidental corruption, not a digital signature against an attacker who can rewrite every file and manifest together.

`preview` additionally checks that the target is empty and reports schema, format, artifact count, reference/analyzer dependency, warnings/errors, and the planned staged operations. It does not create the target. A missing reference DB is a warning because local user facts remain usable; reproduce the recorded source fingerprint before using reference-dependent features. A changed benchmark/curriculum contract is an error because pinned historical content must remain available.

## Clean restore and production recovery

```powershell
python scripts/language_backup.py restore data/backups/<package-directory> C:/safe/empty-language-restore
```

Only an empty, nonproduction destination is accepted. Restore validates first, creates a sibling staging directory, copies the SQLite snapshot and DB-referenced Inbox audio into `data/`, verifies DB integrity/FKs/media hashes, initializes the normal `LanguageStore` at v17, then publishes the staged directory. The source package is never migrated or edited. Supported restore range is exactly main v17 and format v1; newer or older versions fail explicitly. There is no production overwrite flag.

To recover production: stop the API and any jobs; preserve the old `data/language-learning.sqlite` plus its WAL/SHM and `data/language-learning/media/` as a separate safety copy; validate and clean-restore into a separate directory; verify local service reads and required media; confirm the recorded reference/static/Stanza dependencies; then manually move the restored DB and managed media into place while the API remains stopped. Keep the old files until restart, integrity, and representative reads pass. Do not merge individual SQLite/WAL files or copy a live SQLite main file by hand.

The old `LanguageStore.backup_database()` and `/api/language/backup` create a DB-only safety snapshot. Use the Phase 12 CLI for operational disaster recovery.

## Reference and model reprovisioning

The reference fingerprint is a SHA-256 of its migration ledger, registered source/version rows, and source artifact checksum/parser rows. It is a logical source fingerprint, not a hash of the 4.2 GB DB file. Rebuild with `python scripts/build_language_reference.py` using the frozen manifests and acquired sources; `--verify-only` runs the full reference verification when needed. The reference DB must remain read-only schema v3 at runtime. No Tier 3 ingestion is part of recovery.

Canonical Stanza requires the Bokmål packages in `language_learning/analysis/norwegian_bokmal.py`. Optional Grammar additionally requires `depparse=bokmaal_charlm` as documented in `docs/LANGUAGE_GRAMMAR_SETUP.md`. Set `LANGUAGE_STANZA_MODEL_DIR` if using a nondefault cache, provision explicitly, then run `python scripts/diagnose_language_env.py`. Runtime uses `DownloadMethod.NONE`; unavailable models give an explicit health/job error without network installation. Grammar model memory is paid only on explicit Grammar analysis; normal Reader navigation does not construct its dependency pipeline.

## Providers, privacy, and degraded operation

Gemini is optional and configured server-side with `LANGUAGE_GEMINI_*` and `GEMINI_API_KEY`. Explicit automatic generation sends the bounded frozen prompt/context pack; ordinary local study does not. Google Cloud TTS uses server-side ADC/project and receives a requested sentence for explicit audio generation. The Ordbøkene live dictionary receives lookup terms; its failure does not erase local user translations or knowledge. AnkiConnect is loopback-only; the optional key is server-side, and due/snapshot reads depend on a local Anki instance. Browser Bokmål speech is device-local and may lack a compatible voice. A missing provider/model/reference/media item must show unavailable/failure, never fabricate exposure, completion, score, or XP.

### Anki and Reader workflow

AnkiDroid syncs its collection with AnkiWeb. The dashboard's local AnkiConnect endpoint talks to Anki Desktop on the same PC. With Anki Desktop open and both phone and Desktop signed into the same AnkiWeb account, the dashboard syncs Desktop with AnkiWeb every five minutes while the main dashboard or Language page is open. A phone review appears after AnkiDroid uploads it and the PC performs its next sync. The AnkiDroid API switch only permits apps on that Android device to use its local API; it is not a network endpoint for the PC.

Language Reviews shows the selected Norwegian A1 deck and any Reader Story decks, including daily New/Learning/Review counts, a 30-day answer history, a 14-day review forecast, and a searchable card catalog. Forecast numbers assume no later answers. For a simple card whose front is one word or a Norwegian article plus one word, the versioned estimate uses the most recent Anki ratings and card interval to update the corresponding Reader Vocabulary lemma. Ambiguous or sentence cards are not linked to a lemma. Explicit Reader knowledge wins over this estimate. A Reader status change adds `dashboard_status_*` tags to safely matched Anki notes; it does not change Anki intervals, due dates, or answer history. If Anki is offline, the tags are reconciled at the next dashboard initiated AnkiWeb sync.

The Reader can translate one selected Norwegian sentence into English or Polish. It first tries configured Google Cloud Translation, then the public MyMemory service, then a bounded Google Translate public endpoint when the other providers are unavailable. The selected sentence is sent to the provider and its result is cached in the Language database. Public translations are best-effort, subject to a 500-byte sentence limit and provider quota. Generated Reader stories can be previewed as three Anki subdecks (words, phrases, sentences with audio); the word/phrase text and English translations can be corrected in the preview, while exact Reader sentences stay fixed to match their audio. Creating the deck requires a click after preview, uses Basic notes, skips duplicate fronts and then requests AnkiWeb sync. With Anki's default Deck new-card gather order, selecting the parent deck presents the numbered subdecks in order; users who changed this setting should select the subdecks in order. Machine translations should be reviewed before creation.

The operational backup contains private text, notes, study and benchmark history, Anki links, Inbox metadata and owned audio. Store it outside web roots with private filesystem permissions and an independent copy. The API's JSON export also contains private logical history but no audio. No new cloud sync or outbound telemetry is part of Phase 12.

Python static serving denies database files/sidecars, backup directories, `data/reference/`, managed Inbox and generated audio roots, benchmark answer keys, Python files, and env files. Vite dev/preview has matching Language private-path denial. Managed Inbox files resolve only by DB artifact ID through their API endpoint; neither backup input paths nor raw media paths are accepted as static URLs. Language writes use the existing same-origin authorization and bounded payload parsing.

## Jobs, integrity, and troubleshooting

`LanguageJobManager.initialize()` requeues recoverable queued/running text and Grammar work up to the configured attempt limit; cancelled work stays cancelled and exhausted work fails with durable error state. Automatic generation and candidate recovery use their existing separate store paths. Worker cancellation and commit checks prevent shutdown work from silently recording a new authoritative result. Inspect `/api/language/health` and the persisted job row when a job is stuck; retry through the normal API after fixing its dependency. Never edit the job table by hand.

Read-only checks:

```powershell
python -c "import sqlite3; c=sqlite3.connect('file:data/language-learning.sqlite?mode=ro',uri=True); print(c.execute('pragma integrity_check').fetchone()); print(c.execute('pragma foreign_key_check').fetchall()); c.close()"
python scripts/language_backup.py validate data/backups/<package-directory>
python scripts/benchmark_language_operations.py
```

For reference integrity, use the established `python scripts/build_language_reference.py --verify-only` procedure sparingly: full integrity scans of the large reference DB can take minutes. If a package fails validation, keep it unchanged, inspect the first explicit error, and create a new backup from a healthy source. If a media item is missing, restore the matching artifact from a valid package by clean recovery; do not invent a successful listening event. If the main DB cannot open, stop the service and use a validated clean restore; no destructive auto-repair is attempted.

## Performance baseline and accessibility

Run `python scripts/benchmark_language_operations.py` for a temporary generated personal-scale fixture; it never reads personal content or writes production data. Phase 12 measurements and remaining limits are in `LANGUAGE_PHASE12_RESULTS.md`. Normal browsing keeps the Grammar parser lazy. UI status uses native controls, visible text/labels, and error states; existing desktop and 430/390 px Edge smoke scripts cover route layout. Generated audio, the full reference DB, and Python models are excluded from the ordinary package by the resource inventory above.
