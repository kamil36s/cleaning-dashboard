package com.cleaningdashboard.todopocket;

import android.app.PendingIntent;
import android.appwidget.AppWidgetManager;
import android.appwidget.AppWidgetProvider;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.widget.RemoteViews;
import androidx.work.ExistingPeriodicWorkPolicy;
import androidx.work.PeriodicWorkRequest;
import androidx.work.WorkManager;
import java.text.DateFormat;
import java.util.Date;
import java.util.concurrent.TimeUnit;

public final class TodoWidget extends AppWidgetProvider {
    private static final String REFRESH = "com.cleaningdashboard.todopocket.REFRESH";
    private static final String COMPLETE = "com.cleaningdashboard.todopocket.COMPLETE";

    static void schedule(Context context) {
        WorkManager.getInstance(context).enqueueUniquePeriodicWork("todo-widget-sync",
            ExistingPeriodicWorkPolicy.KEEP,
            new PeriodicWorkRequest.Builder(TodoSyncWorker.class, 15, TimeUnit.MINUTES)
                .setConstraints(new androidx.work.Constraints.Builder()
                    .setRequiredNetworkType(androidx.work.NetworkType.CONNECTED).build()).build());
    }
    @Override public void onUpdate(Context context, AppWidgetManager manager, int[] ids) {
        render(context); schedule(context);
        WorkManager.getInstance(context).enqueue(new androidx.work.OneTimeWorkRequest.Builder(TodoSyncWorker.class).build());
    }
    @Override public void onReceive(Context context, Intent intent) {
        super.onReceive(context, intent);
        String action = intent.getAction();
        if (!REFRESH.equals(action) && !COMPLETE.equals(action)) return;
        PendingResult pending = goAsync();
        new Thread(() -> {
            try {
                if (COMPLETE.equals(action)) TodoApi.complete(context, intent.getStringExtra("id"));
                else TodoApi.refresh(context);
                TodoData.prefs(context).edit().remove("error").apply();
            } catch (Exception e) {
                TodoData.prefs(context).edit().putString("error", WifiOnly.connected(context) ?
                    "Brak połączenia · dotknij ↻" : "Połącz z Wi‑Fi").apply();
            } finally { render(context); pending.finish(); }
        }, "todo-widget-action").start();
    }
    static void render(Context context) {
        AppWidgetManager manager = AppWidgetManager.getInstance(context);
        int[] ids = manager.getAppWidgetIds(new ComponentName(context, TodoWidget.class));
        if (ids.length == 0) return;
        long synced = TodoData.prefs(context).getLong("synced", 0);
        String status = TodoData.prefs(context).getString("error", "");
        if (status.isEmpty()) status = synced == 0 ? "Otwórz apkę i połącz" :
            "Odświeżono " + DateFormat.getTimeInstance(DateFormat.SHORT).format(new Date(synced));
        for (int id : ids) {
            RemoteViews views = new RemoteViews(context.getPackageName(), R.layout.todo_widget);
            views.setTextViewText(R.id.widget_status, status);
            Intent open = new Intent(context, MainActivity.class);
            views.setOnClickPendingIntent(R.id.widget_title, PendingIntent.getActivity(context, 0, open,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE));
            Intent refresh = new Intent(context, TodoWidget.class).setAction(REFRESH);
            views.setOnClickPendingIntent(R.id.widget_refresh, PendingIntent.getBroadcast(context, 1, refresh,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE));
            Intent service = new Intent(context, TodoWidgetService.class)
                .setData(Uri.parse("todo-pocket-widget://" + id));
            views.setRemoteAdapter(R.id.widget_list, service);
            Intent complete = new Intent(context, TodoWidget.class).setAction(COMPLETE)
                .setData(Uri.parse("todo-pocket-complete://" + id));
            views.setPendingIntentTemplate(R.id.widget_list, PendingIntent.getBroadcast(context, id, complete,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_MUTABLE));
            manager.updateAppWidget(id, views);
            manager.notifyAppWidgetViewDataChanged(id, R.id.widget_list);
        }
    }
}
