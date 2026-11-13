#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
motion_viewer.py — WifiPad 体感实时监视器

作为 DSU 客户端连接桥接（127.0.0.1:26760），把收到的陀螺仪/加速度
实时画成终端条形图。

用途：不用进游戏，就能确认「手机 → 桥接 → DSU」这条体感链路是通的。

用法
────
    # 先确保桥接在运行
    python Yuzu_Bridge.py

    # 另开一个窗口
    python motion_viewer.py
    python motion_viewer.py --port 26760

看到数值随手机倾斜而变化 = 体感链路正常。
"""

from __future__ import annotations

import argparse
import os
import socket
import struct
import sys
import time
import zlib

DSU_MAGIC = b"DSUC"
HDR = struct.Struct("<4sHHIII")

MSG_VERSION_REQ = 0x100000
MSG_PORTS_REQ = 0x100100
MSG_DATA_REQ = 0x100200
MSG_DATA = 0x100002


def build_packet(msg_type: int, payload: bytes = b"", server_id: int = 0) -> bytes:
    total = HDR.size + len(payload)
    hdr = HDR.pack(DSU_MAGIC, 1001, total, 0, server_id, msg_type)
    raw = hdr + payload
    crc = zlib.crc32(raw) & 0xFFFFFFFF
    return hdr[:8] + struct.pack("<I", crc) + raw[12:]


def bar(value: float, scale: float, width: int = 20, center: bool = True) -> str:
    """画一个条形图。center=True 时为双向（中间为零点）"""
    if center:
        half = width // 2
        v = max(-1.0, min(1.0, value / scale)) if scale else 0.0
        pos = int(round(v * half)) + half
        pos = max(0, min(width, pos))
        cells = ["·"] * width
        cells[half] = "│"
        if pos < half:
            for i in range(pos, half):
                cells[i] = "#"
        elif pos > half:
            for i in range(half + 1, pos + 1):
                cells[i] = "#"
        return "".join(cells)
    else:
        v = max(0.0, min(1.0, value / scale)) if scale else 0.0
        n = int(round(v * width))
        return "#" * n + "·" * (width - n)


def main() -> int:
    ap = argparse.ArgumentParser(description="WifiPad 体感实时监视器 (DSU 客户端)")
    ap.add_argument("--host", default="127.0.0.1", help="桥接地址")
    ap.add_argument("--port", type=int, default=26760, help="DSU 端口")
    ap.add_argument("--fps", type=float, default=15.0, help="刷新率（显示用）")
    args = ap.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(0.2)
    addr = (args.host, args.port)

    # ── 握手 ──
    print(f"连接 DSU 服务器 {args.host}:{args.port} ...")
    connected = False
    for _ in range(5):
        try:
            sock.sendto(build_packet(MSG_VERSION_REQ), addr)
            data, _ = sock.recvfrom(1024)
            if len(data) >= 20 and data[:4] == DSU_MAGIC:
                mtype = HDR.unpack_from(data, 0)[5]
                if mtype == 0x100001:
                    ver = struct.unpack("<H", data[20:22])[0]
                    print(f"  握手成功，协议版本 {ver}")
                    connected = True
                    break
        except socket.timeout:
            continue
        except OSError as e:
            print(f"  错误: {e}")
            break

    if not connected:
        print("\n无法连接。请确认：")
        print("  1. 桥接正在运行（python Yuzu_Bridge.py）")
        print(f"  2. DSU 端口 {args.port} 已监听")
        print("  3. 没有其它程序占用该端口")
        return 1

    # 请求端口列表 + 订阅数据
    sock.sendto(build_packet(MSG_PORTS_REQ), addr)
    try:
        sock.recvfrom(1024)
    except socket.timeout:
        pass
    sock.sendto(build_packet(MSG_DATA_REQ, struct.pack("<BB", 0, 0)), addr)
    print("  已订阅数据流，Ctrl+C 退出\n")
    time.sleep(0.4)

    last_print = 0.0
    interval = 1.0 / max(1.0, args.fps)
    packets = 0
    latest = None
    t_start = time.time()

    clear = "\x1b[2J\x1b[H" if os.name != "nt" else "\x1b[2J\x1b[H"
    print(clear, end="")

    try:
        while True:
            try:
                data, _ = sock.recvfrom(1024)
            except socket.timeout:
                data = None
            except OSError:
                break

            if data and len(data) >= 91:
                mtype = HDR.unpack_from(data, 0)[5]
                if mtype == MSG_DATA:
                    packets += 1
                    p = data[20:]
                    # Cemuhook 标准偏移：accel@23, gyro@35
                    ax, ay, az = struct.unpack("<fff", p[23:35])
                    gx, gy, gz = struct.unpack("<fff", p[35:47])
                    latest = (ax, ay, az, gx, gy, gz)

            now = time.time()
            if now - last_print >= interval:
                last_print = now
                elapsed = now - t_start
                pps = packets / elapsed if elapsed > 0 else 0

                if latest is None:
                    print(clear, end="")
                    print("等待数据…")
                    continue

                ax, ay, az, gx, gy, gz = latest

                lines = []
                lines.append("=" * 58)
                lines.append(f"  WifiPad 体感实时监视   {pps:5.1f} pps   共 {packets} 包")
                lines.append("=" * 58)
                lines.append("")
                lines.append("  陀螺仪 GYRO (deg/s)         范围 ±500")
                lines.append(f"    X {bar(gx, 500):22s} {gx:+8.2f}")
                lines.append(f"    Y {bar(gy, 500):22s} {gy:+8.2f}")
                lines.append(f"    Z {bar(gz, 500):22s} {gz:+8.2f}")
                lines.append("")
                lines.append("  加速度 ACC (g)              范围 ±2")
                lines.append(f"    X {bar(ax, 2):22s} {ax:+8.2f}")
                lines.append(f"    Y {bar(ay, 2):22s} {ay:+8.2f}")
                lines.append(f"    Z {bar(az, 2):22s} {az:+8.2f}")
                lines.append("")

                # 姿态估算（简单的横滚/俯仰）
                import math
                roll = math.degrees(math.atan2(ay, az)) if (ay or az) else 0.0
                pitch = math.degrees(math.atan2(-ax, math.hypot(ay, az))) if (ax or ay or az) else 0.0
                lines.append(f"  估算姿态: 横滚 {roll:+7.1f}°   俯仰 {pitch:+7.1f}°")
                lines.append("")
                lines.append("  【验证方法】")
                lines.append("   · 手机静止平放 → ACC 的 Z 应≈+1.00，GYRO 全≈0")
                lines.append("   · 左右倾斜手机 → ACC 的 X 变化，横滚角变化")
                lines.append("   · 前后翻转手机 → ACC 的 Y 变化，俯仰角变化")
                lines.append("   · 快速转动手机 → GYRO 三个轴出现较大读数")
                lines.append("")
                if packets == 0:
                    lines.append("  ⚠ 没收到数据：手机上「开始连接」了吗？体感开关开了吗？")
                lines.append("=" * 58)

                sys.stdout.write(clear)
                sys.stdout.write("\n".join(lines) + "\n")
                sys.stdout.flush()

    except KeyboardInterrupt:
        print("\n\n退出。")
    finally:
        sock.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())