package com.cleaningdashboard.todopocket;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import androidx.work.OneTimeWorkRequest;
import androidx.work.WorkManager;

/** ADB-only setup hook in debug builds; protected by Android's DUMP permission. */
public final class TodoSetupReceiver extends BroadcastReceiver {
    @Override public void onReceive(Context context, Intent intent) {
        if (!BuildConfig.DEBUG || !"com.cleaningdashboard.todopocket.SETUP".equals(intent.getAction())) return;
        try {
            TodoData.saveConfig(context, intent.getStringExtra("url"), intent.getStringExtra("token"));
            TodoWidget.schedule(context);
            WorkManager.getInstance(context).enqueue(new OneTimeWorkRequest.Builder(TodoSyncWorker.class).build());
            setResultCode(0);
        } catch (Exception e) { setResultCode(1); }
    }
}
