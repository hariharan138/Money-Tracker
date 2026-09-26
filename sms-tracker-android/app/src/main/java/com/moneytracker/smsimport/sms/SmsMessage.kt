package com.moneytracker.smsimport.sms

/** One raw row read from the device's SMS content provider. */
data class RawSms(
    val id: Long,
    val sender: String,
    val body: String,
    val timestamp: Long
)
