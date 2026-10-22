@echo off
rem Optional: add the cut terrain grass to the first level (New Game -> No). Usage: install_grass.bat "C:\path\to\game folder" [--undo]
python "%~dp0install_grass.py" %*
pause
