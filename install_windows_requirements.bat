@echo off
REM Install Python dependencies for this project using the detected Python runtime.
REM 注意: 如果项目内已有 lib\ 目录(离线依赖,方案B),直接运行 run_windows.bat 即可,无需本脚本。
SETLOCAL ENABLEDELAYEDEXPANSION
SET PROJECT_DIR=%~dp0
PUSHD %PROJECT_DIR%

SET PYTHON_EXE=
for %%F in (
    "%PROJECT_DIR%python\python.exe"
    "%PROJECT_DIR%python3\python.exe"
    "%PROJECT_DIR%python310\python.exe"
    "%PROJECT_DIR%venv\Scripts\python.exe"
    "%PROJECT_DIR%Env\Scripts\python.exe"
    "%PROJECT_DIR%..\python\python.exe"
    "%PROJECT_DIR%..\python3\python.exe"
    "%PROJECT_DIR%..\venv\Scripts\python.exe"
) do (
    if exist %%~F (
        set PYTHON_EXE=%%~F
        goto FOUND_PYTHON
    )
)

where python >nul 2>&1
IF %ERRORLEVEL% EQU 0 (
    set PYTHON_EXE=python
    goto FOUND_PYTHON
)

where py >nul 2>&1
IF %ERRORLEVEL% EQU 0 (
    set PYTHON_EXE=py
    goto FOUND_PYTHON
)

ECHO.
ECHO No usable Python runtime found.
ECHO Please place a portable Python folder under this project or install Python on Windows.
ECHO Recommended location: python\python.exe
ECHO.
PAUSE
GOTO END

:FOUND_PYTHON
ECHO Using Python: %PYTHON_EXE%

REM Ensure pip exists
"%PYTHON_EXE%" -m pip --version >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    ECHO pip not found. Attempting to bootstrap pip...
    "%PYTHON_EXE%" -m ensurepip --default-pip >nul 2>&1
    IF %ERRORLEVEL% NEQ 0 (
        ECHO ensurepip failed. Trying get-pip.py download.
        powershell -NoProfile -Command "Try { Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile 'get-pip.py' -UseBasicParsing } Catch { Exit 1 }"
        IF %ERRORLEVEL% NEQ 0 (
            ECHO Failed to download get-pip.py. Please ensure Windows has internet access or use a full Python installation.
            PAUSE
            GOTO END
        )
        "%PYTHON_EXE%" get-pip.py >nul 2>&1
        IF %ERRORLEVEL% NEQ 0 (
            ECHO Failed to install pip from get-pip.py. Please use a Python installation with pip or a complete embeddable package that includes pip.
            PAUSE
            GOTO END
        )
    )
)

ECHO Upgrading pip...
"%PYTHON_EXE%" -m pip install --upgrade pip

ECHO Installing required packages...
"%PYTHON_EXE%" -m pip install -r requirements.txt

ECHO.
ECHO Dependencies installed.
PAUSE

:END
POPD
ENDLOCAL
