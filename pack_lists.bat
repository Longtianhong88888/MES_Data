@echo off
REM Pack the image URL lists into image_lists.zip for transfer via the company netdisk.
SETLOCAL
SET "SCRIPT_DIR=%~dp0"
SET "ZIP_FILE=%SCRIPT_DIR%image_lists.zip"
IF EXIST "%ZIP_FILE%" DEL /Q "%ZIP_FILE%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path '%SCRIPT_DIR%downloads\*images*.txt' -DestinationPath '%ZIP_FILE%' -Force"
IF EXIST "%ZIP_FILE%" (
    ECHO.
    ECHO Packed: %ZIP_FILE%
    ECHO Upload it to the company netdisk, then run download_images.bat on the company desktop.
) ELSE (
    ECHO.
    ECHO No image list files found in %SCRIPT_DIR%downloads - run login_test.ps1 first.
)
ECHO.
PAUSE
ENDLOCAL
