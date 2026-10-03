package com.cleaningdashboard.phonetracker

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.net.InetAddress
import java.net.URI
import java.security.KeyStore
import java.io.File
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import org.json.JSONObject

data class Pairing(val server: String, val deviceId: String, val token: String)

object TrackerConfig {
    private const val ALIAS = "phone-tracker-pairing-v1"
    fun importOneTimePairing(context: Context): Boolean {
        val file = File(context.filesDir, "pairing-once.json")
        if (!file.exists()) return false
        return try {
            require(file.length() in 1..8192) { "Invalid pairing file" }
            val data = JSONObject(file.readText(Charsets.UTF_8))
            save(context, Pairing(data.getString("server"), data.getString("device_id"), data.getString("token")))
            true
        } finally {
            file.delete()
        }
    }
    private fun secret(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey(ALIAS, null) as? SecretKey)?.let { return it }
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        generator.init(KeyGenParameterSpec.Builder(ALIAS,
            KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .build())
        return generator.generateKey()
    }

    fun save(context: Context, pairing: Pairing) {
        val uri = URI(pairing.server.trim())
        require(uri.scheme == "http" && uri.host != null && uri.userInfo == null &&
            uri.path.orEmpty().trimEnd('/').isEmpty()) { "Use a LAN address such as http://192.168.1.2:8000" }
        require(isLanHost(uri.host)) { "Server must resolve to a private LAN address" }
        require(pairing.deviceId.isNotBlank() && pairing.token.isNotBlank())
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, secret())
        val encoded = Base64.encodeToString(cipher.iv + cipher.doFinal(pairing.token.trim().toByteArray()), Base64.NO_WRAP)
        context.getSharedPreferences("phone-tracker", Context.MODE_PRIVATE).edit()
            .putString("server", pairing.server.trim().trimEnd('/'))
            .putString("device_id", pairing.deviceId.trim())
            .putString("token_ciphertext", encoded).apply()
    }

    fun load(context: Context): Pairing? {
        return try {
            val prefs = context.getSharedPreferences("phone-tracker", Context.MODE_PRIVATE)
            val server = prefs.getString("server", null) ?: return null
            val id = prefs.getString("device_id", null) ?: return null
            val data = Base64.decode(prefs.getString("token_ciphertext", null) ?: return null, Base64.DEFAULT)
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.DECRYPT_MODE, secret(), GCMParameterSpec(128, data.copyOfRange(0, 12)))
            Pairing(server, id, String(cipher.doFinal(data.copyOfRange(12, data.size))))
        } catch (_: Exception) { null }
    }

    fun isLanHost(host: String): Boolean = try {
        InetAddress.getAllByName(host).isNotEmpty() && InetAddress.getAllByName(host).all {
            it.isSiteLocalAddress || it.isLinkLocalAddress
        }
    } catch (_: Exception) { false }

    fun lastSync(context: Context): String? = context.getSharedPreferences("phone-tracker", Context.MODE_PRIVATE)
        .getString("last_sync", null)

    fun lastError(context: Context): String? = context.getSharedPreferences("phone-tracker", Context.MODE_PRIVATE)
        .getString("last_error", null)

    fun syncResult(context: Context, at: String?, error: String?) {
        val edit = context.getSharedPreferences("phone-tracker", Context.MODE_PRIVATE).edit()
        if (at != null) edit.putString("last_sync", at)
        edit.putString("last_error", error).apply()
    }
}
