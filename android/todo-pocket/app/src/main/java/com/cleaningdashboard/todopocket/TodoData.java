package com.cleaningdashboard.todopocket;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;
import java.security.KeyStore;
import java.util.ArrayList;
import java.util.List;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

final class TodoData {
    static final String PREFS = "todo_pocket";
    private static final String KEY = "todo_pocket_token";
    private TodoData() {}

    static SharedPreferences prefs(Context context) { return context.getSharedPreferences(PREFS, Context.MODE_PRIVATE); }
    static String url(Context context) { return prefs(context).getString("url", ""); }
    static String token(Context context) {
        String packed = prefs(context).getString("token", "");
        if (packed.isEmpty()) return "";
        try {
            byte[] bytes = Base64.decode(packed, Base64.NO_WRAP);
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.DECRYPT_MODE, secret(), new GCMParameterSpec(128, bytes, 0, 12));
            return new String(cipher.doFinal(bytes, 12, bytes.length - 12), java.nio.charset.StandardCharsets.UTF_8);
        } catch (Exception e) { return ""; }
    }
    static void saveConfig(Context context, String url, String token) throws Exception {
        String clean = url.trim().replaceAll("/+$", "");
        if (!clean.matches("https?://[^/\\s]+(?::[0-9]+)?")) throw new IllegalArgumentException("Podaj adres serwera, np. http://192.168.1.2:8000");
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE, secret());
        byte[] encrypted = cipher.doFinal(token.trim().getBytes(java.nio.charset.StandardCharsets.UTF_8));
        byte[] packed = new byte[cipher.getIV().length + encrypted.length];
        System.arraycopy(cipher.getIV(), 0, packed, 0, cipher.getIV().length);
        System.arraycopy(encrypted, 0, packed, cipher.getIV().length, encrypted.length);
        prefs(context).edit().putString("url", clean)
            .putString("token", Base64.encodeToString(packed, Base64.NO_WRAP)).apply();
    }
    private static SecretKey secret() throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore"); store.load(null);
        SecretKey existing = (SecretKey) store.getKey(KEY, null);
        if (existing != null) return existing;
        KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
        generator.init(new KeyGenParameterSpec.Builder(KEY, KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build());
        return generator.generateKey();
    }

    static List<Item> cached(Context context) {
        try { return parseItems(new JSONArray(prefs(context).getString("items", "[]"))); }
        catch (JSONException e) { return new ArrayList<>(); }
    }
    static void cache(Context context, List<Item> items) {
        JSONArray array = new JSONArray();
        for (Item item : items) {
            JSONObject json = new JSONObject();
            try { json.put("id", item.id); json.put("title", item.title); json.put("bucket", item.bucket); array.put(json); }
            catch (JSONException ignored) {}
        }
        prefs(context).edit().putString("items", array.toString()).putLong("synced", System.currentTimeMillis()).apply();
    }
    static List<Item> parseItems(JSONArray array) {
        List<Item> items = new ArrayList<>();
        for (int i = 0; i < array.length(); i++) {
            JSONObject json = array.optJSONObject(i);
            if (json == null) continue;
            String bucket = json.optString("bucket");
            if ((bucket.equals("now") || bucket.equals("shopping")) && !json.optBoolean("done"))
                items.add(new Item(json.optString("id"), json.optString("title"), bucket));
        }
        return items;
    }
    static final class Item {
        final String id, title, bucket;
        Item(String id, String title, String bucket) { this.id = id; this.title = title; this.bucket = bucket; }
    }
}
