export function wordAudioControl(documentRef, play, label = 'Hear word') {
  if (!play) return null;
  const wrap = documentRef.createElement('span');
  wrap.className = 'language-word-audio';
  const button = documentRef.createElement('button');
  button.type = 'button';
  button.className = 'language-button';
  button.textContent = label;
  const status = documentRef.createElement('small');
  status.setAttribute('role', 'status');
  wrap.append(button, status);
  function showFallback(url) {
    if (!url) return;
    const fallback = documentRef.createElement('audio');
    fallback.controls = true;
    fallback.src = url;
    fallback.setAttribute('aria-label', 'Word pronunciation');
    wrap.querySelector('audio')?.remove();
    wrap.append(fallback);
  }
  button.addEventListener('click', async () => {
    button.disabled = true;
    status.textContent = 'Preparing pronunciation…';
    let audioUrl = null;
    try {
      await play({
        onQueued: (state) => { status.textContent = state === 'RUNNING' ? 'Generating pronunciation…' : 'Queued for pronunciation…'; },
        onReady: (url) => { audioUrl = url; },
        onPlaying: () => { status.textContent = 'Playing pronunciation'; },
        onEnded: () => { status.textContent = ''; },
        onError: (error) => {
          status.textContent = error?.message || 'Pronunciation could not be played.';
          showFallback(audioUrl);
        },
      });
    } catch (error) {
      status.textContent = error?.message || 'Pronunciation unavailable.';
      showFallback(audioUrl);
    } finally {
      button.disabled = false;
    }
  });
  return wrap;
}
