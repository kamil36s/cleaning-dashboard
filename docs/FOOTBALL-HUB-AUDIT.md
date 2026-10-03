# Football Hub audit — 2026-10-03

Baseline: `67931c3`, from dev. The running Todo has 21 tasks (the seed has an extra deferred quiz task; do not restore it). Before means verified code/test capability, not a checkbox. Existing Python regression suite: 20/20 passing. No prior browser verification is claimed.

| Feature | Before | Evidence / problem | Action |
|---|---|---|---|
| Shared Football service | PARTIAL | football_service.py request control + server.py Kitchen fetchers; desktop reads snapshot only | Extend existing service/store, keep shared refresh |
| Favourite clubs | PASS | kitchen settings + football-page test preserving hockey | Retain settings and add profile navigation |
| Favourite competitions | PASS | Same persistence and preservation test | Retain settings and add profile navigation |
| Live scores | PARTIAL | Kitchen fetches ESPN live; desktop never refreshes it | Shared refresh button/polling, stale handling |
| Fixtures | PASS | Kitchen adapters/cache + test_kitchen_football | Preserve |
| Tables | PASS | Kitchen standings + pagination/fallback tests | Preserve, link clubs |
| Match details | PARTIAL | Kitchen renders ESPN events; desktop shows only metadata | Render retained events and club links |
| Players | MISSING | No player entity/view | Lazy profiles from provider squad |
| Squads | MISSING | No roster lookup | ESPN roster; explicit missing state outside mapped coverage |
| Coaches | MISSING | No verified current coach | Only explicit current appointment; do not use ESPN historical list |
| Transfers | MISSING | No transfer adapter | API-Football adapter, honest unavailable state without credentials |
| Player statistics | PARTIAL | Kitchen World Cup goal/assist leaderboards exist; no player profile in desktop | ESPN overview statistics with source season labels |
| Club statistics | MISSING | Standings values available but no club view | Central aggregation with explicit observed-history scope |
| Form | MISSING | No W/D/L calculation | Exclude non-final and duplicate games |
| Competition pages | PARTIAL | Expandable rows, limited table, no profile | Profile/table/results/fixtures/club navigation |
| Historia klubów | MISSING | No structured/editorial separation | Provider metadata; separate sourced knowledge cards |
| Stadiony | MISSING | No entity/view | Provider stadium data, unknown fields stay unknown |
| Tactical concepts | MISSING | No content model | Sourced small learning collection |
| Football education | MISSING | No Learn section | Categories and linked knowledge cards |
| Ciekawostki | MISSING | No source-aware facts | Sourced facts in learning collection |
| Tablet integration | PARTIAL | Shared JSON + request budgets; desktop does not drive freshness | Use same Kitchen refresh owner; retain tablet contract |

## Providers and constraints

- ESPN: existing unauthenticated JSON source, no contractual quota known. Existing local budget 20/min. Roster and overview endpoints verified against real responses. Coach array includes historical Liverpool coaches, so it is not evidence of a current coach.
- TheSportsDB: existing public v1 key 123. Official documentation reports tier limits (including 10-player free roster and restricted search). Lookup responses must match the requested ID; never accept an unrelated example team. Local budget 30/min. https://www.thesportsdb.com/documentation
- API-Football: existing optional server key, not configured in the checked local environment. Local budget 8/min is not a daily provider entitlement. Transfers/coaches must report unavailable until credentials and verified team mapping exist. https://www.api-football.com/documentation-v3
- BBC standings and CONIFA Wikipedia supplement remain existing fallbacks, outside the JSON budget controller. No new scraper/news feed.
- Existing cache: results 30 min, fixtures 2 h, tables 6 h; JSON request dedup 30 s live/scoreboard, 30 min standings, 5 min other.

## Implementation boundary

Extend `football_service.py` and `football_store.py`; add additive `/api/football/*` routes in server.py. No second data system. Keep Kitchen selection/settings and payload compatible. New profile fetches are lazy, persisted with TTL, serialized and deduplicated; stale data retains its original timestamp. Search reads local entities. Learning content is separate from live payloads.

Work uses the documented `start-ai-worktree.ps1` equivalent because Media API/Oscar work continues in the primary checkout. No checkout, merge or push there.
