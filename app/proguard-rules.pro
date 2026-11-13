# 鲸小游 ProGuard / R8 混淆规则
# =================================
# Compose 与 AndroidX 自带 consumer rules，这里的规则只处理本项目自身
# 以及 R8 全模式可能误删的部分。

# ─── 保留行号信息，便于线上崩溃定位 ───
-keepattributes SourceFile,LineNumberTable
-renamesourcefileattribute SourceFile

# ─── 应用入口（四大组件由 AGP 自动保留，这里显式声明更稳妥）───
-keep class com.example.wifipad.MainActivity { *; }

# ─── 协议与传感器类：字段名参与二进制布局/调试输出，保留可读性 ───
#     （即便被混淆也能工作，但保留有助于排查问题）
-keep class com.example.wifipad.net.Protocol { *; }
-keep class com.example.wifipad.net.GamepadPacket { *; }
-keep class com.example.wifipad.net.UdpSender { *; }
-keep class com.example.wifipad.sensor.MotionController { *; }

# ─── Kotlin 元数据 ───
-keep class kotlin.Metadata { *; }
-keepclassmembers class **$WhenMappings {
    <fields>;
}

# ─── 枚举的 values()/valueOf()（R8 全模式会警告）───
-keepclassmembers enum * {
    public static **[] values();
    public static ** valueOf(java.lang.String);
}

# ─── Compose 运行时用反射访问部分内部类，保留 ───
-keepclassmembers class androidx.compose.runtime.** {
    <init>(...);
}

# ─── 不输出警告（避免第三方库噪音阻塞构建）───
-dontwarn org.jetbrains.annotations.**