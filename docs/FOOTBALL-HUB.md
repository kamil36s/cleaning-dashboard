# Football Hub

Review date: 2026-10-03. Task branch: `ai/astra/football-hub`, separate worktree `cleaning-dashboard-football-hub`. No merge into dev/main and no push. The original checkout and Media API/Oscar work are untouched. Runtime preview: `http://127.0.0.1:8017/football.html` while the isolated preview server is running.

## Architecture

```text
ESPN / TheSportsDB / optional API-Football
                   |
     existing http_get_json + FootballRequestControl
                   |
       football_service.py / server.py adapters
        |                               |
 Kitchen score refresh            lazy FootballHub profiles
        |                               |
 Kitchen JSON snapshots <--- tables     FootballStore (SQLite v2)
        |                               |
 /api/kitchen/scores       /api/football + /entity + /search
        |                               |
 Kitchen / tablet                  Football Hub desktop

data/football-knowledge.json --> /api/football/learn --> Learn / Club History
```

This extends the existing service. Kitchen remains the score/fixture/live refresh owner. The same HTTP controller handles profile enrichment. No new independent poller or sports API stack exists.

## Data sources

| Provider | Purpose | Authentication / limits | Cache | Fallback |
|---|---|---|---|---|
| ESPN | Existing scores, fixtures, tables, match events, World Cup leaderboards; new team catalog, squads, player overview statistics | Existing unauthenticated endpoints; no published contractual quota verified; local cap 20/min | JSON 30 s scoreboard/live, 30 min standings, 5 min other; persistent profile TTL below | Original timestamp retained with stale data |
| TheSportsDB | Existing fixtures/results/tables/crests; new club foundation/location/stadium and league logo/current season | Existing public key 123; local cap 30/min; tier restrictions apply | Club/catalog 24 h | Explicit missing state if exact entity ID is not returned |
| API-Football | Existing optional results/tables; new coach appointments and transfers | Existing server `API_FOOTBALL_KEY` / aliases, absent in checked environment; local cap 8/min, not a promise about daily quota | Coach/transfer 6 h | Unavailable without key/mapping; stale cache on error |
| BBC / Wikipedia / existing Manual | Existing standings / CONIFA / supplemental cached results | Unchanged legacy sources; not fully instrumented by JSON request controller | Existing Kitchen policy | Existing source fallbacks |
| FIFA Training Centre, IFAB, Liverpool FC | Manually authored short learning summaries with direct citations | No runtime scraping | Versioned repository content | Empty state, no invented text |

