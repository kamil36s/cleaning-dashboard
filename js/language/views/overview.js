import { formatStudyDuration, lineChart } from '../charts.js';
import { messageState, node, replace, statusPill } from '../components/dom.js';

function metric(label, value, detail) {
  return node('article', { className: 'language-metric' }, [
    node('span', { text: label }), node('strong', { text: value ?? '—' }),
    detail ? node('small', { text: detail }) : null,
  ]);
}

function card(title, kicker, children, className = '') {
  return node('section', { className: `language-card language-analytics-card ${className}`.trim() }, [
    kicker ? node('p', { className: 'language-kicker', text: kicker }) : null,
    node('h3', { text: title }), ...children,
  ]);
}

export function renderToday(mount, summary, { onStartSession, onSelectDuration, selectedMinutes = 20, planLoading = false, planError = null } = {}) {
  const anki = summary.anki || {};
  const cloze = summary.cloze || {};
  const reader = summary.reader || {};
  let minutes = selectedMinutes;
  const durationButtons = [10, 20, 30].map((value) => {
    const button = node('button', { className: `language-button${value === selectedMinutes ? ' is-selected' : ''}`, type: 'button', text: `${value} min`, attrs: { 'aria-pressed': String(value === selectedMinutes) } });
    button.addEventListener('click', () => {
      minutes = value;
      durationButtons.forEach((item) => { item.classList.toggle('is-selected', item === button); item.setAttribute('aria-pressed', String(item === button)); });
      onSelectDuration?.(value);
    });
    return button;
  });
  const start = node('button', { className: 'language-button is-primary language-today-start', type: 'button', text: 'Start today’s study' });
  start.addEventListener('click', () => onStartSession?.(minutes));
  const ankiText = !anki.configured ? 'Anki is not configured.' : anki.newToday != null && anki.dueCount != null
    ? `${anki.newToday} new · ${anki.dueCount} reviews due`
    : anki.dueCount == null
    ? 'No stored due count. Refresh in Reviews.'
    : `${anki.dueCount} due at last sync${anki.stale ? ' · stale' : ''}`;
  const readerText = reader.continue?.title
    ? `Continue “${reader.continue.title}”`
    : 'Choose a text to begin reading.';
  const coreCard = (title, label, main, detail, href, action) => node('article', { className: 'language-card language-today-core-card' }, [
    node('p', { className: 'language-kicker', text: label }),
    node('h4', { text: title }),
    node('strong', { text: main }),
    node('p', { text: detail }),
    node('a', { className: 'language-button', text: action, attrs: { href } }),
  ]);
  const cards = node('section', { className: 'language-today-core', attrs: { 'aria-label': 'Daily Core' } }, [
    node('div', { className: 'language-section-head' }, [node('div', {}, [node('h3', { text: 'Daily Core' }), node('p', { text: 'Three ways to study today, each with its own progress.' })])]),
    node('div', { className: 'language-today-core-grid' }, [
      coreCard('Anki', anki.deckName || 'DUE · LAST SYNC', ankiText, anki.configured
        ? `${anki.learningToday ?? 0} learning · ${anki.answeredCardsToday ?? 0} distinct cards answered today. Anki owns card scheduling.`
        : 'Connect Anki in Settings if you use it.', anki.configured ? '#reviews' : '#settings', anki.configured ? 'Open Reviews' : 'Open Settings'),
      coreCard('Cloze', 'TODAY', `Reviews ${cloze.reviewedToday || 0}/${cloze.dailyReviewGoal || 5} · new sentences ${cloze.newSentencesToday || 0}/${cloze.dailyNewSentenceGoal || 3}`,
        'Choose review practice or Fast Track. Available questions are checked when you start.',
        '#cloze', 'Open Cloze'),
      coreCard('Reader', 'CONTINUE', readerText,
        reader.todaySeconds ? `${Math.floor(reader.todaySeconds / 60)} active min today` : 'Read a Norwegian text at your pace.',
        reader.continue?.id ? `#reader/text/${encodeURIComponent(reader.continue.id)}` : '#reader',
        reader.continue?.id ? 'Continue reading' : 'Choose text'),
    ]),
  ]);
  const compactFacts = [
    summary.streakDays ? metric('Streak', `${summary.streakDays} days`, 'Reader activity') : null,
    summary.level?.lifetimeXp ? metric('Level', summary.level.level, `${summary.level.lifetimeXp} XP`) : null,
    reader.todaySeconds ? metric('Reader today', `${Math.floor(reader.todaySeconds / 60)} min`) : null,
    cloze.answeredToday ? metric('Cloze today', cloze.answeredToday, 'Answers') : null,
  ].filter(Boolean);
  const onboarding = summary.startHere && !window.localStorage?.getItem('language-start-here-dismissed-v1')
    ? node('section', { className: 'language-card language-today-onboarding' }, [
      node('div', { className: 'language-section-head' }, [node('div', {}, [node('p', { className: 'language-kicker', text: 'START HERE' }), node('h3', { text: 'Begin with one small step' })])]),
      node('p', { text: 'Your study history is still empty. Add a short text, try Cloze, or connect Anki if you use it.' }),
      node('div', { className: 'language-form-actions' }, [
        node('a', { className: 'language-button is-primary', text: 'Add a Reader text', attrs: { href: '#reader' } }),
        node('a', { className: 'language-button', text: 'Try Cloze', attrs: { href: '#cloze' } }),
        node('a', { className: 'language-button', text: 'Anki settings', attrs: { href: '#settings' } }),
        node('a', { className: 'language-button', text: 'Run a baseline later', attrs: { href: '#benchmarks' } }),
      ]),
    ]) : null;
  if (onboarding) {
    const dismiss = node('button', { className: 'language-button', type: 'button', text: 'Dismiss start guide' });
    dismiss.addEventListener('click', () => { window.localStorage?.setItem('language-start-here-dismissed-v1', '1'); onboarding.remove(); });
    onboarding.append(dismiss);
  }
  const plan = summary.sessionPreview;
  const preview = node('section', { className: 'language-card language-today-preview' }, [
    node('p', { className: 'language-kicker', text: `TODAY’S SESSION · ${selectedMinutes} MIN` }),
    node('h3', { text: 'Your study mix' }),
    planLoading ? node('p', { text: 'Checking available work…' }) : null,
    planError ? node('p', { className: 'language-inline-error', text: planError }) : null,
    plan && !planLoading ? node('p', { text: plan.plannedMinutes < plan.requestedMinutes
      ? `${plan.requestedMinutes} min requested · ${plan.plannedMinutes} min useful work available`
      : `${plan.plannedMinutes} min of available work` }) : null,
    plan?.segments?.length && !planLoading ? node('ol', { className: 'language-today-preview-list' },
      plan.segments.map((segment) => node('li', {}, [
        node('span', { text: segment.title }), node('strong', { text: `${segment.estimatedMinutes} min` }),
      ]))) : null,
    plan?.unavailableSources?.length && !planLoading ? node('small', { text: 'Some sources are unavailable; the plan uses available work.' }) : null,
    plan && !plan.segments?.length && !planLoading ? node('p', { text: 'No useful work is available for this duration yet. Add a Reader text or try Cloze.' }) : null,
    node('a', { className: 'language-button', text: 'Open Study Session', attrs: { href: '#study-session' } }),
  ]);
  replace(mount, node('div', { className: 'language-today' }, [
    node('section', { className: 'language-card language-today-hero' }, [
      node('p', { className: 'language-kicker', text: 'TODAY’S NORWEGIAN' }),
      node('h3', { text: 'Make time for Norwegian today' }),
      node('p', { text: 'Choose how much time you have. The Study Session Builder will use work already available and show a shorter plan when needed.' }),
      node('div', { className: 'language-today-duration', attrs: { 'aria-label': 'Study duration' } }, durationButtons),
      start,
    ]),
    onboarding, cards, preview,
    compactFacts.length ? node('section', { className: 'language-today-metrics', attrs: { 'aria-label': 'Today progress' } }, compactFacts) : null,
    node('section', { className: 'language-today-secondary' }, [
      node('a', { className: 'language-button', text: 'View Progress', attrs: { href: '#progress' } }),
      node('a', { className: 'language-button', text: 'Generate a text', attrs: { href: '#generate' } }),
      node('a', { className: 'language-button', text: 'Browse Vocabulary', attrs: { href: '#vocabulary' } }),
    ]),
  ]));
}

