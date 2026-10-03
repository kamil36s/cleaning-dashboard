package com.cleaningdashboard.phonetracker

import org.json.JSONObject
import java.time.Instant
import java.time.LocalDate
import java.time.LocalTime
import java.time.ZoneId

data class AccessStatus(
    val target: String, val day: String, val baseline: Double, val normal: Double,
    val bonus: Double, val unlocked: Double,
    val used: Double, val remaining: Double, val reading: JSONObject?, val cleaning: JSONObject?,
    val reason: String?, val version: Int, val cachedProgress: Boolean,
)

fun accessBlockReason(night: Boolean, cooldown: Boolean, sessionMinutes: Double,
                      maxSession: Int, used: Double, totalUnlocked: Double): String? = when {
    night -> "Night lock"
    cooldown -> "Session cooldown"
    sessionMinutes >= maxSession -> "Session limit reached"
    used + 0.001 >= totalUnlocked -> "Daily access used up"
    else -> null
}

object AccessBudget {
    fun policy(config: JSONObject, pkg: String): JSONObject? {
        val policies = config.optJSONObject("access")?.optJSONArray("policies") ?: return null
        repeat(policies.length()) { index ->
            val item = policies.optJSONObject(index) ?: return@repeat
            if (item.optString("target") == pkg && item.optBoolean("enabled",true)) return item
        }
        return null
    }

    private fun inNightWindow(settings: JSONObject): Boolean {
        if (!settings.optBoolean("enabled",false)) return false
        return try {
            val start = LocalTime.parse(settings.optString("from","23:30"))
            val end = LocalTime.parse(settings.optString("until","09:00"))
            val now = LocalTime.now()
            if (start <= end) now >= start && now < end else now >= start || now < end
        } catch (_: Exception) { false }
    }

    private fun session(events: List<TrackerEvent>, pkg: String, now: Instant): Pair<Double,Pair<Double,Instant>?> {
        var currentPackage: String? = null
        var currentStart: Instant? = null
        var last: Pair<Double,Instant>? = null
        fun close(at: Instant) {
            if (currentPackage == pkg && currentStart != null) {
                last = ((at.toEpochMilli()-currentStart!!.toEpochMilli()).coerceAtLeast(0L)/60_000.0) to at
            }
            currentPackage = null
            currentStart = null
        }
        for (event in events) {
            val at = try { Instant.parse(event.timestamp) } catch (_: Exception) { continue }
            when (event.eventType) {
                "app_foreground" -> {
                    if (currentPackage == event.packageName) continue
                    close(at)
                    currentPackage = event.packageName
                    currentStart = at
                }
                "app_background" -> if (currentPackage == event.packageName) close(at)
                "screen_off" -> close(at)
            }
        }
        val active = if (currentPackage == pkg && currentStart != null)
            (now.toEpochMilli()-currentStart!!.toEpochMilli()).coerceAtLeast(0L)/60_000.0 else 0.0
        return active to last
    }

    fun status(config: JSONObject, pkg: String, usedMinutes: Double, events: List<TrackerEvent>, now: Instant = Instant.now()): AccessStatus? {
        val policy = policy(config,pkg) ?: return null
        val state = policy.optJSONObject("state") ?: JSONObject()
        val today = LocalDate.now(ZoneId.systemDefault()).toString()
        val current = state.optString("day") == today
        val baseline = state.optDouble("effective_base_cap_minutes",
            state.optDouble("baseline_minutes",50.0)).coerceIn(1.0,1440.0)
        // Keep enforcing the last synced allowance when the PC is offline across midnight.
        // Usage still resets from today's local events.
        val normal = state.optDouble("normal_unlocked_minutes",state.optDouble("unlocked_minutes",0.0))
            .coerceIn(0.0,baseline)
        val bonus = state.optDouble("extra_reading_bonus_minutes",0.0).coerceAtLeast(0.0)
        val unlocked = state.optDouble("total_unlocked_minutes",normal+bonus).coerceAtLeast(0.0)
        val used = usedMinutes.coerceAtLeast(0.0)
        val remaining = (unlocked-used).coerceAtLeast(0.0)
        val limits = policy.optJSONObject("session") ?: JSONObject()
        val maxSession = limits.optInt("max_minutes",15).coerceIn(1,240)
        val cooldown = limits.optInt("cooldown_minutes",20).coerceIn(0,1440)
        val (sessionMinutes,last) = session(events,pkg,now)
        val cooldownActive = last != null && last.first >= maxSession &&
            now.toEpochMilli()-last.second.toEpochMilli() < cooldown*60_000L
        val reason = accessBlockReason(inNightWindow(policy.optJSONObject("night") ?: JSONObject()),
            cooldownActive,sessionMinutes,maxSession,used,unlocked)
        return AccessStatus(pkg,today,baseline,normal,bonus,unlocked,used,remaining,
            state.optJSONObject("sources")?.optJSONObject("reading"),
            state.optJSONObject("sources")?.optJSONObject("cleaning"),
            reason,config.optJSONObject("access")?.optInt("version",0) ?: 0,!current)
    }

    fun details(status: AccessStatus): List<String> {
        fun minutes(value: Double): String = kotlin.math.round(value).toInt().toString()
        fun source(label: String, data: JSONObject?): String {
            if (data == null) return "$label: waiting for today's plan"
            val current = data.optInt("current_value",0)
            val target = data.optInt("target_value",0)
            val progress = (data.optDouble("progress",0.0)*100).toInt().coerceIn(0,100)
            return "$label: $current / $target · $progress%"
        }
        return listOf("Available now: ${minutes(status.remaining)} min",
            "Base cap: ${minutes(status.baseline)} min",
            "Plan unlocked: ${minutes(status.normal)} min · Reading bonus: +${minutes(status.bonus)} min",
            "Total unlocked: ${minutes(status.unlocked)} min",
            "Used today: ${minutes(status.used)} min",
            source("Reading",status.reading),source("Cleaning",status.cleaning),
            if (status.cachedProgress) "Using last synced progress; connect to the PC for today's plan."
                else "Complete more of today's plan to unlock time.")
    }
}
