# Yuzu_Bridge.py — 使用指南

把手机上的 **WifiPad** App 变成 Yuzu 模拟器可用的手柄（按键 + 摇杆 + **体感**）。

---

## 一、它做了什么

桥接脚本同时扮演两个身份：

| 身份 | 作用 | 端口 |
|---|---|---|
| **虚拟 Xbox 360 手柄** | 用 ViGEmBus 驱动创建，把手机的按键/摇杆映射成 Windows 标准手柄 | — |
| **DSU / Cemuhook 服务端** | 把手机的陀螺仪/加速度计转换成 Yuzu 认识的体感协议 | UDP 26760 |
| **手机数据接收端** | 接收 App 发来的 WP v2 数据包 | UDP 12345 |

数据流：

```
手机 App ──UDP 12345──▶ Yuzu_Bridge ──┬──▶ ViGEmBus 虚拟手柄 ──▶ Yuzu（按键/摇杆）
                                      └──▶ DSU 服务 26760 ──▶ Yuzu（体感）
```

---

## 二、环境准备

### 1. ViGEmBus 驱动（已装好）

本机状态：**已安装并运行**

```powershell
# 检查
sc query ViGEmBus     # 应看到 STATE: 4 RUNNING
```

若未安装（换电脑时），安装包在 `D:\devkit\ViGEmBusSetup_x64.msi`：

```powershell
msiexec /i "D:\devkit\ViGEmBusSetup_x64.msi" /qn /norestart
```

### 2. Python 依赖

**不需要任何第三方库！** 脚本只用标准库 + `ctypes` 直调 `ViGEmClient.dll`。

> 这样设计的原因：vgamepad 在 Python 3.15 上没有预编译包，装不上。
> 本方案绕开了这个坑，任何 Python 3.8+ 都能直接跑。

### 3. 文件清单

```
pc\
├── Yuzu_Bridge.py        # 桥接脚本
└── ViGEmClient.dll       # 必需！ViGEm 客户端库（127 KB）
```

`ViGEmClient.dll` **必须**和脚本放在同一目录。

---

## 三、启动桥接

```powershell
cd D:\devkit\wifipad\pc

# 先检查环境（可选）
python Yuzu_Bridge.py --check

# 启动
python Yuzu_Bridge.py
```

正常输出：

```
[检查] ViGEmBus 服务: 运行中 ✓
[检查] 虚拟 Xbox 360 手柄: 创建成功 ✓
[DSU] 服务端已启动 → udp://0.0.0.0:26760
[RX] 等待手机数据 → udp://0.0.0.0:12345
```

参数：

| 参数 | 默认 | 说明 |
|---|---|---|
| `--port` | 12345 | 手机数据端口 |
| `--dsu-port` | 26760 | DSU 体感端口 |
| `--check` | — | 只检查环境后退出 |

---

## 四、手机端配置

1. 打开 **WifiPad** App
2. 点右上角**齿轮**打开设置抽屉
3. 填入电脑的**局域网 IP**（见下方如何查）
4. 端口填 **12345**
5. 点 **「开始连接」**

桥接窗口出现这行即成功：

```
[RX] 手机已连接 ← 192.168.x.x:xxxxx
```

### 查电脑局域网 IP

```powershell
Get-NetIPAddress -AddressFamily IPv4 |
  Where-Object { $_.IPAddress -notmatch '^(127\.|169\.254)' } |
  Select-Object InterfaceAlias, IPAddress
```

选 **WLAN** 那行的 IP（例如 `10.99.179.83`）。

> ⚠️ **手机必须关掉 VPN / 代理**，否则局域网流量会被路由进隧道，电脑收不到。

---

## 五、Yuzu 配置（关键步骤）

### 1. 打开控制器设置

Yuzu → **模拟(E)** → **设置** → **控制**

### 2. 配置 Player 1（按键/摇杆）

| 项目 | 选择 |
|---|---|
| 输入设备 | **任意控制器 / Pro Controller** |
| 输入方式 | **自动** 或 **SDL** |

点 **「配置」** 后，Yuzu 会自动扫描到 **「Xbox 360 Controller for Windows」** ——
这就是桥接创建的虚拟手柄，直接按提示按键映射即可。

> 如果没识别到，先确认桥接在运行，然后点 **「刷新」**。

### 3. 开启体感（DSU）

在同一设置界面找到 **「体感 / Motion」** 区域：

1. 输入源选 **DSU 客户端（DSU Client）**
2. 服务器地址填 **`127.0.0.1`**
3. 端口填 **`26760`**
4. 点 **「测试」** 或直接进游戏验证

桥接窗口出现这行说明 Yuzu 已订阅：

```
[DSU] Yuzu 已订阅 ← 127.0.0.1:xxxxx
```

之后每 5 秒会看到：

```
[状态] 手机在线 60pps  KEY=-  L=(+0.00,+0.00) R=(+0.00,+0.00)  DSU客户端=1 推送=1200
```

---

## 六、按键映射说明

### 反向映射（重要）

Yuzu 按 **Switch 布局** 识别手柄，所以脚本对 ABXY 做了交换：

