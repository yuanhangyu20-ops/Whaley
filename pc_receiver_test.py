#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WifiPad UDP 测试接收端。

用法：
    python pc_receiver_test.py                 # 监听 0.0.0.0:12345
    python pc_receiver_test.py --port 12345    # 自定义端口
    python pc_receiver_test.py --quiet         # 只打印每秒统计

数据包协议（v1，小端，38 字节）：
    '<2sBBIQHBBbbbbhhhhhh'
    magic(2s) ver(B) flags(B) seq(I) ts(Q) buttons(H)
    lt(B) rt(B) lx(b) ly(b) rx(b) ry(b)
    gx(h) gy(h) gz(h) ax(h) ay(h) az(h)

退出：Ctrl+C
"""

import argparse
import socket
import struct
import sys
import time

# 与 Android 端 Protocol.PACKET_SIZE 一致
PACKET = struct.Struct("<2sBBIQHBBbbbbhhhhhh")
BTN_BITS = [
    (1 << 0, "A"), (1 << 1, "B"), (1 << 2, "X"), (1 << 3, "Y"),
    (1 << 4, "UP"), (1 << 5, "DOWN"), (1 << 6, "LEFT"), (1 << 7, "RIGHT"),
    (1 << 8, "LT"), (1 << 9, "RT"),
]


def decode(raw: bytes):
    if len(raw) < PACKET.size:
        return None
    (magic, ver, flags, seq, ts, buttons,
     lt, rt, lx, ly, rx, ry,
     gx, gy, gz, ax, ay, az) = PACKET.unpack_from(raw)
    if magic != b"WP":
        return None
    pressed = [name for bit, name in BTN_BITS if buttons & bit]
    return {
        "ver": ver, "seq": seq, "ts": ts,
        "buttons": pressed,
        "lt": lt / 255.0, "rt": rt / 255.0,
        "lx": lx / 127.0, "ly": ly / 127.0,
        "rx": rx / 127.0, "ry": ry / 127.0,
        "gx": gx / 100.0, "gy": gy / 100.0, "gz": gz / 100.0,
        "ax": ax / 100.0, "ay": ay / 100.0, "az": az / 100.0,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="WifiPad UDP 测试接收端")
    ap.add_argument("--port", type=int, default=12345, help="监听端口（默认 12345）")
    ap.add_argument("--bind", default="0.0.0.0", help="监听地址（默认 0.0.0.0）")
    ap.add_argument("--quiet", action="store_true", help="只打印每秒统计")
    args = ap.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((args.bind, args.port))
    except OSError as e:
        print(f"[!] 绑定 {args.bind}:{args.port} 失败: {e}", file=sys.stderr)
        return 1

    print(f"[WifiPad] 监听 UDP {args.bind}:{args.port}  (Ctrl+C 停止)", flush=True)
    print(f"[WifiPad] 数据包大小 {PACKET.size} 字节", flush=True)

    count = 0
    last_report = time.time()
    last_seq = None
    first_seen = None

    try:
        while True:
            raw, addr = sock.recvfrom(2048)
            pkt = decode(raw)
            if pkt is None:
                print(f"[!] 无法解析（magic 不符）来自 {addr}，前 8 字节: {raw[:8].hex()}", flush=True)
                continue

            if first_seen is None:
                first_seen = time.time()
                print(f"[WifiPad] 首次收到数据，来自 {addr[0]}:{addr[1]}", flush=True)

            count += 1
            now = time.time()

            # 每秒统计
            if now - last_report >= 1.0:
                elapsed = now - last_report
                print(f"[stat] {count / elapsed:5.1f} pps", flush=True)
                count = 0
                last_report = now

            if args.quiet:
                continue

            gap = ""
            if last_seq is not None:
                expected = (last_seq + 1) & 0xFFFFFFFF
                if pkt["seq"] != expected:
                    dropped = (pkt["seq"] - expected) & 0xFFFFFFFF
                    gap = f"  <丢包 {dropped}>"
            last_seq = pkt["seq"]

            keys = ",".join(pkt["buttons"]) or "-"
            print(
                f"seq={pkt['seq']:<6} "
                f"KEY={keys:<14} "
                f"L=({pkt['lx']:+.2f},{pkt['ly']:+.2f}) "
                f"R=({pkt['rx']:+.2f},{pkt['ry']:+.2f}) "
                f"TRIG={pkt['lt']:.2f}/{pkt['rt']:.2f} "
                f"GYRO=({pkt['gx']:+.2f},{pkt['gy']:+.2f},{pkt['gz']:+.2f}) "
                f"ACC=({pkt['ax']:+.2f},{pkt['ay']:+.2f},{pkt['az']:+.2f})"
                f"{gap}",
                flush=True,
            )
    except KeyboardInterrupt:
        print("\n[WifiPad] 已停止。", flush=True)
    finally:
        sock.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
