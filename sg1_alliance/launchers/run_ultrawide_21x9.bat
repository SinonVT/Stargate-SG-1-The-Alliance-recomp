@echo off
rem Experimental ultrawide: load a map, open the console and type SETRES 1792x768 (21:9). Copy next to sg1_alliance_recomp.exe.
cd /d "%~dp0"
set RECOMP_AV_HDTV=E0000
set RECOMP_MODE_ROW=1792x768
sg1_alliance_recomp.exe
