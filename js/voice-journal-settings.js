export const VOICE_JOURNAL_SETTINGS_KEY = "voiceJournalTranscriptionDefaultsV1";

export const VOICE_JOURNAL_PRESET_LABELS = {
  fast: "Szybka",
  balanced: "Zbalansowana",
  quality: "Najlepsza jakość",
  custom: "Własne",
};

function clone(value) {
  if (value === undefined) return undefined;
  return JSON.parse(JSON.stringify(value));
}

export function supportedTranscriptionSettings(capabilities = {}) {
  const supported = Array.isArray(capabilities.supported) ? capabilities.supported : [];
  const specs = capabilities.specs && typeof capabilities.specs === "object" ? capabilities.specs : {};
  return supported.filter((name) => specs[name]).map((name) => [name, specs[name]]);
}

export function presetTranscriptionSettings(capabilities = {}, preset = "balanced") {
  const presets = capabilities.presets && typeof capabilities.presets === "object" ? capabilities.presets : {};
  return clone(presets[preset] || presets[capabilities.recommendedPreset] || {});
}

export function parseTranscriptionSetting(spec, value) {
  if (spec.type === "boolean") return Boolean(value);
  if (spec.type === "temperature") {
    const parts = String(value).split(",").map((part) => part.trim());
    const values = parts.map(Number);
    if (!parts.length || parts.some((part) => !part) || values.length > 10 || values.some((number) => !Number.isFinite(number) || number < 0 || number > 1)) {
      throw new Error("Temperatura musi zawierać od 1 do 10 wartości w zakresie 0–1.");
    }
    return values.length === 1 ? values[0] : values;
  }
  if (spec.type === "number" || spec.type === "integer") {
    if (String(value).trim() === "") return null;
    const number = Number(value);
    if (!Number.isFinite(number)) throw new Error(`Nieprawidłowa wartość pola „${spec.label}”.`);
    if (number < spec.min || number > spec.max || (spec.type === "integer" && !Number.isInteger(number))) {
      throw new Error(`Pole „${spec.label}” musi mieścić się w zakresie ${spec.min}–${spec.max}.`);
    }
    return number;
  }
  const text = String(value || "").trim();
  if (spec.maxLength && text.length > spec.maxLength) throw new Error(`Pole „${spec.label}” jest zbyt długie.`);
  return text || null;
}

export function effectiveTranscriptionSettings(options, capabilities = {}, { device = "auto", cudaAvailable = false } = {}) {
  const effective = {};
  supportedTranscriptionSettings(capabilities).forEach(([name, spec]) => {
    effective[name] = options && Object.hasOwn(options, name) ? clone(options[name]) : clone(spec.default);
  });
  const effectiveDevice = device === "auto" ? (cudaAvailable ? "cuda" : "cpu") : device;
  if (Object.hasOwn(effective, "fp16") && effectiveDevice !== "cuda") effective.fp16 = false;
  return effective;
}

export function saveTranscriptionDefaults(value, storage = globalThis.localStorage) {
  storage?.setItem(VOICE_JOURNAL_SETTINGS_KEY, JSON.stringify(value));
}

export function loadTranscriptionDefaults(capabilities, storage = globalThis.localStorage) {
  try {
    const parsed = JSON.parse(storage?.getItem(VOICE_JOURNAL_SETTINGS_KEY) || "null");
    if (!parsed || typeof parsed !== "object" || !parsed.options || typeof parsed.options !== "object") return null;
    const supported = new Set(supportedTranscriptionSettings(capabilities).map(([name]) => name));
    return {
      preset: parsed.preset in VOICE_JOURNAL_PRESET_LABELS ? parsed.preset : "custom",
      options: Object.fromEntries(Object.entries(parsed.options).filter(([name]) => supported.has(name))),
    };
  } catch {
    return null;
  }
}
