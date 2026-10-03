/**
 * Moving Countdown Widget
 * Displays the exact countdown until the move.
 */

const MOVING_DATE = new Date(2026, 3, 30, 14, 0, 0);
const CARD_ID = 'moving-countdown-card';
const DAYS_ID = 'moving-countdown-days';
const HOURS_ID = 'moving-countdown-hours';
const MINUTES_ID = 'moving-countdown-minutes';
const SECONDS_ID = 'moving-countdown-seconds';
const TEXT_ID = 'moving-countdown-text';
const NOTE_ID = 'moving-countdown-note';
const META_ID = 'moving-countdown-meta';
const CHIP_ID = 'moving-countdown-chip';
const SECOND_MS = 1000;
const MINUTE_MS = 60 * SECOND_MS;
const HOUR_MS = 60 * MINUTE_MS;
const DAY_MS = 24 * HOUR_MS;

function capitalize(value) {
  if (!value) return '';
  return `${value.charAt(0).toUpperCase()}${value.slice(1)}`;
}

function padTime(value) {
  return String(Math.max(0, value)).padStart(2, '0');
}

function calculateTimeRemaining() {
  const totalMs = Math.max(0, MOVING_DATE.getTime() - Date.now());
  const days = Math.floor(totalMs / DAY_MS);
  const hours = Math.floor((totalMs % DAY_MS) / HOUR_MS);
  const minutes = Math.floor((totalMs % HOUR_MS) / MINUTE_MS);
  const seconds = Math.floor((totalMs % MINUTE_MS) / SECOND_MS);
  return {
    totalMs,
    days,
    hours,
    minutes,
    seconds,
  };
}

function formatMoveDate() {
  return MOVING_DATE.toLocaleDateString('pl-PL', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  });
}

function formatMoveWeekday() {
  return capitalize(MOVING_DATE.toLocaleDateString('pl-PL', {
    weekday: 'long',
  }));
}

function formatMoveTime() {
  return MOVING_DATE.toLocaleTimeString('pl-PL', {
    hour: '2-digit',
    minute: '2-digit',
  });
}

function getCountdownCopy(totalMs) {
  if (totalMs <= 0) {
    return {
      tone: 'is-today',
      label: 'Do przeprowadzki',
      chip: 'Start',
      meta: 'Odliczanie do przeprowadzki',
    };
  }

  if (totalMs <= 6 * HOUR_MS) {
    return {
      tone: 'is-soon',
      label: 'Do przeprowadzki',
      chip: 'Dzisiaj',
      meta: 'Odliczanie do przeprowadzki',
    };
  }

  if (totalMs <= DAY_MS) {
    return {
      tone: 'is-soon',
      label: 'Do przeprowadzki',
      chip: 'Mniej niz doba',
      meta: 'Odliczanie do przeprowadzki',
    };
  }

  if (totalMs <= 7 * DAY_MS) {
    return {
      tone: 'is-soon',
      label: 'Do przeprowadzki',
      chip: 'Niedlugo',
      meta: 'Odliczanie do przeprowadzki',
    };
  }

  return {
    tone: 'is-upcoming',
    label: 'Do przeprowadzki',
    chip: 'W planie',
    meta: 'Odliczanie do przeprowadzki',
  };
}

function updateCountdown() {
  const card = document.getElementById(CARD_ID);
  const daysEl = document.getElementById(DAYS_ID);
  const hoursEl = document.getElementById(HOURS_ID);
  const minutesEl = document.getElementById(MINUTES_ID);
  const secondsEl = document.getElementById(SECONDS_ID);
  const textEl = document.getElementById(TEXT_ID);
  const noteEl = document.getElementById(NOTE_ID);
  const metaEl = document.getElementById(META_ID);
  const chipEl = document.getElementById(CHIP_ID);

  if (
    !card
    || !daysEl
    || !hoursEl
    || !minutesEl
    || !secondsEl
    || !textEl
    || !noteEl
    || !metaEl
    || !chipEl
  ) {
    return;
  }

  const remaining = calculateTimeRemaining();
  const copy = getCountdownCopy(remaining.totalMs);
  const moveDate = formatMoveDate();
  const moveWeekday = formatMoveWeekday();
  const moveTime = formatMoveTime();

  daysEl.textContent = padTime(remaining.days);
  hoursEl.textContent = padTime(remaining.hours);
  minutesEl.textContent = padTime(remaining.minutes);
  secondsEl.textContent = padTime(remaining.seconds);
  textEl.textContent = copy.label;
  noteEl.textContent = `${moveWeekday}, ${moveDate}, ${moveTime}`;
  metaEl.textContent = copy.meta;
  chipEl.textContent = copy.chip;

  card.classList.remove('is-today', 'is-soon', 'is-upcoming');
  card.classList.add(copy.tone);
}

updateCountdown();

setInterval(updateCountdown, SECOND_MS);

document.addEventListener('visibilitychange', () => {
  if (!document.hidden) {
    updateCountdown();
  }
});
