package com.cleaningdashboard.stepssync

import android.content.Context
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.records.StepsRecord
import androidx.health.connect.client.request.AggregateRequest
import androidx.health.connect.client.time.TimeRangeFilter
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId

data class StepAggregation(
    val steps: Long,
    val rawSteps: Long,
    val excludedSteps: Long,
    val capturedAt: Instant,
)

class HealthConnectStepsRepository(context: Context) {
    private val client = HealthConnectClient.getOrCreate(context)

    suspend fun hasRequiredPermissions(): Boolean {
        return client.permissionController.getGrantedPermissions().containsAll(PERMISSIONS)
    }

    suspend fun readStepsForDay(
        day: LocalDate = LocalDate.now(),
        zone: ZoneId = ZoneId.systemDefault(),
    ): Long = readStepsForDayExcluding(day, zone, emptyList()).steps

    suspend fun readStepsForDayExcluding(
        day: LocalDate = LocalDate.now(),
        zone: ZoneId = ZoneId.systemDefault(),
        excludedIntervals: List<StepExclusionInterval>,
    ): StepAggregation {
        val start = day.atStartOfDay(zone).toInstant()
        val end = if (day == LocalDate.now(zone)) {
            Instant.now()
        } else {
            day.plusDays(1).atStartOfDay(zone).toInstant()
        }
        val capturedAt = Instant.now()
        val rawSteps = aggregateSteps(start, end)
        val mergedExclusions = mergeExclusions(excludedIntervals, start, end)
        if (mergedExclusions.isEmpty()) {
            return StepAggregation(rawSteps, rawSteps, 0L, capturedAt)
        }

        var cursor = start
        var countedSteps = 0L
        mergedExclusions.forEach { (excludedStart, excludedEnd) ->
            if (cursor < excludedStart) countedSteps += aggregateSteps(cursor, excludedStart)
            if (cursor < excludedEnd) cursor = excludedEnd
        }
        if (cursor < end) countedSteps += aggregateSteps(cursor, end)
        countedSteps = countedSteps.coerceIn(0L, rawSteps)

        return StepAggregation(
            steps = countedSteps,
            rawSteps = rawSteps,
            excludedSteps = (rawSteps - countedSteps).coerceAtLeast(0L),
            capturedAt = capturedAt,
        )
    }

    private suspend fun aggregateSteps(start: Instant, end: Instant): Long {
        val response = client.aggregate(
            AggregateRequest(
                metrics = setOf(StepsRecord.COUNT_TOTAL),
                timeRangeFilter = TimeRangeFilter.between(start, end),
            ),
        )

        return response[StepsRecord.COUNT_TOTAL] ?: 0L
    }

    private fun mergeExclusions(
        intervals: List<StepExclusionInterval>,
        rangeStart: Instant,
        rangeEnd: Instant,
    ): List<Pair<Instant, Instant>> {
        val clipped = intervals.mapNotNull { interval ->
            val start = maxOf(rangeStart, Instant.ofEpochMilli(interval.startMillis))
            val end = minOf(rangeEnd, Instant.ofEpochMilli(interval.endMillis))
            if (start < end) start to end else null
        }.sortedBy { it.first }
        if (clipped.isEmpty()) return emptyList()

        val merged = mutableListOf(clipped.first())
        clipped.drop(1).forEach { next ->
            val current = merged.last()
            if (next.first <= current.second) {
                merged[merged.lastIndex] = current.first to maxOf(current.second, next.second)
            } else {
                merged += next
            }
        }
        return merged
    }

    companion object {
        val PERMISSIONS = HealthSnapshotRepository.DATA_PERMISSIONS

        fun isAvailable(context: Context): Boolean {
            return HealthConnectClient.getSdkStatus(context) == HealthConnectClient.SDK_AVAILABLE
        }
    }
}
