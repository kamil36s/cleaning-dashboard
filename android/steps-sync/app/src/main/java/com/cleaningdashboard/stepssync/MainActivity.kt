package com.cleaningdashboard.stepssync

import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.health.connect.client.PermissionController
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.time.LocalDate
import java.time.ZoneId

class MainActivity : ComponentActivity() {
    private lateinit var baseUrlInput: EditText
    private lateinit var tokenInput: EditText
    private lateinit var statusView: TextView
    private lateinit var stepsView: TextView

    private val permissionLauncher = registerForActivityResult(
        PermissionController.createRequestPermissionResultContract(),
    ) { granted ->
        if (granted.containsAll(HealthConnectStepsRepository.PERMISSIONS)) {
            setStatus("Health Connect access granted.")
            scheduleStepsSync(this)
        } else {
            setStatus("Full Health Connect access (including sleep) was not granted.")
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(buildContent())
        lifecycleScope.launch { refreshPermissionStatus() }
    }

    private fun buildContent(): View {
        baseUrlInput = EditText(this).apply {
            setText(DashboardConfig.getBaseUrl(this@MainActivity))
            hint = "http://192.168.0.136:8000"
            setSingleLine(true)
        }

        tokenInput = EditText(this).apply {
            setText(DashboardConfig.getToken(this@MainActivity))
            hint = "Dashboard token"
            setSingleLine(true)
        }

        statusView = TextView(this).apply {
            text = "Ready."
            textSize = 15f
            setTextColor(Color.rgb(51, 65, 85))
        }

        stepsView = TextView(this).apply {
            text = "-"
            textSize = 42f
            typeface = Typeface.DEFAULT_BOLD
            setTextColor(Color.rgb(15, 23, 42))
        }

        val content = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(36, 48, 36, 48)
            addView(title("Dashboard Steps"))
            addView(label("Today's steps"))
            addView(stepsView)
            addView(spacer(18))
            addView(label("Dashboard URL"))
            addView(baseUrlInput)
            addView(spacer(10))
            addView(label("Write token"))
            addView(tokenInput)
            addView(spacer(18))
            addView(primaryButton("Grant Health Connect access") { requestHealthConnectAccess() })
            addView(spacer(10))
            addView(primaryButton("Sync now") { syncNow() })
            addView(spacer(10))
            addView(secondaryButton("Enable 15-minute background sync") {
                saveConfig()
                scheduleStepsSync(this@MainActivity)
                setStatus("Background sync enabled.")
            })
            addView(spacer(18))
            addView(statusView)
        }

        return ScrollView(this).apply {
            setBackgroundColor(Color.rgb(248, 250, 252))
            addView(content)
        }
    }

    private fun requestHealthConnectAccess() {
        saveConfig()
        if (!HealthConnectStepsRepository.isAvailable(this)) {
            setStatus("Health Connect is not available on this phone.")
            return
        }
        permissionLauncher.launch(HealthSnapshotRepository.REQUEST_PERMISSIONS)
    }

    private fun syncNow() {
        saveConfig()
        lifecycleScope.launch {
            if (!HealthConnectStepsRepository.isAvailable(this@MainActivity)) {
                setStatus("Health Connect is not available on this phone.")
                return@launch
            }

            val repository = HealthConnectStepsRepository(this@MainActivity)
            if (!repository.hasRequiredPermissions()) {
                setStatus("Grant Health Connect access, including sleep, first.")
                permissionLauncher.launch(HealthSnapshotRepository.REQUEST_PERMISSIONS)
                return@launch
            }

            setStatus("Reading Health Connect...")
            runCatching {
                val zone = ZoneId.systemDefault()
                val day = LocalDate.now(zone)
                withContext(Dispatchers.IO) {
                    val baseUrl = DashboardConfig.getBaseUrl(this@MainActivity)
                    val token = DashboardConfig.getToken(this@MainActivity)
                    val exclusions = DashboardClient.getStepExclusions(baseUrl, token, day)
                    val aggregation = if (exclusions.active) null else {
                        repository.readStepsForDayExcluding(day, zone, exclusions.intervals)
                    }
                    if (aggregation != null) {
                        DashboardClient.postSteps(
                            baseUrl = baseUrl,
                            token = token,
                            day = day,
                            steps = aggregation.steps,
                            rawSteps = aggregation.rawSteps,
                            excludedSteps = aggregation.excludedSteps,
                            capturedAt = aggregation.capturedAt.toString(),
                            excludedIntervals = exclusions.intervals,
                        )
                    }
                    val snapshot = HealthSnapshotRepository(this@MainActivity).readTodaySnapshot(day, zone)
                    DashboardClient.postHealthSnapshot(
                        baseUrl = baseUrl,
                        token = token,
                        payload = snapshot,
                    )
                    aggregation
                }
            }.onSuccess { aggregation ->
                scheduleStepsSync(this@MainActivity)
                if (aggregation == null) {
                    setStatus("Workout active. Automatic step sync skipped.")
                } else {
                    stepsView.text = aggregation.steps.toString()
                    setStatus("Synced ${aggregation.steps} steps outside workouts.")
                }
            }.onFailure { error ->
                setStatus("Sync failed: ${error.message ?: error::class.java.simpleName}")
            }
        }
    }

    private suspend fun refreshPermissionStatus() {
        if (!HealthConnectStepsRepository.isAvailable(this)) {
            setStatus("Health Connect is not available on this phone.")
            return
        }

        val repository = HealthConnectStepsRepository(this)
        if (repository.hasRequiredPermissions()) {
            val steps = repository.readStepsForDay()
            stepsView.text = steps.toString()
            setStatus("Health Connect access is ready.")
        } else {
            setStatus("Grant Health Connect access, including sleep.")
        }
    }

    private fun saveConfig() {
        DashboardConfig.save(
            this,
            baseUrl = baseUrlInput.text.toString(),
            token = tokenInput.text.toString(),
        )
    }

    private fun setStatus(value: String) {
        statusView.text = value
    }

    private fun title(value: String) = TextView(this).apply {
        text = value
        textSize = 26f
        typeface = Typeface.DEFAULT_BOLD
        setTextColor(Color.rgb(15, 23, 42))
        setPadding(0, 0, 0, 28)
    }

    private fun label(value: String) = TextView(this).apply {
        text = value
        textSize = 13f
        typeface = Typeface.DEFAULT_BOLD
        setTextColor(Color.rgb(71, 85, 105))
        setPadding(0, 8, 0, 4)
    }

    private fun primaryButton(text: String, onClick: () -> Unit) = Button(this).apply {
        this.text = text
        setTextColor(Color.WHITE)
        background = rounded(Color.rgb(37, 99, 235))
        setOnClickListener { onClick() }
    }

    private fun secondaryButton(text: String, onClick: () -> Unit) = Button(this).apply {
        this.text = text
        setTextColor(Color.rgb(15, 23, 42))
        background = rounded(Color.rgb(226, 232, 240))
        setOnClickListener { onClick() }
    }

    private fun rounded(color: Int) = GradientDrawable().apply {
        setColor(color)
        cornerRadius = 14f
    }

    private fun spacer(height: Int) = View(this).apply {
        layoutParams = LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT,
            height,
        )
    }
}
