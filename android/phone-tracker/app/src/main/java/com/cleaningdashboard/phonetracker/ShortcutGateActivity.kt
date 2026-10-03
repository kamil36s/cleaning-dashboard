package com.cleaningdashboard.phonetracker

import android.graphics.Color
import android.os.Bundle
import android.view.Gravity
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** Entry point for a user-pinned managed shortcut. Accessibility still guards the real app. */
class ShortcutGateActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val pkg = intent.getStringExtra("target_package")?.takeIf { it.matches(Regex("[a-zA-Z0-9_.]+")) }
        if (pkg == null) { finish(); return }
        lifecycleScope.launch {
            val decision = try { withContext(Dispatchers.IO) { RuleEngine.evaluate(applicationContext,pkg) } }
                catch (_: Exception) { BlockDecision("Access cannot be checked right now",pkg) }
            ManagedShortcuts.update(applicationContext,pkg,decision != null)
            if (decision == null) {
                val launch = packageManager.getLaunchIntentForPackage(pkg)
                if (launch != null) startActivity(launch)
                finish()
            } else showLocked(decision)
        }
    }

    private fun showLocked(decision: BlockDecision) {
        val density = resources.displayMetrics.density
        val padding = (24*density).toInt()
        val layout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            setPadding(padding,padding,padding,padding)
            setBackgroundColor(Color.rgb(10,16,21))
        }
        fun line(value: String, size: Float, color: Int) = TextView(this).apply {
            text = value
            textSize = size
            setTextColor(color)
            gravity = Gravity.CENTER
            setPadding(0,0,0,(10*density).toInt())
        }
        val name = try { packageManager.getApplicationLabel(
            packageManager.getApplicationInfo(decision.target,0)).toString() }
            catch (_: Exception) { decision.target.substringAfterLast('.') }
        layout.addView(line("🔒",44f,Color.WHITE))
        layout.addView(line("$name locked",27f,Color.WHITE))
        layout.addView(line(decision.ruleName,17f,Color.rgb(180,210,207)))
        decision.details.forEach { layout.addView(line(it,15f,Color.rgb(205,225,223))) }
        layout.addView(Button(this).apply { text = "Back to home"; setOnClickListener { finish() } })
        setContentView(layout)
    }
}
