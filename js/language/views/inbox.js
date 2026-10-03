import { field, node, replace, statusPill } from '../components/dom.js';

const SOURCE_LABELS = {
  PASTED_TEXT: 'Paste Norwegian text',
  LOCAL_AUDIO: 'Upload audio',
  LOCAL_TRANSCRIPT: 'Upload transcript',
  LOCAL_AUDIO_PLUS_TRANSCRIPT: 'Upload audio + transcript',
  ARTICLE_REFERENCE: 'Add article reference',
  PODCAST_REFERENCE: 'Add podcast reference',
  VIDEO_REFERENCE: 'Add video reference',
  NRK_REFERENCE: 'Add NRK reference',
};

const STATUS_LABELS = {
  IMPORTED: 'Imported', ANALYZING: 'Analyzing', READY_READER: 'Reader-ready',
  NEEDS_TRANSCRIPT: 'Needs transcript', NEEDS_ALIGNMENT: 'Needs alignment',
  ALIGNING: 'Aligning', READY_LISTENING: 'Listening-ready', REFERENCE_ONLY: 'Reference only',
  FAILED: 'Failed', UNSUPPORTED: 'Unsupported',
};

function statusTone(value) {
  if (value === 'READY_READER' || value === 'READY_LISTENING') return 'ready';
  if (value === 'FAILED' || value === 'UNSUPPORTED') return 'danger';
  return 'warning';
}

function coverageCopy(coverage) {
  if (!coverage) return 'Personal vocabulary coverage is available after canonical analysis.';
  const counts = coverage.counts || coverage;
  const token = coverage.tokenCoveragePercent ?? coverage.tokenCoverage?.percent ?? 0;
  const unique = coverage.uniqueLemmaCoveragePercent ?? coverage.uniqueLemmaCoverage?.percent ?? 0;
  return `${token}% token coverage · ${unique}% unique-lemma coverage · ${counts.unknown ?? 0} unknown · ${counts.learning ?? 0} learning · ${counts.ambiguous ?? 0} ambiguous`;
}

