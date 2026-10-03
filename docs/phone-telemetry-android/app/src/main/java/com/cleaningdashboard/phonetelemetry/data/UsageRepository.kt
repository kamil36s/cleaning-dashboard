package com.cleaningdashboard.phonetelemetry.data

import android.app.usage.UsageEvents
import android.app.usage.UsageStatsManager
import android.content.Context
import android.content.pm.ApplicationInfo
import com.cleaningdashboard.phonetelemetry.data.local.AppUsageSessionEntity
import com.cleaningdashboard.phonetelemetry.data.local.PhoneSessionEntity
import com.cleaningdashboard.phonetelemetry.data.local.TelemetryDatabase
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.format.DateTimeFormatter

class UsageRepository(
    private val context: Context,
) {
    private val usageStatsManager: UsageStatsManager =
        context.getSystemService(UsageStatsManager::class.java)
    private val telemetryDao = TelemetryDatabase.getInstance(context).telemetryDao()

    suspend fun collectAndPersistDay(day: LocalDate) {
        val zone = ZoneId.systemDefault()
        val start = day.atStartOfDay(zone).toInstant()
        val end = day.plusDays(1).atStartOfDay(zone).toInstant()
        val dayKey = day.toString()

        val usageCapture = collectUsageCapture(dayKey, start.toEpochMilli(), end.toEpochMilli())
        telemetryDao.replaceUsageCaptureForDay(
            day = dayKey,
            appUsageSessions = usageCapture.appUsageSessions,
            phoneSessions = usageCapture.phoneSessions,
        )
    }

    private fun collectUsageCapture(
        dayKey: String,
        startMillis: Long,
        endMillis: Long,
    ): UsageCapture {
        val query = usageStatsManager.queryEvents(startMillis, endMillis)
        val event = UsageEvents.Event()

        var currentUnlockStart: Long? = null
        var currentUnlockId: String? = null
        var currentAppPackage: String? = null
        var currentAppStart: Long? = null

        val appSessions = mutableListOf<AppUsageSessionEntity>()
        val phoneSessions = mutableListOf<PhoneSessionEntity>()

        while (query.hasNextEvent()) {
            query.getNextEvent(event)
            val ts = event.timeStamp

            when (event.eventType) {
                UsageEvents.Event.SCREEN_INTERACTIVE -> {
                    currentUnlockStart = ts
                    currentUnlockId = "unlock-$dayKey-$ts"
                }

                UsageEvents.Event.SCREEN_NON_INTERACTIVE -> {
                    currentAppPackage?.let { activePackage ->
                        currentAppStart?.let { activeStart ->
                            appSessions += buildAppSession(
                                dayKey = dayKey,
                                packageName = activePackage,
                                startMillis = activeStart,
                                endMillis = ts,
                                unlockSessionId = currentUnlockId,
                            )
                        }
                    }
                    currentAppPackage = null
                    currentAppStart = null

                    currentUnlockStart?.let { unlockStart ->
                        phoneSessions += buildPhoneSession(
                            dayKey = dayKey,
                            unlockStart = unlockStart,
                            lockTime = ts,
                        )
                    }
                    currentUnlockStart = null
                    currentUnlockId = null
                }

                UsageEvents.Event.MOVE_TO_FOREGROUND -> {
                    currentAppPackage?.let { activePackage ->
                        currentAppStart?.let { activeStart ->
                            appSessions += buildAppSession(
                                dayKey = dayKey,
                                packageName = activePackage,
                                startMillis = activeStart,
                                endMillis = ts,
                                unlockSessionId = currentUnlockId,
                            )
                        }
                    }
                    currentAppPackage = event.packageName
                    currentAppStart = ts
                }

                UsageEvents.Event.MOVE_TO_BACKGROUND -> {
                    if (event.packageName == currentAppPackage && currentAppStart != null) {
                        appSessions += buildAppSession(
                            dayKey = dayKey,
                            packageName = event.packageName,
                            startMillis = currentAppStart!!,
                            endMillis = ts,
                            unlockSessionId = currentUnlockId,
                        )
                        currentAppPackage = null
                        currentAppStart = null
                    }
                }
            }
        }

        return UsageCapture(
            appUsageSessions = appSessions.filter { it.durationSeconds > 0 },
            phoneSessions = phoneSessions.filter { it.durationSeconds > 0 },
        )
    }

    private fun buildAppSession(
        dayKey: String,
        packageName: String,
        startMillis: Long,
        endMillis: Long,
        unlockSessionId: String?,
    ): AppUsageSessionEntity {
        val durationSeconds = (endMillis - startMillis) / 1000
        return AppUsageSessionEntity(
            id = "$dayKey:$packageName:$startMillis",
            day = dayKey,
            appPackage = packageName,
            appLabel = resolveAppLabel(packageName),
            sessionStart = formatMillis(startMillis),
            sessionEnd = formatMillis(endMillis),
            durationSeconds = durationSeconds,
            category = resolveCategory(packageName),
            unlockSessionId = unlockSessionId,
        )
    }

    private fun buildPhoneSession(
        dayKey: String,
        unlockStart: Long,
        lockTime: Long,
    ): PhoneSessionEntity {
        val durationSeconds = (lockTime - unlockStart) / 1000
        return PhoneSessionEntity(
            id = "unlock-$dayKey-$unlockStart",
            day = dayKey,
            screenUnlockTime = formatMillis(unlockStart),
            screenLockTime = formatMillis(lockTime),
            durationSeconds = durationSeconds,
        )
    }

    private fun resolveAppLabel(packageName: String): String {
        return runCatching {
            val appInfo = context.packageManager.getApplicationInfo(packageName, 0)
            context.packageManager.getApplicationLabel(appInfo).toString()
        }.getOrDefault(packageName)
    }

    private fun resolveCategory(packageName: String): String {
        val category = runCatching {
            context.packageManager.getApplicationInfo(packageName, 0).category
        }.getOrNull()

        return when (category) {
            ApplicationInfo.CATEGORY_SOCIAL -> "social"
            ApplicationInfo.CATEGORY_PRODUCTIVITY -> "productivity"
            ApplicationInfo.CATEGORY_VIDEO -> "video"
            ApplicationInfo.CATEGORY_AUDIO -> "media"
            ApplicationInfo.CATEGORY_NEWS -> "news"
            else -> "unknown"
        }
    }

    private fun formatMillis(value: Long): String {
        return Instant.ofEpochMilli(value)
            .atZone(ZoneId.systemDefault())
            .format(DateTimeFormatter.ISO_OFFSET_DATE_TIME)
    }
}

private data class UsageCapture(
    val appUsageSessions: List<AppUsageSessionEntity>,
    val phoneSessions: List<PhoneSessionEntity>,
)
