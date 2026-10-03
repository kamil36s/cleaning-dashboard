package com.cleaningdashboard.stepssync

import android.content.Context
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.records.ActiveCaloriesBurnedRecord
import androidx.health.connect.client.records.DistanceRecord
import androidx.health.connect.client.records.ElevationGainedRecord
import androidx.health.connect.client.records.ExerciseRouteResult
import androidx.health.connect.client.records.ExerciseSessionRecord
import androidx.health.connect.client.records.HeartRateRecord
import androidx.health.connect.client.records.OxygenSaturationRecord
import androidx.health.connect.client.records.SleepSessionRecord
import androidx.health.connect.client.records.SpeedRecord
import androidx.health.connect.client.records.StepsRecord
import androidx.health.connect.client.records.metadata.Metadata
import androidx.health.connect.client.request.AggregateRequest
import androidx.health.connect.client.request.ReadRecordsRequest
import androidx.health.connect.client.time.TimeRangeFilter
import org.json.JSONArray
import org.json.JSONObject
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId

class HealthSnapshotRepository(context: Context) {
    private val client = HealthConnectClient.getOrCreate(context)

    suspend fun hasRequiredPermissions(): Boolean {
        return client.permissionController.getGrantedPermissions().containsAll(DATA_PERMISSIONS)
    }

    suspend fun readTodaySnapshot(
        day: LocalDate = LocalDate.now(),
        zone: ZoneId = ZoneId.systemDefault(),
    ): JSONObject {
        val start = day.atStartOfDay(zone).toInstant()
        val end = if (day == LocalDate.now(zone)) Instant.now() else day.plusDays(1).atStartOfDay(zone).toInstant()
        val range = TimeRangeFilter.between(start, end)

        return JSONObject()
            .put("source", "health-connect")
            .put("day", day.toString())
            .put("timezone", zone.id)
            .put("window_start", start.toString())
            .put("window_end", end.toString())
            .put("metrics", readAggregateMetrics(range))
            .put("heart_rate", readHeartRate(range))
            .put("oxygen_saturation", readOxygenSaturation(range))
            .put("speed", readSpeed(range))
            .put("sleep", readSleep(range))
            .put("exercise", readExercise(range))
    }

    private suspend fun readAggregateMetrics(range: TimeRangeFilter): JSONObject {
        return runCatching {
            val response = client.aggregate(
                AggregateRequest(
                    metrics = setOf(
                        StepsRecord.COUNT_TOTAL,
                        ActiveCaloriesBurnedRecord.ACTIVE_CALORIES_TOTAL,
                        DistanceRecord.DISTANCE_TOTAL,
                        ElevationGainedRecord.ELEVATION_GAINED_TOTAL,
                    ),
                    timeRangeFilter = range,
                ),
            )

            JSONObject()
                .put("steps", response[StepsRecord.COUNT_TOTAL] ?: 0L)
                .put("active_calories_kcal", response[ActiveCaloriesBurnedRecord.ACTIVE_CALORIES_TOTAL]?.inKilocalories)
                .put("distance_meters", response[DistanceRecord.DISTANCE_TOTAL]?.inMeters)
                .put("elevation_gained_meters", response[ElevationGainedRecord.ELEVATION_GAINED_TOTAL]?.inMeters)
        }.getOrElse { errorJson(it) }
    }

    private suspend fun readHeartRate(range: TimeRangeFilter): JSONObject {
        return runCatching {
            val records = client.readRecords(
                ReadRecordsRequest<HeartRateRecord>(timeRangeFilter = range),
            ).records
            val samples = records.flatMap { record ->
                record.samples.map { sample ->
                    JSONObject()
                        .put("time", sample.time.toString())
                        .put("bpm", sample.beatsPerMinute)
                        .putRecordMetadata(record.metadata)
                }
            }
            val bpms = samples.map { it.getLong("bpm") }
            JSONObject()
                .put("sample_count", samples.size)
                .put("min_bpm", bpms.minOrNull())
                .put("max_bpm", bpms.maxOrNull())
                .put("avg_bpm", bpms.takeIf { it.isNotEmpty() }?.average())
                .put("samples", JSONArray(samples.takeLast(500)))
        }.getOrElse { errorJson(it) }
    }

    private suspend fun readOxygenSaturation(range: TimeRangeFilter): JSONObject {
        return runCatching {
            val records = client.readRecords(
                ReadRecordsRequest<OxygenSaturationRecord>(timeRangeFilter = range),
            ).records
            val samples = records.map { record ->
                JSONObject()
                    .put("time", record.time.toString())
                    .put("percentage", record.percentage.value)
            }
            val values = samples.map { it.getDouble("percentage") }
            JSONObject()
                .put("sample_count", samples.size)
                .put("min_percentage", values.minOrNull())
                .put("max_percentage", values.maxOrNull())
                .put("avg_percentage", values.takeIf { it.isNotEmpty() }?.average())
                .put("samples", JSONArray(samples.takeLast(500)))
        }.getOrElse { errorJson(it) }
    }

