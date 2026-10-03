const RATING_VALUES = Array.from({ length: 10 }, (_, index) => (index + 1) / 2);

function normalizeRating(value) {
  if (value === null || value === undefined || value === '') return null;
  const parsed = Number(String(value).replace(',', '.'));
  if (!Number.isFinite(parsed) || parsed < 0.5 || parsed > 5) return null;
  return Math.round(parsed * 2) / 2;
}

function formatRating(value) {
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

export function createAlbumStarRating(selectedValue, options = {}) {
  const {
    ariaLabel = 'Ocena albumu',
    emptyLabel = '—',
  } = options;
  const root = document.createElement('div');
  root.className = 'album-star-rating';
  root.setAttribute('role', 'radiogroup');
  root.setAttribute('aria-label', ariaLabel);

  const stars = document.createElement('div');
  stars.className = 'album-star-rating-stars';
  const glyphs = document.createElement('div');
  glyphs.className = 'album-star-rating-glyphs';
  for (let index = 0; index < 5; index += 1) {
    const star = document.createElement('span');
    star.className = 'album-star-rating-star';
    star.setAttribute('aria-hidden', 'true');
    const base = document.createElement('span');
    base.className = 'album-star-rating-base';
    base.textContent = '★';
    const fill = document.createElement('span');
    fill.className = 'album-star-rating-fill';
    fill.textContent = '★';
    star.append(base, fill);
    glyphs.appendChild(star);
  }
  const targets = document.createElement('div');
  targets.className = 'album-star-rating-targets';
  const output = document.createElement('output');
  output.className = 'album-star-rating-value';

  let value = normalizeRating(selectedValue);
  let disabled = false;

  const paint = (displayValue) => {
    const normalized = normalizeRating(displayValue);
    root.style.setProperty('--album-rating-fill', `${normalized ? normalized * 20 : 0}%`);
    glyphs.querySelectorAll('.album-star-rating-star').forEach((star, index) => {
      const fillAmount = normalized ? Math.max(0, Math.min(1, normalized - index)) : 0;
      star.style.setProperty('--album-star-fill', `${fillAmount * 100}%`);
    });
    output.textContent = normalized ? formatRating(normalized) : emptyLabel;
  };

  const syncChecked = () => {
    targets.querySelectorAll('button').forEach((button) => {
      button.setAttribute('aria-checked', String(Number(button.dataset.value) === value));
    });
    root.setAttribute('aria-valuetext', value ? `${formatRating(value)} na 5` : 'Brak oceny');
  };

  const commit = (nextValue, { emit = true, focus = false } = {}) => {
    if (disabled) return;
    value = normalizeRating(nextValue);
    paint(value);
    syncChecked();
    const target = targets.querySelector(`[data-value="${value}"]`);
    if (focus) target?.focus();
    if (emit) root.dispatchEvent(new Event('change', { bubbles: true }));
  };

  RATING_VALUES.forEach((rating) => {
    const target = document.createElement('button');
    target.type = 'button';
    target.dataset.value = String(rating);
    target.setAttribute('role', 'radio');
    target.setAttribute('aria-label', `${formatRating(rating)} na 5`);
    target.title = `${formatRating(rating)} / 5`;
    target.addEventListener('mouseenter', () => {
      if (!disabled) paint(rating);
    });
    target.addEventListener('focus', () => {
      if (!disabled) paint(rating);
    });
    target.addEventListener('click', () => commit(rating));
    target.addEventListener('keydown', (event) => {
      if (disabled) return;
      let next = null;
      if (event.key === 'ArrowLeft' || event.key === 'ArrowDown') next = Math.max(0.5, rating - 0.5);
      if (event.key === 'ArrowRight' || event.key === 'ArrowUp') next = Math.min(5, rating + 0.5);
      if (event.key === 'Home') next = 0.5;
      if (event.key === 'End') next = 5;
      if (next === null) return;
      event.preventDefault();
      commit(next, { focus: true });
    });
    targets.appendChild(target);
  });

  stars.addEventListener('mouseleave', () => paint(value));
  stars.addEventListener('focusout', () => {
    setTimeout(() => {
      if (!stars.contains(document.activeElement)) paint(value);
    }, 0);
  });
  stars.append(glyphs, targets);
  root.append(stars, output);

  Object.defineProperties(root, {
    value: {
      get: () => value === null ? '' : String(value),
      set: (nextValue) => commit(nextValue, { emit: false }),
    },
    disabled: {
      get: () => disabled,
      set: (nextValue) => {
        disabled = Boolean(nextValue);
        root.classList.toggle('is-disabled', disabled);
        targets.querySelectorAll('button').forEach((button) => {
          button.disabled = disabled;
        });
      },
    },
  });

  paint(value);
  syncChecked();
  return root;
}
