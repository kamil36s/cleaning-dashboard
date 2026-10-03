const pad2 = (value) => String(value).padStart(2, '0');

const asDate = (value) => {
  if (value instanceof Date) return Number.isFinite(value.getTime()) ? value : null;
  if (value == null || value === '') return null;
  const parsed = new Date(value);
  return Number.isFinite(parsed.getTime()) ? parsed : null;
};

export function formatCleaningDate(value) {
  const date = asDate(value);
  if (!date) return '';
  return `${pad2(date.getDate())}/${pad2(date.getMonth() + 1)}/${date.getFullYear()}`;
}

export function formatCleaningDateWithWeekday(value, weekday = 'short') {
  const date = asDate(value);
  if (!date) return '';
  const dayName = date.toLocaleDateString('pl-PL', { weekday }).replace('.', '');
  return `${dayName}, ${formatCleaningDate(date)}`;
}

export function parseCleaningDateInput(value) {
  const text = String(value || '').trim();
  if (!text) return null;
  const match = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(text);
  if (!match) throw new Error('Wpisz datę w formacie dd/mm/yyyy.');
  const day = Number(match[1]);
  const month = Number(match[2]);
  const year = Number(match[3]);
  const date = new Date(year, month - 1, day);
  if (date.getFullYear() !== year || date.getMonth() !== month - 1 || date.getDate() !== day) {
    throw new Error('Podana data nie istnieje.');
  }
  return `${year}-${pad2(month)}-${pad2(day)}`;
}
