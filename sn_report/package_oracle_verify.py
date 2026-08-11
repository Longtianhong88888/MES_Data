#!/usr/bin/env python3
"""打包 Oracle 一键下载验证包(拷到内网台式机运行)。

产物: sn_report/package_oracle_verify/
    run_verify.bat                  一键运行(自动解压 Instant Client + 装 wheels)
    sns.txt                         待验证 SN 列表
    verify_config.json              台式机侧配置(连接名/时间窗/下载目录)
    oracle_download/run_oracle_download.py
    oracle_download/lib/oracle_client.py, config.py, __init__.py
    oracle_download/conns.json      解密后的连接(含 APO006CONN)
    wheels/                         oracledb + 全部离线依赖
    instantclient/                  Windows x64 Instant Client 19.13 (zip)
"""
from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

SN_REPORT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SN_REPORT_DIR.parent
PKG = SN_REPORT_DIR / "package_oracle_verify"


def main() -> None:
    if PKG.exists():
        shutil.rmtree(PKG)
    (PKG / "oracle_download" / "lib").mkdir(parents=True, exist_ok=True)
    (PKG / "wheels").mkdir(parents=True, exist_ok=True)
    (PKG / "instantclient").mkdir(parents=True, exist_ok=True)

    # 1) 主脚本 + lib
    shutil.copy2(SN_REPORT_DIR / "run_oracle_download.py", PKG / "oracle_download")
    for f in ("oracle_client.py", "config.py", "__init__.py",
              "login_dialog.py", "rayprush_auth.py"):
        shutil.copy2(SN_REPORT_DIR / "lib" / f, PKG / "oracle_download" / "lib")

    # 2) 解密连接(含 APO006CONN)
    conns_src = PROJECT_DIR / "reference" / "lth" / "cimtool_conns_decrypted.json"
    shutil.copy2(conns_src, PKG / "oracle_download" / "conns.json")

    # 3) wheels(全部)
    wheels_dir = PROJECT_DIR / "wheels"
    wheel_files = []
    for w in wheels_dir.glob("*.whl"):
        shutil.copy2(w, PKG / "wheels")
        wheel_files.append(w.name)
    (PKG / "requirements.txt").write_text(
        "\n".join(wheel_files) + "\n", encoding="utf-8"
    )
    ic_zip = wheels_dir / "instantclient-basic-windows.x64-19.13.zip"
    if ic_zip.exists():
        shutil.copy2(ic_zip, PKG / "instantclient")
    else:
        print("警告: 未找到 Windows Instant Client zip,台式机将无法连 Oracle 11g")

    # 4) 台式机配置
    cfg = {
        "conns": "conns.json",
        "cfg_conn": "MESSETCONN",
        "data_conn": "APO006CONN",
        "instant_client": "instantclient",
        "analysis_window": {"start": "2026-06-01 00:00", "end": "2026-08-08 23:59"},
        "download_dir": "downloads",
    }
    (PKG / "verify_config.json").write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 5) SN 列表(示例)
    (PKG / "sns.txt").write_text(
        "# 每行一个 Module SN,验证完成后把 verify_output/ 整个拷回来\n"
        "DNMHTV000F50000Y2N+2001+Q\n",
        encoding="utf-8",
    )

    # 6) bat
    bat = r"""@echo off
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
"""
    (PKG / "run_verify.bat").write_text(bat, encoding="utf-8")

    # 7) 验证记录输出目录说明
    (PKG / "README.txt").write_text(
        "Oracle 一键下载验证包\n"
        "=====================\n"
        "1. 双击 run_verify.bat(或命令行运行)\n"
        "2. 脚本会: 解压 Instant Client -> 装 wheels -> 读 sns.txt 逐 SN 查询下载\n"
        "3. 完成后把本目录的 oracle_download/verify_output 和 downloads 整个拷回分析\n"
        "   (verify_output 在 oracle_download/output/oracle_verify/ 下,含 verify.json 和 run.log)\n"
        "4. sns.txt 每行一个 Module SN,可直接修改\n",
        encoding="utf-8",
    )

    print(f"打包完成: {PKG}")


if __name__ == "__main__":
    main()
