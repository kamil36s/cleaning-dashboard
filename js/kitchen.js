import GIOS from "./api/gios.js";
import { tempColor } from "./temp-scale.js";
import { renderRecipeText } from "./kitchen-recipe.js";
import { selectKitchenFootballSlides } from "./kitchen-football-presentation.js";
import { initKitchenToday } from "./kitchen-today.js";
import { namedayLabel } from "./kitchen-namedays.js";

const AQI_LABELS = {
  very_good: "Bardzo dobry",
  good: "Dobry",
  moderate: "Umiarkowany",
  sufficient: "Dostateczny",
  bad: "Zły",
  very_bad: "Bardzo zły",
};

const AQI_BY_PL_LABEL = {
  "Bardzo dobry": "very_good",
  Dobry: "good",
  Umiarkowany: "moderate",
  Dostateczny: "sufficient",
  Zly: "bad",
  "Zły": "bad",
  "Bardzo zly": "very_bad",
  "Bardzo zły": "very_bad",
};

const WX_DESC = {
  0: "Bezchmurnie",
  1: "Głównie słonecznie",
  2: "Częściowe zachmurzenie",
  3: "Pochmurno",
  45: "Mgła",
  48: "Szron/mgła",
  51: "Mżawka lekka",
  53: "Mżawka",
  55: "Mżawka intensywna",
  61: "Deszcz lekki",
  63: "Deszcz",
  65: "Ulewa",
  66: "Marznący deszcz",
  67: "Ulewa marznąca",
  71: "Śnieg lekki",
  73: "Śnieg",
  75: "Śnieg intensywny",
  77: "Ziarna lodowe",
  80: "Przelotny deszcz lekki",
  81: "Przelotny deszcz",
  82: "Ulewy przelotne",
  85: "Przelotny śnieg lekki",
  86: "Przelotny śnieg",
  95: "Burza",
  96: "Burza z gradem",
  99: "Silna burza z gradem",
};

const CLOZEMASTER_DEFAULT_URL = "https://www.clozemaster.com/l/ita-eng/collections/travel-essentials/play?skill=vocabulary&mode=multiple_choice&count=50";
const CLOZEMASTER_STORAGE_KEY = "kitchen.clozemasterUrl";
const CLOZEMASTER_HOLD_MS = 1200;
const KITCHEN_PARAMS = new URLSearchParams(window.location.search);
const DEBUG_SLIDES = KITCHEN_PARAMS.get("debugSlides") === "1";
const DEBUG_START_SLIDE = Math.max(0, Number(KITCHEN_PARAMS.get("slide") || 0) - 1);
const RESULTS_MATCHES_PER_SLIDE = 2;
const NEXT_MATCHES_PER_SLIDE = 3;
const KITCHEN_REFRESH_POLL_MS = 5000;
const KITCHEN_REFRESH_STORAGE_KEY = "kitchen.reload-signal.v1";
const SLIDE_NAV_HIDE_MS = 5000;
const SLIDE_SWIPE_MIN_PX = 56;

let kitchenRefreshInitialized = false;
let kitchenRefreshTimer = 0;
let kitchenRefreshSeenFallback = "";
let kitchenRecipeFitFrame = 0;

const WORLD_CUP_FLAG_CRESTS = {
  "australia": "https://a.espncdn.com/i/teamlogos/countries/500/aus.png",
  "bosnia-herzegovina": "https://a.espncdn.com/i/teamlogos/countries/500/bih.png",
  "brazil": "https://a.espncdn.com/i/teamlogos/countries/500/bra.png",
  "canada": "https://a.espncdn.com/i/teamlogos/countries/500/can.png",
  "czechia": "https://a.espncdn.com/i/teamlogos/countries/500/cze.png",
  "haiti": "https://a.espncdn.com/i/teamlogos/countries/500/hai.png",
  "mexico": "https://a.espncdn.com/i/teamlogos/countries/500/mex.png",
  "morocco": "https://a.espncdn.com/i/teamlogos/countries/500/mar.png",
  "paraguay": "https://a.espncdn.com/i/teamlogos/countries/500/par.png",
  "qatar": "https://a.espncdn.com/i/teamlogos/countries/500/qat.png",
  "scotland": "https://a.espncdn.com/i/teamlogos/countries/500/sco.png",
  "south africa": "https://a.espncdn.com/i/teamlogos/countries/500/rsa.png",
  "south korea": "https://a.espncdn.com/i/teamlogos/countries/500/kors.png",
  "switzerland": "https://a.espncdn.com/i/teamlogos/countries/500/sui.png",
  "turkiye": "https://a.espncdn.com/i/teamlogos/countries/500/tur.png",
  "united states": "https://a.espncdn.com/i/teamlogos/countries/500/usa.png",
};

const TEAM_NAME_ALIASES = {
  "bosnia herzegovina": "bosnia-herzegovina",
  "bosnia and herzegovina": "bosnia-herzegovina",
  "czech republic": "czechia",
  "usa": "united states",
  "u s a": "united states",
  "united states of america": "united states",
};

const ICONS = {
  clear: `<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"></circle><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"></path></svg>`,
  partly: `<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><path d="M6 13a4.5 4.5 0 0 1 8.7-1.5"></path><circle cx="9" cy="8" r="3"></circle><path d="M7 18h9a4 4 0 0 0 0-8 5 5 0 0 0-9.5-1A4 4 0 0 0 7 18z"></path></svg>`,
  cloudy: `<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><path d="M7 18h9a4 4 0 0 0 0-8 5 5 0 0 0-9.5-1A4 4 0 0 0 7 18z"></path></svg>`,
  fog: `<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><path d="M7 14h9a3.5 3.5 0 0 0 0-7 4.5 4.5 0 0 0-8.5-1.1A3.5 3.5 0 0 0 7 14z"></path><path d="M4 17h16M6 20h12"></path></svg>`,
  rain: `<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><path d="M7 13h9a4 4 0 0 0 0-8 5 5 0 0 0-9.5-1A4 4 0 0 0 7 13z"></path><path d="M8 17l-1 2M12 17l-1 2M16 17l-1 2"></path></svg>`,
  snow: `<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><path d="M7 13h9a4 4 0 0 0 0-8 5 5 0 0 0-9.5-1A4 4 0 0 0 7 13z"></path><path d="M8 16v4M7 18h2M12 16v4M11 18h2M16 16v4M15 18h2"></path></svg>`,
  storm: `<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><path d="M7 13h9a4 4 0 0 0 0-8 5 5 0 0 0-9.5-1A4 4 0 0 0 7 13z"></path><path d="M11 14l-2 4h3l-2 4 5-6h-3l2-4z"></path></svg>`,
};

const fmtTime = new Intl.DateTimeFormat("pl-PL", {
  hour: "2-digit",
  minute: "2-digit",
});
const fmtDate = new Intl.DateTimeFormat("pl-PL", {
  weekday: "long",
  day: "numeric",
  month: "long",
});
const fmtMatchTime = new Intl.DateTimeFormat("pl-PL", {
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "Europe/Warsaw",
});
const fmtWorldCupDate = new Intl.DateTimeFormat("pl-PL", {
  day: "numeric",
  month: "long",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "Europe/Warsaw",
});

const $ = (id) => document.getElementById(id);
const setText = (id, value) => {
  const el = $(id);
  if (el) el.textContent = value;
};

const formatTemp = (value) => {
  const number = Number(value);
  return Number.isFinite(number) ? `${Math.round(number)}°C` : "--°C";
};

function proxiedImageSrc(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";
  if (raw.startsWith("/")) return raw;
  return `/api/kitchen/image?u=${encodeURIComponent(raw)}`;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[char]);
}

function displayName(value) {
  return String(value ?? "")
    .replace(/\bWisla\b/g, "Wisła")
    .replace(/\bKrakow\b/g, "Kraków");
}

function escapeName(value) {
  return escapeHtml(displayName(value));
}

function displayLeagueName(value) {
  return displayName(value || "").replace(/\bpremier league\b/gi, "Premier League");
}

function escapeLeagueName(value) {
  return escapeHtml(displayLeagueName(value));
}

function iconForWeather(code) {
  const value = Number(code);
  if (value === 0) return ICONS.clear;
  if (value === 1 || value === 2) return ICONS.partly;
  if (value === 3) return ICONS.cloudy;
  if (value === 45 || value === 48) return ICONS.fog;
  if ((value >= 51 && value <= 67) || (value >= 80 && value <= 82)) return ICONS.rain;
  if ((value >= 71 && value <= 77) || (value >= 85 && value <= 86)) return ICONS.snow;
  if (value === 95 || value === 96 || value === 99) return ICONS.storm;
  return ICONS.cloudy;
}

