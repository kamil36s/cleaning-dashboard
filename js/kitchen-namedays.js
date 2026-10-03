import calendar from '../data/polish-namedays.json';

export function namedaysForDate(date) {
  if (!(date instanceof Date) || Number.isNaN(date.getTime())) return [];
  const key = `${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
  return calendar.days[key] || [];
}

export function namedayLabel(date) {
  const names = namedaysForDate(date).slice(0, 3);
  return `Imieniny: ${names.join(', ') || '--'}`;
}
