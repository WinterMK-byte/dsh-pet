@echo off
REM ============================================================
REM  Marvis Pet 一键打包脚本（PyInstaller 单文件、无控制台）
REM  用法：双击运行 build.bat，产物在 dist\MarvisPet.exe
REM ============================================================
setlocal
cd /d "%~dp0"

echo [1/4] 检查虚拟环境...
if not exist ".venv\Scripts\python.exe" (
    echo   - 未发现 .venv，正在创建（Python 3.12）...
    where py >nul 2>nul && (py -3.12 -m venv .venv) || (python -m venv .venv)
    if errorlevel 1 (
        echo   [错误] 创建虚拟环境失败，请确认已安装 Python 3.10+ 并加入 PATH
        pause & exit /b 1
    )
)
set "PY=.venv\Scripts\python.exe"

echo [2/4] 安装依赖（阿里云镜像）...
"%PY%" -m pip install -i https://mirrors.aliyun.com/pypi/simple -r requirements.txt pyinstaller
if errorlevel 1 (
    echo   [错误] 依赖安装失败，请检查网络
    pause & exit /b 1
)

echo [3/4] 开始打包（MarvisPet.spec 含 assets 资源，使用 pyinstaller.exe 直调以避免 python -m 输出异常）...
".venv\Scripts\pyinstaller.exe" --noconfirm --clean MarvisPet.spec
if errorlevel 1 (
    echo   [错误] 打包失败，请查看上方日志
    pause & exit /b 1
)

echo [4/4] 打包完成：dist\MarvisPet.exe
echo   提示：首次运行会在 exe 同目录生成 config.json
pause
endlocal
