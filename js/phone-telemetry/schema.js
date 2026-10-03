export const PHONE_TELEMETRY_EXPORT_KIND = 'phoneTelemetryExport';
export const PHONE_TELEMETRY_SCHEMA_VERSION = '1.0.0';
export const SUPPORTED_PHONE_TELEMETRY_SCHEMA_VERSIONS = new Set([
  PHONE_TELEMETRY_SCHEMA_VERSION,
]);

// Night usage is counted across the late evening and early morning window.
export const NIGHT_WINDOW = {
  startHour: 22,
  endHour: 6,
};

export const SOCIAL_MEDIA_CATEGORIES = new Set([
  'social',
  'messaging',
  'media',
  'video',
  'entertainment',
]);

export function isSupportedPhoneTelemetrySchemaVersion(value) {
  return SUPPORTED_PHONE_TELEMETRY_SCHEMA_VERSIONS.has(String(value || ''));
}

export function isMessageLikeNotification(event) {
  return Boolean(event?.messageLike);
}

export function getPhoneTelemetrySchemaLabel() {
  return `v${PHONE_TELEMETRY_SCHEMA_VERSION}`;
}
