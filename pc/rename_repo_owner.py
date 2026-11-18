# -*- coding: utf-8 -*-
"""
GitHub 用户名改完后同步本地仓库

用法:
    python pc/rename_repo_owner.py --check          # 只检查
    python pc/rename_repo_owner.py --apply          # 执行替换
    python pc/rename_repo_owner.py --apply --new StarryHaze-ops

做的事:
  1. git remote set-url 换成新用户名
  2. 把 README / 文档里旧用户名的链接全部替换
  3. 打印最终状态，提示下一步 push
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

OLD = "yuanhangyu20-ops"
DEFAULT_NEW = "StarryHaze-ops"
REPO = "WifiPad-Android"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 需要替换链接的文本文件
TEXT_FILES = [
    "README.md",
    os.path.join("pc", "README.md"),
    os.path.join("pc", "YUZU_MOTION_SETUP.md"),
    os.path.join("pc", "requirements.txt"),
    os.path.join("pc", "build_exe.bat"),
]


def run(cmd, cwd=None):
    return subprocess.run(cmd, cwd=cwd or ROOT, capture_output=True, text=True)


def current_remote() -> str:
    r = run(["git", "remote", "get-url", "origin"])
    return r.stdout.strip() if r.returncode == 0 else ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--new", default=DEFAULT_NEW, help=f"新用户名（默认 {DEFAULT_NEW}）")
    ap.add_argument("--old", default=OLD, help="旧用户名")
    ap.add_argument("--apply", action="store_true", help="真正执行修改")
    ap.add_argument("--check", action="store_true", help="只检查")
    args = ap.parse_args()

    if args.old == args.new:
        print("新旧用户名相同，无需修改")
        return 0

    print("=" * 62)
    print(f"  仓库归属迁移: {args.old}  →  {args.new}")
    print("=" * 62)

    # ── 1. remote ──
    url = current_remote()
    print(f"\n[1] 当前 remote\n    {url or '(未设置)'}")
    new_url = f"https://github.com/{args.new}/{REPO}.git"
    print(f"    目标 remote\n    {new_url}")

    # ── 2. 文本引用 ──
    print("\n[2] 需要替换的链接")
    changed_files = []
    for rel in TEXT_FILES:
        path = os.path.join(ROOT, rel)
        if not os.path.isfile(path):
            continue
        try:
            text = open(path, encoding="utf-8").read()
        except Exception:
            continue
        n = text.count(args.old)
        if n:
            print(f"    {rel}: {n} 处")
            changed_files.append((path, rel, text, n))
        else:
            print(f"    {rel}: -")

    if args.check or not args.apply:
        print("\n(未做修改；加 --apply 执行)")
        return 0

    # ── 3. 执行 ──
    print("\n[3] 执行修改")
    if url != new_url:
        r = run(["git", "remote", "set-url", "origin", new_url])
        if r.returncode == 0:
            print("    ✓ remote 已更新")
        else:
            print(f"    ✗ remote 更新失败: {r.stderr.strip()}")
    else:
        print("    · remote 已是目标值")

    total = 0
    for path, rel, text, n in changed_files:
        text = text.replace(args.old, args.new)
        open(path, "w", encoding="utf-8", newline="\n").write(text)
        total += n
        print(f"    ✓ {rel}  替换 {n} 处")

    print(f"\n合计替换 {total} 处")
    print("\n[4] 下一步")
    print("    git add -A")
    print(f'    git commit -m "chore: migrate repo owner to {args.new}"')
    print("    git -c http.proxy=... push")
    print("\n  注意：GitHub 改名后旧链接有 301 重定向，但建议尽快 push 让文档指向新地址。")
    return 0


if __name__ == "__main__":
    sys.exit(main())