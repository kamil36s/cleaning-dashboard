const root = document.getElementById("football-content");
const notice = document.getElementById("football-notice");
const tabs = new Set(["overview", "live", "players", "learn", "search", "matches", "clubs", "competitions", "news", "sources", "following", "settings"]);
let data = null;
let presentationSettings = { kitchenMaxSlides: 6, kitchenShowStandings: true, kitchenShowUpcoming: true };
let tab = "overview";
let matchFilters = { period: "all", date: "", country: "", competition: "", status: "", followed: false };
let clubQuery = "";
let competitionQuery = "";
let renderVersion = 0;
let searchTimer;
let refreshPending = false;
let lastRefresh = 0;

const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
const fmtDate = (value) => {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : new Intl.DateTimeFormat("pl-PL", { dateStyle: "medium", timeStyle: "short" }).format(date);
};
const fmtAge = (seconds) => seconds == null ? "brak" : seconds < 60 ? `${seconds} s` : seconds < 3600 ? `${Math.round(seconds / 60)} min` : `${Math.round(seconds / 3600)} h`;
const badge = (label, kind = "") => `<span class="football-badge ${kind}">${escapeHtml(label)}</span>`;
const empty = (message) => `<div class="football-empty">${escapeHtml(message)}</div>`;
const table = (heads, rows) => `<div class="football-table-wrap"><table class="football-table"><thead><tr>${heads.map(head => `<th>${escapeHtml(head)}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table></div>`;
const cell = (text) => `<td>${escapeHtml(text)}</td>`;
const crest = (url) => url ? `<img class="football-crest" src="/api/kitchen/image?u=${encodeURIComponent(url)}" alt="" loading="lazy">` : "";

function message(text, error = false) {
  notice.hidden = !text;
  notice.textContent = text || "";
  notice.style.background = error ? "#623338" : "#315446";
}

async function load() {
  try {
    const response = await fetch("/api/football", { cache: "no-store" });
    const payload = await response.json();
    if (!response.ok || !payload.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    data = payload;
    try {
      const settingsResponse = await fetch("/api/football/settings", { cache: "no-store" });
      if (settingsResponse.ok) presentationSettings = await settingsResponse.json();
    } catch { /* The desktop remains readable if settings are temporarily unavailable. */ }
    const cache = data.cache[0];
    document.getElementById("football-freshness").textContent = `Lokalny zapis: ${fmtDate(data.updatedAt)} · ${cache.status === "fresh" ? "świeży" : "starszy"} (${fmtAge(cache.ageSeconds)})`;
    render();
  } catch (error) {
    if (!data) root.innerHTML = empty(`Nie udało się odczytać danych: ${error.message}`);
    else message(`Pozostawiono ostatnie dane: ${error.message}`, true);
  }
}

function matchTime(row) { return row.kickoffAt || row.playedAt || ""; }
function isFollowedMatch(row) { return (row.clubKeys || []).some(key => data.following.teams.includes(key)) || data.following.competitions.includes(row.competitionKey); }
function scoreLabel(row) { const score = row.score || {}; return score.home != null && score.away != null ? `${score.home} : ${score.away}` : row.category === "live" ? "LIVE" : "—"; }
function matchRows(matches) {
  return matches.map(row => `<tr>
    <td>${escapeHtml(fmtDate(matchTime(row)))}<small>${escapeHtml(row.category)}</small></td>
    <td>${escapeHtml(row.competitionName || row.leagueName || row.teamName || row.competitionKey)}</td>
    <td>${crest(row.home?.crest)}${entityLink("club", row.clubKeys?.[0], row.home?.name || "?")}</td>
    <td><strong>${escapeHtml(scoreLabel(row))}</strong><small>${escapeHtml(row.liveUnverified ? "niezweryfikowany live · " : "")}${escapeHtml(row.status || "")}</small></td>
    <td>${crest(row.away?.crest)}${entityLink("club", row.clubKeys?.[1], row.away?.name || "?")}</td>
    <td>${escapeHtml(row.provider || "?")}<small>${escapeHtml(row.id || "")}</small></td>
    <td>${entityLink("match", row.id, "Szczegóły meczu")}<details><summary>Źródło</summary><div class="football-small">Aktualizacja: ${escapeHtml(fmtDate(row.sourceUpdatedAt))}<br>Runda: ${escapeHtml(row.round || "—")}<br>Powiązane kluby: ${escapeHtml((row.clubKeys || []).join(", "))}<br>Herb gospodarzy: ${escapeHtml(row.home?.crestSource || "brak")}<br>Herb gości: ${escapeHtml(row.away?.crestSource || "brak")}</div></details></td>
  </tr>`);
}
function matchTable(matches) { return matches.length ? table(["Data", "Rozgrywki", "Gospodarze", "Wynik", "Goście", "Źródło", ""], matchRows(matches)) : empty("Brak meczów w zapisanym lokalnie zakresie."); }

function renderOverview() {
  const followed = data.matches.filter(isFollowedMatch);
  const upcoming = followed.filter(row => row.category === "upcoming").sort((a, b) => matchTime(a).localeCompare(matchTime(b))).slice(0, 8);
  const results = followed.filter(row => row.category === "result").sort((a, b) => matchTime(b).localeCompare(matchTime(a))).slice(0, 8);
  const live = followed.filter(row => row.category === "live" && !row.liveUnverified);
  const issue = data.sourceErrors.length || data.stale;
  return `<section><h2>Overview</h2>${issue ? `<div class="football-warning">${data.stale ? "Lokalne dane są starsze niż TTL. " : ""}${data.sourceErrors.length} problemów źródeł — szczegóły w Sources & Data.</div>` : ""}
    <div class="football-grid"><div class="football-card"><span>Live potwierdzone w cache</span><strong>${live.length}</strong></div><div class="football-card"><span>Wyniki w cache</span><strong>${data.stored.matches}</strong></div><div class="football-card"><span>Mecze zapisane lokalnie</span><strong>${data.storedData?.matches ?? data.stored.matches}</strong></div><div class="football-card"><span>Śledzone kluby</span><strong>${data.following.teams.length}</strong></div></div>
    <div class="football-columns football-section"><section class="football-panel"><h3>Najbliższe śledzone mecze</h3>${matchTable(upcoming)}</section><section class="football-panel"><h3>Ostatnie wyniki</h3>${matchTable(results)}</section></div>
    <section class="football-panel football-section"><h3>Wiadomości</h3>${empty(data.newsStatus)}</section></section>`;
}

function periodMatches(rows) {
  const today = new Date();
  const day = value => new Date(value).toLocaleDateString("sv-SE");
  const offset = days => { const date = new Date(today); date.setDate(date.getDate() + days); return day(date); };
  return rows.filter(row => {
    const when = matchTime(row);
    if (!when) return matchFilters.period === "all";
    const date = day(when);
    switch (matchFilters.period) {
      case "yesterday": return date === offset(-1);
      case "today": return date === offset(0);
      case "tomorrow": return date === offset(1);
      case "24h": return today - new Date(when) >= 0 && today - new Date(when) <= 86400000;
      case "custom": return date === matchFilters.date;
      case "upcoming": return row.category === "upcoming";
      default: return true;
    }
  });
}
function renderMatches() {
  const keysWithMatches = new Set(data.matches.map(row => row.competitionKey));
  const competitionOptions = data.competitions.filter(item => keysWithMatches.has(item.key)).map(item => `<option value="${escapeHtml(item.key)}" ${matchFilters.competition === item.key ? "selected" : ""}>${escapeHtml(item.name)}</option>`).join("");
  const countryOptions = [...new Set(data.competitions.map(item => item.country).filter(Boolean))].sort().map(country => `<option value="${escapeHtml(country)}" ${matchFilters.country === country ? "selected" : ""}>${escapeHtml(country)}</option>`).join("");
  let rows = periodMatches(data.matches);
  if (matchFilters.followed) rows = rows.filter(isFollowedMatch);
  if (matchFilters.competition) rows = rows.filter(row => row.competitionKey === matchFilters.competition);
  if (matchFilters.country) {
    const keys = new Set(data.competitions.filter(item => item.country === matchFilters.country).map(item => item.key));
    rows = rows.filter(row => keys.has(row.competitionKey));
  }
  if (matchFilters.status) rows = rows.filter(row => row.category === matchFilters.status);
  rows.sort((a, b) => matchTime(a).localeCompare(matchTime(b)));
  return `<section><h2>Matches</h2><div class="football-toolbar">
    <label>Okres<select id="football-period">${[["all","Wszystkie w cache"],["yesterday","Wczoraj"],["today","Dzisiaj"],["tomorrow","Jutro"],["24h","Ostatnie 24 godziny"],["upcoming","Nadchodzące"],["custom","Wybrany dzień"]].map(([value,label]) => `<option value="${value}" ${matchFilters.period === value ? "selected" : ""}>${label}</option>`).join("")}</select></label>
    ${matchFilters.period === "custom" ? `<label>Data<input type="date" id="football-custom-date" value="${escapeHtml(matchFilters.date)}"></label>` : ""}
    <label>Kraj / grupa<select id="football-country-filter"><option value="">Wszystkie</option>${countryOptions}</select></label>
    <label>Rozgrywki<select id="football-competition-filter"><option value="">Wszystkie dostępne</option>${competitionOptions}</select></label>
    <label>Typ<select id="football-status-filter"><option value="">Wszystkie</option>${["live","result","upcoming"].map(value => `<option value="${value}" ${matchFilters.status === value ? "selected" : ""}>${value}</option>`).join("")}</select></label>
    <label><span>Śledzone</span><input id="football-followed-filter" type="checkbox" ${matchFilters.followed ? "checked" : ""}></label>
  </div><p class="football-note">${rows.length} meczów w lokalnym zapisie. Starsze dane pojawiają się od momentu uruchomienia nowego magazynu.</p>${matchTable(rows)}</section>`;
}

function renderClubs() {
  const rows = data.clubs.filter(item => item.name?.toLocaleLowerCase().includes(clubQuery.toLocaleLowerCase()));
  return `<section><h2>Clubs</h2><div class="football-toolbar"><label>Szukaj klubu<input id="football-club-query" value="${escapeHtml(clubQuery)}" placeholder="Nazwa klubu"></label></div>
    ${table(["Klub", "Obserwacja", "Mecze zapisane", "Mapowania / nazwy", "Herb"], rows.map(item => {
      const matches = data.matches.filter(row => (row.clubKeys || []).includes(item.key));
      const sources = [...new Set(matches.map(row => row.provider).filter(Boolean))];
      return `<tr><td>${crest(item.crest)}<details><summary>${entityLink("club", item.key, item.name)}</summary><div class="football-details football-small">Źródła meczów: ${escapeHtml(sources.join(", ") || "brak")}<br>${matches.length ? matchTable(matches.slice(0, 8)) : "Brak zapisanych meczów."}</div></details></td><td>${item.followed ? badge("śledzony") : "—"}</td>${cell(matches.length)}<td><small>${escapeHtml(item.names.join(" · "))}</small><small>${escapeHtml(JSON.stringify(item.providerIds))}</small></td><td>${escapeHtml(item.crestSource || "brak")}</td></tr>`;
    }))}</section>`;
}
function renderCompetitions() {
  const rows = data.competitions.filter(item => item.name?.toLocaleLowerCase().includes(competitionQuery.toLocaleLowerCase()));
  return `<section><h2>Competitions</h2><div class="football-toolbar"><label>Szukaj rozgrywek<input id="football-competition-query" value="${escapeHtml(competitionQuery)}" placeholder="Nazwa rozgrywek"></label></div>
    ${table(["Rozgrywki", "Status", "Źródła", "Mecze", "Tabela"], rows.map(item => {
      const matches = data.matches.filter(row => row.competitionKey === item.key);
      return `<tr><td><details><summary>${entityLink("competition", item.key, item.name)}</summary><small>${escapeHtml(item.key)}</small><div class="football-details">${matches.length ? matchTable(matches.slice(0, 12)) : empty("Brak zapisanych meczów.")}</div></details></td><td>${item.followed ? badge("śledzone") : "dostępne"}</td>${cell(item.providers.join(", ") || "brak")}${cell(matches.length)}<td>${item.standings?.rows?.length ? `<details><summary>${item.standings.rows.length} drużyn</summary>${table(["#", "Klub", "Pkt", "Mecze"], item.standings.rows.map(row => `<tr>${cell(row.position || row.rank || "")}${cell(row.name)}${cell(row.points || "")}${cell(row.played || row.gamesPlayed || "")}</tr>`))}</details>` : "Brak tabeli w cache"}</td></tr>`;
    }))}</section>`;
}
function renderNews() { return `<section><h2>News</h2>${empty(data.newsStatus)}<p class="football-note">Ta sekcja czeka na dozwolone i sprawdzone źródło RSS lub API. Aplikacja nie pobiera artykułów przez scraping.</p></section>`; }

function renderSources() {
  const requests = data.requests || [];
  const runs = data.runs || [];
  const providerRows = data.providers.map(item => `<tr><td><details><summary>${escapeHtml(item.name)}</summary><div class="football-small">Typ: ${escapeHtml(item.type)}<br>Ostatni sukces: ${escapeHtml(fmtDate(item.lastSuccess))}<br>Ostatni błąd: ${escapeHtml(fmtDate(item.lastFailure))}<br>Klucz API: ${item.name === "API-Football" ? item.configured ? "skonfigurowany" : "brak" : "nie dotyczy"}<br>Żądania: ${escapeHtml(requests.filter(row => row.provider === item.name).length)} w ograniczonej historii<br>${item.usage ? `Lokalny limit minutowy: ${escapeHtml(item.usage.minute)} / ${escapeHtml(item.usage.minuteLimit)} · błędy z rzędu: ${escapeHtml(item.usage.consecutiveFailures)}<br>` : ""}${item.type === "REST API" ? "Kontrola: 30 s scoreboard/live, 5 min inne JSON, 30 min endpoint standings; HTTP 429 uruchamia cooldown do 1 h." : "Brak instrumentacji żądań tego źródła."}</div></details></td><td>${item.configured ? "tak" : "nie"}</td><td>${escapeHtml(item.features.join(", "))}</td><td>${escapeHtml(item.health)}${item.cooldownSeconds ? ` (${escapeHtml(fmtAge(item.cooldownSeconds))})` : ""}</td><td>${escapeHtml(fmtDate(item.lastRequest?.at))}</td><td>${escapeHtml(item.lastRequest?.status ?? "—")}</td></tr>`);
  const requestRows = requests.map(row => `<tr>${cell(fmtDate(row.at))}${cell(row.provider)}${cell(row.endpoint)}${cell(row.status ?? "błąd")}${cell(row.durationMs != null ? `${row.durationMs} ms` : "—")}${cell(row.received ?? "—")}${cell(row.error || "—")}</tr>`);
  const runRows = runs.map(row => `<tr>${cell(fmtDate(row.at))}${cell(row.status)}${cell(row.receivedNormalized)}${cell(row.storedMatches)}${cell(row.duplicates)}${cell(row.upcoming)}${cell((row.sourceErrors || []).join("; ") || row.error || "—")}</tr>`);
  return `<section><h2>Sources &amp; Data</h2><p class="football-note">${escapeHtml(data.storageNote)}</p>
    <div class="football-grid">${Object.entries(data.stored).map(([key,value]) => `<div class="football-card"><span>${escapeHtml(key)}</span><strong>${escapeHtml(value)}</strong></div>`).join("")}</div>
    <section class="football-section"><h3>Trwały zapis SQLite</h3>${table(["Typ", "Rekordy"], Object.entries(data.storedData || {}).map(([key,value]) => `<tr>${cell(key)}${cell(value)}</tr>`))}</section>
    <section class="football-section"><h3>Providerzy i możliwości</h3>${table(["Źródło", "Włączony", "Możliwości", "Ostatni stan", "Ostatnie żądanie", "HTTP"], providerRows)}</section>
    <section class="football-section"><h3>Cache</h3>${table(["Klucz", "Dane", "Zapisano", "Wiek", "TTL", "Stan", "Rekordy"], data.cache.map(row => `<tr>${cell(row.key)}${cell(row.type)}${cell(fmtDate(row.updatedAt))}${cell(fmtAge(row.ageSeconds))}${cell(fmtAge(row.ttlSeconds))}<td>${badge(row.status, row.status === "fresh" ? "" : "warn")}</td>${cell(row.recordCount)}</tr>`))}</section>
    <section class="football-section"><h3>Błędy i fallback</h3>${data.sourceErrors.length ? data.sourceErrors.map(error => `<p class="football-warning">${escapeHtml(error)}</p>`).join("") : empty("Brak zgłoszonych błędów w ostatnim zapisanym payloadzie.")}<p class="football-note">Fallback wyników: ${data.fallback.scores ? "tak" : "nie"}; terminarza: ${data.fallback.fixtures ? "tak" : "nie"}. Błędy przechwycone głębiej w starszych adapterach mogą nie być zgłoszone.</p></section>
    <section class="football-section"><h3>Śledzone bez meczu w bieżącym cache</h3>${(data.missingData || []).length ? table(["Typ", "Klucz", "Nazwa", "Wyjaśnienie"], data.missingData.map(row => `<tr>${cell(row.type)}${cell(row.key)}${cell(row.name)}${cell(row.explanation)}</tr>`)) : empty("Każdy śledzony klub i rozgrywki mają mecz w bieżącym cache.")}<p class="football-note">Te wskazówki nie rozstrzygają, czy provider nie miał meczu, czy odpowiedź była niepełna. Historia żądań pokazuje ostatnie HTTP i liczbę odebranych rekordów.</p></section>
    <section class="football-section"><h3>Ostatnie synchronizacje</h3>${runs.length ? table(["Czas", "Stan", "Przed deduplikacją", "Zapisane", "Duplikaty", "Przyszłe", "Błędy"], runRows) : empty("Historia synchronizacji zacznie się zapełniać przy kolejnych odświeżeniach Kitchen.")}</section>
    <section class="football-section"><h3>Historia żądań</h3>${requests.length ? table(["Czas", "Provider", "Endpoint", "HTTP", "Czas", "Odebrane", "Błąd"], requestRows) : empty("Brak zarejestrowanych żądań od uruchomienia diagnostyki.")}</section>
    <section class="football-section"><h3>Mapowania providerów</h3>${(data.mappings || []).length ? table(["Typ", "Provider", "ID zewnętrzne", "Encja lokalna", "Nazwa", "Widziano"], data.mappings.map(row => `<tr>${cell(row.entity_type)}${cell(row.provider)}${cell(row.external_id)}${cell(row.entity_key)}${cell(row.observed_name)}${cell(fmtDate(row.updated_at))}</tr>`)) : empty("Brak mapowań w lokalnym zapisie.")}</section>
    <section class="football-section"><h3>Konflikty mapowań</h3>${(data.mappingConflicts || []).length ? table(["Typ", "Provider", "ID zewnętrzne", "Istniejący klucz", "Nowy klucz", "Widziano"], data.mappingConflicts.map(row => `<tr>${cell(row.entity_type)}${cell(row.provider)}${cell(row.external_id)}${cell(row.existing_key)}${cell(row.proposed_key)}${cell(fmtDate(row.updated_at))}</tr>`)) : empty("Brak wykrytych konfliktów mapowań.")}</section>
    <section class="football-section"><h3>Możliwe duplikaty meczów</h3>${(data.duplicateCandidates || []).length ? table(["Rozgrywki", "Data", "Kluby", "Rekordy źródeł"], data.duplicateCandidates.map(row => `<tr>${cell(row.competitionKey)}${cell(row.date)}${cell(`${row.homeKey} – ${row.awayKey}`)}${cell(row.sources.map(source => `${source.provider}: ${source.id} (${source.category})`).join("; "))}</tr>`)) : empty("Brak kandydatów o tych samych klubach i dniu.")}<p class="football-note">Kandydaci są tylko do wglądu. System nie scala automatycznie meczów na podstawie samej nazwy i daty.</p></section>
    <section class="football-section"><h3>Źródła herbów</h3>${table(["Klub", "Wybrany zasób", "Źródło"], data.clubs.filter(item => item.followed || item.matchCount).slice(0, 100).map(item => `<tr><td>${crest(item.crest)}${escapeHtml(item.name)}</td>${cell(item.crest || "brak")}${cell(item.crestSource || "brak")}</tr>`))}</section>
    <section class="football-section"><h3>Przykładowe rekordy po normalizacji</h3><p class="football-note">Oryginalne odpowiedzi providerów nie są zapisywane; widoczny jest ograniczony przykład wewnętrznego rekordu.</p>${(data.matches || []).slice(0, 20).map(row => `<details class="football-panel football-section"><summary>${escapeHtml(row.provider || "?")} ${escapeHtml(row.id || "")} · ${entityLink("club", row.clubKeys?.[0], row.home?.name || "?")} – ${entityLink("club", row.clubKeys?.[1], row.away?.name || "?")}</summary><pre class="football-code">${escapeHtml(JSON.stringify(row, null, 2))}</pre></details>`).join("") || empty("Brak rekordów do inspekcji.")}</section>
    <section class="football-panel football-section"><h3>Dlaczego danych może brakować?</h3><p class="football-note">Wyniki Kitchen są ograniczone do ${escapeHtml(data.following.windowHours)} godzin. Tylko śledzone rozgrywki i zespoły są pobierane. Terminarz ma osobny cache. Pusty wynik może oznaczać brak danych u providera, filtr czasu lub błąd; obecne adaptery nie rozróżniają jeszcze wszystkich tych przypadków.</p></section></section>`;
}

function renderFollowing() {
  const knownTeams = data.clubs.filter(item => !item.key.startsWith("name-"));
  return `<section><h2>Following</h2><p class="football-note">Zmiany używają istniejących ustawień Kitchen i wpływają na następne odświeżenie jego danych. Dostępne kluby pochodzą z obecnego katalogu providerów.</p>
    <div class="football-columns"><section class="football-panel"><h3>Kluby (${data.following.teams.length})</h3><div class="football-list">${knownTeams.map(item => `<label class="football-choice"><input type="checkbox" name="team" value="${escapeHtml(item.key)}" ${item.followed ? "checked" : ""}>${crest(item.crest)}${escapeHtml(item.name)}<small>${entityLink("club",item.key,"Profil")}</small></label>`).join("")}</div></section>
    <section class="football-panel"><h3>Rozgrywki (${data.following.competitions.length})</h3><div class="football-list">${data.competitions.map(item => `<label class="football-choice"><input type="checkbox" name="competition" value="${escapeHtml(item.key)}" ${item.followed ? "checked" : ""}>${escapeHtml(item.name)}<small>${entityLink("competition",item.key,"Profil")}</small></label>`).join("")}</div></section></div>
    <div class="football-actions"><button type="button" class="football-button" id="football-save-following">Zapisz obserwowane</button></div></section>`;
}
function renderSettings() {
  return `<section><h2>Settings</h2><div class="football-columns"><section class="football-panel"><h3>Okno wyników Kitchen</h3><p class="football-note">Obecnie ${escapeHtml(data.following.windowHours)} godzin. Zmiana przeliczy listę ostatnich wyników przy następnym odświeżeniu.</p><div class="football-toolbar"><label>Godziny<select id="football-window">${[24,48,72,96,168].map(value => `<option value="${value}" ${data.following.windowHours === value ? "selected" : ""}>${value}</option>`).join("")}</select></label><button id="football-save-window" type="button">Zapisz</button></div></section>
    <section class="football-panel"><h3>Tabele Kitchen</h3><p class="football-note">Tabela pojawia się tylko dla zaznaczonych rozgrywek i gdy są dostępne dane.</p><div class="football-list">${data.competitions.filter(item => item.followed).map(item => `<label class="football-choice"><input type="checkbox" name="standing" value="${escapeHtml(item.key)}" ${data.following.standings.includes(item.key) ? "checked" : ""}>${escapeHtml(item.name)}</label>`).join("") || empty("Brak śledzonych rozgrywek.")}</div><div class="football-actions"><button class="football-button" id="football-save-standings" type="button">Zapisz tabele</button></div></section></div>
    <section class="football-panel football-section"><h3>Karuzela Kitchen</h3><p class="football-note">Najpierw mecze śledzonych drużyn, potem najbliższe mecze i wyniki. Limit dotyczy normalnej rotacji, a aktywny mecz live ma pierwszeństwo.</p><div class="football-toolbar"><label>Maksimum slajdów<input id="football-max-slides" type="number" min="1" max="12" value="${escapeHtml(presentationSettings.kitchenMaxSlides)}"></label></div><div class="football-list"><label class="football-choice"><input id="football-show-upcoming" type="checkbox" ${presentationSettings.kitchenShowUpcoming ? "checked" : ""}>Pokazuj przyszłe mecze</label><label class="football-choice"><input id="football-show-standings" type="checkbox" ${presentationSettings.kitchenShowStandings ? "checked" : ""}>Dopuszczaj tabele ligowe</label></div><div class="football-actions"><button class="football-button" id="football-save-presentation" type="button">Zapisz karuzelę</button></div></section>
    <p class="football-note">Pełne ustawienia tabletu, przepisu i innych ekranów są nadal dostępne w <a href="./settings.html#kitchen-dashboard">ustawieniach Kitchen</a>.</p></section>`;
}

function render() {
  if (!data) return;
  const route = location.hash.slice(1).split("/");
  const version = ++renderVersion;
  if (["club", "competition", "player", "stadium"].includes(route[0])) {
    document.querySelectorAll("[data-tab]").forEach(link => link.setAttribute("aria-current", "false"));
    root.innerHTML = empty("Ładowanie profilu…");
    renderEntity(route, version);
    return;
  }
  if (route[0] === "match") { root.innerHTML = renderMatch(decodeURIComponent(route[1] || "")); return; }
  tab = tabs.has(route[0]) ? route[0] : "overview";
  if (["players", "search", "learn"].includes(tab)) {
    document.querySelectorAll("[data-tab]").forEach(link => link.setAttribute("aria-current", link.dataset.tab === tab ? "page" : "false"));
    renderCollection(tab, version);
    return;
  }
  document.querySelectorAll("[data-tab]").forEach(link => link.setAttribute("aria-current", link.dataset.tab === tab ? "page" : "false"));
  root.innerHTML = ({ overview: renderOverview, live: renderLive, matches: renderMatches, clubs: renderClubs, competitions: renderCompetitions, news: renderNews, sources: renderSources, following: renderFollowing, settings: renderSettings })[tab]();
  if (tab === "live" && Date.now() - lastRefresh > 30000) refreshShared();
}

async function saveSports(partial) {
  try {
    const response = await fetch("/api/kitchen/settings", { cache: "no-store" });
    const current = await response.json();
    if (!response.ok || !current.ok) throw new Error(current.error || `HTTP ${response.status}`);
    if (partial.enabledTeamKeys) {
      const visible = new Set(data.clubs.filter(item => !item.key.startsWith("name-")).map(item => item.key));
      partial.enabledTeamKeys.push(...(current.sports.enabledTeamKeys || []).filter(key => !visible.has(key)));
    }
    if (partial.enabledLeagueKeys) {
      const visible = new Set(data.competitions.map(item => item.key));
      partial.enabledLeagueKeys.push(...(current.sports.enabledLeagueKeys || []).filter(key => !visible.has(key)));
    }
    if (partial.standingsLeagueKeys) {
      const visible = new Set(data.competitions.map(item => item.key));
      partial.standingsLeagueKeys.push(...(current.sports.standingsLeagueKeys || []).filter(key => !visible.has(key)));
    }
    for (const key of ["enabledTeamKeys", "enabledLeagueKeys", "standingsLeagueKeys"]) {
      if (partial[key]) partial[key] = [...new Set(partial[key])];
    }
    const update = await fetch("/api/kitchen/settings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sports: { ...current.sports, ...partial } }) });
    const result = await update.json();
    if (!update.ok || !result.ok) throw new Error(result.error || `HTTP ${update.status}`);
    message("Zapisano ustawienia. Kitchen uwzględni je przy następnym odświeżeniu.");
    await load();
  } catch (error) { message(`Nie zapisano ustawień: ${error.message}`, true); }
}

async function savePresentation() {
  try {
    const payload = {
      kitchenMaxSlides: Number(document.getElementById("football-max-slides").value),
      kitchenShowUpcoming: document.getElementById("football-show-upcoming").checked,
      kitchenShowStandings: document.getElementById("football-show-standings").checked,
    };
    const response = await fetch("/api/football/settings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    const result = await response.json();
    if (!response.ok || !result.ok) throw new Error(result.error || `HTTP ${response.status}`);
    presentationSettings = result;
    message("Zapisano ustawienia karuzeli Kitchen.");
    render();
  } catch (error) { message(`Nie zapisano ustawień: ${error.message}`, true); }
}

root.addEventListener("change", event => {
  if (event.target.id === "football-form-count") {
    root.querySelectorAll("[data-form-index]").forEach(el => { el.hidden = Number(el.dataset.formIndex) >= Number(event.target.value); });
    return;
  }
  if (event.target.id === "football-transfer-year") {
    const route = location.hash.slice(1).split("/");
    route[3] = event.target.value;
    location.hash = route.join("/");
    return;
  }
  if (event.target.id === "football-learn-category") {
    root.querySelectorAll("[data-knowledge-category]").forEach(el => { el.hidden = !!event.target.value && el.dataset.knowledgeCategory !== event.target.value; });
    return;
  }
  if (event.target.id === "football-period") matchFilters.period = event.target.value;
  else if (event.target.id === "football-custom-date") matchFilters.date = event.target.value;
  else if (event.target.id === "football-country-filter") matchFilters.country = event.target.value;
  else if (event.target.id === "football-competition-filter") matchFilters.competition = event.target.value;
  else if (event.target.id === "football-status-filter") matchFilters.status = event.target.value;
  else if (event.target.id === "football-followed-filter") matchFilters.followed = event.target.checked;
  else return;
  render();
});
root.addEventListener("input", event => {
  if (event.target.id === "football-search-query") {
    clearTimeout(searchTimer);
    const query = event.target.value;
    const version = ++renderVersion;
    searchTimer = setTimeout(() => updateSearch(query, version, tab === "players"), 250);
    return;
  }
  if (event.target.id === "football-club-query") clubQuery = event.target.value;
  else if (event.target.id === "football-competition-query") competitionQuery = event.target.value;
  else return;
  const selection = event.target.selectionStart;
  render();
  const input = document.getElementById(event.target.id);
  input?.focus();
  input?.setSelectionRange(selection, selection);
});
root.addEventListener("click", event => {
  const id = event.target.id;
  if (id === "football-save-following") saveSports({ enabledTeamKeys: [...root.querySelectorAll('input[name="team"]:checked')].map(input => input.value), enabledLeagueKeys: [...root.querySelectorAll('input[name="competition"]:checked')].map(input => input.value) });
  if (id === "football-save-window") saveSports({ windowHours: Number(document.getElementById("football-window").value) });
  if (id === "football-save-standings") saveSports({ standingsLeagueKeys: [...root.querySelectorAll('input[name="standing"]:checked')].map(input => input.value) });
  if (id === "football-save-presentation") savePresentation();
});
window.addEventListener("hashchange", render);
load();

function entityLink(kind, key, label, section = "") {
  return key ? `<a href="#${kind}/${encodeURIComponent(key)}${section ? `/${section}` : ""}">${escapeHtml(label)}</a>` : escapeHtml(label);
}
function externalLink(url, label) {
  return /^https?:\/\//i.test(url || "") ? `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(label)} ↗</a>` : escapeHtml(label);
}
async function getFootball(url) {
  const response = await fetch(url, { cache: "no-store" });
  const value = await response.json();
  if (!response.ok || !value.ok) throw new Error(value.error || `HTTP ${response.status}`);
  return value;
}
function cacheNotice(value) {
  const rows = value.cache || [];
  const dates = rows.map(r => r.fetchedAt).filter(Boolean);
  const warning = rows.some(r => r.state !== "fresh");
  const state = rows.some(r => r.error === "rate-limited") ? "Limit źródła — spróbuj później." : warning ? "Źródło niedostępne lub starszy zapis. Pokazujemy dostępne dane." : "Dane z lokalnego cache źródeł.";
  return `<p class="football-note ${warning ? "football-warning" : ""}">${state}${dates.length ? ` Najstarszy użyty zapis: ${fmtDate(new Date(Math.min(...dates) * 1000).toISOString())}.` : ""}</p>`;
}
function renderLive() {
  return `<h2>Live</h2><p class="football-note">Wspólny snapshot Kitchen. Starsze lub niepotwierdzone wyniki mają osobne oznaczenie.</p>${matchTable(data.matches.filter(r => r.category === "live"))}`;
}
async function refreshShared() {
  if (refreshPending) return;
  refreshPending = true;
  lastRefresh = Date.now();
  const button = document.getElementById("football-refresh");
  if (button) button.disabled = true;
  message("Odświeżanie wspólnych danych Kitchen…");
  try {
    data = await getFootball("/api/football/refresh");
    document.getElementById("football-freshness").textContent = `Lokalny zapis: ${fmtDate(data.updatedAt)}`;
    message(data.sourceErrors?.length ? "Część źródeł jest niedostępna. Zachowano dostępne dane; szczegóły w Sources & Data." : "Odświeżono wspólne dane.", !!data.sourceErrors?.length);
    render();
  } catch (error) { message(`Pozostawiono ostatni widok: ${error.message}`, true); }
  finally { refreshPending = false; if (button) button.disabled = false; }
}
document.getElementById("football-refresh")?.addEventListener("click", refreshShared);
const liveTimer = setInterval(() => {
  if (location.hash === "#live" && !document.hidden) refreshShared();
}, 30000);
window.addEventListener("pagehide", () => clearInterval(liveTimer), { once: true });

function standingsTable(competition, clubs = data.clubs) {
  const rows = competition.standings?.rows || [];
  const lookup = name => clubs.find(c => [c.name, ...(c.names || [])].some(n => n?.toLocaleLowerCase() === name?.toLocaleLowerCase()));
  return rows.length ? table(["#", "Klub", "M", "W", "D", "L", "GF", "GA", "GD", "Pkt"], rows.map(row => `<tr>${cell(row.rank ?? row.position ?? "—")}<td>${entityLink("club", lookup(row.name)?.key, row.name)}</td>${[row.played, row.wins, row.draws, row.losses, row.goalsFor, row.goalsAgainst, row.gd, row.points].map(v => cell(v ?? "—")).join("")}</tr>`)) : empty("Brak tabeli w lokalnym cache.");
}
function splitMatches(matches) {
  return `<h3>Nadchodzące</h3>${matchTable(matches.filter(r => r.category === "upcoming").sort((a,b) => matchTime(a).localeCompare(matchTime(b))))}<h3 class="football-section">Wyniki</h3>${matchTable(matches.filter(r => r.category === "result").sort((a,b) => matchTime(b).localeCompare(matchTime(a))))}`;
}
function renderMatch(id) {
  const row = data.matches.find(m => m.id === id);
  if (!row) return empty("Mecz nie jest już dostępny w lokalnym zakresie.");
  const details = Array.isArray(row.details) ? row.details : [];
  return `<h2>${escapeHtml(row.home?.name)} — ${escapeHtml(row.away?.name)}</h2>${matchTable([row])}<h3 class="football-section">Zdarzenia meczu</h3>${details.length ? table(["Minuta", "Typ", "Drużyna", "Zdarzenie"], details.map(d => `<tr>${[d.minute, d.label || d.kind, d.team, d.text].map(cell).join("")}</tr>`)) : empty("Źródło nie dostarczyło zdarzeń tego meczu.")}<p class="football-note">Przejdź do klubu, aby otworzyć skład i profile zawodników.</p>`;
}
function renderStadium(s) {
  if (!s) return empty("Źródło nie dostarczyło stadionu.");
  return `<h2>${escapeHtml(s.name)}</h2><p>${entityLink("club", s.clubKey, s.clubName)}</p>${s.image ? `<img class="football-stadium-image" src="/api/kitchen/image?u=${encodeURIComponent(s.image)}" alt="${escapeHtml(s.name)}">` : ""}${table(["Pole", "Wartość"], [["Lokalizacja", s.city], ["Pojemność", s.capacity], ["Adres", s.address]].map(([k,v]) => `<tr>${cell(k)}${cell(v || "Brak danych")}</tr>`))}<p class="football-note">${externalLink(s.sourceUrl, s.provider)}</p>`;
}
function renderPlayer(value) {
  const p = value.player;
  const stats = value.statistics || {};
  return `<h2>${escapeHtml(p.name)}</h2><p>${crest(p.photo)}${entityLink("club", p.clubKey, p.clubName)}${value.inCurrentSquad === false ? " · nie występuje w ostatnim dostępnym składzie tego klubu" : ""}</p>${table(["Pole", "Wartość"], [["Pełne imię i nazwisko", p.fullName], ["Narodowość", p.nationality], ["Data urodzenia", p.dateOfBirth?.slice(0,10)], ["Pozycja", p.position], ["Numer", p.number]].map(([k,v]) => `<tr>${cell(k)}${cell(v ?? "Brak danych")}</tr>`))}<h3 class="football-section">Statystyki zawodnika</h3>${(stats.splits || []).length ? stats.splits.map(split => `<section class="football-panel football-section"><h3>${escapeHtml(split.displayName || "Zakres dostawcy")}</h3>${table(stats.displayNames || stats.labels || stats.names || [], [`<tr>${(split.stats || []).map(cell).join("")}</tr>`])}</section>`).join("") : empty("Brak statystyk dla zakresu udostępnionego przez źródło.")}<p class="football-note">Sezon i rozgrywki zgodnie z etykietą źródła. ${externalLink(p.sourceUrl, p.provider)}</p>`;
}
async function renderEntity(route, version) {
  const [kind, rawId, section = "overview", year = ""] = route;
  try {
    const key = decodeURIComponent(rawId || "");
    const value = await getFootball(`/api/football/entity?${new URLSearchParams({ type: kind, id: key, section, year })}`);
    if (version !== renderVersion) return;
    let html = "";
    if (kind === "player") html = renderPlayer(value);
    if (kind === "stadium") html = renderStadium(value.stadium);
    if (kind === "competition") {
      const c = value.competition;
      const season = c.season || c.standings?.season || c.standings?.seasonLabel || "Sezon niepodany w cache";
      html = `<h2>${crest(c.logo)}${escapeHtml(c.name)}</h2><p>${escapeHtml(c.country)} · ${escapeHtml(season)} · ${c.followed ? "Obserwowane" : "Nieobserwowane"} · <a href="#following">Zmień obserwowane</a></p><h3>Tabela</h3>${standingsTable(c, [...value.clubs, ...data.clubs])}<h3 class="football-section">Kluby</h3><div class="football-entity-links">${value.clubs.map(c => entityLink("club", c.key, c.name)).join(" · ") || "Brak katalogu klubów."}</div><h3 class="football-section">Live</h3>${matchTable(value.matches.filter(r => r.category === "live"))}<div class="football-section">${splitMatches(value.matches)}</div>`;
    }
    if (kind === "club") {
      const c = value.club;
      const sections = [["overview","Overview"],["squad","Squad"],["coach","Coach"],["form","Form & Stats"],["matches","Fixtures / Results"],["transfers","Transfers"],["stadium","Stadium"],["history","History"]];
      html = `<h2>${crest(c.crest)}${escapeHtml(c.name)}</h2><p>${escapeHtml(c.country || "Kraj: brak danych")} · ${c.competitionKey ? entityLink("competition", c.competitionKey, "Rozgrywki") : ""} · <a href="#following">${c.followed ? "Obserwowany — ustawienia" : "Ustawienia obserwowanych"}</a></p><nav class="football-tabs-secondary">${sections.map(([id,label]) => entityLink("club", key, label, id)).join("")}</nav>`;
      if (section === "squad") {
        const groups = [...new Set((value.players || []).map(p => p.position || "Nieznana pozycja"))];
        html += `<p class="football-note">${escapeHtml(value.availability)}</p>${groups.map(group => `<h3 class="football-section">${escapeHtml(group)}</h3>${table(["Zawodnik", "Numer", "Narodowość", "Urodzony"], value.players.filter(p => (p.position || "Nieznana pozycja") === group).map(p => `<tr><td>${crest(p.photo)}${entityLink("player", p.key, p.name)}</td>${cell(p.number ?? "—")}${cell(p.nationality || "—")}${cell(p.dateOfBirth?.slice(0,10) || "—")}</tr>`))}`).join("") || empty("Brak składu dla tego klubu.")}`;
      } else if (section === "transfers") {
        html += `<div class="football-toolbar"><label>Sezon transferowy (lipiec–czerwiec)<select id="football-transfer-year"><option value="">Wszystkie</option>${Array.from({length:8},(_,i) => new Date().getFullYear()-i).map(y => `<option value="${y}-${y+1}" ${`${y}-${y+1}`===year ? "selected" : ""}>${y}/${y+1}</option>`).join("")}</select></label></div><p class="football-note">${escapeHtml(value.availability)}</p>${["IN","OUT"].map(dir => `<h3 class="football-section">${dir}</h3>${(value.rows || []).some(r => r.direction === dir) ? table(["Zawodnik","Z klubu","Do klubu","Data","Kwota / typ ze źródła"], value.rows.filter(r => r.direction===dir).map(r => `<tr>${[r.player,r.from,r.to,r.date,r.type ?? "Brak danych"].map(cell).join("")}</tr>`)) : empty("Brak dostępnych transferów w tym zakresie.")}`).join("")}`;
      } else if (section === "coach") {
        html += `<p class="football-note">${escapeHtml(value.availability)}</p>${value.rows?.length ? table(["Trener","Narodowość","Od","Źródło"],value.rows.map(c => `<tr><td>${crest(c.photo)}${escapeHtml(c.name)}</td>${[c.nationality || "—",c.appointed,c.provider].map(cell).join("")}</tr>`)) : empty("Brak zweryfikowanego aktualnego trenera.")}`;
      } else if (section === "stadium") {
        html += c.stadium ? `<p>${entityLink("stadium", c.stadium.key, "Otwórz profil stadionu")}</p>${renderStadium(c.stadium)}` : empty("Brak danych stadionu w źródle.");
      } else if (section === "history") {
        html += table(["Pole","Wartość"], [["Założony",c.founded],["Lokalizacja",c.city]].map(([k,v]) => `<tr>${cell(k)}${cell(v || "Brak danych")}</tr>`));
        html += `<p class="football-note">${externalLink(c.sourceUrl,c.metadataSource || "Brak źródła metadanych")}</p><h3 class="football-section">Historia i wiedza</h3><div id="football-club-knowledge">Ładowanie…</div>`;
      } else if (section === "matches") html += splitMatches(value.matches);
      else {
        html += `<p class="football-note">${escapeHtml(value.scope)}</p>${table(["M","W","D","L","GF","GA","GD","Czyste konta"],[`<tr>${["played","wins","draws","losses","goalsFor","goalsAgainst","goalDifference","cleanSheets"].map(k => cell(value.statistics[k])).join("")}</tr>`])}<h3 class="football-section">Forma — najnowszy mecz pierwszy</h3><div class="football-toolbar"><label>Liczba meczów<select id="football-form-count"><option>5</option><option>10</option></select></label></div><div class="football-form">${value.form.map((r,i) => `<span data-form-index="${i}" ${i>=5 ? "hidden" : ""}>${entityLink("match",r.match.id,`${r.result} · ${r.match.home?.name} ${scoreLabel(r.match)} ${r.match.away?.name}`)}</span>`).join("") || "Brak zakończonych meczów."}</div><h3 class="football-section">Pozycja w tabeli / punkty</h3>${value.tables.filter(c => c.standings.rows.length).map(c => `<p>${entityLink("competition",c.key,c.name)}</p>${standingsTable(c)}`).join("") || empty("Brak pozycji w aktualnych tabelach.")}`;
      }
    }
    root.innerHTML = cacheNotice(value) + html;
    if (kind === "club" && section === "history") {
      const content = await getFootball("/api/football/learn");
      if (version === renderVersion) document.getElementById("football-club-knowledge").innerHTML = knowledgeCards(content.items.filter(c => c.relatedClubKeys?.includes(key)));
    }
  } catch (error) {
    if (version === renderVersion) root.innerHTML = empty(`Nie udało się otworzyć profilu: ${error.message}`) + `<button class="football-button" id="football-retry">Spróbuj ponownie</button>`;
  }
}
function knowledgeCards(items) {
  return items.length ? items.map(item => `<article class="football-panel football-section" data-knowledge-category="${escapeHtml(item.category)}"><h3>${escapeHtml(item.title)}</h3><p>${escapeHtml(item.text)}</p><p class="football-note">${externalLink(item.sourceUrl,item.source)} · dodano ${escapeHtml(item.dateAdded)}</p></article>`).join("") : empty("Brak opublikowanej treści w tej kategorii. Nie uzupełniamy jej niezweryfikowanymi opisami.");
}
async function renderCollection(kind, version) {
  if (kind === "learn") {
    root.innerHTML = empty("Ładowanie Learn…");
    try {
      const value = await getFootball("/api/football/learn");
      if (version !== renderVersion) return;
      root.innerHTML = `<h2>Learn</h2><div class="football-toolbar"><label>Kategoria<select id="football-learn-category"><option value="">Wszystkie</option>${[...new Set(value.items.map(i => i.category))].map(c => `<option>${escapeHtml(c)}</option>`).join("")}</select></label></div>${knowledgeCards(value.items)}`;
    } catch(error) { if (version === renderVersion) root.innerHTML = empty(error.message); }
    return;
  }
  root.innerHTML = `<h2>${kind === "players" ? "Players" : "Search"}</h2><p class="football-note">Wyszukiwanie w lokalnym katalogu. Zawodnicy trafiają tu po otwarciu składu klubu.</p><div class="football-toolbar"><label>Szukaj<input id="football-search-query" placeholder="Klub, zawodnik, rozgrywki…"></label></div><div id="football-search-results">Ładowanie…</div>`;
  await updateSearch("", version, kind === "players");
}
async function updateSearch(query, version, playersOnly) {
  try {
    const value = await getFootball(`/api/football/search?q=${encodeURIComponent(query)}&kind=${playersOnly ? "player" : ""}`);
    if (version !== renderVersion) return;
    const items = value.items.filter(i => !playersOnly || i.kind === "player");
    document.getElementById("football-search-results").innerHTML = items.length ? table(["Typ","Nazwa"],items.map(i => `<tr>${cell(i.kind)}<td>${entityLink(i.kind,i.key,i.name)}</td></tr>`)) : empty("Brak dopasowań. Otwórz klub i jego Squad, aby pobrać zawodników.");
  } catch(error) { if (version === renderVersion) document.getElementById("football-search-results").innerHTML = empty(error.message); }
}
root.addEventListener("click", event => { if (event.target.id === "football-retry") render(); });
