package com.cleaningdashboard.companion

import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import android.net.Uri
import android.provider.OpenableColumns
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.time.Instant
import java.util.UUID

enum class UploadState { PENDING, UPLOADING, UPLOADED, FAILED }

data class QueueItem(
    val id: String,
    val filename: String,
    val mimeType: String,
    val privatePath: String,
    val createdAt: String,
    val state: UploadState,
    val retryCount: Int,
    val serverReceiptId: String?,
    val lastError: String?,
    val attachments: List<QueuedAttachment> = emptyList(),
    val ocrText: String? = null,
    val ocrProvenance: String? = null,
    val ocrStructureJson: String? = null,
    val resultSummary: String? = null,
    val sourceRole: String = "primary",
    val pageNumber: Int? = null,
)

data class QueuedAttachment(
    val filename: String,
    val mimeType: String,
    val privatePath: String,
    val sourceRole: String,
    val pageNumber: Int? = null,
)

data class ScanSourcePlan(val sourceRole: String, val pageNumber: Int?, val isPrimary: Boolean)

object ScanBundlePolicy {
    fun plan(pageCount: Int, hasPdf: Boolean): List<ScanSourcePlan> = buildList {
        repeat(pageCount.coerceAtLeast(0)) { index ->
            add(ScanSourcePlan("page", index + 1, index == 0))
        }
        if (hasPdf) add(ScanSourcePlan("archive", null, pageCount == 0))
    }
}

object ReceiptTypePolicy {
    private val allowed = setOf(
        "application/pdf", "application/json", "text/json",
        "image/jpeg", "image/png", "image/webp",
    )

    fun isSupported(mimeType: String?): Boolean = mimeType?.lowercase() in allowed

    fun extension(mimeType: String): String = when (mimeType.lowercase()) {
        "application/pdf" -> ".pdf"
        "application/json", "text/json" -> ".json"
        "image/png" -> ".png"
        "image/webp" -> ".webp"
        else -> ".jpg"
    }
}

object IncomingIntentPolicy {
    fun uri(intent: Intent): Uri? = when (intent.action) {
        Intent.ACTION_VIEW -> intent.data
        Intent.ACTION_SEND -> if (android.os.Build.VERSION.SDK_INT >= 33) {
            intent.getParcelableExtra(Intent.EXTRA_STREAM, Uri::class.java)
        } else {
            @Suppress("DEPRECATION")
            intent.getParcelableExtra(Intent.EXTRA_STREAM)
        }
        else -> null
    }
}

object QueueStateMachine {
    fun canTransition(from: UploadState, to: UploadState): Boolean = when (from) {
        UploadState.PENDING -> to == UploadState.UPLOADING || to == UploadState.FAILED
        UploadState.UPLOADING -> to == UploadState.UPLOADED || to == UploadState.FAILED
        UploadState.FAILED -> to == UploadState.PENDING || to == UploadState.UPLOADING
        UploadState.UPLOADED -> false
    }
}

class ReceiptQueueDatabase(context: Context) : SQLiteOpenHelper(context, "receipt-queue.sqlite", null, 3) {
    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL(
            """CREATE TABLE uploads(
                id TEXT PRIMARY KEY, filename TEXT NOT NULL, mime_type TEXT NOT NULL,
                private_path TEXT NOT NULL, created_at TEXT NOT NULL,
                state TEXT NOT NULL, retry_count INTEGER NOT NULL DEFAULT 0,
                server_receipt_id TEXT, last_error TEXT,
                attachments_json TEXT NOT NULL DEFAULT '[]', ocr_text TEXT,
                ocr_provenance TEXT, ocr_structure_json TEXT, result_summary TEXT,
                source_role TEXT NOT NULL DEFAULT 'primary', page_number INTEGER
            )""".trimIndent(),
        )
        db.execSQL("CREATE INDEX idx_uploads_state_created ON uploads(state,created_at)")
    }

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
        if (oldVersion < 2) {
            db.execSQL("ALTER TABLE uploads ADD COLUMN attachments_json TEXT NOT NULL DEFAULT '[]'")
            db.execSQL("ALTER TABLE uploads ADD COLUMN ocr_text TEXT")
            db.execSQL("ALTER TABLE uploads ADD COLUMN ocr_provenance TEXT")
            db.execSQL("ALTER TABLE uploads ADD COLUMN result_summary TEXT")
            db.execSQL("ALTER TABLE uploads ADD COLUMN source_role TEXT NOT NULL DEFAULT 'primary'")
            db.execSQL("ALTER TABLE uploads ADD COLUMN page_number INTEGER")
        }
        if (oldVersion < 3) db.execSQL("ALTER TABLE uploads ADD COLUMN ocr_structure_json TEXT")
    }
}

