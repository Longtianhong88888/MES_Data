@echo off
REM Install project dependencies on Windows WITHOUT internet access.
REM 离线方式: 使用项目内 wheels\ 目录的本地安装包(Windows x64 / Python 3.11)。
REM 联网方式: 若 wheels\ 不存在,则回退到 pip 在线安装。
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
            ECHO Failed to install pip from get-pip.py. Please use a Python installation with pip.
            PAUSE
            GOTO END
        )
    )
)

REM 内嵌版 Python 需启用 site(否则第三方包无法导入)
for %%F in ("%PROJECT_DIR%python\python311._pth" "%PROJECT_DIR%python3\python311._pth") do (
    if exist %%F (
        powershell -NoProfile -Command "(Get-Content '%%F') -replace '^#import site','import site' | Set-Content '%%F'"
    )
)

if exist "%PROJECT_DIR%wheels\" (
    ECHO [离线模式] 使用本地 wheels\ 安装依赖(无需联网)...
    "%PYTHON_EXE%" -m pip install --no-index --find-links "%PROJECT_DIR%wheels" -r "%PROJECT_DIR%requirements.txt"
    IF %ERRORLEVEL% EQU 0 (
        ECHO.
        ECHO Dependencies installed OFFLINE.
        PAUSE
        GOTO END
    ) ELSE (
        ECHO.
        ECHO 离线安装失败,请确认 wheels\ 目录完整且 Python 版本为 3.11 x64。
        ECHO 若本机可以联网,也可运行下方在线安装命令重试:
        ECHO   "%PYTHON_EXE%" -m pip install -r "%PROJECT_DIR%requirements.txt"
        PAUSE
        GOTO END
    )
)

ECHO [在线模式] 未找到 wheels\ 目录,尝试联网安装...
"%PYTHON_EXE%" -m pip install --upgrade pip
"%PYTHON_EXE%" -m pip install -r "%PROJECT_DIR%requirements.txt"

ECHO.
ECHO Dependencies installed.
PAUSE

:END
POPD
ENDLOCAL
