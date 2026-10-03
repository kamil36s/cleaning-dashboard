# Phone Tracker Android

Native Kotlin/Compose/Room Android app for `docs/phone-tracker.md`.

The launcher uses an adaptive vector icon and a matching Android SplashScreen. The app uses a dark teal theme and shows a local loading state while Room diagnostics initialize. Pairing credentials stay encrypted in Android Keystore.

Open this directory in Android Studio with SDK 36 and JDK 17. Build with `.\gradlew.bat :app:assembleDebug` on Windows or `./gradlew :app:assembleDebug` on Unix; APK is `app/build/outputs/apk/debug/app-debug.apk`. Install on a selected device with `adb -s <serial> install -r app/build/outputs/apk/debug/app-debug.apk`.

The PC API must be reachable at `http://<PC-LAN-IP>:8000`. Create credentials from `phone-activity.html` on the PC, then paste the server address, device ID and one-time token into the app. Enable Usage Access and Notification Access in Android settings. Accessibility and location are optional. See the main documentation for permissions, limitations, and HyperOS setup.
