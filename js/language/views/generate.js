import { node, replace, statusPill } from '../components/dom.js';

const PRESETS = [
  ['VERY_EASY', 'Very Easy', 99], ['EASY', 'Easy', 97],
  ['BALANCED', 'Normal', 95], ['CHALLENGING', 'Challenge', 90],
];

function field(label, control, help = '') {
  return node('label', { className: 'language-field' }, [
    node('span', { text: label }), control, help ? node('small', { text: help }) : null,
  ]);
}

function candidateCard(candidate, actions) {
  const analysis = candidate.analysis;
  const coverage = analysis?.coverage;
  const card = node('article', { className: 'language-card language-generation-candidate' }, [
    node('div', { className: 'language-generation-card-head' }, [
      node('div', {}, [node('p', { className: 'language-kicker', text: `ATTEMPT ${candidate.attemptNumber}${candidate.isBestCandidate ? ' · BEST AVAILABLE' : ''}` }), node('h3', { text: candidate.title || 'Provider attempt' })]),
      statusPill(candidate.status.replaceAll('_', ' '), candidate.status === 'IN_TOLERANCE' ? 'success' : candidate.status === 'OUT_OF_TOLERANCE' ? 'warning' : 'muted'),
    ]),
    node('p', { className: 'language-generation-provenance', text: `${candidate.source} · ${candidate.providerLabel || candidate.providerId || 'provider not recorded'}${candidate.modelLabel || candidate.modelId ? ` · ${candidate.modelLabel || candidate.modelId}` : ''}${candidate.providerLatencyMs != null ? ` · ${Math.round(candidate.providerLatencyMs)} ms` : ''}` }),
  ]);
  if (coverage) {
    card.append(node('div', { className: 'language-generation-metrics' }, [
      node('div', {}, [node('span', { text: 'Token coverage' }), node('strong', { text: `${coverage.tokenCoveragePercent}%` })]),
      node('div', {}, [node('span', { text: 'Unique lemmas' }), node('strong', { text: `${coverage.uniqueLemmaCoveragePercent}%` })]),
      node('div', {}, [node('span', { text: 'Target' }), node('strong', { text: `${analysis.requestedTokenCoveragePercent}% ± ${analysis.tolerancePercentagePoints}` })]),
      node('div', {}, [node('span', { text: 'Length' }), node('strong', { text: `${analysis.length.actualWords} / ${analysis.length.requestedWords}` })]),
    ]));
    const problems = analysis.problematicWords || [];
    card.append(node('div', { className: 'language-generation-columns' }, [
      node('div', {}, [node('h4', { text: 'Problematic vocabulary' }), problems.length
        ? node('ul', {}, problems.slice(0, 12).map((item) => node('li', { text: `${item.lemma || item.surface} ×${item.count}${item.unresolved ? ' · unresolved' : ''}` })))
        : node('p', { text: 'No uncovered vocabulary measured.' })]),
      node('div', {}, [node('h4', { text: 'Focus-word use' }), node('ul', {}, (analysis.targetUsage || []).map((item) => node('li', { text: `${item.lemma}: ${item.count ? `${item.count} use(s)` : 'missed'}` })))])
    ]));
  }
  const actionsRow = node('div', { className: 'language-form-actions' });
  if (['IMPORTED', 'FAILED'].includes(candidate.status)) {
    const analyze = node('button', { className: 'language-button is-primary', type: 'button', text: 'Analyze locally' });
    analyze.addEventListener('click', () => actions.onAnalyze(candidate.id)); actionsRow.append(analyze);
  }
  if (['QUEUED', 'ANALYZING'].includes(candidate.status)) actionsRow.append(node('span', { text: 'Canonical Stanza analysis is running…' }));
  if (['IN_TOLERANCE', 'OUT_OF_TOLERANCE'].includes(candidate.status)) {
    const revise = node('button', { className: 'language-button', type: 'button', text: 'Copy revision prompt' });
    revise.addEventListener('click', () => actions.onRevision(candidate.id));
    const accept = node('button', { className: 'language-button is-primary', type: 'button', text: candidate.status === 'OUT_OF_TOLERANCE' ? 'Accept despite gap' : 'Accept & save to Reader' });
    accept.addEventListener('click', () => actions.onAccept(candidate.id));
    const reject = node('button', { className: 'language-button is-danger', type: 'button', text: 'Reject' });
    reject.addEventListener('click', () => actions.onReject(candidate.id));
    actionsRow.append(revise, accept, reject);
  }
  if (candidate.status === 'ACCEPTED' && candidate.acceptedTextDocumentId) {
    actionsRow.append(node('a', { className: 'language-button is-primary', text: 'Read now', attrs: { href: `#reader/text/${encodeURIComponent(candidate.acceptedTextDocumentId)}` } }));
  }
  if (candidate.extractedText) {
    const expression = node('input', { type: 'text', placeholder: 'Exact expression from this generated text', attrs: { maxlength: '2000' } });
    const saved = node('span', { className: 'language-definition', attrs: { role: 'status' } });
    const saveExpression = node('button', { className: 'language-button', type: 'button', text: 'Save expression' });
    saveExpression.addEventListener('click', async () => {
      const value = expression.value.trim();
      if (!value) { saved.textContent = 'Enter an exact expression first.'; return; }
      saveExpression.disabled = true; saved.textContent = 'Saving…';
      try {
        const result = await actions.onSaveExpression(candidate, value);
        saved.textContent = result?.reused ? 'Already saved for this generated context.' : 'Saved to Phrasebook.';
      } catch (error) { saved.textContent = error?.message || 'Expression could not be saved.'; }
      finally { saveExpression.disabled = false; }
    });
    actionsRow.append(expression, saveExpression, saved);
  }
  card.append(actionsRow);
  if (candidate.errorMessage) card.append(node('p', { className: 'language-form-error', text: candidate.errorMessage }));
  return card;
}

