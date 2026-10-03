import { addDays, getWeekStart, isWeekend } from "./events-date.js";

const INSIGHT_LIMIT = 8;

export function getLongWeekendSuggestion(event) {
  if (!event?.isDayOff || event.type !== "public_holiday") return null;
  const day = event.dateObj.getDay();

  if (day === 1 || day === 5) {
    return {
      kind: "long_weekend",
      tone: "good",
      text: `${event.title}: gotowy długi weekend.`,
      eventId: event.id,
    };
  }

  if (day === 2) {
    return {
      kind: "long_weekend",
      tone: "warn",
      text: `${event.title}: urlop w poniedziałek robi 4 dni wolnego.`,
      eventId: event.id,
    };
  }

  if (day === 4) {
    return {
      kind: "long_weekend",
      tone: "warn",
      text: `${event.title}: urlop w piątek robi 4 dni wolnego.`,
      eventId: event.id,
    };
  }

  return null;
}

export function generateEventStats(events) {
  const upcoming = events.filter((event) => event.meta.daysUntil >= 0);
  return {
    next7Days: upcoming.filter((event) => event.meta.daysUntil <= 7).length,
    next30Days: upcoming.filter((event) => event.meta.daysUntil <= 30).length,
    publicHolidaysNext60Days: upcoming.filter(
      (event) => event.type === "public_holiday" && event.meta.daysUntil <= 60,
    ).length,
    totalUpcoming: upcoming.length,
  };
}

export function generateEventInsights(events, options = {}) {
  const today = options.today || new Date();
  const upcoming = events.filter((event) => event.meta.daysUntil >= 0);
  const insights = [];
  const stats = generateEventStats(events);
  const nextDayOff = upcoming.find((event) => event.isDayOff);
  const nextBirthday = upcoming.find((event) => event.type === "birthday");

  if (nextDayOff) {
    insights.push({
      kind: "next_day_off",
      tone: "good",
      text: `Next day off: ${nextDayOff.title} (${nextDayOff.date}).`,
      eventId: nextDayOff.id,
    });
  }

  if (nextBirthday) {
    insights.push({
      kind: "next_birthday",
      tone: "info",
      text: `Next birthday: ${nextBirthday.title} (${nextBirthday.date}).`,
      eventId: nextBirthday.id,
    });
  }

  insights.push({
    kind: "next_7_days",
    tone: stats.next7Days > 0 ? "warn" : "neutral",
    text: `Events in the next 7 days: ${stats.next7Days}.`,
  });

  insights.push({
    kind: "next_30_days",
    tone: stats.next30Days > 0 ? "info" : "neutral",
    text: `Events in the next 30 days: ${stats.next30Days}.`,
  });

  insights.push({
    kind: "public_holidays_60_days",
    tone: stats.publicHolidaysNext60Days > 0 ? "good" : "neutral",
    text: `Public holidays in the next 60 days: ${stats.publicHolidaysNext60Days}.`,
  });

  const weekendEvent = upcoming.find((event) => event.meta.isWeekend);
  if (weekendEvent) {
    insights.push({
      kind: "weekend_event",
      tone: "neutral",
      text: `${weekendEvent.title} falls on a weekend.`,
      eventId: weekendEvent.id,
    });
  }

  const currentWeek = getCurrentWeekWorkingDays(events, today);
  if (currentWeek.workingDays < 5) {
    insights.push({
      kind: "short_work_week",
      tone: "good",
      text: `This week has fewer working days: ${currentWeek.workingDays}/5.`,
    });
  }

  upcoming
    .map(getLongWeekendSuggestion)
    .filter(Boolean)
    .slice(0, 2)
    .forEach((insight) => insights.push(insight));

  return {
    stats,
    insights: dedupeInsights(insights).slice(0, INSIGHT_LIMIT),
  };
}

export function getCurrentWeekWorkingDays(events, today = new Date()) {
  const weekStart = getWeekStart(today);
  const weekdays = [0, 1, 2, 3, 4].map((offset) => addDays(weekStart, offset));
  const dayOffDates = new Set(
    events
      .filter((event) => event.isDayOff && !isWeekend(event.dateObj))
      .map((event) => event.date),
  );
  const shortDayDates = new Set(
    events
      .filter((event) => event.isShortDay && !isWeekend(event.dateObj))
      .map((event) => event.date),
  );

  return {
    workingDays: weekdays.filter((date) => !dayOffDates.has(toISODateLike(date))).length,
    shortDays: weekdays.filter((date) => shortDayDates.has(toISODateLike(date))).length,
  };
}

function toISODateLike(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function dedupeInsights(insights) {
  const seen = new Set();
  return insights.filter((insight) => {
    const key = `${insight.kind}:${insight.eventId || ""}:${insight.text}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}
