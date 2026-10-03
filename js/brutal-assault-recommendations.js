function artistKey(value) {
  return String(value || '')
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/ł/g, 'l')
    .replace(/&/g, ' and ')
    .replace(/[^a-z0-9]+/g, ' ')
    .trim();
}

function communityRating(row) {
  const raw = row?.rymRating ?? row?.communityRating;
  if (raw === null || raw === undefined || raw === '') return null;
  const value = Number(raw);
  return Number.isFinite(value) ? value : null;
}

export const BRUTAL_ASSAULT_2027_DEADLINE = '2027-08-04';

const BRUTAL_ASSAULT_RECOMMENDATION_RELEASE_DATES = new Map([
  ['uncle acid and the deadbeats::shapes of midnight', '2026-09-18'],
]);

export function countAlbumDescriptionSentences(value) {
  return (String(value || '').match(/[^.!?]+(?:[.!?]+|$)/g) || [])
    .filter((part) => /\p{L}|\p{N}/u.test(part))
    .length;
}

function albumDescriptionSentences(value) {
  return (String(value || '').match(/[^.!?]+(?:[.!?]+|$)/g) || [])
    .map((part) => part.trim())
    .filter((part) => /\p{L}|\p{N}/u.test(part));
}

function knownDescriptionHeading(value) {
  const match = String(value || '').match(
    /^(?:#{1,3}\s*)?(?:\[\s*)?(w skrócie|ciekawostki(?: i kontekst)?|na co zwrócić uwagę)(?:\s*\])?\s*:?\s*$/i
  );
  if (!match) return '';
  const key = match[1].toLocaleLowerCase('pl-PL');
  if (key === 'w skrócie') return 'W skrócie';
  if (key.startsWith('ciekawostki')) return 'Ciekawostki';
  return 'Na co zwrócić uwagę';
}

export function albumDescriptionTeaser(value, maxLength = Number.POSITIVE_INFINITY) {
  const lines = String(value || '').split(/\r?\n/);
  const introLines = [];
  let introStarted = false;
  for (const rawLine of lines) {
    const line = rawLine.trim();
    const heading = knownDescriptionHeading(line);
    if (heading) {
      if (introStarted) break;
      introStarted = heading.toLocaleLowerCase('pl-PL').startsWith('w skr');
      continue;
    }
    if (introStarted && line) {
      introLines.push(line.replace(/^[-\u2022]\s+/, ''));
    }
  }

  const fallback = albumDescriptionSentences(
    String(value || '')
      .replace(/^#{1,3}\s+.*$/gm, '')
      .replace(/^(?:\[\s*)?(?:w skrócie|ciekawostki(?: i kontekst)?|na co zwrócić uwagę)(?:\s*\])?\s*:?\s*$/gim, '')
      .replace(/^[-•]\s+/gm, '')
  ).slice(0, 2).join(' ');
  const clean = (introLines.join(' ') || fallback)
    .replace(/\*\*/g, '')
    .replace(/\s+/g, ' ')
    .trim();
  if (clean.length <= maxLength) return clean;
  return `${clean.slice(0, Math.max(0, maxLength - 1)).trimEnd()}…`;
}

function appendInlineDescriptionMarkup(element, value) {
  const documentRef = element.ownerDocument || document;
  const parts = String(value || '').split(/(\*\*[^*]+\*\*)/g);
  parts.forEach((part) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      const strong = documentRef.createElement('strong');
      strong.textContent = part.slice(2, -2);
      element.appendChild(strong);
    } else if (part) {
      element.appendChild(documentRef.createTextNode(part));
    }
  });
}

function appendDescriptionListItemMarkup(element, value) {
  const clean = String(value || '').trim();
  if (clean.includes('**')) {
    appendInlineDescriptionMarkup(element, clean);
    return;
  }
  const label = clean.match(/^([^:]{2,52}:)\s+(.+)$/);
  if (!label) {
    appendInlineDescriptionMarkup(element, clean);
    return;
  }
  const documentRef = element.ownerDocument || document;
  const strong = documentRef.createElement('strong');
  strong.textContent = label[1];
  element.append(strong, documentRef.createTextNode(` ${label[2]}`));
}

