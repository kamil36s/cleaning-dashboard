import { wordAudioControl } from './word-audio-control.js';

import {
  DISPOSITIONS,
  KNOWLEDGE_STATUSES,
  dispositionLabel,
  formatLanguageDate,
  knowledgeLabel,
  mappingState,
} from '../model.js';
import { definitionList, field, messageState, node, replace, selectControl, statusPill } from './dom.js';

function scoreSelect(name, value) {
  return selectControl(name, [
    { value: '', label: 'Not scored' },
    ...Array.from({ length: 6 }, (_, score) => ({ value: score, label: `${score} / 5` })),
  ], value ?? '');
}

function readScore(value) {
  return value === '' ? null : Number(value);
}

function renderFormCard(form, handlers) {
  const candidates = Array.isArray(form.candidateMappings) ? form.candidateMappings : [];
  const currentMapping = candidates.find((item) => item.lemmaId === form.lemmaId) || form;
  const state = mappingState(currentMapping);
  const card = node('article', { className: 'language-form-card' });
  const header = node('header', {}, [
    node('strong', { text: form.formDisplay || '—' }),
    statusPill(state.label, state.tone),
  ]);
  const facts = definitionList([
    ['Normalized', form.formNormalized || '—'],
    ['Analyzer/provider', form.providerId || form.mappingProvenance || 'Not reported'],
    ['Provider version', form.providerVersion || '—'],
    ['Ambiguity', form.ambiguityState || 'NOT_REPORTED'],
    ['Lexical status', form.lexicalStatus || 'NOT_ASSESSED'],
    ['Confidence', form.confidence == null ? 'Not reported' : String(form.confidence)],
  ]);

  const mappingSelect = selectControl(`mapping-${form.id}`, candidates.map((candidate) => ({
    value: candidate.lemmaId,
    label: `${candidate.lemmaDisplay || candidate.lemmaId} · ${candidate.partOfSpeech || 'POS not reported'}${candidate.manualLocked ? ' · locked' : ''}`,
  })), currentMapping.lemmaId);
  mappingSelect.setAttribute('aria-label', `Mapping for ${form.formDisplay || 'surface form'}`);
  const lockButton = node('button', {
    className: 'language-button', type: 'button', text: currentMapping.manualLocked ? 'Lock again' : 'Lock mapping',
    disabled: candidates.length === 0,
  });
  const lockStatus = node('p', { className: 'language-form-error', attrs: { role: 'status' }, hidden: true });
  lockButton.addEventListener('click', async () => {
    lockButton.disabled = true;
    lockStatus.hidden = false;
    lockStatus.textContent = 'Saving manual lock…';
    try {
      await handlers.onLockMapping(form.id, mappingSelect.value);
      lockStatus.textContent = 'Manual mapping lock saved.';
    } catch (error) {
      lockStatus.textContent = error?.message || 'Mapping could not be saved.';
      lockButton.disabled = false;
    }
  });
  const controls = node('div', { className: 'language-mapping-controls' }, [
    field('Intended lemma', mappingSelect),
    lockButton,
  ]);

  const evidence = node('details', { className: 'language-evidence' }, [
    node('summary', { text: `Candidate evidence (${candidates.length})` }),
    ...candidates.map((candidate) => definitionList([
      ['Candidate', `${candidate.lemmaDisplay || '—'} · ${candidate.partOfSpeech || 'POS not reported'}`],
      ['Provenance', candidate.mappingProvenance || 'Not reported'],
      ['Manual lock', candidate.manualLocked ? `Yes · ${candidate.manualProvenance || 'manual'}` : 'No'],
      ['Ambiguity', candidate.ambiguityState || 'NOT_REPORTED'],
      ['Morphology', candidate.morphology && Object.keys(candidate.morphology).length
        ? Object.entries(candidate.morphology).map(([key, value]) => `${key}=${value}`).join(', ')
        : 'Not reported'],
    ])),
  ]);
  card.append(header, facts, controls, lockStatus, evidence);
  return card;
}

