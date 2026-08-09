@echo off
REM 以窗口方式运行 SN_Report.exe,出错时窗口不会闪退
cd /d "%~dp0"
SN_Report.exe %*
echo.
echo ===== 退出码: %ERRORLEVEL% =====
if exist "sn_report\output\*.log" (
    echo 日志文件:
    dir /b /o-d sn_report\output\*.log 2>nul
)
pause
