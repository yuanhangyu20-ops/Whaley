package com.example.wifipad

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import com.example.wifipad.ui.GamepadScreen
import com.example.wifipad.ui.theme.WifiPadTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            WifiPadTheme(darkTheme = true) {
                GamepadScreen()
            }
        }
    }
}
