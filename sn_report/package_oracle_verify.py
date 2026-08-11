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

    # 3) wheels(全部)+ requirements.txt(包名==版本,pip 经 --find-links 匹配)
    wheels_dir = PROJECT_DIR / "wheels"
    for w in wheels_dir.glob("*.whl"):
        shutil.copy2(w, PKG / "wheels")
    req_src = PROJECT_DIR / "wheels_requirements.txt"
    if req_src.exists():
        shutil.copy2(req_src, PKG / "requirements.txt")
    else:
        (PKG / "requirements.txt").write_text(
            "oracledb==4.0.2\nPyQt5==5.15.11\nrequests==2.34.2\n",
            encoding="utf-8",
        )
    ic_zip = wheels_dir / "instantclient-basic-windows.x64-19.13.zip"
    if ic_zip.exists():
        shutil.copy2(ic_zip, PKG / "instantclient")
    else:
        print("警告: 未找到 Windows Instant Client zip,台式机将无法连 Oracle 11g")

    # 便携 Python 3.11 x64(台式机零安装;首次运行由 run_verify.bat 自动解压)
    py_tar = Path("/private/tmp/pyportable/python311.tar.gz")
    if py_tar.exists():
        shutil.copy2(py_tar, PKG / "python311.tar.gz")
    else:
        print("警告: 未找到便携 Python tar.gz,台式机需自备 Python 3.11 x64")

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

    # 6) bat (pure ASCII + CRLF + BOM; 全相对路径,避免中文路径参数编码问题)
    bat = """@echo off
chcp 65001 >nul
setlocal EnableExtensions
REM ===== Oracle One-Click Verify Package =====
cd /d "%~dp0"

REM [1/5] Extract portable Python 3.11 if needed
if not exist "python\python.exe" (
  echo [1/5] Extracting portable Python 3.11 ...
  tar -xzf python311.tar.gz -C .
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
  if not exist "instantclient\instantclient-basic-windows.x64-19.13.zip" (
    echo FAILED: instantclient zip missing in instantclient folder.
    pause
    exit /b 1
  )
  tar -xf instantclient\instantclient-basic-windows.x64-19.13.zip -C instantclient
  if %ERRORLEVEL% NEQ 0 (
    echo FAILED: Instant Client extraction error.
    echo Hint: try unzipping instantclient zip manually with 7-Zip if tar fails.
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

REM [5/5] Run verification (cwd = package root, all relative paths)
echo [5/5] Starting Oracle verification ...
"%PYTHON_EXE%" oracle_download\\run_oracle_download.py --sns ..\sns.txt --conns oracle_download\conns.json --data-conn APO006CONN --cfg-conn MESSETCONN --instant-client instantclient\instantclient_19_13 --download-dir downloads
echo.
echo Done. Copy oracle_download/output/oracle_verify and downloads back for analysis.
pause
"""
    (PKG / "run_verify.bat").write_bytes(
        b"\xef\xbb\xbf" + bat.replace("\n", "\r\n").encode("utf-8")
    )
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
