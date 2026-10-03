package com.cleaningdashboard.phonetracker

import android.content.Intent
import android.content.ComponentName
import android.os.Bundle
import android.os.PowerManager
import android.provider.Settings
import android.net.Uri
import android.Manifest
import android.content.pm.PackageManager
import androidx.core.content.ContextCompat
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.core.splashscreen.SplashScreen.Companion.installSplashScreen
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.Image
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Surface
import androidx.compose.material3.darkColorScheme
import androidx.compose.ui.Alignment
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.core.app.NotificationManagerCompat
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.coroutines.launch
import androidx.lifecycle.lifecycleScope
import java.net.HttpURLConnection
import java.net.URL

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        installSplashScreen()
        super.onCreate(savedInstanceState)
        runCatching { TrackerConfig.importOneTimePairing(applicationContext) }
        SyncScheduler.periodic(applicationContext)
        SyncScheduler.collectNow(applicationContext)
        SyncScheduler.immediate(applicationContext)
        GuardService.start(applicationContext)
        if (android.os.Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(this,Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED)
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS),744)
        setContent {
            MaterialTheme(colorScheme = darkColorScheme(
                primary = Color(0xFF76E7CD), onPrimary = Color(0xFF092126),
                background = Color(0xFF091A22), surface = Color(0xFF102833),
                onBackground = Color(0xFFE8F8F6), onSurface = Color(0xFFE8F8F6))) {
                Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) { TrackerScreen() }
            }
        }
    }

    @Composable
    private fun TrackerScreen() {
        val pairing = remember { TrackerConfig.load(this) }
        var server by remember { mutableStateOf(pairing?.server ?: "") }
        var deviceId by remember { mutableStateOf(pairing?.deviceId ?: "") }
        var token by remember { mutableStateOf("") }
        var message by remember { mutableStateOf("") }
        var pending by remember { mutableIntStateOf(0) }
        var rejected by remember { mutableIntStateOf(0) }
        var lastEvent by remember { mutableStateOf<String?>(null) }
        var lastUsage by remember { mutableStateOf<String?>(null) }
        var lastNotification by remember { mutableStateOf<String?>(null) }
        var lastLocation by remember { mutableStateOf<String?>(null) }
        var ready by remember { mutableStateOf(false) }
        var refresh by remember { mutableIntStateOf(0) }
        var access by remember { mutableStateOf<AccessStatus?>(null) }
        var shortcutTargets by remember { mutableStateOf<List<String>>(emptyList()) }
        LaunchedEffect(refresh) {
            val dao = TrackerDatabase.get(applicationContext).dao()
            pending = withContext(Dispatchers.IO) { dao.pendingCount() }
            rejected = withContext(Dispatchers.IO) { dao.rejectedCount() }
            lastEvent = withContext(Dispatchers.IO) { dao.lastEvent() }
            lastUsage = withContext(Dispatchers.IO) { dao.lastOfType("app_foreground") }
            lastNotification = withContext(Dispatchers.IO) { dao.lastOfType("notification_posted") }
            lastLocation = withContext(Dispatchers.IO) { dao.lastOfType("location") }
            access = withContext(Dispatchers.IO) { RuleEngine.accessStatus(applicationContext,"com.instagram.android") }
            shortcutTargets = RulesCache.read(applicationContext).optJSONObject("access")?.optJSONArray("policies")
                ?.let { array -> (0 until array.length()).mapNotNull { index ->
                    array.optJSONObject(index)?.takeIf { it.optBoolean("enabled",true) }
                        ?.optString("target")?.takeIf { it.isNotBlank() }
                } } ?: emptyList()
            ready = true
        }
        if (!ready) {
            Box(Modifier.fillMaxSize().statusBarsPadding().navigationBarsPadding()
                .background(Color(0xFF091A22)), contentAlignment = Alignment.Center) {
                Column(horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(14.dp)) {
                    Image(painterResource(R.drawable.ic_tracker_mark), contentDescription = null,
                        modifier = Modifier.size(112.dp))
                    Text("PHONE TRACKER", style = MaterialTheme.typography.headlineSmall)
                    Text("Loading local activity", color = Color(0xFF9BBFC0))
                    Spacer(Modifier.height(4.dp))
                    CircularProgressIndicator(color = Color(0xFF76E7CD))
                }
            }
            return
        }
        Column(Modifier.fillMaxSize().statusBarsPadding().navigationBarsPadding()
            .verticalScroll(rememberScrollState()).padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Image(painterResource(R.drawable.ic_tracker_mark), contentDescription = null,
                    modifier = Modifier.size(52.dp))
                Text("PHONE TRACKER", style = MaterialTheme.typography.headlineMedium)
            }
            Text("Local collection and Wi-Fi sync", style = MaterialTheme.typography.bodyMedium)
            access?.let { budget ->
                Surface(color = Color(0xFF173840),shape = androidx.compose.foundation.shape.RoundedCornerShape(16.dp),
                    modifier = Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(16.dp),verticalArrangement = Arrangement.spacedBy(5.dp)) {
                        Text("INSTAGRAM ACCESS",color=Color(0xFF76E7CD),style=MaterialTheme.typography.labelLarge)
                        Text("${kotlin.math.round(budget.remaining).toInt()} min available now",style=MaterialTheme.typography.headlineSmall)
                        Text("Unlocked ${kotlin.math.round(budget.unlocked).toInt()} / ${kotlin.math.round(budget.baseline).toInt()} min · used ${kotlin.math.round(budget.used).toInt()} min")
                        Text("Reading ${(budget.reading?.optDouble("progress",0.0)?.times(100))?.toInt() ?: 0}% · " +
                            "Cleaning ${(budget.cleaning?.optDouble("progress",0.0)?.times(100))?.toInt() ?: 0}%")
                    }
                }
            }
            if (!isBlockerEnabled()) Text("App blocking is OFF. Enable Phone Tracker limits in Accessibility settings.",
                color = Color(0xFFFFA8A8))
            HorizontalDivider()
            PermissionRow("Usage Access", UsageCollector.hasAccess(this@MainActivity),
                "App foreground, screen and unlock events",
                Settings.ACTION_USAGE_ACCESS_SETTINGS)
            PermissionRow("Notification Access",
                NotificationManagerCompat.getEnabledListenerPackages(this@MainActivity).contains(packageName),
                "Notification count, title and text",
                Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS)
            PermissionRow("Accessibility blocker", isBlockerEnabled(),
                "Required for app blocking, even when this screen is closed",
                Settings.ACTION_ACCESSIBILITY_SETTINGS)
            PermissionRow("Approximate location",
                ContextCompat.checkSelfPermission(this@MainActivity,Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED,
                "Optional low-power place estimates",Settings.ACTION_APPLICATION_DETAILS_SETTINGS)
            PermissionRow("Background location",
                ContextCompat.checkSelfPermission(this@MainActivity,Manifest.permission.ACCESS_BACKGROUND_LOCATION) == PackageManager.PERMISSION_GRANTED,
                "Optional place collection while the app is closed",Settings.ACTION_APPLICATION_DETAILS_SETTINGS)
            val power = getSystemService(PowerManager::class.java)
            PermissionRow("Battery optimization", power.isIgnoringBatteryOptimizations(packageName),
                "Allow scheduled collection on HyperOS",
                Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS)
            Text("HyperOS can stop Accessibility when Phone Tracker is removed from recent apps. Allow Background autostart and set Battery saver to No restrictions for Phone Tracker.",
                color = Color(0xFFFFD0A4))
            Button(onClick = {
                val intent = Intent().setComponent(ComponentName("com.miui.securitycenter",
                    "com.miui.permcenter.autostart.AutoStartManagementActivity"))
                try { startActivity(intent) } catch (_: Exception) {
                    startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                        Uri.parse("package:$packageName")))
                }
            }) { Text("Background autostart settings") }
            if (shortcutTargets.isNotEmpty()) {
                HorizontalDivider()
                Text("Managed home shortcuts",style = MaterialTheme.typography.titleLarge)
                Text("A managed shortcut can display a black Locked icon and opens through Phone Tracker. Android keeps the original app icon in the app drawer; remove its old home shortcut if you use this one.")
                for (pkg in shortcutTargets) {
                    val label = try { packageManager.getApplicationLabel(
                        packageManager.getApplicationInfo(pkg,0)).toString() }
                        catch (_: Exception) { pkg.substringAfterLast('.') }
                    Button(onClick = {
                        lifecycleScope.launch {
                            val locked = withContext(Dispatchers.IO) {
                                try { RuleEngine.evaluate(applicationContext,pkg) != null }
                                catch (_: Exception) { true }
                            }
                            message = if (ManagedShortcuts.pin(this@MainActivity,pkg,locked))
                                "Approve the $label shortcut in the launcher"
                                else "This launcher does not support managed shortcuts"
                        }
                    }) { Text("Add $label shortcut") }
                }
            }
            HorizontalDivider()
            Text("PC pairing", style = MaterialTheme.typography.titleLarge)
            Text(if (pairing == null) "Create a device in the PC dashboard. Copy the server address, device ID and token here."
                 else "Paired securely with the PC. The token is stored in Android Keystore and hidden here.")
            OutlinedTextField(server, { server = it }, label = { Text("LAN server, e.g. http://192.168.1.2:8000") },
                modifier = Modifier.fillMaxWidth(), singleLine = true)
            OutlinedTextField(deviceId, { deviceId = it }, label = { Text("Device ID") },
                modifier = Modifier.fillMaxWidth(), singleLine = true)
            OutlinedTextField(token, { token = it }, label = { Text(if (pairing == null) "Pairing token" else "New token (leave blank to keep current)") },
                modifier = Modifier.fillMaxWidth(), singleLine = true,
                visualTransformation = PasswordVisualTransformation())
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = {
                    try {
                        val savedToken = token.ifBlank { TrackerConfig.load(this@MainActivity)?.token.orEmpty() }
                        TrackerConfig.save(this@MainActivity, Pairing(server, deviceId, savedToken))
                        token = ""
                        message = "Pairing saved in Android Keystore. Sync queued."
                        SyncScheduler.collectNow(applicationContext)
                        SyncScheduler.immediate(applicationContext)
                    } catch (error: Exception) { message = error.message ?: "Invalid pairing" }
                }) { Text("Save pairing") }
                Button(onClick = {
                    SyncScheduler.collectNow(applicationContext)
                    SyncScheduler.immediate(applicationContext)
                    refresh++
                    message = "Collection and sync queued"
                }) { Text("Sync now") }
            }
            if (message.isNotBlank()) Text(message)
            HorizontalDivider()
            Text("Diagnostics", style = MaterialTheme.typography.titleLarge)
            Text("Pending events: $pending")
            Text("Rejected events: $rejected")
            Text("Last event: ${lastEvent ?: "none"}")
            Text("Last app event: ${lastUsage ?: "none"}")
            Text("Last notification: ${lastNotification ?: "none"}")
            Text("Last location: ${lastLocation ?: "none"}")
            Text("Last sync: ${TrackerConfig.lastSync(this@MainActivity) ?: "none"}")
            Text("Last error: ${TrackerConfig.lastError(this@MainActivity) ?: "none"}")
            Text("The collector scans Android's usage history every 15 minutes. HyperOS may delay background jobs; opening this app triggers another scan.")
            Button(onClick = { refresh++ }) { Text("Refresh status") }
            Button(onClick = {
                lifecycleScope.launch {
                    val saved = TrackerConfig.load(applicationContext)
                    if (saved == null) { message = "Pair a phone first"; return@launch }
                    message = withContext(Dispatchers.IO) {
                        try {
                            val conn = (URL("${saved.server}/api/phone-tracker/config").openConnection() as HttpURLConnection).apply {
                                connectTimeout = 8000; readTimeout = 8000
                                setRequestProperty("Authorization","Bearer ${saved.token}")
                                setRequestProperty("X-Phone-Device-ID",saved.deviceId)
                            }
                            try { if (conn.responseCode == 200) "PC connection OK" else "PC HTTP ${conn.responseCode}" }
                            finally { conn.disconnect() }
                        } catch (error: Exception) { "Connection failed: ${error.message?.take(100)}" }
                    }
                }
            }) { Text("Test PC connection") }
            Button(onClick = {
                val diagnostic = "Phone Tracker diagnostics\nUsage access: ${UsageCollector.hasAccess(this@MainActivity)}\n" +
                    "Pending: $pending\nRejected: $rejected\nLast event: $lastEvent\nLast sync: ${TrackerConfig.lastSync(this@MainActivity)}\n" +
                    "Last error: ${TrackerConfig.lastError(this@MainActivity)}\nServer: ${TrackerConfig.load(this@MainActivity)?.server}\n"
                startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).apply {
                    type = "text/plain"; putExtra(Intent.EXTRA_TEXT,diagnostic)
                },"Export diagnostics"))
            }) { Text("Export diagnostics") }
        }
    }

    @Composable
    private fun PermissionRow(name: String, granted: Boolean, explanation: String, action: String) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Column(Modifier.weight(1f)) {
                Text("$name  ${if (granted) "✓" else "!"}", style = MaterialTheme.typography.titleMedium)
                Text(explanation, style = MaterialTheme.typography.bodySmall)
            }
            Button(onClick = {
                val intent = Intent(action)
                if (action == Settings.ACTION_APPLICATION_DETAILS_SETTINGS) intent.data = Uri.parse("package:$packageName")
                try { startActivity(intent) } catch (_: Exception) { startActivity(Intent(Settings.ACTION_SETTINGS)) }
            }) { Text("Settings") }
        }
    }

    private fun isBlockerEnabled(): Boolean {
        return BlockerHealth.isRunning(this)
    }
}
