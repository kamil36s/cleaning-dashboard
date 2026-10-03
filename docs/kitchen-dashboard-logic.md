# Kitchen Dashboard - logika i konfiguracja sportu

Ten plik jest mapa decyzyjna dla sportowej czesci Kitchen Dashboardu. Ma pomagac szybko zmienic: co jest pobierane, z jakiego okna czasu, jak powstaja slajdy, kiedy pokazuje sie tabela, jak traktowane sa puchary, jak dzialaja przyszle mecze i gdzie dopisac wyjatki.

## Pliki sterujace

- `server.py` - katalog lig/zespolow, pobieranie providerow, cache, normalizacja, slajdy.
- `js/kitchen.js` - render slajdow i klientowa normalizacja/chunkowanie.
- `kitchen.css` - wyglad slajdow.
- `settings.html`, `js/settings.js`, `styles.css` - panel ustawien Kitchen Dashboardu.
- `data/kitchen-settings.json` - aktywne ligi, tabele, zespoly i okno wynikow.
- `data/kitchen-scores.json` - cache payloadu wynikow.
- `data/kitchen-leagues.json` - cache listy lig w settingsach.
- `data/kitchen-team-crests.json` - cache herbow.

## Najwazniejsze przelaczniki

```py
KITCHEN_WINDOW_HOUR_OPTIONS = [24, 48, 72, 96, 168]
KITCHEN_DEFAULT_WINDOW_HOURS = 24
KITCHEN_SCORES_CACHE_TTL = 30 * 60
KITCHEN_LEAGUES_CACHE_TTL = 60 * 60 * 24
KITCHEN_UEFA_QUALIFIER_KEYS = {"champions-league", "europa-league", "conference-league"}
KITCHEN_FULL_ROUND_LEAGUE_KEYS = KITCHEN_UEFA_QUALIFIER_KEYS
KITCHEN_FULL_ROUND_NUMBERS = ["400"]
```

Co zmienic:

- wiecej opcji okna wynikow: `KITCHEN_WINDOW_HOUR_OPTIONS`,
- domyslne okno: `KITCHEN_DEFAULT_WINDOW_HOURS`,
- czestosc odswiezania cache wynikow: `KITCHEN_SCORES_CACHE_TTL`,
- ligi pobierane jako pelna runda zamiast pojedynczy next/past: `KITCHEN_FULL_ROUND_LEAGUE_KEYS`,
- numery rund TheSportsDB dla pelnorundowego pobierania: `KITCHEN_FULL_ROUND_NUMBERS`.

Po zmianie kontraktu payloadu podbij `KITCHEN_SCORES_SCHEMA_VERSION`. Po zmianie katalogu lig/settings podbij `KITCHEN_LEAGUES_CATALOG_SCHEMA_VERSION`.

## Katalog lig i zespolow

Glowne wpisy sa w `KITCHEN_LEAGUES`.

Typy:

- `type: "competition"` - liga albo rozgrywki.
- `type: "team"` - obserwowany zespol, ktory moze dostac pelny slajd meczu.

Wazne pola dla ligi:

- `key` - stabilny identyfikator; nie zmieniac bez migracji settingsow.
- `name` - nazwa na ekranie.
- `sport` - np. `Soccer`, `Ice Hockey`.
- `thesportsdb_id` - id ligi w TheSportsDB.
- `espn_sport`, `espn_league` - ESPN scoreboard.
- `api_football_id` - API-Football, jesli jest klucz.
- `standing` - provider tabeli.
- `roundType: "cup"` - traktuj jako puchar/knockout.
- `defaultEnabled: False` - pokazuj w settingsach, ale nie wlaczaj domyslnie.
- `settingsGroup` - wlasna grupa w settingsach.
- `nextTournament` - metadane najblizszego turnieju dla listy w settingsach.

Wazne pola dla zespolu:

- `thesportsdb_team_id` - ostatnie i najblizsze mecze z TheSportsDB.
- `espn_sport`, `espn_league`, `espn_team_names` - fallback ESPN.
- `crest` - reczny herb, jezeli provider go nie daje.

`KITCHEN_NEXT_TEAMS` steruje tym, ktore obserwowane zespoly moga pojawiac sie w slajdzie `Nastepne mecze`.

## Settings

`data/kitchen-settings.json`:

