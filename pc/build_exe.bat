@echo off
chcp 65001 >nul
REM ============================================================
REM  鲸小游桥接 - 一键打包单文件 exe（图形界面版）
REM ============================================================
REM  生成 dist\Whaley-Bridge.exe
REM
REM  关于文件名：Windows 防火墙弹窗显示的是 exe 的实际文件名，
REM  不受版本资源影响。若 exe 叫「鲸小游桥接.exe」，弹窗就会显示
REM  这个中文名。为了弹窗显示 Whaley-Bridge，这里用英文文件名，
REM  桌面上再放一个中文名的快捷方式即可。
REM
REM  需要: Python 3.8+ 与 pyinstaller
REM        pip install pyinstaller
REM ============================================================

cd /d "%~dp0"

echo.
echo [1/2] 检查 pyinstaller ...
python -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo     未安装，正在安装 ...
    python -m pip install pyinstaller
    if errorlevel 1 (
        echo.
        echo [失败] 无法安装 pyinstaller，请检查网络或 pip 配置。
        pause
        exit /b 1
    )
)

echo.
echo [2/2] 开始打包 ...
python -m PyInstaller ^
    --onefile ^
    --windowed ^
    --name "Whaley-Bridge" ^
    --icon "app.ico" ^
    --version-file "version_info.txt" ^
    --add-binary "ViGEmClient.dll;." ^
    --add-data "app_icon.png;." ^
    --hidden-import gui ^
    --exclude-module unittest ^
    --exclude-module pydoc ^
    --clean --noconfirm ^
    Yuzu_Bridge.py

if errorlevel 1 (
    echo.
    echo [失败] 打包出错，请查看上面的日志。
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  打包完成: dist\Whaley-Bridge.exe
echo ============================================================
echo.
echo  双击打开图形控制面板。
echo  桌面快捷方式可以命名成「鲸小游桥接」。
echo  仍需先安装 ViGEmBus 驱动。
echo.
pause