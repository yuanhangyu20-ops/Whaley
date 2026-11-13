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
import math
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

APP_PACKET = struct.Struct("<2sBBIQHBBbbbbhhhhhhffff")   # 52 字节（v3 含四元数）
APP_PACKET_V2 = struct.Struct("<2sBBIQHBBbbbbhhhhhh")     # 36 字节（v2 兼容）
APP_MAGIC = b"WP"
APP_VERSION = 3

# 程序版本（GUI 标题与 --version 使用）
__version__ = "1.3.0"
APP_PACKET_SIZE = APP_PACKET.size
APP_PACKET_SIZE_V2 = APP_PACKET_V2.size

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

# ==================================================================
#  路径处理：兼容「直接运行 .py」与「PyInstaller 单文件 exe」
# ==================================================================
#
# 打包成 exe(--onefile) 后：
#   sys._MEIPASS   = 运行时临时解压目录，ViGEmClient.dll 在这里
#   sys.executable = exe 的实际路径，日志应该写在它旁边
# 若继续用 __file__ 会导致 DLL 找不到、日志写进临时目录后消失。


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_dir() -> str:
    """可执行文件所在目录（日志写这里）"""
    if _is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def resource_dir() -> str:
    """随程序打包的资源目录（DLL 在这里）"""
    if _is_frozen():
        return getattr(sys, "_MEIPASS", app_dir())
    return os.path.dirname(os.path.abspath(__file__))


class VirtualDS4:
    """通过 ViGEmClient.dll 创建并驱动一个虚拟 DualShock 4 手柄"""

    def __init__(self, dll_path: str | None = None):
        if dll_path is None:
            # 先找资源目录（打包后是临时解压目录），再退回 exe 同级
            for base in (resource_dir(), app_dir()):
                cand = os.path.join(base, "ViGEmClient.dll")
                if os.path.isfile(cand):
                    dll_path = cand
                    break
            else:
                dll_path = os.path.join(resource_dir(), "ViGEmClient.dll")
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
        self.qx = 0.0                # 手机相对姿态四元数
        self.qy = 0.0
        self.qz = 0.0
        self.qw = 1.0
        self.has_quat = False        # 手机是否提供姿态

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
            self.qx = pkt.get("qx", 0.0)
            self.qy = pkt.get("qy", 0.0)
            self.qz = pkt.get("qz", 0.0)
            self.qw = pkt.get("qw", 1.0)
            self.has_quat = pkt.get("has_quat", False)
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
                "qx": self.qx, "qy": self.qy,
                "qz": self.qz, "qw": self.qw,
                "has_quat": self.has_quat,
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

# 设备静默多久后改发"心跳帧"（角速度归零）。见 PhoneGyro 的 heartbeatLoop：
# 若继续发送最后一帧的角速度，客户端会把它当成本帧的真实转速持续积分，
# 表现为"手机已经断开，游戏里的视角还在匀速转圈"。
IDLE_AFTER_SEC = 0.25

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


# ══════════════════════════════════════════════════════════════════
#  姿态锚定（Attitude Anchor）
# ══════════════════════════════════════════════════════════════════
#
# 为什么需要它
# ────────────
# DSU 客户端（Yuzu/Cemu）自己用陀螺仪积分姿态。陀螺仪有零偏和标度误差，
# 积分会持续累积：快速挥动时一分钟就能偏 8~16°。重力能慢慢把 pitch/roll
# 拉回来，但**航向(yaw)没有任何参考能修正**，于是越玩越歪，且每次连接
# 的零点不同 → 表现为"平放却是斜的、每次还不一样"。
#
# 做法（思路来自开源项目 PhoneGyro 的 motion/attitudeanchor.go）
# ─────────────────────────────────────────────────────────────
# 1. 维护 est：模拟「客户端按我们发出的角速度积分后会到达的姿态」
# 2. 手机上送相对姿态四元数 q_ref 作为真值参考
# 3. 误差 e = log(conj(est) ⊗ q_ref)，把 2e/dt 的角速度叠加到输出上
# 4. 限幅 20°/s —— 让修正是"缓慢牵引"，不会盖掉真实的快速动作
#
# 结果：客户端积分被持续拉向真实姿态，航向漂移基本消失。


def _q_mul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    )


def _q_conj(q):
    return (-q[0], -q[1], -q[2], q[3])


def _q_norm(q):
    return math.sqrt(q[0] * q[0] + q[1] * q[1] + q[2] * q[2] + q[3] * q[3])


