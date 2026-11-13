package com.example.wifipad.ui

import android.app.Activity
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.pointer.PointerId
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat

/** 半透明控件常用色 */
private val GlassFill = Color.White.copy(alpha = 0.12f)
private val GlassFillActive = Color.White.copy(alpha = 0.42f)
private val GlassBorder = Color.White.copy(alpha = 0.38f)
private val GlassBorderActive = Color.White.copy(alpha = 0.92f)
private val DebugGreen = Color(0xFF00E676)
private val DebugText = Color(0xFFB2FF59)

@Composable
fun GamepadScreen() {
    val state = remember { GamepadState() }
    HideSystemBars()

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Color.Black.copy(alpha = 0.32f))
    ) {
        // ── 顶部左右扳机 ──
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 26.dp, vertical = 10.dp),
            horizontalArrangement = Arrangement.SpaceBetween
        ) {
            TriggerKey(label = "LT", active = state.lTrigger > 0.5f) { down ->
                state.lTrigger = if (down) 1f else 0f
            }
            TriggerKey(label = "RT", active = state.rTrigger > 0.5f) { down ->
                state.rTrigger = if (down) 1f else 0f
            }
        }

        // ── 左下：摇杆 ──
        Box(
            modifier = Modifier
                .align(Alignment.BottomStart)
                .padding(start = 34.dp, bottom = 18.dp)
        ) {
            Joystick(state = state, diameter = 150.dp)
        }

        // ── 左上偏中：十字键 ──
        Box(
            modifier = Modifier
                .align(Alignment.TopStart)
                .padding(start = 96.dp, top = 74.dp)
        ) {
            DPad(state = state)
        }

        // ── 右侧：ABXY ──
        Box(
            modifier = Modifier
                .align(Alignment.CenterEnd)
                .padding(end = 44.dp, top = 18.dp)
        ) {
            ActionKeys(state = state)
        }

        // ── 顶部中央：调试面板 ──
        Box(
            modifier = Modifier
                .align(Alignment.TopCenter)
                .padding(top = 6.dp)
        ) {
            DebugPanel(state = state)
        }
    }
}

/** 隐藏系统状态栏/导航栏，进入沉浸全屏 */
@Composable
private fun HideSystemBars() {
    val view = LocalView.current
    androidx.compose.runtime.SideEffect {
        val activity = view.context as? Activity ?: return@SideEffect
        val window = activity.window
        WindowCompat.setDecorFitsSystemWindows(window, false)
        WindowInsetsControllerCompat(window, view).apply {
            hide(WindowInsetsCompat.Type.systemBars())
            systemBarsBehavior = WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        }
    }
}

/**
 * 通用「按住」手势：每个控件独立追踪自己的第一根手指，
 * 多个控件同时按压互不干扰（多点触控的基础）。
 */
