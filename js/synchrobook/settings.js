const STORAGE_KEY = "dashboard.synchrobook.settings.v1";

export const HIGHLIGHT_PRESETS = {
  yellow: { highlightBackground: "#ffd84d", highlightText: "#111111" },
  cyan: { highlightBackground: "#67e8f9", highlightText: "#071318" },
  lime: { highlightBackground: "#bef264", highlightText: "#101708" },
  pink: { highlightBackground: "#f9a8d4", highlightText: "#2a0718" },
  white: { highlightBackground: "#ffffff", highlightText: "#111111" },
};

const HIGHLIGHT_DEFAULTS = {
  highlightPreset: "yellow",
  ...HIGHLIGHT_PRESETS.yellow,
  highlightGlow: 18,
  highlightBold: true,
};

export const PRESETS = {
  desk: { mode: "desk", fontSize: 20, lineHeight: 1.7, columnWidth: 760, autoScroll: true, ...HIGHLIGHT_DEFAULTS },
  relax: { mode: "relax", fontSize: 27, lineHeight: 1.85, columnWidth: 820, autoScroll: true, ...HIGHLIGHT_DEFAULTS },
  bike: { mode: "bike", fontSize: 48, lineHeight: 1.9, columnWidth: 1160, autoScroll: true, ...HIGHLIGHT_DEFAULTS },
};

const VALID_COLOR = /^#[0-9a-f]{6}$/i;

function colorOrDefault(value, fallback) {
  return VALID_COLOR.test(value || "") ? value : fallback;
}

export function loadSettings() {
  try {
    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
    const mode = Object.hasOwn(PRESETS, stored?.mode) ? stored.mode : "desk";
    const migrated = { ...stored };
    if (mode === "bike" && migrated.fontSize === 44) migrated.fontSize = PRESETS.bike.fontSize;
    if (mode === "bike" && migrated.columnWidth === 1040) migrated.columnWidth = PRESETS.bike.columnWidth;
    return { ...PRESETS[mode], ...migrated, mode };
  } catch {
    return { ...PRESETS.desk };
  }
}

export function saveSettings(settings) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
}

export function applySettings(settings) {
  document.documentElement.dataset.synchrobookMode = settings.mode;
  document.documentElement.style.setProperty("--synchrobook-font-size", `${settings.fontSize}px`);
  document.documentElement.style.setProperty("--synchrobook-line-height", String(settings.lineHeight));
  document.documentElement.style.setProperty("--synchrobook-column", `${settings.columnWidth}px`);
  document.documentElement.style.setProperty("--synchrobook-highlight-bg", colorOrDefault(settings.highlightBackground, HIGHLIGHT_DEFAULTS.highlightBackground));
  document.documentElement.style.setProperty("--synchrobook-highlight-text", colorOrDefault(settings.highlightText, HIGHLIGHT_DEFAULTS.highlightText));
  document.documentElement.style.setProperty("--synchrobook-highlight-glow", `${Math.max(0, Math.min(36, Number(settings.highlightGlow) || 0))}px`);
  document.documentElement.style.setProperty("--synchrobook-highlight-weight", settings.highlightBold === false ? "400" : "800");
}