export function renderInboxLanding(mount, state, handlers = {}) {
  const sourceType = node('select', {}, Object.entries(SOURCE_LABELS).map(([value, text]) => (
    node('option', { text, attrs: { value } })
  )));
  const title = node('input', { type: 'text', attrs: { maxlength: '500', placeholder: 'Content title' } });
  const text = node('textarea', { attrs: { rows: '8', placeholder: 'Paste Norwegian text or transcript…' } });
  const uri = node('input', { type: 'url', attrs: { placeholder: 'https://…' } });
  const audio = node('input', { type: 'file', attrs: { accept: '.mp3,.m4a,.wav,.ogg,audio/mpeg,audio/mp4,audio/wav,audio/ogg' } });
  const transcript = node('input', { type: 'file', attrs: { accept: '.txt,.srt,.vtt,text/plain,text/vtt' } });
  const format = node('select', {}, [
    node('option', { text: 'Plain transcript', attrs: { value: 'PLAIN' } }),
    node('option', { text: 'SRT subtitles', attrs: { value: 'SRT' } }),
    node('option', { text: 'WebVTT subtitles', attrs: { value: 'VTT' } }),
  ]);
  const textField = field('Text / transcript', text);
  const uriField = field('External reference URL', uri);
  const audioField = field('Audio file · MP3, M4A, WAV or OGG · max 64 MiB', audio);
  const transcriptField = field('Optional transcript file', transcript);
  const formatField = field('Transcript format', format);
  const submit = node('button', { type: 'submit', className: 'language-button is-primary', text: 'Add content' });
  const sourceHint = node('p', { className: 'language-definition', attrs: { role: 'status' } });
  const form = node('form', { className: 'language-card language-inbox-form' }, [
    node('p', { className: 'language-kicker', text: 'NEW MATERIAL' }),
    node('h3', { text: 'What are you adding?' }),
    node('p', { text: 'Local user-owned files may be stored. External URLs stay reference-only and are never fetched by the server.' }),
    node('div', { className: 'language-form-grid' }, [field('Material type', sourceType), field('Title', title)]),
    sourceHint,
    textField, uriField, audioField, transcriptField, formatField,
    node('div', { className: 'language-form-actions' }, [submit]),
  ]);
  function updateFields() {
    const value = sourceType.value;
    const reference = value.endsWith('_REFERENCE');
    const hasAudio = value === 'LOCAL_AUDIO' || value === 'LOCAL_AUDIO_PLUS_TRANSCRIPT';
    const hasTranscript = value === 'LOCAL_TRANSCRIPT' || value === 'LOCAL_AUDIO_PLUS_TRANSCRIPT';
    sourceHint.textContent = reference ? 'Save a reference link for later. This does not fetch or store the linked page.'
      : hasAudio ? 'Choose a local audio file you own; add a transcript if available.'
      : hasTranscript ? 'Add a transcript you can study or pair with audio.'
      : 'Paste a Norwegian text to make it available for study.';
    textField.hidden = !(value === 'PASTED_TEXT' || hasTranscript);
    uriField.hidden = !reference;
    audioField.hidden = !hasAudio;
    transcriptField.hidden = !hasTranscript;
    formatField.hidden = !hasTranscript;
  }
  sourceType.addEventListener('change', updateFields);
  updateFields();
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    submit.disabled = true;
    try {
      await handlers.onAdd?.({
        sourceType: sourceType.value, title: title.value.trim(), text: text.value,
        sourceUri: uri.value.trim(), audioFile: audio.files?.[0] || null,
        transcriptFile: transcript.files?.[0] || null, format: format.value,
      });
      form.reset(); updateFields();
    } finally { submit.disabled = false; }
  });

  const cards = (state.items || []).map((item) => {
    const open = node('button', { type: 'button', className: 'language-button', text: 'Inspect content' });
    open.addEventListener('click', () => handlers.onOpen?.(item.id));
    return node('article', { className: 'language-card language-inbox-item' }, [
      node('div', {}, [
        node('p', { className: 'language-kicker', text: SOURCE_LABELS[item.sourceType] || item.sourceType || 'CONTENT' }),
        node('h3', { text: item.title || 'Untitled content' }),
        node('div', { className: 'language-inbox-statuses' }, [
          statusPill(STATUS_LABELS[item.status] || item.status, statusTone(item.status)),
          statusPill(item.rightsStatus === 'STORAGE_NOT_AUTHORIZED' ? 'Storage not authorized' : 'Local storage allowed', item.rightsStatus === 'STORAGE_NOT_AUTHORIZED' ? 'warning' : 'ready'),
        ]),
        node('p', { text: item.sourceUri || item.originalDisplayName || item.sourceName || 'Local user-provided material' }),
      ]), open,
    ]);
  });
  replace(mount, node('div', { className: 'language-inbox-view' }, [
    form,
    state.error ? node('p', { className: 'language-form-error', text: state.error }) : null,
    node('section', { className: 'language-inbox-section' }, [
      node('div', {}, [node('p', { className: 'language-kicker', text: 'INTAKE PIPELINE' }), node('h3', { text: 'Your content' })]),
      state.loading && !cards.length ? node('p', { className: 'language-empty-copy', text: 'Loading Content Inbox…' }) : null,
      cards.length ? node('div', { className: 'language-inbox-grid' }, cards)
        : node('p', { className: 'language-empty-copy', text: 'No content has been added yet.' }),
    ]),
  ]));
}

