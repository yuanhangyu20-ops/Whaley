package com.example.wifipad.net

import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.net.NetworkInterface
import java.net.SocketTimeoutException

/**
 * 局域网自动发现：让用户不用手输 IP。
 *
 * 原理
 * ────
 * 手机向广播地址发送 `WIFIPAD_DISCOVER`，电脑端的桥接程序在 UDP 9999 上
 * 监听并应答 `WIFIPAD_HERE|<ip>|<port>`，手机据此自动填好地址。
 *
 * 为什么要遍历各网卡的广播地址
 * ──────────────────────────
 * `255.255.255.255` 在部分安卓 ROM/路由器上会被丢弃，只发它经常搜不到。
 * 从 NetworkInterface 拿到每个网卡的真实广播地址（如 192.168.1.255）更可靠。
 */
object Discovery {

    const val PORT = 9999
    private const val REQ = "WIFIPAD_DISCOVER"
    private const val RSP_PREFIX = "WIFIPAD_HERE|"

    /** 找到的电脑地址 */
    data class Result(val ip: String, val port: Int)

    /**
     * 广播搜索电脑。
     *
     * @param timeoutMs 总超时；期间会重复广播几次，避免首包丢失。
     * @return 找到则返回地址，否则 null
     */
    fun discover(timeoutMs: Long = 4500): Result? {
        val targets = buildTargets()
        if (targets.isEmpty()) return null

        DatagramSocket().use { sock ->
            sock.broadcast = true
            sock.soTimeout = 500
            val payload = REQ.toByteArray()

            val deadline = System.currentTimeMillis() + timeoutMs
            var lastSend = 0L
            val buf = ByteArray(256)

            while (System.currentTimeMillis() < deadline) {
                val now = System.currentTimeMillis()
                // 每 900ms 重发一轮，提高弱网下的成功率
                if (now - lastSend > 900) {
                    for (addr in targets) {
                        try {
                            sock.send(DatagramPacket(payload, payload.size, addr, PORT))
                        } catch (_: Exception) {
                            // 某个网卡不可用就跳过
                        }
                    }
                    lastSend = now
                }

                try {
                    val pkt = DatagramPacket(buf, buf.size)
                    sock.receive(pkt)
                    val text = String(pkt.data, 0, pkt.length, Charsets.UTF_8)
                    if (text.startsWith(RSP_PREFIX)) {
                        val parts = text.split("|")
                        if (parts.size >= 3) {
                            val ip = parts[1].trim()
                            val port = parts[2].trim().toIntOrNull() ?: 12345
                            if (ip.isNotEmpty()) return Result(ip, port)
                        }
                    }
                } catch (_: SocketTimeoutException) {
                    // 没收到就继续等/重发
                } catch (_: Exception) {
                    // 单个包解析失败不影响后续
                }
            }
        }
        return null
    }

    /**
     * 收集所有可能的广播目标：
     *   1. 各网卡的真实子网广播地址（最可靠）
     *   2. 全局广播 255.255.255.255
     *   3. 常见家用网段，兜底
     */
    private fun buildTargets(): List<InetAddress> {
        val out = LinkedHashSet<InetAddress>()

        try {
            for (nif in NetworkInterface.getNetworkInterfaces()) {
                if (!nif.isUp || nif.isLoopback) continue
                for (ia in nif.interfaceAddresses) {
                    ia.broadcast?.let { out.add(it) }
                }
            }
        } catch (_: Exception) {
        }

        for (ip in listOf(
            "255.255.255.255",
            "192.168.0.255", "192.168.1.255", "192.168.2.255",
            "192.168.31.255", "10.0.0.255", "10.0.1.255"
        )) {
            try {
                out.add(InetAddress.getByName(ip))
            } catch (_: Exception) {
            }
        }
        return out.toList()
    }
}