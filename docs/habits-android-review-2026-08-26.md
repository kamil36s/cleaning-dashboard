# Audyt `DashboardHabits.rar` — 2026-08-26

## Werdykt

Projekt jest działającym szkieletem UI i kompiluje się, ale nie jest jeszcze bezpiecznym klientem dwukierunkowej synchronizacji. Nie należy podłączać go do danych produkcyjnych przed zamknięciem punktów P0 poniżej.

Sprawdzone elementy:

- Compose, Room, Retrofit, DataStore i WorkManager są podłączone;
- model DTO jest zbliżony do kontraktu z `habits-android-sync-spec.md`;
- lokalny zapis wpisu i mutacji odbywa się transakcyjnie;
- projekt przeszedł `testDebugUnitTest`, uruchomiony bezpośrednio przez JAR wrappera;
- obecne testy są wyłącznie testami szablonowymi i nie sprawdzają synchronizacji.

## P0 — blokery prawdziwego syncu

1. `AddEditHabitViewModel.saveHabit()` przy edycji ustawia ponownie `revision = 0`, `position = 0`, target i reminder. Edycja istniejącego nawyku może więc zgubić metadane i natychmiast wywołać konflikt rewizji.
2. Każde kliknięcie tworzy nową mutację z rewizją odczytaną z tej samej lokalnej encji. Kilka zmian przed syncem wysyła kilka mutacji z tym samym `baseRevision`.
3. Pull zapisuje encje przez `OnConflictStrategy.REPLACE`. Odpowiedź serwera może nadpisać optymistyczną zmianę, dla której nadal istnieje niepotwierdzona mutacja w outboxie.
4. Wyczyszczenie wpisu jest wysyłane jako zwykły `UPSERT`; brakuje jednoznacznego `DELETE`/tombstone i testu zastosowania tombstone z serwera.
5. `deviceId` jest utrwalany dopiero po udanym syncu. Do pierwszego sukcesu każda nieudana próba może używać nowego identyfikatora urządzenia.
6. Lokalna edycja nie enqueue'uje syncu. Worker jest uruchamiany tylko przy starcie aplikacji i ręcznym przyciskiem.
7. Worker nie ma pełnej maszyny stanów: brak konfiguracji nie zapisuje `API not configured`, brak Wi-Fi zwraca retry bez czytelnego stanu, a większość błędów HTTP/IO nie jest zapisywana w Room.
8. `ExistingWorkPolicy.REPLACE` może anulować trwający sync po ponownym kliknięciu. Dla jednej kolejki synchronizacji właściwsza jest polityka `KEEP` lub bezpiecznie zaprojektowany łańcuch.

## P1 — ważne poprawki

- Token API jest zapisany jako jawny tekst w Preferences DataStore. Powinien być chroniony mechanizmem opartym o Android Keystore i nigdy logowany.
- `android:usesCleartextTraffic="true"` dotyczy całej aplikacji. W XML użyto wpisów CIDR (`192.168.0.0/16` itd.), których element `<domain>` nie obsługuje. Potrzebny jest osobny wariant `lan` i walidacja URL w kodzie.
- W `build.gradle.kts` nie ma zadeklarowanych flavorów, mimo że artefakty build sugerują wcześniejsze `lanDebug`/`standardDebug`.
- `gradlew.bat` ustawia pusty classpath i kończy się błędem `-classpath requires class path specification`. AGP 8.7.3 ma współpracować z Gradle 8.9; wrapper w archiwum wskazuje Gradle 9.3.1.
- Home nie filtruje konsekwentnie encji usuniętych i zarchiwizowanych.
- Część dat i statystyk używa domyślnej strefy urządzenia zamiast `Europe/Warsaw`; statystyki ignorują wartości numeryczne.
- Mapowanie kategorii ma niespójny fallback (`Nawyki` kontra `HABIT`).
- Health check powinien weryfikować także `service` i `schemaVersion`, nie tylko `ok`.
- Pole tokenu powinno być maskowane.

## Gotowy prompt naprawczy do Android Studio Gemini

Wklej cały poniższy blok w otwartym projekcie Android Studio. Nie proś Gemini o przebudowę aplikacji od zera.

