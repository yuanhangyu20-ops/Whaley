package com.example.wifipad.net

import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * WifiPad 二进制协议（v2）
 *
 * 定长 36 字节，小端序；按钮字段扩展到 LB/RB/L3/R3：
 * ```
 * offset size field
 * 0      2    magic     "WP"
 * 2      1    version   2
 * 3      1    flags     保留
 * 4      4    seq       包序号（u32，自增）
 * 8      8    timestamp 手机 uptime（ms，u64）
 * 16     2    buttons   按键位掩码（u16）：
 *                        A=bit0  B=bit1  X=bit2  Y=bit3
 *                        UP=bit4 DOWN=bit5 LEFT=bit6 RIGHT=bit7
 *                        LT=bit8 RT=bit9 LB=bit10 RB=bit11 L3=bit12 R3=bit13
 * 18     1    lt        左扳机 0..255
 * 19     1    rt        右扳机 0..255
 * 20     1    lx        左摇杆 X  -127..127
 * 21     1    ly        左摇杆 Y  -127..127
 * 22     1    rx        右摇杆 X  -127..127
 * 23     1    ry        右摇杆 Y  -127..127
 * 24     2    gx        陀螺仪 X  0.01 rad/s
 * 26     2    gy
 * 28     2    gz
 * 30     2    ax        加速度 X  0.01 m/s^2
 * 32     2    ay
 * 34     2    az
 * ```
 */
object Protocol {
    const val DEFAULT_PORT = 12345
    const val PACKET_SIZE = 36
    const val VERSION = 2

    // 按键位掩码
    const val B_A = 1 shl 0
    const val B_B = 1 shl 1
    const val B_X = 1 shl 2
    const val B_Y = 1 shl 3
    const val B_UP = 1 shl 4
    const val B_DOWN = 1 shl 5
    const val B_LEFT = 1 shl 6
    const val B_RIGHT = 1 shl 7
    const val B_LT = 1 shl 8
    const val B_RT = 1 shl 9
    const val B_LB = 1 shl 10
    const val B_RB = 1 shl 11
    const val B_L3 = 1 shl 12
    const val B_R3 = 1 shl 13
}

/** 一帧完整的输入状态 */
data class GamepadPacket(
    val seq: Int,
    val timestampMs: Long,
    val buttons: Int,
    val lTrigger: Float,
    val rTrigger: Float,
    val lx: Float,
    val ly: Float,
    val rx: Float,
    val ry: Float,
    val gx: Float,
    val gy: Float,
    val gz: Float,
    val ax: Float,
    val ay: Float,
    val az: Float
) {
    fun encode(): ByteArray {
        val buf = ByteBuffer.allocate(Protocol.PACKET_SIZE).order(ByteOrder.LITTLE_ENDIAN)
        buf.put('W'.code.toByte())
        buf.put('P'.code.toByte())
        buf.put(Protocol.VERSION.toByte())
        buf.put(0)
        buf.putInt(seq)
        buf.putLong(timestampMs)
        buf.putShort(buttons.toShort())
        buf.put(q01(lTrigger))
        buf.put(q01(rTrigger))
        buf.put(qAxis(lx))
        buf.put(qAxis(ly))
        buf.put(qAxis(rx))
        buf.put(qAxis(ry))
        buf.putShort(qSensor(gx))
        buf.putShort(qSensor(gy))
        buf.putShort(qSensor(gz))
        buf.putShort(qSensor(ax))
        buf.putShort(qSensor(ay))
        buf.putShort(qSensor(az))
        return buf.array()
    }

    private fun q01(v: Float): Byte =
        (v.coerceIn(0f, 1f) * 255f).toInt().toByte()

    private fun qAxis(v: Float): Byte =
        (v.coerceIn(-1f, 1f) * 127f).toInt().toByte()

    private fun qSensor(v: Float): Short =
        (v * 100f).toInt().coerceIn(-32768, 32767).toShort()
}
