@echo off
REM Download station images from the URL lists in .\downloads.
REM Run this on a machine that can reach the image file servers.
SETLOCAL
SET "SCRIPT_DIR=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%download_images.ps1" %*
ECHO.
PAUSE
ENDLOCAL
