# Reading Local API

Reading Dashboard przechowuje dane kanoniczne w `data/reading.sqlite`. Frontend
korzysta z tego samego kontraktu HTTP, ktory w przyszlosci moze obslugiwac lekka
aplikacje na Androida.

## Endpointy

| Metoda | Sciezka | Zastosowanie |
| --- | --- | --- |
| `GET` | `/api/reading/state` | Ksiazki, aktywne ksiazki, dzienne statystyki i ustawienia w jednym odczycie. |
| `GET` | `/api/reading/books` | Pelna biblioteka i statystyki biblioteki. |
| `POST` | `/api/reading/books` | Dodanie ksiazki. |
| `PATCH` | `/api/reading/books/<id>/progress` | Zmiana aktualnej strony. |
| `GET` / `POST` | `/api/reading/history` | Odczyt lub zapis calego kanonicznego dziennika czytania. |
| `GET` / `POST` | `/api/reading/settings` | Odczyt lub zapis map aktywnosci, wlasnosci i wyboru ksiazki. |

`PATCH .../progress` przyjmuje `pageCurrent`, opcjonalne `day` (`YYYY-MM-DD`) i
`recordHistory`. Domyslnie `recordHistory` ma wartosc `true`, dzieki czemu przyszly
klient mobilny moze atomowo zmienic strone i dopisac dzienny postep. Obecny frontend
przekazuje `false`, poniewaz zachowuje dotychczasowa, bardziej rozbudowana logike
wyliczania historii oraz funkcje Undo, a nastepnie zapisuje wynik przez endpoint
historii.

## Dostep z telefonu

Serwer domyslnie nasluchuje tylko na `127.0.0.1`. W sieci lokalnej nalezy ustawic
`DASHBOARD_HOST` na adres interfejsu lub `0.0.0.0`. Zapisy spoza lokalnego procesu
wymagaja naglowka `Authorization: Bearer <DASHBOARD_WRITE_TOKEN>` albo
`X-Dashboard-Token`. Token powinien byc losowy i pozostac poza repozytorium.

Android nie powinien bezposrednio otwierac pliku SQLite. Warstwa HTTP jest granica
systemu: pozwala pozniej dodac uwierzytelnianie, wersjonowanie i rozwiazywanie
konfliktow bez zmiany schematu aplikacji desktopowej.

## Kopie zapasowe

Przed kopiowaniem dzialajacej bazy najlepiej zatrzymac serwer albo wykonac backup
przez mechanizm SQLite. Przy zwyklym kopiowaniu nalezy uwzglednic rowniez pliki
`reading.sqlite-wal` i `reading.sqlite-shm`, jesli istnieja.
