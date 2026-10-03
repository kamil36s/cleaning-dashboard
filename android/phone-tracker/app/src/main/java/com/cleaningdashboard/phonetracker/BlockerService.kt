package com.cleaningdashboard.phonetracker

import android.accessibilityservice.AccessibilityService
import android.graphics.PixelFormat
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.view.Gravity
import android.view.View
import android.view.WindowManager
import android.view.accessibility.AccessibilityEvent
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.EditText
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.time.Instant
import java.util.UUID

class BlockerService : AccessibilityService() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val main = Handler(Looper.getMainLooper())
    private var monitor: Job? = null
    private var foreground: String? = null
    private var overlay: View? = null
    private var overlayPackage: String? = null
    private var lastBlockAt = 0L
    private val heartbeat = object : Runnable {
        override fun run() {
            BlockerHealth.heartbeat(applicationContext)
            main.postDelayed(this,20_000)
        }
    }

    override fun onServiceConnected() {
        super.onServiceConnected()
        GuardService.start(applicationContext)
        main.removeCallbacks(heartbeat)
        main.post(heartbeat)
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        if (event?.eventType != AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED) return
        val pkg = event.packageName?.toString() ?: return
        if (pkg == packageName) return
        if (foreground == pkg && monitor?.isActive == true) return
        foreground = pkg
        monitor?.cancel()
        if (overlayPackage != pkg) main.post { hideOverlay() }
        monitor = scope.launch {
            try { UsageCollector.collect(applicationContext) } catch (_: Exception) { }
            while (foreground == pkg) {
                val decision = try { RuleEngine.evaluate(applicationContext,pkg) } catch (error: Exception) {
                    Log.e("PhoneBlocker", "evaluation failed for $pkg",error)
                    null
                }
                ManagedShortcuts.update(applicationContext,pkg,decision != null)
                if (decision != null) {
                    if (overlayPackage != pkg) NotificationCollector.reconcileBlocked()
                    if (overlayPackage != pkg && System.currentTimeMillis() - lastBlockAt > 1_000L) {
                        TrackerDatabase.get(applicationContext).dao().insert(
                            TrackerEvent(UUID.randomUUID().toString(), Instant.now().toString(),
                                "block",pkg,metadataJson = "{\"rule\":${org.json.JSONObject.quote(decision.ruleName)}}"))
                        lastBlockAt = System.currentTimeMillis()
                        SyncScheduler.immediate(applicationContext)
                    }
                    main.post { if (foreground == pkg) showOverlay(decision) }
                } else if (overlayPackage == pkg) {
                    main.post { if (overlayPackage == pkg) hideOverlay() }
                }
                // Recheck after an override expires even if the foreground window never changes.
                delay(if (decision != null) 5_000 else 30_000)
            }
        }
    }

    override fun onInterrupt() {
        monitor?.cancel()
        main.post { hideOverlay() }
    }

    override fun onDestroy() {
        main.removeCallbacks(heartbeat)
        BlockerHealth.disconnected(applicationContext)
        scope.cancel()
        main.post { hideOverlay() }
        super.onDestroy()
    }

    private fun showOverlay(decision: BlockDecision) {
        if (overlayPackage == decision.target) return
        hideOverlay()
        val manager = getSystemService(WindowManager::class.java)
        val density = resources.displayMetrics.density
        val layout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            setPadding((28*density).toInt(),0,(28*density).toInt(),0)
            setBackgroundColor(0xFF0B1720.toInt())
        }
        val title = TextView(this).apply {
            val appName = try {
                packageManager.getApplicationLabel(packageManager.getApplicationInfo(decision.target,0)).toString()
            } catch (_: Exception) { decision.target.substringAfterLast('.') }
            text = "$appName locked"
            textSize = 28f
            setTextColor(0xFFF1FFFF.toInt())
            gravity = Gravity.CENTER
        }
        val reason = TextView(this).apply {
            text = decision.ruleName
            textSize = 17f
            setTextColor(0xFFB3D7D7.toInt())
            gravity = Gravity.CENTER
            setPadding(0,(12*density).toInt(),0,(24*density).toInt())
        }
        val back = Button(this).apply { text = "Back to home"; setOnClickListener {
            hideOverlay(); performGlobalAction(GLOBAL_ACTION_HOME)
        } }
        layout.addView(title); layout.addView(reason)
        for (line in decision.details) layout.addView(TextView(this).apply {
            text = line
            textSize = 15f
            setTextColor(0xFFD0EAE7.toInt())
            gravity = Gravity.CENTER
            setPadding(0,0,0,(5*density).toInt())
        })
        layout.addView(back)
        val policy = RulesCache.policy(applicationContext)
        val access = AccessBudget.policy(RulesCache.read(applicationContext),decision.target)?.optJSONObject("override")
        val mode = if (access?.optBoolean("enabled",true) == false) "disabled" else policy.optString("mode","always")
        val duration = (access?.optInt("duration_minutes",5) ?: policy.optInt("duration_minutes",5)).coerceIn(1,60)
        val cooldown = (access?.optInt("cooldown_minutes",60) ?: policy.optInt("cooldown_minutes",0)).coerceIn(0,1440)
        val maxOverrides = access?.optInt("max_per_day",1) ?: Int.MAX_VALUE
        val lastOverride = RulesCache.lastOverride(applicationContext,decision.target)
        val remaining = cooldown*60_000L - (System.currentTimeMillis()-lastOverride)
        if (RulesCache.overrideCount(applicationContext,decision.target) >= maxOverrides) {
            layout.addView(TextView(this).apply {
                text = "Today's temporary unlocks are used"
                setTextColor(0xFFB3D7D7.toInt())
            })
        } else if ((mode == "cooldown" || access != null) && lastOverride > 0L && remaining > 0L) {
            layout.addView(TextView(this).apply {
                text = "Override available in ${(remaining/60_000L)+1} min"
                setTextColor(0xFFB3D7D7.toInt())
            })
        } else if (mode != "disabled") {
            val pinInput = if (mode == "pin") EditText(this).apply {
                hint = "PIN"
                inputType = android.text.InputType.TYPE_CLASS_NUMBER or android.text.InputType.TYPE_NUMBER_VARIATION_PASSWORD
            } else null
            if (pinInput != null) layout.addView(pinInput)
            val feedback = TextView(this).apply { setTextColor(0xFFFF9999.toInt()) }
            val override = Button(this).apply { text = "Unlock for $duration minutes"; setOnClickListener {
                if (mode == "pin" && !RulesCache.pinMatches(applicationContext,pinInput?.text?.toString().orEmpty())) {
                    feedback.text = "Incorrect PIN"
                    return@setOnClickListener
                }
                RulesCache.override(applicationContext,decision.target,duration)
                scope.launch {
                    TrackerDatabase.get(applicationContext).dao().insert(
                        TrackerEvent(UUID.randomUUID().toString(),Instant.now().toString(),
                            "override",decision.target,
                            metadataJson=org.json.JSONObject().put("minutes",duration).put("mode",mode).toString()))
                    SyncScheduler.immediate(applicationContext)
                }
                hideOverlay()
            } }
            layout.addView(override); layout.addView(feedback)
        }
        val params = WindowManager.LayoutParams(WindowManager.LayoutParams.MATCH_PARENT,
            WindowManager.LayoutParams.MATCH_PARENT, WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
            WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN, PixelFormat.TRANSLUCENT)
        try {
            manager.addView(layout,params)
            overlay = layout
            overlayPackage = decision.target
        } catch (error: Exception) { Log.e("PhoneBlocker", "overlay failed",error); overlay = null; overlayPackage = null }
    }

    private fun hideOverlay() {
        overlay?.let { view ->
            try { getSystemService(WindowManager::class.java).removeView(view) } catch (_: Exception) { }
        }
        overlay = null
        overlayPackage = null
    }
}
