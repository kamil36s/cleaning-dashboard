package com.cleaningdashboard.phonetelemetry.export

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import androidx.work.workDataOf
import com.cleaningdashboard.phonetelemetry.data.UsageRepository
import com.cleaningdashboard.phonetelemetry.data.local.TelemetryDatabase
import com.cleaningdashboard.phonetelemetry.permissions.UsageAccessHelper
import java.time.LocalDate
import java.time.ZoneId

class ExportWorker(
    appContext: Context,
    params: WorkerParameters,
) : CoroutineWorker(appContext, params) {
    override suspend fun doWork(): Result {
        if (!UsageAccessHelper.hasUsageAccess(applicationContext)) {
            // Without usage access, the export will be incomplete.
            return Result.retry()
        }

        val targetDay = LocalDate.now(ZoneId.systemDefault()).minusDays(1)
        val targetDayKey = targetDay.toString()

        val repository = UsageRepository(applicationContext)
        repository.collectAndPersistDay(targetDay)

        val dao = TelemetryDatabase.getInstance(applicationContext).telemetryDao()
        val exportSerializer = ExportSerializer(applicationContext)
        val exportWriter = MediaStoreExportWriter(applicationContext)

        val exportFile = exportSerializer.buildDailyExport(
            day = targetDayKey,
            appUsageSessions = dao.getAppUsageSessionsForDay(targetDayKey),
            phoneSessions = dao.getPhoneSessionsForDay(targetDayKey),
            notificationEvents = dao.getNotificationEventsForDay(targetDayKey),
            storeNotificationText = true,
        )

        val fileName = "phone-telemetry-$targetDayKey.json"
        exportWriter.writeJsonFile(fileName, exportSerializer.serialize(exportFile))

        return Result.success(
            workDataOf(
                "exportDay" to targetDayKey,
                "fileName" to fileName,
            )
        )
    }
}
