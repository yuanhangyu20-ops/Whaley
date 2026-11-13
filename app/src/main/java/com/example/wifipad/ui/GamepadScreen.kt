package com.example.wifipad.ui

import android.app.Activity
import android.os.SystemClock
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.pointer.PointerId
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import com.example.wifipad.net.GamepadPacket
import com.example.wifipad.net.Protocol
import com.example.wifipad.net.UdpSender
import com.example.wifipad.sensor.MotionController
import kotlinx.coroutines.awaitCancellation
import java.util.concurrent.atomic.AtomicInteger

private val GlassFill = Color.White.copy(alpha = 0.12f)
private val GlassFillActive = Color.White.copy(alpha = 0.42f)
private val GlassBorder = Color.White.copy(alpha = 0.38f)
private val GlassBorderActive = Color.White.copy(alpha = 0.92f)
private val DebugGreen = Color(0xFF00E676)
private val DebugText = Color(0xFFB2FF59)
private val Mono = FontFamily.Monospace

@Composable
fun GamepadScreen() {
    val state = remember { GamepadState() }
    val context = LocalContext.current
    val motion = remember { MotionController(context) }
    val sender = remember { UdpSender() }
    val sentCounter = remember { AtomicInteger(0) }

    HideSystemBars()

    // 传感器生命周期跟随界面
    DisposableEffect(Unit) {
        motion.start()
        onDispose { motion.stop() }
    }

    var ipText by rememberSaveable { mutableStateOf("192.168.1.100") }
    var portText by rememberSaveable { mutableStateOf(Protocol.DEFAULT_PORT.toString()) }
    var sending by remember { mutableStateOf(false) }
    var statusText by remember { mutableStateOf("待连接") }
    var pps by remember { mutableIntStateOf(0) }
    // seq 用 AtomicInteger：在 IO 线程递增，不触发 Compose 重组
    val seqCounter = remember { AtomicInteger(0) }

    // 60Hz UDP 发送（IP / 端口 / 开关变化时重启）
    LaunchedEffect(sending, ipText, portText) {
        if (!sending) return@LaunchedEffect
        val host = ipText.trim()
        val port = portText.trim().toIntOrNull() ?: Protocol.DEFAULT_PORT
        statusText = "发送中 60Hz → $host:$port"

        sender.onError = { msg ->
            statusText = "错误: $msg"
            sending = false
        }
        sender.onSent = { sentCounter.incrementAndGet() }

        sender.start(
            scope = this,
            host = host,
            port = port
        ) {
            GamepadPacket(
                seq = seqCounter.getAndIncrement(),
                timestampMs = SystemClock.uptimeMillis(),
                buttons = state.currentButtonMask(),
                lTrigger = state.netLTrigger,
                rTrigger = state.netRTrigger,
                lx = state.netStickX,
                ly = state.netStickY,
                rx = motion.rStickX,
                ry = motion.rStickY,
                gx = motion.gx,
                gy = motion.gy,
                gz = motion.gz,
                ax = motion.ax,
                ay = motion.ay,
                az = motion.az
            )
        }

        try {
            awaitCancellation()
        } finally {
            sender.stop()
        }
    }

    // 每秒统计发送频率
    LaunchedEffect(sending) {
        if (!sending) {
            pps = 0
            return@LaunchedEffect
        }
        while (true) {
            val before = sentCounter.get()
            kotlinx.coroutines.delay(1000)
            pps = sentCounter.get() - before
        }
    }

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
                state.updateLTrigger(if (down) 1f else 0f)
            }
            TriggerKey(label = "RT", active = state.rTrigger > 0.5f) { down ->
                state.updateRTrigger(if (down) 1f else 0f)
            }
        }

        // ── 左下：摇杆 ──
        Box(
            modifier = Modifier
                .align(Alignment.BottomStart)
                .padding(start = 34.dp, bottom = 16.dp)
        ) {
            Joystick(state = state, diameter = 146.dp)
        }

        // ── 左上偏中：十字键 ──
        Box(
            modifier = Modifier
                .align(Alignment.TopStart)
                .padding(start = 92.dp, top = 76.dp)
        ) {
            DPad(state = state)
        }

        // ── 右侧：ABXY ──
        Box(
            modifier = Modifier
                .align(Alignment.CenterEnd)
                .padding(end = 40.dp, top = 16.dp)
        ) {
            ActionKeys(state = state)
        }

        // ── 顶部中央：调试面板 + 网络面板 ──
        Column(
            modifier = Modifier
                .align(Alignment.TopCenter)
                .padding(top = 4.dp),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            DebugPanel(state = state, motion = motion, pps = pps)
            Box(Modifier.height(4.dp))
            NetPanel(
                ip = ipText,
                onIpChange = { ipText = it },
                port = portText,
                onPortChange = { portText = it },
                sending = sending,
                status = statusText,
                onToggle = { sending = !sending }
            )
        }
    }
}

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

