export const fmtDate = d => d
  ? new Date(d).toLocaleDateString('pl-PL', { day: '2-digit', month: 'short', year: 'numeric' })
  : '—';

export const bust = url => url + (url.includes('?') ? '&' : '?') + '_=' + Date.now();