@echo off
rem Makes SG1.zip: the executable, the compiler folder that builds the game code on the player's PC, an empty assets
rem folder, the README and the Visual C++ runtime. No game files and no game code go in it.
setlocal
set "GAME_EXE=SG1"
cd /d "%~dp0"
set "OUT=out\build\release"
set "STAGE=%OUT%\release"
rem the Visual C++ runtime beside the executable, so a fresh Windows install needs nothing more
set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
for /f "usebackq tokens=*" %%i in (`"%VSWHERE%" -latest -products * -property installationPath`) do set "VSDIR=%%i"
for /d %%v in ("%VSDIR%\VC\Redist\MSVC\1*") do for /d %%c in ("%%v\x64\Microsoft.VC*.CRT") do set "VCRUNTIME=%%c"
if not exist "%VCRUNTIME%\vcruntime140.dll" (echo   Visual C++ runtime not found: install Visual Studio with the C++ workload. & goto :fail)
if not exist "%OUT%\%GAME_EXE%.exe" (echo   Build the game first: run build.bat. & goto :fail)
rem the configure step writes where the SDK is
if not exist "%OUT%\sdk_dir.txt" cmake --preset release >nul
if not exist "%OUT%\sdk_dir.txt" (echo   %OUT%\sdk_dir.txt was not written, update the SDK. & goto :fail)
set /p SDK=<"%OUT%\sdk_dir.txt"
where tar >nul 2>nul || (echo   tar.exe not found: it comes with Windows 10 1803 and later. & goto :fail)

echo   Staging the release in %STAGE%
rd /s /q "%STAGE%" 2>nul
mkdir "%STAGE%\assets" || goto :fail
rem only the runtime DLLs the executables import; xbe_recomp.exe needs its own copy, Windows only looks beside the
rem exe it starts
del /q "%OUT%\compiler\*.dll" 2>nul
for %%f in (msvcp140 vcruntime140) do copy /y "%VCRUNTIME%\%%f.dll" "%OUT%\compiler\" >nul
copy /y "%OUT%\%GAME_EXE%.exe" "%STAGE%\" >nul || goto :fail
for %%f in (msvcp140 vcruntime140 vcruntime140_1) do copy /y "%VCRUNTIME%\%%f.dll" "%STAGE%\" >nul || goto :fail
copy /y README.md "%STAGE%\" >nul
if exist "%SDK%\THIRD_PARTY.txt" copy /y "%SDK%\THIRD_PARTY.txt" "%STAGE%\" >nul
rem the compiler folder without its work folder: no game code goes in the zip, the first start builds it
robocopy "%OUT%\compiler" "%STAGE%\compiler" /E /XD work /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 (echo   Copying the compiler folder failed. & goto :fail)

echo   Zipping %GAME_EXE%.zip
del /q "%GAME_EXE%.zip" 2>nul
set "FILES=%GAME_EXE%.exe assets compiler README.md msvcp140.dll vcruntime140.dll vcruntime140_1.dll"
if exist "%STAGE%\THIRD_PARTY.txt" set "FILES=%FILES% THIRD_PARTY.txt"
tar -a -c -f "%GAME_EXE%.zip" -C "%STAGE%" %FILES% || (echo   Zipping failed. & goto :fail)
echo.
echo   Done: %CD%\%GAME_EXE%.zip
echo   The same files are in %CD%\%STAGE%
echo.
choice /c YN /n /m "  Test the release now (put the game in its assets folder first; the first start builds the game code, which takes a few minutes)? [Y/N] "
if not errorlevel 2 start "" /d "%STAGE%" "%STAGE%\%GAME_EXE%.exe"
exit /b 0

:fail
echo.
echo   RELEASE FAILED. Read the last message above.
echo.
if not defined CI pause
exit /b 1
