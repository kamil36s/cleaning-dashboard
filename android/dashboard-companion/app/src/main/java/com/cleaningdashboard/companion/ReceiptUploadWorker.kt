package com.cleaningdashboard.companion

import android.content.Context
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

class ReceiptUploadWorker(context: Context, parameters: WorkerParameters) : CoroutineWorker(context, parameters) {
    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        val config = CompanionConfig.load(applicationContext)
        if (!config.configured) return@withContext Result.failure()
        val queue = ReceiptQueue(applicationContext)
        var item = queue.nextPending()
        while (item != null) {
            try {
                queue.transition(item.id, UploadState.UPLOADING)
                val uploaded = DashboardClient.upload(config, item)
                queue.transition(
                    item.id, UploadState.UPLOADED, receiptId = uploaded.receiptId,
                    resultSummary = uploaded.summary(),
                )
            } catch (error: Exception) {
                queue.transition(item.id, UploadState.FAILED, error = error.message ?: "Błąd synchronizacji")
                return@withContext if (runAttemptCount < 4) Result.retry() else Result.failure()
            }
            item = queue.nextPending()
        }
        Result.success()
    }
}

object CompanionSync {
    private const val WORK_NAME = "dashboard-companion-receipt-sync"

    fun schedule(context: Context) {
        val request = OneTimeWorkRequestBuilder<ReceiptUploadWorker>()
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
            .build()
        WorkManager.getInstance(context).enqueueUniqueWork(WORK_NAME, ExistingWorkPolicy.KEEP, request)
    }

    fun retry(context: Context) {
        ReceiptQueue(context).retryFailed()
        val request = OneTimeWorkRequestBuilder<ReceiptUploadWorker>()
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
            .build()
        WorkManager.getInstance(context).enqueueUniqueWork(WORK_NAME, ExistingWorkPolicy.REPLACE, request)
    }
}
