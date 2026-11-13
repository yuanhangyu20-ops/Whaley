package com.example.wifipad.ui.components

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.pointer.PointerId
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.example.wifipad.haptic.HapticController
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlin.math.abs

/**
 * 蘑菇头摇杆。
 *
 * 手势冲突判定：
 *  - 手指按下后，位移超过 [DRAG_THRESHOLD] 视为「拖拽」，更新 X/Y；
 *  - 位移小于阈值且按住时间短于 [TAP_TIMEOUT_MS]，视为「点击」→ 触发 L3/R3。
 *
 * 视觉：
 *  - 同心圆纹理 + 高光的蘑菇头
 *  - L3/R3 触发时摇杆头短暂下沉（scale 0.9、阴影变浅）
 */
@Composable
fun Joystick(
    value: Offset,
    onChange: (Offset) -> Unit,
    onL3: () -> Unit,
    haptic: HapticController,
    isDark: Boolean,
    label: String,
    diameter: Dp,
    modifier: Modifier = Modifier
) {
    val density = LocalDensity.current
    val px = with(density) { diameter.toPx() }
    val baseR = px / 2f
    val knobR = px * 0.30f
    val maxR = baseR * 0.50f
    val dragThreshold = with(density) { 9.dp.toPx() }

    var center by remember { mutableStateOf(Offset.Zero) }
    var sunk by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()

    val fill = if (isDark) Color.White.copy(alpha = 0.06f) else Color.Black.copy(alpha = 0.05f)
    val ring = if (isDark) Color.White.copy(alpha = 0.14f) else Color.Black.copy(alpha = 0.14f)
    val border = if (isDark) Color.White.copy(alpha = 0.28f) else Color.Black.copy(alpha = 0.26f)
    val knobColor = if (isDark) Color(0xFF3A3A3A) else Color(0xFFEDEDED)
    val knobBorder = if (isDark) Color.White.copy(alpha = 0.30f) else Color.Black.copy(alpha = 0.28f)
    val shadowColor = if (isDark) Color.Black.copy(alpha = 0.55f) else Color.Black.copy(alpha = 0.22f)

    Canvas(
        modifier = modifier
            .size(diameter)
            .onGloballyPositioned { coords ->
                center = Offset(coords.size.width / 2f, coords.size.height / 2f)
            }
            .pointerInput(Unit) {
                awaitPointerEventScope {
                    var tracked: PointerId? = null
                    var downPos = Offset.Zero
                    var downTime = 0L
                    var moved = false

                    while (true) {
                        val event = awaitPointerEvent()
                        for (change in event.changes) {
                            val current = tracked
                            if (current == null) {
                                // 只接受落在底座范围内的按下
                                if (change.pressed &&
                                    (change.position - center).getDistance() <= baseR
                                ) {
                                    tracked = change.id
                                    downPos = change.position
                                    downTime = System.currentTimeMillis()
                                    moved = false
                                    change.consume()
                                }
                            } else if (change.id == current) {
                                if (change.pressed) {
                                    if ((change.position - downPos).getDistance() > dragThreshold) {
                                        moved = true
                                    }
                                    if (moved) {
                                        val delta = change.position - center
                                        val dist = delta.getDistance()
                                        val clamped =
                                            if (dist > maxR) delta / dist * maxR else delta
                                        onChange(Offset(clamped.x / maxR, -(clamped.y / maxR)))
                                    }
                                    change.consume()
                                } else {
                                    val heldMs = System.currentTimeMillis() - downTime
                                    val isTap = !moved && heldMs < 260
                                    tracked = null
                                    onChange(Offset.Zero)
                                    change.consume()

                                    if (isTap) {
                                        // 下压 L3/R3：短脉冲 + 视觉下沉
                                        sunk = true
                                        onL3()
                                        scope.launch {
                                            delay(110)
                                            sunk = false
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
    ) {
        val c = Offset(size.width / 2f, size.height / 2f)

        // ── 底座 ──
        drawCircle(fill, radius = baseR, center = c)
        drawCircle(border, radius = baseR, center = c, style = Stroke(1.5.dp.toPx()))
        // 底座内刻度圈
        drawCircle(ring, radius = baseR * 0.62f, center = c, style = Stroke(1.dp.toPx()))
        drawCircle(ring, radius = baseR * 0.30f, center = c, style = Stroke(1.dp.toPx()))
        // 方向刻度
        for (i in 0 until 4) {
            val angle = Math.toRadians((i * 90).toDouble())
            val inner = Offset(
                c.x + (baseR * 0.80f) * Math.cos(angle).toFloat(),
                c.y + (baseR * 0.80f) * Math.sin(angle).toFloat()
            )
            val outer = Offset(
                c.x + (baseR * 0.94f) * Math.cos(angle).toFloat(),
                c.y + (baseR * 0.94f) * Math.sin(angle).toFloat()
            )
            drawLine(ring, inner, outer, strokeWidth = 1.5.dp.toPx())
        }

        // ── 蘑菇头 ──
        val head = Offset(c.x + value.x * maxR, c.y - value.y * maxR)
        val scale = if (sunk) 0.88f else 1f
        val r = knobR * scale

        // 阴影
        drawCircle(shadowColor, radius = r * 1.06f, center = head + Offset(0f, 3.dp.toPx()))
        // 主体
        drawCircle(knobColor, radius = r, center = head)
        // 同心圆纹理
        for (i in 1..3) {
            drawCircle(
                ring,
                radius = r * (1f - i * 0.20f),
                center = head,
                style = Stroke(1.dp.toPx())
            )
        }
        // 左上高光
        drawCircle(
            Color.White.copy(alpha = 0.16f),
            radius = r * 0.42f,
            center = head + Offset(-r * 0.30f, -r * 0.30f)
        )
        // 外描边
        drawCircle(knobBorder, radius = r, center = head, style = Stroke(1.5.dp.toPx()))
    }
}
