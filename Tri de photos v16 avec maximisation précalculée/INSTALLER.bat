@echo off
title Installation - Tri de photos 14.29
cd /d "%~dp0"

py -m pip install --upgrade pip
py -m pip install -r requirements.txt

rem Cree un raccourci avec la meme icone que l'application.
set "APPDIR=%~dp0"
set "TARGET=%~dp0LANCER_TRIPHOTOS.bat"
set "ICON=%~dp0triphotos_icon.ico"
set "LOCAL_LINK=%~dp0LANCER_TRIPHOTOS.lnk"

powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws=New-Object -ComObject WScript.Shell; $s=$ws.CreateShortcut($env:LOCAL_LINK); $s.TargetPath=$env:TARGET; $s.WorkingDirectory=$env:APPDIR; $s.IconLocation=$env:ICON + ',0'; $s.Description='Tri de photos'; $s.Save()"

rem Cree aussi le raccourci sur le Bureau de Windows.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws=New-Object -ComObject WScript.Shell; $desktop=[Environment]::GetFolderPath('Desktop'); $s=$ws.CreateShortcut((Join-Path $desktop 'Tri de photos.lnk')); $s.TargetPath=$env:TARGET; $s.WorkingDirectory=$env:APPDIR; $s.IconLocation=$env:ICON + ',0'; $s.Description='Tri de photos'; $s.Save()"

echo.
echo Installation terminee.
echo Le raccourci LANCER_TRIPHOTOS utilise maintenant l'icone de Tri de photos.
pause
