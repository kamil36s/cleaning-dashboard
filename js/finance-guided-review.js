const UNKNOWN_CHOICES = [
  { id: "unknown", label: "Nie wiem / nie pamiętam", stop: true },
  { id: "skip", label: "Pomiń na razie", stop: true },
];

const CATEGORY_TARGETS = {
  mixed_shop: ["Zakupy codzienne", "Zakupy mieszane"],
  groceries: ["Zakupy codzienne", "Spożywcze"],
  stimulants: ["Zakupy codzienne", "Używki"],
  restaurant: ["Jedzenie poza domem", "Restauracje"],
  delivery: ["Jedzenie poza domem", "Delivery"],
  snacks: ["Jedzenie poza domem", "Kawa i przekąski"],
  public_transport: ["Transport", "Komunikacja"],
  taxi: ["Transport", "Taxi / rideshare"],
  rail: ["Transport", "Kolej"],
  fuel: ["Transport", "Paliwo"],
  other_transport: ["Transport", "Inny transport"],
  pharmacy: ["Zdrowie", "Apteka"],
  doctors: ["Zdrowie", "Lekarze"],
  tests: ["Zdrowie", "Badania"],
  hygiene: ["Higiena i uroda", null],
  events: ["Rozrywka", "Wydarzenia"],
  games: ["Rozrywka", "Gry"],
  cinema: ["Rozrywka", "Kino"],
  hobby: ["Rozrywka", "Hobby"],
  subscriptions: ["Usługi i subskrypcje", "Subskrypcje"],
  apps: ["Usługi i subskrypcje", "Aplikacje"],
  bills: ["Usługi i subskrypcje", "Rachunki i usługi"],
  services: ["Usługi i subskrypcje", "Inne usługi"],
  electronics: ["Zakupy", "Elektronika"],
  clothes: ["Zakupy", "Odzież"],
  home_shop: ["Zakupy", "Dom"],
  other_shop: ["Zakupy", "Inne zakupy"],
  lodging: ["Podróże", "Noclegi"],
  travel_transport: ["Podróże", "Transport w podróży"],
  other_travel: ["Podróże", "Inne podróże"],
  education: ["Edukacja", null],
  fees: ["Opłaty i prowizje", null],
  other: ["Inne", "Do ustalenia"],
};

const KIND_LABELS = {
  expense: "Wydatek", transfer: "Przelew", salary: "Wynagrodzenie",
  income: "Dochód", refund: "Zwrot", saving: "Oszczędzanie",
  cash: "Gotówka", other: "Inne",
};

const fold = (value) => String(value || "").trim().toLocaleLowerCase("pl");

function choice(id, label, effect = {}) {
  return { id, label, ...effect };
}

function question(id, prompt, choices, explanation = "") {
  return { id, prompt, explanation, choices: [...choices, ...UNKNOWN_CHOICES] };
}

