package com.moneytracker.smsimport.sms

import java.util.Locale

/** A transaction candidate extracted from one SMS. Not yet saved anywhere. */
data class ParsedTransaction(
    val amount: Double,
    val type: String, // "DEBIT" or "CREDIT"
    val merchant: String?,
    val accountLast4: String?,
    val bank: String?,
    val sms: RawSms
)

/**
 * Heuristic, regex-based reader for bank/UPI/card transaction alerts.
 * Tuned for common Indian bank SMS formats (HDFC, SBI, ICICI, Axis, Paytm,
 * PhonePe, UPI, ...). Non-transactional SMS never match and are dropped.
 *
 * This is a starting point, not an exhaustive bank-format database: add more
 * hint words / regex variants here as you find messages it misses.
 */
object TransactionParser {

    private val amountRegex = Regex(
        """(?:rs\.?|inr|₹)\s?([0-9][0-9,]*(?:\.[0-9]{1,2})?)""",
        RegexOption.IGNORE_CASE
    )

    private val debitKeywords = listOf(
        "debited", "spent", "withdrawn", "paid", "purchase", "sent", "debit"
    )

    private val creditKeywords = listOf(
        "credited", "received", "deposited", "refund", "credit"
    )

    private val merchantRegex = Regex(
        """(?:at|to|towards|VPA)\s+([A-Za-z0-9@.&_\- ]{2,30}?)(?:\s+on|\s+ref|\.|,|$)""",
        RegexOption.IGNORE_CASE
    )

    private val accountRegex = Regex(
        """(?:a/?c|acct|account|card)\D{0,12}([xX*]{2,}\d{2,4}|\d{4})""",
        RegexOption.IGNORE_CASE
    )

    private val bankSenderRegex = Regex("""^[A-Z]{2}-?[A-Z0-9]{4,8}$""")

    private val bankHintWords = listOf(
        "bank", "hdfc", "icici", "sbi", "axis", "kotak", "paytm", "phonepe",
        "upi", "ybl", "idfc", "yesbank", "pnb", "canara", "indusind"
    )

    /** Cheap pre-filter: does this look like a transaction alert at all? */
    fun isLikelyTransaction(sms: RawSms): Boolean {
        val body = sms.body.lowercase(Locale.ROOT)
        val hasAmount = amountRegex.containsMatchIn(sms.body)
        val hasKeyword = debitKeywords.any { body.contains(it) } ||
            creditKeywords.any { body.contains(it) }
        return hasAmount && hasKeyword
    }

    /** Returns null when the SMS is not a recognizable transaction alert. */
    fun parse(sms: RawSms): ParsedTransaction? {
        if (!isLikelyTransaction(sms)) return null

        val body = sms.body
        val lower = body.lowercase(Locale.ROOT)

        val amountMatch = amountRegex.find(body) ?: return null
        val amount = amountMatch.groupValues[1].replace(",", "").toDoubleOrNull() ?: return null

        val type = when {
            debitKeywords.any { lower.contains(it) } -> "DEBIT"
            creditKeywords.any { lower.contains(it) } -> "CREDIT"
            else -> "DEBIT"
        }

        val merchant = merchantRegex.find(body)?.groupValues?.get(1)?.trim()?.takeIf { it.isNotBlank() }
        val accountLast4 = accountRegex.find(body)?.groupValues?.get(1)?.takeLast(4)
        val bank = detectBank(sms.sender, lower)

        return ParsedTransaction(
            amount = amount,
            type = type,
            merchant = merchant,
            accountLast4 = accountLast4,
            bank = bank,
            sms = sms
        )
    }

    private fun detectBank(sender: String, lowerBody: String): String? {
        val upperSender = sender.uppercase(Locale.ROOT)

        bankHintWords.forEach { hint ->
            if (upperSender.contains(hint.uppercase(Locale.ROOT))) return hint.uppercase(Locale.ROOT)
        }
        bankHintWords.forEach { hint ->
            if (lowerBody.contains(hint)) return hint.uppercase(Locale.ROOT)
        }

        return if (bankSenderRegex.matches(upperSender)) upperSender else null
    }
}
