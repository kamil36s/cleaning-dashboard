export const BUDGET_CSV_HEADERS = Object.freeze({
  date: "#Data operacji",
  description: "#Opis operacji",
  account: "#Rachunek",
  category: "#Kategoria",
  amount: "#Kwota",
  balanceAfter: "#Saldo po operacji",
});

export const DEFAULT_BUDGET_DATA = Object.freeze({
  source: {
    name: "",
    importedAt: "",
    rows: 0,
  },
  settings: {
    savingsCategories: ["regularne oszczędzanie", "oszczędzanie"],
    ignoredCategories: [],
    userCategories: [
      "Jedzenie",
      "Zakupy spozywcze",
      "Chemia i dom",
      "Kawa i slodycze",
      "Restauracje",
      "Bary",
      "Delivery",
      "Transport",
      "Taxi",
      "Komunikacja miejska",
      "Rachunki",
      "Mieszkanie",
      "Subskrypcje",
      "Telefon i internet",
      "Zdrowie",
      "Apteka",
      "Ubrania",
      "Elektronika",
      "Kosmetyki",
      "Rozrywka",
      "Kultura",
      "Sport",
      "Podróże",
      "Prezenty",
      "Oszczędności",
      "Przelewy",
      "Gotówka",
      "Praca",
      "Inne",
    ],
    merchantTypes: [
      "Sklep spozywczy",
      "Sklep convenience",
      "Dyskont",
      "Drogeria",
      "Apteka",
      "Restauracja",
      "Bar",
      "Kawiarnia",
      "Piekarnia",
      "Delivery",
      "Taxi",
      "Transport publiczny",
      "Paliwo",
      "Parking",
      "Subskrypcja",
      "Marketplace",
      "Sklep internetowy",
      "Usluga",
      "Przelew",
      "Bankomat",
      "Bank",
      "Urzad",
      "Przychodnia",
      "Silownia",
      "Kino",
      "Hotel",
      "Loty",
      "Inne",
    ],
    rejectedSuggestionKeys: [],
  },
  transactions: [],
});

const MERCHANT_STOP_PATTERNS = [
  /\bzakup\s+przy\s+u[żz]yciu\s+karty\b.*$/i,
  /\bplatnosc\s+karta\b.*$/i,
  /\bp[łl]atno[śs][ćc]\s+kart[ąa]\b.*$/i,
  /\btransakcja\s+karta\b.*$/i,
  /\btransakcja\s+kart[ąa]\b.*$/i,
  /\bkarta\s+w\s+kraju\b.*$/i,
  /\bw\s+kraju\b.*$/i,
  /\bterminal\b.*$/i,
];

const MERCHANT_TYPE_HINTS = [
  { pattern: /\b(zabka|biedronka|lidl|aldi|auchan|carrefour|kaufland|netto|stokrotka|dino)\b/, type: "Sklep" },
  { pattern: /\b(rossmann|hebe|drogeria)\b/, type: "Sklep" },
  { pattern: /\b(apteka|pharmacy)\b/, type: "Apteka" },
  { pattern: /\b(uber|bolt|taxi|jakdojade|mpk|ztm|koleje|intercity)\b/, type: "Transport" },
  { pattern: /\b(spotify|netflix|hbo|disney|youtube|apple\.com|google)\b/, type: "Subskrypcja" },
  { pattern: /\b(bar|pub|cafe|coffee|kawiarnia)\b/, type: "Bar" },
  { pattern: /\b(restauracja|restaurant|pizza|kebab|mcdonald|burger)\b/, type: "Restauracja" },
  { pattern: /\b(bankomat|atm)\b/, type: "Bankomat" },
];

function stripDiacritics(value) {
  return String(value || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "");
}

export function normalizeBudgetText(value) {
  return stripDiacritics(value)
    .trim()
    .toLocaleLowerCase("pl-PL")
    .replace(/\s+/g, " ");
}

function titleCaseMerchant(value) {
  const raw = String(value || "").trim().replace(/\s+/g, " ");
  if (!raw) return "";
  if (raw.length <= 4 && raw === raw.toUpperCase()) return raw;
  return raw
    .toLocaleLowerCase("pl-PL")
    .replace(/(^|\s|-)([a-ząćęłńóśźż])/gi, (match, prefix, letter) =>
      `${prefix}${letter.toLocaleUpperCase("pl-PL")}`);
}

