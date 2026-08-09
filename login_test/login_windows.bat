@echo off
REM Quick login test launcher - uses built-in PowerShell, nothing to install.
SETLOCAL
SET "SCRIPT_DIR=%~dp0"
PUSHD "%SCRIPT_DIR%" 2>nul
IF ERRORLEVEL 1 (
    ECHO.
    ECHO Cannot access the project folder:
    ECHO   %SCRIPT_DIR%
    ECHO If this is a UNC path, try running:  pushd "%SCRIPT_DIR%"
    ECHO.
    PAUSE
    ENDLOCAL
    EXIT /B 1
)
SET "LOG_FILE=%SCRIPT_DIR%login.log"
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%login_test.ps1" > "%LOG_FILE%" 2>&1
SET EXIT_CODE=%ERRORLEVEL%
ECHO.
ECHO ===== Output (also saved in login.log) =====
TYPE "%LOG_FILE%"
ECHO ===========================================
ECHO Exit code: %EXIT_CODE%
ECHO.
PAUSE
POPD
ENDLOCAL
