package com.cleaningdashboard.phonetelemetry.notifications

import android.app.Notification
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import com.cleaningdashboard.phonetelemetry.data.local.NotificationEventEntity
import com.cleaningdashboard.phonetelemetry.data.local.TelemetryDatabase
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.UUID

class NotificationCaptureService : NotificationListenerService() {
    private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    override fun onDestroy() {
        super.onDestroy()
        serviceScope.cancel()
    }

    override fun onNotificationPosted(sbn: StatusBarNotification?) {
        if (sbn == null) return

        val extras = sbn.notification.extras
        val timestamp = Instant.ofEpochMilli(sbn.postTime)
        val zonedTimestamp = timestamp.atZone(ZoneId.systemDefault())
        val day = zonedTimestamp.toLocalDate().toString()

        val title = extras.getCharSequence(Notification.EXTRA_TITLE)?.toString()
        val text = extras.getCharSequence(Notification.EXTRA_TEXT)?.toString()
        val textLines = extras.getCharSequenceArray(Notification.EXTRA_TEXT_LINES)
        val messageCount = textLines?.size?.takeIf { it > 0 } ?: 1
        val isMessageLike = isMessageLikeNotification(sbn)
        val conversationId = sbn.notification.shortcutId ?: sbn.overrideGroupKey ?: sbn.groupKey

        val entity = NotificationEventEntity(
            id = UUID.randomUUID().toString(),
            day = day,
            timestamp = zonedTimestamp.format(DateTimeFormatter.ISO_OFFSET_DATE_TIME),
            sourceAppPackage = sbn.packageName,
            sourceAppLabel = resolveAppLabel(sbn.packageName),
            senderOrThreadTitle = title,
            conversationId = conversationId,
            previewAvailable = !text.isNullOrBlank(),
            messageCount = messageCount,
            isGroup = sbn.isGroup,
            eventSource = "notification",
            messageLike = isMessageLike,
            rawTitle = title,
            rawText = text,
        )

        serviceScope.launch {
            TelemetryDatabase.getInstance(applicationContext)
                .telemetryDao()
                .insertNotificationEvents(listOf(entity))
        }
    }

    private fun isMessageLikeNotification(sbn: StatusBarNotification): Boolean {
        val category = sbn.notification.category
        if (category == Notification.CATEGORY_MESSAGE) return true

        val extras = sbn.notification.extras
        val people = extras.getStringArray(Notification.EXTRA_PEOPLE)
        val messagingText = extras.getCharSequenceArray(Notification.EXTRA_TEXT_LINES)
        return !people.isNullOrEmpty() || !messagingText.isNullOrEmpty()
    }

    private fun resolveAppLabel(packageName: String): String {
        return runCatching {
            val packageInfo = packageManager.getApplicationInfo(packageName, 0)
            packageManager.getApplicationLabel(packageInfo).toString()
        }.getOrDefault(packageName)
    }
}
