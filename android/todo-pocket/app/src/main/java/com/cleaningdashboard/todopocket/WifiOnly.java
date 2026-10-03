package com.cleaningdashboard.todopocket;

import android.content.Context;
import android.net.ConnectivityManager;
import android.net.NetworkCapabilities;

final class WifiOnly {
    private WifiOnly() {}
    static boolean connected(Context context) {
        ConnectivityManager manager = (ConnectivityManager) context.getSystemService(Context.CONNECTIVITY_SERVICE);
        if (manager == null) return false;
        NetworkCapabilities capabilities = manager.getNetworkCapabilities(manager.getActiveNetwork());
        return capabilities != null && capabilities.hasTransport(NetworkCapabilities.TRANSPORT_WIFI);
    }
}
