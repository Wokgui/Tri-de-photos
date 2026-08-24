@echo off
title Installation - Tri de photos
cd /d "%~dp0"

py -m pip install --upgrade pip
py -m pip install -r requirements.txt

set "APPDIR=%~dp0"
set "SCRIPT=%~dp0triphotos_v14_29.py"
set "ICON_SRC=%~dp0triphotos_icon.png"
set "ICON_DIR=%LOCALAPPDATA%\Tri de photos"
set "ICON=%LOCALAPPDATA%\Tri de photos\Tri de photos tuile blanche v4.ico"
set "LOCAL_LINK=%~dp0Tri de photos.lnk"

rem Nettoie les anciens raccourcis et anciennes icones generees.
del /f /q "%~dp0LANCER_TRIPHOTOS.lnk" >nul 2>&1
del /f /q "%~dp0Tri de photos.lnk" >nul 2>&1
del /f /q "%~dp0lancer_triphotos_interne.bat" >nul 2>&1
del /f /q "%~dp0tri_de_photos_bureau.ico" >nul 2>&1
del /f /q "%~dp0tri_de_photos_bureau.ico.b64" >nul 2>&1
if not exist "%ICON_DIR%" mkdir "%ICON_DIR%"
del /f /q "%LOCALAPPDATA%\Tri de photos\Tri de photos.ico" >nul 2>&1
del /f /q "%LOCALAPPDATA%\Tri de photos\Tri de photos transparent v2.ico" >nul 2>&1
del /f /q "%LOCALAPPDATA%\Tri de photos\Tri de photos transparent v3.ico" >nul 2>&1

rem Garde la tuile blanche arrondie et rend seulement les coins exterieurs transparents.
rem On applique un masque arrondi a toute l'icone : rien de blanc a l'interieur n'est supprime.
py -c "from PIL import Image,ImageDraw,ImageChops,ImageOps; import os; src=Image.open(os.environ['ICON_SRC']).convert('RGBA'); w,h=src.size; m=int(min(w,h)*0.035); src=src.crop((m,m,w-m,h-m)); src=ImageOps.fit(src,(512,512),method=Image.Resampling.LANCZOS,centering=(0.5,0.5)); mask=Image.new('L',(512,512),0); ImageDraw.Draw(mask).rounded_rectangle((6,6,506,506),radius=86,fill=255); src.putalpha(ImageChops.multiply(src.getchannel('A'),mask)); bg=Image.new('RGBA',(512,512),(255,255,255,0)); white=Image.new('RGBA',(512,512),(255,255,255,255)); white.putalpha(mask); bg.alpha_composite(white); bg.alpha_composite(src); bg.putalpha(mask); bg.save(os.environ['ICON'],format='ICO',sizes=[(256,256),(128,128),(96,96),(64,64),(48,48),(32,32),(24,24),(16,16)])"
if errorlevel 1 (
    echo Erreur lors de la creation de l'icone.
    pause
    exit /b 1
)

rem Cree le raccourci principal dans le dossier.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws=New-Object -ComObject WScript.Shell; $pyw=(Get-Command pyw.exe -ErrorAction SilentlyContinue).Source; if(-not $pyw){$pyw=(Get-Command py.exe -ErrorAction Stop).Source}; $s=$ws.CreateShortcut($env:LOCAL_LINK); $s.TargetPath=$pyw; $s.Arguments='\"' + $env:SCRIPT + '\"'; $s.WorkingDirectory=$env:APPDIR; $s.IconLocation=$env:ICON + ',0'; $s.Description='Tri de photos'; $s.Save()"

rem Remplace aussi le raccourci du Bureau avec le nouveau chemin d'icone.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws=New-Object -ComObject WScript.Shell; $desktop=[Environment]::GetFolderPath('Desktop'); Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $desktop 'LANCER_TRIPHOTOS.lnk'); Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $desktop 'Tri de photos.lnk'); $pyw=(Get-Command pyw.exe -ErrorAction SilentlyContinue).Source; if(-not $pyw){$pyw=(Get-Command py.exe -ErrorAction Stop).Source}; $s=$ws.CreateShortcut((Join-Path $desktop 'Tri de photos.lnk')); $s.TargetPath=$pyw; $s.Arguments='\"' + $env:SCRIPT + '\"'; $s.WorkingDirectory=$env:APPDIR; $s.IconLocation=$env:ICON + ',0'; $s.Description='Tri de photos'; $s.Save()"

ie4uinit.exe -ClearIconCache >nul 2>&1
ie4uinit.exe -show >nul 2>&1

echo.
echo Installation terminee.
echo La tuile blanche est conservee et seuls les coins exterieurs sont transparents.
pause