const QUESTIONS = {
  root: () => question("root_kind", "Co to było?", [
    choice("purchase", "Zakup / wydatek", { kind: "expense", branch: "expense" }),
    choice("transfer", "Przelew", { kind: "transfer", branch: "transfer" }),
    choice("income", "Dochód", { kind: "income", branch: "income" }),
    choice("refund", "Zwrot", { kind: "refund", complete: true }),
    choice("saving", "Oszczędzanie", { kind: "saving", complete: true }),
    choice("cash", "Gotówka", { kind: "cash", branch: "cash" }),
    choice("fee", "Opłata / prowizja", { kind: "expense", category: "fees", complete: true }),
    choice("other", "Inne", { kind: "other", complete: true }),
  ], "Wybierz znaczenie operacji, nie nazwę z banku."),
  expense: () => question("expense_domain", "Czego dotyczył ten wydatek?", [
    choice("shop", "Sklep / zakupy", { branch: "shop", path: "Sklep" }),
    choice("food", "Jedzenie / gastronomia", { branch: "food", path: "Jedzenie" }),
    choice("transport", "Transport", { branch: "transport", path: "Transport" }),
    choice("service", "Usługa / rachunek", { branch: "service", path: "Usługa" }),
    choice("entertainment", "Rozrywka / bilet", { branch: "entertainment", path: "Rozrywka" }),
    choice("health", "Zdrowie", { branch: "health", path: "Zdrowie" }),
    choice("travel", "Podróż", { branch: "travel", path: "Podróż" }),
    choice("education", "Edukacja", { category: "education", complete: true }),
    choice("hygiene", "Higiena / uroda", { category: "hygiene", complete: true }),
    choice("other", "Inny wydatek", { category: "other", complete: true }),
  ]),
  shop: () => question("shop_type", "Jaki to był rodzaj sklepu?", [
    choice("mixed", "Supermarket / convenience", { category: "mixed_shop", merchantType: ["Supermarket", "Sklep spożywczy"], complete: true, note: "Szczegóły będzie można później rozbić na podstawie paragonu." }),
    choice("drugstore", "Drogeria", { category: "hygiene", merchantType: ["Drogeria"], complete: true }),
    choice("clothes", "Odzież", { category: "clothes", merchantType: ["Odzież"], complete: true }),
    choice("electronics", "Elektronika", { category: "electronics", complete: true }),
    choice("home", "Dom / wyposażenie", { category: "home_shop", merchantType: ["Dom i wyposażenie"], complete: true }),
    choice("pharmacy", "Apteka", { category: "pharmacy", merchantType: ["Apteka"], complete: true }),
    choice("hobby", "Hobby", { category: "hobby", complete: true }),
    choice("marketplace", "Marketplace / sklep online", { category: "other_shop", merchantType: ["Marketplace", "Sklep internetowy"], complete: true }),
    choice("other", "Inny sklep", { category: "other_shop", complete: true }),
  ], "Supermarket pozostaje zakupem mieszanym bez danych z paragonu."),
  food: () => question("food_type", "Jaki to był rodzaj jedzenia?", [
    choice("restaurant", "Restauracja", { category: "restaurant", merchantType: ["Restauracja"], complete: true }),
    choice("delivery", "Delivery", { category: "delivery", merchantType: ["Delivery"], complete: true }),
    choice("fast_food", "Fast food", { category: "restaurant", merchantType: ["Restauracja"], complete: true }),
    choice("cafe", "Kawiarnia", { category: "snacks", merchantType: ["Kawiarnia"], complete: true }),
    choice("bar", "Bar / pub", { category: "stimulants", merchantType: ["Bar / klub"], complete: true }),
    choice("bakery", "Piekarnia", { category: "groceries", merchantType: ["Piekarnia"], complete: true }),
    choice("snacks", "Przekąski", { category: "snacks", complete: true }),
    choice("other", "Inne jedzenie", { category: "restaurant", complete: true }),
  ]),
  transport: () => question("transport_type", "Jaki to był transport?", [
    choice("taxi", "Taxi / rideshare", { category: "taxi", merchantType: ["Taxi / rideshare"], complete: true }),
    choice("public", "Komunikacja miejska", { category: "public_transport", merchantType: ["Komunikacja miejska"], complete: true }),
    choice("rail", "Pociąg", { category: "rail", merchantType: ["Kolej"], complete: true }),
    choice("fuel", "Paliwo", { category: "fuel", merchantType: ["Stacja paliw"], complete: true }),
    choice("parking", "Parking", { category: "other_transport", complete: true }),
    choice("car", "Samochód / serwis", { category: "other_transport", complete: true }),
    choice("flight", "Lot", { category: "travel_transport", merchantType: ["Loty"], complete: true }),
    choice("other", "Inny transport", { category: "other_transport", complete: true }),
  ]),
  service: () => question("service_type", "Jakiego rodzaju była to usługa?", [
    choice("telecom", "Telefon / internet", { category: "bills", complete: true }),
    choice("utilities", "Media domowe", { category: "bills", complete: true }),
    choice("software", "Software", { category: "apps", merchantType: ["Aplikacja"], complete: true }),
    choice("streaming", "Streaming", { category: "subscriptions", merchantType: ["Subskrypcja"], complete: true }),
    choice("subscription", "Subskrypcja", { category: "subscriptions", merchantType: ["Subskrypcja"], complete: true }),
    choice("professional", "Usługa profesjonalna", { category: "services", complete: true }),
    choice("home", "Usługa domowa", { category: "services", complete: true }),
    choice("bank", "Bank / prowizja", { category: "fees", merchantType: ["Bank"], complete: true }),
    choice("other", "Inna usługa", { category: "services", complete: true }),
  ]),
  entertainment: () => question("entertainment_type", "Czego dotyczyła rozrywka?", [
    choice("concert", "Koncert", { category: "events", complete: true }),
    choice("festival", "Festiwal", { category: "events", complete: true }),
    choice("cinema", "Kino", { category: "cinema", merchantType: ["Kino"], complete: true }),
    choice("sport", "Sport", { category: "hobby", complete: true }),
    choice("theatre", "Teatr", { category: "events", complete: true }),
    choice("game", "Gra", { category: "games", merchantType: ["Gry"], complete: true }),
    choice("hobby", "Hobby", { category: "hobby", complete: true }),
    choice("other", "Inne wydarzenie", { category: "events", complete: true }),
  ]),
  health: () => question("health_type", "Czego dotyczył wydatek na zdrowie?", [
    choice("pharmacy", "Apteka / leki", { category: "pharmacy", merchantType: ["Apteka"], complete: true }),
    choice("doctor", "Lekarz", { category: "doctors", merchantType: ["Lekarze"], complete: true }),
    choice("dentist", "Dentysta", { category: "doctors", complete: true }),
    choice("tests", "Badania", { category: "tests", complete: true }),
    choice("physio", "Fizjoterapia", { category: "doctors", complete: true }),
    choice("other", "Inne zdrowie", { category: "doctors", complete: true }),
  ]),
  travel: () => question("travel_type", "Czego dotyczyła podróż?", [
    choice("lodging", "Nocleg", { category: "lodging", merchantType: ["Nocleg", "Hotel"], complete: true }),
    choice("transport", "Transport", { category: "travel_transport", complete: true }),
    choice("flight", "Lot", { category: "travel_transport", merchantType: ["Loty"], complete: true }),
    choice("attraction", "Bilet / atrakcja", { category: "other_travel", complete: true }),
    choice("food", "Jedzenie w podróży", { category: "restaurant", complete: true }),
    choice("other", "Inne", { category: "other_travel", complete: true }),
  ]),
  transfer: () => question("transfer_type", "Czego dotyczył ten przelew?", [
    choice("own", "Między moimi kontami", { kind: "transfer", complete: true }),
    choice("refund", "Zwrot kosztów", { kind: "refund", complete: true }),
    choice("debt", "Oddanie długu / pożyczka", { kind: "transfer", complete: true }),
    choice("private", "Prezent / prywatny przelew", { kind: "transfer", complete: true }),
    choice("purchase", "Zapłata za coś", { kind: "expense", branch: "expense" }),
    choice("income", "Dochód", { kind: "income", complete: true }),
    choice("saving", "Oszczędzanie", { kind: "saving", complete: true }),
    choice("other", "Inny przelew", { kind: "transfer", complete: true }),
  ], "Zwykły przelew nie potrzebuje kategorii zakupowej."),
  income: () => question("income_type", "Jaki to był wpływ?", [
    choice("salary", "Wynagrodzenie", { kind: "salary", complete: true }),
    choice("income", "Inny dochód", { kind: "income", complete: true }),
    choice("expense_refund", "Zwrot kosztów", { kind: "refund", complete: true }),
    choice("purchase_refund", "Zwrot zakupu", { kind: "refund", complete: true }),
    choice("own_transfer", "Między moimi kontami", { kind: "transfer", complete: true }),
    choice("private", "Prezent / prywatny przelew", { kind: "transfer", complete: true }),
    choice("other", "Inny wpływ", { kind: "income", complete: true }),
  ], "Zwrot nie będzie liczony jako dochód."),
  cash: () => question("cash_use", "Czy wiesz, na co została użyta gotówka?", [
    choice("withdrawal", "Nie — to tylko wypłata gotówki", { kind: "cash", complete: true }),
    choice("purchase", "Tak — zapłaciłem za coś", { kind: "expense", branch: "expense" }),
  ], "Sama wypłata z bankomatu nie jest wydatkiem konsumpcyjnym."),
};

