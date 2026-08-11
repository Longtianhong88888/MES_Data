@echo off
chcp 65001 >nul
REM Oracle 一键下载验证包 - 内网台式机运行
cd /d %~dp0

REM 1. 解压便携 Python 3.11(若未解压;Windows 10 1803+ 自带 tar)
if not exist "python\python.exe" (
  echo [1/5] 解压便携 Python 3.11 ...
  tar -xzf python311.tar.gz
  if %ERRORLEVEL% NEQ 0 (
    echo 便携 Python 解压失败,请确认 python311.tar.gz 存在且系统支持 tar。
    pause
    exit /b 1
  )
)

REM 2. 解压 Instant Client(若未解压)
if not exist "instantclient\instantclient_19_13\oci.dll" (
  echo [2/5] 解压 Oracle Instant Client ...
  powershell -Command "Expand-Archive -Path 'instantclient\instantclient-basic-windows.x64-19.13.zip' -DestinationPath 'instantclient' -Force"
)

REM 3. 使用项目内置便携 Python(免安装,不依赖系统 Python)
SET PYTHON_EXE=python\python.exe
echo [3/5] 使用 Python: %PYTHON_EXE%

REM 4. 离线安装 wheels(仅首次)
if not exist ".venv_ok" (
  echo [4/5] 离线安装依赖(wheels)...
  "%PYTHON_EXE%" -m pip install --no-index --find-links=wheels -r requirements.txt
  if %ERRORLEVEL% NEQ 0 (
    echo 依赖安装失败,请确认 wheels 目录完整或查看上方错误。
    pause
    exit /b 1
  )
  echo ok > .venv_ok
)

REM 5. 运行验证
echo [5/5] 开始 Oracle 一键下载验证 ...
cd oracle_download
..\%PYTHON_EXE% run_oracle_download.py --sns ..\sns.txt --conns conns.json --data-conn APO006CONN --cfg-conn MESSETCONN --instant-client ..\instantclient\instantclient_19_13 --download-dir ..\downloads
echo.
echo 验证完成。请把 verify_output 和 downloads 目录拷回分析。
pause
