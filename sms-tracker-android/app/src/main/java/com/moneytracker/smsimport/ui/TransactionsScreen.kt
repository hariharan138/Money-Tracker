package com.moneytracker.smsimport.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.CallMade
import androidx.compose.material.icons.automirrored.filled.CallReceived
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.moneytracker.smsimport.ui.components.EmptyState
import com.moneytracker.smsimport.ui.components.ScreenHeader
import com.moneytracker.smsimport.ui.components.Tone
import com.moneytracker.smsimport.ui.components.TransactionRow
import com.moneytracker.smsimport.ui.theme.LocalAppColors
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

@Composable
fun TransactionsScreen(viewModel: ScanViewModel) {
    val transactions by viewModel.transactions.collectAsState()
    val total by viewModel.totalSpent.collectAsState()
    val colors = LocalAppColors.current
    val dateFormat = remember { SimpleDateFormat("dd MMM yyyy", Locale.getDefault()) }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = 22.dp, vertical = 28.dp)
    ) {
        ScreenHeader(
            eyebrow = "Local ledger",
            title = "Transactions",
            subtitle = "Total spent: ₹${"%.2f".format(total)}"
        )
        Spacer(Modifier.height(20.dp))

        if (transactions.isEmpty()) {
            EmptyState("No transactions imported yet. Scan your SMS inbox to get started.")
        } else {
            LazyColumn(
                modifier = Modifier.fillMaxWidth(),
                verticalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                items(transactions, key = { it.id }) { transaction ->
                    TransactionRow(
                        icon = if (transaction.type == "CREDIT") Icons.AutoMirrored.Filled.CallReceived else Icons.AutoMirrored.Filled.CallMade,
                        tone = if (transaction.type == "CREDIT") Tone.GREEN else Tone.AMBER,
                        title = transaction.merchant ?: (transaction.bank ?: transaction.smsSender),
                        subtitle = null,
                        meta = "${transaction.bank ?: transaction.smsSender} · ${dateFormat.format(Date(transaction.smsDate))}",
                        amountLabel = "${if (transaction.type == "CREDIT") "+" else "-"}₹${"%.2f".format(transaction.amount)}",
                        trailing = {
                            IconButton(onClick = { viewModel.deleteTransaction(transaction) }) {
                                Icon(Icons.Filled.Delete, contentDescription = "Delete", tint = colors.soft)
                            }
                        }
                    )
                }
            }
        }
    }
}