function updateClock() {
  const now = new Date();
  setText("kitchen-time", fmtTime.format(now));
  setText("kitchen-recipe-clock", fmtTime.format(now));
  setText("kitchen-date", fmtDate.format(now));
  setText("kitchen-daily", namedayLabel(now));
  applyNightMode(now);
}

function applyKitchenRecipeMode(settings) {
  const screen = $("kitchen-screen");
  const recipeView = $("kitchen-recipe");
  const recipeContent = $("kitchen-recipe-content");
  if (!screen || !recipeView || !recipeContent) return;

  const recipe = settings?.recipe || {};
  const content = String(recipe.content || "").trim();
  const isActive = recipe.enabled === true && Boolean(content);
  screen.classList.toggle("is-recipe-mode", isActive);
  document.body.classList.toggle("recipe-mode", isActive);
  recipeView.hidden = !isActive;
  document.querySelector(".kitchen-top")?.setAttribute("aria-hidden", String(isActive));
  document.querySelector(".score-stage")?.setAttribute("aria-hidden", String(isActive));
  recipeContent.innerHTML = isActive ? renderRecipeText(content) : "";
  if (isActive) {
    organizeKitchenRecipeLayout(recipeContent);
    scheduleKitchenRecipeFit();
  }
}

function organizeKitchenRecipeLayout(content) {
  const children = Array.from(content.children);
  const headings = children.filter((node) => node.matches?.("h2"));
  const ingredientsHeading = headings.find((node) => node.textContent.trim().toLocaleLowerCase("pl-PL") === "składniki");
  const preparationHeading = headings.find((node) => ["przygotowanie", "wykonanie", "sposób przygotowania"]
    .includes(node.textContent.trim().toLocaleLowerCase("pl-PL")));
  const ingredientsIndex = children.indexOf(ingredientsHeading);
  const preparationIndex = children.indexOf(preparationHeading);
  if (ingredientsIndex < 0 || preparationIndex <= ingredientsIndex) return;

  const intro = children.slice(0, ingredientsIndex);
  const ingredients = document.createElement("section");
  ingredients.className = "recipe-column recipe-column--ingredients";
  ingredients.append(...children.slice(ingredientsIndex, preparationIndex));

  const preparation = document.createElement("section");
  preparation.className = "recipe-column recipe-column--preparation";
  preparation.append(...children.slice(preparationIndex));

  const layout = document.createElement("div");
  layout.className = "recipe-layout";
  layout.append(ingredients, preparation);
  content.replaceChildren(...intro, layout);
}

function fitKitchenRecipeToScreen() {
  const recipeView = $("kitchen-recipe");
  const recipeContent = $("kitchen-recipe-content");
  const shell = recipeContent?.closest(".kitchen-recipe-shell");
  if (!recipeView || !recipeContent || !shell || recipeView.hidden) return;

  recipeContent.style.setProperty("--recipe-scale", "1");
  recipeContent.style.width = "100%";

  const viewRect = recipeView.getBoundingClientRect();
  const contentRect = recipeContent.getBoundingClientRect();
  const shellStyle = window.getComputedStyle(shell);
  const bottomPadding = Number.parseFloat(shellStyle.paddingBottom) || 0;
  const availableHeight = Math.max(1, viewRect.bottom - contentRect.top - bottomPadding);

  const applyScale = (scale) => {
    recipeContent.style.setProperty("--recipe-scale", String(scale));
    recipeContent.style.width = `${100 / scale}%`;
  };

  let low = 0.24;
  let high = 1.45;
  for (let step = 0; step < 12; step += 1) {
    const scale = (low + high) / 2;
    applyScale(scale);
    if (recipeContent.scrollHeight * scale <= availableHeight) {
      low = scale;
    } else {
      high = scale;
    }
  }
  applyScale(low);
}

function scheduleKitchenRecipeFit() {
  window.cancelAnimationFrame(kitchenRecipeFitFrame);
  kitchenRecipeFitFrame = window.requestAnimationFrame(() => {
    kitchenRecipeFitFrame = window.requestAnimationFrame(fitKitchenRecipeToScreen);
  });
}

async function setupKitchenRecipeMode() {
  try {
    const settings = await fetchJsonNoStore("/api/kitchen/settings");
    applyKitchenRecipeMode(settings);
  } catch (error) {
    applyKitchenRecipeMode(null);
  }
}

function applyNightMode(now) {
  const forced = KITCHEN_PARAMS.get("night");
  const isNight = forced === "1" || (forced !== "0" && now.getHours() >= 0 && now.getHours() < 6);
  document.body.classList.toggle("night-mode", isNight);
  document.documentElement.classList.toggle("night-mode", isNight);
}

async function updateWeather() {
  try {
    const response = await fetch("/api/kitchen/weather", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    const now = data.weather || {};
    const accent = tempColor(Number(now.temp));
    if (accent) document.documentElement.style.setProperty("--weather-accent", accent);
    setText("kitchen-temp", formatTemp(now.temp));
    setText(
      "kitchen-condition",
      data.weatherError ? "Nie udało się pobrać pogody" : (WX_DESC[Number(now.code)] || "Brak opisu"),
    );
    const icon = $("kitchen-weather-icon");
    if (icon) icon.innerHTML = iconForWeather(now.code);
    renderAqi(await resolveKitchenAqi(data.aqi));
    renderMoon(data.daily?.moon);
  } catch (error) {
    setText("kitchen-condition", "Nie udało się pobrać pogody");
    renderAqi(await fetchBrowserAqiFallback());
  }
}

async function resolveKitchenAqi(serverAqi) {
  if (serverAqi && (normalizeAqiKey(serverAqi.category) || Number.isFinite(Number(serverAqi.value)))) {
    return serverAqi;
  }
  return await fetchBrowserAqiFallback();
}

async function fetchBrowserAqiFallback() {
  try {
    const index = await GIOS.getIndex(400);
    return {
      category: index.category,
      value: index.value,
      computedAt: index.computedAt,
    };
  } catch (error) {
    console.warn("[Kitchen AQI] Browser fallback failed:", error);
    return null;
  }
}

function normalizeAqiKey(label) {
  const raw = String(label || "").trim();
  if (AQI_LABELS[raw]) return raw;
  return AQI_BY_PL_LABEL[raw] || null;
}

function applyAqiClass(key) {
  const el = $("kitchen-aqi");
  if (!el) return;
  for (const name of Object.keys(AQI_LABELS)) {
    el.classList.remove(`aqi-${name}`);
  }
  if (key) el.classList.add(`aqi-${key}`);
}

function renderAqi(index) {
  const key = normalizeAqiKey(index?.category);
  if (key) {
    applyAqiClass(key);
    setText("kitchen-aqi-label", AQI_LABELS[key]);
  } else {
    applyAqiClass(null);
    setText("kitchen-aqi-label", "Brak danych");
  }
}

function moonSvg(moon) {
  const label = String(moon?.label || "").toLowerCase();
  let content = `<circle cx="50" cy="50" r="42" fill="#10151a" stroke="rgba(255,255,255,0.2)" stroke-width="2"/>`;
  if (label.includes("pełnia")) {
    content += `<circle cx="50" cy="50" r="42" fill="#dfe6ef"/>`;
  } else if (label.includes("pierwsza kwadra")) {
    content += `<path d="M50 8 A42 42 0 0 1 50 92 Z" fill="#dfe6ef"/>`;
  } else if (label.includes("ostatnia kwadra")) {
    content += `<path d="M50 8 A42 42 0 0 0 50 92 Z" fill="#dfe6ef"/>`;
  } else if (label.includes("sierp rosn")) {
    content += `<path d="M63 9 A42 42 0 0 1 63 91 C45 80 45 20 63 9 Z" fill="#dfe6ef"/>`;
  } else if (label.includes("sierp male")) {
    content += `<path d="M37 9 A42 42 0 0 0 37 91 C55 80 55 20 37 9 Z" fill="#dfe6ef"/>`;
  } else if (label.includes("garbaty rosn")) {
    content += `<circle cx="50" cy="50" r="42" fill="#dfe6ef"/><path d="M38 9 A42 42 0 0 0 38 91 C27 76 27 24 38 9 Z" fill="#10151a"/>`;
  } else if (label.includes("garbaty male")) {
    content += `<circle cx="50" cy="50" r="42" fill="#dfe6ef"/><path d="M62 9 A42 42 0 0 1 62 91 C73 76 73 24 62 9 Z" fill="#10151a"/>`;
  }
  return `<svg class="moon-svg" viewBox="0 0 100 100" aria-hidden="true">${content}</svg>`;
}

function renderMoon(moon) {
  const label = moon?.label || "--";
  const illumination = Number(moon?.illumination);
  setText("kitchen-moon-label", Number.isFinite(illumination) ? `${label}, ${illumination}%` : label);
  const thumb = $("kitchen-moon-thumb");
  if (thumb) thumb.innerHTML = moonSvg(moon);
}

let slides = [];
let currentSlide = 0;
let liveFocusIndex = 0;
let scoreTimer = null;
let scoreRefreshTimer = null;
let worldCupCountdownTimer = null;
let slideNavHideTimer = null;
let scoreWindowHours = 24;
let hasLiveScore = false;
let lastTickerSignature = "";

function initials(name) {
  return String(name || "")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0])
    .join("")
    .toUpperCase() || "?";
}

