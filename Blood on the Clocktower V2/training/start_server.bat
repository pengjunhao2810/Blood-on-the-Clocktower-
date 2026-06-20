@chcp 65001 >nul
@echo off
title BotC Server

cd /d "%~dp0"
start "" /MIN python app.py
timeout /t 3 /nobreak >nul
start http://127.0.0.1:5000
echo.
echo Ready! http://127.0.0.1:5000
echo Close this window to stop.
echo.
pause >nul
taskkill /fi "WINDOWTITLE eq app.py" /f >nul 2>&1
