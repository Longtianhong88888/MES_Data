@echo off
REM Quick login test launcher - uses built-in PowerShell, nothing to install.
SETLOCAL
SET SCRIPT_DIR=%~dp0
PUSHD "%SCRIPT_DIR%"

powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%login_test.ps1" > login.log 2>&1
SET EXIT_CODE=%ERRORLEVEL%

ECHO.
ECHO ===== Output (also saved in login.log) =====
TYPE login.log
ECHO ===========================================
ECHO Exit code: %EXIT_CODE%
ECHO.
PAUSE

POPD
ENDLOCAL
