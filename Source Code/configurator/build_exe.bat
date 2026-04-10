@echo off
setlocal enabledelayedexpansion
echo ==========================================
echo  OCC - Open Controller Configurator
echo  Build Script
echo ==========================================
echo.

REM FIX: pushd now covers entire script, not just cleanup.
REM Previously the working directory reset after popd, so PyInstaller
REM couldn't resolve --add-data paths relative to the script folder.
pushd "%~dp0"

REM App version — read from version.txt. Edit that file before building.
set "APP_VERSION=dev"
if exist "version.txt" (
    set /p APP_VERSION=<version.txt
    echo   Building version: !APP_VERSION!
) else (
    echo   WARNING: version.txt not found - version will be "dev". Create it with your version number.
)
echo.

if exist build (
    echo Deleting build folder...
    rmdir /s /q build
)
if exist dist (
    echo Deleting dist folder...
    rmdir /s /q dist
)

echo Deleting old .spec files...
for %%S in (*.spec) do (
    echo   Removing %%S
    del /f /q "%%S"
)
echo Cleanup complete.
echo.

pip install pyserial pyinstaller Pillow

echo.
echo Scanning for .uf2 firmware files...
dir /b *.uf2 >nul 2>&1
if errorlevel 1 (
    echo   No .uf2 files found.
) else (
    for %%F in (*.uf2) do echo   - %%F
)

REM Build --add-data args, separating nuke from regular firmware
set "UF2_ARGS="
set "NUKE_ARG="
set "NUKE_FOUND="
for /f "usebackq delims=" %%A in (`dir /b *.uf2 2^>nul`) do call :check_and_append "%%A"

if not defined NUKE_FOUND (
    echo.
    echo   WARNING: resetFW.uf2 not found - Factory Reset will not work in the exe.
    echo   Place resetFW.uf2 next to this script and rebuild.
) else (
    echo   Bundling nuke: !NUKE_FOUND!
    set "NUKE_ARG=--add-data="!NUKE_FOUND!;.""
)

REM Bundle all .gif files found in this folder (firmware tile animations)
echo.
echo Scanning for .gif files...
set "GIF_ARGS="
for %%G in (*.gif) do (
    echo   Bundling GIF: %%G
    set "GIF_ARGS=!GIF_ARGS! --add-data="%%G;.""
)
if not defined GIF_ARGS (
    echo   No .gif files found.
)

REM ── Generate fw_dates.json ──────────────────────────────────────
REM Requires _gen_fw_dates.py alongside this script (shipped together).
REM For each non-nuke .uf2, reads the matching .uf2.date sidecar.
REM Falls back to file last-modified date if no sidecar exists.
echo.
echo Generating fw_dates.json...
if exist "_gen_fw_dates.py" (
    py _gen_fw_dates.py
) else (
    echo   ERROR: _gen_fw_dates.py not found next to build_exe.bat
    echo   Place it alongside this script and rebuild.
)

set "FW_DATES_ARG="
if exist "fw_dates.json" (
    set "FW_DATES_ARG=--add-data=fw_dates.json;."
    echo   fw_dates.json will be bundled.
) else (
    echo   WARNING: fw_dates.json could not be generated.
)

REM ControllerFWPresets.json — preset-to-firmware mapping for Controller Presets tab
set "FW_PRESETS_ARG="
if exist "ControllerFWPresets.json" (
    set "FW_PRESETS_ARG=--add-data=ControllerFWPresets.json;."
    echo   ControllerFWPresets.json will be bundled.
) else (
    echo   WARNING: ControllerFWPresets.json not found - Controller Presets tab will be empty.
)

REM Font folder — bundle every .ttf / .otf found in font\
set "FONT_ARGS="
if exist "font\" (
    echo.
    echo Scanning for font files in font\...
    for %%F in (font\*.ttf font\*.otf font\*.TTF font\*.OTF) do (
        if exist "%%F" (
            echo   Bundling font: %%F
            set "FONT_ARGS=!FONT_ARGS! --add-data="%%F;font""
        )
    )
    if not defined FONT_ARGS (
        echo   font\ folder exists but contains no .ttf/.otf files.
    )
) else (
    echo.
    echo   WARNING: font\ folder not found - Helvetica will not be embedded.
    echo   Create a font\ folder next to this script with the .ttf files and rebuild.
)

