package com.cleaningdashboard.howifeel

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

class ApiException(val status: Int, message: String) : IllegalStateException(message)

class FeelingsClient(private val config: ServerConfig) {
    private fun request(path: String, method: String = "GET", body: JSONObject? = null): JSONObject {
        val connection = (URL("${config.baseUrl}/api/feelings$path").openConnection() as HttpURLConnection).apply {
            requestMethod = method
            connectTimeout = 10_000
            readTimeout = 15_000
            setRequestProperty("Authorization", "Bearer ${config.token}")
            setRequestProperty("Accept", "application/json")
            if (body != null) {
                doOutput = true
                setRequestProperty("Content-Type", "application/json; charset=utf-8")
            }
        }
        return try {
            if (body != null) connection.outputStream.use { it.write(body.toString().toByteArray()) }
            val status = connection.responseCode
            val stream = if (status in 200..299) connection.inputStream else connection.errorStream
            val text = stream?.bufferedReader()?.use { it.readText() }.orEmpty()
            val payload = runCatching { JSONObject(text) }.getOrDefault(JSONObject())
            if (status !in 200..299) throw ApiException(status, payload.optString("error", "HTTP $status"))
            payload
        } finally {
            connection.disconnect()
        }
    }

    fun emotions(): List<Emotion> {
        val values = request("/emotions").optJSONArray("emotions") ?: JSONArray()
        return buildList { for (index in 0 until values.length()) values.optJSONObject(index)?.let { add(Emotion.fromJson(it)) } }
            .filter { it.meter }.sortedWith(compareBy<Emotion> { it.y }.thenBy { it.x })
    }

    fun tags(): List<FeelingTag> {
        val values = request("/tags").optJSONArray("tags") ?: JSONArray()
        return buildList { for (index in 0 until values.length()) values.optJSONObject(index)?.let { add(FeelingTag.fromJson(it)) } }
    }

    fun history(): List<CheckinSummary> {
        val values = request("/checkins?limit=50").optJSONArray("checkins") ?: JSONArray()
        return buildList { for (index in 0 until values.length()) values.optJSONObject(index)?.let { add(CheckinSummary.fromJson(it)) } }
    }

    fun create(checkin: PendingCheckin) = request("/checkins", "POST", checkin.toJson())
}

object LocalFeelingsStore {
    private const val PREFS = "how_i_feel_local"
    private const val EMOTIONS = "emotions"
    private const val TAGS = "tags"
    private const val PENDING = "pending"

    fun saveCatalog(context: Context, emotions: List<Emotion>, tags: List<FeelingTag>) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
            .putString(EMOTIONS, JSONArray().apply { emotions.forEach { put(it.toJson()) } }.toString())
            .putString(TAGS, JSONArray().apply { tags.forEach { put(it.toJson()) } }.toString())
            .apply()
    }

    fun emotions(context: Context): List<Emotion> = readArray(context, EMOTIONS).mapNotNull {
        runCatching { Emotion.fromJson(it) }.getOrNull()
    }

    fun tags(context: Context): List<FeelingTag> = readArray(context, TAGS).mapNotNull {
        runCatching { FeelingTag.fromJson(it) }.getOrNull()
    }

    fun pending(context: Context): MutableList<PendingCheckin> = readArray(context, PENDING).mapNotNull {
        runCatching { PendingCheckin.fromJson(it) }.getOrNull()
    }.toMutableList()

    fun enqueue(context: Context, checkin: PendingCheckin) {
        val pending = pending(context)
        if (pending.none { it.id == checkin.id }) pending.add(checkin)
        savePending(context, pending)
    }

    fun flush(context: Context, client: FeelingsClient): Int {
        val remaining = mutableListOf<PendingCheckin>()
        var sent = 0
        pending(context).forEach { checkin ->
            try {
                client.create(checkin)
                sent += 1
            } catch (error: ApiException) {
                if (error.status == 409) sent += 1 else remaining.add(checkin)
            } catch (_: Exception) {
                remaining.add(checkin)
            }
        }
        savePending(context, remaining)
        return sent
    }

    private fun readArray(context: Context, key: String): List<JSONObject> {
        val raw = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString(key, "[]") ?: "[]"
        val array = runCatching { JSONArray(raw) }.getOrDefault(JSONArray())
        return buildList { for (index in 0 until array.length()) array.optJSONObject(index)?.let(::add) }
    }

    private fun savePending(context: Context, pending: List<PendingCheckin>) {
        val raw = JSONArray().apply { pending.forEach { put(it.toJson()) } }.toString()
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putString(PENDING, raw).apply()
    }
}
