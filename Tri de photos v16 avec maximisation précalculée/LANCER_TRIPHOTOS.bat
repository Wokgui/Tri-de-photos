@echo off
title Tri de photos - Deux par deux
cd /d "%~dp0"
where pyw >nul 2>&1
if not errorlevel 1 (
    start "" pyw triphotos_v14_29.py
    exit /b 0
)
py triphotos_v14_29.py
if errorlevel 1 pause