```text
Pracujesz w istniejącym projekcie DashboardHabits. Nie twórz nowego projektu i nie zmieniaj package name. Najpierw przeczytaj cały docs/habits-android-sync-spec.md, a następnie popraw istniejącą implementację minimalnymi, dobrze przetestowanymi zmianami. Nie implementuj backendu ani nie wymyślaj innego kontraktu JSON.

CEL
Przygotuj bezpiecznego offline-first klienta dwukierunkowej synchronizacji z dashboardem PC w tej samej sieci Wi-Fi. Room pozostaje lokalnym źródłem prawdy. Każda lokalna zmiana encji i outboxa musi być atomowa. Nie wolno tracić lokalnej zmiany ani nadpisywać jej odpowiedzią pull, dopóki nie została ACK-owana albo jawnie rozstrzygnięta jako konflikt.

NAJPIERW NAPRAW BUILD
1. Zachowaj AGP 8.7.3, compileSdk/targetSdk 35 i JDK 17. Ustaw wrapper na Gradle 8.9 zgodnie z tabelą kompatybilności AGP 8.7 i popraw/regeneruj oba skrypty wrappera tak, aby `gradlew.bat testDebugUnitTest` działało na Windows.
2. Usuń wygenerowane katalogi build z zakresu zmian. Nie commituj sekretów ani local.properties.

P0 — WYMAGANE POPRAWKI DANYCH I SYNCU
1. Edycja HabitEntity ma zachować id, createdAt, revision, position, target, reminder oraz wszystkie nieedytowane pola. Dla nowej encji ustawiaj wartości domyślne, ale dla istniejącej użyj copy() na aktualnej encji. Nie ustawiaj revision=0 podczas edycji.
2. Zaprojektuj kolejkę outbox odporną na wiele zmian tej samej encji przed syncem oraz na zmianę wykonaną podczas requestu. Użyj stanów PENDING/IN_FLIGHT i transakcji. Możesz scalać najnowszy PENDING dla tego samego entityType+entityKey, lecz nigdy nie modyfikuj mutacji IN_FLIGHT. Po ACK usuń wyłącznie dokładnie wysłany mutationId, a nowszą mutację przelicz na revision potwierdzoną przez serwer. Dodaj indeksy/unikalność i migrację Room.
3. Przed requestem atomowo oznacz pobraną paczkę jako IN_FLIGHT. Po IO/timeout/5xx przywróć ją do PENDING i zwiększ attemptCount. ACK nie może usunąć mutacji utworzonej lub zmienionej po rozpoczęciu requestu.
4. Przy stosowaniu changes z serwera sprawdź, czy dana encja ma lokalną PENDING/IN_FLIGHT mutację. Nie używaj ślepego REPLACE. Jeśli zmiany są zgodne z ACK, zastosuj rewizję serwera; jeśli niezależne i kolidują, zapisz SyncConflictEntity; jeśli nie ma lokalnej mutacji, zastosuj wersję serwera.
5. Usunięcie/wyczyszczenie wpisu wysyłaj jednoznacznie jako operation=DELETE z tombstone. Obsłuż pulled deletedAt dla habit i entry. Encje usunięte nie mogą pojawiać się w normalnym UI.
6. Wygeneruj i zapisz stabilny deviceId przy pierwszej inicjalizacji bazy/preferencji, zanim wystartuje pierwszy request. Nie zmieniaj go po błędzie ani restarcie procesu.
7. Utwórz jeden SyncScheduler używany przez start aplikacji, ręczny Sync now, przejście na Wi-Fi i każdą lokalną edycję. Użyj unikalnej pracy `habits-sync`, ExistingWorkPolicy.KEEP, ograniczenia CONNECTED i wykładniczego backoff. W samym workerze nadal sprawdzaj TRANSPORT_WIFI, gdy wifiOnly=true.
8. Zaimplementuj jawne stany: API_NOT_CONFIGURED, WAITING_FOR_WIFI, PC_UNAVAILABLE, SYNCING, SYNCED, PENDING, UNAUTHORIZED, ERROR. Brak URL/tokena i brak Wi-Fi nie są awarią danych. 401/403 kończą pracę bez nieskończonego retry; IO/timeout/5xx używają retry/backoff.
9. Paginacja hasMore ma przetwarzać ACK/changes/cursor atomowo dla strony i nie wysyłać ponownie ACK-owanych mutacji. Nie używaj `response.body()!!`; obsłuż pustą lub niepoprawną odpowiedź.
10. Health check akceptuje tylko ok=true, service=`cleaning-dashboard-habits` i schemaVersion=1.

LAN I BEZPIECZEŃSTWO
1. Utwórz product flavors w jednym dimension: `standard` oraz `lan`.
2. W main/standard cleartext ma być wyłączony. Usuń globalne usesCleartextTraffic=true.
3. W lan użyj osobnego manifestu i Network Security Config z base-config cleartextTrafficPermitted=true. Nie wpisuj CIDR do elementów `<domain>` — Android tego nie obsługuje.
4. Dodaj walidator URL. HTTPS jest dozwolone. HTTP w flavorze lan jest dozwolone tylko dla 10.0.2.2, literalnych adresów RFC1918 lub hosta .local, który rozwiązuje się wyłącznie do adresu lokalnego. Odrzuć userinfo, fragment, publiczny adres, nieoczekiwany schemat i URL bez hosta. Normalizuj końcowy slash.
5. Przy targetSdk 35 nie dodawaj ACCESS_LOCAL_NETWORK. Zostaw w kodzie/README notatkę migracyjną, że permission będzie wymagane dopiero przy targetSdk >=37.
6. Token przenieś z jawnego Preferences DataStore do magazynu chronionego Android Keystore. Pole tokenu maskuj; nie umieszczaj tokenu w logach, wyjątkach, BuildConfig ani repozytorium.

UI I MODELE
1. Filtruj deletedAt != null i archived=true w zwykłym Home; dodaj osobny jawny sposób pokazania archiwalnych, jeśli już istnieje w UI.
2. Ujednolić category do HABIT/MEDICATION/SUPPLEMENT w encjach, DTO i filtrach.
3. Wszystkie daty biznesowe licz w ZoneId.of("Europe/Warsaw"), również detail, heatmap i testy DST.
4. Zachowaj pełne pola create/edit: type, name, question, description, color, frequency, unit, target, reminder, archived i position. Ekran nie może kasować pól, których chwilowo nie pokazuje.
5. Status na Home i Settings ma pokazywać prawdziwy stan workera oraz pending count. `Synced` tylko po atomowym zastosowaniu prawidłowej odpowiedzi.

TESTY — NIE ZOSTAWIAJ TESTÓW SZABLONOWYCH JAKO JEDYNEGO POKRYCIA
1. Unit: cykl binarny, numeric/valueMilli, URL validator, DTO, Europe/Warsaw+DST, score/streak, mapowanie błędów i health response.
2. Room/instrumented: entry+outbox atomowo; wiele edycji tej samej encji; edycja podczas IN_FLIGHT; ACK usuwa tylko wysłany mutationId; pull nie nadpisuje pending; tombstone; migracja bazy.
3. Worker z MockWebServer: brak requestu bez configu i poza Wi-Fi; 401 bez retry; 5xx/IO z retry; poprawny bearer token; hasMore; pusty body; konflikt rewizji; stabilny deviceId.
4. Compose: maskowany token, statusy sync, pending count, binary/numeric edit i ekran konfliktu.

KRYTERIA ODBIORU
- `gradlew.bat testDebugUnitTest` działa z normalnego terminala Windows.
- `gradlew.bat connectedDebugAndroidTest` jest gotowe do uruchomienia na emulatorze/telefonie.
- `gradlew.bat assembleLanDebug` i `gradlew.bat assembleStandardDebug` kończą się sukcesem.
- Szybkie 3 kliknięcia offline, restart aplikacji, a potem sync nie tracą ostatniego stanu i nie tworzą fałszywego konfliktu.
- Edycja na telefonie podczas trwającego pulla nie jest nadpisywana.
- Brak PC lub Wi-Fi pozostawia dane w Room i mutacje w outboxie.
- Nie zmieniaj publicznego kontraktu DTO bez wskazania konkretnej niezgodności ze specyfikacją.

Na końcu podaj: listę zmienionych plików, krótkie uzasadnienie modelu outbox/IN_FLIGHT, migracje Room, komendy i pełne wyniki test/build. Jeśli czegoś nie udało się uruchomić, napisz dokładnie czego i dlaczego; nie deklaruj sukcesu na podstawie samej kompilacji.
```

## Co robimy po tej poprawce

Po otrzymaniu poprawionego projektu ponownie sprawdzamy P0 i testy. Dopiero wtedy implementujemy w dashboardzie centralne SQLite, `GET /api/habits/health`, `POST /api/habits/sync`, uwierzytelnienie Bearer oraz przełączamy widget z preview/localStorage na prawdziwe API.