| 手机按键 | 虚拟手柄发送 | Yuzu 中表现为 |
|---|---|---|
| **A** | B | Switch **A**（确认） |
| **B** | A | Switch **B**（取消） |
| **X** | Y | Switch **X** |
| **Y** | X | Switch **Y** |

这样你在手机上按 A，Yuzu 里就是"确认"，符合直觉。

### 其余按键（正常映射）

| 手机 | 虚拟手柄 |
|---|---|
| 十字键 | D-Pad |
| LB / RB | Left / Right Shoulder |
| **LT / RT** | **左右扳机（模拟量 0~255，不是按钮）** |
| L3 / R3（摇杆下压） | Left / Right Thumb |
| **VIEW** | **BACK（Switch 的 Minus 键）** |
| **MENU** | **START（Switch 的 Plus 键）** |
| 左摇杆 | 左摇杆 |
| 右摇杆 | 右摇杆（**只由触摸控制，不含体感**） |

> 若想关闭 ABXY 交叉映射，启动时加 `--no-swap`：
> ```powershell
> python Yuzu_Bridge.py --no-swap
> ```

### 体感与右摇杆是分开的

- **右摇杆**：只响应屏幕上的触摸拖拽
- **体感**：只通过 DSU 协议单独发送，不参与摇杆

手机端已确保陀螺仪/加速度数据不叠加进 `rx/ry`，两者互不干扰。

### 体感

手机陀螺仪 → DSU：

| 手机 | DSU 字段 | 单位转换 |
|---|---|---|
| 陀螺仪 rad/s | gyro (deg/s) | × 57.2958 |
| 加速度 m/s² | accel (g) | ÷ 9.80665 |

> **单位换算必须做**：DSU 协议要求加速度以 **g** 为单位、陀螺仪以 **度/秒** 为单位。
> 手机原始数据是 m/s² 和 rad/s，直接发会导致体感异常（幅度差几十倍）。

---

## 七、故障排查

### 手机显示"发送中"但桥接没反应

1. **检查手机 VPN**（最常见原因）
   ```powershell
   # 在手机上确认：设置 → 网络 → VPN 全部关闭
   ```
2. 确认 IP 填对（电脑 WLAN 的 IPv4 地址）
3. Windows 防火墙放行：

   ```powershell
   New-NetFirewallRule -DisplayName "WifiPad UDP 12345" `
     -Direction Inbound -Protocol UDP -LocalPort 12345 -Action Allow
   ```

### Yuzu 找不到虚拟手柄

```powershell
# 确认 XInput 能看到手柄
python Yuzu_Bridge.py --check
```

若 `--check` 通过但 Yuzu 看不到，在 Yuzu 控制器设置里点 **「刷新」**，或重启 Yuzu。

### Yuzu 体感搜不到 DSU 服务器

1. 确认桥接窗口有 `[DSU] 服务端已启动`
2. Yuzu 里 DSU 地址必须是 **`127.0.0.1`**（不是局域网 IP）
3. 端口 `26760`
4. 若仍不行，检查端口占用：

   ```powershell
   netstat -ano | findstr :26760
   ```

### 按键错乱（A 变成 B）

这是**预期行为**——脚本故意交换了 ABXY 以适配 Yuzu 的 Switch 布局（见第六节）。
若你希望不交换，修改 `build_report()` 中的映射分支即可。

### 虚拟手柄创建失败

```
[检查] 虚拟手柄创建失败：连接 ViGEmBus 失败
```

1. 确认服务在跑：`sc query ViGEmBus`
2. 确认 `ViGEmClient.dll` 在脚本同目录
3. 重启电脑（驱动首次安装后有时需要）

---

## 八、性能说明

| 指标 | 值 |
|---|---|
| 手机 → 桥接 | UDP，无握手，典型延迟 < 5ms（局域网） |
| 手柄刷新 | 60 Hz（固定步长，带漂移补偿） |
| DSU 推送 | 60 Hz（仅在有客户端订阅时） |
| CPU 占用 | 单核约 2~3% |

三个线程互不阻塞：

- **RX 线程**：收手机数据，只更新共享状态（加锁时间极短）
- **PAD 线程**：60Hz 推送虚拟手柄
- **DSU 线程**：60Hz 推送体感 + 响应握手

主线程只负责监控和打印状态。

---

## 九、常见问题

**Q: 为什么不用 vgamepad？**
A: Python 3.15 太新，vgamepad 的依赖 `hidapi` 没有预编译包，装不上。
本方案用 ctypes 直接调 `ViGEmClient.dll`，零依赖。

**Q: 手柄和体感能同时用吗？**
A: 能。Yuzu 把虚拟手柄当作"输入设备"（按键/摇杆），DSU 作为独立的"体感源"，
两者互不干扰。

**Q: 关闭桥接后虚拟手柄还在吗？**
A: 不在。脚本退出时会调用 `vigem_target_remove` 移除设备。
若异常退出残留，重启 Yuzu 或重启电脑即可。

**Q: 能同时连多个手机吗？**
A: 当前版本只处理最后连接的手机。多手机需要扩展 slot 逻辑。