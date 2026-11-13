#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_yuzu_motion.py — 把 Yuzu 的体感输入源切换成 Cemuhook (DSU)

问题背景
────────
Yuzu 的「控制 → 体感」有两个输入源：

    sdl       从 SDL 手柄读陀螺仪。ViGEm 的 DS4 虚拟手柄没有陀螺仪
              数据（DS4_REPORT 结构里就没有 gyro 字段），所以选了 sdl
              会永远读不到动作，界面上的体感指示器纹丝不动。
    muhooku   从 Cemuhook / DSU 服务器读，即本项目桥接的 UDP 26760。

Yuzu 默认会选 sdl。在界面里手动改成 muhooku 后体感立刻正常，但配置
文件里的写法是：

    player_0_motionleft="engine:sdl,motion:0,port:0,guid:030000004c05..."
    player_0_motionright="engine:sdl,motion:0,port:0,guid:030000004c05..."

必须改成 cemuhookudp 才会持久化。

用法
────
    # Yuzu 必须先关闭，否则它退出时会覆盖配置
    python fix_yuzu_motion.py --check     # 只检查
    python fix_yuzu_motion.py             # 修复
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import time

# Cemuhook 客户端对 127.0.0.1 的约定写法：
# guid 是 127.0.0.1 的十六进制（7f000001），不是设备 GUID
CEMUHOOK_TEMPLATE = (
    'engine:cemuhookudp,guid:0000000000000000000000007f000001,'
    'port:{port},pad:{slot},motion:0'
)


def find_config(yuzu_dir: str) -> str:
    for rel in (os.path.join("user", "config", "qt-config.ini"), "qt-config.ini"):
        p = os.path.join(yuzu_dir, rel)
        if os.path.isfile(p):
            return p
    raise FileNotFoundError(f"在 {yuzu_dir} 找不到 qt-config.ini")


def yuzu_running() -> bool:
    try:
        import subprocess
        r = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq yuzu.exe", "/NH"],
            capture_output=True, text=True, timeout=5
        )
        return "yuzu.exe" in r.stdout.lower()
    except Exception:
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description="把 Yuzu 体感输入源改成 Cemuhook (DSU)")
    ap.add_argument("--yuzu", default=r"D:\Apps\YUZU(EA)", help="Yuzu 安装目录")
    ap.add_argument("--port", type=int, default=26760, help="DSU 端口")
    ap.add_argument("--slot", type=int, default=0, help="DSU 槽位")
    ap.add_argument("--player", type=int, default=0, help="玩家编号（0 = 玩家1）")
    ap.add_argument("--check", action="store_true", help="只检查不修改")
    args = ap.parse_args()

    print("=" * 62)
    print("  Yuzu 体感输入源检查 / 修复")
    print("=" * 62)

    try:
        cfg = find_config(args.yuzu)
    except FileNotFoundError as e:
        print(f"\n✗ {e}")
        return 1

    text = open(cfg, encoding="utf-8", errors="replace").read()
    print(f"\n配置文件: {cfg}")

    # ── 读取当前两个体感槽位 ──
    keys = [f"player_{args.player}_motionleft",
            f"player_{args.player}_motionright"]
    current = {}
    for k in keys:
        m = re.search(rf'^{re.escape(k)}="([^"]*)"', text, re.M)
        current[k] = m.group(1) if m else None
        eng = (current[k] or "").split(",")[0]
        status = "cemuhookudp ✓" if "cemuhookudp" in (current[k] or "") else \
                 ("sdl ✗（读不到虚拟手柄的陀螺仪）" if "sdl" in (current[k] or "") else "未配置")
        print(f"\n  {k}")
        print(f"    当前: {current[k] or '(缺失)'}")
        print(f"    判定: {status}")

    need_fix = [
        k for k in keys
        if not (current[k] and "cemuhookudp" in current[k])
    ]

    if not need_fix:
        print("\n✓ 体感输入源已经是 Cemuhook，无需修改")
        return 0

    if args.check:
        print(f"\n✗ 需要修复 {len(need_fix)} 项（去掉 --check 运行即可）")
        return 2

    if yuzu_running():
        print("\n✗ Yuzu 正在运行，它退出时会覆盖配置。请先关闭 Yuzu 再运行。")
        return 1

    # ── 备份并修复 ──
    backup = f"{cfg}.bak_motion_{time.strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(cfg, backup)
    print(f"\n已备份: {os.path.basename(backup)}")

    new_value = CEMUHOOK_TEMPLATE.format(port=args.port, slot=args.slot)
    for k in need_fix:
        line = f'{k}="{new_value}"'
        m = re.search(rf'^{re.escape(k)}="[^"]*"', text, re.M)
        if m:
            text = text[:m.start()] + line + text[m.end():]
            print(f"  替换 {k}")
        else:
            text = text.rstrip() + "\n" + line + "\n"
            print(f"  新增 {k}")

    # 顺带确保 motion_enabled 与 udp_input_servers 正确
    if re.search(r'^motion_enabled=', text, re.M):
        text = re.sub(r'^motion_enabled=.*$', 'motion_enabled=true', text, flags=re.M)
    if re.search(r'^udp_input_servers=', text, re.M):
        text = re.sub(r'^udp_input_servers=.*$',
                      f'udp_input_servers=127.0.0.1:{args.port}', text, flags=re.M)

    open(cfg, "w", encoding="utf-8", newline="\n").write(text)

    print(f"\n✓ 已设置为 Cemuhook (127.0.0.1:{args.port}, slot {args.slot})")
    print("  下一步：启动 Yuzu，在 控制 页面确认「体感」显示 muhooku")
    return 0


if __name__ == "__main__":
    sys.exit(main())