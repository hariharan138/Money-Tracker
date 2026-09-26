package com.moneytracker.smsimport.data

import com.moneytracker.smsimport.sms.ParsedTransaction
import kotlinx.coroutines.flow.Flow

fun fingerprintOf(sender: String, date: Long, body: String) = "$sender|$date|$body"

class TransactionRepository(private val dao: TransactionDao) {

    val allTransactions: Flow<List<TransactionEntity>> = dao.getAll()
    val totalSpent: Flow<Double> = dao.getTotalSpent()

    suspend fun importedFingerprints(): Set<String> = dao.getImportedFingerprints().toSet()

    suspend fun import(parsed: List<ParsedTransaction>) {
        val entities = parsed.map {
            TransactionEntity(
                amount = it.amount,
                type = it.type,
                merchant = it.merchant,
                accountLast4 = it.accountLast4,
                bank = it.bank,
                smsSender = it.sms.sender,
                smsDate = it.sms.timestamp,
                rawBody = it.sms.body
            )
        }
        dao.insertAll(entities)
    }

    suspend fun delete(transaction: TransactionEntity) = dao.delete(transaction)
}
