package com.cleaningdashboard.stepssync

import android.content.Context
import androidx.work.Constraints
import androidx.work.Data
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import java.util.concurrent.TimeUnit

fun scheduleStepsSync(
    context: Context,
    dashboardBaseUrl: String,
    dashboardToken: String,
) {
    val input = Data.Builder()
        .putString(DashboardStepsSyncWorker.KEY_DASHBOARD_BASE_URL, dashboardBaseUrl)
        .putString(DashboardStepsSyncWorker.KEY_DASHBOARD_TOKEN, dashboardToken)
        .build()

    val request = PeriodicWorkRequestBuilder<DashboardStepsSyncWorker>(15, TimeUnit.MINUTES)
        .setInputData(input)
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
