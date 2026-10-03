# Local Network Monitor

Minimalny lokalny backend do widżetu monitorującego urządzenia w domowej sieci Wi-Fi/LAN.

## Co robi

- skanuje lokalna siec co `30s` domyslnie
- wykrywa hosty przez lekki ping sweep + ARP cache
- zapisuje historie do SQLite
- wystawia tylko dwa endpointy read-only:
  - `GET /api/network/devices`
  - `GET /api/network/summary`
- dodatkowo ma lokalny endpoint zapisu nazw urządzeń:
  - `GET /api/network/device-names`
  - `POST /api/network/device-names`
- dodatkowo ma read-only endpoint historii:
  - `GET /api/network/history`
- nasluchuje tylko na `127.0.0.1`

## Instalacja

1. Zainstaluj zaleznosc Python:

```bash
py -m pip install -r requirements-network.txt
```

2. Uruchom backend:

```bash
py run_network_monitor.py
```

Jeśli `py` nie jest dostępne, użyj:

```bash
python run_network_monitor.py
```

Backend startuje domyslnie na:

- `http://127.0.0.1:8765`

Jesli korzystasz z `start-dev.cmd`, to po poprawce uruchamia on teraz rowniez ten backend automatycznie.

## Frontend

Widżet w `index.html` próbuje łączyć się z:

- `http://127.0.0.1:8765`

odswieza dane co `10s` i pokazuje:

- urządzenia online
- ostatnio widziane urządzenia
- od kiedy dane urządzenie jest online
- liczbę wszystkich wykrytych urządzeń
- czas ostatniego skanu

W ustawieniach urządzeń dostajesz też agregaty historii:

- `Dzień` - czas online/offline od początku dzisiejszego dnia
- `Tydzień` - czas online/offline od początku bieżącego tygodnia
- `Miesiąc` - czas online/offline od początku bieżącego miesiąca

To są wartości przybliżone do interwału skanowania, bo stan zmienia się w modelu przy kolejnych skanach.

Jeśli backend nie działa, karta pokaże stan offline zamiast wysypać UI.

## Nazwy urządzeń z UI

Nazwy mozna ustawic w:

- `settings.html`
- modalu `Settings` otwieranym z dashboardu

Sekcja `Nazwy urządzeń w sieci` pokazuje wykryte hosty, ich MAC/IP oraz stan online/offline.
Zapis idzie lokalnie do pliku JSON i od razu aktualizuje listę urządzeń bez restartu backendu.

## Pliki danych

- baza SQLite: `data/network-monitor.sqlite`
- mapowanie nazw: `data/network-known-devices.json`

Przyklad mapowania MAC -> nazwa:

```json
{
  "AA:BB:CC:DD:EE:FF": "Laptop biurkowy",
  "11:22:33:44:55:66": {
    "name": "TV salon"
  }
}
```

Widżet i API używają tej nazwy jako priorytetowej. Jeśli dla MAC nie ma wpisu, pokazywana jest nazwa wykryta lokalnie albo samo IP/MAC.

## Opcjonalne zmienne srodowiskowe

- `NETWORK_MONITOR_PORT` - domyslnie `8765`
- `NETWORK_MONITOR_SCAN_INTERVAL` - domyslnie `30`
- `NETWORK_MONITOR_PING_TIMEOUT_MS` - domyslnie `400`
- `NETWORK_MONITOR_MAX_HOSTS` - domyslnie `256`
- `NETWORK_MONITOR_MAX_WORKERS` - domyslnie `16`
- `NETWORK_MONITOR_DB_PATH` - sciezka do SQLite
- `NETWORK_MONITOR_NAMES_PATH` - sciezka do pliku z nazwami MAC

## Uwagi

- MAC jest zwykle stabilny dla TV, drukarek, konsol, IoT i urządzeń po kablu.
- Telefony i laptopy na Wi-Fi mogą używać prywatnego lub losowego MAC dla danego SSID. Często jest on stabilny przez dłuższy czas dla tej samej sieci, ale nie jest gwarantowany na zawsze.
- Dlatego najlepsza identyfikacja urządzenia jest po MAC, ale trzeba liczyć się z tym, że niektóre mobilne urządzenia mogą kiedyś pojawić się jako nowy wpis.
- Kod ma adapter pod Windows i Linux.
- Startowo najlepiej wspierany jest scenariusz lokalny na Windows.
- Vendor lookup nie jest wymagany i nie blokuje działania.
- Backend nie loguje się do routera i nie udostępnia żadnych endpointów POST/PUT/DELETE.
