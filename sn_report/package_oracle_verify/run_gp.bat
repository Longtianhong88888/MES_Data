@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"

REM ===== log all output to run_gp.log too =====
del run_gp.log >nul 2>&1
echo === run_gp.bat start === >> run_gp.log

REM ===== Step 1: extract portable python if missing =====
if not exist "python\python.exe" (
  if not exist "python311.tar.gz" (
    echo [FAIL] python311.tar.gz missing here: %~dp0
    echo [FAIL] python311.tar.gz missing here: %~dp0 >> run_gp.log
    pause
    exit /b 1
  )
  echo [1/4] Extracting portable Python ...
  echo [1/4] Extracting portable Python ... >> run_gp.log
  tar -xzf python311.tar.gz -C . >> run_gp.log 2>&1
  if errorlevel 1 (
    echo [FAIL] tar extract failed.
    pause
    exit /b 1
  )
)
echo [2/4] Python OK >> run_gp.log

REM ===== Step 2: install wheels if not done =====
if not exist ".venv_ok" (
  echo [3/4] Installing offline wheels ...
  echo [3/4] Installing offline wheels ... >> run_gp.log
  python\python.exe -m pip install --no-index --find-links=wheels -r requirements.txt >> run_gp.log 2>&1
  if errorlevel 1 (
    echo [FAIL] pip install failed. See run_gp.log
    pause
    exit /b 1
  )
  echo ok > .venv_ok
)

REM ===== Step 3: run =====
set "SN_IN=%~1"
if not defined SN_IN (
  echo Enter Module SN:
  set /p SN_IN=
)
if not defined SN_IN (
  echo [FAIL] no SN entered.
  pause
  exit /b 1
)
echo [4/4] Running SN=%SN_IN% ...
echo [4/4] Running SN=%SN_IN% ... >> run_gp.log
python\python.exe oracle_download\run_gp_download.py --sn %SN_IN% >> run_gp.log 2>&1
echo.
echo Done. See run_gp.log and oracle_download\output\gp_verify
echo Done. >> run_gp.log
pause
