export function createLanguagePlaybackCoordinator() {
  let current = null;

  return {
    activate(owner, cancel) {
      if (!owner || typeof cancel !== 'function') throw new TypeError('Playback owner and cancel callback are required.');
      if (current && current.owner !== owner) {
        const previous = current;
        current = null;
        previous.cancel();
      }
      current = { owner, cancel };
    },
    release(owner) {
      if (current?.owner === owner) current = null;
    },
    stop() {
      if (!current) return false;
      const previous = current;
      current = null;
      previous.cancel();
      return true;
    },
    currentOwner() {
      return current?.owner || null;
    },
  };
}

