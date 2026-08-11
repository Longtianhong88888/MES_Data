@echo off
chcp 65001 >nul
setlocal EnableExtensions
REM ============================================================
REM  Build SN_Report Windows exe (PyInstaller onedir)
REM  Run on ANY Windows machine that can access the internet.
REM  Output: dist\SN_Report_Windows\  (exe + _internal folder)
REM  Copy that whole folder to the target PC and double-click exe.
REM ============================================================
cd /d "%~dp0.."
set "REPO_ROOT=%CD%"

REM ---- find python ----
set PYTHON_EXE=
for %%F in (python\python.exe python3\python.exe venv\Scripts\python.exe) do (
  if exist %%~F set "PYTHON_EXE=%%~F"
)
if not defined PYTHON_EXE (
  where python >nul 2>&1 && set "PYTHON_EXE=python"
)
if not defined PYTHON_EXE (
  echo [FAIL] Python not found. Install Python 3.10+ x64 first.
  pause
  exit /b 1
)
echo [1/4] Python: %PYTHON_EXE%
%PYTHON_EXE% --version

REM ---- install pyinstaller + runtime deps ----
echo [2/4] Installing pyinstaller and dependencies (needs internet) ...
%PYTHON_EXE% -m pip install --upgrade pip >nul 2>&1
%PYTHON_EXE% -m pip install pyinstaller >nul 2>&1
%PYTHON_EXE% -m pip install -r sn_report\requirements.txt >nul 2>&1
if errorlevel 1 (
  echo [FAIL] pip install failed. Check internet.
  pause
  exit /b 1
)

REM ---- build onedir ----
echo [3/4] Building exe ...
if exist sn_report\build rmdir /s /q sn_report\build
if exist sn_report\dist rmdir /s /q sn_report\dist
%PYTHON_EXE% -m PyInstaller --noconfirm --clean --onedir --windowed ^
  --name SN_Report ^
  --paths sn_report ^
  --icon "%REPO_ROOT%\sn_report\favicon.ico" ^
  --add-data "%REPO_ROOT%\sn_report\favicon.ico;." ^
  --hidden-import pg8000.native ^
  --hidden-import scramp ^
  --hidden-import gp_gui ^
  --hidden-import apple_style ^
  --hidden-import excel_report ^
  --hidden-import openpyxl ^
  --collect-submodules PyQt5 ^
  --distpath sn_report\dist ^
  --workpath sn_report\build ^
  --specpath sn_report\build ^
  sn_report\gp_gui.py
if errorlevel 1 (
  echo [FAIL] PyInstaller build failed.
  pause
  exit /b 1
)

REM ---- package ----
echo [4/4] Packaging ...
if exist "sn_report\dist\SN_Report_Windows" rmdir /s /q "sn_report\dist\SN_Report_Windows"
rename "sn_report\dist\SN_Report" "SN_Report_Windows"
echo.
echo ===== DONE =====
echo Output folder: sn_report\dist\SN_Report_Windows\
echo Copy this folder to the target Windows PC, then double-click SN_Report.exe
echo Press any key to exit ...
pause >nul
