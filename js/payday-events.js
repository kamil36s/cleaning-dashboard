import { parseISODate, toISODate } from "./events-date.js";

const DEFAULT_MONTHS_AHEAD = 14;
const DECEMBER_PAYDAY_DAY = 22;

export function generatePredictedPaydays(options = {}) {
  const today = options.today || new Date();
  const monthsAhead = Number.isFinite(options.monthsAhead)
    ? Math.max(1, Math.round(options.monthsAhead))
    : DEFAULT_MONTHS_AHEAD;
  const holidayDates = new Set(options.holidayDates || []);
  const events = [];

  for (let offset = 0; offset < monthsAhead; offset += 1) {
    const monthDate = new Date(today.getFullYear(), today.getMonth() + offset, 1);
    const payday = getPredictedPayday(monthDate.getFullYear(), monthDate.getMonth(), holidayDates);
    if (!payday) continue;

    events.push({
      id: `predicted-payday-${toISODate(payday).slice(0, 7)}`,
      date: toISODate(payday),
      title: "Wypłata",
      type: "payday",
      isDayOff: false,
      isShortDay: false,
      source: "payday_prediction",
      notes: getPaydayRuleNote(payday),
    });
  }

  return events;
}

export function getPredictedPayday(year, monthIndex, holidayDates = new Set()) {
  if (monthIndex === 11) {
    return previousBusinessDay(new Date(year, monthIndex, DECEMBER_PAYDAY_DAY), holidayDates);
  }

  const lastDay = new Date(year, monthIndex + 1, 0);
  const businessDays = [];
  for (let date = new Date(year, monthIndex, 1); date <= lastDay; date.setDate(date.getDate() + 1)) {
    const candidate = new Date(date);
    if (isBusinessDay(candidate, holidayDates)) {
      businessDays.push(candidate);
    }
  }

  return businessDays.at(-2) || businessDays.at(-1) || null;
}

export function inferPaydayRule(samples) {
  const validSamples = (Array.isArray(samples) ? samples : [])
    .map((sample) => parseISODate(sample))
    .filter(Boolean);

  const secondLastMatches = validSamples.filter((date) => {
    if (date.getMonth() === 11) return true;
    const predicted = getPredictedPayday(date.getFullYear(), date.getMonth());
    return predicted && toISODate(predicted) === toISODate(date);
  });

  return {
    rule: "second_last_business_day",
    decemberRule: "business_day_on_or_before_december_22",
    confidence: validSamples.length ? secondLastMatches.length / validSamples.length : 0,
  };
}

function previousBusinessDay(date, holidayDates) {
  const candidate = new Date(date);
  while (!isBusinessDay(candidate, holidayDates)) {
    candidate.setDate(candidate.getDate() - 1);
  }
  return candidate;
}

function isBusinessDay(date, holidayDates) {
  const day = date.getDay();
  return day !== 0 && day !== 6 && !holidayDates.has(toISODate(date));
}

function getPaydayRuleNote(date) {
  if (date.getMonth() === 11) {
    return "Prognoza: grudniowa wypłata przed świętami, najpóźniej 22.12.";
  }
  return "Prognoza: przedostatni dzień roboczy miesiąca.";
}
