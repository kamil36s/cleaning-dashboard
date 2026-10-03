export function createClozeAudioPlayer({
  AudioClass = globalThis.Audio,
  coordinator = null,
  owner = `cloud-audio-${Math.random().toString(16).slice(2)}`,
} = {}) {
  let current = null;
  let currentCallbacks = null;
  let sequence = 0;

  function available() {
    return typeof AudioClass === 'function';
  }

  function stopInternal({ release = true, notify = true } = {}) {
    sequence += 1;
    if (!current) return false;
    const audio = current;
    const callbacks = currentCallbacks;
    current = null;
    currentCallbacks = null;
    audio.onended = null;
    audio.onerror = null;
    audio.pause?.();
    try { audio.currentTime = 0; } catch (_error) { /* read-only before metadata in some browsers */ }
    if (release) coordinator?.release(owner);
    if (notify) callbacks?.onCancel?.(audio);
    return true;
  }

  function stop() {
    stopInternal();
  }

  function pause() {
    current?.pause?.();
  }

  async function resume() {
    if (!current) throw new Error('No paused sentence audio is available.');
    await current.play();
    return current;
  }

  async function play(url, callbacks = {}) {
    const { onPlaying, onEnded, onError } = callbacks;
    if (!available()) throw new Error('Audio playback is unavailable in this browser.');
    stop();
    const token = sequence;
    const audio = new AudioClass(url);
    current = audio;
    currentCallbacks = callbacks;
    coordinator?.activate(owner, () => stopInternal({ release: false }));
    audio.preload = 'auto';
    audio.onended = () => {
      if (token !== sequence) return;
      current = null;
      currentCallbacks = null;
      coordinator?.release(owner);
      onEnded?.(audio);
    };
    audio.onerror = () => {
      if (token !== sequence) return;
      current = null;
      currentCallbacks = null;
      coordinator?.release(owner);
      onError?.(new Error('The cached sentence audio could not be played.'), audio);
    };
    try {
      await audio.play();
      if (token === sequence) onPlaying?.(audio);
    } catch (error) {
      if (token === sequence) {
        current = null;
        currentCallbacks = null;
        coordinator?.release(owner);
        onError?.(error, audio);
      }
      throw error;
    }
    return audio;
  }

  return { available, play, pause, resume, stop };
}
