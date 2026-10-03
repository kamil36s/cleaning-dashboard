# Classical Composer Library

The dashboard module lives at `classical-library.html`. When the local Python server is running, the pretty routes `/classical-library` and `/classical-library/composer/<composerId>` are also mapped to that page.

## Data Layout

- `data/classical-library/composers/*.json` stores imported or manually corrected catalogue data.
- `data/classical-library/progress/progress.json` stores listening progress only.
- `data/classical-library/normalization/*.json` stores category and version rules.
- `data/classical-library/raw/` is reserved for source snapshots from Open Opus, Wikidata, Wikimedia Commons, MusicBrainz, and RYM source-work captures.

## RYM work table format

RYM-style source captures live under `data/classical-library/raw/rym/<composer-id>.json`. They preserve the artist page Works table as source groups:

- `groups[].name` is the exact RYM work-type header.
- `groups[].works[]` keeps the exact source order, date, role, title, catalogue numbers, and RYM path.
- Run `node scripts/materialize-rym-works.mjs data/classical-library/raw/rym/<composer-id>.json data/classical-library/composers/<composer-id>.json` to materialize the composer JSON used by the widget and static build.

The classical library defaults to `Sort: RYM source order`, so these groups render as the page source provides them instead of being remapped into the local normalized category list.

Catalogue refreshes should merge source data into composer JSON without deleting `userMetadataOverrides`. Progress updates must only touch `progress/progress.json`.

## Adding a Composer

Open the module, use **Add Composer**, search the seeded known-composer list, and add the profile. This creates a composer record with basic metadata and an empty works list. Use **Import Works** when you explicitly want to populate works later.

For now the source adapters are placeholders. The UI and API are ready for:

- Open Opus work catalogue imports
- Wikidata/Wikipedia profile enrichment
- Wikimedia Commons image/license metadata
- MusicBrainz work/recording relations later

## Manual Corrections

Every composer and work has an edit action. Work edits support title, year, catalogue, category, instrumentation, version, arrangement fields, source notes, confidence, review flag, hiding/restoring, and duplicate merge notes. Listening status, rating, reaction, and notes are saved separately in progress JSON.

## Profile Images

Composer edit forms support a local profile-image upload. The local API stores uploaded files in `public/assets/composers/`, mirrors them to `assets/composers/` for the Python static server, and writes the composer `image.localFile` as `/assets/composers/<file>`.

## RateYourMusic Caution

The UI is organized in a RateYourMusic-like compact catalogue shape: category sections, parent works, expandable parts/movements, and dense status/rating/reaction/notes controls. The app does not scrape RYM automatically. If you manually correct data to match RYM, those corrections are stored locally and preserved across future imports.
