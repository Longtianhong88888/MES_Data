@echo off
chcp 65001 >nul
cd /d %~dp0
echo 应用补丁 %~dp0 ...
for %%F in (..\python\python.exe ..\python3\python.exe python python3) do (
  where %%F >nul 2>&1 && set PY=%%F && goto FOUND
)
:FOUND
if not defined PY (
  echo 未找到 Python,请用 python apply_patch.py 手动应用。
  pause
  exit /b 1
)
%PY% apply_patch.py
pause