export function renderOverview(mount, { overview }, { onQuickGenerate, onStartSession, onSelectDuration } = {}) {
  if (overview.loading && !overview.data) {
    replace(mount, messageState('loading', 'Loading truthful learning metrics…'));
    return;
  }
  if (overview.error) {
    replace(mount, messageState('error', 'Overview is unavailable.', overview.error));
    return;
  }
  const data = overview.data;
  if (!data) {
    replace(mount, messageState('empty', 'No overview data is available.'));
    return;
  }
  if (data.policyVersion === 'language.today-summary/v1') {
    renderToday(mount, data, { onStartSession, onSelectDuration, selectedMinutes: overview.minutes,
      planLoading: overview.planLoading, planError: overview.planError });
    return;
  }
  const stats = data.statistics;
  const vocabulary = stats.vocabulary;
  const classifiers = vocabulary.classifierCounts;
  const goal = data.goals?.find((item) => item.goal?.enabled);
  const plan = data.todayPlan?.items || [];
  const recycle = data.todayPlan?.wordsToRecycle?.items || [];
  const topics = data.topics || [];
  const recent = stats.reading?.recent || [];
  const anki = data.anki || { status: 'NOT_CONFIGURED' };
  const game = data.gamification || null;
  const mistakes = data.mistakes || { activeClusterCount: 0, recoveredClusterCount: 0, topProblems: [] };

  const summary = node('section', { className: 'language-overview-summary' }, [
    metric('Study streak', `${stats.streak.currentDays} day${stats.streak.currentDays === 1 ? '' : 's'}`, 'Real Reader activity only'),
    metric('Active study · 7 days', formatStudyDuration(stats.reading.activeSeconds), 'Server-authoritative time'),
    metric('Tracked vocabulary', vocabulary.totalTracked, `${vocabulary.newlyAdvanced} advanced this range`),
    metric('Reader exposures', stats.exposures.totalReaderOccurrences, `${stats.exposures.uniqueLemmas} unique lemmas`),
  ]);
  const progressCard = game ? card(game.level.label, 'MOTIVATION · NOT PROFICIENCY', [
    node('div', { className: 'language-goal-progress' }, [
      node('strong', { text: `${game.level.lifetimeXp} lifetime XP` }),
      node('progress', {
        value: game.level.xpIntoLevel,
        attrs: { max: game.level.nextLevelXp - game.level.currentLevelXpFloor, 'aria-label': `${game.level.xpNeeded} XP to the next Norwegian account level` },
      }),
      node('span', { text: `${game.level.xpNeeded} XP to Level ${game.level.level + 1}` }),
    ]),
    game.today?.items?.length ? node('a', {
      className: 'language-overview-progress-link', attrs: { href: '#progress' },
    }, [
      node('strong', { text: game.today.items.find((item) => !item.completed)?.title || 'Today’s quests complete' }),
      node('span', { text: `${game.today.completedCount} / ${game.today.items.length} quests complete` }),
    ]) : null,
    game.campaign?.nextMilestone ? node('p', { className: 'language-definition', text: `${game.campaign.name}: ${game.campaign.nextMilestone.current} / ${game.campaign.nextMilestone.target} ${game.campaign.nextMilestone.type.replaceAll('_', ' ').toLowerCase()}` }) : null,
    game.recentAchievement ? node('p', { className: 'language-definition', text: `Recent achievement: ${game.recentAchievement.achievementKey.replaceAll('_', ' ')}` }) : null,
    node('a', { className: 'language-button is-primary', text: 'Open Progress', attrs: { href: '#progress' } }),
  ], 'is-wide') : null;

  const vocabularyCard = card('Vocabulary status', 'DERIVED · CLASSIFIER V1', [
    node('div', { className: 'language-metric-row' }, [
      metric('Passive', classifiers.passive, 'Known, below active recall/production threshold'),
      metric('Active', classifiers.active, 'Recall ≥4 or production ≥3'),
      metric('Mastered', classifiers.mastered, 'Explicit MASTERED only'),
    ]),
  ]);
  const growthCard = card('Vocabulary over time', 'KNOWLEDGE EVENTS', [
    lineChart(vocabulary.series, {
      label: 'Tracked vocabulary over the last seven days', valueKey: 'totalTracked',
      emptyText: 'No vocabulary history yet. Analyze a text or edit a vocabulary item.',
    }),
  ], 'is-wide');
  const planCard = card("Today's plan", data.todayPlan?.ruleVersion, plan.length ? [
    node('ol', { className: 'language-action-list' }, plan.map((item) => node('li', {}, [
      node('a', { text: item.title, attrs: { href: item.href } }), node('span', { text: item.detail }),
    ]))),
  ] : [node('p', { className: 'language-empty-copy', text: 'No actionable work is supported by the current evidence.' })]);
  const recycleCard = card('Words to recycle', 'WEAK · RECENT · UNDEREXPOSED', recycle.length ? [
    node('ul', { className: 'language-recycle-list' }, recycle.map((item) => node('li', {}, [
      node('a', { text: item.lemma, attrs: { href: `#vocabulary/lemma/${encodeURIComponent(item.lemmaId)}` } }),
      node('span', { text: item.reasons.join(' · ') }),
    ]))),
  ] : [node('p', { className: 'language-empty-copy', text: 'No words currently meet the versioned recycle rules.' })]);
  const mistakeCard = card('Mistakes needing attention', 'DETERMINISTIC / DIAGNOSTIC', [
    node('p', { text: mistakes.activeClusterCount
      ? `${mistakes.activeClusterCount} established cluster${mistakes.activeClusterCount === 1 ? '' : 's'} currently need attention.`
      : 'No established mistake cluster currently needs attention.' }),
    mistakes.topProblems?.length
      ? node('p', { className: 'language-definition', text: mistakes.topProblems.map((item) => item.target?.lemma).filter(Boolean).join(' / ') })
      : null,
    node('a', { className: 'language-button', text: 'Review mistakes', attrs: { href: '#reviews' } }),
  ]);
  const topicCard = card('Topic mastery', 'USER-MAPPED DENOMINATORS', topics.length ? [
    node('div', { className: 'language-topic-summary-list' }, topics.slice(0, 4).map((item) => node('a', {
      attrs: { href: '#topics' }, className: 'language-topic-summary',
    }, [
      node('span', { text: item.topic.displayName }),
      node('strong', { text: item.weightedMasteryPercent == null ? '—' : `${item.weightedMasteryPercent}%` }),
      node('small', { text: `${item.mappedLemmaCount} mapped · partial domain` }),
    ]))),
  ] : [
    node('p', { className: 'language-empty-copy', text: 'No topic membership exists yet. Percentages stay hidden until lemmas are assigned.' }),
    node('a', { className: 'language-button', text: 'Create a topic', attrs: { href: '#topics' } }),
  ]);
  const goalCard = card('Weekly goal', 'EUROPE/WARSAW', goal ? [
    node('div', { className: 'language-goal-progress' }, [
      node('strong', { text: `${goal.current} / ${goal.target} ${goal.goal.unit.toLowerCase()}` }),
      node('progress', { value: goal.current, attrs: { max: goal.target, 'aria-label': `${goal.percentage}% of weekly goal` } }),
      node('span', { text: `${goal.remaining} remaining · ${goal.percentage}%` }),
    ]),
  ] : [
    node('p', { className: 'language-empty-copy', text: 'No enabled goal. Progress is never invented.' }),
    node('a', { className: 'language-button', text: 'Create a goal', attrs: { href: '#goals' } }),
  ]);
  const recentCard = card('Recent reading', 'CANONICAL READER HISTORY', recent.length ? [
    node('ul', { className: 'language-action-list' }, recent.map((item) => node('li', {}, [
      node('a', { text: item.title, attrs: { href: `#reader/text/${encodeURIComponent(item.id)}` } }),
      node('span', { text: `${item.readingStatus || 'Not started'} · ${formatStudyDuration(item.activeSeconds)}` }),
    ]))),
  ] : [
    node('p', { className: 'language-empty-copy', text: 'No texts yet.' }),
    node('a', { className: 'language-button is-primary', text: 'Add a Reader text', attrs: { href: '#reader' } }),
  ]);
  const unavailableCard = card('Reference integrations', 'TRUTHFUL AVAILABILITY', [
    node('div', { className: 'language-health-list' }, [
      node('div', { className: 'language-health-row' }, [node('span', { text: 'Ranked frequency coverage' }), statusPill('Not configured', 'muted')]),
      node('p', { className: 'language-definition', text: data.frequencyCoverage.message }),
      node('div', { className: 'language-health-row' }, [
        node('span', { text: 'Anki' }),
        statusPill(anki.status || 'NOT_CONFIGURED', anki.status === 'CONNECTED' ? 'success' : 'muted'),
      ]),
      node('p', { className: 'language-definition', text: anki.status === 'CONNECTED'
        ? `${anki.dueCount == null ? 'Due count not pulled' : `${anki.dueCount} due`} / ${anki.linkedVocabulary || 0} linked / ${anki.conflicts || 0} conflicts`
        : 'Language learning remains available when Anki is closed or not configured.' }),
      node('a', { className: 'language-button', text: 'Open Anki reviews', attrs: { href: '#reviews' } }),
    ]),
  ]);
  const quickLength = node('select', {}, [200, 400, 700].map((value) => node('option', { text: `${value} words`, attrs: { value } })));
  quickLength.value = '400';
  const quickPreset = node('select', {}, [['VERY_EASY', 'Very Easy · 99%'], ['EASY', 'Easy · 97%'], ['BALANCED', 'Normal · 95%'], ['CHALLENGING', 'Challenge · 90%']].map(([value, label]) => node('option', { text: label, attrs: { value } })));
  quickPreset.value = 'BALANCED';
  const quickButton = node('button', { className: 'language-button is-primary', type: 'button', text: 'Open generator' });
  quickButton.addEventListener('click', () => onQuickGenerate?.({ length: Number(quickLength.value), difficultyPreset: quickPreset.value }));
  const generateCard = card('Generate adaptive text', 'MANUAL EXTERNAL LLM', [
    node('p', { text: 'Prepare a frozen, privacy-bounded prompt. The dashboard never contacts an AI provider.' }),
    node('div', { className: 'language-form-actions' }, [quickLength, quickPreset, quickButton]),
  ]);

  replace(mount, node('div', { className: 'language-overview-dashboard' }, [
    summary,
    node('div', { className: 'language-analytics-grid' }, [
      progressCard, generateCard, vocabularyCard, growthCard, planCard, mistakeCard, recycleCard, topicCard, goalCard, recentCard, unavailableCard,
    ]),
  ]));
}