function renderMergeSection(detail, handlers) {
  const lemma = detail.lemma;
  const input = node('input', { type: 'search', placeholder: 'Search target lemma…', attrs: { autocomplete: 'off' } });
  const searchButton = node('button', { className: 'language-button', type: 'submit', text: 'Find target' });
  const results = node('div', { className: 'language-merge-search-results', attrs: { 'aria-live': 'polite' } });
  const form = node('form', { className: 'language-form' }, [
    field('Target lemma', input),
    searchButton,
    results,
  ]);
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const query = input.value.trim();
    if (!query) {
      replace(results, node('p', { className: 'language-inline-error', text: 'Enter a target lemma.' }));
      return;
    }
    searchButton.disabled = true;
    replace(results, node('p', { text: 'Searching…' }));
    try {
      const matches = (await handlers.onSearchMerge(query)).filter((item) => item.id !== lemma.id);
      if (!matches.length) {
        replace(results, node('p', { text: 'No other matching target lemma was found.' }));
        return;
      }
      replace(results, ...matches.map((target) => {
        const review = node('button', { className: 'language-button is-danger', type: 'button', text: 'Review merge' });
        review.addEventListener('click', () => handlers.onPrepareMerge(target));
        return node('div', { className: 'language-merge-target' }, [
          node('div', {}, [
            node('strong', { text: target.lemmaDisplay || '—' }),
            node('span', { text: `${target.partOfSpeech || 'POS not reported'} · ${knowledgeLabel(target.knowledgeStatus)}` }),
          ]),
          review,
        ]);
      }));
    } catch (error) {
      replace(results, node('p', { className: 'language-inline-error', text: error?.message || 'Search failed.' }));
    } finally {
      searchButton.disabled = false;
    }
  });
  return node('section', { className: 'language-detail-section' }, [
    node('h3', { text: 'Merge duplicate lemma' }),
    node('p', { text: 'Search for an existing target. The merge requires a separate explicit confirmation.' }),
    form,
  ]);
}

function renderAnkiSection(detail, handlers) {
  const anki = detail.anki || {};
  const connection = anki.status?.status || 'NOT_CONFIGURED';
  const link = anki.link;
  const available = ['CONNECTED', 'NOT_CHECKED'].includes(connection);
  const output = node('div', { className: 'language-anki-preview', attrs: { 'aria-live': 'polite' } });
  const previewButton = node('button', {
    className: 'language-button is-primary', type: 'button',
    text: link ? 'Preview Anki sync' : 'Preview add to Anki', disabled: !available,
  });
  previewButton.addEventListener('click', async () => {
    previewButton.disabled = true;
    replace(output, node('p', { text: 'Building read-only preview...' }));
    try {
      const preview = await handlers.onAnkiPreview();
      const confirm = node('button', {
        className: 'language-button is-primary', type: 'button', text: 'Confirm Anki change',
        disabled: ['CONFLICT', 'DUPLICATE_RISK'].includes(preview.action),
      });
      confirm.addEventListener('click', async () => {
        confirm.disabled = true;
        try {
          await handlers.onAnkiCommit(preview);
          replace(output, node('p', { text: 'Anki link is synchronized.' }));
        } catch (error) {
          replace(output, node('p', { className: 'language-inline-error', text: error?.message || 'Anki commit failed.' }));
        }
      });
      const conflicts = preview.conflicts?.length ? node('div', { className: 'language-anki-conflicts' }, preview.conflicts.map((item) => node('article', { className: 'language-form-card' }, [
        node('strong', { text: item.field }),
        definitionList([
          ['Last synced', item.lastSynced || '(blank)'],
          ['Dashboard proposed', item.dashboardProposed || '(blank)'],
          ['Anki current', item.ankiCurrent || '(blank)'],
        ]),
      ]))) : null;
      const resolutions = preview.action === 'CONFLICT' ? node('div', { className: 'language-form-actions' }, [
        ...['DASHBOARD_WINS', 'ANKI_WINS'].map((resolution) => {
          const button = node('button', { className: 'language-button', type: 'button', text: resolution === 'DASHBOARD_WINS' ? 'Keep dashboard' : 'Keep Anki' });
          button.addEventListener('click', async () => {
            button.disabled = true;
            try {
              await handlers.onAnkiResolve(resolution);
              replace(output, node('p', { text: `Conflict resolved: ${resolution === 'DASHBOARD_WINS' ? 'dashboard fields pushed' : 'Anki state accepted'}.` }));
            } catch (error) {
              button.disabled = false;
              replace(output, node('p', { className: 'language-inline-error', text: error?.message || 'Conflict resolution failed.' }));
            }
          });
          return button;
        }),
      ]) : null;
      replace(output, node('div', { className: 'language-anki-preview-card' }, [
        statusPill(preview.action, preview.action === 'CONFLICT' ? 'warning' : 'info'),
        definitionList([
          ['Deck', preview.deckName], ['Model', preview.modelName],
          ['Context', preview.logicalFields?.context || '(none)'],
          ['Translation', preview.logicalFields?.translation || '(blank)'],
          ['Definition', preview.logicalFields?.definition || '(blank)'],
          ['Existing note', preview.existingNoteId || 'None'],
        ], 'language-evidence'),
        conflicts, resolutions, confirm,
      ]));
    } catch (error) {
      replace(output, node('p', { className: 'language-inline-error', text: error?.message || 'Anki preview failed.' }));
      previewButton.disabled = !available;
    }
  });
  const noteId = node('input', { type: 'number', placeholder: 'Existing Anki note ID', attrs: { min: '1' } });
  const linkButton = node('button', { className: 'language-button', type: 'button', text: 'Preview existing note link', disabled: !available });
  linkButton.addEventListener('click', async () => {
    const externalNoteId = Number(noteId.value);
    if (!Number.isInteger(externalNoteId) || externalNoteId <= 0) {
      replace(output, node('p', { className: 'language-inline-error', text: 'Enter a positive Anki note ID.' }));
      return;
    }
    try {
      const preview = await handlers.onAnkiLink(externalNoteId, false);
      const confirm = node('button', { className: 'language-button is-primary', type: 'button', text: 'Confirm link' });
      confirm.addEventListener('click', async () => {
        await handlers.onAnkiLink(externalNoteId, true);
        replace(output, node('p', { text: 'Existing note linked.' }));
      });
      replace(output, node('div', {}, [
        node('p', { text: `Link note ${preview.preview?.externalNoteId} without changing its fields.` }), confirm,
      ]));
    } catch (error) {
      replace(output, node('p', { className: 'language-inline-error', text: error?.message || 'Existing note could not be inspected.' }));
    }
  });
  return node('section', { className: 'language-detail-section language-anki-section' }, [
    node('h3', { text: 'Anki' }),
    node('div', { className: 'language-health-row' }, [
      node('span', { text: link ? `Linked note ${link.externalNoteId}` : 'Not linked' }),
      statusPill(link?.conflictState || connection, link?.conflictState === 'BOTH_CHANGED' ? 'warning' : 'muted'),
    ]),
    link ? definitionList([
      ['Deck', link.deckName], ['Model', link.modelName], ['Last sync', formatLanguageDate(link.lastSyncAt)],
      ['Observed cards', anki.cards?.length || 0],
    ], 'language-evidence') : node('p', { text: available ? 'Preview before any remote write.' : 'Configure or reconnect Anki in Settings.' }),
    node('div', { className: 'language-form-actions' }, [previewButton]),
    node('div', { className: 'language-anki-link-row' }, [noteId, linkButton]),
    output,
  ]);
}

