// @vitest-environment happy-dom
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import { mountKermit } from '../js/kermit-chat.js';

const tick = () => new Promise(resolve => setTimeout(resolve, 0));
const status = (modelState = 'sleeping', resourceGate = 'green') => ({
  contractVersion: 1, status: 'ok', profiles: ['quick', 'normal'], profile: 'normal',
  modelState, resourceGate, resource: { availableMb: 3400, minimumMb: 5200,
    recommendedMb: 6600, deficitToMinimumMb: 1800 },
  index: { state: 'current', buildId: 'abcdef123456' },
});

const answer = {
  contractVersion: 1, status: 'ok', answer: 'Fact [E1]. <img src=x onerror=alert(1)>',
  groundingStatus: 'grounded',
  citations: [{ evidenceId: 'E1', path: '<script>alert(1)</script>', locator: { heading: 'Section' } }],
  uncertainty: ['<svg onload=alert(1)>'],
  conflicts: [{ type: 'TEST_COVERAGE_GAP', description: 'Missing focused test' }],
};

describe('Kermit Phase 7 panel', () => {
  beforeEach(() => { document.body.replaceChildren(); });
  afterEach(() => { vi.restoreAllMocks(); document.body.replaceChildren(); });

  it('stays collapsed until opened, uses service profiles, and renders untrusted text safely', async () => {
    const api = { getKermitStatus: vi.fn().mockResolvedValue(status()), chatKermit: vi.fn().mockResolvedValue(answer) };
    const ui = mountKermit(document.body, api);
    expect(ui.panel.hidden).toBe(true);
    expect(api.getKermitStatus).toHaveBeenCalledTimes(1);
    ui.toggle.click(); await tick();
    expect(ui.panel.hidden).toBe(false);
    expect(ui.profile.value).toBe('normal');
    expect([...ui.profile.options].map(option => option.value)).toEqual(['quick', 'normal']);
    expect(ui.status.textContent).toBe('Kermit sleeping');
    expect(ui.panel.textContent).toContain('Index: current · abcdef12');
    ui.profile.value = 'quick';
    ui.input.value = 'Where does Quote come from?';
    ui.input.closest('form').requestSubmit(); await tick(); await tick();
    expect(api.chatKermit).toHaveBeenCalledWith('Where does Quote come from?', 'quick', [], null, false);
    expect(ui.conversation.textContent).toContain('Fact [E1].');
    expect(ui.conversation.textContent).toContain('Test coverage gap');
    expect(ui.conversation.textContent).toContain('<script>alert(1)</script>');
    expect(ui.conversation.querySelector('img, script, svg')).toBeNull();
    expect(document.querySelector('.kermit-citation-marker')).not.toBeNull();
    expect(document.querySelector('.kermit-sources')).not.toBeNull();
  });

  it('shows RED memory numbers and checks again on demand', async () => {
    const api = { getKermitStatus: vi.fn().mockResolvedValue(status('waiting_for_memory', 'red')), chatKermit: vi.fn() };
    const ui = mountKermit(document.body, api);
    ui.toggle.click(); await tick();
    expect(ui.status.textContent).toBe('Needs memory');
    expect(ui.resource.textContent).toContain('3.4 GB');
    expect(ui.resource.textContent).toContain('5.2 GB');
    expect(ui.resource.textContent).toContain('1.8 GB');
    ui.resource.querySelector('button').click(); await tick();
    expect(api.getKermitStatus).toHaveBeenCalledTimes(3);
    expect(api.chatKermit).not.toHaveBeenCalled();
  });

  it('requires a separate Start anyway click for YELLOW', async () => {
    const api = {
      getKermitStatus: vi.fn().mockResolvedValue(status()),
      chatKermit: vi.fn().mockResolvedValueOnce({ status: 'confirmation_required', resource: status().resource })
        .mockResolvedValueOnce(answer),
    };
    const ui = mountKermit(document.body, api);
    ui.toggle.click(); await tick();
    ui.input.value = 'Question'; ui.input.closest('form').requestSubmit(); await tick();
    expect(api.chatKermit).toHaveBeenCalledTimes(1);
    expect(ui.status.textContent).toBe('Memory pressure');
    ui.resource.querySelectorAll('button')[1].click(); await tick(); await tick();
    expect(api.chatKermit).toHaveBeenLastCalledWith('Question', 'normal', [], null, true);
  });

  it('shows unavailable state and can be disabled without status checks', async () => {
    const api = { getKermitStatus: vi.fn().mockRejectedValue(new Error('offline')), chatKermit: vi.fn() };
    expect(mountKermit(document.body, api, false)).toBeNull();
    expect(document.querySelector('.kermit-shell')).toBeNull();
    expect(api.getKermitStatus).not.toHaveBeenCalled();
    const ui = mountKermit(document.body, api);
    ui.toggle.click(); await tick();
    expect(ui.status.textContent).toBe('Cannot connect to Kermit.');
    expect(api.chatKermit).not.toHaveBeenCalled();
  });

  it('shows ready and an in-flight generating state without background startup polling', async () => {
    let resolveAnswer;
    const api = { getKermitStatus: vi.fn().mockResolvedValue(status('ready')),
      chatKermit: vi.fn().mockImplementation(() => new Promise(resolve => { resolveAnswer = resolve; })) };
    const ui = mountKermit(document.body, api);
    ui.toggle.click(); await tick();
    expect(ui.status.textContent).toBe('Ready');
    ui.input.value = 'Question'; ui.input.closest('form').requestSubmit(); await tick();
    expect(ui.status.textContent).toBe('Thinking…');
    resolveAnswer(answer); await tick(); await tick();
    expect(ui.status.textContent).toBe('Ready');
  });

  it('reports an old listener as restart required while preserving index status', async () => {
    const error = Object.assign(new Error('old service'), { kind: 'incompatible',
      body: { index: { state: 'current' } } });
    const api = { getKermitStatus: vi.fn().mockRejectedValue(error), chatKermit: vi.fn() };
    const ui = mountKermit(document.body, api);
    ui.toggle.click(); await tick();
    expect(ui.status.textContent).toBe('Kermit restart required: old service lacks chat.');
    expect(ui.panel.textContent).toContain('Index: current');
    expect(ui.profile.disabled).toBe(true);
    expect(ui.panel.querySelector('.kermit-send').disabled).toBe(true);
    expect(api.chatKermit).not.toHaveBeenCalled();
  });

  it('distinguishes model inference failure from connection and grounding failures', async () => {
    const api = { getKermitStatus: vi.fn().mockResolvedValue(status('ready')),
      chatKermit: vi.fn().mockResolvedValue({ status: 'unavailable', modelState: 'unavailable',
        groundingStatus: 'not_required', answer: 'The local model is unavailable.' }) };
    const ui = mountKermit(document.body, api);
    ui.toggle.click(); await tick();
    ui.input.value = 'Hi'; ui.input.closest('form').requestSubmit(); await tick(); await tick();
    expect(ui.status.textContent).toBe('Local model unavailable.');
    expect(ui.conversation.textContent).toContain('The local model is unavailable.');
  });

  it('labels a failed conversational inference separately from model absence', async () => {
    const api = { getKermitStatus: vi.fn().mockResolvedValue(status('ready')),
      chatKermit: vi.fn().mockResolvedValue({ status: 'unavailable',
        groundingStatus: 'not_required', answer: 'The local model could not answer.' }) };
    const ui = mountKermit(document.body, api);
    ui.toggle.click(); await tick();
    ui.input.value = 'Hi'; ui.input.closest('form').requestSubmit(); await tick(); await tick();
    expect(ui.status.textContent).toBe('Model response failed.');
    expect(ui.conversation.textContent).toContain('The local model could not answer.');
  });

  it('shows loading for a sleeping model while its answer is pending', async () => {
    let resolveAnswer;
    const api = { getKermitStatus: vi.fn().mockResolvedValue(status('sleeping')),
      chatKermit: vi.fn().mockImplementation(() => new Promise(resolve => { resolveAnswer = resolve; })) };
    const ui = mountKermit(document.body, api);
    ui.toggle.click(); await tick();
    ui.input.value = 'Question'; ui.input.closest('form').requestSubmit(); await tick();
    expect(ui.status.textContent).toBe('Loading model…');
    resolveAnswer(answer); await tick(); await tick();
    expect(ui.status.textContent).toBe('Kermit sleeping');
  });

  it('shows an invalid grounded response and its uncertainty without claiming an outage', async () => {
    const api = { getKermitStatus: vi.fn().mockResolvedValue(status('ready')),
      chatKermit: vi.fn().mockResolvedValue({ status: 'invalid', answer: 'Rejected factual draft.',
        groundingStatus: 'invalid', citations: [{ evidenceId: 'E1', path: 'docs/example.md' }],
        conflicts: [], uncertainty: ['Cited evidence is unrelated.'] }) };
    const ui = mountKermit(document.body, api);
    ui.toggle.click(); await tick();
    ui.input.value = 'Question'; ui.input.closest('form').requestSubmit(); await tick(); await tick();
    expect(ui.conversation.textContent).toContain('The answer could not be verified. Please try again.');
    expect(ui.conversation.textContent).not.toContain('Rejected factual draft.');
    expect(ui.conversation.textContent).not.toContain('Sources (1)');
    expect(ui.conversation.textContent).toContain('Cited evidence is unrelated.');
    expect(ui.status.textContent).toBe('Answer verification failed.');
  });

  it('keeps bounded context in memory and clears history and routing state', async () => {
    const api = { getKermitStatus: vi.fn().mockResolvedValue(status('ready')),
      chatKermit: vi.fn().mockResolvedValueOnce({ contractVersion: 1, status: 'ok', answer: 'Hey!',
        groundingStatus: 'not_required', route: 'GENERAL_CONVERSATION', topic: null, citations: [] })
        .mockResolvedValueOnce({ ...answer, route: 'PROJECT_GROUNDED', topic: 'quote' })
        .mockResolvedValueOnce({ contractVersion: 1, status: 'ok', answer: 'Fresh start',
          groundingStatus: 'not_required', route: 'GENERAL_CONVERSATION', topic: null, citations: [] }) };
    const ui = mountKermit(document.body, api);
    ui.toggle.click(); await tick();
    ui.input.value = 'Hi'; ui.input.closest('form').requestSubmit(); await tick(); await tick();
    ui.input.value = 'How does Quote work?'; ui.input.closest('form').requestSubmit(); await tick(); await tick();
    expect(api.chatKermit).toHaveBeenNthCalledWith(2, 'How does Quote work?', 'normal',
      [{ role: 'user', content: 'Hi' }, { role: 'assistant', content: 'Hey!' }],
      { route: 'GENERAL_CONVERSATION', topic: null }, false);
    expect(ui.conversation.textContent).toContain('Verified dashboard sources');
    ui.clear.click();
    expect(ui.conversation.textContent).toBe('');
    ui.input.value = 'Hi again'; ui.input.closest('form').requestSubmit(); await tick(); await tick();
    expect(api.chatKermit).toHaveBeenNthCalledWith(3, 'Hi again', 'normal', [], null, false);
  });
});
