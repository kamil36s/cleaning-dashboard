package com.cleaningdashboard.phonetracker

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import androidx.core.app.NotificationCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch

/** Keeps the blocker process alive when its Activity is closed and reports lost protection. */
class GuardService : Service() {
    private val handler = Handler(Looper.getMainLooper())
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val check = object : Runnable {
        override fun run() {
            RewardNotifier.blockerHealth(applicationContext)
            scope.launch {
                try { ManagedShortcuts.updateFromConfig(applicationContext,RulesCache.read(applicationContext)) }
                catch (_: Exception) { }
                NotificationCollector.reconcileBlocked()
            }
            handler.postDelayed(this,60_000)
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel("phone_tracker_guard",
            "Phone Tracker protection",NotificationManager.IMPORTANCE_LOW))
        val open = PendingIntent.getActivity(this,0,Intent(this,MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val notification: Notification = NotificationCompat.Builder(this,"phone_tracker_guard")
            .setSmallIcon(R.drawable.ic_tracker_mark)
            .setContentTitle("Phone Tracker protection")
            .setContentText("App limits run while Phone Tracker is closed")
            .setContentIntent(open).setOngoing(true).build()
        startForeground(10002,notification,ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        handler.removeCallbacks(check)
        handler.post(check)
        return START_STICKY
    }

    override fun onDestroy() {
        handler.removeCallbacks(check)
        scope.cancel()
        super.onDestroy()
    }

    companion object {
        fun start(context: Context) {
            try { context.startForegroundService(Intent(context,GuardService::class.java)) }
            catch (_: Exception) { /* Accessibility continues even if the OEM rejects a foreground service. */ }
        }
    }
}
