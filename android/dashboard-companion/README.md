# Dashboard Companion

Local Android companion for the Cleaning Dashboard. Pack D adds receipt capture/import,
durable offline upload, and local EAN/UPC product lookup. It does not contain a finance
database and does not call OpenFoodFacts or any cloud OCR service.

## Pair and configure

1. Start the dashboard server on the local network with `DASHBOARD_HOST=0.0.0.0`.
2. On the desktop Finance API, create a device token with the localhost-only
   `POST /api/budget/companion/pair` endpoint (the Finance UI can expose this later).
3. Enter the local server URL and the one-time token in the app. No LAN address or token
   is built into the APK. The token is encrypted with Android Keystore.
4. Revocation is available through `POST /api/budget/companion/revoke` from localhost.

The receipt/product endpoints require the paired bearer token for non-local clients.
Receipt source previews deliberately remain browser-only and same-origin; the companion token cannot read originals back.
Original files are copied immediately from Android content URIs into app-private storage
and remain queued until a confirmed server response is stored.

## Build

```powershell
.\build-debug.cmd
```

APK: `app\build\outputs\apk\debug\app-debug.apk`

The document scanner uses Google Play services ML Kit with crop, rotate, gallery import,
multi-page capture, JPEG and PDF output. The code scanner accepts EAN-13, EAN-8, UPC-A,
and UPC-E. Document scans preserve ordered JPEG pages for bundled ML Kit text recognition
and retain the generated PDF as archival evidence. ML Kit supplies text evidence only:
merchant, total, items, categories, and transaction matching remain canonical backend decisions.
Both scanners process images on-device; receipt parsing remains on the local
Dashboard backend.
