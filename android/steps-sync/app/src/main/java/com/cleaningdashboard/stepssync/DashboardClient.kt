package com.cleaningdashboard.stepssync

import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.time.LocalDate

data class StepExclusionInterval(
    val startMillis: Long,
    val endMillis: Long,
    val sessionId: String?,
    val status: String?,
    val workoutType: String?,
) {
    fun toJson(): JSONObject = JSONObject()
        .put("start", startMillis)
        .put("end", endMillis)
        .put("session_id", sessionId)
        .put("status", status)
        .put("workout_type", workoutType)
}

data class StepExclusions(
    val active: Boolean,
    val intervals: List<StepExclusionInterval>,
)

object DashboardClient {
    fun getStepExclusions(
        baseUrl: String,
        token: String,
        day: LocalDate,
    ): StepExclusions {
        val endpoint = "${baseUrl.trim().trimEnd('/')}/api/steps/exclusions?day=$day"
        val connection = (URL(endpoint).openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            connectTimeout = 10_000
            readTimeout = 10_000
            setRequestProperty("Authorization", "Bearer ${token.trim()}")
        }

        return try {
            val body = runCatching {
                val stream = if (connection.responseCode in 200..299) {
                    connection.inputStream
                } else {
                    connection.errorStream
                }
                stream?.bufferedReader()?.use { it.readText() }.orEmpty()
            }.getOrDefault("")
            if (connection.responseCode !in 200..299) {
                throw IllegalStateException("HTTP ${connection.responseCode}: $body")
            }
            val payload = JSONObject(body)
            val rawIntervals = payload.optJSONArray("intervals") ?: JSONArray()
            val intervals = buildList {
                for (index in 0 until rawIntervals.length()) {
                    val interval = rawIntervals.optJSONObject(index) ?: continue
                    val start = interval.optLong("start", -1L)
                    val end = interval.optLong("end", -1L)
                    if (start < 0L || end <= start) continue
                    add(
                        StepExclusionInterval(
                            startMillis = start,
                            endMillis = end,
                            sessionId = interval.optString("session_id").takeIf(String::isNotBlank),
                            status = interval.optString("status").takeIf(String::isNotBlank),
                            workoutType = interval.optString("workout_type").takeIf(String::isNotBlank),
                        ),
                    )
                }
            }
            StepExclusions(payload.optBoolean("active", false), intervals)
        } finally {
            connection.disconnect()
        }
    }

    fun postSteps(
        baseUrl: String,
        token: String,
        day: LocalDate,
        steps: Long,
        rawSteps: Long = steps,
        excludedSteps: Long = 0L,
        capturedAt: String? = null,
        excludedIntervals: List<StepExclusionInterval> = emptyList(),
        source: String = "health-connect",
    ): String {
        val payload = JSONObject()
            .put("day", day.toString())
            .put("steps", steps)
            .put("raw_steps", rawSteps)
            .put("excluded_steps", excludedSteps)
            .put("captured_at", capturedAt)
            .put("excluded_intervals", JSONArray().apply {
                excludedIntervals.forEach { put(it.toJson()) }
            })
            .put("source", source)
            .toString()

        val endpoint = "${baseUrl.trim().trimEnd('/')}/api/steps/events/upsert"
        val connection = (URL(endpoint).openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            connectTimeout = 10_000
            readTimeout = 10_000
            doOutput = true
            setRequestProperty("Authorization", "Bearer ${token.trim()}")
            setRequestProperty("Content-Type", "application/json; charset=utf-8")
        }

        return try {
            connection.outputStream.use { it.write(payload.toByteArray(Charsets.UTF_8)) }
            val body = runCatching {
                val stream = if (connection.responseCode in 200..299) {
                    connection.inputStream
                } else {
                    connection.errorStream
                }
                stream?.bufferedReader()?.use { it.readText() }.orEmpty()
            }.getOrDefault("")

            if (connection.responseCode !in 200..299) {
                throw IllegalStateException("HTTP ${connection.responseCode}: $body")
            }
            body
        } finally {
            connection.disconnect()
        }
    }

    fun postHealthSnapshot(
        baseUrl: String,
        token: String,
        payload: JSONObject,
    ): String {
        val endpoint = "${baseUrl.trim().trimEnd('/')}/api/health-connect/snapshot"
        val connection = (URL(endpoint).openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            connectTimeout = 10_000
            readTimeout = 20_000
            doOutput = true
            setRequestProperty("Authorization", "Bearer ${token.trim()}")
            setRequestProperty("Content-Type", "application/json; charset=utf-8")
        }

        return try {
            connection.outputStream.use { it.write(payload.toString().toByteArray(Charsets.UTF_8)) }
            val body = runCatching {
                val stream = if (connection.responseCode in 200..299) connection.inputStream else connection.errorStream
                stream?.bufferedReader()?.use { it.readText() }.orEmpty()
            }.getOrDefault("")

            if (connection.responseCode !in 200..299) {
                throw IllegalStateException("HTTP ${connection.responseCode}: $body")
            }
            body
        } finally {
            connection.disconnect()
        }
    }
}
