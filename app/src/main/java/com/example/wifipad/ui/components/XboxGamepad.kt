package com.example.wifipad.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.width
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.example.wifipad.haptic.HapticController
import com.example.wifipad.ui.Btn
import com.example.wifipad.ui.GamepadState

private val XboxGreen = Color(0xFF4CAF50)
private val XboxRed = Color(0xFFF44336)
private val XboxBlue = Color(0xFF2196F3)
private val XboxYellow = Color(0xFFFFC107)

/**
 * Xbox 手柄 1:1 布局：
 *
 * ```
 * [LT] [LB]                [RB] [RT]
 *
 *  L-Stick                    ABXY
 *
 *  D-Pad                      R-Stick
 * ```
 */
@Composable
fun XboxGamepad(
    state: GamepadState,
    haptic: HapticController,
    isDark: Boolean,
    modifier: Modifier = Modifier
) {
    Box(modifier = modifier.fillMaxSize()) {

        // ── 顶部：扳机与肩键 ──
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 22.dp, vertical = 8.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                TriggerKey(
                    label = "LT",
                    pressed = state.isDown(Btn.LT),
                    haptic = haptic,
                    isDark = isDark,
                    onPress = { down -> toggle(state, Btn.LT, down) }
                )
                Spacer(Modifier.width(10.dp))
                ShoulderKey(
                    label = "LB",
                    pressed = state.isDown(Btn.LB),
                    haptic = haptic,
                    isDark = isDark,
                    onPress = { down -> toggle(state, Btn.LB, down) }
                )
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                ShoulderKey(
                    label = "RB",
                    pressed = state.isDown(Btn.RB),
                    haptic = haptic,
                    isDark = isDark,
                    onPress = { down -> toggle(state, Btn.RB, down) }
                )
                Spacer(Modifier.width(10.dp))
                TriggerKey(
                    label = "RT",
                    pressed = state.isDown(Btn.RT),
                    haptic = haptic,
                    isDark = isDark,
                    onPress = { down -> toggle(state, Btn.RT, down) }
                )
            }
        }

        // ── 左侧：L-Stick 上 / D-Pad 下 ──
        Column(
            modifier = Modifier
                .align(Alignment.CenterStart)
                .padding(start = 24.dp, top = 66.dp, bottom = 10.dp),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Joystick(
                value = Offset(state.stickX, state.stickY),
                onChange = { v -> state.setStick(v.x, v.y) },
                onL3 = {
                    haptic.press()
                    pulseButton(state, Btn.L3)
                },
                haptic = haptic,
                isDark = isDark,
                label = "L-Stick",
                diameter = 132.dp
            )
            Spacer(Modifier.height(16.dp))
            DPad(
                pressedDir = listOf(Btn.DPAD_UP, Btn.DPAD_DOWN, Btn.DPAD_LEFT, Btn.DPAD_RIGHT)
                    .firstOrNull { state.isDown(it) },
                onDirDown = { dir -> state.press(dir) },
                onDirUp = {
                    state.release(Btn.DPAD_UP)
                    state.release(Btn.DPAD_DOWN)
                    state.release(Btn.DPAD_LEFT)
                    state.release(Btn.DPAD_RIGHT)
                },
                haptic = haptic,
                isDark = isDark,
                diameter = 122.dp
            )
        }

        // ── 右侧：ABXY 上 / R-Stick 下 ──
        Column(
            modifier = Modifier
                .align(Alignment.CenterEnd)
                .padding(end = 24.dp, top = 62.dp, bottom = 10.dp),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            ActionPad(state = state, haptic = haptic, size = 138.dp)
            Spacer(Modifier.height(14.dp))
            Joystick(
                value = Offset(state.rStickX, state.rStickY),
                onChange = { v -> state.setRightStick(v.x, v.y) },
                onL3 = {
                    haptic.press()
                    pulseButton(state, Btn.R3)
                },
                haptic = haptic,
                isDark = isDark,
                label = "R-Stick",
                diameter = 124.dp
            )
        }
    }
}

/** ABXY 菱形布局 */
@Composable
private fun ActionPad(
    state: GamepadState,
    haptic: HapticController,
    size: androidx.compose.ui.unit.Dp
) {
    val key = 56.dp
    Box(Modifier.size(size)) {
        Box(Modifier.align(Alignment.TopCenter)) {
            XboxKey("Y", XboxYellow, state.isDown(Btn.Y), haptic, { d -> toggle(state, Btn.Y, d) }, key)
        }
        Box(Modifier.align(Alignment.CenterStart)) {
            XboxKey("X", XboxBlue, state.isDown(Btn.X), haptic, { d -> toggle(state, Btn.X, d) }, key)
        }
        Box(Modifier.align(Alignment.CenterEnd)) {
            XboxKey("B", XboxRed, state.isDown(Btn.B), haptic, { d -> toggle(state, Btn.B, d) }, key)
        }
        Box(Modifier.align(Alignment.BottomCenter)) {
            XboxKey("A", XboxGreen, state.isDown(Btn.A), haptic, { d -> toggle(state, Btn.A, d) }, key)
        }
    }
}

private fun toggle(state: GamepadState, id: Int, down: Boolean) {
    if (down) state.press(id) else state.release(id)
}

/** 摇杆下压：短脉冲（约 90ms）后自动释放，模拟实体 L3/R3 点按 */
private fun pulseButton(state: GamepadState, id: Int) {
    state.press(id)
    android.os.Handler(android.os.Looper.getMainLooper()).postDelayed({
        state.release(id)
    }, 90L)
}
