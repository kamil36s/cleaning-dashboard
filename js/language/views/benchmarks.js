const LABELS = {
  VOCABULARY: 'Vocabulary recognition', CLOZE: 'Cloze',
  READING: 'Reading comprehension', LISTENING: 'Listening comprehension',
};
const ORDER = Object.keys(LABELS);

function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
}

function button(label, callback) {
  const element = node('button', label, 'language-button');
  element.type = 'button';
  element.addEventListener('click', callback);
  return element;
}

function scoreText(score) {
  if (!score || score.status === 'UNAVAILABLE') return 'Unavailable';
  return `${score.correct} / ${score.total} · ${score.percent}%${score.unavailable ? ` · ${score.unavailable} unavailable` : ''}`;
}

export function renderBenchmarkLanding(mount, history, preparation, { start, open }) {
  mount.replaceChildren();
  const intro = node('section', undefined, 'language-card language-benchmark-card');
  intro.append(node('h3', 'Progress benchmarks'), node('p', 'Fixed, internal synthetic tasks in four separate dimensions. Results are personal checkpoints, not a certified level.'));
  intro.append(button(history.runs.some((run) => run.status === 'ACTIVE') ? 'Resume benchmark' : 'Start benchmark', start));
  mount.append(intro);

  const historySection = node('section', undefined, 'language-card language-benchmark-card');
  historySection.append(node('h3', 'History'));
  if (!history.runs.length) {
    historySection.append(node('p', 'No baseline yet. Run your first checkpoint to see separate reading, listening, vocabulary, and Cloze results.'));
    historySection.append(button('Run baseline', start));
  }
  history.runs.forEach((run) => {
    const row = node('div', undefined, 'language-benchmark-row');
    row.append(node('span', `${run.kind} · ${run.status} · ${run.formId} · ${run.startedAt.slice(0, 10)}`));
    row.append(button(run.status === 'ACTIVE' ? 'Resume' : 'Results', () => open(run.id)));
    historySection.append(row);
  });
  mount.append(historySection);

  const norway = node('section', undefined, 'language-card language-benchmark-card');
  norway.append(node('h3', 'Norway Preparation'), node('p', 'Separate source-defined curriculum counts and latest comprehension benchmarks. No combined readiness score.'));
  const dimensions = node('div', undefined, 'language-benchmark-dimensions');
  preparation.curricula.forEach((pack) => {
    const card = node('article', undefined, 'language-benchmark-dimension');
    card.append(node('strong', pack.name), node('span', `${pack.completed} / ${pack.total} acquired`));
    const meter = node('progress'); meter.max = Math.max(1, Number(pack.total) || 0); meter.value = Math.min(meter.max, Number(pack.completed) || 0);
    meter.setAttribute('aria-label', `${pack.name}: ${pack.completed} of ${pack.total} acquired`);
    card.append(meter);
    const source = node('details'); source.append(node('summary', 'Source details'), node('p', `${pack.packId} v${pack.version}${pack.source ? ` · ${pack.source}` : ''}`));
    card.append(source); dimensions.append(card);
  });
  ['READING', 'LISTENING'].forEach((dimension) => {
    const card = node('article', undefined, 'language-benchmark-dimension');
    card.append(node('strong', LABELS[dimension]), node('span', scoreText(preparation.benchmarks[dimension])));
    const percent = preparation.benchmarks[dimension]?.percent;
    if (typeof percent === 'number') {
      const meter = node('progress'); meter.max = 100; meter.value = Math.max(0, Math.min(100, percent));
      meter.setAttribute('aria-label', `${LABELS[dimension]}: ${percent}%`); card.append(meter);
    }
    dimensions.append(card);
  });
  norway.append(dimensions);
  mount.append(norway);
}

