package com.cleaningdashboard.phonetracker

import android.content.Context
import android.content.Intent
import android.content.pm.ShortcutInfo
import android.content.pm.ShortcutManager
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.drawable.Icon
import org.json.JSONObject

/** Optional home screen shortcuts owned by Phone Tracker. The original app icon is untouched. */
object ManagedShortcuts {
    private fun id(pkg: String) = "access:$pkg"

    private fun label(context: Context, pkg: String): String = try {
        context.packageManager.getApplicationLabel(context.packageManager.getApplicationInfo(pkg,0)).toString()
    } catch (_: Exception) { pkg.substringAfterLast('.') }

    private fun icon(context: Context, pkg: String, locked: Boolean): Icon {
        val bitmap = Bitmap.createBitmap(144,144,Bitmap.Config.ARGB_8888)
        val canvas = Canvas(bitmap)
        if (locked) {
            val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.rgb(10,16,21) }
            canvas.drawRoundRect(0f,0f,144f,144f,27f,27f,paint)
            paint.color = Color.WHITE
            paint.style = Paint.Style.STROKE
            paint.strokeWidth = 10f
            canvas.drawRoundRect(49f,33f,95f,93f,22f,22f,paint)
            paint.style = Paint.Style.FILL
            canvas.drawRoundRect(37f,68f,107f,113f,9f,9f,paint)
            paint.color = Color.rgb(10,16,21)
            canvas.drawCircle(72f,87f,5f,paint)
        } else {
            try {
                val appIcon = context.packageManager.getApplicationIcon(pkg)
                appIcon.setBounds(0,0,144,144)
                appIcon.draw(canvas)
            } catch (_: Exception) {
                return Icon.createWithResource(context,R.mipmap.ic_launcher)
            }
        }
        return Icon.createWithBitmap(bitmap)
    }

    private fun shortcut(context: Context, pkg: String, locked: Boolean): ShortcutInfo {
        val app = label(context,pkg)
        val intent = Intent(context,ShortcutGateActivity::class.java).apply {
            action = Intent.ACTION_VIEW
            putExtra("target_package",pkg)
        }
        return ShortcutInfo.Builder(context,id(pkg))
            .setShortLabel(if (locked) "Locked" else app.take(20))
            .setLongLabel(if (locked) "Locked" else app)
            .setIcon(icon(context,pkg,locked)).setIntent(intent).build()
    }

    fun canPin(context: Context): Boolean = try {
        context.getSystemService(ShortcutManager::class.java).isRequestPinShortcutSupported
    } catch (_: Exception) { false }

    fun pin(context: Context, pkg: String, locked: Boolean): Boolean {
        val manager = context.getSystemService(ShortcutManager::class.java)
        if (!manager.isRequestPinShortcutSupported) return false
        return manager.requestPinShortcut(shortcut(context,pkg,locked),null)
    }

    fun update(context: Context, pkg: String, locked: Boolean) {
        try {
            val manager = context.getSystemService(ShortcutManager::class.java)
            if (manager.pinnedShortcuts.none { it.id == id(pkg) }) return
            val prefs = context.getSharedPreferences("phone-access-shortcuts",Context.MODE_PRIVATE)
            val previous = prefs.getString(pkg,null)
            val next = if (locked) "locked-v2" else "available-v2"
            if (previous == next) return
            if (manager.updateShortcuts(listOf(shortcut(context,pkg,locked))))
                prefs.edit().putString(pkg,next).apply()
        } catch (_: Exception) { /* Launcher may reject updates while locked or rate limited. */ }
    }

    suspend fun updateFromConfig(context: Context, config: JSONObject) {
        val policies = config.optJSONObject("access")?.optJSONArray("policies") ?: return
        repeat(policies.length()) { index ->
            val policy = policies.optJSONObject(index) ?: return@repeat
            if (!policy.optBoolean("enabled",true)) return@repeat
            val pkg = policy.optString("target")
            val locked = RuleEngine.evaluate(context,pkg) != null
            update(context,pkg,locked)
        }
    }
}
