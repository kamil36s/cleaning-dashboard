import { onDomReady } from './dom-ready.js';
import { fmtDateTimeShort } from './utils.js';
import { setDailyAchievement } from './daily-achievements.js';
import {
  dateKey,
  summarizeHabitsForDashboard,
  readPreviewMutations,
} from './habits-app-model.js';
import {
  resolveDontDrinkHabitState,
  isDontDrinkConfirmedToday,
} from './sobriety-streak.js';

let liveHabits = null;

async function getHabitsState() {
  const res = await fetch('./data/habits.json', { cache: 'no-store' });
  if (!res.ok) throw new Error('habits fetch failed');
  return res.json();
}

function $(sel) {
  return document.querySelector(sel);
}

function polishSobrietyDays(days) {
  return `${days} ${days === 1 ? 'dzień' : 'dni'}`;
}

function getCurrentDontDrinkState() {
  const habits = liveHabits
    || (Array.isArray(window.HABIT_DB?.habits) ? window.HABIT_DB.habits : []);
  return resolveDontDrinkHabitState(habits, dateKey(new Date()), readPreviewMutations());
}

function renderCurrentSobriety(soberNum) {
  const current = getCurrentDontDrinkState();
  if (!current) return false;
  if (soberNum) soberNum.textContent = String(current.days);
  setDailyAchievement('sobriety', {
    state: current.confirmedToday ? 'complete' : 'pending',
    value: polishSobrietyDays(current.days),
    detail: current.confirmedToday ? 'Dzisiejszy dzień potwierdzony' : 'Seria potwierdzona do wczoraj',
  });
  return true;
}

// Category assignment.
// You can edit this list anytime without touching export-habits.js.
function categorizeHabit(name) {
  // normalize for matching
  const n = name.toLowerCase();

  // Meds (prescription / psychoactive)
  if (
    n.includes('duloxetine') ||
    n.includes('concerta') ||
    n.includes('atenza') ||
    n.includes('medikinet cr') ||
    n.includes('medikinet ir') ||
    n.includes('pregabalin')
  ) {
    return 'Meds';
  }

  // Supplements / vitamins / minerals / nootropics
  if (
    n.includes('ashwagand') ||
    n.includes('b12') ||
    n.includes('biotyn') ||
    n.includes('complex') ||
    n.includes('kolagen') ||
    n.includes("lion's mane") ||
    n.includes('magnes') ||
    n.includes('omega 3') ||
    n.includes('vitamin') ||
    n.includes('vitaminy') ||
    n.includes('vitamin d') ||
    n.includes('zinc') ||
    n.includes('c ') || // Vitamin C
    n === 'vitamin c'
  ) {
    return 'Supplements';
  }

  // Habits (behavioral / lifestyle)
  if (
    n.includes("don't drink") ||
    n.includes("don't smoke cigarettes") ||
    n.includes("don't smoke weed") ||
    n.includes('push-ups') ||
    n.includes('meditation') ||
    n.includes('add 10 sentences') // the Anki/języki habit
  ) {
    return 'Habits';
  }

  // fallback
  return 'Other';
}

function createHabitItem(h) {
  const li = document.createElement('li');
  li.className = 'hb-item';

  const nameSpan = document.createElement('span');
  nameSpan.className = 'hb-name';
  nameSpan.textContent = h.name;

  const flag = document.createElement('span');
  if (h.doneToday) {
    flag.className = 'hb-flag ok';
    flag.textContent = h.todayDisplay || 'DONE';
  } else {
    flag.className = h.recordedZero ? 'hb-flag recorded-zero' : 'hb-flag missed';
    flag.textContent = h.todayDisplay || 'MISSED';
  }

  li.appendChild(nameSpan);
  li.appendChild(flag);

  return li;
}


// Render one category block:
// <div class="hb-group">
//   <h4 class="hb-cat">Supplements</h4>
//   <ul class="hb-list"> ...hb-item... </ul>
// </div>
function renderCategoryBlock(catName, habitsInCat) {
  if (!habitsInCat.length) return null;

  const wrap = document.createElement('div');
  wrap.className = 'hb-group';

  const header = document.createElement('h4');
  header.className = 'hb-cat';
  header.textContent = catName;

  const ul = document.createElement('ul');
  ul.className = 'hb-list';

  habitsInCat.forEach(h => {
    ul.appendChild(createHabitItem(h));
  });

  wrap.appendChild(header);
  wrap.appendChild(ul);

  return wrap;
}