function referenceMetricValue(item) {
  if (item.rank != null) return `#${item.rank}`;
  if (item.rawCount != null) return Number(item.rawCount).toLocaleString();
  if (item.frequencyPerMillion != null) return `${item.frequencyPerMillion} per million`;
  if (item.zipfScore != null) return `${item.zipfScore} Zipf`;
  return 'Available';
}

function renderReferenceSection(detail) {
  const reference = detail.reference || {};
  const resolution = detail.referenceResolution || { status: 'UNAVAILABLE', candidates: [] };
  const tone = resolution.status === 'MATCHED' ? 'ready'
    : resolution.status === 'AMBIGUOUS' ? 'warning'
      : resolution.status === 'UNMATCHED' ? 'muted' : 'error';
  const section = node('section', { className: 'language-detail-section language-reference-section' }, [
    node('p', { className: 'language-kicker', text: 'REFERENCE · READ ONLY' }),
    node('div', { className: 'language-reference-heading' }, [
      node('h3', { text: 'Source-backed lexical reference' }),
      statusPill(resolution.status || 'UNAVAILABLE', tone),
    ]),
    node('p', { className: 'language-reference-boundary', text: 'Reference facts are separate from your knowledge, scores, exposures and Anki state.' }),
  ]);
  if (!reference.available) {
    section.append(node('p', { text: reference.error || 'Reference data is unavailable. Vocabulary and study state remain fully usable.' }));
    return section;
  }
  if (resolution.status === 'AMBIGUOUS' || resolution.status === 'UNMATCHED') {
    const candidates = resolution.candidates || [];
    section.append(candidates.length
      ? node('div', { className: 'language-reference-candidates' }, candidates.map((candidate) => node('article', { className: 'language-form-card' }, [
        node('span', { className: 'language-kicker', text: 'Reference candidate' }),
        node('strong', { text: candidate.canonicalForm || 'Reference candidate' }),
        definitionList([
          ['POS', candidate.partOfSpeech || 'Not reported'],
          ['Identity', candidate.stableKey || candidate.id || '—'],
          ['Match basis', candidate.matchBasis || 'Review required'],
        ]),
      ])))
      : node('p', { text: 'No exact reference candidate was found. No fuzzy selection was made.' }));
    if (resolution.status !== 'MATCHED') return section;
  }
  const unit = reference.unit;
  if (unit) section.append(definitionList([
    ['Canonical reference lemma', unit.canonicalForm],
    ['Part of speech', unit.partOfSpeech || 'Not reported'],
    ['Reference identity', unit.stableKey],
    ['Resolver rule', resolution.ruleVersion || 'reference-resolver/v1'],
    ['CEFR', reference.cefrAvailable ? 'Source evidence available below' : 'Not available'],
  ], 'language-evidence'));
  const evidence = reference.frequencyEvidence || [];
  section.append(node('details', { open: true }, [
    node('summary', { text: `Frequency and rank evidence (${evidence.length})` }),
    evidence.length
      ? node('div', { className: 'language-reference-list' }, evidence.map((item) => node('div', { className: 'language-reference-row' }, [
        node('div', {}, [node('strong', { text: item.label || item.metricType }), node('small', { text: `${item.sourceName || item.sourceId} · ${item.sourceVersion || 'version not reported'} · ${item.scope || 'REFERENCE_UNIT'}` })]),
        node('span', { text: referenceMetricValue(item), attrs: { title: item.methodVersion ? `${item.method || 'Derived method'} · ${item.methodVersion}` : item.metricType } }),
      ])))
      : node('p', { text: 'No source-specific frequency evidence is available.' }),
  ]));
  const forms = reference.forms || [];
  section.append(node('details', {}, [
    node('summary', { text: `Reference morphology (${forms.length})` }),
    forms.length
      ? node('div', { className: 'language-reference-forms' }, forms.slice(0, 24).map((form) => node('span', {
        className: 'language-reference-form',
        text: `${form.displayForm}${Object.keys(form.morphology || {}).length ? ` · ${Object.entries(form.morphology).map(([key, value]) => `${key}=${value}`).join(', ')}` : ''}`,
      })))
      : node('p', { text: 'No reference forms are available.' }),
  ]));
  const expressions = reference.expressions || [];
  section.append(node('details', {}, [
    node('summary', { text: `Expressions (${expressions.length})` }),
    expressions.length
      ? node('ul', {}, expressions.map((item) => node('li', { text: `${item.canonicalForm} · ${item.unitType}` })))
      : node('p', { text: 'No linked idiom or MWE evidence is available.' }),
  ]));
  const sources = reference.sources || [];
  section.append(node('details', {}, [
    node('summary', { text: `Sources (${sources.length})` }),
    sources.length
      ? node('ul', {}, sources.map((source) => node('li', { text: `${source.name || source.sourceId} · ${source.provider} · ${source.version}${source.license ? ` · ${source.license}` : ''}` })))
      : node('p', { text: 'No bounded provenance rows are available.' }),
  ]));
  return section;
}

