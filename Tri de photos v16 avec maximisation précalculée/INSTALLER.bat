@echo off
title Installation - Tri de photos 14.29
cd /d "%~dp0"
py -m pip install --upgrade pip
py -m pip install -r requirements.txt
echo.
echo Installation terminee.
pause
