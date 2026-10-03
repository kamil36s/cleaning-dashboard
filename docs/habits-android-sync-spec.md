# Habits App: Android + dashboard + synchronizacja

## Co jest gotowe w dashboardzie

Widget `habits-app` jest podłączony do działającego backendu w `server.py` i centralnej bazy `data/habits.sqlite`. Obsługuje:

- 27 obecnych nawyków, ich typy, jednostki, kolory i kolejność;
- widok siedmiu dni, filtrowanie i wyszukiwanie;
- wpisy binarne oraz liczbowe;
- score, streak i prostą historię wybranego nawyku;
- optymistyczne zmiany i trwałą kolejkę awaryjną w `localStorage` pod kluczem `habits.app.preview-mutations.v1`;
- push/pull przez `/api/habits/sync`, rewizje, ACK, idempotencję, konflikty i stronicowany change-log;
- wspólne dane dashboardu i aplikacji Android;
- import startowy 27 nawyków i 9679 wpisów z eksportu Loop.

Centralnym źródłem wymiany jest teraz SQLite backendu. `localStorage` służy tylko jako krótkotrwały outbox dashboardu podczas braku połączenia.

## Docelowa architektura

```text
Android UI (Compose)                 Dashboard UI
          |                               |
          v                               v
Android Repository + Room          wspólny REST client
          |                               |
          +---------- REST/JSON ----------+
                          |
                          v
             Dashboard Habits API + SQLite
                   (źródło centralne)
```

Android ma działać offline. Room jest jego lokalnym źródłem prawdy, a UI czyta wyłącznie `Flow` z Room. Każda zmiana najpierw trafia w jednej transakcji do tabeli wpisów i outboxa, więc nie ginie bez internetu. WorkManager wysyła outbox i pobiera zmiany z serwera po odzyskaniu sieci.

Dashboardowy backend jest centralnym źródłem wymiany między urządzeniami. Dashboard i telefon nie synchronizują się przez pliki `.db`, współdzielony folder ani bezpośrednie nadpisywanie baz SQLite.

## Tryb docelowy: synchronizacja tylko w tym samym Wi-Fi

Tak, podstawowy scenariusz zakłada brak chmury. Telefon synchronizuje się bezpośrednio z API uruchomionym na PC, kiedy oba urządzenia są podłączone do tej samej sieci lokalnej:

```text
Telefon Android                           PC z dashboardem
Room + outbox                             Habits API + SQLite
      |                                         |
      +---- domowe Wi-Fi / LAN, REST/JSON ------+
             http://192.168.0.136:8000
```

Internet nie jest do tego potrzebny. Gdy telefon jest poza domowym Wi-Fi, PC jest wyłączony albo API nie odpowiada, aplikacja nadal zapisuje wszystko do Room i pozostawia mutacje w outboxie. Po ponownym pojawieniu się osiągalnego PC na tej samej sieci wykonuje push i pull.

### Wymagania po stronie PC

- Backend musi nasłuchiwać na interfejsie LAN, czyli `0.0.0.0:8000`, a nie wyłącznie `127.0.0.1:8000`.
- Telefon używa obecnie adresu LAN komputera `http://192.168.0.136:8000`. `localhost` i `127.0.0.1` na telefonie oznaczają telefon, nie PC.
- Najprostsza stabilna konfiguracja to rezerwacja adresu DHCP dla PC w routerze. Wtedy adres nie zmienia się po restarcie.
- Zapora Windows ma zezwalać na przychodzący TCP port `8000` wyłącznie dla profilu **Private**, nigdy dla profilu Public. Przykładowa komenda uruchomiona jako administrator:

```powershell
New-NetFirewallRule -DisplayName "Cleaning Dashboard Habits LAN 8000" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8000 -RemoteAddress LocalSubnet -Profile Private
```

- API udostępnia lekki endpoint `GET /api/habits/health`, który nie zwraca prywatnych danych:

```json
{
  "ok": true,
  "service": "cleaning-dashboard-habits",
  "schemaVersion": 1,
  "deviceName": "Cleaning Dashboard PC"
}
```