export function extractBudgetMerchantCandidate(description) {
  let text = String(description || "")
    .replace(/\s+/g, " ")
    .trim();

  MERCHANT_STOP_PATTERNS.forEach((pattern) => {
    text = text.replace(pattern, "");
  });

  text = text
    .replace(/\b\d{2}[./-]\d{2}[./-]\d{2,4}\b/g, " ")
    .replace(/\b\d{1,2}:\d{2}(:\d{2})?\b/g, " ")
    .replace(/\b\d{4,}\b/g, " ")
    .replace(/\s{2,}/g, " ")
    .replace(/[-,;:.]+$/g, "")
    .trim();

  if (!text) return "";
  const words = text.split(" ").filter(Boolean);
  if (words.length > 4) {
    return titleCaseMerchant(words.slice(0, 4).join(" "));
  }
  return titleCaseMerchant(text);
}

function inferMerchantType(merchant) {
  const normalized = normalizeBudgetText(merchant);
  return MERCHANT_TYPE_HINTS.find((hint) => hint.pattern.test(normalized))?.type || "";
}

export function parseBudgetMoney(value) {
  if (typeof value === "number") return Number.isFinite(value) ? value : 0;

  const raw = String(value ?? "").trim();
  if (!raw) return 0;

  const withoutCurrency = raw
    .replace(/\bPLN\b/gi, "")
    .replace(/\s+/g, "")
    .replace(/\u00a0/g, "");

  const normalized = withoutCurrency.includes(",")
    ? withoutCurrency.replace(/\./g, "").replace(",", ".")
    : withoutCurrency.replace(/,/g, "");

  const parsed = Number(normalized);
  return Number.isFinite(parsed) ? parsed : 0;
}

export function parseBudgetDate(value) {
  const raw = String(value || "").trim();
  const pl = raw.match(/^(\d{1,2})\.(\d{1,2})\.(\d{4})$/);
  if (pl) {
    return `${pl[3]}-${pl[2].padStart(2, "0")}-${pl[1].padStart(2, "0")}`;
  }

  const iso = raw.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
  if (iso) {
    return `${iso[1]}-${iso[2].padStart(2, "0")}-${iso[3].padStart(2, "0")}`;
  }

  return "";
}

