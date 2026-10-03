import { afterEach, describe, expect, it, vi } from 'vitest';
import { createAuthenticMediaPlayer, coveredMilliseconds } from '../js/language/audio/authentic-media.js';
import { renderInboxDetail, renderInboxLanding } from '../js/language/views/inbox.js';
import { renderListeningText } from '../js/language/views/listening.js';

class FakeAudio extends EventTarget {
  constructor() {
    super(); this.src = ''; this.currentTime = 0; this.duration = 10; this.paused = true; this.playbackRate = 1;
  }
  async play() { this.paused = false; this.dispatchEvent(new Event('playing')); }
  pause() { this.paused = true; this.dispatchEvent(new Event('pause')); }
  advance(seconds) { this.currentTime = seconds; this.dispatchEvent(new Event('timeupdate')); }
  seek(seconds) {
    this.dispatchEvent(new Event('seeking')); this.currentTime = seconds; this.dispatchEvent(new Event('seeked'));
  }
}

describe('Phase 10.5 Content Inbox', () => {
  afterEach(() => document.body.replaceChildren());

  it('renders one intake flow and non-color readiness/rights states', async () => {
    const mount = document.createElement('main');
    const onOpen = vi.fn();
    renderInboxLanding(mount, { items: [
      { id: 'a', title: 'NRK episode', sourceType: 'NRK_REFERENCE', status: 'REFERENCE_ONLY', rightsStatus: 'STORAGE_NOT_AUTHORIZED', sourceUri: 'https://nrk.no/test' },
      { id: 'b', title: 'Owned audio', sourceType: 'LOCAL_AUDIO', status: 'NEEDS_TRANSCRIPT', rightsStatus: 'USER_OWNED_STORAGE_ALLOWED' },
      { id: 'c', title: 'Aligned', sourceType: 'LOCAL_AUDIO', status: 'READY_LISTENING', rightsStatus: 'USER_OWNED_STORAGE_ALLOWED' },
    ] }, { onOpen, onAdd: vi.fn() });
    expect(mount.querySelectorAll('form')).toHaveLength(1);
    expect(mount.textContent).toContain('Reference only');
    expect(mount.textContent).toContain('Storage not authorized');
    expect(mount.textContent).toContain('Needs transcript');
    expect(mount.textContent).toContain('Listening-ready');
    mount.querySelectorAll('article button')[2].click();
    expect(onOpen).toHaveBeenCalledWith('c');
  });

  it('shows personal coverage without a CEFR claim and supports manual timing correction', () => {
    const mount = document.createElement('main');
    const onAlignment = vi.fn();
    renderInboxDetail(mount, { detail: {
      item: { id: 'c', title: 'Owned audio', sourceType: 'LOCAL_AUDIO', status: 'READY_LISTENING', rightsStatus: 'USER_OWNED_STORAGE_ALLOWED', retentionPolicy: 'KEEP_UNTIL_USER_DELETES' },
      media: { url: '/api/language/content/media/a' },
      document: { id: 't', processingState: 'ANALYZED' },
      currentTranscript: { id: 'x', version: 1 },
      coverage: { tokenCoveragePercent: 95, uniqueLemmaCoveragePercent: 90, counts: { unknown: 2, learning: 1, ambiguous: 0 }, policyVersion: 'language.coverage-policy/v1' },
      alignmentPolicyVersion: 'language.transcript-alignment/v1',
      alignments: [{ id: 'z', sentenceOrder: 0, exactText: 'Jeg jobber.', startMs: 0, endMs: 2000, method: 'IMPORTED_SRT', confidenceBasis: 'CONFIDENCE_NOT_REPORTED', exposureEligible: true }],
    } }, { onAlignment });
    expect(mount.textContent).toContain('PERSONAL COMPREHENSIBILITY · NOT CEFR');
    expect(mount.textContent).toContain('95% token coverage');
    expect(mount.textContent).toContain('CONFIDENCE_NOT_REPORTED');
    mount.querySelector('.language-alignment-row button').click();
    expect(onAlignment).toHaveBeenCalledWith('z', { startMs: 0, endMs: 2000 });
  });

  it('renders accessible authentic controls, alignment disclosure, listening-only and Phrasebook action', () => {
    const mount = document.createElement('main');
    document.body.append(mount);
    const handlers = { onPlay: vi.fn(), onSeek: vi.fn(), onSaveExpression: vi.fn(), onPreference: vi.fn() };
    renderListeningText(mount, {
      payload: { document: { id: 't', title: 'Podcast', sourceType: 'CONTENT_TRANSCRIPT' }, sentences: [
        { id: 's', sentenceOrder: 0, exactText: 'Jeg jobber.', startMs: 1000, endMs: 3000, alignmentMethod: 'IMPORTED_VTT' },
      ] },
      progress: {}, preferences: { defaultMode: 'LISTENING_ONLY', rate: 1 },
      authenticMedia: { sourceName: 'User-owned upload' }, alignmentStatus: 'IMPORTED_VTT',
    }, handlers);
    expect(mount.textContent).toContain('AUTHENTIC MEDIA');
    expect(mount.textContent).toContain('IMPORTED_VTT');
    expect(mount.querySelector('[aria-current="true"]')).not.toBeNull();
    expect(mount.querySelector('[aria-label="Aligned sentence timeline"]')).not.toBeNull();
    [...mount.querySelectorAll('button')].find((button) => button.textContent === 'Save sentence to Phrasebook').click();
    expect(handlers.onSaveExpression).toHaveBeenCalledWith(expect.objectContaining({ id: 's' }));
  });

  it('keeps the transcript DOM bounded for large authentic imports', () => {
    const mount = document.createElement('main');
    renderListeningText(mount, {
      payload: {
        document: { id: 'large', title: 'Large transcript', sourceType: 'CONTENT_TRANSCRIPT' },
        sentences: Array.from({ length: 5000 }, (_, index) => ({
          id: `s-${index}`, sentenceOrder: index, exactText: `Sentence ${index}`,
          startMs: index * 1000, endMs: (index + 1) * 1000, alignmentMethod: 'IMPORTED_SRT',
        })),
      },
      currentIndex: 2500, progress: {}, preferences: {}, authenticMedia: { sourceName: 'Upload' },
    });
    expect(mount.querySelectorAll('.language-listening-sentence').length).toBeLessThanOrEqual(201);
    expect(mount.textContent).toContain('Sentence 2501 / 5000');
  });
});

