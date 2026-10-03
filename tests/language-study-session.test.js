import { describe, expect, it, vi } from 'vitest';
import { parseLanguageRoute, formatLanguageRoute, routeHeading } from '../js/language/router.js';
import { renderStudySession } from '../js/language/views/study-session.js';

describe('Language Study Session Builder', () => {
  it('has a reload-safe route', () => {
    expect(parseLanguageRoute('#study-session')).toEqual({ name: 'study-session', valid: true });
    expect(formatLanguageRoute('study-session')).toBe('#study-session');
    expect(routeHeading({ name: 'study-session' })).toBe('Study Session');
  });

  it('offers only 10, 20 and 30 minutes with a keyboard form', () => {
    const mount = document.createElement('main');
    const onBuild = vi.fn();
    renderStudySession(mount, { minutes: 20 }, { onBuild });
    const select = mount.querySelector('select');
    expect([...select.options].map((item) => item.value)).toEqual(['10', '20', '30']);
    for (const minutes of [10, 20, 30]) {
      select.value = String(minutes);
      mount.querySelector('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
      expect(onBuild).toHaveBeenLastCalledWith(minutes);
    }
  });

  it('renders ordered explanations, durations, handoffs and degradation safely', () => {
    const mount = document.createElement('main');
    renderStudySession(mount, { minutes: 20, plan: {
      policyVersion: 'language.study-session-builder/v1', generatedAtLocalDate: '2026-09-24',
      snapshotFingerprint: 'abc', requestedMinutes: 20, plannedMinutes: 12, segmentCount: 2,
      unavailableSources: ['Anki'], segments: [
        { title: '<unsafe>', reason: 'Current mistake', estimatedMinutes: 5,
          sourceOwner: 'Mistake Intelligence', destinationRoute: '#cloze' },
        { title: 'Continue Reader', reason: 'Unfinished text', estimatedMinutes: 7,
          sourceOwner: 'Reader', destinationRoute: '#reader/text/abc' },
      ],
    } }, { onBuild: vi.fn() });
    expect(mount.textContent).toContain('20 min requested · 12 min planned · 2 segments');
    expect([...mount.querySelectorAll('.language-session-card h3')].map((item) => item.textContent))
      .toEqual(['<unsafe>', 'Continue Reader']);
    expect(mount.querySelector('unsafe')).toBeNull();
    expect(mount.textContent).toContain('Current mistake');
    expect(mount.textContent).toContain('7 min');
    expect(mount.querySelector('.language-session-card a').getAttribute('href')).toBe('#cloze');
    expect(mount.querySelectorAll('a[href="#cloze"]')).toHaveLength(2);
    expect(mount.textContent).toContain('Unavailable sources: Anki');
    expect(mount.textContent).toContain('snapshot abc');
  });

  it('shows honest empty and API failure states', () => {
    const mount = document.createElement('main');
    renderStudySession(mount, { minutes: 10, plan: {
      requestedMinutes: 10, plannedMinutes: 0, segmentCount: 0, segments: [],
      unavailableSources: ['Anki'],
    } }, { onBuild: vi.fn() });
    expect(mount.textContent).toContain('No useful study work');
    expect(mount.textContent).not.toContain('uses the remaining work');
    renderStudySession(mount, { minutes: 10, error: 'offline' }, { onBuild: vi.fn() });
    expect(mount.textContent).toContain('offline');
  });
});
