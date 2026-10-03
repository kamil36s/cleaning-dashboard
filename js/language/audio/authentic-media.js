function mergeIntervals(intervals) {
  const sorted = intervals.filter(([start, end]) => end > start).sort((a, b) => a[0] - b[0]);
  const result = [];
  sorted.forEach(([start, end]) => {
    const current = result[result.length - 1];
    if (!current || start > current[1] + 50) result.push([start, end]);
    else current[1] = Math.max(current[1], end);
  });
  return result;
}

export function coveredMilliseconds(intervals) {
  return mergeIntervals(intervals).reduce((sum, [start, end]) => sum + Math.max(0, end - start), 0);
}

export function createAuthenticMediaPlayer({
  AudioClass = globalThis.Audio,
  coordinator,
  clock = () => globalThis.performance?.now?.() ?? Date.now(),
} = {}) {
  if (typeof AudioClass !== 'function') throw new TypeError('Audio is unavailable.');
  const audio = new AudioClass();
  let segment = null;
  let activeStartedAt = null;
  let activeMs = 0;
  let lastMediaMs = null;
  let intervals = [];
  let seeking = false;
  let finishing = false;
  let loadedUrl = null;
  let startNotified = false;

  function accumulateActive() {
    if (activeStartedAt == null) return;
    activeMs += Math.max(0, clock() - activeStartedAt);
    activeStartedAt = null;
  }
  function summary() {
    return {
      activeMs: Math.round(activeMs),
      coverageMs: Math.round(coveredMilliseconds(intervals)),
      durationMs: segment ? Math.max(1, segment.endMs - segment.startMs) : null,
      intervals: mergeIntervals(intervals),
    };
  }
  function recordPosition() {
    if (!segment || seeking) return;
    const current = Math.round(Number(audio.currentTime || 0) * 1000);
    if (lastMediaMs != null) {
      const delta = current - lastMediaMs;
      if (delta >= 0 && delta <= 1500) {
        const start = Math.max(segment.startMs, lastMediaMs);
        const end = Math.min(segment.endMs, current);
        if (end > start) intervals.push([start, end]);
      }
    }
    lastMediaMs = current;
    segment.onProgress?.({ currentMs: current, ...summary() });
    if (current >= segment.endMs && !finishing) finish('ENDED');
  }
  function finish(outcome) {
    if (!segment || finishing) return;
    finishing = true;
    accumulateActive();
    recordPosition();
    audio.pause?.();
    const callback = outcome === 'ERROR' ? segment.onError : segment.onEnded;
    const evidence = summary();
    coordinator?.release?.('listening-authentic');
    callback?.(evidence);
    finishing = false;
  }

  audio.addEventListener?.('playing', () => {
    if (!segment) return;
    activeStartedAt = clock();
    lastMediaMs = Math.round(Number(audio.currentTime || 0) * 1000);
    if (!startNotified) {
      startNotified = true;
      segment.onStart?.();
    }
  });
  audio.addEventListener?.('timeupdate', recordPosition);
  audio.addEventListener?.('pause', accumulateActive);
  audio.addEventListener?.('ended', () => finish('ENDED'));
  audio.addEventListener?.('error', () => finish('ERROR'));
  audio.addEventListener?.('seeking', () => { accumulateActive(); seeking = true; lastMediaMs = null; });
  audio.addEventListener?.('seeked', () => {
    seeking = false;
    lastMediaMs = Math.round(Number(audio.currentTime || 0) * 1000);
    if (!audio.paused) activeStartedAt = clock();
  });
  audio.addEventListener?.('waiting', accumulateActive);
  audio.addEventListener?.('stalled', accumulateActive);

  return {
    audio,
    async playSegment({ url, startMs, endMs, rate = 1, onStart, onProgress, onEnded, onError }) {
      if (!(Number.isFinite(startMs) && Number.isFinite(endMs) && endMs > startMs)) {
        throw new TypeError('A valid aligned sentence interval is required.');
      }
      this.stop();
      segment = { startMs, endMs, onStart, onProgress, onEnded, onError };
      activeMs = 0; activeStartedAt = null; intervals = []; lastMediaMs = null; seeking = false; finishing = false; startNotified = false;
      coordinator?.activate?.('listening-authentic', () => this.stop());
      if (loadedUrl !== url) {
        audio.src = url;
        loadedUrl = url;
      }
      audio.playbackRate = Math.max(0.5, Math.min(2, Number(rate) || 1));
      audio.currentTime = startMs / 1000;
      try { await audio.play(); } catch (error) { coordinator?.release?.('listening-authentic'); segment = null; throw error; }
    },
    pause() { if (!segment) return; accumulateActive(); audio.pause?.(); },
    async resume() {
      if (!segment) return;
      await audio.play();
    },
    stop() {
      accumulateActive();
      audio.pause?.();
      coordinator?.release?.('listening-authentic');
      segment = null; activeStartedAt = null; lastMediaMs = null;
    },
    seek(ms) {
      if (!segment) return;
      audio.currentTime = Math.max(segment.startMs, Math.min(segment.endMs, Number(ms) || segment.startMs)) / 1000;
    },
    setRate(value) { audio.playbackRate = Math.max(0.5, Math.min(2, Number(value) || 1)); },
    summary,
  };
}

export { mergeIntervals };
