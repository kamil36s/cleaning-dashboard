(() => {
  const card = document.getElementById('hm-card');
  const db = window.HABIT_DB;
  if (!card || !db || !Array.isArray(db.habits)) {
    return;
  }

  const DAY_MS = 86400000;
  const PAD = { l: 40, r: 12, t: 12, b: 26 };
  const COLORS = ['#86efac', '#60a5fa', '#facc15', '#f472b6', '#22d3ee', '#f97316', '#a78bfa'];

  const EXCLUDED_BINARY = [
    /ash?wagand[ae]h?a?/i,
    /biotyn|b\s*complex/i,
    /collagen/i,
    /l[-\s]?theanine/i,
    /lion'?s?\s*mane/i,
    /magnez|magnesium/i,
    /omega\s*3/i,
    /witamin[ay]\s*d|vitamin\s*d/i,
    /^zinc$/i
  ];

  const habits = db.habits.map((h) => ({
    id: h.id,
    name: h.name,
    type: h.type,
    unit: (h.unit || '').replace(/μ/g, 'u'),
    points: Array.isArray(h.points) ? h.points : []
  }));

  let minTs = Infinity;
  let maxTs = -Infinity;
  habits.forEach((h) => {
    if (h.points.length) {
      minTs = Math.min(minTs, h.points[0][0]);
      maxTs = Math.max(maxTs, h.points[h.points.length - 1][0]);
    }
  });
  if (!isFinite(minTs)) {
    return;
  }

  const totalDays = Math.round((maxTs - minTs) / DAY_MS) + 1;
  habits.forEach((h) => {
    const series = new Float32Array(totalDays);
    let maxVal = 0;
    for (const [ts, raw] of h.points) {
      const idx = Math.round((ts - minTs) / DAY_MS);
      if (idx < 0 || idx >= totalDays) continue;
      if (h.type === 0) {
        const val = raw > 0 ? 1 : 0;
        if (val > series[idx]) series[idx] = val;
      } else {
        const val = raw / 1000;
        series[idx] += val;
      }
    }
    for (let i = 0; i < series.length; i += 1) {
      if (series[i] > maxVal) maxVal = series[i];
    }
    h.series = series;
    h.maxVal = maxVal || 1;
  });

  const colorMap = new Map();
  habits.forEach((h, i) => {
    colorMap.set(h.id, COLORS[i % COLORS.length]);
  });

  const elWindow = document.getElementById('hm-window');
  const elWindowVal = document.getElementById('hm-window-val');
  const elOffset = document.getElementById('hm-offset');
  const elRangeLabel = document.getElementById('hm-range-label');
  const elPills = document.getElementById('hm-pills');
  const elSelectAll = document.getElementById('hm-select-all');
  const elClear = document.getElementById('hm-clear');
  const elLast = document.getElementById('hm-last');
  const elNormalize = document.getElementById('hm-normalize');
  const elSelected = document.getElementById('hm-selected');
  const elBinary = document.getElementById('hm-binary');
  const elBinaryLabels = document.getElementById('hm-binary-labels');
  const elBinaryRows = document.getElementById('hm-binary-rows');
  const canvas = document.getElementById('hm-canvas');
  const tip = document.getElementById('hm-tooltip');
  const ctx = canvas.getContext('2d');

  const minWindow = Math.min(14, totalDays);
  const state = {
    window: Math.min(90, totalDays),
    offset: Math.max(0, totalDays - Math.min(90, totalDays)),
    hoverIndex: null,
    normalize: false
  };

  const selected = new Set();
  habits.forEach((h) => {
    if (/concerta|medikinet/i.test(h.name)) {
      selected.add(h.id);
    }
  });
  if (!selected.size && habits.length) {
    selected.add(habits[0].id);
  }

  const pillButtons = new Map();
  let drag = null;
  let binaryDrag = null;

  const PILL_CATEGORIES = [
    {
      id: 'meds',
      title: 'Meds',
      re: /concerta|atenza|medikinet|pregabalin|duloxetine|sertraline|escitalopram|bupropion|fluoxetine|venlafaxine/i
    },
    {
      id: 'supplements',
      title: 'Supplements',
      re: /ash?wagand[ae]h?a?|biotyn|b\s*complex|b12|kolagen|collagen|lion'?s?\s*mane|magnez|magnesium|omega\s*3|vitamin\s*[cd]|witamin[ay]\s*[cd]|zinc|theanine/i
    }
  ];

  function pillCategory(name) {
    for (const cat of PILL_CATEGORIES) {
      if (cat.re.test(name)) return cat;
    }
    return { id: 'other', title: 'Other' };
  }

  function clamp(val, min, max) {
    return Math.max(min, Math.min(max, val));
  }

  function fmtDate(ts) {
    return new Date(ts).toISOString().slice(0, 10);
  }

  function formatValue(habit, val) {
    if (habit.type === 0) {
      return val > 0 ? 'done' : 'miss';
    }
    const unit = habit.unit ? habit.unit : '';
    const num = Number.isInteger(val) ? String(val) : val.toFixed(1).replace(/\.0$/, '');
    return unit ? `${num} ${unit}` : num;
  }

  function updateRangeLabel() {
    const start = state.offset;
    const end = Math.min(totalDays - 1, state.offset + state.window - 1);
    const a = minTs + start * DAY_MS;
    const b = minTs + end * DAY_MS;
    elRangeLabel.textContent = `${fmtDate(a)} -> ${fmtDate(b)}`;
  }

  function updateSelectedLabel() {
    elSelected.textContent = `${selected.size} selected`;
  }

  function updateNormalizeUI() {
    const on = state.normalize;
    elNormalize.classList.toggle('is-on', on);
    elNormalize.setAttribute('aria-pressed', on ? 'true' : 'false');
  }

  function renderBinaryTiles() {
    if (!elBinary || !elBinaryLabels || !elBinaryRows) return;
    const { start, end } = metrics();
    const binaryHabits = habits.filter((h) => h.type === 0 && !EXCLUDED_BINARY.some((re) => re.test(h.name)));
    if (!binaryHabits.length) {
      elBinary.hidden = true;
      return;
    }

    elBinary.hidden = false;
    elBinaryLabels.innerHTML = '';
    elBinaryRows.innerHTML = '';
    const days = end - start + 1;

    binaryHabits.forEach((h) => {
      const label = document.createElement('div');
      label.className = 'hm-binary-label';
      label.textContent = h.name;
      elBinaryLabels.appendChild(label);

      const grid = document.createElement('div');
      grid.className = 'hm-binary-grid';

      for (let i = 0; i < days; i += 1) {
        const idx = start + i;
        const val = h.series[idx] || 0;
        const tile = document.createElement('div');
        tile.className = `hm-tile ${val > 0 ? 'is-on' : 'is-off'}`;
        const dateObj = new Date(minTs + idx * DAY_MS);
        const day = dateObj.getDate();
        const month = dateObj.getMonth() + 1;
        const label = `${day}.${String(month).padStart(2, '0')}`;
        tile.innerHTML = `<span class="hm-tile-date">${label}</span>`;
        tile.title = `${fmtDate(minTs + idx * DAY_MS)}: ${val > 0 ? 'yes' : 'no'}`;
        grid.appendChild(tile);
      }

      elBinaryRows.appendChild(grid);
    });
  }

  function updatePills() {
    pillButtons.forEach((btn, id) => {
      const on = selected.has(id);
      btn.classList.toggle('is-on', on);
      btn.classList.toggle('is-off', !on);
    });
  }

  function buildPills() {
    elPills.innerHTML = '';
    const groups = new Map();
    habits.forEach((h) => {
      const cat = pillCategory(h.name);
      if (!groups.has(cat.id)) groups.set(cat.id, { title: cat.title, items: [] });
      groups.get(cat.id).items.push(h);
    });

    const ordered = [
      groups.get('meds'),
      groups.get('supplements'),
      groups.get('other')
    ].filter(Boolean);

    ordered.forEach((group) => {
      const section = document.createElement('div');
      section.className = 'hm-pill-section';

      const head = document.createElement('div');
      head.className = 'hm-pill-head';
      head.innerHTML = `<span class="hm-pill-title">${group.title}</span><span class="hm-pill-line"></span>`;
      section.appendChild(head);

      const wrap = document.createElement('div');
      wrap.className = 'hm-pill-group';

      group.items
        .sort((a, b) => a.name.localeCompare(b.name))
        .forEach((h) => {
          const btn = document.createElement('button');
          btn.type = 'button';
          btn.className = 'pill hm-habit-pill';
          btn.dataset.id = String(h.id);
          btn.textContent = h.name;
          const meta = h.type === 0 ? 'binary' : (h.unit || 'value');
          btn.title = meta ? `${h.name} (${meta})` : h.name;
          btn.addEventListener('click', () => {
            if (selected.has(h.id)) selected.delete(h.id);
            else selected.add(h.id);
            updateSelectedLabel();
            updatePills();
            renderBinaryTiles();
            render();
          });
          wrap.appendChild(btn);
          pillButtons.set(h.id, btn);
        });

      section.appendChild(wrap);
      elPills.appendChild(section);
    });
    updatePills();
  }

  function setWindow(days) {
    state.window = clamp(days, minWindow, totalDays);
    elWindow.value = String(state.window);
    elWindowVal.textContent = String(state.window);
    elOffset.max = String(Math.max(0, totalDays - state.window));
    state.offset = clamp(state.offset, 0, Number(elOffset.max));
    elOffset.value = String(state.offset);
    state.hoverIndex = null;
    tip.hidden = true;
    updateRangeLabel();
    renderBinaryTiles();
    render();
  }

  function setOffset(days) {
    state.offset = clamp(days, 0, Number(elOffset.max));
    elOffset.value = String(state.offset);
    state.hoverIndex = null;
    tip.hidden = true;
    updateRangeLabel();
    renderBinaryTiles();
    render();
  }

  function metrics() {
    const rect = canvas.getBoundingClientRect();
    const plotW = Math.max(1, rect.width - PAD.l - PAD.r);
    const plotH = Math.max(1, rect.height - PAD.t - PAD.b);
    const start = state.offset;
    const end = Math.min(totalDays - 1, start + state.window - 1);
    const count = end - start + 1;
    const xStep = count > 1 ? plotW / (count - 1) : 0;
    return { rect, plotW, plotH, start, end, count, xStep };
  }

  function render() {
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    ctx.clearRect(0, 0, w, h);

    const { plotW, plotH, start, end, count, xStep } = metrics();
    const selectedHabits = habits.filter((h) => selected.has(h.id));

    if (!selectedHabits.length) {
      ctx.fillStyle = 'rgba(255,255,255,0.4)';
      ctx.font = '12px Inter, system-ui, sans-serif';
      ctx.fillText('Select habits to show chart', PAD.l, PAD.t + 16);
      return;
    }

    const normalize = state.normalize;
    let axisMax = 1;
    if (!normalize) {
      selectedHabits.forEach((h) => {
        const localMax = h.type === 0 ? 1 : h.maxVal;
        if (localMax > axisMax) axisMax = localMax;
      });
    }

    ctx.strokeStyle = 'rgba(255,255,255,0.08)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(PAD.l, PAD.t + plotH);
    ctx.lineTo(PAD.l + plotW, PAD.t + plotH);
    ctx.stroke();

    const labelMax = normalize ? '100%' : (Number.isInteger(axisMax) ? String(axisMax) : axisMax.toFixed(1).replace(/\.0$/, ''));
    const labelMin = normalize ? '0%' : '0';
    ctx.fillStyle = 'rgba(255,255,255,0.35)';
    ctx.font = '11px Inter, system-ui, sans-serif';
    ctx.fillText(labelMin, 8, PAD.t + plotH + 4);
    ctx.fillText(labelMax, 6, PAD.t + 10);

    selectedHabits.forEach((h) => {
      const color = colorMap.get(h.id) || COLORS[0];
      ctx.beginPath();
      const scale = normalize ? (h.maxVal || 1) : axisMax;
      for (let i = 0; i < count; i += 1) {
        const val = h.series[start + i] || 0;
        const ratio = scale ? (val / scale) : 0;
        const x = PAD.l + i * xStep;
        const y = PAD.t + plotH - ratio * plotH;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      ctx.stroke();
    });

    if (state.hoverIndex !== null) {
      const idx = clamp(state.hoverIndex, start, end);
      const local = idx - start;
      const x = PAD.l + local * xStep;

      ctx.strokeStyle = 'rgba(255,255,255,0.25)';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x, PAD.t);
      ctx.lineTo(x, PAD.t + plotH);
      ctx.stroke();

      selectedHabits.forEach((h) => {
        const color = colorMap.get(h.id) || COLORS[0];
        const val = h.series[idx] || 0;
        const scale = normalize ? (h.maxVal || 1) : axisMax;
        const ratio = scale ? (val / scale) : 0;
        const y = PAD.t + plotH - ratio * plotH;
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(x, y, 3, 0, Math.PI * 2);
        ctx.fill();
      });
    }
  }

  function updateTooltip(idx, localX) {
    const selectedHabits = habits.filter((h) => selected.has(h.id));
    if (!selectedHabits.length) {
      tip.hidden = true;
      return;
    }

    const rows = selectedHabits.map((h) => {
      const color = colorMap.get(h.id) || COLORS[0];
      const val = h.series[idx] || 0;
      const valueText = formatValue(h, val);
      return `<div class="hm-tip-row"><span class="hm-tip-dot" style="background:${color}"></span>${h.name}: ${valueText}</div>`;
    }).join('');

    const date = fmtDate(minTs + idx * DAY_MS);
    tip.innerHTML = `<div class="hm-tip-date">${date}</div>${rows}`;
    tip.style.left = `${localX + 8}px`;
    tip.style.top = '16px';
    tip.hidden = false;
  }

  function resizeCanvas() {
    const rect = canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.max(1, Math.floor(rect.width * dpr));
    canvas.height = Math.max(1, Math.floor(rect.height * dpr));
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    render();
  }

  const ro = new ResizeObserver(resizeCanvas);
  ro.observe(canvas);

  canvas.addEventListener('pointerdown', (e) => {
    drag = { x: e.clientX, offset: state.offset };
    canvas.setPointerCapture(e.pointerId);
  });

  canvas.addEventListener('pointermove', (e) => {
    const { rect, plotW, start, end, count, xStep } = metrics();

    if (drag) {
      const dx = e.clientX - drag.x;
      const dayShift = xStep ? Math.round(-dx / xStep) : 0;
      setOffset(drag.offset + dayShift);
    }

    const x = e.clientX - rect.left - PAD.l;
    if (x < 0 || x > plotW) {
      state.hoverIndex = null;
      tip.hidden = true;
      render();
      return;
    }

    const local = count > 1 ? Math.round(x / xStep) : 0;
    const idx = clamp(start + local, start, end);
    state.hoverIndex = idx;
    updateTooltip(idx, PAD.l + local * xStep);
    render();
  });

  canvas.addEventListener('pointerup', () => {
    drag = null;
  });

  canvas.addEventListener('pointerleave', () => {
    drag = null;
    state.hoverIndex = null;
    tip.hidden = true;
    render();
  });

  if (elBinary) {
    const scrollEl = document.getElementById('hm-binary-scroll');
    if (scrollEl) {
      scrollEl.addEventListener('pointerdown', (e) => {
        binaryDrag = { x: e.clientX, scrollLeft: scrollEl.scrollLeft };
        scrollEl.classList.add('is-dragging');
        scrollEl.setPointerCapture(e.pointerId);
      });
      scrollEl.addEventListener('pointermove', (e) => {
        if (!binaryDrag) return;
        const dx = e.clientX - binaryDrag.x;
        scrollEl.scrollLeft = binaryDrag.scrollLeft - dx;
      });
      const endDrag = () => {
        binaryDrag = null;
        scrollEl.classList.remove('is-dragging');
      };
      scrollEl.addEventListener('pointerup', endDrag);
      scrollEl.addEventListener('pointerleave', endDrag);
    }
  }

  canvas.addEventListener('wheel', (e) => {
    e.preventDefault();
    if (e.ctrlKey) {
      const delta = Math.sign(e.deltaY);
      setWindow(state.window + delta * 7);
    } else {
      const delta = Math.sign(e.deltaY);
      setOffset(state.offset + delta * 3);
    }
  }, { passive: false });

  elWindow.min = String(minWindow);
  elWindow.max = String(totalDays);
  elWindow.value = String(state.window);
  elWindowVal.textContent = String(state.window);
  elOffset.max = String(Math.max(0, totalDays - state.window));
  elOffset.value = String(state.offset);

  elWindow.addEventListener('input', (e) => setWindow(Number(e.target.value)));
  elOffset.addEventListener('input', (e) => setOffset(Number(e.target.value)));
  elNormalize.addEventListener('click', () => {
    state.normalize = !state.normalize;
    updateNormalizeUI();
    render();
  });
  elSelectAll.addEventListener('click', () => {
    habits.forEach((h) => selected.add(h.id));
    updateSelectedLabel();
    updatePills();
    renderBinaryTiles();
    render();
  });
  elClear.addEventListener('click', () => {
    selected.clear();
    updateSelectedLabel();
    updatePills();
    renderBinaryTiles();
    render();
  });
  elLast.addEventListener('click', () => {
    setOffset(totalDays - state.window);
  });

  buildPills();
  updateNormalizeUI();
  updateRangeLabel();
  updateSelectedLabel();
  renderBinaryTiles();
  render();
})();
