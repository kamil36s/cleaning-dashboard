package com.cleaningdashboard.phonetracker

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import android.util.Base64
import java.io.ByteArrayOutputStream

object AppIconRegistry {
    suspend fun register(context: Context, packageName: String, appName: String) {
        if (TrackerDatabase.get(context).dao().hasApp(packageName) > 0) return
        val encoded = try {
            val icon = context.packageManager.getApplicationIcon(packageName)
            val bitmap = Bitmap.createBitmap(64,64,Bitmap.Config.ARGB_8888)
            val canvas = Canvas(bitmap)
            icon.setBounds(0,0,64,64)
            icon.draw(canvas)
            val output = ByteArrayOutputStream()
            bitmap.compress(Bitmap.CompressFormat.PNG,100,output)
            bitmap.recycle()
            Base64.encodeToString(output.toByteArray(),Base64.NO_WRAP)
        } catch (_: Exception) { null }
        TrackerDatabase.get(context).dao().registerApp(AppRegistryEntry(packageName,appName,encoded))
    }
}
