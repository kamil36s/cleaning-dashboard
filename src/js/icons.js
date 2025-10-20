// Map category -> inline SVG (string)
export const CATEGORY_ICON = {
  'Przetarcie kurzu': '<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M3 20h18M5 16h14l-1.5-7.5A3 3 0 0 0 14.6 6H9.4a3 3 0 0 0-2.9 2.5L5 16Z"/><path d="M10 6V4a2 2 0 0 1 4 0v2"/></svg>',
  'Przetarcie': '<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="7" width="18" height="10" rx="2"/><path d="M7 7V5m10 2V5"/></svg>',
  'Umywalka': '<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M6 12h12"/><path d="M7 12a5 5 0 0 0 10 0"/><path d="M12 6v3"/><path d="M10 6h4"/></svg>',
  'Zlew': '<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="8" width="18" height="8" rx="2"/><path d="M12 8V5h3"/></svg>',
  'Lustro': '<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 7l6 6M9 11l2 2"/></svg>',
  'Odkurzanie': '<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M6 15h7a3 3 0 0 1 3 3v1H6z"/><path d="M10 15V6a3 3 0 0 1 6 0v4"/><circle cx="8" cy="19" r="1.6"/><circle cx="16" cy="19" r="1.6"/></svg>',
  'Mycie mopem': '<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 3v12"/><path d="M5 19h14l-2 2H7z"/></svg>',
  'Prysznic': '<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 4a5 5 0 0 1 5 5v1H7V9a5 5 0 0 1 5-5Z"/><path d="M7 14h10"/><path d="M8 16v2M12 16v2M16 16v2"/></svg>',
  'Kibel': '<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M7 4h10v4H7z"/><path d="M6 8h12l-1 5a6 6 0 0 1-10 0z"/></svg>',
  'Pralka': '<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="4" y="3" width="16" height="18" rx="2"/><circle cx="12" cy="13" r="4"/><circle cx="8" cy="6" r="1"/><circle cx="12" cy="6" r="1"/></svg>',
  'Okno': '<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="4" y="4" width="16" height="16" rx="1"/><path d="M12 4v16M4 12h16"/></svg>',
  'Łóżko': '<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M3 12h18v6H3z"/><path d="M3 12V9a2 2 0 0 1 2-2h6v5"/></svg>',
  'Śmieci': '<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 7h16"/><path d="M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12"/><path d="M9 7V5h6v2"/></svg>',
  'Organizacja': '<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="4" y="5" width="16" height="4" rx="1"/><rect x="4" y="10" width="16" height="4" rx="1"/><rect x="4" y="15" width="16" height="4" rx="1"/></svg>',
  'Inne': '<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16h.01"/></svg>'
};

export function iconFor(category) {
  const keys = Object.keys(CATEGORY_ICON);
  const hit = keys.find(k => (category || '').toLowerCase().includes(k.toLowerCase()));
  return CATEGORY_ICON[hit || 'Inne'];
}