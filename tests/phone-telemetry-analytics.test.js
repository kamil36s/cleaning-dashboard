import { describe, expect, it } from 'vitest';
import {
  buildHourlyUsageHistogram,
  buildTopAppsByDuration,
  calculateDailyTelemetryInsights,
  detectMessageBursts,
} from '../js/phone-telemetry/analytics.js';

const dayData = {
  day: '2026-03-14',
  dailyAggregate: null,
  phoneSessions: [
    {
      id: 'unlock-1',
      day: '2026-03-14',
      screenUnlockTime: '2026-03-14T06:00:00+01:00',
      screenLockTime: '2026-03-14T06:10:00+01:00',
      durationSeconds: 600,
    },
    {
      id: 'unlock-2',
      day: '2026-03-14',
      screenUnlockTime: '2026-03-14T12:00:00+01:00',
      screenLockTime: '2026-03-14T12:06:00+01:00',
      durationSeconds: 360,
    },
  ],
  appUsageSessions: [
    {
      id: 'app-1',
      day: '2026-03-14',
      appPackage: 'com.whatsapp',
      appLabel: 'WhatsApp',
      sessionStart: '2026-03-14T06:00:00+01:00',
      sessionEnd: '2026-03-14T06:04:00+01:00',
      durationSeconds: 240,
      category: 'messaging',
      unlockSessionId: 'unlock-1',
    },
    {
      id: 'app-2',
      day: '2026-03-14',
      appPackage: 'com.android.chrome',
      appLabel: 'Chrome',
      sessionStart: '2026-03-14T06:04:00+01:00',
      sessionEnd: '2026-03-14T06:10:00+01:00',
      durationSeconds: 360,
      category: 'browsing',
      unlockSessionId: 'unlock-1',
    },
    {
      id: 'app-3',
      day: '2026-03-14',
      appPackage: 'com.whatsapp',
      appLabel: 'WhatsApp',
      sessionStart: '2026-03-14T12:00:00+01:00',
      sessionEnd: '2026-03-14T12:06:00+01:00',
      durationSeconds: 360,
      category: 'messaging',
      unlockSessionId: 'unlock-2',
    },
  ],
  notificationEvents: [
    {
      id: 'notif-1',
      day: '2026-03-14',
      timestamp: '2026-03-14T05:58:00+01:00',
      sourceAppPackage: 'com.whatsapp',
      sourceAppLabel: 'WhatsApp',
      senderOrThreadTitle: 'Alex',
      conversationId: 'wa:alex',
      previewAvailable: true,
      messageCount: 1,
      isGroup: false,
      eventSource: 'notification',
      messageLike: true,
      rawTitle: 'Alex',
      rawText: 'Hi',
    },
    {
      id: 'notif-2',
      day: '2026-03-14',
      timestamp: '2026-03-14T12:00:00+01:00',
      sourceAppPackage: 'com.whatsapp',
      sourceAppLabel: 'WhatsApp',
      senderOrThreadTitle: 'Alex',
      conversationId: 'wa:alex',
      previewAvailable: true,
      messageCount: 1,
      isGroup: false,
      eventSource: 'notification',
      messageLike: true,
      rawTitle: 'Alex',
      rawText: 'Ping',
    },
    {
      id: 'notif-3',
      day: '2026-03-14',
      timestamp: '2026-03-14T12:01:00+01:00',
      sourceAppPackage: 'com.whatsapp',
      sourceAppLabel: 'WhatsApp',
      senderOrThreadTitle: 'Alex',
      conversationId: 'wa:alex',
      previewAvailable: true,
      messageCount: 1,
      isGroup: false,
      eventSource: 'notification',
      messageLike: true,
      rawTitle: 'Alex',
      rawText: 'Ping',
    },
    {
      id: 'notif-4',
      day: '2026-03-14',
      timestamp: '2026-03-14T12:02:00+01:00',
      sourceAppPackage: 'com.whatsapp',
      sourceAppLabel: 'WhatsApp',
      senderOrThreadTitle: 'Alex',
      conversationId: 'wa:alex',
      previewAvailable: true,
      messageCount: 1,
      isGroup: false,
      eventSource: 'notification',
      messageLike: true,
      rawTitle: 'Alex',
      rawText: 'Ping',
    },
    {
      id: 'notif-5',
      day: '2026-03-14',
      timestamp: '2026-03-14T12:03:00+01:00',
      sourceAppPackage: 'com.whatsapp',
      sourceAppLabel: 'WhatsApp',
      senderOrThreadTitle: 'Alex',
      conversationId: 'wa:alex',
      previewAvailable: true,
      messageCount: 1,
      isGroup: false,
      eventSource: 'notification',
      messageLike: true,
      rawTitle: 'Alex',
      rawText: 'Ping',
    },
    {
      id: 'notif-6',
      day: '2026-03-14',
      timestamp: '2026-03-14T12:04:00+01:00',
      sourceAppPackage: 'com.whatsapp',
      sourceAppLabel: 'WhatsApp',
      senderOrThreadTitle: 'Alex',
      conversationId: 'wa:alex',
      previewAvailable: true,
      messageCount: 1,
      isGroup: false,
      eventSource: 'notification',
      messageLike: true,
      rawTitle: 'Alex',
      rawText: 'Ping',
    },
  ],
};

describe('Phone telemetry analytics', () => {
  it('builds hourly usage buckets in seconds and minutes', () => {
    const hourly = buildHourlyUsageHistogram(dayData.phoneSessions, '2026-03-14');

    expect(hourly[6].minutes).toBe(10);
    expect(hourly[12].minutes).toBe(6);
  });

  it('builds top apps by duration', () => {
    const topApps = buildTopAppsByDuration(dayData.appUsageSessions);

    expect(topApps[0].appLabel).toBe('WhatsApp');
    expect(topApps[0].durationSeconds).toBe(600);
  });

  it('detects message bursts in a 10 minute window', () => {
    const bursts = detectMessageBursts(dayData.notificationEvents);

    expect(bursts).toHaveLength(1);
    expect(bursts[0].count).toBe(5);
  });

  it('calculates daily insights and derived metrics', () => {
    const insights = calculateDailyTelemetryInsights(dayData);

    expect(insights.core.totalPhoneMinutes).toBe(16);
    expect(insights.core.unlockCount).toBe(2);
    expect(insights.core.appSwitchCount).toBe(1);
    expect(insights.messaging.totalMessageLikeNotificationCount).toBe(6);
    expect(insights.messaging.messageBursts).toHaveLength(1);
    expect(insights.synthetic.reactionProxy.matches).toBe(2);
  });
});
