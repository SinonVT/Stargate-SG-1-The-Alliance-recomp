@echo off
rem SG-1 HD texture pack: the original full-size textures, extracted from YOUR game files (assets\Textures\*.utx)
rem into out\build\release\texpack (hd\*.png + index.txt). A few minutes; run it again and it resumes.
rem Optional argument: the size cap per texture (default 1024, e.g. 512 or 2048).
rem Needs Python 3 (python.org, tick "Add to PATH"); numpy and Pillow are installed if missing.
cd /d "%~dp0"
set "PY=python"
where py >nul 2>nul && set "PY=py -3"
%PY% -c "import numpy, PIL" >nul 2>nul || %PY% -m pip install numpy pillow
set "OUT=%~dp0out\build\release\texpack"
if not exist "%OUT%\custom" mkdir "%OUT%\custom"
if not exist "%OUT%\upscale_dump.bat" copy /y "%~dp0tools\upscale_dump.bat" "%OUT%\" >nul
%PY% "%~dp0tools\make_hdpack.py" "%~dp0assets" "%OUT%" %1
if errorlevel 1 (echo. & echo Something went wrong, see above.) else (echo. & echo DONE. In the game: Insert, Reload textures.)
pause
