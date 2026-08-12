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
%PYTHON_EXE% -m pip install -r NPD_EOL_FACA_Tool\requirements.txt >nul 2>&1
if errorlevel 1 (
  echo [FAIL] pip install failed. Check internet.
  pause
  exit /b 1
)

REM ---- build onedir ----
echo [3/4] Building exe ...
if exist NPD_EOL_FACA_Tool\build rmdir /s /q NPD_EOL_FACA_Tool\build
if exist NPD_EOL_FACA_Tool\dist rmdir /s /q NPD_EOL_FACA_Tool\dist
%PYTHON_EXE% -m PyInstaller --noconfirm --clean --onedir --windowed ^
  --name SN_Report ^
  --paths NPD_EOL_FACA_Tool ^
  --icon "%REPO_ROOT%\NPD_EOL_FACA_Tool\favicon.ico" ^
  --add-data "%REPO_ROOT%\NPD_EOL_FACA_Tool\favicon.ico;." ^
  --hidden-import pg8000.native ^
  --hidden-import scramp ^
  --hidden-import gp_gui ^
  --hidden-import apple_style ^
  --hidden-import excel_report ^
  --hidden-import openpyxl ^
  --hidden-import sfc_app007 ^
  --hidden-import sn_info ^
  --hidden-import commonality_data ^
  --hidden-import commonality_analysis ^
  --hidden-import commonality_ppt ^
  --collect-submodules PyQt5 ^
  --distpath NPD_EOL_FACA_Tool\dist ^
  --workpath NPD_EOL_FACA_Tool\build ^
  --specpath NPD_EOL_FACA_Tool\build ^
  NPD_EOL_FACA_Tool\gp_gui.py
if errorlevel 1 (
  echo [FAIL] PyInstaller build failed.
  pause
  exit /b 1
)

REM ---- package ----
echo [4/4] Packaging ...
if exist "NPD_EOL_FACA_Tool\dist\SN_Report_Windows" rmdir /s /q "NPD_EOL_FACA_Tool\dist\SN_Report_Windows"
rename "NPD_EOL_FACA_Tool\dist\SN_Report" "SN_Report_Windows"
echo.
echo ===== DONE =====
echo Output folder: NPD_EOL_FACA_Tool\dist\SN_Report_Windows\
echo Copy this folder to the target Windows PC, then double-click SN_Report.exe
echo Press any key to exit ...
pause >nul
