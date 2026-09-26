package com.moneytracker.smsimport.data

import androidx.room.Entity
import androidx.room.PrimaryKey

/** A transaction the user has confirmed and imported into local storage. */
@Entity(tableName = "transactions")
data class TransactionEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val amount: Double,
    val type: String,
    val merchant: String?,
    val accountLast4: String?,
    val bank: String?,
    val smsSender: String,
    val smsDate: Long,
    val rawBody: String,
    val category: String = "Uncategorized",
    val importedAt: Long = System.currentTimeMillis()
)
