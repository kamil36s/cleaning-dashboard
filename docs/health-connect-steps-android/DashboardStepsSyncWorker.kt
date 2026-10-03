package com.cleaningdashboard.stepssync

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.time.LocalDate
import java.time.ZoneId

class DashboardStepsSyncWorker(
    appContext: Context,
    params: WorkerParameters,
) : CoroutineWorker(appContext, params) {
    override suspend fun doWork(): Result {
        val baseUrl = inputData.getString(KEY_DASHBOARD_BASE_URL)?.trimEnd('/')
        val token = inputData.getString(KEY_DASHBOARD_TOKEN).orEmpty()
        if (baseUrl.isNullOrBlank() || token.isBlank()) return Result.failure()

        val repository = HealthConnectStepsRepository(applicationContext)
        if (!repository.hasRequiredPermissions()) return Result.retry()

        val zone = ZoneId.systemDefault()
        val day = LocalDate.now(zone)
        val steps = repository.readStepsForDay(day, zone)

        val payload = JSONObject()
            .put("day", day.toString())
            .put("steps", steps)
            .put("source", "health-connect")

        return postJson("$baseUrl/api/steps/events/upsert", token, payload.toString())
    }

    private fun postJson(endpoint: String, token: String, payload: String): Result {
        val connection = (URL(endpoint).openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            connectTimeout = 10_000
            readTimeout = 10_000
            doOutput = true
            setRequestProperty("Authorization", "Bearer $token")
            setRequestProperty("Content-Type", "application/json; charset=utf-8")
        }

        return try {
            connection.outputStream.use { it.write(payload.toByteArray(Charsets.UTF_8)) }
            val code = connection.responseCode
            if (code in 200..299) Result.success() else Result.retry()
        } catch (_: Exception) {
            Result.retry()
        } finally {
            connection.disconnect()
        }
    }

    companion object {
        const val KEY_DASHBOARD_BASE_URL = "dashboard_base_url"
        const val KEY_DASHBOARD_TOKEN = "dashboard_token"
    }
}