onDomReady(async () => {
  const card = document.querySelector('.card.habits');
  if (!card) return;

  const doneEl   = $('#hb-done');
  const missEl   = $('#hb-missed');
  const totalEl  = $('#hb-total');
  const groupsEl = $('#hb-groups');
  const footEl   = $('#hb-foot');
  const subEl    = $('#hb-sub');
  const soberNum = $('#hb-sober-num');
  if (Array.isArray(window.HABITS_APP_LIVE_DATA?.habits)) {
    liveHabits = window.HABITS_APP_LIVE_DATA.habits;
  }
  let hasCurrentSobriety = renderCurrentSobriety(soberNum);

  function renderHabitSummary(data) {
    doneEl.textContent = data.stats.doneToday;
    missEl.textContent = data.stats.missedToday;
    totalEl.textContent = data.stats.totalActive;
    subEl.textContent = `Dzisiejszy status nawyków (${data.today})`;
    const buckets = { Habits: [], Meds: [], Supplements: [], Other: [] };
    data.habits.forEach((habit) => {
      const category = categorizeHabit(habit.name);
      buckets[category].push(habit);
    });
    groupsEl.replaceChildren();
    ['Habits', 'Meds', 'Supplements', 'Other'].forEach((category) => {
      const block = renderCategoryBlock(category, buckets[category]);
      if (block) groupsEl.appendChild(block);
    });
  }

  function renderLiveSummary() {
    if (!Array.isArray(liveHabits)) return false;
    renderHabitSummary(summarizeHabitsForDashboard(liveHabits, dateKey(new Date()), readPreviewMutations()));
    if (footEl) footEl.textContent = 'Dane z synchronizacji Habits App';
    return true;
  }

  document.addEventListener('habits-app:data-updated', (event) => {
    if (!Array.isArray(event.detail?.habits)) return;
    liveHabits = event.detail.habits;
    hasCurrentSobriety = renderCurrentSobriety(soberNum) || hasCurrentSobriety;
    renderLiveSummary();
  });

  const habitsAppRoot = document.getElementById('habits-app-root');
  if (habitsAppRoot) {
    const observer = new MutationObserver(() => {
      hasCurrentSobriety = renderCurrentSobriety(soberNum) || hasCurrentSobriety;
    });
    observer.observe(habitsAppRoot, { childList: true, subtree: true });
  }
  window.addEventListener('storage', (event) => {
    if (event.key === 'habits.app.preview-mutations.v1') {
      hasCurrentSobriety = renderCurrentSobriety(soberNum) || hasCurrentSobriety;
      renderLiveSummary();
    }
  });

  try {
    const data = await getHabitsState();

    // Awaryjny fallback dla instalacji bez aktualnego HABIT_DB.
    if (!hasCurrentSobriety) {
      const sobrietyDays = Math.max(0, Math.round(Number(data.sobrietyDays) || 0));
      const dontDrinkHabit = (Array.isArray(data.habits) ? data.habits : [])
        .find((habit) => String(habit?.name || '').toLowerCase().startsWith("don't drink"));
      const sobrietyConfirmedToday = isDontDrinkConfirmedToday(dontDrinkHabit);
      if (soberNum) soberNum.textContent = String(sobrietyDays);
      setDailyAchievement('sobriety', {
        state: sobrietyConfirmedToday ? 'complete' : 'pending',
        value: polishSobrietyDays(sobrietyDays),
        detail: sobrietyConfirmedToday ? 'Dzisiejszy dzień potwierdzony' : 'Seria potwierdzona do wczoraj',
      });
    }

    if (!renderLiveSummary()) renderHabitSummary(data);

    // footer
    const ts = new Date(data.generatedAt);
    if (footEl && !footEl.hasAttribute('data-fixed')) {
      footEl.textContent =
        `Ostatnia aktualizacja: ${fmtDateTimeShort(ts)}\n` +
        `Czarna plakietka = streak w dniach`;
    }

  } catch (e) {
    if (renderLiveSummary()) return;
    console.error('[Habits] Error:', e);
    if (!hasCurrentSobriety) {
      setDailyAchievement('sobriety', {
        state: 'error',
        value: 'Brak danych',
        detail: "Nie udało się odczytać Don't Drink",
        eligible: false,
      });
    }
    subEl.textContent = 'Error loading habits';
    if (footEl && !footEl.hasAttribute('data-fixed')) footEl.textContent = 'Brak danych';
  }
});
