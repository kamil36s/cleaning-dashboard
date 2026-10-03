package com.cleaningdashboard.phonetracker

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/** Restore periodic collection and the visible blocker health check after a reboot. */
class TrackerBootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Intent.ACTION_BOOT_COMPLETED) return
        SyncScheduler.periodic(context)
        SyncScheduler.immediate(context)
        GuardService.start(context)
    }
}
