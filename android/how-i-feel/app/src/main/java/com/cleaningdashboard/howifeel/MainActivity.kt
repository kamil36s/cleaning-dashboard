package com.cleaningdashboard.howifeel

import android.Manifest
import android.content.pm.PackageManager
import android.content.res.ColorStateList
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.os.Build
import android.text.InputType
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.OnBackPressedCallback
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import androidx.core.content.res.ResourcesCompat
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter
import java.util.UUID
import java.util.concurrent.Executors

class MainActivity : ComponentActivity() {
    private lateinit var host: FrameLayout
    private val executor = Executors.newSingleThreadExecutor()
    private var emotions: List<Emotion> = emptyList()
    private var tags: List<FeelingTag> = emptyList()
    private var history: List<CheckinSummary> = emptyList()
    private var currentScreen = Screen.LOADING
    private var activeEmotion: Emotion? = null

    private val white = Color.rgb(244, 244, 244)
    private val muted = Color.rgb(155, 155, 155)
    private val panel = Color.rgb(25, 25, 25)
    private val border = Color.rgb(53, 53, 53)
    private val bodyTypeface by lazy { ResourcesCompat.getFont(this, R.font.lato_regular) ?: Typeface.DEFAULT }
    private val bodySemiboldTypeface by lazy { ResourcesCompat.getFont(this, R.font.lato_semibold) ?: Typeface.DEFAULT_BOLD }
    private val displayTypeface by lazy { ResourcesCompat.getFont(this, R.font.dm_serif_display_regular) ?: Typeface.SERIF }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        window.statusBarColor = Color.rgb(5, 5, 5)
        window.navigationBarColor = Color.rgb(5, 5, 5)
        host = FrameLayout(this).apply { setBackgroundColor(Color.rgb(5, 5, 5)) }
        ViewCompat.setOnApplyWindowInsetsListener(host) { view, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            view.setPadding(bars.left, bars.top, bars.right, bars.bottom)
            insets
        }
        setContentView(host)
        ReminderNotifications.createChannel(this)
        ReminderScheduler.ensureScheduled(this)
        requestNotificationPermission()
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                when (currentScreen) {
                    Screen.MAP, Screen.HISTORY, Screen.SAVED -> showQuadrants()
                    Screen.DETAILS -> activeEmotion?.let { showEmotionMap(it.quadrant) } ?: showQuadrants()
                    Screen.SETTINGS -> if (emotions.isNotEmpty()) showQuadrants() else finish()
                    Screen.LOADING, Screen.MAIN -> finish()
                }
            }
        })
        if (AppConfig.load(this).configured) refresh(false) else showSettings()
    }

    override fun onDestroy() {
        executor.shutdownNow()
        super.onDestroy()
    }

    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()

    private fun background(color: Int, radius: Int = 18, stroke: Int? = null) = GradientDrawable().apply {
        setColor(color)
        cornerRadius = dp(radius).toFloat()
        stroke?.let { setStroke(dp(1), it) }
    }

    private fun requestNotificationPermission() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            ActivityCompat.requestPermissions(this, arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1401)
        }
    }

    private fun text(value: String, size: Float = 16f, color: Int = white, bold: Boolean = false, display: Boolean = false) = TextView(this).apply {
        text = value
        textSize = size
        setTextColor(color)
        typeface = when {
            display -> displayTypeface
            bold -> bodySemiboldTypeface
            else -> bodyTypeface
        }
        includeFontPadding = false
    }

    private fun button(value: String, color: Int = Color.rgb(40, 40, 40), textColor: Int = white, action: () -> Unit) = Button(this).apply {
        text = value
        isAllCaps = false
        setTextColor(textColor)
        typeface = bodySemiboldTypeface
        backgroundTintList = ColorStateList.valueOf(color)
        background = background(color, 22)
        setOnClickListener { action() }
    }

    private fun column(padding: Int = 20) = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        setPadding(dp(padding), dp(padding), dp(padding), dp(36))
    }

    private fun scroll(content: View): ScrollView = ScrollView(this).apply {
        isFillViewport = true
        isVerticalScrollBarEnabled = false
        addView(content, ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
    }

    private fun replace(view: View) {
        host.removeAllViews()
        host.addView(view, FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT))
    }

    private fun addSpace(parent: LinearLayout, value: Int) = parent.addView(View(this), LinearLayout.LayoutParams(1, dp(value)))

    private fun addHeader(parent: LinearLayout, subtitle: String) {
        val row = LinearLayout(this).apply { gravity = Gravity.CENTER_VERTICAL }
        val titles = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            addView(text("How I Feel", 28f, white, true))
            addView(text(subtitle, 12f, muted))
        }
        row.addView(titles, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        row.addView(button("History") { showHistory() }, LinearLayout.LayoutParams(dp(92), dp(44)))
        row.addView(View(this), LinearLayout.LayoutParams(dp(8), 1))
        row.addView(button("Settings") { showSettings() }, LinearLayout.LayoutParams(dp(92), dp(44)))
        parent.addView(row)
        addSpace(parent, 24)
    }

    private fun showLoading(title: String = "Getting things ready", detail: String = "Loading emotions and recent check-ins") {
        currentScreen = Screen.LOADING
        replace(column().apply {
            gravity = Gravity.CENTER
            addView(SyncLoadingView(this@MainActivity), LinearLayout.LayoutParams(dp(170), dp(170)).apply { gravity = Gravity.CENTER_HORIZONTAL })
            addSpace(this, 26)
            addView(text(title, 28f, white, true).apply { gravity = Gravity.CENTER })
            addSpace(this, 8)
            addView(text(detail, 14f, muted).apply { gravity = Gravity.CENTER })
        })
    }

    private fun showSettings(error: String = "") {
        currentScreen = Screen.SETTINGS
        val current = AppConfig.load(this)
        val content = column(24)
        if (emotions.isNotEmpty()) {
            content.addView(button("Back") { showQuadrants() }, LinearLayout.LayoutParams(dp(96), dp(44)))
            addSpace(content, 22)
        }
        content.addView(text("How I Feel", 36f, white, true))
        content.addView(text("Connect the app to your private PC dashboard.", 15f, muted))
        addSpace(content, 28)
        content.addView(text("SERVER ADDRESS", 11f, muted, true))
        val url = EditText(this).apply {
            hint = "http://192.168.1.100:8000"
            setText(current.baseUrl)
            setTextColor(white)
            setHintTextColor(Color.DKGRAY)
            isSingleLine = true
            background = background(panel, 12, border)
            setPadding(dp(14), 0, dp(14), 0)
        }
        content.addView(url, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(52)))
        addSpace(content, 16)
        content.addView(text("HOW I FEEL TOKEN", 11f, muted, true))
        val token = EditText(this).apply {
            hint = "DASHBOARD_FEELINGS_TOKEN"
            setText(current.token)
            setTextColor(white)
            setHintTextColor(Color.DKGRAY)
            isSingleLine = true
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
            background = background(panel, 12, border)
            setPadding(dp(14), 0, dp(14), 0)
        }
        content.addView(token, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(52)))
        if (error.isNotBlank()) {
            addSpace(content, 14)
            content.addView(text(error, 13f, Color.rgb(255, 110, 125)))
        }
        addSpace(content, 24)
        content.addView(button("Save and connect", white, Color.BLACK) {
            try {
                AppConfig.save(this, url.text.toString(), token.text.toString())
                refresh(false)
            } catch (exception: IllegalArgumentException) {
                showSettings(exception.message.orEmpty())
            }
        }, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(54)))
        addSpace(content, 18)
        content.addView(text("Your token is protected by Android Keystore. Your phone and PC must be on the same local network.", 12f, muted))
        replace(scroll(content))
    }

    private fun refresh(openHistory: Boolean) {
        val config = AppConfig.load(this)
        if (!config.configured) return showSettings("Enter the server address and token.")
        showLoading()
        executor.execute {
            try {
                val client = FeelingsClient(config)
                LocalFeelingsStore.flush(this, client)
                val freshEmotions = client.emotions()
                val freshTags = client.tags()
                val freshHistory = client.history()
                LocalFeelingsStore.saveCatalog(this, freshEmotions, freshTags)
                runOnUiThread {
                    emotions = freshEmotions
                    tags = freshTags
                    history = freshHistory
                    if (openHistory) showHistory() else showQuadrants("Connected to PC - ${emotions.size} emotions")
                }
            } catch (exception: Exception) {
                val cachedEmotions = LocalFeelingsStore.emotions(this)
                val cachedTags = LocalFeelingsStore.tags(this)
                runOnUiThread {
                    if (cachedEmotions.isNotEmpty()) {
                        emotions = cachedEmotions
                        tags = cachedTags
                        showQuadrants("Offline - check-ins will sync later")
                        Toast.makeText(this, exception.message ?: "No connection", Toast.LENGTH_LONG).show()
                    } else showSettings(exception.message ?: "Could not connect to your PC")
                }
            }
        }
    }

    private fun showQuadrants(status: String = "Choose the closest color") {
        currentScreen = Screen.MAIN
        activeEmotion = null
        val content = column()
        addHeader(content, status)
        content.addView(text("How are you feeling right now?", 36f, white, display = true).apply {
            gravity = Gravity.CENTER
            textAlignment = View.TEXT_ALIGNMENT_CENTER
        })
        addSpace(content, 14)
        val picker = QuadrantPickerView(this).apply { onQuadrantSelected = ::showEmotionMap }
        content.addView(picker, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(390)))
        val pending = LocalFeelingsStore.pending(this).size
        if (pending > 0) {
            addSpace(content, 16)
            content.addView(text("$pending check-in waiting to sync.", 13f, Color.rgb(255, 200, 61)))
        }
        replace(scroll(content))
    }

    private fun showEmotionMap(initialQuadrant: String?) {
        currentScreen = Screen.MAP
        val root = FrameLayout(this).apply { setBackgroundColor(Color.rgb(5, 5, 5)) }
        val map = EmotionMapView(this).apply {
            emotions = this@MainActivity.emotions
            contentDescription = "Emotion map. Pinch to zoom and drag to move."
        }
        root.addView(map, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))

        val name = text("", 28f, white, display = true)
        val definition = text("", 14f, white).apply { maxLines = 3 }
        val next = button(">", white, Color.BLACK) {}.apply {
            textSize = 30f
            background = GradientDrawable().apply { shape = GradientDrawable.OVAL; setColor(white) }
        }
        val infoText = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            addView(name)
            addView(definition)
        }
        val infoCard = LinearLayout(this).apply {
            gravity = Gravity.CENTER_VERTICAL
            background = background(Color.rgb(30, 30, 30), 30)
            elevation = dp(10).toFloat()
            setPadding(dp(20), dp(17), dp(14), dp(17))
            visibility = View.INVISIBLE
            alpha = 0f
            translationY = dp(18).toFloat()
            addView(infoText, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
            addView(View(this@MainActivity), LinearLayout.LayoutParams(dp(12), 1))
            addView(next, LinearLayout.LayoutParams(dp(72), dp(72)))
        }
        root.addView(infoCard, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.BOTTOM).apply {
            setMargins(dp(14), dp(14), dp(14), dp(16))
        })

        var chosen: Emotion? = null
        map.onEmotionSelected = { emotion ->
            chosen = emotion
            activeEmotion = emotion
            name.text = emotion.name
            name.setTextColor(runCatching { Color.parseColor(emotion.color) }.getOrDefault(white))
            definition.text = emotion.description
            if (infoCard.visibility != View.VISIBLE) {
                infoCard.visibility = View.VISIBLE
                infoCard.animate().alpha(1f).translationY(0f).setDuration(180L).start()
                infoCard.post { map.setBottomObstruction(infoCard.height + dp(32)) }
            }
        }
        next.setOnClickListener { chosen?.let(::showDetails) }
        initialQuadrant?.let(map::setInitialQuadrant)
        replace(root)
    }

    private fun showDetails(emotion: Emotion) {
        currentScreen = Screen.DETAILS
        activeEmotion = emotion
        val accent = runCatching { Color.parseColor(emotion.color) }.getOrDefault(white)
        val content = column()
        content.addView(button("Back to map") { showEmotionMap(emotion.quadrant) }, LinearLayout.LayoutParams(dp(140), dp(44)))
        addSpace(content, 20)
        content.addView(text("What were you doing when you felt", 28f, white, true))
        content.addView(text(emotion.name.lowercase(), 42f, accent, display = true))
        content.addView(text(emotion.description, 14f, muted))
        addSpace(content, 28)

        val selectedTags = linkedSetOf<String>()
        val groups = tags.groupBy { it.category.ifBlank { "Context" } }
        groups.forEach { (category, groupTags) ->
            content.addView(text(category.replaceFirstChar { it.uppercase() }, 17f, white, true))
            addSpace(content, 10)
            val flow = FlowLayout(this).apply {
                horizontalSpacing = dp(8)
                verticalSpacing = dp(9)
            }
            groupTags.forEach { tag ->
                var selected = false
                val chip = text(tag.name, 15f, white).apply {
                    gravity = Gravity.CENTER
                    minHeight = dp(42)
                    setPadding(dp(17), dp(9), dp(17), dp(9))
                    background = background(Color.rgb(31, 31, 31), 24, border)
                    setOnClickListener {
                        selected = !selected
                        if (selected) selectedTags.add(tag.name) else selectedTags.remove(tag.name)
                        setTextColor(if (selected) Color.BLACK else white)
                        background = background(if (selected) accent else Color.rgb(31, 31, 31), 24, if (selected) null else border)
                    }
                }
                flow.addView(chip)
            }
            content.addView(flow, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
            addSpace(content, 22)
        }

        content.addView(text("NOTE", 11f, muted, true))
        addSpace(content, 8)
        val note = EditText(this).apply {
            hint = "What is happening? (optional)"
            minLines = 4
            gravity = Gravity.TOP
            setTextColor(white)
            setHintTextColor(Color.DKGRAY)
            background = background(panel, 14, border)
            setPadding(dp(14), dp(12), dp(14), dp(12))
        }
        content.addView(note, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(130)))
        addSpace(content, 22)
        val save = button("Save check-in", white, Color.BLACK) {}
        save.setOnClickListener {
            save.isEnabled = false
            saveCheckin(PendingCheckin(
                id = UUID.randomUUID().toString().replace("-", ""),
                emotionId = emotion.id,
                tagNames = selectedTags.toList(),
                note = note.text.toString().trim(),
                occurredAt = LocalDateTime.now().withNano(0).format(DateTimeFormatter.ISO_LOCAL_DATE_TIME),
            ))
        }
        content.addView(save, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(56)))
        replace(scroll(content))
    }

    private fun saveCheckin(checkin: PendingCheckin) {
        ReminderPreferences.recordCheckIn(this)
        showLoading("Saving your check-in", "Keeping it safe while it syncs with your PC")
        executor.execute {
            var synced = false
            try {
                FeelingsClient(AppConfig.load(this)).create(checkin)
                synced = true
            } catch (error: ApiException) {
                if (error.status == 409) synced = true else LocalFeelingsStore.enqueue(this, checkin)
            } catch (_: Exception) {
                LocalFeelingsStore.enqueue(this, checkin)
            }
            runOnUiThread { showSaved(synced) }
        }
    }

    private fun showSaved(synced: Boolean) {
        currentScreen = Screen.SAVED
        val content = column().apply { gravity = Gravity.CENTER }
        content.addView(text(if (synced) "Done" else "Queued", 30f, if (synced) Color.rgb(73, 221, 160) else Color.rgb(255, 200, 61), true).apply { gravity = Gravity.CENTER })
        content.addView(text(if (synced) "Saved to your PC" else "Saved offline", 30f, white, true).apply { gravity = Gravity.CENTER })
        content.addView(text(if (synced) "Your dashboard already has this check-in." else "The app will send it when the connection returns.", 14f, muted).apply { gravity = Gravity.CENTER })
        addSpace(content, 26)
        content.addView(button("New check-in", white, Color.BLACK) { showQuadrants() }, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(54)))
        addSpace(content, 10)
        content.addView(button("History") { refresh(true) }, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(50)))
        replace(content)
    }

    private fun showHistory() {
        currentScreen = Screen.HISTORY
        val content = column()
        content.addView(button("Back") { showQuadrants() }, LinearLayout.LayoutParams(dp(96), dp(44)))
        addSpace(content, 18)
        content.addView(text("History", 34f, white, true))
        content.addView(text("Synced with your PC", 13f, muted))
        addSpace(content, 22)
        val titleRow = LinearLayout(this).apply { gravity = Gravity.CENTER_VERTICAL }
        titleRow.addView(text("Recent check-ins", 29f, white, true), LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        titleRow.addView(button("Refresh") { refresh(true) }, LinearLayout.LayoutParams(dp(100), dp(44)))
        content.addView(titleRow)
        addSpace(content, 16)
        if (history.isEmpty()) content.addView(text("No history is available, or the app is offline.", 14f, muted))
        history.forEach { checkin ->
            content.addView(LinearLayout(this).apply {
                orientation = LinearLayout.VERTICAL
                background = background(panel, 16, Color.rgb(42, 42, 42))
                setPadding(dp(16), dp(14), dp(16), dp(14))
                addView(text(checkin.emotionName, 27f, runCatching { Color.parseColor(checkin.emotionColor) }.getOrDefault(white), display = true))
                addView(text(checkin.occurredAt.replace('T', ' ').take(16), 12f, muted))
                if (checkin.tags.isNotEmpty()) addView(text(checkin.tags.joinToString(" - "), 13f, Color.LTGRAY))
                if (checkin.note.isNotBlank()) addView(text(checkin.note, 14f, white))
            }, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply { bottomMargin = dp(10) })
        }
        addSpace(content, 12)
        content.addView(button("New check-in", white, Color.BLACK) { showQuadrants() }, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(54)))
        replace(scroll(content))
    }

    private enum class Screen {
        LOADING,
        MAIN,
        MAP,
        DETAILS,
        SETTINGS,
        HISTORY,
        SAVED,
    }
}
