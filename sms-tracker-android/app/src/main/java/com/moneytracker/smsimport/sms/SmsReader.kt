package com.moneytracker.smsimport.sms

import android.content.Context
import android.provider.Telephony

/**
 * Reads every SMS on the device via the platform content provider.
 * Requires android.permission.READ_SMS to already be granted; the caller
 * (ScanViewModel) checks that before invoking this.
 */
object SmsReader {

    fun readAll(context: Context): List<RawSms> {
        val messages = mutableListOf<RawSms>()
        val projection = arrayOf(
            Telephony.Sms._ID,
            Telephony.Sms.ADDRESS,
            Telephony.Sms.BODY,
            Telephony.Sms.DATE
        )

        val cursor = context.contentResolver.query(
            Telephony.Sms.CONTENT_URI,
            projection,
            null,
            null,
            "${Telephony.Sms.DATE} DESC"
        )

        cursor?.use {
            val idIndex = it.getColumnIndexOrThrow(Telephony.Sms._ID)
            val addressIndex = it.getColumnIndexOrThrow(Telephony.Sms.ADDRESS)
            val bodyIndex = it.getColumnIndexOrThrow(Telephony.Sms.BODY)
            val dateIndex = it.getColumnIndexOrThrow(Telephony.Sms.DATE)

            while (it.moveToNext()) {
                messages.add(
                    RawSms(
                        id = it.getLong(idIndex),
                        sender = it.getString(addressIndex) ?: "",
                        body = it.getString(bodyIndex) ?: "",
                        timestamp = it.getLong(dateIndex)
                    )
                )
            }
        }

        return messages
    }
}
