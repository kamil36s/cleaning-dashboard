package com.cleaningdashboard.phonetracker

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.LocalDateTime
import java.security.MessageDigest
import javax.crypto.SecretKeyFactory
import javax.crypto.spec.PBEKeySpec

data class BlockDecision(val ruleName: String, val target: String, val details: List<String> = emptyList())

object RulesCache {
    private const val PREFS = "phone-tracker-rules"
    fun save(context: Context, data: JSONObject) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putString("config", data.toString()).apply()
    }
    fun read(context: Context): JSONObject = try {
        JSONObject(context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString("config", "{}") ?: "{}")
    } catch (_: Exception) { JSONObject() }
    fun overrideUntil(context: Context, pkg: String): Long = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        .getLong("override:$pkg", 0L)
    fun lastOverride(context: Context, pkg: String): Long = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        .getLong("last_override:$pkg", 0L)
    fun policy(context: Context): JSONObject = read(context).optJSONObject("override_policy") ?: JSONObject()
    fun pinMatches(context: Context, pin: String): Boolean = try {
        val data = policy(context)
        val salt = data.getString("pin_salt")
        val expected = data.getString("pin_hash")
        val saltBytes = salt.chunked(2).map { it.toInt(16).toByte() }.toByteArray()
        val spec = PBEKeySpec(pin.toCharArray(),saltBytes,120_000,256)
        val actual = SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256").generateSecret(spec).encoded
            .joinToString("") { "%02x".format(it) }
        MessageDigest.isEqual(actual.toByteArray(),expected.toByteArray())
    } catch (_: Exception) { false }
    fun override(context: Context, pkg: String, durationMinutes: Int = 5) {
        val now = System.currentTimeMillis()
        val day = LocalDate.now().toString()
        val oldCount = overrideCount(context,pkg)
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
            .putLong("override:$pkg", now + durationMinutes * 60_000L)
            .putLong("last_override:$pkg",now)
            .putString("override_day:$pkg",day)
            .putInt("override_count:$pkg",oldCount+1).apply()
    }
    fun overrideCount(context: Context, pkg: String): Int {
        val prefs = context.getSharedPreferences(PREFS,Context.MODE_PRIVATE)
        return if (prefs.getString("override_day:$pkg",null) == LocalDate.now().toString())
            prefs.getInt("override_count:$pkg",0) else 0
    }
}

object RuleEngine {
    private val protected = setOf("com.android.settings", "com.android.dialer", "com.google.android.dialer",
        "com.android.systemui", "com.cleaningdashboard.phonetracker", "com.miui.home",
        "com.google.android.apps.nexuslauncher")

    suspend fun evaluate(context: Context, pkg: String): BlockDecision? {
        if (pkg in protected || pkg.contains("emergency",ignoreCase = true)) return null
        if (RulesCache.overrideUntil(context,pkg) > System.currentTimeMillis()) return null
        val config = RulesCache.read(context)
        val rules = config.optJSONArray("rules") ?: return null
        val dayStart = LocalDate.now().atStartOfDay(ZoneId.systemDefault()).toInstant()
        val events = TrackerDatabase.get(context).dao().usageSince(dayStart.minusSeconds(86_400).toString())
        val categories = config.optJSONObject("categories") ?: JSONObject()
        val externals = config.optJSONObject("external_conditions") ?: JSONObject()
        val externalDates = config.optJSONObject("external_condition_dates") ?: JSONObject()
        val now = Instant.now()
        val secondsByApp = mutableMapOf<String, Double>()
        val launchesByApp = mutableMapOf<String, Int>()
        var active: Pair<String, Instant>? = null
        for (event in events) {
            val at = try { Instant.parse(event.timestamp) } catch (_: Exception) { continue }
            when (event.eventType) {
                "app_foreground" -> {
                    active?.let { (previous, began) ->
                        secondsByApp[previous] = secondsByApp.getOrDefault(previous,0.0) +
                            (at.toEpochMilli()-maxOf(began,dayStart).toEpochMilli()).coerceAtLeast(0L)/1000.0
                    }
                    val name = event.packageName ?: continue
                    if (!at.isBefore(dayStart)) launchesByApp[name] = launchesByApp.getOrDefault(name,0) + 1
                    active = name to at
                }
                "app_background" -> {
                    if (active?.first == event.packageName) {
                        val (name,began) = active!!
                        secondsByApp[name] = secondsByApp.getOrDefault(name,0.0) +
                            (at.toEpochMilli()-maxOf(began,dayStart).toEpochMilli()).coerceAtLeast(0L)/1000.0
                        active = null
                    }
                }
                "screen_off" -> {
                    active?.let { (name,began) ->
                        secondsByApp[name] = secondsByApp.getOrDefault(name,0.0) +
                            (at.toEpochMilli()-maxOf(began,dayStart).toEpochMilli()).coerceAtLeast(0L)/1000.0
                    }
                    active = null
                }
            }
        }
        active?.let { (name,began) ->
            secondsByApp[name] = secondsByApp.getOrDefault(name,0.0) +
                (now.toEpochMilli()-maxOf(began,dayStart).toEpochMilli()).coerceAtLeast(0L)/1000.0
        }
        AccessBudget.status(config,pkg,secondsByApp.getOrDefault(pkg,0.0)/60.0,events,now)?.let { status ->
            if (status.reason != null) return BlockDecision(status.reason,pkg,AccessBudget.details(status))
        }
        repeat(rules.length()) { index ->
            val rule = rules.optJSONObject(index) ?: return@repeat
            if (!rule.optBoolean("enabled",true) || rule.optString("target") != pkg) return@repeat
            if (condition(rule.optJSONObject("when") ?: JSONObject(),pkg,secondsByApp,launchesByApp,categories,externals,externalDates,active))
                return BlockDecision(rule.optString("name","Daily limit"),pkg)
        }
        return null
    }