Provider references: [TheSportsDB documentation](https://www.thesportsdb.com/documentation), [API-Football v3](https://www.api-football.com/documentation-v3), [ESPN team roster used for verification](https://site.api.espn.com/apis/site/v2/sports/soccer/eng.1/teams/364/roster). ESPN responses are not a guarantee of roster completeness. Its coach list returned historical Liverpool names, so the application deliberately does not treat it as the current coach.

## Data flow

`/api/football` is still a local snapshot read. It ingests available Kitchen results into the existing historical store and merges history with current events. ESPN upcoming/live/final IDs are compared using the underlying event ID, without changing public IDs. A historical upcoming row no longer resurfaces after the final result.

Desktop Live and the refresh button call `/api/football/refresh`, which enters the same `read_kitchen_scores()` lock as the tablet. Updated live rows are persisted with a separate `liveUpdatedAt`; results/fixtures retain their own timestamps. Failures retain old live rows and mark them unverified. Hockey remains in Kitchen settings and data; the Football snapshot excludes hockey entities and matches.

Opening a club resolves a provider mapping using exact catalog names and existing IDs. Opening Squad fetches the roster; player profiles then reuse it. Entity search only reads local catalogs and cached entities. An untracked competition can fetch its table through the existing Kitchen adapters; it publishes the result back into Kitchen JSON without changing favourites or refreshing unrelated table timestamps.

## Cache policy

`PROFILE_TTLS` in `football_service.py` owns enrichment TTLs: catalog/club/stadium metadata 24 h, squads/coaches/transfers/standings 6 h, player statistics 1 h. Stadium metadata shares the club lookup to avoid a duplicate provider request. Existing score/fixture/table TTLs remain 30 min / 2 h / 6 h.

Persistent payloads live in SQLite `entity_cache`. Identical concurrent profile requests are serialized and reuse that cache. Failed lookups have a bounded 120 s negative cache; failure cooldown does not extend on each read. Original timestamps survive fallback. HTTP 429 and provider failure are distinguished from no data. Existing provider rolling budgets and HTTP `Retry-After` remain active. Those budgets are in-memory and reset on process restart; this is not a persistent daily-quota ledger.

## Entity model

Existing club/competition/match keys remain intact. New player/stadium/transfer/coach keys are UUID-based internal keys; provider IDs remain separate and are recorded in the existing `provider_mappings` table. Entity records are stored in the additive `entities` table. SQLite `user_version` is 2; all original tables remain.

Season is source-provided metadata, not a guessed uniform calendar. Squads carry source season data; player statistic splits retain the provider's exact season/competition labels. Transfer filtering explicitly uses July–June windows, including both boundaries in the UI label; this is not a claim about every league's season calendar.

Club statistics and form use a single central calculation over observed final matches. Only known final statuses with numeric scores count. Cancelled, postponed, abandoned, scheduled and live rows are excluded. Conservative club/date deduplication prevents repeated provider records from inflating form. W/D/L describes the score after play, not a penalty-shootout winner. Form offers 5/10 games, newest first, with links to Match Details. League points come from standings, not an invented points calculation. The archive does not contain a complete historical season.

## API routes

Existing routes are preserved: `/api/football`, `/api/football/settings`, `/api/kitchen/scores`, `/api/kitchen/settings`.

New GET routes:

- `/api/football/entity?type=club&id=<key>&section=overview|squad|coach|form|matches|transfers|stadium|history&year=2026-2027`
- `/api/football/entity?type=competition|player|stadium&id=<key>`
- `/api/football/search?q=<text>&kind=player` (kind optional; 100-result limit after filtering)
- `/api/football/learn`
- `/api/football/refresh` (uses normal cache, no force bypass)

Entity envelopes include `cache`, `stale` and `sourceErrors`. Unknown entities return 404; backend failure returns 503. Empty sections keep their availability explanation. No credential is returned in the API or diagnostics.

## Favourites

The existing Kitchen settings remain canonical. Following preserves non-football selections, deduplicates arrays, supports add/remove and links to profiles. Browser verification toggled Liverpool and Premier League, reloaded to verify persistence, restored the selections, and confirmed Montreal Canadiens was preserved. This was performed only against the isolated worktree's settings copy.

## Live data

Only the visible Live tab polls every 30 s; an in-flight request prevents overlapping desktop refreshes. Other views read local data until manual refresh. There were no active football matches in the browser-test snapshot; real empty Live and refresh states were checked, while live/status/failure transitions are covered by fixture tests. No claim is made that an actual goal was observed during testing.

## Learn content

`data/football-knowledge.json` is independent of live football records. Seven initial cards cover pressing, mid-block, transitions, offside, ball out of play, sourced trivia and Liverpool's foundation. Each has `id`, `title`, `text`, `category`, `source`, `sourceUrl`, `dateAdded`, `relatedClubKeys`. Learn filters by category; History displays related cards plus provider foundation/location metadata. Unknown trophies, previous names, capacity and coordinates stay unknown. This is a small sourced starting collection, not a full encyclopedia.

## Tablet integration

No tablet UI redesign. Kitchen's existing payload and presentation settings remain compatible. Desktop refresh and tablet refresh share one lock and published live snapshot. On-demand tables write through to the same Kitchen snapshot. Presentation regression tests pass. The browser checked the Football Hub at 1440×1000 and 1024×768; this does not claim a full physical-tablet acceptance test.

## Debugging

Use Sources & Data for bounded provider HTTP history, cooldowns, stored matches and mappings. Profile API responses expose per-resource cache states without placing raw cache identifiers in the normal UI. Inspect the original fetch time when stale data is displayed. An empty current coach is intentional if there is no verified open appointment; a historical ESPN coach list is insufficient evidence.

Focused validation:

```powershell
python -m unittest discover -s tests -p 'test_football*.py' -q
python -m unittest discover -s tests -p test_kitchen_football.py -q
npm run test:run -- tests/football-hub.test.js tests/football-page.test.js tests/kitchen-football-presentation.test.js
npm run build
```

## Adding a new data source

Add an adapter through the existing controlled server transport, register its host/budget, validate entity identity and payload errors, and retain source IDs separately from canonical IDs. Add a central TTL and fixture tests for failure, stale fallback, concurrent lookup, unknown fields and mapping conflicts. Do not follow provider-supplied arbitrary URLs or create browser-side authenticated requests. New editorial entries require a direct source URL and reviewed summary.

## Acceptance results

The before audit is in `FOOTBALL-HUB-AUDIT.md`. PASS means tested behavior within available provider coverage; it does not promise every club/league has every field.

| # | Feature | Before | After | Evidence / limit |
|---|---|---|---|---|
| 1 | Shared Football service | PARTIAL | PASS | Existing service/store extended; shared refresh/table path |
| 2 | Favourite clubs | PASS | PASS | Browser persistence + preservation tests |
| 3 | Favourite competitions | PASS | PASS | Browser persistence + preservation tests |
| 4 | Live scores | PARTIAL | PASS | Shared live timestamp/fallback tests; browser empty/refresh |
| 5 | Fixtures | PASS | PASS | Existing tests and real fixtures in browser |
| 6 | Tables | PASS | PASS | Existing adapters; real 20-team Premier League table |
| 7 | Match details | PARTIAL | PASS | Events rendered safely; match/club navigation |
| 8 | Players | MISSING | PASS | Real roster profiles; club links; unknown fields |
| 9 | Squads | MISSING | PASS | Real 31-player Liverpool roster, position groups; coverage depends on ESPN mapping |
| 10 | Coaches | MISSING | PARTIAL | Adapter/UI/fixtures pass; production API-Football key absent |
| 11 | Transfers | MISSING | PARTIAL | IN/OUT, date/type and window parsing tested; production key absent |
| 12 | Player statistics | PARTIAL | PASS | Real ESPN season-labelled splits; existing tablet leaders retained |
| 13 | Club statistics | MISSING | PASS | Central final-match aggregates + source league points |
| 14 | Form | MISSING | PASS | 5/10 navigation; status/dedup/order tests |
| 15 | Competition pages | PARTIAL | PASS | Logo, country, season, table, clubs, results, fixtures, favourites |
| 16 | Historia klubów | MISSING | PASS | Source metadata + separate linked historical card |
| 17 | Stadiony | MISSING | PASS | Real Anfield profile; absent capacity/address not invented |
| 18 | Tactical concepts | MISSING | PASS | Three sourced initial cards |
| 19 | Football education | MISSING | PASS | Learn/category navigation |
| 20 | Ciekawostki | MISSING | PASS | Sourced trivia record and category |
| 22 | Tablet integration | PARTIAL | PASS | Shared payload/live/table tests; existing presentation retained |

The IDs deliberately skip 21: the user deleted the deferred quiz item. The 21-item runtime list is preserved.

### Tests and browser review

57/57 focused tests pass: 41 football Python (including Todo isolation) + 9 Kitchen Python + 7 frontend. Production Vite build passes. Existing build warnings concern non-module legacy scripts, runtime JSON paths and large chunks outside Football Hub.

Browser checked Overview, Live/refresh, Matches/details, Premier League, Liverpool overview, Squad, Player/statistics, Form 5/10, Transfers and Coach unavailable states, Stadium, History, Learn/category, Search, Players, Following/add/remove/persistence/profile navigation. No page JavaScript errors. Screenshots and run log are local ignored artifacts in `reports/football-hub/`; they are not production fixtures.

### Not completed / coverage limits

- Coaches and Transfers require configured API-Football credentials and matching team coverage before production acceptance. No key was requested or invented; no provider restriction was bypassed.
- Squads/player statistics use available ESPN mappings. Clubs outside that coverage display an explicit missing state. Historical team/name collisions are not solved by fuzzy merging.
- No complete historical results backfill, stadium coordinate/capacity database, news ingest, physical-tablet redesign, persistent provider daily quota ledger, or encyclopedia.
- Code remains on the review branch; the primary running dashboard will receive it only after an explicit integration step.

### Todo Projects

`scripts/update-football-hub-todo.py` applies these reviewed results to the existing private Todo file: 19/21 done, Coaches and Transfers incomplete, no new/deleted subtasks. It preserves IDs, makes a backup, checks for concurrent file changes before replacement and verifies unrelated projects afterwards. The project description records that code awaits integration from this worktree. No seed/reset of other projects is performed.

Applied to the primary checkout's existing Todo file on 2026-10-03. Read-back confirmed 19/21 and exactly Coaches / Transfers pending. The other 78 entries were unchanged. The before-image backup is alongside that private file with a `todo.football-hub-before-*.json.bak` name; it is not committed.

## Files and Git review

Created: `data/football-knowledge.json`, `docs/FOOTBALL-HUB-AUDIT.md`, `docs/FOOTBALL-HUB.md`, `scripts/update-football-hub-todo.py`, `tests/football-hub.test.js`, `tests/test_football_hub.py`, `tests/test_football_todo.py`.

Modified: `football.html`, `football.css`, `js/football.js`, `football_service.py`, `football_store.py`, `server.py`, `PROJECT_MAP.md`; `CHANGELOG-AUTO.md` is generated by the existing checkpoint helper. Runtime caches, preview screenshots and the private Todo update are not committed.

Branch: `ai/astra/football-hub`, based on dev commit `67931c3`. Implementation checkpoints: `build-0004` (`6952f70`, audit), `build-0006` (`92ed6a7`, profiles/UI/tests), `build-0007` (`6bd2da1`, completed validation and docs). These are three implementation commits ahead of the starting dev; the final report is checkpointed by `scripts/finish-ai-task.ps1`. No merge, push, Git backup-script changes or changes to save/auto tags.

The isolated preview imports the existing server handler on port 8017 without starting the main application workers. Its Kitchen cache/settings/database are separate from the primary checkout; its crest writes are redirected to an ignored preview file. Source integration will require reviewing the small Football-specific `server.py` changes alongside any Media API/Oscar changes made in parallel.
