import { KERMIT_ENABLED } from './kermit-config.js';
import { chatKermit, getKermitStatus } from './kermit-client.js';

const LABELS = {
  sleeping: 'Kermit sleeping', loading: 'Loading model…', ready: 'Ready',
  generating: 'Thinking…', resource_pressure: 'Memory pressure',
  waiting_for_memory: 'Needs memory', unavailable: 'Kermit unavailable',
  restart_required: 'Restart required', connection_error: 'Connection failed',
  model_unavailable: 'Model unavailable', inference_error: 'Response failed',
  grounding_error: 'Verification failed', protocol_error: 'Response invalid',
};

const node = (tag, className, label = '') => {
  const element = document.createElement(tag);
  if (className) element.className = className;
  element.textContent = label;
  return element;
};

export function mountKermit(root = document.body, api = { chatKermit, getKermitStatus }, enabled = KERMIT_ENABLED) {
  if (!enabled) return null;
  const shell = node('section', 'kermit-shell');
  shell.setAttribute('aria-label', 'Kermit chat');
  const toggle = node('button', 'kermit-toggle', 'Kermit unavailable');
  toggle.type = 'button';
  toggle.setAttribute('aria-expanded', 'false');
  const panel = node('section', 'kermit-panel');
  panel.id = 'kermit-chat-panel';
  panel.hidden = true;
  panel.setAttribute('aria-label', 'Kermit chat panel');
  toggle.setAttribute('aria-controls', panel.id);
  const header = node('header', 'kermit-header');
  const avatar = node('span', 'kermit-avatar', 'K');
  avatar.setAttribute('aria-hidden', 'true');
  const title = node('strong', '', 'Kermit');
  const status = node('span', 'kermit-status', 'Kermit service is unavailable.');
  status.setAttribute('role', 'status');
  header.append(avatar, title, status);
  const clear = node('button', 'kermit-clear', 'Clear conversation');
  clear.type = 'button';
  clear.setAttribute('aria-label', 'Clear conversation');
  header.insertBefore(clear, status);
  const profileLabel = node('label', 'kermit-profile-label', 'Profile ');
  const profile = node('select', 'kermit-profile');
  profile.setAttribute('aria-label', 'Kermit profile');
  profile.disabled = true;
  profileLabel.append(profile);
  const indexState = node('span', 'kermit-index-state', 'Index status unknown');
  const conversation = node('div', 'kermit-conversation');
  conversation.setAttribute('role', 'log');
  conversation.setAttribute('aria-live', 'polite');
  const resource = node('div', 'kermit-resource');
  resource.hidden = true;
  const resourceText = node('p', 'kermit-resource-text');
  const buttons = node('div', 'kermit-resource-actions');
  const check = node('button', '', 'Check again');
  const start = node('button', '', 'Start anyway');
  const cancel = node('button', '', 'Cancel');
  for (const button of [check, start, cancel]) button.type = 'button';
  buttons.append(check, start, cancel);
  resource.append(resourceText, buttons);
  const composer = node('form', 'kermit-composer');
  const input = node('textarea', 'kermit-input');
  input.rows = 2;
  input.maxLength = 500;
  input.setAttribute('aria-label', 'Ask Kermit');
  input.placeholder = 'Talk with Kermit…';
  const send = node('button', 'kermit-send', 'Send');
  send.type = 'submit';
  send.disabled = true;
  composer.append(input, send);
  panel.append(header, profileLabel, indexState, conversation, resource, composer);
  shell.append(panel, toggle);
  root.append(shell);

  let pending = null;
  let busy = false;
  let poll = null;
  let currentState = 'unavailable';
  let history = [];
  let conversationState = null;

  function remember(role, content) {
    history.push({ role, content: String(content).slice(0, 1200) });
    history = history.slice(-12);
    while (history.reduce((sum, item) => sum + item.content.length, 0) > 3000) history.shift();
  }

  function setState(state) {
    currentState = LABELS[state] ? state : 'unavailable';
    shell.dataset.state = currentState;
    status.textContent = {
      unavailable: 'Kermit service is unavailable.',
      restart_required: 'Kermit restart required: old service lacks chat.',
      connection_error: 'Cannot connect to Kermit.',
      model_unavailable: 'Local model unavailable.',
      inference_error: 'Model response failed.',
      grounding_error: 'Answer verification failed.',
      protocol_error: 'Kermit returned an invalid response.',
    }[currentState] || LABELS[currentState];
    toggle.textContent = `K · ${LABELS[currentState]}`;
  }

  function showResource(body) {
    const gate = body?.status === 'confirmation_required' ? 'yellow' : body?.status === 'waiting_for_memory' ? 'red' : null;
    if (!gate) {
      resource.hidden = true;
      return;
    }
    const value = body.resource || {};
    const format = amount => Number.isFinite(amount) ? `${(amount / 1000).toFixed(1)} GB` : 'unknown';
    resourceText.textContent = `${gate === 'yellow' ? 'Memory pressure.' : 'Kermit needs more memory.'} Available RAM: ${format(value.availableMb)}. Minimum: ${format(value.minimumMb)}. Recommended: ${format(value.recommendedMb)}. ${gate === 'red' ? `Free about ${format(value.deficitToMinimumMb)} to start.` : ''}`;
    resource.hidden = false;
    start.hidden = gate !== 'yellow';
    check.hidden = gate !== 'red';
    pending = gate === 'yellow' ? pending : null;
    setState(gate === 'yellow' ? 'resource_pressure' : 'waiting_for_memory');
  }

  function addMessage(kind, text) {
    const message = node('article', `kermit-message kermit-${kind}`);
    message.append(node('span', 'kermit-speaker', kind === 'user' ? 'You' : 'Kermit'));
    const body = node('div', 'kermit-message-body');
    message.append(body);
    conversation.append(message);
    conversation.scrollTop = conversation.scrollHeight;
    if (text) body.textContent = text;
    return body;
  }

  function renderAnswer(answer) {
    const body = addMessage('answer');
    if (answer.route === 'PROJECT_GROUNDED' && Array.isArray(answer.citations) && answer.citations.length) {
      body.append(node('span', 'kermit-verified', 'Verified dashboard sources'));
    }
    const citations = new Map((Array.isArray(answer.citations) ? answer.citations : []).map(item => [item.evidenceId, item]));
    const text = String(answer.answer || '');
    for (const piece of text.split(/(\[E[1-9]\d*\])/g)) {
      const id = piece.slice(1, -1);
      if (/^\[E[1-9]\d*\]$/.test(piece) && citations.has(id)) {
        body.append(node('sup', 'kermit-citation-marker', piece));
      } else {
        body.append(document.createTextNode(piece));
      }
    }
    if (citations.size) {
      const details = node('details', 'kermit-sources');
      details.append(node('summary', '', `Sources (${citations.size})`));
      const list = node('ul');
      for (const item of citations.values()) {
        const locator = item.locator?.heading || item.locator?.symbol || item.locator?.name || item.locator?.lineStart || '';
        list.append(node('li', '', `${item.evidenceId} · ${item.path || ''}${locator ? ` :: ${locator}` : ''}`));
      }
      details.append(list);
      body.append(details);
    }
    if (answer.evidenceAsOf?.buildFingerprint) body.append(node('span', 'kermit-evidence-time',
      `Evidence build: ${String(answer.evidenceAsOf.buildFingerprint).slice(0, 12)}`));
    const uncertainty = Array.isArray(answer.uncertainty) ? answer.uncertainty : [];
    const conflicts = Array.isArray(answer.conflicts) ? answer.conflicts : [];
    if (uncertainty.length || conflicts.length) {
      const details = node('details', 'kermit-notes');
      details.append(node('summary', '', 'Evidence notes'));
      const list = node('ul');
      for (const note of uncertainty) list.append(node('li', '', String(note)));
      for (const conflict of conflicts) {
        const type = conflict.type === 'TEST_COVERAGE_GAP' ? 'Test coverage gap' :
          conflict.type === 'UNKNOWN_BEHAVIOR' ? 'Unknown behavior' : 'Conflicting or scoped evidence';
        list.append(node('li', '', `${type}: ${conflict.description || ''}`));
      }
      details.append(list);
      body.append(details);
    }
  }

  async function checkStatus() {
    try {
      const response = await api.getKermitStatus();
      if (response.status !== 'ok') throw new Error('Service unavailable');
      const offered = Array.isArray(response.profiles) ? response.profiles.filter(value => value === 'quick' || value === 'normal') : [];
      const selected = profile.value;
      profile.replaceChildren();
      for (const value of offered) {
        const option = node('option', '', value === 'quick' ? 'Quick' : 'Normal');
        option.value = value;
        profile.append(option);
      }
      profile.disabled = !offered.length;
      send.disabled = busy || profile.disabled;
      profile.value = offered.includes(selected) ? selected : offered.includes(response.profile) ? response.profile : offered[0] || '';
      const buildId = typeof response.index?.buildId === 'string' ? response.index.buildId.slice(0, 8) : '';
      indexState.textContent = `Index: ${response.index?.state || 'unavailable'}${buildId ? ` · ${buildId}` : ''}`;
      setState(response.providerAvailable === false ? 'model_unavailable' : response.modelState);
      if (response.resourceGate === 'red' && response.modelState === 'waiting_for_memory') showResource({ status: 'waiting_for_memory', resource: response.resource });
      else if (response.resourceGate === 'yellow' && response.modelState === 'resource_pressure') showResource({ status: 'confirmation_required', resource: response.resource });
      else resource.hidden = true;
      return response;
    } catch (error) {
      setState(error?.kind === 'incompatible' ? 'restart_required' :
        error?.kind === 'connection' || !error?.kind ? 'connection_error' :
          error?.kind === 'protocol' ? 'protocol_error' : 'unavailable');
      const index = error?.body?.index;
      indexState.textContent = index?.state ? `Index: ${index.state}` : 'Index status unknown';
      resource.hidden = true;
      profile.disabled = true;
      send.disabled = true;
      return null;
    }
  }

  async function submit(question, override = false) {
    if (busy || !question.trim() || profile.disabled) return;
    busy = true;
    send.disabled = true;
    if (!override) addMessage('user', question);
    pending = question;
    resource.hidden = true;
    setState(currentState === 'ready' ? 'generating' : 'loading');
    poll = window.setInterval(() => { if (!panel.hidden) void checkStatus(); }, 2000);
    try {
      const answer = await api.chatKermit(question, profile.value, history.slice(), conversationState, override);
      if (answer.status === 'confirmation_required' || answer.status === 'waiting_for_memory') {
        showResource(answer);
      } else if (answer.status === 'unavailable' || answer.groundingStatus === 'unavailable') {
        pending = null;
        addMessage('answer', answer.answer || answer.message || 'The local model is unavailable.');
        setState(answer.resource?.reason === 'model_unavailable' || answer.modelState === 'unavailable'
          ? 'model_unavailable' : 'inference_error');
      } else if (answer.status === 'invalid' || answer.groundingStatus === 'invalid') {
        pending = null;
        renderAnswer(answer.route === 'PROJECT_GROUNDED' || answer.groundingStatus === 'invalid'
          ? { ...answer, answer: 'The answer could not be verified. Please try again.', citations: [], conflicts: [] }
          : { ...answer, citations: [], conflicts: [] });
        setState(answer.route === 'PROJECT_GROUNDED' || answer.groundingStatus === 'invalid'
          ? 'grounding_error' : 'inference_error');
      } else if (typeof answer.answer === 'string' && typeof answer.groundingStatus === 'string') {
        pending = null;
        remember('user', question);
        remember('assistant', answer.answer);
        conversationState = { route: answer.route || 'CLARIFICATION_REQUIRED', topic: answer.topic || null };
        renderAnswer(answer);
        await checkStatus();
      } else {
        pending = null;
        addMessage('answer', answer.message || 'Kermit service is unavailable.');
        setState(answer.status === 'busy' ? 'generating' : 'unavailable');
      }
    } catch (error) {
      pending = null;
      const incompatible = error?.kind === 'incompatible';
      addMessage('answer', incompatible ? 'Kermit restart required: the running service is outdated.' :
        error?.kind === 'connection' || !error?.kind ? 'Cannot connect to the local Kermit service.' :
          'Kermit returned an invalid response.');
      setState(incompatible ? 'restart_required' :
        error?.kind === 'connection' || !error?.kind ? 'connection_error' : 'protocol_error');
      if (incompatible) profile.disabled = true;
    } finally {
      window.clearInterval(poll);
      poll = null;
      busy = false;
      send.disabled = profile.disabled;
    }
  }

  toggle.addEventListener('click', () => {
    panel.hidden = !panel.hidden;
    toggle.setAttribute('aria-expanded', String(!panel.hidden));
    if (!panel.hidden) { input.focus(); void checkStatus(); }
  });
  composer.addEventListener('submit', event => {
    event.preventDefault();
    const question = input.value.trim();
    if (!question) return;
    input.value = '';
    void submit(question);
  });
  input.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); composer.requestSubmit(); }
  });
  check.addEventListener('click', () => { void checkStatus(); });
  start.addEventListener('click', () => { if (pending) void submit(pending, true); });
  cancel.addEventListener('click', () => { pending = null; resource.hidden = true; input.focus(); });
  clear.addEventListener('click', () => {
    if (busy) return;
    history = [];
    conversationState = null;
    pending = null;
    conversation.replaceChildren();
    resource.hidden = true;
    input.focus();
  });
  panel.addEventListener('keydown', event => {
    if (event.key === 'Escape') {
      panel.hidden = true;
      toggle.setAttribute('aria-expanded', 'false');
      toggle.focus();
    }
  });
  void checkStatus();
  return { shell, toggle, panel, input, profile, status, conversation, resource, clear, checkStatus };
}
