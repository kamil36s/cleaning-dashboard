package com.cleaningdashboard.stepssync

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import java.time.LocalDate
import java.time.ZoneId

class DashboardStepsSyncWorker(
    appContext: Context,
    params: WorkerParameters,
) : CoroutineWorker(appContext, params) {
    override suspend fun doWork(): Result {
        if (!HealthConnectStepsRepository.isAvailable(applicationContext)) return Result.retry()

        return try {
            val repository = HealthConnectStepsRepository(applicationContext)
            if (!repository.hasRequiredPermissions()) return Result.retry()

            val zone = ZoneId.systemDefault()
            val day = LocalDate.now(zone)
            val baseUrl = DashboardConfig.getBaseUrl(applicationContext)
            val token = DashboardConfig.getToken(applicationContext)
            val exclusions = DashboardClient.getStepExclusions(baseUrl, token, day)
            val snapshot = HealthSnapshotRepository(applicationContext).readTodaySnapshot(day, zone)

            if (!exclusions.active) {
                val aggregation = repository.readStepsForDayExcluding(day, zone, exclusions.intervals)
                DashboardClient.postSteps(
                    baseUrl = baseUrl,
                    token = token,
                    day = day,
                    steps = aggregation.steps,
                    rawSteps = aggregation.rawSteps,
                    excludedSteps = aggregation.excludedSteps,
                    capturedAt = aggregation.capturedAt.toString(),
                    excludedIntervals = exclusions.intervals,
                )
            }
            DashboardClient.postHealthSnapshot(
                baseUrl = baseUrl,
                token = token,
                payload = snapshot,
            )
            Result.success()
        } catch (_: Exception) {
            Result.retry()
        }
    }
}
