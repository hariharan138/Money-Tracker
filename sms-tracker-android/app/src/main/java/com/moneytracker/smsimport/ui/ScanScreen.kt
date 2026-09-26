package com.moneytracker.smsimport.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.CallMade
import androidx.compose.material.icons.automirrored.filled.CallReceived
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CheckboxDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.moneytracker.smsimport.ui.components.EmptyState
import com.moneytracker.smsimport.ui.components.PrimaryButton
import com.moneytracker.smsimport.ui.components.ScreenHeader
import com.moneytracker.smsimport.ui.components.Tone
import com.moneytracker.smsimport.ui.components.TransactionRow
import com.moneytracker.smsimport.ui.theme.LocalAppColors
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

@Composable
fun ScanScreen(
    viewModel: ScanViewModel,
    hasPermission: Boolean,
    onRequestPermission: () -> Unit
) {
    val candidates by viewModel.candidates.collectAsState()
    val isScanning by viewModel.isScanning.collectAsState()
    val colors = LocalAppColors.current
    val dateFormat = remember { SimpleDateFormat("dd MMM, hh:mm a", Locale.getDefault()) }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = 22.dp, vertical = 28.dp)
    ) {
        ScreenHeader(
            eyebrow = "On-device only",
            title = "Scan SMS",
            subtitle = "Everything stays on this phone. Nothing is uploaded."
        )
        Spacer(Modifier.height(20.dp))

        if (!hasPermission) {
            PrimaryButton(text = "Grant SMS permission", onClick = onRequestPermission)
        } else {
            PrimaryButton(
                text = if (isScanning) "Scanning…" else "Scan inbox",
                onClick = { viewModel.scanInbox() },
                enabled = !isScanning
            )
        }

        Spacer(Modifier.height(20.dp))

        val selectedCount = candidates.count { it.selected && !it.alreadyImported }

        when {
            candidates.isEmpty() && hasPermission -> EmptyState(
                "No transactions scanned yet. Tap “Scan inbox” to look for bank and UPI alerts."
            )
            candidates.isNotEmpty() -> {
                LazyColumn(
                    modifier = Modifier.fillMaxWidth().weight(1f, fill = true),
                    verticalArrangement = Arrangement.spacedBy(10.dp)
                ) {
                    itemsIndexed(candidates, key = { _, c -> c.parsed.sms.id }) { index, candidate ->
                        val p = candidate.parsed
                        val tone = if (p.type == "CREDIT") Tone.GREEN else Tone.AMBER
                        val sign = if (p.type == "CREDIT") "+" else "-"
                        val metaParts = listOfNotNull(
                            p.bank ?: p.sms.sender,
                            dateFormat.format(Date(p.sms.timestamp)),
                            "Already imported".takeIf { candidate.alreadyImported }
                        )
                        TransactionRow(
                            icon = if (p.type == "CREDIT") Icons.AutoMirrored.Filled.CallReceived else Icons.AutoMirrored.Filled.CallMade,
                            tone = tone,
                            title = p.merchant ?: (p.bank ?: p.sms.sender),
                            subtitle = null,
                            meta = metaParts.joinToString(" · "),
                            amountLabel = "$sign₹${"%.2f".format(p.amount)}",
                            leading = {
                                Checkbox(
                                    checked = candidate.selected,
                                    onCheckedChange = { viewModel.toggleSelection(index) },
                                    enabled = !candidate.alreadyImported,
                                    colors = CheckboxDefaults.colors(checkedColor = colors.accent)
                                )
                            }
                        )
                    }
                }

                Spacer(Modifier.height(12.dp))
                PrimaryButton(
                    text = "Import selected ($selectedCount)",
                    onClick = { viewModel.importSelected() },
                    enabled = selectedCount > 0,
                    modifier = Modifier.fillMaxWidth()
                )
            }
        }
    }
}
