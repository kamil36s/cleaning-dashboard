# Phone Tracker / Phone Activity

## Stan i architektura

To nowy, lokalny przepływ działający obok starego widgetu **Phone Telemetry** z ręcznym importem JSON. Źródłem danych telefonu jest natywna aplikacja w `android/phone-tracker/`. Zapisuje zdarzenia w Room, zbiera historię użycia w zadaniu WorkManager co około 15 minut także bez sieci, a osobne zadanie synchronizuje paczki po Wi-Fi/Ethernet z `server.py`. PC zapisuje je w prywatnym `data/phone-tracker.sqlite`; `phone_tracker.py` tworzy read model dla widgetu `phone-activity` i strony `phone-activity.html`. Żadna usługa chmurowa ani SDK analytics nie bierze udziału w tym przepływie.

```
Android UsageStats / NotificationListener / PackageReceiver / battery / passive location
    → Room events + app_registry (pending)
    → WorkManager + LAN HTTP bearer token
    → /api/phone-tracker/sync i /apps
    → SQLite events (UTC) + app registry
    → /summary i /events
    → Phone Activity widget / detail page
```

## Budowa, instalacja, parowanie

1. Uruchom normalny dashboard z lokalnym API na porcie 8000 i Vite na porcie 5173. Na PC otwórz `http://localhost:5173/cleaning-dashboard/phone-activity.html` lub link **Phone Activity** z dashboardu. Pairing i ustawienia administracyjne działają tylko przez adres localhost na PC.
2. W sekcji **Pair a phone** utwórz urządzenie. Skopiuj wyświetlony `device_id` i token od razu: token jest pokazywany tylko raz. Znajdź adres IP komputera w tej samej sieci Wi-Fi (np. `192.168.1.20`); Android potrzebuje `http://192.168.1.20:8000`. Port 8000 musi być osiągalny z telefonu przez zaporę systemu.
3. Otwórz `android/phone-tracker/` w Android Studio (SDK 36, JDK 17). Zbuduj **debug APK** poleceniem `cd android/phone-tracker; .\gradlew.bat :app:assembleDebug` w PowerShell albo przyciskiem Build. APK: `android/phone-tracker/app/build/outputs/apk/debug/app-debug.apk`.
4. Zainstaluj APK na wybranym urządzeniu przez Android Studio albo `adb -s <serial> install -r app-debug.apk`. Gdy ADB widzi kilka urządzeń, podaj serial telefonu jawnie.
5. W aplikacji wpisz adres LAN PC, `device_id` i token. Dotknij **Save pairing**. Token jest szyfrowany kluczem Android Keystore w prywatnej pamięci aplikacji. Dla debug APK można zamiast ręcznego wpisywania użyć `scripts/provision-phone-tracker.py --serial <ADB-serial> --server http://<PC-IP>:8000`: skrypt tworzy parowanie i przekazuje token przez ADB stdin do jednorazowego prywatnego pliku, który aplikacja usuwa po zaszyfrowaniu. Otwórz systemowe ustawienia **Usage Access** i **Notification Access** z ekranu setupu. Lokalizacja i Accessibility są opcjonalne dla podstawowego przepływu.
6. Użyj **Test PC connection** i **Sync now**. Na telefonie sprawdź `Pending events`, `Last event`, `Last sync`, `Last error`. Na PC odśwież Phone Activity: status urządzenia, zdarzenia i agregaty powinny się pojawić. Zamknij PC lub odłącz Wi-Fi: liczba pending na telefonie rośnie; po przywróceniu LAN maleje. Status PC pokazuje ostatnią *zgłoszoną* liczbę pending, nie bieżącą liczbę z telefonu offline.

`Sync now` i zadanie WorkManager nie blokują UI. Błąd serwera pozostawia niepotwierdzone zdarzenia w Room i uruchamia ponowienie z wykładniczym backoff. Rekordy odrzucone przez walidację są zachowane lokalnie ze stanem `rejectedReason` do diagnostyki, a pozostałe paczki mogą iść dalej. WorkManager i HyperOS mogą opóźnić pracę w tle; w ustawieniach HyperOS warto zezwolić na autostart, pracę w tle i wyłączyć restrykcyjną optymalizację baterii dla tej aplikacji.

## Uprawnienia

