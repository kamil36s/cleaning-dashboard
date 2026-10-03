export function formatDurationShort(totalSeconds) {
  const safeSeconds = Math.max(0, Math.round(Number(totalSeconds) || 0));
  const hours = Math.floor(safeSeconds / 3600);
  const minutes = Math.floor((safeSeconds % 3600) / 60);
  const seconds = safeSeconds % 60;

  if (hours > 0) {
    return `${hours}h ${String(minutes).padStart(2, '0')}m`;
  }
  if (minutes > 0) {
    return `${minutes}m ${String(seconds).padStart(2, '0')}s`;
  }
  return `${seconds}s`;
}

export function formatMinutesValue(totalSeconds) {
  const minutes = Math.round((Number(totalSeconds) || 0) / 60);
  return `${minutes} min`;
}

export function formatPercent(value, digits = 0) {
  const safe = Number(value);
  if (!Number.isFinite(safe)) return '-';
  return `${safe.toFixed(digits)}%`;
}

export function formatDateLabel(dayKey) {
  if (!dayKey) return '-';
  const date = new Date(`${dayKey}T12:00:00`);
  if (Number.isNaN(date.getTime())) return dayKey;
  return date.toLocaleDateString('pl-PL', {
    weekday: 'short',
    day: '2-digit',
    month: '2-digit',
  });
}

export function formatClockHour(hour) {
  return String(hour).padStart(2, '0');
}
