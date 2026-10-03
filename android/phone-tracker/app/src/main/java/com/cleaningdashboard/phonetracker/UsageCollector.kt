package com.cleaningdashboard.phonetracker

import android.app.AppOpsManager
import android.app.usage.UsageEvents
import android.app.usage.UsageStatsManager
import android.content.Context
import android.os.Process
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.nio.charset.StandardCharsets
import java.time.Instant
import java.util.UUID

object UsageCollector {
    fun hasAccess(context: Context): Boolean {
        val ops = context.getSystemService(AppOpsManager::class.java)
        return ops.checkOpNoThrow(AppOpsManager.OPSTR_GET_USAGE_STATS, Process.myUid(), context.packageName) == AppOpsManager.MODE_ALLOWED
    }

    suspend fun collect(context: Context): Int = withContext(Dispatchers.IO) {
        if (!hasAccess(context)) return@withContext 0
        val manager = context.getSystemService(UsageStatsManager::class.java)
        val now = System.currentTimeMillis()
        val prefs = context.getSharedPreferences("phone-tracker", Context.MODE_PRIVATE)
        val lastScan = prefs.getLong("last_usage_scan_ms", 0L)
        val initialBackfill = prefs.getInt("usage_backfill_version",0) < 1
        val earliest = if (initialBackfill) now - 30L * 86_400_000L
            else maxOf(lastScan - 10L * 60_000L, now - 7L * 86_400_000L)
        // A fixed UTC-day start makes event IDs stable across overlapping scans and restarts.
        val start = (earliest / 86_400_000L) * 86_400_000L
        val cursor = manager.queryEvents(start, now)
        val event = UsageEvents.Event()
        val duplicatesAtInstant = mutableMapOf<String, Int>()
        val registered = mutableSetOf<String>()
        val dao = TrackerDatabase.get(context).dao()
        val batch = ArrayList<TrackerEvent>(200)
        var count = 0
        while (cursor.hasNextEvent()) {
            cursor.getNextEvent(event)
            val type = when (event.eventType) {
                UsageEvents.Event.ACTIVITY_RESUMED -> "app_foreground"
                UsageEvents.Event.ACTIVITY_PAUSED -> "app_background"
                UsageEvents.Event.SCREEN_INTERACTIVE -> "screen_on"
                UsageEvents.Event.SCREEN_NON_INTERACTIVE -> "screen_off"
                UsageEvents.Event.KEYGUARD_HIDDEN -> "unlock"
                UsageEvents.Event.DEVICE_STARTUP -> "device_boot"
                else -> null
            } ?: continue
            val pkg = event.packageName?.takeUnless { it == context.packageName }
            if (type.startsWith("app_") && pkg == null) continue
            val key = "${event.timeStamp}|$type|${pkg.orEmpty()}"
            val ordinal = duplicatesAtInstant.getOrDefault(key, 0)
            duplicatesAtInstant[key] = ordinal + 1
            val id = UUID.nameUUIDFromBytes("$key|$ordinal".toByteArray(StandardCharsets.UTF_8)).toString()
            val appName = pkg?.let { name ->
                try { context.packageManager.getApplicationLabel(context.packageManager.getApplicationInfo(name, 0)).toString() }
                catch (_: Exception) { name }
            }
            if (pkg != null && appName != null && registered.add(pkg)) AppIconRegistry.register(context,pkg,appName)
            batch.add(TrackerEvent(id, Instant.ofEpochMilli(event.timeStamp).toString(), type, pkg, appName))
            if (batch.size >= 200) {
                dao.insertMany(batch.toList())
                batch.clear()
            }
            count++
        }
        if (batch.isNotEmpty()) dao.insertMany(batch)
        prefs.edit().putLong("last_usage_scan_ms", now).putInt("usage_backfill_version",1).apply()
        count
    }
}