| Uprawnienie | Zastosowanie | Bez niego |
| --- | --- | --- |
| `PACKAGE_USAGE_STATS` (Usage Access) | Historia foreground/background, screen on/off, unlock | Brak tych zdarzeń; inne collectory działają |
| Notification Listener | Post/remove, tytuł, tekst, identyfikator, kategoria, kanał, reason | Brak powiadomień |
| Accessibility Service | Reguły blokujące foreground app i nakładka | Tracking i sync działają bez blokowania |
| `ACCESS_COARSE_LOCATION` / `ACCESS_BACKGROUND_LOCATION` | Ostatni dostępny pasywny/network fix | Brak miejsc; brak awarii |
| `QUERY_ALL_PACKAGES` | Nazwy i rzeczywiste ikony używanych aplikacji | Niektóre nazwy/ikony mogą być niedostępne |
| `INTERNET`, `ACCESS_NETWORK_STATE` | Synchronizacja po LAN | Lokalna kolejka działa dalej |

Lokalizacja zaczyna od istniejących świeżych fixów (`PASSIVE_PROVIDER`/`NETWORK_PROVIDER`). Jeśli ich brak, na Androidzie 11+ próbuje pojedynczego fixu sieciowego z limitem 8 sekund, najwyżej raz na godzinę; nie uruchamia ciągłego GPS. Akceptowane są punkty nie starsze niż 30 minut, dokładność do 1000 m; nowy punkt trafia do Room po ruchu ≥150 m albo upływie ≥1 godziny. Brak świeżego fixu oznacza brak punktu, nie wymyśloną pozycję. Standardowy `LocationManager` udostępnia ostatnią znaną pozycję, a nie pełną dawną historię tras z Google Timeline lub innych aplikacji.

## Eventy i bazy

Model wspólny `event_id` UUID, `device_id`, `timestamp` UTC, `event_type`, `package_name`, `app_name`, `session_id`, `value_numeric`, `value_text`, `metadata_json`, `received_at`. Telefon utrzymuje `events` ze stanami `syncedAt` i `rejectedReason` oraz `app_registry`; Room ma migracje 1→2→3. PC używa `PRAGMA user_version` (obecnie v4) i tabel `devices`, `apps`, `events`, `sync_batches`, `rules`, `external_conditions`, `place_names`, `settings`, `override_settings`. Indeksy obejmują identyfikatory, typ, pakiet i czas. Ikony są PNG do 64 KiB na aplikację, synchronizowane oddzielnie, nie przy każdym zdarzeniu.

Typy przyjmowane przez API: `app_foreground`, `app_background`, `screen_on`, `screen_off`, `unlock`, `notification_posted`, `notification_removed`, `battery`, `location`, `app_installed`, `app_removed`, `device_boot`, `block`, `override`. App usage pochodzi z `UsageStatsManager.queryEvents`; powiadomienia z `NotificationListenerService`; zmiany pakietów z broadcast receiver; bateria z `ACTION_BATTERY_CHANGED`.

## Synchronizacja i endpointy

`POST /api/phone-tracker/sync` przyjmuje `schema_version:1`, UUID `device_id`, UUID `batch_id`, `sent_at`, `pending_count` i maks. 500 `events` (telefon wysyła po 200). Nagłówki: `Authorization: Bearer <pairing-token>` i `X-Phone-Device-ID`. Odpowiedź zawiera `accepted`, `duplicates`, `rejected`; ACK tylko accepted/duplicates oznacza lokalny rekord jako zsynchronizowany. `event_id` jest unikatowy w PC SQLite; ponowna paczka zwraca utrwalony wynik z `sync_batches`. Powtórka ze świeżym `batch_id` deduplikuje po `event_id`. Telefon akceptuje wyłącznie prywatny adres LAN i używa timeoutów 10/15 s.

Pozostałe trasy:

- `POST /pair`, `GET /devices`, `GET /status`, `DELETE /devices/<uuid>` — utworzenie, podgląd, ostatni raport, unieważnienie tokenu (historia zostaje).
- `POST /apps` — osobny rejestr aplikacji/ikon.
- `GET /config` — wersjonowany cache reguł, kategorii, warunków zewnętrznych i retencji dla sparowanego telefonu.
- `GET /summary`, `GET /events` — dynamiczne odczyty `range=today|yesterday|previous_day|7d|previous_7d|30d|previous_30d|month|previous_month|custom|all`, `tz=<IANA>`, opcjonalne `device_id`; custom używa `start/end=YYYY-MM-DD`.
- `GET /insights` — dzienny trend, streaki limitów i opisowe porównanie (`days=7..90`, `metric`, `operator`, `threshold`, `outcome`); metryki `screen_time`, `notifications`, `unlocks`, `app_usage:<package>`, `app_launches:<package>`.
- `GET/POST /rules`, `DELETE /rules/<uuid>`, `POST /category`, `POST /external-condition`, `POST /place` — reguły, kategorie, warunki i nazwy miejsc.
- `GET/POST /override-policy` — tryb, czas i opcjonalny PIN czasowego odblokowania dla `device_id`; odczyt panelu nie zwraca skrótu PIN. Pełną konfigurację otrzymuje tylko sparowany telefon przez `/config`.
- `GET/POST /retention`, `DELETE /events`, `DELETE /all?confirm=delete` — retencja i kasowanie na PC.
- `POST/DELETE /sample` — oddzielne syntetyczne urządzenie (`source=sample` w odczytach); prawdziwe odczyty domyślnie wykluczają sample.

