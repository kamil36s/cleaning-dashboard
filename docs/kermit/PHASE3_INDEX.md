# Phase 3 L2 index

Status: implemented offline derived metadata for the four reviewed pilots only. Phase 4 offline retrieval consumes the index; no serving runtime exists.

## Layout and commands

- `kermit_index/admission.json` is the versioned, positive admission manifest. Every admitted path is an explicit entry. Group defaults supply source class, expected role, privacy class, parser mode, content mode, and byte limit; each entry supplies a path and subsystem.
- `kermit_index/schema.json` defines the versioned machine-readable record contract. `kermit_index/finding_sides.json` supplies reviewed categories and exact, admitted side spans for the eight findings. `kermit_index/builder.py` implements inert parsing, path validation, fingerprints, schema validation, and artifact creation. It imports no dashboard modules.
- `tests/test_kermit_index.py` uses synthetic temporary sources and fake secret strings.
- `data/generated/kermit-index/` contains disposable outputs. It is the only production write target. Remove that directory to delete the index, then run `python -m kermit_index build` to recreate it.

From the repository root:

```text
python -B -m kermit_index build
python -B -m kermit_index validate
python -B -m unittest tests.test_kermit_index
```

`-B` prevents Python bytecode caches in source directories. `build` first rejects any missing, oversized, non-UTF-8, binary, unsafe, or non-admitted source. It then writes and validates the generated artifacts. `validate` recomputes from current admitted sources and fails on any changed, missing, or malformed artifact. It never repairs the index. New files remain outside the admission set until a reviewed manifest edit. A deleted admitted file fails closed. For deterministic testing, `--root` selects a synthetic repository with its own manifest and output under `data/generated/kermit-index/`; `--output` cannot redirect writes elsewhere.

## Artifact contract

All core artifacts use schema version 1 and indexer version 1.0.0. JSONL rows are sorted by stable ID; JSON object keys are sorted. Paths inside artifacts are repository-relative. No timestamp is written into core data, so two builds of unchanged bytes are byte-identical. `build.json` records core SHA-256 values and counts and is deterministic too. `report.txt` is a human-readable deterministic build report. These outputs are derived and never authoritative for dashboard behavior.

| Artifact | Contents |
| --- | --- |
| `manifest.json` | Effective admitted source metadata, with no source body |
| `sources.jsonl` | Each admitted path, SHA-256, class, role, privacy, parser/content mode, byte size, subsystem, indexer version, manifest provenance |
| `entities.jsonl` | Versioned typed entities and source references |
| `relationships.jsonl` | Directional typed edges with provenance |
| `documents.jsonl` | Markdown heading units with heading locator, source hash/status, bounded section content, and truncation flag |
| `conflicts.jsonl` | Eight Phase 2 findings with reviewed category, side descriptions and exact admitted source references, original type, impact, blocking status, and register provenance |
| `build.json`, `report.txt` | Deterministic checksums and validation summary |

Entity types: `subsystem`, `page`, `widget`, `module`, `symbol`, `api_operation`, `store`, `data_artifact`, `transformation`, `metric`, `job_worker`, `integration`, `test_contract`, `document`, `conflict`. The schema allows unknown metadata to be absent. Code metadata contains symbol names, line locators, and bounded static imports; no code body, comments, literals, runtime values, or database content is copied. L1 derived concepts are labeled `documented_in_L1`, while source symbols are `current`. An API operation found only in a pack is not upgraded to a verified route. Documentation units preserve reviewed/current/proposed context from their parent evidence; they do not make plans current code.

Relationship types: `owns`, `calls`, `reads`, `writes`, `renders`, `exposes`, `handles`, `imports`, `depends_on`, `generates`, `caches`, `processes`, `tests`, `documents`, `supersedes`, `conflicts_with`. The schema recognizes all of these; this pilot build emits only edges supported by exact L1 path references, HTML `data-widget` attributes, or literal static imports. An unused relationship type is not inferred from a similar filename.

Entity IDs are `{type}:{identity}`. Subsystems use the reviewed pack slug, widgets use their exact `data-widget` key, modules/documents/tests/pages use repository-relative paths, symbols use `path::qualified-name`, API operations use `METHOD:/api/path`, and L1 concepts use `subsystem:normalized-name`. Names are lowercased and punctuation collapses to hyphens for concept keys; colliding concepts from the same section are not duplicated. Relationships use a SHA-256 digest of type, endpoints, and exact evidence locator. IDs never contain absolute paths or source body content.

Every entity, document unit, finding, and edge has at least one `provenance` entry containing admitted source ID, repository-relative path, SHA-256 fingerprint, and locator. Source records point back to their manifest entry. Validation checks versions, duplicates, endpoint existence, source IDs and hashes, allowed privacy classes, artifact byte limits, and exact deterministic recomputation. There is no fuzzy stale fallback: a changed or missing admitted source makes validation fail until rebuild. Index records are never used as a second source of truth.

## Admission and privacy boundary

The initial manifest admits 102 explicit files: L0, current Kermit design and pilot docs, three reviewed supporting docs, and only project-owned code/tests named by the four Quote, Finance, Language Learning, and Weather packs. Shared `index.html`, `server.py`, widget loader, and Vite configuration are admitted for metadata only. Source code is parsed as text or Python AST; no repository code is imported or executed. HTML parsing selects pilot `data-widget` registrations and exact admitted script references only. `server.py` symbol extraction is additionally restricted to Finance/Language names. Private runtime paths named by L1 are conceptual descriptions, not admitted files or fingerprints.

The gate rejects absolute/parent/encoded paths, symlinks and junction escapes, hidden or temporary sources, private/credential paths, logs, backups, SQLite databases and sidecars, generated data, dependencies, media, unknown formats, and over-limit files. The one explicit `js/language/audio/browser-speech.js` source file is allowed as implementation metadata; generated audio remains denied. The ChatGPT history archive is excluded and receives no adapter. Tests seed recognizable fake credentials in denied fixtures and confirm the bytes are absent from every artifact. No application DB, worker, importer, migration, external provider, model, retrieval service, API, or UI is opened or started.

The index is a bounded pilot. Static JavaScript extraction recognizes simple declarations and literal imports; it does not attempt full JavaScript analysis. L1 shorthand routes are not expanded into guessed endpoints. Missing relationships or details stay absent. Phase 4 must review freshness, conflict handling, and evidence selection separately before using these artifacts for retrieval.
