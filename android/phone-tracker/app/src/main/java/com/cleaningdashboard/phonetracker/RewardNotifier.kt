package com.cleaningdashboard.phonetracker

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.content.pm.PackageManager
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.work.CoroutineWorker
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import org.json.JSONObject
import java.time.LocalDate
import java.util.concurrent.TimeUnit

object RewardNotifier {
    private const val CHANNEL = "app_access_rewards"
    private const val HEALTH_CHANNEL = "app_blocker_health"
    private const val PREFS = "phone-access-notifications"

    private fun permitted(context: Context): Boolean = ContextCompat.checkSelfPermission(
        context,Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED

    private fun channels(context: Context) {
        val manager = context.getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel(CHANNEL,"App access rewards",NotificationManager.IMPORTANCE_DEFAULT))
        manager.createNotificationChannel(NotificationChannel(HEALTH_CHANNEL,"App blocker health",NotificationManager.IMPORTANCE_HIGH))
    }

    fun onConfig(context: Context, config: JSONObject) {
        val policies = config.optJSONObject("access")?.optJSONArray("policies") ?: return
        val prefs = context.getSharedPreferences(PREFS,Context.MODE_PRIVATE)
        repeat(policies.length()) { index ->
            val policy = policies.optJSONObject(index) ?: return@repeat
            if (!policy.optBoolean("enabled",true)) return@repeat
            val settings = policy.optJSONObject("notifications") ?: JSONObject()
            val state = policy.optJSONObject("state") ?: return@repeat
            val day = state.optString("day")
            if (day != LocalDate.now().toString()) return@repeat
            val target = policy.optString("target")
            val key = "$day:$target"
            val normal = state.optInt("normal_unlocked_minutes",state.optInt("unlocked_minutes",0))
            val bonus = state.optDouble("extra_reading_bonus_minutes",0.0)
            val plan = state.optJSONObject("reduction_plan") ?: JSONObject()
            val forecast = plan.optJSONObject("forecast") ?: JSONObject()
            val complete = listOf("reading","cleaning").all { source ->
                val item = state.optJSONObject("sources")?.optJSONObject(source)
                item != null && item.optInt("target_value",0) > 0 && item.optDouble("progress",0.0) >= 1.0
            }
            val pending = (settings.optBoolean("enabled",true) && normal > prefs.getInt("sent:$key",0)) ||
                (settings.optBoolean("extra_reading_enabled",true) &&
                    bonusDelta(prefs.getFloat("bonus:$key",0f).toDouble(),bonus) != null) ||
                (settings.optBoolean("full_plan_enabled",true) && complete && !prefs.getBoolean("full:$key",false)) ||
                (settings.optBoolean("reduction_enabled",false) && plan.optInt("day",0)>0 &&
                    forecast.optDouble("today",0.0) < forecast.optDouble("yesterday",0.0)-0.001 &&
                    !prefs.getBoolean("reduction:$key",false))
            if (!pending) return@repeat
            val request = OneTimeWorkRequestBuilder<RewardNotificationWorker>()
                .setInitialDelay(settings.optLong("debounce_seconds",30).coerceIn(0,300),TimeUnit.SECONDS).build()
            WorkManager.getInstance(context).enqueueUniqueWork("phone-reward:$target",ExistingWorkPolicy.REPLACE,request)
        }
    }

