#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Yuzu_Bridge.py — WifiPad 手机虚拟手柄 → Yuzu 模拟器 综合桥接

功能
────
1. 虚拟 DualShock 4 手柄（ViGEmBus + ctypes 直调 ViGEmClient.dll）
   · 必须用 DS4 而非 Xbox 360：ViGEm 的 X360 手柄只更新 XInput 接口，
     SDL2（Yuzu 使用）通过 HID 读取会得到全零，表现为游戏里按什么都没反应
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
#  DS4 (DualShock 4) 常量 —— ViGEm DS4_REPORT 定义
# ══════════════════════════════════════════════════════════════════

# 面板按键位
DS4_SQUARE = 1 << 4
DS4_CROSS = 1 << 5
DS4_CIRCLE = 1 << 6
DS4_TRIANGLE = 1 << 7
# 肩键 / 扳机键（数字位）
DS4_L1 = 1 << 8
DS4_R1 = 1 << 9
DS4_L2 = 1 << 10
DS4_R2 = 1 << 11
# 功能键
DS4_SHARE = 1 << 12
DS4_OPTIONS = 1 << 13
# 摇杆下压
DS4_L3 = 1 << 14
DS4_R3 = 1 << 15

# D-Pad 是 wButtons 的低 4 位（HAT 编码）
DS4_DPAD_N = 0
DS4_DPAD_NE = 1
DS4_DPAD_E = 2
DS4_DPAD_SE = 3
DS4_DPAD_S = 4
DS4_DPAD_SW = 5
DS4_DPAD_W = 6
DS4_DPAD_NW = 7
DS4_DPAD_NONE = 8
DS4_DPAD_MASK = 0x0F

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


class DS4_REPORT(ctypes.Structure):
    """
    ViGEmBus 的 DualShock 4 输入报告。

    为什么用 DS4 而不是 Xbox 360？
    ─────────────────────────────
    ViGEm 的虚拟 Xbox 360 手柄只更新 XInput 接口，SDL2 通过 HID 读取时
    永远得到全零 —— 实测 XInput 能读到 btn=0x1000，但 SDL 的
    GameController 和 Joystick 两层都是 0。Yuzu 用 SDL，所以按什么都没反应。

    ViGEm 的 DS4 手柄会生成完整的 HID 输入报告，SDL2 通过 HIDAPI 能正常读取。
    """
    _fields_ = [
        ("bThumbLX", ctypes.c_ubyte),   # 0..255, 中心 128
        ("bThumbLY", ctypes.c_ubyte),
        ("bThumbRX", ctypes.c_ubyte),
        ("bThumbRY", ctypes.c_ubyte),
        ("wButtons", ctypes.c_ushort),
        ("bSpecial", ctypes.c_ubyte),
        ("bTriggerL", ctypes.c_ubyte),  # 0..255
        ("bTriggerR", ctypes.c_ubyte),
    ]


# ══════════════════════════════════════════════════════════════════
#  ViGEmClient 封装（ctypes）
# ══════════════════════════════════════════════════════════════════

class VirtualDS4:
    """通过 ViGEmClient.dll 创建并驱动一个虚拟 DualShock 4 手柄"""

    def __init__(self, dll_path: str | None = None):
        if dll_path is None:
            dll_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "ViGEmClient.dll")
        if not os.path.isfile(dll_path):
            raise FileNotFoundError(f"找不到 ViGEmClient.dll：{dll_path}")

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
                f"请确认已安装 ViGEmBus 驱动且服务正在运行。")

        self._target = self._dll.vigem_target_ds4_alloc()
        if not self._target:
            self._dll.vigem_disconnect(self._client)
            self._dll.vigem_free(self._client)
            raise RuntimeError("vigem_target_ds4_alloc 失败")

        err = self._dll.vigem_target_add(self._client, self._target)
        if err != VIGEM_ERROR_NONE:
            self._dll.vigem_target_free(self._target)
            self._dll.vigem_disconnect(self._client)
            self._dll.vigem_free(self._client)
            raise RuntimeError(f"添加虚拟手柄失败：{self._err_text(err)}")

        self._connected = True

        # 等待系统枚举完设备，否则最初的报告会被丢弃
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
        d.vigem_target_ds4_alloc.argtypes = ()
        d.vigem_target_ds4_alloc.restype = ctypes.c_void_p
        d.vigem_target_free.argtypes = (ctypes.c_void_p,)
        d.vigem_target_free.restype = None
        d.vigem_target_add.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
        d.vigem_target_add.restype = ctypes.c_uint
        d.vigem_target_remove.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
        d.vigem_target_remove.restype = ctypes.c_uint
        d.vigem_target_ds4_update.argtypes = (
            ctypes.c_void_p, ctypes.c_void_p, DS4_REPORT)
        d.vigem_target_ds4_update.restype = ctypes.c_uint

    @staticmethod
    def _err_text(code: int) -> str:
        if code == VIGEM_ERROR_NONE:
            return "成功"
        return VIGEM_ERRORS.get(code, f"未知错误 0x{code:08X}")

    def update(self, report) -> int:
        return self._dll.vigem_target_ds4_update(self._client, self._target, report)

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

