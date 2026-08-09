@echo off
REM 把 sn_report 打成 Windows 免安装 exe(需要在一台能联网且装有 Python 的 Windows 机器上执行)
REM 用法: 双击本脚本,或 build_windows.bat
REM 产物: sn_report\dist\SN_Report.exe —— 拷到 VM 的 MES_Data 根目录,双击即可运行
REM 注意: 该机器只是"打包机";打好的 exe 自带 Python 3.x 运行时,VM 系统不会删除 exe

SETLOCAL ENABLEDELAYEDEXPANSION
SET PROJECT_DIR=%~dp0..
PUSHD %PROJECT_DIR%

SET PYTHON_EXE=
for %%F in (
    "python\python.exe"
    "python3\python.exe"
    "python310\python.exe"
    "venv\Scripts\python.exe"
    "Env\Scripts\python.exe"
    "..\python\python.exe"
    "..\python3\python.exe"
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

ECHO 未找到 Python。打包机需要先安装 Python 3.9+。
PAUSE
GOTO END

:FOUND_PYTHON
ECHO 使用 Python: %PYTHON_EXE%
ECHO 安装打包依赖(首次需要联网)...
"%PYTHON_EXE%" -m pip install --upgrade pip
"%PYTHON_EXE%" -m pip install pyinstaller
"%PYTHON_EXE%" -m pip install -r requirements.txt
IF %ERRORLEVEL% NEQ 0 (
    ECHO 依赖安装失败,请检查网络。
    PAUSE
    GOTO END
)

ECHO 开始打包...
cd sn_report
"%PYTHON_EXE%" -m PyInstaller --noconfirm --onefile ^
    --name SN_Report ^
    --distpath dist ^
    --workpath build ^
    --specpath build ^
    --hidden-import PIL ^
    --hidden-import openpyxl ^
    --hidden-import xlsxwriter ^
    sn_report.py
cd ..

ECHO.
ECHO ===== 打包完成 =====
ECHO 产物: sn_report\dist\SN_Report.exe
ECHO 拷贝 SN_Report.exe 到 VM 的 MES_Data 根目录(与 sn_report\ 同级),然后:
ECHO   双击运行,或命令行: SN_Report.exe --sns sns.txt
ECHO.
PAUSE

:END
POPD
ENDLOCAL
