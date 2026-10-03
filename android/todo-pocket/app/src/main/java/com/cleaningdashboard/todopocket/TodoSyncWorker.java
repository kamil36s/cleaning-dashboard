package com.cleaningdashboard.todopocket;

import android.content.Context;
import androidx.annotation.NonNull;
import androidx.work.Worker;
import androidx.work.WorkerParameters;

public final class TodoSyncWorker extends Worker {
    public TodoSyncWorker(@NonNull Context context, @NonNull WorkerParameters params) { super(context, params); }
    @NonNull @Override public Result doWork() {
        if (TodoData.url(getApplicationContext()).isEmpty()) return Result.success();
        if (!WifiOnly.connected(getApplicationContext())) return Result.success();
        try {
            TodoApi.refresh(getApplicationContext());
            TodoData.prefs(getApplicationContext()).edit().remove("error").apply();
            TodoWidget.render(getApplicationContext());
            return Result.success();
        } catch (Exception e) {
            TodoData.prefs(getApplicationContext()).edit().putString("error", "Brak połączenia · dotknij ↻").apply();
            TodoWidget.render(getApplicationContext());
            return Result.retry();
        }
    }
}
