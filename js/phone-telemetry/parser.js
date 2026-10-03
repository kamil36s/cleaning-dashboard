import {
  PHONE_TELEMETRY_EXPORT_KIND,
  PHONE_TELEMETRY_SCHEMA_VERSION,
  isSupportedPhoneTelemetrySchemaVersion,
} from './schema.js';

function isObject(value) {
  return value != null && typeof value === 'object' && !Array.isArray(value);
}

function ensureObject(value, label) {
  if (!isObject(value)) {
    throw new Error(`${label} must be an object`);
  }
  return value;
}

function ensureString(value, fallback = '') {
  if (value == null) return fallback;
  return String(value);
}

function ensureNumber(value, fallback = 0) {
  const out = Number(value);
  return Number.isFinite(out) ? out : fallback;
}

function ensureBoolean(value, fallback = false) {
  if (typeof value === 'boolean') return value;
  if (value === 'true') return true;
  if (value === 'false') return false;
  return fallback;
}

function toDayKey(explicitDay, timestampValue) {
  const rawDay = ensureString(explicitDay).trim();
  if (rawDay) return rawDay;

  const ts = ensureString(timestampValue).trim();
  if (!ts) return '';
  const match = ts.match(/^(\d{4}-\d{2}-\d{2})/);
  return match ? match[1] : '';
}

function uniqueBy(items, keyFn) {
  const map = new Map();
  for (const item of items) {
    const key = keyFn(item);
    if (!map.has(key)) {
      map.set(key, item);
    }
  }
  return [...map.values()];
}

function sortByTimestamp(items, key) {
  return items
    .slice()
    .sort((a, b) => {
      const aTs = new Date(a[key]).getTime();
      const bTs = new Date(b[key]).getTime();
      return aTs - bTs;
    });
}

function normalizeDevice(device) {
  const safe = ensureObject(device || {}, 'device');
  return {
    deviceId: ensureString(safe.deviceId || safe.deviceLabel || 'unknown-device'),
    deviceLabel: ensureString(safe.deviceLabel || safe.model || 'Unknown device'),
    manufacturer: ensureString(safe.manufacturer || 'Unknown'),
    model: ensureString(safe.model || 'Unknown'),
    sdkInt: ensureNumber(safe.sdkInt, 0),
    osVersion: ensureString(safe.osVersion || 'unknown'),
    appVersionName: ensureString(safe.appVersionName || '0.0.0'),
    appVersionCode: ensureNumber(safe.appVersionCode, 0),
  };
}

function normalizePrivacy(privacy) {
  const safe = ensureObject(privacy || {}, 'privacy');
  return {
    storeNotificationText: ensureBoolean(safe.storeNotificationText, true),
    notificationTextMode: ensureString(safe.notificationTextMode || 'raw'),
  };
}

function normalizeAppUsageSession(record, index) {
  const safe = ensureObject(record || {}, `appUsageSessions[${index}]`);
  return {
    id: ensureString(safe.id || `app-session-${index + 1}`),
    day: toDayKey(safe.day, safe.sessionStart),
    appPackage: ensureString(safe.appPackage || 'unknown.package'),
    appLabel: ensureString(safe.appLabel || safe.appPackage || 'Unknown app'),
    sessionStart: ensureString(safe.sessionStart),
    sessionEnd: ensureString(safe.sessionEnd),
    durationSeconds: ensureNumber(safe.durationSeconds, 0),
    category: ensureString(safe.category || 'unknown'),
    unlockSessionId: ensureString(safe.unlockSessionId || ''),
  };
}

function normalizePhoneSession(record, index) {
  const safe = ensureObject(record || {}, `phoneSessions[${index}]`);
  return {
    id: ensureString(safe.id || `phone-session-${index + 1}`),
    day: toDayKey(safe.day, safe.screenUnlockTime),
    screenUnlockTime: ensureString(safe.screenUnlockTime),
    screenLockTime: ensureString(safe.screenLockTime),
    durationSeconds: ensureNumber(safe.durationSeconds, 0),
  };
}