- Publiczny endpoint health nie zwraca prywatnych danych i można go otworzyć bez tokenu. Prywatne endpointy `/api/habits/snapshot` i `/api/habits/sync` zawsze wymagają poprawnego Bearer tokenu dla klienta spoza dashboardu.
- Sieć gościnna lub opcja routera „AP/client isolation” może blokować komunikację między urządzeniami mimo tego samego SSID. Oba urządzenia muszą być w sieci, która pozwala klientom LAN komunikować się ze sobą.

### Zachowanie aplikacji Android

- Ustawienie **Synchronizuj tylko przez Wi-Fi** jest domyślnie włączone.
- Worker przed requestem sprawdza przez `ConnectivityManager`, czy aktywna sieć ma `TRANSPORT_WIFI`. Sama dostępność internetu nie wystarcza.
- Po przejściu z LTE na Wi-Fi, otwarciu aplikacji, lokalnej edycji oraz ręcznym odświeżeniu aplikacja enqueue'uje unikalną pracę `habits-sync`.
- Następnie aplikacja sprawdza `GET /api/habits/health` z krótkim timeoutem. Dopiero po poprawnej odpowiedzi wykonuje `/api/habits/sync`.
- Nieosiągalny host, timeout lub wyłączony PC nie są konfliktem ani utratą danych. Status brzmi `PC niedostępny · N zmian czeka`, a worker stosuje backoff.
- Status `Synced` wolno pokazać wyłącznie po prawidłowej odpowiedzi API i atomowym zapisaniu ACK, zmian oraz cursora w Room.
- Aplikacja przechowuje ostatni działający URL, ale użytkownik może zmienić go w Settings i uruchomić `Test connection`.
- Dla fizycznego telefonu nie używamy `10.0.2.2`; ten specjalny adres dotyczy wyłącznie emulatora Androida.

### Adres IP a automatyczne wykrywanie

W wersji pierwszej używamy ręcznie wpisanego, zarezerwowanego adresu IP. To jest prostsze i bardziej przewidywalne. Opcjonalny etap późniejszy może dodać mDNS/DNS-SD:

- PC ogłasza usługę `_habits-dashboard._tcp` z portem `8000`;
- Android wyszukuje ją przez `NsdManager`;
- znaleziony adres zawsze musi przejść `GET /api/habits/health` i weryfikację `service` oraz `schemaVersion`;
- ręczny URL pozostaje fallbackiem.

### Uprawnienia Androida dla LAN

- Aplikacja deklaruje `INTERNET` i `ACCESS_NETWORK_STATE`.
- Jeśli projekt targetuje Android 17 / API 37 lub nowszy, musi również zadeklarować i poprosić w runtime o `ACCESS_LOCAL_NETWORK`. Odmowa nie może blokować działania offline; UI pokazuje wtedy `Brak dostępu do sieci lokalnej`.
- Dla target SDK 36 i starszego nie należy dodawać `ACCESS_LOCAL_NETWORK`; dostęp LAN korzysta z dotychczasowego modelu uprawnień.
- Android 9+ domyślnie blokuje zwykły HTTP. Docelowo preferujemy HTTPS. Jeżeli pierwsza prywatna wersja korzysta z HTTP w LAN, wyjątek cleartext ma istnieć wyłącznie w osobnym wariancie/build flavor `lan`, a kod musi odrzucać publiczne hosty HTTP i zezwalać tylko na prywatne adresy RFC1918 lub zweryfikowaną nazwę `.local`.

## Tożsamość i daty

- `habitId`: stabilny UUID. Obecny eksport nie zawierał użytecznego UUID, dlatego backend wyznaczył deterministyczny UUIDv5 z identyfikatora Loop; kolejne uruchomienia zachowują ten sam identyfikator.
- `entryId`: deterministyczne `${habitId}:${date}` albo osobny UUID z unikalnym indeksem `(habitId, date)`.
- `date`: lokalny dzień w formacie `YYYY-MM-DD`, bez konwersji na UTC. Strefa użytkownika: `Europe/Warsaw`.
- `updatedAt`: pełny timestamp UTC ISO-8601, używany do audytu, nie do wyznaczania dnia.
- wartość liczbowa: `valueMilli` jako liczba całkowita. `150 mg` zapisujemy jako `150000`. To jest zgodne z formatem Loop i eliminuje błędy zmiennoprzecinkowe.
- wpis binarny: `status` równe `DONE`, `MISSED`, `SKIPPED` albo `null`.

