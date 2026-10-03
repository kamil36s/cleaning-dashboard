import { onDomReady } from './dom-ready.js';
import { calculateDailyTelemetryInsights } from './phone-telemetry/analytics.js';
import {
  formatDateLabel,
  formatDurationShort,
  formatMinutesValue,
  formatPercent,
} from './phone-telemetry/formatters.js';
import {
  mergePhoneTelemetryExports,
  parsePhoneTelemetryJsonText,
  selectPhoneTelemetryDay,
} from './phone-telemetry/parser.js';
import { getPhoneTelemetrySchemaLabel } from './phone-telemetry/schema.js';
import { escapeHtml } from './utils.js';

const SAMPLE_FILES = [
  './data/phone-telemetry/mock-export-2026-03-12.json',
  './data/phone-telemetry/mock-export-2026-03-13.json',
  './data/phone-telemetry/mock-export-2026-03-14.json',
];

const state = {
  dataset: null,
  selectedDay: '',
  sourceLabel: '',
};

function $(id) {
  return document.getElementById(id);
}

function setStatus(message, detail = '') {
  const status = $('pt-status');
  const source = $('pt-source');
  if (status) status.textContent = message;
  if (source) source.textContent = detail;
}

function setError(message = '') {
  const error = $('pt-error');
  if (!error) return;
  const hasError = Boolean(message);
  error.hidden = !hasError;
  error.textContent = message;
}

function setSchemaPill() {
  const pill = $('pt-schema-pill');
  if (!pill) return;
  pill.textContent = `Schema ${getPhoneTelemetrySchemaLabel()}`;
}

function updateDaySelect(dataset, selectedDay) {
  const select = $('pt-day-select');
  if (!select) return;

  select.innerHTML = dataset?.availableDays?.length
    ? dataset.availableDays
        .map((day) => `<option value="${day}">${formatDateLabel(day)}</option>`)
        .join('')
    : '<option value="">Select day</option>';

  select.disabled = !dataset?.availableDays?.length;
  if (selectedDay) {
    select.value = selectedDay;
  }
}

function renderOverview(insights) {
  const root = $('pt-overview');
  if (!root) return;

  const items = [
    { label: 'Phone time', value: formatMinutesValue(insights.core.totalPhoneTimeSeconds) },
    { label: 'Unlocks', value: String(insights.core.unlockCount) },
    { label: 'Avg session', value: formatDurationShort(insights.core.averageSessionDurationSeconds) },
    { label: 'Sessions', value: String(insights.core.sessionCount) },
    { label: 'Short <2m', value: String(insights.core.shortSessionsUnder2m) },
    { label: 'Short ratio', value: formatPercent(insights.core.shortSessionRatio) },
    { label: 'Longest gap', value: formatDurationShort(insights.core.longestNoPhoneWindowSeconds) },
    { label: 'App switches', value: String(insights.core.appSwitchCount) },
    { label: 'Notifications', value: String(insights.messaging.totalNotificationCount) },
    { label: 'Msg-like', value: String(insights.messaging.totalMessageLikeNotificationCount) },
    { label: 'Night use', value: `${insights.core.nightUsageMinutes} min` },
    { label: 'Pressure', value: `${insights.messaging.messagingPressureScore}/100` },
  ];

  root.innerHTML = items
    .map(
      (item) => `
        <article class="pt-stat">
          <div class="pt-stat-label">${escapeHtml(item.label)}</div>
          <div class="pt-stat-value">${escapeHtml(item.value)}</div>
        </article>
      `
    )
    .join('');
}

function getChartLabel(item, index, options = {}) {
  if (typeof options.labelFormatter === 'function') {
    return options.labelFormatter(item, index);
  }
  return item.label;
}

function renderVerticalChart(containerId, series, options = {}) {
  const root = $(containerId);
  if (!root) return;

  root.className = `pt-vchart ${options.chartClass || ''}`.trim();
  const maxValue = Math.max(1, ...series.map((item) => Number(item.value) || 0));

  root.innerHTML = series
    .map((item, index) => {
      const value = Number(item.value) || 0;
      const pct = value > 0 ? Math.max(8, Math.round((value / maxValue) * 100)) : 4;
      const title = options.title
        ? options.title(item)
        : `${item.label}: ${options.valueLabel ? options.valueLabel(value, item) : value}`;
      const display = options.showValues === false
        ? ''
        : (options.displayValue ? options.displayValue(value, item) : String(value));
      const label = getChartLabel(item, index, options);
      const valueClass = options.showValues === false ? 'is-hidden' : '';

      return `
        <div class="pt-vbar ${escapeHtml(options.barClass || '')}" title="${escapeHtml(title)}">
          <div class="pt-vbar-track">
            <div class="pt-vbar-fill ${escapeHtml(options.fillClass || '')}" style="height:${pct}%"></div>
          </div>
          <div class="pt-vbar-value ${valueClass}">${escapeHtml(display)}</div>
          <div class="pt-vbar-label">${escapeHtml(label)}</div>
        </div>
      `;
    })
    .join('');
}

