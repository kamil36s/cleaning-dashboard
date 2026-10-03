import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderCurriculumLanding, renderCurriculumPack } from '../js/language/views/curriculum.js';
import { formatLanguageRoute, parseLanguageRoute, routeSection } from '../js/language/router.js';

function progress(items = []) {
  return {
    sourceItemTotal: 3, approvedTotal: 3, mappedTotal: 2, ambiguousTotal: 1,
    unresolvedTotal: 0, excludedTotal: 0, eligibleDenominator: 2, completed: 1,
    progressPercent: 50, completionSemantics: 'KNOWN and MASTERED count as acquired.', items,
  };
}

function pack(items = []) {
  return {
    id: 'nb.public-services.work', version: 1, status: 'ACTIVE', category: 'WORK',
    name: 'Work <img src=x onerror=alert(1)>', description: 'Official & reviewed',
    fingerprint: 'sha256:pack',
    source: { name: 'Los', provider: 'Digdir', version: '3.0', license: 'CC0', membershipBasis: 'Leaf concepts.' },
    mappingSnapshot: { referenceFingerprint: 'sha256:reference' }, progress: progress(items),
  };
}

describe('Language curriculum UI', () => {
  beforeEach(() => { document.body.innerHTML = '<main id="mount"></main>'; });

  it('parses and formats reload-safe version-pinned pack routes', () => {
    const route = { name: 'curriculumPack', packId: 'nb.public-services.work', version: 1 };
    expect(formatLanguageRoute(route)).toBe('#curriculum/nb.public-services.work/v/1');
    expect(parseLanguageRoute(formatLanguageRoute(route))).toEqual({ ...route, valid: true });
    expect(routeSection(route)).toBe('curriculum');
  });

  it('renders source and denominator disclosure with safe text nodes', () => {
    const mount = document.querySelector('#mount');
    const onOpenPack = vi.fn();
    renderCurriculumLanding(mount, {
      loading: false, error: null,
      landing: {
        policyVersion: 'language.curriculum-policy/v1', packs: [pack()],
        unavailablePacks: [{ name: 'Warehouse', status: 'UNAVAILABLE', reason: 'No approved source.' }],
        boundaries: { proficiency: 'Pack progress is not proficiency.' },
      },
    }, { onOpenPack });
    expect(mount.textContent).toContain('Source 3 · approved 3 · mapped 2 · ambiguous 1');
    expect(mount.querySelector('img')).toBeNull();
    mount.querySelector('button').click();
    expect(onOpenPack).toHaveBeenCalledWith('nb.public-services.work', 1);
  });

  it('keeps NEW separate and filters searchable multiword items', () => {
    const mount = document.querySelector('#mount');
    const items = [
      { membershipId: 'a'.repeat(32), displayTerm: 'Arbeidsavtale', normalizedLookup: 'arbeidsavtale', mappingState: 'MAPPED', reviewState: 'APPROVED', priority: 'USEFUL', referenceUnit: { partOfSpeech: 'NOUN' }, user: { state: 'NEW', acquired: false } },
      { membershipId: 'b'.repeat(32), displayTerm: 'Offentlig transport', normalizedLookup: 'offentlig transport', mappingState: 'MAPPED', reviewState: 'APPROVED', priority: 'USEFUL', referenceUnit: { partOfSpeech: 'NOUN' }, user: { state: 'KNOWN', acquired: true } },
      { membershipId: 'c'.repeat(32), displayTerm: 'Lønn', normalizedLookup: 'lønn', mappingState: 'AMBIGUOUS', reviewState: 'APPROVED', priority: 'USEFUL', user: { state: 'NOT_ELIGIBLE', acquired: false } },
    ];
    const state = { loading: false, error: null, pack: pack(items), query: '', stateFilter: '' };
    const onStateFilter = vi.fn();
    renderCurriculumPack(mount, state, { onStateFilter });
    expect(mount.textContent).toContain('NEW');
    expect(mount.textContent).toContain('KNOWN');
    const select = mount.querySelector('select');
    select.value = 'NEW';
    select.dispatchEvent(new Event('change'));
    expect(onStateFilter).toHaveBeenCalledWith('NEW');
  });
});
