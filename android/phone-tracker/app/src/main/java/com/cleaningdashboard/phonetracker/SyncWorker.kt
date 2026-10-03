package com.cleaningdashboard.phonetracker

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkerParameters
import androidx.work.WorkManager
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URI
import java.net.URL
import java.time.Instant
import java.util.UUID
import java.util.concurrent.TimeUnit

object SyncScheduler {
    private val constraints = Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()

    fun periodic(context: Context) {
        val request = PeriodicWorkRequestBuilder<CollectorWorker>(15, TimeUnit.MINUTES)
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS).build()
        WorkManager.getInstance(context).enqueueUniquePeriodicWork("phone-tracker-collector",
            ExistingPeriodicWorkPolicy.KEEP, request)
    }

    fun collectNow(context: Context) {
        val request = OneTimeWorkRequestBuilder<CollectorWorker>().build()
        WorkManager.getInstance(context).enqueueUniqueWork("phone-tracker-collect-now",ExistingWorkPolicy.KEEP,request)
    }

    fun immediate(context: Context) {
        val request = OneTimeWorkRequestBuilder<SyncWorker>().setConstraints(constraints)
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS).build()
        WorkManager.getInstance(context).enqueueUniqueWork("phone-tracker-now", ExistingWorkPolicy.KEEP, request)
    }
}

class CollectorWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context,params) {
    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        try {
            UsageCollector.collect(applicationContext)
            SupportingCollectors.battery(applicationContext)
            SupportingCollectors.location(applicationContext)
            LocalRetention.prune(applicationContext)
            SyncScheduler.immediate(applicationContext)
            Result.success()
        } catch (error: Exception) {
            TrackerConfig.syncResult(applicationContext,null,"Collector: ${error.message?.take(120)}")
            Result.retry()
        }
    }
}

class SyncWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        try {
            UsageCollector.collect(applicationContext)
            SupportingCollectors.battery(applicationContext)
            SupportingCollectors.location(applicationContext)
            LocalRetention.prune(applicationContext)
            val pairing = TrackerConfig.load(applicationContext) ?: return@withContext Result.success()
            val uri = URI(pairing.server)
            if (!onWifi()) return@withContext Result.success()
            if (!TrackerConfig.isLanHost(uri.host)) return@withContext Result.retry()
            val dao = TrackerDatabase.get(applicationContext).dao()
            var batches = 0
            while (batches++ < 100) {
                val pending = dao.pending(200)
                if (pending.isEmpty() && batches > 1) break
                val payload = JSONObject().put("schema_version", 1)
                    .put("device_id", pairing.deviceId).put("batch_id", UUID.randomUUID().toString())
                    .put("sent_at", Instant.now().toString()).put("pending_count",dao.pendingCount())
                    .put("blocker_enabled",BlockerHealth.isRunning(applicationContext))
                    .put("config_version",RulesCache.read(applicationContext).optJSONObject("access")?.optInt("version",0) ?: 0)
                val events = JSONArray()
                pending.forEach { event ->
                    events.put(JSONObject().put("event_id", event.eventId).put("timestamp", event.timestamp)
                        .put("event_type", event.eventType).put("package_name", event.packageName)
                        .put("app_name", event.appName).put("metadata", JSONObject(event.metadataJson)))
                }
                payload.put("events", events)
                val url = URL("${pairing.server}/api/phone-tracker/sync")
                val conn = (url.openConnection() as HttpURLConnection).apply {
                    requestMethod = "POST"
                    connectTimeout = 10_000
                    readTimeout = 15_000
                    doOutput = true
                    setRequestProperty("Content-Type", "application/json; charset=utf-8")
                    setRequestProperty("Authorization", "Bearer ${pairing.token}")
                    setRequestProperty("X-Phone-Device-ID", pairing.deviceId)
                }
                try {
                    conn.outputStream.use { it.write(payload.toString().toByteArray(Charsets.UTF_8)) }
                    if (conn.responseCode != 200) throw IllegalStateException("Sync HTTP ${conn.responseCode}")
                    val response = JSONObject(conn.inputStream.bufferedReader().use { it.readText() })
                    val confirmed = mutableListOf<String>()
                    for (field in listOf("accepted", "duplicates")) {
                        val array = response.getJSONArray(field)
                        repeat(array.length()) { confirmed += array.getString(it) }
                    }
                    if (confirmed.isNotEmpty()) dao.acknowledge(confirmed, Instant.now().toString())
                    val rejected = response.getJSONArray("rejected")
                    repeat(rejected.length()) { index ->
                        val item = rejected.getJSONObject(index)
                        val id = item.optString("event_id")
                        if (id.isNotBlank()) dao.reject(id, item.optString("reason", "Rejected by PC").take(160))
                    }
                    if (pending.isNotEmpty() && confirmed.isEmpty() && rejected.length() == 0)
                        throw IllegalStateException("Server did not acknowledge the batch")
                } finally { conn.disconnect() }
            }
            if (dao.pendingCount() > 0) return@withContext Result.retry()
            var appBatches = 0
            while (appBatches++ < 10) {
                val apps = dao.pendingApps(10)
                if (apps.isEmpty()) break
                val payload = JSONObject().put("device_id",pairing.deviceId)
                val array = JSONArray()
                apps.forEach { app -> array.put(JSONObject().put("package_name",app.packageName)
                    .put("app_name",app.appName).put("icon_base64",app.iconBase64)) }
                payload.put("apps",array)
                val conn = (URL("${pairing.server}/api/phone-tracker/apps").openConnection() as HttpURLConnection).apply {
                    requestMethod = "POST"; connectTimeout = 10_000; readTimeout = 15_000; doOutput = true
                    setRequestProperty("Content-Type","application/json; charset=utf-8")
                    setRequestProperty("Authorization","Bearer ${pairing.token}")
                    setRequestProperty("X-Phone-Device-ID",pairing.deviceId)
                }
                try {
                    conn.outputStream.use { it.write(payload.toString().toByteArray(Charsets.UTF_8)) }
                    if (conn.responseCode != 200) throw IllegalStateException("App registry HTTP ${conn.responseCode}")
                    val response = JSONObject(conn.inputStream.bufferedReader().use { it.readText() })
                    val accepted = response.getJSONArray("accepted")
                    val names = (0 until accepted.length()).map { accepted.getString(it) }
                    if (names.isEmpty()) throw IllegalStateException("App registry not acknowledged")
                    dao.acknowledgeApps(names,Instant.now().toString())
                } finally { conn.disconnect() }
            }
            val configConnection = (URL("${pairing.server}/api/phone-tracker/config").openConnection() as HttpURLConnection).apply {
                connectTimeout = 10_000
                readTimeout = 10_000
                setRequestProperty("Authorization", "Bearer ${pairing.token}")
                setRequestProperty("X-Phone-Device-ID", pairing.deviceId)
            }
            try {
                if (configConnection.responseCode != 200) throw IllegalStateException("Rules HTTP ${configConnection.responseCode}")
                val config = JSONObject(configConnection.inputStream.bufferedReader().use { it.readText() })
                RulesCache.save(applicationContext,config)
                NotificationCollector.reconcileBlocked()
                ManagedShortcuts.updateFromConfig(applicationContext,config)
                RewardNotifier.onConfig(applicationContext,config)
                RewardNotifier.blockerHealth(applicationContext)
                LocalRetention.prune(applicationContext)
            } finally { configConnection.disconnect() }
            TrackerConfig.syncResult(applicationContext, Instant.now().toString(), null)
            Result.success()
        } catch (error: Exception) {
            TrackerConfig.syncResult(applicationContext, null, error.message?.take(160) ?: "Sync failed")
            Result.retry()
        }
    }

    private fun onWifi(): Boolean {
        val manager = applicationContext.getSystemService(ConnectivityManager::class.java)
        val network = manager.activeNetwork ?: return false
        val caps = manager.getNetworkCapabilities(network) ?: return false
        return caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) ||
            caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET)
    }
}
