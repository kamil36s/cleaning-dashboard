package com.cleaningdashboard.phonetelemetry.export

import kotlinx.serialization.Serializable

@Serializable
data class PhoneTelemetryExportFile(
    val exportKind: String = "phoneTelemetryExport",
    val schemaVersion: String = "1.0.0",
    val exportedAt: String,
    val timezone: String,
    val device: DeviceMetadata,
    val privacy: PrivacyMetadata,
    val dayRange: DayRange,
    val appUsageSessions: List<AppUsageSessionExport>,
    val phoneSessions: List<PhoneSessionExport>,
    val notificationEvents: List<NotificationEventExport>,
    val dailyAggregates: List<DailyAggregateExport>,
)

@Serializable
data class DeviceMetadata(
    val deviceId: String,
    val deviceLabel: String,
    val manufacturer: String,
    val model: String,
    val sdkInt: Int,
    val osVersion: String,
    val appVersionName: String,
    val appVersionCode: Long,
)

@Serializable
data class PrivacyMetadata(
    val storeNotificationText: Boolean,
    val notificationTextMode: String,
)

@Serializable
data class DayRange(
    val startDay: String,
    val endDay: String,
)

@Serializable
data class AppUsageSessionExport(
    val id: String,
    val day: String,
    val appPackage: String,
    val appLabel: String,
    val sessionStart: String,
    val sessionEnd: String,
    val durationSeconds: Long,
    val category: String,
    val unlockSessionId: String?,
)

@Serializable
data class PhoneSessionExport(
    val id: String,
    val day: String,
    val screenUnlockTime: String,
    val screenLockTime: String,
    val durationSeconds: Long,
)

@Serializable
data class NotificationEventExport(
    val id: String,
    val day: String,
    val timestamp: String,
    val sourceAppPackage: String,
    val sourceAppLabel: String,
    val senderOrThreadTitle: String?,
    val conversationId: String?,
    val previewAvailable: Boolean,
    val messageCount: Int,
    val isGroup: Boolean,
    val eventSource: String,
    val messageLike: Boolean,
    val rawTitle: String?,
    val rawText: String?,
)

@Serializable
data class DailyAggregateExport(
    val day: String,
    val totalPhoneMinutes: Long,
    val unlockCount: Int,
    val notificationCount: Int,
    val messageLikeNotificationCount: Int,
    val appSwitchCount: Int,
    val nightUsageMinutes: Long,
    val topApps: List<TopAppAggregateExport>,
    val topContactsOrThreads: List<TopContactAggregateExport>,
)

@Serializable
data class TopAppAggregateExport(
    val appPackage: String,
    val appLabel: String,
    val durationSeconds: Long,
    val sessionCount: Int,
)

@Serializable
data class TopContactAggregateExport(
    val label: String,
    val conversationId: String?,
    val messageLikeCount: Int,
    val sourceAppPackage: String,
    val sourceAppLabel: String,
)
