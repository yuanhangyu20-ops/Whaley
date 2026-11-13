package com.example.wifipad.sensor

import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.os.Build
import android.view.Surface
import android.view.WindowManager
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.setValue
import kotlin.math.abs

/**
 * 陀螺仪 / 加速度计读取。
 *
 * 关键设计：**同时暴露原始值与滤波值**
 * ─────────────────────────────────
 * - 原始值（raw*）用于 DSU 体感上传：Yuzu 内部有自己的融合滤波
 *   （互补/卡尔曼），再喂给它平滑过的数据会造成双重滤波 ——
 *   表现为"倾斜幅度变浅、反应延迟、动一下就停"。
 * - 滤波值（ax/ay/az/gx/gy/gz）只用于界面调试显示。
 *
 * 采样率用 SENSOR_DELAY_FASTEST，让传感器以硬件最高频率回调，
 * 避免低于 60Hz 的 DSU 推送节奏导致数据重复。
 */
class MotionController(private val context: Context) : SensorEventListener {

    private val sensorManager =
        context.getSystemService(Context.SENSOR_SERVICE) as SensorManager

    private val accelerometer = sensorManager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)
    private val gyroscope = sensorManager.getDefaultSensor(Sensor.TYPE_GYROSCOPE)

    /**
     * 姿态传感器。用 GAME_ROTATION_VECTOR（不含磁力计）：
     * 磁力计会被周围电器干扰导致航向乱跳，而姿态锚定只需要短时间稳定的参考。
     */
    private val rotationSensor =
        sensorManager.getDefaultSensor(Sensor.TYPE_GAME_ROTATION_VECTOR)

    /**
     * 相对姿态四元数：相对于「开始采集那一刻」的旋转。
     *
     * 为什么用相对值而不是绝对值：
     * 手机姿态的绝对朝向取决于设备摆放，每次连接都不一样；而 DSU 客户端
     * 是从连接瞬间开始积分角速度的。用相对四元数可以让两边的零点天然对齐，
     * 姿态锚定才能算出有意义的误差。
     */
    var qx by mutableFloatStateOf(0f); private set
    var qy by mutableFloatStateOf(0f); private set
    var qz by mutableFloatStateOf(0f); private set
    var qw by mutableFloatStateOf(1f); private set

    /** 基准姿态（开始采集时的方向） */
    private var q0: FloatArray? = null

    /** 四元数是否可用（设备是否有旋转矢量传感器） */
    val hasOrientation: Boolean get() = rotationSensor != null

    // ── 原始值（m/s² 与 rad/s），供 DSU 使用 ──
    var rawAx by mutableFloatStateOf(0f); private set
    var rawAy by mutableFloatStateOf(0f); private set
    var rawAz by mutableFloatStateOf(0f); private set
    var rawGx by mutableFloatStateOf(0f); private set
    var rawGy by mutableFloatStateOf(0f); private set
    var rawGz by mutableFloatStateOf(0f); private set

    /** 滤波后的加速度（m/s²），仅用于界面显示 */
    var ax by mutableFloatStateOf(0f); private set
    var ay by mutableFloatStateOf(0f); private set
    var az by mutableFloatStateOf(0f); private set

    /** 滤波后的角速度（rad/s），仅用于界面显示 */
    var gx by mutableFloatStateOf(0f); private set
    var gy by mutableFloatStateOf(0f); private set
    var gz by mutableFloatStateOf(0f); private set

    /** 体感映射出的右摇杆，范围 [-1, 1]（当前不叠加到 R-Stick） */
    var rStickX by mutableFloatStateOf(0f); private set
    var rStickY by mutableFloatStateOf(0f); private set

    /** 显示用轻滤波系数（提高后抖动略多但跟手） */
    private val alpha = 0.45f

    /** 死区：小于该值的输出归零，消除静止漂移 */
    private val deadZone = 0.045f

    /** 灵敏度：rad/s 到摇杆轴的放大倍数 */
    private val sensitivity = 2.6f

    val available: Boolean get() = gyroscope != null

    fun start() {
        // FASTEST：由硬件决定最高频率（通常 100~200Hz），远高于 DSU 的 60Hz
        accelerometer?.let {
            sensorManager.registerListener(this, it, SensorManager.SENSOR_DELAY_FASTEST)
        }
        gyroscope?.let {
            sensorManager.registerListener(this, it, SensorManager.SENSOR_DELAY_FASTEST)
        }
        rotationSensor?.let {
            sensorManager.registerListener(this, it, SensorManager.SENSOR_DELAY_FASTEST)
        }
        q0 = null
    }

    fun stop() {
        sensorManager.unregisterListener(this)
    }

    override fun onSensorChanged(event: SensorEvent) {
        when (event.sensor.type) {
            Sensor.TYPE_ACCELEROMETER -> {
                val (x, y, z) = toScreenSpace(
                    event.values[0], event.values[1], event.values[2]
                )
                rawAx = x
                rawAy = y
                rawAz = z
                ax = lowPass(ax, rawAx)
                ay = lowPass(ay, rawAy)
                az = lowPass(az, rawAz)
            }

            Sensor.TYPE_GYROSCOPE -> {
                val (x, y, z) = toScreenSpace(
                    event.values[0], event.values[1], event.values[2]
                )
                rawGx = x
                rawGy = y
                rawGz = z
                gx = lowPass(gx, rawGx)
                gy = lowPass(gy, rawGy)
                gz = lowPass(gz, rawGz)

                // 左右转（绕 Y）→ 右摇杆 X；前后倾（绕 X）→ 右摇杆 Y
                rStickX = deadZone(-gy * sensitivity)
                rStickY = deadZone(gx * sensitivity)
            }

            Sensor.TYPE_GAME_ROTATION_VECTOR -> {
                // values[0..2] = x·sin(θ/2), y·sin(θ/2), z·sin(θ/2)
                // values[3]     = cos(θ/2)（部分设备不提供，需要自己算）
                val v = event.values
                var x = v[0]
                var y = v[1]
                var z = v[2]
                var w = if (v.size > 3) v[3] else 0f
                if (w == 0f) {
                    val t = 1f - (x * x + y * y + z * z)
                    w = if (t > 0f) kotlin.math.sqrt(t) else 0f
                }
                // 归一化，防止数值误差累积
                val norm = kotlin.math.sqrt(x * x + y * y + z * z + w * w)
                if (norm < 1e-6f) return
                x /= norm; y /= norm; z /= norm; w /= norm

                val cur = floatArrayOf(x, y, z, w)
                val base = q0
                if (base == null) {
                    q0 = cur
                    qx = 0f; qy = 0f; qz = 0f; qw = 1f
                } else {
                    // 相对姿态 = conj(base) ⊗ cur
                    val rel = quatMul(quatConj(base), cur)
                    qx = rel[0]; qy = rel[1]; qz = rel[2]; qw = rel[3]
                }
            }
        }
    }

    /** 四元数乘法 a ⊗ b */
    private fun quatMul(a: FloatArray, b: FloatArray): FloatArray {
        val ax = a[0]; val ay = a[1]; val az = a[2]; val aw = a[3]
        val bx = b[0]; val by = b[1]; val bz = b[2]; val bw = b[3]
        return floatArrayOf(
            aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz
        )
    }

    /** 四元数共轭（单位四元数的逆） */
    private fun quatConj(q: FloatArray): FloatArray =
        floatArrayOf(-q[0], -q[1], -q[2], q[3])

    /**
     * Android 的传感器坐标系锚定在设备的**自然方向**（竖屏）。
     * 本 App 强制横屏，若不补偿，横屏下的 X/Y 轴与实际"左右/前后"对不上，
     * 表现为倾斜方向错乱、幅度被拆到两个轴上显得不够。
     *
     * 这里按当前屏幕旋转把传感器向量转到屏幕坐标系。
     */
    private fun toScreenSpace(x: Float, y: Float, z: Float): Triple<Float, Float, Float> =
        when (currentRotation()) {
            Surface.ROTATION_90 -> Triple(-y, x, z)
            Surface.ROTATION_180 -> Triple(-x, -y, z)
            Surface.ROTATION_270 -> Triple(y, -x, z)
            else -> Triple(x, y, z)   // ROTATION_0
        }

    private fun currentRotation(): Int = try {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            context.display?.rotation ?: Surface.ROTATION_0
        } else {
            @Suppress("DEPRECATION")
            (context.getSystemService(Context.WINDOW_SERVICE) as WindowManager)
                .defaultDisplay.rotation
        }
    } catch (e: Exception) {
        Surface.ROTATION_0
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
