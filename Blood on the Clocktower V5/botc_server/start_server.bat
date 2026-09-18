@echo off
chcp 65001 >nul
title 血染钟楼 Go 游戏服务 (8741)
cd /d %~dp0

if not exist botc-server.exe (
    echo [编译] 正在构建 botc-server.exe ...
    go build -o botc-server.exe .
    if errorlevel 1 (
        echo [错误] 编译失败，请检查 Go 环境
        pause
        exit /b 1
    )
)

echo [启动] Go 游戏服务 http://127.0.0.1:8741
botc-server.exe
pause