function crestHtml(team) {
  if (team?.crest) {
    return `<img class="team-crest" src="${escapeHtml(proxiedImageSrc(team.crest))}" alt="" loading="eager" decoding="async">`;
  }
  return `<div class="team-placeholder" aria-hidden="true">${escapeHtml(initials(team?.name))}</div>`;
}

function roundLabel(match) {
  if (isWorldCupMatch(match)) return "";
  if (match?.roundType === "cup") return "";
  const raw = String(match?.round || "").trim();
  if (!raw || raw === "0") return "";
  const number = raw.match(/(\d+)(?!.*\d)/)?.[1] || raw;
  if (number === "0") return "";
  return `kolejka ${number}`;
}

function tournamentContextLabels(match) {
  const labels = [];
  if (isWorldCupMatch(match)) {
    labels.push(match?.groupLabel);
    if (match?.stageLabel && match.stageLabel !== match?.groupLabel) labels.push(match.stageLabel);
  } else {
    labels.push(match?.stageLabel);
    if (match?.roundType === "cup" && match?.round && match.round !== match?.stageLabel) labels.push(match.round);
  }
  labels.push(match?.legLabel);
  labels.push(match?.firstLegLabel);
  labels.push(match?.aggregateLabel);
  if (!labels.some(Boolean)) labels.push(roundLabel(match));
  return Array.from(new Set(labels.map((value) => String(value || "").trim()).filter(Boolean)));
}

function tournamentContextLabel(match) {
  return tournamentContextLabels(match)[0] || "";
}

function contextLabelsHtml(match, className) {
  const labels = tournamentContextLabels(match);
  return labels.length
    ? `<div class="${className}">${labels.map((label) => `<span>${escapeHtml(label)}</span>`).join("")}</div>`
    : "";
}

function detailIcon(kind) {
  if (kind === "goal") return "⚽";
  if (kind === "yellow-card" || kind === "red-card") return "";
  return "•";
}

function eventDetailText(item) {
  let text = String(item?.text || item?.label || "").trim();
  if (item?.kind === "goal") {
    text = text
      .replace(/\bGoal\b\s*[-–]?\s*/gi, "")
      .replace(/\s*[-–]\s*(Header|Volley|Left Footed Shot|Right Footed Shot|Shot).*$/i, "");
  }
  if (item?.kind === "yellow-card") text = text.replace(/\bYellow Card\b\s*[-–]?\s*/gi, "");
  if (item?.kind === "red-card") text = text.replace(/\bRed Card\b\s*[-–]?\s*/gi, "");
  text = text.replace(/\s+/g, " ").replace(/^[\s–-]+|[\s–-]+$/g, "");
  return text || item?.team || "";
}

function eventInlineText(item) {
  return playerSurname(eventDetailText(item));
}