@Composable
private fun DPad(state: GamepadState) {
    val key = 44.dp
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
        drawCircle(Color.White.copy(alpha = 0.07f), radius = baseR, center = c)
        drawCircle(Color.White.copy(alpha = 0.30f), radius = baseR, center = c, style = Stroke(2.dp.toPx()))
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

@Composable
private fun DebugPanel(state: GamepadState, motion: MotionController, pps: Int) {
    Column(
        modifier = Modifier
            .background(Color.Black.copy(alpha = 0.55f), RoundedCornerShape(8.dp))
            .border(1.dp, DebugGreen.copy(alpha = 0.45f), RoundedCornerShape(8.dp))
            .padding(horizontal = 10.dp, vertical = 5.dp)
    ) {
        Text(
            "DEBUG · MULTI-TOUCH · TX ${pps}Hz",
            color = DebugGreen,
            fontSize = 10.sp,
            fontWeight = FontWeight.Bold,
            fontFamily = Mono
        )
        Text(
            "KEYS[${state.pressedIds().joinToString(",")}] ${state.pressedLabels()}",
            color = DebugText, fontSize = 10.sp, fontFamily = Mono
        )
        Text(
            "L-STICK x=${"%+.2f".format(state.stickX)} y=${"%+.2f".format(state.stickY)}",
            color = DebugText, fontSize = 10.sp, fontFamily = Mono
        )
        Text(
            "R-STICK x=${"%+.2f".format(motion.rStickX)} y=${"%+.2f".format(motion.rStickY)}",
            color = DebugText, fontSize = 10.sp, fontFamily = Mono
        )
        Text(
            "GYRO x=${"%+.2f".format(motion.gx)} y=${"%+.2f".format(motion.gy)} z=${"%+.2f".format(motion.gz)}",
            color = DebugText, fontSize = 10.sp, fontFamily = Mono
        )
    }
}

@Composable
private fun NetPanel(
    ip: String,
    onIpChange: (String) -> Unit,
    port: String,
    onPortChange: (String) -> Unit,
    sending: Boolean,
    status: String,
    onToggle: () -> Unit
) {
    Column(
        modifier = Modifier
            .background(Color.Black.copy(alpha = 0.55f), RoundedCornerShape(8.dp))
            .border(1.dp, Color(0xFF40C4FF).copy(alpha = 0.45f), RoundedCornerShape(8.dp))
            .padding(horizontal = 8.dp, vertical = 5.dp),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            SmallField(value = ip, onValueChange = onIpChange, width = 132.dp, keyboardType = KeyboardType.Uri)
            Box(Modifier.width(4.dp))
            SmallField(value = port, onValueChange = onPortChange, width = 62.dp, keyboardType = KeyboardType.Number)
            Box(Modifier.width(6.dp))
            Box(
                modifier = Modifier
                    .size(width = 62.dp, height = 26.dp)
                    .clip(RoundedCornerShape(6.dp))
                    .background(if (sending) Color(0xFFFF5252).copy(alpha = 0.35f) else Color(0xFF40C4FF).copy(alpha = 0.28f))
                    .border(1.dp, if (sending) Color(0xFFFF5252) else Color(0xFF40C4FF), RoundedCornerShape(6.dp))
                    .pressGesture { down -> if (down) onToggle() },
                contentAlignment = Alignment.Center
            ) {
                Text(
                    if (sending) "停止" else "连接",
                    color = Color.White, fontSize = 11.sp, fontWeight = FontWeight.Bold
                )
            }
        }
        Box(Modifier.height(2.dp))
        Text(
            "NET: $status",
            color = Color(0xFF80D8FF), fontSize = 9.sp, fontFamily = Mono
        )
    }
}

@Composable
private fun SmallField(
    value: String,
    onValueChange: (String) -> Unit,
    width: Dp,
    keyboardType: KeyboardType
) {
    Box(
        modifier = Modifier
            .width(width)
            .height(26.dp)
            .clip(RoundedCornerShape(6.dp))
            .background(Color.Black.copy(alpha = 0.55f))
            .border(1.dp, Color.White.copy(alpha = 0.28f), RoundedCornerShape(6.dp))
            .padding(horizontal = 7.dp),
        contentAlignment = Alignment.CenterStart
    ) {
        BasicTextField(
            value = value,
            onValueChange = onValueChange,
            singleLine = true,
            textStyle = TextStyle(color = Color.White, fontSize = 11.sp, fontFamily = Mono),
            keyboardOptions = KeyboardOptions(keyboardType = keyboardType),
            cursorBrush = SolidColor(Color.White),
            modifier = Modifier.fillMaxWidth()
        )
    }
}
