package com.cleaningdashboard.companion

import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URLEncoder
import java.net.URL
import java.util.Base64

data class UploadResult(
    val receiptId: String,
    val duplicate: Boolean,
    val validationState: String,
    val processingState: String,
    val matchState: String,
    val itemCount: Int,
    val processingMessage: String?,
) {
    fun summary(): String {
        val duplicateLabel = if (duplicate) "duplikat · " else ""
        val matchLabel = when (matchState) {
            "exact", "strong", "manual" -> "dopasowany"
            "ambiguous" -> "wymaga wyboru transakcji"
            else -> "bez dopasowania"
        }
        val stateLabel = when (processingState) {
            "parsed" -> "odczytano $itemCount pozycji"
            "ocr_unavailable" -> "OCR serwera niedostępny"
            "ocr_failed" -> "OCR nie odczytał dokumentu"
            else -> processingMessage ?: processingState
        }
        return "$duplicateLabel$stateLabel · $matchLabel"
    }
}
data class ProductLookup(val barcode: String, val known: Boolean, val name: String?, val category: String?)

object DashboardClient {
    private fun connection(config: ServerConfig, path: String, method: String): HttpURLConnection =
        (URL("${config.baseUrl.trimEnd('/')}$path").openConnection() as HttpURLConnection).apply {
            requestMethod = method
            connectTimeout = 12_000
            readTimeout = 30_000
            setRequestProperty("Authorization", "Bearer ${config.token}")
            setRequestProperty("Accept", "application/json")
        }

    private fun response(connection: HttpURLConnection): JSONObject {
        val code = connection.responseCode
        val body = (if (code in 200..299) connection.inputStream else connection.errorStream)
            ?.bufferedReader()?.use { it.readText() }.orEmpty()
        if (code !in 200..299) throw IllegalStateException("Serwer zwrócił HTTP $code")
        return JSONObject(body)
    }

    fun status(config: ServerConfig): Boolean {
        if (!config.configured) return false
        val connection = connection(config, "/api/budget/companion/status", "GET")
        return try { response(connection).optBoolean("connected", false) } finally { connection.disconnect() }
    }

    fun upload(config: ServerConfig, item: QueueItem): UploadResult {
        val file = File(item.privatePath)
        val payload = JSONObject()
            .put("filename", item.filename)
            .put("mimeType", item.mimeType)
            .put("contentBase64", Base64.getEncoder().encodeToString(file.readBytes()))
            .put("sourceRole", item.sourceRole)
        if (item.pageNumber != null) payload.put("pageNumber", item.pageNumber)
        if (!item.ocrText.isNullOrBlank()) {
            val ocrEvidence = JSONObject()
                .put("provider", item.ocrProvenance ?: "android_mlkit")
                .put("text", item.ocrText)
            item.ocrStructureJson?.let { raw ->
                runCatching { JSONObject(raw).optJSONArray("pages") }.getOrNull()?.let { ocrEvidence.put("pages", it) }
            }
            payload.put("ocrEvidence", ocrEvidence)
        }
        payload.put("attachments", JSONArray().apply {
            item.attachments.forEach { attachment ->
                put(JSONObject()
                    .put("filename", attachment.filename)
                    .put("mimeType", attachment.mimeType)
                    .put("contentBase64", Base64.getEncoder().encodeToString(File(attachment.privatePath).readBytes()))
                    .put("sourceRole", attachment.sourceRole)
                    .also { if (attachment.pageNumber != null) it.put("pageNumber", attachment.pageNumber) })
            }
        })
        val connection = connection(config, "/api/budget/receipts/import", "POST").apply {
            doOutput = true
            setRequestProperty("Content-Type", "application/json; charset=utf-8")
        }
        return try {
            connection.outputStream.use { it.write(payload.toString().toByteArray(Charsets.UTF_8)) }
            val receipt = response(connection).getJSONObject("receipt")
            UploadResult(
                receipt.getString("id"), receipt.optBoolean("duplicate"), receipt.optString("validationState"),
                receipt.optString("processingState"), receipt.optString("matchState"), receipt.optInt("itemCount"),
                receipt.optString("processingMessage").takeIf { it.isNotBlank() && it != "null" },
            )
        } finally { connection.disconnect() }
    }

    fun lookupBarcode(config: ServerConfig, barcode: String): ProductLookup {
        val safe = URLEncoder.encode(barcode, Charsets.UTF_8.name())
        val connection = connection(config, "/api/budget/products/barcode/$safe", "GET")
        return try {
            val payload = response(connection)
            val product = payload.optJSONObject("product")
            ProductLookup(barcode, payload.optBoolean("known"), product?.optString("canonicalName"), product?.optString("productCategory"))
        } finally { connection.disconnect() }
    }

    fun savePendingBarcode(config: ServerConfig, barcode: String, name: String?): ProductLookup {
        val payload = JSONObject().put("barcode", barcode).put("name", name.orEmpty())
        val connection = connection(config, "/api/budget/products/pending", "POST").apply {
            doOutput = true
            setRequestProperty("Content-Type", "application/json; charset=utf-8")
        }
        return try {
            connection.outputStream.use { it.write(payload.toString().toByteArray(Charsets.UTF_8)) }
            val result = response(connection).getJSONObject("product").getJSONObject("product")
            ProductLookup(barcode, false, result.optString("canonicalName"), result.optString("productCategory"))
        } finally { connection.disconnect() }
    }
}
