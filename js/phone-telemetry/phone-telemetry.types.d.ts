export type TelemetrySchemaVersion = '1.0.0';
export type TelemetryExportKind = 'phoneTelemetryExport';
export type NotificationTextMode = 'raw' | 'redacted' | 'disabled';

export interface PhoneTelemetryDeviceMetadata {
  deviceId: string;
  deviceLabel: string;
  manufacturer: string;
  model: string;
  sdkInt: number;
  osVersion: string;
  appVersionName: string;
  appVersionCode: number;
}

export interface PhoneTelemetryPrivacySettings {
  storeNotificationText: boolean;
  notificationTextMode: NotificationTextMode;
}

export interface PhoneTelemetryDayRange {
  startDay: string;
  endDay: string;
}

export interface AppUsageSessionRecord {
  id: string;
  day: string;
  appPackage: string;
  appLabel: string;
  sessionStart: string;
  sessionEnd: string;
  durationSeconds: number;
  category: string;
  unlockSessionId?: string | null;
}

export interface PhoneSessionRecord {
  id: string;
  day: string;
  screenUnlockTime: string;
  screenLockTime: string;
  durationSeconds: number;
}

export interface NotificationEventRecord {
  id: string;
  day: string;
  timestamp: string;
  sourceAppPackage: string;
  sourceAppLabel: string;
  senderOrThreadTitle?: string | null;
  conversationId?: string | null;
  previewAvailable: boolean;
  messageCount: number;
  isGroup?: boolean | null;
  eventSource: 'notification';
  messageLike: boolean;
  rawTitle?: string | null;
  rawText?: string | null;
}

export interface DailyTopAppAggregate {
  appPackage: string;
  appLabel: string;
  durationSeconds: number;
  sessionCount: number;
}

export interface DailyTopContactAggregate {
  label: string;
  conversationId?: string | null;
  messageLikeCount: number;
  sourceAppPackage: string;
  sourceAppLabel: string;
}

export interface PhoneTelemetryDailyAggregate {
  day: string;
  totalPhoneMinutes: number;
  unlockCount: number;
  notificationCount: number;
  messageLikeNotificationCount: number;
  appSwitchCount: number;
  nightUsageMinutes: number;
  topApps: DailyTopAppAggregate[];
  topContactsOrThreads: DailyTopContactAggregate[];
}

export interface PhoneTelemetryExport {
  exportKind: TelemetryExportKind;
  schemaVersion: TelemetrySchemaVersion;
  exportedAt: string;
  timezone: string;
  device: PhoneTelemetryDeviceMetadata;
  privacy: PhoneTelemetryPrivacySettings;
  dayRange: PhoneTelemetryDayRange;
  appUsageSessions: AppUsageSessionRecord[];
  phoneSessions: PhoneSessionRecord[];
  notificationEvents: NotificationEventRecord[];
  dailyAggregates: PhoneTelemetryDailyAggregate[];
}
