import { fetchDashboardEvents } from "./events-api.js";
import {
  buildCinemaCitySummary,
  getCinemaCityMembershipState,
  formatAvailableScreeningCount,
  formatCinemaStats,
  isCinemaStatsAuthError,
} from "./cinema-city.js";
import { fetchCinemaCityMonthlyStats } from "./cinema-city-stats-adapter.js";
import { fetchCinemaCityRepertoire } from "./cinema-city-repertoire-adapter.js";
import { formatLoadedAt, startLoadTimer } from "./load-timing.js";

const AUTO_REFRESH_INTERVAL_MS = 5 * 60 * 1000;
const FOCUS_REFRESH_MIN_AGE_MS = 60 * 1000;
const COUNTDOWN_REFRESH_INTERVAL_MS = 60 * 1000;
const EVENTS_WINDOW_DAYS = 45;

const card = document.getElementById("cinema-city-card");
const monthly = document.getElementById("cinema-city-monthly");
const todayList = document.getElementById("cinema-city-today");
const watchlist = document.getElementById("cinema-city-watchlist");
const footer = document.getElementById("cinema-city-foot");
const countdown = document.getElementById("cinema-city-countdown");
const countdownValue = document.getElementById("cinema-city-countdown-value");

let state = {
  loading: false,
  loadedAt: null,
  refreshError: null,
};
let refreshTimer = 0;
let countdownTimer = 0;
let refreshInFlight = null;
let lastRefreshAt = 0;

if (card && monthly && todayList && watchlist) {
  initCinemaCityWidget();
}

async function initCinemaCityWidget() {
  if (!renderMembershipCountdown()) return;
  startMembershipCountdown();
  await loadCinemaData();
  startAutoRefresh();
}

function renderMembershipCountdown() {
  const membership = getCinemaCityMembershipState();
  if (!membership.active) {
    card.hidden = true;
    card.dataset.membershipInactive = "true";
    if (refreshTimer) window.clearInterval(refreshTimer);
    if (countdownTimer) window.clearInterval(countdownTimer);
    return false;
  }

  delete card.dataset.membershipInactive;
  card.classList.toggle("is-last-chance", membership.days < 7);
  if (countdown) countdown.hidden = false;
  if (countdownValue) {
    countdownValue.textContent = membership.days > 0
      ? formatPolishDays(membership.days)
      : "Dzisiaj ostatni dzień Unlimited";
  }
  return true;
}

function startMembershipCountdown() {
  if (countdownTimer) return;
  countdownTimer = window.setInterval(renderMembershipCountdown, COUNTDOWN_REFRESH_INTERVAL_MS);
}

function formatPolishDays(days) {
  if (days === 1) return "1 dzień";
  return `${days} dni`;
}

async function loadCinemaData(options = {}) {
  if (refreshInFlight) return refreshInFlight;
  const preserveOnError = Boolean(options.preserveOnError);
  state.loading = true;
  if (!preserveOnError) renderLoading();

  refreshInFlight = (async () => {
    const stopTimer = startLoadTimer();
    try {
      const [eventsPayload, monthlyStats, repertoire] = await Promise.all([
        fetchDashboardEvents({
          includeLocal: false,
          requireGoogle: true,
          showPastEvents: false,
          sync: false,
          windowDays: EVENTS_WINDOW_DAYS,
        }).catch((error) => ({ events: [], error })),
        fetchCinemaCityMonthlyStats().catch((error) => ({
          configured: false,
          error: error?.message || String(error || "cinema_stats_failed"),
          status: error?.status || null,
        })),
        fetchCinemaCityRepertoire().catch((error) => ({
          ok: false,
          events: [],
          error,
        })),
      ]);
      if (repertoire.ok !== true && eventsPayload.error) throw repertoire.error || eventsPayload.error;
      const loadedAt = new Date().toISOString();
      const sourceEvents = repertoire.ok === true ? repertoire.events : eventsPayload.events;
      const summary = buildCinemaCitySummary(sourceEvents, monthlyStats);
      state = {
        loading: false,
        loadedAt,
        refreshError: null,
        loadMs: stopTimer(),
      };
      lastRefreshAt = Date.now();
      renderSummary(summary);
    } catch (error) {
      state = {
        ...state,
        loading: false,
        refreshError: error?.message || String(error || "cinema_load_failed"),
      };
      if (!preserveOnError) renderError();
      else renderFooter();
    } finally {
      refreshInFlight = null;
    }
  })();

  return refreshInFlight;
}

