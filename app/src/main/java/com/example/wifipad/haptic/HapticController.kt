package com.example.wifipad.haptic

import android.content.Context
import android.os.Build
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager

/**
 * 触觉反馈封装。
 *
 * - [tick] 普通按键：短促清脆的轻震
 * - [press] 摇杆下压（L3/R3）：稍重、略长，模拟实体按压手感
 *
 * API 31+ 使用 VibratorManager，低版本回退到 Vibrator。
 */
class HapticController(context: Context) {

    private val vibrator: Vibrator? = run {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            val manager =
                context.getSystemService(Context.VIBRATOR_MANAGER_SERVICE) as? VibratorManager
            manager?.defaultVibrator
        } else {
            @Suppress("DEPRECATION")
            context.getSystemService(Context.VIBRATOR_SERVICE) as? Vibrator
        }
    }

    private val enabled: Boolean
        get() = vibrator?.hasVibrator() == true

    /** 普通按键：12ms 轻震 */
    fun tick() {
        vibrate(durationMs = 12L, amplitude = 70)
    }

    /** 摇杆下压：26ms，力度更大一些 */
    fun press() {
        vibrate(durationMs = 26L, amplitude = 140)
    }

    private fun vibrate(durationMs: Long, amplitude: Int) {
        val v = vibrator ?: return
        if (!enabled) return
        try {
            v.vibrate(VibrationEffect.createOneShot(durationMs, amplitude.coerceIn(1, 255)))
        } catch (_: Exception) {
            // 某些设备权限/安全策略受限时静默失败
        }
    }
}
