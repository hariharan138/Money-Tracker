package com.moneytracker.smsimport.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
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
import com.moneytracker.smsimport.data.TransactionEntity
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

@Composable
fun TransactionsScreen(viewModel: ScanViewModel) {
    val transactions by viewModel.transactions.collectAsState()
    val total by viewModel.totalSpent.collectAsState()
    val dateFormat = remember { SimpleDateFormat("dd MMM yyyy", Locale.getDefault()) }

    Column(modifier = Modifier.fillMaxSize().padding(16.dp)) {
        Text("Local transactions", style = MaterialTheme.typography.titleLarge)
        Text("Total spent: ₹${"%.2f".format(total)}", style = MaterialTheme.typography.bodyLarge)
        Spacer(Modifier.height(12.dp))

        if (transactions.isEmpty()) {
            Text("No transactions imported yet. Scan your SMS inbox to get started.")
        } else {
            LazyColumn {
                items(transactions, key = { it.id }) { transaction ->
                    TransactionRow(
                        transaction = transaction,
                        dateLabel = dateFormat.format(Date(transaction.smsDate)),
                        onDelete = { viewModel.deleteTransaction(transaction) }
                    )
                    HorizontalDivider()
                }
            }
        }
    }
}

@Composable
private fun TransactionRow(
    transaction: TransactionEntity,
    dateLabel: String,
    onDelete: () -> Unit
) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier.fillMaxWidth().padding(vertical = 8.dp)
    ) {
        Column(modifier = Modifier.fillMaxWidth(0.85f)) {
            val sign = if (transaction.type == "DEBIT") "-" else "+"
            Text(
                "$sign₹${"%.2f".format(transaction.amount)}",
                fontWeight = FontWeight.Bold
            )
            transaction.merchant?.let { Text(it) }
            Text(
                "${transaction.bank ?: transaction.smsSender} · $dateLabel",
                style = MaterialTheme.typography.labelSmall
            )
        }
        IconButton(onClick = onDelete) {
            Icon(Icons.Filled.Delete, contentDescription = "Delete")
        }
    }
}
