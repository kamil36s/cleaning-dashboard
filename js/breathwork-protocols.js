// js/breathwork-protocols.js
// Konfiguracja protokołów oddechowych.
// Każdy protokół to lista faz z czasami trwania.
// Aby dodać nowy protokół (np. Box Breathing), wystarczy dodać go do tej tablicy.

/**
 * @typedef {Object} Phase
 * @property {string} id          - Unikalny identyfikator fazy
 * @property {string} label       - Krótki label wyświetlany na ekranie (PL)
 * @property {string} instruction - Dłuższa instrukcja (PL)
 * @property {number} duration    - Czas trwania w sekundach
 * @property {'inhale'|'hold'|'exhale'} type - Typ fazy dla animacji kółka
 */

/**
 * @typedef {Object} Protocol
 * @property {string}  id               - Unikalny identyfikator protokołu
 * @property {string}  name             - Pełna nazwa
 * @property {string}  tagline          - Krótki opis (1 zdanie)
 * @property {string}  rhythm           - Zapis rytmu, np. "4-7-8"
 * @property {number}  cycleDurationSec - Łączny czas jednego cyklu w sekundach
 * @property {number}  defaultCycles    - Domyślna liczba cykli na sesję
 * @property {number}  maxCycles        - Maksymalna liczba cykli
 * @property {Phase[]} phases           - Lista faz protokołu
 */

/** @type {Protocol[]} */
export const PROTOCOLS = [
  {
    id: '4-7-8',
    name: 'Technika 4-7-8',
    tagline: 'Fizjologiczny hack — natychmiastowe przejście w tryb głębokiej regeneracji.',
    rhythm: '4 · 7 · 8',
    cycleDurationSec: 19, // 4 + 7 + 8
    defaultCycles: 4,     // Miesiąc 1: dokładnie 4 cykle
    maxCycles: 8,         // Miesiąc 2+: do 8 cykli
    phases: [
      {
        id: 'inhale',
        label: 'Wdech',
        instruction: 'Zamknij usta — cicho przez nos',
        duration: 4,
        type: 'inhale',
      },
      {
        id: 'hold',
        label: 'Zatrzymaj',
        instruction: 'Całkowicie zablokuj oddech',
        duration: 7,
        type: 'hold',
      },
      {
        id: 'exhale',
        label: 'Wydech',
        instruction: 'Przez usta — głośny świst',
        duration: 8,
        type: 'exhale',
      },
    ],
  },

  // Box Breathing — gotowe do aktywacji w przyszłości:
  // {
  //   id: 'box-4-4-4-4',
  //   name: 'Box Breathing',
  //   tagline: 'Metoda Navy SEAL — równomierne oddychanie kwadratowe.',
  //   rhythm: '4 · 4 · 4 · 4',
  //   cycleDurationSec: 16,
  //   defaultCycles: 5,
  //   maxCycles: 10,
  //   phases: [
  //     { id: 'inhale',   label: 'Wdech',     instruction: 'Przez nos',    duration: 4, type: 'inhale' },
  //     { id: 'hold-in',  label: 'Zatrzymaj', instruction: 'Zablokuj',     duration: 4, type: 'hold'   },
  //     { id: 'exhale',   label: 'Wydech',    instruction: 'Przez usta',   duration: 4, type: 'exhale' },
  //     { id: 'hold-out', label: 'Pauza',     instruction: 'Nie oddychaj', duration: 4, type: 'hold'   },
  //   ],
  // },
];

/**
 * Zwraca protokół po ID lub pierwszy z tablicy (fallback).
 * @param {string} [id]
 * @returns {Protocol}
 */
export function getProtocol(id) {
  return PROTOCOLS.find(p => p.id === id) ?? PROTOCOLS[0];
}
