package com.example.wifipad.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

/**
 * 黑白双主题：
 *  - 深色：近黑底 + 浅灰控件
 *  - 浅色：近白底 + 深灰控件
 * ABXY 的功能色（绿/红/蓝/黄）在两种主题下保持不变。
 */
private val DarkColors = darkColorScheme(
    primary = Color(0xFFE8E8E8),
    onPrimary = Color(0xFF141414),
    secondary = Color(0xFFB0B0B0),
    onSecondary = Color(0xFF141414),
    background = Color(0xFF0C0C0C),
    onBackground = Color(0xFFEDEDED),
    surface = Color(0xFF181818),
    onSurface = Color(0xFFEDEDED),
    surfaceVariant = Color(0xFF262626),
    onSurfaceVariant = Color(0xFFC4C4C4),
    outline = Color(0xFF6B6B6B),
    outlineVariant = Color(0xFF3A3A3A),
)

private val LightColors = lightColorScheme(
    primary = Color(0xFF1C1C1C),
    onPrimary = Color(0xFFFFFFFF),
    secondary = Color(0xFF555555),
    onSecondary = Color(0xFFFFFFFF),
    background = Color(0xFFF3F3F3),
    onBackground = Color(0xFF141414),
    surface = Color(0xFFFFFFFF),
    onSurface = Color(0xFF141414),
    surfaceVariant = Color(0xFFE6E6E6),
    onSurfaceVariant = Color(0xFF444444),
    outline = Color(0xFF9A9A9A),
    outlineVariant = Color(0xFFCFCFCF),
)

@Composable
fun WifiPadTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit
) {
    MaterialTheme(
        colorScheme = if (darkTheme) DarkColors else LightColors,
        content = content
    )
}
