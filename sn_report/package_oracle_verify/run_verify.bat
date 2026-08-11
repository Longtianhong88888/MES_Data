@echo off
chcp 65001 >nul
setlocal EnableExtensions
REM ===== Oracle One-Click Verify Package =====
cd /d %~dp0

REM [1/5] Extract portable Python 3.11 if needed
if not exist "python\python.exe" (
  echo [1/5] Extracting portable Python 3.11 ...
  tar -xzf python311.tar.gz
  if %ERRORLEVEL% NEQ 0 (
    echo FAILED: python311.tar.gz missing or tar not available.
    echo Hint: Windows 10 1803+ includes tar. Or unzip it manually.
    pause
    exit /b 1
  )
)

REM [2/5] Extract Oracle Instant Client if needed
if not exist "instantclient\instantclient_19_13\oci.dll" (
  echo [2/5] Extracting Oracle Instant Client ...
  powershell -Command "Expand-Archive -Path 'instantclient\instantclient-basic-windows.x64-19.13.zip' -DestinationPath 'instantclient' -Force"
  if %ERRORLEVEL% NEQ 0 (
    echo FAILED: Instant Client extraction error.
    pause
    exit /b 1
  )
)

REM [3/5] Use bundled portable Python
SET PYTHON_EXE=python\python.exe
echo [3/5] Using Python: %PYTHON_EXE%

REM [4/5] Offline install wheels (first run only)
if not exist ".venv_ok" (
  echo [4/5] Installing offline wheels ...
  "%PYTHON_EXE%" -m pip install --no-index --find-links=wheels -r requirements.txt
  if %ERRORLEVEL% NEQ 0 (
    echo FAILED: dependency install. Check wheels/ folder or error above.
    pause
    exit /b 1
  )
  echo ok > .venv_ok
)

REM [5/5] Run verification
echo [5/5] Starting Oracle verification ...
cd oracle_download
..\%PYTHON_EXE% run_oracle_download.py --sns ..\sns.txt --conns conns.json --data-conn APO006CONN --cfg-conn MESSETCONN --instant-client ..\instantclient\instantclient_19_13 --download-dir ..\downloads
echo.
echo Done. Copy oracle_download/output/oracle_verify and downloads back for analysis.
pause
