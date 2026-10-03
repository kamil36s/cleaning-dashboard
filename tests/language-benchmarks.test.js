import { describe, expect, it, vi } from 'vitest';
import { formatLanguageRoute, parseLanguageRoute, routeSection } from '../js/language/router.js';
import { renderBenchmarkLanding, renderBenchmarkRun } from '../js/language/views/benchmarks.js';
import { financePrivacyPlugin } from '../vite.config.js';

const id = 'a'.repeat(32);

describe('Language benchmarks', () => {
  it('keeps landing and run routes reload safe', () => {
    expect(parseLanguageRoute('#benchmarks')).toEqual({ name: 'benchmarks', valid: true });
    expect(parseLanguageRoute(`#benchmarks/run/${id}`)).toEqual({ name: 'benchmarkRun', runId: id, valid: true });
    expect(formatLanguageRoute({ name: 'benchmarkRun', runId: id })).toBe(`#benchmarks/run/${id}`);
    expect(routeSection({ name: 'benchmarkRun' })).toBe('benchmarks');
  });

  it('blocks benchmark answer content through Vite source URLs', () => {
    let middleware;
    financePrivacyPlugin().configureServer({ middlewares: { use: (handler) => { middleware = handler; } } });
    for (const url of ['/language_learning/benchmark_content/v1.json', '/@fs/C:/project/language_learning/benchmark_content/v1.json']) {
      const response = { statusCode: 200, end: vi.fn() };
      const next = vi.fn();
      middleware({ url }, response, next);
      expect(response.statusCode).toBe(404);
      expect(next).not.toHaveBeenCalled();
    }
  });

  it('renders history and separate Norway evidence without a composite', () => {
    const mount = document.createElement('main');
    renderBenchmarkLanding(mount, { runs: [{ id, kind: 'BASELINE', status: 'ACTIVE', formId: 'FORM_A', startedAt: '2026-09-24T12:00:00Z' }] }, {
      curricula: [{ name: 'Work', completed: 2, total: 22, packId: 'work', version: 1 }],
      benchmarks: { READING: { status: 'SCORED', correct: 2, total: 3, percent: 66.7 }, LISTENING: null },
    }, { start: vi.fn(), open: vi.fn() });
    expect(mount.textContent).toContain('2 / 22 acquired');
    expect(mount.textContent).toContain('Reading comprehension2 / 3');
    expect(mount.textContent).toContain('Listening comprehensionUnavailable');
    expect(mount.textContent).not.toMatch(/readiness:\s*\d/);
    expect(mount.querySelectorAll('button').length).toBe(2);
  });

  it('keeps listening transcript out of the DOM and supports unavailable state', () => {
    const mount = document.createElement('main');
    const answer = vi.fn();
    const run = {
      id, kind: 'BASELINE', status: 'ACTIVE', formId: 'FORM_A',
      responses: {}, items: [{ id: 'a-l1', dimension: 'LISTENING', speech: 'Hidden Norwegian transcript',
        prompt: 'What happened?', options: ['A', 'B'], itemVersion: 1 }],
    };
    renderBenchmarkRun(mount, run, {
      answer, complete: vi.fn(), back: vi.fn(),
      speech: { snapshot: () => ({ state: 'NO_BOKMAL_VOICE' }), play: vi.fn() },
    });
    expect(mount.textContent).not.toContain('Hidden Norwegian transcript');
    expect(mount.textContent).toContain('1');
    [...mount.querySelectorAll('button')].find((button) => button.textContent.includes('unavailable')).click();
    expect(answer).toHaveBeenCalledWith('a-l1', { unavailable: true });
    renderBenchmarkRun(mount, {
      ...run, items: [{ id: 'a-c1', dimension: 'CLOZE', prompt: 'Jeg ___ hjem.', hint: 'go', itemVersion: 1 }],
    }, { answer, complete: vi.fn(), back: vi.fn(), speech: { snapshot: () => ({ state: 'AVAILABLE' }), play: vi.fn() } });
    const textInput = mount.querySelector('input');
    expect(textInput.getAttribute('aria-label')).toBe('Missing Norwegian word');
    textInput.value = 'går';
    mount.querySelector('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    expect(answer).toHaveBeenCalledWith('a-c1', { response: 'går' });
  });

  it('renders separate scores and discloses repeat influence', () => {
    const mount = document.createElement('main');
    const score = { correct: 1, total: 2, percent: 50, status: 'SCORED' };
    renderBenchmarkRun(mount, {
      kind: 'CHECKPOINT', status: 'COMPLETED', formId: 'FORM_A', scores: {
        VOCABULARY: score, CLOZE: score, READING: score, LISTENING: score,
      }, comparison: { state: 'REPEAT_INFLUENCED' },
    }, { back: vi.fn() });
    expect(mount.textContent).toContain('REPEAT INFLUENCED');
    expect(mount.textContent.match(/1 \/ 2/g)).toHaveLength(4);
  });
});