function renderHorizontalBars(containerId, series, options = {}) {
  const root = $(containerId);
  if (!root) return;

  const maxValue = Math.max(1, ...series.map((item) => Number(item.value) || 0));

  root.innerHTML = series.length
    ? series
        .map((item) => {
          const value = Number(item.value) || 0;
          const pct = Math.max(6, Math.round((value / maxValue) * 100));
          return `
            <div class="pt-hbar-row">
              <div class="pt-hbar-head">
                <span class="pt-hbar-label">${escapeHtml(item.label)}</span>
                <span class="pt-hbar-value">${escapeHtml(
                  options.valueLabel ? options.valueLabel(value, item) : String(value)
                )}</span>
              </div>
              <div class="pt-hbar-track">
                <div class="pt-hbar-fill ${escapeHtml(options.fillClass || '')}" style="width:${pct}%"></div>
              </div>
            </div>
          `;
        })
        .join('')
    : '<div class="pt-list-empty">No records for this day.</div>';
}

function renderList(containerId, rows, renderer) {
  const root = $(containerId);
  if (!root) return;
  root.innerHTML = rows.length
    ? rows.map(renderer).join('')
    : '<div class="pt-list-empty">No records for this day.</div>';
}

function renderInsights(daySlice, insights) {
  const body = $('pt-body');
  const empty = $('pt-empty');
  if (!body || !empty) return;

  const deviceLabel = daySlice.device?.deviceLabel || 'Unknown device';
  setStatus(
    `${formatDateLabel(daySlice.day)} | ${deviceLabel}`,
    `${state.sourceLabel} | ${daySlice.timezone} | ${state.dataset.exportCount} export(s)`
  );

  renderOverview(insights);

  renderVerticalChart(
    'pt-usage-chart',
    insights.charts.hourlyUsage.map((item) => ({
      label: item.label,
      value: item.minutes,
    })),
    {
      chartClass: 'is-hourly',
      fillClass: 'is-usage',
      showValues: false,
      labelFormatter: (item, index) => {
        if (index === 0 || index === 23 || index % 2 === 0) return item.label;
        return '';
      },
      title: (item) => `${item.label}:00-${item.label}:59 | ${item.minutes} min`,
    }
  );

  renderVerticalChart('pt-message-chart', insights.charts.hourlyNotifications, {
    chartClass: 'is-hourly',
    fillClass: 'is-messaging',
    showValues: false,
    labelFormatter: (item, index) => {
      if (index === 0 || index === 23 || index % 2 === 0) return item.label;
      return '';
    },
    title: (item) => `${item.label}:00-${item.label}:59 | ${item.value} message-like notifications`,
  });

  renderHorizontalBars(
    'pt-app-share-chart',
    insights.charts.topAppDurationSeries,
    {
      fillClass: 'is-app-share',
      valueLabel: (value) => formatMinutesValue(value),
    }
  );

  renderList('pt-top-apps', insights.core.topAppsByDuration, (item) => `
    <div class="pt-list-row">
      <div class="pt-list-main">
        <div class="pt-list-title">${escapeHtml(item.appLabel)}</div>
        <div class="pt-list-meta">${escapeHtml(item.category || 'unknown')} | ${item.sessionCount} sessions</div>
      </div>
      <div class="pt-list-value">${escapeHtml(formatMinutesValue(item.durationSeconds))}</div>
    </div>
  `);

  renderList('pt-top-messaging-apps', insights.messaging.topMessagingApps, (item) => `
    <div class="pt-list-row">
      <div class="pt-list-main">
        <div class="pt-list-title">${escapeHtml(item.sourceAppLabel)}</div>
        <div class="pt-list-meta">${item.eventCount} events | weight ${item.messageWeight}</div>
      </div>
      <div class="pt-list-value">${item.messageWeight}</div>
    </div>
  `);

  renderList('pt-top-contacts', insights.messaging.topContacts, (item) => `
    <div class="pt-list-row">
      <div class="pt-list-main">
        <div class="pt-list-title">${escapeHtml(item.label)}</div>
        <div class="pt-list-meta">${escapeHtml(item.sourceAppLabel)} | ${item.eventCount} events</div>
      </div>
      <div class="pt-list-value">${item.messageWeight}</div>
    </div>
  `);

  const burstSummary = $('pt-burst-summary');
  if (burstSummary) {
    const topBurst = insights.messaging.messageBursts[0] || null;
    burstSummary.textContent = topBurst
      ? `${insights.messaging.messageBursts.length} burst(s) | strongest window ${topBurst.count} events`
      : '0 bursts detected';
  }

  const synthetic = $('pt-synthetic-summary');
  if (synthetic) {
    const reactionRatio = insights.synthetic.reactionProxy.ratio == null
      ? '-'
      : formatPercent(insights.synthetic.reactionProxy.ratio * 100);
    synthetic.textContent =
      `Fragmentation ${insights.synthetic.fragmentationIndex}/100 | ` +
      `Social/media ${insights.synthetic.socialMediaTimePercent}% | ` +
      `Messaging concentration ${insights.synthetic.messagingConcentrationIndex} | ` +
      `Reaction proxy ${reactionRatio}`;
  }

  empty.hidden = true;
  body.hidden = false;
}

