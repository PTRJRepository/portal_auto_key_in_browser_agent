@echo off
chcp 65001 >nul
cd /d "D:\Gawean Rebinmas\Browser_Auto_key_in new\Auto Key In Refactor"
echo ============================================
echo         AUTO KEY-IN - DEV MODE
echo ============================================
echo.

:: Check Python paths
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] Using fallback Python path...
    set PYTHONPATH=D:\Gawean Rebinmas\Browser_Auto_key_in new\Auto Key In Refactor
    "C:\Users\nbgmf\AppData\Local\Microsoft\WindowsApps\python.exe" -m app
) else (
    python -m app
)
pause
