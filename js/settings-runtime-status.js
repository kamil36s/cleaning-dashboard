const summary = document.getElementById("settings-runtime-summary");
const dashboardTime = document.getElementById("settings-runtime-dashboard-time");
const dashboardElapsed = document.getElementById("settings-runtime-dashboard-elapsed");
const bootTime = document.getElementById("settings-runtime-boot-time");
const bootElapsed = document.getElementById("settings-runtime-boot-elapsed");
const refreshButton = document.getElementById("settings-runtime-refresh");

function elapsedSince(date) {
  const minutes = Math.max(0, Math.floor((Date.now() - date.getTime()) / 60000));
  const days = Math.floor(minutes / 1440);
  const hours = Math.floor((minutes % 1440) / 60);
  if (days) return `${days} dni ${hours} godz.`;
  if (hours) return `${hours} godz. ${minutes % 60} min`;
  return `${minutes} min`;
}

function showTime(element, elapsedElement, value, fallback, fallbackDetail = "") {
  const date = value ? new Date(value) : null;
  if (!date || Number.isNaN(date.getTime())) {
    element.textContent = fallback;
    element.removeAttribute("datetime");
    elapsedElement.textContent = fallbackDetail;
    return;
  }
  element.dateTime = date.toISOString();
  element.textContent = date.toLocaleString("pl-PL", { dateStyle: "long", timeStyle: "short" });
  elapsedElement.textContent = `Temu: ${elapsedSince(date)}`;
}

async function refreshStatus() {
  try {
    const response = await fetch("/api/dashboard/runtime-status", { cache: "no-store" });
    if (response.status === 404) {
      showTime(dashboardTime, dashboardElapsed, null, "Po ponownym uruchomieniu");
      showTime(bootTime, bootElapsed, null, "Po ponownym uruchomieniu");
      summary.textContent = "Nowy odczyt statusu będzie dostępny po ponownym uruchomieniu start-dev.cmd.";
      summary.dataset.tone = "idle";
      return;
    }
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const status = await response.json();
    showTime(
      dashboardTime,
      dashboardElapsed,
      status.dashboard_started_at,
      "Brak zapisu startu",
      "Czas pojawi się po następnym uruchomieniu start-dev.cmd.",
    );
    showTime(bootTime, bootElapsed, status.system_booted_at, "Nie udało się odczytać");
    summary.textContent = "Dashboard jest dostępny, a API odpowiada. Nie ma potrzeby restartu profilaktycznego.";
    summary.dataset.tone = "saved";
  } catch {
    showTime(dashboardTime, dashboardElapsed, null, "Brak połączenia");
    showTime(bootTime, bootElapsed, null, "Brak danych");
    summary.textContent = "Nie udało się pobrać statusu. Sprawdź usługi; restart dashboardu może pomóc.";
    summary.dataset.tone = "error";
  }
}

refreshButton?.addEventListener("click", refreshStatus);
refreshStatus();
setInterval(refreshStatus, 60_000);