describe('Authentic media interval evidence', () => {
  it('merges played intervals and excludes manual seek gaps', async () => {
    let now = 0;
    const ended = vi.fn();
    const player = createAuthenticMediaPlayer({ AudioClass: FakeAudio, clock: () => now });
    await player.playSegment({ url: '/media/a', startMs: 0, endMs: 2000, onEnded: ended });
    now = 500; player.audio.advance(0.5);
    player.audio.seek(1.5);
    now = 1000; player.audio.advance(2);
    expect(ended).toHaveBeenCalledTimes(1);
    const evidence = ended.mock.calls[0][0];
    expect(evidence.activeMs).toBe(1000);
    expect(evidence.coverageMs).toBe(1000);
    expect(evidence.durationMs).toBe(2000);
  });

  it('does not double-count overlapping playback samples', () => {
    expect(coveredMilliseconds([[0, 500], [450, 1000], [1500, 1750]])).toBe(1250);
  });

  it('does not repeat start evidence or reload the same media URL on resume and replay', async () => {
    const player = createAuthenticMediaPlayer({ AudioClass: FakeAudio });
    const onStart = vi.fn();
    await player.playSegment({ url: '/media/a', startMs: 0, endMs: 2000, onStart });
    await player.resume();
    expect(onStart).toHaveBeenCalledTimes(1);
    expect(player.audio.src).toBe('/media/a');
  });
});
