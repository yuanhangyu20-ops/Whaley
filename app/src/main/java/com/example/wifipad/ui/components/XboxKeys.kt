package com.example.wifipad.ui.components

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.lerp
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.pointer.PointerId
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.example.wifipad.haptic.HapticController
import kotlin.math.abs

/**
 * 通用「按住」手势：每个控件独立追踪自己的第一根手指，
 * 各控件同时按压互不干扰，并在按下瞬间触发震动。
 */
fun Modifier.pressGesture(
    haptic: HapticController,
    heavy: Boolean = false,
    onChange: (Boolean) -> Unit
): Modifier = this.pointerInput(Unit) {
    awaitPointerEventScope {
        var tracked: PointerId? = null
        while (true) {
            val event = awaitPointerEvent()
            for (change in event.changes) {
                val current = tracked
                if (current == null) {
                    if (change.pressed) {
                        tracked = change.id
                        if (heavy) haptic.press() else haptic.tick()
                        onChange(true)
                        change.consume()
                    }
                } else if (change.id == current && !change.pressed) {
                    tracked = null
                    onChange(false)
                    change.consume()
                }
            }
        }
    }
}

/**
 * Xbox ABXY 键：功能色 + 渐变高光 + 3D 阴影，按下时缩小、阴影消失。
 */
@Composable
fun XboxKey(
    label: String,
    color: Color,
    pressed: Boolean,
    haptic: HapticController,
    onPress: (Boolean) -> Unit,
    keySize: Dp = 56.dp
) {
    val scale by animateFloatAsState(if (pressed) 0.86f else 1f, label = "keyScale")
    val bright = lerp(color, Color.White, 0.32f)
    val deep = lerp(color, Color.Black, 0.30f)

    Box(
        modifier = Modifier
            .size(keySize)
            .graphicsLayer {
                scaleX = scale
                scaleY = scale
            }
            .shadow(elevation = if (pressed) 1.dp else 6.dp, shape = CircleShape)
            .clip(CircleShape)
            .background(
                Brush.verticalGradient(listOf(bright, color, deep))
            )
            .border(1.2.dp, deep.copy(alpha = 0.7f), CircleShape)
            .pressGesture(haptic, heavy = false, onChange = onPress),
        contentAlignment = Alignment.Center
    ) {
        // 左上角高光
        Canvas(Modifier.fillMaxSize()) {
            val s = size.width
            drawCircle(
                Color.White.copy(alpha = if (pressed) 0.10f else 0.30f),
                radius = s * 0.20f,
                center = Offset(s * 0.33f, s * 0.27f)
            )
        }
        Text(
            text = label,
            color = Color.White,
            fontSize = 21.sp,
            fontWeight = FontWeight.Black,
            fontFamily = FontFamily.SansSerif
        )
    }
}

/**
 * 一体化圆盘十字键：圆盘底 + 十字凸起，按下方向高亮，支持滑动切换方向。
 */
