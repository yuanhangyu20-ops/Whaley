package com.example.wifipad.ui

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.setValue

/**
 * 按键 ID 常量。
 * 这些 ID 后续会直接用于 UDP 协议，与 PC 端保持一一对应。
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

    val names: Map<Int, String> = mapOf(
        A to "A", B to "B", X to "X", Y to "Y",
        DPAD_UP to "UP", DPAD_DOWN to "DOWN",
        DPAD_LEFT to "LEFT", DPAD_RIGHT to "RIGHT",
        LT to "LT", RT to "RT"
    )
}

/**
 * 虚拟手柄运行时状态。
 * 全部字段都是 Compose Snapshot 状态，读写会自动触发重组。
 */
class GamepadState {
    /** 左摇杆 X 轴，范围 [-1, 1]（右为正） */
    var stickX by mutableFloatStateOf(0f)
        private set

    /** 左摇杆 Y 轴，范围 [-1, 1]（上为正） */
    var stickY by mutableFloatStateOf(0f)
        private set

    /** 左扳机，范围 [0, 1] */
    var lTrigger by mutableFloatStateOf(0f)

    /** 右扳机，范围 [0, 1] */
    var rTrigger by mutableFloatStateOf(0f)

    private val pressed = mutableStateListOf<Int>()

    fun setStick(x: Float, y: Float) {
        stickX = x
        stickY = y
    }

    fun press(id: Int) {
        if (!pressed.contains(id)) pressed.add(id)
    }

    fun release(id: Int) {
        pressed.remove(id)
    }

    fun isDown(id: Int): Boolean = pressed.contains(id)

    fun pressedIds(): List<Int> = pressed.toList()

    fun pressedLabels(): String =
        pressed.map { Btn.names[it] ?: it.toString() }.joinToString(",")
}
