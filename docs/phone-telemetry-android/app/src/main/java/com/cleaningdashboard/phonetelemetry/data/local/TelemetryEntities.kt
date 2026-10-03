package com.cleaningdashboard.phonetelemetry.data.local

import androidx.room.Entity
import androidx.room.PrimaryKey

@Entity(tableName = "app_usage_sessions")
data class AppUsageSessionEntity(
    @PrimaryKey val id: String,
    val day: String,
    val appPackage: String,
    val appLabel: String,
    val sessionStart: String,
    val sessionEnd: String,
    val durationSeconds: Long,
    val category: String,
    val unlockSessionId: String?,
)

@Entity(tableName = "phone_sessions")
data class PhoneSessionEntity(
    @PrimaryKey val id: String,
    val day: String,
    val screenUnlockTime: String,
    val screenLockTime: String,
    val durationSeconds: Long,
)

@Entity(tableName = "notification_events")
data class NotificationEventEntity(
    @PrimaryKey val id: String,
    val day: String,
    val timestamp: String,
    val sourceAppPackage: String,
    val sourceAppLabel: String,
    val senderOrThreadTitle: String?,
    val conversationId: String?,
    val previewAvailable: Boolean,
    val messageCount: Int,
    val isGroup: Boolean,
    val eventSource: String,
    val messageLike: Boolean,
    val rawTitle: String?,
    val rawText: String?,
)