export function renderBrutalAssaultAlbumDescription(element, value) {
  if (!element) return;
  const documentRef = element.ownerDocument || document;
  const clean = String(value || '').trim();
  element.replaceChildren();
  element.classList.add('ba2027-description-content');
  if (!clean) return;

  const lines = clean.split(/\n/).map((line) => line.trim());
  const hasFormatting = lines.some((line) => (
    /^(?:#{1,3}\s+|[-•]\s+)/.test(line) || Boolean(knownDescriptionHeading(line))
  ));

  if (!hasFormatting) {
    const sentences = albumDescriptionSentences(clean);
    const lead = documentRef.createElement('p');
    lead.className = 'ba2027-description-lead';
    appendInlineDescriptionMarkup(lead, sentences.slice(0, 2).join(' '));
    element.appendChild(lead);
    if (sentences.length > 2) {
      const heading = documentRef.createElement('h5');
      heading.textContent = 'Ciekawostki i kontekst';
      const list = documentRef.createElement('ul');
      sentences.slice(2).forEach((sentence) => {
        const item = documentRef.createElement('li');
        appendInlineDescriptionMarkup(item, sentence);
        list.appendChild(item);
      });
      element.append(heading, list);
    }
    return;
  }

  let list = null;
  let section = '';
  let lead = null;
  lines.forEach((line) => {
    if (!line) {
      list = null;
      return;
    }
    const headingMatch = line.match(/^#{1,3}\s+(.+)$/);
    const knownHeading = knownDescriptionHeading(line);
    if (headingMatch || knownHeading) {
      const headingText = knownHeading || headingMatch[1];
      const heading = documentRef.createElement('h5');
      appendInlineDescriptionMarkup(heading, headingText);
      element.appendChild(heading);
      section = knownHeading;
      list = null;
      lead = null;
      return;
    }
    const bulletMatch = line.match(/^[-•]\s+(.+)$/);
    const shouldBeListItem = bulletMatch || section === 'Ciekawostki'
      || section === 'Na co zwrócić uwagę';
    if (shouldBeListItem) {
      if (!list) {
        list = documentRef.createElement('ul');
        element.appendChild(list);
      }
      const item = documentRef.createElement('li');
      appendDescriptionListItemMarkup(item, bulletMatch ? bulletMatch[1] : line);
      list.appendChild(item);
      return;
    }
    if (section === 'W skrócie') {
      if (!lead) {
        lead = documentRef.createElement('p');
        lead.className = 'ba2027-description-lead';
        element.appendChild(lead);
      } else {
        lead.appendChild(documentRef.createTextNode(' '));
      }
      appendInlineDescriptionMarkup(lead, line);
      return;
    }
    const paragraph = documentRef.createElement('p');
    appendInlineDescriptionMarkup(paragraph, line);
    element.appendChild(paragraph);
    list = null;
  });
}

export function buildBrutalAssaultAlbumPrompt(row) {
  const artist = String(row?.artist || '').trim() || 'wykonawcy';
  const album = String(row?.album || '').trim() || 'albumu';
  return `Przygotuj po polsku krótki, atrakcyjny opis albumu „${album}” zespołu ${artist}, który naprawdę zachęca do odsłuchania. Sprawdź fakty i nie dopowiadaj niczego, czego nie da się wiarygodnie potwierdzić. Maksymalnie 10 zdań łącznie. Zwróć wyłącznie zwykły tekst w dokładnie tym układzie, bez Markdown, bloku kodu i dodatkowego komentarza:\n\n[W SKRÓCIE]\nDwa krótkie, konkretne zdania: czym ten album się wyróżnia i dlaczego warto go włączyć.\n\n[CIEKAWOSTKI]\n• Krótkie hasło: jedna zaskakująca, sprawdzona ciekawostka.\n• Krótkie hasło: druga sprawdzona ciekawostka.\n• Krótkie hasło: kontekst powstania albo znaczenie albumu w dyskografii.\n\n[NA CO ZWRÓCIĆ UWAGĘ]\n• Brzmienie: konkretna cecha muzyki, produkcji lub wokalu, której warto posłuchać.\n• Moment albumu: utwór, fragment albo motyw będący dobrym punktem zaczepienia.\n\nZachowaj dokładnie nagłówki w nawiasach kwadratowych i znaki •. Każdy punkt ma być krótki, zaczynać się hasłem zakończonym dwukropkiem i zawierać najwyżej jedno zdanie. Bez lania wody, ocen liczbowych i powtarzania informacji.`;
}

export function buildBrutalAssaultBulkDescriptionPrompt(rows) {
  const albums = (Array.isArray(rows) ? rows : [])
    .map((row) => {
      const id = Number(row?.rowId);
      const artist = String(row?.artist || '').replace(/\|/g, '/').trim();
      const album = String(row?.album || '').replace(/\|/g, '/').trim();
      return Number.isInteger(id) && artist && album ? `${id}|${artist}|${album}` : '';
    })
    .filter(Boolean);
  return `Przygotuj krótkie polskie opisy poniższych albumów. Zwróć WYŁĄCZNIE poprawny JSON: jeden obiekt, w którym kluczem jest ID albumu, a wartością opis. Bez bloku kodu i komentarza. Każdy opis ma mieć dokładnie ten zwykły tekstowy układ:\n[W SKRÓCIE]\n2 krótkie zdania: charakter albumu i powód, by go posłuchać.\n[CIEKAWOSTKI]\n• Hasło: sprawdzony fakt.\n• Hasło: sprawdzony fakt.\n• Hasło: kontekst powstania lub miejsce w dyskografii.\n[NA CO ZWRÓCIĆ UWAGĘ]\n• Brzmienie: konkretny element do wychwycenia.\n• Moment albumu: utwór lub fragment będący dobrym punktem zaczepienia.\nMaksymalnie 7 zdań na album, najlepiej 12–24 słowa na zdanie. Nie wymyślaj faktów; pomiń niepewny punkt zamiast halucynować. Zachowaj nagłówki, znaki • i hasła zakończone dwukropkiem.\n\nALBUMY (ID|ARTYSTA|ALBUM):\n${albums.join('\n')}`;
}

export function buildRymPolishBlackMetalAlbumPrompt(row) {
  const artist = String(row?.artist || '').trim() || 'wykonawcy';
  const album = String(row?.album || '').trim() || 'albumu';
  const rank = Number(row?.sourceRank);
  const year = String(row?.year || '').trim();
  const context = [Number.isFinite(rank) ? `pozycja #${rank} na tej liście RYM` : '', year]
    .filter(Boolean)
    .join(', ');
  return `Przygotuj po polsku krótki, konkretny opis albumu „${album}” zespołu ${artist}${context ? ` (${context})` : ''}. Zweryfikuj fakty i nie dopowiadaj niczego, czego nie da się wiarygodnie potwierdzić. Maksymalnie 10 zdań łącznie. Zwróć wyłącznie zwykły tekst w dokładnie tym układzie, bez bloku kodu i dodatkowego komentarza:

[W SKRÓCIE]
Dwa różnie zbudowane zdania: charakter płyty oraz konkretny powód jej obecności na liście lub najlepszy punkt wejścia.

[CIEKAWOSTKI]
• Krótkie hasło: jedna zaskakująca, sprawdzona ciekawostka.
• Krótkie hasło: drugi sprawdzony fakt z innego obszaru.
• Krótkie hasło: kontekst powstania albo znaczenie albumu w dyskografii.

[NA CO ZWRÓCIĆ UWAGĘ]
• Brzmienie: precyzyjna cecha muzyki, produkcji, instrumentów lub wokalu.
• Moment albumu: utwór, fragment albo motyw będący dobrym punktem zaczepienia.

REGUŁY STYLU: NIE używaj nigdzie formuł „Warto posłuchać dla…”, „Warto go posłuchać…”, „Warto włączyć…” ani podobnych szkolnych rekomendacji. Nie zaczynaj dwóch zdań tą samą konstrukcją. Unikaj ogólników typu „to wyjątkowy album” i seryjnego schematu „album robi X, warto go słuchać dla Y”. Każde zdanie ma wnosić inną, charakterystyczną dla tej płyty informację. Zachowaj nagłówki w nawiasach kwadratowych i znaki •; każdy punkt zaczyna się krótkim hasłem zakończonym dwukropkiem.`;
}

export function buildRymPolishBlackMetalBulkDescriptionPrompt(rows) {
  const albums = (Array.isArray(rows) ? rows : [])
    .map((row) => {
      const id = Number(row?.rowId);
      const rank = Number(row?.sourceRank);
      const artist = String(row?.artist || '').replace(/\|/g, '/').trim();
      const album = String(row?.album || '').replace(/\|/g, '/').trim();
      const year = String(row?.year || '').trim();
      return Number.isInteger(id) && artist && album
        ? `${id}|${Number.isFinite(rank) ? rank : ''}|${artist}|${album}|${year}`
        : '';
    })
    .filter(Boolean);
  return `Przygotuj krótkie polskie opisy albumów z listy Top 100 RYM Polish BM. Zwróć WYŁĄCZNIE poprawny JSON: jeden obiekt, w którym kluczem jest ID albumu, a wartością opis. Bez bloku kodu i komentarza. Każdy opis ma mieć dokładnie ten układ:
[W SKRÓCIE]
2 krótkie, różnie zbudowane zdania: charakter albumu oraz konkretny punkt wejścia lub znaczenie płyty.
[CIEKAWOSTKI]
• Hasło: sprawdzony fakt.
• Hasło: sprawdzony fakt z innego obszaru.
• Hasło: kontekst powstania lub miejsce w dyskografii.
[NA CO ZWRÓCIĆ UWAGĘ]
• Brzmienie: konkretny element do wychwycenia.
• Moment albumu: utwór lub fragment będący dobrym punktem zaczepienia.

Maksymalnie 7 zdań na album, najlepiej 12–24 słowa na zdanie. Nie wymyślaj faktów; pomiń niepewny punkt zamiast halucynować. NAJWAŻNIEJSZE: opisy w paczce muszą brzmieć jak napisane osobno, nie z jednego szablonu. Żadne dwa opisy nie mogą zaczynać się tymi samymi trzema słowami. Zmieniaj składnię, rytm i sposób otwarcia sekcji [W SKRÓCIE]. NIE używaj nigdzie formuł „Warto posłuchać dla…”, „Warto go posłuchać…”, „Warto włączyć…” ani ich bliskich wariantów. Nie powtarzaj konstrukcji „album robi X, warto go słuchać dla Y”. Każde zdanie ma wnosić szczegół właściwy wyłącznie danej płycie. Zachowaj nagłówki, znaki • i hasła zakończone dwukropkiem.

ALBUMY (ID|RANGA_NA_LIŚCIE|ARTYSTA|ALBUM|ROK):
${albums.join('\n')}`;
}

export function parseBrutalAssaultBulkDescriptionJson(value) {
  let clean = String(value || '').trim();
  clean = clean.replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/, '').trim();
  if (!clean) throw new Error('Wklej odpowiedź JSON z AI.');

  let parsed;
  try {
    parsed = JSON.parse(clean);
  } catch {
    throw new Error('To nie jest poprawny JSON. Poproś AI o sam obiekt JSON bez komentarza.');
  }

  let source = parsed?.descriptions ?? parsed;
  if (Array.isArray(source)) {
    source = Object.fromEntries(source.map((item) => [
      item?.rowId ?? item?.id,
      item?.description,
    ]));
  }
  if (!source || typeof source !== 'object' || Array.isArray(source)) {
    throw new Error('JSON musi być obiektem: {"ID":"opis"}.');
  }

  const entries = Object.entries(source);
  if (!entries.length) throw new Error('JSON nie zawiera żadnych opisów.');
  if (entries.length > 50) throw new Error('Jedna paczka może zawierać maksymalnie 50 opisów.');

  const descriptions = {};
  entries.forEach(([rawId, rawDescription]) => {
    const id = Number(rawId);
    const description = String(rawDescription || '').trim();
    if (!Number.isInteger(id) || id <= 0) throw new Error(`Nieprawidłowe ID albumu: ${rawId}.`);
    if (!description) throw new Error(`Opis albumu ${id} jest pusty.`);
    if (description.length > 4000) throw new Error(`Opis albumu ${id} przekracza 4000 znaków.`);
    descriptions[String(id)] = description;
  });
  return descriptions;
}

function normalizedDescriptionOpening(description) {
  const shortSection = String(description || '')
    .split(/\[W SKRÓCIE\]/i)[1]
    ?.split(/\[CIEKAWOSTKI\]/i)[0] || String(description || '');
  return shortSection
    .replace(/^\s*[•*-].*$/gm, ' ')
    .replace(/\[[^\]]+\]/g, ' ')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .match(/[a-z0-9]+/g)
    ?.slice(0, 3)
    .join(' ') || '';
}