@Composable
fun DPad(
    pressedDir: Int?,
    onDirDown: (Int) -> Unit,
    onDirUp: () -> Unit,
    haptic: HapticController,
    isDark: Boolean,
    diameter: Dp = 132.dp
) {
    val density = androidx.compose.ui.platform.LocalDensity.current
    val sizePx = with(density) { diameter.toPx() }
    val fill = if (isDark) Color.White.copy(alpha = 0.06f) else Color.Black.copy(alpha = 0.05f)
    val ring = if (isDark) Color.White.copy(alpha = 0.14f) else Color.Black.copy(alpha = 0.14f)
    val border = if (isDark) Color.White.copy(alpha = 0.26f) else Color.Black.copy(alpha = 0.24f)
    val crossColor = if (isDark) Color(0xFF3A3A3A) else Color(0xFFEDEDED)
    val crossBorder = if (isDark) Color.White.copy(alpha = 0.22f) else Color.Black.copy(alpha = 0.20f)
    val activeColor = if (isDark) Color(0xFF9E9E9E) else Color(0xFF5A5A5A)

    Canvas(
        modifier = Modifier
            .size(diameter)
            .pointerInput(Unit) {
                awaitPointerEventScope {
                    var tracked: PointerId? = null
                    var currentDir: Int? = null

                    while (true) {
                        val event = awaitPointerEvent()
                        for (change in event.changes) {
                            val cur = tracked
                            if (cur == null) {
                                if (change.pressed) {
                                    tracked = change.id
                                    val dir = dirAt(change.position, sizePx)
                                    if (dir != null) {
                                        currentDir = dir
                                        haptic.tick()
                                        onDirDown(dir)
                                    }
                                    change.consume()
                                }
                            } else if (change.id == cur) {
                                if (change.pressed) {
                                    val dir = dirAt(change.position, sizePx)
                                    if (dir != currentDir) {
                                        currentDir = null
                                        onDirUp()
                                        if (dir != null) {
                                            currentDir = dir
                                            onDirDown(dir)
                                        }
                                    }
                                    change.consume()
                                } else {
                                    tracked = null
                                    currentDir = null
                                    onDirUp()
                                    change.consume()
                                }
                            }
                        }
                    }
                }
            }
    ) {
        val c = Offset(size.width / 2f, size.height / 2f)
        val r = size.width / 2f
        val armHalf = r * 0.19f
        val armLen = r * 0.82f

        drawCircle(fill, radius = r, center = c)
        drawCircle(border, radius = r, center = c, style = Stroke(1.5.dp.toPx()))
        drawCircle(ring, radius = r * 0.70f, center = c, style = Stroke(1.dp.toPx()))

        // 十字（两个圆角矩形叠加，形成一体化圆盘凸起）
        drawRoundRect(
            crossColor,
            topLeft = Offset(c.x - armLen, c.y - armHalf),
            size = Size(armLen * 2, armHalf * 2),
            cornerRadius = CornerRadius(armHalf)
        )
        drawRoundRect(
            crossColor,
            topLeft = Offset(c.x - armHalf, c.y - armLen),
            size = Size(armHalf * 2, armLen * 2),
            cornerRadius = CornerRadius(armHalf)
        )
        // 十字描边提示
        drawLine(
            crossBorder,
            Offset(c.x - armLen * 0.9f, c.y - armHalf),
            Offset(c.x + armLen * 0.9f, c.y - armHalf),
            strokeWidth = 1.dp.toPx()
        )
        drawLine(
            crossBorder,
            Offset(c.x - armLen * 0.9f, c.y + armHalf),
            Offset(c.x + armLen * 0.9f, c.y + armHalf),
            strokeWidth = 1.dp.toPx()
        )
        drawLine(
            crossBorder,
            Offset(c.x - armHalf, c.y - armLen * 0.9f),
            Offset(c.x - armHalf, c.y + armLen * 0.9f),
            strokeWidth = 1.dp.toPx()
        )
        drawLine(
            crossBorder,
            Offset(c.x + armHalf, c.y - armLen * 0.9f),
            Offset(c.x + armHalf, c.y + armLen * 0.9f),
            strokeWidth = 1.dp.toPx()
        )

        // 当前方向高亮
        when (pressedDir) {
            com.example.wifipad.ui.Btn.DPAD_UP -> drawRoundRect(
                activeColor,
                topLeft = Offset(c.x - armHalf, c.y - armLen),
                size = Size(armHalf * 2, armLen),
                cornerRadius = CornerRadius(armHalf)
            )
            com.example.wifipad.ui.Btn.DPAD_DOWN -> drawRoundRect(
                activeColor,
                topLeft = Offset(c.x - armHalf, c.y),
                size = Size(armHalf * 2, armLen),
                cornerRadius = CornerRadius(armHalf)
            )
            com.example.wifipad.ui.Btn.DPAD_LEFT -> drawRoundRect(
                activeColor,
                topLeft = Offset(c.x - armLen, c.y - armHalf),
                size = Size(armLen, armHalf * 2),
                cornerRadius = CornerRadius(armHalf)
            )
            com.example.wifipad.ui.Btn.DPAD_RIGHT -> drawRoundRect(
                activeColor,
                topLeft = Offset(c.x, c.y - armHalf),
                size = Size(armLen, armHalf * 2),
                cornerRadius = CornerRadius(armHalf)
            )
        }
    }
}

/** 根据触摸点相对圆心的方向判定 D-Pad 方向 */
private fun dirAt(position: Offset, sizePx: Float): Int? {
    val c = Offset(sizePx / 2f, sizePx / 2f)
    val dx = position.x - c.x
    val dy = position.y - c.y
    if (abs(dx) < sizePx * 0.06f && abs(dy) < sizePx * 0.06f) return null
    return if (abs(dx) > abs(dy)) {
        if (dx > 0) com.example.wifipad.ui.Btn.DPAD_RIGHT else com.example.wifipad.ui.Btn.DPAD_LEFT
    } else {
        if (dy > 0) com.example.wifipad.ui.Btn.DPAD_DOWN else com.example.wifipad.ui.Btn.DPAD_UP
    }
}

