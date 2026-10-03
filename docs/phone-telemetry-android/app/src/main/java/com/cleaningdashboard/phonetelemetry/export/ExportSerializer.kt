package com.cleaningdashboard.phonetelemetry.export

import android.content.Context
import android.os.Build
import com.cleaningdashboard.phonetelemetry.data.local.AppUsageSessionEntity
import com.cleaningdashboard.phonetelemetry.data.local.NotificationEventEntity
import com.cleaningdashboard.phonetelemetry.data.local.PhoneSessionEntity
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

class ExportSerializer(
    private val context: Context,
) {
    private val json = Json {
        prettyPrint = true
        encodeDefaults = true
        explicitNulls = true
    }

    fun buildDailyExport(
        day: String,
        appUsageSessions: List<AppUsageSessionEntity>,
        phoneSessions: List<PhoneSessionEntity>,
        notificationEvents: List<NotificationEventEntity>,
        storeNotificationText: Boolean = true,
    ): PhoneTelemetryExportFile {
        val topApps = appUsageSessions
            .groupBy { it.appPackage }
            .map { (_, items) ->
                TopAppAggregateExport(
                    appPackage = items.first().appPackage,
                    appLabel = items.first().appLabel,
                    durationSeconds = items.sumOf { it.durationSeconds },
                    sessionCount = items.size,
                )
            }
            .sortedByDescending { it.durationSeconds }
            .take(5)

        val topContacts = notificationEvents
            .filter { it.messageLike }
            .groupBy { it.conversationId ?: it.senderOrThreadTitle ?: it.sourceAppPackage }
            .map { (_, items) ->
                TopContactAggregateExport(
                    label = items.first().senderOrThreadTitle ?: items.first().sourceAppLabel,
                    conversationId = items.first().conversationId,
                    messageLikeCount = items.sumOf { maxOf(1, it.messageCount) },
                    sourceAppPackage = items.first().sourceAppPackage,
                    sourceAppLabel = items.first().sourceAppLabel,
                )
            }
            .sortedByDescending { it.messageLikeCount }
            .take(5)

        val aggregate = DailyAggregateExport(
            day = day,
            totalPhoneMinutes = phoneSessions.sumOf { it.durationSeconds } / 60,
            unlockCount = phoneSessions.size,
            notificationCount = notificationEvents.size,
            messageLikeNotificationCount = notificationEvents.count { it.messageLike },
            appSwitchCount = calculateAppSwitchCount(appUsageSessions),
            nightUsageMinutes = calculateNightUsageMinutes(phoneSessions),
            topApps = topApps,
            topContactsOrThreads = topContacts,
        )

        return PhoneTelemetryExportFile(
            exportedAt = nowIso(),
            timezone = ZoneId.systemDefault().id,
            device = buildDeviceMetadata(),
            privacy = PrivacyMetadata(
                storeNotificationText = storeNotificationText,
                notificationTextMode = if (storeNotificationText) "raw" else "disabled",
            ),
            dayRange = DayRange(startDay = day, endDay = day),
            appUsageSessions = appUsageSessions.map {
                AppUsageSessionExport(
                    id = it.id,
                    day = it.day,
                    appPackage = it.appPackage,
                    appLabel = it.appLabel,
                    sessionStart = it.sessionStart,
                    sessionEnd = it.sessionEnd,
                    durationSeconds = it.durationSeconds,
                    category = it.category,
                    unlockSessionId = it.unlockSessionId,
                )
            },
            phoneSessions = phoneSessions.map {
                PhoneSessionExport(
                    id = it.id,
                    day = it.day,
                    screenUnlockTime = it.screenUnlockTime,
                    screenLockTime = it.screenLockTime,
                    durationSeconds = it.durationSeconds,
                )
            },
            notificationEvents = notificationEvents.map {
                NotificationEventExport(
                    id = it.id,
                    day = it.day,
                    timestamp = it.timestamp,
                    sourceAppPackage = it.sourceAppPackage,
                    sourceAppLabel = it.sourceAppLabel,
                    senderOrThreadTitle = it.senderOrThreadTitle,
                    conversationId = it.conversationId,
                    previewAvailable = it.previewAvailable,
                    messageCount = it.messageCount,
                    isGroup = it.isGroup,
                    eventSource = it.eventSource,
                    messageLike = it.messageLike,
                    rawTitle = if (storeNotificationText) it.rawTitle else null,
                    rawText = if (storeNotificationText) it.rawText else null,
                )
            },
            dailyAggregates = listOf(aggregate),
        )
    }

    fun serialize(exportFile: PhoneTelemetryExportFile): String {
        return json.encodeToString(exportFile)
    }

    private fun buildDeviceMetadata(): DeviceMetadata {
        val packageInfo = context.packageManager.getPackageInfo(context.packageName, 0)
        val versionCode = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            packageInfo.longVersionCode
        } else {
            @Suppress("DEPRECATION")
            packageInfo.versionCode.toLong()
        }

        return DeviceMetadata(
            deviceId = "${Build.MANUFACTURER}:${Build.MODEL}",
            deviceLabel = Build.MODEL,
            manufacturer = Build.MANUFACTURER,
            model = Build.MODEL,
            sdkInt = Build.VERSION.SDK_INT,
            osVersion = Build.VERSION.RELEASE ?: "unknown",
            appVersionName = packageInfo.versionName ?: "0.0.0",
            appVersionCode = versionCode,
        )
    }

    private fun calculateAppSwitchCount(appUsageSessions: List<AppUsageSessionEntity>): Int {
        val sorted = appUsageSessions.sortedBy { it.sessionStart }
        var switches = 0
        for (index in 1 until sorted.size) {
            val previous = sorted[index - 1]
            val current = sorted[index]
            val sameUnlock = previous.unlockSessionId != null &&
                previous.unlockSessionId == current.unlockSessionId
            if (sameUnlock && previous.appPackage != current.appPackage) {
                switches += 1
            }
        }
        return switches
    }

    private fun calculateNightUsageMinutes(phoneSessions: List<PhoneSessionEntity>): Long {
        return phoneSessions.sumOf { session ->
            val hour = runCatching { Instant.parse(session.screenUnlockTime).atZone(ZoneId.systemDefault()).hour }
                .getOrDefault(12)
            if (hour >= 22 || hour < 6) session.durationSeconds / 60 else 0
        }
    }

    private fun nowIso(): String {
        return Instant.now()
            .atZone(ZoneId.systemDefault())
            .format(DateTimeFormatter.ISO_OFFSET_DATE_TIME)
    }
}
