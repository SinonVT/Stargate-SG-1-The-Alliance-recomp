@echo off
rem Usage: setup_sg1.bat "C:\path\to\game folder"   (add --build to also build; run from a VS 2022 x64 Native Tools prompt for --build)
if "%~1"=="" (echo Usage: setup_sg1.bat "C:\path\to\game folder" [--build] [--redo] & exit /b 1)
py -3 "%~dp0setup_sg1.py" %*