class ReceiptQueue(private val context: Context) {
    private val database = ReceiptQueueDatabase(context.applicationContext)

    fun enqueue(uri: Uri, suppliedMimeType: String? = null): QueueItem {
        val resolver = context.contentResolver
        val mimeType = suppliedMimeType?.takeIf(ReceiptTypePolicy::isSupported)
            ?: resolver.getType(uri)?.takeIf(ReceiptTypePolicy::isSupported)
            ?: throw IllegalArgumentException("Nieobsługiwany typ pliku")
        val displayName = resolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { cursor ->
            if (cursor.moveToFirst()) cursor.getString(0) else null
        } ?: "receipt${ReceiptTypePolicy.extension(mimeType)}"
        val id = "upload_${UUID.randomUUID().toString().replace("-", "")}" 
        val directory = File(context.filesDir, "receipt-queue").apply { mkdirs() }
        val destination = File(directory, "$id${ReceiptTypePolicy.extension(mimeType)}")
        resolver.openInputStream(uri)?.use { input -> destination.outputStream().use(input::copyTo) }
            ?: throw IllegalArgumentException("Nie można odczytać pliku")
        val item = QueueItem(id, displayName.take(160), mimeType, destination.absolutePath, Instant.now().toString(), UploadState.PENDING, 0, null, null)
        insert(item)
        return item
    }

    fun enqueuePrivateFile(file: File, filename: String, mimeType: String): QueueItem {
        require(ReceiptTypePolicy.isSupported(mimeType))
        val id = "upload_${UUID.randomUUID().toString().replace("-", "")}" 
        val directory = File(context.filesDir, "receipt-queue").apply { mkdirs() }
        val destination = File(directory, "$id${ReceiptTypePolicy.extension(mimeType)}")
        file.inputStream().use { input -> destination.outputStream().use(input::copyTo) }
        return QueueItem(id, filename.take(160), mimeType, destination.absolutePath, Instant.now().toString(), UploadState.PENDING, 0, null, null).also(::insert)
    }

    fun enqueueScan(pageUris: List<Uri>, pdfUri: Uri?): QueueItem {
        require(pageUris.isNotEmpty() || pdfUri != null) { "Skan nie zawiera stron" }
        val id = "upload_${UUID.randomUUID().toString().replace("-", "")}"
        val directory = File(context.filesDir, "receipt-queue").apply { mkdirs() }
        val plans = ScanBundlePolicy.plan(pageUris.size, pdfUri != null)
        val attachments = mutableListOf<QueuedAttachment>()
        var primaryPath: String? = null
        var primaryFilename = "scan.pdf"
        var primaryMime = "application/pdf"

        pageUris.forEachIndexed { index, uri ->
            val filename = "scan-page-${index + 1}.jpg"
            val destination = File(directory, "$id-page-${index + 1}.jpg")
            copyUri(uri, destination)
            val plan = plans[index]
            if (plan.isPrimary) {
                primaryPath = destination.absolutePath
                primaryFilename = filename
                primaryMime = "image/jpeg"
            } else {
                attachments.add(QueuedAttachment(filename, "image/jpeg", destination.absolutePath, "page", index + 1))
            }
        }
        pdfUri?.let { uri ->
            val destination = File(directory, "$id-archive.pdf")
            copyUri(uri, destination)
            if (primaryPath == null) {
                primaryPath = destination.absolutePath
            } else {
                attachments.add(QueuedAttachment("scan.pdf", "application/pdf", destination.absolutePath, "archive"))
            }
        }
        val item = QueueItem(
            id, primaryFilename, primaryMime, requireNotNull(primaryPath), Instant.now().toString(),
            UploadState.PENDING, 0, null, null, attachments, sourceRole = if (pageUris.isNotEmpty()) "page" else "primary",
            pageNumber = if (pageUris.isNotEmpty()) 1 else null,
        )
        insert(item)
        return item
    }

    private fun copyUri(uri: Uri, destination: File) {
        context.contentResolver.openInputStream(uri)?.use { input -> destination.outputStream().use(input::copyTo) }
            ?: throw IllegalArgumentException("Nie moĹĽna odczytaÄ‡ pliku")
    }

    private fun attachmentsJson(attachments: List<QueuedAttachment>): String = JSONArray().apply {
        attachments.forEach { attachment ->
            put(JSONObject().apply {
                put("filename", attachment.filename); put("mimeType", attachment.mimeType)
                put("privatePath", attachment.privatePath); put("sourceRole", attachment.sourceRole)
                if (attachment.pageNumber != null) put("pageNumber", attachment.pageNumber)
            })
        }
    }.toString()

