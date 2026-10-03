package com.cleaningdashboard.phonetracker

import android.Manifest
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.location.Location
import android.location.LocationManager
import android.os.BatteryManager
import android.os.Build
import android.os.CancellationSignal
import androidx.core.content.ContextCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withTimeoutOrNull
import org.json.JSONObject
import java.nio.charset.StandardCharsets
import java.time.Instant
import java.util.UUID
import kotlin.coroutines.resume

object SupportingCollectors {
    suspend fun battery(context: Context) {
        val state = context.registerReceiver(null,IntentFilter(Intent.ACTION_BATTERY_CHANGED)) ?: return
        val level = state.getIntExtra(BatteryManager.EXTRA_LEVEL,-1)
        val scale = state.getIntExtra(BatteryManager.EXTRA_SCALE,100)
        if (level < 0 || scale <= 0) return
        val status = state.getIntExtra(BatteryManager.EXTRA_STATUS,-1)
        val charging = status == BatteryManager.BATTERY_STATUS_CHARGING ||
            status == BatteryManager.BATTERY_STATUS_FULL
        val bucket = System.currentTimeMillis() / (15L*60_000L)
        val id = UUID.nameUUIDFromBytes("battery:$bucket".toByteArray(StandardCharsets.UTF_8)).toString()
        val metadata = JSONObject().put("percent",level*100.0/scale).put("charging",charging)
        TrackerDatabase.get(context).dao().insert(TrackerEvent(id,Instant.now().toString(),"battery",
            metadataJson=metadata.toString()))
    }

    suspend fun location(context: Context) {
        if (ContextCompat.checkSelfPermission(context,Manifest.permission.ACCESS_COARSE_LOCATION) != PackageManager.PERMISSION_GRANTED) return
        val manager = context.getSystemService(LocationManager::class.java)
        val candidates = listOf(LocationManager.PASSIVE_PROVIDER,LocationManager.NETWORK_PROVIDER)
            .mapNotNull { provider -> try { manager.getLastKnownLocation(provider) } catch (_: Exception) { null } }
        var point = candidates.maxByOrNull { it.time }
        val now = System.currentTimeMillis()
        if ((point == null || now-point.time > 30L*60_000L || point.accuracy > 1000f) &&
            Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            val prefs = context.getSharedPreferences("phone-tracker",Context.MODE_PRIVATE)
            val lastAttempt = prefs.getLong("last_network_fix_attempt_ms",0L)
            if (now-lastAttempt >= 60L*60_000L) {
                prefs.edit().putLong("last_network_fix_attempt_ms",now).apply()
                val current = withTimeoutOrNull(8_000L) { suspendCancellableCoroutine<Location?> { continuation ->
                    val signal = CancellationSignal()
                    continuation.invokeOnCancellation { signal.cancel() }
                    try {
                        manager.getCurrentLocation(LocationManager.NETWORK_PROVIDER,signal,context.mainExecutor) { fix ->
                            if (continuation.isActive) continuation.resume(fix)
                        }
                    } catch (_: Exception) { if (continuation.isActive) continuation.resume(null) }
                } }
                if (current != null) point = current
            }
        }
        point ?: return
        if (System.currentTimeMillis()-point.time > 30L*60_000L || point.accuracy > 1000f) return
        val previous = TrackerDatabase.get(context).dao().lastLocation()
        if (previous != null) {
            val old = try { JSONObject(previous.metadataJson) } catch (_: Exception) { JSONObject() }
            if (old.has("latitude") && old.has("longitude")) {
                val oldPoint = Location("stored").apply {
                    latitude = old.getDouble("latitude"); longitude = old.getDouble("longitude")
                }
                if (oldPoint.distanceTo(point) < 150f &&
                    System.currentTimeMillis()-Instant.parse(previous.timestamp).toEpochMilli() < 60L*60_000L) return
            }
        }
        val metadata = JSONObject().put("latitude",point.latitude).put("longitude",point.longitude)
            .put("accuracy_m",point.accuracy).put("provider",point.provider)
        val id = UUID.nameUUIDFromBytes("location:${point.time}:${point.latitude}:${point.longitude}".toByteArray(StandardCharsets.UTF_8)).toString()
        TrackerDatabase.get(context).dao().insert(TrackerEvent(id,Instant.ofEpochMilli(point.time).toString(),
            "location",metadataJson=metadata.toString()))
    }
}

class PackageCollector : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val pkg = intent.data?.schemeSpecificPart ?: return
        if (intent.getBooleanExtra(Intent.EXTRA_REPLACING,false)) return
        val type = when (intent.action) {
            Intent.ACTION_PACKAGE_ADDED -> "app_installed"
            Intent.ACTION_PACKAGE_REMOVED -> "app_removed"
            else -> return
        }
        val pending = goAsync()
        CoroutineScope(Dispatchers.IO).launch {
            try {
                if (type == "app_installed") AppIconRegistry.register(context,pkg,pkg)
                TrackerDatabase.get(context).dao().insert(TrackerEvent(UUID.randomUUID().toString(),
                    Instant.now().toString(),type,pkg,pkg))
                SyncScheduler.immediate(context)
            } finally { pending.finish() }
        }
    }
}