## Minimalny model danych

### Habit

```json
{
  "id": "8d4c945f35e04e9c870c12f84d119b56",
  "name": "Don't drink",
  "type": "BINARY",
  "question": "Did you have an alcohol-free day?",
  "description": "",
  "color": "#1976D2",
  "unit": "",
  "targetType": null,
  "targetValueMilli": null,
  "frequencyNumerator": 1,
  "frequencyDenominator": 1,
  "position": 0,
  "archived": false,
  "reminder": { "hour": 20, "minute": 0, "daysMask": 127 },
  "revision": 4,
  "updatedAt": "2026-08-25T16:40:00Z",
  "deletedAt": null
}
```

### HabitEntry

```json
{
  "id": "8d4c945f35e04e9c870c12f84d119b56:2026-08-25",
  "habitId": "8d4c945f35e04e9c870c12f84d119b56",
  "date": "2026-08-25",
  "status": "DONE",
  "valueMilli": null,
  "note": null,
  "revision": 7,
  "updatedAt": "2026-08-25T16:42:10Z",
  "deletedAt": null
}
```

Wpis liczbowy ma `status: null` i ustawione `valueMilli`. Usunięcie wpisu jest tombstonem (`deletedAt`), a nie natychmiastowym fizycznym kasowaniem.

## Kontrakt synchronizacji v1

Jeden endpoint obsługuje push i pull:

```http
POST /api/habits/sync
Authorization: Bearer <token>
Content-Type: application/json
```

Żądanie:

```json
{
  "schemaVersion": 1,
  "deviceId": "android-9ee61c2e-...",
  "lastPulledCursor": "1842",
  "mutations": [
    {
      "mutationId": "cf0dfb69-...",
      "entityType": "ENTRY",
      "entityId": "8d4c...:2026-08-25",
      "operation": "UPSERT",
      "baseRevision": 6,
      "clientUpdatedAt": "2026-08-25T16:42:08Z",
      "payload": {
        "habitId": "8d4c...",
        "date": "2026-08-25",
        "status": "DONE",
        "valueMilli": null,
        "note": null
      }
    }
  ],
  "limit": 500
}
```

Odpowiedź:

```json
{
  "schemaVersion": 1,
  "serverTime": "2026-08-25T16:42:11Z",
  "nextCursor": "1855",
  "hasMore": false,
  "acknowledgedMutationIds": ["cf0dfb69-..."],
  "changes": [
    {
      "cursor": "1855",
      "entityType": "ENTRY",
      "operation": "UPSERT",
      "entity": {
        "id": "8d4c...:2026-08-25",
        "habitId": "8d4c...",
        "date": "2026-08-25",
        "status": "DONE",
        "valueMilli": null,
        "note": null,
        "revision": 7,
        "updatedAt": "2026-08-25T16:42:10Z",
        "deletedAt": null
      }
    }
  ],
  "conflicts": []
}
```

Wymagania serwera:

- `mutationId` ma unikalny indeks. Ponowne wysłanie tego samego żądania zwraca ten sam ACK i nie duplikuje zmiany.
- Każda zaakceptowana zmiana zwiększa `revision` encji i globalny, monotoniczny `cursor` change-logu.
- Zmiana jest przyjmowana, jeśli `baseRevision` zgadza się z bieżącą rewizją albo encja jeszcze nie istnieje i `baseRevision` jest `null`/`0`.
- Przy różnicy rewizji serwer nie nadpisuje danych po cichu. Zwraca konflikt z wersją lokalną i serwerową.
- Klient zapisuje ACK, zmiany i nowy cursor w jednej transakcji Room. Dopiero potem usuwa potwierdzone elementy outboxa.
- Gdy `hasMore` jest `true`, klient od razu wykonuje następny pull z `nextCursor`, ale nie wysyła drugi raz potwierdzonych mutacji.

### Konflikt