export function renderGenerate(mount, state, actions) {
  const providerHealth = state.providerHealth || {};
  const providerReady = providerHealth.configured === true
    && ['CONFIGURED', 'AVAILABLE'].includes(providerHealth.state);
  const generationMode = node('select', {}, [
    node('option', { text: 'Automatic · Gemini free tier', attrs: { value: 'AUTOMATIC' } }),
    node('option', { text: 'Manual · copy and paste', attrs: { value: 'MANUAL' } }),
  ]);
  generationMode.value = providerReady ? (state.form.generationMode || 'AUTOMATIC') : 'MANUAL';
  const length = node('input', { type: 'number', value: state.form.length, attrs: { min: '50', max: '5000', step: '50', required: '' } });
  const preset = node('select', {}, PRESETS.map(([value, label, percent]) => node('option', { text: `${label} · ${percent}%`, attrs: { value } })));
  preset.value = state.form.difficultyPreset;
  const customCoverage = node('input', { type: 'number', value: state.form.targetCoverage, attrs: { min: '50', max: '100', step: '.1', required: '' } });
  preset.addEventListener('change', () => { customCoverage.value = PRESETS.find(([value]) => value === preset.value)?.[2] ?? 95; });
  const topic = node('select', {}, [node('option', { text: 'No stored topic', attrs: { value: '' } }), ...(state.topics || []).map((item) => node('option', { text: item.topic.displayName, attrs: { value: item.topic.id } }))]);
  const customTopic = node('input', { type: 'text', value: state.form.customTopic, placeholder: 'e.g. an unexpected discovery', attrs: { maxlength: '500' } });
  const grammar = node('input', { type: 'text', value: state.form.grammarFocus, placeholder: 'Optional grammar focus', attrs: { maxlength: '1000' } });
  const style = node('input', { type: 'text', value: state.form.styleInstruction, placeholder: 'Optional tone or format', attrs: { maxlength: '1000' } });
  const referenceEnrichment = node('input', { type: 'checkbox' });
  referenceEnrichment.checked = state.form.referenceEnrichment !== false;
  const storyMode = node('select', {}, [
    node('option', { text: 'New story or standalone text', attrs: { value: 'NEW' } }),
    node('option', { text: 'Continue a previous episode', attrs: { value: 'CONTINUE' } }),
  ]);
  storyMode.value = state.form.storyMode || 'NEW';
  const seriesChoice = node('select');
  const previousText = node('select');
  const seriesTitle = node('input', { type: 'text', placeholder: 'e.g. The Saturday Mystery', attrs: { maxlength: '200' } });
  const seriesPremise = node('textarea', { placeholder: 'Who is the story about, where does it happen, and what is the longer story arc?', attrs: { maxlength: '2000', rows: '3' } });
  const seriesNotes = node('textarea', { placeholder: 'Names, relationships, places, established facts and open threads', attrs: { maxlength: '4000', rows: '3' } });
  seriesTitle.value = state.form.newSeries?.title || '';
  seriesPremise.value = state.form.newSeries?.premise || '';
  seriesNotes.value = state.form.newSeries?.continuityNotes || '';
  const direction = node('textarea', { placeholder: 'What should happen in this episode? Leave blank for a natural next step.', attrs: { maxlength: '1000', rows: '2' } });
  direction.value = state.form.episodeDirection || '';
  const avoid = node('textarea', { placeholder: 'Scenes, twists or events that should not happen again', attrs: { maxlength: '1000', rows: '2' } });
  avoid.value = state.form.avoidRepeating || '';
  const pacing = node('select', {}, [
    node('option', { text: 'Balanced', attrs: { value: 'STEADY' } }),
    node('option', { text: 'Calm', attrs: { value: 'CALM' } }),
    node('option', { text: 'Tense', attrs: { value: 'TENSE' } }),
  ]);
  pacing.value = state.form.pacing || 'STEADY';
  const ending = node('select', {}, [
    node('option', { text: 'Open ending', attrs: { value: 'OPEN' } }),
    node('option', { text: 'Resolve this episode', attrs: { value: 'RESOLVED' } }),
    node('option', { text: 'Cliffhanger', attrs: { value: 'CLIFFHANGER' } }),
  ]);
  ending.value = state.form.ending || 'OPEN';
  const newSeriesFields = node('div', { className: 'language-generation-story-fields' }, [
    field('Series name', seriesTitle), field('Premise and longer arc', seriesPremise), field('Continuity notes', seriesNotes),
  ]);
  const previousField = field('Continue after', previousText, 'The prompt includes the selected episode (with bounded excerpts for very long texts), recent episodes and series notes.');
  function syncStoryFields() {
    const continuation = storyMode.value === 'CONTINUE';
    const selectedSeries = seriesChoice.value;
    const choices = continuation
      ? (state.series || []).filter((item) => item.episodeCount > 0)
      : (state.series || []).filter((item) => !item.episodeCount);
    const current = selectedSeries || state.form.seriesId || (state.form.newSeries ? '__new__' : '');
    seriesChoice.replaceChildren(
      ...(continuation ? [node('option', { text: 'Choose a series', attrs: { value: '' } }), node('option', { text: 'Turn a standalone text into a new series', attrs: { value: '__new__' } })]
        : [node('option', { text: 'Standalone text', attrs: { value: '' } }), node('option', { text: 'Start a new series', attrs: { value: '__new__' } })]),
      ...choices.map((item) => node('option', { text: `${item.title}${continuation ? ` · ${item.episodeCount} episodes` : ' · empty series'}`, attrs: { value: item.id } })),
    );
    seriesChoice.value = choices.some((item) => item.id === current) || current === '__new__' ? current : '';
    newSeriesFields.hidden = seriesChoice.value !== '__new__';
    previousField.hidden = !continuation;
    const series = (state.series || []).find((item) => item.id === seriesChoice.value);
    previousText.replaceChildren(
      node('option', { text: 'Choose the previous episode', attrs: { value: '' } }),
      ...(seriesChoice.value === '__new__' ? (state.texts || []).filter((item) => !item.seriesId).map((item) => ({
        episodeNumber: null, title: item.title, textDocumentId: item.id,
      })) : (series?.episodes || [])).map((episode) => node('option', {
        text: episode.episodeNumber ? `Episode ${episode.episodeNumber}: ${episode.title}` : episode.title,
        attrs: { value: episode.textDocumentId },
      })),
    );
    const requested = state.form.previousTextId || '';
    const available = seriesChoice.value === '__new__'
      ? (state.texts || []).filter((item) => !item.seriesId).map((item) => ({ textDocumentId: item.id }))
      : (series?.episodes || []);
    previousText.value = available.some((episode) => episode.textDocumentId === requested)
      ? requested : (seriesChoice.value === '__new__' ? available[0] : available.at(-1))?.textDocumentId || '';
    previousText.required = continuation;
    seriesChoice.required = continuation;
    seriesTitle.required = !newSeriesFields.hidden;
  }
  storyMode.addEventListener('change', () => { seriesChoice.value = ''; syncStoryFields(); });
  seriesChoice.addEventListener('change', syncStoryFields);
  syncStoryFields();
  const createRequest = node('button', {
    className: 'language-button is-primary', type: 'submit',
    text: state.busy ? 'Preparing…' : 'Create request',
    disabled: state.busy || (generationMode.value === 'AUTOMATIC' && !providerReady),
  });
  generationMode.addEventListener('change', () => {
    createRequest.disabled = state.busy || (generationMode.value === 'AUTOMATIC' && !providerReady);
  });
  const form = node('form', { className: 'language-card language-generation-form' }, [
    node('p', { className: 'language-kicker', text: 'CREATE A READING TEXT' }), node('h3', { text: 'What would you like to read?' }),
    node('p', { text: 'Choose a new story or the next episode of a series. You review the text before saving it to Reader.' }),
    node('div', { className: 'language-generation-story' }, [
      node('div', { className: 'language-form-grid' }, [field('What are you creating?', storyMode), field('Series', seriesChoice)]),
      previousField, newSeriesFields,
      field('What should happen next?', direction),
      field('What should this episode avoid repeating?', avoid),
      node('div', { className: 'language-form-grid' }, [field('Pacing', pacing), field('Ending', ending)]),
    ]),
    node('div', { className: 'language-form-grid' }, [field('Approximate words', length), field('Difficulty', preset), field('What is it about?', customTopic), field('Style', style)]),
    node('details', { className: 'language-technical-details' }, [
      node('summary', { text: 'Advanced options' }),
      node('div', { className: 'language-form-grid' }, [field('Generation mode', generationMode), field('Known-token target (%)', customCoverage), field('Stored topic', topic), field('Grammar focus', grammar)]),
      node('label', { className: 'language-check language-reference-toggle' }, [referenceEnrichment, node('span', { text: 'Use read-only source-backed reference facts' })]),
      node('div', { className: 'language-generation-provider' }, [
        statusPill(providerReady ? 'Gemini ready' : 'Automatic unavailable', providerReady ? 'success' : 'warning'),
        node('span', { text: providerReady
          ? `${providerHealth.modelId || 'Gemini'} · free tier · key held by the server`
          : `${providerHealth.reason || providerHealth.state || 'Provider not configured'} · manual copy/paste remains available` }),
      ]),
    ]),
    node('div', { className: 'language-form-actions' }, [createRequest]),
  ]);
  form.addEventListener('submit', (event) => { event.preventDefault(); actions.onCreate({
    generationMode: generationMode.value, length: Number(length.value), difficultyPreset: preset.value,
    targetCoverage: Number(customCoverage.value), topicId: topic.value || null,
    customTopic: customTopic.value.trim() || null, grammarFocus: grammar.value.trim() || null,
    styleInstruction: style.value.trim() || null, explicitTargetLemmaIds: [], referenceEnrichment: referenceEnrichment.checked,
    storyMode: storyMode.value, seriesId: seriesChoice.value && seriesChoice.value !== '__new__' ? seriesChoice.value : null,
    previousTextId: storyMode.value === 'CONTINUE' ? previousText.value || null : null,
    episodeDirection: direction.value.trim() || null, avoidRepeating: avoid.value.trim() || null,
    pacing: pacing.value, ending: ending.value,
    ...(seriesChoice.value === '__new__' ? { newSeries: {
      title: seriesTitle.value.trim(), premise: seriesPremise.value.trim(), continuityNotes: seriesNotes.value.trim(),
    } } : {}),
  }); });
  const children = [node('div', { className: 'language-section-heading' }, [node('div', {}, [node('p', { className: 'language-kicker', text: 'ADAPTIVE READING' }), node('h3', { text: 'Generate' }), node('p', { text: 'Create a Norwegian reading text shaped around your vocabulary.' })])]), form];
  if (state.error) children.push(node('p', { className: 'language-form-error', attrs: { role: 'alert' }, text: state.error }));
  if (state.notice) children.push(node('p', { className: 'language-notice', attrs: { role: 'status' }, text: state.notice }));
  if (state.request) {
    const pack = state.contextPack; const files = pack?.files || {};
    const automatic = state.request.generationMode === 'AUTOMATIC';
    if (automatic) {
      const running = ['QUEUED', 'RUNNING'].includes(state.request.automaticStatus);
      const statusCard = node('section', { className: 'language-card language-generation-run', attrs: { role: 'status', 'aria-live': 'polite' } }, [
        node('div', { className: 'language-generation-card-head' }, [
          node('div', {}, [
            node('p', { className: 'language-kicker', text: 'AUTOMATIC GEMINI' }),
            node('h3', { text: state.request.automaticStage?.replaceAll('_', ' ') || 'Ready to start' }),
          ]),
          statusPill(state.request.automaticStatus?.replaceAll('_', ' ') || 'IDLE', state.request.automaticStatus === 'READY' ? 'success' : running ? 'info' : ['FAILED', 'OUT_OF_TOLERANCE'].includes(state.request.automaticStatus) ? 'warning' : 'muted'),
        ]),
        node('progress', { attrs: { max: '1', value: String(state.request.automaticProgress ?? 0), 'aria-label': 'Automatic generation progress' } }),
        node('p', { text: `Attempts ${state.candidates.length} / ${state.request.maxProviderAttempts || 3}. ${state.request.automaticErrorMessage || 'The local analyzer—not Gemini self-reporting—decides coverage and focus-word success.'}` }),
      ]);
      const runControls = node('div', { className: 'language-form-actions' });
      if (state.request.automaticStatus === 'IDLE') {
        const startAutomatic = node('button', { className: 'language-button is-primary', type: 'button', text: 'Generate automatically', disabled: !providerReady });
        startAutomatic.addEventListener('click', actions.onStartAutomatic);
        runControls.append(startAutomatic);
      }
      if (running) {
        const cancel = node('button', { className: 'language-button is-danger', type: 'button', text: 'Cancel after current bounded step' });
        cancel.addEventListener('click', actions.onCancelAutomatic);
        runControls.append(cancel);
      }
      runControls.append(node('span', { text: 'No candidate is auto-accepted.' }));
      statusCard.append(runControls);
      children.push(statusCard);
    }
    const contextCard = node('section', { className: 'language-card language-generation-pack' }, [
      node('p', { className: 'language-kicker', text: 'TECHNICAL DETAILS' }), node('h3', { text: automatic ? 'Inspect the exact provider context' : 'Copy into your external chat' }),
      node('p', { text: `${pack?.estimatedCharacterCount || 0} characters · ${files['metadata.json']?.knownVocabularyIncluded || 0} known lemmas · ${files['metadata.json']?.focusVocabularyCount || 0} focus words · snapshot ${files['metadata.json']?.createdAt || pack?.generatedAt || 'unknown'}` }),
      node('p', { className: 'language-generation-reference-summary', text: files['metadata.json']?.referenceEnrichment?.enabled
        ? `Reference v2 · schema ${files['metadata.json'].referenceEnrichment.schemaVersion} · frozen fingerprint ${files['metadata.json'].referenceEnrichment.referenceFingerprint}`
        : files['metadata.json']?.referenceEnrichment?.requested
          ? 'Reference data unavailable; this request stayed on the compatible v1 contract.'
          : 'Generation v1 · no reference enrichment.' }),
      node('pre', { text: files['prompt.md'] || '' }),
    ]);
    const controls = node('div', { className: 'language-form-actions' });
    [['Copy complete prompt', () => actions.onCopy(files['prompt.md'] || '')], ['Copy known vocabulary', () => actions.onCopy(files['known-vocabulary.txt'] || '')], ['Copy focus vocabulary', () => actions.onCopy(JSON.stringify(files['focus-vocabulary.json'] || {}, null, 2))], ...(files['reference-facts.json'] ? [['Copy reference facts', () => actions.onCopy(JSON.stringify(files['reference-facts.json'], null, 2))]] : []), ['Export context pack', () => actions.onExport(pack)]].forEach(([label, handler]) => { const button = node('button', { className: 'language-button', type: 'button', text: label }); button.addEventListener('click', handler); controls.append(button); });
    contextCard.append(controls); children.push(contextCard);
    const response = node('textarea', { placeholder: '{"title":"…","text":"…"}', attrs: { required: '' } });
    const provider = node('input', { type: 'text', placeholder: 'Provider label (optional)', attrs: { maxlength: '120' } });
    const model = node('input', { type: 'text', placeholder: 'Model label (optional)', attrs: { maxlength: '120' } });
    const plain = node('input', { type: 'checkbox' });
    const importForm = node('form', { className: 'language-card language-generation-import' }, [node('p', { className: 'language-kicker', text: 'PASTE RESPONSE' }), node('h3', { text: 'Import candidate' }), field('External response', response, 'JSON {title,text} is preferred.'), node('div', { className: 'language-form-grid' }, [field('Provider', provider), field('Model', model)]), node('label', { className: 'language-check' }, [plain, node('span', { text: 'Treat as plain text (explicit fallback)' })]), node('button', { className: 'language-button is-primary', type: 'submit', text: 'Import candidate' })]);
    importForm.addEventListener('submit', (event) => { event.preventDefault(); actions.onImport({ response: response.value, providerLabel: provider.value.trim() || null, modelLabel: model.value.trim() || null, treatAsPlainText: plain.checked }); });
    children.push(importForm);
  }
  if (state.candidates.length) children.push(node('section', { className: 'language-generation-history' }, [node('div', { className: 'language-section-heading' }, [node('h3', { text: 'Candidate history' }), node('p', { text: 'Attempts remain separate and retain their original frozen snapshot.' })]), ...state.candidates.map((candidate) => candidateCard(candidate, actions))]));
  replace(mount, node('div', { className: 'language-generation-page' }, children));
}