function categoryIndex(categories) {
  const byPath = new Map();
  for (const item of categories || []) {
    const path = item.parentName ? `${fold(item.parentName)}>${fold(item.name)}` : fold(item.name);
    byPath.set(path, item);
  }
  return byPath;
}

function findCategory(categories, target) {
  const [parent, child] = CATEGORY_TARGETS[target] || [];
  if (!parent) return null;
  const key = child ? `${fold(parent)}>${fold(child)}` : fold(parent);
  return categoryIndex(categories).get(key) || null;
}

function findMerchantType(types, names = []) {
  const wanted = new Set(names.map(fold));
  return (types || []).find((item) => wanted.has(fold(item.name))) || null;
}

function knownKind(group) {
  const kinds = [...new Set((group?.transactionKinds || []).filter((value) => value && value !== "unknown"))];
  return kinds.length === 1 ? kinds[0] : null;
}

function shortcutQuestion(group) {
  const suggestion = group?.suggestion || {};
  if (!["exact", "strong"].includes(suggestion.confidence) || !suggestion.resolvesAllFields) return null;
  const semanticKinds = new Set((group?.transactionKinds || []).filter((value) => value && value !== "unknown"));
  if (semanticKinds.size > 1 || fold(suggestion.category) === fold("Do ustalenia")) return null;
  const category = [suggestion.parentCategory, suggestion.category].filter(Boolean).join(" → ");
  const merchant = suggestion.merchant || group.displayName;
  let prompt = `To wygląda na „${category || KIND_LABELS[suggestion.transactionKind] || "rozpoznaną operację"}”`;
  if (suggestion.category === "Taxi / rideshare") prompt = `To wygląda na przejazd${merchant ? ` w ${merchant}` : ""}`;
  else if (suggestion.category === "Delivery") prompt = `To wygląda na zamówienie jedzenia${merchant ? ` w ${merchant}` : ""}`;
  else if (suggestion.category === "Subskrypcje") prompt = `To wygląda na subskrypcję${merchant ? ` ${merchant}` : ""}`;
  return question("evidence_confirmation", `${prompt}. Zgadza się?`, [
    choice("yes", "Tak", { acceptSuggestion: true, complete: true }),
    choice("no", "Nie", { rejectSuggestion: true }),
  ], (suggestion.evidence || [])[0] || "Rozpoznanie wynika ze spójnych danych historycznych.");
}

