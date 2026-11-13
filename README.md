# WifiPad-Android

把 Android 手机变成低延迟、高精度体感 + 自定义按键布局的无线手柄（PC 端 Python 收包，兼容 Yuzu/Ryujinx 与 Steam/XInput）。

## 技术栈

| 端 | 技术 |
|---|---|
| Android | Kotlin 2.0.21 + Jetpack Compose (Material3) + AGP 8.7.3 |
| 构建 | Gradle 8.14.2（wrapper 指向国内镜像） |
| PC（规划） | Python (asyncio) + ViGEmBus + DSU/Cemuhook + PySide6 |

## 当前进度

| 阶段 | 内容 | 状态 |
|---|---|---|
| Phase 1 | 工程骨架 / Hello World 真机跑通 | ✅ |
| Phase 2 | 虚拟手柄 UI：摇杆 + ABXY + 十字键 + LT/RT，**多点触控**，调试面板 | ✅ |
| Phase 3 | 体感采集（陀螺仪 + 加速度计 + 滤波）+ 60Hz UDP 发送 + PC 测试接收端 | ✅ |
| Phase 4 | 自定义按键布局编辑器 | ⏳ |
| Phase 5 | PC 端 Python + ViGEmBus + DSU | ⏳ |

### Phase 3 已实现

- **体感**：`SensorManager` 读取陀螺仪 / 加速度计，一阶低通滤波 + 死区去抖；
  绕 Y 轴旋转 → 右摇杆 X，绕 X 轴旋转 → 右摇杆 Y（下方调试面板实时可见）
- **网络**：60Hz UDP 客户端，IP / 端口在 UI 内可填（默认端口 12345）
- **协议**：36 字节定长二进制包（见 `app/.../net/Protocol.kt` 注释）
- **PC 测试**：项目根目录运行 `python pc_receiver_test.py`（默认监听 12345）

#### 常见问题

- **手机显示“错误: socket failed: EPERM”** → 缺少 `INTERNET` 权限（已修复）
- **手机显示发送中但 PC 收不到** → 手机开启了 VPN/代理时，局域网 UDP 会被路由到 `tun0` 隧道。
  解决方法：关闭 VPN，或把 `10.x.x.0/24` 加入代理直连/绕过局域网。
- **Windows 防火墙**：已为 UDP 12345 添加入站放行规则（`WifiPad UDP 12345`）。

## 构建

```bash
# 环境要求：JDK 17、Android SDK (API 35)
./gradlew assembleDebug          # Windows: gradlew.bat assembleDebug
./gradlew installDebug           # 直接安装到已连接的设备
```

## 文档

- `docs/screenshots/` — 各阶段真机运行截图

## License

私有项目，保留所有权利。
