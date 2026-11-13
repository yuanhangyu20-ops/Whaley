package com.example.wifipad.sensor

import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.setValue
import kotlin.math.abs

/**
 * 陀螺仪 / 加速度计读取 + 基础滤波 + 体感映射。
 *
 * 处理链：
 * 1. 一阶低通滤波（指数平滑）抑制高频抖动
 * 2. 死区（dead zone）抑制静止漂移
 * 3. 陀螺仪角速度映射为右摇杆：
 *    - 绕 Y 轴旋转（左右转手机）→ 右摇杆 X
 *    - 绕 X 轴旋转（前后倾手机）→ 右摇杆 Y
 */
class MotionController(context: Context) : SensorEventListener {

    private val sensorManager =
        context.getSystemService(Context.SENSOR_SERVICE) as SensorManager

    private val accelerometer = sensorManager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)
    private val gyroscope = sensorManager.getDefaultSensor(Sensor.TYPE_GYROSCOPE)

    /** 滤波后的加速度（m/s²） */
    var ax by mutableFloatStateOf(0f); private set
    var ay by mutableFloatStateOf(0f); private set
    var az by mutableFloatStateOf(0f); private set

    /** 滤波后的角速度（rad/s） */
    var gx by mutableFloatStateOf(0f); private set
    var gy by mutableFloatStateOf(0f); private set
    var gz by mutableFloatStateOf(0f); private set

    /** 体感映射出的右摇杆，范围 [-1, 1] */
    var rStickX by mutableFloatStateOf(0f); private set
    var rStickY by mutableFloatStateOf(0f); private set

    /** 低通滤波系数：越小越平滑、越迟钝（60Hz 下 0.18 手感较跟手） */
    private val alpha = 0.18f

    /** 死区：小于该值的输出归零，消除静止漂移 */
    private val deadZone = 0.045f

    /** 灵敏度：rad/s 到摇杆轴的放大倍数 */
    private val sensitivity = 2.6f

    val available: Boolean get() = gyroscope != null

    fun start() {
        accelerometer?.let {
            sensorManager.registerListener(this, it, SensorManager.SENSOR_DELAY_GAME)
        }
        gyroscope?.let {
            sensorManager.registerListener(this, it, SensorManager.SENSOR_DELAY_GAME)
        }
    }

    fun stop() {
        sensorManager.unregisterListener(this)
    }

    override fun onSensorChanged(event: SensorEvent) {
        when (event.sensor.type) {
            Sensor.TYPE_ACCELEROMETER -> {
                ax = lowPass(ax, event.values[0])
                ay = lowPass(ay, event.values[1])
                az = lowPass(az, event.values[2])
            }

            Sensor.TYPE_GYROSCOPE -> {
                gx = lowPass(gx, event.values[0])
                gy = lowPass(gy, event.values[1])
                gz = lowPass(gz, event.values[2])

                // 左右转（绕 Y）→ 右摇杆 X；前后倾（绕 X）→ 右摇杆 Y
                rStickX = deadZone(-gy * sensitivity)
                rStickY = deadZone(gx * sensitivity)
            }
        }
    }

    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {
        // 无需处理
    }

    private fun lowPass(previous: Float, raw: Float): Float =
        previous + alpha * (raw - previous)

    private fun deadZone(value: Float): Float {
        val magnitude = abs(value)
        if (magnitude <= deadZone) return 0f
        val scaled = (magnitude - deadZone) / (1f - deadZone)
        return scaled.coerceAtMost(1f) * if (value < 0f) -1f else 1f
    }
}
