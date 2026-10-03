export function financeDateLabel(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(value || ""));
  return match ? `${match[3]}/${match[2]}/${match[1]}` : "—";
}

export function financeDateToIso(value) {
  const text = String(value || "").trim();
  if (!text) return "";
  if (/^\d{4}-\d{2}-\d{2}$/.test(text)) return text;
  const match = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(text);
  if (!match) return "";
  const parsed = new Date(`${match[3]}-${match[2]}-${match[1]}T12:00:00`);
  return Number.isNaN(parsed.getTime()) || parsed.getDate() !== Number(match[1]) || parsed.getMonth() + 1 !== Number(match[2])
    ? "" : `${match[3]}-${match[2]}-${match[1]}`;
}