```json
{
  "sports": {
    "windowHours": 24,
    "enabledLeagueKeys": ["champions-league"],
    "standingsLeagueKeys": ["ekstraklasa"],
    "enabledTeamKeys": ["besiktas"]
  }
}
```

Znaczenie:

- `enabledLeagueKeys` - ligi/rozgrywki, ktore moga generowac wyniki i przyszle mecze.
- `standingsLeagueKeys` - tabele dozwolone dla aktywnych lig.
- `enabledTeamKeys` - obserwowane zespoly.
- `windowHours` - zakonczone mecze tylko z tego okna.

Panel settings pobiera `/api/kitchen/settings`. W `sportsOptions.nextTournaments` backend zwraca najblizsze turnieje z `nextTournament`, posortowane po dacie startu, z polem `daysLabel` typu `trwa`, `jutro`, `za 127 dni`.

## Zrodla wynikow

Kolejnosc pobierania wynikow:

1. API-Football, jesli `API_FOOTBALL_KEY` jest ustawiony.
2. ESPN competition scores.
3. TheSportsDB `eventsday.php`.
4. TheSportsDB fallback `eventspastleague.php`.
5. TheSportsDB pelne rundy `eventsround.php` dla `KITCHEN_FULL_ROUND_LEAGUE_KEYS`.
6. TheSportsDB/ESPN team scores.
7. `KITCHEN_SUPPLEMENTAL_MATCHES`.

Wszystkie mecze sa potem normalizowane, wzbogacane herbami, deduplikowane i sortowane.

## Eliminacje UEFA

Champions League, Europa League i Conference League maja dodatkowa logike:

- sa w `KITCHEN_UEFA_QUALIFIER_KEYS`,
- przyszle i zakonczone mecze moga byc brane z pelnej rundy `eventsround.php`,
- etapy sa opisane w `KITCHEN_UEFA_STAGE_WINDOWS`,
- rewanze dostaja `firstLeg`, `firstLegLabel`, a zakonczone rewanze takze `aggregateLabel`.

Konfiguracja etapow:

```py
KITCHEN_UEFA_STAGE_WINDOWS = {
    "champions-league": [
        {"stage": "II runda kwalifikacji", "leg": "1. mecz", "start": "2026-07-21", "end": "2026-07-22"},
        {"stage": "II runda kwalifikacji", "leg": "rewanz", "start": "2026-07-28", "end": "2026-07-29"},
    ],
}
```

Co zmienic:

- inny opis etapu: `stage`,
- inne okno dat: `start` / `end`,
- inne nazewnictwo pierwszego meczu albo rewanzu: `leg`,
- dodanie kolejnej rozgrywki z dwumeczami: dopisz jej `key` do `KITCHEN_UEFA_QUALIFIER_KEYS` i `KITCHEN_FULL_ROUND_LEAGUE_KEYS`.

## Nastepne mecze

Backend buduje `nextMatches` z:

- ESPN dla rozgrywek z `espn_sport`/`espn_league`,
- TheSportsDB `eventsnextleague.php`,
- TheSportsDB `eventsround.php` dla pelnorundowych rozgrywek UEFA,
- TheSportsDB/ESPN dla obserwowanych zespolow,
- `KITCHEN_SUPPLEMENTAL_NEXT_MATCHES`.

Domyslne okno przyszlych meczow to 5 dni. Zespoly pokazuja najblizszy pojedynczy mecz, a rozgrywki moga pokazac wiele meczow. Frontend dzieli slajd `next` na porcje przez `NEXT_MATCHES_PER_SLIDE`.

## Wyniki i slajdy

Backend tworzy slajdy w `build_kitchen_slides()`:

1. `worldCupCountdown`.
2. Dla aktywnych lig: `results`.
3. Dla aktywnych lig z tabela i wynikami: `standings`.
4. Dla obserwowanych zespolow: osobne `match`.
5. Jesli sa przyszle mecze: `next`.
6. Jesli sa liderzy turnieju: `leaderboards`.

Frontend w `normalizeKitchenSlides()`:

- usuwa countdown z normalnej rotacji,
- deduplikuje mecze,
- dzieli `results` przez `RESULTS_MATCHES_PER_SLIDE`,
- dzieli `next` przez `NEXT_MATCHES_PER_SLIDE`.

## Tabele

Tabela pojawia sie tylko gdy:

1. liga jest w `enabledLeagueKeys`,
2. liga jest w `standingsLeagueKeys`,
3. liga nie jest pucharem,
4. w aktywnym oknie wynikow byl mecz tej ligi,
5. provider zwrocil sensowne rows.

