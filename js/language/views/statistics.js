import { distributionBars, formatStudyDuration, lineChart } from '../charts.js';
import { messageState, node, replace } from '../components/dom.js';

function stat(label, value, definition) {
  return node('article', { className: 'language-metric' }, [
    node('span', { text: label }), node('strong', { text: value }),
    definition ? node('small', { text: definition }) : null,
  ]);
}

function panel(title, description, children) {
  return node('section', { className: 'language-card language-stat-panel' }, [
    node('h3', { text: title }), description ? node('p', { className: 'language-definition', text: description }) : null,
    ...children,
  ]);
}

export function renderStatistics(mount, state, { onRange }) {
  if (state.loading && !state.data) return replace(mount, messageState('loading', 'Calculating statistics from canonical facts…'));
  if (state.error) return replace(mount, messageState('error', 'Statistics are unavailable.', state.error));
  const data = state.data;
  if (!data) return replace(mount, messageState('empty', 'No statistics are available.'));
  const range = node('select', { attrs: { 'aria-label': 'Statistics time range' } }, [
    node('option', { value: '7d', text: '7 days' }), node('option', { value: '30d', text: '30 days' }),
    node('option', { value: '90d', text: '90 days' }), node('option', { value: 'all', text: 'All time' }),
  ]);
  range.value = state.range;
  range.addEventListener('change', () => onRange(range.value));
  const head = node('div', { className: 'language-view-head' }, [
    node('div', {}, [node('p', { className: 'language-kicker', text: 'EVENT-DERIVED ANALYTICS' }), node('h3', { text: 'Statistics' })]), range,
  ]);
  const knownSeries = (data.vocabulary.series || []).map((item) => ({
    date: item.date, knownWords: item.knownWords ?? ((item.known || 0) + (item.mastered || 0)),
  }));
  const dailyKnown = knownSeries.map((item, index) => ({
    date: item.date, count: index ? Math.max(0, item.knownWords - knownSeries[index - 1].knownWords) : 0,
  }));
  const vocabulary = panel('Known Words', 'Reader vocabulary marked KNOWN or MASTERED. Historical values come from knowledge events.', [
    node('div', { className: 'language-metric-row' }, [
      stat('Tracked', data.vocabulary.totalTracked, 'Non-excluded canonical lemmas'),
      stat('Learning', data.vocabulary.knowledgeCounts.learning, 'Current explicit status'),
      stat('Known Words', data.vocabulary.knownWords ?? ((data.vocabulary.knowledgeCounts.known || 0) + (data.vocabulary.knowledgeCounts.mastered || 0)), 'KNOWN + MASTERED, tracked'),
      stat('Newly advanced', data.vocabulary.newlyAdvanced, 'In selected range'),
    ]),
    node('div', { className: 'language-known-charts' }, [
      node('div', {}, [node('h4', { text: 'Known Words · cumulative' }),
        lineChart(knownSeries, { label: 'Cumulative Known Words', valueKey: 'knownWords' })]),
      node('div', {}, [node('h4', { text: 'Known Words · gained daily' }),
        lineChart(dailyKnown, { label: 'Known Words gained per day', valueKey: 'count' })]),
    ]),
  ]);
  const exposures = panel('Exposure activity', 'Only accepted Reader ExposureEvent occurrence counts; imported tokens are not study evidence.', [
    node('div', { className: 'language-metric-row' }, [
      stat('Occurrences', data.exposures.totalReaderOccurrences, 'Canonical Reader exposure'),
      stat('Unique lemmas', data.exposures.uniqueLemmas, 'Exposed in selected range'),
      stat('Underexposed', data.vocabulary.classifierCounts.underexposed, '< 3 real exposures'),
    ]),
    lineChart(data.exposures.byDay, { label: 'Reader exposure occurrences by day', valueKey: 'count' }),
    distributionBars(data.exposures.distribution, { label: 'Exposure count distribution by lemma' }),
    data.exposures.highExposure?.length
      ? node('ul', { className: 'language-action-list' }, data.exposures.highExposure.map((item) => node('li', {}, [
        node('strong', { text: item.lemma }), node('span', { text: `${item.occurrenceCount} Reader occurrences in range` }),
      ])))
      : node('div', { className: 'language-chart-empty', text: 'No exposed lemmas in this range.' }),
  ]);
  const reading = panel('Reader activity', 'Active time excludes hidden or paused periods. Word encounters are accepted Reader exposure events.', [
    node('div', { className: 'language-metric-row' }, [
      stat('Active time', formatStudyDuration(data.reading.activeSeconds), 'Reader sessions only'),
      stat('Word encounters', data.exposures.totalReaderOccurrences, 'Recorded Reader occurrences'),
      stat('Unique words seen', data.exposures.uniqueLemmas, 'Distinct Reader lemmas'),
      stat('Texts completed', data.reading.textsCompleted, 'Explicit completion'),
      stat('Current streak', `${data.streak.currentDays} days`, data.streak.definition),
    ]),
    lineChart(data.reading.byDay, { label: 'Active reading seconds by day', valueKey: 'activeSeconds' }),
  ]);
  const listening = panel('Listening activity', 'Audible playback lifecycle only. Active minutes are activity evidence, not a comprehension or proficiency score.', [
    node('div', { className: 'language-metric-row' }, [
      stat('Active time', formatStudyDuration(data.listening?.activeSeconds || 0), 'Listening sessions only'),
      stat('Sessions', data.listening?.sessions || 0, 'Started by actual playback'),
      stat('Sentences', data.listening?.sentencesListened || 0, 'Qualified sentence completions'),
      stat('Texts completed', data.listening?.textsCompleted || 0, 'Listening completion policy'),
    ]),
    node('p', { className: 'language-definition', text: `Reader ${formatStudyDuration(data.studyTime?.readingActiveSeconds || 0)} · Listening ${formatStudyDuration(data.studyTime?.listeningActiveSeconds || 0)}. Their displayed sum may overlap in Read + Listen mode and is not unique wall-clock time.` }),
  ]);
  const coverage = panel('Coverage history', 'Completion snapshots are immutable and are not rescored with today’s vocabulary.', [
    data.coverage.history.length
      ? node('ul', { className: 'language-action-list' }, data.coverage.history.map((item) => node('li', {}, [
        node('strong', { text: item.title }),
        node('span', { text: item.tokenCoveragePercent == null ? 'Coverage unavailable' : `${item.tokenCoveragePercent}% at completion` }),
      ])))
      : node('div', { className: 'language-chart-empty', text: 'No completed-text coverage snapshots yet.' }),
  ]);
  const cloze = panel('Cloze practice', 'Dashboard practice evidence is explicit and remains separate from Anki scheduling.', [
    node('div', { className: 'language-metric-row' }, [
      stat('Attempts', data.cloze?.attempts || 0, 'Correct, incorrect, revealed, and skipped'),
      stat('Correct', data.cloze?.correct || 0, 'Explicit correct choices'),
      stat('Incorrect', data.cloze?.incorrect || 0, 'Eligible for recycling'),
      stat('Accuracy', data.cloze?.accuracy == null ? '—' : `${data.cloze.accuracy}%`, 'Correct / scored answers'),
    ]),
    node('p', { className: 'language-definition', text: `${data.cloze?.revealed || 0} revealed · ${data.cloze?.skipped || 0} skipped · ${data.cloze?.encounteredTargets || 0} targets encountered` }),
  ]);
  const mistakes = panel('Mistake intelligence', 'Historical errors remain separate from current remediation state. One-off errors do not form established clusters.', [
    node('div', { className: 'language-metric-row' }, [
      stat('Historical errors', data.mistakes?.historicalIncorrectCount || 0, 'All canonical incorrect Cloze attempts'),
      stat('Active clusters', data.mistakes?.activeClusterCount || 0, 'Established current remediation needs'),
      stat('New / 7 days', data.mistakes?.newInLast7Days || 0, 'Recently established clusters'),
      stat('Recovered / 7 days', data.mistakes?.recoveredInLast7Days || 0, 'Recovery reached without deleting history'),
    ]),
    data.mistakes?.topProblems?.length
      ? node('ul', { className: 'language-action-list' }, data.mistakes.topProblems.slice(0, 5).map((item) => node('li', {}, [
        node('strong', { text: item.target?.lemma || item.title }),
        node('span', { text: `${item.category.replaceAll('_', ' ')} / ${item.state} / ${item.historicalFailureCount} qualifying failures` }),
      ])))
      : node('div', { className: 'language-chart-empty', text: 'No established mistake cluster in this range.' }),
  ]);
  const topics = panel('Topic progress', 'Every percentage covers only manually mapped lemmas, not the full semantic domain.', [
    data.topics.length
      ? node('ul', { className: 'language-action-list' }, data.topics.map((item) => node('li', {}, [
        node('strong', { text: item.topic.displayName }),
        node('span', { text: `${item.weightedMasteryPercent ?? '—'}% · ${item.mappedLemmaCount} mapped · partial denominator` }),
      ])))
      : node('div', { className: 'language-chart-empty', text: 'No topic membership exists.' }),
  ]);
  const frequency = panel('Ranked frequency coverage', 'wordfreq Zipf scores are available; exact lemma ranks are not.', [
    node('div', { className: 'language-chart-empty', text: 'Not configured' }),
  ]);
  replace(mount, node('div', { className: 'language-statistics-view' }, [head, vocabulary, reading, exposures, listening, cloze, mistakes, coverage, topics, frequency]));
}
