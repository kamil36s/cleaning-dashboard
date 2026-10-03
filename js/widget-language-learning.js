import { createLanguageApi } from './language/api.js';
import { createKnownWordsControl } from './language/known-words.js';
import { setDailyAchievement } from './daily-achievements.js';
import { ankiAchievement, ankiDailyProgress, mainAnkiDecks } from './language/anki-daily.js';

// User-confirmed Anki daily goals before reliable daily plans were recorded.
const confirmedAnkiCompletionDates = new Set([
  '2026-09-25', '2026-09-26', '2026-09-27', '2026-09-28', '2026-09-29',
]);

export function selectLanguageWidgetProfile(items = []) {
  return items.find((item) => item.languageCode === 'nb' && item.locale === 'nb-NO')
    || items.find((item) => item.status === 'ACTIVE')
    || items[0]
    || null;
}

function renderAnkiWeek(days) {
  if (!Array.isArray(days) || days.length !== 7) return null;
  const section = document.createElement('div');
  section.className = 'language-learning-widget-anki-rhythm';
  const head = document.createElement('div');
  head.className = 'language-learning-widget-anki-rhythm-head';
  const title = document.createElement('span');
  title.textContent = 'Anki streak';
  let streak = 0;
  for (let index = days.length - 1; index >= 0; index -= 1) {
    if (index === days.length - 1 && !(Number(days[index]?.answers) > 0)) continue;
    if (!(Number(days[index]?.answers) > 0)) break;
    streak += 1;
  }
  const count = document.createElement('strong');
  const reachesWeekStart = streak > 0 && streak === days.length - (Number(days.at(-1)?.answers) > 0 ? 0 : 1);
  count.textContent = `${streak}${reachesWeekStart ? '+' : ''} day streak`;
  head.append(title, count);
  const week = document.createElement('div');
  week.className = 'language-learning-widget-anki-week';
  week.setAttribute('aria-label', 'Anki answers over the last 7 days');
  days.forEach((day, index) => {
    const date = new Date(`${day.date}T12:00:00`);
    const answers = Math.max(0, Number(day.answers) || 0);
    const userConfirmed = confirmedAnkiCompletionDates.has(day.date);
    const isComplete = userConfirmed || day.complete === true;
    const item = document.createElement('div');
    item.className = 'language-learning-widget-anki-week-day';
    item.classList.toggle('has-answers', answers > 0);
    item.classList.toggle('is-complete', isComplete);
    item.classList.toggle('is-unknown', answers > 0 && !userConfirmed && day.complete == null);
    item.classList.toggle('is-today', index === days.length - 1);
    item.setAttribute('aria-label', `${date.toLocaleDateString('en-US', { weekday: 'long', month: 'short', day: 'numeric' })}: ${answers} Anki answers`
      + (userConfirmed ? ', daily plan confirmed complete'
        : day.complete == null ? ', historical plan unavailable'
          : day.planned > 0 ? `, ${isComplete ? 'daily plan complete' : 'daily plan incomplete'}` : ''));
    const label = document.createElement('span');
    label.textContent = date.toLocaleDateString('en-US', { weekday: 'narrow' });
    const dot = document.createElement('span');
    dot.className = 'language-learning-widget-anki-week-dot';
    dot.setAttribute('aria-hidden', 'true');
    dot.textContent = answers > 0 ? '✓' : '';
    const value = document.createElement('span');
    value.textContent = String(answers);
    item.append(label, dot, value);
    week.append(item);
  });
  section.append(head, week);
  return section;
}