    suspend fun accessStatus(context: Context, pkg: String): AccessStatus? {
        val today = LocalDate.now().atStartOfDay(ZoneId.systemDefault()).toInstant()
        val events = TrackerDatabase.get(context).dao().usageSince(today.minusSeconds(86_400).toString())
        var active: Pair<String,Instant>? = null
        var seconds = 0.0
        val now = Instant.now()
        for (event in events) {
            val at = try { Instant.parse(event.timestamp) } catch (_: Exception) { continue }
            when (event.eventType) {
                "app_foreground" -> {
                    active?.let { (name,start) -> if (name == pkg) seconds +=
                        (at.toEpochMilli()-maxOf(start,today).toEpochMilli()).coerceAtLeast(0L)/1000.0 }
                    active = event.packageName?.let { it to at }
                }
                "app_background" -> if (active?.first == event.packageName) {
                    val start = active!!.second
                    if (event.packageName == pkg) seconds +=
                        (at.toEpochMilli()-maxOf(start,today).toEpochMilli()).coerceAtLeast(0L)/1000.0
                    active = null
                }
                "screen_off" -> {
                    active?.let { (name,start) -> if (name == pkg) seconds +=
                        (at.toEpochMilli()-maxOf(start,today).toEpochMilli()).coerceAtLeast(0L)/1000.0 }
                    active = null
                }
            }
        }
        active?.let { (name,start) -> if (name == pkg) seconds +=
            (now.toEpochMilli()-maxOf(start,today).toEpochMilli()).coerceAtLeast(0L)/1000.0 }
        return AccessBudget.status(RulesCache.read(context),pkg,seconds/60.0,events,now)
    }

    private fun condition(node: JSONObject, pkg: String, seconds: Map<String,Double>,
        launches: Map<String,Int>, categories: JSONObject, externals: JSONObject, externalDates: JSONObject,
        active: Pair<String,Instant>?): Boolean {
        node.optJSONArray("all")?.let { return (0 until it.length()).all { i ->
            condition(it.getJSONObject(i),pkg,seconds,launches,categories,externals,externalDates,active) } }
        node.optJSONArray("any")?.let { return (0 until it.length()).any { i ->
            condition(it.getJSONObject(i),pkg,seconds,launches,categories,externals,externalDates,active) } }
        node.optJSONObject("not")?.let { return !condition(it,pkg,seconds,launches,categories,externals,externalDates,active) }
        val metric = node.optString("metric")
        val group = node.optString("category",categories.optString(pkg))
        val observed: Double = when (metric) {
            "app_usage_today" -> seconds.getOrDefault(pkg,0.0)/60.0
            "app_launches_today" -> launches.getOrDefault(pkg,0).toDouble()
            "category_usage_today" -> if (group.isBlank()) 0.0 else seconds.entries.sumOf { (name,value) -> if (categories.optString(name)==group) value else 0.0 }/60.0
            "category_launches_today" -> if (group.isBlank()) 0.0 else launches.entries.sumOf { (name,value) -> if (categories.optString(name)==group) value else 0 }.toDouble()
            "time_of_day" -> java.time.LocalTime.now().toSecondOfDay()/60.0
            "doomscroll_minutes" -> if (active?.first == pkg) (Instant.now().toEpochMilli()-active.second.toEpochMilli()).coerceAtLeast(0L)/60_000.0 else 0.0
            else -> if (metric.startsWith("external:")) {
                val name = metric.removePrefix("external:")
                if (name == "cleaning_done_today" && externalDates.optString(name) !=
                    LocalDateTime.now().minusHours(6).toLocalDate().toString()) return false
                val value = externals.opt(name)
                when (value) { is Boolean -> if (value) 1.0 else 0.0; is Number -> value.toDouble(); else -> return false }
            } else return false
        }
        val wanted = when (val value = node.opt("value")) { is Boolean -> if (value) 1.0 else 0.0; is Number -> value.toDouble(); else -> return false }
        return when (node.optString("operator")) {
            "<" -> observed < wanted; "<=" -> observed <= wanted; "==" -> observed == wanted
            ">=" -> observed >= wanted; ">" -> observed > wanted; else -> false
        }
    }
}
