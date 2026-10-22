@echo off
rem Experimental: lets the game console command SETRES 1280x720 work (16:9). Copy next to sg1_alliance_recomp.exe.
cd /d "%~dp0"
set RECOMP_AV_HDTV=E0000
sg1_alliance_recomp.exe
