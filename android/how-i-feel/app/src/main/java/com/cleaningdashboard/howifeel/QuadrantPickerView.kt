package com.cleaningdashboard.howifeel

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.view.MotionEvent
import android.view.View
import androidx.core.content.res.ResourcesCompat
import kotlin.math.min

class QuadrantPickerView(context: Context) : View(context) {
    var onQuadrantSelected: ((String) -> Unit)? = null

    private val fill = Paint(Paint.ANTI_ALIAS_FLAG)
    private val label = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.rgb(8, 8, 8)
        textAlign = Paint.Align.CENTER
        typeface = ResourcesCompat.getFont(context, R.font.lato_semibold)
    }
    private val choices = listOf(
        Choice("high_unpleasant", "HIGH ENERGY", "UNPLEASANT", Color.rgb(255, 75, 91), Color.rgb(155, 44, 57)),
        Choice("high_pleasant", "HIGH ENERGY", "PLEASANT", Color.rgb(255, 204, 66), Color.rgb(164, 128, 32)),
        Choice("low_unpleasant", "LOW ENERGY", "UNPLEASANT", Color.rgb(116, 150, 255), Color.rgb(70, 88, 166)),
        Choice("low_pleasant", "LOW ENERGY", "PLEASANT", Color.rgb(73, 221, 160), Color.rgb(39, 139, 98)),
    )

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val radius = min(width * .285f, height * .285f)
        val centers = listOf(
            width * .275f to height * .29f,
            width * .725f to height * .29f,
            width * .275f to height * .71f,
            width * .725f to height * .71f,
        )
        choices.forEachIndexed { index, choice ->
            val (centerX, centerY) = centers[index]
            val path = blob(centerX, centerY, radius, index)
            canvas.save()
            canvas.translate(radius * .055f, radius * .075f)
            fill.color = choice.shadow
            canvas.drawPath(path, fill)
            canvas.restore()
            fill.color = choice.color
            canvas.drawPath(path, fill)
            drawLabel(canvas, choice, centerX, centerY)
        }
    }

    override fun onTouchEvent(event: MotionEvent): Boolean {
        if (event.actionMasked != MotionEvent.ACTION_UP) return true
        performClick()
        val pleasant = event.x >= width / 2f
        val low = event.y >= height / 2f
        onQuadrantSelected?.invoke(when {
            !low && !pleasant -> "high_unpleasant"
            !low -> "high_pleasant"
            !pleasant -> "low_unpleasant"
            else -> "low_pleasant"
        })
        return true
    }

    override fun performClick(): Boolean {
        super.performClick()
        return true
    }

    private fun drawLabel(canvas: Canvas, choice: Choice, centerX: Float, centerY: Float) {
        label.textSize = 13f * resources.displayMetrics.scaledDensity
        val lineHeight = label.fontMetrics.run { descent - ascent }
        val centerBaseline = centerY - (label.ascent() + label.descent()) / 2f
        canvas.drawText(choice.firstLine, centerX, centerBaseline - lineHeight * .48f, label)
        canvas.drawText(choice.secondLine, centerX, centerBaseline + lineHeight * .48f, label)
    }

    private fun blob(centerX: Float, centerY: Float, radius: Float, variant: Int): Path {
        val horizontal = radius * if (variant % 2 == 0) 1.02f else .98f
        val vertical = radius * if (variant < 2) .96f else 1.01f
        return Path().apply {
            moveTo(centerX, centerY - vertical)
            cubicTo(centerX + horizontal * .66f, centerY - vertical * 1.02f, centerX + horizontal, centerY - vertical * .42f, centerX + horizontal, centerY)
            cubicTo(centerX + horizontal * 1.02f, centerY + vertical * .66f, centerX + horizontal * .46f, centerY + vertical, centerX, centerY + vertical)
            cubicTo(centerX - horizontal * .68f, centerY + vertical * 1.02f, centerX - horizontal, centerY + vertical * .4f, centerX - horizontal, centerY)
            cubicTo(centerX - horizontal * 1.01f, centerY - vertical * .62f, centerX - horizontal * .48f, centerY - vertical, centerX, centerY - vertical)
            close()
        }
    }

    private data class Choice(
        val key: String,
        val firstLine: String,
        val secondLine: String,
        val color: Int,
        val shadow: Int,
    )
}