function merchantQuestion(session) {
  const displayName = String(session.input.group?.displayName || "").trim();
  return {
    id: "merchant_resolution",
    prompt: "Jak nazywa się to miejsce?",
    explanation: displayName
      ? `Wyszukaj istniejące miejsce albo utwórz nowe. Opis z banku: „${displayName}”.`
      : "Wyszukaj istniejące miejsce albo wpisz nazwę nowego.",
    choices: [
      choice("select_merchant", "Wybierz lub utwórz miejsce", { manualField: "merchant" }),
      choice("skip", "Nie wiem — zostaw bez miejsca", { skipField: "unknown_merchant" }),
    ],
  };
}

function baseState(session) {
  const group = session.input.group || {};
  const suggestion = group.suggestion || {};
  const kind = knownKind(group);
  const reliableMerchant = suggestion.merchantId && ["exact", "strong"].includes(suggestion.confidence);
  return {
    kind,
    branch: null,
    classification: reliableMerchant ? { merchantId: Number(suggestion.merchantId) } : {},
    labels: reliableMerchant ? { merchant: suggestion.merchant || group.displayName } : {},
    path: kind ? [KIND_LABELS[kind] || kind] : [],
    assumptions: [], notes: [], stopped: false, complete: !(group.unresolvedFields || []).length,
    shortcutHandled: false, rejectedSuggestion: false, skippedFields: [],
  };
}

