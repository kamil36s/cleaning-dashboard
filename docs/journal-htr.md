# OCR dziennika — lokalny eScriptorium/Kraken

## Zakres, prywatność i architektura

Moduł digitalizuje polskie, angielskie i mieszane rękopisy. Oryginały, kopie
robocze, transkrypcje, rewizje i modele pozostają lokalne. Kod nie wywołuje
zewnętrznych usług AI ani nie zapisuje tokenu lub treści dziennika w logach.
Gdy `HTR_ENABLED=false`, pozostały dashboard działa normalnie.

```text
index.html / journal-ocr.html
          │  /api/journal-htr/*
          ▼
server.py + JournalHtrService
          ├── data/journal-htr/journal-htr.sqlite
          ├── data/journal-htr/originals + working
          └── HtrProvider
                 ▼
          eScriptorium 26.04 REST API
                 ▼
          Celery + Kraken 7.x
```

Dashboard ma lekką kolejkę dla uploadu, wywołań providera i synchronizacji.
Długie zadania segmentacji, recognition i treningu są kolejkowane przez
eScriptorium/Celery; frontend używa pollingu.

## Przypięte wersje i API

- eScriptorium i jego nginx: obrazy `26.04`;
- Kraken: linia `7.x` zawarta w eScriptorium 26.04;
- PostgreSQL: linia 15; Redis: linia 7.

Adapter został sprawdzony względem oficjalnego tagu `26.04` (commit
`d7dcfc642899500cdd5737404971ba474eca8852`). Używa stabilnych tras:

- `GET /api/`;
- `POST /api/documents/`;
- `POST /api/documents/{document}/parts/`;
- `POST /api/documents/{document}/import/` dla PDF;
- `POST /api/documents/{document}/segment/`;
- `POST /api/documents/{document}/transcribe/`;
- `GET /api/documents/{document}/parts/{part}/lines/`;
- `GET/PATCH /api/documents/{document}/parts/{part}/transcriptions/…`;
- `POST /api/documents/{document}/train/` i `segtrain/`;
- `GET /api/tasks/`, `GET /api/models/`;
- `POST /api/documents/{document}/export/`.

eScriptorium nie ma pojęcia jednego aktywnego modelu; aktywacja jest stanem
lokalnym dashboardu i zawsze wymaga ręcznej decyzji.

