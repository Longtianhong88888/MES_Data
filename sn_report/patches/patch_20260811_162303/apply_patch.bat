@echo off
chcp 65001 >nul
cd /d %~dp0
echo Applying patch %~dp0 ...
set PY=
if exist ..\python\python.exe set PY=..\python\python.exe
if not defined PY for %%F in (python python3) do (where %%F >nul 2>&1 && set PY=%%F)
if not defined PY (
  echo Python not found. Run: python apply_patch.py
  pause
  exit /b 1
)
%PY% apply_patch.py
pause
