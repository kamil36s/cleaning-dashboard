(() => {
  const uploadBtn = document.getElementById('hm-upload-btn');
  const fileInput = document.getElementById('hm-db-input');
  const statusEl = document.getElementById('hm-upload-status');
  if (!uploadBtn || !fileInput || !statusEl) {
    return;
  }

  function resolveApiUrl() {
    const localHosts = new Set(['localhost', '127.0.0.1']);
    const isLocal = localHosts.has(window.location.hostname);
    if (isLocal && window.location.port !== '8000') {
      return 'http://127.0.0.1:8000/api/habits/upload-db';
    }
    return '/api/habits/upload-db';
  }

  const API_URL = resolveApiUrl();
  const MAX_BYTES = 64 * 1024 * 1024;

  function setStatus(message, kind = '') {
    statusEl.textContent = message || '';
    statusEl.classList.remove('is-ok', 'is-error');
    if (kind) statusEl.classList.add(kind);
  }

  function fileToBase64(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        const result = String(reader.result || '');
        const comma = result.indexOf(',');
        if (comma < 0) {
          reject(new Error('Nieprawidłowy format pliku'));
          return;
        }
        resolve(result.slice(comma + 1));
      };
      reader.onerror = () => reject(new Error('Nie udało się odczytać pliku'));
      reader.readAsDataURL(file);
    });
  }

  async function uploadDb(file) {
    if (!file) return;
    if (!/\.db$/i.test(file.name)) {
      setStatus('Wybierz plik z rozszerzeniem .db', 'is-error');
      return;
    }
    if (file.size > MAX_BYTES) {
      setStatus('Plik jest za duży (max 64 MB)', 'is-error');
      return;
    }

    uploadBtn.disabled = true;
    uploadBtn.classList.add('is-loading');
    setStatus(`Upload: ${file.name}...`);

    try {
      const contentBase64 = await fileToBase64(file);
      const res = await fetch(API_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          filename: file.name,
          contentBase64
        })
      });

      const payload = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(payload.error || `Upload failed (${res.status})`);
      }

      const habitsCount = payload.summary && Number.isFinite(payload.summary.habits)
        ? ` | habits: ${payload.summary.habits}`
        : '';
      setStatus(`OK: ${payload.file}${habitsCount}. Odświeżam widok...`, 'is-ok');
      setTimeout(() => {
        window.location.reload();
      }, 700);
    } catch (err) {
      let msg = err && err.message ? err.message : 'Upload failed';
      if (/Failed to fetch/i.test(msg) || /NetworkError/i.test(msg)) {
        msg = 'Brak połączenia z API (127.0.0.1:8000). Uruchom start-dev.cmd.';
      }
      setStatus(msg, 'is-error');
    } finally {
      uploadBtn.disabled = false;
      uploadBtn.classList.remove('is-loading');
      fileInput.value = '';
    }
  }

  uploadBtn.addEventListener('click', () => fileInput.click());
  fileInput.addEventListener('change', () => {
    const file = fileInput.files && fileInput.files[0];
    uploadDb(file);
  });
})();
