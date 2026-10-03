import {
  NIGHT_WINDOW,
  SOCIAL_MEDIA_CATEGORIES,
  isMessageLikeNotification,
} from './schema.js';

const DAY_SECONDS = 24 * 60 * 60;

function clamp01(value) {
  return Math.min(1, Math.max(0, value));
}

function toDate(value) {
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function buildDayBounds(dayKey) {
  const start = toDate(`${dayKey}T00:00:00`);
  const end = toDate(`${dayKey}T24:00:00`);
  return { start, end };
}

function clipIntervalToDay(start, end, dayKey) {
  const rangeStart = toDate(start);
  const rangeEnd = toDate(end);
  const bounds = buildDayBounds(dayKey);
  if (!rangeStart || !rangeEnd || !bounds.start || !bounds.end) return null;
  const clippedStart = Math.max(rangeStart.getTime(), bounds.start.getTime());
  const clippedEnd = Math.min(rangeEnd.getTime(), bounds.end.getTime());
  if (clippedEnd <= clippedStart) return null;
  return {
    start: new Date(clippedStart),
    end: new Date(clippedEnd),
    seconds: Math.round((clippedEnd - clippedStart) / 1000),
  };
}

function buildHourlyBuckets() {
  return Array.from({ length: 24 }, (_, hour) => ({
    hour,
    label: String(hour).padStart(2, '0'),
    value: 0,
  }));
}

function addIntervalToBuckets(buckets, start, end, dayKey) {
  const clipped = clipIntervalToDay(start, end, dayKey);
  if (!clipped) return;

  let cursor = clipped.start.getTime();
  const endMs = clipped.end.getTime();

  while (cursor < endMs) {
    const cursorDate = new Date(cursor);
    const hour = cursorDate.getHours();
    const hourEnd = new Date(cursorDate);
    hourEnd.setMinutes(59, 59, 999);
    const sliceEnd = Math.min(endMs, hourEnd.getTime() + 1);
    buckets[hour].value += (sliceEnd - cursor) / 1000;
    cursor = sliceEnd;
  }
}

function aggregateBy(items, keyFn, seedFn, reduceFn) {
  const map = new Map();
  for (const item of items) {
    const key = keyFn(item);
    const current = map.get(key) || seedFn(item);
    map.set(key, reduceFn(current, item));
  }
  return [...map.values()];
}

function sumDuration(items) {
  return items.reduce((total, item) => total + (Number(item.durationSeconds) || 0), 0);
}

function getWeightForNotification(event) {
  return Math.max(1, Number(event.messageCount) || 1);
}

function isNightHour(hour) {
  if (NIGHT_WINDOW.startHour < NIGHT_WINDOW.endHour) {
    return hour >= NIGHT_WINDOW.startHour && hour < NIGHT_WINDOW.endHour;
  }
  return hour >= NIGHT_WINDOW.startHour || hour < NIGHT_WINDOW.endHour;
}

export function buildHourlyUsageHistogram(phoneSessions, dayKey) {
  const buckets = buildHourlyBuckets();
  for (const session of phoneSessions || []) {
    addIntervalToBuckets(buckets, session.screenUnlockTime, session.screenLockTime, dayKey);
  }
  return buckets.map((bucket) => ({
    ...bucket,
    minutes: Math.round(bucket.value / 60),
  }));
}

export function buildHourlyNotificationHistogram(notificationEvents, { messageLikeOnly = true } = {}) {
  const buckets = buildHourlyBuckets();
  for (const event of notificationEvents || []) {
    if (messageLikeOnly && !isMessageLikeNotification(event)) continue;
    const date = toDate(event.timestamp);
    if (!date) continue;
    buckets[date.getHours()].value += 1;
  }
  return buckets;
}

export function calculateAppSwitchCount(appUsageSessions) {
  const sorted = (appUsageSessions || [])
    .slice()
    .sort((a, b) => new Date(a.sessionStart).getTime() - new Date(b.sessionStart).getTime());

  let switches = 0;
  for (let index = 1; index < sorted.length; index += 1) {
    const previous = sorted[index - 1];
    const current = sorted[index];
    const sameUnlock =
      previous.unlockSessionId &&
      current.unlockSessionId &&
      previous.unlockSessionId === current.unlockSessionId;
    const canCompare = sameUnlock || (!previous.unlockSessionId && !current.unlockSessionId);
    if (!canCompare) continue;
    if (previous.appPackage !== current.appPackage) {
      switches += 1;
    }
  }
  return switches;
}

export function calculateLongestNoPhoneWindow(phoneSessions, dayKey) {
  const sorted = (phoneSessions || [])
    .slice()
    .sort((a, b) => new Date(a.screenUnlockTime).getTime() - new Date(b.screenUnlockTime).getTime());
  const bounds = buildDayBounds(dayKey);
  if (!bounds.start || !bounds.end) return 0;
  if (!sorted.length) return DAY_SECONDS;

  let longest = 0;
  let previousEnd = bounds.start.getTime();

  for (const session of sorted) {
    const start = toDate(session.screenUnlockTime)?.getTime();
    const end = toDate(session.screenLockTime)?.getTime();
    if (!Number.isFinite(start) || !Number.isFinite(end)) continue;
    longest = Math.max(longest, Math.round((start - previousEnd) / 1000));
    previousEnd = Math.max(previousEnd, end);
  }

  longest = Math.max(longest, Math.round((bounds.end.getTime() - previousEnd) / 1000));
  return Math.max(0, longest);
}

export function buildTopAppsByDuration(appUsageSessions, limit = 5) {
  return aggregateBy(
    appUsageSessions || [],
    (item) => item.appPackage,
    (item) => ({
      appPackage: item.appPackage,
      appLabel: item.appLabel,
      category: item.category,
      durationSeconds: 0,
      sessionCount: 0,
    }),
    (current, item) => ({
      ...current,
      durationSeconds: current.durationSeconds + (Number(item.durationSeconds) || 0),
      sessionCount: current.sessionCount + 1,
    })
  )
    .sort((a, b) => b.durationSeconds - a.durationSeconds || b.sessionCount - a.sessionCount)
    .slice(0, limit);
}

export function buildTopAppsBySessionCount(appUsageSessions, limit = 5) {
  return aggregateBy(
    appUsageSessions || [],
    (item) => item.appPackage,
    (item) => ({
      appPackage: item.appPackage,
      appLabel: item.appLabel,
      category: item.category,
      durationSeconds: 0,
      sessionCount: 0,
    }),
    (current, item) => ({
      ...current,
      durationSeconds: current.durationSeconds + (Number(item.durationSeconds) || 0),
      sessionCount: current.sessionCount + 1,
    })
  )
    .sort((a, b) => b.sessionCount - a.sessionCount || b.durationSeconds - a.durationSeconds)
    .slice(0, limit);
}

export function buildTopMessagingApps(notificationEvents, limit = 5) {
  return aggregateBy(
    (notificationEvents || []).filter(isMessageLikeNotification),
    (item) => item.sourceAppPackage,
    (item) => ({
      sourceAppPackage: item.sourceAppPackage,
      sourceAppLabel: item.sourceAppLabel,
      eventCount: 0,
      messageWeight: 0,
    }),
    (current, item) => ({
      ...current,
      eventCount: current.eventCount + 1,
      messageWeight: current.messageWeight + getWeightForNotification(item),
    })
  )
    .sort((a, b) => b.messageWeight - a.messageWeight || b.eventCount - a.eventCount)
    .slice(0, limit);
}

export function buildTopContacts(notificationEvents, limit = 5) {
  return aggregateBy(
    (notificationEvents || []).filter(isMessageLikeNotification),
    (item) => item.conversationId || item.senderOrThreadTitle || `${item.sourceAppPackage}:unknown`,
    (item) => ({
      label: item.senderOrThreadTitle || item.sourceAppLabel,
      conversationId: item.conversationId || '',
      sourceAppPackage: item.sourceAppPackage,
      sourceAppLabel: item.sourceAppLabel,
      eventCount: 0,
      messageWeight: 0,
    }),
    (current, item) => ({
      ...current,
      eventCount: current.eventCount + 1,
      messageWeight: current.messageWeight + getWeightForNotification(item),
    })
  )
    .sort((a, b) => b.messageWeight - a.messageWeight || b.eventCount - a.eventCount)
    .slice(0, limit);
}

export function detectMessageBursts(notificationEvents, { windowMinutes = 10, threshold = 5 } = {}) {
  const sorted = (notificationEvents || [])
    .filter(isMessageLikeNotification)
    .slice()
    .sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime());

  const bursts = [];
  let startIndex = 0;

  for (let endIndex = 0; endIndex < sorted.length; endIndex += 1) {
    const endTs = toDate(sorted[endIndex].timestamp)?.getTime();
    if (!Number.isFinite(endTs)) continue;

    while (startIndex <= endIndex) {
      const startTs = toDate(sorted[startIndex].timestamp)?.getTime();
      if (!Number.isFinite(startTs)) {
        startIndex += 1;
        continue;
      }
      const diffMinutes = (endTs - startTs) / (60 * 1000);
      if (diffMinutes <= windowMinutes) break;
      startIndex += 1;
    }

    const count = endIndex - startIndex + 1;
    if (count >= threshold) {
      const windowItems = sorted.slice(startIndex, endIndex + 1);
      const topThread = buildTopContacts(windowItems, 1)[0] || null;
      const burstId = `${windowItems[0].id}:${windowItems[windowItems.length - 1].id}`;
      const alreadyRecorded = bursts.some((item) => item.id === burstId);
      if (!alreadyRecorded) {
        bursts.push({
          id: burstId,
          start: windowItems[0].timestamp,
          end: windowItems[windowItems.length - 1].timestamp,
          count,
          topThread,
        });
      }
    }
  }

  return bursts;
}

