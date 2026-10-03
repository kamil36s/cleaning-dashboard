package com.cleaningdashboard.phonetelemetry.export

import android.content.ContentValues
import android.content.Context
import android.os.Environment
import android.provider.MediaStore

class MediaStoreExportWriter(
    private val context: Context,
) {
    fun writeJsonFile(fileName: String, content: String) {
        val resolver = context.contentResolver
        val values = ContentValues().apply {
            put(MediaStore.MediaColumns.DISPLAY_NAME, fileName)
            put(MediaStore.MediaColumns.MIME_TYPE, "application/json")
            put(
                MediaStore.MediaColumns.RELATIVE_PATH,
                Environment.DIRECTORY_DOWNLOADS + "/CleaningDashboardTelemetry",
            )
        }

        val uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
            ?: error("Failed to create MediaStore file for $fileName")

        resolver.openOutputStream(uri)?.bufferedWriter().use { writer ->
            writer?.write(content)
        }
    }
}
