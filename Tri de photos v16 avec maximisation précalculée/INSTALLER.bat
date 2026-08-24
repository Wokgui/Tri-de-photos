@echo off
title Installation - Tri de photos
cd /d "%~dp0"

py -m pip install --upgrade pip
py -m pip install -r requirements.txt

set "APPDIR=%~dp0"
set "SCRIPT=%~dp0triphotos_v14_29.py"
set "ICON=%~dp0triphotos_icon.ico"
set "LOCAL_LINK=%~dp0Tri de photos.lnk"

rem Nettoie les anciens lanceurs eventuels.
del /q "%~dp0LANCER_TRIPHOTOS.lnk" >nul 2>&1
del /q "%~dp0lancer_triphotos_interne.bat" >nul 2>&1

rem Cree le raccourci principal directement vers Python, sans lanceur intermediaire visible.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws=New-Object -ComObject WScript.Shell; $pyw=(Get-Command pyw.exe -ErrorAction SilentlyContinue).Source; if(-not $pyw){$pyw=(Get-Command py.exe -ErrorAction Stop).Source}; $s=$ws.CreateShortcut($env:LOCAL_LINK); $s.TargetPath=$pyw; $s.Arguments='\"' + $env:SCRIPT + '\"'; $s.WorkingDirectory=$env:APPDIR; $s.IconLocation=$env:ICON + ',0'; $s.Description='Tri de photos'; $s.Save()"

rem Cree le meme raccourci sur le Bureau.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws=New-Object -ComObject WScript.Shell; $desktop=[Environment]::GetFolderPath('Desktop'); $pyw=(Get-Command pyw.exe -ErrorAction SilentlyContinue).Source; if(-not $pyw){$pyw=(Get-Command py.exe -ErrorAction Stop).Source}; $s=$ws.CreateShortcut((Join-Path $desktop 'Tri de photos.lnk')); $s.TargetPath=$pyw; $s.Arguments='\"' + $env:SCRIPT + '\"'; $s.WorkingDirectory=$env:APPDIR; $s.IconLocation=$env:ICON + ',0'; $s.Description='Tri de photos'; $s.Save()"

echo.
echo Installation terminee.
echo Le lanceur s'appelle maintenant Tri de photos.
pause
