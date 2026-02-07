// export-habits.js
// Usage: node export-habits.js "Loop Habits Backup 2025-10-25 163924.db"

import fs from 'fs';
import sqlite3 from 'sqlite3';
import { open } from 'sqlite';

// helper: start of day (local) -> ms since epoch
function startOfDayMs(d = new Date()) {
  const tmp = new Date(d.getFullYear(), d.getMonth(), d.getDate(), 0, 0, 0, 0);
  return tmp.getTime();
}

// yyyy-mm-dd
function isoDay(ms) {
  const d = new Date(ms);
  return d.toISOString().slice(0, 10);
}

// streak = consecutive days (including today) where the habit has any entry
// "any entry" means: for that day, at least one repetition row exists
function calcStreak(doneDaySet, todayStartMs) {
  let streak = 0;
  let day = todayStartMs;
  while (doneDaySet.has(day.toString())) {
    streak += 1;
    day -= 24 * 60 * 60 * 1000;
  }
  return streak;
}

// scaleLoopDose:
// Loop zapisuje dawki jako wartość *1000 (np. 60000 => 60 mg, 950000 => 950 µg).
// Dzielimy tylko jeśli to jest liczba dawki, NIE jeśli to jest znacznik "2" (DONE).
function scaleLoopDose(rawValue, unit) {
  if (rawValue == null) return rawValue;

  // "2" to boolean DONE, nie dawka
  if (rawValue === 2) return rawValue;

  // tylko leki / suplementy w mg / µg / ug chcemy dzielić
  if (!unit) return rawValue;

  const u = unit.toLowerCase();
  if (u.includes('mg') || u.includes('µg') || u.includes('ug')) {
    return rawValue / 1000;
  }

  // np. push-ups, streaki, inne jednostki zostają jak są
  return rawValue;
}

async function main() {
  const dbPath = process.argv[2];
  if (!dbPath) {
    console.error("Pass path to .db file");
    process.exit(1);
  }

  const db = await open({
    filename: dbPath,
    driver: sqlite3.Database
  });

  // 1. All habits
  const habits = await db.all(`
    SELECT
      Id            AS id,
      name          AS name,
      archived      AS archived,
      unit          AS unit,
      target_type   AS targetType,
      target_value  AS targetValue,
      freq_num      AS freqNum,
      freq_den      AS freqDen
    FROM Habits
  `);

  // 2. All repetitions
  // timestamp in ms
  // value is 2 for yes/no "done"
  // value can also be numeric amount like 60000 (mg), 150000 (mg), etc.
  const reps = await db.all(`
    SELECT
      habit,
      timestamp,
      value
    FROM Repetitions
  `);

  const todayStart = startOfDayMs(new Date());

  // Group reps per habit
  const byHabit = {};
  for (const r of reps) {
    if (!byHabit[r.habit]) byHabit[r.habit] = [];
    byHabit[r.habit].push(r);
  }

  const out = [];

  // build per-habit objects
  for (const h of habits) {
    const rows = byHabit[h.id] || [];

    // Map of dayStartMs -> array of values for that day
    const perDay = new Map();

    for (const r of rows) {
      const dayStart = startOfDayMs(new Date(r.timestamp));
      if (!perDay.has(dayStart)) perDay.set(dayStart, []);
      perDay.get(dayStart).push(r.value);
      // lastDoneMs liczymy niżej
    }

    // figure out today info
    const todaysVals = perDay.get(todayStart) || [];

    // doneToday = jakikolwiek wpis w tym dniu
    const doneToday = todaysVals.length > 0;

    // wybór wartości do wyświetlenia
    // - numeric amount (np. dawka) -> największa niezerowa
    // - jeśli tylko 2 (DONE) -> DONE
    // - jeśli brak -> frontend pokaże MISSED
    let todayValueRaw = null;
    if (doneToday) {
      const nonZero = todaysVals.filter(v => v !== 0 && v !== null);
      if (nonZero.length > 0) {
        todayValueRaw = nonZero.sort((a, b) => b - a)[0];
      } else {
        todayValueRaw = todaysVals[0];
      }
    }

    // streak dla tego habitu
    const doneDaySet = new Set(Array.from(perDay.keys()).map(ms => ms.toString()));
    const streakToday = calcStreak(doneDaySet, todayStart);

    // ostatni dzień kiedy coś było logowane
    let lastDoneMs = null;
    for (const r of rows) {
      if (lastDoneMs == null || r.timestamp > lastDoneMs) {
        lastDoneMs = r.timestamp;
      }
    }

    // przeskalowana dawka (dzielimy przez 1000 dla mg/µg/ug)
    const scaledTodayValue = scaleLoopDose(todayValueRaw, h.unit || "");

    out.push({
      id: h.id,
      name: h.name,
      archived: !!h.archived,
      unit: h.unit || "",

      doneToday: doneToday,

      todayValue: scaledTodayValue, // np. 60 zamiast 60000
      todayDisplay: (doneToday
        ? (
            scaledTodayValue != null && scaledTodayValue !== 2
              ? (h.unit ? `${scaledTodayValue} ${h.unit}` : String(scaledTodayValue))
              : 'DONE'
          )
        : null
      ),

      streak: streakToday,
      lastDone: lastDoneMs ? isoDay(lastDoneMs) : null
    });
  } // <- KONIEC for (const h of habits)

  // summary for widget header

  const activeHabits = out.filter(h => !h.archived);
  const doneCount = activeHabits.filter(h => h.doneToday).length;
  const missedCount = activeHabits.length - doneCount;

  // sobriety streak = current "Don't drink" streak
  // 1) find habit "Don't drink"
  const dontDrinkHabit = habits.find(
    h => h.name && h.name.toLowerCase().startsWith("don't drink")
  );

  let sobrietyDays = 0;

  if (dontDrinkHabit) {
    const ddRows = byHabit[dontDrinkHabit.id] || [];

    // perDay for that habit only
    const perDayDD = new Map();
    for (const r of ddRows) {
      const dayStart = startOfDayMs(new Date(r.timestamp));
      if (!perDayDD.has(dayStart)) perDayDD.set(dayStart, []);
      perDayDD.get(dayStart).push(r.value);
    }

    const isSoberDay = vals => vals && vals.some(v => v === 2);

    // walk backward from today until first day without v===2
    let streak = 0;
    let dayPtr = todayStart;
    while (true) {
      const vals = perDayDD.get(dayPtr) || [];
      if (isSoberDay(vals)) {
        streak += 1;
        dayPtr -= 24 * 60 * 60 * 1000;
      } else {
        break;
      }
    }
    sobrietyDays = streak;
  }

  const result = {
    generatedAt: new Date().toISOString(),
    today: isoDay(todayStart),
    sobrietyDays, // ile dni bez alkoholu
    stats: {
      totalActive: activeHabits.length,
      doneToday: doneCount,
      missedToday: missedCount
    },
    habits: activeHabits.sort((a, b) => a.name.localeCompare(b.name))
  };

  fs.writeFileSync(
    './public/data/habits.json',
    JSON.stringify(result, null, 2),
    'utf8'
  );
  console.log('Wrote public/data/habits.json');
}

main();
