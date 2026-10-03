# Media / Oscar implementation audit

2026-10-03. Baseline `c6fba01`; Sync foundation is integrated in dev and main.
Runtime inspection is read-only until verified backup. Backlog checkboxes are not evidence.

| Feature | Before | Evidence | Problem | Action |
| --- | --- | --- | --- | --- |
| Oscar audit | PARTIAL | PROJECT_MAP, server.py, js/oscars-data.js | No acceptance audit | This document and executable tests |
| Canonical Movie | PARTIAL | film_library, upsert_film_library_row | Metadata mixed with personal state | Retain movie IDs, separate user tables |
| Canonical TV | MISSING | No show/season/episode tables | No typed hierarchy | Add typed tables in existing DB |
| Person | MISSING | director text only | No shared identity/credits | Canonical persons and credits |
| Award | MISSING | List source_kind=oscars | Not an entity | Award and category tables |
| Nomination | MISSING | Delimited category strings | No nominee relations | Nomination and nominee relations |
| Ceremony/year | PARTIAL | watchlist.oscars_year, film_lists.source_year | Only year label | Ceremony entity preserving original year |
| External IDs | PARTIAL | canonical_key prioritizes IMDb then Wikipedia | Cannot map multiple identifiers independently | Unique typed provider mappings |
| Shared service | PARTIAL | server.py film/Oscar functions | Separate watchlist reads and writes | Shared persistence/lookup service |
| Cache | PARTIAL | Wiki/TMDB helpers, local posters, static snapshots | Scattered policies | Central cache policy and fallback |
| Dedupe | PARTIAL | canonical_key unique | Different identifiers can split identities; title key can overmerge | External mappings, conservative unmatched identity |
| Oscar migration | MISSING | fetch_all reads watchlist | Competing metadata/user state | Canonical projection with legacy row IDs |
| Library integration | PARTIAL | fetch_film_library reads film_library | One-way copy from Oscars | Shared canonical metadata and user state |
| Watch state separated | MISSING | watched/date columns in both tables | Library edits diverge from Oscars | Separate authoritative state |
| Rating separated | MISSING | rating_1_10 in both tables | Library edits diverge from Oscars | Separate authoritative ratings |
| Other awards extension | MISSING | Oscar-specific category strings | No relational extension | Award-independent ceremony/category/nominee model |

Baseline: 285 Oscar rows, 286 library films, 7 lists, 286 memberships;
635 delimited nominations, 122 winner-category occurrences, 25 distinct category
labels, 6 ceremonies. These are counts of the existing data, not a claim of a
complete Academy history. Historical rows contain no actor/composer nominee
identities: do not manufacture people from category labels.

Backup: `data/backups/media-api-oscar/20261003T084236.568069Z/` contains an online
SQLite backup and Todo settings, plus a size-independent SHA-256/integrity/count
manifest. SQLite integrity_check is ok. Original watchlist and film IDs must be
preserved; legacy data stays available as migration evidence.

The dashboard currently registers `films`, not `oscars`. `oscars.html` and the
existing `widget-oscars.js` remain supported without changing widget visibility.
Oscar browser-only mode has existing private localStorage data. It must remain
explicitly local and must never silently overwrite the server during migration.
