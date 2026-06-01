@echo off
chcp 65001 >nul
title Auto Key-In - PlantwareP3
cd /d "D:\Gawean Rebinmas\Browser_Auto_key_in new\Auto Key In Refactor"

echo.
echo ============================================
echo         AUTO KEY-IN - PLANTWAREP3
echo ============================================
echo.

:: Gunakan Python 3.10 yang sudah terinstall PySide6
"C:\Users\nbgmf\AppData\Local\Microsoft\WindowsApps\python.exe" -m app

if errorlevel 1 (
    echo.
    echo ERROR: Aplikasi gagal dijalankan.
    echo Pastikan tidak ada error di atas.
)
pause