export function formatBudgetDate(value) {
  const iso = parseBudgetDate(value);
  if (!iso) return "";
  const [year, month, day] = iso.split("-").map(Number);
  const date = new Date(year, month - 1, day);
  if (!Number.isFinite(date.getTime())) return "";
  return date.toLocaleDateString("pl-PL", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
}

export function formatBudgetMoney(value, options = {}) {
  const amount = Number(value);
  const currency = options.currency || "zł";
  const formatted = (Number.isFinite(amount) ? amount : 0).toLocaleString("pl-PL", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return `${formatted} ${currency}`;
}

function normalizeTransaction(transaction, index = 0) {
  const amount = parseBudgetMoney(transaction?.amount);
  const balanceAfter = transaction?.balanceAfter == null || transaction.balanceAfter === ""
    ? null
    : parseBudgetMoney(transaction.balanceAfter);
  const date = parseBudgetDate(transaction?.date);

  const normalized = {
    id: String(transaction?.id || ""),
    date,
    description: String(transaction?.description || "").trim(),
    account: String(transaction?.account || "").trim(),
    accountDisplay: String(transaction?.accountDisplay || "").trim(),
    category: String(transaction?.category || "").trim(),
    userCategory: String(transaction?.userCategory || "").trim(),
    merchant: String(transaction?.merchant || "").trim(),
    merchantId: transaction?.merchantId ?? null,
    merchantType: String(transaction?.merchantType || "").trim(),
    merchantTypeId: transaction?.merchantTypeId ?? null,
    categoryId: transaction?.categoryId ?? null,
    parentCategory: String(transaction?.parentCategory || "").trim(),
    transactionKind: String(transaction?.transactionKind || (amount < 0 ? "expense" : "other")),
    classification: transaction?.classification && typeof transaction.classification === "object"
      ? { ...transaction.classification }
      : {},
    note: String(transaction?.note || "").trim(),
    amount,
    balanceAfter,
    currency: String(transaction?.currency || "PLN").trim() || "PLN",
  };
  normalized.id = normalized.id || `legacy-row-${index}`;
  return normalized;
}

function normalizeTextList(value) {
  const list = Array.isArray(value) ? value : String(value || "").split(/[,\n;]/);
  const seen = new Set();
  const result = [];

  list.forEach((entry) => {
    const text = normalizeBudgetText(entry);
    if (!text || seen.has(text)) return;
    seen.add(text);
    result.push(text);
  });

  return result;
}

export function normalizeBudgetData(payload = {}) {
  const source = payload?.source && typeof payload.source === "object" ? payload.source : {};
  const settings = payload?.settings && typeof payload.settings === "object" ? payload.settings : {};
  const normalizedTransactions = (Array.isArray(payload?.transactions) ? payload.transactions : [])
    .map(normalizeTransaction)
    .filter((transaction) => transaction.date || transaction.description || transaction.amount !== 0);
  const transactions = normalizedTransactions
    .sort((a, b) => {
      if (a.date !== b.date) return a.date < b.date ? 1 : -1;
      return Math.abs(b.amount) - Math.abs(a.amount);
    });

  return {
    source: {
      name: String(source.name || "").trim(),
      importedAt: String(source.importedAt || "").trim(),
      rows: transactions.length,
    },
    settings: {
      savingsCategories: normalizeTextList(
        settings.savingsCategories ?? DEFAULT_BUDGET_DATA.settings.savingsCategories,
      ),
      ignoredCategories: normalizeTextList(
        settings.ignoredCategories ?? DEFAULT_BUDGET_DATA.settings.ignoredCategories,
      ),
      userCategories: normalizeLabelList(
        settings.userCategories ?? DEFAULT_BUDGET_DATA.settings.userCategories,
      ),
      merchantTypes: normalizeLabelList(
        settings.merchantTypes ?? DEFAULT_BUDGET_DATA.settings.merchantTypes,
      ),
      rejectedSuggestionKeys: normalizeLabelList(
        settings.rejectedSuggestionKeys ?? DEFAULT_BUDGET_DATA.settings.rejectedSuggestionKeys,
      ),
    },
    transactions,
  };
}

function normalizeLabelList(value) {
  const list = Array.isArray(value) ? value : String(value || "").split(/[,\n;]/);
  const seen = new Set();
  const result = [];

  list.forEach((entry) => {
    const label = String(entry || "").trim();
    const key = normalizeBudgetText(label);
    if (!key || seen.has(key)) return;
    seen.add(key);
    result.push(label);
  });

  return result;
}

export function getBudgetTransactionCategory(transaction) {
  return String(transaction?.userCategory || transaction?.category || "Bez kategorii").trim() || "Bez kategorii";
}

export function getBudgetTransactionPlace(transaction) {
  return String(transaction?.merchant || transaction?.description || "").trim();
}

export function updateBudgetTransaction(data, transactionId, updates = {}) {
  const normalized = normalizeBudgetData(data);
  return normalizeBudgetData({
    ...normalized,
    transactions: normalized.transactions.map((transaction) =>
      transaction.id === transactionId
        ? {
          ...transaction,
          userCategory: updates.userCategory ?? transaction.userCategory,
          merchant: updates.merchant ?? transaction.merchant,
          merchantType: updates.merchantType ?? transaction.merchantType,
          note: updates.note ?? transaction.note,
        }
        : transaction),
  });
}

function createLearningMaps(transactions) {
  const byDescription = new Map();
  const byMerchantCandidate = new Map();

  transactions.forEach((transaction) => {
    if (!transaction.merchant && !transaction.userCategory && !transaction.merchantType) return;
    const learned = {
      merchant: transaction.merchant,
      userCategory: transaction.userCategory,
      merchantType: transaction.merchantType,
    };
    const descriptionKey = normalizeBudgetText(transaction.description);
    const candidateKey = normalizeBudgetText(extractBudgetMerchantCandidate(transaction.description));

    if (descriptionKey) byDescription.set(descriptionKey, learned);
    if (candidateKey) byMerchantCandidate.set(candidateKey, learned);
  });

  return { byDescription, byMerchantCandidate };
}

function groupTransactionsForSuggestions(transactions, learningMaps) {
  const groups = new Map();

  transactions.forEach((transaction) => {
    const candidate = transaction.merchant || extractBudgetMerchantCandidate(transaction.description);
    const candidateKey = normalizeBudgetText(candidate);
    if (!candidateKey) return;

    const descriptionKey = normalizeBudgetText(transaction.description);
    const learned = learningMaps.byDescription.get(descriptionKey)
      || learningMaps.byMerchantCandidate.get(candidateKey)
      || null;

    const key = learned?.merchant
      ? `learned:${normalizeBudgetText(learned.merchant)}`
      : `candidate:${candidateKey}`;

    if (!groups.has(key)) {
      groups.set(key, {
        key,
        rawCandidate: candidate,
        learned,
        transactions: [],
      });
    }

    groups.get(key).transactions.push(transaction);
  });

  return groups;
}

export function buildBudgetRuleSuggestions(input = DEFAULT_BUDGET_DATA, options = {}) {
  const data = normalizeBudgetData(input);
  const minCount = Math.max(2, Number(options.minCount || 2));
  const rejectedKeys = new Set(data.settings.rejectedSuggestionKeys);
  const learningMaps = createLearningMaps(data.transactions);
  const groups = groupTransactionsForSuggestions(data.transactions, learningMaps);

  return Array.from(groups.values())
    .map((group) => {
      const learned = group.learned || {};
      const merchant = learned.merchant || group.rawCandidate;
      const userCategory = learned.userCategory || "";
      const merchantType = learned.merchantType || inferMerchantType(merchant);
      const transactionIds = group.transactions
        .filter((transaction) =>
          (merchant && !transaction.merchant)
          || (userCategory && !transaction.userCategory)
          || (merchantType && !transaction.merchantType))
        .map((transaction) => transaction.id);
      const transactionSummaries = group.transactions.map((transaction) => ({
        id: transaction.id,
        date: transaction.date,
        description: transaction.description,
        category: transaction.category,
        userCategory: transaction.userCategory,
        merchant: transaction.merchant,
        merchantType: transaction.merchantType,
        amount: transaction.amount,
        canApply: transactionIds.includes(transaction.id),
      }));

      return {
        key: group.key,
        merchant,
        userCategory,
        merchantType,
        count: group.transactions.length,
        applyCount: transactionIds.length,
        transactionIds,
        transactions: transactionSummaries,
        sampleDescriptions: Array.from(new Set(group.transactions.map((transaction) => transaction.description).filter(Boolean))).slice(0, 3),
        source: group.learned ? "learned" : "repeat",
      };
    })
    .filter((suggestion) =>
      !rejectedKeys.has(suggestion.key)
      && suggestion.applyCount > 0
      && (suggestion.count >= minCount || suggestion.source === "learned")
      && (suggestion.merchant || suggestion.userCategory || suggestion.merchantType))
    .sort((a, b) =>
      (b.applyCount - a.applyCount)
      || (b.count - a.count)
      || a.merchant.localeCompare(b.merchant, "pl"));
}

export function applyBudgetRuleSuggestions(input = DEFAULT_BUDGET_DATA, suggestions = []) {
  const data = normalizeBudgetData(input);
  const selected = Array.isArray(suggestions) ? suggestions.filter((suggestion) => suggestion?.selected !== false) : [];
  const updatesById = new Map();

  selected.forEach((suggestion) => {
    (Array.isArray(suggestion.transactionIds) ? suggestion.transactionIds : []).forEach((id) => {
      if (!id) return;
      const current = updatesById.get(id) || {};
      updatesById.set(id, {
        merchant: current.merchant ?? suggestion.merchant ?? "",
        userCategory: current.userCategory ?? suggestion.userCategory ?? "",
        merchantType: current.merchantType ?? suggestion.merchantType ?? "",
      });
    });
  });

  return normalizeBudgetData({
    ...data,
    settings: {
      ...data.settings,
      userCategories: [
        ...data.settings.userCategories,
        ...selected.map((suggestion) => suggestion.userCategory).filter(Boolean),
      ],
      merchantTypes: [
        ...data.settings.merchantTypes,
        ...selected.map((suggestion) => suggestion.merchantType).filter(Boolean),
      ],
    },
    transactions: data.transactions.map((transaction) => {
      const update = updatesById.get(transaction.id);
      if (!update) return transaction;
      return {
        ...transaction,
        merchant: transaction.merchant || update.merchant || "",
        userCategory: transaction.userCategory || update.userCategory || "",
        merchantType: transaction.merchantType || update.merchantType || "",
      };
    }),
  });
}

function categoryMatches(category, patterns) {
  const normalized = normalizeBudgetText(category);
  return patterns.some((pattern) => normalized.includes(pattern));
}

function getLatestBalance(transactions) {
  return transactions.find((transaction) => transaction.balanceAfter != null)?.balanceAfter ?? null;
}

function getDateRange(transactions) {
  const dates = transactions.map((transaction) => transaction.date).filter(Boolean).sort();
  if (!dates.length) return { from: "", to: "" };
  return { from: dates[0], to: dates[dates.length - 1] };
}

function getBudgetMonthKey(value) {
  const iso = parseBudgetDate(value);
  return iso ? iso.slice(0, 7) : "";
}

function getBudgetDayOfMonth(value) {
  const iso = parseBudgetDate(value);
  return iso ? Number(iso.slice(8, 10)) : 0;
}

function getReferenceMonthKey(referenceDate = new Date()) {
  if (referenceDate instanceof Date && Number.isFinite(referenceDate.getTime())) {
    return `${referenceDate.getFullYear()}-${String(referenceDate.getMonth() + 1).padStart(2, "0")}`;
  }

  const parsed = parseBudgetDate(referenceDate);
  if (parsed) return parsed.slice(0, 7);

  const date = new Date(referenceDate);
  if (Number.isFinite(date.getTime())) {
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
  }

  return getReferenceMonthKey(new Date());
}

function shiftBudgetMonthKey(monthKey, offset) {
  const match = String(monthKey || "").match(/^(\d{4})-(\d{2})$/);
  if (!match) return "";

  const date = new Date(Number(match[1]), Number(match[2]) - 1 + offset, 1);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}

function filterCategoryTransactions(transactions, options = {}) {
  if (options.categoryPeriod !== "current-month") return transactions;

  const currentMonth = getReferenceMonthKey(options.referenceDate);
  return transactions.filter((transaction) => getBudgetMonthKey(transaction.date) === currentMonth);
}

function getCategoryNameForSummary(transaction, options = {}) {
  if (options.categorySource === "user") {
    return String(transaction?.userCategory || "").trim();
  }

  return getBudgetTransactionCategory(transaction);
}

function isCategoryExpense(transaction, settings, options = {}) {
  if (transaction.amount >= 0) return false;

  const categoryName = getCategoryNameForSummary(transaction, options);
  if (!categoryName) return false;
  if (categoryMatches(categoryName, settings.ignoredCategories)) return false;
  if (categoryMatches(categoryName, settings.savingsCategories)) return false;

  return true;
}

function summarizeCategories(transactions, settings, options = {}) {
  const totals = new Map();

  transactions.forEach((transaction) => {
    if (!isCategoryExpense(transaction, settings, options)) return;

    const name = getCategoryNameForSummary(transaction, options);
    totals.set(name, (totals.get(name) || 0) + Math.abs(transaction.amount));
  });

  return Array.from(totals.entries())
    .map(([name, amount]) => ({ name, amount }))
    .sort((a, b) => b.amount - a.amount)
    .slice(0, 6);
}

function sumCategorySpending(transactions, settings, options = {}) {
  return transactions
    .filter((transaction) => isCategoryExpense(transaction, settings, options))
    .reduce((sum, transaction) => sum + Math.abs(transaction.amount), 0);
}

function pickSalaryTransaction(transactions) {
  return transactions
    .filter((transaction) => transaction.transactionKind === "salary" && transaction.amount > 0)
    .sort((a, b) => (b.amount - a.amount) || String(b.date).localeCompare(String(a.date)))[0] || null;
}

function summarizeCurrentMonth(transactions, settings, options = {}) {
  const currentMonth = getReferenceMonthKey(options.referenceDate);
  const previousMonth = shiftBudgetMonthKey(currentMonth, -1);
  const salaryStartDay = Math.max(1, Math.min(31, Number(options.salaryStartDay || 20)));
  const ignored = (transaction) => categoryMatches(getBudgetTransactionCategory(transaction), settings.ignoredCategories);
  const savings = (transaction) =>
    transaction.amount < 0 && categoryMatches(getBudgetTransactionCategory(transaction), settings.savingsCategories);
  const currentMonthTransactions = transactions.filter((transaction) =>
    getBudgetMonthKey(transaction.date) === currentMonth && !ignored(transaction));
  const previousMonthIncomeTransactions = transactions.filter((transaction) =>
    getBudgetMonthKey(transaction.date) === previousMonth
    && transaction.amount > 0
    && !ignored(transaction));
  const latePreviousMonthIncomeTransactions = previousMonthIncomeTransactions.filter((transaction) =>
    getBudgetDayOfMonth(transaction.date) >= salaryStartDay);
  const salaryTransaction = pickSalaryTransaction(latePreviousMonthIncomeTransactions)
    || pickSalaryTransaction(previousMonthIncomeTransactions);
  const spendingTransactions = currentMonthTransactions.filter((transaction) =>
    transaction.amount < 0 && !savings(transaction));
  const savingsTransactions = currentMonthTransactions.filter(savings);
  const totalSpending = spendingTransactions.reduce((sum, transaction) => sum + Math.abs(transaction.amount), 0);
  const totalSavings = savingsTransactions.reduce((sum, transaction) => sum + Math.abs(transaction.amount), 0);
  const salaryAmount = salaryTransaction?.amount || 0;

  return {
    month: currentMonth,
    salaryMonth: previousMonth,
    totalSpending,
    totalSavings,
    salaryAmount,
    salaryDate: salaryTransaction?.date || "",
    salaryDescription: salaryTransaction?.description || "",
    salarySpentPercent: salaryAmount > 0 ? (totalSpending / salaryAmount) * 100 : null,
  };
}

export function summarizeBudgetData(input = DEFAULT_BUDGET_DATA, options = {}) {
  const data = normalizeBudgetData(input);
  const { transactions, settings } = data;
  const ignored = (transaction) => categoryMatches(getBudgetTransactionCategory(transaction), settings.ignoredCategories);
  const savings = (transaction) => transaction.amount < 0 && categoryMatches(getBudgetTransactionCategory(transaction), settings.savingsCategories);
  const categoryTransactions = filterCategoryTransactions(transactions, options);

  const spendingTransactions = transactions.filter((transaction) =>
    transaction.amount < 0 && !ignored(transaction) && !savings(transaction));
  const incomeTransactions = transactions.filter((transaction) =>
    transaction.amount > 0 && !ignored(transaction));
  const savingsTransactions = transactions.filter(savings);

  const totalSpending = spendingTransactions.reduce((sum, transaction) => sum + Math.abs(transaction.amount), 0);
  const totalIncome = incomeTransactions.reduce((sum, transaction) => sum + transaction.amount, 0);
  const totalSavings = savingsTransactions.reduce((sum, transaction) => sum + Math.abs(transaction.amount), 0);
  const net = transactions
    .filter((transaction) => !ignored(transaction))
    .reduce((sum, transaction) => sum + transaction.amount, 0);
  const range = getDateRange(transactions);

  return {
    source: data.source,
    rows: transactions.length,
    range,
    latestBalance: getLatestBalance(transactions),
    totalSpending,
    totalIncome,
    totalSavings,
    net,
    transactionCount: transactions.length,
    spendingCount: spendingTransactions.length,
    incomeCount: incomeTransactions.length,
    savingsCount: savingsTransactions.length,
    currentMonth: summarizeCurrentMonth(transactions, settings, options),
    categories: summarizeCategories(categoryTransactions, settings, options),
    categoryTotalSpending: sumCategorySpending(categoryTransactions, settings, options),
    recentTransactions: transactions.slice(0, 8),
  };
}
