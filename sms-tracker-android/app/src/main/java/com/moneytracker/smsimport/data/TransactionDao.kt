package com.moneytracker.smsimport.data

import androidx.room.Dao
import androidx.room.Delete
import androidx.room.Insert
import androidx.room.Query
import kotlinx.coroutines.flow.Flow

@Dao
interface TransactionDao {

    @Query("SELECT * FROM transactions ORDER BY smsDate DESC")
    fun getAll(): Flow<List<TransactionEntity>>

    /** sender|date|body per row, used to skip SMS that are already imported. */
    @Query("SELECT smsSender || '|' || smsDate || '|' || rawBody FROM transactions")
    suspend fun getImportedFingerprints(): List<String>

    @Insert
    suspend fun insertAll(transactions: List<TransactionEntity>)

    @Delete
    suspend fun delete(transaction: TransactionEntity)

    @Query("SELECT COALESCE(SUM(CASE WHEN type = 'DEBIT' THEN amount ELSE 0 END), 0) FROM transactions")
    fun getTotalSpent(): Flow<Double>
}
