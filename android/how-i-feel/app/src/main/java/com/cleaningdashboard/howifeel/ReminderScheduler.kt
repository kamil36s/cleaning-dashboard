package com.cleaningdashboard.howifeel

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.work.Data
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.Worker
import androidx.work.WorkerParameters
import java.time.Duration
import java.time.LocalDate
import java.time.ZonedDateTime
import java.util.concurrent.TimeUnit
import kotlin.random.Random

internal enum class ReminderSlot(val startHour: Int, val startMinute: Int, val windowMinutes: Int) {
    MORNING(9, 15, 135),
    AFTERNOON(13, 45, 165),
    EVENING(18, 30, 150),
}

internal object ReminderPreferences {
    private const val PREFS = "how_i_feel_reminders"
    private const val LAST_CHECK_IN = "last_check_in"
    private const val LAST_NOTIFICATION = "last_notification"

    fun recordCheckIn(context: Context, nowMillis: Long = System.currentTimeMillis()) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putLong(LAST_CHECK_IN, nowMillis).apply()
    }

    fun shouldNotify(context: Context, nowMillis: Long = System.currentTimeMillis()): Boolean {
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val lastCheckIn = prefs.getLong(LAST_CHECK_IN, 0L)
        val lastNotification = prefs.getLong(LAST_NOTIFICATION, 0L)
        return nowMillis - lastCheckIn >= TimeUnit.MINUTES.toMillis(90) &&
            nowMillis - lastNotification >= TimeUnit.HOURS.toMillis(2)
    }

    fun recordNotification(context: Context, nowMillis: Long = System.currentTimeMillis()) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putLong(LAST_NOTIFICATION, nowMillis).apply()
    }
}

internal object ReminderScheduler {
    private const val KEY_SLOT = "slot"
    private const val KEY_TARGET_MILLIS = "target_millis"

    fun ensureScheduled(context: Context) {
        ReminderSlot.entries.forEach { schedule(context, it, LocalDate.now()) }
    }

    fun scheduleNext(context: Context, slot: ReminderSlot, previousTargetMillis: Long) {
        val previousDate = ZonedDateTime.ofInstant(
            java.time.Instant.ofEpochMilli(previousTargetMillis),
            java.time.ZoneId.systemDefault(),
        ).toLocalDate()
        schedule(context, slot, previousDate.plusDays(1))
    }

    private fun schedule(context: Context, slot: ReminderSlot, requestedDate: LocalDate) {
        val now = ZonedDateTime.now()
        var date = requestedDate
        var target = targetFor(date, slot)
        while (!target.isAfter(now.plusMinutes(5))) {
            date = date.plusDays(1)
            target = targetFor(date, slot)
        }
        val delay = Duration.between(now, target).toMillis().coerceAtLeast(0L)
        val data = Data.Builder()
            .putString(KEY_SLOT, slot.name)
            .putLong(KEY_TARGET_MILLIS, target.toInstant().toEpochMilli())
            .build()
        val request = OneTimeWorkRequestBuilder<CheckInReminderWorker>()
            .setInputData(data)
            .setInitialDelay(delay, TimeUnit.MILLISECONDS)
            .addTag("how-i-feel-reminders")
            .build()
        WorkManager.getInstance(context).enqueueUniqueWork(
            "how-i-feel-${slot.name.lowercase()}-$date",
            ExistingWorkPolicy.KEEP,
            request,
        )
    }

    private fun targetFor(date: LocalDate, slot: ReminderSlot): ZonedDateTime {
        val seed = date.toEpochDay() * 31L + slot.ordinal * 7_919L
        val minuteOffset = Random(seed).nextInt(slot.windowMinutes)
        return date.atTime(slot.startHour, slot.startMinute)
            .atZone(java.time.ZoneId.systemDefault())
            .plusMinutes(minuteOffset.toLong())
    }

    fun slot(data: Data): ReminderSlot? = data.getString(KEY_SLOT)?.let { value ->
        ReminderSlot.entries.firstOrNull { it.name == value }
    }

    fun targetMillis(data: Data): Long = data.getLong(KEY_TARGET_MILLIS, 0L)
}

