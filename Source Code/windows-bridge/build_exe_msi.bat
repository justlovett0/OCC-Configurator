@echo off
setlocal enabledelayedexpansion

set BRIDGE=%~dp0

echo ============================================================
echo  OCC Bridge -- Build and Package
echo ============================================================
echo.
echo This will publish OccBridge.App and OccBridge.Install,
echo build the MSI and the full Setup bundle.
echo.
echo Prerequisites required in OccBridge.Install\Prerequisites\:
echo   ViGEmBus_1.22.0.exe
echo   HidHide_1.5.230.exe
echo.

:: Optional: pass a version override as the first argument.
:: If omitted, the build script derives the version from the build date (YY.M.D).
set VERSION_ARG=
if not "%~1"=="" (
    set VERSION_ARG=-Version "%~1"
    echo Version override: %~1
) else (
    echo Version will be set from build date.
)
echo.

powershell -ExecutionPolicy Bypass -File "%BRIDGE%build\Publish-OCCBridgeSetup.ps1" !VERSION_ARG!
if errorlevel 1 (
    echo.
    echo ERROR: Publish script failed. See output above.
    pause
    exit /b 1
)

set SETUP_SRC=%BRIDGE%artifacts\bundle\OCCBridgeSetup.exe
set SETUP_DST=%BRIDGE%..\..\OCC Bridge Setup.exe

if exist "%SETUP_SRC%" (
    echo Copying setup to OCC root folder...
    copy /y "%SETUP_SRC%" "%SETUP_DST%"
    if exist "%SETUP_DST%" (
        echo   Copied to OCC Bridge Setup.exe
    ) else (
        echo   WARNING: Copy failed, setup remains in artifacts\bundle\
    )
) else (
    echo   WARNING: Could not find OCCBridgeSetup.exe to copy
)

echo.
echo ============================================================
echo  Done!
echo    %BRIDGE%artifacts\installer\OccBridge.Package.msi
echo    %BRIDGE%artifacts\bundle\OCCBridgeSetup.exe
echo    %SETUP_DST%
echo ============================================================
echo.
pause
