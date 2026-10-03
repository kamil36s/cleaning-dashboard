import { createLanguageApi } from './language/api.js';
import { ankiAchievement } from './language/anki-daily.js';
import { setDailyAchievement } from './daily-achievements.js';

const api = createLanguageApi();
let profileId = null;
let refreshing = false;

export async function refreshDailyAnkiAchievement() {
  if (refreshing) return;
  refreshing = true;
  try {
    if (!profileId) {
      const profiles = await api.profiles();
      profileId = (profiles.items || []).find((item) => item.languageCode === 'nb' && item.locale === 'nb-NO')?.id || null;
    }
    if (!profileId) {
      setDailyAchievement('anki-norwegian', {
        state: 'neutral', value: 'No profile', detail: 'Norwegian profile is unavailable', eligible: false,
      });
      return;
    }
    const status = await api.ankiStatus(profileId);
    if (status.status === 'UNAVAILABLE') {
      setDailyAchievement('anki-norwegian', {
        state: 'error', value: 'Unavailable', detail: 'Open Anki Desktop to refresh', eligible: false,
      });
      return;
    }
    setDailyAchievement('anki-norwegian', ankiAchievement(status.decks || []));
  } catch (error) {
    setDailyAchievement('anki-norwegian', {
      state: 'error', value: 'Unavailable', detail: error?.message || 'Anki data could not be loaded', eligible: false,
    });
  } finally {
    refreshing = false;
  }
}

if (typeof document !== 'undefined' && document.querySelector('[data-daily-achievement="anki-norwegian"]')) {
  refreshDailyAnkiAchievement();
  window.setInterval(() => { if (!document.hidden) refreshDailyAnkiAchievement(); }, 5 * 60 * 1000);
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) refreshDailyAnkiAchievement();
  });
}
