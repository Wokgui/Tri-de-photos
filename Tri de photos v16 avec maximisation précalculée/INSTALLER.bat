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

rem Cree l'icone sans la grande carte blanche : on garde seulement
rem l'objectif/les anneaux et le texte Tri de photos, tout le reste devient transparent.
py -c "from PIL import Image,ImageDraw,ImageChops,ImageOps; import os; src=Image.open(os.environ['ICON_SRC']).convert('RGBA').resize((512,512),Image.Resampling.LANCZOS); out=Image.new('RGBA',(512,512),(0,0,0,0)); lens=src.copy(); mask=Image.new('L',(512,512),0); ImageDraw.Draw(mask).ellipse((52,18,460,426),fill=255); lens.putalpha(ImageChops.multiply(lens.getchannel('A'),mask)); out.alpha_composite(lens); txt=src.crop((82,382,430,474)); px=list(txt.getdata()); txt.putdata([(r,g,b,0 if (max(r,g,b)>220 and max(r,g,b)-min(r,g,b)<45) else a) for r,g,b,a in px]); out.alpha_composite(txt,(82,382)); box=out.getbbox() or (0,0,512,512); out=out.crop(box); s=max(out.size); pad=max(8,int(s*0.035)); canvas=Image.new('RGBA',(s+2*pad,s+2*pad),(0,0,0,0)); canvas.alpha_composite(out,((canvas.width-out.width)//2,(canvas.height-out.height)//2)); canvas.save(os.environ['ICON'],format='ICO',sizes=[(256,256),(128,128),(96,96),(64,64),(48,48),(32,32),(24,24),(16,16)])"
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
