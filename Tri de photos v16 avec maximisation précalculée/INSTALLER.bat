@echo off
title Installation - Tri de photos
cd /d "%~dp0"

py -m pip install --upgrade pip
py -m pip install -r requirements.txt

set "APPDIR=%~dp0"
set "SCRIPT=%~dp0triphotos_v14_29.py"
set "ICON_SRC=%~dp0triphotos_header_icon.png"
set "ICON_DIR=%LOCALAPPDATA%\Tri de photos"
set "ICON=%LOCALAPPDATA%\Tri de photos\Tri de photos bureau.ico"
set "LOCAL_LINK=%~dp0Tri de photos.lnk"

rem Nettoie les anciens lanceurs et anciens fichiers techniques.
del /f /q "%~dp0LANCER_TRIPHOTOS.lnk" >nul 2>&1
del /f /q "%~dp0Tri de photos.lnk" >nul 2>&1
del /f /q "%~dp0lancer_triphotos_interne.bat" >nul 2>&1
del /f /q "%~dp0tri_de_photos_bureau.ico" >nul 2>&1
del /f /q "%~dp0tri_de_photos_bureau.ico.b64" >nul 2>&1
if not exist "%ICON_DIR%" mkdir "%ICON_DIR%"

rem Fabrique un vrai .ico Windows multi-resolution a partir du logo haute resolution.
rem Le logo remplit presque tout le carre, comme une icone d'application type Photoshop.
py -c "from PIL import Image,ImageDraw,ImageOps,ImageChops; import os; src=Image.open(os.environ['ICON_SRC']).convert('RGBA'); a=src.getchannel('A'); box=a.getbbox() or (0,0,src.width,src.height); lens=src.crop(box); lens=ImageOps.fit(lens,(448,448),method=Image.Resampling.LANCZOS,centering=(0.5,0.5)); mask=Image.new('L',(448,448),0); ImageDraw.Draw(mask).ellipse((0,0,447,447),fill=255); lens.putalpha(ImageChops.multiply(lens.getchannel('A'),mask)); canvas=Image.new('RGBA',(512,512),(0,0,0,0)); ImageDraw.Draw(canvas).rounded_rectangle((4,4,508,508),radius=92,fill=(10,30,58,255)); canvas.alpha_composite(lens,(32,32)); canvas.save(os.environ['ICON'],format='ICO',sizes=[(256,256),(128,128),(96,96),(64,64),(48,48),(32,32),(24,24),(16,16)])"
if errorlevel 1 (
    echo Erreur lors de la creation de l'icone.
    pause
    exit /b 1
)

rem Cree le raccourci principal directement vers Python.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws=New-Object -ComObject WScript.Shell; $pyw=(Get-Command pyw.exe -ErrorAction SilentlyContinue).Source; if(-not $pyw){$pyw=(Get-Command py.exe -ErrorAction Stop).Source}; $s=$ws.CreateShortcut($env:LOCAL_LINK); $s.TargetPath=$pyw; $s.Arguments='\"' + $env:SCRIPT + '\"'; $s.WorkingDirectory=$env:APPDIR; $s.IconLocation=$env:ICON + ',0'; $s.Description='Tri de photos'; $s.Save()"

rem Remplace aussi l'ancien raccourci du Bureau.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws=New-Object -ComObject WScript.Shell; $desktop=[Environment]::GetFolderPath('Desktop'); Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $desktop 'LANCER_TRIPHOTOS.lnk'); Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $desktop 'Tri de photos.lnk'); $pyw=(Get-Command pyw.exe -ErrorAction SilentlyContinue).Source; if(-not $pyw){$pyw=(Get-Command py.exe -ErrorAction Stop).Source}; $s=$ws.CreateShortcut((Join-Path $desktop 'Tri de photos.lnk')); $s.TargetPath=$pyw; $s.Arguments='\"' + $env:SCRIPT + '\"'; $s.WorkingDirectory=$env:APPDIR; $s.IconLocation=$env:ICON + ',0'; $s.Description='Tri de photos'; $s.Save()"

rem Demande a Windows de rafraichir les icones.
ie4uinit.exe -show >nul 2>&1

echo.
echo Installation terminee.
echo Le seul lanceur visible s'appelle Tri de photos.
pause
