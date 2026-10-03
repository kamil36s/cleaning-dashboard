package com.cleaningdashboard.stepssync

import android.content.Context

object DashboardConfig {
    private const val PREFS = "dashboard_steps_sync"
    private const val KEY_BASE_URL = "base_url"
    private const val KEY_TOKEN = "token"

    private const val LEGACY_BASE_URL = "http://192.168.0.137:8000"
    private const val DEFAULT_BASE_URL = "http://192.168.0.136:8000"
    private const val DEFAULT_TOKEN = "Steps2137!"

    fun getBaseUrl(context: Context): String {
        val preferences = prefs(context)
        val savedUrl = preferences.getString(KEY_BASE_URL, DEFAULT_BASE_URL) ?: DEFAULT_BASE_URL
        if (savedUrl == LEGACY_BASE_URL) {
            preferences.edit().putString(KEY_BASE_URL, DEFAULT_BASE_URL).apply()
            return DEFAULT_BASE_URL
        }
        return savedUrl
    }

    fun getToken(context: Context): String {
        return prefs(context).getString(KEY_TOKEN, DEFAULT_TOKEN) ?: DEFAULT_TOKEN
    }

    fun save(context: Context, baseUrl: String, token: String) {
        prefs(context).edit()
            .putString(KEY_BASE_URL, baseUrl.trim().trimEnd('/'))
            .putString(KEY_TOKEN, token.trim())
            .apply()
    }

    private fun prefs(context: Context) =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
}
