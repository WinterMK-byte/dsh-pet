@echo off
chcp 65001 >nul
set "NODE_OPTIONS=--experimental-sqlite"
cd /d "%~dp0"
set "NODE_EXE=C:/Users/makexuan/.workbuddy/binaries/node/versions/22.12.0/node.exe"
if not exist "%NODE_EXE%" set "NODE_EXE=node"
start "" "%NODE_EXE%" lib\standalone.js
