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
 * 60Hz UDP 发送器。
 *
 * 用「下一帧绝对时间」的方式补偿，避免 delay 累积漂移；
 * 若落后超过一帧则重置基准，防止雪崩式追赶。
 */
class UdpSender {
    private var job: Job? = null
    private var socket: DatagramSocket? = null

    var onError: ((String) -> Unit)? = null
    var onSent: (() -> Unit)? = null

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
                sock = DatagramSocket().also { socket = it }
                val frameNs = 1_000_000_000L / 60L
                var next = System.nanoTime()

                while (isActive) {
                    val data = provider().encode()
                    sock.send(DatagramPacket(data, data.size, target, port))
                    onSent?.invoke()

                    next += frameNs
                    val waitMs = (next - System.nanoTime()) / 1_000_000L
                    if (waitMs > 0) {
                        delay(waitMs)
                    } else {
                        // 已经落后，重置基准
                        next = System.nanoTime()
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
