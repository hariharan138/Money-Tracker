package com.moneytracker.smsimport.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.moneytracker.smsimport.ui.theme.LocalAppColors
import com.moneytracker.smsimport.ui.theme.LocalAppTypography

/** The rounded, softly-shadowed 18dp card every list row and panel sits in (CSS: .tx, .empty, box-shadow: var(--shadow)). */
val CardShape = RoundedCornerShape(18.dp)
val PillShape = RoundedCornerShape(percent = 50)
val ButtonShape = RoundedCornerShape(16.dp)

@Composable
fun AppCardSurface(
    modifier: Modifier = Modifier,
    shape: Shape = CardShape,
    content: @Composable () -> Unit
) {
    val colors = LocalAppColors.current
    Box(
        modifier = modifier
            .shadow(elevation = 6.dp, shape = shape, ambientColor = colors.shadow, spotColor = colors.shadow)
            .background(colors.card, shape)
    ) {
        content()
    }
}

/** eyebrow + bold title (+ optional muted subtitle), matching the CSS .eyebrow / h1 / .page-sub pattern. */
@Composable
fun ScreenHeader(
    eyebrow: String,
    title: String,
    subtitle: String? = null
) {
    val colors = LocalAppColors.current
    val type = LocalAppTypography.current
    Column {
        Text(eyebrow, style = type.eyebrow, color = colors.muted)
        Text(title, style = type.title, color = colors.ink)
        if (subtitle != null) {
            Spacer(Modifier.height(6.dp))
            Text(subtitle, style = type.pageSub, color = colors.muted)
        }
    }
}

enum class Tone { GREEN, AMBER, INK }

/** The 44dp circular category disc from CSS .icon / .icon.tone-*. Green = money in, amber = money out. */
@Composable
fun ToneIcon(icon: ImageVector, tone: Tone, size: androidx.compose.ui.unit.Dp = 44.dp) {
    val colors = LocalAppColors.current
    val (bg, fg) = when (tone) {
        Tone.GREEN -> colors.tintGreen to colors.green
        Tone.AMBER -> colors.tintAmber to colors.amberText
        Tone.INK -> colors.subtle to colors.ink
    }
    Box(
        modifier = Modifier
            .size(size)
            .background(bg, CircleShape),
        contentAlignment = Alignment.Center
    ) {
        Icon(icon, contentDescription = null, tint = fg)
    }
}

/**
 * One row in a transaction list: icon disc, name + meta, amount on the right.
 * Mirrors the CSS .tx grid (44px icon | flexible text | amount).
 */
@Composable
fun TransactionRow(
    icon: ImageVector,
    tone: Tone,
    title: String,
    subtitle: String?,
    meta: String,
    amountLabel: String,
    modifier: Modifier = Modifier,
    leading: (@Composable () -> Unit)? = null,
    trailing: (@Composable () -> Unit)? = null
) {
    val colors = LocalAppColors.current
    val type = LocalAppTypography.current

    AppCardSurface(modifier = modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .defaultMinSize(minHeight = 74.dp)
                .padding(horizontal = 14.dp, vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            if (leading != null) {
                leading()
                Spacer(Modifier.width(4.dp))
            }
            ToneIcon(icon = icon, tone = tone)
            Spacer(Modifier.width(12.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    title,
                    style = type.name,
                    color = colors.ink,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
                if (subtitle != null) {
                    Text(
                        subtitle,
                        style = type.meta,
                        color = colors.muted,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis
                    )
                }
                Text(
                    meta,
                    style = type.meta,
                    color = colors.muted,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
            }
            Spacer(Modifier.width(8.dp))
            Text(amountLabel, style = type.amount, color = colors.ink)
            if (trailing != null) {
                Spacer(Modifier.width(4.dp))
                trailing()
            }
        }
    }
}

/** Centered muted message in a rounded card, matching CSS .empty. */
@Composable
fun EmptyState(message: String) {
    val colors = LocalAppColors.current
    val type = LocalAppTypography.current
    AppCardSurface(modifier = Modifier.fillMaxWidth()) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .padding(vertical = 36.dp, horizontal = 18.dp),
            contentAlignment = Alignment.Center
        ) {
            Text(message, style = type.meta, color = colors.muted)
        }
    }
}

/** The dark "charcoal" primary action button (CSS .save-expense / --accent, --on-accent). */
@Composable
fun PrimaryButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true
) {
    val colors = LocalAppColors.current
    val type = LocalAppTypography.current
    Button(
        onClick = onClick,
        enabled = enabled,
        shape = ButtonShape,
        colors = ButtonDefaults.buttonColors(
            containerColor = colors.accent,
            contentColor = colors.onAccent,
            disabledContainerColor = colors.accent.copy(alpha = 0.55f),
            disabledContentColor = colors.onAccent.copy(alpha = 0.85f)
        ),
        modifier = modifier.height(50.dp)
    ) {
        Text(text, style = type.button)
    }
}

data class NavEntry(val label: String, val icon: ImageVector, val selected: Boolean, val onClick: () -> Unit)

/**
 * The floating pill bottom nav from CSS .bottom-nav: a rounded, elevated
 * capsule centered near the bottom of the screen rather than a full-width bar.
 */
@Composable
fun FloatingBottomNav(items: List<NavEntry>) {
    val colors = LocalAppColors.current
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 14.dp),
        contentAlignment = Alignment.Center
    ) {
        Row(
            modifier = Modifier
                .widthIn(max = 402.dp)
                .fillMaxWidth()
                .height(72.dp)
                .shadow(elevation = 10.dp, shape = PillShape, ambientColor = colors.shadow, spotColor = colors.shadow)
                .background(colors.card, PillShape)
                .padding(horizontal = 12.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            items.forEach { entry -> NavItem(entry) }
        }
    }
}

@Composable
private fun RowScope.NavItem(entry: NavEntry) {
    val colors = LocalAppColors.current
    val type = LocalAppTypography.current
    val tint = if (entry.selected) colors.ink else colors.muted

    Column(
        modifier = Modifier
            .weight(1f)
            .clickable(onClick = entry.onClick),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        Icon(entry.icon, contentDescription = entry.label, tint = tint)
        Spacer(Modifier.height(3.dp))
        Text(entry.label, style = type.navLabel, color = tint)
    }
}