    suspend fun sendPending(context: Context) {
        if (!permitted(context)) return
        channels(context)
        val policies = RulesCache.read(context).optJSONObject("access")?.optJSONArray("policies") ?: return
        val prefs = context.getSharedPreferences(PREFS,Context.MODE_PRIVATE)
        repeat(policies.length()) { index ->
            val policy = policies.optJSONObject(index) ?: return@repeat
            if (!policy.optBoolean("enabled",true)) return@repeat
            val settings = policy.optJSONObject("notifications") ?: JSONObject()
            val state = policy.optJSONObject("state") ?: return@repeat
            val day = state.optString("day")
            if (day != LocalDate.now().toString()) return@repeat
            val target = policy.optString("target")
            val key = "$day:$target"
            val sent = prefs.getInt("sent:$key",0)
            val normal = state.optInt("normal_unlocked_minutes",state.optInt("unlocked_minutes",0))
            val bonus = state.optDouble("extra_reading_bonus_minutes",0.0)
            val total = state.optDouble("total_unlocked_minutes",normal+bonus)
            val baseline = state.optDouble("effective_base_cap_minutes",
                state.optDouble("baseline_minutes",50.0)).toInt().coerceAtLeast(1)
            val milestones = settings.optJSONArray("milestones")
            val marks = if (settings.optBoolean("milestones_enabled",true) && milestones != null)
                (0 until milestones.length()).map { milestones.optInt(it,101) } else emptyList()
            val decision = if (settings.optBoolean("enabled",true))
                rewardDecision(sent,normal,baseline,settings.optInt("minimum_increase",1),
                    marks,state.optDouble("progress",0.0)) else null
            val status = RuleEngine.accessStatus(context,target)
            val used = status?.used ?: state.optDouble("used_minutes",0.0)
            val remaining = (total-used).coerceAtLeast(0.0)
            val label = if (target == "com.instagram.android") "Instagram" else target.substringAfterLast('.')
            fun minutes(value: Double) = kotlin.math.round(value).toInt().toString()
            fun progress(name: String): Int = (state.optJSONObject("sources")?.optJSONObject(name)
                ?.optDouble("progress",0.0)?.times(100))?.toInt() ?: 0
            val lines = buildList {
                add(if (settings.optBoolean("show_baseline",true)) "Base cap: $baseline min · Plan: $normal min"
                    else "Plan unlocked: $normal min")
                add("Reading bonus: +${minutes(bonus)} min · Total: ${minutes(total)} min")
                if (settings.optBoolean("show_used",true)) add("Used: ${minutes(used)} min")
                if (settings.optBoolean("show_remaining",true)) add("Remaining: ${minutes(remaining)} min")
                if (settings.optBoolean("show_reading",true)) add("Reading: ${progress("reading")}%")
                if (settings.optBoolean("show_cleaning",true)) add("Cleaning: ${progress("cleaning")}%")
            }
            val manager = NotificationManagerCompat.from(context)
            fun send(id: Int, title: String, content: List<String>) {
                val notification = NotificationCompat.Builder(context,CHANNEL)
                    .setSmallIcon(R.drawable.ic_tracker_mark).setContentTitle(title)
                    .setContentText(content.firstOrNull().orEmpty())
                    .setStyle(NotificationCompat.BigTextStyle().bigText(content.joinToString("\n")))
                    .setAutoCancel(true).build()
                manager.notify(id,notification)
            }
            if (decision != null) {
                send(target.hashCode(),"+${decision.newMinutes} min $label plan progress",lines)
                prefs.edit().putInt("sent:$key",normal).apply()
            }
            val sentBonus = prefs.getFloat("bonus:$key",0f).toDouble()
            val newBonus = bonusDelta(sentBonus,bonus)
            if (settings.optBoolean("extra_reading_enabled",true) && newBonus != null) {
                val extra = state.optInt("extra_reading_pages",0)
                val read = state.optJSONObject("sources")?.optJSONObject("reading")
                send(target.hashCode()+1,"+${minutes(newBonus)} min bonus $label",
                    listOf("$extra extra reading pages · ${read?.optInt("current_value",0) ?: 0} / ${read?.optInt("target_value",0) ?: 0} pages")+lines)
                prefs.edit().putFloat("bonus:$key",bonus.toFloat()).apply()
            }
            val complete = listOf("reading","cleaning").all { source ->
                val item = state.optJSONObject("sources")?.optJSONObject(source)
                item != null && item.optInt("target_value",0) > 0 && item.optDouble("progress",0.0) >= 1.0
            }
            if (settings.optBoolean("full_plan_enabled",true) && complete && !prefs.getBoolean("full:$key",false)) {
                send(target.hashCode()+2,"Today's plan completed",
                    listOf("Reading ✓ · Cleaning ✓","Base allowance: $normal min",
                           "Reading bonus: +${minutes(bonus)} min","Total: ${minutes(total)} min"))
                prefs.edit().putBoolean("full:$key",true).apply()
            }
            val plan = state.optJSONObject("reduction_plan") ?: JSONObject()
            val forecast = plan.optJSONObject("forecast") ?: JSONObject()
            if (settings.optBoolean("reduction_enabled",false) && plan.optInt("day",0)>0 &&
                forecast.optDouble("today",0.0) < forecast.optDouble("yesterday",0.0)-0.001 &&
                !prefs.getBoolean("reduction:$key",false)) {
                send(target.hashCode()+3,"Today's $label base cap: ${minutes(forecast.optDouble("today"))} min",
                    listOf("Yesterday: ${minutes(forecast.optDouble("yesterday"))} min",
                           "Reduction day ${plan.optInt("day",0)} · Floor: ${minutes(forecast.optDouble("floor"))} min"))
                prefs.edit().putBoolean("reduction:$key",true).apply()
            }
        }
    }

    fun blockerHealth(context: Context) {
        if (!permitted(context)) return
        val manager = NotificationManagerCompat.from(context)
        if (BlockerHealth.isRunning(context)) { manager.cancel(10001); return }
        channels(context)
        val notification = NotificationCompat.Builder(context,HEALTH_CHANNEL)
            .setSmallIcon(R.drawable.ic_tracker_mark)
            .setContentTitle("App blocking is off")
            .setContentText("Enable Phone Tracker limits in Accessibility settings.")
            .setOngoing(true).build()
        manager.notify(10001,notification)
    }
}

class RewardNotificationWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context,params) {
    override suspend fun doWork(): Result {
        RewardNotifier.sendPending(applicationContext)
        return Result.success()
    }
}