export function validateRymDescriptionBatch(descriptions) {
  const openings = new Map();
  const repetitiveRecommendation = /\bwarto\s+(?:(?:go|ją|ich)\s+)?(?:posłuchać|włączyć)(?=\s|[.,;:!?…]|$)/iu;

  Object.entries(descriptions || {}).forEach(([id, rawDescription]) => {
    const description = String(rawDescription || '').trim();
    if (repetitiveRecommendation.test(description)) {
      throw new Error(`Opis albumu ${id} zawiera zakazaną szablonową formułę „Warto posłuchać / włączyć”.`);
    }
    const opening = normalizedDescriptionOpening(description);
    if (!opening) return;
    const previousId = openings.get(opening);
    if (previousId) {
      throw new Error(`Opisy albumów ${previousId} i ${id} zaczynają się tak samo („${opening}”). Zróżnicuj otwarcia.`);
    }
    openings.set(opening, id);
  });
  return descriptions;
}

async function copyRymPromptText(prompt) {
  if (globalThis.navigator?.clipboard?.writeText) {
    try {
      await globalThis.navigator.clipboard.writeText(prompt);
      return;
    } catch {
      // Fall back to a temporary textarea when clipboard permission is blocked.
    }
  }
  const textarea = document.createElement('textarea');
  textarea.value = prompt;
  textarea.style.position = 'fixed';
  textarea.style.opacity = '0';
  document.body.appendChild(textarea);
  textarea.select();
  const copied = document.execCommand('copy');
  textarea.remove();
  if (!copied) throw new Error('Clipboard is unavailable');
}