```json
{
  "mutationId": "cf0dfb69-...",
  "entityType": "ENTRY",
  "entityId": "8d4c...:2026-08-25",
  "reason": "REVISION_MISMATCH",
  "clientEntity": { "status": "DONE", "baseRevision": 6 },
  "serverEntity": { "status": "MISSED", "revision": 7 }
}
```

Android zapisuje konflikt lokalnie i pokazuje użytkownikowi wybór „zachowaj z telefonu” / „zachowaj z serwera”. Wybranie telefonu tworzy nową mutację z `baseRevision` równym aktualnej rewizji serwera. Dzięki temu konflikt nie wpada w pętlę.

## Kiedy uruchamiać synchronizację

- po otwarciu aplikacji;
- po ręcznym „Synchronizuj” / pull-to-refresh;
- jako `OneTimeWorkRequest` po lokalnej edycji;
- po podłączeniu telefonu do Wi-Fi;
- okresowo, ale tylko przy aktywnym Wi-Fi i osiągalnym PC;
- po zmianie adresu API lub tokenu.

Nie blokujemy UI na czas sieci. Zapis lokalny ma być natychmiastowy, a nagłówek pokazuje: ostatni udany sync, liczbę oczekujących zmian i ewentualny błąd.

## Konfiguracja i bezpieczeństwo

- Adres API oraz token ustawia się na ekranie Settings. Dla tego komputera jest to `http://192.168.0.136:8000`, nigdy `localhost`.
- Domyślnie synchronizacja jest ograniczona do Wi-Fi. Połączenie LTE/5G nie próbuje wysyłać danych do prywatnego adresu LAN.
- Token nie trafia do Git, `BuildConfig` ani logów. Na urządzeniu należy go przechowywać przez Android Keystore / szyfrowane lokalne ustawienia.
- Nawet w domowym LAN żądania wymagają Bearer tokenu. Sam fakt bycia w tej samej sieci nie jest autoryzacją.
- Poza zaufanym LAN używamy HTTPS, najlepiej przez prywatną sieć typu Tailscale. Nie wystawiamy dashboardu bezpośrednio do internetu.
- Logi nie mogą zawierać tokenu ani pełnych odpowiedzi z prywatną historią.

## Jak pracować z Gemini w Android Studio

1. Utwórz nowy projekt **Empty Activity** z Kotlinem i Jetpack Compose. Zostaw bieżące `minSdk` i wersje zaproponowane przez Android Studio.
2. Uruchom pustą aplikację raz na telefonie.
3. Wklej do Gemini cały prompt z następnej sekcji.
4. Pozwól Gemini najpierw wypisać plan i listę plików. Potem każ mu realizować etapy po kolei, uruchamiając build/test po każdym etapie.
5. Jeśli Gemini chce „uprościć” synchronizację przez bezpośrednie wysyłanie z ViewModelu, przerwij i przypomnij: Room jest źródłem prawdy, a zapis UI i outbox muszą powstać atomowo.
6. Do pierwszego uruchomienia pozostaw pusty URL API. Aplikacja ma w pełni działać offline i wyświetlać jawny status „API not configured”.

## Gotowy prompt do Gemini