export function countNightMessaging(notificationEvents) {
  return (notificationEvents || [])
    .filter(isMessageLikeNotification)
    .filter((item) => {
      const date = toDate(item.timestamp);
      return date ? isNightHour(date.getHours()) : false;
    })
    .length;
}

export function calculateReactionProxy(notificationEvents, appUsageSessions, { windowMinutes = 5 } = {}) {
  const notifications = (notificationEvents || [])
    .filter(isMessageLikeNotification)
    .slice()
    .sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime());
  const sessions = (appUsageSessions || [])
    .slice()
    .sort((a, b) => new Date(a.sessionStart).getTime() - new Date(b.sessionStart).getTime());

  if (!notifications.length || !sessions.length) {
    return {
      matches: 0,
      opportunities: notifications.length,
      ratio: null,
    };
  }

  let matches = 0;

  for (const notification of notifications) {
    const notificationTs = toDate(notification.timestamp)?.getTime();
    if (!Number.isFinite(notificationTs)) continue;
    const windowEnd = notificationTs + windowMinutes * 60 * 1000;
    const found = sessions.find((session) => {
      const sessionTs = toDate(session.sessionStart)?.getTime();
      if (!Number.isFinite(sessionTs)) return false;
      if (session.appPackage !== notification.sourceAppPackage) return false;
      return sessionTs >= notificationTs && sessionTs <= windowEnd;
    });
    if (found) matches += 1;
  }

  return {
    matches,
    opportunities: notifications.length,
    ratio: notifications.length ? matches / notifications.length : null,
  };
}

