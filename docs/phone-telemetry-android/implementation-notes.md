# Implementation Notes

## Data collection limits

`UsageStatsManager` and `UsageEvents` can reconstruct a large amount of phone behavior, but not everything:

- app foreground/background transitions are approximate
- some OEMs throttle or reshape usage records
- notification text availability depends on the app and user privacy choices
- "sender" and "conversation" metadata are not guaranteed

The correct approach is to keep uncertainty visible in the schema instead of pretending the data is perfect.

## Recommended day boundary

Use local-device day boundaries:

- start: `00:00:00`
- end: `23:59:59.999`
- timezone: store the device IANA timezone string in every export

That matches how the dashboard date selector and daily aggregates are expected to behave.

## Export cadence

Phase 1 should export once per day:

- target day: usually yesterday
- worker time: shortly after midnight, with retry support
- output directory: `Downloads/CleaningDashboardTelemetry/`

This keeps exports human-inspectable and easy to import.

## Privacy

Phase 1 schema already supports privacy settings:

- raw text stored
- raw text redacted
- raw text disabled

The Android app can start in raw mode but should keep the field and serializer structure ready for later settings UI.
