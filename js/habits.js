import { fmtDateTimeShort } from './utils.js';

async function getHabitsState() {
  const res = await fetch('./data/habits.json', { cache: 'no-store' });
  if (!res.ok) throw new Error('habits fetch failed');
  return res.json();
}

function $(sel) {
  return document.querySelector(sel);
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
    flag.className = 'hb-flag missed';
    flag.textContent = 'MISSED';
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

document.addEventListener('DOMContentLoaded', async () => {
  const card = document.querySelector('.card.habits');
  if (!card) return;

  const doneEl   = $('#hb-done');
  const missEl   = $('#hb-missed');
  const totalEl  = $('#hb-total');
  const groupsEl = $('#hb-groups');
  const footEl   = $('#hb-foot');
  const subEl    = $('#hb-sub');
  const soberNum = $('#hb-sober-num');

  try {
    const data = await getHabitsState();

    // sobriety banner
    soberNum.textContent = data.sobrietyDays ?? 0;

    // header pills
    doneEl.textContent  = data.stats.doneToday;
    missEl.textContent  = data.stats.missedToday;
    totalEl.textContent = data.stats.totalActive;

    // subtitle "Dzisiejszy status nawyków (2025-10-24)"
    subEl.textContent = `Dzisiejszy status nawyków (${data.today})`;

    // group habits into buckets
    const buckets = {
      'Habits': [],
      'Meds': [],
      'Supplements': [],
      'Other': []
    };

    data.habits.forEach(h => {
      const cat = categorizeHabit(h.name);
      if (!buckets[cat]) buckets[cat] = [];
      buckets[cat].push(h);
    });

    // order of category rendering
    const order = ['Habits', 'Meds', 'Supplements', 'Other'];

    order.forEach(catName => {
      const block = renderCategoryBlock(catName, buckets[catName] || []);
      if (block) groupsEl.appendChild(block);
    });

    // footer
    const ts = new Date(data.generatedAt);
    if (footEl && !footEl.hasAttribute('data-fixed')) {
      footEl.textContent =
        `Ostatnia aktualizacja: ${fmtDateTimeShort(ts)}\n` +
        `Czarna plakietka = streak w dniach`;
    }

  } catch (e) {
    console.error('[Habits] Error:', e);
    subEl.textContent = 'Error loading habits';
    if (footEl && !footEl.hasAttribute('data-fixed')) footEl.textContent = 'Brak danych';
  }
});
