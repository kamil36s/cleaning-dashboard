# Language Learning Phase 3 results

Status: COMPLETE  
Date verified: 2026-09-16  
Database schema version: 2 (unchanged)  
Frontend page: `language.html`

## 1. Outcome

Phase 3 adds the first user-visible Language Learning interface. It is a native Vite multi-page entry with a persistent dashboard-style shell and reload-safe hash routes for a deliberately small truthful Overview, server-paginated Vocabulary, routed lemma detail, and Settings.

The page edits the same canonical `VocabularyLemma` and `LemmaKnowledge` records created in Phases 1 and 2. It does not create browser-side vocabulary persistence. Future navigation items are visibly disabled and no Reader, exposure tracking, dashboard widget, statistics, topic, goal, Anki, AI generation, Cloze, Listening, or Grammar behavior was added.

## 2. Files created

- `language.html`
- `language.css`
- `js/language/app.js`
- `js/language/api.js`
- `js/language/router.js`
- `js/language/state.js`
- `js/language/model.js`
- `js/language/components/dom.js`
- `js/language/components/lemma-detail.js`
- `js/language/views/overview.js`
- `js/language/views/vocabulary.js`
- `js/language/views/settings.js`
- `tests/language-api.test.js`
- `tests/language-router.test.js`
- `tests/language-model.test.js`
- `tests/language-page.test.js`
- `docs/LANGUAGE_PHASE3_RESULTS.md`

## 3. Files modified

- `vite.config.js`: registers `language.html` without changing the production base.
- `index.html`: adds one narrow Language Learning shortcut inside the existing `Czytanie` group.
- `language_learning/store.py`: returns form candidate evidence and lemma frequency evidence, and enriches bounded vocabulary rows with form count, knowledge dates/overrides, and current Zipf metadata.
- `language_learning/service.py`: exposes candidate/frequency evidence and the existing manual mapping-lock operation.
- `server.py`: adds thin GET/PATCH `/api/language/forms/{formId}/mapping` dispatch.
- `tests/test_language_api.py`: verifies candidate evidence, manual locking, validation, and not-found behavior.
- `docs/LANGUAGE_IMPLEMENTATION_PLAN.md`
- `docs/LANGUAGE_RUN_PROGRESS.md`

No migration, table, external provider, dependency, global CSS framework, frontend framework, or second server was introduced.

## 4. Vite, page shell, and routing

The page uses existing relative asset conventions and builds under `base: '/cleaning-dashboard/'`. `dist/language.html` and hashed Language CSS/JS assets are present in production output.

The shell mounts once. Only the main view changes while the sidebar, header, profile summary, API health state, and native dialogs remain mounted. Pure router helpers parse and format:

- `#overview`
- `#vocabulary`
- `#vocabulary/lemma/<lemmaId>`
- `#settings`

The application listens to `hashchange`, so direct loading, refresh, back, and forward all resolve from the URL. Invalid routes replace themselves with `#overview` and leave a visible non-destructive notice. Lemma detail uses a native `<dialog>` while keeping the lemma ID in the route; closing it returns to `#vocabulary`.

## 5. Overview

Overview intentionally shows only current canonical facts:

- selected Bokmål profile, language code, and locale;
- bounded API totals for vocabulary lemmas and saved texts;
- schema and offset contract;
- canonical Stanza analyzer identity and lazy runtime state;
- wordfreq Zipf provider identity/version;
- analysis-worker state;
- links to Vocabulary and Settings plus honest future-state labels.

It does not show streaks, mastery totals, goals, frequency bands, Anki due counts, study time, or any other Phase 5 metric.

## 6. Vocabulary

Vocabulary calls `GET /api/language/profiles/{profileId}/vocabulary` with a limit of 30 and server-owned query parameters. It supports:

- debounced lemma/surface-form search;
- knowledge-status filter;
- disposition filter;
- deterministic backend ordering;
- cursor load-more pagination;
- loading, empty, offline/error, and partial-pagination error states.

Every new query aborts the previous request and increments a request sequence. A stale response therefore cannot overwrite a newer query even if an injected transport ignores abort.

Rows show canonical lemma/POS, knowledge/disposition, recognition/recall/production, linked form count, real exposure total, last-seen date, and Zipf score/provider when present. A missing score renders as unknown, not zero. Zipf is explicitly presented as a score and never as an exact rank or Top-N band.

## 7. Lemma detail, edits, mapping, and merge

Routed lemma detail displays:

- display and normalized lemma, POS, ID, notes, and merge redirect;
- knowledge status, disposition, 0–5/null scores, exposures, dates, and manual override flags;
- linked forms, normalization, morphology, analyzer/provider/version, ambiguity/lexical states, nullable confidence, and all current candidate mappings;
- explicit analyzer-selected, ambiguous, unresolved, and manual-lock labels;
- stored Zipf evidence including provider/version, lookup value, match basis, and the explicit absence of exact rank;
- recent knowledge-event summaries.

Knowledge and notes are PATCHed through the existing canonical lemma endpoint. The UI waits for the accepted server response and rebuilds the detail from that response; rejected validation is shown inline.

Phase 1 already had `lock_form_lemma_mapping`, but no HTTP route could call it. Phase 3 adds the smallest thin route required: GET reads one form's candidates and PATCH manually locks a selected same-profile lemma. The service/database invariants still enforce profile ownership and manual precedence.

Merge is available only after searching for an existing target. A separate native confirmation dialog shows source and target, requires an explicit checkbox, reports server errors, and routes to the resulting target lemma after success. No automatic merge suggestions were added.

## 8. Settings and health semantics

Settings allows only the profile fields already supported by the backend: display name and ordered translation-locale preferences. Language code, locale, and profile status are shown read-only.

