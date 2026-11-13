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
| Phase 4 | Xbox 1:1 布局重构 + Material 3 抽屉 + 黑白双主题 + 震动反馈 + L3/R3 | ✅ |
| Phase 5 | 自定义按键布局编辑器 | ⏳ |
| Phase 6 | PC 端 Python + ViGEmBus + DSU | ⏳ |

### Phase 4 已实现

- **系统**：强制横屏、屏幕常亮（`FLAG_KEEP_SCREEN_ON`）、沉浸式全屏
- **布局（Xbox 1:1）**
  - 左：左上 L-Stick（蘑菇头 + 同心圆纹理）、左下 一体化圆盘 D-Pad
  - 右：右上 ABXY（A绿 / B红 / X蓝 / Y黄，渐变高光 + 3D 阴影）、右下 R-Stick
  - 顶：最外侧 LT/RT（圆角矩形 + 按下填充进度）、内侧 LB/RB（梯形肩键）
- **Material 3**：`ModalNavigationDrawer` 从右侧滑出（RTL 技巧），齿轮图标唤出；
  IP/端口、连接状态、调试数据全部收进抽屉；抽屉内可切换**黑白双主题**
- **手势**：摇杆拖拽与点击冲突判定 —— 位移 > 9dp 为拖拽，短促下压（<260ms）触发 **L3/R3**
- **动效**：所有按键按下均有缩放/下沉/阴影变化
- **震动**：`VibratorManager`（API 31+ 回退 `Vibrator`），普通按键 12ms、L3/R3 26ms 更重
- **协议 v2**：按键位扩展为 `LB/RB/L3/R3`，右摇杆 = 实体摇杆 + 体感映射叠加

#### 常见问题

- **手机显示“错误: socket failed: EPERM”** → 缺少 `INTERNET` 权限（已修复）
- **手机显示发送中但 PC 收不到** → 手机开启 VPN/代理时，局域网 UDP 会被路由到 `tun0` 隧道。
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
