package com.example.wifipad.ui

import android.app.Activity
import android.os.SystemClock
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Button
import androidx.compose.material3.DrawerValue
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalDrawerSheet
import androidx.compose.material3.ModalNavigationDrawer
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.rememberDrawerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import com.example.wifipad.haptic.HapticController
import com.example.wifipad.net.GamepadPacket
import com.example.wifipad.net.Protocol
import com.example.wifipad.net.UdpSender
import com.example.wifipad.sensor.MotionController
import com.example.wifipad.ui.components.XboxGamepad
import com.example.wifipad.ui.theme.WifiPadTheme
import kotlinx.coroutines.awaitCancellation
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.util.concurrent.atomic.AtomicInteger

@Composable
fun WifiPadApp() {
    val context = LocalContext.current
    val state = remember { GamepadState() }
    val motion = remember { MotionController(context) }
    val haptic = remember { HapticController(context) }
    val sender = remember { UdpSender() }
    val sentCounter = remember { AtomicInteger(0) }
    val seqCounter = remember { AtomicInteger(0) }
    val scope = rememberCoroutineScope()

    // ── 主题 ──
    var isDark by rememberSaveable { mutableStateOf(true) }

    // ── 抽屉 ──
    val drawerState = rememberDrawerState(DrawerValue.Closed)

    // ── 网络 ──
    // ── 网络参数持久化（SharedPreferences，重启 App 不丢失）──
    val prefs = remember {
        context.getSharedPreferences("wifipad", android.content.Context.MODE_PRIVATE)
    }
    var ipText by rememberSaveable {
        mutableStateOf(prefs.getString("ip", "192.168.1.100") ?: "192.168.1.100")
    }
    var portText by rememberSaveable {
        mutableStateOf(prefs.getString("port", Protocol.DEFAULT_PORT.toString())
            ?: Protocol.DEFAULT_PORT.toString())
    }
    // 自动保存
    LaunchedEffect(ipText, portText) {
        prefs.edit().putString("ip", ipText).putString("port", portText).apply()
    }
    var sending by remember { mutableStateOf(false) }
    var statusText by remember { mutableStateOf("待连接") }
    var pps by remember { mutableIntStateOf(0) }

    WifiPadTheme(darkTheme = isDark) {
        HideSystemBars()

        // ── 返回键处理：抽屉打开时关闭抽屉；否则最小化而非退出 ──
        androidx.activity.compose.BackHandler(enabled = true) {
            if (drawerState.isOpen) {
                scope.launch { drawerState.close() }
            } else {
                (context as? Activity)?.moveTaskToBack(true)
            }
        }

        DisposableEffect(Unit) {
            motion.start()
            onDispose { motion.stop() }
        }

        // 60Hz UDP 发送（后台协程，不阻塞 UI）
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

            sender.start(this, host, port) {
                GamepadPacket(
                    seq = seqCounter.getAndIncrement(),
                    timestampMs = SystemClock.uptimeMillis(),
                    buttons = state.currentButtonMask(),
                    lTrigger = state.netLTrigger,
                    rTrigger = state.netRTrigger,
                    lx = state.netStickX,
                    ly = state.netStickY,
                    // 右摇杆：只由屏幕触摸拖拽控制。
                    // 体感数据绝不叠加进来 —— 否则手一动摇杆就跟着动。
                    // 体感只通过 gx/gy/gz + ax/ay/az 字段发送，由 PC 端走 DSU。
                    rx = state.netRStickX,
                    ry = state.netRStickY,
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
                delay(1000)
                pps = sentCounter.get() - before
            }
        }

        // 右侧抽屉：通过 RTL 让 ModalNavigationDrawer 从右边滑出
        CompositionLocalProvider(LocalLayoutDirection provides LayoutDirection.Rtl) {
            ModalNavigationDrawer(
                drawerState = drawerState,
                gesturesEnabled = true,
                drawerContent = {
                    CompositionLocalProvider(LocalLayoutDirection provides LayoutDirection.Ltr) {
                        SettingsDrawer(
                            isDark = isDark,
                            onDarkChange = { isDark = it },
                            ip = ipText,
                            onIpChange = { ipText = it },
                            port = portText,
                            onPortChange = { portText = it },
                            sending = sending,
                            status = statusText,
                            pps = pps,
                            onToggle = { sending = !sending },
                            state = state,
                            motion = motion,
                            onClose = { scope.launch { drawerState.close() } }
                        )
                    }
                }
            ) {
                CompositionLocalProvider(LocalLayoutDirection provides LayoutDirection.Ltr) {
                    Box(
                        modifier = Modifier
                            .fillMaxSize()
                            .background(MaterialTheme.colorScheme.background)
                    ) {
                        XboxGamepad(
                            state = state,
                            haptic = haptic,
                            isDark = isDark
                        )

                        // 唤出抽屉的小齿轮
                        IconButton(
                            onClick = { scope.launch { drawerState.open() } },
                            modifier = Modifier
                                .align(Alignment.TopCenter)
                                .padding(top = 2.dp)
                        ) {
                            Icon(
                                imageVector = Icons.Default.Settings,
                                contentDescription = "设置",
                                tint = MaterialTheme.colorScheme.onBackground.copy(alpha = 0.55f),
                                modifier = Modifier.size(22.dp)
                            )
                        }
                    }
                }
            }
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

@Composable
private fun SettingsDrawer(
    isDark: Boolean,
    onDarkChange: (Boolean) -> Unit,
    ip: String,
    onIpChange: (String) -> Unit,
    port: String,
    onPortChange: (String) -> Unit,
    sending: Boolean,
    status: String,
    pps: Int,
    onToggle: () -> Unit,
    state: GamepadState,
    motion: MotionController,
    onClose: () -> Unit
) {
    ModalDrawerSheet(modifier = Modifier.width(320.dp)) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 16.dp, vertical = 12.dp)
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    text = "设置",
                    style = MaterialTheme.typography.titleLarge,
                    fontWeight = FontWeight.Bold
                )
                Spacer(Modifier.weight(1f))
                IconButton(onClick = onClose) {
                    Icon(Icons.Default.Close, contentDescription = "关闭")
                }
            }

            HorizontalDivider(Modifier.padding(vertical = 8.dp))

            // ── 主题切换 ──
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier.fillMaxWidth()
            ) {
                Column(Modifier.weight(1f)) {
                    Text("深色主题", style = MaterialTheme.typography.bodyLarge)
                    Text(
                        "黑白双主题",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
                Switch(checked = isDark, onCheckedChange = onDarkChange)
            }

            HorizontalDivider(Modifier.padding(vertical = 8.dp))

            // ── 网络 ──
            Text(
                "网络",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold
            )
            Spacer(Modifier.height(8.dp))
            OutlinedTextField(
                value = ip,
                onValueChange = onIpChange,
                label = { Text("电脑 IP") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth()
            )
            Spacer(Modifier.height(8.dp))
            OutlinedTextField(
                value = port,
                onValueChange = onPortChange,
                label = { Text("端口") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth()
            )
            Spacer(Modifier.height(10.dp))
            Button(
                onClick = onToggle,
                modifier = Modifier.fillMaxWidth()
            ) {
                Text(if (sending) "停止发送" else "开始连接")
            }
            Spacer(Modifier.height(6.dp))
            Text(
                "状态：$status",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )

            HorizontalDivider(Modifier.padding(vertical = 10.dp))

            // ── 调试数据 ──
            Text(
                "调试数据",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold
            )
            Spacer(Modifier.height(6.dp))
            DebugLine("KEYS", state.pressedLabels().ifEmpty { "-" })
            DebugLine("L-STICK", "x=%+.2f  y=%+.2f".format(state.stickX, state.stickY))
            DebugLine("R-STICK", "x=%+.2f  y=%+.2f".format(state.rStickX, state.rStickY))
            DebugLine("GYRO", "x=%+.2f  y=%+.2f  z=%+.2f".format(motion.gx, motion.gy, motion.gz))
            DebugLine("ACC", "x=%+.2f  y=%+.2f  z=%+.2f".format(motion.ax, motion.ay, motion.az))
            DebugLine("TX", "$pps Hz")

            Spacer(Modifier.height(16.dp))
        }
    }
}

@Composable
private fun DebugLine(label: String, value: String) {
    Row(modifier = Modifier.fillMaxWidth()) {
        Text(
            text = label,
            fontFamily = FontFamily.Monospace,
            fontSize = 11.sp,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.width(64.dp)
        )
        Text(
            text = value,
            fontFamily = FontFamily.Monospace,
            fontSize = 11.sp,
            color = MaterialTheme.colorScheme.onSurface
        )
    }
}