class CheckInReminderWorker(context: Context, params: WorkerParameters) : Worker(context, params) {
    override fun doWork(): Result {
        val slot = ReminderScheduler.slot(inputData) ?: return Result.failure()
        val targetMillis = ReminderScheduler.targetMillis(inputData)
        ReminderScheduler.scheduleNext(applicationContext, slot, targetMillis)

        val now = System.currentTimeMillis()
        if (targetMillis <= 0L || now - targetMillis > TimeUnit.HOURS.toMillis(3)) return Result.success()
        if (!ReminderPreferences.shouldNotify(applicationContext, now)) return Result.success()
        if (!ReminderNotifications.canNotify(applicationContext)) return Result.success()

        ReminderNotifications.show(applicationContext, slot, targetMillis)
        ReminderPreferences.recordNotification(applicationContext, now)
        return Result.success()
    }
}

internal object ReminderNotifications {
    private const val CHANNEL_ID = "gentle_check_ins"

    fun createChannel(context: Context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val channel = NotificationChannel(
            CHANNEL_ID,
            "Gentle check-ins",
            NotificationManager.IMPORTANCE_DEFAULT,
        ).apply {
            description = "A few quiet prompts to notice how you feel"
            enableVibration(false)
            setShowBadge(true)
        }
        context.getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
    }

    fun canNotify(context: Context): Boolean {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) return false
        return NotificationManagerCompat.from(context).areNotificationsEnabled()
    }

    fun show(context: Context, slot: ReminderSlot, targetMillis: Long) {
        createChannel(context)
        val copy = copyFor(slot, targetMillis)
        val intent = Intent(context, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
        }
        val requestCode = (targetMillis xor slot.ordinal.toLong()).hashCode()
        val pendingIntent = PendingIntent.getActivity(
            context,
            requestCode,
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val notification = NotificationCompat.Builder(context, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_notification)
            .setLargeIcon(largeIcon())
            .setColor(Color.rgb(73, 221, 160))
            .setContentTitle(copy.first)
            .setContentText(copy.second)
            .setStyle(NotificationCompat.BigTextStyle().bigText(copy.second))
            .setContentIntent(pendingIntent)
            .setCategory(NotificationCompat.CATEGORY_REMINDER)
            .setPriority(NotificationCompat.PRIORITY_DEFAULT)
            .setAutoCancel(true)
            .build()
        NotificationManagerCompat.from(context).notify(requestCode, notification)
    }

    private fun copyFor(slot: ReminderSlot, targetMillis: Long): Pair<String, String> {
        val options = when (slot) {
            ReminderSlot.MORNING -> listOf(
                "A quiet morning check-in" to "What feeling is setting the tone for your day?",
                "Notice what is here" to "Take ten seconds. Which word fits this morning?",
            )
            ReminderSlot.AFTERNOON -> listOf(
                "A moment for you" to "Pause between things. How do you feel right now?",
                "Check in, without fixing" to "Name what is present and carry on with a little more clarity.",
            )
            ReminderSlot.EVENING -> listOf(
                "Before the day moves on" to "What feeling stayed with you this evening?",
                "One small pause" to "Give today a feeling word while it is still fresh.",
            )
        }
        return options[Random(targetMillis xor slot.ordinal.toLong()).nextInt(options.size)]
    }

    private fun largeIcon(): Bitmap {
        val bitmap = Bitmap.createBitmap(128, 128, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(bitmap)
        val paint = Paint(Paint.ANTI_ALIAS_FLAG)
        listOf(
            Triple(45f, 45f, Color.rgb(255, 75, 91)),
            Triple(83f, 45f, Color.rgb(255, 204, 66)),
            Triple(45f, 83f, Color.rgb(116, 150, 255)),
            Triple(83f, 83f, Color.rgb(73, 221, 160)),
        ).forEach { (x, y, color) ->
            paint.color = color
            canvas.drawCircle(x, y, 29f, paint)
        }
        paint.color = Color.WHITE
        canvas.drawCircle(64f, 64f, 12f, paint)
        return bitmap
    }
}
