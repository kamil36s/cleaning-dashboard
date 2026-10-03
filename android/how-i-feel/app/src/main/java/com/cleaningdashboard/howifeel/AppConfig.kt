package com.cleaningdashboard.howifeel

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

data class ServerConfig(val baseUrl: String, val token: String) {
    val configured: Boolean get() = baseUrl.isNotBlank() && token.isNotBlank()
}

object ServerConfigValidator {
    fun normalizeBaseUrl(value: String): String {
        val normalized = value.trim().trimEnd('/')
        if (normalized.isBlank()) return ""
        require(normalized.startsWith("http://") || normalized.startsWith("https://")) {
            "The address must start with http:// or https://"
        }
        return normalized
    }
}

object AppConfig {
    private const val PREFS = "how_i_feel_config"
    private const val URL = "base_url"
    private const val TOKEN = "token_encrypted"
    private const val KEY_ALIAS = "how_i_feel_dashboard_token"

    fun load(context: Context): ServerConfig {
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val token = runCatching { decrypt(prefs.getString(TOKEN, "").orEmpty()) }.getOrDefault("")
        return ServerConfig(prefs.getString(URL, "").orEmpty(), token)
    }

    fun save(context: Context, baseUrl: String, token: String) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
            .putString(URL, ServerConfigValidator.normalizeBaseUrl(baseUrl))
            .putString(TOKEN, encrypt(token.trim()))
            .apply()
    }

    private fun key(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey(KEY_ALIAS, null) as? SecretKey)?.let { return it }
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        generator.init(
            KeyGenParameterSpec.Builder(KEY_ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .build(),
        )
        return generator.generateKey()
    }

    private fun encrypt(value: String): String {
        if (value.isBlank()) return ""
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, key())
        return Base64.encodeToString(cipher.iv + cipher.doFinal(value.toByteArray()), Base64.NO_WRAP)
    }

    private fun decrypt(value: String): String {
        if (value.isBlank()) return ""
        val packed = Base64.decode(value, Base64.NO_WRAP)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, packed.copyOfRange(0, 12)))
        return cipher.doFinal(packed.copyOfRange(12, packed.size)).toString(Charsets.UTF_8)
    }
}
