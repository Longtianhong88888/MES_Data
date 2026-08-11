@echo off
chcp 65001 >nul
REM Oracle 一键下载验证包 - 内网台式机运行
cd /d %~dp0

REM 1. 解压 Instant Client(若未解压)
if not exist "instantclient\instantclient_19_13\oci.dll" (
  echo [1/4] 解压 Oracle Instant Client ...
  powershell -Command "Expand-Archive -Path 'instantclient\instantclient-basic-windows.x64-19.13.zip' -DestinationPath 'instantclient' -Force"
)

REM 2. 找 Python
set PYTHON_EXE=
for %%F in (python\python.exe python3\python.exe python310\python.exe ..\python\python.exe ..\python3\python.exe) do (
  if exist %%~F set "PYTHON_EXE=%%~F"
)
if not defined PYTHON_EXE (
  where python >nul 2>&1
  if %ERRORLEVEL% EQU 0 set "PYTHON_EXE=python"
)
if not defined PYTHON_EXE (
  echo 未找到 Python。请把 Python 3.11 x64 放到项目 python\ 目录或安装到 PATH。
  pause
  exit /b 1
)
echo [2/4] 使用 Python: %PYTHON_EXE%

REM 3. 离线安装 wheels(仅首次)
if not exist ".venv_ok" (
  echo [3/4] 离线安装依赖(wheels)...
  "%PYTHON_EXE%" -m pip install --no-index --find-links=wheels -r requirements.txt >nul 2>&1
  if %ERRORLEVEL% NEQ 0 (
    echo 依赖安装失败,请确认 wheels 目录完整。
    pause
    exit /b 1
  )
  echo ok > .venv_ok
)

REM 4. 运行验证
echo [4/4] 开始 Oracle 一键下载验证 ...
cd oracle_download
"%PYTHON_EXE%" run_oracle_download.py --sns ..\sns.txt --conns conns.json --data-conn APO006CONN --cfg-conn MESSETCONN --instant-client ..\instantclient\instantclient_19_13 --download-dir ..\downloads
echo.
echo 验证完成。请把 verify_output 和 downloads 目录拷回分析。
pause