def _q_normalize(q):
    n = _q_norm(q)
    if n < 1e-9:
        return (0.0, 0.0, 0.0, 1.0)
    return (q[0] / n, q[1] / n, q[2] / n, q[3] / n)


def _q_exp(v):
    """旋转向量（轴×角度）→ 四元数"""
    theta = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if theta < 1e-9:
        return (0.0, 0.0, 0.0, 1.0)
    s = math.sin(theta * 0.5) / theta
    return (v[0] * s, v[1] * s, v[2] * s, math.cos(theta * 0.5))


def _q_log(q):
    """四元数 → 旋转向量"""
    q = _q_normalize(q)
    if q[3] < 0.0:          # 取最短路径
        q = (-q[0], -q[1], -q[2], -q[3])
    vn = math.sqrt(q[0] * q[0] + q[1] * q[1] + q[2] * q[2])
    if vn < 1e-9:
        return (0.0, 0.0, 0.0)
    theta = 2.0 * math.atan2(vn, q[3])
    k = theta / vn
    return (q[0] * k, q[1] * k, q[2] * k)


class AttitudeAnchor:
    """用手机姿态真值修正 DSU 客户端的积分漂移"""

    # 增益策略：误差就是"客户端姿态偏离真值多少"。
    #   · 小误差用低增益，避免把传感器噪声放大成抖动
    #   · 大误差（快速甩动后积累的）用高增益，尽快把画面拉回来，
    #     否则用户会感觉"停了要等两三秒才归位"
    # 三档增益：按剩余误差决定拉回力度
    #   大误差（刚甩完）→ 猛拉，0.3 秒归位
    #   中误差        → 快拉
    #   小误差        → 温和，避免把噪声放大成抖动
    GAIN_TIERS = (
        (2.0, 30.0),    # 剩余 > 2°：猛拉
        (0.5, 12.0),    # 剩余 > 0.5°：快拉
        (0.0, 3.0),     # 其余：温和收尾（不抖）
    )
    MAX_CORR = math.radians(180.0)     # 上限 180°/s，允许「几乎立即」归位
    MIN_DT = 1e-4

    def _gain_for(self, err_deg: float) -> float:
        for threshold, gain in self.GAIN_TIERS:
            if err_deg > threshold:
                return gain
        return 2.0

    def __init__(self):
        self.est = (0.0, 0.0, 0.0, 1.0)   # 客户端将达到的姿态
        self.q_ref = None                 # 手机相对姿态
        self.last_t = None
        self.active = False
        self.corr_mag = 0.0
        self.last_q = None               # 当前修正强度（rad/s），供诊断

    def reset(self):
        self.est = (0.0, 0.0, 0.0, 1.0)
        self.last_t = None
        self.active = False
        self.corr_mag = 0.0
        self.last_q = None
        self.last_q = None

    # 四元数突变阈值：超过它说明手机换了基准（用户点了"设正面"或重连）
    Q_JUMP_THRESH = 0.30

    def push_ref(self, q):
        """更新手机姿态参考"""
        if q is None:
            return
        n = _q_norm(q)
        if n < 1e-6:
            return
        q = _q_normalize(q)

        # 检测手机端「重新居中」：q 会瞬间跳回单位四元数附近。
        # 此时把 est 也同步到新基准，画面才会真的回到正前方，
        # 否则锚定会拿旧基准去纠正，方向还是错的。
        if self.last_q is not None:
            d = math.sqrt(sum((q[i] - self.last_q[i]) ** 2 for i in range(4)))
            if d > self.Q_JUMP_THRESH:
                self.est = q
                self.q_ref = q
                self.last_q = q
                self.last_t = None
                print("[锚定] 检测到手机重新居中，基准已同步", flush=True)
                return
        self.last_q = q

        self.q_ref = q
        # 首帧或参考归零时同步 est，避免一上来就产生巨大修正
        if not self.active:
            self.est = self.q_ref
            self.active = True

    def correct(self, gyro_rad, now_t):
        """
        Args:
            gyro_rad: 手机坐标系下的角速度 (rad/s)
        Returns:
            (修正后的角速度, 是否生效)
        """
        if not self.active or self.q_ref is None:
            return gyro_rad, False

        if self.last_t is None:
            self.last_t = now_t
            return gyro_rad, False

        dt = now_t - self.last_t
        self.last_t = now_t
        if dt < self.MIN_DT:
            return gyro_rad, False
        # 间隔过大（丢帧/卡顿）时不做修正，否则会算出一个巨大的角速度
        if dt > 0.1:
            return gyro_rad, False

        # 1. 误差 = log(conj(est) ⊗ q_ref)，est 是上一帧结束时客户端的姿态
        err = _q_log(_q_mul(_q_conj(self.est), self.q_ref))

        # 2. 修正量 = gain * err（rad/s），**不要除以 dt**
        #    除以 dt 会把修正放大 (1/dt) 倍：dt≈8ms 时放大 125 倍，
        #    0.08° 的微小误差就会顶到上限，表现为画面被持续拖着转。
        err_mag = math.sqrt(err[0] ** 2 + err[1] ** 2 + err[2] ** 2)
        gain = self._gain_for(math.degrees(err_mag))
        corr = [gain * e for e in err]
        mag = err_mag * gain
        if mag > self.MAX_CORR:
            k = self.MAX_CORR / mag
            corr = [c * k for c in corr]
            mag = self.MAX_CORR
        self.corr_mag = mag

        out = (gyro_rad[0] + corr[0],
               gyro_rad[1] + corr[1],
               gyro_rad[2] + corr[2])

        # 3. est 必须用**实际发出的**角速度（含修正）推进，
        #    否则它模拟的不是客户端的真实积分，误差会算偏。
        self.est = _q_normalize(
            _q_mul(self.est, _q_exp((out[0] * dt, out[1] * dt, out[2] * dt)))
        )

        return out, True


