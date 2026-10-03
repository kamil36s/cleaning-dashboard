package com.cleaningdashboard.phonetracker

import android.accessibilityservice.AccessibilityServiceInfo
import android.content.Context
import android.provider.Settings
import android.view.accessibility.AccessibilityManager

object BlockerHealth {
    private const val PREFS = "phone-tracker-blocker-health"

    fun heartbeat(context: Context) {
        context.getSharedPreferences(PREFS,Context.MODE_PRIVATE).edit()
            .putLong("heartbeat",System.currentTimeMillis()).apply()
    }

    fun disconnected(context: Context) {
        context.getSharedPreferences(PREFS,Context.MODE_PRIVATE).edit().putLong("heartbeat",0L).apply()
    }

    fun isRunning(context: Context): Boolean {
        if (Settings.Secure.getInt(context.contentResolver,Settings.Secure.ACCESSIBILITY_ENABLED,0) != 1)
            return false
        val manager = context.getSystemService(AccessibilityManager::class.java)
        val enabled = manager.getEnabledAccessibilityServiceList(AccessibilityServiceInfo.FEEDBACK_ALL_MASK)
            .any { info -> info.resolveInfo?.serviceInfo?.let { it.packageName == context.packageName &&
                it.name == BlockerService::class.java.name } == true }
        val last = context.getSharedPreferences(PREFS,Context.MODE_PRIVATE).getLong("heartbeat",0L)
        return enabled && System.currentTimeMillis()-last < 90_000L
    }
}
