package com.cleaningdashboard.phonetelemetry.data.local

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Transaction

@Dao
interface TelemetryDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertAppUsageSessions(items: List<AppUsageSessionEntity>)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertPhoneSessions(items: List<PhoneSessionEntity>)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertNotificationEvents(items: List<NotificationEventEntity>)

    @Query("DELETE FROM app_usage_sessions WHERE day = :day")
    suspend fun deleteAppUsageSessionsForDay(day: String)

    @Query("DELETE FROM phone_sessions WHERE day = :day")
    suspend fun deletePhoneSessionsForDay(day: String)

    @Query("SELECT * FROM app_usage_sessions WHERE day = :day ORDER BY sessionStart ASC")
    suspend fun getAppUsageSessionsForDay(day: String): List<AppUsageSessionEntity>

    @Query("SELECT * FROM phone_sessions WHERE day = :day ORDER BY screenUnlockTime ASC")
    suspend fun getPhoneSessionsForDay(day: String): List<PhoneSessionEntity>

    @Query("SELECT * FROM notification_events WHERE day = :day ORDER BY timestamp ASC")
    suspend fun getNotificationEventsForDay(day: String): List<NotificationEventEntity>

    @Transaction
    suspend fun replaceUsageCaptureForDay(
        day: String,
        appUsageSessions: List<AppUsageSessionEntity>,
        phoneSessions: List<PhoneSessionEntity>,
    ) {
        deleteAppUsageSessionsForDay(day)
        deletePhoneSessionsForDay(day)
        insertAppUsageSessions(appUsageSessions)
        insertPhoneSessions(phoneSessions)
    }
}
