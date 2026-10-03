const IMPORTANCE_OPTIONS = new Set(["ignore", "nice", "important", "must"]);
const YES_NO_UNKNOWN = new Set(["unknown", "yes", "no"]);

export const FLAT_IMPORTANCE_LABELS = Object.freeze({
  ignore: "olej",
  nice: "miło mieć",
  important: "ważne",
  must: "must have",
});

const IMPORTANCE_WEIGHTS = Object.freeze({
  ignore: 0,
  nice: 1,
  important: 2.2,
  must: 3.4,
});

export const FLAT_CATEGORY_LABELS = Object.freeze({
  budget: "Budżet i metraż",
  location: "Lokalizacja i budynek",
  comfort: "Komfort i wyposażenie",
});

const LOCATION_OPTIONS = Object.freeze([
  { value: "center", label: "centrum", rank: 0 },
  { value: "near-center", label: "blisko centrum", rank: 1 },
  { value: "further", label: "dalej od centrum", rank: 2 },
]);

const BUILDING_OPTIONS = Object.freeze([
  { value: "kamienica", label: "kamienica" },
  { value: "new", label: "nowe budownictwo" },
  { value: "block", label: "blok" },
  { value: "other", label: "inne" },
]);

const FLOOR_OPTIONS = Object.freeze([
  { value: "basement", label: "przyziemie / suterena", rank: 0 },
  { value: "ground", label: "parter", rank: 1 },
  { value: "first-plus", label: "1 lub wyżej", rank: 2 },
  { value: "top", label: "ostatnie piętro", rank: 3 },
]);

const LIGHT_OPTIONS = Object.freeze([
  { value: "poor", label: "słabo", rank: 0 },
  { value: "ok", label: "ok", rank: 1 },
  { value: "bright", label: "jasno", rank: 2 },
  { value: "sunny", label: "bardzo jasno", rank: 3 },
]);

const CONDITION_OPTIONS = Object.freeze([
  { value: "poor", label: "słaby stan", rank: 0 },
  { value: "ok", label: "do ogarnięcia", rank: 1 },
  { value: "good", label: "dobry stan", rank: 2 },
  { value: "renovated", label: "po remoncie", rank: 3 },
]);

const HEATING_OPTIONS = Object.freeze([
  { value: "city", label: "miejskie" },
  { value: "gas", label: "gazowe" },
  { value: "electric", label: "elektryczne" },
  { value: "other", label: "inne" },
]);

const BOOL_LISTING_OPTIONS = Object.freeze([
  { value: "unknown", label: "nie wiem" },
  { value: "yes", label: "tak" },
  { value: "no", label: "nie" },
]);

function optionLabels(options) {
  const labels = {};
  for (const option of options) {
    labels[option.value] = option.label;
  }
  return Object.freeze(labels);
}

export const FLAT_OPTION_LABELS = Object.freeze({
  importance: FLAT_IMPORTANCE_LABELS,
  choice: Object.freeze({
    unknown: "nie wiem",
    yes: "tak",
    no: "nie",
  }),
  location: optionLabels(LOCATION_OPTIONS),
  buildingType: optionLabels(BUILDING_OPTIONS),
  floor: optionLabels(FLOOR_OPTIONS),
  light: optionLabels(LIGHT_OPTIONS),
  condition: optionLabels(CONDITION_OPTIONS),
  heatingType: optionLabels(HEATING_OPTIONS),
});

const BUILDING_MATCH_SCORES = Object.freeze({
  kamienica: Object.freeze({ kamienica: 1, new: 0.58, block: 0.24, other: 0.38 }),
  new: Object.freeze({ kamienica: 0.76, new: 1, block: 0.48, other: 0.52 }),
  block: Object.freeze({ kamienica: 0.7, new: 0.56, block: 1, other: 0.5 }),
  other: Object.freeze({ kamienica: 0.55, new: 0.55, block: 0.42, other: 1 }),
});

const HEATING_MATCH_SCORES = Object.freeze({
  city: Object.freeze({ city: 1, gas: 0.72, electric: 0.2, other: 0.4 }),
  gas: Object.freeze({ city: 0.7, gas: 1, electric: 0.18, other: 0.4 }),
  electric: Object.freeze({ city: 0.26, gas: 0.24, electric: 1, other: 0.45 }),
  other: Object.freeze({ city: 0.42, gas: 0.4, electric: 0.36, other: 1 }),
});

function getOptionMap(options) {
  const map = new Map();
  for (const option of options) {
    map.set(option.value, option);
  }
  return map;
}

