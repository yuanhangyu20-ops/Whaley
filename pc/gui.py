# -*- coding: utf-8 -*-
"""
鲸小游桥接 · 图形界面

用 tkinter（Python 标准库，无需额外依赖）做一个轻量的控制面板：
显示连接状态、局域网 IP、实时体感数据、运行日志。

设计原则
────────
· 深色界面，配色取自鲸鱼图标的蓝色，和手机端风格一致
· 一眼能看出「手机连没连上」「Yuzu 订阅没」「是不是在推送」
· 出错时给明确的中文提示，而不是抛一堆英文堆栈
"""
from __future__ import annotations

import os
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import font as tkfont
from tkinter import messagebox

# 背景 / 前景配色（鲸鱼蓝）
BG        = "#0F1720"
CARD_BG   = "#1A2430"
CARD_EDGE = "#243244"
FG        = "#E8F1FA"
FG_DIM    = "#8BA0B8"
ACCENT    = "#1E94FD"
ACCENT_DK = "#0B6FD0"
OK_COLOR  = "#3DDC84"
WARN      = "#FFB020"
ERR       = "#FF5C5C"


class _QueueWriter:
    """把 write() 的内容塞进队列，由 GUI 线程消费（线程安全）"""

    def __init__(self, q, mirror=None):
        self.q = q
        self.mirror = mirror

    def write(self, s):
        if not s:
            return 0
        try:
            self.q.put(s)
        except Exception:
            pass
        # 打包成 exe 时 mirror 可能是 None（无控制台）
        if self.mirror is not None:
            try:
                self.mirror.write(s)
                self.mirror.flush()
            except Exception:
                pass
        return len(s)

    def flush(self):
        if self.mirror is not None:
            try:
                self.mirror.flush()
            except Exception:
                pass


