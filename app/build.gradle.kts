plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

android {
    namespace = "com.example.wifipad"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.example.wifipad"
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "1.0.0"
    }

    // Release 签名。密钥随仓库一起提供，方便任何人构建同签名版本；
    // 密码是公开的（开源项目惯例），仅用于发布，不做安全用途。
    signingConfigs {
        create("release") {
            storeFile = file("jingxiaoyou-release.keystore")
            storePassword = "jingxiaoyou2024"
            keyAlias = "jingxiaoyou"
            keyPassword = "jingxiaoyou2024"
        }
    }

    buildTypes {
        release {
            // R8 代码压缩 + 混淆 + 资源裁剪
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
            signingConfig = signingConfigs.getByName("release")
        }
        debug {
            // 调试包也加上最小混淆，避免「debug 能跑、release 崩」
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        compose = true
    }

    // 输出 APK 文件名带上版本，方便发布
    applicationVariants.all {
        outputs.all {
            val out = this as com.android.build.gradle.internal.api.BaseVariantOutputImpl
            if (buildType.name == "release") {
                out.outputFileName = "jingxiaoyou-v${versionName}.apk"
            }
        }
    }
}

dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2024.12.01")
    implementation(composeBom)
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-graphics")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-core")
    debugImplementation("androidx.compose.ui:ui-tooling")
}