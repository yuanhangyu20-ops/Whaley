package com.example.wifipad.ui

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.setValue
import com.example.wifipad.net.Protocol
import java.util.concurrent.atomic.AtomicInteger

/**
 * 按键 ID 常量（与 UDP 协议位一一对应）。
 */
object Btn {
    const val A = 1
    const val B = 2
    const val X = 3
    const val Y = 4
    const val DPAD_UP = 5
    const val DPAD_DOWN = 6
    const val DPAD_LEFT = 7
    const val DPAD_RIGHT = 8
    const val LT = 9
    const val RT = 10
    const val LB = 11
    const val RB = 12
    const val L3 = 13
    const val R3 = 14

    val names: Map<Int, String> = mapOf(
        A to "A", B to "B", X to "X", Y to "Y",
        DPAD_UP to "UP", DPAD_DOWN to "DOWN",
        DPAD_LEFT to "LEFT", DPAD_RIGHT to "RIGHT",
        LT to "LT", RT to "RT", LB to "LB", RB to "RB",
        L3 to "L3", R3 to "R3"
    )

    fun protocolBit(id: Int): Int = when (id) {
        A -> Protocol.B_A
        B -> Protocol.B_B
        X -> Protocol.B_X
        Y -> Protocol.B_Y
        DPAD_UP -> Protocol.B_UP
        DPAD_DOWN -> Protocol.B_DOWN
        DPAD_LEFT -> Protocol.B_LEFT
        DPAD_RIGHT -> Protocol.B_RIGHT
        LT -> Protocol.B_LT
        RT -> Protocol.B_RT
        LB -> Protocol.B_LB
        RB -> Protocol.B_RB
        L3 -> Protocol.B_L3
        R3 -> Protocol.B_R3
        else -> 0
    }
}

/**
 * 虚拟手柄运行时状态。
 *
 * Compose 状态用于 UI 渲染；
 * 另维护线程安全快照（AtomicInteger 位掩码 + @Volatile 数值）供 60Hz UDP 线程读取。
 */
class GamepadState {

    // ── 左摇杆 ──
    var stickX by mutableFloatStateOf(0f)
        private set
    var stickY by mutableFloatStateOf(0f)
        private set

    // ── 右摇杆（实体）──
    var rStickX by mutableFloatStateOf(0f)
        private set
    var rStickY by mutableFloatStateOf(0f)
        private set

    var lTrigger by mutableFloatStateOf(0f)
        private set
    var rTrigger by mutableFloatStateOf(0f)
        private set

    private val pressed = mutableStateListOf<Int>()

    // ── 网络线程安全快照 ──
    private val buttonMask = AtomicInteger(0)

    @Volatile
    var netStickX = 0f
        private set

    @Volatile
    var netStickY = 0f
        private set

    @Volatile
    var netRStickX = 0f
        private set

    @Volatile
    var netRStickY = 0f
        private set

    @Volatile
    var netLTrigger = 0f
        private set

    @Volatile
    var netRTrigger = 0f
        private set

    fun setStick(x: Float, y: Float) {
        stickX = x
        stickY = y
        netStickX = x
        netStickY = y
    }

    fun setRightStick(x: Float, y: Float) {
        rStickX = x
        rStickY = y
        netRStickX = x
        netRStickY = y
    }

    fun updateLTrigger(value: Float) {
        lTrigger = value
        netLTrigger = value
    }

    fun updateRTrigger(value: Float) {
        rTrigger = value
        netRTrigger = value
    }

    fun press(id: Int) {
        if (!pressed.contains(id)) pressed.add(id)
        val bit = Btn.protocolBit(id)
        buttonMask.updateAndGet { current -> current or bit }
    }

    fun release(id: Int) {
        pressed.remove(id)
        val bit = Btn.protocolBit(id)
        buttonMask.updateAndGet { current -> current and bit.inv() }
    }

    fun isDown(id: Int): Boolean = pressed.contains(id)

    fun pressedIds(): List<Int> = pressed.toList()

    fun pressedLabels(): String =
        pressed.map { Btn.names[it] ?: it.toString() }.joinToString(", ")

    /** 当前按键位掩码（供网络层读取） */
    fun currentButtonMask(): Int = buttonMask.get()
}
