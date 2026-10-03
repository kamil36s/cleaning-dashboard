package com.cleaningdashboard.companion

import android.content.Intent
import androidx.core.content.FileProvider
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

@RunWith(AndroidJUnit4::class)
class ReceiptQueueInstrumentedTest {
    @Test fun shareIntentContentUriIsCopiedIntoDurablePrivateQueue() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        context.deleteDatabase("receipt-queue.sqlite")
        val directory = File(context.filesDir, "receipt-queue").apply { mkdirs() }
        val source = File(directory, "shared.json").apply { writeText("{\"schemaVersion\":\"finance-receipt-1\"}") }
        val uri = FileProvider.getUriForFile(context, "${context.packageName}.files", source)
        val intent = Intent(Intent.ACTION_SEND).setType("application/json").putExtra(Intent.EXTRA_STREAM, uri)

        val extracted = IncomingIntentPolicy.uri(intent)
        val item = ReceiptQueue(context).enqueue(extracted!!, intent.type)

        assertEquals(UploadState.PENDING, item.state)
        assertArrayEquals(source.readBytes(), File(item.privatePath).readBytes())
    }
}
