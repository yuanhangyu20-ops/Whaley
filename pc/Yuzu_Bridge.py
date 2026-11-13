#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Yuzu_Bridge.py — WifiPad 手机虚拟手柄 → Yuzu 模拟器 综合桥接

功能
────
1. 虚拟 Xbox 360 手柄（ViGEmBus + ctypes 直调 ViGEmClient.dll，无需 vgamepad）
   · 按键反向映射：手机 Xbox A→虚拟 B，B→A，X→Y，Y→X（适配 Yuzu 的 Switch 布局）
   · LB/RB、LT/RT、十字键、L3/R3、双摇杆全部映射
2. DSU / Cemuhook 服务端（UDP 26760）
   · 把手机的陀螺仪 / 加速度计转换为 DSU 协议广播给 Yuzu
   · 单位换算：gyro rad/s → deg/s，accel m/s² → g
3. 多线程
   · 主线程：初始化 + 状态监控
   · RX 线程：接收手机 UDP（默认 12345）并更新共享状态
   · PAD 线程：60Hz 推送虚拟手柄报告
   · DSU 线程：响应握手 + 60Hz 广播体感数据

依赖
────
仅 Python 标准库！不需要 pip install vgamepad / pygame。
唯一外部依赖是 ViGEmClient.dll（本目录已附带）与系统已安装的 ViGEmBus 驱动。

用法
────
    python Yuzu_Bridge.py
    python Yuzu_Bridge.py --port 12345 --dsu-port 26760
    python Yuzu_Bridge.py --list-devices      # 检查虚拟手柄是否创建成功

