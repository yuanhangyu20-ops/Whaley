# 鲸小游 · WifiPad

> **把手机变成全能体感手柄** —— 安卓手机上的 Xbox / Switch 虚拟手柄 + Cemuhook 体感，
> 经局域网直连 PC，驱动 Yuzu、Cemu、Ryujinx、Steam 等平台。

<p align="center">
  <img alt="Android" src="https://img.shields.io/badge/Android-8.0%2B-3DDC84?logo=android&logoColor=white">
  <img alt="Kotlin" src="https://img.shields.io/badge/Kotlin-2.0-7F52FF?logo=kotlin&logoColor=white">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.8%2B-3776AB?logo=python&logoColor=white">
  <img alt="License" src="https://img.shields.io/badge/License-MIT-blue">
</p>

---

## 目录

- [它是什么](#它是什么)
- [核心特性](#核心特性)
- [工作原理](#工作原理)
- [快速开始](#快速开始)
  - [第一步：电脑端](#第一步电脑端)
  - [第二步：手机端](#第二步手机端)
  - [第三步：Yuzu 体感](#第三步yuzu-体感)
- [Steam 全平台适配](#steam-全平台适配)
- [常见问题](#常见问题)
- [项目结构](#项目结构)
- [致谢](#致谢)

---

## 它是什么

一台手机 + 一个 Python 脚本，就能替代一套 Switch Pro 手柄。

- **手机当手柄**：完整的 Xbox 1:1 布局，支持 L3/R3、VIEW/MENU、模拟扳机、十字键
- **真体感**：不是模拟摇杆，而是标准 Cemuhook DSU 协议，塞尔达射箭、神庙体感球都能玩
- **零延迟设计**：手机 120Hz 采样 → PC 120Hz 推送，端到端延迟肉眼难辨
- **不漂移**：自研姿态锚定算法，航向误差长期稳定在 0.2° 以内

---

## 核心特性

| 能力 | 说明 |
|---|---|
| 🎮 **虚拟手柄** | 通过 ViGEm 驱动创建虚拟 DualShock 4，被 XInput / DirectInput / SDL 全部识别 |
| 🌀 **Cemuhook DSU 体感** | 标准 UDP 26760 协议，陀螺仪 + 加速度计 + 姿态四元数 |
| 🔄 **Xbox / Switch 双模式** | 一键切换 ABXY 布局（Switch 模式自动做 A↔B、X↔Y 交叉映射） |
| ⚖️ **姿态锚定** | 用手机姿态真值反向修正客户端积分漂移，解决"越玩越歪" |
| 💓 **心跳保活** | 手机断开后自动发零速帧，画面立即停住而不是继续转圈 |
| 🎯 **一键居中** | 手机摆正后点一下，游戏视角立刻回到正前方 |
| 🌗 **深色 / 浅色主题** | Material Design 3 抽屉式设置面板 |
| 📳 **触觉反馈** | 按键震动，手感接近实体手柄 |
| 🛡️ **老设备兼容** | 无陀螺仪设备自动禁用体感并提示，绝不闪退 |
| 📡 **自动发现** | 手机广播搜索，点一下自动填好电脑 IP，无需手输 |
| 📦 **免安装 exe** | PC 端单文件双击即用，带图形控制面板，不用装 Python |

---

## 工作原理

```
┌─────────────────────────┐         UDP 12345          ┌──────────────────────────┐
│      手机（鲸小游）      │ ─────────────────────────► │   PC 桥接 Yuzu_Bridge.py  │
│                         │   36→52 字节二进制包        │                          │
│  ┌─────────────────┐    │   · 按键 / 摇杆 / 扳机      │  ┌────────────────────┐  │
│  │ 触摸按钮 28 个   │    │   · 陀螺仪 / 加速度计       │  │ ViGEm → 虚拟 DS4    │  │
│  ├─────────────────┤    │   · 相对姿态四元数          │  │  按键 / 摇杆 → 游戏  │  │
│  │ 陀螺仪 + 加速度计│    │                             │  └────────────────────┘  │
│  ├─────────────────┤    │                             │  ┌────────────────────┐  │
│  │ 姿态四元数       │    │                             │  │ DSU Server :26760   │  │
│  └─────────────────┘    │                             │  │  120Hz 推送体感      │  │
└─────────────────────────┘                             │  └─────────┬──────────┘  │
                                                         └────────────┼─────────────┘
                                                                      │
                                                     ┌────────────────┴───────────────┐
                                                     │  Yuzu / Cemu / Steam           │
                                                     │  · 按键走 XInput               │
                                                     │  · 体感走 Cemuhook (muhooku)   │
                                                     └────────────────────────────────┘
```

**两条独立通道**是关键设计：

- **按键 / 摇杆 / 扳机** → 虚拟 DS4 手柄（HID 报告），游戏当作普通手柄
- **体感** → DSU 协议（UDP），模拟器直接读取角速度和重力

> ⚠️ ViGEm 的虚拟 DS4 **没有陀螺仪字段**，所以体感必须走 DSU 通道。
> 这也意味着 Yuzu 里的体感输入源必须选 **muhooku**，不能选 **sdl**（详见下文）。

---

## 快速开始

### 第一步：电脑端

#### 1. 安装 ViGEmBus 驱动（必需）

这是 Windows 上的虚拟手柄驱动，官方下载：

```
https://github.com/nefarius/ViGEmBus/releases
```

下载 `ViGEmBus_Setup_x64.msi` 安装，然后验证：

```powershell
sc query ViGEmBus
# 应显示 STATE : 4  RUNNING
```

#### 2. 启动桥接（两种方式）

**方式 A：免安装 exe（推荐，不用装 Python）**

从 [Releases](https://github.com/yuanhangyu20-ops/WifiPad-Android/releases)
下载 **`JingXiaoYou-Bridge.exe`**（即鲸小游桥接），**双击运行**。

它带一个**图形控制面板**，不需要看命令行：

```
┌────────────────────────────────────┐
│ 🐋 鲸小游 · 手柄桥接  v1.3.0        │
├────────────────────────────────────┤
│ ● 一切就绪 · Yuzu 已连接            │
│                                    │
│ 手机端要填的 IP                     │
│   192.168.1.100 :12345    [复制]   │
│                                    │
│ 手机    DSU客户端   已推送          │
│ 在线       1         12000         │
│ 模式    体感        锚定误差        │
│ Switch   开启        0.2°          │
│                                    │
│ ┌ 运行日志 ──────────────────────┐ │
│ │ [RX] 手机已连接 ← 192.168.1.5  │ │
│ │ [DSU] Yuzu 已订阅              │ │
│ └────────────────────────────────┘ │
│                                    │
│ [停止桥接]  [打开日志文件]          │
└────────────────────────────────────┘
```

界面上的状态灯含义：

| 灯色 | 含义 |
|---|---|
| 🔴 红 | 手机还没连上 |
| 🟡 黄 | 手机已连，但 Yuzu 还没订阅体感（去打开一次 Yuzu 控制设置）|
| 🟢 绿 | 全部就绪，可以玩了 |

> GitHub 上使用英文文件名是为了避免下载时的编码问题；
> 程序界面和窗口标题都是中文的。

单文件、自包含，内置了 `ViGEmClient.dll`，唯一的系统依赖仍是 ViGEmBus 驱动。

**方式 B：从源码运行**

需要 **Python 3.8 或更高**（已在 3.11 / 3.12 / 3.13 / 3.15 上验证）。

本项目**不需要任何第三方库** —— 虚拟手柄通过 `ctypes` 直接调用
`ViGEmClient.dll`，全部代码只用 Python 标准库。

```powershell
cd pc
python Yuzu_Bridge.py
```

> 想自己打包 exe：`pip install pyinstaller` 后运行 `pc\build_exe.bat`。

#### 3. 确认启动成功

看到下面这些就算就绪：

```
[检查] ViGEmBus 服务: 运行中 ✓
[检查] 虚拟 DualShock 4 手柄: 创建成功 ✓
[RX] 等待手机数据 → udp://0.0.0.0:12345
[DSU] 服务端已启动 → udp://0.0.0.0:26760
```

**记住本机局域网 IP**（手机要填）：

```powershell
ipconfig | Select-String "IPv4"
```

> 💡 所有输出同时写入 `pc/bridge.log`，随时可查：
> `Get-Content pc\bridge.log -Tail 20`

**可选参数**：

| 参数 | 说明 |
|---|---|
| `--port 12345` | 手机数据端口，默认 12345 |
| `--dsu-port 26760` | DSU 体感端口，默认 26760 |
| `--no-swap` | 关闭 ABXY 交叉映射 |
| `--no-anchor` | 禁用姿态锚定（画面异常匀速旋转时用） |

---

### 第二步：手机端

#### 1. 安装 APK

从 [Releases](https://github.com/yuanhangyu20-ops/WifiPad-Android/releases) 下载最新的
`jingxiaoyou-v1.0.0.apk` 安装。

#### 2. 连接（两种方式）

**方式一：自动搜索（推荐，零配置）**

1. 手机连上**与电脑相同的 Wi-Fi**
2. 打开**鲸小游**，点右上角 ⚙️ 打开设置抽屉
3. 点 **「自动搜索电脑」**
4. 几秒内自动填入 IP 和端口 → 点 **「开始连接」**

> 原理：手机向局域网广播 `WIFIPAD_DISCOVER`（UDP 9999），
> 电脑端桥接自动应答自己的地址，无需任何手动输入。

**方式二：手动填写**

桥接启动时已经会打印该填的 IP：

```
┌──────────────────────────────────────────┐
│  手机端填写下面这个 IP（端口 12345）      │
└──────────────────────────────────────────┘
    192.168.1.100  ← 推荐
```

把它填进手机的 **电脑 IP** 框，端口保持 `12345`，点「开始连接」。

连接成功后，抽屉里的状态会显示延迟和发包率。

#### 3. Xbox / Switch 模式切换

在设置抽屉里切换，影响 **ABXY 的映射方式**：

| 模式 | 适用场景 | 按键映射 |
|---|---|---|
| **Switch 模式**（默认）| Yuzu 当作 Switch Pro 手柄用 | 交叉映射：手机上的 A 发 B、B 发 A、X 发 Y、Y 发 X |
| **Xbox 模式** | Steam 游戏、PC 原生游戏 | 一一对应 |

> 💡 **为什么需要交叉映射？**
> Switch 的 A 键在右侧、B 键在下方，而 Xbox 的 A 在下方、B 在右侧。
> 手机界面按 Xbox 布局画，当模拟器里选的是 Switch Pro 手柄时，
> 需要把物理位置对应过去，玩起来手感才和屏幕上一致。

#### 4. 体感

- 打开 **体感** 开关（没有陀螺仪的设备会自动禁用并提示"当前设备不支持体感"）
- 手机摆到舒服的姿势后，点 **「把当前姿态设为正面」** 重新居中
- 玩到一半觉得视角歪了，摆正手机再点一次即可

---

### 第三步：Yuzu 体感

这是最容易踩坑的一步，请按顺序操作。

#### 1. 配置 DSU 端口

Yuzu → **模拟 → 设置 → 控制**：

- **体感**：下拉选择 **muhooku**（❗️**不要选 sdl**）
- 点旁边的 **设置**，确认服务器地址为 `127.0.0.1:26760`

> ❗️**关键**：`sdl` 会去读 SDL 手柄的陀螺仪，而虚拟 DS4 根本没有陀螺仪数据，
> 选了 sdl 会永远显示静止、怎么晃都不动。必须是 **muhooku**。

如果界面里改不动，刊关闭 Yuzu 后运行：

```powershell
cd pc
python fix_yuzu_motion.py --check    # 检查当前状态
python fix_yuzu_motion.py            # 修复（Yuzu 必须先关闭）
```

#### 2. 验证连接

桥接窗口 / `bridge.log` 里出现这两行就说明通了：

```
[DSU] Yuzu 已订阅 ← 127.0.0.1:xxxxx
[状态] 手机在线 120pps  姿态=有  锚定=0.0°/s  DSU客户端=1  推送持续增长
```

#### 3. 成功判据

打开 Yuzu 的控制设置页面，中间那个**长方体示意**会跟着手机转：

- 手机**平放** → 长方体躺平
- 手机**举起来左右转** → 长方体跟着转

进游戏（如塞尔达举弓）时视角跟随手机倾斜就成功了。

---

## Steam 全平台适配

### 为什么 Steam 能直接识别

桥接创建的虚拟手柄走的是 **ViGEmBus → XUSB（Xbox 控制器驱动）** 路径：

```
ViGEmBus 驱动
    └─ 虚拟 DualShock 4 (HID)
         ├─ XInput  API  ──► Steam Input / 大部分 PC 游戏
         ├─ DirectInput  ──► 老游戏
         └─ SDL2         ──► 现代引擎、模拟器
```

因为伪装的是**真实存在的手柄型号（DS4）**，Windows 会按标准 HID 设备加载驱动，
Steam、Epic、GOG 以及几乎所有 PC 游戏都无需额外配置即可识别。

### Steam 里的推荐设置

1. **Steam → 设置 → 控制器 → 常规控制器设置**
   勾选 **PlayStation 配置支持**（因为虚拟设备是 DS4）

2. 游戏中通过 **Steam Input** 可以把 DS4 映射成任意布局

3. 如果游戏只认 Xbox 手柄，在 Steam 的控制器布局里选 **"手柄"** 模板即可

### 已验证平台

| 平台 | 按键 | 体感 | 备注 |
|---|---|---|---|
| Yuzu | ✅ | ✅ | 体感走 DSU，需选 muhooku |
| Cemu | ✅ | ✅ | 同上 |
| Ryujinx | ✅ | ✅ | 同上 |
| Steam 游戏 | ✅ | ❌ | Steam 不读 DSU，体感不可用 |
| 一般 PC 游戏 | ✅ | ❌ | 走 XInput |

---

## 常见问题

<details>
<summary><b>手机连不上电脑</b></summary>

1. 确认手机和电脑在**同一个 Wi-Fi**（不要一个连 5G 一个连 2.4G 的不同网段）
2. 关闭手机上的 **VPN**（VPN 会劫持局域网流量）
3. 检查 Windows 防火墙：允许 Python 访问专用网络
4. 先在电脑上 `ping <手机IP>` 试试通不通
</details>

<details>
<summary><b>按键有反应，体感完全不动</b></summary>

最常见的原因是 Yuzu 的体感源选成了 `sdl`：

- 打开 Yuzu 控制设置 → 体感 → 改成 **muhooku**
- 或者关闭 Yuzu 后运行 `python pc/fix_yuzu_motion.py`

次要原因：桥接日志里 `DSU客户端=0`，说明 Yuzu 还没订阅 —— 打开一次控制设置页面触发订阅。
</details>

<details>
<summary><b>体感一直自己转圈 / 越玩越歪</b></summary>

- 先确认 `bridge.log` 里 `锚定=` 的值。静止时应接近 `0.0°/s`。
- 如果持续顶在 `20.0°/s` 以上，用 `python Yuzu_Bridge.py --no-anchor` 关掉锚定对比
- 如果关了锚定就不转，说明手机的旋转矢量传感器和陀螺仪轴向不一致，可提 issue
</details>

<details>
<summary><b>快速甩动后视角归位慢</b></summary>

姿态锚定采用三档增益自动收敛，20° 偏差约 **0.16 秒**回到 1° 以内。
如果仍觉得慢，可以调大 `pc/Yuzu_Bridge.py` 里的 `GAIN_TIERS` 和 `MAX_CORR`。
</details>

<details>
<summary><b>手机断开后游戏视角还在转</b></summary>

已通过**心跳帧**解决：静默超过 250ms 后桥接改发零角速度帧，
画面会立即冻结在当前姿态。如果仍出现，说明用的是旧版桥接脚本。
</details>

<details>
<summary><b>ABXY 按键位置不对</b></summary>

切换 Xbox / Switch 模式。Switch 模式会做 A↔B、X↔Y 的交叉映射，
以匹配 Switch Pro 手柄的物理布局。
</details>

<details>
<summary><b>安装 APK 被手机拦截</b></summary>

部分国产 ROM（vivo / OPPO / 小米）需要：
`设置 → 安全 → 允许安装未知来源应用`，并临时关闭"应用安全检测"。
</details>

---

## 项目结构

```
wifipad/
├── app/                              # 安卓端（Kotlin + Jetpack Compose）
│   └── src/main/
│       ├── java/com/example/wifipad/
│       │   ├── MainActivity.kt
│       │   ├── net/Protocol.kt        # 52 字节 UDP 协议定义
│       │   ├── net/UdpSender.kt       # 120Hz 高精度发送器
│       │   ├── sensor/MotionController.kt  # 传感器 + 姿态四元数
│       │   └── ui/WifiPadApp.kt       # 手柄界面 + 设置抽屉
│       └── res/
│           ├── mipmap-*/              # 各密度图标（自适应图标）
│           └── values/strings.xml     # app_name = 鲸小游
│
└── pc/                               # 电脑端（Python，零第三方依赖）
    ├── Yuzu_Bridge.py                # 主桥接：虚拟 DS4 + DSU 服务器
    ├── ViGEmClient.dll               # ViGEm 客户端库
    ├── gui.py                        # 图形控制面板（tkinter）
    ├── app.ico                       # exe 圆角图标
    ├── app_icon.png                  # 窗口图标
    ├── build_exe.bat                 # 一键打包单文件 exe
    ├── fix_yuzu_motion.py            # 把 Yuzu 体感源改成 muhooku
    ├── fix_yuzu_guid.py              # 修正 Yuzu 的控制器 GUID 绑定
    ├── motion_viewer.py              # DSU 体感可视化调试工具
    ├── requirements.txt              # 依赖清单（无第三方库）
    ├── README.md                     # 电脑端详细说明
    └── YUZU_MOTION_SETUP.md          # 体感排查深度指南
```

---

## 技术细节

<details>
<summary><b>UDP 协议格式（手机 → PC，52 字节）</b></summary>

| 偏移 | 长度 | 字段 | 说明 |
|---|---|---|---|
| 0 | 2 | magic | `"WP"` |
| 2 | 1 | version | `3` |
| 3 | 1 | flags | bit0=Switch 模式，bit1=体感有效 |
| 4 | 4 | seq | 序号 |
| 8 | 8 | timestamp | 毫秒时间戳 |
| 16 | 2 | buttons | 按键位掩码 |
| 18 | 1 | lt / rt | 模拟扳机 0~255 |
| 20 | 6 | lx ly rx ry | 摇杆，−100~+100 |
| 26 | 12 | gx gy gz ax ay az | 角速度 / 加速度 |
| 38 | 16 | qx qy qz qw | 相对姿态四元数（float32）|
</details>

<details>
<summary><b>DSU 包结构（100 字节）</b></summary>

| 偏移 | 字段 |
|---|---|
| 0 | magic `"DSUS"` |
| 4 | 协议版本 1001 |
| 6 | length = payload + 4 |
| 8 | CRC32 |
| 12 | server id |
| 16 | 消息类型（`0x100000` 版本 / `0x100001` 端口 / `0x100002` 数据）|
| 20 | slot / state / model / conn_type |
| 32 | packet_number |
| 48 | **timestamp（积分时钟）** |
| 56 | 加速度 ×3（g）|
| 68 | 角速度 ×3（deg/s）|
</details>

<details>
<summary><b>姿态锚定算法</b></summary>

DSU 只提供角速度和重力：重力能慢慢修正 pitch/roll，但 **yaw 没有任何参考**，
客户端纯积分必然漂移。

解决方案（思路来自开源项目 PhoneGyro）：

1. 手机额外上报相对姿态四元数 `q_ref`
2. PC 维护 `est` = 客户端按我们发出的角速度积分后会到达的姿态
3. 误差 `e = log(conj(est) ⊗ q_ref)`
4. 修正量 `gain × e`（rad/s）叠加到输出角速度，三档增益自适应
5. 客户端积分时被持续牵引回真实姿态

实测：无修正漂移 38° → 有锚定误差 0.2°。
</details>

---

## 致谢

- [ViGEmBus](https://github.com/nefarius/ViGEmBus) —— Windows 虚拟手柄驱动
- [PhoneGyro](https://github.com/MrHoustonOff/PhoneGyro) —— 姿态锚定与 DSU 实现的参考
- [Cemuhook](https://cemuhook.sshnuke.net/) —— DSU 体感协议规范

---

## 许可证

MIT License

---

<p align="center">
  <b>鲸小游</b> · 把手机变成全能体感手柄<br>
  <sub>Made with Kotlin + Python</sub>
</p>