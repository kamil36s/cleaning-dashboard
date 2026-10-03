package com.cleaningdashboard.howifeel

import android.animation.ValueAnimator
import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.view.View
import android.view.animation.AccelerateDecelerateInterpolator
import kotlin.math.min

class SyncLoadingView(context: Context) : View(context) {
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
    private var progress = 0f
    private val animator = ValueAnimator.ofFloat(0f, 1f).apply {
        duration = 1050L
        repeatCount = ValueAnimator.INFINITE
        repeatMode = ValueAnimator.REVERSE
        interpolator = AccelerateDecelerateInterpolator()
        addUpdateListener {
            progress = it.animatedValue as Float
            invalidate()
        }
    }

    override fun onAttachedToWindow() {
        super.onAttachedToWindow()
        animator.start()
    }

    override fun onDetachedFromWindow() {
        animator.cancel()
        super.onDetachedFromWindow()
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val size = min(width, height).toFloat()
        val radius = size * (.19f + progress * .025f)
        val offset = size * (.125f - progress * .015f)
        val centerX = width / 2f
        val centerY = height / 2f
        canvas.save()
        canvas.rotate(-5f + progress * 10f, centerX, centerY)
        drawCircle(canvas, centerX - offset, centerY - offset, radius, Color.rgb(255, 75, 91))
        drawCircle(canvas, centerX + offset, centerY - offset, radius, Color.rgb(255, 204, 66))
        drawCircle(canvas, centerX - offset, centerY + offset, radius, Color.rgb(116, 150, 255))
        drawCircle(canvas, centerX + offset, centerY + offset, radius, Color.rgb(73, 221, 160))
        drawCircle(canvas, centerX, centerY, size * .075f, Color.WHITE)
        canvas.restore()
    }

    private fun drawCircle(canvas: Canvas, x: Float, y: Float, radius: Float, color: Int) {
        paint.color = color
        canvas.drawCircle(x, y, radius, paint)
    }
}
