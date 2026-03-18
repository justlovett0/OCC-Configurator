@echo off
setlocal enabledelayedexpansion

set SRC=%~dp0

echo ============================================================
echo  Step 1: Build All Firmware
echo ============================================================
call "%SRC%build_all_firmware.bat" NOPAUSE
if errorlevel 1 (
    echo.
    echo ERROR: Firmware build step failed. Aborting.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  Step 2: Build Configurator EXE
echo ============================================================
call "%SRC%configurator\build_exe.bat"
if errorlevel 1 (
    echo.
    echo ERROR: Configurator build step failed.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  All steps complete.
echo ============================================================