Źródła: [API eScriptorium](https://escriptorium.readthedocs.io/en/latest/api/),
[wydanie 26.04](https://gitlab.com/scripta/escriptorium/-/releases),
[zmiany Krakena 7](https://kraken.re/main/changelog.html).

Kraken 7 zmienił API treningowe i inferencyjne, przeniósł trening do
`kraken.train`, wprowadził typowane klasy konfiguracji i zmienił argumenty
manifestów. Dashboard nie uruchamia starych poleceń `ketos` ani nie przekazuje
niesprawdzonych parametrów CLI.

## Uruchamianie i wyłączanie

Uruchom dashboard jak dotychczas:

```powershell
start-dev.cmd
```

Dashboard nie uruchamia Dockera ani OCR podczas zwykłego startu. Na widżecie
„OCR dziennika” kliknij **Uruchom serwer** dopiero wtedy, gdy chcesz pracować
z rękopisem. Widżet pokazuje postęp, a po zakończeniu udostępnia przyciski
**Otwórz** i **Wyłącz serwer**.

Przy pierwszym uruchomieniu `scripts/journal_htr_bootstrap.py`:

- generuje prywatne sekrety;
- uruchamia kontenery na porcie 8081;
- wykonuje migracje;
- tworzy lokalnego administratora, token API i projekt;
- pobiera i importuje startowy model pisma;
- włącza moduł w `.env.development`.

Kolejne uruchomienia korzystają z zapisanej konfiguracji i pomijają pełny
provisioning oraz migracje. Wyłączenie z widżetu zatrzymuje kontenery przez
`docker compose stop`, ale zachowuje bazę, modele, pliki i wolumeny.

Nie trzeba ręcznie edytować plików `.env`. Jeżeli firmware ma wyłączone
AMD-V/SVM, upload i lokalny zapis nadal działają, a OCR dokończy provisioning
przy kolejnym kliknięciu **Uruchom serwer** po włączeniu wirtualizacji.

## Zmienne środowiskowe

| Zmienna | Znaczenie |
| --- | --- |
| `HTR_ENABLED` | Włączenie/wyłączenie modułu |
| `HTR_PROVIDER` | `escriptorium`; `fake` wyłącznie w testach |
| `ESCRIPTORIUM_BASE_URL` | Lokalny adres, zwykle `http://localhost:8080` |
| `ESCRIPTORIUM_API_TOKEN` | Token DRF; nigdy nie commitować |
| `ESCRIPTORIUM_PROJECT_SLUG` | Slug istniejącego projektu |
| `ESCRIPTORIUM_MAIN_SCRIPT` | Skrypt dokumentu, domyślnie `Latin` |
| `HTR_STORAGE_PATH` | Opcjonalny bezwzględny katalog danych |
| `HTR_MAX_UPLOAD_MB` | Limit jednego pliku |
| `HTR_TRAINING_MIN_LINES` | Próg sugestii pierwszego treningu |
| `HTR_RETRAIN_AFTER_NEW_LINES` | Próg sugestii kolejnej wersji |

## Model bazowy

Zaimportuj model w lokalnym eScriptorium (`Models → Upload model`). eScriptorium
waliduje plik i jego typ. Następnie kliknij „Synchronizuj” na stronie OCR.
Dashboard nie zakłada, że odpowiedni model jest automatycznie dostępny.

## Workflow

1. Dodaj JPG/PNG/TIFF lub PDF. Data systemowa pliku nie staje się datą wpisu.
2. Oryginał pozostaje bez zmian; kopia robocza traci EXIF, jeśli jest Pillow.
3. Zaznacz strony, uruchom segmentację, po jej zakończeniu synchronizuj.
4. Popraw geometrię w eScriptorium i uruchom transkrypcję.
5. Synchronizuj, popraw tekst linia po linii i oznacz ground truth.
6. Utwórz dataset. Podział jest wykonywany według stron, a test pozostaje stały.
7. Uruchom trening; kandydat nie zostanie automatycznie aktywowany.
8. Oceń model i ręcznie wybierz wersję.
9. Zaznacz kompletne strony i utwórz wpis w Dzienniku.

Nie poprawiaj błędów autora ani nie zgaduj. Linie `uncertain`, `illegible` i
`excluded` są domyślnie wyłączone z treningu.

## Dane, migracje i backup

SQLite jest migrowany idempotentnie przy starcie (`CREATE TABLE IF NOT EXISTS`).
Są klucze obce z `ON DELETE CASCADE` i indeksy statusów/kolejek. Projekt nie
używa ORM.

Backup obejmuje:

- cały `data/journal-htr/` lub `HTR_STORAGE_PATH`;
- wolumeny Compose `htr-media` i `htr-postgres`;
- eksportowane artefakty modeli.

```powershell
docker run --rm -v cleaning-dashboard-htr_htr-media:/source:ro -v ${PWD}/backup:/backup alpine tar czf /backup/htr-media.tgz -C /source .
```

Przed aktualizacją zrób backup, przeczytaj release notes eScriptorium i Kraken,
zmień jeden przypięty tag, wykonaj migracje, a potem sprawdź upload, segmentację,
transkrypcję oraz odczyt istniejącego modelu.

## Typowe błędy

- **HTR wyłączony** — ustaw `HTR_ENABLED=true` i zrestartuj backend.
- **Brak tokenu / 401** — wygeneruj token ponownie.
- **eScriptorium offline** — sprawdź `docker compose ... ps` i logi usług.
- **Brak modelu** — importuj `.mlmodel` w eScriptorium i synchronizuj.
- **Brak miejsca** — przenieś `HTR_STORAGE_PATH` lub zwolnij miejsce.
- **Model niezgodny z Krakenem 7** — użyj modelu zgodnego z Krakenem 7;
  dashboard nie omija walidacji eScriptorium.
- **Strona pozostaje `segmenting`/`transcribing`** — sprawdź zadanie w
  eScriptorium i kliknij „Synchronizuj”.

## Jawne ograniczenia

- własny edytor geometrii, crop, deskew, perspektywa, kontrast i redukcja cieni
  są oznaczone jako niedostępne; geometrię poprawia się w eScriptorium;
- nie ma jeszcze lokalnego workera ewaluacyjnego Kraken, więc dashboard nie
  uruchamia inference kandydata na stałym teście; CER/WER mają przetestowane
  funkcje obliczeniowe, ale promocja bez metryk pozostaje ręczna;
- import modelu odbywa się bezpośrednio w eScriptorium;
- PDF trafia do stabilnego importera eScriptorium; lokalnie ma jeden rekord
  źródłowy do czasu synchronizacji jego części.

## Wyłączenie

Do codziennego wyłączania użyj przycisku **Wyłącz serwer** na widżecie. Jako
awaryjny odpowiednik z terminala możesz zatrzymać kontenery bez utraty danych
poleceniem:

```powershell
python scripts/journal_htr_bootstrap.py --stop
```

`docker compose -f docker-compose.htr.yml down -v` trwale usuwa wolumeny i
powinno być użyte dopiero po backupie.
