package com.cleaningdashboard.phonetelemetry.permissions

import android.app.AppOpsManager
import android.app.usage.UsageStatsManager
import android.content.Context
import android.content.Intent
import android.os.Build
import android.provider.Settings

data class TelemetryPermissionState(
    val hasUsageAccess: Boolean = false,
    val hasNotificationListenerAccess: Boolean = false,
)

object UsageAccessHelper {
    fun getPermissionState(context: Context): TelemetryPermissionState {
        return TelemetryPermissionState(
            hasUsageAccess = hasUsageAccess(context),
            hasNotificationListenerAccess = hasNotificationListenerAccess(context),
        )
    }

    fun hasUsageAccess(context: Context): Boolean {
        val appOps = context.getSystemService(AppOpsManager::class.java) ?: return false
        val mode = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            appOps.unsafeCheckOpNoThrow(
                AppOpsManager.OPSTR_GET_USAGE_STATS,
                android.os.Process.myUid(),
                context.packageName,
            )
        } else {
            @Suppress("DEPRECATION")
            appOps.checkOpNoThrow(
                AppOpsManager.OPSTR_GET_USAGE_STATS,
                android.os.Process.myUid(),
                context.packageName,
            )
        }

        if (mode == AppOpsManager.MODE_ALLOWED) {
            return true
        }

        // Fallback check: some devices report permission state more reliably through an actual query.
        val usageStatsManager = context.getSystemService(UsageStatsManager::class.java) ?: return false
        val end = System.currentTimeMillis()
        val start = end - 60 * 60 * 1000
        val stats = usageStatsManager.queryUsageStats(UsageStatsManager.INTERVAL_DAILY, start, end)
        return !stats.isNullOrEmpty()
    }

    fun hasNotificationListenerAccess(context: Context): Boolean {
        val enabled = Settings.Secure.getString(
            context.contentResolver,
            "enabled_notification_listeners",
        ) ?: return false

        return enabled.contains(context.packageName)
    }

    fun openUsageAccessSettings(context: Context) {
        context.startActivity(
            Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
        )
    }

    fun openNotificationListenerSettings(context: Context) {
        context.startActivity(
            Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
        )
    }
}