function receiptCategory(session, id) {
  return (session.input.productCategories || []).find((item) => String(item.id) === String(id)) || null;
}

function receiptBaseState(session) {
  const suggestion = session.input.group?.suggestion || {};
  return {
    kind: "receipt_item", branch: null, classification: {}, labels: {}, path: [], assumptions: [], notes: [],
    stopped: false, complete: false, shortcutHandled: false, rejectedSuggestion: false,
    reliableSuggestion: suggestion.confidence === "exact" && suggestion.productId ? suggestion : null,
    nameConfirmed: session.input.group?.nameConfidence !== "weak",
  };
}

function applyReceiptChoice(state, selected, session) {
  const next = structuredClone(state);
  if (selected.stop) {
    next.stopped = true; next.complete = true;
    next.assumptions.push("Pozycja pozostaje nierozpoznana zgodnie z odpowiedzią użytkownika.");
    return next;
  }
  if (selected.acceptSuggestion) {
    const suggestion = session.input.group?.suggestion || {};
    if (suggestion.productId) next.classification.productId = suggestion.productId;
    if (suggestion.productCategoryId) next.classification.productCategoryId = Number(suggestion.productCategoryId);
    next.labels.product = suggestion.productName;
    next.labels.category = suggestion.productCategory;
    next.path = [suggestion.productName, suggestion.productCategory].filter(Boolean);
    next.shortcutHandled = true; next.complete = true;
    return next;
  }
  if (selected.rejectSuggestion) {
    next.shortcutHandled = true; next.rejectedSuggestion = true; next.reliableSuggestion = null;
    return next;
  }
  if (selected.productCategoryId) {
    const category = receiptCategory(session, selected.productCategoryId);
    if (category) {
      next.classification.productCategoryId = Number(category.id);
      next.labels.category = category.parentName ? `${category.parentName} → ${category.name}` : category.name;
      next.path.push(next.labels.category);
      if (!category.parentId && fold(category.name) === fold("Żywność")) {
        next.branch = "receipt_food";
      } else {
        next.complete = true;
      }
    }
  }
  if (selected.canonicalName) next.classification.canonicalName = selected.canonicalName;
  if (selected.confirmName) next.nameConfirmed = true;
  if (selected.manualField === "product_name" && selected.manualValue) {
    next.classification.canonicalName = selected.manualValue;
    next.labels.product = selected.manualValue;
    next.nameConfirmed = true;
  }
  return next;
}

function receiptParseBaseState() {
  return {
    kind: "receipt_parse", branch: null, classification: { receiptUpdates: [] }, labels: {}, path: [],
    assumptions: [], notes: [], stopped: false, complete: false, shortcutHandled: false, rejectedSuggestion: false,
  };
}

function applyReceiptParseChoice(state, selected) {
  const next = structuredClone(state);
  if (selected.stop) { next.stopped = true; next.complete = true; return next; }
  let update = selected.receiptUpdate ? { ...selected.receiptUpdate } : null;
  if (selected.manualField && selected.manualValue) {
    update = selected.manualField === "total"
      ? { field: "total", valueMinor: Math.round(Number(String(selected.manualValue).replace(",", ".")) * 100) }
      : selected.manualField === "purchase_date" ? { field: "purchase_date", value: selected.manualValue } : null;
  }
  if (update) {
    next.classification.receiptUpdates.push(update);
    next.path.push(selected.label || update.field);
  }
  if (selected.itemDecision) {
    next.classification.receiptUpdates.push({ field: "item", ...selected.itemDecision });
    next.path.push(selected.itemDecision.accepted ? "potwierdzona pozycja" : "odrzucona pozycja");
  }
  return next;
}

