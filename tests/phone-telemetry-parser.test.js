import { describe, expect, it } from 'vitest';
import {
  mergePhoneTelemetryExports,
  parsePhoneTelemetrySource,
  selectPhoneTelemetryDay,
} from '../js/phone-telemetry/parser.js';

const sampleExport = {
  exportKind: 'phoneTelemetryExport',
  schemaVersion: '1.0.0',
  exportedAt: '2026-03-15T00:05:00+01:00',
  timezone: 'Europe/Warsaw',
  device: {
    deviceId: 'pixel7-demo',
    deviceLabel: 'Pixel 7',
    manufacturer: 'Google',
    model: 'Pixel 7',
    sdkInt: 34,
    osVersion: '14',
    appVersionName: '0.1.0',
    appVersionCode: 1,
  },
  privacy: {
    storeNotificationText: true,
    notificationTextMode: 'raw',
  },
  dayRange: {
    startDay: '2026-03-14',
    endDay: '2026-03-14',
  },
  appUsageSessions: [
    {
      id: 'app-1',
      day: '2026-03-14',
      appPackage: 'com.whatsapp',
      appLabel: 'WhatsApp',
      sessionStart: '2026-03-14T06:00:00+01:00',
      sessionEnd: '2026-03-14T06:05:00+01:00',
      durationSeconds: 300,
      category: 'messaging',
      unlockSessionId: 'unlock-1',
    },
  ],
  phoneSessions: [
    {
      id: 'unlock-1',
      day: '2026-03-14',
      screenUnlockTime: '2026-03-14T06:00:00+01:00',
      screenLockTime: '2026-03-14T06:06:00+01:00',
      durationSeconds: 360,
    },
  ],
  notificationEvents: [
    {
      id: 'notif-1',
      day: '2026-03-14',
      timestamp: '2026-03-14T06:01:00+01:00',
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
      rawText: 'Hello',
    },
  ],
  dailyAggregates: [
    {
      day: '2026-03-14',
      totalPhoneMinutes: 6,
      unlockCount: 1,
      notificationCount: 1,
      messageLikeNotificationCount: 1,
      appSwitchCount: 0,
      nightUsageMinutes: 0,
      topApps: [],
      topContactsOrThreads: [],
    },
  ],
};

describe('Phone telemetry parser', () => {
  it('parses a valid export object', () => {
    const dataset = parsePhoneTelemetrySource(sampleExport, { sourceName: 'sample' });

    expect(dataset.exportCount).toBe(1);
    expect(dataset.availableDays).toEqual(['2026-03-14']);
    expect(dataset.appUsageSessions[0].appLabel).toBe('WhatsApp');
  });

  it('merges multiple exports and sorts available days descending', () => {
    const older = {
      ...sampleExport,
      appUsageSessions: [],
      phoneSessions: [],
      notificationEvents: [],
      dailyAggregates: [],
      dayRange: { startDay: '2026-03-13', endDay: '2026-03-13' },
      exportedAt: '2026-03-14T00:05:00+01:00',
    };
    older.appUsageSessions = [
      {
        ...sampleExport.appUsageSessions[0],
        id: 'app-older',
        day: '2026-03-13',
        sessionStart: '2026-03-13T06:00:00+01:00',
        sessionEnd: '2026-03-13T06:02:00+01:00',
      },
    ];
    older.phoneSessions = [
      {
        ...sampleExport.phoneSessions[0],
        id: 'unlock-older',
        day: '2026-03-13',
        screenUnlockTime: '2026-03-13T06:00:00+01:00',
        screenLockTime: '2026-03-13T06:03:00+01:00',
      },
    ];

    const dataset = mergePhoneTelemetryExports([
      parsePhoneTelemetrySource(sampleExport).exports[0],
      parsePhoneTelemetrySource(older).exports[0],
    ]);

    expect(dataset.availableDays).toEqual(['2026-03-14', '2026-03-13']);
  });

  it('selects a single day slice', () => {
    const dataset = parsePhoneTelemetrySource(sampleExport);
    const daySlice = selectPhoneTelemetryDay(dataset, '2026-03-14');

    expect(daySlice.day).toBe('2026-03-14');
    expect(daySlice.phoneSessions).toHaveLength(1);
    expect(daySlice.notificationEvents).toHaveLength(1);
  });

  it('rejects unsupported schema versions', () => {
    expect(() =>
      parsePhoneTelemetrySource({
        ...sampleExport,
        schemaVersion: '9.9.9',
      })
    ).toThrow(/Unsupported phone telemetry schema version/);
  });
});
