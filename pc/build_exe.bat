@echo off
chcp 65001 >nul
REM ============================================================
REM  鲸小游桥接 - 一键打包单文件 exe（图形界面版）
REM ============================================================
REM  生成 dist\JingXiaoYou-Bridge.exe（无控制台，纯图形界面），
REM  内置 ViGEmClient.dll，目标机器无需安装 Python，
REM  仅需 ViGEmBus 驱动。
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
    --name "JingXiaoYou-Bridge" ^
    --icon "app.ico" ^
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
echo  打包完成: dist\JingXiaoYou-Bridge.exe
echo ============================================================
echo.
echo  这是图形界面版本，双击打开控制面板。
echo  仍需先安装 ViGEmBus 驱动。
echo.
pause