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
| Phase 2 | UDP 通信骨架 + 陀螺仪采集 | ⏳ |
| Phase 3 | 自定义按键布局编辑器 | ⏳ |
| Phase 4 | PC 端 Python + ViGEmBus + DSU | ⏳ |

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
