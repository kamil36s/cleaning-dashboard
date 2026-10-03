package com.cleaningdashboard.companion

data class NormalizedOcrBox(val x: Double, val y: Double, val width: Double, val height: Double)

object OcrGeometry {
    fun normalizedBox(
        left: Int, top: Int, right: Int, bottom: Int, imageWidth: Int, imageHeight: Int,
    ): NormalizedOcrBox? {
        if (imageWidth <= 0 || imageHeight <= 0 || right <= left || bottom <= top) return null
        val x = (left.toDouble() / imageWidth).coerceIn(0.0, 1.0)
        val y = (top.toDouble() / imageHeight).coerceIn(0.0, 1.0)
        val boundedRight = (right.toDouble() / imageWidth).coerceIn(x, 1.0)
        val boundedBottom = (bottom.toDouble() / imageHeight).coerceIn(y, 1.0)
        return NormalizedOcrBox(x, y, boundedRight - x, boundedBottom - y)
    }
}