export function renderInboxDetail(mount, state, handlers = {}) {
  const detail = state.detail || {};
  const item = detail.item || {};
  const transcript = detail.currentTranscript;
  const alignments = detail.alignments || [];
  const refresh = node('button', { type: 'button', className: 'language-button', text: 'Refresh status' });
  refresh.addEventListener('click', () => handlers.onRefresh?.());
  const addTranscript = node('form', { className: 'language-card language-inbox-form' });
  const transcriptText = node('textarea', { attrs: { rows: '7', placeholder: 'Paste transcript text or subtitle cues…' } });
  const transcriptFile = node('input', { type: 'file', attrs: { accept: '.txt,.srt,.vtt,text/plain,text/vtt' } });
  const format = node('select', {}, ['PLAIN', 'SRT', 'VTT'].map((value) => node('option', { text: value, attrs: { value } })));
  const submit = node('button', { type: 'submit', className: 'language-button is-primary', text: transcript ? 'Add transcript revision' : 'Add transcript' });
  addTranscript.append(
    node('p', { className: 'language-kicker', text: 'TRANSCRIPT' }),
    node('h3', { text: transcript ? 'Preserve the source and add a new revision' : 'Attach transcript' }),
    field('Format', format), field('Transcript file', transcriptFile), field('Transcript text', transcriptText),
    node('div', { className: 'language-form-actions' }, [submit]),
  );
  addTranscript.addEventListener('submit', async (event) => {
    event.preventDefault(); submit.disabled = true;
    try {
      let value = transcriptText.value;
      if (transcriptFile.files?.[0]) value = await transcriptFile.files[0].text();
      await handlers.onTranscript?.({ format: format.value, transcriptText: value });
    } finally { submit.disabled = false; }
  });

  const alignmentRows = alignments.slice(0, 100).map((alignment) => {
    const start = node('input', { type: 'number', value: String(alignment.startMs), attrs: { min: '0', step: '1', 'aria-label': 'Sentence start milliseconds' } });
    const end = node('input', { type: 'number', value: String(alignment.endMs), attrs: { min: '1', step: '1', 'aria-label': 'Sentence end milliseconds' } });
    const save = node('button', { type: 'button', className: 'language-button', text: 'Save timing' });
    save.addEventListener('click', () => handlers.onAlignment?.(alignment.id, { startMs: Number(start.value), endMs: Number(end.value) }));
    return node('li', { className: 'language-alignment-row' }, [
      node('div', {}, [
        node('strong', { text: `${Number(alignment.sentenceOrder) + 1}. ${alignment.exactText || ''}` }),
        node('small', { text: `${alignment.method} · ${alignment.confidenceBasis || 'CONFIDENCE_NOT_REPORTED'} · ${alignment.exposureEligible ? 'exposure eligible' : 'activity only'}` }),
      ]), node('div', { className: 'language-alignment-controls' }, [start, node('span', { text: 'to' }), end, save]),
    ]);
  });
  replace(mount, node('div', { className: 'language-inbox-view' }, [
    node('div', { className: 'language-reader-actions' }, [node('a', { className: 'language-button', text: '← Content Inbox', attrs: { href: '#inbox' } })]),
    node('section', { className: 'language-card language-inbox-detail' }, [
      node('p', { className: 'language-kicker', text: `${item.sourceType || 'CONTENT'} · ${item.rightsPolicyVersion || detail.rightsPolicyVersion || ''}` }),
      node('h2', { text: item.title || 'Content' }),
      node('div', { className: 'language-inbox-statuses' }, [
        statusPill(STATUS_LABELS[item.status] || item.status || 'UNKNOWN', statusTone(item.status)),
        statusPill(item.rightsStatus || 'UNKNOWN_RIGHTS', item.rightsStatus === 'STORAGE_NOT_AUTHORIZED' ? 'warning' : 'ready'),
      ]),
      node('p', { text: item.sourceUri || item.sourceName || 'User-provided local material' }),
      node('p', { className: 'language-definition', text: `Retention: ${item.retentionPolicy || 'not specified'} · License: ${item.license || 'not specified'} · Attribution: ${item.attribution || 'not required/provided'}` }),
      node('div', { className: 'language-form-actions' }, [
        detail.document?.processingState === 'ANALYZED' ? node('a', { className: 'language-button', text: 'Open in Reader', attrs: { href: `#reader/text/${detail.document.id}` } }) : null,
        item.status === 'READY_LISTENING' ? node('a', { className: 'language-button is-primary', text: 'Study in Listening', attrs: { href: `#listening/content/${item.id}` } }) : null,
        refresh,
      ]),
    ]),
    node('section', { className: 'language-card' }, [
      node('p', { className: 'language-kicker', text: 'PERSONAL COMPREHENSIBILITY · NOT CEFR' }),
      node('h3', { text: 'Vocabulary coverage for this learner' }),
      node('p', { text: coverageCopy(detail.coverage) }),
      node('p', { className: 'language-definition', text: `Coverage policy: ${detail.coverage?.policyVersion || 'pending canonical analysis'} · No reading-level or CEFR claim.` }),
    ]),
    item.status !== 'REFERENCE_ONLY' ? addTranscript : null,
    node('section', { className: 'language-card' }, [
      node('p', { className: 'language-kicker', text: `SENTENCE ALIGNMENT · ${detail.alignmentPolicyVersion || ''}` }),
      node('h3', { text: alignments.length ? `${alignments.length} aligned sentences` : 'No sentence timeline' }),
      node('p', { text: alignments.length
        ? 'Imported source timestamps are mapped deterministically. Manual corrections create a new version and remain authoritative.'
        : `${detail.forcedAlignment?.state || 'UNAVAILABLE'}: ${detail.forcedAlignment?.reason || 'No timestamped transcript.'}` }),
      alignmentRows.length ? node('ol', { className: 'language-alignment-list' }, alignmentRows) : null,
      alignments.length > alignmentRows.length ? node('p', { className: 'language-definition', text: `Showing the first ${alignmentRows.length} rows; playback loads one bounded timeline map.` }) : null,
    ]),
  ]));
}

export { SOURCE_LABELS, STATUS_LABELS };