export async function copyRymPolishBlackMetalAlbumPrompt(row) {
  return copyRymPromptText(buildRymPolishBlackMetalAlbumPrompt(row));
}

export async function copyBrutalAssaultAlbumPrompt(row) {
  const prompt = buildBrutalAssaultAlbumPrompt(row);
  if (globalThis.navigator?.clipboard?.writeText) {
    try {
      await globalThis.navigator.clipboard.writeText(prompt);
      return;
    } catch {
      // Some browsers expose Clipboard API but block it; use the local fallback.
    }
  }
  const textarea = document.createElement('textarea');
  textarea.value = prompt;
  textarea.style.position = 'fixed';
  textarea.style.opacity = '0';
  document.body.appendChild(textarea);
  textarea.select();
  const copied = document.execCommand('copy');
  textarea.remove();
  if (!copied) throw new Error('Clipboard is unavailable');
}

function dateParts(value) {
  if (value instanceof Date && Number.isFinite(value.getTime())) {
    return [value.getFullYear(), value.getMonth() + 1, value.getDate()];
  }
  const match = String(value || '').match(/^(\d{4})-(\d{2})-(\d{2})/);
  return match ? match.slice(1).map(Number) : null;
}

function utcDayNumber(value) {
  const parts = dateParts(value);
  return parts ? Date.UTC(parts[0], parts[1] - 1, parts[2]) / 86400000 : null;
}

