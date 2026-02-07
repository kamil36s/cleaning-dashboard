let active = null;
let counter = 0;

function ensureToast() {
  let toast = document.getElementById('undo-toast');
  if (toast) {
    return {
      root: toast,
      text: toast.querySelector('.undo-toast-text'),
      button: toast.querySelector('.undo-toast-btn'),
    };
  }

  toast = document.createElement('div');
  toast.id = 'undo-toast';
  toast.className = 'undo-toast';
  toast.setAttribute('role', 'status');
  toast.setAttribute('aria-live', 'polite');

  toast.innerHTML = `
    <span class="undo-toast-text"></span>
    <button class="undo-toast-btn" type="button">Cofnij</button>
  `;

  document.body.appendChild(toast);

  return {
    root: toast,
    text: toast.querySelector('.undo-toast-text'),
    button: toast.querySelector('.undo-toast-btn'),
  };
}

export function scheduleUndo({ message, duration = 4000, onCommit, onUndo }) {
  if (active && typeof active.commit === 'function') {
    active.commit();
  }

  const { root, text, button } = ensureToast();
  const id = ++counter;
  let done = false;
  let timeout = null;

  const cleanup = () => {
    if (timeout) {
      clearTimeout(timeout);
      timeout = null;
    }
    root.classList.remove('show');
    if (active && active.id === id) {
      active = null;
    }
  };

  const commit = () => {
    if (done) return;
    done = true;
    cleanup();
    try {
      const res = onCommit && onCommit();
      if (res && typeof res.catch === 'function') {
        res.catch((err) => console.error('Undo commit failed:', err));
      }
    } catch (err) {
      console.error('Undo commit failed:', err);
    }
  };

  const undo = () => {
    if (done) return;
    done = true;
    cleanup();
    try {
      if (onUndo) onUndo();
    } catch (err) {
      console.error('Undo rollback failed:', err);
    }
  };

  text.textContent = message || 'Zaznaczone.';
  button.onclick = (ev) => {
    ev.preventDefault();
    undo();
  };

  root.classList.add('show');
  timeout = setTimeout(commit, duration);

  active = { id, commit, undo };
  return { commit, undo };
}
