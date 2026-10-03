import {
  getCleaningSettings,
  saveCleaningSettings,
} from './cleaning-api.js';

const STORAGE_KEY = 'cleaning.apartment.v1';

export const CLEANING_APARTMENTS = Object.freeze([
  {
    id: 'aleja-pokoju6',
    label: 'Mieszkanie',
    sheetName: 'sprzatanie_tracker_detailed_aleja_pokoju6',
  },
  {
    id: 'classic',
    label: 'Poprzedni setup',
    sheetName: 'sprzatanie_tracker_detailed',
  },
]);

export const DEFAULT_CLEANING_APARTMENT_ID = CLEANING_APARTMENTS[0].id;

const canUseStorage = () => typeof window !== 'undefined' && !!window.localStorage;
let activeApartmentCache = null;

function readLocalActiveApartmentId() {
  if (!canUseStorage()) return DEFAULT_CLEANING_APARTMENT_ID;
  return window.localStorage.getItem(STORAGE_KEY) || DEFAULT_CLEANING_APARTMENT_ID;
}

async function hydrateActiveApartment() {
  let server = null;
  try {
    server = await getCleaningSettings();
  } catch {}
  const localId = readLocalActiveApartmentId();
  const nextId = findCleaningApartment(server?.activeApartmentId || server?.settings?.activeApartmentId || localId).id;
  activeApartmentCache = nextId;
  if (canUseStorage()) {
    window.localStorage.setItem(STORAGE_KEY, nextId);
  }
  if (!server?.activeApartmentId && !server?.settings?.activeApartmentId) {
    saveCleaningSettings({ activeApartmentId: nextId }).catch(() => {});
  }
}

hydrateActiveApartment().catch(() => {});

export function findCleaningApartment(id) {
  return CLEANING_APARTMENTS.find((apartment) => apartment.id === id) || CLEANING_APARTMENTS[0];
}

export function getActiveCleaningApartmentId() {
  const saved = activeApartmentCache || readLocalActiveApartmentId();
  return findCleaningApartment(saved).id;
}

export function getActiveCleaningApartment() {
  return findCleaningApartment(getActiveCleaningApartmentId());
}

export function setActiveCleaningApartment(id) {
  const apartment = findCleaningApartment(id);
  if (canUseStorage()) {
    window.localStorage.setItem(STORAGE_KEY, apartment.id);
  }
  activeApartmentCache = apartment.id;
  saveCleaningSettings({ activeApartmentId: apartment.id }).catch(() => {});
  return apartment;
}

export function getCleaningApartmentHistoryKey(baseKey) {
  return `${baseKey}.${getActiveCleaningApartmentId()}`;
}