function applyChoice(state, selected, session) {
  const next = structuredClone(state);
  if (selected.stop) {
    next.stopped = true;
    next.complete = true;
    next.assumptions.push("Pozostawiono nierozstrzygnięte zgodnie z odpowiedzią użytkownika.");
    return next;
  }
  if (selected.acceptSuggestion) {
    const suggestion = session.input.group?.suggestion || {};
    for (const key of ["merchantId", "categoryId", "merchantTypeId"]) {
      if (suggestion[key] != null) next.classification[key] = Number(suggestion[key]);
    }
    if (suggestion.transactionKind) next.classification.transactionKind = suggestion.transactionKind;
    next.kind = suggestion.transactionKind || next.kind;
    next.labels = {
      ...next.labels,
      merchant: suggestion.merchant || next.labels.merchant,
      category: [suggestion.parentCategory, suggestion.category].filter(Boolean).join(" → ") || next.labels.category,
      merchantType: suggestion.merchantType || next.labels.merchantType,
    };
    next.path = [KIND_LABELS[next.kind] || next.kind, next.labels.category].filter(Boolean);
    next.shortcutHandled = true;
    next.complete = true;
    return next;
  }
  if (selected.rejectSuggestion) {
    next.shortcutHandled = true;
    next.rejectedSuggestion = true;
    next.classification = next.classification.merchantId ? { merchantId: next.classification.merchantId } : {};
    next.labels = next.labels.merchant ? { merchant: next.labels.merchant } : {};
    next.branch = next.kind === "expense" ? "expense" : (["transfer", "cash"].includes(next.kind) ? next.kind : null);
    return next;
  }
  if (selected.kind) {
    next.kind = selected.kind;
    next.classification.transactionKind = selected.kind;
    next.path = [KIND_LABELS[selected.kind] || selected.kind];
  }
  if (selected.skipField && !next.skippedFields.includes(selected.skipField)) {
    next.skippedFields.push(selected.skipField);
  }
  if (selected.merchantId) {
    next.classification.merchantId = Number(selected.merchantId);
    delete next.classification.merchantName;
    next.labels.merchant = selected.merchantLabel || selected.manualValue || selected.label;
  } else if (selected.merchantName) {
    next.classification.merchantName = selected.merchantName;
    next.labels.merchant = selected.merchantName;
  }
  if (selected.path) next.path.push(selected.path);
  if (selected.category) {
    const category = findCategory(session.input.categories, selected.category);
    if (category) {
      next.classification.categoryId = Number(category.id);
      next.labels.category = category.parentName ? `${category.parentName} → ${category.name}` : category.name;
      if (!next.path.includes(next.labels.category)) next.path.push(next.labels.category);
    } else {
      next.assumptions.push(`Brakuje kanonicznej kategorii: ${(CATEGORY_TARGETS[selected.category] || []).filter(Boolean).join(" → ")}.`);
    }
  }
  if (selected.merchantType) {
    const merchantType = findMerchantType(session.input.merchantTypes, selected.merchantType);
    if (merchantType) {
      next.classification.merchantTypeId = Number(merchantType.id);
      next.labels.merchantType = merchantType.name;
    }
  }
  if (selected.note) next.notes.push(selected.note);
  next.branch = selected.branch || null;
  next.complete = Boolean(selected.complete);
  return next;
}

function replay(session) {
  const receiptItem = session.domain === "receipt_item";
  const receiptParse = session.domain === "receipt_parse";
  let state = receiptItem ? receiptBaseState(session) : receiptParse ? receiptParseBaseState(session) : baseState(session);
  for (const answer of session.answers) state = receiptItem
    ? applyReceiptChoice(state, answer.choice, session)
    : receiptParse ? applyReceiptParseChoice(state, answer.choice) : applyChoice(state, answer.choice, session);
  return state;
}

export function createGuidedReviewSession(input = {}) {
  return { domain: input.domain || "transaction", input: { ...input }, answers: [] };
}