function renderUserTranslations(detail, handlers) {
  const lexical = detail.lexical || {};
  const translations = lexical.translations?.user || [];
  const preferred = lexical.preferredTranslationLocales?.length
    ? lexical.preferredTranslationLocales : ['pl-PL', 'en'];
  const locale = node('select', {}, preferred.map((value) => node('option', {
    text: value, attrs: { value },
  })));
  const value = node('input', { type: 'text', placeholder: 'Your translation', attrs: { maxlength: '2000' } });
  const status = node('span', { className: 'language-definition', attrs: { role: 'status' } });
  const save = node('button', { className: 'language-button', type: 'button', text: 'Save translation' });
  save.addEventListener('click', async () => {
    if (!value.value.trim()) { status.textContent = 'Enter a translation.'; return; }
    save.disabled = true; status.textContent = 'Saving…';
    try {
      await handlers.onSaveTranslation(locale.value, value.value.trim());
      status.textContent = 'User translation saved separately from provider facts.';
    } catch (error) { status.textContent = error?.message || 'Translation could not be saved.'; save.disabled = false; }
  });
  return node('div', { className: 'language-user-translations' }, [
    node('h4', { text: 'Your translations' }),
    translations.length ? node('ul', {}, translations.map((item) => {
      const remove = node('button', { className: 'language-button is-quiet', type: 'button', text: 'Delete' });
      remove.addEventListener('click', () => handlers.onDeleteTranslation(item.targetLocale));
      return node('li', {}, [node('strong', { text: `${item.targetLocale}: ` }), node('span', { text: item.translationText }), remove]);
    })) : node('p', { text: 'No user translation saved.' }),
    node('div', { className: 'language-form-actions' }, [locale, value, save, status]),
  ]);
}