function calculateNightUsageMinutes(phoneSessions, dayKey) {
  const hourly = buildHourlyUsageHistogram(phoneSessions, dayKey);
  const nightSeconds = hourly
    .filter((bucket) => isNightHour(bucket.hour))
    .reduce((total, bucket) => total + bucket.value, 0);
  return Math.round(nightSeconds / 60);
}

function calculateFragmentationIndex({ sessionCount, shortSessionsUnder2m, appSwitchCount, totalPhoneTimeSeconds }) {
  if (!sessionCount || !totalPhoneTimeSeconds) return 0;
  const shortShare = shortSessionsUnder2m / sessionCount;
  const switchesPerSession = appSwitchCount / sessionCount;
  const unlocksPerHour = sessionCount / Math.max(totalPhoneTimeSeconds / 3600, 0.25);
  const score = (
    clamp01(shortShare) * 0.5 +
    clamp01(switchesPerSession / 4) * 0.3 +
    clamp01(unlocksPerHour / 12) * 0.2
  ) * 100;
  return Math.round(score);
}

function calculateSocialMediaTimePercent(appUsageSessions) {
  const total = sumDuration(appUsageSessions || []);
  if (!total) return 0;
  const socialMediaTotal = (appUsageSessions || [])
    .filter((item) => SOCIAL_MEDIA_CATEGORIES.has(String(item.category || '').toLowerCase()))
    .reduce((sum, item) => sum + (Number(item.durationSeconds) || 0), 0);
  return Math.round((socialMediaTotal / total) * 100);
}

function calculateMessagingConcentration(topContacts) {
  const total = (topContacts || []).reduce((sum, item) => sum + (Number(item.messageWeight) || 0), 0);
  if (!total) return 0;
  const hhi = (topContacts || []).reduce((sum, item) => {
    const share = (Number(item.messageWeight) || 0) / total;
    return sum + share * share;
  }, 0);
  return Math.round(hhi * 100) / 100;
}

function calculateMessagingPressureScore({ messageLikeCount, burstCount, nightMessagingCount, uniqueContacts }) {
  const volumeComponent = clamp01(messageLikeCount / 30);
  const burstComponent = clamp01(burstCount / 4);
  const nightComponent = clamp01(nightMessagingCount / 10);
  const spreadComponent = clamp01(uniqueContacts / 15);

  return Math.round(
    (volumeComponent * 0.45 +
      burstComponent * 0.3 +
      nightComponent * 0.15 +
      spreadComponent * 0.1) * 100
  );
}

