package com.moneytracker.smsimport.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.Composable
import androidx.compose.ui.unit.sp

private fun materialScheme(colors: AppColors, dark: Boolean) = if (dark) {
    darkColorScheme(
        primary = colors.accent,
        onPrimary = colors.onAccent,
        background = colors.paper,
        onBackground = colors.ink,
        surface = colors.card,
        onSurface = colors.ink,
        surfaceVariant = colors.subtle,
        error = colors.danger
    )
} else {
    lightColorScheme(
        primary = colors.accent,
        onPrimary = colors.onAccent,
        background = colors.paper,
        onBackground = colors.ink,
        surface = colors.card,
        onSurface = colors.ink,
        surfaceVariant = colors.subtle,
        error = colors.danger
    )
}

private val materialTypography = Typography(
    bodyLarge = DefaultAppTypography.meta.copy(fontSize = 13.sp),
    titleLarge = DefaultAppTypography.title,
    labelSmall = DefaultAppTypography.navLabel
)

@Composable
fun SmsTrackerTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit
) {
    val appColors = if (darkTheme) DarkAppColors else LightAppColors

    CompositionLocalProvider(
        LocalAppColors provides appColors,
        LocalAppTypography provides DefaultAppTypography
    ) {
        MaterialTheme(
            colorScheme = materialScheme(appColors, darkTheme),
            typography = materialTypography,
            content = content
        )
    }
}