Analyzer state distinguishes ready, lazy/not loaded, unavailable, and error-like conditions. Frequency identifies wordfreq/version and its Zipf-only role. Dictionary, translation provider, CEFR, and exact ranked frequency are calm `Not configured` states. Anki and AI are `Not implemented yet`; Phase 3 performs no probe or write.

Opening Overview, Vocabulary, Settings, and direct lemma detail left the real health endpoint at `LAZY_NOT_CREATED`. No frontend read route loads Stanza or downloads a model.

## 9. Unicode offset utility and safe rendering

`js/language/model.js` provides the single canonical browser boundary:

- `codePointOffsetToUtf16Index(text, offset)`
- `codePointRangeToUtf16Range(text, start, end)`

Tests cover ASCII, `æøå`, one and multiple emoji, another non-BMP character, empty/range/end boundaries, and invalid offsets.

Production Language modules contain no `innerHTML`, `outerHTML`, localStorage, or sessionStorage use. DOM nodes and `textContent` render profile, lemma, form, provider, note, and error strings. Tests pass literal `<script>` and `<img onerror>`-like values and verify that no executable elements are created.

## 10. Accessibility

- Functional navigation uses links and `aria-current="page"`; future items are disabled buttons.
- Filters and edits use native labeled inputs/selects/textareas.
- Lemma and merge surfaces use native dialogs with Escape behavior; the merge dialog explicitly focuses its confirmation control.
- Actions are real buttons, table headers use scopes, and loading/status/error text uses live regions where useful.
- Visible `:focus-visible` treatment is scoped to the Language page.
- Status is not communicated by color alone.

## 11. Visual and manual verification

Real Edge headless rendering was inspected at:

- 1440 × 1000: canonical Overview;
- 1440 × 1000: canonical empty Vocabulary;
- 1440 × 1000: isolated temporary populated Vocabulary;
- 1440 × 1000: routed lemma dialog with `menneskerettighetsorganisasjon` / `menneskerettighetsorganisasjonen`;
- 430 × 900: Settings and responsive shell.

The page follows the existing dark palette, tokens, borders, radii, compact sidebar, table density, native dialogs, and button conventions. Long Norwegian words wrap without horizontal page overflow. The temporary populated visual server used a temporary SQLite file and was stopped after inspection; canonical personal data was not mutated.

## 12. Tests and build

New frontend tests:

| File | Result |
| --- | ---: |
| `tests/language-api.test.js` | 4 passed |
| `tests/language-router.test.js` | 8 passed |
| `tests/language-model.test.js` | 10 passed |
| `tests/language-page.test.js` | 14 passed |
| **New Phase 3 frontend total** | **36 passed** |

Full verification:

| Command/check | Exact result |
| --- | --- |
| focused Phase 3 frontend suite | 36 passed, 0 failed |
| focused Language API suite | 13 passed, 0 failed |
| complete Language backend suite | 78 passed, 0 failed |
| real persisted Stanza integration | passed; provisioned offline pipeline reused, download/network paths blocked |
| focused Language plus dashboard UI regressions | 78 passed, 0 failed across 11 Vitest files |
| `npm run test:run` | 664 passed, 2 skipped, 0 failed |
| `python -m unittest discover -s tests -p "test_*.py" -v` | 426 passed, 1 skipped, 0 failed |
| `npm run build` | passed; `dist/language.html` present; existing warnings only |
| Language JavaScript syntax check | 10 files passed |
| Python compilation | Language store/service and `server.py` passed |
| canonical database | schema v2; 15 tables; `integrity_check = ok`; zero FK violations |
| post-page analyzer health | `LAZY_NOT_CREATED` |

The known Stanza-adjacent `requests` dependency warning and existing Vite large-chunk/non-module warnings remain unchanged and non-failing.

## 13. Dashboard regression

The main Vite page returned HTTP 200. Static/runtime checks confirmed the new `./language.html#overview` shortcut and preserved:

- Todo widget markup and focused rendering test;
- separate Sensors/temperature and Habits widget identities and focused rendering tests;
- AI Usage Details link and widget tests;
- Event Countdown filter controls and 18 focused tests;
- Kitchen entry/link unchanged by Phase 3.

No dashboard widget registry, widget order, dashboard settings, Kitchen page, or global Language styles were added or changed.

## 14. Deviations and known limitations

- One thin GET/PATCH form-mapping route was required because the service operation existed but was not externally reachable. This is additive and introduced no persistence change.
- Lemma detail returns candidate and frequency evidence additively, and vocabulary rows return form/frequency/date fields already stored in schema v2.
- The canonical database had zero vocabulary rows during visual verification, so populated-list/detail inspection used an isolated temporary schema-v2 database.
- Vocabulary sorting remains the Phase 1 deterministic normalized-lemma order; the backend exposes no alternate sort contract yet.
- Definitions, translations, CEFR, exact ranks/bands, senses, and richer lexical reference content remain unavailable because no verified provider has been selected.
- There is no Reader, session/exposure command UI, text import UI, reanalysis UI, or analytics. These omissions are intentional phase boundaries.

## 15. Acceptance and exact Phase 4 recommendation

All 29 Phase 3 acceptance criteria passed. Phase 3 is complete.

Proceed with **Phase 4 only**: add the Reader vertical slice over existing text/job/detail endpoints, render exact original text through the tested code-point-to-UTF-16 boundary, reuse this canonical lemma detail, show versioned raw coverage, and add conservative idempotent study-session/exposure commands with active-time handling and history. Preserve manual locks and define historical token/reanalysis behavior before exposing reanalysis for studied documents.

Do not add the Phase 5 widget/statistics/topics/goals, Anki, AI generation, Cloze, Listening, or Grammar as part of Phase 4.
