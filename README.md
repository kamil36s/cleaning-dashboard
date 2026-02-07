# Cleaning Dashboard (multi-file)

## Dev quick start
Open `src/index.html` via a local server (for ES Modules):

- Node: `npx http-server src -p 5173` or `npx serve src`
- Python: `python -m http.server 5173 -d src`

Then open http://localhost:5173

## Testy
Szybki start:
- `npm run test` - tryb watch (czeka na zmiany plikow)
- `npm run test:run` - jednorazowy run
- `npm run test:report` - generuje raport HTML + coverage
- `npm run test:ui` - UI testow w przegladarce
- `npm run report:open` - uruchamia raport w przegladarce
- `npm run help` - lista wszystkich komend z opisem

Raporty HTML:
- `reports/vitest/index.html`
- `reports/vitest/coverage/index.html`

## Where things live
- **styles.css** — all styles and design tokens
- **js/config.js** — API base URL and write token
- **js/icons.js** — inline SVG for categories + `iconFor()`
- **js/utils.js** — `fmtDate()` and `bust()` anti-cache helper
- **js/state.js** — shared in-memory `DATA` + setter
- **js/api.js** — `fetchData()`, `markDone()` and boot debug
- **js/render.js** — KPI calc, card templating, and diff-render loop
- **js/main.js** — wire-up events and kick-off

## Jak odpalić projekt lokalnie

1. Zainstaluj zależności:

```bash
npm install
```

2. Upewnij się że masz plik `.env.development` w głównym folderze projektu z linią:

```bash
VITE_GIOS_BASE=/gios
```

To jest baza URL dla proxy do API GIOŚ.

3. Odpal serwer deweloperski:

```bash
npm run dev
```

To uruchamia Vite w trybie dev, razem z proxy `/gios -> https://api.gios.gov.pl`. Po starcie wejdź w przeglądarce na adres podany w konsoli (najczęściej [http://localhost:5173](http://localhost:5173)).

4. Build produkcyjny (statyczne pliki do `dist/`):

```bash
npm run build
```

5. Podgląd builda:

```bash
npm run preview
```

Uwaga: `npm run preview` nie ma dev proxy. Kafelek jakości powietrza (`AQI`) nie pobierze danych z `/gios/...` jeśli nie ustawisz zewnętrznego proxy (np. Cloudflare Worker) i nie ustawisz `VITE_GIOS_BASE` na jego adres w `.env.production`.

### Debug szybkiego requestu AQI

W trybie dev możesz sprawdzić czy proxy działa wpisując w konsoli przeglądarki:

```js
fetch('/gios/pjp-api/v1/rest/aqindex/getIndex/400')
  .then(r => r.json())
  .then(console.log)
```

Jeśli dostajesz JSON i tam jest `"Nazwa kategorii indeksu": "Umiarkowany"` to działa.
