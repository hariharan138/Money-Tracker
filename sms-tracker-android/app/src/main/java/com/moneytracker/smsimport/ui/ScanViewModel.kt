package com.moneytracker.smsimport.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.moneytracker.smsimport.data.AppDatabase
import com.moneytracker.smsimport.data.TransactionEntity
import com.moneytracker.smsimport.data.TransactionRepository
import com.moneytracker.smsimport.data.fingerprintOf
import com.moneytracker.smsimport.sms.ParsedTransaction
import com.moneytracker.smsimport.sms.SmsReader
import com.moneytracker.smsimport.sms.TransactionParser
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

/** One scanned SMS shown in the review list, with its selection state. */
data class Candidate(
    val parsed: ParsedTransaction,
    val alreadyImported: Boolean,
    val selected: Boolean
)

class ScanViewModel(application: Application) : AndroidViewModel(application) {

    private val repository = TransactionRepository(
        AppDatabase.getInstance(application).transactionDao()
    )

    val transactions: StateFlow<List<TransactionEntity>> = repository.allTransactions
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val totalSpent: StateFlow<Double> = repository.totalSpent
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), 0.0)

    private val _candidates = MutableStateFlow<List<Candidate>>(emptyList())
    val candidates: StateFlow<List<Candidate>> = _candidates

    private val _isScanning = MutableStateFlow(false)
    val isScanning: StateFlow<Boolean> = _isScanning

    /** Reads the whole SMS inbox, parses it, and shows transaction candidates for review. */
    fun scanInbox() {
        viewModelScope.launch {
            _isScanning.value = true
            val context = getApplication<Application>()
            val fingerprints = repository.importedFingerprints()

            val parsed = SmsReader.readAll(context).mapNotNull { TransactionParser.parse(it) }

            _candidates.value = parsed.map { p ->
                val fp = fingerprintOf(p.sms.sender, p.sms.timestamp, p.sms.body)
                val already = fingerprints.contains(fp)
                Candidate(parsed = p, alreadyImported = already, selected = !already)
            }
            _isScanning.value = false
        }
    }

    fun toggleSelection(index: Int) {
        _candidates.value = _candidates.value.toMutableList().also { list ->
            val item = list[index]
            list[index] = item.copy(selected = !item.selected)
        }
    }

    /** Saves every selected, not-yet-imported candidate into local storage. */
    fun importSelected() {
        viewModelScope.launch {
            val toImport = _candidates.value
                .filter { it.selected && !it.alreadyImported }
                .map { it.parsed }

            if (toImport.isNotEmpty()) {
                repository.import(toImport)
            }

            val fingerprints = repository.importedFingerprints()
            _candidates.value = _candidates.value.map { c ->
                val fp = fingerprintOf(c.parsed.sms.sender, c.parsed.sms.timestamp, c.parsed.sms.body)
                if (fingerprints.contains(fp)) c.copy(alreadyImported = true, selected = false) else c
            }
        }
    }

    fun deleteTransaction(transaction: TransactionEntity) {
        viewModelScope.launch { repository.delete(transaction) }
    }
}