export function renderBenchmarkRun(mount, run, { answer, complete, back, speech }) {
  mount.replaceChildren();
  const card = node('section', undefined, 'language-card language-benchmark-card');
  card.append(button('← Benchmark history', back));
  card.append(node('h3', `${run.kind} · ${run.formId}`));
  card.append(node('p', 'Internal synthetic content · Answers are scored on the server.'));
  if (run.status === 'COMPLETED') {
    ORDER.forEach((dimension) => {
      const change = run.comparison?.dimensions?.[dimension]?.changePp;
      const changeText = change === null || change === undefined ? '' : ` · observed ${change >= 0 ? '+' : ''}${change} pp (repeat influenced)`;
      card.append(node('p', `${LABELS[dimension]}: ${scoreText(run.scores[dimension])}${changeText}`));
    });
    if (run.comparison?.state && run.comparison.state !== 'NO_BASELINE') {
      card.append(node('p', run.comparison.state === 'REPEAT_INFLUENCED'
        ? 'Baseline comparison: REPEAT INFLUENCED. Same form and scoring, but prior exposure may raise the score; changes are descriptive, not proof of learning.'
        : 'Baseline comparison: NOT COMPARABLE. Different forms or versions; no percentage-point trend is shown.'));
    }
    if (run.comparison?.repeatInfluence?.repeatedItemCount) {
      card.append(node('p', `${run.comparison.repeatInfluence.repeatedItemCount} items in this run had been shown in an earlier run.`));
    }
    mount.append(card);
    return;
  }
  const items = run.items || [];
  const completed = Object.keys(run.responses || {}).length;
  const progress = node('p', `${completed} / ${items.length} answered`, 'language-benchmark-progress');
  progress.setAttribute('role', 'status');
  card.append(progress);
  ORDER.forEach((dimension) => {
    const sectionItems = items.filter((item) => item.dimension === dimension);
    const count = sectionItems.filter((item) => run.responses?.[item.id]).length;
    card.append(node('p', `${LABELS[dimension]}: ${count} / ${sectionItems.length}`));
  });
  const item = items.find((candidate) => !run.responses?.[candidate.id]);
  if (!item) {
    card.append(button('Finish and score', complete));
    mount.append(card);
    return;
  }
  const question = node('form', undefined, 'language-benchmark-question');
  question.append(node('h4', LABELS[item.dimension]));
  if (item.target) question.append(node('p', item.target));
  if (item.passage) question.append(node('p', item.passage));
  if (item.dimension === 'LISTENING') {
    // The transcript is passed to speech synthesis only. It is never inserted into the DOM.
    const playback = speech.snapshot();
    const available = playback.state === 'AVAILABLE';
    question.append(node('p', available ? 'Listen before answering. Speech rate: 1.0.'
      : playback.state === 'VOICE_LOADING' ? 'Browser voices are loading. Retry detection or continue without Listening.'
        : 'Compatible Bokmål speech is unavailable on this device.'));
    if (available) question.append(button('Play audio', () => speech.play(item.speech)));
    else {
      if (playback.state === 'VOICE_LOADING') question.append(button('Retry voice detection', () => speech.retry()));
      question.append(button('Mark Listening unavailable', () => answer(item.id, { unavailable: true })));
      card.append(question);
      mount.append(card);
      return;
    }
  }
  question.append(node('p', item.prompt));
  if (item.hint) question.append(node('p', `Hint: ${item.hint}`));
  let input;
  if (item.dimension === 'CLOZE') {
    input = node('input');
    input.type = 'text';
    input.required = true;
    input.maxLength = 200;
    input.autocomplete = 'off';
    input.setAttribute('aria-label', 'Missing Norwegian word');
    question.append(input);
  } else {
    input = node('select');
    input.required = true;
    input.setAttribute('aria-label', 'Select answer');
    const placeholder = node('option', 'Choose an answer');
    placeholder.value = '';
    input.append(placeholder);
    item.options.forEach((option) => {
      const entry = node('option', option);
      entry.value = option;
      input.append(entry);
    });
    question.append(input);
  }
  if (item.dimension !== 'LISTENING' || speech.snapshot().state === 'AVAILABLE') {
    const submit = node('button', 'Save answer', 'language-button');
    submit.type = 'submit';
    question.append(submit);
  }
  question.addEventListener('submit', (event) => {
    event.preventDefault();
    if (input.value) answer(item.id, { response: input.value });
  });
  card.append(question);
  mount.append(card);
}