function normalizeNotificationEvent(record, index) {
  const safe = ensureObject(record || {}, `notificationEvents[${index}]`);
  return {
    id: ensureString(safe.id || `notification-${index + 1}`),
    day: toDayKey(safe.day, safe.timestamp),
    timestamp: ensureString(safe.timestamp),
    sourceAppPackage: ensureString(safe.sourceAppPackage || 'unknown.package'),
    sourceAppLabel: ensureString(safe.sourceAppLabel || safe.sourceAppPackage || 'Unknown app'),
    senderOrThreadTitle: ensureString(safe.senderOrThreadTitle || ''),
    conversationId: ensureString(safe.conversationId || ''),
    previewAvailable: ensureBoolean(safe.previewAvailable, false),
    messageCount: Math.max(1, ensureNumber(safe.messageCount, 1)),
    isGroup: ensureBoolean(safe.isGroup, false),
    eventSource: 'notification',
    messageLike: ensureBoolean(safe.messageLike, false),
    rawTitle: safe.rawTitle == null ? null : ensureString(safe.rawTitle),
    rawText: safe.rawText == null ? null : ensureString(safe.rawText),
  };
}

function normalizeDailyAggregate(record, index) {
  const safe = ensureObject(record || {}, `dailyAggregates[${index}]`);
  const topApps = Array.isArray(safe.topApps) ? safe.topApps : [];
  const topContactsOrThreads = Array.isArray(safe.topContactsOrThreads)
    ? safe.topContactsOrThreads
    : [];

  return {
    day: ensureString(safe.day),
    totalPhoneMinutes: ensureNumber(safe.totalPhoneMinutes, 0),
    unlockCount: ensureNumber(safe.unlockCount, 0),
    notificationCount: ensureNumber(safe.notificationCount, 0),
    messageLikeNotificationCount: ensureNumber(safe.messageLikeNotificationCount, 0),
    appSwitchCount: ensureNumber(safe.appSwitchCount, 0),
    nightUsageMinutes: ensureNumber(safe.nightUsageMinutes, 0),
    topApps: topApps.map((item, itemIndex) => ({
      appPackage: ensureString(item?.appPackage || `unknown.package.${itemIndex + 1}`),
      appLabel: ensureString(item?.appLabel || item?.appPackage || 'Unknown app'),
      durationSeconds: ensureNumber(item?.durationSeconds, 0),
      sessionCount: ensureNumber(item?.sessionCount, 0),
    })),
    topContactsOrThreads: topContactsOrThreads.map((item) => ({
      label: ensureString(item?.label || 'Unknown thread'),
      conversationId: ensureString(item?.conversationId || ''),
      messageLikeCount: ensureNumber(item?.messageLikeCount, 0),
      sourceAppPackage: ensureString(item?.sourceAppPackage || 'unknown.package'),
      sourceAppLabel: ensureString(item?.sourceAppLabel || item?.sourceAppPackage || 'Unknown app'),
    })),
  };
}

function normalizeExport(rawExport, options = {}) {
  const safe = ensureObject(rawExport, 'telemetry export');
  const schemaVersion = ensureString(safe.schemaVersion);

  if (!isSupportedPhoneTelemetrySchemaVersion(schemaVersion)) {
    throw new Error(
      `Unsupported phone telemetry schema version "${schemaVersion}". Supported: ${PHONE_TELEMETRY_SCHEMA_VERSION}`
    );
  }

  const exportKind = ensureString(safe.exportKind || PHONE_TELEMETRY_EXPORT_KIND);
  if (exportKind !== PHONE_TELEMETRY_EXPORT_KIND) {
    throw new Error(`Unsupported exportKind "${exportKind}"`);
  }

  return {
    exportKind,
    schemaVersion,
    exportedAt: ensureString(safe.exportedAt),
    timezone: ensureString(safe.timezone || 'UTC'),
    sourceName: ensureString(options.sourceName || 'manual-import'),
    device: normalizeDevice(safe.device),
    privacy: normalizePrivacy(safe.privacy),
    dayRange: {
      startDay: ensureString(safe.dayRange?.startDay || ''),
      endDay: ensureString(safe.dayRange?.endDay || ''),
    },
    appUsageSessions: sortByTimestamp(
      (Array.isArray(safe.appUsageSessions) ? safe.appUsageSessions : []).map(normalizeAppUsageSession),
      'sessionStart'
    ),
    phoneSessions: sortByTimestamp(
      (Array.isArray(safe.phoneSessions) ? safe.phoneSessions : []).map(normalizePhoneSession),
      'screenUnlockTime'
    ),
    notificationEvents: sortByTimestamp(
      (Array.isArray(safe.notificationEvents) ? safe.notificationEvents : []).map(normalizeNotificationEvent),
      'timestamp'
    ),
    dailyAggregates: (Array.isArray(safe.dailyAggregates) ? safe.dailyAggregates : []).map(normalizeDailyAggregate),
  };
}