class DSUServer(threading.Thread):
    """Cemuhook DSU 服务端：响应握手并向 Yuzu 推送体感数据"""

    SLOT_INDEX = 0
    SLOT_STATE_CONNECTED = 2

    def __init__(self, state: SharedState, port: int = 26760, host: str = "0.0.0.0",
                 anchor_enabled: bool = True):
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
        # 姿态锚定：抑制 DSU 客户端的积分漂移（尤其航向 yaw）
        self.anchor = AttitudeAnchor()
        self.anchor_enabled = anchor_enabled
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

        # ── 心跳：手机静默时只维持订阅，不贡献任何旋转 ──
        last_rx = s.get("last_rx_time", 0.0)
        idle = (last_rx <= 0.0) or (now_t - last_rx > IDLE_AFTER_SEC)
        if self._last_push_t is None:
            self._ts_us += 16667          # 16.667ms ≈ 60Hz
        else:
            delta = int((now_t - self._last_push_t) * 1_000_000)
            # 夹在 [100µs, 100ms]：太小的抖动用最小值，长时间停顿也不至于爆掉
            self._ts_us += max(100, min(delta, 100_000))
        self._last_push_t = now_t
        ts_us = self._ts_us & 0xFFFFFFFFFFFFFFFF

        # ── 姿态锚定（在手机坐标系里做，最后才转到 DSU 坐标系）──
        gx_r, gy_r, gz_r = s["gx"], s["gy"], s["gz"]
        anchored = False
        if idle:
            # 心跳帧：角速度清零。加速度保留最后值，让客户端冻结在当前姿态
            # 而不是继续累积旋转；若从未收到过数据则用标准平放值。
            gx_r = gy_r = gz_r = 0.0
            if s["ax"] == 0.0 and s["ay"] == 0.0 and s["az"] == 0.0:
                s = dict(s)
                s["az"] = GRAVITY
        elif self.anchor_enabled and s.get("motion_enabled") and s.get("has_quat"):
            self.anchor.push_ref((s["qx"], s["qy"], s["qz"], s["qw"]))
            (gx_r, gy_r, gz_r), anchored = self.anchor.correct(
                (gx_r, gy_r, gz_r), now_t)
        elif self.anchor.active:
            # 手机停止上报姿态：复位，避免用陈旧参考继续拉扯
            self.anchor.reset()

        # ── 单位换算：m/s² → g，rad/s → deg/s ──
        mx = s["ax"] / GRAVITY      # 手机坐标：X 右
        my = s["ay"] / GRAVITY      #           Y 上
        mz = s["az"] / GRAVITY      #           Z 屏幕外
        mgx = gx_r * RAD2DEG        # 绕 X（前后倾）
        mgy = gy_r * RAD2DEG        # 绕 Y（左右转）
        mgz = gz_r * RAD2DEG        # 绕 Z（屏幕内旋转）

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

            if len(data) < APP_PACKET_SIZE_V2:
                continue
            qx = qy = qz = 0.0
            qw = 1.0
            has_quat = False
            try:
                if len(data) >= APP_PACKET_SIZE:
                    (magic, ver, flags, seq, ts, buttons,
                     lt, rt, lx, ly, rx, ry,
                     gx, gy, gz, ax, ay, az,
                     qx, qy, qz, qw) = APP_PACKET.unpack_from(data)
                    has_quat = True
                else:
                    (magic, ver, flags, seq, ts, buttons,
                     lt, rt, lx, ly, rx, ry,
                     gx, gy, gz, ax, ay, az) = APP_PACKET_V2.unpack_from(data)
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
                "qx": qx, "qy": qy, "qz": qz, "qw": qw,
                "has_quat": has_quat and motion_on,
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

