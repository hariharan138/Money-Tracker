package com.moneytracker.smsimport.ui.theme

import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color

/**
 * Design tokens mirrored 1:1 from frontend/styles.css (:root and
 * :root[data-theme="dark"]), so this native app reads as the same product
 * as the web dashboard rather than a generic Material app.
 */
data class AppColors(
    val ink: Color,
    val label: Color,
    val muted: Color,
    val soft: Color,
    val paper: Color,
    val card: Color,
    val subtle: Color,
    val chip: Color,
    val line: Color,
    val accent: Color,
    val onAccent: Color,
    val green: Color,
    val orange: Color,
    val danger: Color,
    val amberText: Color,
    val tintGreen: Color,
    val tintAmber: Color,
    val tintRed: Color,
    val shadow: Color
)

val LightAppColors = AppColors(
    ink = Color(0xFF151922),
    label = Color(0xFF5B6068),
    muted = Color(0xFF9A9DA5),
    soft = Color(0xFFC0C4CA),
    paper = Color(0xFFF5F5F7),
    card = Color(0xFFFFFFFF),
    subtle = Color(0xFFF4F5F7),
    chip = Color(0xFFEBEBEF),
    line = Color(0xFFE3E5E9),
    accent = Color(0xFF1C2128),
    onAccent = Color(0xFFFFFFFF),
    green = Color(0xFF22C55E),
    orange = Color(0xFFFFB02E),
    danger = Color(0xFFEF4444),
    amberText = Color(0xFFF59E0B),
    tintGreen = Color(0xFFE8FAF0),
    tintAmber = Color(0xFFFFF4E3),
    tintRed = Color(0xFFFDEAEA),
    shadow = Color(0xFF1C2128)
)

val DarkAppColors = AppColors(
    ink = Color(0xFFE9ECF1),
    label = Color(0xFFA6ADB7),
    muted = Color(0xFF8B919B),
    soft = Color(0xFF626973),
    paper = Color(0xFF101317),
    card = Color(0xFF181C22),
    subtle = Color(0xFF1E232A),
    chip = Color(0xFF242A32),
    line = Color(0xFF2A313A),
    accent = Color(0xFFEEF1F5),
    onAccent = Color(0xFF14181E),
    green = Color(0xFF22C55E),
    orange = Color(0xFFFFB02E),
    danger = Color(0xFFEF4444),
    amberText = Color(0xFFF5B544),
    tintGreen = Color(0xFF143025),
    tintAmber = Color(0xFF382B14),
    tintRed = Color(0xFF3B1F1F),
    shadow = Color(0xFF000000)
)

val LocalAppColors = staticCompositionLocalOf { LightAppColors }
