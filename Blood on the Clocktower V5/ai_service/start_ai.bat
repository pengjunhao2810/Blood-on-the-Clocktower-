@echo off
chcp 65001 >nul
title 血染钟楼 AI 推理服务 (8742)
cd /d %~dp0

if not exist venv (
    echo [初始化] 创建 Python 虚拟环境 ...
    python -m venv venv
    venv\Scripts\python.exe -m pip install -r requirements.txt
)

echo [启动] AI 推理服务 http://127.0.0.1:8742
venv\Scripts\python.exe main.py
pause
