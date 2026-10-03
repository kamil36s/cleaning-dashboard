import { analyzerRuntimeStatus, providerStatus } from '../model.js';
import { definitionList, field, node, replace, statusPill } from '../components/dom.js';

function referenceRow(title, description, status, tone = 'muted') {
  return node('div', { className: 'language-reference-row' }, [
    node('div', {}, [node('strong', { text: title }), node('small', { text: description })]),
    statusPill(status, tone),
  ]);
}

export function renderSettings(mount, {
  profile, health, onSaveProfile, anki = {}, onSaveAnki = async () => {},
  onTestAnki = async () => {}, onDiscoverAnki = async () => ({ decks: [], models: [], fields: [] }),
  listening = {}, onSaveListening = () => {},
}) {
  const analyzer = health?.canonicalAnalyzer || {};
  const analyzerState = analyzerRuntimeStatus(analyzer.runtimeState);
  const frequency = health?.referenceProviders?.zipfFrequency || null;
  const dictionary = health?.referenceProviders?.dictionary || null;
  const translations = health?.referenceProviders?.translations || {};
  const frequencyState = providerStatus(frequency);

  const nameInput = node('input', { type: 'text', value: profile?.displayName || '', attrs: { maxlength: '120', required: '' } });
  const translationsInput = node('input', {
    type: 'text',
    value: Array.isArray(profile?.translationLocales) ? profile.translationLocales.join(', ') : '',
    placeholder: 'pl-PL, en-GB',
  });
  const saveButton = node('button', { className: 'language-button is-primary', type: 'submit', text: 'Save profile' });
  const saveStatus = node('p', { className: 'language-form-error', attrs: { role: 'status', 'aria-live': 'polite' }, hidden: true });
  const profileForm = node('form', { className: 'language-form' }, [
    node('div', { className: 'language-form-grid' }, [
      field('Display name', nameInput),
      field('Translation locale preferences', translationsInput),
    ]),
    definitionList([
      ['Language code', profile?.languageCode || '—'],
      ['Locale', profile?.locale || '—'],
      ['Profile status', profile?.status || '—'],
    ], 'language-evidence'),
    node('div', { className: 'language-form-actions' }, [saveButton, saveStatus]),
  ]);
  profileForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    saveButton.disabled = true;
    saveStatus.hidden = false;
    saveStatus.textContent = 'Saving…';
    try {
      const translationLocales = translationsInput.value.split(',').map((value) => value.trim()).filter(Boolean);
      await onSaveProfile({ displayName: nameInput.value.trim(), translationLocales });
      saveStatus.textContent = 'Profile saved.';
    } catch (error) {
      saveStatus.textContent = error?.message || 'Profile could not be saved.';
    } finally {
      saveButton.disabled = false;
    }
  });

  const profileCard = node('section', { className: 'language-card language-settings-card is-wide' }, [
    node('p', { className: 'language-kicker', text: 'PROFILE' }),
    node('h3', { text: 'Norwegian Bokmål' }),
    node('p', { text: 'These are the currently supported user-editable profile fields.' }),
    profileForm,
  ]);

  const analyzerCard = node('section', { className: 'language-card language-settings-card' }, [
    node('p', { className: 'language-kicker', text: 'ANALYZER' }),
    node('h3', { text: 'Stanza Bokmål' }),
    node('p', { text: 'The analyzer remains lazy. Opening this page does not construct or download its model.' }),
    statusPill(analyzerState.label, analyzerState.tone),
    definitionList([
      ['Analyzer ID', analyzer.id || profile?.analyzerId || '—'],
      ['Adapter version', analyzer.adapterVersion || profile?.analyzerVersion || '—'],
      ['Model version', analyzer.modelVersion || '—'],
      ['Processors', Array.isArray(analyzer.processors) ? analyzer.processors.join(', ') : '—'],
      ['Network policy', profile?.analyzerSettings?.runtimeNetworkPolicy || 'Offline only'],
    ], 'language-evidence'),
  ]);

  const frequencyCard = node('section', { className: 'language-card language-settings-card' }, [
    node('p', { className: 'language-kicker', text: 'FREQUENCY' }),
    node('h3', { text: 'Zipf score only' }),
    node('p', { text: 'wordfreq supplies an approximate Zipf frequency score. It is not an exact lemma rank or a Top-N band.' }),
    statusPill(frequencyState.label, frequencyState.tone),
    definitionList([
      ['Provider', frequency?.id || 'Not configured'],
      ['Version', frequency?.version || '—'],
      ['Metric', frequency?.metric || 'ZIPF_FREQUENCY'],
      ['Exact rank/bands', 'Not configured'],
    ], 'language-evidence'),
  ]);

  const referencesCard = node('section', { className: 'language-card language-settings-card is-wide' }, [
    node('p', { className: 'language-kicker', text: 'REFERENCE DATA' }),
    node('h3', { text: 'Lexical sources' }),
    node('p', { text: 'Provider facts are read only and remain separate from user notes, translations and learning state.' }),
    node('div', { className: 'language-reference-list' }, [
      referenceRow('Bokmålsordboka', dictionary
        ? `${dictionary.version} · ${dictionary.license} · live on explicit lemma lookup · no cache`
        : 'Provider not configured.', dictionary?.availability || 'Not configured', dictionary ? 'ready' : 'muted'),
      referenceRow('English learner gloss', 'KELLY evidence is shown as SOURCE_GLOSS, never as a dictionary sense.', translations.englishLearnerGloss || 'Unavailable', 'ready'),
      referenceRow('Polish provider translation', 'No accepted open source is configured; user translations remain available.', translations.polish || 'Not configured'),
      referenceRow('CEFR', 'No versioned source is selected.', 'Not configured'),
      referenceRow('Exact ranked frequency dataset', 'Zipf scores are not converted into ranks.', 'Not configured'),
    ]),
  ]);

  const config = anki.config || { enabled: false, autoSync: false, endpoint: 'http://127.0.0.1:8765', deckName: '', modelName: '', fieldMap: {} };
  const enabled = node('input', { type: 'checkbox', checked: Boolean(config.enabled) });
  enabled.checked = Boolean(config.enabled);
  const autoSync = node('input', { type: 'checkbox', checked: Boolean(config.autoSync) });
  autoSync.checked = Boolean(config.autoSync);
  const endpoint = node('input', { type: 'url', value: config.endpoint || 'http://127.0.0.1:8765', attrs: { required: '' } });
  const deck = node('input', { type: 'text', value: config.deckName || '', attrs: { maxlength: '200' } });
  const model = node('input', { type: 'text', value: config.modelName || '', attrs: { maxlength: '200' } });
  const logicalFields = ['target', 'lemma', 'context', 'translation', 'definition', 'notes', 'source', 'topic', 'dashboardKey'];
  const fieldInputs = Object.fromEntries(logicalFields.map((key) => [key, node('input', {
    type: 'text', value: config.fieldMap?.[key] || '', attrs: { maxlength: '200' },
  })]));
  const ankiFeedback = node('p', { className: 'language-form-error', attrs: { role: 'status', 'aria-live': 'polite' }, hidden: true });
  const saveAnki = node('button', { className: 'language-button is-primary', type: 'submit', text: 'Save Anki settings' });
  const testAnki = node('button', { className: 'language-button', type: 'button', text: 'Test connection' });
  const discover = node('button', { className: 'language-button', type: 'button', text: 'Refresh decks, models and fields' });
  const discovery = node('p', { className: 'language-definition', text: 'Discovery has not run in this view.' });
  const ankiForm = node('form', { className: 'language-form' }, [
    node('label', { className: 'language-checkbox-row' }, [enabled, node('span', { text: 'Enable local AnkiConnect' })]),
    node('label', { className: 'language-checkbox-row' }, [autoSync, node('span', { text: 'Sync AnkiWeb every 5 minutes while the dashboard is open' })]),
    node('div', { className: 'language-form-grid' }, [
      field('Loopback endpoint', endpoint), field('Target deck', deck), field('Note model', model),
    ]),
    node('h4', { text: 'Field mapping' }),
    node('p', { className: 'language-definition', text: 'Model and field mapping are only needed if you create or link cards from Language. Leave them blank to track the selected deck read-only.' }),
    node('div', { className: 'language-anki-field-grid' }, logicalFields.map((key) => field(key, fieldInputs[key]))),
    node('div', { className: 'language-form-actions' }, [saveAnki, testAnki, discover, ankiFeedback]),
    discovery,
  ]);
  ankiForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    saveAnki.disabled = true;
    ankiFeedback.hidden = false;
    ankiFeedback.textContent = 'Saving Anki configuration...';
    try {
      const fieldMap = Object.fromEntries(logicalFields.map((key) => [key, fieldInputs[key].value.trim()]).filter(([, value]) => value));
      await onSaveAnki({ enabled: enabled.checked, autoSync: autoSync.checked, endpoint: endpoint.value.trim(), deckName: deck.value.trim(), modelName: model.value.trim(), fieldMap });
      ankiFeedback.textContent = 'Anki configuration saved server-side.';
    } catch (error) {
      ankiFeedback.textContent = error?.message || 'Anki configuration could not be saved.';
    } finally {
      saveAnki.disabled = false;
    }
  });
  testAnki.addEventListener('click', async () => {
    testAnki.disabled = true;
    ankiFeedback.hidden = false;
    ankiFeedback.textContent = 'Testing read-only connection...';
    try {
      const result = await onTestAnki();
      ankiFeedback.textContent = `Connection state: ${result.status?.status || 'unknown'}.`;
    } catch (error) {
      ankiFeedback.textContent = error?.message || 'Connection test failed.';
    } finally {
      testAnki.disabled = false;
    }
  });
  discover.addEventListener('click', async () => {
    discover.disabled = true;
    try {
      const result = await onDiscoverAnki(model.value.trim());
      discovery.textContent = `Decks: ${(result.decks || []).join(', ') || 'none'} / Models: ${(result.models || []).join(', ') || 'none'} / Fields: ${(result.fields || []).join(', ') || 'choose a model'}`;
    } catch (error) {
      discovery.textContent = error?.message || 'Discovery failed.';
    } finally {
      discover.disabled = false;
    }
  });
  const ankiCard = node('section', { className: 'language-card language-settings-card is-wide language-anki-settings' }, [
    node('p', { className: 'language-kicker', text: 'LOCAL ANKICONNECT' }),
    node('h3', { text: 'Safe card linking and metadata pull' }),
    node('p', { text: 'Only loopback HTTP endpoints are accepted. The optional API key comes from the server environment and is never returned here.' }),
    statusPill(anki.status?.status || (config.enabled ? 'Not checked' : 'Not configured'), anki.status?.status === 'CONNECTED' ? 'success' : 'muted'),
    definitionList([
      ['API key', config.apiKeyConfigured ? 'Configured on server' : 'Not configured'],
      ['Linked vocabulary', anki.status?.linkedVocabulary ?? 0],
      ['Conflicts', anki.status?.conflicts ?? 0],
      ['Scheduling ownership', 'Anki only'],
    ], 'language-evidence'),
    ankiForm,
  ]);

  const generationProvider = health?.generationProvider || {};
  const generatedAudio = health?.generatedReaderAudio || {};
  const providerReady = generationProvider.configured === true
    && ['CONFIGURED', 'AVAILABLE'].includes(generationProvider.state);
  const generationCard = node('section', { className: 'language-card language-settings-card is-wide' }, [
    node('p', { className: 'language-kicker', text: 'GENERATION & AUDIO' }),
    node('h3', { text: 'Server-managed providers' }),
    node('p', { text: 'Secrets stay in server environment variables and are never returned to this page. Automatic generation has no paid-tier fallback; manual copy/paste remains available.' }),
    node('div', { className: 'language-reference-list' }, [
      referenceRow(
        'Gemini automatic generation',
        `${generationProvider.modelId || 'gemini-3.8-flash'} · ${generationProvider.policy || 'FREE_ONLY'} · set LANGUAGE_GEMINI_ENABLED and GEMINI_API_KEY on the server`,
        providerReady ? 'Ready' : (generationProvider.reason || generationProvider.state || 'Not configured'),
        providerReady ? 'ready' : 'muted',
      ),
      referenceRow(
        'Google Cloud Reader TTS',
        `${generatedAudio.language || 'nb-NO'} · ${generatedAudio.voiceId || 'voice resolved on server'} · ${generatedAudio.audioEncoding || 'MP3'} · same deterministic cache as Cloze`,
        generatedAudio.state || 'Not configured',
        generatedAudio.state === 'CONFIGURED' ? 'ready' : 'muted',
      ),
    ]),
  ]);

  const speech = listening.speech || {};
  const listeningPreferences = listening.preferences || {};
  const selectedListeningVoice = (speech.voices || []).find(
    (item) => item.id === listeningPreferences.preferredVoiceId,
  ) || (speech.voices || [])[0] || null;
  const voice = node('select', { attrs: { 'aria-label': 'Preferred browser Bokm\u00e5l voice' } }, [
    node('option', { text: 'Automatic compatible voice', attrs: { value: '' } }),
    ...(speech.voices || []).map((item) => node('option', {
      text: `${item.name} (${item.lang})`, attrs: { value: item.id },
    })),
  ]);
  voice.value = listeningPreferences.preferredVoiceId || '';
  const rate = node('input', {
    type: 'range', value: String(listeningPreferences.rate || 1),
    attrs: { min: '0.6', max: '1.4', step: '0.1' },
  });
  const mode = node('select', {}, [
    node('option', { text: 'Read + Listen', attrs: { value: 'READ_LISTEN' } }),
    node('option', { text: 'Listening Only', attrs: { value: 'LISTENING_ONLY' } }),
  ]);
  mode.value = listeningPreferences.defaultMode === 'LISTENING_ONLY' ? 'LISTENING_ONLY' : 'READ_LISTEN';
  const listeningStatus = node('p', { className: 'language-definition', attrs: { role: 'status' } });
  const persistListening = () => {
    onSaveListening({
      preferredVoiceId: voice.value,
      rate: Number(rate.value),
      defaultMode: mode.value,
    });
    listeningStatus.textContent = `Saved on this browser \u00b7 rate ${Number(rate.value).toFixed(1)}\u00d7`;
  };
  voice.addEventListener('change', persistListening);
  rate.addEventListener('change', persistListening);
  mode.addEventListener('change', persistListening);
  const listeningCard = node('section', { className: 'language-card language-settings-card is-wide' }, [
    node('p', { className: 'language-kicker', text: 'LISTENING \u00b7 THIS BROWSER' }),
    node('h3', { text: 'Bokm\u00e5l browser speech' }),
    node('p', { text: 'Voice availability is device-local and is not a server or Google Cloud capability. Browser speech stays ephemeral; generated Reader and Cloze Cloud audio remain separate.' }),
    statusPill(speech.state || 'VOICE_LOADING', speech.state === 'AVAILABLE' ? 'ready' : 'muted'),
    node('div', { className: 'language-form-grid' }, [
      field('Preferred compatible voice', voice),
      field('Speech rate (0.6\u20131.4)', rate),
      field('Default study mode', mode),
    ]),
    definitionList([
      ['Compatible voices found', speech.voices?.length || 0],
      ['Selected/fallback voice', selectedListeningVoice?.id || 'None available yet'],
      ['Capability scope', speech.capabilityScope || 'DEVICE_LOCAL_NOT_SERVER_GLOBAL'],
      ['Browser audio storage', 'None'],
    ], 'language-evidence'),
    listeningStatus,
  ]);

  replace(mount, node('div', { className: 'language-settings-sections' }, [
    node('section', {}, [node('h3', { text: 'Profile' }), profileCard]),
    node('section', {}, [node('h3', { text: 'Study and audio' }), listeningCard]),
    node('section', {}, [node('h3', { text: 'Integrations' }), ankiCard]),
    node('section', { className: 'language-card language-settings-backup' }, [
      node('h3', { text: 'Data and backup' }),
      node('p', { text: 'Your Language database is local. Use the documented backup and staged restore process before changing machines or recovering data.' }),
      node('a', { className: 'language-button', text: 'Open backup guidance', attrs: { href: './developer-docs.html' } }),
    ]),
    node('details', { className: 'language-settings-advanced' }, [
      node('summary', { text: 'Advanced and technical status' }),
      node('div', { className: 'language-settings-grid' }, [analyzerCard, frequencyCard, referencesCard, generationCard]),
    ]),
  ]));
}