REM Buttons folder — bundle every .gif found in buttons\
REM These land in a "buttons" subfolder inside the EXE bundle so
REM _resource_path("buttons", "strumbar_normal.gif") resolves correctly.
set "BUTTONS_ARGS="
if exist "buttons\" (
    echo.
    echo Scanning for GIF files in buttons\...
    for %%G in (buttons\*.gif buttons\*.GIF) do (
        if exist "%%G" (
            echo   Bundling button GIF: %%G
            set "BUTTONS_ARGS=!BUTTONS_ARGS! --add-data="%%G;buttons""
        )
    )
    if not defined BUTTONS_ARGS (
        echo   buttons\ folder exists but contains no .gif files.
    )
) else (
    echo.
    echo   WARNING: buttons\ folder not found - button animations will not work.
    echo   Place the buttons\ folder next to this script and rebuild.
)

REM PresetConfigs folder — bundle all .json preset files
set "PRESET_ARGS="
if exist "PresetConfigs\" (
    echo.
    echo Scanning for preset config files in PresetConfigs\...
    for %%P in (PresetConfigs\*.json) do (
        if exist "%%P" (
            echo   Bundling preset: %%P
            set "PRESET_ARGS=!PRESET_ARGS! --add-data="%%P;PresetConfigs""
        )
    )
    if not defined PRESET_ARGS (
        echo   PresetConfigs\ folder exists but contains no .json files.
    )
) else (
    echo   No PresetConfigs\ folder found - presets will not be bundled.
)

    REM ---- GIF files ----
    for %%G in (PresetConfigs\*.gif PresetConfigs\*.GIF) do (
        if exist "%%G" (
            echo Bundling preset GIF: %%G
            set "PRESET_ARGS=!PRESET_ARGS! --add-data="%%G;PresetConfigs""
        )
    )
) else (
    echo No PresetConfigs\ folder found - presets will not be bundled.
)

REM Splash image
set "SPLASH_ARG="
for %%S in (splash.png splash.PNG splash.jpg splash.JPG) do (
    if not defined SPLASH_ARG (
        if exist "%%S" set "SPLASH_ARG=--add-data=%%S;."
    )
)

REM Startup sound
set "SOUND_ARG="
for %%A in (startup.wav startup.mp3 startup.ogg startup.flac startup.aac startup.wma) do (
    if not defined SOUND_ARG (
        if exist "%%A" set "SOUND_ARG=--add-data=%%A;."
    )
)

REM Icon
set "ICON_ARG="
set "ICON_DATA_ARG="
for %%I in (*.ico) do (
    if not defined ICON_ARG (
        set "ICON_ARG=--icon=%%I"
        set "ICON_DATA_ARG=--add-data=%%I;."
    )
)

echo.
echo Running PyInstaller...
pyinstaller --clean --onefile --windowed ^
    --name "OCC Configurator" ^
    %ICON_ARG% %ICON_DATA_ARG% ^
    %SPLASH_ARG% %SOUND_ARG% ^
    %FONT_ARGS% ^
    !BUTTONS_ARGS! ^
    !PRESET_ARGS! ^
    %UF2_ARGS% !NUKE_ARG! ^
    !GIF_ARGS! ^
    !FW_DATES_ARG! %FW_PRESETS_ARG% --add-data=version.txt;. ^
    --exclude-module numpy --exclude-module matplotlib ^
    configurator.py

echo.
echo ==========================================
if exist "dist\OCC Configurator.exe" (
    echo  SUCCESS!  dist\OCC Configurator.exe
    echo  Moving to OCC root folder...
    move /y "dist\OCC Configurator.exe" "..\..\OCC Configurator v!APP_VERSION!.exe"
    if exist "..\..\OCC Configurator v!APP_VERSION!.exe" (
        echo  Moved to OCC Configurator v!APP_VERSION!.exe
    ) else (
        echo  WARNING: Move failed, exe remains in dist\
    )
) else (
    echo  BUILD FAILED - check output above
)
echo ==========================================
popd
pause
exit /b 0

:check_and_append
REM /i flag makes this case-insensitive: resetFW.uf2, ResetFW.UF2, RESETFW.UF2 all match
if /i "%~1"=="resetFW.uf2" (
    set "NUKE_FOUND=%~1"
    exit /b 0
)
REM Regular firmware file — add to UF2_ARGS
set "UF2_ARGS=!UF2_ARGS! --add-data="%~1;.""
exit /b 0
