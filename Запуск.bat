@echo off
chcp 65001 >nul
cd /d "%~dp0"
py "game_backlog_qt.py"
if errorlevel 1 pause