```text
Zbuduj w tym projekcie kompletną prywatną aplikację Android „Habits”, inspirowaną układem Loop Habit Tracker, ale napisaną od zera. Pracuj bez usuwania istniejących plików i bez zgadywania działającego backendu. Najpierw przeanalizuj projekt, wypisz krótki plan i listę plików, a następnie implementuj etapami. Po każdym etapie uruchom build oraz testy i napraw błędy.

TECHNOLOGIE I ARCHITEKTURA
- Kotlin, Jetpack Compose i Material 3.
- Zachowaj minSdk i wersje ustawione przez bieżący Android Studio. Zależności dodawaj przez version catalog; wybieraj aktualne stabilne wydania kompatybilne z projektem.
- Architektura offline-first: UI -> ViewModel -> HabitsRepository -> Room. UI i ViewModel nie mogą czytać bezpośrednio z Retrofit ani z DAO.
- Room jest jedynym lokalnym źródłem prawdy. Repository wystawia Flow/StateFlow. Compose używa collectAsStateWithLifecycle.
- Sieć: Retrofit + OkHttp + kotlinx.serialization (albo istniejący spójny stos projektu, jeśli już jest).
- Synchronizacja trwała: WorkManager + CoroutineWorker, constraint NETWORK_CONNECTED, unikalna praca „habits-sync”.
- Bez Hilt, jeśli projekt go jeszcze nie ma; zastosuj mały AppContainer/manual DI, żeby ograniczyć złożoność.

MODEL ROOM
Utwórz encje HabitEntity, HabitEntryEntity, OutboxMutationEntity, SyncStateEntity i SyncConflictEntity oraz DAO i migracje.

HabitEntity:
id String UUID primary key, name, type BINARY|NUMERIC, question, description, colorHex, unit, targetType nullable, targetValueMilli Long nullable, frequencyNumerator Int, frequencyDenominator Int, position Int, archived Boolean, reminderHour nullable, reminderMinute nullable, reminderDaysMask Int, revision Long, updatedAt String UTC, deletedAt nullable.

HabitEntryEntity:
id String primary key; wyliczaj jako "habitId:YYYY-MM-DD"; habitId foreign key; date String YYYY-MM-DD; status DONE|MISSED|SKIPPED nullable; valueMilli Long nullable; note nullable; revision Long; updatedAt String UTC; deletedAt nullable. Dodaj unikalny indeks (habitId, date).

OutboxMutationEntity:
mutationId UUID primary key, entityType HABIT|ENTRY, entityId, operation UPSERT|DELETE, baseRevision nullable, payloadJson, clientUpdatedAt, attemptCount, lastError nullable, createdAt.

SyncStateEntity:
singleton id=1, deviceId stabilny UUID, lastPulledCursor nullable, lastSuccessfulSyncAt nullable, lastError nullable.

SyncConflictEntity:
id UUID, mutationId, entityType, entityId, clientJson, serverJson, reason, createdAt.

DATY I WARTOŚCI
- Dzień nawyku to java.time.LocalDate w strefie Europe/Warsaw i w JSON ma format YYYY-MM-DD. Nigdy nie wyznaczaj dnia przez UTC timestamp.
- updatedAt to Instant w UTC.
- Wartość liczbowa jest zawsze Long valueMilli: 150 mg = 150000, 1.5 mg = 1500. UI formatuje i parsuje ją bez użycia Float.
- Binarne wpisy mają status DONE, MISSED, SKIPPED albo brak wpisu. Numeryczne mają valueMilli i status null.

ZAPIS OFFLINE
- Każda edycja z UI w jednej transakcji Room natychmiast aktualizuje wpis/nawyk i dodaje lub zastępuje mutację outboxa dla tej encji.
- UI aktualizuje się natychmiast z Room, bez czekania na sieć.
- Po zapisie enqueue unikalny OneTimeWorkRequest do synchronizacji.
- Ponowne kliknięcie wpisu binarnego przełącza: brak -> DONE -> MISSED -> brak. Dodaj osobną akcję SKIPPED w menu po długim przytrzymaniu.
- Wpis liczbowy otwiera dialog z wartością, jednostką, Save oraz Delete entry.

TRYB LAN: PC I TELEFON W TYM SAMYM WI-FI
- To jest podstawowy tryb synchronizacji. Nie korzystaj z Firebase ani innej chmury.
- API działa na PC. Obecny adres telefonu to http://192.168.0.136:8000. Nigdy nie używaj localhost/127.0.0.1 na fizycznym telefonie. 10.0.2.2 wolno podpowiedzieć wyłącznie dla emulatora.
- Dodaj INTERNET i ACCESS_NETWORK_STATE. Jeśli targetSdk >= 37, zadeklaruj ACCESS_LOCAL_NETWORK, poproś o nie w runtime przed pierwszym połączeniem LAN i obsłuż odmowę bez blokowania trybu offline. Jeśli targetSdk <= 36, nie dodawaj ACCESS_LOCAL_NETWORK.
- W Settings dodaj: API base URL, token, przełącznik „Synchronizuj tylko przez Wi-Fi” domyślnie ON oraz Test connection.
- Przed sync sprawdź przez ConnectivityManager/NetworkCapabilities, że aktywna sieć ma TRANSPORT_WIFI. Gdy nie ma Wi-Fi, nie wykonuj requestu, pozostaw outbox i pokaż „Czekam na Wi-Fi”.
- Test connection i worker najpierw wywołują GET /api/habits/health. Oczekiwany JSON: {"ok":true,"service":"cleaning-dashboard-habits","schemaVersion":1,"deviceName":"Cleaning Dashboard PC"}. Dopiero poprawna odpowiedź pozwala wywołać POST /api/habits/sync.
- Po podłączeniu Wi-Fi enqueue unikalny habits-sync. Użyj obserwacji sieci zgodnej z cyklem życia i WorkManagera; nie utrzymuj wiecznie działającego serwisu.
- Jeśli PC jest wyłączony, port zamknięty albo health timeoutuje, nie usuwaj outboxa i nie pokazuj „Synced”. Pokaż „PC niedostępny · N zmian czeka” i zastosuj backoff.
- Użyj krótkiego connect timeout dla health oraz rozsądnego timeoutu sync. Rozróżnij: brak Wi-Fi, brak uprawnienia LAN, PC nieosiągalny, 401 oraz błąd serwera.
- Android 9+ blokuje cleartext HTTP. Preferuj HTTPS. Dla pierwszej prywatnej wersji LAN utwórz osobny build flavor `lan`, w którym Network Security Config używa `base-config cleartextTrafficPermitted="true"`; wariant standard/release ma cleartext wyłączony. Element `<domain>` nie obsługuje zakresów CIDR, a adres PC jest ustawiany w runtime, dlatego ograniczenie do LAN wykonuj również w kodzie: odrzucaj publiczne hosty HTTP i dopuszczaj wyłącznie RFC1918 (10/8, 172.16/12, 192.168/16), adres emulatora `10.0.2.2` albo zweryfikowany host `.local` rozwiązujący się do adresu lokalnego.
- Opcjonalnie przygotuj interfejs LanServerDiscovery i ręczny URL jako fallback. Nie implementuj mDNS w pierwszym etapie, chyba że cała warstwa bazowa i testy już działają.

API V1
Zaimplementuj SyncApi POST /api/habits/sync z Bearer tokenem. URL i token pochodzą z ekranu Settings. Jeśli nie są ustawione, worker kończy się sukcesem bez requestu, a UI pokazuje „API not configured”; nigdy nie udawaj udanego syncu.

Request:
{
  "schemaVersion":1,
  "deviceId":"stable UUID",
  "lastPulledCursor":"1842 or null",
  "mutations":[{
    "mutationId":"UUID",
    "entityType":"ENTRY",
    "entityId":"habitId:2026-08-25",
    "operation":"UPSERT",
    "baseRevision":6,
    "clientUpdatedAt":"UTC ISO-8601",
    "payload":{"habitId":"UUID","date":"2026-08-25","status":"DONE","valueMilli":null,"note":null}
  }],
  "limit":500
}

Response:
{
  "schemaVersion":1,
  "serverTime":"UTC ISO-8601",
  "nextCursor":"1855",
  "hasMore":false,
  "acknowledgedMutationIds":["UUID"],
  "changes":[{"cursor":"1855","entityType":"ENTRY","operation":"UPSERT","entity":{...pełna encja z revision...}}],
  "conflicts":[{"mutationId":"UUID","entityType":"ENTRY","entityId":"...","reason":"REVISION_MISMATCH","clientEntity":{...},"serverEntity":{...}}]
}

ALGORYTM WORKERA
1. Odczytaj SyncState i maksymalnie 500 mutacji outboxa.
2. Wyślij request. mutationId jest idempotency key i musi pozostać ten sam przy retry.
3. W jednej transakcji Room: zastosuj pełne encje z changes, zapisz konflikty, usuń wyłącznie acknowledgedMutationIds, ustaw nextCursor i lastSuccessfulSyncAt, wyczyść lastError.
4. Jeśli hasMore=true, wykonaj następne pobranie z nextCursor bez ponownego wysyłania już potwierdzonych mutacji.
5. Dla timeout/5xx/IO zwróć Result.retry z backoff. Dla 401/403 zapisz czytelny błąd i Result.failure. Nie retry bez końca błędów 4xx.
6. Nie loguj tokenu ani prywatnej treści wpisów.

KONFLIKTY
- Nie rozwiązuj REVISION_MISMATCH po cichu i nie stosuj last-write-wins na podstawie zegara telefonu.
- Zapisz konflikt i pokaż banner. Ekran konfliktów pozwala wybrać „wersja telefonu” albo „wersja serwera”.
- Wybranie serwera usuwa konflikt i aktualizuje Room wersją serwera.
- Wybranie telefonu tworzy nową mutację z baseRevision równym revision otrzymanym z serwera, po czym usuwa konflikt.

EKRANY
1. Home: ciemny wygląd podobny funkcjonalnie do Loop. App bar „Habits”, przyciski add/filter/settings/sync. Poziomy nagłówek 7 dni z aktualnym dniem po prawej. Każdy wiersz: kolorowy ring, nazwa, siedem klikalnych wpisów. Wartości numeryczne pokazują liczbę i jednostkę. Dodaj filtry Wszystkie/Nawyki/Leki/Suplementy oraz wyszukiwarkę.
2. Habit detail: pytanie, częstotliwość/reminder, score 30/90 dni, current streak, best streak, total, wykres historii, kalendarz/heatmapa 12 tygodni. Obliczenia wykonuj na lokalnych danych Room.
3. Create/Edit Habit: binary lub numeric, nazwa, pytanie, opis, kolor, częstotliwość, jednostka, target, reminder, archiwizacja.
4. Settings: API base URL, token (pole maskowane), przełącznik Wi-Fi only domyślnie ON, przycisk Test connection przez `/api/habits/health`, ręczny Sync now, last successful sync, liczba pending mutations, reverse day order, extend day to 03:00, enable skip days, import/export później oznaczone jako „Not implemented” zamiast atrap.
5. Conflicts: lista i wybór wersji.

STARTOWE DANE
- Nie wpisuj moich prywatnych 27 nawyków na stałe w kod.
- Jeśli Room jest pusty i API nie jest skonfigurowane, pokaż pusty stan i możliwość dodania nawyku.
- Przy pierwszym prawdziwym syncu serwer dostarczy istniejące nawyki wraz z UUID z Loop.

STATUS SYNC
W nagłówku pokaż jedną z wartości: Offline, API not configured, Waiting for Wi-Fi, Local network permission required, PC unavailable, Syncing, Synced <czas>, <N> pending, Unauthorized, Sync error. Przycisk sync uruchamia tę samą unikalną pracę WorkManager. Brak Wi-Fi lub wyłączony PC nie blokują edycji.

BEZPIECZEŃSTWO
- Token przechowuj z użyciem Android Keystore / bezpiecznego lokalnego mechanizmu, nigdy w repo, resources, BuildConfig ani logach.
- Zwykły wariant aplikacji ma wymagać HTTPS. Wyjątek HTTP istnieje wyłącznie w wariancie `lan`; ponieważ Network Security Config nie obsługuje CIDR ani dynamicznego hosta z ustawień, wariant ten używa osobnego `base-config`, a kod bezwzględnie waliduje prywatny/lokalny adres docelowy.

TESTY I KRYTERIA ODBIORU
- Unit tests: konwersja valueMilli, LocalDate Europe/Warsaw także przy DST, cykl statusu binarnego, score/streak, mapowanie DTO, konflikt rewizji.
- DAO/instrumented tests: atomowy zapis entry+outbox, ACK usuwa tylko potwierdzone mutacje, pull stosuje tombstone, cursor aktualizuje się atomowo.
- Worker tests: retry dla IO/5xx, failure dla 401, brak requestu bez konfiguracji, hasMore pobiera kolejne strony.
- Compose UI tests: klik binarny, dialog numeric, filtr, status pending, ekran konfliktu.
- Aplikacja ma zbudować się i działać całkowicie offline. Rotacja i restart procesu nie mogą tracić danych. Nie zostawiaj TODO w krytycznej ścieżce zapisu ani synchronizacji.

Na końcu podaj: listę utworzonych/zmienionych plików, komendy test/build, wynik testów oraz krótką instrukcję ustawienia URL i tokenu. Jeśli jakiegoś API Androida nie jesteś pewien, sprawdź aktualną oficjalną dokumentację Android Developers zamiast zgadywać.
```

