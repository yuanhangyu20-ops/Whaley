@echo off
chcp 65001 >nul
REM ============================================================
REM  鲸小游桥接 - 一键打包单文件 exe
REM ============================================================
REM  生成 dist\鲸小游桥接.exe，内置 ViGEmClient.dll，
REM  目标机器无需安装 Python，仅需 ViGEmBus 驱动。
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
    --name "鲸小游桥接" ^
    --icon "app.ico" ^
    --add-binary "ViGEmClient.dll;." ^
    --exclude-module tkinter ^
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
echo  打包完成: dist\鲸小游桥接.exe
echo ============================================================
echo.
echo  把这个 exe 发给别人，对方双击就能用
echo  （仍需先安装 ViGEmBus 驱动）
echo.
pause