Tabela jest kontekstem do ostatnich wynikow, a nie osobnym centrum tabel.

## Herby i obrazy

Frontend zawsze proxyuje obrazy przez:

`/api/kitchen/image?u=...`

Dozwolone hosty sa w `KITCHEN_IMAGE_HOSTS`. Jesli logo sie nie laduje:

- sprawdz, czy URL zwraca `200` i `image/*`,
- sprawdz, czy host jest w `KITCHEN_IMAGE_HOSTS`,
- sprawdz `KITCHEN_TEAM_CRESTS`,
- sprawdz `data/kitchen-team-crests.json`,
- sprawdz, czy provider nie zwraca placeholdera.

Beşiktaş powinien uzywac SVG z Wikimedia Commons: `https://upload.wikimedia.org/wikipedia/commons/d/da/BesiktasJK-Logo.svg`. Wariant `www.thesportsdb.com/images/...` potrafi zwracac 404, a badge z TheSportsDB bywa niestabilny w UI.

## Mundial

Slajd `worldCupCountdown` jest nadal dodawany przez backend, ale jego tekst pochodzi z payloadu:

- `leagueName`,
- `eyebrow`,
- `title`,
- `matchupTitle`,
- `displayDate`,
- `venue`,
- `city`,
- `image`,
- opcjonalnie `home` / `away`.

Po MŚ 2026 slajd wskazuje na FIFA World Cup 2030. FIFA potwierdza okno otwarcia 13-14 czerwca 2030, ale bez par i godzin, wiec renderer nie powinien wpisywac stalego `vs`.

## Cache i debug

Cache wynikow:

- plik: `data/kitchen-scores.json`,
- TTL: `KITCHEN_SCORES_CACHE_TTL`,
- schema: `KITCHEN_SCORES_SCHEMA_VERSION`,
- settings signature: `windowHours`, aktywne ligi, tabele i zespoly.

Cache katalogu lig:

- plik: `data/kitchen-leagues.json`,
- TTL: `KITCHEN_LEAGUES_CACHE_TTL`,
- schema: `KITCHEN_LEAGUES_CATALOG_SCHEMA_VERSION`.

Debug:

- `kitchen.html?debugSlides=1` - podglad slajdow.
- `/api/kitchen/debug` - providerzy, cache, bledy.

## Szybkie przepisy

Dopisac nowa lige:

1. Dodaj wpis do `KITCHEN_LEAGUES`.
2. Ustaw provider: TheSportsDB, ESPN albo API-Football.
3. Jesli ma tabele, dodaj `standing`.
4. Jesli to puchar, dodaj `roundType: "cup"` albo klucz do `KITCHEN_CUP_KEYS`.
5. Podbij `KITCHEN_LEAGUES_CATALOG_SCHEMA_VERSION`.

Dopisac turniej do listy settings:

1. Wpisz `nextTournament` przy lidze albo przez `national_tournament(...)`.
2. Ustaw `startDate` i `endDate`, jesli da sie policzyc dni.
3. Ustaw `status: "confirmed"` tylko gdy daty i gospodarz sa wiarygodne.
4. Podbij `KITCHEN_LEAGUES_CATALOG_SCHEMA_VERSION`.

Zmienic etap eliminacji UEFA:

1. Edytuj `KITCHEN_UEFA_STAGE_WINDOWS`.
2. Jesli TheSportsDB zmieni numer rundy, edytuj `KITCHEN_FULL_ROUND_NUMBERS`.
3. Podbij `KITCHEN_SCORES_SCHEMA_VERSION`.

Dopisac reczny mecz:

1. Wynik: `KITCHEN_SUPPLEMENTAL_MATCHES`.
2. Przyszly mecz: `KITCHEN_SUPPLEMENTAL_NEXT_MATCHES`.
3. Uzyj takiego samego formatu `home`, `away`, `score`, `round`, `roundType`.

Naprawic herb:

1. Sprawdz URL `HEAD` albo w przegladarce.
2. Jesli host jest nowy, dodaj go do `KITCHEN_IMAGE_HOSTS`.
3. Jesli URL jest staly, dodaj do `KITCHEN_TEAM_CRESTS`.
4. Jesli to nazwa z providera, dodaj alias w `KITCHEN_TEAM_CREST_ALIASES`.
