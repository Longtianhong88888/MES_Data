@echo off
REM Offline launcher for MES_Data. No install needed: lib\ holds all dependencies.
REM If debug_run.txt is NOT created after double-click, this bat never ran.

SETLOCAL ENABLEDELAYEDEXPANSION
SET PROJECT_DIR=%~dp0
PUSHD %PROJECT_DIR%

ECHO %date% %time% - run_windows.bat started > debug_run.txt

ECHO Script dir: %PROJECT_DIR%
ECHO Working dir: %CD%

SET PYTHON_EXE=

REM 1) Project-local portable Python (relative paths, works on UNC shared folders)
for %%F in (
    "python\python.exe"
    "python3\python.exe"
    "python310\python.exe"
    "venv\Scripts\python.exe"
    "Env\Scripts\python.exe"
) do (
    if exist %%~F (
        set "PYTHON_EXE=%%~F"
        goto FOUND_PYTHON
    )
)

REM 2) Sibling portable Python folders from other projects
for %%F in (
    "..\python\python.exe"
    "..\python3\python.exe"
    "..\venv\Scripts\python.exe"
    "..\PY\auto_report\python\python.exe"
    "..\PY\auto_report\python310\python.exe"
) do (
    if exist %%~F (
        set "PYTHON_EXE=%%~F"
        goto FOUND_PYTHON
    )
)

REM 3) System Python on PATH, but only if it really runs (filters out Store stubs)
where python >nul 2>&1
IF %ERRORLEVEL% EQU 0 (
    python --version >nul 2>&1
    IF %ERRORLEVEL% EQU 0 (
        set "PYTHON_EXE=python"
        goto FOUND_PYTHON
    )
)

REM 4) py launcher, same validation
where py >nul 2>&1
IF %ERRORLEVEL% EQU 0 (
    py --version >nul 2>&1
    IF %ERRORLEVEL% EQU 0 (
        set "PYTHON_EXE=py"
        goto FOUND_PYTHON
    )
)

ECHO.
ECHO No usable Python runtime found.
ECHO Put a portable Python (python.exe) into this project's python\ folder.
ECHO.
ECHO No usable Python runtime found. > run.log
PAUSE
GOTO END

:FOUND_PYTHON
ECHO Using Python: %PYTHON_EXE%
"%PYTHON_EXE%" main.py > run.log 2>&1
SET EXIT_CODE=%ERRORLEVEL%
ECHO.
ECHO ===== Program output (also saved in run.log) =====
TYPE run.log
ECHO ==================================================
ECHO Exit code: %EXIT_CODE%
ECHO.
PAUSE

:END
POPD
ENDLOCAL
