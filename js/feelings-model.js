export const QUADRANT_META = {
  high_unpleasant: { label: "High Energy · Unpleasant", short: "Red", color: "#ff4661" },
  high_pleasant: { label: "High Energy · Pleasant", short: "Yellow", color: "#ffc83d" },
  low_unpleasant: { label: "Low Energy · Unpleasant", short: "Blue", color: "#6f91ff" },
  low_pleasant: { label: "Low Energy · Pleasant", short: "Green", color: "#49dda0" },
};

const normalize = (value) => String(value || "").normalize("NFKD").toLocaleLowerCase();

export function emotionMeterItems(emotions) {
  return (emotions || [])
    .filter((emotion) => {
      const x = Number(emotion.x);
      const y = Number(emotion.y);
      const hasCanonicalCoordinates = Number.isInteger(x) && Number.isInteger(y) && x >= 0 && x < 12 && y >= 0 && y < 12;
      return emotion.meter === true || (emotion.meter == null && hasCanonicalCoordinates);
    })
    .sort((left, right) => Number(left.y) - Number(right.y) || Number(left.x) - Number(right.x));
}

export function searchEmotions(emotions, query = "", quadrants = []) {
  const needle = normalize(query).trim();
  const active = new Set(quadrants || []);
  return (emotions || []).filter((emotion) => {
    if (active.size && !active.has(emotion.quadrant)) return false;
    return !needle || normalize(emotion.name).includes(needle) || normalize(emotion.description).includes(needle);
  });
}

export function filterCheckins(checkins, filters = {}) {
  const needle = normalize(filters.q).trim();
  const from = filters.from ? `${filters.from}T00:00:00` : "";
  const to = filters.to ? `${filters.to}T23:59:59` : "";
  return (checkins || []).filter((item) => {
    if (from && item.occurredAt < from) return false;
    if (to && item.occurredAt > to) return false;
    if (filters.quadrant && item.emotion?.quadrant !== filters.quadrant) return false;
    if (filters.emotion && item.emotion?.name !== filters.emotion && item.emotion?.id !== filters.emotion) return false;
    if (filters.tag && !item.tags?.some((tag) => tag.name === filters.tag || tag.id === filters.tag)) return false;
    if (needle) {
      const haystack = normalize([item.emotion?.name, item.note, ...(item.tags || []).map((tag) => tag.name)].join(" "));
      if (!haystack.includes(needle)) return false;
    }
    return true;
  });
}

export function quickRange(days, now = new Date()) {
  if (!Number.isFinite(days) || days <= 0) return { from: "", to: "" };
  const end = new Date(now);
  const start = new Date(now);
  start.setDate(start.getDate() - days + 1);
  return { from: localDate(start), to: localDate(end) };
}

export function localDate(date) {
  const offset = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 10);
}

export function localDateTime(date = new Date()) {
  const offset = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 16);
}

export function groupCheckins(checkins, now = new Date()) {
  const today = localDate(now);
  const yesterdayDate = new Date(now);
  yesterdayDate.setDate(yesterdayDate.getDate() - 1);
  const yesterday = localDate(yesterdayDate);
  const formatter = new Intl.DateTimeFormat(undefined, { month: "long", year: "numeric" });
  const groups = new Map();
  (checkins || []).forEach((item) => {
    const day = item.occurredAt.slice(0, 10);
    const key = day === today ? "Today" : day === yesterday ? "Yesterday" : formatter.format(new Date(`${day}T12:00:00`));
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(item);
  });
  return [...groups].map(([label, items]) => ({ label, items }));
}

export function weekSummary(checkins, now = new Date()) {
  const from = new Date(now);
  from.setDate(from.getDate() - 6);
  const recent = filterCheckins(checkins, { from: localDate(from), to: localDate(now) });
  const counts = new Map();
  recent.forEach((item) => counts.set(item.emotion?.quadrant, (counts.get(item.emotion?.quadrant) || 0) + 1));
  const leading = [...counts].sort((a, b) => b[1] - a[1])[0];
  return leading ? `Mostly ${QUADRANT_META[leading[0]]?.label.toLocaleLowerCase()} this week` : "No check-ins this week yet";
}

export function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
