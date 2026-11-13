package com.example.wifipad.net

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress

/**
 * 高频 UDP 发送器（默认 120Hz）。
 *
 * 为什么不是 60Hz
 * ──────────────
 * 传感器以 100~200Hz 采样，若发循环只有 60Hz，每个采样值平均要等
 * 8.3ms（最差 16.7ms）才被发出；PC 端的 DSU 推送又是另一级 60Hz 等待，
 * 两级叠加就是用户能明显感觉到的输入迟滞。提到 120Hz 后每级等待减半。
 *
 * 等待策略
 * ───────
 * Android 的 delay() 只有毫秒级精度，剩下的细粒度误差会让节拍漂移。
 * 这里先用 delay 睡到"还差 2ms"，最后这一段用自旋把误差压到亚毫秒，
 * 让发送节拍稳定贴着目标频率走。
 */
class UdpSender {

    var onError: ((String) -> Unit)? = null
    var onSent: (() -> Unit)? = null

    private var job: Job? = null
    private var socket: DatagramSocket? = null

    /** 发送频率（Hz）。120 足以覆盖手机传感器带宽。 */
    var rateHz: Int = 120

    fun start(
        scope: CoroutineScope,
        host: String,
        port: Int,
        provider: () -> GamepadPacket
    ) {
        stop()
        job = scope.launch(Dispatchers.IO) {
            var sock: DatagramSocket? = null
            try {
                val target = InetAddress.getByName(host)
                sock = DatagramSocket().also {
                    it.trafficClass = 0x10   // IPTOS_LOWDELAY：让系统优先排队
                    socket = it
                }

                // 发送缓冲区尽量小，避免内核攒包增加延迟
                try {
                    sock.sendBufferSize = 4096
                } catch (_: Exception) {
                }

                val frameNs = 1_000_000_000L / rateHz.toLong()
                var next = System.nanoTime()

                while (isActive) {
                    val data = provider().encode()
                    sock.send(DatagramPacket(data, data.size, target, port))
                    onSent?.invoke()

                    next += frameNs
                    val remain = next - System.nanoTime()
                    if (remain <= 0) {
                        // 已经落后：不追帧，直接从当前时刻重新对齐，避免雪崩
                        next = System.nanoTime()
                        continue
                    }
                    // 先睡到还差 2ms，再用自旋收尾
                    val sleepMs = (remain - 2_000_000L) / 1_000_000L
                    if (sleepMs > 0) {
                        delay(sleepMs)
                    }
                    while (System.nanoTime() < next && isActive) {
                        Thread.yield()
                    }
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                onError?.invoke(e.message ?: e.toString())
            } finally {
                sock?.close()
                socket = null
            }
        }
    }

    fun stop() {
        job?.cancel()
        job = null
        socket?.close()
        socket = null
    }
}