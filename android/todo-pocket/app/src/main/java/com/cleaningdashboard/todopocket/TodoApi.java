package com.cleaningdashboard.todopocket;

import android.content.Context;
import org.json.JSONObject;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.List;

final class TodoApi {
    private TodoApi() {}
    static List<TodoData.Item> refresh(Context context) throws Exception { return request(context, null); }
    static List<TodoData.Item> add(Context context, String title, String bucket) throws Exception {
        return request(context, new JSONObject().put("action", "add").put("title", title).put("bucket", bucket));
    }
    static List<TodoData.Item> complete(Context context, String id) throws Exception {
        return request(context, new JSONObject().put("action", "complete").put("id", id));
    }
    private static List<TodoData.Item> request(Context context, JSONObject body) throws Exception {
        if (!WifiOnly.connected(context)) throw new IllegalStateException("Synchronizacja działa tylko przez Wi‑Fi");
        String base = TodoData.url(context), token = TodoData.token(context);
        if (base.isEmpty() || token.isEmpty()) throw new IllegalStateException("Ustaw adres i token w aplikacji");
        HttpURLConnection connection = (HttpURLConnection) new URL(base + "/api/phone-todo").openConnection();
        connection.setConnectTimeout(5000); connection.setReadTimeout(8000);
        connection.setRequestProperty("Authorization", "Bearer " + token);
        connection.setRequestProperty("Accept", "application/json");
        if (body != null) {
            connection.setRequestMethod("POST"); connection.setDoOutput(true);
            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
            try (var output = connection.getOutputStream()) { output.write(body.toString().getBytes(StandardCharsets.UTF_8)); }
        }
        try {
            int status = connection.getResponseCode();
            InputStream stream = status < 400 ? connection.getInputStream() : connection.getErrorStream();
            String data;
            try (stream) { data = new String(stream.readAllBytes(), StandardCharsets.UTF_8); }
            JSONObject result = new JSONObject(data);
            if (status >= 400 || !result.optBoolean("ok")) throw new IllegalStateException(
                status == 401 ? "Sprawdź token i połączenie z komputerem" : result.optString("error", "Błąd synchronizacji"));
            List<TodoData.Item> items = TodoData.parseItems(result.getJSONArray("items"));
            TodoData.cache(context, items);
            TodoWidget.render(context);
            return items;
        } finally { connection.disconnect(); }
    }
}
