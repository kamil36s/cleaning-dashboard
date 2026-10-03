package com.cleaningdashboard.phonetracker

import android.content.Context
import androidx.room.Dao
import androidx.room.Database
import androidx.room.Entity
import androidx.room.Index
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.PrimaryKey
import androidx.room.Query
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase

@Entity(tableName = "events", indices = [Index("timestamp"), Index("syncedAt")])
data class TrackerEvent(
    @PrimaryKey val eventId: String,
    val timestamp: String,
    val eventType: String,
    val packageName: String? = null,
    val appName: String? = null,
    val metadataJson: String = "{}",
    val syncedAt: String? = null,
    val rejectedReason: String? = null,
)

@Entity(tableName = "app_registry")
data class AppRegistryEntry(
    @PrimaryKey val packageName: String,
    val appName: String,
    val iconBase64: String?,
    val syncedAt: String? = null,
)

@Dao
interface TrackerDao {
    @Insert(onConflict = OnConflictStrategy.IGNORE)
    suspend fun insert(event: TrackerEvent)

    @Insert(onConflict = OnConflictStrategy.IGNORE)
    suspend fun insertMany(events: List<TrackerEvent>)

    @Query("SELECT * FROM events WHERE syncedAt IS NULL AND rejectedReason IS NULL ORDER BY timestamp,eventId LIMIT :limit")
    suspend fun pending(limit: Int): List<TrackerEvent>

    @Query("UPDATE events SET syncedAt=:at WHERE eventId IN (:ids) AND syncedAt IS NULL")
    suspend fun acknowledge(ids: List<String>, at: String)

    @Query("SELECT COUNT(*) FROM events WHERE syncedAt IS NULL AND rejectedReason IS NULL")
    suspend fun pendingCount(): Int

    @Query("UPDATE events SET rejectedReason=:reason WHERE eventId=:id AND syncedAt IS NULL")
    suspend fun reject(id: String, reason: String)

    @Query("SELECT COUNT(*) FROM events WHERE rejectedReason IS NOT NULL")
    suspend fun rejectedCount(): Int

    @Query("SELECT MAX(timestamp) FROM events")
    suspend fun lastEvent(): String?

    @Query("SELECT MAX(timestamp) FROM events WHERE eventType=:eventType")
    suspend fun lastOfType(eventType: String): String?

    @Query("SELECT * FROM events WHERE timestamp>=:start AND eventType IN ('app_foreground','app_background','screen_off') ORDER BY timestamp,eventId")
    suspend fun usageSince(start: String): List<TrackerEvent>

    @Query("SELECT * FROM events WHERE eventType='location' ORDER BY timestamp DESC LIMIT 1")
    suspend fun lastLocation(): TrackerEvent?

    @Query("SELECT * FROM events WHERE eventType='notification_posted' AND timestamp<:cutoff AND (metadataJson LIKE '%\"title\"%' OR metadataJson LIKE '%\"text\"%') ORDER BY timestamp LIMIT 500")
    suspend fun oldNotifications(cutoff: String): List<TrackerEvent>

    @Query("UPDATE events SET metadataJson=:metadata WHERE eventId=:id")
    suspend fun updateMetadata(id: String, metadata: String)

    @Insert(onConflict = OnConflictStrategy.IGNORE)
    suspend fun registerApp(entry: AppRegistryEntry)

    @Query("SELECT COUNT(*) FROM app_registry WHERE packageName=:packageName")
    suspend fun hasApp(packageName: String): Int

    @Query("SELECT * FROM app_registry WHERE syncedAt IS NULL ORDER BY packageName LIMIT :limit")
    suspend fun pendingApps(limit: Int): List<AppRegistryEntry>

    @Query("UPDATE app_registry SET syncedAt=:at WHERE packageName IN (:packages)")
    suspend fun acknowledgeApps(packages: List<String>, at: String)
}

@Database(entities = [TrackerEvent::class, AppRegistryEntry::class], version = 3, exportSchema = true)
abstract class TrackerDatabase : RoomDatabase() {
    abstract fun dao(): TrackerDao
    companion object {
        @Volatile private var instance: TrackerDatabase? = null
        private val migration1to2 = object : Migration(1, 2) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("ALTER TABLE events ADD COLUMN rejectedReason TEXT")
            }
        }
        private val migration2to3 = object : Migration(2, 3) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("CREATE TABLE IF NOT EXISTS app_registry (packageName TEXT NOT NULL PRIMARY KEY, appName TEXT NOT NULL, iconBase64 TEXT, syncedAt TEXT)")
            }
        }
        fun get(context: Context): TrackerDatabase = instance ?: synchronized(this) {
            instance ?: Room.databaseBuilder(context.applicationContext, TrackerDatabase::class.java,
                "phone-tracker.sqlite").addMigrations(migration1to2,migration2to3).build().also { instance = it }
        }
    }
}
