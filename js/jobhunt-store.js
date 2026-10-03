export const JOBHUNT_OFFERS_STORAGE_KEY = "dashboard.jobhunt.offers";
export const JOBHUNT_MATCH_SETTINGS_STORAGE_KEY = "dashboard.jobhunt.matchSettings";
export const JOBHUNT_CHANGED_EVENT = "jobhunt:changed";

export const JOBHUNT_STATUSES = [
  "new",
  "to_review",
  "worth_applying",
  "applied",
  "follow_up",
  "interview",
  "offer",
  "expired",
  "rejected",
  "archived",
];

export const JOBHUNT_PRIORITIES = ["P1", "P2", "P3", "skip", "unknown"];

export const JOBHUNT_NEXT_ACTIONS = [
  "analyze",
  "tailor_cv",
  "apply",
  "follow_up",
  "prepare_interview",
  "ask_recruiter",
  "archive",
  "none",
];

export const JOBHUNT_MATCH_SETTINGS_DEFAULTS = [
  { id: "manual_qa", label: "Manual QA", weight: 10 },
  { id: "uat_iat", label: "UAT/IAT", weight: 10 },
  { id: "test_scenarios", label: "Test scenarios/test cases", weight: 10 },
  { id: "defect_management", label: "Defect management", weight: 10 },
  { id: "stakeholder_coordination", label: "Client/stakeholder coordination", weight: 10 },
  { id: "jira_alm_testrail", label: "Jira/ALM/TestRail", weight: 10 },
  { id: "api_testing", label: "API testing", weight: 8 },
  { id: "automation_path", label: "Automation as development path", weight: 7 },
  { id: "krakow_remote_hybrid", label: "Krakow/remote/hybrid fit", weight: 8 },
  { id: "uop", label: "UoP", weight: 7 },
];

const STATUS_SET = new Set(JOBHUNT_STATUSES);
const PRIORITY_SET = new Set(JOBHUNT_PRIORITIES);
const NEXT_ACTION_SET = new Set(JOBHUNT_NEXT_ACTIONS);
const ARCHIVED_STATUSES = new Set(["archived"]);
const TERMINAL_STATUSES = new Set(["rejected", "archived", "offer"]);
const CLOSED_STATUSES = new Set(["rejected", "archived", "offer", "expired"]);
const APPLIED_STATUSES = new Set(["applied", "follow_up", "interview", "offer", "expired", "rejected", "archived"]);
const PRIORITY_ORDER = new Map([
  ["P1", 0],
  ["P2", 1],
  ["P3", 2],
  ["unknown", 3],
  ["skip", 4],
]);

function canUseStorage() {
  return typeof globalThis !== "undefined" && !!globalThis.localStorage;
}

function emitChanged() {
  if (typeof window === "undefined" || typeof window.dispatchEvent !== "function") return;
  window.dispatchEvent(new CustomEvent(JOBHUNT_CHANGED_EVENT));
}

function readJson(key, fallback) {
  if (!canUseStorage()) return fallback;
  try {
    const raw = globalThis.localStorage.getItem(key);
    if (!raw) return fallback;
    return JSON.parse(raw);
  } catch {
    return fallback;
  }
}

function writeJson(key, value) {
  if (!canUseStorage()) return;
  try {
    globalThis.localStorage.setItem(key, JSON.stringify(value));
  } catch {}
}

function asString(value, fallback = "") {
  const text = String(value ?? "").trim();
  return text || fallback;
}

function asArray(value) {
  if (!Array.isArray(value)) return [];
  return value.map((item) => asString(item)).filter(Boolean);
}

