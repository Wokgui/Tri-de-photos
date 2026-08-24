@echo off
title Installation - Tri de photos
cd /d "%~dp0"

py -m pip install --upgrade pip
py -m pip install -r requirements.txt

set "APPDIR=%~dp0"
set "SCRIPT=%~dp0triphotos_v14_29.py"
set "ICON_SRC=%~dp0triphotos_icon.png"
set "ICON_DIR=%LOCALAPPDATA%\Tri de photos"
set "ICON=%LOCALAPPDATA%\Tri de photos\Tri de photos.ico"
set "LOCAL_LINK=%~dp0Tri de photos.lnk"

rem Nettoie les anciens lanceurs et anciennes icones techniques.
del /f /q "%~dp0LANCER_TRIPHOTOS.lnk" >nul 2>&1
del /f /q "%~dp0Tri de photos.lnk" >nul 2>&1
del /f /q "%~dp0lancer_triphotos_interne.bat" >nul 2>&1
del /f /q "%~dp0tri_de_photos_bureau.ico" >nul 2>&1
del /f /q "%~dp0tri_de_photos_bureau.ico.b64" >nul 2>&1
if not exist "%ICON_DIR%" mkdir "%ICON_DIR%"

rem Cree l'icone Windows a partir du visuel exact de triphotos_icon.png.
rem Recadre la marge blanche exterieure puis rend les coins exterieurs transparents.
rem La tuile, le logo et le texte restent inchanges.
py -c "from PIL import Image,ImageDraw,ImageChops; import os; src=Image.open(os.environ['ICON_SRC']).convert('RGBA'); w,h=src.size; m=int(min(w,h)*0.055); src=src.crop((m,m,w-m,h-m)); s=min(src.size); src=src.crop(((src.width-s)//2,(src.height-s)//2,(src.width+s)//2,(src.height+s)//2)); mask=Image.new('L',src.size,0); r=int(s*0.16); ImageDraw.Draw(mask).rounded_rectangle((0,0,s-1,s-1),radius=r,fill=255); src.putalpha(ImageChops.multiply(src.getchannel('A'),mask)); src.save(os.environ['ICON'],format='ICO',sizes=[(256,256),(128,128),(96,96),(64,64),(48,48),(32,32),(24,24),(16,16)])"
if errorlevel 1 (
    echo Erreur lors de la creation de l'icone.
    pause
    exit /b 1
)

rem Cree le raccourci principal dans le dossier.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws=New-Object -ComObject WScript.Shell; $pyw=(Get-Command pyw.exe -ErrorAction SilentlyContinue).Source; if(-not $pyw){$pyw=(Get-Command py.exe -ErrorAction Stop).Source}; $s=$ws.CreateShortcut($env:LOCAL_LINK); $s.TargetPath=$pyw; $s.Arguments='\"' + $env:SCRIPT + '\"'; $s.WorkingDirectory=$env:APPDIR; $s.IconLocation=$env:ICON + ',0'; $s.Description='Tri de photos'; $s.Save()"

rem Remplace aussi le raccourci du Bureau.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws=New-Object -ComObject WScript.Shell; $desktop=[Environment]::GetFolderPath('Desktop'); Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $desktop 'LANCER_TRIPHOTOS.lnk'); Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $desktop 'Tri de photos.lnk'); $pyw=(Get-Command pyw.exe -ErrorAction SilentlyContinue).Source; if(-not $pyw){$pyw=(Get-Command py.exe -ErrorAction Stop).Source}; $s=$ws.CreateShortcut((Join-Path $desktop 'Tri de photos.lnk')); $s.TargetPath=$pyw; $s.Arguments='\"' + $env:SCRIPT + '\"'; $s.WorkingDirectory=$env:APPDIR; $s.IconLocation=$env:ICON + ',0'; $s.Description='Tri de photos'; $s.Save()"

rem Force Windows a recharger l'icone au lieu d'afficher une ancienne version en cache.
ie4uinit.exe -ClearIconCache >nul 2>&1
ie4uinit.exe -show >nul 2>&1

echo.
echo Installation terminee.
echo Le seul lanceur visible s'appelle Tri de photos.
pause
