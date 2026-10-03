package com.cleaningdashboard.howifeel

import android.animation.ValueAnimator
import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RectF
import android.graphics.Typeface
import android.os.SystemClock
import android.view.GestureDetector
import android.view.MotionEvent
import android.view.ScaleGestureDetector
import android.view.View
import android.widget.OverScroller
import android.view.animation.DecelerateInterpolator
import androidx.core.content.res.ResourcesCompat
import kotlin.math.abs
import kotlin.math.min

class EmotionMapView(context: Context) : View(context) {
    var emotions: List<Emotion> = emptyList()
        set(value) {
            field = value.filter { it.meter && it.x in 0..11 && it.y in 0..11 }
            selected = null
            rebuildRenderNodes()
            invalidate()
        }
    var onEmotionSelected: ((Emotion) -> Unit)? = null

    private var selected: Emotion? = null
    private var scaleValue = 1f
    private var offsetX = 0f
    private var offsetY = 0f
    private var pendingQuadrant: String? = null
    private var animator: ValueAnimator? = null
    private var bottomObstruction = 0f
    private var flingInProgress = false
    private var renderNodes: List<RenderNode> = emptyList()
    private val acceptTapsAfter = SystemClock.uptimeMillis() + 350L
    private val scroller = OverScroller(context)

