package com.cleaningdashboard.howifeel

import android.content.Context
import android.view.View
import android.view.ViewGroup

class FlowLayout(context: Context) : ViewGroup(context) {
    var horizontalSpacing = 8
    var verticalSpacing = 8

    override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) {
        val available = MeasureSpec.getSize(widthMeasureSpec) - paddingLeft - paddingRight
        var lineWidth = 0
        var lineHeight = 0
        var usedHeight = paddingTop + paddingBottom
        var widest = 0
        for (index in 0 until childCount) {
            val child = getChildAt(index)
            if (child.visibility == View.GONE) continue
            measureChildWithMargins(child, widthMeasureSpec, 0, heightMeasureSpec, usedHeight)
            val params = child.layoutParams as MarginLayoutParams
            val childWidth = child.measuredWidth + params.leftMargin + params.rightMargin
            val childHeight = child.measuredHeight + params.topMargin + params.bottomMargin
            if (lineWidth > 0 && lineWidth + horizontalSpacing + childWidth > available) {
                widest = maxOf(widest, lineWidth)
                usedHeight += lineHeight + verticalSpacing
                lineWidth = childWidth
                lineHeight = childHeight
            } else {
                lineWidth += if (lineWidth == 0) childWidth else horizontalSpacing + childWidth
                lineHeight = maxOf(lineHeight, childHeight)
            }
        }
        widest = maxOf(widest, lineWidth)
        usedHeight += lineHeight
        setMeasuredDimension(
            resolveSize(widest + paddingLeft + paddingRight, widthMeasureSpec),
            resolveSize(usedHeight, heightMeasureSpec),
        )
    }

    override fun onLayout(changed: Boolean, left: Int, top: Int, right: Int, bottom: Int) {
        val available = right - left - paddingLeft - paddingRight
        var x = paddingLeft
        var y = paddingTop
        var lineHeight = 0
        for (index in 0 until childCount) {
            val child = getChildAt(index)
            if (child.visibility == View.GONE) continue
            val params = child.layoutParams as MarginLayoutParams
            val childWidth = child.measuredWidth + params.leftMargin + params.rightMargin
            val childHeight = child.measuredHeight + params.topMargin + params.bottomMargin
            if (x > paddingLeft && x + childWidth > paddingLeft + available) {
                x = paddingLeft
                y += lineHeight + verticalSpacing
                lineHeight = 0
            }
            val childLeft = x + params.leftMargin
            val childTop = y + params.topMargin
            child.layout(childLeft, childTop, childLeft + child.measuredWidth, childTop + child.measuredHeight)
            x += childWidth + horizontalSpacing
            lineHeight = maxOf(lineHeight, childHeight)
        }
    }

    override fun generateDefaultLayoutParams() = MarginLayoutParams(LayoutParams.WRAP_CONTENT, LayoutParams.WRAP_CONTENT)
    override fun generateLayoutParams(attributes: android.util.AttributeSet?) = MarginLayoutParams(context, attributes)
    override fun generateLayoutParams(params: LayoutParams?) = MarginLayoutParams(params)
    override fun checkLayoutParams(params: LayoutParams?) = params is MarginLayoutParams
}