# ══════════════════════════════════════════════════════════════════
#  自动发现：让手机不用手输 IP
# ══════════════════════════════════════════════════════════════════
#
# 手机在局域网里广播 WIFIPAD_DISCOVER，本服务应答 WIFIPAD_HERE|ip|port，
# 手机就能自动填好地址直接连。端口与手柄数据端口分开，互不干扰。

DISCOVERY_PORT = 9999
DISCOVERY_REQ = b"WIFIPAD_DISCOVER"
DISCOVERY_RSP = b"WIFIPAD_HERE"


def get_lan_ip() -> str:
    """
    取本机在局域网中的 IP。

    不需要真的联网：连一个外部地址只是让内核选出「默认路由使用的网卡」，
    UDP connect 不会发包，即使断网也能立刻返回。
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def get_all_lan_ips() -> list:
    """列出所有可能的局域网 IPv4（多网卡时给用户参考）"""
    ips = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips and not ip.startswith("127."):
                ips.append(ip)
    except Exception:
        pass
    # 把默认路由网卡的 IP 提到最前面（VPN/虚拟网卡常有多个地址）
    primary = get_lan_ip()
    if primary and not primary.startswith("127."):
        if primary in ips:
            ips.remove(primary)
        ips.insert(0, primary)
    return ips


class DiscoveryResponder(threading.Thread):
    """监听广播请求，回复本机的桥接地址"""

    def __init__(self, data_port: int, host: str = ""):
        super().__init__(daemon=True, name="DiscoveryResponder")
        self.data_port = data_port
        self.host = host
        self._stop = threading.Event()
        self._sock = None
        self.requests = 0

    def run(self):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            # 允许接收广播
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.bind(("", DISCOVERY_PORT))
            sock.settimeout(1.0)
            self._sock = sock
        except Exception as e:
            print(f"[发现] 启动失败（不影响手动连接）: {e}", flush=True)
            return

        while not self._stop.is_set():
            try:
                data, addr = sock.recvfrom(256)
            except socket.timeout:
                continue
            except OSError:
                time.sleep(0.2)
                continue

            if not data.startswith(DISCOVERY_REQ):
                continue

            self.requests += 1
            ip = get_lan_ip()
            reply = f"{DISCOVERY_RSP.decode()}|{ip}|{self.data_port}".encode()
            try:
                sock.sendto(reply, addr)
                if self.requests <= 5:
                    print(f"[发现] {addr[0]} 请求连接 → 已告知地址 {ip}:{self.data_port}",
                          flush=True)
            except OSError:
                pass

        try:
            sock.close()
        except Exception:
            pass

    def stop(self):
        self._stop.set()


# ══════════════════════════════════════════════════════════════════
#  日志落盘：桥接窗口可能被其它窗口挡住，用户随时可以看 bridge.log
# ══════════════════════════════════════════════════════════════════

LOG_PATH = os.path.join(app_dir(), "bridge.log")


class _Tee:
    """把输出同时写到控制台和文件"""

    def __init__(self, *streams):
        self._streams = streams

    def write(self, data):
        for s in self._streams:
            try:
                s.write(data)
                s.flush()
            except Exception:
                pass

    def flush(self):
        for s in self._streams:
            try:
                s.flush()
            except Exception:
                pass


def _install_log_file():
    try:
        f = open(LOG_PATH, "w", encoding="utf-8", buffering=1)
        sys.stdout = _Tee(sys.__stdout__, f)
        sys.stderr = _Tee(sys.__stderr__, f)
        return f
    except Exception:
        return None


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


# ==================================================================
#  桥接服务封装：把「虚拟手柄 + DSU + 手机接收 + 自动发现」
#  打包成一个可启停的对象，供命令行和图形界面共用。
# ==================================================================


class BridgeService:
    """管理桥接的全部后台组件"""

    def __init__(self, port: int = 12345, dsu_port: int = 26760,
                 bind: str = "0.0.0.0", swap_abxy: bool = True,
                 anchor: bool = True):
        self.port = port
        self.dsu_port = dsu_port
        self.bind = bind
        self.swap_abxy = swap_abxy
        self.anchor_enabled = anchor

        self.state = None
        self.gamepad = None
        self.rx = None
        self.dsu = None
        self.discovery = None

        self._stop = threading.Event()
        self._pad_thread = None
        self.error = None
        self.running = False

    # ---------- 启动 ----------
    def start(self) -> bool:
        """启动全部组件。失败时 self.error 里是原因，返回 False。"""
        # 1. 虚拟手柄（最可能失败的一步，先做）
        try:
            self.gamepad = VirtualDS4()
        except Exception as e:
            self.error = str(e)
            return False

        # 2. 共享状态 + 两个服务线程
        self.state = SharedState()
        self.rx = PhoneReceiver(self.state, port=self.port, host=self.bind)
        self.dsu = DSUServer(self.state, port=self.dsu_port, host=self.bind,
                             anchor_enabled=self.anchor_enabled)
        self.rx.start()
        self.dsu.start()

        # 3. 手柄状态推送线程
        self._pad_thread = threading.Thread(
            target=pad_loop,
            args=(self.gamepad, self.state, self._stop, self.swap_abxy),
            daemon=True, name="PAD",
        )
        self._pad_thread.start()

        # 4. 自动发现（手机点「自动搜索电脑」时应答）
        self.discovery = DiscoveryResponder(self.port)
        self.discovery.start()

        self.running = True
        return True

    # ---------- 停止 ----------
    def stop(self):
        if not self.running:
            return
        self.running = False
        self._stop.set()
        for obj in (self.rx, self.dsu, self.discovery):
            if obj is not None:
                try:
                    obj.stop()
                except Exception:
                    pass
        if self.gamepad is not None:
            try:
                self.gamepad.close()
            except Exception:
                pass

    # ---------- 状态查询（给 GUI 用）----------
    def snapshot(self) -> dict:
        """返回一份易读的状态快照"""
        if self.state is None:
            return {"running": False}

        s = self.state.snapshot()
        now = time.monotonic()
        age = now - s["last_rx_time"] if s["last_rx_time"] else 999.0
        online = age < 2.0

        keys = ",".join(n for bit, n in BTN_NAMES.items() if s["buttons"] & bit) or "-"

        anchor_deg = 0.0
        err_deg = 0.0
        if self.dsu is not None and s.get("has_quat"):
            a = self.dsu.anchor
            anchor_deg = math.degrees(a.corr_mag)
            if a.active and a.q_ref is not None:
                e = _q_log(_q_mul(_q_conj(a.est), a.q_ref))
                err_deg = math.degrees(math.sqrt(sum(x * x for x in e)))

        return {
            "running": self.running,
            "online": online,
            "pps": s["packets"],
            "keys": keys,
            "mode": "Switch" if s.get("switch_mode", True) else "Xbox",
            "motion": bool(s.get("motion_enabled", True)),
            "has_quat": bool(s.get("has_quat")),
            "anchor_deg": anchor_deg,
            "err_deg": err_deg,
            "dsu_clients": self.dsu.client_count if self.dsu else 0,
            "dsu_sent": self.dsu.sent if self.dsu else 0,
            "gyro": (s["gx"], s["gy"], s["gz"]),
            "acc": (s["ax"] / GRAVITY, s["ay"] / GRAVITY, s["az"] / GRAVITY),
            "port": self.port,
            "dsu_port": self.dsu_port,
        }


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
    ap.add_argument("--no-anchor", action="store_true",
                    help="禁用姿态锚定（视角出现异常匀速旋转时使用）")
    args = ap.parse_args()

    _install_log_file()

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

    # 命令行模式复用 BridgeService，保证与 GUI 行为一致
    gamepad.close()          # 刚才只用于环境检查，交给 service 重新创建
    svc = BridgeService(port=args.port, dsu_port=args.dsu_port, bind=args.bind,
                        swap_abxy=not args.no_swap, anchor=not args.no_anchor)
    if not svc.start():
        print(f"\n启动失败: {svc.error}")
        print("无法继续，请先解决驱动问题。")
        return 1
    state = svc.state
    dsu = svc.dsu
    discovery = svc.discovery

    print("\n" + "-" * 62)
    lan_ips = get_all_lan_ips()
    print()
    print("  ┌──────────────────────────────────────────────────────┐")
    print("  │  手机端填写下面这个 IP（端口 %-5d）              │" % args.port)
    print("  └──────────────────────────────────────────────────────┘")
    if lan_ips:
        for i, ip in enumerate(lan_ips):
            mark = "  ← 推荐" if i == 0 else ""
            print(f"      {ip}{mark}")
    else:
        print("      (未检测到局域网 IP，请用 ipconfig 查看)")

    print(f"\n  或者：手机端点「自动搜索电脑」即可，无需手输 IP")

    # 自动发现服务
    discovery = DiscoveryResponder(args.port)
    discovery.start()
    print(f"  [发现] 自动搜索服务已启动 (UDP {DISCOVERY_PORT})")
    print("  Yuzu 中把控制器设为「任意控制器」并启用体感（DSU）")
    print("  ABXY: " + ("交叉 A->B B->A X->Y Y->X" if not args.no_swap else "一一对应"))
    print("  姿态锚定: " + ("关闭" if args.no_anchor else "开启（抑制航向漂移）"))
    print(f"  日志文件: {LOG_PATH}")
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
                anchor_txt = "—"
                quat_txt = "—"
                if s.get("has_quat"):
                    a = dsu.anchor
                    anchor_txt = f"{math.degrees(a.corr_mag):.1f}°/s"
                    # 误差角：est 与 q_ref 的偏离（度）
                    if a.active and a.q_ref is not None:
                        e = _q_log(_q_mul(_q_conj(a.est), a.q_ref))
                        err_deg = math.degrees(math.sqrt(sum(x*x for x in e)))
                    else:
                        err_deg = 0.0
                    quat_txt = (f"q=({s['qx']:+.3f},{s['qy']:+.3f},{s['qz']:+.3f},{s['qw']:+.3f}) "
                                f"误差={err_deg:.1f}°")
                print(
                    f"[状态] 手机{online} {pps:2d}pps  模式={mode} 体感={mot}  "
                    f"姿态={'有' if s.get('has_quat') else '无'} 锚定={anchor_txt}  "
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
                if s.get("has_quat"):
                    print(f"        {quat_txt}")
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


def main_gui() -> int:
    """图形界面模式（默认）。没有 tkinter 时自动退回命令行。"""
    _install_log_file()
    try:
        from gui import BridgeGUI
    except Exception as e:
        print(f"[警告] 无法加载图形界面（{e}），改用命令行模式")
        return main()

    # GUI 里不需要 argparse，用默认值；想改端口就用命令行参数
    port, dsu_port, bind = 12345, 26760, "0.0.0.0"
    swap, anchor = True, True
    argv = sys.argv[1:]
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--port" and i + 1 < len(argv):
            port = int(argv[i + 1]); i += 2
        elif a == "--dsu-port" and i + 1 < len(argv):
            dsu_port = int(argv[i + 1]); i += 2
        elif a == "--no-swap":
            swap = False; i += 1
        elif a == "--no-anchor":
            anchor = False; i += 1
        else:
            i += 1

    svc = BridgeService(port=port, dsu_port=dsu_port, bind=bind,
                        swap_abxy=swap, anchor=anchor)

    # 环境检查：失败也把窗口开起来，让用户看到明确的中文原因
    vigem_ok = check_vigem_service()

    app = BridgeGUI(svc)

    # 把 print/stdout 接到 GUI 日志区（同时保留控制台与文件输出）
    try:
        from gui import _QueueWriter
        _console = sys.stdout if sys.stdout is not None else None
        _redirect = _QueueWriter(app.log_queue, mirror=_console)
        sys.stdout = _redirect
        sys.stderr = _redirect
    except Exception:
        pass

    if not vigem_ok:
        app.log_queue.put(
            "[错误] 未检测到 ViGEmBus 驱动服务。\n"
            "        请先安装：https://github.com/nefarius/ViGEmBus/releases\n"
        )
        app.status_lbl.configure(text="缺少 ViGEmBus 驱动，无法创建虚拟手柄")
        app.lamp.itemconfigure(app.lamp_id, fill="#FF5C5C")
    else:
        app.log_queue.put("[检查] ViGEmBus 服务运行中 ✓\n")
        app._start_service_async()

    app.run()
    return 0


if __name__ == "__main__":
    # --cli / --check 走命令行；其余默认启动图形界面
    argv = sys.argv[1:]
    if "--cli" in argv or "--check" in argv:
        sys.argv = [a for a in sys.argv if a != "--cli"]
        sys.exit(main())
    sys.exit(main_gui())