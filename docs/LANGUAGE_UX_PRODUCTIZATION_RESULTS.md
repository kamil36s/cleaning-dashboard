# Language Learning productization, V1

## Purpose and previous state

The Phase 12 feature set worked, but the learner entry point was a dense Overview of system facts. The sidebar was flat, the dashboard widget was hidden by default, and Reader word clicks opened the large technical lemma dialog. Generation, grammar, settings, and several empty states presented operational details before the next useful learner action. This pass makes existing capabilities easier to start and use. The completed Phase 0–12 roadmap remains complete.

## Information architecture and Today

The existing `#overview` route now displays **Today**. The sidebar groups existing hashes under Today, Practice, Library, Tools, Insights, and Settings. A collapsed **Browse sections** control keeps the learner action visible on narrow screens. The header has route-specific **How this works** help. Direct links, reloads, and browser history retain their existing routes.

Today starts with a 10/20/30 minute choice and one action. It previews the existing Study Session Builder result and reuses that plan when opening Study Session. The builder can shorten a plan when work is unavailable. Daily Core shows three separate owners:

- **Anki:** persisted due count at last sync, with an explicit stale indicator; no live probe on Today or the dashboard widget. Anki remains the scheduler.
- **Cloze:** a suggested practice length and attempts today. The number is a suggestion; questions are checked when starting, and it is never labeled due.
- **Reader:** the most recent in-progress text or an available analyzed text, with an explicit continue action.

The first-use Start Here area links to a source text and initial practice. Its dismissal is a disposable local browser preference. Today shows a small activity summary after the actions, followed by secondary links. The dashboard Language widget uses the same bounded `language.today-summary/v1` data, shows the three owners, streak/XP, and a study CTA. It is enabled in default widget settings while existing saved visibility preferences continue to win.

## Reader and shared lexical interaction

Reader preserves exact source text and token offsets. Lexical tokens are buttons with one roving tab stop. A 320 ms hover or keyboard focus delay opens a short meaning card; leaving cancels it. Preview requests are abortable, stale responses are ignored, and a 48-entry cache avoids repeated requests. Clicking or pressing Enter opens a compact dialog on desktop and a bottom sheet on mobile. It shows English and Polish meanings (or an explicit unavailable message), a source sentence with the selected word marked, forms when known, status actions, and Phrasebook saving. **Open full details** reaches the original technical lemma dialog. Dictionary detail is requested only when a panel is opened, with a bounded 20-entry cache; hover uses only local preview data.

Arrow Left/Right moves between lexical tokens and skips punctuation. `1`, `2`, `3`, `4`, and `X` set New, Learning, Known, Mastered, and Ignored on tracked lemmas. A successful save updates all visible occurrences of that lemma and advances focus. Failed saves keep focus and the old state. Enter opens and Escape closes; shortcuts do not run inside form controls. Focus returns to the word on close. Semantic classes and labels distinguish New, Learning, Known, Mastered, Ignored, Excluded, and Unresolved without relying on color alone. The vocabulary color toggle is retained.

The preview policy is read-only: user translations first; reference English learner glosses when available; missing English or Polish translations say so. A visible untracked surface can be looked up without creating a vocabulary lemma or learning event. There is no automatic Gemini dictionary lookup. Full lemma details still use the existing dictionary provider path after an explicit click. Phrase saving reuses the existing Phrasebook endpoint and source provenance. Reader coverage, reference, analysis, and grammar details remain available inside disclosure panels below the prose.

The shared inspector also works on visible Cloze context, visible Listening transcript, and vocabulary rows. Cloze masks its target sentence span and suppresses answer-option words before grading, so lookup cannot reveal the answer. Feedback may expose the answer afterward. Hidden Listening transcript creates no inspectable tokens; revealing it enables lookup. Active benchmark prompts have no lexical inspector or dictionary affordance. Reviews keep Anki scheduling and local practice distinct; linked vocabulary can be reached through existing detail routes.

## Page and visual changes

| Surface | Productization change |
| --- | --- |
| Reader library | Continue text first; adding text is secondary. Reader prose has a bounded 880 px measure. |
| Vocabulary | Compact lexical preview from list rows; full technical detail is secondary. |
| Progress | Collection provenance is collapsed; the primary progress cards remain visible. |
| Benchmarks | Norway Preparation is split into source-specific dimension cards and progress; no composite score. |
| Curriculum | Learner pack actions lead; diagnostics are collapsed. |
| Content Inbox | The next material choice and action lead; rights details remain available. |
| Reviews | Today and Needs attention precede other practice and history. |
| Cloze | Visible context lookup with answer masking and a valid full-detail route. |
| Generate | Length, difficulty, topic, and style lead; generation mode, provider, target, and reference options are in Advanced options. |
| Listening | Visible transcript lookup; hidden transcript remains uninspectable. |
| Grammar | Compact catalogue rows and examples; parser and detector evidence is collapsed. |
| Statistics | A bounded two-column analytical layout on wide screens and one column on mobile. |
| Goals | Active goals and a useful empty state precede the create form. |
| Settings | Profile, study/audio, and integration settings are grouped; technical status is secondary. |
| Phrasebook and Topics | Empty states explain the next action. |

