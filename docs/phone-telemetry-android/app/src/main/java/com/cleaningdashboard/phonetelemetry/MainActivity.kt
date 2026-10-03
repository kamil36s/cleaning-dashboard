package com.cleaningdashboard.phonetelemetry

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.cleaningdashboard.phonetelemetry.permissions.TelemetryPermissionState
import com.cleaningdashboard.phonetelemetry.permissions.UsageAccessHelper

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        setContent {
            MaterialTheme {
                Surface(modifier = Modifier.fillMaxSize()) {
                    PermissionStatusScreen()
                }
            }
        }
    }
}

@Composable
private fun PermissionStatusScreen() {
    val context = LocalContext.current
    var refreshToken by remember { mutableIntStateOf(0) }
    var permissionState by remember {
        mutableStateOf(TelemetryPermissionState())
    }

    LaunchedEffect(refreshToken) {
        permissionState = UsageAccessHelper.getPermissionState(context)
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Text(
            text = "Phone Telemetry Setup",
            style = MaterialTheme.typography.headlineSmall
        )
        Text(
            text = "This screen is intentionally simple. It shows the two critical special-access permissions before you try to collect data.",
            style = MaterialTheme.typography.bodyMedium
        )

        PermissionCard(
            title = "Usage access",
            granted = permissionState.hasUsageAccess,
            detail = "Needed for app usage sessions and unlock/lock reconstruction.",
            actionLabel = "Open usage access settings",
            onAction = { UsageAccessHelper.openUsageAccessSettings(context) }
        )

        PermissionCard(
            title = "Notification listener",
            granted = permissionState.hasNotificationListenerAccess,
            detail = "Needed for message-like notification capture.",
            actionLabel = "Open notification listener settings",
            onAction = { UsageAccessHelper.openNotificationListenerSettings(context) }
        )

        Button(
            onClick = { refreshToken += 1 },
            modifier = Modifier.fillMaxWidth()
        ) {
            Text("Refresh status")
        }
    }
}

@Composable
private fun PermissionCard(
    title: String,
    granted: Boolean,
    detail: String,
    actionLabel: String,
    onAction: () -> Unit,
) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Text(text = title, style = MaterialTheme.typography.titleMedium)
            Text(
                text = if (granted) "Status: granted" else "Status: missing",
                style = MaterialTheme.typography.bodyMedium
            )
            Text(text = detail, style = MaterialTheme.typography.bodySmall)
            Button(onClick = onAction, modifier = Modifier.fillMaxWidth()) {
                Text(actionLabel)
            }
        }
    }
}