function renderWidget() {
  const body = $('pt-body');
  const empty = $('pt-empty');
  if (!body || !empty) return;

  if (!state.dataset || !state.selectedDay) {
    body.hidden = true;
    empty.hidden = false;
    return;
  }

  const daySlice = selectPhoneTelemetryDay(state.dataset, state.selectedDay);
  const insights = calculateDailyTelemetryInsights(daySlice);
  renderInsights(daySlice, insights);
}

async function parseImportedFiles(files) {
  const datasets = await Promise.all(
    files.map(async (file) => {
      const text = await file.text();
      return parsePhoneTelemetryJsonText(text, { sourceName: file.name });
    })
  );
  return mergePhoneTelemetryExports(datasets.flatMap((dataset) => dataset.exports));
}

async function loadSampleData() {
  const datasets = await Promise.all(
    SAMPLE_FILES.map(async (path) => {
      const response = await fetch(path, { cache: 'no-store' });
      if (!response.ok) {
        throw new Error(`Failed to load sample file: ${path}`);
      }
      const text = await response.text();
      return parsePhoneTelemetryJsonText(text, { sourceName: path });
    })
  );
  return mergePhoneTelemetryExports(datasets.flatMap((dataset) => dataset.exports));
}

function applyDataset(dataset, sourceLabel) {
  state.dataset = dataset;
  state.selectedDay = dataset.availableDays[0] || '';
  state.sourceLabel = sourceLabel;
  updateDaySelect(dataset, state.selectedDay);
  setError('');
  renderWidget();
}

function wireEvents() {
  const importButton = $('pt-import-btn');
  const loadSampleButton = $('pt-load-sample');
  const fileInput = $('pt-file-input');
  const daySelect = $('pt-day-select');

  importButton?.addEventListener('click', () => fileInput?.click());

  loadSampleButton?.addEventListener('click', async () => {
    setError('');
    setStatus('Loading sample telemetry...', 'Reading local mock exports');
    try {
      const dataset = await loadSampleData();
      applyDataset(dataset, 'Local sample telemetry');
    } catch (error) {
      setError(error?.message || 'Failed to load sample telemetry');
      setStatus('Sample load failed', 'Check the mock files in data/phone-telemetry/');
    }
  });

  fileInput?.addEventListener('change', async () => {
    const files = [...(fileInput.files || [])];
    if (!files.length) return;
    setError('');
    setStatus(`Importing ${files.length} file(s)...`, 'Validating schema and merging records');
    try {
      const dataset = await parseImportedFiles(files);
      applyDataset(dataset, `${files.length} imported JSON file(s)`);
    } catch (error) {
      setError(error?.message || 'Failed to parse telemetry files');
      setStatus('Import failed', 'See error details below.');
    } finally {
      fileInput.value = '';
    }
  });

  daySelect?.addEventListener('change', () => {
    state.selectedDay = daySelect.value;
    renderWidget();
  });
}

onDomReady(() => {
  if (!$('phone-telemetry-card')) return;
  setSchemaPill();
  setStatus(
    'No telemetry imported',
    'Import one or more daily JSON exports from the Android telemetry app.'
  );
  wireEvents();
  renderWidget();
});
