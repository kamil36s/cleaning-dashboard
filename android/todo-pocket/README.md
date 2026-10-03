# Taski na telefon

Minimalna aplikacja Android z przewijanym widżetem ekranu głównego. Pokazuje wszystkie otwarte pozycje `now` i `shopping` z istniejącego `data/settings/todo.json`. Dotknięcie pozycji ją kończy. Projekty i pomysły pozostają poza aplikacją.

Synchronizacja działa wyłącznie przy aktywnym połączeniu Wi-Fi. Aplikacja odświeża dane przy otwarciu, widżet po dotknięciu ↻ i w tle co około 15 minut (według planowania Androida). Ostatnia pobrana lista jest dostępna offline.

## Serwer

Serwer musi nasłuchiwać w sieci lokalnej (`DASHBOARD_HOST=0.0.0.0`). Token można ustawić w `DASHBOARD_TODO_TOKEN` albo umieścić w `~/.cleaning-dashboard/todo-phone-token` na komputerze. `DASHBOARD_WRITE_TOKEN` też jest akceptowany. Endpoint `/api/phone-todo` wymaga tokenu i klienta z prywatnej sieci LAN.

## Instalacja

Zbuduj `:app:assembleDebug` przy ustawionym `ANDROID_HOME`, a następnie zainstaluj `app/build/outputs/apk/debug/app-debug.apk` przez ADB. Po pierwszym uruchomieniu podaj adres `http://<IP-komputera>:8000` i token. W wersji debug można też przekazać je przez ADB do `TodoSetupReceiver` (chronionego uprawnieniem `android.permission.DUMP`). Token jest szyfrowany w Android Keystore.

W menu ⚙ wybierz **Dodaj widżet**. Jeśli launcher nie obsługuje przypinania, przytrzymaj ekran główny i wybierz **Widżety → Taski**.