function renderLexicalSection(detail) {
  const lexical = detail.lexical || {};
  const dictionary = lexical.dictionary || { available: false, lookupStatus: 'NOT_LOADED', articles: [] };
  const section = node('section', { className: 'language-detail-section language-meanings-section' }, [
    node('p', { className: 'language-kicker', text: 'MEANINGS · READ ONLY' }),
    node('div', { className: 'language-reference-heading' }, [
      node('h3', { text: 'Dictionary meanings' }),
      statusPill(dictionary.lookupStatus || 'UNAVAILABLE', dictionary.lookupStatus === 'MATCHED' ? 'ready' : 'muted'),
    ]),
  ]);
  if (!dictionary.available) {
    section.append(node('p', { text: dictionary.reason || 'The runtime dictionary provider is unavailable. Local reference facts remain usable.' }));
  } else if (!(dictionary.articles || []).length) {
    section.append(node('p', { text: dictionary.lookupStatus === 'POS_MISMATCH'
      ? 'The spelling exists, but no article matched this lemma part of speech. Nothing was guessed.'
      : 'No matching dictionary sense was found.' }));
  } else {
    (dictionary.articles || []).forEach((article) => {
      const card = node('article', { className: 'language-dictionary-article' }, [
        node('h4', { text: `${(article.lemmas || []).join(', ') || 'Dictionary article'} · ${(article.partsOfSpeech || []).join(', ') || 'POS not reported'}` }),
      ]);
      if (article.pronunciations?.length) card.append(node('p', { text: `Pronunciation supplied by source: ${article.pronunciations.join(' · ')}` }));
      const senses = article.senses || [];
      card.append(senses.length ? node('ol', { className: 'language-sense-list' }, senses.map((sense) => node('li', {}, [
        node('p', { className: 'language-definition', text: sense.definition }),
        sense.usageLabels?.length ? node('p', { text: `Usage: ${sense.usageLabels.join(', ')}` }) : null,
        sense.examples?.length ? node('ul', {}, sense.examples.map((example) => node('li', { text: example }))) : null,
        sense.relations?.length ? node('p', { text: `Related: ${sense.relations.map((item) => `${item.type}: ${item.term}`).join(' · ')}` }) : null,
        node('small', { text: `Sense ${sense.sourceLocalId} · ${article.sourceVersion}` }),
      ]))) : node('p', { text: 'The source article has no displayable definition.' }));
      section.append(card);
    });
  }
  const glosses = lexical.translations?.learnerGlosses || [];
  section.append(node('details', { open: true }, [
    node('summary', { text: `English learner glosses (${glosses.length})` }),
    glosses.length ? node('ul', {}, glosses.map((item) => node('li', {}, [
      node('strong', { text: item.value }),
      node('small', { text: ` · SOURCE_GLOSS · ${item.role} · ${item.source?.name || item.source?.id}` }),
    ]))) : node('p', { text: 'No English learner gloss is available.' }),
  ]));
  const machine = lexical.translations?.machine || [];
  if (machine.length) section.append(node('p', { text: machine.map((item) =>
    `${item.targetLocale.toUpperCase()}: ${item.value} (automatic · ${item.source})`).join(' · ') }));
  else if (!lexical.translations?.user?.some((item) => String(item.targetLocale || '').startsWith('pl')))
    section.append(node('p', { text: 'No Polish translation is available here. Check the dictionaries below.' }));
  const term = encodeURIComponent(detail.lemma?.lemmaDisplay || '');
  if (term) section.append(node('div', { className: 'language-word-sources' }, [
    ['Bokmålsordboka', `https://ordbokene.no/bm/${term}`],
    ['NAOB', `https://naob.no/ordbok/${term}`],
    ['Wiktionary EN', `https://en.wiktionary.org/wiki/${term}`],
    ['Glosbe EN', `https://glosbe.com/nb/en/${term}`],
    ['Wikisłownik PL', `https://pl.wiktionary.org/wiki/${term}`],
  ].map(([label, href]) => node('a', { className: 'language-button', text: label,
    attrs: { href, target: '_blank', rel: 'noopener noreferrer' } }))));
  if (dictionary.provider) section.append(node('details', {}, [
    node('summary', { text: 'Dictionary source and license' }),
    node('p', { text: `${dictionary.provider.id} · ${dictionary.provider.version} · ${dictionary.provider.license}` }),
    node('p', { text: dictionary.provider.attribution }),
  ]));
  return section;
}

