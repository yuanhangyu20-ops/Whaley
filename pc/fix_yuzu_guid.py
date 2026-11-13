#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_yuzu_guid.py — 自动把 Yuzu 的控制器绑定同步到 ViGEm 虚拟手柄

问题背景
────────
Yuzu 的按键绑定记录的是 SDL 设备 GUID。如果之前用实体手柄配过，
或者虚拟手柄被重建过，GUID 就可能对不上 —— 表现为"手柄在 Windows
里正常，但游戏里按什么都没有反应"。

本脚本会：
  1. 用 SDL2 枚举当前所有手柄及其 GUID
  2. 找出 ViGEm 虚拟 Xbox 360 手柄的 GUID
  3. 改写 Yuzu 配置里 player_N_* 的 guid:... 字段
  4. 自动备份原配置

用法
────
    python fix_yuzu_guid.py --check      # 只对比，不修改
    python fix_yuzu_guid.py              # 检测并修复
    python fix_yuzu_guid.py --yuzu "D:\\Apps\\YUZU(EA)"
"""

from __future__ import annotations

import argparse
import ctypes
import os
import re
import shutil
import sys
import time

VIGEM_DEVICES = {
    # (vendor, product): 说明
    (0x045E, 0x028E): "Xbox 360 Controller",
    (0x054C, 0x05C4): "DualShock 4 (ViGEm)",
    (0x054C, 0x09CC): "DualShock 4 v2 (ViGEm)",
}


class SDL_GUID(ctypes.Structure):
    _fields_ = [("data", ctypes.c_ubyte * 16)]


def load_sdl(yuzu_dir: str):
    """加载 Yuzu 自带的 SDL2.dll"""
    for name in ("SDL2.dll", os.path.join("yuzu", "SDL2.dll")):
        p = os.path.join(yuzu_dir, name)
        if os.path.isfile(p):
            return ctypes.CDLL(p), p
    raise FileNotFoundError(f"在 {yuzu_dir} 找不到 SDL2.dll")


def enumerate_gamepads(sdl) -> list[dict]:
    """返回 [{'index':n, 'name':str, 'guid':hex}]"""
    sdl.SDL_Init.argtypes = [ctypes.c_uint32]
    sdl.SDL_Init.restype = ctypes.c_int
    sdl.SDL_NumJoysticks.restype = ctypes.c_int
    sdl.SDL_JoystickNameForIndex.argtypes = [ctypes.c_int]
    sdl.SDL_JoystickNameForIndex.restype = ctypes.c_char_p
    sdl.SDL_JoystickGetDeviceGUID.argtypes = [ctypes.c_int]
    sdl.SDL_JoystickGetDeviceGUID.restype = SDL_GUID

    SDL_INIT_GAMECONTROLLER = 0x00002000
    if sdl.SDL_Init(SDL_INIT_GAMECONTROLLER) != 0:
        raise RuntimeError("SDL_Init 失败")

    result = []
    for i in range(sdl.SDL_NumJoysticks()):
        nm = sdl.SDL_JoystickNameForIndex(i)
        raw = sdl.SDL_JoystickGetDeviceGUID(i)
        guid = "".join(f"{b:02x}" for b in raw.data)
        result.append({
            "index": i,
            "name": nm.decode("utf-8", "replace") if nm else "(unknown)",
            "guid": guid,
        })
    return result


def vigem_kind(guid: str) -> str | None:
    """
    判断这个 SDL GUID 是不是 ViGEm 虚拟设备，返回设备名或 None。

    SDL GUID 布局（16 字节）：
      0-1  bus        2-3  crc
      4-5  vendor     6-7  0
      8-9  product   10-11 0
      12-15 版本/其它
    """
    if len(guid) != 32:
        return None
    try:
        vendor = int.from_bytes(bytes.fromhex(guid[8:12]), "little") & 0xFFFF
        product = int.from_bytes(bytes.fromhex(guid[16:20]), "little") & 0xFFFF
    except ValueError:
        return None
    return VIGEM_DEVICES.get((vendor, product))


def find_config(yuzu_dir: str) -> str:
    for rel in (os.path.join("user", "config", "qt-config.ini"), "qt-config.ini"):
        p = os.path.join(yuzu_dir, rel)
        if os.path.isfile(p):
            return p
    raise FileNotFoundError(f"在 {yuzu_dir} 找不到 qt-config.ini")


GUID_RE = re.compile(r"guid:([0-9a-fA-F]{32})")


def main() -> int:
    ap = argparse.ArgumentParser(description="同步 Yuzu 控制器绑定到 ViGEm 虚拟手柄")
    ap.add_argument("--yuzu", default=r"D:\Apps\YUZU(EA)", help="Yuzu 安装目录")
    ap.add_argument("--check", action="store_true", help="只检查不修改")
    args = ap.parse_args()

    print("=" * 60)
    print("  Yuzu 控制器 GUID 同步工具")
    print("=" * 60)

    # ── 1. 枚举 SDL 手柄 ──
    try:
        sdl, dll_path = load_sdl(args.yuzu)
        print(f"\n[1] 已加载 {dll_path}")
        pads = enumerate_gamepads(sdl)
    except Exception as e:
        print(f"\n[1] 失败: {e}")
        return 1

    if not pads:
        print("    ✗ SDL 没有检测到任何手柄")
        print("      → 确认桥接（Yuzu_Bridge.py）正在运行")
        return 1

    print(f"    检测到 {len(pads)} 个手柄:")
    target_guid = None
    for p in pads:
        mark = ""
        kind = vigem_kind(p["guid"])
        if kind:
            target_guid = p["guid"]
            mark = f"   ← ViGEm 虚拟设备 ({kind})"
        print(f"      [{p['index']}] {p['name']}")
        print(f"           GUID = {p['guid']}{mark}")

    if not target_guid:
        print("\n    ✗ 没有找到 ViGEm 虚拟手柄")
        print("      → 确认 Yuzu_Bridge.py 正在运行且创建成功")
        return 1

    print(f"\n    目标 GUID = {target_guid}")

    # ── 2. 读取配置 ──
    try:
        cfg = find_config(args.yuzu)
        print(f"\n[2] 配置文件: {cfg}")
        text = open(cfg, encoding="utf-8", errors="replace").read()
    except Exception as e:
        print(f"\n[2] 失败: {e}")
        return 1

    # ── 3. 对比 ──
    guids_in_cfg = set(GUID_RE.findall(text))
    # 排除 cemuhook 的伪装 GUID（127.0.0.1 的十六进制）
    guids_in_cfg.discard("0000000000000000000000007f000001")
    print(f"    配置里使用的设备 GUID: {guids_in_cfg or '(无)'}")

    if guids_in_cfg == {target_guid}:
        print("\n    ✓ 配置已经正确，无需修改")
        return 0

    if args.check:
        print(f"\n    ✗ 需要修复：配置用的是 {guids_in_cfg}，实际设备是 {target_guid}")
        print("      去掉 --check 重新运行即可修复")
        return 2

    # ── 4. 修复 ──
    backup = f"{cfg}.bak_{time.strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(cfg, backup)
    print(f"\n[3] 已备份到 {os.path.basename(backup)}")

    count = 0
    for old in guids_in_cfg:
        n = text.count(old)
        text = text.replace(old, target_guid)
        count += n
        print(f"    替换 {old} → {target_guid}  ({n} 处)")

    open(cfg, "w", encoding="utf-8", newline="\n").write(text)
    print(f"\n    ✓ 完成，共替换 {count} 处")
    print("\n    下一步：重启 Yuzu（配置只在启动时加载）")
    return 0


if __name__ == "__main__":
    sys.exit(main())