@echo off
rem OPTIONAL: make your own AI-upscaled textures. The game already ships the original full-size art in texpack\hd.
rem 1) Put realesrgan-ncnn-vulkan.exe (+ its models folder) next to this file.
rem 2) Run this file. It upscales every image in texpack\hd and writes the result, with the SAME file name, into texpack\custom.
rem    (You can also copy just a few images from hd to a work folder and edit/upscale only those.)
rem 3) Files in texpack\custom override the ones in texpack\hd (Insert menu: "Custom textures" = on).
rem    Delete a file from custom to go back to the original.
cd /d "%~dp0"
set REALESR=realesrgan-ncnn-vulkan.exe
if not exist "%REALESR%" (echo Put realesrgan-ncnn-vulkan.exe and the models folder in %~dp0 & pause & exit /b 1)
if not exist custom mkdir custom
"%REALESR%" -i hd -o custom -n realesrgan-x4plus -s 4 -f png
echo Done. Toggle "Custom textures" off/on in the game menu, or restart.
pause