private fun Modifier.pressGesture(onChange: (Boolean) -> Unit): Modifier = this.pointerInput(Unit) {
    awaitPointerEventScope {
        var tracked: PointerId? = null
        while (true) {
            val event = awaitPointerEvent()
            for (change in event.changes) {
                val current = tracked
                if (current == null) {
                    if (change.pressed) {
                        tracked = change.id
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

@Composable
private fun TriggerKey(label: String, active: Boolean, onDown: (Boolean) -> Unit) {
    Box(
        modifier = Modifier
            .size(width = 112.dp, height = 44.dp)
            .clip(RoundedCornerShape(10.dp))
            .background(if (active) GlassFillActive else GlassFill)
            .border(2.dp, if (active) GlassBorderActive else GlassBorder, RoundedCornerShape(10.dp))
            .pressGesture(onDown),
        contentAlignment = Alignment.Center
    ) {
        Text(label, color = Color.White, fontSize = 15.sp, fontWeight = FontWeight.Bold)
    }
}

/** 圆形按键（ABXY 与方向键共用） */
@Composable
private fun RoundKey(
    label: String,
    active: Boolean,
    onDown: (Boolean) -> Unit,
    size: Dp = 56.dp
) {
    Box(
        modifier = Modifier
            .size(size)
            .clip(CircleShape)
            .background(if (active) GlassFillActive else GlassFill)
            .border(2.dp, if (active) GlassBorderActive else GlassBorder, CircleShape)
            .pressGesture(onDown),
        contentAlignment = Alignment.Center
    ) {
        Text(label, color = Color.White, fontSize = 18.sp, fontWeight = FontWeight.Bold)
    }
}

/** ABXY 菱形布局 */
@Composable
private fun ActionKeys(state: GamepadState) {
    val key = 54.dp
    Box(modifier = Modifier.size(key * 2 + 22.dp)) {
        Box(Modifier.align(Alignment.TopCenter)) {
            RoundKey("Y", state.isDown(Btn.Y), { d -> toggle(state, Btn.Y, d) }, key)
        }
        Box(Modifier.align(Alignment.CenterStart)) {
            RoundKey("X", state.isDown(Btn.X), { d -> toggle(state, Btn.X, d) }, key)
        }
        Box(Modifier.align(Alignment.CenterEnd)) {
            RoundKey("B", state.isDown(Btn.B), { d -> toggle(state, Btn.B, d) }, key)
        }
        Box(Modifier.align(Alignment.BottomCenter)) {
            RoundKey("A", state.isDown(Btn.A), { d -> toggle(state, Btn.A, d) }, key)
        }
    }
}

/** 十字键 */
@Composable
private fun DPad(state: GamepadState) {
    val key = 46.dp
    Box(modifier = Modifier.size(key * 2 + 18.dp)) {
        Box(Modifier.align(Alignment.TopCenter)) {
            RoundKey("↑", state.isDown(Btn.DPAD_UP), { d -> toggle(state, Btn.DPAD_UP, d) }, key)
        }
        Box(Modifier.align(Alignment.BottomCenter)) {
            RoundKey("↓", state.isDown(Btn.DPAD_DOWN), { d -> toggle(state, Btn.DPAD_DOWN, d) }, key)
        }
        Box(Modifier.align(Alignment.CenterStart)) {
            RoundKey("←", state.isDown(Btn.DPAD_LEFT), { d -> toggle(state, Btn.DPAD_LEFT, d) }, key)
        }
        Box(Modifier.align(Alignment.CenterEnd)) {
            RoundKey("→", state.isDown(Btn.DPAD_RIGHT), { d -> toggle(state, Btn.DPAD_RIGHT, d) }, key)
        }
    }
}

private fun toggle(state: GamepadState, id: Int, down: Boolean) {
    if (down) state.press(id) else state.release(id)
}

/**
 * 模拟摇杆。
 * 指针事件在 Canvas 上手动处理：只锁定第一根落在底座范围内的手指，
 * 其余手指事件完全不受影响 → 左手摇杆与右手按键可同时工作。
 */
@Composable
private fun Joystick(state: GamepadState, diameter: Dp) {
    val density = LocalDensity.current
    val pxSize = with(density) { diameter.toPx() }
    val baseR = pxSize / 2f
    val knobR = pxSize * 0.21f
    val maxR = baseR * 0.68f

    var center by remember { mutableStateOf(Offset.Zero) }
    var tracked by remember { mutableStateOf<PointerId?>(null) }

    Canvas(
        modifier = Modifier
            .size(diameter)
            .onGloballyPositioned { coords ->
                center = Offset(coords.size.width / 2f, coords.size.height / 2f)
            }
            .pointerInput(Unit) {
                awaitPointerEventScope {
                    while (true) {
                        val event = awaitPointerEvent()
                        for (change in event.changes) {
                            val current = tracked
                            if (current == null) {
                                if (change.pressed &&
                                    (change.position - center).getDistance() <= baseR * 1.2f
                                ) {
                                    tracked = change.id
                                    updateStick(state, change.position, center, maxR)
                                    change.consume()
                                }
                            } else if (change.id == current) {
                                if (change.pressed) {
                                    updateStick(state, change.position, center, maxR)
                                    change.consume()
                                } else {
                                    tracked = null
                                    state.setStick(0f, 0f)
                                    change.consume()
                                }
                            }
                        }
                    }
                }
            }
    ) {
        val c = Offset(size.width / 2f, size.height / 2f)
        // 底座
        drawCircle(Color.White.copy(alpha = 0.07f), radius = baseR, center = c)
        drawCircle(Color.White.copy(alpha = 0.30f), radius = baseR, center = c, style = Stroke(2.dp.toPx()))
        // 十字参考线
        drawLine(
            Color.White.copy(alpha = 0.12f),
            Offset(c.x - baseR * 0.72f, c.y),
            Offset(c.x + baseR * 0.72f, c.y),
            strokeWidth = 1.dp.toPx()
        )
        drawLine(
            Color.White.copy(alpha = 0.12f),
            Offset(c.x, c.y - baseR * 0.72f),
            Offset(c.x, c.y + baseR * 0.72f),
            strokeWidth = 1.dp.toPx()
        )
        // 摇杆头
        val head = Offset(
            c.x + state.stickX * maxR,
            c.y - state.stickY * maxR
        )
        drawCircle(Color.White.copy(alpha = 0.26f), radius = knobR, center = head)
        drawCircle(Color.White.copy(alpha = 0.60f), radius = knobR, center = head, style = Stroke(2.dp.toPx()))
    }
}

private fun updateStick(state: GamepadState, position: Offset, center: Offset, maxR: Float) {
    val delta = position - center
    val dist = delta.getDistance()
    val clamped = if (dist > maxR) delta / dist * maxR else delta
    state.setStick(clamped.x / maxR, -(clamped.y / maxR))
}

/** 调试面板：实时显示按键 ID 与摇杆坐标 */
@Composable
private fun DebugPanel(state: GamepadState) {
    val mono = FontFamily.Monospace
    val ids = state.pressedIds()
    Column(
        modifier = Modifier
            .background(Color.Black.copy(alpha = 0.55f), RoundedCornerShape(8.dp))
            .border(1.dp, DebugGreen.copy(alpha = 0.45f), RoundedCornerShape(8.dp))
            .padding(horizontal = 10.dp, vertical = 6.dp)
    ) {
        Text(
            "DEBUG  ·  MULTI-TOUCH",
            color = DebugGreen,
            fontSize = 10.sp,
            fontWeight = FontWeight.Bold,
            fontFamily = mono
        )
        Text(
            "KEYS[${ids.joinToString(",")}] ${state.pressedLabels()}",
            color = DebugText,
            fontSize = 10.sp,
            fontFamily = mono
        )
        Text(
            "STICK x=${"%+.2f".format(state.stickX)} y=${"%+.2f".format(state.stickY)}",
            color = DebugText,
            fontSize = 10.sp,
            fontFamily = mono
        )
        Text(
            "TRIG L=${"%.2f".format(state.lTrigger)} R=${"%.2f".format(state.rTrigger)}",
            color = DebugText,
            fontSize = 10.sp,
            fontFamily = mono
        )
    }
}