export function renderLanguageWidget(root, summary) {
  if (!root) return;
  root.replaceChildren();
  if (!summary) {
    const empty = document.createElement('div');
    empty.className = 'language-learning-widget-empty';
    empty.textContent = 'No Language profile is available.';
    root.append(empty);
    return;
  }
  if (summary.policyVersion === 'language.today-summary/v1') {
    const element = (tag, className, value) => {
      const result = document.createElement(tag);
      if (className) result.className = className;
      if (value !== undefined) result.textContent = String(value);
      return result;
    };
    const link = (label, hash, className = 'language-learning-widget-action') => {
      const anchor = element('a', className, label);
      anchor.href = `./language.html${hash}`;
      return anchor;
    };
    const anki = summary.anki || {};
    const cloze = summary.cloze || {};
    const reader = summary.reader || {};
    const allDecks = Array.isArray(anki.decks) ? anki.decks : anki.deck ? [anki.deck] : [];
    const decks = mainAnkiDecks(allDecks);
    const { done: dailyDone, planned: dailyPlanned } = ankiDailyProgress(allDecks);
    const ankiBlock = element('section', 'language-learning-widget-anki');
    const hasDailyProgress = decks.some((item) => Number.isInteger(item.reviewsCompletedToday));
    const dailyPercent = dailyPlanned > 0 ? Math.round(dailyDone / dailyPlanned * 100) : 0;
    if (hasDailyProgress) {
      const today = element('div', 'language-learning-widget-anki-today');
      const caption = element('div');
      caption.append(element('strong', '', 'Anki today'),
        element('span', '', `${dailyDone}/${dailyPlanned} cards · ${dailyPercent}%`
          + (dailyDone > dailyPlanned ? ` · +${dailyDone - dailyPlanned} extra` : '')));
      const bar = element('progress');
      bar.max = Math.max(dailyPlanned, 1);
      bar.value = Math.min(dailyDone, dailyPlanned);
      bar.setAttribute('aria-label', `Anki today: ${dailyDone} of ${dailyPlanned} planned new and review cards`);
      today.append(caption, bar);
      ankiBlock.append(today);
    }
    const deckList = element('div', 'language-learning-widget-deck-list');
    decks.forEach((item) => {
      const deck = element('div', 'language-learning-widget-deck');
      const path = String(item.name || '').split('::');
      const title = link(path.at(-1), '#reviews', 'language-learning-widget-deck-name');
      title.title = item.name;
      title.setAttribute('aria-label', item.name);
      const heading = element('div', 'language-learning-widget-deck-heading');
      heading.append(title);
      deck.append(heading);
      if (item.error) {
        deck.append(element('small', 'language-learning-widget-sync-error', item.error));
      } else {
        const details = element('small', 'language-learning-widget-deck-details',
          `Reviews ${item.due || 0} · New ${item.new || 0}`);
        const done = (item.reviewsCompletedToday || 0) + (item.newCompletedToday || 0);
        const total = (item.reviewsPlannedToday || 0) + (item.newPlannedToday || 0);
        if (Number.isInteger(item.reviewsCompletedToday) && Number.isInteger(item.newCompletedToday)) {
          heading.append(element('strong', 'language-learning-widget-deck-today', `${done}/${total}`));
        } else if (!item.answeredCardsToday && !item.due && !item.new) {
          details.textContent = 'No cards today';
        }
        deck.append(details);
      }
      deckList.append(deck);
    });
    if (decks.length) ankiBlock.append(deckList);
    if (decks.length && Array.isArray(anki.week)) {
      const week = renderAnkiWeek(anki.week);
      if (week) ankiBlock.append(week);
    }
    if (decks.length && anki.config?.autoSync) {
      ankiBlock.append(element('p', 'language-learning-widget-campaign', 'AnkiWeb syncs while this dashboard and Anki Desktop are open.'));
    }
    if (decks.length) {
      ankiBlock.classList.toggle('is-goal-complete', hasDailyProgress && dailyPlanned > 0
        && dailyDone >= dailyPlanned && decks.every((item) => !item.error));
      root.append(ankiBlock);
    }
    if (anki.configured && !allDecks.length) {
      root.append(element('p', 'language-learning-widget-campaign',
        anki.status === 'DECK_MISSING' ? 'Selected Anki deck is missing. Check Language settings.'
          : anki.status === 'UNAVAILABLE' ? `AnkiConnect is not listening at ${anki.config?.endpoint || 'the configured address'}. Open Anki Desktop and check the AnkiConnect add-on.`
            : anki.message || 'Anki counts could not be loaded. Check Language settings.'));
    }
    if (decks.length && !anki.config?.autoSync) {
      root.append(element('p', 'language-learning-widget-campaign', 'Decks from Anki Desktop. Sync AnkiWeb in Language → Reviews to refresh.'));
    }
    const core = element('div', 'language-learning-widget-core');
    const facts = [
      ['Anki · due', !anki.configured ? 'Set up' : anki.status === 'UNAVAILABLE' ? 'Open Anki Desktop' : anki.dueCount == null ? 'No count' : `${anki.dueCount}${anki.stale ? ' · stale' : ''}`, '#reviews'],
    ];
    if (decks.length) facts.shift();
    facts.forEach(([label, value, href]) => {
      const row = link('', href, 'language-learning-widget-core-row');
      row.append(element('span', '', label), element('strong', '', value));
      core.append(row);
    });
    const clozeRow = link('', '#cloze', 'language-learning-widget-core-row language-learning-widget-cloze-row');
    const reviewGoal = Number(cloze.dailyReviewGoal) || 5;
    const newSentenceGoal = Number(cloze.dailyNewSentenceGoal) || 3;
    const reviewedToday = Number(cloze.reviewedToday) || 0;
    const newSentencesToday = Number(cloze.newSentencesToday) || 0;
    clozeRow.classList.toggle('is-goal-complete', reviewedToday >= reviewGoal && newSentencesToday >= newSentenceGoal);
    clozeRow.append(element('span', '', 'Cloze · today'), element('strong', '',
      `Reviews ${reviewedToday}/${reviewGoal} · New ${newSentencesToday}/${newSentenceGoal}`));
    core.append(clozeRow);
    const currentText = reader.continue;
    const readerRow = link('', currentText?.id ? `#reader/text/${encodeURIComponent(currentText.id)}` : '#reader', 'language-learning-widget-core-row language-learning-widget-reader-row');
    const readerInfo = element('div', 'language-learning-widget-reader-info');
    readerInfo.append(element('strong', '', currentText?.title || 'Choose text'));
    if (currentText?.textLength) {
      const read = Math.min(Number(currentText.textLength), Number(currentText.progressSourceOffset) || 0);
      const sentences = currentText.sentenceCount
        ? `${currentText.sentencesRead || 0}/${currentText.sentenceCount} sentences · ` : '';
      readerInfo.append(element('small', '', `${sentences}${Math.round(100 * read / currentText.textLength)}% read`));
    }
    readerRow.append(element('span', '', 'Reader · continue'), readerInfo);
    core.append(readerRow);
    root.append(core);
    const progress = element('p', 'language-learning-widget-campaign',
      `${summary.streakDays || 0} day streak · Level ${summary.level?.level || 1} · ${summary.level?.lifetimeXp || 0} XP`
      + (cloze.answeredToday ? ` · ${cloze.answeredToday} Cloze today` : '')
      + (reader.todaySeconds ? ` · ${Math.floor(reader.todaySeconds / 60)} min reading today` : ''));
    root.append(progress);
    root.append(link('Start a 20 min study session', '#study-session', 'language-learning-widget-action is-primary'));
    return;
  }
  const metrics = document.createElement('div');
  metrics.className = 'language-learning-widget-metrics';
  const metricRows = [
    ['Level', summary.level?.level || 1],
    ['Streak', `${summary.streakDays || 0}d`],
    ['Known', summary.known || 0],
    ['Active · 7d', `${summary.activeMinutes7d || 0}m`],
  ];
  if (Number.isInteger(summary.ankiDueCount)) metricRows.push(['Anki due', summary.ankiDueCount]);
  metricRows.forEach(([label, value]) => {
    const item = document.createElement('div');
    const small = document.createElement('span');
    small.textContent = label;
    const strong = document.createElement('strong');
    strong.textContent = String(value);
    item.append(small, strong);
    metrics.append(item);
  });
  root.append(metrics);
  if (summary.level) {
    const level = document.createElement('div');
    level.className = 'language-learning-widget-goal';
    const copy = document.createElement('div');
    copy.append(
      Object.assign(document.createElement('span'), { textContent: `${summary.level.lifetimeXp} lifetime XP` }),
      Object.assign(document.createElement('strong'), { textContent: `${summary.level.xpNeeded} to next` }),
    );
    const progress = document.createElement('progress');
    progress.max = summary.level.nextLevelXp - summary.level.currentLevelXpFloor;
    progress.value = summary.level.xpIntoLevel;
    progress.setAttribute('aria-label', `${summary.level.xpNeeded} XP to Norwegian Level ${summary.level.level + 1}`);
    level.append(copy, progress);
    root.append(level);
  }
  if (summary.weeklyGoal) {
    const goal = document.createElement('div');
    goal.className = 'language-learning-widget-goal';
    const copy = document.createElement('div');
    copy.append(
      Object.assign(document.createElement('span'), { textContent: 'Weekly goal' }),
      Object.assign(document.createElement('strong'), { textContent: `${summary.weeklyGoal.percentage}%` }),
    );
    const progress = document.createElement('progress');
    progress.max = Number(summary.weeklyGoal.target) || 1;
    progress.value = Number(summary.weeklyGoal.current) || 0;
    progress.setAttribute('aria-label', `${summary.weeklyGoal.percentage}% of weekly Language goal`);
    goal.append(copy, progress);
    root.append(goal);
  }
  if (summary.dailyQuest) {
    const quest = document.createElement('a');
    quest.className = 'language-learning-widget-action';
    quest.href = `./language.html${summary.dailyQuest.href || '#progress'}`;
    quest.textContent = `${summary.dailyQuest.title} · ${summary.dailyQuest.current}/${summary.dailyQuest.target}`;
    root.append(quest);
  }
  if (summary.campaignMilestone) {
    const campaign = document.createElement('p');
    campaign.className = 'language-learning-widget-campaign';
    campaign.textContent = `Campaign · ${summary.campaignMilestone.current}/${summary.campaignMilestone.target} ${String(summary.campaignMilestone.type || '').replaceAll('_', ' ').toLowerCase()}`;
    root.append(campaign);
  }
  const action = document.createElement('a');
  action.className = 'language-learning-widget-action';
  action.href = summary.nextAction
    ? `./language.html${summary.nextAction.href}`
    : './language.html#progress';
  action.textContent = summary.nextAction?.title || 'Open Language Progress';
  root.append(action);
}