export function renderReferenceOnlyDetail(mount, payload) {
  if (!payload) {
    replace(mount, messageState('loading', 'Loading curriculum lexical detail…'));
    return;
  }
  const item = payload.item || {};
  const detail = {
    reference: payload.reference || { available: false },
    referenceResolution: payload.resolution || { status: 'UNAVAILABLE', candidates: [] },
    lexical: payload.lexical || {},
  };
  replace(mount, node('article', { className: 'language-detail' }, [
    node('header', { className: 'language-detail-header' }, [
      node('p', { className: 'language-kicker', text: 'CURRICULUM ITEM · READ ONLY' }),
      node('h2', { id: 'language-lemma-dialog-title', text: item.displayTerm || 'Curriculum item' }),
      node('p', { text: `${item.mappingState || 'UNRESOLVED'} · ${item.user?.state || 'NOT ELIGIBLE'}` }),
      node('p', { className: 'language-reference-boundary', text: 'Opening this source item does not create a vocabulary lemma or change your knowledge state.' }),
    ]),
    node('div', { className: 'language-detail-layout' }, [
      node('div', {}, [
        node('section', { className: 'language-detail-section' }, [
          node('h3', { text: 'Curriculum membership' }),
          definitionList([
            ['Display term', item.displayTerm],
            ['Learning state', item.user?.state || 'NOT_ELIGIBLE'],
            ['Mapping state', item.mappingState],
            ['Review state', item.reviewState],
            ['Priority', item.priority],
            ['Membership ID', item.membershipId],
            ['Source membership', item.sourceMembershipId],
          ], 'language-evidence'),
        ]),
      ]),
      node('aside', {}, [renderLexicalSection(detail), renderReferenceSection(detail)]),
    ]),
  ]));
}