function playerSurname(value) {
  const cleaned = String(value || "")
    .replace(/\([^)]*\)/g, " ")
    .replace(/\b(Yellow|Red|Card|Goal|Scored|Penalty|Header|Volley|Shot)\b/gi, " ")
    .replace(/[^\p{L}\p{M}' -]/gu, " ")
    .replace(/\s+/g, " ")
    .trim();
  const parts = cleaned.split(/\s+/).filter(Boolean);
  return parts.at(-1) || cleaned;
}

function eventIconHtml(kind) {
  if (kind === "goal") return "&#9917;";
  return "";
}

function eventMinuteValue(item) {
  const raw = String(item?.minute || "").trim();
  const match = raw.match(/(\d{1,3})(?:\D+(\d{1,2}))?/);
  if (!match) return -1;
  return Number(match[1]) + (Number(match[2]) || 0) / 100;
}

function teamKey(value) {
  return String(value || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

function canonicalTeamKey(value) {
  const key = teamKey(value);
  return TEAM_NAME_ALIASES[key] || key;
}

function isWorldCupMatch(match) {
  const text = [
    match?.leagueKey,
    match?.leagueName,
    match?.competitionName,
    match?.teamName,
  ].map((value) => String(value || "").toLowerCase()).join(" ");
  return text.includes("world-cup") || text.includes("world cup");
}

function normalizeWorldCupTeam(team, match) {
  if (!team || !isWorldCupMatch(match)) return team;
  const crest = WORLD_CUP_FLAG_CRESTS[canonicalTeamKey(team.name)];
  return crest ? { ...team, crest } : team;
}

function normalizeKitchenMatch(match) {
  if (!match || typeof match !== "object") return match;
  return {
    ...match,
    home: normalizeWorldCupTeam(match.home, match),
    away: normalizeWorldCupTeam(match.away, match),
  };
}

function matchTimeKey(match) {
  return String(match?.playedAt || match?.kickoffAt || "").slice(0, 16);
}

function matchIdentityKey(match) {
  const home = canonicalTeamKey(match?.home?.name);
  const away = canonicalTeamKey(match?.away?.name);
  const teams = [home, away].sort().join("|");
  const league = isWorldCupMatch(match)
    ? "world-cup"
    : (match?.leagueKey || match?.competitionName || match?.leagueName || "");
  return [
    league,
    teams,
    matchTimeKey(match),
  ].join("::");
}

function teamCrestScore(team) {
  const crest = String(team?.crest || "");
  if (!crest) return 0;
  if (crest.includes("/teamlogos/countries/")) return 4;
  if (crest.includes("/team/badge/")) return 1;
  return 2;
}

function matchQualityScore(match) {
  return teamCrestScore(match?.home)
    + teamCrestScore(match?.away)
    + (String(match?.home?.name || "").length > 3 ? 1 : 0)
    + (String(match?.away?.name || "").length > 3 ? 1 : 0);
}

function dedupeKitchenMatches(matches) {
  const byKey = new Map();
  for (const raw of Array.isArray(matches) ? matches : []) {
    const match = normalizeKitchenMatch(raw);
    const key = matchIdentityKey(match);
    const existing = byKey.get(key);
    if (!existing || matchQualityScore(match) > matchQualityScore(existing)) {
      byKey.set(key, { ...existing, ...match });
    }
  }
  return Array.from(byKey.values());
}

function chunkItems(items, size) {
  const chunks = [];
  for (let index = 0; index < items.length; index += size) {
    chunks.push(items.slice(index, index + size));
  }
  return chunks;
}

function normalizeKitchenSlides(rawSlides) {
  const normalized = [];
  for (const raw of Array.isArray(rawSlides) ? rawSlides : []) {
    if (!raw || raw.type === "worldCupCountdown") continue;
    if (raw.type === "next") {
      const matches = dedupeKitchenMatches(raw.matches);
      for (const chunk of chunkItems(matches, NEXT_MATCHES_PER_SLIDE)) {
        normalized.push({ ...raw, matches: chunk });
      }
      continue;
    }
    if (Array.isArray(raw.matches)) {
      const matches = dedupeKitchenMatches(raw.matches);
      if (raw.type === "results" && !matches.length) continue;
      if (raw.type === "results") {
        for (const chunk of chunkItems(matches, RESULTS_MATCHES_PER_SLIDE)) {
          normalized.push({ ...raw, matches: chunk });
        }
        continue;
      }
      normalized.push({ ...raw, matches });
      continue;
    }
    normalized.push(normalizeKitchenMatch(raw));
  }
  return normalized;
}

function eventSide(item, match) {
  const team = teamKey(item?.team);
  const home = teamKey(match?.home?.name);
  const away = teamKey(match?.away?.name);
  if (team && home && (team === home || team.includes(home) || home.includes(team))) return "left";
  if (team && away && (team === away || team.includes(away) || away.includes(team))) return "right";
  return "center";
}

function matchDetailsHtml() {
  return "";
}

function tickerText(matches) {
  const items = Array.isArray(matches) ? matches : [];
  if (!items.length) return `Brak zakończonych wyników z ostatnich ${scoreWindowLabel(scoreWindowHours)}`;
  return items.map((match) => {
    const score = match.score || {};
    return `${match.leagueName || "Wyniki"}: ${displayName(match.home?.name || "Gospodarze")} ${score.home ?? "-"}:${score.away ?? "-"} ${displayName(match.away?.name || "Goście")}`;
  }).join("   •   ");
}

function compactScore(match) {
  const score = match?.score || {};
  return `${score.home ?? "-"}:${score.away ?? "-"}`;
}

function tickerItemHtml(match) {
  return `
    <span class="score-ticker-item">
      ${crestHtml(match.home)}
      <span class="score-ticker-name">${escapeName(match.home?.name || "Gospodarze")}</span>
      <strong>${escapeHtml(compactScore(match))}</strong>
      <span class="score-ticker-name">${escapeName(match.away?.name || "GoĹ›cie")}</span>
      ${crestHtml(match.away)}
    </span>
  `;
}

function tickerItemsHtml(matches) {
  const items = Array.isArray(matches) ? matches : [];
  if (!items.length) {
    return `<span class="score-ticker-empty">Brak zakoĹ„czonych wynikĂłw z ostatnich ${escapeHtml(scoreWindowLabel(scoreWindowHours))}</span>`;
  }
  return items.map(tickerItemHtml).join("");
}

function tickerHtml(matches) {
  const items = tickerItemsHtml(matches);
  return `
    <div class="score-ticker" aria-label="ZakoĹ„czone wyniki">
      <div class="score-ticker-track">
        <div class="score-ticker-group">${items}</div>
        <div class="score-ticker-group" aria-hidden="true">${items}</div>
      </div>
    </div>
  `;
}

function tickerTrackHtml(matches) {
  const items = tickerItemsHtml(matches);
  return `
    <div class="score-ticker-track">
      <div class="score-ticker-group">${items}</div>
      <div class="score-ticker-group" aria-hidden="true">${items}</div>
    </div>
  `;
}

function ensureScoreTicker() {
  let ticker = $("kitchen-score-ticker");
  if (ticker) return ticker;
  const stage = document.querySelector(".score-stage");
  if (!(stage instanceof HTMLElement)) return null;
  ticker = document.createElement("div");
  ticker.id = "kitchen-score-ticker";
  ticker.className = "score-ticker";
  ticker.setAttribute("aria-label", "ZakoĹ„czone wyniki");
  stage.appendChild(ticker);
  return ticker;
}

function updateScoreTicker(matches) {
  const items = Array.isArray(matches) ? matches : [];
  const signature = JSON.stringify(items.map((match) => [
    match?.id,
    match?.home?.name,
    match?.away?.name,
    match?.score?.home,
    match?.score?.away,
  ]));
  if (signature === lastTickerSignature) return;
  const ticker = ensureScoreTicker();
  if (!ticker) return;
  ticker.innerHTML = tickerTrackHtml(items);
  lastTickerSignature = signature;
}

function startOfLocalDay(value) {
  const date = new Date(value);
  date.setHours(0, 0, 0, 0);
  return date;
}

function relativeDayLabel(value) {
  if (!(value instanceof Date) || Number.isNaN(value.getTime())) return "zakończony";
  const now = new Date();
  const diffDays = Math.round((startOfLocalDay(now) - startOfLocalDay(value)) / 86400000);
  if (diffDays <= 0) return "dzisiaj";
  if (diffDays === 1) return "wczoraj";
  return "przedwczoraj";
}

function relativeFutureDayLabel(value) {
  if (!(value instanceof Date) || Number.isNaN(value.getTime())) return "wkrótce";
  const now = new Date();
  const diffDays = Math.round((startOfLocalDay(value) - startOfLocalDay(now)) / 86400000);
  if (diffDays <= 0) return "dzisiaj";
  if (diffDays === 1) return "jutro";
  if (diffDays === 2) return "pojutrze";
  return `za ${diffDays} dni`;
}

function setScoreHeader(kicker, title) {
  setText("kitchen-score-kicker", kicker);
  setText("kitchen-score-league", displayLeagueName(title));
  setText("kitchen-score-counter", slides.length ? `${currentSlide + 1}/${slides.length}` : "0/0");
  updateSlideDebugStatus();
}

function stopWorldCupCountdown() {
  if (worldCupCountdownTimer) clearInterval(worldCupCountdownTimer);
  worldCupCountdownTimer = null;
}

function scoreWindowLabel(hours) {
  const value = Number(hours);
  if (value === 24) return "24h";
  if (value % 24 === 0) {
    const days = value / 24;
    return days === 1 ? "1 dzień" : `${days} dni`;
  }
  return `${value}h`;
}

function worldCupCountdownParts(target) {
  const diff = Math.max(0, target.getTime() - Date.now());
  const totalSeconds = Math.floor(diff / 1000);
  const days = Math.floor(totalSeconds / 86400);
  const hours = Math.floor((totalSeconds % 86400) / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  return { days, hours, minutes, seconds };
}

function worldCupCountdownValuesHtml(parts) {
  return [
    ["dni", parts.days],
    ["godz.", parts.hours],
    ["min", parts.minutes],
    ["sek", parts.seconds],
  ].map(([label, value]) => `
    <div class="world-cup-count">
      <strong>${escapeHtml(String(value).padStart(label === "dni" ? 1 : 2, "0"))}</strong>
      <span>${escapeHtml(label)}</span>
    </div>
  `).join("");
}

function updateWorldCupCountdown(target) {
  const values = $("world-cup-countdown-values");
  if (!values) return;
  if (target.getTime() <= Date.now()) {
    values.classList.add("is-started");
    values.setAttribute("aria-label", "Mecz otwarcia już się rozpoczął");
    values.innerHTML = `<div class="world-cup-started">Mecz już trwa</div>`;
    if (worldCupCountdownTimer) {
      clearInterval(worldCupCountdownTimer);
      worldCupCountdownTimer = null;
    }
    return;
  }
  values.classList.remove("is-started");
  values.setAttribute("aria-label", "Odliczanie do meczu otwarcia");
  values.innerHTML = worldCupCountdownValuesHtml(worldCupCountdownParts(target));
}

function renderWorldCupCountdownSlide(slide) {
  const root = $("kitchen-score-match");
  if (!root) return;
  setScoreHeader(slide.title || "Nastepny mundial", slide.leagueName || "FIFA World Cup");
  const kickoff = slide.kickoffAt ? new Date(slide.kickoffAt) : null;
  const kickoffLabel = slide.displayDate || (kickoff && !Number.isNaN(kickoff.getTime())
    ? fmtWorldCupDate.format(kickoff)
    : "data do potwierdzenia");
  const logo = slide.image || slide.lockupImage || "";
  const hasTeams = Boolean(slide.home?.name || slide.away?.name);
  root.innerHTML = `
    <div class="world-cup-slide">
      <div class="world-cup-copy">
        <div class="world-cup-eyebrow">${escapeHtml(slide.eyebrow || slide.leagueName || "FIFA World Cup")}</div>
        <div class="world-cup-title">${escapeHtml(slide.matchupTitle || slide.title || "Nastepny mundial")}</div>
        <div id="world-cup-countdown-values" class="world-cup-countdown" aria-label="Odliczanie do meczu otwarcia"></div>
        <div class="world-cup-opening">
          <div>
            <strong>${escapeHtml(kickoffLabel)}</strong>
            <span>${escapeHtml([slide.venue, slide.city].filter(Boolean).join(", "))}</span>
          </div>
        </div>
      </div>
      <div class="world-cup-art">
        ${logo ? `<img class="world-cup-logo" src="${escapeHtml(proxiedImageSrc(logo))}" alt="" loading="eager" decoding="async">` : ""}
        ${hasTeams ? `<div class="world-cup-teams">
          <div>${crestHtml(slide.home)}<span>${escapeName(slide.home?.name || "Meksyk")}</span></div>
          <strong>vs</strong>
          <div>${crestHtml(slide.away)}<span>${escapeName(slide.away?.name || "RPA")}</span></div>
        </div>` : ""}
      </div>
    </div>
  `;
  if (kickoff && !Number.isNaN(kickoff.getTime())) {
    updateWorldCupCountdown(kickoff);
    worldCupCountdownTimer = setInterval(() => updateWorldCupCountdown(kickoff), 1000);
  }
}

function renderMatchSlide(match) {
  const root = $("kitchen-score-match");
  if (!root) return;
  setScoreHeader(`Ostatnie ${scoreWindowLabel(scoreWindowHours)}`, match.leagueName || "Wyniki");

  const playedAt = match.playedAt ? new Date(match.playedAt) : null;
  const playedLabel = playedAt && !Number.isNaN(playedAt.getTime())
    ? `${relativeDayLabel(playedAt)}, ${fmtMatchTime.format(playedAt)}`
    : "zakończony";
  const contextHtml = contextLabelsHtml(match, "match-context-list");

  root.innerHTML = `
    <div class="score-grid">
      <div class="team-column">
        <div class="team-crest-wrap">${crestHtml(match.home)}</div>
        <div class="team-name">${escapeName(match.home?.name || "Gospodarze")}</div>
      </div>
      <div class="score-center">
        <div>
          <div class="scoreline">
            <span>${escapeHtml(match.score?.home ?? "-")}</span>
            <span class="score-dash">:</span>
            <span>${escapeHtml(match.score?.away ?? "-")}</span>
          </div>
          <div class="match-meta">
            <div class="match-time">${escapeHtml(playedLabel)}</div>
            ${contextHtml}
          </div>
          ${matchDetailsHtml(match.details, match)}
          ${match.fact ? `<div class="match-fact">${escapeHtml(match.fact)}</div>` : ""}
        </div>
      </div>
      <div class="team-column">
        <div class="team-crest-wrap">${crestHtml(match.away)}</div>
        <div class="team-name">${escapeName(match.away?.name || "Goście")}</div>
      </div>
    </div>
  `;
}

function matchCardHtml(match) {
  const playedAt = match.playedAt ? new Date(match.playedAt) : null;
  const playedLabel = playedAt && !Number.isNaN(playedAt.getTime())
    ? `${relativeDayLabel(playedAt)}, ${fmtMatchTime.format(playedAt)}`
    : "FT";
  const contextLabels = tournamentContextLabels(match);
  return `
    <div class="result-card">
      <div class="result-meta">
        <span>${escapeHtml(playedLabel)}</span>
        ${contextLabels.map((label) => `<span>${escapeHtml(label)}</span>`).join("")}
      </div>
      <div class="result-matchup">
        <div class="result-team">
          ${crestHtml(match.home)}
          <span>${escapeName(match.home?.name || "Gospodarze")}</span>
        </div>
        <strong class="result-score">${escapeHtml(match.score?.home ?? "-")}:${escapeHtml(match.score?.away ?? "-")}</strong>
        <div class="result-team is-away">
          <span>${escapeName(match.away?.name || "Goscie")}</span>
          ${crestHtml(match.away)}
        </div>
      </div>
      ${matchDetailsHtml(match.details, match)}
      ${match.fact ? `<div class="match-fact">${escapeHtml(match.fact)}</div>` : ""}
    </div>
  `;
}

function renderResultsSlide(slide) {
  const root = $("kitchen-score-match");
  if (!root) return;
  const matches = Array.isArray(slide.matches) ? slide.matches : [];
  setScoreHeader(`Ostatnie ${scoreWindowLabel(scoreWindowHours)}`, slide.leagueName || "Wyniki");
  if (!matches.length) {
    root.innerHTML = `<div class="score-empty">Brak wynikow z ostatnich ${escapeHtml(scoreWindowLabel(scoreWindowHours))}</div>`;
    return;
  }
  const countClass = `is-count-${Math.min(matches.length, 6)}`;
  root.innerHTML = `
    <div class="results-slide ${countClass}">
      <div class="results-list">
        ${matches.map(matchCardHtml).join("")}
      </div>
    </div>
  `;
}

function standingCrestHtml(row) {
  if (row?.crest) {
    return `<img class="standing-crest" src="${escapeHtml(proxiedImageSrc(row.crest))}" alt="" loading="eager" decoding="async">`;
  }
  return `<div class="standing-placeholder">${escapeHtml(initials(row?.name))}</div>`;
}

function standingValue(value) {
  return value === 0 || value ? escapeHtml(value) : "-";
}

function standingRecord(row) {
  if (row.record) return row.record;
  const parts = [row.wins, row.draws, row.losses].map((value) => (
    value === 0 || value ? String(value) : ""
  ));
  return parts.some(Boolean) ? parts.join("-") : "-";
}

function movementHtml(row) {
  if (row.movement === "up") return `&#9650;${row.rankDelta ? `<span>${escapeHtml(row.rankDelta)}</span>` : ""}`;
  if (row.movement === "down") return `&#9660;${row.rankDelta ? `<span>${escapeHtml(row.rankDelta)}</span>` : ""}`;
  return `&bull;`;
}

function standingsLegendHtml(legend) {
  const items = Array.isArray(legend) ? legend : [];
  if (!items.length) return "";
  return `
    <div class="standings-legend">
      ${items.map((item) => `
        <span class="standings-legend-item is-${escapeHtml(item.kind || "zone")}">
          <span>${escapeHtml(item.places || "")}</span>
          <strong>${escapeHtml(item.abbrev || item.label || "")}</strong>
        </span>
      `).join("")}
    </div>
  `;
}

function normalizeLiveToken(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";
  const upper = raw.toUpperCase();
  if (upper === "LIVE") return "";
  if (upper === "1H" || upper === "2H") return "";
  if (upper === "HT" || upper === "FT") return upper;
  const addedLoose = raw.match(/^(\d{1,3}).*?\+.*?(\d{1,2})/);
  if (addedLoose) return `${addedLoose[1]}+${addedLoose[2]}'`;
  const added = raw.match(/^(\d{1,3})(?::\d{2})?\s*[+']/);
  if (added) {
    const extra = raw.slice(added[0].length).match(/\d{1,2}/)?.[0];
    if (extra) return `${added[1]}+${extra}'`;
  }
  const minute = raw.match(/^(\d{1,3})(?::\d{2})?['â€™]?$/);
  if (minute) return `${minute[1]}'`;
  return raw.replace(/\s+/g, " ");
}

function liveStatusText(match) {
  const clock = normalizeLiveToken(match?.clock);
  if (clock) return clock;
  return normalizeLiveToken(match?.statusText || match?.status) || "Live";
}

function isActiveLiveMatch(match) {
  const haystack = [match?.status, match?.statusText, match?.clock]
    .map((value) => String(value || "").toLowerCase())
    .join(" ");
  if (/\b(ft|full time|finished|final|match finished|ended|aet|after extra time|aot|after overtime|ap|after penalties|pen|pens|penalties)\b/.test(haystack)) return false;
  if (normalizeLiveToken(match?.clock)) return true;
  if (normalizeLiveToken(match?.statusText || match?.status)) return true;
  return false;
}

function renderLiveSlideOld(slide) {
  const root = $("kitchen-score-match");
  if (!root) return;
  const liveMatches = Array.isArray(slide.matches) ? slide.matches : [];
  if (liveMatches.length) liveFocusIndex = liveFocusIndex % liveMatches.length;
  const main = liveMatches[liveFocusIndex] || liveMatches[0];
  if (!main) {
    root.innerHTML = `<div class="score-empty">Brak meczu live</div>`;
    return;
  }
  setScoreHeader("LIVE", main.leagueName || "Mecz na żywo");
  const status = [main.clock, main.statusText || main.status].filter(Boolean).join(" · ") || "Live";
  root.innerHTML = `
    <div class="live-board">
      <div class="live-now">
        <div class="live-pill"><span></span>LIVE</div>
        <div class="live-status">${escapeHtml(status)}</div>
      </div>
      <div class="live-match">
        <div class="live-team">
          <div class="team-crest-wrap">${crestHtml(main.home)}</div>
          <div class="team-name">${escapeName(main.home?.name || "Gospodarze")}</div>
        </div>
        <div class="live-score">
          <div class="scoreline">
            <span>${escapeHtml(main.score?.home ?? "-")}</span>
            <span class="score-dash">:</span>
            <span>${escapeHtml(main.score?.away ?? "-")}</span>
          </div>
          <div class="match-round">${escapeHtml(main.competitionName || main.leagueName || "")}</div>
          ${matchDetailsHtml(main.details, main)}
        </div>
        <div class="live-team">
          <div class="team-crest-wrap">${crestHtml(main.away)}</div>
          <div class="team-name">${escapeName(main.away?.name || "Goście")}</div>
        </div>
      </div>
      ${liveMatches.length > 1 ? `
        <div class="live-other">
          ${liveMatches.slice(1, 4).map((match) => `
            <div>${escapeName(match.home?.name || "")} <strong>${escapeHtml(match.score?.home ?? "-")}:${escapeHtml(match.score?.away ?? "-")}</strong> ${escapeName(match.away?.name || "")}</div>
          `).join("")}
        </div>
      ` : ""}
      <div class="score-ticker" aria-label="Zakończone wyniki">
        <div class="score-ticker-track">
          <span>${escapeHtml(tickerText(slide.tickerMatches))}</span>
          <span>${escapeHtml(tickerText(slide.tickerMatches))}</span>
        </div>
      </div>
    </div>
  `;
}

function renderLiveSlideCurrent(slide) {
  const root = $("kitchen-score-match");
  if (!root) return;
  const liveMatches = Array.isArray(slide.matches) ? slide.matches : [];
  if (liveMatches.length) liveFocusIndex = liveFocusIndex % liveMatches.length;
  const main = liveMatches[liveFocusIndex] || liveMatches[0];
  if (!main) {
    root.innerHTML = `<div class="score-empty">Brak meczu live</div>`;
    return;
  }
  setScoreHeader("LIVE", main.leagueName || "Mecz live");
  root.innerHTML = `
    <div class="live-board">
      <div class="live-now">
        <div class="live-pill"><span></span>LIVE</div>
        <div class="live-status">${escapeHtml(liveStatusText(main))}</div>
      </div>
      <div class="live-match">
        <div class="live-team">
          <div class="team-crest-wrap">${crestHtml(main.home)}</div>
          <div class="team-name">${escapeName(main.home?.name || "Gospodarze")}</div>
        </div>
        <div class="live-score">
          <div class="scoreline">
            <span>${escapeHtml(main.score?.home ?? "-")}</span>
            <span class="score-dash">:</span>
            <span>${escapeHtml(main.score?.away ?? "-")}</span>
          </div>
          <div class="match-round">${escapeLeagueName(main.competitionName || main.leagueName || "")}</div>
          ${matchDetailsHtml(main.details, main)}
        </div>
        <div class="live-team">
          <div class="team-crest-wrap">${crestHtml(main.away)}</div>
          <div class="team-name">${escapeName(main.away?.name || "Goscie")}</div>
        </div>
      </div>
    </div>
  `;
}

function renderStandingsSlide(slide) {
  const root = $("kitchen-score-match");
  if (!root) return;
  setScoreHeader(slide.title || "Tabela", slide.leagueName || "Tabela");
  const rows = Array.isArray(slide.rows) ? slide.rows : [];
  root.innerHTML = `
    <div class="standings-slide">
      <div class="standings-head">
        <span>#</span>
        <span>Klub</span>
        <span>Ruch</span>
        <span>Bilans</span>
        <span>PKT</span>
      </div>
      <div class="standings-list">
        ${rows.map((row) => `
          <div class="standing-row ${row.movement ? `is-${escapeHtml(row.movement)}` : ""}">
            <div class="standing-rank">${escapeHtml(row.rank ?? "-")}</div>
            <div class="standing-team">
              ${standingCrestHtml(row)}
              <span>
                <strong>${escapeName(row.name || "Team")}</strong>
                ${row.movementMatch ? `<small>${escapeName(row.movementMatch)}</small>` : ""}
              </span>
            </div>
            <div class="standing-move">
              ${row.movement === "up" ? "▲" : row.movement === "down" ? "▼" : "•"}
              ${row.rankDelta ? escapeHtml(row.rankDelta) : ""}
            </div>
            <div>${escapeHtml(row.record || [row.wins, row.draws, row.losses].filter(Boolean).join("-") || "-")}</div>
            <strong>${escapeHtml(row.points || "-")}</strong>
          </div>
        `).join("")}
      </div>
    </div>
  `;
}

function renderStandingsSlideFull(slide) {
  const root = $("kitchen-score-match");
  if (!root) return;
  setScoreHeader(slide.title || "Tabela", slide.leagueName || "Tabela");
  const rows = Array.isArray(slide.rows) ? slide.rows : [];
  const legend = Array.isArray(slide.legend) ? slide.legend : [];
  const countClass = `is-count-${Math.min(rows.length, 12)}`;
  const groupClass = slide.part === "world-cup-group" ? "is-world-cup-group" : "";
  root.innerHTML = `
    <div class="standings-slide ${countClass} ${groupClass}">
      <div class="standings-head">
        <span>#</span>
        <span>Klub</span>
        <span>Ruch</span>
        <span>MP</span>
        <span>W-D-L</span>
        <span>GF</span>
        <span>GA</span>
        <span>GD</span>
        <span>Pts</span>
      </div>
      <div class="standings-list">
        ${rows.map((row) => `
          <div class="standing-row ${row.movement ? `is-${escapeHtml(row.movement)}` : ""} ${row.zoneKind ? `zone-${escapeHtml(row.zoneKind)}` : ""}">
            <div class="standing-rank">
              <span class="standing-zone-mark" title="${escapeHtml(row.zoneLabel || "")}"></span>
              ${escapeHtml(row.rank ?? "-")}
            </div>
            <div class="standing-team">
              ${standingCrestHtml(row)}
              <span>
                <strong>${escapeName(row.name || "Team")}</strong>
                ${row.movementMatch ? `<small>${escapeName(row.movementMatch)}</small>` : ""}
              </span>
            </div>
            <div class="standing-move">${movementHtml(row)}</div>
            <div>${standingValue(row.played)}</div>
            <div>${escapeHtml(standingRecord(row))}</div>
            <div>${standingValue(row.goalsFor)}</div>
            <div>${standingValue(row.goalsAgainst)}</div>
            <div>${standingValue(row.gd)}</div>
            <strong>${standingValue(row.points)}</strong>
          </div>
        `).join("")}
      </div>
      ${standingsLegendHtml(legend)}
    </div>
  `;
}

function leaderCrestHtml(item) {
  if (item?.teamCrest) {
    return `<img class="leader-crest" src="${escapeHtml(proxiedImageSrc(item.teamCrest))}" alt="" loading="eager" decoding="async">`;
  }
  return `<div class="leader-placeholder">${escapeHtml(initials(item?.teamName || item?.name))}</div>`;
}

function leaderRowsHtml(items, valueLabel) {
  const leaders = Array.isArray(items) ? items.slice(0, 5) : [];
  if (!leaders.length) return `<div class="leaderboard-empty">Brak danych</div>`;
  return leaders.map((item, index) => `
    <div class="leader-row">
      <div class="leader-rank">${escapeHtml(item.rank ?? index + 1)}</div>
      ${leaderCrestHtml(item)}
      <div class="leader-player">
        <strong>${escapeName(item.name || item.fullName || "Player")}</strong>
        <span>${escapeName(item.teamName || "")}</span>
      </div>
      <div class="leader-value">
        <strong>${escapeHtml(item.value ?? "-")}</strong>
        <span>${escapeHtml(valueLabel)}</span>
      </div>
    </div>
  `).join("");
}

function renderLeaderboardsSlide(slide) {
  const root = $("kitchen-score-match");
  if (!root) return;
  setScoreHeader(slide.title || "Liderzy turnieju", slide.leagueName || "FIFA World Cup");
  root.innerHTML = `
    <div class="leaderboards-slide">
      <section class="leaderboard-panel">
        <div class="leaderboard-title">Król strzelców</div>
        <div class="leaderboard-list">${leaderRowsHtml(slide.goals, "gole")}</div>
      </section>
      <section class="leaderboard-panel">
        <div class="leaderboard-title">Król asyst</div>
        <div class="leaderboard-list">${leaderRowsHtml(slide.assists, "asysty")}</div>
      </section>
    </div>
  `;
}

function renderNextSlide(slide) {
  const root = $("kitchen-score-match");
  if (!root) return;
  setScoreHeader(slide.title || "Najbliższe 14 dni", slide.leagueName || "Następne mecze");
  const items = Array.isArray(slide.matches) ? slide.matches : [];
  if (!items.length) {
    root.innerHTML = `<div class="score-empty">Brak meczów w najbliższych 14 dniach</div>`;
    return;
  }
  root.innerHTML = `
    <div class="next-slide">
      ${items.map((match) => {
        const kickoff = match.kickoffAt ? new Date(match.kickoffAt) : null;
        const when = kickoff && !Number.isNaN(kickoff.getTime())
          ? `${relativeFutureDayLabel(kickoff)}, ${fmtMatchTime.format(kickoff)}`
          : "wkrótce";
        const contextHtml = contextLabelsHtml(match, "next-context");
        return `
          <div class="next-card">
            <div class="next-card-head">
              <div class="next-team-label">${escapeHtml(match.teamName || "Mecz")}</div>
              <div class="next-meta">${escapeHtml(when)}</div>
            </div>
            <div class="next-matchup">
              <div class="next-row">${crestHtml(match.home)}<span>${escapeName(match.home?.name || "Gospodarze")}</span></div>
              <div class="next-vs">vs</div>
              <div class="next-row">${crestHtml(match.away)}<span>${escapeName(match.away?.name || "Goście")}</span></div>
            </div>
            <div class="next-competition">${escapeLeagueName(match.competitionName || "")}</div>
            ${contextHtml}
          </div>
        `;
      }).join("")}
    </div>
  `;
}

function renderSlide() {
  const root = $("kitchen-score-match");
  if (!root) return;
  stopWorldCupCountdown();
  updateSlideNavigationState();

  if (!slides.length) {
    setScoreHeader(`Ostatnie ${scoreWindowLabel(scoreWindowHours)}`, "Wyniki");
    root.innerHTML = `<div class="score-empty">Brak wyników z ostatnich ${scoreWindowLabel(scoreWindowHours)}</div>`;
    return;
  }

  currentSlide = currentSlide % slides.length;
  const slide = slides[currentSlide];
  if (slide.type === "live") {
    renderLiveSlideCurrent(slide);
  } else if (slide.type === "worldCupCountdown") {
    renderWorldCupCountdownSlide(slide);
  } else if (slide.type === "results") {
    renderResultsSlide(slide);
  } else if (slide.type === "standings") {
    renderStandingsSlideFull(slide);
  } else if (slide.type === "leaderboards") {
    renderLeaderboardsSlide(slide);
  } else if (slide.type === "next") {
    renderNextSlide(slide);
  } else {
    renderMatchSlide(slide);
  }
}

function updateSlideNavigationState() {
  const controls = $("kitchen-slide-controls");
  if (!controls) return;
  const hasMultipleSlides = slides.length > 1;
  controls.hidden = !hasMultipleSlides;
  controls.querySelectorAll("button[data-slide-nav]").forEach((button) => {
    button.disabled = !hasMultipleSlides;
  });
}

function setSlideControlsVisible(visible, autoHide = false) {
  const controls = $("kitchen-slide-controls");
  if (!controls || controls.hidden) return;
  window.clearTimeout(slideNavHideTimer);
  controls.classList.toggle("is-visible", visible);
  if (visible && autoHide) {
    slideNavHideTimer = window.setTimeout(() => {
      controls.classList.remove("is-visible");
    }, SLIDE_NAV_HIDE_MS);
  }
}

function moveKitchenSlide(delta) {
  if (slides.length <= 1) return;
  currentSlide = (currentSlide + slides.length + delta) % slides.length;
  liveFocusIndex = 0;
  renderSlide();
  startScoreRotation();
}

function setupSlideNavigation() {
  const stage = document.querySelector(".score-stage");
  const controls = $("kitchen-slide-controls");
  if (!stage || !controls) return;

  controls.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-slide-nav]");
    if (!button) return;
    event.preventDefault();
    event.stopPropagation();
    moveKitchenSlide(button.dataset.slideNav === "prev" ? -1 : 1);
    setSlideControlsVisible(true, true);
  });

  let swipeStart = null;
  stage.addEventListener("pointerdown", (event) => {
    if (!event.isPrimary || event.target.closest("button")) return;
    swipeStart = {
      id: event.pointerId,
      x: event.clientX,
      y: event.clientY,
    };
    setSlideControlsVisible(true, true);
  });

  stage.addEventListener("pointerup", (event) => {
    if (!swipeStart || swipeStart.id !== event.pointerId) return;
    const dx = event.clientX - swipeStart.x;
    const dy = event.clientY - swipeStart.y;
    swipeStart = null;
    if (Math.abs(dx) < SLIDE_SWIPE_MIN_PX || Math.abs(dx) < Math.abs(dy) * 1.25) return;
    event.preventDefault();
    moveKitchenSlide(dx < 0 ? 1 : -1);
    setSlideControlsVisible(true, true);
  });

  stage.addEventListener("pointercancel", () => {
    swipeStart = null;
  });

  stage.addEventListener("pointermove", () => {
    if (!controls.classList.contains("is-visible")) {
      setSlideControlsVisible(true, true);
    }
  });

  window.addEventListener("keydown", (event) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    moveKitchenSlide(event.key === "ArrowLeft" ? -1 : 1);
    setSlideControlsVisible(true, true);
  });

  updateSlideNavigationState();
}

function updateSlideDebugStatus() {
  const status = $("slide-debug-status");
  if (!status) return;
  const slide = slides[currentSlide] || {};
  const label = slide.type === "worldCupCountdown"
    ? "FIFA World Cup 2026: odliczanie"
    : slide.type === "results"
    ? `${slide.leagueName || "Wyniki"}: ${(slide.matches || []).length} wynikow`
    : slide.type === "match"
    ? `${slide.leagueName || "Wynik"}: ${displayName(slide.home?.name || "")} - ${displayName(slide.away?.name || "")}`
    : slide.type === "leaderboards"
    ? `${slide.leagueName || "FIFA World Cup"}: liderzy`
    : `${slide.type || "brak"} ${slide.leagueName || ""}`;
  status.textContent = slides.length ? `${currentSlide + 1}/${slides.length} - ${label}` : "0/0";
}

function setupSlideDebugControls() {
  if (!DEBUG_SLIDES) return;
  const panel = document.createElement("aside");
  panel.className = "slide-debug-panel";
  panel.innerHTML = `
    <strong>Debug slajdów</strong>
    <div id="slide-debug-status">0/0</div>
    <div class="slide-debug-actions">
      <button type="button" data-debug-slide="prev">Poprzedni</button>
      <button type="button" data-debug-slide="next">Następny</button>
      <button type="button" data-debug-slide="refresh">Odśwież</button>
    </div>
  `;
  document.body.appendChild(panel);
  panel.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-debug-slide]");
    if (!button) return;
    const action = button.dataset.debugSlide;
    if (action === "refresh") {
      updateScores();
      return;
    }
    if (!slides.length) return;
    currentSlide = action === "prev"
      ? (currentSlide + slides.length - 1) % slides.length
      : (currentSlide + 1) % slides.length;
    liveFocusIndex = 0;
    renderSlide();
  });
}

function startScoreRotation() {
  if (scoreTimer) clearInterval(scoreTimer);
  if (DEBUG_SLIDES) return;
  scoreTimer = setInterval(() => {
    const slide = slides[currentSlide];
    const liveMatches = slide?.type === "live" && Array.isArray(slide.matches) ? slide.matches : [];
    if (liveMatches.length > 1) {
      liveFocusIndex = (liveFocusIndex + 1) % liveMatches.length;
      renderSlide();
      return;
    }
    if (slides.length <= 1) return;
    currentSlide = (currentSlide + 1) % slides.length;
    liveFocusIndex = 0;
    renderSlide();
  }, 18000);
}

function scheduleScoreRefresh() {
  if (scoreRefreshTimer) clearTimeout(scoreRefreshTimer);
  scoreRefreshTimer = setTimeout(updateScores, hasLiveScore ? 30 * 1000 : 5 * 60 * 1000);
}

async function updateScores() {
  try {
    const response = await fetch("/api/kitchen/scores", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    scoreWindowHours = Number(payload.windowHours) || 24;
    const resultMatches = dedupeKitchenMatches(payload.matches);
    updateScoreTicker(resultMatches);
    const liveMatches = dedupeKitchenMatches(payload.liveMatches).filter(isActiveLiveMatch);
    hasLiveScore = liveMatches.length > 0;
    if (liveMatches.length && !DEBUG_SLIDES) {
      slides = [{
        type: "live",
        matches: liveMatches,
        tickerMatches: resultMatches,
      }];
    } else {
      slides = normalizeKitchenSlides(
        Array.isArray(payload.slides) && payload.slides.length
          ? payload.slides
          : resultMatches.map((match) => ({ type: "match", ...match }))
      );
      if (!DEBUG_SLIDES) slides = selectKitchenFootballSlides(slides, payload.footballPresentation);
      if (liveMatches.length) {
        slides = [{
          type: "live",
          matches: liveMatches,
          tickerMatches: resultMatches,
        }, ...slides];
      }
    }
      currentSlide = DEBUG_SLIDES && DEBUG_START_SLIDE < slides.length ? DEBUG_START_SLIDE : 0;
    liveFocusIndex = 0;
    renderSlide();
    startScoreRotation();
  } catch (error) {
    hasLiveScore = false;
    const root = $("kitchen-score-match");
    if (root) root.innerHTML = `<div class="score-empty">Nie udało się pobrać wyników</div>`;
  } finally {
    scheduleScoreRefresh();
  }
}

function setupFullscreen() {
  const screen = $("kitchen-screen");
  if (!screen) return;
  screen.addEventListener("click", () => {
    if (document.fullscreenElement) return;
    screen.requestFullscreen?.();
  }, { once: true });
}

function setupClozemasterShortcut() {
  const button = $("kitchen-clozemaster");
  if (!button) return;
  let holdTimer = null;
  let didConfigure = false;
  let cachedRemoteUrl = "";

  const validateClozemasterUrl = (value) => {
    const raw = String(value || "").trim();
    if (!raw) return "";
    try {
      const url = new URL(raw);
      return url.origin === "https://www.clozemaster.com" ? url.href : "";
    } catch (error) {
      return "";
    }
  };

  const storedClozemasterUrl = () => {
    try {
      return window.localStorage.getItem(CLOZEMASTER_STORAGE_KEY) || CLOZEMASTER_DEFAULT_URL;
    } catch (error) {
      return CLOZEMASTER_DEFAULT_URL;
    }
  };

  const fetchRemoteClozemasterUrl = async () => {
    try {
      const response = await fetch("/api/kitchen/settings", { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      const url = validateClozemasterUrl(payload?.clozemasterUrl);
      if (url) {
        cachedRemoteUrl = url;
        try {
          window.localStorage.setItem(CLOZEMASTER_STORAGE_KEY, url);
        } catch (error) {}
        return url;
      }
    } catch (error) {}
    return validateClozemasterUrl(cachedRemoteUrl) || storedClozemasterUrl();
  };

  const saveClozemasterUrl = async (value) => {
    const raw = String(value || "").trim();
    const url = validateClozemasterUrl(raw);
    if (raw && !url) return false;

    try {
      if (!raw) {
        window.localStorage.removeItem(CLOZEMASTER_STORAGE_KEY);
      } else {
        window.localStorage.setItem(CLOZEMASTER_STORAGE_KEY, url);
      }
    } catch (error) {
      // The server-side setting below is the source of truth.
    }

    try {
      const response = await fetch("/api/kitchen/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        cache: "no-store",
        body: JSON.stringify({ clozemasterUrl: raw }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      cachedRemoteUrl = validateClozemasterUrl(payload?.clozemasterUrl) || cachedRemoteUrl;
      return true;
    } catch (error) {
      return true;
    }
  };

  const configureClozemaster = async () => {
    didConfigure = true;
    const current = await fetchRemoteClozemasterUrl();
    const next = window.prompt("Wklej nowy link Clozemaster. Puste = domyślny.", current);
    if (next === null) return;
    if (!(await saveClozemasterUrl(next))) {
      window.alert("Nieprawidłowy link. Użyj adresu z https://www.clozemaster.com/");
    }
  };

  const openClozemaster = async () => {
    window.location.href = await fetchRemoteClozemasterUrl();
  };

  const startHold = () => {
    didConfigure = false;
    window.clearTimeout(holdTimer);
    holdTimer = window.setTimeout(configureClozemaster, CLOZEMASTER_HOLD_MS);
  };

  const cancelHold = () => {
    window.clearTimeout(holdTimer);
    holdTimer = null;
  };

  button.addEventListener("touchstart", startHold, { passive: true });
  button.addEventListener("touchend", cancelHold);
  button.addEventListener("touchcancel", cancelHold);
  button.addEventListener("mousedown", startHold);
  button.addEventListener("mouseup", cancelHold);
  button.addEventListener("mouseleave", cancelHold);

  button.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    if (didConfigure) return;
    openClozemaster();
  });
  window.addEventListener("keydown", (event) => {
    if (event.key === "F10" || (event.shiftKey && event.key.toLowerCase() === "c")) {
      event.preventDefault();
      configureClozemaster();
      return;
    }
    if (event.key === "F9" || event.key.toLowerCase() === "c") {
      openClozemaster();
    }
  });
}

function setupInputTest() {
  if (KITCHEN_PARAMS.get("inputTest") !== "1") return;

  const panel = document.createElement("aside");
  panel.className = "input-test-panel";
  panel.innerHTML = `
    <strong>Pad / klawiatura test</strong>
    <div id="input-test-log">Naciśnij przycisk na padzie...</div>
  `;
  document.body.appendChild(panel);
  const log = $("input-test-log");
  const lines = [];
  const write = (line) => {
    lines.unshift(line);
    if (lines.length > 8) lines.pop();
    if (log) log.innerHTML = lines.map(escapeHtml).join("<br>");
  };

  window.addEventListener("keydown", (event) => {
    write(`keydown key=${event.key} code=${event.code} keyCode=${event.keyCode}`);
  });
  window.addEventListener("gamepadconnected", (event) => {
    write(`gamepad: ${event.gamepad.id}`);
  });

  const pollGamepads = () => {
    const gamepads = navigator.getGamepads?.() || [];
    for (const gamepad of gamepads) {
      if (!gamepad) continue;
      const buttons = gamepad.buttons
        .map((button, index) => button.pressed ? index : null)
        .filter((index) => index !== null);
      if (buttons.length) write(`buttons: ${buttons.join(", ")}`);
    }
    requestAnimationFrame(pollGamepads);
  };
  pollGamepads();
}

function kitchenRefreshFingerprint(value) {
  try {
    return JSON.stringify(value ?? null);
  } catch (error) {
    return "null";
  }
}

function readSeenKitchenRefreshSignal() {
  try {
    return window.localStorage?.getItem(KITCHEN_REFRESH_STORAGE_KEY) || kitchenRefreshSeenFallback;
  } catch (error) {
    return kitchenRefreshSeenFallback;
  }
}

function writeSeenKitchenRefreshSignal(value) {
  kitchenRefreshSeenFallback = value;
  try {
    window.localStorage?.setItem(KITCHEN_REFRESH_STORAGE_KEY, value);
  } catch (error) {}
}

async function fetchJsonNoStore(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) return null;
  return response.json().catch(() => null);
}

async function fetchKitchenRefreshSnapshot() {
  const [dashboardSettings, kitchenSettings] = await Promise.all([
    fetchJsonNoStore("/api/settings/dashboard"),
    fetchJsonNoStore("/api/kitchen/settings"),
  ]);
  return {
    dashboard: dashboardSettings?.data || null,
    kitchen: kitchenSettings || null,
  };
}

async function checkKitchenRefreshSignal() {
  let snapshot = null;
  try {
    snapshot = await fetchKitchenRefreshSnapshot();
  } catch (error) {
    snapshot = null;
  }

  const signal = kitchenRefreshFingerprint(snapshot);
  const seen = readSeenKitchenRefreshSignal();
  if (!kitchenRefreshInitialized) {
    kitchenRefreshInitialized = true;
    if (!seen) {
      writeSeenKitchenRefreshSignal(signal);
      return;
    }
  }

  if (signal !== readSeenKitchenRefreshSignal()) {
    writeSeenKitchenRefreshSignal(signal);
    window.location.reload();
  }
}

function setupKitchenAutoRefresh() {
  if (kitchenRefreshTimer || typeof fetch !== "function") return;
  checkKitchenRefreshSignal();
  kitchenRefreshTimer = window.setInterval(checkKitchenRefreshSignal, KITCHEN_REFRESH_POLL_MS);
}

updateClock();
setInterval(updateClock, 1000);
setupFullscreen();
setupSlideNavigation();
initKitchenToday();
setupInputTest();
setupSlideDebugControls();
setupKitchenAutoRefresh();
setupKitchenRecipeMode();
updateWeather();
updateScores();
setInterval(updateWeather, 5 * 60 * 1000);
window.addEventListener("resize", scheduleKitchenRecipeFit);
document.addEventListener("fullscreenchange", scheduleKitchenRecipeFit);