Adresy w powyższej liście mają wspólny prefiks `/api/phone-tracker`. Administracyjne zapisy/parowanie wymagają przeglądarki na PC przez localhost. Sync/config/apps wymagają poprawnego tokenu i prywatnego adresu IP. Tokeny w PC są haszowane SHA-256; pełen token pojawia się tylko przy utworzeniu parowania.

## Definicje metryk

- **App session**: `app_foreground` otwiera sesję. Pasujące `app_background`, następny `app_foreground` lub `screen_off` ją zamyka. Otwartego końca nie dopisuje się sztucznie do `now`; bez zamknięcia nie wchodzi do sumy historycznej. Przy zakresie doby sesja jest obcięta do lokalnych granic dnia.
- **Phone session**: pierwszy `unlock` rozpoczyna; pierwszy późniejszy `screen_off` kończy. Screen-on bez unlock nie rozpoczyna sesji. Bardzo krótkie sesje pozostają w raw data; nie są odrzucane heurystycznie. Brakujący unlock/off oznacza sesję niekompletną, której nie liczymy.
- **Powroty i sekwencje**: średnia przerwa między zakończoną sesją aplikacji a jej kolejnym otwarciem jest liczona dla tej samej aplikacji i urządzenia; kolejność aplikacji w ukończonej sesji telefonu pochodzi z ich jawnych eventów foreground.
- **Notification attribution**: najbliższe wcześniejsze, nieprzypisane powiadomienie z tej samej aplikacji, w konfigurowalnym oknie 1–3600 s (domyślnie 120 s), jest łączone z jednym otwarciem. Jest to związek czasowy, nie dowód przyczynowości.
- **Miejsca**: komórki siatki około 500 m z punktów lokalizacji o określonej dokładności. Czas w miejscu to dolna granica z kolejnych punktów w tej samej komórce i odstępie ≤2 h. Screen time w miejscu to oszacowane nakładanie się takiego odcinka i sesji aplikacji. Nie ma reverse geocodingu ani mapy online.
- **Doomscroll**: obecnie ukończona sesja aplikacji ≥20 min. **Rapid switching**: co najmniej 12 otwarć w 10 min. **Night use**: lokalne godziny 00:00–04:59. Parametry wykrywania są obecnie stałe, wskazane w API.
- **Bateria**: procent i stan ładowania są próbkowane co około 15 min. Spadek między dwoma próbkami bez ładowania jest dzielony proporcjonalnie do czasu nakładania się sesji aplikacji; wynik jest jawnie oznaczony jako estymacja ekspozycji, a nie pomiar zużycia przez aplikację.
- **Streak**: podstawowy licznik dla zapisanych limitów dziennych aplikacji/kategorii sprawdza ukończone dni wstecz od wczoraj, maksymalnie 90 dni. Dzień bez sygnału użycia kończy serię jako `no_coverage`, a nie sukces. Porównanie warunkowe (`/insights`) liczy średnią wybranej metryki w dniach spełniających próg i pozostałych dniach, jawnie podając obie liczności i brak wnioskowania o przyczynach.

Daty w DB są UTC. Granice doby i histogramy liczy strefa IANA przesłana przez UI, także przy DST. Android używa lokalnej strefy urządzenia do reguł dziennych.

## Reguły i blokowanie

### App Access: redukcja bazy i bonus za czytanie

`GET/POST /api/phone-tracker/access` zachowuje istniejącą politykę i dodaje `reduction`,
`extra_reading` oraz osobne przełączniki powiadomień. `POST /api/phone-tracker/access/plan`
przyjmuje `pause`, `resume` lub potwierdzony w UI `restart`. Plan zapisuje bazę z dnia
uruchomienia z pełną precyzją; późniejsza średnia historyczna jest tylko informacją.
Migracja tworzy tabele `app_access_reduction_plans`, `app_access_reward_events` i
`app_access_day_corrections`, pozostawiając stare reguły, zdarzenia i migawki dni.

Limit bazowy to `max(floor, start * (1-rate)^dni)` albo
`max(floor, start - fixed_minutes*dni)`. Pauza zapisuje bieżący limit i zatrzymuje licznik dni. Normalny dostęp
pozostaje `floor(limit_bazowy * postęp_Reading_Cleaning)`. Bonus jest liczony wyłącznie
z pełnych bloków stron ponad dzisiejszy cel Reading (chyba że włączono nagrody częściowe),
nie jest mnożony przez postęp Cleaning i domyślnie może przekroczyć limit bazowy.
Całość: `normalny_dostęp + bonus`; pozostały czas: `max(0, całość - użycie)`.
Przy korekcie postępu nie tworzy się ponownie zdarzeń nagrody o tym samym progu; już
zużyty czas nie staje się ujemnym saldem. Telefon otrzymuje rozbicie i sumę w dotychczasowym
`GET /config` oraz egzekwuje ostatnią zsynchronizowaną konfigurację także bez PC.