export function renderLemmaDetail(mount, detail, handlers) {
  if (!detail) {
    replace(mount, messageState('loading', 'Loading lemma…'));
    return;
  }
  const lemma = detail.lemma || {};
  const knowledge = detail.knowledge || {};
  const merged = Boolean(lemma.mergedIntoId);
  const statusSelect = selectControl('knowledgeStatus', KNOWLEDGE_STATUSES.map((value) => ({ value, label: knowledgeLabel(value) })), knowledge.knowledgeStatus);
  const dispositionSelect = selectControl('disposition', DISPOSITIONS.map((value) => ({ value, label: dispositionLabel(value) })), knowledge.disposition);
  const recognition = scoreSelect('recognition', knowledge.recognition);
  const recall = scoreSelect('recall', knowledge.recall);
  const production = scoreSelect('production', knowledge.production);
  const notes = node('textarea', { name: 'userNotes', text: lemma.userNotes || '', attrs: { maxlength: '10000' } });
  const save = node('button', { className: 'language-button is-primary', type: 'submit', text: 'Save vocabulary state', disabled: merged });
  const error = node('p', { className: 'language-form-error', attrs: { role: 'alert' }, hidden: true });
  const form = node('form', { className: 'language-form' }, [
    node('div', { className: 'language-form-grid' }, [
      field('Knowledge status', statusSelect),
      field('Disposition', dispositionSelect),
      field('Recognition', recognition),
      field('Recall', recall),
      field('Production', production),
    ]),
    field('User notes', notes),
    node('div', { className: 'language-form-actions' }, [save, error]),
  ]);
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    save.disabled = true;
    error.hidden = false;
    error.textContent = 'Saving…';
    try {
      await handlers.onSave({
        knowledgeStatus: statusSelect.value,
        disposition: dispositionSelect.value,
        recognition: readScore(recognition.value),
        recall: readScore(recall.value),
        production: readScore(production.value),
        userNotes: notes.value.trim() || null,
      });
      error.textContent = 'Saved to canonical vocabulary.';
    } catch (saveError) {
      error.textContent = saveError?.message || 'Vocabulary state could not be saved.';
      save.disabled = false;
    }
  });

  const header = node('header', { className: 'language-detail-header' }, [
    node('p', { className: 'language-kicker', text: merged ? 'MERGED LEMMA REDIRECT' : 'VOCABULARY LEMMA' }),
    node('h2', { id: 'language-lemma-dialog-title', text: lemma.lemmaDisplay || 'Lemma detail' }),
    node('p', { text: `${lemma.lemmaNormalized || 'No normalized lemma'} · ${lemma.partOfSpeech || 'POS not reported'} · ID ${lemma.id || '—'}` }),
    wordAudioControl(mount.ownerDocument, !merged ? handlers.onPlayAudio : null),
    merged ? node('a', { className: 'language-button', text: 'Open target lemma', attrs: { href: `#vocabulary/lemma/${encodeURIComponent(lemma.mergedIntoId)}` } }) : null,
  ]);

  const knowledgeSection = node('section', { className: 'language-detail-section' }, [
    node('p', { className: 'language-kicker', text: 'USER KNOWLEDGE' }),
    node('h3', { text: 'Knowledge and notes' }),
    form,
    definitionList([
      ['Total exposures', knowledge.totalExposures ?? 0],
      ['First seen', formatLanguageDate(knowledge.firstSeenAt)],
      ['Last seen', formatLanguageDate(knowledge.lastSeenAt)],
      ['Last review', formatLanguageDate(knowledge.lastReviewAt)],
      ['Manual status override', knowledge.manualStatusOverride ? 'Yes' : 'No'],
      ['Manual score override', knowledge.manualScoresOverride ? 'Yes' : 'No'],
    ], 'language-evidence'),
    renderUserTranslations(detail, handlers),
  ]);

  const formsSection = node('section', { className: 'language-detail-section' }, [
    node('h3', { text: `Forms and mapping evidence (${detail.forms?.length || 0})` }),
    detail.forms?.length
      ? node('div', { className: 'language-forms' }, detail.forms.map((item) => renderFormCard(item, handlers)))
      : node('p', { text: 'No surface forms are linked yet.' }),
  ]);

  const frequencySection = node('section', { className: 'language-detail-section' }, [
    node('h3', { text: 'Frequency evidence' }),
    detail.frequencies?.length
      ? node('div', { className: 'language-forms' }, detail.frequencies.map((frequency) => node('div', { className: 'language-form-card' }, [
        statusPill(`${Number(frequency.score).toFixed(2)} Zipf`, 'info'),
        definitionList([
          ['Metric', frequency.metric],
          ['Provider', frequency.providerId],
          ['Provider version', frequency.providerVersion],
          ['Match basis', frequency.matchKind],
          ['Lookup value', frequency.lookupValue],
          ['Exact rank', 'Not configured'],
        ]),
      ])))
      : node('p', { text: 'No Zipf frequency evidence is stored for this lemma.' }),
  ]);

  const historySection = node('section', { className: 'language-detail-section' }, [
    node('h3', { text: 'Recent evidence history' }),
    detail.events?.length
      ? node('div', { className: 'language-forms' }, detail.events.slice(-5).reverse().map((event) => node('div', { className: 'language-form-card' }, [
        node('strong', { text: event.eventType || 'Event' }),
        node('div', { text: `${event.source || 'Unknown source'} · ${formatLanguageDate(event.createdAt)}` }),
      ])))
      : node('p', { text: 'No knowledge events have been recorded.' }),
  ]);

  const primary = node('div', {}, [knowledgeSection, formsSection]);
  const secondary = node('aside', {}, [
    renderLexicalSection(detail),
    renderReferenceSection(detail),
    renderAnkiSection(detail, handlers),
    frequencySection,
    historySection,
    !merged ? renderMergeSection(detail, handlers) : null,
  ]);
  replace(mount, node('article', { className: 'language-detail' }, [
    header,
    node('div', { className: 'language-detail-layout' }, [primary, secondary]),
  ]));
}

export function renderLemmaError(mount, message, { notFound = false } = {}) {
  replace(mount, messageState('error', notFound ? 'Lemma was not found.' : 'Lemma could not be loaded.', message));
}