function renderLoading() {
  monthly.textContent = "Ładowanie kina...";
  todayList.replaceChildren(createEmpty("Ładuję dostępne seanse..."));
  watchlist.replaceChildren();
  if (footer) footer.textContent = "ostatnia aktualizacja: ładowanie...";
}

function renderSummary(summary) {
  card.classList.toggle("is-error", false);
  renderMonthlyStats(summary);
  renderToday(summary.todayScreenings);
  renderMovies(summary.movies);
  renderFooter();
  document.dispatchEvent(new Event("dashboard:net"));
}

function renderMonthlyStats(summary) {
  monthly.replaceChildren();
  if (isCinemaStatsAuthError(summary.stats?.error)) {
    monthly.append("statystyki kina: ");
    const link = document.createElement("a");
    link.className = "cinema-auth-link";
    link.href = "/api/google-calendar/auth/start";
    link.textContent = "połącz ponownie";
    monthly.appendChild(link);
    return;
  }
  monthly.textContent = formatCinemaStats(summary.stats, summary.monthLabel);
}

function renderToday(items) {
  todayList.replaceChildren();
  if (!items.length) {
    todayList.appendChild(createEmpty("Brak dostępnych seansów dzisiaj"));
    return;
  }
  items.forEach((item) => {
    const row = document.createElement("li");
    row.className = "cinema-row cinema-row--today";

    const time = document.createElement("span");
    time.className = "cinema-time";
    time.textContent = item.startTime;

    const title = document.createElement("span");
    title.className = "cinema-title";
    title.textContent = item.title;

    row.append(time, title);
    todayList.appendChild(row);
  });
}

function renderMovies(items) {
  watchlist.replaceChildren();
  if (!items.length) {
    watchlist.appendChild(createEmpty("Brak dostępnych filmów"));
    return;
  }
  items.forEach((item) => {
    const row = document.createElement("li");
    row.className = "cinema-row cinema-row--movie";

    const title = document.createElement("span");
    title.className = "cinema-title";
    title.textContent = item.title;

    const count = document.createElement("span");
    count.className = "cinema-count";
    count.textContent = formatAvailableScreeningCount(item.count);

    const status = document.createElement("span");
    status.className = `cinema-status ${statusClass(item.status)}`;
    status.textContent = item.status;

    row.append(title, count, status);
    watchlist.appendChild(row);
  });
}

function renderError() {
  card.classList.toggle("is-error", true);
  monthly.textContent = "— filmów | — zł / film";
  todayList.replaceChildren(createEmpty("Nie udało się pobrać danych kina"));
  watchlist.replaceChildren();
  renderFooter("ostatnia aktualizacja: błąd odświeżania");
}

function renderFooter(text) {
  if (!footer) return;
  if (text) {
    footer.textContent = text;
    return;
  }
  footer.textContent = state.loadedAt
    ? `ostatnia aktualizacja: ${formatCinemaLoadedAt(state.loadedAt)}`
    : "ostatnia aktualizacja: —";
}

function formatCinemaLoadedAt(value) {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return formatLoadedAt(value);
  const weekday = date.toLocaleDateString("pl-PL", { weekday: "short" });
  return `${weekday} ${formatLoadedAt(date)}`;
}

function createEmpty(text) {
  const item = document.createElement("li");
  item.className = "cinema-empty";
  item.textContent = text;
  return item;
}

function statusClass(status) {
  if (status === "często grany") return "is-frequent";
  if (status === "OK") return "is-ok";
  if (status === "event") return "is-event";
  return "is-ending";
}

function startAutoRefresh() {
  if (refreshTimer) return;
  refreshTimer = window.setInterval(() => {
    refreshCinemaData("interval");
  }, AUTO_REFRESH_INTERVAL_MS);

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") refreshCinemaData("visible");
  });
  window.addEventListener("focus", () => refreshCinemaData("focus"));
}

function refreshCinemaData(reason) {
  if (document.visibilityState === "hidden") return;
  if (refreshInFlight) return;

  const now = Date.now();
  const minAge = reason === "interval" ? AUTO_REFRESH_INTERVAL_MS - 1000 : FOCUS_REFRESH_MIN_AGE_MS;
  if (lastRefreshAt && now - lastRefreshAt < minAge) return;

  loadCinemaData({ preserveOnError: true });
}
