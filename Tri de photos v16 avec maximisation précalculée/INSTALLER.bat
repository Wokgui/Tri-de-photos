@echo off
title Installation - Tri de photos
cd /d "%~dp0"

py -m pip install --upgrade pip
py -m pip install -r requirements.txt
py -m pip install pillow

set "APPDIR=%~dp0"
set "SCRIPT=%~dp0triphotos_v14_29.py"
set "ICON_SRC=%~dp0triphotos_icon_final.png"
set "ICON_DIR=%LOCALAPPDATA%\Tri de photos"
set "ICON=%LOCALAPPDATA%\Tri de photos\Tri de photos final v11.ico"
set "LOCAL_LINK=%~dp0Tri de photos.lnk"

rem Nettoie les anciens lanceurs.
del /f /q "%~dp0LANCER_TRIPHOTOS.lnk" >nul 2>&1
del /f /q "%~dp0Tri de photos.lnk" >nul 2>&1
del /f /q "%~dp0lancer_triphotos_interne.bat" >nul 2>&1

if not exist "%ICON_DIR%" mkdir "%ICON_DIR%"

rem Supprime les anciennes icones generees pour eviter le cache Windows.
del /f /q "%LOCALAPPDATA%\Tri de photos\Tri de photos*.ico" >nul 2>&1

rem Cree l'ICO Windows directement a partir du PNG final valide stocke dans le depot.
py -c "from PIL import Image; import os; src=Image.open(os.environ['ICON_SRC']); src.load(); src=src.convert('RGBA'); src.save(os.environ['ICON'],format='ICO',sizes=[(96,96),(64,64),(48,48),(32,32),(24,24),(16,16)])"
if errorlevel 1 (
    echo Erreur lors de la creation de l'icone Windows.
    pause
    exit /b 1
)

rem Cree le raccourci Tri de photos dans le dossier.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws=New-Object -ComObject WScript.Shell; $pyw=(Get-Command pyw.exe -ErrorAction SilentlyContinue).Source; if(-not $pyw){$pyw=(Get-Command py.exe -ErrorAction Stop).Source}; $s=$ws.CreateShortcut($env:LOCAL_LINK); $s.TargetPath=$pyw; $s.Arguments='\"' + $env:SCRIPT + '\"'; $s.WorkingDirectory=$env:APPDIR; $s.IconLocation=$env:ICON + ',0'; $s.Description='Tri de photos'; $s.Save()"

rem Cree le meme raccourci sur le Bureau. Windows ajoute sa petite fleche normale.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws=New-Object -ComObject WScript.Shell; $desktop=[Environment]::GetFolderPath('Desktop'); Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $desktop 'LANCER_TRIPHOTOS.lnk'); Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $desktop 'Tri de photos.lnk'); $pyw=(Get-Command pyw.exe -ErrorAction SilentlyContinue).Source; if(-not $pyw){$pyw=(Get-Command py.exe -ErrorAction Stop).Source}; $s=$ws.CreateShortcut((Join-Path $desktop 'Tri de photos.lnk')); $s.TargetPath=$pyw; $s.Arguments='\"' + $env:SCRIPT + '\"'; $s.WorkingDirectory=$env:APPDIR; $s.IconLocation=$env:ICON + ',0'; $s.Description='Tri de photos'; $s.Save()"

rem Force le rechargement des icones Windows.
ie4uinit.exe -ClearIconCache >nul 2>&1
ie4uinit.exe -show >nul 2>&1

echo.
echo Installation terminee.
echo L'icone du dossier et du Bureau utilise le visuel final valide.
pause