Widths are tokenized at 880 px reading, 1040 px form, 1280 px standard, and 1500 px wide surfaces. Cards use a restrained dark palette, small uppercase section labels, clear headings, and consistent action styling. At 700 px and below, grids stack and the navigation collapses. The word dialog becomes a bottom sheet. Focus styles, semantic labels, native dialog behavior, reduced motion, and keyboard navigation remain available.

## Backend and data boundaries

`GET /api/language/profiles/{id}/today-summary` composes a small read-only snapshot from bounded local queries plus persisted Anki sync state. The existing widget-summary endpoint uses the same contract. `GET /api/language/lemmas/{id}/preview` and `/api/language/profiles/{id}/lexical-preview?surface=...` supply read-only lexical previews. Hover and browsing do not call the parser, live Anki, Gemini, or the dictionary provider. The click panel can use the existing lexical detail route for provider-backed detail. Existing knowledge updates and Phrasebook saves remain explicit mutations.

The canonical user schema stays **v16** and reference schema stays **v3**. No migration, API route rename, localStorage key rename, benchmark answer exposure, Anki template rewrite, or Finance code change was made for this pass.

## Performance and verification

On a generated temporary fixture with 251 lemmas, 12 analyzed texts, and 500 knowledge events, 20 local service calls each measured these medians: Today **14.86 ms** (941 bytes), widget **12.55 ms** (941 bytes), lexical hover preview **8.95 ms** (291 bytes), untracked preview **5.50 ms** (212 bytes), and Reader document **8.49 ms** (22,326 bytes). Full lexical detail with a **fake local provider** measured **8.80 ms** (496 bytes); real provider latency is outside this figure. The browser's second hover of a cached lemma makes no preview request. The benchmark is reproducible with `python scripts/benchmark_language_productization.py`.

Automated tests cover Today/owner semantics, widget visibility, no live Anki probe, lexical read-only behavior, keyboard focus and repeated lemma updates, failed saves, Cloze answer masking, hidden Listening transcript, route preservation, and the existing Language suites. Real Edge screenshots were captured for 19 Language surfaces plus the dashboard widget, quick hover, compact word panel, and advanced detail at **2048×1010, 1440×1000, 430×900, and 390×844** under `reports/language-productization/`. The isolated fixture includes analyzed Reader text and seven token states. The dashboard capture temporarily clears an unrelated cleaning lock and forces the widget visible in the isolated browser profile; this does not change saved user settings. The browser smoke checks route content, no global horizontal overflow, roving focus, and panel opening. Contact sheets and representative full-size captures were visually reviewed; the mobile navigation and Study Session minute wrapping were corrected from this review.

The final Language frontend run passed **175/175 tests across 24 files**. The complete Language backend run passed **279 tests, one skipped**. The latest broad frontend run passed **1058 tests, two skipped, two failed**: a Finance Pack D.2 source assertion expecting synchronous refresh while the already modified Finance code refreshes in the background, plus a Reading E2E undo assertion that passed on an isolated rerun (24/24 Reading E2E tests). An earlier broad run had only the Finance failure. Neither failure is in Language, and no Finance or Reading code was changed by this pass. The broad backend run passed **959 tests, seven skipped**. Production Vite build and changed JavaScript/Python syntax checks passed.

In the isolated Edge runs, initial Today readiness took roughly **0.76–1.02 s** across the four viewports and Reader route initialization took roughly **0.34 s**. These are local browser timings, not a guarantee for slower hardware or live providers. Hovering the same lemma twice kept preview resource count unchanged on the second hover. The Edge flow also verified repeated-lemma status updates, compact panel, full detail, and mobile sheet status change.

## Deviations and limitations

- Synthetic fixture words have no English or Polish glosses, so the Edge word-sheet capture displays the explicit unavailable fallbacks. Translation behavior is covered with frontend data fixtures and the read-only service tests.
- The dashboard screenshot fixture must bypass the existing cleaning lock and a persisted widget preference in this workspace. Normal default visibility is covered by widget settings tests; a user who previously hid the widget keeps that choice.
- A Reader streak uses a bounded recent-event window. Extremely high activity beyond that window can undercount a long streak; it never invents activity.
- Real provider latency, actual Anki availability, and native touch hardware were not measured in the isolated Edge fixture. The mobile sheet was exercised at touch-sized Edge viewports.
- Existing technical labels remain inside some advanced panels. They are retained for provenance rather than treated as learner achievements.
- The original full lemma dialog is still dense, especially on a phone. It is now a secondary action and scrolls within the viewport; a later focused redesign would be separate from this V1 pass.
