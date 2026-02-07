export const fmtDateShort = (d) => {
  if (!d) return '—';
  const dt = new Date(d);
  if (Number.isNaN(dt.getTime())) return '—';
  return dt.toLocaleDateString('pl-PL', { day: 'numeric', month: 'short', year: 'numeric' });
};

export const fmtDateTimeShort = (d) => {
  if (!d) return '—';
  const dt = new Date(d);
  if (Number.isNaN(dt.getTime())) return '—';
  const date = dt.toLocaleDateString('pl-PL', { day: 'numeric', month: 'short', year: 'numeric' });
  const time = dt.toLocaleTimeString('pl-PL', { hour: '2-digit', minute: '2-digit' });
  return `${date}, ${time}`;
};

export const fmtDate = fmtDateShort;

export const bust = (url) => url + (url.includes('?') ? '&' : '?') + '_=' + Date.now();

export const fmtTimeShort = (d) => {
  if (!d) return 'â€”';
  const dt = d instanceof Date ? d : new Date(d);
  if (Number.isNaN(dt.getTime())) return 'â€”';
  return dt.toLocaleTimeString('pl-PL', { hour: '2-digit', minute: '2-digit' });
};

export const parseDateMaybe = (value) => {
  if (value == null || value === '') return null;
  if (value instanceof Date) return value;
  if (typeof value === 'number') return new Date(value);
  const str = String(value).trim();
  if (!str) return null;

  let match = str.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (match) {
    const year = Number(match[1]);
    const month = Number(match[2]) - 1;
    const day = Number(match[3]);
    return new Date(year, month, day);
  }

  match = str.match(/^(\d{1,2})[./-](\d{1,2})[./-](\d{4})$/);
  if (match) {
    const day = Number(match[1]);
    const month = Number(match[2]) - 1;
    const year = Number(match[3]);
    return new Date(year, month, day);
  }

  const dt = new Date(str);
  if (Number.isNaN(dt.getTime())) return null;
  return dt;
};

export const isSameDay = (a, b) => {
  if (!a || !b) return false;
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
};