export function calculateDailyTelemetryInsights(dayData) {
  const phoneSessions = dayData?.phoneSessions || [];
  const appUsageSessions = dayData?.appUsageSessions || [];
  const notificationEvents = dayData?.notificationEvents || [];
  const dailyAggregate = dayData?.dailyAggregate || null;
  const dayKey = dayData?.day || dailyAggregate?.day || '';

  const totalPhoneTimeSeconds = sumDuration(phoneSessions);
  const sessionCount = phoneSessions.length || Number(dailyAggregate?.unlockCount) || 0;
  const unlockCount = phoneSessions.length || Number(dailyAggregate?.unlockCount) || 0;
  const shortSessionsUnder30s = phoneSessions.filter((item) => (Number(item.durationSeconds) || 0) < 30).length;
  const shortSessionsUnder2m = phoneSessions.filter((item) => (Number(item.durationSeconds) || 0) < 120).length;
  const averageSessionDurationSeconds = sessionCount
    ? Math.round(totalPhoneTimeSeconds / sessionCount)
    : 0;
  const appSwitchCount = appUsageSessions.length
    ? calculateAppSwitchCount(appUsageSessions)
    : Number(dailyAggregate?.appSwitchCount) || 0;
  const longestNoPhoneWindowSeconds = dayKey
    ? calculateLongestNoPhoneWindow(phoneSessions, dayKey)
    : 0;
  const topAppsByDuration = appUsageSessions.length
    ? buildTopAppsByDuration(appUsageSessions, 5)
    : (dailyAggregate?.topApps || []).slice(0, 5);
  const topAppsBySessionCount = buildTopAppsBySessionCount(appUsageSessions, 5);
  const topMessagingApps = buildTopMessagingApps(notificationEvents, 5);
  const topContacts = notificationEvents.length
    ? buildTopContacts(notificationEvents, 5)
    : (dailyAggregate?.topContactsOrThreads || []).slice(0, 5).map((item) => ({
        ...item,
        eventCount: Number(item.messageLikeCount) || 0,
        messageWeight: Number(item.messageLikeCount) || 0,
      }));
  const messageBursts = detectMessageBursts(notificationEvents);
  const notificationCount = notificationEvents.length || Number(dailyAggregate?.notificationCount) || 0;
  const messageLikeCount = notificationEvents.filter(isMessageLikeNotification).length
    || Number(dailyAggregate?.messageLikeNotificationCount) || 0;
  const uniqueContacts = new Set(
    topContacts.map((item) => item.conversationId || item.label).filter(Boolean)
  ).size;
  const hourlyUsage = buildHourlyUsageHistogram(phoneSessions, dayKey);
  const hourlyNotifications = buildHourlyNotificationHistogram(notificationEvents, {
    messageLikeOnly: true,
  });
  const topAppDurationSeries = topAppsByDuration.map((item) => ({
    label: item.appLabel,
    value: Number(item.durationSeconds) || 0,
  }));
  const nightUsageMinutes = phoneSessions.length
    ? calculateNightUsageMinutes(phoneSessions, dayKey)
    : Number(dailyAggregate?.nightUsageMinutes) || 0;
  const nightMessagingCount = countNightMessaging(notificationEvents);
  const reactionProxy = calculateReactionProxy(notificationEvents, appUsageSessions);

  const shortSessionRatio = sessionCount ? (shortSessionsUnder2m / sessionCount) * 100 : 0;
  const fragmentationIndex = calculateFragmentationIndex({
    sessionCount,
    shortSessionsUnder2m,
    appSwitchCount,
    totalPhoneTimeSeconds,
  });
  const socialMediaTimePercent = calculateSocialMediaTimePercent(appUsageSessions);
  const messagingConcentrationIndex = calculateMessagingConcentration(topContacts);
  const messagingPressureScore = calculateMessagingPressureScore({
    messageLikeCount,
    burstCount: messageBursts.length,
    nightMessagingCount,
    uniqueContacts,
  });

  return {
    core: {
      totalPhoneTimeSeconds,
      totalPhoneMinutes: Math.round(totalPhoneTimeSeconds / 60),
      unlockCount,
      averageSessionDurationSeconds,
      sessionCount,
      shortSessionsUnder30s,
      shortSessionsUnder2m,
      shortSessionRatio,
      appSwitchCount,
      longestNoPhoneWindowSeconds,
      topAppsByDuration,
      topAppsBySessionCount,
      nightUsageMinutes,
    },
    messaging: {
      totalNotificationCount: notificationCount,
      totalMessageLikeNotificationCount: messageLikeCount,
      uniqueContacts,
      topContacts,
      topMessagingApps,
      messageBursts,
      nightMessagingCount,
      messagingPressureScore,
    },
    synthetic: {
      fragmentationIndex,
      socialMediaTimePercent,
      messagingConcentrationIndex,
      reactionProxy,
    },
    charts: {
      hourlyUsage,
      hourlyNotifications,
      topAppDurationSeries,
    },
  };
}
