package com.cleaningdashboard.howifeel

import org.json.JSONArray
import org.json.JSONObject

data class Emotion(
    val id: String,
    val name: String,
    val description: String,
    val quadrant: String,
    val color: String,
    val x: Int,
    val y: Int,
    val shape: String,
    val meter: Boolean,
) {
    fun toJson() = JSONObject()
        .put("id", id).put("name", name).put("description", description)
        .put("quadrant", quadrant).put("color", color).put("x", x).put("y", y)
        .put("shape", shape).put("meter", meter)

    companion object {
        fun fromJson(value: JSONObject): Emotion {
            val x = value.optDouble("x", -1.0)
            val y = value.optDouble("y", -1.0)
            val canonical = x >= 0 && x < 12 && y >= 0 && y < 12 && x % 1.0 == 0.0 && y % 1.0 == 0.0
            return Emotion(
                id = value.optString("id"),
                name = value.optString("name"),
                description = value.optString("description"),
                quadrant = value.optString("quadrant"),
                color = value.optString("color", "#777777"),
                x = x.toInt(), y = y.toInt(),
                shape = value.optString("shape", "circle"),
                meter = if (value.has("meter")) value.optBoolean("meter") else canonical,
            )
        }
    }
}

data class FeelingTag(val id: String, val name: String, val category: String) {
    fun toJson() = JSONObject().put("id", id).put("name", name).put("category", category)
    companion object {
        fun fromJson(value: JSONObject) = FeelingTag(
            value.optString("id"), value.optString("name"), value.optString("category"),
        )
    }
}

data class CheckinSummary(
    val id: String,
    val occurredAt: String,
    val emotionName: String,
    val emotionColor: String,
    val tags: List<String>,
    val note: String,
) {
    companion object {
        fun fromJson(value: JSONObject): CheckinSummary {
            val emotion = value.optJSONObject("emotion") ?: JSONObject()
            val rawTags = value.optJSONArray("tags") ?: JSONArray()
            return CheckinSummary(
                id = value.optString("id"),
                occurredAt = value.optString("occurredAt"),
                emotionName = emotion.optString("name", "Unknown"),
                emotionColor = emotion.optString("color", "#777777"),
                tags = buildList {
                    for (index in 0 until rawTags.length()) add(rawTags.optJSONObject(index)?.optString("name").orEmpty())
                }.filter(String::isNotBlank),
                note = value.optString("note"),
            )
        }
    }
}

data class PendingCheckin(
    val id: String,
    val emotionId: String,
    val tagNames: List<String>,
    val note: String,
    val occurredAt: String,
) {
    fun toJson() = JSONObject()
        .put("id", id)
        .put("emotionIds", JSONArray().put(emotionId))
        .put("tags", JSONArray(tagNames))
        .put("note", note)
        .put("occurredAt", occurredAt)
        .put("timezone", "Europe/Warsaw")
        .put("source", "android-how-i-feel")
        .put("sourceDevice", android.os.Build.MODEL)
        .put("syncId", id)
        .put("schemaVersion", 1)

    companion object {
        fun fromJson(value: JSONObject): PendingCheckin {
            val emotions = value.optJSONArray("emotionIds") ?: JSONArray()
            val tags = value.optJSONArray("tags") ?: JSONArray()
            return PendingCheckin(
                id = value.optString("id"),
                emotionId = emotions.optString(0),
                tagNames = buildList { for (index in 0 until tags.length()) add(tags.optString(index)) },
                note = value.optString("note"),
                occurredAt = value.optString("occurredAt"),
            )
        }
    }
}
