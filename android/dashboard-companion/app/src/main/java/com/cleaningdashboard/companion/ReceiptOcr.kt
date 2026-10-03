package com.cleaningdashboard.companion

import android.content.Context
import android.net.Uri
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.text.TextRecognition
import com.google.mlkit.vision.text.latin.TextRecognizerOptions
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

data class ReceiptOcrEvidence(val text: String?, val structureJson: String?)

object ReceiptOcr {
    fun recognize(context: Context, item: QueueItem, completed: (ReceiptOcrEvidence) -> Unit) {
        val pages: List<Pair<Int, String>> = buildList {
            if (item.mimeType.startsWith("image/")) add((item.pageNumber ?: 1) to item.privatePath)
            item.attachments.filter { it.sourceRole == "page" && it.mimeType.startsWith("image/") }
                .forEach { add((it.pageNumber ?: Int.MAX_VALUE) to it.privatePath) }
        }.sortedBy { it.first }
        if (pages.isEmpty()) {
            completed(ReceiptOcrEvidence(null, null))
            return
        }
        val recognizer = TextRecognition.getClient(TextRecognizerOptions.DEFAULT_OPTIONS)
        val text = mutableListOf<String>()
        val structuredPages = JSONArray()

        fun boxJson(left: Int, top: Int, right: Int, bottom: Int, width: Int, height: Int): JSONObject? =
            OcrGeometry.normalizedBox(left, top, right, bottom, width, height)?.let { box ->
                JSONObject().put("x", box.x).put("y", box.y).put("width", box.width).put("height", box.height)
            }

        fun process(index: Int) {
            if (index >= pages.size) {
                recognizer.close()
                completed(ReceiptOcrEvidence(
                    text.joinToString("\n").trim().ifBlank { null },
                    JSONObject().put("pages", structuredPages).toString().takeIf { structuredPages.length() > 0 },
                ))
                return
            }
            val page = pages[index]
            val image = runCatching { InputImage.fromFilePath(context, Uri.fromFile(File(page.second))) }.getOrNull()
            if (image == null) {
                process(index + 1)
                return
            }
            recognizer.process(image)
                .addOnSuccessListener { result ->
                    if (result.text.isNotBlank()) text.add(result.text)
                    val lines = JSONArray()
                    result.textBlocks.forEachIndexed { blockIndex, block ->
                        block.lines.forEach { line ->
                            val lineJson = JSONObject().put("text", line.text).put("block", blockIndex)
                            line.boundingBox?.let { rect ->
                                boxJson(rect.left, rect.top, rect.right, rect.bottom, image.width, image.height)
                                    ?.let { lineJson.put("box", it) }
                            }
                            val elements = JSONArray()
                            line.elements.forEach { element ->
                                val elementJson = JSONObject().put("text", element.text)
                                element.boundingBox?.let { rect ->
                                    boxJson(rect.left, rect.top, rect.right, rect.bottom, image.width, image.height)
                                        ?.let { elementJson.put("box", it) }
                                }
                                elements.put(elementJson)
                            }
                            lineJson.put("elements", elements)
                            lines.put(lineJson)
                        }
                    }
                    structuredPages.put(JSONObject()
                        .put("pageNumber", page.first)
                        .put("width", image.width)
                        .put("height", image.height)
                        .put("lines", lines))
                    process(index + 1)
                }
                .addOnFailureListener { process(index + 1) }
        }
        process(0)
    }
}
