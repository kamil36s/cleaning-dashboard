package com.cleaningdashboard.phonetracker

import android.content.Context
import org.json.JSONObject
import java.time.Instant
import java.time.temporal.ChronoUnit

object LocalRetention {
    suspend fun prune(context: Context) {
        val days = RulesCache.read(context).optJSONObject("retention")
            ?.optInt("raw_notification_text_days",30)?.coerceIn(1,3650) ?: 30
        val cutoff = Instant.now().minus(days.toLong(),ChronoUnit.DAYS).toString()
        val dao = TrackerDatabase.get(context).dao()
        dao.oldNotifications(cutoff).forEach { event ->
            val metadata = JSONObject(event.metadataJson)
            metadata.remove("title")
            metadata.remove("text")
            dao.updateMetadata(event.eventId,metadata.toString())
        }
    }
}