退出：Ctrl+C
"""

from __future__ import annotations

import argparse
import ctypes
import os
import socket
import struct
import sys
import threading
import time
import zlib
from ctypes import wintypes

# ══════════════════════════════════════════════════════════════════
#  协议常量（与 Android 端 Protocol.kt v2 完全一致）
# ══════════════════════════════════════════════════════════════════

APP_PACKET = struct.Struct("<2sBBIQHBBbbbbhhhhhh")   # 36 字节
APP_MAGIC = b"WP"
APP_VERSION = 2
APP_PACKET_SIZE = APP_PACKET.size

# 按键位（与 Protocol.kt 的 B_* 对应）
B_A = 1 << 0
B_B = 1 << 1
B_X = 1 << 2
B_Y = 1 << 3
B_UP = 1 << 4
B_DOWN = 1 << 5
B_LEFT = 1 << 6
B_RIGHT = 1 << 7
B_LT = 1 << 8
B_RT = 1 << 9
B_LB = 1 << 10
B_RB = 1 << 11
B_L3 = 1 << 12
B_R3 = 1 << 13
B_VIEW = 1 << 14
B_MENU = 1 << 15

# flags 位（与手机端 Protocol.kt 一致）
FLAG_MODE_SWITCH = 1 << 0   # 1 = Switch 交叉映射, 0 = Xbox 直接映射
FLAG_MOTION = 1 << 1        # 1 = 本帧体感有效

BTN_NAMES = {
    B_A: "A", B_B: "B", B_X: "X", B_Y: "Y",
    B_UP: "UP", B_DOWN: "DOWN", B_LEFT: "LEFT", B_RIGHT: "RIGHT",
    B_LT: "LT", B_RT: "RT", B_LB: "LB", B_RB: "RB",
    B_L3: "L3", B_R3: "R3", B_VIEW: "VIEW", B_MENU: "MENU",
}

# ══════════════════════════════════════════════════════════════════
#  XInput / ViGEm 常量
# ══════════════════════════════════════════════════════════════════

XUSB_DPAD_UP = 0x0001
XUSB_DPAD_DOWN = 0x0002
XUSB_DPAD_LEFT = 0x0004
XUSB_DPAD_RIGHT = 0x0008
XUSB_START = 0x0010
XUSB_BACK = 0x0020
XUSB_LEFT_THUMB = 0x0040
XUSB_RIGHT_THUMB = 0x0080
XUSB_LEFT_SHOULDER = 0x0100
XUSB_RIGHT_SHOULDER = 0x0200
XUSB_GUIDE = 0x0400
XUSB_A = 0x1000
XUSB_B = 0x2000
XUSB_X = 0x4000
XUSB_Y = 0x8000

VIGEM_ERROR_NONE = 0x20000000
VIGEM_ERRORS = {
    0xE0000001: "初始化失败",
    0xE0000002: "已连接",
    0xE0000003: "未连接",
    0xE0000004: "无效目标",
    0xE0000005: "驱动版本不匹配",
    0xE0000006: "忙",
    0xE0000007: "目标已存在",
    0xE0000008: "目标不可用",
}


class XUSB_REPORT(ctypes.Structure):
    """ViGEmBus 的 Xbox 360 输入报告"""
    _fields_ = [
        ("wButtons", ctypes.c_ushort),
        ("bLeftTrigger", ctypes.c_ubyte),
        ("bRightTrigger", ctypes.c_ubyte),
        ("sThumbLX", ctypes.c_short),
        ("sThumbLY", ctypes.c_short),
        ("sThumbRX", ctypes.c_short),
        ("sThumbRY", ctypes.c_short),
    ]


# ══════════════════════════════════════════════════════════════════
#  ViGEmClient 封装（ctypes）
# ══════════════════════════════════════════════════════════════════

class VirtualXbox360:
    """通过 ViGEmClient.dll 创建并驱动一个虚拟 Xbox 360 手柄"""

    def __init__(self, dll_path: str | None = None):
        if dll_path is None:
            dll_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "ViGEmClient.dll")
        if not os.path.isfile(dll_path):
            raise FileNotFoundError(
                f"找不到 ViGEmClient.dll：{dll_path}\n"
                f"请把它放在与本脚本相同的目录下。"
            )

        self._dll = ctypes.CDLL(dll_path)
        self._bind()

        self._client = self._dll.vigem_alloc()
        if not self._client:
            raise RuntimeError("vigem_alloc 失败")

        err = self._dll.vigem_connect(self._client)
        if err != VIGEM_ERROR_NONE:
            self._dll.vigem_free(self._client)
            raise RuntimeError(
                f"连接 ViGEmBus 失败：{self._err_text(err)}\n"
                f"请确认已安装 ViGEmBus 驱动且服务正在运行。"
            )

        self._target = self._dll.vigem_target_x360_alloc()
        if not self._target:
            self._dll.vigem_disconnect(self._client)
            self._dll.vigem_free(self._client)
            raise RuntimeError("vigem_target_x360_alloc 失败")

        err = self._dll.vigem_target_add(self._client, self._target)
        if err != VIGEM_ERROR_NONE:
            self._dll.vigem_target_free(self._target)
            self._dll.vigem_disconnect(self._client)
            self._dll.vigem_free(self._client)
            raise RuntimeError(f"添加虚拟手柄失败：{self._err_text(err)}")

        self._connected = True

        # ── 关键：等待系统枚举完设备 ──
        # 驱动添加目标后，XInput 需要 1~3 秒才能枚举到该设备。
        # 若在此期间调用 update，报告会被直接丢弃（表现为手柄存在但数值永不更新）。
        time.sleep(2.5)

    def _bind(self):
        d = self._dll
        d.vigem_alloc.argtypes = ()
        d.vigem_alloc.restype = ctypes.c_void_p

        d.vigem_free.argtypes = (ctypes.c_void_p,)
        d.vigem_free.restype = None

        d.vigem_connect.argtypes = (ctypes.c_void_p,)
        d.vigem_connect.restype = ctypes.c_uint

        d.vigem_disconnect.argtypes = (ctypes.c_void_p,)
        d.vigem_disconnect.restype = None

        d.vigem_target_x360_alloc.argtypes = ()
        d.vigem_target_x360_alloc.restype = ctypes.c_void_p

        d.vigem_target_free.argtypes = (ctypes.c_void_p,)
        d.vigem_target_free.restype = None

        d.vigem_target_add.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
        d.vigem_target_add.restype = ctypes.c_uint

        d.vigem_target_remove.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
        d.vigem_target_remove.restype = ctypes.c_uint

        d.vigem_target_x360_update.argtypes = (
            ctypes.c_void_p, ctypes.c_void_p, XUSB_REPORT
        )
        d.vigem_target_x360_update.restype = ctypes.c_uint

    @staticmethod
    def _err_text(code: int) -> str:
        if code == VIGEM_ERROR_NONE:
            return "成功"
        return VIGEM_ERRORS.get(code, f"未知错误 0x{code:08X}")

    def update(self, report: XUSB_REPORT) -> int:
        return self._dll.vigem_target_x360_update(self._client, self._target, report)

    def close(self):
        if not self._connected:
            return
        self._connected = False
        try:
            self._dll.vigem_target_remove(self._client, self._target)
            self._dll.vigem_target_free(self._target)
            self._dll.vigem_disconnect(self._client)
            self._dll.vigem_free(self._client)
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════
#  共享状态
# ══════════════════════════════════════════════════════════════════

class SharedState:
    """手机 → 桥接 的最新一帧数据（线程安全）"""

    def __init__(self):
        self._lock = threading.Lock()
        self.buttons = 0
        self.lt = 0.0
        self.rt = 0.0
        self.lx = 0.0
        self.ly = 0.0
        self.rx = 0.0
        self.ry = 0.0
        self.gx = 0.0
        self.gy = 0.0
        self.gz = 0.0
        self.ax = 0.0
        self.ay = 0.0
        self.az = 9.81
        self.seq = 0
        self.last_rx_time = 0.0
        self.packets = 0
        self.switch_mode = True      # 由手机 flags 更新
        self.motion_enabled = True   # 由手机 flags 更新

    def update_from_app(self, pkt: dict):
        with self._lock:
            self.buttons = pkt["buttons"]
            self.lt = pkt["lt"]
            self.rt = pkt["rt"]
            self.lx = pkt["lx"]
            self.ly = pkt["ly"]
            self.rx = pkt["rx"]
            self.ry = pkt["ry"]
            self.gx = pkt["gx"]
            self.gy = pkt["gy"]
            self.gz = pkt["gz"]
            self.ax = pkt["ax"]
            self.ay = pkt["ay"]
            self.az = pkt["az"]
            self.seq = pkt["seq"]
            self.switch_mode = pkt.get("switch_mode", True)
            self.motion_enabled = pkt.get("motion_enabled", True)
            self.last_rx_time = time.monotonic()
            self.packets += 1

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "buttons": self.buttons,
                "lt": self.lt, "rt": self.rt,
                "lx": self.lx, "ly": self.ly,
                "rx": self.rx, "ry": self.ry,
                "gx": self.gx, "gy": self.gy, "gz": self.gz,
                "ax": self.ax, "ay": self.ay, "az": self.az,
                "seq": self.seq,
                "last_rx_time": self.last_rx_time,
                "packets": self.packets,
                "switch_mode": self.switch_mode,
                "motion_enabled": self.motion_enabled,
            }


# ══════════════════════════════════════════════════════════════════
#  DSU / Cemuhook 服务端
# ══════════════════════════════════════════════════════════════════

DSU_MAGIC = b"DSUC"
DSU_PROTOCOL_VERSION = 1001

DSUS_MSG_VERSION_REQ = 0x100000
DSUS_MSG_VERSION_RESP = 0x100001
DSUS_MSG_PORTS_REQ = 0x100100
DSUS_MSG_PORTS_RESP = 0x100101
DSUS_MSG_DATA = 0x100002
DSUS_MSG_DATA_REQ = 0x100200

DSU_HEADER = struct.Struct("<4sHHIII")   # 20 字节

# 单位换算
RAD2DEG = 57.29577951308232     # rad/s → deg/s
GRAVITY = 9.80665               # m/s² → g


def dsu_build(server_id: int, msg_type: int, payload: bytes) -> bytes:
    """构造 DSU 包（含 CRC32）"""
    total = DSU_HEADER.size + len(payload)
    header = DSU_HEADER.pack(
        DSU_MAGIC, DSU_PROTOCOL_VERSION, total, 0, server_id, msg_type
    )
    raw = header + payload
    crc = zlib.crc32(raw) & 0xFFFFFFFF
    return header[:8] + struct.pack("<I", crc) + raw[12:]


class DSUServer(threading.Thread):
    """Cemuhook DSU 服务端：响应握手并向 Yuzu 推送体感数据"""

    SLOT_INDEX = 0
    SLOT_STATE_CONNECTED = 2

    def __init__(self, state: SharedState, port: int = 26760, host: str = "0.0.0.0"):
        super().__init__(daemon=True, name="DSU-Server")
        self.state = state
        self.port = port
        self.host = host
        self._stop = threading.Event()
        self._clients: dict[tuple, int] = {}     # addr → slot
        self._clients_lock = threading.Lock()
        self._packet_no = 0
        self._server_id = int(time.time()) & 0xFFFFFFFF
        self._sock: socket.socket | None = None
        self.sent = 0

    # ── 收包线程 ──
    def run(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((self.host, self.port))
        except OSError as e:
            print(f"[DSU] 绑定 {self.host}:{self.port} 失败: {e}")
            return
        self._sock = sock
        sock.settimeout(0.5)
        print(f"[DSU] 服务端已启动 → udp://{self.host}:{self.port}")

        # 推送线程
        pusher = threading.Thread(target=self._push_loop, daemon=True, name="DSU-Push")
        pusher.start()

        while not self._stop.is_set():
            try:
                data, addr = sock.recvfrom(1024)
            except socket.timeout:
                continue
            except OSError:
                break
            self._handle(data, addr, sock)

        sock.close()

    def _handle(self, data: bytes, addr, sock: socket.socket):
        if len(data) < DSU_HEADER.size:
            return
        try:
            magic, proto, size, crc, server_id, msg = DSU_HEADER.unpack_from(data, 0)
        except struct.error:
            return
        if magic != DSU_MAGIC:
            return

        if msg == DSUS_MSG_VERSION_REQ:
            payload = struct.pack("<H", DSU_PROTOCOL_VERSION)
            sock.sendto(dsu_build(self._server_id, DSUS_MSG_VERSION_RESP, payload), addr)

        elif msg == DSUS_MSG_PORTS_REQ:
            payload = struct.pack("<BB", 1, self.SLOT_INDEX)
            payload += struct.pack("<B", self.SLOT_STATE_CONNECTED)
            sock.sendto(dsu_build(self._server_id, DSUS_MSG_PORTS_RESP, payload), addr)

        elif msg == DSUS_MSG_DATA_REQ:
            with self._clients_lock:
                if addr not in self._clients:
                    self._clients[addr] = self.SLOT_INDEX
                    print(f"[DSU] Yuzu 已订阅 ← {addr[0]}:{addr[1]}  "
                          f"(共 {len(self._clients)} 个客户端)", flush=True)

    # ── 推送线程 ──
    def _push_loop(self):
        frame = 1.0 / 60.0
        next_t = time.monotonic()
        while not self._stop.is_set():
            with self._clients_lock:
                targets = list(self._clients.keys())
            if not targets or self._sock is None:
                time.sleep(0.05)
                next_t = time.monotonic()
                continue

            pkt = self._make_data_packet()
            for addr in targets:
                try:
                    self._sock.sendto(pkt, addr)
                    self.sent += 1
                except OSError:
                    pass

            next_t += frame
            wait = next_t - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            else:
                next_t = time.monotonic()

    def _make_data_packet(self) -> bytes:
        s = self.state.snapshot()
        self._packet_no = (self._packet_no + 1) & 0xFFFFFFFF
        ts_us = int(time.monotonic() * 1_000_000) & 0xFFFFFFFFFFFFFFFF

        # 单位换算：m/s² → g，rad/s → deg/s
        ax, ay, az = s["ax"] / GRAVITY, s["ay"] / GRAVITY, s["az"] / GRAVITY
        gp, gy, gr = s["gx"] * RAD2DEG, s["gy"] * RAD2DEG, s["gz"] * RAD2DEG

        payload = struct.pack("<BB", self.SLOT_INDEX, self.SLOT_STATE_CONNECTED)
        payload += struct.pack("<I", self._packet_no)
        payload += b"\x00\x00\x00\x00\x00\x00"          # MAC 占位
        payload += struct.pack("<BB", 0xEF, 1)          # 电量 / is_active
        payload += struct.pack("<Q", ts_us)
        payload += struct.pack("<fff", ax, ay, az)      # 加速度（g）
        payload += struct.pack("<fff", gp, gy, gr)      # 陀螺仪（deg/s）
        payload += struct.pack("<fff", 0.0, 0.0, 0.0)   # 保留
        payload += b"\x00" * 12                          # 触摸数据

        return dsu_build(self._server_id, DSUS_MSG_DATA, payload)

    def stop(self):
        self._stop.set()

    @property
    def client_count(self) -> int:
        with self._clients_lock:
            return len(self._clients)


# ══════════════════════════════════════════════════════════════════
#  手机 UDP 接收
# ══════════════════════════════════════════════════════════════════

class PhoneReceiver(threading.Thread):
    """接收手机发来的 WP v2 数据包"""

    def __init__(self, state: SharedState, port: int = 12345, host: str = "0.0.0.0"):
        super().__init__(daemon=True, name="Phone-RX")
        self.state = state
        self.port = port
        self.host = host
        self._stop = threading.Event()
        self._peer: tuple | None = None

    def run(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((self.host, self.port))
        except OSError as e:
            print(f"[RX] 绑定 {self.host}:{self.port} 失败: {e}")
            return
        sock.settimeout(0.5)
        print(f"[RX] 等待手机数据 → udp://{self.host}:{self.port}")

        while not self._stop.is_set():
            try:
                data, addr = sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break

            if len(data) < APP_PACKET_SIZE:
                continue
            try:
                (magic, ver, flags, seq, ts, buttons,
                 lt, rt, lx, ly, rx, ry,
                 gx, gy, gz, ax, ay, az) = APP_PACKET.unpack_from(data)
            except struct.error:
                continue
            if magic != APP_MAGIC:
                continue

            if self._peer != addr:
                self._peer = addr
                print(f"[RX] 手机已连接 ← {addr[0]}:{addr[1]}")

            # 体感：手机已把关闭时的传感器字段清 0，这里再按 flags 防一手。
            # 体感关闭时上报「设备水平静止」的标准姿态 (0,0,1g) + 零角速度，
            # 而不是全 0 —— 全 0 会让 Yuzu 认为手柄翻转朝下。
            motion_on = bool(flags & FLAG_MOTION)
            if motion_on:
                gxf, gyf, gzf = gx / 100.0, gy / 100.0, gz / 100.0
                axf, ayf, azf = ax / 100.0, ay / 100.0, az / 100.0
            else:
                gxf = gyf = gzf = 0.0
                axf = ayf = 0.0
                azf = GRAVITY      # 1g

            self.state.update_from_app({
                "seq": seq,
                "buttons": buttons,
                "lt": lt / 255.0,
                "rt": rt / 255.0,
                "lx": lx / 127.0,
                "ly": ly / 127.0,
                "rx": rx / 127.0,
                "ry": ry / 127.0,
                "gx": gxf,
                "gy": gyf,
                "gz": gzf,
                "ax": axf,
                "ay": ayf,
                "az": azf,
                "switch_mode": bool(flags & FLAG_MODE_SWITCH),
                "motion_enabled": motion_on,
            })

        sock.close()

    def stop(self):
        self._stop.set()


# ══════════════════════════════════════════════════════════════════
#  虚拟手柄推送
# ══════════════════════════════════════════════════════════════════

def axis_to_xinput(v: float) -> int:
    """[-1,1] → [-32768, 32767]"""
    v = max(-1.0, min(1.0, v))
    return int(v * 32767) if v >= 0 else int(v * 32768)


def build_report(s: dict, swap_abxy: bool = True) -> XUSB_REPORT:
    """
    手机按键 → XInput 报告

    Args:
        s: 共享状态快照
        swap_abxy: True 时做 A/B、X/Y 交叉映射（适配跳过关的 Switch 布局直觉）
                   False 时一一对应
    """
    b = s["buttons"]
    wb = 0

    # ── ABXY 映射 ──
    if swap_abxy:
        # 交叉：手机 A → 虚拟 B，B → A，X → Y，Y → X
        if b & B_A:
            wb |= XUSB_B
        if b & B_B:
            wb |= XUSB_A
        if b & B_X:
            wb |= XUSB_Y
        if b & B_Y:
            wb |= XUSB_X
    else:
        if b & B_A:
            wb |= XUSB_A
        if b & B_B:
            wb |= XUSB_B
        if b & B_X:
            wb |= XUSB_X
        if b & B_Y:
            wb |= XUSB_Y

    # ── 其余按键正常映射 ──
    if b & B_UP:
        wb |= XUSB_DPAD_UP
    if b & B_DOWN:
        wb |= XUSB_DPAD_DOWN
    if b & B_LEFT:
        wb |= XUSB_DPAD_LEFT
    if b & B_RIGHT:
        wb |= XUSB_DPAD_RIGHT
    if b & B_LB:
        wb |= XUSB_LEFT_SHOULDER
    if b & B_RB:
        wb |= XUSB_RIGHT_SHOULDER
    if b & B_L3:
        wb |= XUSB_LEFT_THUMB
    if b & B_R3:
        wb |= XUSB_RIGHT_THUMB
    # VIEW → BACK（Switch 的 Minus 键）, MENU → START（Switch 的 Plus 键）
    if b & B_VIEW:
        wb |= XUSB_BACK
    if b & B_MENU:
        wb |= XUSB_START

    rep = XUSB_REPORT()
    rep.wButtons = wb
    # 扳机是模拟量 0~255，不是布尔键。手机端传 0.0~1.0 的浮点。
    rep.bLeftTrigger = int(max(0.0, min(1.0, s["lt"])) * 255)
    rep.bRightTrigger = int(max(0.0, min(1.0, s["rt"])) * 255)
    rep.sThumbLX = axis_to_xinput(s["lx"])
    rep.sThumbLY = axis_to_xinput(s["ly"])
    rep.sThumbRX = axis_to_xinput(s["rx"])
    rep.sThumbRY = axis_to_xinput(s["ry"])
    return rep


def pad_loop(gamepad: VirtualXbox360, state: SharedState, stop: threading.Event,
             swap_abxy: bool = True):
    """60Hz 推送虚拟手柄状态"""
    frame = 1.0 / 60.0
    next_t = time.monotonic()
    errors = 0
    frames = 0
    try:
        # ── 启动抖动 ──
        # XInput 对新建的 ViGEm 虚拟手柄存在缓存问题：若首帧就是全零报告，
        # XInputGetState 可能长期返回初始的陈旧值（pack 不递增）。
        # 先发送几次明显不同的报告，强制 XInput 刷新内部状态。
        for jiggle in (
            (0x1000, 32767, -32768, 32767, -32768),   # A键 + 摇杆打角
            (0x0000, -32768, 32767, -32768, 32767),   # 反向打角
            (0x0000, 0, 0, 0, 0),                     # 回中
        ):
            r = XUSB_REPORT()
            r.wButtons = jiggle[0]
            r.sThumbLX = jiggle[1]
            r.sThumbLY = jiggle[2]
            r.sThumbRX = jiggle[3]
            r.sThumbRY = jiggle[4]
            for _ in range(5):
                gamepad.update(r)
                time.sleep(0.02)
        print("[PAD] 已发送启动抖动，XInput 状态已刷新", flush=True)

        while not stop.is_set():
            s = state.snapshot()
            # 手机端的模式优先；命令行 --no-swap 只是默认值
            use_swap = s.get("switch_mode", swap_abxy)
            rep = build_report(s, use_swap)
            err = gamepad.update(rep)
            frames += 1
            if frames % 300 == 0:
                print(
                    f"[PAD] 已推送 {frames} 帧  "
                    f"btn=0x{rep.wButtons:04X} LT={rep.bLeftTrigger} RT={rep.bRightTrigger} "
                    f"L=({rep.sThumbLX},{rep.sThumbLY}) R=({rep.sThumbRX},{rep.sThumbRY}) ret=0x{err:08X}",
                    flush=True,
                )
            if err != VIGEM_ERROR_NONE:
                errors += 1
                if errors == 1:
                    print(f"[PAD] 更新失败: {VirtualXbox360._err_text(err)}", flush=True)
            next_t += frame
            wait = next_t - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            else:
                next_t = time.monotonic()
    except Exception as e:
        import traceback
        print(f"[PAD] 线程异常退出: {e}", flush=True)
        traceback.print_exc()
    finally:
        print(f"[PAD] 线程结束，共推送 {frames} 帧", flush=True)


# ══════════════════════════════════════════════════════════════════
#  主程序
# ══════════════════════════════════════════════════════════════════

def check_vigem_service() -> bool:
    """检查 ViGEmBus 驱动是否就绪"""
    try:
        import subprocess
        r = subprocess.run(
            ["sc", "query", "ViGEmBus"],
            capture_output=True, text=True, timeout=5
        )
        return "RUNNING" in r.stdout.upper()
    except Exception:
        return False


def main() -> int:
    ap = argparse.ArgumentParser(
        description="WifiPad → Yuzu 综合桥接（虚拟手柄 + DSU 体感）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python Yuzu_Bridge.py                     # 默认 12345 / 26760
  python Yuzu_Bridge.py --port 12346        # 改手机数据端口
  python Yuzu_Bridge.py --check             # 只检查环境
"""
    )
    ap.add_argument("--port", type=int, default=12345,
                    help="手机 UDP 数据端口（默认 12345）")
    ap.add_argument("--dsu-port", type=int, default=26760,
                    help="DSU 体感端口（默认 26760）")
    ap.add_argument("--bind", default="0.0.0.0", help="监听地址")
    ap.add_argument("--check", action="store_true", help="只检查环境后退出")
    ap.add_argument("--no-swap", action="store_true",
                    help="关闭 ABXY 交叉映射")
    args = ap.parse_args()

    print("=" * 62)
    print("  WifiPad → Yuzu 桥接")
    print("  · 虚拟 Xbox 360 手柄（按键/摇杆）")
    print("  · DSU 体感（陀螺仪/加速度计）")
    print("=" * 62)

    # ── 环境检查 ──
    vigem_ok = check_vigem_service()
    print(f"[检查] ViGEmBus 服务: {'运行中 ✓' if vigem_ok else '未运行 ✗'}")
    if not vigem_ok:
        print("       → 请先安装 ViGEmBus 驱动（安装包随 vgamepad 提供）")

    try:
        gamepad = VirtualXbox360()
        print("[检查] 虚拟 Xbox 360 手柄: 创建成功 ✓")
    except Exception as e:
        print(f"[检查] 虚拟手柄创建失败: {e}")
        if args.check:
            return 1
        print("\n无法继续，请先解决驱动问题。")
        return 1

    if args.check:
        gamepad.close()
        print("\n环境检查通过。")
        return 0

    state = SharedState()
    stop = threading.Event()

    rx = PhoneReceiver(state, port=args.port, host=args.bind)
    dsu = DSUServer(state, port=args.dsu_port, host=args.bind)

    rx.start()
    dsu.start()

    pad_thread = threading.Thread(
        target=pad_loop, args=(gamepad, state, stop, not args.no_swap),
        daemon=True, name="PAD"
    )
    pad_thread.start()

    print("\n" + "-" * 62)
    print("  就绪。请在手机上填入本机 IP，端口 %d，点「开始连接」" % args.port)
    print("  Yuzu 中把控制器设为「任意控制器」并启用体感（DSU）")
    print("  ABXY: " + ("交叉 A->B B->A X->Y Y->X" if not args.no_swap else "一一对应"))
    print("  Ctrl+C 退出")
    print("-" * 62 + "\n")

    t0 = time.monotonic()
    last_report = t0
    last_packets = 0
    try:
        while True:
            time.sleep(1.0)
            now = time.monotonic()
            s = state.snapshot()
            pps = s["packets"] - last_packets
            last_packets = s["packets"]

            if now - last_report >= 5.0:
                last_report = now
                age = now - s["last_rx_time"] if s["last_rx_time"] else 999
                online = "在线" if age < 2.0 else "离线"
                keys = ",".join(
                    n for bit, n in BTN_NAMES.items() if s["buttons"] & bit
                ) or "-"
                mode = "Switch" if s.get("switch_mode", True) else "Xbox"
                mot = "开" if s.get("motion_enabled", True) else "关"
                print(
                    f"[状态] 手机{online} {pps:2d}pps  模式={mode} 体感={mot}  "
                    f"DSU客户端={dsu.client_count} 推送={dsu.sent}"
                )
                print(
                    f"        KEY={keys:<18} "
                    f"L=({s['lx']:+.2f},{s['ly']:+.2f}) "
                    f"R=({s['rx']:+.2f},{s['ry']:+.2f}) "
                    f"TRIG={s['lt']:.2f}/{s['rt']:.2f}"
                )
                print(
                    f"        GYRO=({s['gx']:+.2f},{s['gy']:+.2f},{s['gz']:+.2f}) rad/s  "
                    f"ACC=({s['ax']/9.80665:+.2f},{s['ay']/9.80665:+.2f},"
                    f"{s['az']/9.80665:+.2f}) g"
                )
    except KeyboardInterrupt:
        print("\n[退出] 正在关闭…")
    finally:
        stop.set()
        rx.stop()
        dsu.stop()
        time.sleep(0.3)
        gamepad.close()
        print("[退出] 虚拟手柄已移除。")
    return 0


if __name__ == "__main__":
    sys.exit(main())