Przykład definicji w `POST /rules`:

```json
{
  "device_id": "UUID",
  "rule": {
    "name": "Instagram 45 min",
    "target": "com.instagram.android",
    "action": "block",
    "when": { "metric": "app_usage_today", "operator": ">=", "value": 45, "unit": "minutes" }
  }
}
```

Drzewo `when` obsługuje `all`, `any`, `not` oraz operatory `<`, `<=`, `==`, `>=`, `>`. Dostępne metryki: `app_usage_today`, `app_launches_today`, `category_usage_today`, `category_launches_today`, `time_of_day`, `doomscroll_minutes`, `external:<name>`. Kategorie ustawia PC; warunki zewnętrzne mają boolean lub wartość liczbową. Telefon przechowuje ostatni pobrany config lokalnie i ocenia go bez PC. Accessibility sprawdza aplikację przy zmianie okna i co 30 s w trakcie aktywnej aplikacji. Nakładka oferuje **Back to home** i opcjonalny czasowy unlock; block/override są zdarzeniami. Politykę unlock ustawia się w widoku Phone Activity: zawsze, PIN 4–12 cyfr, cooldown albo wyłączenie, z czasem 1–60 minut. PIN jest hashowany PBKDF2 i nie jest pokazywany ponownie w UI; jego skrót trafia do telefonu, aby tryb działał offline. Dialer, Settings, System UI, launcher, interfejs alarmowy i sam tracker są chronione. To prywatna samokontrola, nie blokada odporna na wyłączenie usługi.

## Prywatność, ograniczenia i diagnostyka

Domyślnie tytuł/tekst powiadomień jest usuwany po 30 dniach na PC i w Room; metadane zdarzenia zostają. Retencja eventów użycia na PC jest domyślnie bezterminowa. Strona umożliwia skasowanie okresu lub całego PC store wraz z parowaniem, ikonami i regułami. Nie usuwa to danych z telefonu; ponowne wysłanie już ACK-owanych rekordów nie następuje automatycznie. Po pełnym usunięciu trzeba sparować telefon ponownie.

LAN sync używa obecnie HTTP, więc token i prywatne treści są widoczne dla osoby zdolnej podsłuchać niezaufaną sieć Wi-Fi. Używaj wyłącznie zaufanej sieci domowej; szyfrowanie transportowe/pinning jest osobną pracą. Dashboard jako całość nie ma kont użytkowników; nie udostępniaj portów 8000/5173 do Internetu. Lokalny plik SQLite jest chroniony przez politykę statycznych plików serwera i Vite.

Android/HyperOS może opóźnić WorkManager, ograniczyć Accessibility, usunąć starszą historię UsageEvents lub nie zwrócić lokalizacji/ikony. Brakujące dane pozostają brakującymi. Split-screen, szybkie przejścia, clock/timezone change, niekompletne screen-off i reboot ograniczają dokładność. Pierwszy skan pyta o 30 dni wstecz, lecz Android zwykle przechowuje surowe UsageEvents znacznie krócej; collector zapisuje tylko rzeczywiście zwrócone zdarzenia. Kolejne skany mają zakładkę 10 minut. NotificationListener zapisuje wyłącznie powiadomienia dostarczone po przyznaniu dostępu.

`Test PC connection` sprawdza token i trasę config; `Export diagnostics` udostępnia daty/statusy bez tokenu i treści powiadomień. Brak danych na PC sprawdź w kolejności: Usage Access, pending Room, adres IP/port 8000, Wi-Fi, `Last error`, firewall i ostatni sync w `/status`.

### Zakres nadal otwarty

Nie ma jeszcze NSD/mDNS discovery, TLS/pinning, edytora dowolnych drzew AND/OR/NOT w UI (API działa), pełnych definicji celów i streaków wykraczających poza dzienne limity, ogólnego silnika korelacji wykraczającego poza opisowe porównanie warunkowe, precyzyjnej atrybucji baterii, pełnych rozkładów odstępów i sekwencji dla każdej aplikacji, automatycznych testów na fizycznym Redmi ani gwarancji działania blokera na każdej wersji HyperOS. Dashboard udostępnia główne metryki, trendy, timeline, miejsca, wzorce, limity i status; pozostałe analizy wymagają kolejnej implementacji.