    private val fill = Paint(Paint.ANTI_ALIAS_FLAG)
    private val stroke = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        color = Color.WHITE
        strokeWidth = 3f
    }
    private val label = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.rgb(7, 7, 7)
        textAlign = Paint.Align.CENTER
        typeface = ResourcesCompat.getFont(context, R.font.dm_serif_display_regular)
    }
    private val overviewPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.WHITE
        textAlign = Paint.Align.CENTER
        typeface = ResourcesCompat.getFont(context, R.font.lato_semibold)
    }
    private val overviewPanel = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.argb(190, 8, 8, 8) }

    private val scaleDetector = ScaleGestureDetector(context, object : ScaleGestureDetector.SimpleOnScaleGestureListener() {
        override fun onScaleBegin(detector: ScaleGestureDetector): Boolean {
            animator?.cancel()
            scroller.forceFinished(true)
            flingInProgress = false
            return true
        }

        override fun onScale(detector: ScaleGestureDetector): Boolean {
            val oldScale = scaleValue
            val nextScale = (scaleValue * detector.scaleFactor).coerceIn(MIN_SCALE, MAX_SCALE)
            if (abs(nextScale - oldScale) < .001f) return true
            val centerX = width / 2f
            val centerY = height / 2f
            val mapX = (detector.focusX - offsetX - centerX) / oldScale + centerX
            val mapY = (detector.focusY - offsetY - centerY) / oldScale + centerY
            scaleValue = nextScale
            offsetX = detector.focusX - centerX - (mapX - centerX) * nextScale
            offsetY = detector.focusY - centerY - (mapY - centerY) * nextScale
            clampOffsets()
            invalidate()
            return true
        }

        override fun onScaleEnd(detector: ScaleGestureDetector) = settleToBounds()
    })

    private val gestureDetector = GestureDetector(context, object : GestureDetector.SimpleOnGestureListener() {
        override fun onDown(event: MotionEvent): Boolean {
            animator?.cancel()
            scroller.forceFinished(true)
            flingInProgress = false
            return true
        }

        override fun onScroll(first: MotionEvent?, current: MotionEvent, distanceX: Float, distanceY: Float): Boolean {
            offsetX -= distanceX
            offsetY -= distanceY
            clampOffsets(allowElastic = true)
            invalidate()
            return true
        }

        override fun onFling(first: MotionEvent?, current: MotionEvent, velocityX: Float, velocityY: Float): Boolean {
            if (scaleValue <= 1.08f) return false
            val bounds = offsetBounds(scaleValue)
            flingInProgress = true
            scroller.fling(
                offsetX.toInt(),
                offsetY.toInt(),
                velocityX.toInt(),
                velocityY.toInt(),
                bounds.minX.toInt(),
                bounds.maxX.toInt(),
                bounds.minY.toInt(),
                bounds.maxY.toInt(),
            )
            postInvalidateOnAnimation()
            return true
        }

        override fun onSingleTapUp(event: MotionEvent): Boolean {
            if (SystemClock.uptimeMillis() < acceptTapsAfter) return true
            performClick()
            val localX = (event.x - offsetX - width / 2f) / scaleValue + width / 2f
            val localY = (event.y - offsetY - height / 2f) / scaleValue + height / 2f
            if (scaleValue < 1.3f) {
                focusQuadrant(quadrantAt(localX, localY))
                return true
            }
            emotionAt(localX, localY)?.let { emotion ->
                selected = emotion
                contentDescription = "${emotion.name}. ${emotion.description}"
                announceForAccessibility(contentDescription)
                onEmotionSelected?.invoke(emotion)
                focusEmotion(emotion)
            }
            return true
        }
    })

    fun setInitialQuadrant(quadrant: String) {
        pendingQuadrant = quadrant
        post {
            if (width > 0 && height > 0) {
                pendingQuadrant = null
                focusQuadrant(quadrant, animate = false)
            }
        }
    }

    fun showAll() = animateViewport(1f, 0f, 0f)

    fun setBottomObstruction(heightPx: Int) {
        bottomObstruction = heightPx.coerceAtLeast(0).toFloat()
        clampOffsets()
        invalidate()
    }

    fun zoomIn() = animateViewport((scaleValue + .45f).coerceAtMost(MAX_SCALE), offsetX, offsetY)

    fun zoomOut() {
        val next = (scaleValue - .45f).coerceAtLeast(MIN_SCALE)
        if (next <= 1.05f) showAll() else animateViewport(next, offsetX, offsetY)
    }

    override fun performClick(): Boolean {
        super.performClick()
        return true
    }

    override fun onTouchEvent(event: MotionEvent): Boolean {
        if (event.actionMasked == MotionEvent.ACTION_DOWN) parent?.requestDisallowInterceptTouchEvent(true)
        scaleDetector.onTouchEvent(event)
        if (!scaleDetector.isInProgress) gestureDetector.onTouchEvent(event)
        if (event.actionMasked == MotionEvent.ACTION_UP || event.actionMasked == MotionEvent.ACTION_CANCEL) {
            parent?.requestDisallowInterceptTouchEvent(false)
            if (!scaleDetector.isInProgress && !flingInProgress) settleToBounds()
        }
        return true
    }

    override fun computeScroll() {
        if (!scroller.computeScrollOffset()) {
            if (flingInProgress) {
                flingInProgress = false
                settleToBounds()
            }
            return
        }
        offsetX = scroller.currX.toFloat()
        offsetY = scroller.currY.toFloat()
        invalidate()
        postInvalidateOnAnimation()
    }

    override fun onSizeChanged(width: Int, height: Int, oldWidth: Int, oldHeight: Int) {
        super.onSizeChanged(width, height, oldWidth, oldHeight)
        rebuildRenderNodes()
        pendingQuadrant?.let {
            pendingQuadrant = null
            focusQuadrant(it, animate = false)
        }
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        canvas.drawColor(Color.rgb(5, 5, 5))
        canvas.save()
        canvas.translate(offsetX, offsetY)
        canvas.scale(scaleValue, scaleValue, width / 2f, height / 2f)
        val visible = visibleMapRect()
        renderNodes.forEach { node ->
            if (RectF.intersects(node.rect, visible)) drawEmotion(canvas, node)
        }
        if (scaleValue < 1.3f) drawOverviewLabels(canvas)
        canvas.restore()
    }

    private fun mapGeometry(): Pair<Float, Float> {
        val size = min(width.toFloat(), height.toFloat()) * .97f
        return size to size / 12f
    }

    private fun rectFor(emotion: Emotion): RectF {
        val (size, cell) = mapGeometry()
        val gap = maxOf(1.2f, cell * .018f)
        val left = (width - size) / 2f + emotion.x * cell + gap
        val top = (height - size) / 2f + emotion.y * cell + gap
        return RectF(left, top, left + cell - gap * 2f, top + cell - gap * 2f)
    }

    private fun visibleMapRect(): RectF {
        val centerX = width / 2f
        val centerY = height / 2f
        return RectF(
            (0f - offsetX - centerX) / scaleValue + centerX,
            (0f - offsetY - centerY) / scaleValue + centerY,
            (width - offsetX - centerX) / scaleValue + centerX,
            (height - offsetY - centerY) / scaleValue + centerY,
        )
    }

    private fun emotionAt(x: Float, y: Float): Emotion? = renderNodes.lastOrNull { it.rect.contains(x, y) }?.emotion

    private fun quadrantAt(x: Float, y: Float): String {
        val (size) = mapGeometry()
        val left = (width - size) / 2f
        val top = (height - size) / 2f
        val pleasant = x >= left + size / 2f
        val low = y >= top + size / 2f
        return when {
            !low && !pleasant -> "high_unpleasant"
            !low -> "high_pleasant"
            !pleasant -> "low_unpleasant"
            else -> "low_pleasant"
        }
    }

    private fun drawEmotion(canvas: Canvas, node: RenderNode) {
        fill.color = node.color
        fill.style = Paint.Style.FILL
        if (node.emotion.shape == "circle") canvas.drawOval(node.rect, fill) else canvas.drawPath(node.path, fill)
        if (selected?.id == node.emotion.id) {
            stroke.strokeWidth = 3f / scaleValue
            if (node.emotion.shape == "circle") canvas.drawOval(node.rect, stroke) else canvas.drawPath(node.path, stroke)
        }
        if (scaleValue >= 1.28f) {
            label.textSize = node.textSize
            node.lines.forEachIndexed { index, line ->
                canvas.drawText(line, node.rect.centerX(), node.firstBaseline + index * node.lineHeight, label)
            }
        }
    }

    private fun buildLabel(value: String, rect: RectF, shape: String): LabelLayout {
        val maxWidth = rect.width() * if (shape == "petal") .64f else .82f
        val maxHeight = rect.height() * .58f
        var textSize = 9f * resources.displayMetrics.scaledDensity
        val minimum = (if (shape == "petal") 1.9f else 2.8f) * resources.displayMetrics.scaledDensity
        label.textSize = textSize
        var lines = labelLines(value, maxWidth)
        while ((lines.any { label.measureText(it) > maxWidth } || lines.size * textSize > maxHeight) && textSize > minimum) {
            textSize -= .5f
            label.textSize = textSize
            lines = labelLines(value, maxWidth)
        }
        val lineHeight = label.fontMetrics.run { (descent - ascent) * .88f }
        val firstBaseline = rect.centerY() - (lines.size - 1) * lineHeight / 2f - (label.ascent() + label.descent()) / 2f
        return LabelLayout(lines.take(2), textSize, firstBaseline, lineHeight)
    }

    private fun rebuildRenderNodes() {
        if (width <= 0 || height <= 0) return
        renderNodes = emotions.map { emotion ->
            val rect = rectFor(emotion)
            val layout = buildLabel(emotion.name, rect, emotion.shape)
            RenderNode(
                emotion = emotion,
                rect = rect,
                path = shapePath(emotion.shape, rect),
                color = runCatching { Color.parseColor(emotion.color) }.getOrDefault(Color.GRAY),
                lines = layout.lines,
                textSize = layout.textSize,
                firstBaseline = layout.firstBaseline,
                lineHeight = layout.lineHeight,
            )
        }
    }

    private fun labelLines(value: String, maxWidth: Float): List<String> {
        if (label.measureText(value) <= maxWidth) return listOf(value)
        val words = value.split(' ').filter(String::isNotBlank)
        if (words.size > 1) {
            var best = listOf(value)
            var bestWidth = Float.MAX_VALUE
            for (split in 1 until words.size) {
                val candidate = listOf(words.take(split).joinToString(" "), words.drop(split).joinToString(" "))
                val width = candidate.maxOf(label::measureText)
                if (width < bestWidth) {
                    best = candidate
                    bestWidth = width
                }
            }
            return best
        }
        return listOf(value)
    }

    private fun drawOverviewLabels(canvas: Canvas) {
        val (size) = mapGeometry()
        val left = (width - size) / 2f
        val top = (height - size) / 2f
        val labels = listOf(
            Triple("HIGH ENERGY\nUNPLEASANT", left + size * .25f, top + size * .25f),
            Triple("HIGH ENERGY\nPLEASANT", left + size * .75f, top + size * .25f),
            Triple("LOW ENERGY\nUNPLEASANT", left + size * .25f, top + size * .75f),
            Triple("LOW ENERGY\nPLEASANT", left + size * .75f, top + size * .75f),
        )
        overviewPaint.textSize = 9f * resources.displayMetrics.scaledDensity
        labels.forEach { (value, centerX, centerY) ->
            val panel = RectF(centerX - size * .18f, centerY - size * .057f, centerX + size * .18f, centerY + size * .057f)
            canvas.drawRoundRect(panel, panel.height() / 2f, panel.height() / 2f, overviewPanel)
            val parts = value.split('\n')
            val lineHeight = overviewPaint.fontMetrics.run { descent - ascent }
            parts.forEachIndexed { index, part ->
                val baseline = centerY + (index - .5f) * lineHeight - (overviewPaint.ascent() + overviewPaint.descent()) / 2f
                canvas.drawText(part, centerX, baseline, overviewPaint)
            }
        }
    }

    private fun focusQuadrant(quadrant: String, animate: Boolean = true) {
        val (size) = mapGeometry()
        val pleasant = quadrant.endsWith("_pleasant")
        val low = quadrant.startsWith("low")
        val targetScale = 3.15f
        val mapCenterX = width / 2f + (if (pleasant) size / 4f else -size / 4f)
        val mapCenterY = height / 2f + (if (low) size / 4f else -size / 4f)
        val targetX = -(mapCenterX - width / 2f) * targetScale
        val targetY = -(mapCenterY - height / 2f) * targetScale
        if (animate) animateViewport(targetScale, targetX, targetY) else {
            scaleValue = targetScale
            offsetX = targetX
            offsetY = targetY
            clampOffsets()
            invalidate()
        }
    }

    private fun focusEmotion(emotion: Emotion) {
        val rect = renderNodes.firstOrNull { it.emotion.id == emotion.id }?.rect ?: rectFor(emotion)
        val targetScale = maxOf(scaleValue, 3.35f).coerceAtMost(MAX_SCALE)
        val targetX = -(rect.centerX() - width / 2f) * targetScale
        val targetY = -(rect.centerY() - height / 2f) * targetScale
        animateViewport(targetScale, targetX, targetY)
    }

    private fun settleToBounds() {
        if (scaleValue <= 1.08f) {
            showAll()
            return
        }
        val target = clampedOffsets(offsetX, offsetY, scaleValue)
        if (abs(target.first - offsetX) > .5f || abs(target.second - offsetY) > .5f) {
            animateViewport(scaleValue, target.first, target.second)
        }
    }

    private fun clampOffsets(allowElastic: Boolean = false) {
        val target = clampedOffsets(offsetX, offsetY, scaleValue, allowElastic)
        offsetX = target.first
        offsetY = target.second
    }

    private fun clampedOffsets(x: Float, y: Float, scale: Float, allowElastic: Boolean = false): Pair<Float, Float> {
        val bounds = offsetBounds(scale, allowElastic)
        return x.coerceIn(bounds.minX, bounds.maxX) to y.coerceIn(bounds.minY, bounds.maxY)
    }

    private fun offsetBounds(scale: Float, allowElastic: Boolean = false): OffsetBounds {
        val (size) = mapGeometry()
        val extra = if (allowElastic) size * .035f else 0f
        val horizontal = maxOf(0f, (size * scale - width) / 2f)
        val vertical = maxOf(0f, (size * scale - height) / 2f)
        return OffsetBounds(
            minX = -horizontal - extra,
            maxX = horizontal + extra,
            minY = -vertical - bottomObstruction - extra,
            maxY = vertical + extra,
        )
    }

    private fun animateViewport(targetScale: Float, rawX: Float, rawY: Float) {
        animator?.cancel()
        val target = clampedOffsets(rawX, rawY, targetScale)
        val startScale = scaleValue
        val startX = offsetX
        val startY = offsetY
        animator = ValueAnimator.ofFloat(0f, 1f).apply {
            duration = 260L
            interpolator = DecelerateInterpolator()
            addUpdateListener { animation ->
                val progress = animation.animatedValue as Float
                scaleValue = startScale + (targetScale - startScale) * progress
                offsetX = startX + (target.first - startX) * progress
                offsetY = startY + (target.second - startY) * progress
                invalidate()
            }
            start()
        }
    }

    private fun shapePath(shape: String, rect: RectF): Path {
        val path = Path()
        val width = rect.width()
        val height = rect.height()
        when (shape) {
            "soft-square" -> path.addRoundRect(rect, width * .29f, height * .29f, Path.Direction.CW)
            "petal" -> {
                path.moveTo(rect.centerX(), rect.top)
                path.cubicTo(rect.right, rect.top, rect.right, rect.bottom, rect.centerX(), rect.bottom)
                path.cubicTo(rect.left, rect.bottom, rect.left, rect.top + height * .36f, rect.centerX(), rect.top)
                path.close()
            }
            "arch" -> {
                path.moveTo(rect.left, rect.bottom)
                path.lineTo(rect.left, rect.centerY())
                path.cubicTo(rect.left, rect.top, rect.right, rect.top, rect.right, rect.centerY())
                path.lineTo(rect.right, rect.bottom)
                path.close()
            }
            "notched" -> {
                path.moveTo(rect.left, rect.top)
                path.lineTo(rect.left + width * .38f, rect.top)
                path.lineTo(rect.centerX(), rect.top + height * .15f)
                path.lineTo(rect.left + width * .62f, rect.top)
                path.lineTo(rect.right, rect.top)
                path.lineTo(rect.right, rect.bottom)
                path.lineTo(rect.left + width * .62f, rect.bottom)
                path.lineTo(rect.centerX(), rect.bottom - height * .15f)
                path.lineTo(rect.left + width * .38f, rect.bottom)
                path.lineTo(rect.left, rect.bottom)
                path.close()
            }
            else -> path.addOval(rect, Path.Direction.CW)
        }
        return path
    }

    companion object {
        private const val MIN_SCALE = 1f
        private const val MAX_SCALE = 3.8f
    }

    private data class LabelLayout(
        val lines: List<String>,
        val textSize: Float,
        val firstBaseline: Float,
        val lineHeight: Float,
    )

    private data class RenderNode(
        val emotion: Emotion,
        val rect: RectF,
        val path: Path,
        val color: Int,
        val lines: List<String>,
        val textSize: Float,
        val firstBaseline: Float,
        val lineHeight: Float,
    )

    private data class OffsetBounds(
        val minX: Float,
        val maxX: Float,
        val minY: Float,
        val maxY: Float,
    )
}
