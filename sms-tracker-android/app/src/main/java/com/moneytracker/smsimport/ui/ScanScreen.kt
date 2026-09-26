package com.moneytracker.smsimport.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
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
    val dateFormat = remember { SimpleDateFormat("dd MMM yyyy, hh:mm a", Locale.getDefault()) }

    Column(modifier = Modifier.fillMaxSize().padding(16.dp)) {
        Text("Scan your SMS inbox for transactions", style = MaterialTheme.typography.titleLarge)
        Spacer(Modifier.height(4.dp))
        Text(
            "Everything stays on this device. Nothing is uploaded.",
            style = MaterialTheme.typography.bodyLarge
        )
        Spacer(Modifier.height(16.dp))

        if (!hasPermission) {
            Button(onClick = onRequestPermission) {
                Text("Grant SMS permission")
            }
        } else {
            Button(onClick = { viewModel.scanInbox() }, enabled = !isScanning) {
                Text(if (isScanning) "Scanning…" else "Scan inbox")
            }
        }

        Spacer(Modifier.height(16.dp))

        val selectedCount = candidates.count { it.selected && !it.alreadyImported }

        if (candidates.isNotEmpty()) {
            Text("${candidates.size} possible transactions found", style = MaterialTheme.typography.bodyLarge)
            Spacer(Modifier.height(8.dp))

            LazyColumn(modifier = Modifier.fillMaxWidth().weight(1f, fill = true)) {
                itemsIndexed(candidates) { index, candidate ->
                    CandidateRow(
                        candidate = candidate,
                        dateLabel = dateFormat.format(Date(candidate.parsed.sms.timestamp)),
                        onToggle = { viewModel.toggleSelection(index) }
                    )
                    HorizontalDivider()
                }
            }

            Spacer(Modifier.height(8.dp))
            Button(
                onClick = { viewModel.importSelected() },
                enabled = selectedCount > 0,
                modifier = Modifier.fillMaxWidth()
            ) {
                Text("Import selected ($selectedCount)")
            }
        }
    }
}

@Composable
private fun CandidateRow(
    candidate: Candidate,
    dateLabel: String,
    onToggle: () -> Unit
) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier.fillMaxWidth().padding(vertical = 8.dp)
    ) {
        Checkbox(
            checked = candidate.selected,
            onCheckedChange = { onToggle() },
            enabled = !candidate.alreadyImported
        )
        Spacer(Modifier.width(8.dp))
        Column {
            val sign = if (candidate.parsed.type == "DEBIT") "-" else "+"
            Text(
                "$sign₹${"%.2f".format(candidate.parsed.amount)}  ${candidate.parsed.type}",
                fontWeight = FontWeight.Bold
            )
            candidate.parsed.merchant?.let { Text(it, style = MaterialTheme.typography.bodyLarge) }
            Text(
                "${candidate.parsed.bank ?: candidate.parsed.sms.sender} · $dateLabel",
                style = MaterialTheme.typography.labelSmall
            )
            if (candidate.alreadyImported) {
                Text("Already imported", style = MaterialTheme.typography.labelSmall)
            }
        }
    }
}