export function getGuidedReviewState(session) {
  const state = replay(session);
  if (session.domain === "receipt_parse") {
    const unresolved = [...(session.input.receipt?.parseReview?.unresolved || [])];
    state.classification.receiptUpdates.forEach((update) => {
      const key = update.field === "purchase_date" ? "purchase_date" : update.field;
      const index = unresolved.indexOf(key);
      if (index >= 0) unresolved.splice(index, 1);
    });
    return {
      ...state, complete: unresolved.length === 0, answerCount: session.answers.length,
      unresolvedFields: unresolved, evidence: [], proposedMemoryMechanism: null,
    };
  }
  if (session.domain === "receipt_item") {
    return {
      ...state, answerCount: session.answers.length,
      unresolvedFields: state.complete && !state.stopped ? [] : ["unknown_product"],
      evidence: session.input.group?.suggestion?.evidence || [],
      proposedMemoryMechanism: state.classification.productId || state.classification.productCategoryId
        ? "retailer_product_alias" : null,
    };
  }
  const unresolved = new Set(session.input.group?.unresolvedFields || []);
  if (state.classification.merchantId || state.classification.merchantName) unresolved.delete("unknown_merchant");
  if (state.classification.categoryId) {
    unresolved.delete("missing_category");
    unresolved.delete("ambiguous_category_mapping");
  }
  if (state.classification.transactionKind || state.kind) unresolved.delete("missing_transaction_kind");
  if (state.kind && state.kind !== "expense") unresolved.delete("missing_category");
  if (!["expense", "refund", "other"].includes(state.kind)) unresolved.delete("unknown_merchant");
  return {
    ...state,
    answerCount: session.answers.length,
    unresolvedFields: [...unresolved],
    evidence: session.input.group?.suggestion?.evidence || [],
    proposedMemoryMechanism: state.classification.categoryId
      ? (state.classification.merchantId || state.classification.merchantName ? "merchant_default" : "exact_description_rule")
      : null,
  };
}

