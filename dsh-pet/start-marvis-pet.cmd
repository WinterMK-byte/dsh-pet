@echo off
chcp 65001 >nul
set "NODE_OPTIONS=--experimental-sqlite"
cd /d "%~dp0"
set "NODE_EXE=C:/Users/makexuan/.workbuddy/binaries/node/versions/22.12.0/node.exe"
if not exist "%NODE_EXE%" set "NODE_EXE=node"

rem 1) 清理残留：上次没关干净的话，旧 standalone/electron-helper 会抢端口或让新窗口不出现
powershell -NoProfile -ExecutionPolicy Bypass -File cleanup-marvis-pet.ps1
timeout /t 2 /nobreak >nul 2>&1 || ping -n 3 127.0.0.1 >nul

rem 2) 兜底恢复：若上次通过托盘/右键把 display 切成了 none/web，重新启动时恢复为 desktop
"%NODE_EXE%" fix-display-on-start.js

start "" "%NODE_EXE%" lib\standalone.js