function isBrutalAssaultRecommendationAvailable(row, today) {
  const key = `${artistKey(row?.artist)}::${artistKey(row?.album)}`;
  const releaseDate = BRUTAL_ASSAULT_RECOMMENDATION_RELEASE_DATES.get(key);
  if (!releaseDate) return true;
  const todayDay = utcDayNumber(today);
  const releaseDay = utcDayNumber(releaseDate);
  return todayDay === null || releaseDay === null || todayDay >= releaseDay;
}

export function computeBrutalAssaultDeadlineStats(rows, today = new Date()) {
  const source = Array.isArray(rows) ? rows : [];
  const remainingRows = source.filter((row) => row && !row.listened);
  const rowsWithMinutes = remainingRows.filter((row) => Number.isFinite(row.minutes));
  const todayDay = utcDayNumber(today);
  const deadlineDay = utcDayNumber(BRUTAL_ASSAULT_2027_DEADLINE);
  const daysLeft = todayDay === null || deadlineDay === null
    ? 0
    : Math.max(0, deadlineDay - todayDay);
  const remainingMinutes = rowsWithMinutes.reduce((sum, row) => sum + row.minutes, 0);

  return {
    deadline: BRUTAL_ASSAULT_2027_DEADLINE,
    daysLeft,
    albumCount: remainingRows.length,
    albumsWithMinutes: rowsWithMinutes.length,
    missingMinutes: remainingRows.length - rowsWithMinutes.length,
    remainingMinutes,
    albumsPerDay: daysLeft > 0 ? remainingRows.length / daysLeft : null,
    minutesPerDay: daysLeft > 0 ? remainingMinutes / daysLeft : null,
  };
}