export function getNextGuidedQuestion(session) {
  const state = replay(session);
  if (state.stopped) return null;
  if (session.domain === "receipt_parse") {
    const review = session.input.receipt?.parseReview || {};
    const answered = new Set(state.classification.receiptUpdates.map((item) => item.field));
    if ((review.unresolved || []).includes("total") && !answered.has("total")) {
      return question("receipt_parse_total", "Która to suma paragonu?", [
        ...(review.totalCandidates || []).map((item, index) => choice(`total_${index}`, `${item.label} PLN`, { receiptUpdate: { field: "total", valueMinor: item.valueMinor } })),
        choice("manual_total", "Wpiszę ręcznie", { manualField: "total" }),
      ], "Nie udało mi się jednoznacznie odczytać kwoty końcowej.");
    }
    if ((review.unresolved || []).includes("purchase_date") && !answered.has("purchase_date")) {
      return question("receipt_parse_date", "Która to data zakupu?", [
        ...(review.dateCandidates || []).map((item, index) => choice(`date_${index}`, item.label, { receiptUpdate: { field: "purchase_date", value: item.value } })),
        choice("manual_date", "Wpiszę inną", { manualField: "purchase_date" }),
      ]);
    }
    const candidate = (review.itemCandidates || []).find((item) => !state.classification.receiptUpdates.some((update) => update.itemId === item.itemId));
    if (candidate) return question("receipt_parse_item", `Czy „${candidate.name}” jest produktem?`, [
      choice("yes", "Tak", { itemDecision: { itemId: candidate.itemId, accepted: true } }),
      choice("no", "Nie", { itemDecision: { itemId: candidate.itemId, accepted: false } }),
    ], candidate.priceLabel || "Potwierdź tylko wtedy, gdy linia naprawdę opisuje zakupiony produkt.");
    state.complete = true;
    return null;
  }
  if (session.domain === "receipt_item") {
    if (state.complete) return null;
    if (!state.nameConfirmed) return question("receipt_product_name", `Czy nazwa „${session.input.group?.rawName || ""}” jest poprawna?`, [
      choice("yes", "Tak", { confirmName: true }),
      choice("edit", "Poprawię nazwę", { manualField: "product_name" }),
    ], "Najpierw potwierdź nazwę produktu odczytaną z paragonu.");
    if (state.reliableSuggestion && !state.shortcutHandled) {
      return question("receipt_alias_confirmation", `To wygląda na „${state.reliableSuggestion.productName}”. Zgadza się?`, [
        choice("yes", "Tak", { acceptSuggestion: true }),
        choice("no", "Nie", { rejectSuggestion: true }),
      ], "Rozpoznanie pochodzi z potwierdzonego aliasu tego sprzedawcy.");
    }
    const categories = session.input.productCategories || [];
    if (state.branch === "receipt_food") {
      const food = categories.find((item) => !item.parentId && fold(item.name) === fold("Żywność"));
      const children = categories.filter((item) => String(item.parentId) === String(food?.id));
      if (children.length) {
        return question("receipt_food_type", "Jaki to rodzaj żywności?", children.map((item) => (
          choice(`category_${item.id}`, item.name, { productCategoryId: item.id })
        )));
      }
      state.complete = true;
      return null;
    }
    const roots = categories.filter((item) => !item.parentId);
    return question("receipt_item_type", "Co to było?", roots.map((item) => (
      choice(`category_${item.id}`, item.name === "Żywność" ? "Jedzenie" : item.name, { productCategoryId: item.id })
    )), "Klasyfikujesz produkt z paragonu, nie całą transakcję bankową.");
  }
  if (!state.shortcutHandled) {
    const shortcut = shortcutQuestion(session.input.group);
    if (shortcut) return shortcut;
  }
  if (state.branch && QUESTIONS[state.branch]) return QUESTIONS[state.branch]();
  const originalUnresolved = new Set(session.input.group?.unresolvedFields || []);
  if (originalUnresolved.has("missing_transaction_kind") && !state.classification.transactionKind
      && ["transfer", "cash"].includes(state.kind)) return QUESTIONS[state.kind]();
  const unresolved = new Set(getGuidedReviewState(session).unresolvedFields);
  if (!unresolved.size) return null;
  if (!state.kind && unresolved.has("missing_transaction_kind")) return QUESTIONS.root();
  if (!state.kind) return QUESTIONS.root();
  if (state.kind === "other" && (session.input.group?.unresolvedFields || []).includes("ambiguous_category_mapping")) return QUESTIONS.root();
  const needsCategory = unresolved.has("missing_category") || unresolved.has("ambiguous_category_mapping");
  if (needsCategory && state.kind === "expense" && !state.classification.categoryId && !state.branch) state.branch = "expense";
  if (needsCategory && state.kind === "expense" && !state.classification.categoryId) return QUESTIONS.expense();
  if (unresolved.has("unknown_merchant") && !state.skippedFields.includes("unknown_merchant")) return merchantQuestion(session);
  return null;
}

export function answerGuidedQuestion(session, questionId, choiceId, extra = {}) {
  const current = getNextGuidedQuestion(session);
  if (!current || current.id !== questionId) throw new Error("Ta odpowiedź nie pasuje do bieżącego pytania.");
  const selected = current.choices.find((item) => item.id === choiceId);
  if (!selected) throw new Error("Nieznana odpowiedź przewodnika.");
  const applied = { ...selected, ...extra };
  return { ...session, answers: [...session.answers, { questionId, choiceId, label: selected.label, choice: applied }] };
}

export function backGuidedReview(session) {
  return { ...session, answers: session.answers.slice(0, -1) };
}

export function restartGuidedReview(session) {
  return { ...session, answers: [] };
}

export function guidedReviewResult(session) {
  const state = getGuidedReviewState(session);
  return {
    classification: { ...state.classification }, labels: { ...state.labels },
    semanticKind: state.kind, path: [...state.path], answerCount: state.answerCount,
    unresolvedFields: [...state.unresolvedFields], evidence: [...state.evidence],
    assumptions: [...state.assumptions], notes: [...state.notes], stopped: state.stopped,
    proposedMemoryMechanism: state.proposedMemoryMechanism, domain: session.domain,
  };
}

export const GUIDED_CATEGORY_TARGETS = CATEGORY_TARGETS;