## Stan wdrożenia 2026-08-26

- Backend: `habits_store.py`, SQLite `data/habits.sqlite` i trasy `/api/habits/health`, `/api/habits/snapshot`, `/api/habits/sync` są wdrożone.
- Serwer nasłuchuje na `0.0.0.0:8000`; URL telefonu to `http://192.168.0.136:8000`.
- Sekretny token jest ładowany z ignorowanego przez Git `DASHBOARD_HABITS_TOKEN` w `.env.development`.
- Widget dashboardu korzysta z API, wysyła lokalną kolejkę i pokazuje rzeczywisty stan połączenia.
- Backend odrzuca zdalne żądania bez poprawnego Bearer tokenu (`401`).
- Reguła Windows Firewall wymaga jednorazowego wykonania powyższej komendy w PowerShell uruchomionym jako administrator.

## Źródła architektoniczne

- [Android Developers: Build an offline-first app](https://developer.android.com/topic/architecture/data-layer/offline-first)
- [Android Developers: Save data in a local database using Room](https://developer.android.com/training/data-storage/room)
- [Android Developers: Persistent work with WorkManager](https://developer.android.com/develop/background-work/background-tasks/persistent)
- [Android Developers: Local network permission](https://developer.android.com/privacy-and-security/local-network-permission)
- [Android Developers: Network Security Configuration](https://developer.android.com/privacy-and-security/security-config)
- [Android Developers: Network Service Discovery](https://developer.android.com/develop/connectivity/wifi/use-nsd)

## Active/inactive habits and live dashboard (implemented 2026-08-26)

- `archived=true` means inactive, not deleted. Archiving a habit must never delete or rewrite any historical entries.
- Main habit lists on Android and the web show only habits with `archived=false`. Settings/management lists show both active and inactive habits and allow either state to be restored.
- Changing visibility is a normal `HABIT` `UPSERT` using the same habit UUID and revision flow. The backend accepts a partial archive update and preserves all existing habit metadata and entries.
- The web widget polls `POST /api/habits/sync` with an empty mutation list and its current cursor every 3 seconds while the page is visible. When the cursor changes, it reloads the snapshot and renders without a page refresh.
- The 12-week web heatmap is aligned to full Monday-Sunday weeks and includes weekday labels, month labels, an exact date range, and an accessible exact-date/value label for every cell.

## Health Connect steps and Live Workout exclusion (implemented 2026-08-26)

- Steps have three preserved sources: `manual`, `automatic` (Health Connect), and `virtual_walk` (Live Workout). Historical source values are never deleted by an automatic sync.
- A manual value is authoritative for the ordinary-step part of a day. Health Connect is stored separately and becomes the counted ordinary value only when no manual value exists. Virtual-walk steps are always added separately.
- Android reads Health Connect only after the user grants `READ_STEPS`. Automatic sync uses the existing LAN base URL and Bearer token, runs periodically through WorkManager, and is also queued after Wi-Fi becomes available.
- Before reading a day, Android calls `GET /api/steps/exclusions?day=YYYY-MM-DD`. The response contains dashboard-started Live Workout intervals in Europe/Warsaw time.
- Health Connect aggregation is split around those intervals. Steps recorded during Live Workout are excluded, while the Live Workout counter remains the source for those intervals.
- If a dashboard-started Live Workout is currently running or paused, the server accepts no automatic step update. `POST /api/steps/events/upsert` returns `ignored=true` with reason `live_workout_active` and does not change the stored event.
- `POST /api/steps/events/upsert` accepts `source=health_connect` using the same `DASHBOARD_HABITS_TOKEN` already configured for habit synchronization.
- The dashboard displays manual, automatic, and virtual-walk contributions separately and uses their counted total for the 10,000-step daily achievement.
