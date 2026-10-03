package com.cleaningdashboard.stepssync

import android.app.Activity
import android.os.Bundle
import android.view.Gravity
import android.widget.TextView

class HealthPermissionRationaleActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(
            TextView(this).apply {
                text = "Dashboard Steps reads today's step count from Health Connect and sends it to your private dashboard."
                gravity = Gravity.CENTER
                textSize = 18f
                setPadding(48, 48, 48, 48)
            },
        )
    }
}
