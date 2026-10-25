@echo off
rem Starts the game with full logging (out\build\release\logs). Use it when reporting a problem.
cd /d "%~dp0out\build\release"
set XBE_VERBOSE=1
SG1.exe
