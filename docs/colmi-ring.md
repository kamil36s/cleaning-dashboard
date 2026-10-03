# COLMI Ring — automatyczny lokalny collector BLE

## Zakres i izolacja

Moduł jest celowo odseparowany od Zdrowia, The Great Timeline i pozostałych aplikacji:

`COLMI R10 → BLE → ring_collector.py → data/ring.sqlite → /api/ring/* → ring.html`

Tabele ringa pozostają odseparowane od pozostałych danych zdrowotnych. Historia HR odczytuje je jednak jako źródło zapasowe: smartwatch ma priorytet w każdej minucie, a COLMI uzupełnia wyłącznie minuty bez próbki zegarka. Połączenie jest własnością procesu `server.py`, nie karty przeglądarki. Zamknięcie strony nie zatrzymuje synchronizacji historii.

Implementacja używa `bleak` i natywnego stosu Bluetooth WinRT. Ramki i UUID są oparte na dokumentacji [openring](https://github.com/robinojw/openring), [colmi_r02_client](https://tahnok.github.io/colmi_r02_client/colmi_r02_client/client.html) oraz [colmi-docs](https://colmi.puxtril.com/commands/). QRing, konto i chmura nie są potrzebne.

## Instalacja i start na Windows

W PowerShell, w katalogu projektu:

```powershell
py -m pip install -r requirements-ring.txt
npm run dev:all
```

Otwórz `http://localhost:5173/cleaning-dashboard/ring.html` albo kliknij **COLMI Ring** w sekcji **Zdrowie** po lewej stronie dashboardu.

Wymagania:

- Windows 10/11 z Bluetooth LE;
- włączony Bluetooth Windows;
- zamknięty QRing i wyłączone jego automatyczne łączenie w telefonie;
- ring nie musi być ręcznie parowany w panelu Windows.

## Jak działa automatyka

Po uruchomieniu backendu collector:

1. rozpoczyna skan BLE i wyszukuje wcześniej zapamiętany ring;
2. po znalezieniu łączy się bez kliknięcia oraz zachowuje uchwyt `BLEDevice` ze skanu;
3. ustawia zegar, odczytuje baterię i włącza okresowy pomiar HR co 5 minut;
4. pobiera znaną historię HR i aktywności z ostatnich 7 dni oraz całą historię snu i SpO₂ zwróconą przez kanał Big Data;
5. powtarza synchronizację co 15 minut;
6. po zerwaniu połączenia skanuje i łączy się ponownie z opóźnieniem rosnącym od 5 sekund do maksymalnie 5 minut.

Otwarta i widoczna strona Ring wysyła heartbeat do collectora. Wtedy collector dodatkowo wykonuje cykle realtime HR i SpO₂ mniej więcej raz na minutę i od razu zapisuje poprawne próbki. Po zamknięciu strony realtime się zatrzymuje, żeby nie męczyć baterii i diod sensora; synchronizacja historii nadal działa w tle.

Przyciski **Synchronizuj teraz**, skanowanie i ręczne połączenie pozostają wyłącznie jako narzędzia awaryjne. Normalnie nie trzeba ich używać.

Ustawienia opcjonalne przez zmienne środowiskowe:

- `RING_SYNC_INTERVAL_SECONDS` — domyślnie `900`, minimum `300`;
- `RING_HISTORY_DAYS` — domyślnie `7`, zakres `1–30`;
- `RING_HR_INTERVAL_MINUTES` — domyślnie `5`, zakres `1–60`;
- `RING_LIVE_CYCLE_SECONDS` — domyślnie `60`, minimum `30`.

## Zapisywane dane

Trwała baza trybu real to `data/ring.sqlite`. Każda ponowna synchronizacja używa kluczy deduplikacji, dlatego ten sam rekord nie jest dopisywany drugi raz. Czasy kanoniczne są przechowywane w UTC, a sloty zależne od lokalnego dnia są rekonstruowane w `Europe/Warsaw` z DST.

Tabele:

- `devices` — wybrany ring, bateria, wersje i czasy połączeń;
- `heart_rate` — automatyczna historia i próbki realtime;
- `spo2` — realtime oraz eksperymentalna historia Big Data;
- `activity` — natywne sloty kroków, dystansu i kalorii;
- `hrv` — eksperymentalna wartość/proxy podana przez firmware;
- `sleep_nights`, `sleep_segments` — noce i kolejne przedziały awake/light/deep/REM;
- `sync_runs`, `ble_packets`, `collector_events` — synchronizacje i pełna diagnostyka RX/TX.

Status protokołu:

- stabilne: bateria, zegar, ustawienia i historia HR, realtime HR, realtime SpO₂, aktywność;
- eksperymentalne: sen Big Data `0x27`, historia SpO₂ `0x2A`, firmware'owe HRV proxy;
- nieznane i niewyświetlane jako pomiary: stres, surowe PPG, surowy akcelerometr.

„Wszystkie dane” oznaczają wszystkie poprawnie zdekodowane rekordy, które ring zwraca przez znane komendy. Aplikacja zachowuje surowe ramki diagnostyczne, ale nie wymyśla znaczenia nieznanych pól. HRV nie jest nazywane RMSSD bez potwierdzonych odstępów R–R.

## API

- `GET /api/ring/state`;
- `GET /api/ring/history?limit=2000`;
- `GET /api/ring/capabilities`;
- `GET /api/ring/diagnostics?limit=100`;
- `POST /api/ring/presence` — heartbeat widocznego UI;
- `POST /api/ring/scan`;
- `POST /api/ring/connect`;
- `POST /api/ring/disconnect`;
- `POST /api/ring/sync`.

## Gdy coś się zepsuje

UI pokazuje automatyczny stan oraz konkretną podpowiedź dla ostatniego błędu. Collector sam ponawia próby. Najczęściej wystarczy:

1. zbliżyć lub doładować ring;
2. zamknąć QRing w telefonie;
3. sprawdzić Bluetooth Windows;
4. jeśli błąd trwa — uruchomić ponownie `npm run dev:all`;
5. skopiować ostatnie zdarzenia i pakiety z zakładki **Diagnostyka**.

## Tryb MOCK

Mock używa osobnej bazy `data/ring-mock.sqlite` i nigdy nie włącza się sam po błędzie prawdziwego urządzenia:

```powershell
$env:RING_COLLECTOR_MODE = "mock"
npm run dev:all
```

Do prawdziwego BLE wrócisz po usunięciu tej zmiennej albo ustawieniu jej na `real` i ponownym uruchomieniu stosu.

## Android jako mostek BLE

Przy słabym sygnale Bluetooth komputera właściwa aplikacja `C:\Users\kamil\AndroidStudioProjects\DashboardHabits` może przejąć połączenie z ringiem. Telefon utrzymuje foreground service, zapisuje surowe RX/TX oraz rozpoznane pomiary do lokalnego SQLite i wysyła kolejkę do `POST /api/ring/phone/ingest` dopiero po osiągnięciu dashboardu przez Wi-Fi.

Telefon sprawdza świeżość HR smartwatcha. Gdy zegarek przestaje dostarczać próbki, przełącza automatyczny harmonogram COLMI na pomiar co 1 minutę; po powrocie zegarka wraca do oszczędnego interwału 5 minut. Historia HR nadal odrzuca każdą próbkę ringa z minuty, w której istnieje próbka smartwatcha.

Serwer potwierdza każde zewnętrzne ID, zapisuje surowe ramki z transportem `android-ble` i deduplikuje pomiary. Aktywny heartbeat telefonu pauzuje bezpośrednie BLE komputera; po 20 minutach ciszy PC znów próbuje być fallbackiem.

To jest aktualizacja istniejącej aplikacji z tym samym `applicationId` (`com.cleaningdashboard.dashboardhabits`), a nie osobna aplikacja. W Android Studio wybierz wariant `lanDebug` i użyj zwykłego **Run**. Z terminala odpowiednikiem jest:

```powershell
cd C:\Users\kamil\AndroidStudioProjects\DashboardHabits
.\gradlew.bat assembleLanDebug
```

Przy pierwszym uruchomieniu po aktualizacji wejdź w **Settings → COLMI R10**, nadaj dostęp do urządzeń w pobliżu i zamknij QRing. Później aplikacja sama startuje, skanuje, łączy się ponownie i opróżnia bufor po Wi-Fi.
