@echo off
REM SN 全制程追溯报告工具 - Windows 一键启动
REM 用法: 双击运行;或 run_sn_report.bat --sns sns.txt --out output/xxx.pptx
SETLOCAL ENABLEDELAYEDEXPANSION
SET PROJECT_DIR=%~dp0..
PUSHD %PROJECT_DIR%

ECHO SN 全制程追溯报告工具
ECHO.

REM 查找 Python:优先项目内便携版,其次系统 Python
SET PYTHON_EXE=
for %%F in (
    "python\python.exe"
    "python3\python.exe"
    "python310\python.exe"
    "venv\Scripts\python.exe"
    "Env\Scripts\python.exe"
    "..\python\python.exe"
    "..\python3\python.exe"
    "..\venv\Scripts\python.exe"
) do (
    if exist %%~F (
        set "PYTHON_EXE=%%~F"
        goto FOUND_PYTHON
    )
)

where python >nul 2>&1
IF %ERRORLEVEL% EQU 0 (
    python --version >nul 2>&1
    IF %ERRORLEVEL% EQU 0 (
        set "PYTHON_EXE=python"
        goto FOUND_PYTHON
    )
)

where py >nul 2>&1
IF %ERRORLEVEL% EQU 0 (
    py --version >nul 2>&1
    IF %ERRORLEVEL% EQU 0 (
        set "PYTHON_EXE=py"
        goto FOUND_PYTHON
    )
)

ECHO 未找到可用 Python。请把便携版 Python 放到项目的 python\ 目录,或安装 Python 后重试。
PAUSE
GOTO END

:FOUND_PYTHON
ECHO 使用 Python: %PYTHON_EXE%
"%PYTHON_EXE%" sn_report\run_sn_report.py %*
SET EXIT_CODE=%ERRORLEVEL%
ECHO.
ECHO ===== 退出码: %EXIT_CODE% =====
ECHO 报告与日志保存在 sn_report\output\ 目录
ECHO.
PAUSE

:END
POPD
ENDLOCAL
