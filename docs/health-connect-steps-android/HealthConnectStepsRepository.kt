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

class HealthConnectStepsRepository(context: Context) {
    private val client = HealthConnectClient.getOrCreate(context)

    val permissions = setOf(
        HealthPermission.getReadPermission(StepsRecord::class),
    )

    suspend fun hasRequiredPermissions(): Boolean {
        return client.permissionController.getGrantedPermissions().containsAll(permissions)
    }

    suspend fun readStepsForDay(
        day: LocalDate = LocalDate.now(),
        zone: ZoneId = ZoneId.systemDefault(),
    ): Long {
        val start = day.atStartOfDay(zone).toInstant()
        val end = if (day == LocalDate.now(zone)) {
            Instant.now()
        } else {
            day.plusDays(1).atStartOfDay(zone).toInstant()
        }

        val response = client.aggregate(
            AggregateRequest(
                metrics = setOf(StepsRecord.COUNT_TOTAL),
                timeRangeFilter = TimeRangeFilter.between(start, end),
            ),
        )

        return response[StepsRecord.COUNT_TOTAL] ?: 0L
    }
}