function toNumber(value) {
  if (value == null || value === "") return null;
  const normalized = String(value).trim().replace(",", ".");
  const parsed = Number(normalized);
  return Number.isFinite(parsed) ? parsed : null;
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function normalizeImportance(value, fallback = "ignore") {
  const normalized = String(value ?? fallback).trim().toLowerCase();
  return IMPORTANCE_OPTIONS.has(normalized) ? normalized : fallback;
}

function normalizeYesNoUnknown(value) {
  if (value === true) return "yes";
  if (value === false) return "no";
  const normalized = String(value ?? "unknown").trim().toLowerCase();
  return YES_NO_UNKNOWN.has(normalized) ? normalized : "unknown";
}

function normalizeSelect(value, options, fallback) {
  const normalized = String(value ?? fallback).trim().toLowerCase();
  return options.some((option) => option.value === normalized) ? normalized : fallback;
}

function pushUnique(list, message) {
  if (!message || list.includes(message)) return;
  list.push(message);
}

function formatIntegerLike(value) {
  const amount = Number(value);
  if (!Number.isFinite(amount)) return "-";
  const hasFraction = Math.abs(amount % 1) > 0.001;
  return amount.toLocaleString("pl-PL", {
    minimumFractionDigits: hasFraction ? 1 : 0,
    maximumFractionDigits: hasFraction ? 1 : 0,
  });
}

export function formatFlatMoney(value) {
  const amount = Number(value);
  if (!Number.isFinite(amount)) return "-";
  const hasFraction = Math.abs(amount % 1) > 0.001;
  return `${amount.toLocaleString("pl-PL", {
    minimumFractionDigits: hasFraction ? 2 : 0,
    maximumFractionDigits: hasFraction ? 2 : 0,
  })} z?`;
}

export const FLAT_FACTOR_DEFINITIONS = Object.freeze([
  {
    id: "maxTotalPrice",
    category: "budget",
    label: "Max all-in",
    description: "Cały miesięczny koszt z mediami i internetem.",
    kind: "max-number",
    listingKey: "totalPrice",
    unit: "z?",
    preferenceInput: { type: "number", label: "Limit", step: "50", placeholder: "2500" },
    listingInput: { type: "number", label: "Cena all-in (z?)", step: "50", placeholder: "2500" },
    defaultPreference: { importance: "must", target: 2500 },
    searchToken: (preference) => preference.target ? `do ${Math.round(preference.target)} z?` : "",
    callQuestion: (preference) =>
      preference.target
        ? `Ile wychodzi całość miesięcznie ze wszystkim? Mój limit to ${formatFlatMoney(preference.target)} all-in.`
        : "Ile wychodzi całość miesięcznie ze wszystkim?",
  },
  {
    id: "minTotalArea",
    category: "budget",
    label: "Min metraż całości",
    description: "Całe mieszkanie, nie tylko pokój.",
    kind: "min-number",
    listingKey: "totalArea",
    unit: "m2",
    preferenceInput: { type: "number", label: "Minimum", step: "0.5", placeholder: "35" },
    listingInput: { type: "number", label: "Całe mieszkanie (m2)", step: "0.5", placeholder: "35" },
    defaultPreference: { importance: "important", target: 35 },
    searchToken: (preference) => preference.target ? `${formatIntegerLike(preference.target)}m2` : "",
    callQuestion: (preference) =>
      preference.target
        ? `Jaki jest cały metraż mieszkania? Szukam czegoś, co ma co najmniej ${formatIntegerLike(preference.target)} m2.`
        : "Jaki jest cały metraż mieszkania?",
  },
  {
    id: "minMainRoomArea",
    category: "budget",
    label: "Min główny pokój",
    description: "Pokój / strefa dzienna na łóżko i biurko.",
    kind: "min-number",
    listingKey: "mainRoomArea",
    unit: "m2",
    preferenceInput: { type: "number", label: "Minimum", step: "0.5", placeholder: "24" },
    listingInput: { type: "number", label: "Główny pokój / strefa (m2)", step: "0.5", placeholder: "24" },
    defaultPreference: { importance: "must", target: 24 },
    searchToken: () => "\"duży pokój\"",
    callQuestion: (preference) =>
      preference.target
        ? `Jaki metraż ma główny pokój / strefa dzienna? Potrzebuję minimum ${formatIntegerLike(preference.target)} m2.`
        : "Jaki metraż ma główny pokój / strefa dzienna?",
  },
  {
    id: "minWindowsCount",
    category: "budget",
    label: "Min liczba okien",
    description: "Dobry skrót do tego, czy mieszkanie oddycha i ma światło.",
    kind: "min-number",
    listingKey: "windowsCount",
    unit: "okna",
    preferenceInput: { type: "number", label: "Minimum", step: "1", placeholder: "3" },
    listingInput: { type: "number", label: "Liczba okien", step: "1", placeholder: "2" },
    defaultPreference: { importance: "important", target: 3 },
    searchToken: () => "\"dużo okien\"",
    callQuestion: () => "Ile jest okien i czy mieszkanie nie jest przygaszone?",
  },
  {
    id: "location",
    category: "location",
    label: "Maks dystans od centrum",
    description: "Maksymalna odległość, jaką jeszcze akceptujesz.",
    kind: "max-rank",
    listingKey: "location",
    options: LOCATION_OPTIONS,
    optionMap: getOptionMap(LOCATION_OPTIONS),
    preferenceInput: { type: "select", label: "Najdalej", options: LOCATION_OPTIONS },
    listingInput: { type: "select", label: "Lokalizacja", options: [{ value: "unknown", label: "nie wiem" }, ...LOCATION_OPTIONS] },
    defaultPreference: { importance: "important", target: "near-center" },
    searchToken: (preference) => preference.target === "center" ? "centrum" : (preference.target === "near-center" ? "centrum OR \"blisko centrum\"" : ""),
    callQuestion: (preference) => preference.target === "center"
      ? "Czy to jest faktycznie centrum, a nie tylko opis z ogłoszenia?"
      : "Jak daleko jest do centrum i jaki jest szybki dojazd / dojście?",
  },
  {
    id: "buildingType",
    category: "location",
    label: "Typ budynku",
    description: "Kamienica, nowe, blok albo inne.",
    kind: "choice-map",
    listingKey: "buildingType",
    options: BUILDING_OPTIONS,
    optionMap: getOptionMap(BUILDING_OPTIONS),
    matchScores: BUILDING_MATCH_SCORES,
    preferenceInput: { type: "select", label: "Preferowane", options: BUILDING_OPTIONS },
    listingInput: { type: "select", label: "Budynek", options: [{ value: "unknown", label: "nie wiem" }, ...BUILDING_OPTIONS] },
    defaultPreference: { importance: "important", target: "kamienica" },
    searchToken: (preference) => preference.target === "kamienica" ? "kamienica" : "",
    callQuestion: () => "Jaki to jest budynek i jaki ma klimat na żywo?",
  },
  {
    id: "floor",
    category: "location",
    label: "Minimalne piętro",
    description: "Przyziemie i parter można tu zjechać, jeśli Ci nie siadają.",
    kind: "min-rank",
    listingKey: "floor",
    options: FLOOR_OPTIONS,
    optionMap: getOptionMap(FLOOR_OPTIONS),
    preferenceInput: { type: "select", label: "Minimum", options: FLOOR_OPTIONS.filter((option) => option.value !== "basement") },
    listingInput: { type: "select", label: "Piętro", options: [{ value: "unknown", label: "nie wiem" }, ...FLOOR_OPTIONS] },
    defaultPreference: { importance: "important", target: "first-plus" },
    searchToken: () => "",
    callQuestion: () => "Które to piętro i czy nie jest to parter albo przyziemie?",
  },
  {
    id: "light",
    category: "location",
    label: "Poziom światła",
    description: "Jak jasno ma być w mieszkaniu za dnia.",
    kind: "min-rank",
    listingKey: "light",
    options: LIGHT_OPTIONS,
    optionMap: getOptionMap(LIGHT_OPTIONS),
    preferenceInput: { type: "select", label: "Minimum", options: LIGHT_OPTIONS.filter((option) => option.value !== "poor") },
    listingInput: { type: "select", label: "Światło", options: [{ value: "unknown", label: "nie wiem" }, ...LIGHT_OPTIONS] },
    defaultPreference: { importance: "important", target: "bright" },
    searchToken: (preference) => preference.target === "bright" || preference.target === "sunny" ? "jasne" : "",
    callQuestion: () => "Jak mieszkanie wypada w dzień bez odpalania lamp?",
  },
  {
    id: "condition",
    category: "location",
    label: "Stan mieszkania",
    description: "Czy ma być po remoncie, czy wystarczy sensowny standard.",
    kind: "min-rank",
    listingKey: "condition",
    options: CONDITION_OPTIONS,
    optionMap: getOptionMap(CONDITION_OPTIONS),
    preferenceInput: { type: "select", label: "Minimum", options: CONDITION_OPTIONS.filter((option) => option.value !== "poor") },
    listingInput: { type: "select", label: "Stan mieszkania", options: [{ value: "unknown", label: "nie wiem" }, ...CONDITION_OPTIONS] },
    defaultPreference: { importance: "important", target: "good" },
    searchToken: () => "",
    callQuestion: () => "Jaki jest realny stan mieszkania, a nie tylko fotki z ogłoszenia?",
  },
  {
    id: "heatingType",
    category: "location",
    label: "Typ ogrzewania",
    description: "Możesz ustawić, jaki system grzania preferujesz.",
    kind: "choice-map",
    listingKey: "heatingType",
    options: HEATING_OPTIONS,
    optionMap: getOptionMap(HEATING_OPTIONS),
    matchScores: HEATING_MATCH_SCORES,
    preferenceInput: { type: "select", label: "Preferowane", options: HEATING_OPTIONS },
    listingInput: { type: "select", label: "Ogrzewanie", options: [{ value: "unknown", label: "nie wiem" }, ...HEATING_OPTIONS] },
    defaultPreference: { importance: "ignore", target: "city" },
    searchToken: () => "",
    callQuestion: () => "Jakie jest ogrzewanie i jak wyglądają rachunki w zimie?",
  },
  {
    id: "deskAndBed",
    category: "comfort",
    label: "Biurko i łóżko",
    description: "Czy oba meble wchodzą bez robienia kiszki z układu.",
    kind: "boolean",
    listingKey: "deskAndBed",
    listingInput: { type: "select", label: "Biurko + łóżko", options: BOOL_LISTING_OPTIONS },
    defaultPreference: { importance: "must" },
    searchToken: () => "\"duży pokój\"",
    callQuestion: () => "Czy wejdzie biurko i łóżko bez upychania wszystkiego na styk?",
  },
  {
    id: "kitchen",
    category: "comfort",
    label: "Kuchnia",
    description: "Normalna kuchnia albo przynajmniej sensowna strefa kuchenna.",
    kind: "boolean",
    listingKey: "kitchen",
    listingInput: { type: "select", label: "Kuchnia", options: BOOL_LISTING_OPTIONS },
    defaultPreference: { importance: "must" },
    searchToken: () => "",
    callQuestion: () => "Czy jest normalna kuchnia i co realnie jest na wyposażeniu?",
  },
  {
    id: "bathroom",
    category: "comfort",
    label: "Łazienka",
    description: "Własna łazienka w sensownym stanie.",
    kind: "boolean",
    listingKey: "bathroom",
    listingInput: { type: "select", label: "Łazienka", options: BOOL_LISTING_OPTIONS },
    defaultPreference: { importance: "must" },
    searchToken: () => "",
    callQuestion: () => "Czy łazienka jest normalna i w jakim jest stanie?",
  },
  {
    id: "internetReady",
    category: "comfort",
    label: "Internet",
    description: "Czy da się od razu podpiąć sensowny internet.",
    kind: "boolean",
    listingKey: "internetReady",
    listingInput: { type: "select", label: "Internet gotowy", options: BOOL_LISTING_OPTIONS },
    defaultPreference: { importance: "important" },
    searchToken: () => "",
    callQuestion: () => "Czy internet jest już podłączony albo czy są dobre opcje podpięcia?",
  },
  {
    id: "washingMachine",
    category: "comfort",
    label: "Pralka",
    description: "Czy nie musisz od razu dokładać tematu prania.",
    kind: "boolean",
    listingKey: "washingMachine",
    listingInput: { type: "select", label: "Pralka", options: BOOL_LISTING_OPTIONS },
    defaultPreference: { importance: "important" },
    searchToken: () => "",
    callQuestion: () => "Czy w mieszkaniu jest pralka i miejsce na suszenie rzeczy?",
  },
  {
    id: "quiet",
    category: "comfort",
    label: "Cisza",
    description: "Ulica, sąsiedzi, podwórko, tramwaj - wszystko co potrafi męczyć.",
    kind: "boolean",
    listingKey: "quiet",
    listingInput: { type: "select", label: "Cicho / spokojnie", options: BOOL_LISTING_OPTIONS },
    defaultPreference: { importance: "nice" },
    searchToken: () => "\"ciche\"",
    callQuestion: () => "Czy mieszkanie jest ciche i nie słychać ulicy albo sąsiadów?",
  },
  {
    id: "storage",
    category: "comfort",
    label: "Przechowywanie",
    description: "Szafa, schowek albo po prostu sensowne miejsce na rzeczy.",
    kind: "boolean",
    listingKey: "storage",
    listingInput: { type: "select", label: "Miejsce do przechowywania", options: BOOL_LISTING_OPTIONS },
    defaultPreference: { importance: "nice" },
    searchToken: () => "",
    callQuestion: () => "Czy jest sensowna szafa albo miejsce do przechowywania?",
  },
  {
    id: "whiteWall",
    category: "comfort",
    label: "Biala sciana pod rzutnik",
    description: "Bonus, ale wiadomo, ze klimat robi.",
    kind: "boolean",
    listingKey: "whiteWall",
    listingInput: { type: "select", label: "Biala sciana", options: BOOL_LISTING_OPTIONS },
    defaultPreference: { importance: "nice" },
    searchToken: () => "",
    callQuestion: () => "Czy jest sensowna biala sciana albo miejsce pod rzutnik?",
  },
  {
    id: "balcony",
    category: "comfort",
    label: "Balkon",
    description: "Wrzuc to tylko, jesli faktycznie Ci robi roznice.",
    kind: "boolean",
    listingKey: "balcony",
    listingInput: { type: "select", label: "Balkon", options: BOOL_LISTING_OPTIONS },
    defaultPreference: { importance: "ignore" },
    searchToken: () => "balkon",
    callQuestion: () => "Czy jest balkon albo chociaz sensowne wyjscie na zewnatrz?",
  },
  {
    id: "elevator",
    category: "comfort",
    label: "Winda",
    description: "Przydaje się, jeśli nie chcesz nosić wszystkiego po schodach.",
    kind: "boolean",
    listingKey: "elevator",
    listingInput: { type: "select", label: "Winda", options: BOOL_LISTING_OPTIONS },
    defaultPreference: { importance: "ignore" },
    searchToken: () => "",
    callQuestion: () => "Czy jest winda i jak wyglada wejscie do budynku?",
  },
]);

const FACTOR_MAP = new Map(FLAT_FACTOR_DEFINITIONS.map((definition) => [definition.id, definition]));

export function createDefaultFlatHuntPreferences() {
  const output = {};
  for (const definition of FLAT_FACTOR_DEFINITIONS) {
    output[definition.id] = {
      importance: normalizeImportance(definition.defaultPreference.importance, "ignore"),
    };
    if (definition.defaultPreference.target != null) {
      output[definition.id].target = definition.defaultPreference.target;
    }
  }
  return output;
}

export const DEFAULT_FLAT_HUNT_PREFERENCES = Object.freeze(createDefaultFlatHuntPreferences());
export const DEFAULT_FLAT_HUNT_PROFILE = DEFAULT_FLAT_HUNT_PREFERENCES;

export const DEFAULT_FLAT_HUNT_DRAFT = Object.freeze({
  title: "",
  district: "",
  notes: "",
  totalPrice: "",
  totalArea: "",
  mainRoomArea: "",
  windowsCount: "",
  location: "unknown",
  buildingType: "unknown",
  floor: "unknown",
  light: "unknown",
  condition: "unknown",
  heatingType: "unknown",
  deskAndBed: "unknown",
  kitchen: "unknown",
  bathroom: "unknown",
  internetReady: "unknown",
  washingMachine: "unknown",
  quiet: "unknown",
  storage: "unknown",
  whiteWall: "unknown",
  balcony: "unknown",
  elevator: "unknown",
});

function clonePreferenceValue(definition, incoming = {}) {
  const output = {
    importance: normalizeImportance(incoming.importance, definition.defaultPreference.importance),
  };
  if (definition.defaultPreference.target != null) {
    if (definition.kind === "max-number" || definition.kind === "min-number") {
      output.target = toNumber(incoming.target ?? definition.defaultPreference.target)
        ?? definition.defaultPreference.target;
    } else {
      output.target = normalizeSelect(
        incoming.target ?? definition.defaultPreference.target,
        definition.options || [],
        definition.defaultPreference.target,
      );
    }
  }
  return output;
}

export function normalizeFlatPreferences(input = {}) {
  const output = {};
  for (const definition of FLAT_FACTOR_DEFINITIONS) {
    output[definition.id] = clonePreferenceValue(definition, input?.[definition.id]);
  }
  return output;
}

export function normalizeFlatListing(input = {}) {
  const output = {
    title: String(input.title ?? "").trim(),
    district: String(input.district ?? "").trim(),
    notes: String(input.notes ?? "").trim(),
  };

  for (const definition of FLAT_FACTOR_DEFINITIONS) {
    const raw = input?.[definition.listingKey];
    if (definition.kind === "max-number" || definition.kind === "min-number") {
      output[definition.listingKey] = toNumber(raw);
    } else if (definition.kind === "boolean") {
      output[definition.listingKey] = normalizeYesNoUnknown(raw);
    } else {
      output[definition.listingKey] = normalizeSelect(raw, definition.options || [], "unknown");
    }
  }

  return output;
}

function formatFactorValue(definition, value) {
  if (value == null || value === "") return "brak";
  if (definition.kind === "max-number" || definition.kind === "min-number") {
    return definition.unit === "z?"
      ? formatFlatMoney(value)
      : `${formatIntegerLike(value)} ${definition.unit || ""}`.trim();
  }
  if (definition.kind === "boolean") {
    return FLAT_OPTION_LABELS.choice[value] || value;
  }
  const option = definition.optionMap?.get(value);
  return option?.label || String(value);
}

function summaryForPreference(definition, preference) {
  if (preference.importance === "ignore") return "";
  if (definition.kind === "boolean") return definition.label;
  if (preference.target == null || preference.target === "") return definition.label;
  return `${definition.label}: ${formatFactorValue(definition, preference.target)}`;
}

function evaluateNumber(definition, preference, value, mode) {
  if (value == null) {
    return {
      state: "unknown",
      satisfaction: 0.4,
      message: `Brak danych: ${definition.listingInput.label.toLowerCase()}.`,
      actual: null,
      expected: summaryForPreference(definition, preference),
    };
  }

  const target = Number(preference.target);
  const actualText = formatFactorValue(definition, value);
  const targetText = formatFactorValue(definition, target);

  if (mode === "max") {
    if (value <= target) {
      return {
        state: "match",
        satisfaction: 1,
        message: `${definition.label} spełnione: ${actualText} <= ${targetText}.`,
        actual: actualText,
        expected: targetText,
      };
    }
    const margin = Math.max(1, target * 0.25);
    return {
      state: "fail",
      satisfaction: clamp(1 - (value - target) / margin, 0, 1) * 0.45,
      message: `${definition.label} nie siada: ${actualText} > ${targetText}.`,
      actual: actualText,
      expected: targetText,
    };
  }

  if (value >= target) {
    return {
      state: "match",
      satisfaction: 1,
      message: `${definition.label} spełnione: ${actualText} >= ${targetText}.`,
      actual: actualText,
      expected: targetText,
    };
  }

  return {
    state: "fail",
    satisfaction: clamp(value / Math.max(1, target), 0, 1) * 0.45,
    message: `${definition.label} nie dobija: ${actualText} < ${targetText}.`,
    actual: actualText,
    expected: targetText,
  };
}

function evaluateBoolean(definition, value) {
  if (value === "unknown") {
    return {
      state: "unknown",
      satisfaction: 0.45,
      message: `Brak potwierdzenia: ${definition.label.toLowerCase()}.`,
      actual: "nie wiem",
      expected: "tak",
    };
  }
  if (value === "yes") {
    return {
      state: "match",
      satisfaction: 1,
      message: `${definition.label} jest ogarniete.`,
      actual: "tak",
      expected: "tak",
    };
  }
  return {
    state: "fail",
    satisfaction: 0,
    message: `${definition.label} nie jest spełnione.`,
    actual: "nie",
    expected: "tak",
  };
}

function evaluateRank(definition, preference, value, mode) {
  if (value === "unknown") {
    return {
      state: "unknown",
      satisfaction: 0.42,
      message: `Brak danych: ${definition.label.toLowerCase()}.`,
      actual: "nie wiem",
      expected: summaryForPreference(definition, preference),
    };
  }

  const actualOption = definition.optionMap.get(value);
  const targetOption = definition.optionMap.get(preference.target);
  if (!actualOption || !targetOption) {
    return {
      state: "unknown",
      satisfaction: 0.35,
      message: `Brak danych: ${definition.label.toLowerCase()}.`,
      actual: "nie wiem",
      expected: summaryForPreference(definition, preference),
    };
  }

  const actualRank = Number(actualOption.rank);
  const targetRank = Number(targetOption.rank);
  const pass = mode === "min" ? actualRank >= targetRank : actualRank <= targetRank;
  const distance = mode === "min" ? targetRank - actualRank : actualRank - targetRank;

  if (pass) {
    return {
      state: "match",
      satisfaction: 1,
      message: `${definition.label} trafia w Twoj prog (${actualOption.label}).`,
      actual: actualOption.label,
      expected: targetOption.label,
    };
  }

  return {
    state: "fail",
    satisfaction: clamp(1 - (distance + 1) / 4, 0, 1) * 0.4,
    message: `${definition.label} jest slabsze niz chcesz (${actualOption.label} vs ${targetOption.label}).`,
    actual: actualOption.label,
    expected: targetOption.label,
  };
}

function evaluateChoiceMap(definition, preference, value) {
  if (value === "unknown") {
    return {
      state: "unknown",
      satisfaction: 0.42,
      message: `Brak danych: ${definition.label.toLowerCase()}.`,
      actual: "nie wiem",
      expected: summaryForPreference(definition, preference),
    };
  }

  const actualOption = definition.optionMap.get(value);
  const targetOption = definition.optionMap.get(preference.target);
  if (!actualOption || !targetOption) {
    return {
      state: "unknown",
      satisfaction: 0.35,
      message: `Brak danych: ${definition.label.toLowerCase()}.`,
      actual: "nie wiem",
      expected: summaryForPreference(definition, preference),
    };
  }

  const rawScore = definition.matchScores?.[preference.target]?.[value] ?? (preference.target === value ? 1 : 0.3);
  const state = rawScore >= 0.85 ? "match" : "fail";
  return {
    state,
    satisfaction: state === "match" ? 1 : clamp(rawScore, 0, 1) * 0.5,
    message: state === "match"
      ? `${definition.label} pasuje (${actualOption.label}).`
      : `${definition.label} odbiega od preferencji (${actualOption.label} vs ${targetOption.label}).`,
    actual: actualOption.label,
    expected: targetOption.label,
  };
}

function evaluateFactor(definition, preference, listing) {
  const value = listing[definition.listingKey];
  if (definition.kind === "max-number") return evaluateNumber(definition, preference, value, "max");
  if (definition.kind === "min-number") return evaluateNumber(definition, preference, value, "min");
  if (definition.kind === "boolean") return evaluateBoolean(definition, value);
  if (definition.kind === "min-rank") return evaluateRank(definition, preference, value, "min");
  if (definition.kind === "max-rank") return evaluateRank(definition, preference, value, "max");
  if (definition.kind === "choice-map") return evaluateChoiceMap(definition, preference, value);
  return {
    state: "unknown",
    satisfaction: 0.35,
    message: `Brak logiki dla: ${definition.label}.`,
    actual: null,
    expected: summaryForPreference(definition, preference),
  };
}

export function scoreFlatListing(input, preferencesInput = DEFAULT_FLAT_HUNT_PREFERENCES) {
  const listing = normalizeFlatListing(input);
  const preferences = normalizeFlatPreferences(preferencesInput);
  const positives = [];
  const warnings = [];
  const blockers = [];
  const details = [];
  let weightedScore = 0;
  let totalWeight = 0;
  let activeCount = 0;

  for (const definition of FLAT_FACTOR_DEFINITIONS) {
    const preference = preferences[definition.id];
    if (!preference || preference.importance === "ignore") continue;

    const weight = IMPORTANCE_WEIGHTS[preference.importance] || 0;
    const result = evaluateFactor(definition, preference, listing);
    activeCount += 1;
    totalWeight += weight;
    weightedScore += result.satisfaction * weight;

    details.push({
      id: definition.id,
      label: definition.label,
      category: definition.category,
      categoryLabel: FLAT_CATEGORY_LABELS[definition.category] || definition.category,
      importance: preference.importance,
      importanceLabel: FLAT_IMPORTANCE_LABELS[preference.importance],
      state: result.state,
      satisfaction: result.satisfaction,
      targetSummary: summaryForPreference(definition, preference),
      actualSummary: result.actual,
      message: result.message,
    });

    if (result.state === "match") {
      pushUnique(positives, result.message);
    } else if (result.state === "fail" && preference.importance === "must") {
      pushUnique(blockers, result.message);
    } else {
      pushUnique(warnings, result.message);
    }
  }

  const score = totalWeight > 0
    ? clamp(Math.round((weightedScore / totalWeight) * 100), 0, 100)
    : 0;

  let verdict = "Skonfiguruj kryteria";
  let verdictTone = "maybe";
  if (activeCount > 0) {
    verdict = "Raczej nie";
    verdictTone = "bad";
    if (blockers.length === 0 && score >= 85) {
      verdict = "Dzwon teraz";
      verdictTone = "excellent";
    } else if (blockers.length === 0 && score >= 70) {
      verdict = "Bierz ogledziny";
      verdictTone = "good";
    } else if (blockers.length === 0 && score >= 55) {
      verdict = "Do sprawdzenia";
      verdictTone = "maybe";
    }
  }

  const budgetPreference = preferences.maxTotalPrice;
  const budgetSlack = budgetPreference?.importance !== "ignore" && listing.totalPrice != null && budgetPreference?.target != null
    ? budgetPreference.target - listing.totalPrice
    : null;

  return {
    listing,
    preferences,
    score,
    verdict,
    verdictTone,
    positives,
    warnings,
    blockers,
    details,
    activeCount,
    budgetSlack,
  };
}

export function buildPreferenceHighlights(preferencesInput = DEFAULT_FLAT_HUNT_PREFERENCES, limit = 8) {
  const preferences = normalizeFlatPreferences(preferencesInput);
  return FLAT_FACTOR_DEFINITIONS
    .map((definition) => ({ definition, preference: preferences[definition.id] }))
    .filter(({ preference }) => preference.importance !== "ignore")
    .sort((a, b) =>
      (IMPORTANCE_WEIGHTS[b.preference.importance] || 0) - (IMPORTANCE_WEIGHTS[a.preference.importance] || 0)
      || a.definition.label.localeCompare(b.definition.label, "pl"))
    .slice(0, limit)
    .map(({ definition, preference }) => summaryForPreference(definition, preference))
    .filter(Boolean);
}

export function buildPreferenceStats(preferencesInput = DEFAULT_FLAT_HUNT_PREFERENCES) {
  const preferences = normalizeFlatPreferences(preferencesInput);
  const stats = { must: 0, important: 0, nice: 0, active: 0, budget: null };
  for (const definition of FLAT_FACTOR_DEFINITIONS) {
    const preference = preferences[definition.id];
    if (!preference || preference.importance === "ignore") continue;
    stats.active += 1;
    stats[preference.importance] += 1;
    if (definition.id === "maxTotalPrice" && preference.target != null) {
      stats.budget = preference.target;
    }
  }
  return stats;
}

function collectSearchTokens(preferences) {
  const tokens = [];
  for (const definition of FLAT_FACTOR_DEFINITIONS) {
    const preference = preferences[definition.id];
    if (!preference || preference.importance === "ignore") continue;
    if (preference.importance === "nice" && definition.id !== "quiet" && definition.id !== "whiteWall") continue;
    const token = definition.searchToken?.(preference);
    if (token && !tokens.includes(token)) tokens.push(token);
  }
  return tokens.slice(0, 8);
}

export function buildSearchPresets(preferencesInput = DEFAULT_FLAT_HUNT_PREFERENCES) {
  const preferences = normalizeFlatPreferences(preferencesInput);
  const queryCore = ["Kraków", "mieszkanie", ...collectSearchTokens(preferences)].filter(Boolean).join(" ");
  const presets = [
    { key: "otodom", label: "Google x Otodom", siteLabel: "otodom.pl", description: "Szeroki sweep z aktywnych kryteriów.", query: `site:otodom.pl ${queryCore}` },
    { key: "olx", label: "Google x OLX", siteLabel: "olx.pl", description: "Dobre na świeże i bardziej surowe leady.", query: `site:olx.pl ${queryCore}` },
    { key: "wide", label: "Szeroki sweep", siteLabel: "google", description: "Bez filtra serwisu - do zbierania wszystkiego, co może mieć sens.", query: queryCore },
  ];
  return presets.map((preset) => ({
    ...preset,
    url: `https://www.google.com/search?q=${encodeURIComponent(preset.query)}`,
  }));
}

export function buildCallScript(preferencesInput = DEFAULT_FLAT_HUNT_PREFERENCES) {
  const preferences = normalizeFlatPreferences(preferencesInput);
  const active = FLAT_FACTOR_DEFINITIONS
    .map((definition) => ({ definition, preference: preferences[definition.id] }))
    .filter(({ preference }) => preference.importance !== "ignore")
    .sort((a, b) => (IMPORTANCE_WEIGHTS[b.preference.importance] || 0) - (IMPORTANCE_WEIGHTS[a.preference.importance] || 0));

  const quickIds = new Set(["maxTotalPrice", "minTotalArea", "minMainRoomArea", "kitchen", "bathroom", "location", "floor"]);
  const quickFilter = active
    .filter(({ definition }) => quickIds.has(definition.id))
    .map(({ definition, preference }) => definition.callQuestion?.(preference))
    .filter(Boolean);
  const detailQuestions = active
    .filter(({ definition }) => !quickIds.has(definition.id))
    .map(({ definition, preference }) => definition.callQuestion?.(preference))
    .filter(Boolean)
    .slice(0, 8);

  return [
    {
      key: "filter",
      title: "1. Szybki filtr",
      meta: "Najpierw wytnij leady, które i tak nie przejdą przez Twoje must-have.",
      items: quickFilter.length ? quickFilter : ["Najpierw ustaw kilka aktywnych kryteriów, a tu zbuduje się szybki filtr do telefonu."],
    },
    {
      key: "details",
      title: "2. Szczegóły pod Twoje preferencje",
      meta: "Pytania wyciągnięte z kryteriów, które ustawiłeś jako ważne albo must-have.",
      items: detailQuestions.length ? detailQuestions : ["Po ustawieniu preferencji pojawią się tutaj dopasowane pytania dodatkowe."],
    },
    {
      key: "costs",
      title: "3. Koszty i formalności",
      meta: "To warto odhaczyć prawie zawsze, niezależnie od samego score.",
      items: [
        "Ile wynosi czynsz administracyjny, a ile realnie wychodzą media w zimie i latem?",
        "Jaka jest długość umowy, okres wypowiedzenia i czy można się normalnie zameldować?",
        "Czy jest prowizja, kaucja i od kiedy lokal jest dostępny?",
        "Czy internet jest już podłączony albo czy są dobre opcje podpięcia?",
      ],
    },
    {
      key: "visit",
      title: "4. Na miejscu",
      meta: "Score jest pomocny, ale oglądanie i tak musi potwierdzić klimat mieszkania.",
      items: [
        "Sprawdź mieszkanie za dnia bez lamp - czy światło faktycznie dowozi.",
        "Przejdź układ z miarką: łóżko, biurko, szafa, przejście, rzutnik.",
        "Posłuchaj, czy nie słychać ulicy, podwórka albo sąsiadów.",
        "Zobacz stan okien, łazienki, kuchni i wszystkie rzeczy, które na zdjęciach są zawsze piękniejsze.",
      ],
    },
  ];
}

export function buildCallScriptText(sections = []) {
  return sections
    .map((section) => [section.title, section.meta, ...section.items.map((item) => `- ${item}`)].join("\n"))
    .join("\n\n");
}

export function buildLeadCopyText(input, evaluationInput, preferencesInput = DEFAULT_FLAT_HUNT_PREFERENCES) {
  const listing = normalizeFlatListing(input);
  const evaluation = evaluationInput?.score != null ? evaluationInput : scoreFlatListing(listing, preferencesInput);
  const title = listing.title || "Bez nazwy";
  const location = listing.district || "bez dzielnicy";
  const lines = [`${title} / ${location}`, `Score: ${evaluation.score}/100 (${evaluation.verdict})`];

  if (listing.totalPrice != null) lines.push(`Cena all-in: ${formatFlatMoney(listing.totalPrice)}`);
  if (listing.totalArea != null) lines.push(`Metraż całości: ${formatIntegerLike(listing.totalArea)} m2`);
  if (listing.mainRoomArea != null) lines.push(`Glowna strefa: ${formatIntegerLike(listing.mainRoomArea)} m2`);

  const musts = evaluation.details
    .filter((detail) => detail.importance === "must")
    .slice(0, 4)
    .map((detail) => `${detail.label}: ${detail.state}`);
  if (musts.length) lines.push(`Must-have: ${musts.join("; ")}`);
  if (evaluation.warnings.length) lines.push(`Do sprawdzenia: ${evaluation.warnings.slice(0, 4).join("; ")}`);
  if (evaluation.blockers.length) lines.push(`Blockery: ${evaluation.blockers.slice(0, 3).join("; ")}`);
  if (listing.notes) lines.push(`Notatki: ${listing.notes}`);
  return lines.join("\n");
}
