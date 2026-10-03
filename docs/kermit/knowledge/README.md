# Kermit L1 knowledge packs

Status: four historical pilots plus Phase 8 B1 (Cleaning, Reading, Todo) and B2 (Dashboard, Settings, central API/static security). Kermit has a local read-only chat service and dashboard panel; the static index is still rebuilt separately. See `COVERAGE.md` for the current ledger.

An L1 pack is a bounded, source-backed explanation of one implemented subsystem: ownership, user and data flows, storage roles, calculations, failure/recovery, and exact evidence locators. It should answer ordinary "how does this work?" questions without requiring a reader to inspect an entire large source file. It is reviewed prose, not a live observation or a substitute for current code.

`PROJECT_MAP.md` is L0: use it to find the owner, then read the relevant L1 pack. Phase 3 L2 metadata indexes admitted pack entities and relationships; Phase 4 provides bounded on-demand L3 excerpts from admitted code. These packs do not admit private runtime material.

Pilots: `quote`, `finance`, `language-learning`, and `weather`. Phase 8 B1: `cleaning`, `reading`, and `todo`. Phase 8 B2: `dashboard`, `settings`, and `central-api`. The pilots cover a small widget, a SQLite domain, a worker and AI boundary, and a browser integration. B1 adds active page/widget pairs and contrasts two canonical SQLite stores with a file-backed browser mirror. B2 establishes shared widget registration, settings roles and the central application boundary. Ten validated packs do not claim whole-repository coverage; 44 units remain in `COVERAGE.md`.

## Conventions

- Use repository-relative paths and stable locators: `file.py::Class.method`, `file.js::function`, `server.py::GET /api/...`, `index.html::data-widget="..."`, or a test name. A route is identified by method plus path. Avoid copied source bodies.
- Mark consequential claims **verified implementation**, **documented current contract**, **inferred**, **proposed**, **historical/legacy**, or **unknown/conflicted** as defined in `KNOWLEDGE_MODEL.md`. A current code claim is verified by a named symbol/route; tests strengthen but do not override code. No runtime observation was made for these packs.
- Name storage roles: **canonical**, **cache**, **generated**, **raw archive**, **backup**, **migration input**, **legacy**, **browser-only**. `None` means a role does not exist in the scoped flow; `Not applicable` means the concept does not fit; `Not implemented` means a desired feature is absent; `Unknown` means source review did not establish it.
- State each important metric's inputs, filter/window, formula, units, null behavior, and test. If a formula remains unverified, name the gap rather than guessing.
- When source and documentation differ, preserve both and register the discrepancy in `GAPS_AND_CONFLICTS.md`. Historical phase results and plans are not current behavior.

## Maintenance and verification

The verification date and Git revision in each pack describe a source review, not a guarantee that the running dashboard matches the repository. Recheck affected symbols, active schemas, route handlers, and focused tests when a feature changes. Refresh only its pack and gap entries; do not copy L0 inventory wholesale. Follow the deterministic maintenance workflow in `COVERAGE.md`. Sources follow `SOURCE_POLICY.md`: no private database, raw import, archive, backup, secret, or generated data was opened for these packs.

## Pilot evaluation

The template works for the tiny Quote widget and browser-only Weather flow by explicitly saying where backend, job, and canonical-store fields are not applicable. It also holds Finance's separate import, receipt, planning, analytics, and review owners and Language's user DB, reference DB, audio cache, deterministic NLP, generative provider, and worker lifecycle. Repeatedly inapplicable fields are retained as short one-line declarations rather than removed: they prevent a future answer from inventing a backend or store. The pilots exposed a useful field absent from the original list: **authority/claim status by source**, added to the template's Evidence section. Another useful field is **route method and owner**, included in Backend. Sections can become verbose in large domains, so tables and symbol-level citations keep them bounded. With these conventions, L1 scales as independently maintained subsystem packs, though future retrieval should use sections rather than load a whole Finance or Language pack for every question.