/**
 * 扳机键 LT / RT：圆角矩形，按下时从底部填充进度。
 */
@Composable
fun TriggerKey(
    label: String,
    pressed: Boolean,
    haptic: HapticController,
    isDark: Boolean,
    onPress: (Boolean) -> Unit,
    width: Dp = 104.dp,
    height: Dp = 46.dp
) {
    val progress by animateFloatAsState(if (pressed) 1f else 0f, label = "trigger")
    val scale by animateFloatAsState(if (pressed) 0.94f else 1f, label = "triggerScale")

    val fill = if (isDark) Color.White.copy(alpha = 0.07f) else Color.Black.copy(alpha = 0.05f)
    val border = if (isDark) Color.White.copy(alpha = 0.28f) else Color.Black.copy(alpha = 0.24f)
    val active = if (isDark) Color(0xFFBDBDBD) else Color(0xFF6A6A6A)
    val shape = RoundedCornerShape(12.dp)

    Box(
        modifier = Modifier
            .size(width, height)
            .graphicsLayer {
                scaleX = scale
                scaleY = scale
            }
            .clip(shape)
            .background(fill)
            .border(1.4.dp, border, shape)
            .pressGesture(haptic, heavy = false, onChange = onPress),
        contentAlignment = Alignment.Center
    ) {
        // 填充进度（从底部升起）
        Box(
            Modifier
                .fillMaxWidth()
                .fillMaxHeight(progress)
                .align(Alignment.BottomCenter)
                .background(
                    Brush.verticalGradient(
                        listOf(active.copy(alpha = 0.75f), active.copy(alpha = 0.35f))
                    )
                )
        )
        Text(
            label,
            color = if (isDark) Color.White.copy(alpha = 0.92f) else Color.Black.copy(alpha = 0.85f),
            fontSize = 15.sp,
            fontWeight = FontWeight.Bold,
            fontFamily = FontFamily.SansSerif
        )
    }
}

/**
 * 肩键 LB / RB：扁梯形，按下时下沉并变色。
 */
@Composable
fun ShoulderKey(
    label: String,
    pressed: Boolean,
    haptic: HapticController,
    isDark: Boolean,
    onPress: (Boolean) -> Unit,
    width: Dp = 118.dp,
    height: Dp = 44.dp
) {
    val scale by animateFloatAsState(if (pressed) 0.93f else 1f, label = "shoulderScale")
    val fill = if (isDark) Color.White.copy(alpha = 0.10f) else Color.Black.copy(alpha = 0.07f)
    val pressedFill = if (isDark) Color.White.copy(alpha = 0.30f) else Color.Black.copy(alpha = 0.22f)
    val border = if (isDark) Color.White.copy(alpha = 0.30f) else Color.Black.copy(alpha = 0.25f)

    Box(
        modifier = Modifier
            .size(width, height)
            .graphicsLayer {
                scaleX = scale
                scaleY = scale
                translationY = if (pressed) 2.dp.toPx() else 0f
            }
            .pointerInput(Unit) {
                awaitPointerEventScope {
                    var tracked: PointerId? = null
                    while (true) {
                        val event = awaitPointerEvent()
                        for (change in event.changes) {
                            val cur = tracked
                            if (cur == null) {
                                if (change.pressed) {
                                    tracked = change.id
                                    haptic.tick()
                                    onPress(true)
                                    change.consume()
                                }
                            } else if (change.id == cur && !change.pressed) {
                                tracked = null
                                onPress(false)
                                change.consume()
                            }
                        }
                    }
                }
            }
    ) {
        Canvas(Modifier.fillMaxSize()) {
            val w = size.width
            val h = size.height
            val path = Path().apply {
                moveTo(0f, h)
                lineTo(w, h)
                lineTo(w * 0.80f, 0f)
                lineTo(w * 0.20f, 0f)
                close()
            }
            drawPath(path, if (pressed) pressedFill else fill)
            drawPath(path, border, style = Stroke(1.4.dp.toPx()))
        }
        Text(
            label,
            modifier = Modifier.align(Alignment.Center),
            color = if (isDark) Color.White.copy(alpha = 0.9f) else Color.Black.copy(alpha = 0.8f),
            fontSize = 14.sp,
            fontWeight = FontWeight.Bold,
            fontFamily = FontFamily.SansSerif
        )
    }
}