class BridgeGUI:
    """主窗口"""

    REFRESH_MS = 500          # 状态刷新间隔
    LOG_MAX_LINES = 500       # 日志区最多保留行数

    def __init__(self, service, title=None):
        if title is None:
            try:
                from Yuzu_Bridge import __version__
                title = f"鲸小游 · 手柄桥接  v{__version__}"
            except Exception:
                title = "鲸小游 · 手柄桥接"
        self.svc = service
        self.log_queue = queue.Queue()
        self._build(title)
        self._pump_log()
        self._tick()

    # ---------------------------------------------------------------- UI
    def _build(self, title):
        self.root = tk.Tk()
        self.root.title(title)
        self.root.configure(bg=BG)
        self.root.geometry("660x820")
        self.root.minsize(600, 720)

        # 窗口图标（打包后从临时目录读）
        try:
            base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
            icon = os.path.join(base, "app_icon.png")
            if os.path.isfile(icon):
                self._icon_img = tk.PhotoImage(file=icon)
                self.root.iconphoto(True, self._icon_img)
        except Exception:
            pass

        f_title = tkfont.Font(family="Microsoft YaHei UI", size=17, weight="bold")
        f_sub   = tkfont.Font(family="Microsoft YaHei UI", size=9)
        f_body  = tkfont.Font(family="Microsoft YaHei UI", size=10)
        f_mono  = tkfont.Font(family="Consolas", size=9)
        f_num   = tkfont.Font(family="Consolas", size=15, weight="bold")

        # ── 顶部标题栏 ──
        head = tk.Frame(self.root, bg=BG)
        head.pack(fill="x", padx=18, pady=(16, 4))
        tk.Label(head, text="鲸小游", font=f_title, bg=BG, fg=FG).pack(side="left")
        tk.Label(head, text="  把手机变成全能体感手柄", font=f_sub,
                 bg=BG, fg=FG_DIM).pack(side="left", pady=(6, 0))

        # ── 状态灯 ──
        stat = tk.Frame(self.root, bg=BG)
        stat.pack(fill="x", padx=18, pady=(2, 10))
        self.lamp = tk.Canvas(stat, width=10, height=10, bg=BG,
                              highlightthickness=0)
        self.lamp.pack(side="left", pady=(2, 0))
        self.lamp_id = self.lamp.create_oval(1, 1, 9, 9, fill=WARN, outline="")
        self.status_lbl = tk.Label(stat, text="正在启动…", font=f_body,
                                   bg=BG, fg=FG_DIM)
        self.status_lbl.pack(side="left", padx=(8, 0))

        # ── IP 卡片 ──
        ipcard = self._card(self.root)
        ipcard.pack(fill="x", padx=18, pady=(0, 12))
        inner = tk.Frame(ipcard, bg=CARD_BG)
        inner.pack(fill="x", padx=16, pady=14)

        tk.Label(inner, text="手机端要填的 IP", font=f_sub,
                 bg=CARD_BG, fg=FG_DIM).pack(anchor="w")
        row = tk.Frame(inner, bg=CARD_BG)
        row.pack(fill="x", pady=(4, 0))
        self.ip_lbl = tk.Label(row, text="检测中…", font=f_num,
                               bg=CARD_BG, fg=ACCENT)
        self.ip_lbl.pack(side="left")

        self.copy_btn = tk.Button(
            row, text="复制", font=f_sub, bg=CARD_EDGE, fg=FG,
            activebackground=ACCENT_DK, activeforeground="white",
            relief="flat", bd=0, padx=14, pady=4, cursor="hand2",
            command=self._copy_ip,
        )
        self.copy_btn.pack(side="left", padx=(14, 0))

        tk.Label(inner, text="或在手机上点「自动搜索电脑」，无需手输",
                 font=f_sub, bg=CARD_BG, fg=FG_DIM).pack(anchor="w", pady=(6, 0))

        # ── 指标网格 ──
        grid = tk.Frame(self.root, bg=BG)
        grid.pack(fill="x", padx=18, pady=(0, 12))
        for c in range(3):
            grid.columnconfigure(c, weight=1, uniform="m")

        self.m_phone = self._metric(grid, 0, 0, "手机", "离线")
        self.m_dsu   = self._metric(grid, 0, 1, "DSU 客户端", "0")
        self.m_push  = self._metric(grid, 0, 2, "已推送", "0")
        self.m_mode  = self._metric(grid, 1, 0, "模式", "—")
        self.m_motion= self._metric(grid, 1, 1, "体感", "—")
        self.m_anchor= self._metric(grid, 1, 2, "锚定误差", "—")

        # ── 日志 ──
        logcard = self._card(self.root)
        logcard.pack(fill="both", expand=True, padx=18, pady=(0, 12))
        tk.Label(logcard, text="运行日志", font=f_sub, bg=CARD_BG, fg=FG_DIM)\
            .pack(anchor="w", padx=16, pady=(12, 4))

        holder = tk.Frame(logcard, bg=CARD_BG)
        holder.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.log = tk.Text(holder, height=11, font=f_mono, bg="#0B1219", fg=FG_DIM,
                           relief="flat", bd=0, wrap="word",
                           insertbackground=FG, padx=10, pady=8)
        self.log.pack(side="left", fill="both", expand=True)
        sb = tk.Scrollbar(holder, command=self.log.yview, width=10,
                          bg=CARD_BG, troughcolor=CARD_BG, bd=0,
                          relief="flat", highlightthickness=0)
        sb.pack(side="right", fill="y")
        self.log.configure(yscrollcommand=sb.set, state="disabled")

        # ── 底部按钮 ──
        foot = tk.Frame(self.root, bg=BG)
        foot.pack(fill="x", padx=18, pady=(0, 16))

        self.toggle_btn = tk.Button(
            foot, text="停止桥接", font=f_body,
            bg=CARD_EDGE, fg=FG, activebackground=ACCENT_DK,
            activeforeground="white", relief="flat", bd=0,
            padx=22, pady=8, cursor="hand2", command=self._toggle,
        )
        self.toggle_btn.pack(side="left")

        tk.Button(
            foot, text="打开日志文件", font=f_sub,
            bg=CARD_EDGE, fg=FG_DIM, activebackground=ACCENT_DK,
            activeforeground="white", relief="flat", bd=0,
            padx=16, pady=8, cursor="hand2", command=self._open_log,
        ).pack(side="left", padx=(10, 0))

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _card(self, parent):
        f = tk.Frame(parent, bg=CARD_BG, highlightbackground=CARD_EDGE,
                     highlightthickness=1)
        return f

    def _metric(self, parent, row, col, label, value):
        card = tk.Frame(parent, bg=CARD_BG, highlightbackground=CARD_EDGE,
                        highlightthickness=1)
        card.grid(row=row, column=col, sticky="nsew",
                  padx=(0 if col == 0 else 6, 0), pady=3)
        inner = tk.Frame(card, bg=CARD_BG)
        inner.pack(fill="x", padx=12, pady=10)
        tk.Label(inner, text=label, font=("Microsoft YaHei UI", 8),
                 bg=CARD_BG, fg=FG_DIM).pack(anchor="w")
        val = tk.Label(inner, text=value, font=("Consolas", 13, "bold"),
                       bg=CARD_BG, fg=FG)
        val.pack(anchor="w", pady=(2, 0))
        return val

    # ------------------------------------------------------------ actions
    def _copy_ip(self):
        text = self.ip_lbl.cget("text")
        if text and text != "检测中…" and not text.startswith("("):
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.copy_btn.configure(text="已复制 ✓", bg=OK_COLOR, fg="#06210F")
            self.root.after(1400, lambda: self.copy_btn.configure(
                text="复制", bg=CARD_EDGE, fg=FG))

    def _open_log(self):
        try:
            from Yuzu_Bridge import LOG_PATH
            if os.path.isfile(LOG_PATH):
                os.startfile(LOG_PATH)
            else:
                messagebox.showinfo("提示", "日志文件尚未生成")
        except Exception as e:
            messagebox.showerror("无法打开", str(e))

    def _toggle(self):
        if self.svc.running:
            self.svc.stop()
            self.log_write("桥接已停止。\n")
            self.toggle_btn.configure(text="启动桥接")
            self.status_lbl.configure(text="已停止")
            self.lamp.itemconfigure(self.lamp_id, fill=WARN)
        else:
            self.toggle_btn.configure(text="停止桥接")
            self.status_lbl.configure(text="正在启动…")
            self._start_service_async()

    def _start_service_async(self):
        def work():
            ok = self.svc.start()
            if not ok:
                self.log_queue.put(f"[错误] 启动失败: {self.svc.error}\n")
        threading.Thread(target=work, daemon=True).start()

    # -------------------------------------------------------------- log
    def log_write(self, text: str):
        self.log.configure(state="normal")
        self.log.insert("end", text)
        # 限制行数，避免长时间运行内存膨胀
        lines = int(self.log.index("end-1c").split(".")[0])
        if lines > self.LOG_MAX_LINES:
            self.log.delete("1.0", f"{lines - self.LOG_MAX_LINES}.0")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _pump_log(self):
        try:
            while True:
                self.log_write(self.log_queue.get_nowait())
        except queue.Empty:
            pass
        self.root.after(120, self._pump_log)

    # ------------------------------------------------------------- tick
    def _tick(self):
        try:
            self._refresh()
        except Exception:
            pass
        self.root.after(self.REFRESH_MS, self._tick)

    def _refresh(self):
        st = self.svc.snapshot()

        if not st.get("running"):
            self.lamp.itemconfigure(self.lamp_id, fill=WARN)
            self.status_lbl.configure(text="已停止", fg=FG_DIM)
            self.toggle_btn.configure(text="启动桥接")
            return

        # 运行中：按钮应显示「停止桥接」（原来只有停止分支会改文字，
        # 导致启动后按钮仍显示「启动桥接」）
        if self.toggle_btn.cget("text") != "停止桥接":
            self.toggle_btn.configure(text="停止桥接")

        online = st["online"]
        clients = st["dsu_clients"]

        # 状态灯：手机在线且 Yuzu 已订阅 = 绿色；部分就绪 = 黄色；都没有 = 红
        if online and clients > 0:
            self.lamp.itemconfigure(self.lamp_id, fill=OK_COLOR)
            self.status_lbl.configure(
                text=f"一切就绪 · Yuzu 已连接 · 手机 {st['pps']} pps", fg=OK_COLOR)
        elif online:
            self.lamp.itemconfigure(self.lamp_id, fill=WARN)
            self.status_lbl.configure(
                text="手机已连接，等待 Yuzu 打开控制设置以订阅体感", fg=WARN)
        else:
            self.lamp.itemconfigure(self.lamp_id, fill=ERR)
            self.status_lbl.configure(
                text="等待手机连接…（在手机上点「开始连接」）", fg=FG_DIM)

        # IP
        try:
            from Yuzu_Bridge import get_all_lan_ips
            ips = get_all_lan_ips()
            self.ip_lbl.configure(
                text=f"{ips[0]}  :{st['port']}" if ips else "(未检测到)")
        except Exception:
            pass

        # 指标
        self.m_phone.configure(text=f"{'在线' if online else '离线'}",
                               fg=OK_COLOR if online else FG_DIM)
        self.m_dsu.configure(text=str(clients),
                             fg=OK_COLOR if clients else FG_DIM)
        self.m_push.configure(text=f"{st['dsu_sent']}")
        self.m_mode.configure(text=st["mode"])
        self.m_motion.configure(
            text="开启" if st["motion"] else "关闭",
            fg=OK_COLOR if st["motion"] else FG_DIM)

        if st["has_quat"]:
            self.m_anchor.configure(text=f"{st['err_deg']:.1f}°",
                                   fg=FG)
        else:
            self.m_anchor.configure(text="—", fg=FG_DIM)

    # ------------------------------------------------------------ close
    def _on_close(self):
        try:
            self.svc.stop()
        except Exception:
            pass
        self.root.destroy()

    def run(self):
        self.root.mainloop()