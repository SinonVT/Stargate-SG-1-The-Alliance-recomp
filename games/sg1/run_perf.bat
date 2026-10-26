@echo off
rem Starts the game logging every hitch (a frame much longer than the ones around it) with what that frame did,
rem to out\build\release\logs\game.log. Use it when reporting stutter.
cd /d "%~dp0out\build\release"
set XBE_PERF=1
SG1.exe
