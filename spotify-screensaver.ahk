#Requires AutoHotkey v2.0
#SingleInstance Force

; -----------------------------
; Configuration
; -----------------------------
IDLE_MINUTES := NumberOrDefault(EnvGet("IDLE_MINUTES"), 3)
CHECK_INTERVAL_MS := NumberOrDefault(EnvGet("CHECK_INTERVAL_MS"), 5000)
DASHBOARD_URL := EnvOrDefault("DASHBOARD_URL", "http://127.0.0.1:8000")
CHROME_PATH := EnvOrDefault("CHROME_PATH", FindChrome())
CHROME_PROFILE_DIR := EnvOrDefault("CHROME_PROFILE_DIR", A_ScriptDir "\.chrome-spotify-screensaver")

STATUS_URL := RTrim(DASHBOARD_URL, "/") . "/api/screensaver-status"
SCREENSAVER_URL := RTrim(DASHBOARD_URL, "/") . "/spotify-screensaver"
CONFIG_URL := RTrim(DASHBOARD_URL, "/") . "/api/screensaver-config"

IDLE_THRESHOLD_MS := IDLE_MINUTES * 60 * 1000
kioskPid := 0

SetTimer(CheckScreensaver, CHECK_INTERVAL_MS)
SetTimer(CloseKioskAfterInput, 250)

CheckScreensaver() {
    global IDLE_THRESHOLD_MS, STATUS_URL, SCREENSAVER_URL, CHROME_PATH, CHROME_PROFILE_DIR, kioskPid

    RefreshRemoteConfig()

    if (A_TimeIdlePhysical < IDLE_THRESHOLD_MS) {
        return
    }

    if (IsKioskRunning()) {
        return
    }

    if (!CanUseChrome(CHROME_PATH)) {
        Log("Chrome path not found. Set CHROME_PATH at the top of this script or as an environment variable.")
        return
    }

    statusJson := HttpGet(STATUS_URL)
    if (statusJson = "") {
        return
    }

    if (!JsonBoolean(statusJson, "shouldShow")) {
        return
    }

    DirCreate(CHROME_PROFILE_DIR)

    ; The dedicated --user-data-dir keeps this kiosk instance separate from normal Chrome windows.
    command := Quote(CHROME_PATH) . " --user-data-dir=" . Quote(CHROME_PROFILE_DIR) . " --no-first-run --disable-session-crashed-bubble --kiosk " . Quote(SCREENSAVER_URL)

    try {
        Run(command, , , &kioskPid)
    } catch as err {
        kioskPid := 0
        Log("Could not launch Chrome kiosk: " . err.Message)
    }
}

RefreshRemoteConfig() {
    global CONFIG_URL, IDLE_MINUTES, CHECK_INTERVAL_MS, IDLE_THRESHOLD_MS

    configJson := HttpGet(CONFIG_URL)
    if (configJson = "") {
        return
    }

    nextIdleMinutes := JsonNumber(configJson, "idleMinutes", IDLE_MINUTES)
    nextCheckIntervalMs := JsonNumber(configJson, "checkIntervalMs", CHECK_INTERVAL_MS)

    if (nextIdleMinutes > 0) {
        IDLE_MINUTES := nextIdleMinutes
        IDLE_THRESHOLD_MS := IDLE_MINUTES * 60 * 1000
    }

    if (nextCheckIntervalMs >= 1000 && nextCheckIntervalMs != CHECK_INTERVAL_MS) {
        CHECK_INTERVAL_MS := nextCheckIntervalMs
        SetTimer(CheckScreensaver, CHECK_INTERVAL_MS)
    }
}

CloseKioskAfterInput() {
    if (!IsKioskRunning()) {
        return
    }

    if (A_TimeIdlePhysical < 750) {
        CloseKioskChrome()
    }
}

IsKioskRunning() {
    global kioskPid, CHROME_PROFILE_DIR

    if (kioskPid && ProcessExist(kioskPid)) {
        return true
    }

    kioskPid := 0
    return HasChromeProcessForProfile(CHROME_PROFILE_DIR)
}

CloseKioskChrome() {
    global kioskPid, CHROME_PROFILE_DIR

    ; Chrome may move the visible window into a child process. To avoid killing normal Chrome,
    ; close only chrome.exe processes whose command line contains this kiosk profile directory.
    try {
        wmi := ComObjGet("winmgmts:")
        processes := wmi.ExecQuery("SELECT ProcessId, CommandLine FROM Win32_Process WHERE Name = 'chrome.exe'")
        for process in processes {
            commandLine := String(process.CommandLine)
            if (InStr(commandLine, CHROME_PROFILE_DIR)) {
                ProcessClose(process.ProcessId)
            }
        }
    } catch as err {
        Log("Could not close kiosk Chrome by profile: " . err.Message)
        if (kioskPid && ProcessExist(kioskPid)) {
            ProcessClose(kioskPid)
        }
    }

    kioskPid := 0
}

HasChromeProcessForProfile(profileDir) {
    try {
        wmi := ComObjGet("winmgmts:")
        processes := wmi.ExecQuery("SELECT CommandLine FROM Win32_Process WHERE Name = 'chrome.exe'")
        for process in processes {
            if (InStr(String(process.CommandLine), profileDir)) {
                return true
            }
        }
    } catch {
        return false
    }

    return false
}

HttpGet(url) {
    try {
        request := ComObject("WinHttp.WinHttpRequest.5.1")
        request.SetTimeouts(2000, 2000, 3000, 3000)
        request.Open("GET", url, false)
        request.Send()

        if (request.Status < 200 || request.Status >= 300) {
            return ""
        }

        return request.ResponseText
    } catch {
        return ""
    }
}

JsonBoolean(json, key) {
    pattern := '"' . key . '"\s*:\s*(true|false)'
    if (!RegExMatch(json, pattern, &match)) {
        return false
    }

    return match[1] = "true"
}

JsonNumber(json, key, fallback) {
    pattern := '"' . key . '"\s*:\s*([0-9]+(?:\.[0-9]+)?)'
    if (!RegExMatch(json, pattern, &match)) {
        return fallback
    }

    try {
        return Number(match[1])
    } catch {
        return fallback
    }
}

CanUseChrome(chromePath) {
    return chromePath != "" && FileExist(chromePath)
}

FindChrome() {
    candidates := [
        EnvGet("ProgramFiles") "\Google\Chrome\Application\chrome.exe",
        EnvGet("ProgramFiles(x86)") "\Google\Chrome\Application\chrome.exe",
        EnvGet("LocalAppData") "\Google\Chrome\Application\chrome.exe"
    ]

    for candidate in candidates {
        if (candidate != "" && FileExist(candidate)) {
            return candidate
        }
    }

    return ""
}

EnvOrDefault(name, fallback) {
    value := EnvGet(name)
    return value != "" ? value : fallback
}

NumberOrDefault(value, fallback) {
    try {
        number := Number(value)
    } catch {
        return fallback
    }

    return number > 0 ? number : fallback
}

Quote(value) {
    ; File paths should not contain quotes; strip them rather than risking command injection.
    return Chr(34) . StrReplace(value, Chr(34), "") . Chr(34)
}

Log(message) {
    OutputDebug("[spotify-screensaver] " . message)
}