export function mergePhoneTelemetryExports(exports) {
  const safeExports = Array.isArray(exports) ? exports : [];
  const appUsageSessions = uniqueBy(
    safeExports.flatMap((item) => item.appUsageSessions),
    (item) => item.id
  );
  const phoneSessions = uniqueBy(
    safeExports.flatMap((item) => item.phoneSessions),
    (item) => item.id
  );
  const notificationEvents = uniqueBy(
    safeExports.flatMap((item) => item.notificationEvents),
    (item) => item.id
  );
  const dailyAggregates = uniqueBy(
    safeExports.flatMap((item) => item.dailyAggregates),
    (item) => item.day
  );
  const availableDays = [...new Set([
    ...appUsageSessions.map((item) => item.day),
    ...phoneSessions.map((item) => item.day),
    ...notificationEvents.map((item) => item.day),
    ...dailyAggregates.map((aggregate) => aggregate.day),
  ])]
    .filter(Boolean)
    .sort((a, b) => b.localeCompare(a));
  const devices = uniqueBy(
    safeExports.map((item) => item.device),
    (item) => item.deviceId
  );
  const timezone = safeExports[0]?.timezone || 'UTC';

  return {
    schemaVersion: PHONE_TELEMETRY_SCHEMA_VERSION,
    exportCount: safeExports.length,
    exports: safeExports,
    timezone,
    devices,
    availableDays,
    appUsageSessions: sortByTimestamp(appUsageSessions, 'sessionStart'),
    phoneSessions: sortByTimestamp(phoneSessions, 'screenUnlockTime'),
    notificationEvents: sortByTimestamp(notificationEvents, 'timestamp'),
    dailyAggregates: dailyAggregates.sort((a, b) => b.day.localeCompare(a.day)),
  };
}

export function parsePhoneTelemetrySource(rawSource, options = {}) {
  if (typeof rawSource === 'string') {
    return parsePhoneTelemetryJsonText(rawSource, options);
  }

  if (Array.isArray(rawSource)) {
    return mergePhoneTelemetryExports(
      rawSource.map((item, index) =>
        normalizeExport(item, {
          sourceName: options.sourceName || `array-item-${index + 1}`,
        })
      )
    );
  }

  return mergePhoneTelemetryExports([
    normalizeExport(rawSource, options),
  ]);
}

export function parsePhoneTelemetryJsonText(text, options = {}) {
  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch (error) {
    throw new Error(`Invalid JSON in ${options.sourceName || 'telemetry file'}`);
  }
  return parsePhoneTelemetrySource(parsed, options);
}

export function selectPhoneTelemetryDay(dataset, dayKey) {
  const safeDataset = dataset || mergePhoneTelemetryExports([]);
  const selectedDay = ensureString(dayKey || safeDataset.availableDays[0] || '');
  const dailyAggregate = safeDataset.dailyAggregates.find((item) => item.day === selectedDay) || null;

  return {
    day: selectedDay,
    timezone: safeDataset.timezone,
    device: safeDataset.devices[0] || null,
    dailyAggregate,
    appUsageSessions: safeDataset.appUsageSessions.filter((item) => item.day === selectedDay),
    phoneSessions: safeDataset.phoneSessions.filter((item) => item.day === selectedDay),
    notificationEvents: safeDataset.notificationEvents.filter((item) => item.day === selectedDay),
  };
}