function formatDeadlineDecimal(value, digits = 2) {
  return Number(value).toLocaleString('pl-PL', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function deadlineMetric(documentRef, value, label) {
  const metric = documentRef.createElement('div');
  metric.className = 'ba2027-deadline-metric';

  const strong = documentRef.createElement('strong');
  strong.textContent = value;
  const span = documentRef.createElement('span');
  span.textContent = label;

  metric.append(strong, span);
  return metric;
}

export function renderBrutalAssaultDeadlineSummary(element, stats) {
  if (!element || !stats) return;
  const documentRef = element.ownerDocument || document;
  element.replaceChildren();
  element.classList.add('ba2027-deadline-summary');
  element.hidden = false;

  const head = documentRef.createElement('div');
  head.className = 'ba2027-deadline-head';
  const eyebrow = documentRef.createElement('span');
  eyebrow.textContent = 'Brutal Assault 2027';
  const headline = documentRef.createElement('strong');

  if (!stats.albumCount) {
    headline.textContent = 'Wszystko przesłuchane';
    head.append(eyebrow, headline);
    element.appendChild(head);
    return;
  }

  headline.textContent = stats.daysLeft > 0
    ? `${stats.daysLeft} dni do startu`
    : 'Festiwal już się rozpoczął';
  head.append(eyebrow, headline);

  const metrics = documentRef.createElement('div');
  metrics.className = 'ba2027-deadline-metrics';
  metrics.append(
    deadlineMetric(
      documentRef,
      stats.albumsPerDay === null ? '—' : formatDeadlineDecimal(stats.albumsPerDay),
      'albumu dziennie'
    ),
    deadlineMetric(
      documentRef,
      stats.minutesPerDay === null ? '—' : `${Math.ceil(stats.minutesPerDay)} min`,
      'słuchania dziennie'
    )
  );

  const footer = documentRef.createElement('div');
  footer.className = 'ba2027-deadline-footer';
  const footerParts = [];
  if (stats.albumsPerDay > 0) {
    footerParts.push(`1 album co ${formatDeadlineDecimal(1 / stats.albumsPerDay, 1)} dnia`);
  }
  footerParts.push('start 4 sierpnia 2027');
  if (stats.missingMinutes) {
    footerParts.push(`${stats.missingMinutes} bez podanego czasu`);
  }
  footer.textContent = footerParts.join(' • ');

  element.append(head, metrics, footer);
}

function compareAlbums(a, b) {
  const aRating = a?.rymRating === null || a?.rymRating === undefined || a?.rymRating === ''
    ? null
    : Number(a.rymRating);
  const bRating = b?.rymRating === null || b?.rymRating === undefined || b?.rymRating === ''
    ? null
    : Number(b.rymRating);
  const normalizedARating = Number.isFinite(aRating) ? aRating : null;
  const normalizedBRating = Number.isFinite(bRating) ? bRating : null;
  if (normalizedARating !== null || normalizedBRating !== null) {
    if (normalizedARating === null) return 1;
    if (normalizedBRating === null) return -1;
    if (normalizedBRating !== normalizedARating) return normalizedBRating - normalizedARating;
  }

  const artistDifference = String(a?.artist || '').localeCompare(String(b?.artist || ''), 'pl');
  if (artistDifference) return artistDifference;
  const albumDifference = String(a?.album || '').localeCompare(String(b?.album || ''), 'pl');
  if (albumDifference) return albumDifference;
  return Number(a?.rowId || 0) - Number(b?.rowId || 0);
}

export function isUnheardArtist(row, rows) {
  const key = artistKey(row?.artist);
  return Boolean(key) && !(rows || []).some((candidate) => (
    candidate?.listened && artistKey(candidate.artist) === key
  ));
}

export function buildBrutalAssaultRecommendationQueue(rows, today = new Date()) {
  const source = Array.isArray(rows) ? rows : [];
  const pending = source.filter((row) => (
    row && !row.listened && isBrutalAssaultRecommendationAvailable(row, today)
  ));
  const heardArtists = new Set(
    source.filter((row) => row?.listened).map((row) => artistKey(row.artist)).filter(Boolean)
  );
  const firstUnheardAlbumByArtist = new Map();

  pending.forEach((row) => {
    const key = artistKey(row.artist);
    if (!key || heardArtists.has(key)) return;
    const current = firstUnheardAlbumByArtist.get(key);
    if (!current || compareAlbums(row, current) < 0) {
      firstUnheardAlbumByArtist.set(key, row);
    }
  });

  const firstWave = [...firstUnheardAlbumByArtist.values()].sort(compareAlbums);
  const firstWaveRows = new Set(firstWave);
  const mixedArtistOrder = new Map(
    buildBrutalAssaultArtistRatingRankings(source).mixed
      .map((entry, index) => [artistKey(entry.artist), index])
  );
  const remaining = pending
    .filter((row) => !firstWaveRows.has(row))
    .sort((a, b) => {
      const aRank = mixedArtistOrder.get(artistKey(a.artist));
      const bRank = mixedArtistOrder.get(artistKey(b.artist));
      const normalizedARank = Number.isInteger(aRank) ? aRank : Number.MAX_SAFE_INTEGER;
      const normalizedBRank = Number.isInteger(bRank) ? bRank : Number.MAX_SAFE_INTEGER;
      return normalizedARank - normalizedBRank || compareAlbums(a, b);
    });

  return [...firstWave, ...remaining];
}

export function communityRatingLabel(row) {
  const rating = communityRating(row);
  if (rating === null) return '';
  const rymRating = row?.rymRating === null || row?.rymRating === undefined || row?.rymRating === ''
    ? null
    : Number(row.rymRating);
  if (Number.isFinite(rymRating)) return `Rate Your Music ${rymRating.toFixed(2)}/5`;
  const votes = Number(row?.communityVotes || 0);
  const source = String(row?.communitySource || 'MusicBrainz').trim();
  const formatted = source === 'Rate Your Music'
    ? rating.toFixed(2)
    : rating.toFixed(1);
  return `${source} ${formatted}/5${votes ? ` · ${votes} gł.` : ''}`;
}

export function brutalAssaultMixedRating(row) {
  const rym = Number(row?.rymRating);
  const own = Number(row?.rating);
  const hasRym = row?.rymRating !== null && row?.rymRating !== undefined && row?.rymRating !== ''
    && Number.isFinite(rym);
  const hasOwn = row?.rating !== null && row?.rating !== undefined && row?.rating !== ''
    && Number.isFinite(own);
  return hasRym && hasOwn ? (rym + own) / 2 : null;
}

export function sortBrutalAssaultAlbumsByRating(rows, mode = 'own') {
  const scoreFor = (row) => {
    if (mode === 'rym') {
      const value = Number(row?.rymRating);
      return row?.rymRating !== null && row?.rymRating !== undefined && row?.rymRating !== ''
        && Number.isFinite(value) ? value : null;
    }
    if (mode === 'mixed') return brutalAssaultMixedRating(row);
    const value = Number(row?.rating);
    return row?.rating !== null && row?.rating !== undefined && row?.rating !== ''
      && Number.isFinite(value) ? value : null;
  };

  return (Array.isArray(rows) ? rows : [])
    .map((row) => ({ row, score: scoreFor(row) }))
    .filter((item) => item.score !== null)
    .sort((a, b) => (
      b.score - a.score
      || String(a.row?.artist || '').localeCompare(String(b.row?.artist || ''), 'pl')
      || String(a.row?.album || '').localeCompare(String(b.row?.album || ''), 'pl')
      || Number(a.row?.rowId || 0) - Number(b.row?.rowId || 0)
    ))
    .map((item) => item.row);
}

export function buildBrutalAssaultArtistRatingRankings(rows) {
  const artists = new Map();
  (Array.isArray(rows) ? rows : []).forEach((row) => {
    const key = artistKey(row?.artist);
    if (!key) return;
    const entry = artists.get(key) || {
      artist: String(row.artist || '').trim(),
      rymTotal: 0,
      rymCount: 0,
      ownTotal: 0,
      ownCount: 0,
      bestRymAlbum: null,
      bestOwnAlbum: null,
      bestMixedAlbum: null,
    };
    const rym = row?.rymRating === null || row?.rymRating === undefined || row?.rymRating === ''
      ? null : Number(row.rymRating);
    const own = row?.rating === null || row?.rating === undefined || row?.rating === ''
      ? null : Number(row.rating);
    const mixed = brutalAssaultMixedRating(row);
    if (Number.isFinite(rym)) {
      entry.rymTotal += rym;
      entry.rymCount += 1;
      if (!entry.bestRymAlbum || rym > entry.bestRymAlbum.score) {
        entry.bestRymAlbum = { album: row.album, score: rym };
      }
    }
    if (Number.isFinite(own)) {
      entry.ownTotal += own;
      entry.ownCount += 1;
      if (!entry.bestOwnAlbum || own > entry.bestOwnAlbum.score) {
        entry.bestOwnAlbum = { album: row.album, score: own };
      }
    }
    if (mixed !== null && (!entry.bestMixedAlbum || mixed > entry.bestMixedAlbum.score)) {
      entry.bestMixedAlbum = { album: row.album, score: mixed };
    }
    artists.set(key, entry);
  });

  const values = [...artists.values()].map((entry) => {
    const rymAverage = entry.rymCount ? entry.rymTotal / entry.rymCount : null;
    const ownAverage = entry.ownCount ? entry.ownTotal / entry.ownCount : null;
    return {
      ...entry,
      rymAverage,
      ownAverage,
      mixedAverage: rymAverage !== null && ownAverage !== null
        ? (rymAverage + ownAverage) / 2
        : null,
    };
  });
  const ranked = (field) => values
    .filter((entry) => entry[field] !== null)
    .sort((a, b) => (
      b[field] - a[field]
      || (b.rymCount + b.ownCount) - (a.rymCount + a.ownCount)
      || a.artist.localeCompare(b.artist, 'pl')
    ));
  return {
    rym: ranked('rymAverage'),
    own: ranked('ownAverage'),
    mixed: ranked('mixedAverage'),
  };
}