DSU_MAGIC_CLIENT = b"DSUC"   # 客户端 → 服务器
DSU_MAGIC_SERVER = b"DSUS"   # 服务器 → 客户端（必须用这个，之前用 DSUC 是错的）
DSU_PROTOCOL_VERSION = 1001

# 消息类型：Cemuhook 的请求与响应共用同一 type
DSUS_MSG_VERSION = 0x100000     # 版本握手
DSUS_MSG_PORTS = 0x100001       # 端口列表
DSUS_MSG_DATA = 0x100002        # 手柄数据（也是订阅请求）

# 兼容旧式命名（部分实现把端口请求写成 0x100100）
DSUS_MSG_PORTS_LEGACY = 0x100100

DSU_HEADER = struct.Struct("<4sHHIII")   # 20 字节

# 单位换算
RAD2DEG = 57.29577951308232     # rad/s → deg/s
GRAVITY = 9.80665               # m/s² → g


def dsu_build(server_id: int, msg_type: int, payload: bytes) -> bytes:
    """
    构造 DSU 包（服务器 → 客户端）。

    关键细节（对齐 PhoneGyro 的实测实现）：
      · magic 必须是 "DSUS"，不是 "DSUC"
      · length 字段 = payload 长度 + 4（msgType），**不是**整包长度
      · CRC32 对整包计算，计算时 CRC 字段本身保持 0
    """
    length = len(payload) + 4
    total = DSU_HEADER.size + len(payload)
    header = DSU_HEADER.pack(
        DSU_MAGIC_SERVER, DSU_PROTOCOL_VERSION, length, 0, server_id, msg_type
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
        # DSU 时间戳必须是一个「积分时钟」：从 0 起算，每帧累加真实间隔。
        # 若直接用 monotonic() 的绝对值（系统启动以来的微秒，可达 1e10），
        # 客户端第一帧拿到的 delta 就是天文数字，角速度积分直接爆掉。
        self._ts_us = 0
        self._last_push_t = None
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
            except ConnectionResetError:
                # Windows 特有：对端端口不可达时内核回 ICMP Port Unreachable，
                # recvfrom 会抛 WinError 10054。这**不是**致命错误，继续监听。
                continue
            except OSError as e:
                if self._stop.is_set():
                    break
                # 其他瞬时网络错误：退避后继续，绝不让 DSU 线程死掉
                print(f"[DSU] recv 异常（已忽略）: {e}", flush=True)
                time.sleep(0.1)
                continue
            self._handle(data, addr, sock)

        sock.close()

    def _handle(self, data: bytes, addr, sock: socket.socket):
        # 诊断：记录进入 DSU 端口的**任何**原始包，无论格式是否合法
        if not hasattr(self, "_raw_count"):
            self._raw_count = 0
        self._raw_count += 1
        if self._raw_count <= 20:
            print(f"[DSU-RAW] #{self._raw_count} len={len(data)} "
                  f"from {addr[0]}:{addr[1]} hex={data[:32].hex()}", flush=True)

        if len(data) < DSU_HEADER.size:
            return
        try:
            magic, proto, size, crc, server_id, msg = DSU_HEADER.unpack_from(data, 0)
        except struct.error:
            return
        if magic != DSU_MAGIC_CLIENT:
            return

        if msg not in getattr(self, "_seen_msgs", set()):
            if not hasattr(self, "_seen_msgs"):
                self._seen_msgs = set()
            self._seen_msgs.add(msg)
            names = {
                0x100000: "VERSION", 0x100001: "PORTS",
                0x100002: "DATA/SUBSCRIBE", 0x100100: "PORTS(legacy)",
            }
            print(f"[DSU] 收到 {names.get(msg, f'0x{msg:06X}')} "
                  f"from {addr[0]}:{addr[1]}", flush=True)

        # ── 版本握手（响应 type 与请求相同：0x100000）──
        if msg == DSUS_MSG_VERSION:
            buf = bytearray(24)
            struct.pack_into("<HHIII", buf, 4, DSU_PROTOCOL_VERSION, 8, 0, self._server_id, 0)
            buf[0:4] = DSU_MAGIC_SERVER
            struct.pack_into("<I", buf, 16, DSUS_MSG_VERSION)
            struct.pack_into("<H", buf, 20, DSU_PROTOCOL_VERSION)
            crc = zlib.crc32(bytes(buf)) & 0xFFFFFFFF
            struct.pack_into("<I", buf, 8, crc)
            try:
                sock.sendto(bytes(buf), addr)
            except OSError:
                pass

        # ── 端口列表（响应 type 同为 0x100001；兼容旧式 0x100100 请求）──
        elif msg in (DSUS_MSG_PORTS, DSUS_MSG_PORTS_LEGACY):
            payload = bytearray(12)
            payload[0] = self.SLOT_INDEX
            payload[1] = self.SLOT_STATE_CONNECTED
            payload[2] = 2              # model = 完整陀螺仪
            payload[3] = 2              # conn_type = 无线
            payload[10] = 5             # battery = 满电
            payload[11] = 1             # is_active
            resp = dsu_build(self._server_id, DSUS_MSG_PORTS, bytes(payload))
            # length 字段必须是 12+4
            resp = resp[:6] + struct.pack("<H", 16) + resp[8:]
            crc = zlib.crc32(resp[:8] + b"\x00\x00\x00\x00" + resp[12:]) & 0xFFFFFFFF
            resp = resp[:8] + struct.pack("<I", crc) + resp[12:]
            try:
                sock.sendto(resp, addr)
            except OSError:
                pass

        # ── 数据请求 = 订阅 ──
        elif msg == DSUS_MSG_DATA:
            with self._clients_lock:
                if addr not in self._clients:
                    self._clients[addr] = self.SLOT_INDEX
                    print(f"[DSU] Yuzu 已订阅 ← {addr[0]}:{addr[1]}  "
                          f"(共 {len(self._clients)} 个客户端)", flush=True)
            # 新订阅者立刻收到一帧静止数据，避免客户端等下一轮
            try:
                sock.sendto(self._make_data_packet(), addr)
            except OSError:
                pass

    # ── 推送线程 ──
    def _push_loop(self):
        # 与手机 120Hz 发送率对齐：每一帧新鲜数据都尽快转给 Yuzu，
        # 避免 60Hz 时最多再等 16.7ms 才发出。
        frame = 1.0 / 120.0
        next_t = time.monotonic()
        while not self._stop.is_set():
            with self._clients_lock:
                targets = list(self._clients.keys())
            if not targets or self._sock is None:
                time.sleep(0.05)
                next_t = time.monotonic()
                continue

            pkt = self._make_data_packet()
            dead = []
            for addr in targets:
                try:
                    self._sock.sendto(pkt, addr)
                    self.sent += 1
                except OSError:
                    dead.append(addr)
            # 清理已失效的客户端，避免推送数停滞
            if dead:
                with self._clients_lock:
                    for a in dead:
                        self._clients.pop(a, None)

            next_t += frame
            wait = next_t - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            else:
                next_t = time.monotonic()

    def _make_data_packet(self) -> bytes:
        s = self.state.snapshot()
        self._packet_no = (self._packet_no + 1) & 0xFFFFFFFF
        # 积分时钟：首帧按标准 60Hz 间隔起算，之后累加真实推送间隔。
        now_t = time.monotonic()
        if self._last_push_t is None:
            self._ts_us += 16667          # 16.667ms ≈ 60Hz
        else:
            delta = int((now_t - self._last_push_t) * 1_000_000)
            # 夹在 [100µs, 100ms]：太小的抖动用最小值，长时间停顿也不至于爆掉
            self._ts_us += max(100, min(delta, 100_000))
        self._last_push_t = now_t
        ts_us = self._ts_us & 0xFFFFFFFFFFFFFFFF

        # ── 单位换算：m/s² → g，rad/s → deg/s ──
        mx = s["ax"] / GRAVITY      # 手机坐标：X 右
        my = s["ay"] / GRAVITY      #           Y 上
        mz = s["az"] / GRAVITY      #           Z 屏幕外
        mgx = s["gx"] * RAD2DEG     # 绕 X（前后倾）
        mgy = s["gy"] * RAD2DEG     # 绕 Y（左右转）
        mgz = s["gz"] * RAD2DEG     # 绕 Z（屏幕内旋转）

        # ── 坐标系转换：手机 → DSU/Switch Pro Controller ──
        # PadTest 验证的 DSU 约定（见 PhoneGyro docs/motion-pipeline §7）：
        #   平放时 AccY = -1g，即 Y 轴指向重力方向
        # 手机平放时 mz = +1g（Z 朝上），所以 DSU 的 Y 取 -mz。
        # 再叠加上 DSU 客户端的符号修正：RotY 取反、AccX 取反、AccZ 取反，
        # 否则会出现偏航镜像、保持倾斜时角度缓慢回爬。
        ax = -mx                    # AccX 取反
        ay = -mz                    # 重力 -> Y 轴，平放得 -1g
        az = -my                    # AccZ 取反（原 Y 轴）

        gp = mgx                    # RotX = 绕 X
        gy = mgz                    # RotY = 绕 Z 经取反
        gr = mgy                    # RotZ = 绕 Y

        # ── 80 字节 payload（偏移与 Cemuhook/PhoneGyro 一致）──
        #   p[0]      slot
        #   p[1]      slot_state      2 = 已连接
        #   p[2]      model           2 = 完整陀螺仪手柄
        #   p[3]      conn_type       2 = 蓝牙/无线
        #   p[4:10]   mac
        #   p[10]     battery
        #   p[11]     is_active       1
        #   p[12:16]  packet_number
        #   p[20:24]  四根摇杆轴（128 = 中位）
        #   p[48:56]  timestamp u64 微秒   ← 客户端按此差值积分角速度
        #   p[56:68]  加速度 float32×3   单位 g
        #   p[68:80]  角速度 float32×3   单位 deg/s
        p = bytearray(80)
        p[0] = self.SLOT_INDEX
        p[1] = self.SLOT_STATE_CONNECTED
        p[2] = 2                      # model = 完整陀螺仪手柄
        p[3] = 2                      # conn_type = 无线
        p[10] = 5                     # battery = 满电
        p[11] = 1                     # is_active
        struct.pack_into("<I", p, 12, self._packet_no)
        p[20] = 128                   # 左摇杆 X（按键/摇杆走 DS4，这里保持中位）
        p[21] = 128
        p[22] = 128
        p[23] = 128
        struct.pack_into("<Q", p, 48, ts_us)
        struct.pack_into("<fff", p, 56, ax, ay, az)     # 加速度（g）
        struct.pack_into("<fff", p, 68, gp, gy, gr)     # 角速度（deg/s）

        return dsu_build(self._server_id, DSUS_MSG_DATA, bytes(p))

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

def axis_to_ds4(v: float) -> int:
    """[-1,1] → [0,255]，中心 128"""
    v = max(-1.0, min(1.0, v))
    return int(round((v + 1.0) * 127.5))


def build_report(s: dict, swap_abxy: bool = True) -> DS4_REPORT:
    """
    手机按键 → DS4 报告

    与 Yuzu 的映射关系（Pro Controller 布局）：
      Switch A(右) = DS4 Circle，Switch B(下) = DS4 Cross
      Switch X(上) = DS4 Triangle，Switch Y(左) = DS4 Square

    swap_abxy=True 时做交叉，让"手机 A"落在 Switch 的 A 上。
    """
    b = s["buttons"]
    wb = 0

    # ── ABXY 映射 ──
    if swap_abxy:
        # 手机 A → Circle(右)，B → Cross(下)，X → Triangle(上)，Y → Square(左)
        if b & B_A:
            wb |= DS4_CIRCLE
        if b & B_B:
            wb |= DS4_CROSS
        if b & B_X:
            wb |= DS4_TRIANGLE
        if b & B_Y:
            wb |= DS4_SQUARE
    else:
        if b & B_A:
            wb |= DS4_CROSS
        if b & B_B:
            wb |= DS4_CIRCLE
        if b & B_X:
            wb |= DS4_SQUARE
        if b & B_Y:
            wb |= DS4_TRIANGLE

    # ── 肩键 / 扳机数字位 ──
    if b & B_LB:
        wb |= DS4_L1
    if b & B_RB:
        wb |= DS4_R1
    if b & B_LT:
        wb |= DS4_L2
    if b & B_RT:
        wb |= DS4_R2

    # ── 摇杆下压 ──
    if b & B_L3:
        wb |= DS4_L3
    if b & B_R3:
        wb |= DS4_R3

    # ── VIEW → SHARE（Switch Minus），MENU → OPTIONS（Switch Plus）──
    if b & B_VIEW:
        wb |= DS4_SHARE
    if b & B_MENU:
        wb |= DS4_OPTIONS

    # ── D-Pad：低 4 位 HAT 编码 ──
    up = bool(b & B_UP)
    down = bool(b & B_DOWN)
    left = bool(b & B_LEFT)
    right = bool(b & B_RIGHT)
    if up and right:
        hat = DS4_DPAD_NE
    elif down and right:
        hat = DS4_DPAD_SE
    elif down and left:
        hat = DS4_DPAD_SW
    elif up and left:
        hat = DS4_DPAD_NW
    elif up:
        hat = DS4_DPAD_N
    elif down:
        hat = DS4_DPAD_S
    elif left:
        hat = DS4_DPAD_W
    elif right:
        hat = DS4_DPAD_E
    else:
        hat = DS4_DPAD_NONE
    wb = (wb & ~DS4_DPAD_MASK) | (hat & DS4_DPAD_MASK)

    rep = DS4_REPORT()
    rep.wButtons = wb
    rep.bSpecial = 0
    # 扳机是模拟量 0..255
    rep.bTriggerL = int(max(0.0, min(1.0, s["lt"])) * 255)
    rep.bTriggerR = int(max(0.0, min(1.0, s["rt"])) * 255)
    rep.bThumbLX = axis_to_ds4(s["lx"])
    rep.bThumbLY = axis_to_ds4(-s["ly"])   # DS4 的 Y 轴向下为正
    rep.bThumbRX = axis_to_ds4(s["rx"])
    rep.bThumbRY = axis_to_ds4(-s["ry"])
    return rep


def pad_loop(gamepad: VirtualDS4, state: SharedState, stop: threading.Event,
             swap_abxy: bool = True):
    """60Hz 推送虚拟手柄状态"""
    frame = 1.0 / 60.0
    next_t = time.monotonic()
    errors = 0
    frames = 0
    try:
        # ── 启动抖动 ──
        # 先发几帧明显不同的报告，让 SDL/系统立刻感知到设备活动
        for jiggle in (
            (DS4_CROSS, 255, 255, 0, 0),      # A + 摇杆打到一边
            (0, 0, 0, 255, 255),              # 反向
            (0, 128, 128, 128, 128),          # 回中
        ):
            r = DS4_REPORT()
            r.wButtons = jiggle[0]
            r.bSpecial = 0
            r.bTriggerL = 0
            r.bTriggerR = 0
            r.bThumbLX = jiggle[1]
            r.bThumbLY = jiggle[2]
            r.bThumbRX = jiggle[3]
            r.bThumbRY = jiggle[4]
            for _ in range(5):
                gamepad.update(r)
                time.sleep(0.02)
        print("[PAD] 已发送启动抖动", flush=True)

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
                    f"btn=0x{rep.wButtons:04X} LT={rep.bTriggerL} RT={rep.bTriggerR} "
                    f"L=({rep.bThumbLX},{rep.bThumbLY}) R=({rep.bThumbRX},{rep.bThumbRY}) ret=0x{err:08X}",
                    flush=True,
                )
            if err != VIGEM_ERROR_NONE:
                errors += 1
                if errors == 1:
                    print(f"[PAD] 更新失败: {VirtualDS4._err_text(err)}", flush=True)
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
    print("  · 虚拟 DualShock 4 手柄（按键/摇杆）")
    print("  · DSU 体感（陀螺仪/加速度计）")
    print("=" * 62)

    # ── 环境检查 ──
    vigem_ok = check_vigem_service()
    print(f"[检查] ViGEmBus 服务: {'运行中 ✓' if vigem_ok else '未运行 ✗'}")
    if not vigem_ok:
        print("       → 请先安装 ViGEmBus 驱动（安装包随 vgamepad 提供）")

    try:
        gamepad = VirtualDS4()
        print("[检查] 虚拟 DualShock 4 手柄: 创建成功 ✓")
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