    private fun parseAttachments(raw: String?): List<QueuedAttachment> {
        val array = runCatching { JSONArray(raw ?: "[]") }.getOrElse { JSONArray() }
        return buildList {
            for (index in 0 until array.length()) {
                val value = array.optJSONObject(index) ?: continue
                add(QueuedAttachment(
                    value.optString("filename"), value.optString("mimeType"), value.optString("privatePath"),
                    value.optString("sourceRole", "attachment"),
                    if (value.has("pageNumber")) value.optInt("pageNumber") else null,
                ))
            }
        }
    }

    private fun insert(item: QueueItem) {
        database.writableDatabase.insertOrThrow("uploads", null, ContentValues().apply {
            put("id", item.id); put("filename", item.filename); put("mime_type", item.mimeType)
            put("private_path", item.privatePath); put("created_at", item.createdAt); put("state", item.state.name.lowercase())
            put("retry_count", item.retryCount)
            put("attachments_json", attachmentsJson(item.attachments))
            put("ocr_text", item.ocrText); put("ocr_provenance", item.ocrProvenance)
            put("ocr_structure_json", item.ocrStructureJson)
            put("result_summary", item.resultSummary)
            put("source_role", item.sourceRole); put("page_number", item.pageNumber)
        })
    }

    fun list(): List<QueueItem> = database.readableDatabase.query(
        "uploads", null, null, null, null, null, "created_at DESC",
    ).use { cursor ->
        buildList {
            while (cursor.moveToNext()) add(QueueItem(
                cursor.getString(cursor.getColumnIndexOrThrow("id")),
                cursor.getString(cursor.getColumnIndexOrThrow("filename")),
                cursor.getString(cursor.getColumnIndexOrThrow("mime_type")),
                cursor.getString(cursor.getColumnIndexOrThrow("private_path")),
                cursor.getString(cursor.getColumnIndexOrThrow("created_at")),
                UploadState.valueOf(cursor.getString(cursor.getColumnIndexOrThrow("state")).uppercase()),
                cursor.getInt(cursor.getColumnIndexOrThrow("retry_count")),
                cursor.getString(cursor.getColumnIndexOrThrow("server_receipt_id")),
                cursor.getString(cursor.getColumnIndexOrThrow("last_error")),
                parseAttachments(cursor.getString(cursor.getColumnIndexOrThrow("attachments_json"))),
                cursor.getString(cursor.getColumnIndexOrThrow("ocr_text")),
                cursor.getString(cursor.getColumnIndexOrThrow("ocr_provenance")),
                cursor.getString(cursor.getColumnIndexOrThrow("ocr_structure_json")),
                cursor.getString(cursor.getColumnIndexOrThrow("result_summary")),
                cursor.getString(cursor.getColumnIndexOrThrow("source_role")),
                cursor.getInt(cursor.getColumnIndexOrThrow("page_number")).takeIf {
                    !cursor.isNull(cursor.getColumnIndexOrThrow("page_number"))
                },
            ))
        }
    }

    fun nextPending(): QueueItem? = list().lastOrNull { it.state == UploadState.PENDING || it.state == UploadState.FAILED }

    fun transition(id: String, to: UploadState, receiptId: String? = null, error: String? = null, resultSummary: String? = null) {
        val current = list().firstOrNull { it.id == id } ?: return
        require(QueueStateMachine.canTransition(current.state, to) || current.state == to)
        database.writableDatabase.update("uploads", ContentValues().apply {
            put("state", to.name.lowercase())
            put("retry_count", if (to == UploadState.FAILED) current.retryCount + 1 else current.retryCount)
            put("server_receipt_id", receiptId)
            put("last_error", error?.take(300))
            put("result_summary", resultSummary?.take(500))
        }, "id=?", arrayOf(id))
    }

    fun updateOcr(id: String, evidence: ReceiptOcrEvidence) {
        database.writableDatabase.update("uploads", ContentValues().apply {
            put("ocr_text", evidence.text?.takeIf { it.isNotBlank() })
            put("ocr_provenance", if (evidence.text.isNullOrBlank()) null else "android_mlkit")
            put("ocr_structure_json", evidence.structureJson)
        }, "id=?", arrayOf(id))
    }

    fun retryFailed() {
        database.writableDatabase.execSQL("UPDATE uploads SET state='pending',last_error=NULL WHERE state='failed'")
    }
}
