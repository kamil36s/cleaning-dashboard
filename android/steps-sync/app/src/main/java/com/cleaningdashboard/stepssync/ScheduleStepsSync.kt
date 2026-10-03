package com.cleaningdashboard.stepssync

import android.content.Context
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import java.util.concurrent.TimeUnit

fun scheduleStepsSync(context: Context) {
    val request = PeriodicWorkRequestBuilder<DashboardStepsSyncWorker>(15, TimeUnit.MINUTES)
        .setConstraints(
            Constraints.Builder()
                .setRequiredNetworkType(NetworkType.CONNECTED)
                .build(),
        )
        .build()

    WorkManager.getInstance(context).enqueueUniquePeriodicWork(
        "dashboard-steps-sync",
        ExistingPeriodicWorkPolicy.UPDATE,
        request,
    )
}
