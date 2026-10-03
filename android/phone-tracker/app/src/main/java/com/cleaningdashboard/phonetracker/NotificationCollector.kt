package com.cleaningdashboard.phonetracker

import android.app.Notification
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import android.os.Build
import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.time.Instant
import java.util.UUID

class NotificationCollector : NotificationListenerService() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    override fun onListenerConnected() {
        super.onListenerConnected()
        connected = this
        reconcileActive()
    }

    override fun onListenerDisconnected() {
        if (connected === this) connected = null
        super.onListenerDisconnected()
    }

    override fun onDestroy() {
        if (connected === this) connected = null
        scope.cancel()
        super.onDestroy()
    }

    override fun onNotificationPosted(sbn: StatusBarNotification?) {
        if (sbn == null || sbn.packageName == packageName) return
        val notice = sbn.notification
        val importance = try {
            val ranking = Ranking()
            if (currentRanking.getRanking(sbn.key,ranking)) ranking.importance else null
        } catch (_: Exception) { null }
        val data = JSONObject()
            .put("notification_key", sbn.key)
            .put("notification_id", sbn.id)
            .put("tag", sbn.tag)
            .put("title", notice.extras.getCharSequence(Notification.EXTRA_TITLE)?.toString()?.take(250))
            .put("text", notice.extras.getCharSequence(Notification.EXTRA_TEXT)?.toString()?.take(4000))
            .put("channel", if (Build.VERSION.SDK_INT >= 26) notice.channelId else null)
            .put("category", notice.category)
            .put("importance",importance)
            .put("observed_at",Instant.now().toString())
        persist("notification_posted", sbn, data)
        if (sbn.isClearable) scope.launch { suppressIfBlocked(sbn) }
    }

    override fun onNotificationRemoved(sbn: StatusBarNotification?, rankingMap: RankingMap?, reason: Int) {
        if (sbn == null || sbn.packageName == packageName) return
        persist("notification_removed", sbn,
            JSONObject().put("notification_key", sbn.key).put("notification_id", sbn.id)
                .put("tag", sbn.tag).put("reason", reason))
    }

    private fun persist(type: String, sbn: StatusBarNotification, metadata: JSONObject) {
        scope.launch {
            val name = try {
                packageManager.getApplicationLabel(packageManager.getApplicationInfo(sbn.packageName, 0)).toString()
            } catch (_: Exception) { sbn.packageName }
            TrackerDatabase.get(applicationContext).dao().insert(
                TrackerEvent(UUID.randomUUID().toString(),
                    (if (type == "notification_posted") Instant.ofEpochMilli(sbn.postTime) else Instant.now()).toString(), type,
                    sbn.packageName, name, metadata.toString()))
            SyncScheduler.immediate(applicationContext)
        }
    }

    private fun isManaged(pkg: String): Boolean {
        val config = RulesCache.read(applicationContext)
        if (AccessBudget.policy(config,pkg) != null) return true
        val rules = config.optJSONArray("rules") ?: return false
        return (0 until rules.length()).any { index ->
            val rule = rules.optJSONObject(index)
            rule?.optString("target") == pkg && rule.optBoolean("enabled",true)
        }
    }

    private suspend fun suppressIfBlocked(sbn: StatusBarNotification) {
        if (!isManaged(sbn.packageName)) return
        val blocked = try { RuleEngine.evaluate(applicationContext,sbn.packageName) != null }
            catch (error: Exception) {
                Log.w("PhoneBlocker", "notification rule check failed",error)
                false
            }
        if (!blocked) return
        withContext(Dispatchers.Main) {
            if (connected === this@NotificationCollector) try { cancelNotification(sbn.key) }
                catch (error: Exception) { Log.w("PhoneBlocker", "notification dismissal failed",error) }
        }
    }

    private fun reconcileActive() {
        val notices = try { activeNotifications?.filter { it.packageName != packageName && it.isClearable }.orEmpty() }
            catch (_: Exception) { emptyList() }
        scope.launch {
            val blocked = mutableMapOf<String,Boolean>()
            for (notice in notices) {
                val shouldSuppress = blocked[notice.packageName] ?: run {
                    val result = isManaged(notice.packageName) && try {
                        RuleEngine.evaluate(applicationContext,notice.packageName) != null
                    } catch (error: Exception) {
                        Log.w("PhoneBlocker", "notification rule check failed",error)
                        false
                    }
                    blocked[notice.packageName] = result
                    result
                }
                if (shouldSuppress) withContext(Dispatchers.Main) {
                    if (connected === this@NotificationCollector) try { cancelNotification(notice.key) }
                        catch (error: Exception) { Log.w("PhoneBlocker", "notification dismissal failed",error) }
                }
            }
        }
    }

    companion object {
        @Volatile private var connected: NotificationCollector? = null
        fun reconcileBlocked() { connected?.reconcileActive() }
    }
}
