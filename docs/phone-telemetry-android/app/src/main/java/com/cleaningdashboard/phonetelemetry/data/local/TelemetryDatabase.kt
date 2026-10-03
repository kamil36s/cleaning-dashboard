package com.cleaningdashboard.phonetelemetry.data.local

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase

@Database(
    entities = [
        AppUsageSessionEntity::class,
        PhoneSessionEntity::class,
        NotificationEventEntity::class,
    ],
    version = 1,
    exportSchema = true,
)
abstract class TelemetryDatabase : RoomDatabase() {
    abstract fun telemetryDao(): TelemetryDao

    companion object {
        @Volatile
        private var instance: TelemetryDatabase? = null

        fun getInstance(context: Context): TelemetryDatabase {
            return instance ?: synchronized(this) {
                instance ?: Room.databaseBuilder(
                    context.applicationContext,
                    TelemetryDatabase::class.java,
                    "phone_telemetry.db",
                ).build().also { built ->
                    instance = built
                }
            }
        }
    }
}