function toNumberOrNull(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function clampScore(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return null;
  return Math.max(0, Math.min(100, Math.round(number)));
}

function isoNow(now = new Date()) {
  const date = now instanceof Date ? now : new Date(now);
  return Number.isNaN(date.getTime()) ? new Date().toISOString() : date.toISOString();
}

function todayInputValue(now = new Date()) {
  const date = now instanceof Date ? now : new Date(now);
  const safeDate = Number.isNaN(date.getTime()) ? new Date() : date;
  const month = String(safeDate.getMonth() + 1).padStart(2, "0");
  const day = String(safeDate.getDate()).padStart(2, "0");
  return `${safeDate.getFullYear()}-${month}-${day}`;
}

function normalizeDateInput(value) {
  const text = asString(value);
  if (!text) return null;
  const match = text.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return null;
  const date = new Date(`${text}T12:00:00`);
  if (Number.isNaN(date.getTime())) return null;
  return todayInputValue(date) === text ? text : null;
}

export function getDaysUntilExpiration(offer, now = new Date()) {
  const expiresAt = normalizeDateInput(offer?.expiresAt);
  if (!expiresAt) return null;
  const today = new Date(`${todayInputValue(now)}T12:00:00`);
  const expiry = new Date(`${expiresAt}T12:00:00`);
  return Math.round((expiry.getTime() - today.getTime()) / 86400000);
}

export function getExpirationTone(offer, now = new Date()) {
  if (offer?.status === "expired") return "expired";
  const days = getDaysUntilExpiration(offer, now);
  if (days === null) return "none";
  if (days < 0) return "expired";
  if (days <= 3) return "urgent";
  if (days <= 7) return "soon";
  return "ok";
}

export function formatExpirationLabel(offer, now = new Date()) {
  const expiresAt = normalizeDateInput(offer?.expiresAt);
  const days = getDaysUntilExpiration(offer, now);
  if (offer?.status === "expired" && (!expiresAt || days === null || days >= 0)) return "Expired";
  if (!expiresAt || days === null) return "No expiration";
  if (days < 0) return `Expired ${Math.abs(days)}d ago`;
  if (days === 0) return "Expires today";
  if (days === 1) return "Expires tomorrow";
  return `${days}d left`;
}

function shouldExpireStatus(status, expiresAt, now = new Date()) {
  if (!expiresAt || TERMINAL_STATUSES.has(status)) return false;
  return getDaysUntilExpiration({ expiresAt }, now) < 0;
}

export function addDaysToDateInput(day, amount) {
  const date = new Date(`${day || todayInputValue()}T12:00:00`);
  if (Number.isNaN(date.getTime())) return todayInputValue();
  date.setDate(date.getDate() + amount);
  return todayInputValue(date);
}

function createOfferId(offer, now = new Date()) {
  const company = asString(offer?.company, "company").toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");
  const role = asString(offer?.role, "role").toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");
  const stamp = todayInputValue(now).replace(/-/g, "");
  return `job_${stamp}_${company || "company"}_${role || "role"}_${Math.random().toString(36).slice(2, 7)}`;
}

export function getMatchCategory(score) {
  const value = clampScore(score);
  if (value === null) return "unknown";
  if (value >= 80) return "strong_fit";
  if (value >= 65) return "good_fit";
  if (value >= 50) return "stretch";
  return "low_fit";
}

export function getMatchTone(score) {
  const value = clampScore(score);
  if (value === null) return "unknown";
  if (value >= 80) return "strong";
  if (value >= 65) return "good";
  if (value >= 50) return "medium";
  return "low";
}

export function normalizeJobOffer(input = {}, options = {}) {
  const now = options.now || new Date();
  const score = clampScore(input?.match?.score);
  const inputStatus = STATUS_SET.has(input.status) ? input.status : "to_review";
  const expiresAt = normalizeDateInput(input.expiresAt);
  const status = shouldExpireStatus(inputStatus, expiresAt, now) ? "expired" : inputStatus;
  const priority = PRIORITY_SET.has(input.priority) ? input.priority : "unknown";
  const nextAction = NEXT_ACTION_SET.has(input.nextAction) ? input.nextAction : "analyze";
  const createdAt = asString(input.createdAt, isoNow(now));
  const updatedAt = asString(input.updatedAt, isoNow(now));

  return {
    id: asString(input.id, createOfferId(input, now)),
    company: asString(input.company, "unknown"),
    role: asString(input.role, "unknown"),
    seniority: asString(input.seniority, "unknown"),
    location: {
      city: asString(input.location?.city, "unknown"),
      country: asString(input.location?.country, "unknown"),
      workMode: asString(input.location?.workMode, "unknown"),
      hybridDetails: asString(input.location?.hybridDetails, "unknown"),
    },
    contract: {
      type: asString(input.contract?.type, "unknown"),
      details: asString(input.contract?.details, "unknown"),
    },
    salary: {
      min: toNumberOrNull(input.salary?.min),
      max: toNumberOrNull(input.salary?.max),
      currency: asString(input.salary?.currency, "unknown"),
      period: asString(input.salary?.period, "unknown"),
      taxType: asString(input.salary?.taxType, "unknown"),
      isKnown: Boolean(input.salary?.isKnown ?? (input.salary?.min || input.salary?.max)),
    },
    source: {
      name: asString(input.source?.name, "unknown"),
      url: asString(input.source?.url, ""),
      capturedAt: asString(input.source?.capturedAt, isoNow(now)),
    },
    branding: {
      logoDataUrl: asString(input.branding?.logoDataUrl || input.companyLogoDataUrl),
    },
    expiresAt,
    status,
    priority,
    nextAction,
    match: {
      score: score ?? 0,
      category: asString(input.match?.category, getMatchCategory(score)),
      summary: asString(input.match?.summary, "No match summary yet."),
      isExperimental: input.match?.isExperimental !== false,
    },
    requirements: {
      mustHave: asArray(input.requirements?.mustHave),
      niceToHave: asArray(input.requirements?.niceToHave),
      tools: asArray(input.requirements?.tools),
    },
    analysis: {
      greenFlags: asArray(input.analysis?.greenFlags),
      redFlags: asArray(input.analysis?.redFlags),
      skillGaps: asArray(input.analysis?.skillGaps),
      fitReasons: asArray(input.analysis?.fitReasons),
    },
    cv: {
      recommendedVersion: asString(input.cv?.recommendedVersion, "unknown"),
      bulletsToEmphasize: asArray(input.cv?.bulletsToEmphasize),
    },
    application: {
      dateApplied: asString(input.application?.dateApplied) || null,
      followUpDate: asString(input.application?.followUpDate) || null,
      recruiterName: asString(input.application?.recruiterName) || null,
      recruiterContact: asString(input.application?.recruiterContact) || null,
    },
    notes: asString(input.notes),
    originalText: asString(input.originalText),
    createdAt,
    updatedAt,
  };
}

function validateOneOffer(input, index) {
  const prefix = index === null ? "Offer" : `Offer ${index + 1}`;
  const errors = [];
  const warnings = [];

  if (!asString(input?.company)) errors.push(`${prefix}: company is required.`);
  if (!asString(input?.role)) errors.push(`${prefix}: role is required.`);
  if (!asString(input?.source?.url)) errors.push(`${prefix}: source.url is required.`);
  if (!asString(input?.status)) errors.push(`${prefix}: status is required.`);
  if (asString(input?.status) && !STATUS_SET.has(input.status)) {
    errors.push(`${prefix}: status "${input.status}" is not supported.`);
  }
  if (input?.priority !== undefined && input?.priority !== null && !PRIORITY_SET.has(input.priority)) {
    errors.push(`${prefix}: priority "${input.priority}" is not supported.`);
  }
  if (input?.match?.score === undefined || input?.match?.score === null || input?.match?.score === "") {
    errors.push(`${prefix}: match.score is required.`);
  } else if (clampScore(input.match.score) === null || Number(input.match.score) < 0 || Number(input.match.score) > 100) {
    errors.push(`${prefix}: match.score must be between 0 and 100.`);
  }
  if (input?.nextAction !== undefined && input?.nextAction !== null && !NEXT_ACTION_SET.has(input.nextAction)) {
    warnings.push(`${prefix}: unknown nextAction was replaced with "analyze".`);
  }
  if (!input?.priority) warnings.push(`${prefix}: missing priority was filled with "unknown".`);

  return { errors, warnings };
}

function sameCompanyRoleLocation(a, b) {
  return asString(a.company).toLowerCase() === asString(b.company).toLowerCase()
    && asString(a.role).toLowerCase() === asString(b.role).toLowerCase()
    && asString(a.location?.city).toLowerCase() === asString(b.location?.city).toLowerCase()
    && asString(a.location?.workMode).toLowerCase() === asString(b.location?.workMode).toLowerCase();
}

export function findPossibleDuplicate(offer, existingOffers = []) {
  const url = asString(offer?.source?.url).toLowerCase();
  return existingOffers.find((existing) => {
    const existingUrl = asString(existing?.source?.url).toLowerCase();
    if (url && existingUrl && url === existingUrl) return true;
    return sameCompanyRoleLocation(offer, existing);
  }) || null;
}

export function validateJobOfferPayload(payload, existingOffers = [], options = {}) {
  let parsed = payload;
  const errors = [];
  const warnings = [];

  if (typeof payload === "string") {
    try {
      parsed = JSON.parse(payload);
    } catch (error) {
      return {
        ok: false,
        offers: [],
        errors: [`JSON is not valid: ${error.message}`],
        warnings: [],
        duplicates: [],
      };
    }
  }

  const rawOffers = Array.isArray(parsed) ? parsed : [parsed];
  if (!rawOffers.length || rawOffers.some((item) => !item || typeof item !== "object" || Array.isArray(item))) {
    errors.push("Payload must be a JobOffer object or an array of JobOffer objects.");
  }

  rawOffers.forEach((raw, index) => {
    const result = validateOneOffer(raw, Array.isArray(parsed) ? index : null);
    errors.push(...result.errors);
    warnings.push(...result.warnings);
  });

  if (errors.length) {
    return { ok: false, offers: [], errors, warnings, duplicates: [] };
  }

  const offers = rawOffers.map((offer) => normalizeJobOffer(offer, options));
  const duplicates = offers
    .map((offer) => ({ offer, existing: findPossibleDuplicate(offer, existingOffers) }))
    .filter((item) => item.existing);

  duplicates.forEach(({ offer }) => {
    warnings.push(`Possible duplicate found: ${offer.company} - ${offer.role}`);
  });

  return {
    ok: true,
    offers,
    errors: [],
    warnings,
    duplicates,
  };
}

export function loadJobOffers() {
  const raw = readJson(JOBHUNT_OFFERS_STORAGE_KEY, []);
  if (!Array.isArray(raw)) return [];
  return raw.map((offer) => normalizeJobOffer(offer));
}

export function saveJobOffers(offers) {
  const normalized = Array.isArray(offers) ? offers.map((offer) => normalizeJobOffer(offer)) : [];
  writeJson(JOBHUNT_OFFERS_STORAGE_KEY, normalized);
  emitChanged();
  return normalized;
}

export function importJobOffers(offers, existingOffers = loadJobOffers()) {
  return saveJobOffers([...existingOffers, ...offers]);
}

export function upsertJobOffer(offer, existingOffers = loadJobOffers(), options = {}) {
  const normalized = normalizeJobOffer({
    ...offer,
    updatedAt: isoNow(options.now || new Date()),
  }, options);
  const index = existingOffers.findIndex((item) => item.id === normalized.id);
  const next = index >= 0
    ? existingOffers.map((item, itemIndex) => itemIndex === index ? normalized : item)
    : [normalized, ...existingOffers];
  return saveJobOffers(next);
}

export function deleteJobOffer(id, existingOffers = loadJobOffers()) {
  return saveJobOffers(existingOffers.filter((offer) => offer.id !== id));
}

export function updateJobOffer(id, patch, existingOffers = loadJobOffers(), options = {}) {
  const now = isoNow(options.now || new Date());
  return saveJobOffers(existingOffers.map((offer) => {
    if (offer.id !== id) return offer;
    return normalizeJobOffer({
      ...offer,
      ...patch,
      location: { ...offer.location, ...(patch.location || {}) },
      contract: { ...offer.contract, ...(patch.contract || {}) },
      salary: { ...offer.salary, ...(patch.salary || {}) },
      source: { ...offer.source, ...(patch.source || {}) },
      branding: { ...offer.branding, ...(patch.branding || {}) },
      match: { ...offer.match, ...(patch.match || {}) },
      application: { ...offer.application, ...(patch.application || {}) },
      expiresAt: patch.expiresAt !== undefined ? patch.expiresAt : offer.expiresAt,
      updatedAt: now,
    }, options);
  }));
}

export function markJobOfferAsApplied(id, existingOffers = loadJobOffers(), options = {}) {
  const today = todayInputValue(options.now || new Date());
  return updateJobOffer(id, {
    status: "applied",
    nextAction: "follow_up",
    application: {
      dateApplied: today,
      followUpDate: addDaysToDateInput(today, 7),
    },
  }, existingOffers, options);
}

export function markJobOfferFollowUpSent(id, existingOffers = loadJobOffers(), options = {}) {
  const today = todayInputValue(options.now || new Date());
  const offer = existingOffers.find((item) => item.id === id);
  const noteLine = `[${today}] Follow-up sent.`;
  return updateJobOffer(id, {
    status: offer?.status === "applied" ? "follow_up" : offer?.status,
    application: {
      followUpDate: addDaysToDateInput(today, 7),
    },
    notes: [offer?.notes, noteLine].filter(Boolean).join("\n"),
  }, existingOffers, options);
}

function isDateThisWeek(value, now = new Date()) {
  if (!value) return false;
  const date = new Date(`${value}T12:00:00`);
  if (Number.isNaN(date.getTime())) return false;
  const anchor = now instanceof Date ? new Date(now) : new Date(now);
  const day = (anchor.getDay() + 6) % 7;
  const start = new Date(anchor);
  start.setHours(0, 0, 0, 0);
  start.setDate(anchor.getDate() - day);
  const end = new Date(start);
  end.setDate(start.getDate() + 7);
  return date >= start && date < end;
}

export function getFollowUpsDue(offers, now = new Date()) {
  const today = todayInputValue(now);
  return offers
    .filter((offer) =>
      offer.application?.followUpDate
      && offer.application.followUpDate <= today
      && !CLOSED_STATUSES.has(offer.status))
    .sort((a, b) =>
      String(a.application.followUpDate).localeCompare(String(b.application.followUpDate))
      || priorityRank(a.priority) - priorityRank(b.priority)
      || (Number(b.match?.score) || 0) - (Number(a.match?.score) || 0)
      || String(b.createdAt || "").localeCompare(String(a.createdAt || "")));
}

export function getBestJobOffer(offers) {
  return offers
    .filter((offer) => !ARCHIVED_STATUSES.has(offer.status) && offer.status !== "expired" && offer.evaluationSource !== "none")
    .sort((a, b) =>
      (Number(b.match?.score) || 0) - (Number(a.match?.score) || 0)
      || priorityRank(a.priority) - priorityRank(b.priority)
      || String(b.createdAt).localeCompare(String(a.createdAt)))[0] || null;
}

function priorityRank(priority) {
  return PRIORITY_ORDER.get(priority) ?? PRIORITY_ORDER.get("unknown");
}

export function sortJobOffers(offers = []) {
  return [...offers].sort((a, b) =>
    expirationRank(a) - expirationRank(b)
    ||
    priorityRank(a.priority) - priorityRank(b.priority)
    || (Number(b.match?.score) || 0) - (Number(a.match?.score) || 0)
    || String(b.createdAt || "").localeCompare(String(a.createdAt || "")));
}

function expirationRank(offer) {
  if (offer?.status === "expired") return 2;
  const days = getDaysUntilExpiration(offer);
  if (days === null) return 1;
  if (days < 0) return 2;
  return 0;
}

export function filterJobOffers(offers = [], filters = {}) {
  const search = asString(filters.search).toLowerCase();
  return sortJobOffers(offers).filter((offer) => {
    if (filters.status && filters.status !== "all" && offer.status !== filters.status) return false;
    if (filters.priority && filters.priority !== "all" && offer.priority !== filters.priority) return false;
    if (filters.workMode && filters.workMode !== "all" && offer.location?.workMode !== filters.workMode) return false;
    if (!search) return true;
    return [offer.company, offer.role].join(" ").toLowerCase().includes(search);
  });
}

export function getJobhuntSummary(offers = [], now = new Date()) {
  const bestMatch = getBestJobOffer(offers);
  const followUpsDue = getFollowUpsDue(offers, now);
  const active = offers.filter((offer) => !CLOSED_STATUSES.has(offer.status));
  const worthApplying = offers.filter((offer) =>
    !CLOSED_STATUSES.has(offer.status)
    && (offer.status === "worth_applying" || offer.priority === "P1" || offer.priority === "P2"));
  const expiring = offers
    .filter((offer) => !CLOSED_STATUSES.has(offer.status))
    .map((offer) => ({ offer, days: getDaysUntilExpiration(offer, now) }))
    .filter((item) => item.days !== null && item.days >= 0 && item.days <= 7)
    .sort((a, b) => a.days - b.days || priorityRank(a.offer.priority) - priorityRank(b.offer.priority));

  return {
    total: offers.length,
    worthApplying: worthApplying.length,
    appliedThisWeek: offers.filter((offer) => isDateThisWeek(offer.application?.dateApplied, now)).length,
    followUpsDue: followUpsDue.length,
    expired: offers.filter((offer) => offer.status === "expired").length,
    expiringSoon: expiring.length,
    nextExpiration: expiring[0] || null,
    interviewsActive: offers.filter((offer) => offer.status === "interview").length,
    bestMatch,
    bestMatchScore: bestMatch ? clampScore(bestMatch.match?.score) : null,
    nextAction: getNextBestAction(offers, now),
    activeOffers: active.length,
  };
}

export function getNextBestAction(offers = [], now = new Date()) {
  const due = getFollowUpsDue(offers, now)[0];
  if (due) {
    return {
      type: "follow_up",
      title: `Send follow-up to ${due.company} - ${due.role}`,
      reason: "Follow-up date is due or overdue.",
      offerId: due.id,
      offer: due,
    };
  }

  const apply = sortJobOffers(offers).find((offer) =>
    offer.priority === "P1" && !APPLIED_STATUSES.has(offer.status));
  if (apply) {
    return {
      type: "apply",
      title: `Apply to ${apply.company} - ${apply.role}`,
      reason: `P1 priority, ${apply.match.score}/100 match, not applied yet.`,
      offerId: apply.id,
      offer: apply,
    };
  }

  const reviewCount = offers.filter((offer) => offer.status === "new" || offer.status === "to_review").length;
  if (reviewCount) {
    return {
      type: "review",
      title: `Review ${reviewCount} new offers`,
      reason: "New or to-review offers need a decision.",
      offerId: null,
      offer: null,
    };
  }

  const interview = sortJobOffers(offers).find((offer) => offer.status === "interview");
  if (interview) {
    return {
      type: "prepare_interview",
      title: `Prepare for interview: ${interview.company} - ${interview.role}`,
      reason: "Interview status is active.",
      offerId: interview.id,
      offer: interview,
    };
  }

  return {
    type: "none",
    title: "No urgent jobhunt action",
    reason: "Nothing needs attention right now.",
    offerId: null,
    offer: null,
  };
}

export function getSkillGapSummary(offers = [], limit = 6) {
  const counts = new Map();
  offers
    .filter((offer) => !ARCHIVED_STATUSES.has(offer.status))
    .forEach((offer) => {
      asArray(offer.analysis?.skillGaps).forEach((skill) => {
        const key = skill.toLowerCase();
        const item = counts.get(key) || { skill, count: 0 };
        item.count += 1;
        counts.set(key, item);
      });
    });

  return [...counts.values()]
    .sort((a, b) => b.count - a.count || a.skill.localeCompare(b.skill, "pl"))
    .slice(0, limit)
    .map((item) => ({
      ...item,
      priority: item.count >= 8 ? "high" : item.count >= 4 ? "medium" : "low",
    }));
}

export function loadJobhuntMatchSettings() {
  const raw = readJson(JOBHUNT_MATCH_SETTINGS_STORAGE_KEY, null);
  if (!Array.isArray(raw)) return JOBHUNT_MATCH_SETTINGS_DEFAULTS.map((item) => ({ ...item }));
  const byId = new Map(raw.map((item) => [item.id, item]));
  return JOBHUNT_MATCH_SETTINGS_DEFAULTS.map((item) => ({
    ...item,
    weight: Math.max(0, Math.min(100, Number(byId.get(item.id)?.weight ?? item.weight) || 0)),
  }));
}

export function saveJobhuntMatchSettings(settings) {
  const normalized = JOBHUNT_MATCH_SETTINGS_DEFAULTS.map((item) => {
    const match = Array.isArray(settings) ? settings.find((candidate) => candidate.id === item.id) : null;
    return {
      ...item,
      weight: Math.max(0, Math.min(100, Number(match?.weight ?? item.weight) || 0)),
    };
  });
  writeJson(JOBHUNT_MATCH_SETTINGS_STORAGE_KEY, normalized);
  return normalized;
}

export function formatJobLocation(offer) {
  const city = asString(offer?.location?.city, "unknown");
  const mode = asString(offer?.location?.workMode, "unknown");
  return `${city} / ${mode}`;
}

export function formatJobSalary(offer) {
  if (!offer?.salary?.isKnown) return "unknown";
  const min = toNumberOrNull(offer.salary.min);
  const max = toNumberOrNull(offer.salary.max);
  const range = min !== null && max !== null
    ? `${min.toLocaleString("pl-PL")}-${max.toLocaleString("pl-PL")}`
    : `${(min ?? max ?? 0).toLocaleString("pl-PL")}`;
  return `${range} ${asString(offer.salary.currency, "")}`.trim();
}