    private suspend fun readSpeed(range: TimeRangeFilter): JSONObject {
        return runCatching {
            val records = client.readRecords(
                ReadRecordsRequest<SpeedRecord>(timeRangeFilter = range),
            ).records
            val samples = records.flatMap { record ->
                record.samples.map { sample ->
                    JSONObject()
                        .put("time", sample.time.toString())
                        .put("meters_per_second", sample.speed.inMetersPerSecond)
                }
            }
            val values = samples.map { it.getDouble("meters_per_second") }
            JSONObject()
                .put("sample_count", samples.size)
                .put("max_meters_per_second", values.maxOrNull())
                .put("avg_meters_per_second", values.takeIf { it.isNotEmpty() }?.average())
                .put("samples", JSONArray(samples.takeLast(500)))
        }.getOrElse { errorJson(it) }
    }

    private suspend fun readSleep(range: TimeRangeFilter): JSONObject {
        return runCatching {
            val records = client.readRecords(
                ReadRecordsRequest<SleepSessionRecord>(timeRangeFilter = range),
            ).records
            val sessions = records.map { record ->
                JSONObject()
                    .put("start", record.startTime.toString())
                    .put("end", record.endTime.toString())
                    .put("title", record.title)
                    .put("notes", record.notes)
                    .putRecordMetadata(record.metadata)
                    .put("stages", JSONArray(record.stages.map { stage ->
                        JSONObject()
                            .put("start", stage.startTime.toString())
                            .put("end", stage.endTime.toString())
                            .put("type", stage.stage)
                    }))
            }
            JSONObject()
                .put("session_count", sessions.size)
                .put("sessions", JSONArray(sessions))
        }.getOrElse { errorJson(it) }
    }

    private suspend fun readExercise(range: TimeRangeFilter): JSONObject {
        return runCatching {
            val records = client.readRecords(
                ReadRecordsRequest<ExerciseSessionRecord>(timeRangeFilter = range),
            ).records
            val sessions = records.map { record ->
                val route = when (val result = record.exerciseRouteResult) {
                    is ExerciseRouteResult.Data -> JSONObject()
                        .put("status", "data")
                        .put("point_count", result.exerciseRoute.route.size)
                        .put("points", JSONArray(result.exerciseRoute.route.take(1000).map { point ->
                            JSONObject()
                                .put("time", point.time.toString())
                                .put("latitude", point.latitude)
                                .put("longitude", point.longitude)
                                .put("altitude_meters", point.altitude?.inMeters)
                                .put("horizontal_accuracy_meters", point.horizontalAccuracy?.inMeters)
                                .put("vertical_accuracy_meters", point.verticalAccuracy?.inMeters)
                        }))
                    is ExerciseRouteResult.ConsentRequired -> JSONObject().put("status", "consent_required")
                    is ExerciseRouteResult.NoData -> JSONObject().put("status", "no_data")
                    else -> JSONObject().put("status", "unknown")
                }

                JSONObject()
                    .put("id", record.metadata.id)
                    .put("start", record.startTime.toString())
                    .put("end", record.endTime.toString())
                    .put("exercise_type", record.exerciseType)
                    .put("title", record.title)
                    .put("notes", record.notes)
                    .put("route", route)
                    .put("segment_count", record.segments.size)
                    .put("lap_count", record.laps.size)
            }
            JSONObject()
                .put("session_count", sessions.size)
                .put("sessions", JSONArray(sessions))
        }.getOrElse { errorJson(it) }
    }

    private fun errorJson(error: Throwable): JSONObject {
        return JSONObject()
            .put("error", error.message ?: error::class.java.simpleName)
    }

    private fun JSONObject.putRecordMetadata(metadata: Metadata): JSONObject = apply {
        put("record_id", metadata.id)
        put("data_origin", metadata.dataOrigin.packageName)
        put("recording_method", metadata.recordingMethod)
        metadata.device?.let { device ->
            put("device_type", device.type)
            device.manufacturer?.let { put("manufacturer", it) }
            device.model?.let { put("model", it) }
        }
    }

    companion object {
        private const val READ_HEALTH_DATA_IN_BACKGROUND = "android.permission.health.READ_HEALTH_DATA_IN_BACKGROUND"

        val DATA_PERMISSIONS = setOf(
            HealthPermission.getReadPermission(StepsRecord::class),
            HealthPermission.getReadPermission(ActiveCaloriesBurnedRecord::class),
            HealthPermission.getReadPermission(DistanceRecord::class),
            HealthPermission.getReadPermission(ElevationGainedRecord::class),
            HealthPermission.getReadPermission(ExerciseSessionRecord::class),
            HealthPermission.getReadPermission(HeartRateRecord::class),
            HealthPermission.getReadPermission(OxygenSaturationRecord::class),
            HealthPermission.getReadPermission(SleepSessionRecord::class),
            HealthPermission.getReadPermission(SpeedRecord::class),
        )

        val REQUEST_PERMISSIONS = DATA_PERMISSIONS + READ_HEALTH_DATA_IN_BACKGROUND
    }
}
