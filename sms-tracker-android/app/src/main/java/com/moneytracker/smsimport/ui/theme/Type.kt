@file:OptIn(ExperimentalTextApi::class)

package com.moneytracker.smsimport.ui.theme

import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.text.ExperimentalTextApi
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontVariation
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp
import com.moneytracker.smsimport.R

/**
 * Plus Jakarta Sans (variable font), same family the web dashboard uses
 * (frontend/styles.css: font-family: "Plus Jakarta Sans", ...). One weight
 * axis instance per FontWeight used by AppTypography below.
 */
private fun jakartaWeight(weight: Int) = Font(
    resId = R.font.plus_jakarta_sans,
    weight = FontWeight(weight),
    variationSettings = FontVariation.Settings(FontVariation.weight(weight))
)

val PlusJakartaSans = FontFamily(
    jakartaWeight(400),
    jakartaWeight(500),
    jakartaWeight(650),
    jakartaWeight(700),
    jakartaWeight(720),
    jakartaWeight(760),
    jakartaWeight(800)
)

/** Text styles mapped from the CSS rules for h1, .eyebrow, .name, .desc/.meta, .amount, .nav-label. */
data class AppTypography(
    val title: TextStyle,
    val eyebrow: TextStyle,
    val pageSub: TextStyle,
    val name: TextStyle,
    val meta: TextStyle,
    val amount: TextStyle,
    val navLabel: TextStyle,
    val button: TextStyle
)

val DefaultAppTypography = AppTypography(
    title = TextStyle(
        fontFamily = PlusJakartaSans,
        fontWeight = FontWeight(800),
        fontSize = 24.sp,
        letterSpacing = (-0.7).sp,
        lineHeight = 27.sp
    ),
    eyebrow = TextStyle(
        fontFamily = PlusJakartaSans,
        fontWeight = FontWeight(500),
        fontSize = 13.sp
    ),
    pageSub = TextStyle(
        fontFamily = PlusJakartaSans,
        fontWeight = FontWeight(500),
        fontSize = 11.sp
    ),
    name = TextStyle(
        fontFamily = PlusJakartaSans,
        fontWeight = FontWeight(720),
        fontSize = 14.sp,
        letterSpacing = (-0.2).sp
    ),
    meta = TextStyle(
        fontFamily = PlusJakartaSans,
        fontWeight = FontWeight(400),
        fontSize = 11.sp
    ),
    amount = TextStyle(
        fontFamily = PlusJakartaSans,
        fontWeight = FontWeight(760),
        fontSize = 13.sp
    ),
    navLabel = TextStyle(
        fontFamily = PlusJakartaSans,
        fontWeight = FontWeight(650),
        fontSize = 10.sp,
        letterSpacing = (-0.1).sp
    ),
    button = TextStyle(
        fontFamily = PlusJakartaSans,
        fontWeight = FontWeight(800),
        fontSize = 15.sp
    )
)

val LocalAppTypography = staticCompositionLocalOf { DefaultAppTypography }
