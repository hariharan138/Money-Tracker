package com.moneytracker.smsimport

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.Scaffold
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.core.content.ContextCompat
import androidx.lifecycle.viewmodel.compose.viewModel
import com.moneytracker.smsimport.ui.ScanScreen
import com.moneytracker.smsimport.ui.ScanViewModel
import com.moneytracker.smsimport.ui.TransactionsScreen
import com.moneytracker.smsimport.ui.components.FloatingBottomNav
import com.moneytracker.smsimport.ui.components.NavEntry
import com.moneytracker.smsimport.ui.theme.LocalAppColors
import com.moneytracker.smsimport.ui.theme.SmsTrackerTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            SmsTrackerTheme {
                AppRoot()
            }
        }
    }
}

@Composable
private fun AppRoot() {
    val viewModel: ScanViewModel = viewModel()
    var selectedTab by remember { mutableIntStateOf(0) }
    var hasPermission by remember { mutableStateOf(false) }
    val context = LocalContext.current
    val colors = LocalAppColors.current

    LaunchedEffect(Unit) {
        hasPermission = ContextCompat.checkSelfPermission(
            context, Manifest.permission.READ_SMS
        ) == PackageManager.PERMISSION_GRANTED
    }

    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted -> hasPermission = granted }

    Scaffold(
        containerColor = colors.paper,
        bottomBar = {
            FloatingBottomNav(
                items = listOf(
                    NavEntry("Scan SMS", Icons.Filled.Search, selectedTab == 0) { selectedTab = 0 },
                    NavEntry("Transactions", Icons.AutoMirrored.Filled.List, selectedTab == 1) { selectedTab = 1 }
                )
            )
        }
    ) { padding ->
        Box(
            modifier = Modifier
                .background(colors.paper)
                .padding(padding)
        ) {
            when (selectedTab) {
                0 -> ScanScreen(
                    viewModel = viewModel,
                    hasPermission = hasPermission,
                    onRequestPermission = { permissionLauncher.launch(Manifest.permission.READ_SMS) }
                )
                else -> TransactionsScreen(viewModel = viewModel)
            }
        }
    }
}