export async function initLanguageLearningWidget({
  api = createLanguageApi(),
  root = document.querySelector('#language-learning-widget-body'),
} = {}) {
  if (!root) return null;
  root.setAttribute('aria-busy', 'true');
  try {
    const profiles = await api.profiles();
    const profile = selectLanguageWidgetProfile(profiles.items || []);
    const summary = profile ? await api.widgetSummary(profile.id) : null;
    renderLanguageWidget(root, summary);
    const knownMount = root.closest('#language-learning-card')?.querySelector('#language-learning-known-words');
    if (knownMount && profile && summary && typeof api.vocabulary === 'function') {
      knownMount.replaceChildren(createKnownWordsControl({
        api, profileId: profile.id, count: summary.knownWords, baseHref: './language.html',
      }));
    }
    if (profile && summary && typeof api.ankiStatus === 'function') {
      try {
        const status = await api.ankiStatus(profile.id);
        const showStatus = (nextStatus) => {
          renderLanguageWidget(root, { ...summary, anki: { ...summary.anki, ...nextStatus } });
          const all = Array.isArray(nextStatus.decks) ? nextStatus.decks : nextStatus.deck ? [nextStatus.deck] : [];
          setDailyAchievement('anki-norwegian', ankiAchievement(all));
          if (!nextStatus.config?.enabled || typeof api.syncAnkiWeb !== 'function') return;
          const button = document.createElement('button');
          button.type = 'button';
          button.className = 'language-learning-widget-action';
          button.textContent = nextStatus.status === 'UNAVAILABLE' ? 'Retry after opening Anki' : 'Sync AnkiWeb now';
          button.addEventListener('click', async () => {
            button.disabled = true;
            button.textContent = 'Syncing AnkiWeb…';
            try {
              const result = await api.syncAnkiWeb(profile.id, { force: true });
              showStatus(result.status);
              delete root.dataset.ankiSyncError;
            } catch (error) {
              root.dataset.ankiSyncError = error?.message || 'AnkiWeb sync failed';
              button.textContent = nextStatus.status === 'UNAVAILABLE' ? 'Retry after opening Anki' : 'Sync AnkiWeb now';
              button.disabled = false;
              if (nextStatus.status !== 'UNAVAILABLE') {
                const note = document.createElement('p');
                note.className = 'language-learning-widget-sync-error';
                note.textContent = root.dataset.ankiSyncError;
                button.after(note);
              }
            }
          });
          root.append(button);
        };
        showStatus(status);
        if (status.config?.autoSync && typeof api.syncAnkiWeb === 'function' && root.isConnected) {
          let refreshing = false;
          const refresh = async () => {
            if (document.hidden || !root.isConnected || refreshing) return;
            refreshing = true;
            try {
              const result = await api.syncAnkiWeb(profile.id);
              showStatus(result.status);
              delete root.dataset.ankiSyncError;
            } catch (error) {
              root.dataset.ankiSyncError = error?.message || 'AnkiWeb sync failed';
              const deck = root.querySelector('.language-learning-widget-deck');
              if (deck) {
                const note = deck.querySelector('.language-learning-widget-sync-error') || document.createElement('small');
                note.className = 'language-learning-widget-sync-error';
                note.textContent = root.dataset.ankiSyncError;
                deck.append(note);
              }
            } finally {
              refreshing = false;
            }
          };
          const onVisible = () => { if (!document.hidden) refresh(); };
          refresh();
          const timer = window.setInterval(() => {
            if (!root.isConnected) {
              window.clearInterval(timer);
              document.removeEventListener('visibilitychange', onVisible);
            } else refresh();
          }, 5 * 60 * 1000);
          document.addEventListener('visibilitychange', onVisible);
        }
      } catch (error) {
        root.dataset.ankiSyncError = error?.message || 'Anki is unavailable';
        setDailyAchievement('anki-norwegian', {
          state: 'error', value: 'Unavailable', detail: root.dataset.ankiSyncError, eligible: false,
        });
      }
    }
    return summary;
  } catch (error) {
    root.replaceChildren();
    const state = document.createElement('div');
    state.className = 'language-learning-widget-empty';
    state.textContent = 'Language summary is unavailable.';
    root.append(state);
    return null;
  } finally {
    root.setAttribute('aria-busy', 'false');
  }
}

if (typeof document !== 'undefined' && document.querySelector('#language-learning-widget-body')) {
  initLanguageLearningWidget();
}
