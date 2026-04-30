@echo off
setlocal enabledelayedexpansion

set BASH="C:\Program Files\Git\bin\bash.exe"
set SRC=%~dp0
set CONFIGURATOR=%SRC%configurator
set ESP_IDF_PATH=%IDF_PATH%
if not defined ESP_IDF_PATH if exist "C:\esp\v6.0.1\esp-idf\tools\idf.py" set ESP_IDF_PATH=C:\esp\v6.0.1\esp-idf

set ESP_TOOLS_PATH=%IDF_TOOLS_PATH%
if not defined ESP_TOOLS_PATH if exist "C:\Espressif\tools" set ESP_TOOLS_PATH=C:\Espressif\tools

set ESP_PYTHON_ENV=%IDF_PYTHON_ENV_PATH%
if not defined ESP_PYTHON_ENV if defined ESP_TOOLS_PATH if exist "%ESP_TOOLS_PATH%\python\v6.0.1\venv\Scripts\python.exe" set ESP_PYTHON_ENV=%ESP_TOOLS_PATH%\python\v6.0.1\venv

set ESP_PYTHON=%ESP_PYTHON_ENV%\Scripts\python.exe

if not defined ESP_ROM_ELF_DIR if defined ESP_TOOLS_PATH if exist "%ESP_TOOLS_PATH%\esp-rom-elfs\20241011" set ESP_ROM_ELF_DIR=%ESP_TOOLS_PATH%\esp-rom-elfs\20241011\
if not defined ESP_IDF_VERSION if defined ESP_IDF_PATH set ESP_IDF_VERSION=6.0.1

if defined ESP_IDF_PATH set IDF_PATH=%ESP_IDF_PATH%
if defined ESP_TOOLS_PATH set IDF_TOOLS_PATH=%ESP_TOOLS_PATH%
if defined ESP_PYTHON_ENV set IDF_PYTHON_ENV_PATH=%ESP_PYTHON_ENV%

if defined ESP_TOOLS_PATH if exist "%ESP_TOOLS_PATH%\cmake\4.0.3\bin" set "PATH=%ESP_TOOLS_PATH%\cmake\4.0.3\bin;%PATH%"
if defined ESP_TOOLS_PATH if exist "%ESP_TOOLS_PATH%\ninja\1.12.1" set "PATH=%ESP_TOOLS_PATH%\ninja\1.12.1;%PATH%"
if defined ESP_TOOLS_PATH if exist "%ESP_TOOLS_PATH%\idf-exe\1.0.3" set "PATH=%ESP_TOOLS_PATH%\idf-exe\1.0.3;%PATH%"
if defined ESP_TOOLS_PATH if exist "%ESP_TOOLS_PATH%\xtensa-esp-elf\esp-15.2.0_20251204\xtensa-esp-elf\bin" set "PATH=%ESP_TOOLS_PATH%\xtensa-esp-elf\esp-15.2.0_20251204\xtensa-esp-elf\bin;%PATH%"
if defined ESP_TOOLS_PATH if exist "%ESP_TOOLS_PATH%\riscv32-esp-elf\esp-15.2.0_20251204\riscv32-esp-elf\bin" set "PATH=%ESP_TOOLS_PATH%\riscv32-esp-elf\esp-15.2.0_20251204\riscv32-esp-elf\bin;%PATH%"
if exist "%ESP_PYTHON%" set "PATH=%ESP_PYTHON_ENV%\Scripts;%PATH%"

echo ============================================================
echo  OCC Firmware Build All
echo ============================================================
echo.

:: ------------------------------------------------------------
:: 1. Wired Guitar Controller
:: ------------------------------------------------------------
echo [1/12] Building pico-guitar-controller-wired...
cd /d "%SRC%pico-guitar-controller-wired"
%BASH% -c "rm -rf build && mkdir build && cd build && cmake -G Ninja .. && ninja"
if errorlevel 1 (
    echo ERROR: pico-guitar-controller-wired build FAILED.
    goto :error
)

echo Copying Wired Guitar Controller firmware...
copy /Y "build\pico_guitar_controller.uf2" "%CONFIGURATOR%\Wired_Guitar_Controller.uf2"
copy /Y "build\pico_guitar_controller.uf2.date" "%CONFIGURATOR%\Wired_Guitar_Controller.uf2.date"
echo   OK
echo.

:: ------------------------------------------------------------
:: 2. Wired Guitar Controller 6-Fret
:: ------------------------------------------------------------
echo [2/12] Building pico-guitar-controller-wired-6fret...
cd /d "%SRC%pico-guitar-controller-wired-6fret"
%BASH% -c "rm -rf build && mkdir build && cd build && cmake -G Ninja .. && ninja"
if errorlevel 1 (
    echo ERROR: pico-guitar-controller-wired-6fret build FAILED.
    goto :error
)

echo Copying Wired Guitar Controller 6-Fret firmware...
copy /Y "build\pico_guitar_controller_6fret.uf2" "%CONFIGURATOR%\Wired_Guitar_Controller_6Fret.uf2"
copy /Y "build\pico_guitar_controller_6fret.uf2.date" "%CONFIGURATOR%\Wired_Guitar_Controller_6Fret.uf2.date"
echo   OK
echo.

:: ------------------------------------------------------------
:: 3. Wired Drum Controller
:: ------------------------------------------------------------
echo [3/12] Building pico-drums-wired...
cd /d "%SRC%pico-drums-wired"
%BASH% -c "rm -rf build && mkdir build && cd build && cmake -G Ninja .. && ninja"
if errorlevel 1 (
    echo ERROR: pico-drums-wired build FAILED.
    goto :error
)

echo Copying Wired Drum Controller firmware...
copy /Y "build\pico_drum_controller.uf2" "%CONFIGURATOR%\Wired_Drum_Controller.uf2"
copy /Y "build\pico_drum_controller.uf2.date" "%CONFIGURATOR%\Wired_Drum_Controller.uf2.date"
echo   OK
echo.

:: ------------------------------------------------------------
:: 4. Wireless Drum Controller
:: ------------------------------------------------------------
echo [4/12] Building pico-drums-wireless...
cd /d "%SRC%pico-drums-wireless"
%BASH% -c "rm -rf build && mkdir build && cd build && cmake -G Ninja .. && ninja"
if errorlevel 1 (
    echo ERROR: pico-drums-wireless build FAILED.
    goto :error
)

echo Copying Wireless Drum Controller firmware...
copy /Y "build\pico_drum_controller_bt.uf2" "%CONFIGURATOR%\Wireless_Drum_Controller.uf2"
copy /Y "build\pico_drum_controller_bt.uf2.date" "%CONFIGURATOR%\Wireless_Drum_Controller.uf2.date"
echo   OK
echo.

:: ------------------------------------------------------------
:: 5. Wired Retro Controller
:: ------------------------------------------------------------
echo [5/12] Building pico-retro...
cd /d "%SRC%pico-retro"
%BASH% -c "rm -rf build && mkdir build && cd build && cmake -G Ninja .. && ninja"
if errorlevel 1 (
    echo ERROR: pico-retro build FAILED.
    goto :error
)

echo Copying Wired Retro Controller firmware...
copy /Y "build\Retro_Controller.uf2" "%CONFIGURATOR%\Wired_Retro_Controller.uf2"
copy /Y "build\Retro_Controller.uf2.date" "%CONFIGURATOR%\Wired_Retro_Controller.uf2.date"
echo   OK
echo.

:: ------------------------------------------------------------
:: 6. Wireless Guitar Controller
:: ------------------------------------------------------------
echo [6/12] Building pico-guitar-controller-wireless...
cd /d "%SRC%pico-guitar-controller-wireless"
%BASH% -c "rm -rf build && mkdir build && cd build && cmake -G Ninja .. && ninja"
if errorlevel 1 (
    echo ERROR: pico-guitar-controller-wireless build FAILED.
    goto :error
)

echo Copying Wireless Guitar Controller firmware...
copy /Y "build\pico_guitar_controller_bt.uf2" "%CONFIGURATOR%\Wireless_Guitar_Controller.uf2"
copy /Y "build\pico_guitar_controller_bt.uf2.date" "%CONFIGURATOR%\Wireless_Guitar_Controller.uf2.date"
echo   OK
echo.

:: ------------------------------------------------------------
:: 7. Wireless Dongle
:: ------------------------------------------------------------
::echo [6/12] Building pico-dongle...
::cd /d "%SRC%pico-dongle"
::%BASH% -c "rm -rf build && mkdir build && cd build && cmake -G Ninja .. && ninja"
::if errorlevel 1 (
::    echo ERROR: pico-dongle build FAILED.
::    goto :error
::)
::
echo Copying Wireless Dongle firmware...
::copy /Y "build\pico_guitar_dongle.uf2" "%CONFIGURATOR%\Wireless_Dongle.uf2"
echo   OK
echo.

:: ------------------------------------------------------------
:: 8. Wireless Dongle 4-Channel
:: ------------------------------------------------------------
echo [8/12] Building pico-dongle-4channel...
cd /d "%SRC%pico-dongle-4channel"
%BASH% -c "rm -rf build && mkdir build && cd build && cmake -G Ninja .. && ninja"
if errorlevel 1 (
    echo ERROR: pico-dongle-4channel build FAILED.
    goto :error
)

echo Copying Wireless Dongle 4-Channel firmware...
copy /Y "build\pico_guitar_dongle_4channel.uf2" "%CONFIGURATOR%\Wireless_Dongle_4Channel.uf2"
echo   OK
echo.

:: ------------------------------------------------------------
:: 9. Pedal Controller
:: ------------------------------------------------------------
echo [9/12] Building pico-pedal...
cd /d "%SRC%pico-pedal"
%BASH% -c "rm -rf build && mkdir build && cd build && cmake -G Ninja .. && ninja"
if errorlevel 1 (
    echo ERROR: pico-pedal build FAILED.
    goto :error
)

echo Copying Pedal Controller firmware...
copy /Y "build\pico_pedal_controller.uf2" "%CONFIGURATOR%\Pedal_Accessory.uf2"
copy /Y "build\pico_pedal_controller.uf2.date" "%CONFIGURATOR%\Pedal_Accessory.uf2.date"
echo   OK
echo.

:: ------------------------------------------------------------
:: 10. Keyboard Macro Pad
:: ------------------------------------------------------------
echo [10/12] Building pico-keyboard-macro...
cd /d "%SRC%pico-keyboard-macro"
%BASH% -c "rm -rf build && mkdir build && cd build && cmake -G Ninja .. && ninja"
if errorlevel 1 (
    echo ERROR: pico-keyboard-macro build FAILED.
    goto :error
)

echo Copying Keyboard Macro Pad firmware...
copy /Y "build\pico_keyboard_macro.uf2" "%CONFIGURATOR%\Keyboard_Macro_Pad.uf2"
copy /Y "build\pico_keyboard_macro.uf2.date" "%CONFIGURATOR%\Keyboard_Macro_Pad.uf2.date"
echo   OK
echo.

:: ------------------------------------------------------------
:: 11. Arcade Stick
:: ------------------------------------------------------------
echo [11/12] Building pico-arcadestick...
cd /d "%SRC%pico-arcadestick"
%BASH% -c "rm -rf build && mkdir build && cd build && cmake -G Ninja .. && ninja"
if errorlevel 1 (
    echo ERROR: pico-arcadestick build FAILED.
    goto :error
)

echo Copying Arcade Stick firmware...
copy /Y "build\ArcadeStick_Controller.uf2" "%CONFIGURATOR%\Wired_ArcadeStick_Controller.uf2"
copy /Y "build\ArcadeStick_Controller.uf2.date" "%CONFIGURATOR%\Wired_ArcadeStick_Controller.uf2.date"
echo   OK
echo.

:: ------------------------------------------------------------
:: 12. ESP32-S3 Wireless Dongle 3-Channel
:: ------------------------------------------------------------
echo [12/12] Building esp32-dongle-3channel...
call :build_esp32 "esp32-dongle-3channel" "ESP32-S3 Wireless Dongle 3-Channel" "esp32_dongle_3channel.bin" "Wireless_Dongle_3Channel_ESP32"
if errorlevel 1 goto :error

:: ------------------------------------------------------------
:: Done
:: ------------------------------------------------------------
echo ============================================================
echo  All firmware projects processed and copied to configurator folder.
echo ============================================================
goto :end

:build_esp32
if not exist "%ESP_IDF_PATH%\tools\idf.py" (
    echo ERROR: ESP-IDF not found. Set IDF_PATH or install it under C:\esp\v6.0.1\esp-idf.
    exit /b 1
)
if not exist "%ESP_PYTHON%" (
    echo ERROR: ESP-IDF Python environment not found. Set IDF_PYTHON_ENV_PATH or install the ESP tools.
    exit /b 1
)

echo Building %~2...
cd /d "%SRC%%~1"
if exist build rmdir /s /q build
"%ESP_PYTHON%" "%ESP_IDF_PATH%\tools\idf.py" set-target esp32s3
if errorlevel 1 (
    echo ERROR: %~1 target setup FAILED.
    exit /b 1
)

"%ESP_PYTHON%" "%ESP_IDF_PATH%\tools\idf.py" build
if errorlevel 1 (
    echo ERROR: %~1 build FAILED.
    exit /b 1
)

echo Copying %~2 firmware...
copy /Y "build\%~3" "%CONFIGURATOR%\%~4.bin" >nul
copy /Y "build\bootloader\bootloader.bin" "%CONFIGURATOR%\%~4_bootloader.bin" >nul
copy /Y "build\partition_table\partition-table.bin" "%CONFIGURATOR%\%~4_partition-table.bin" >nul
copy /Y "build\flash_args" "%CONFIGURATOR%\%~4.flash_args" >nul
copy /Y "build\flasher_args.json" "%CONFIGURATOR%\%~4.flasher_args.json" >nul
echo   OK
echo.
exit /b 0

:error
echo.
echo ============================================================
echo  Build FAILED. See error above.
echo ============================================================

:end
if /i "%~1"=="NOPAUSE" exit /b 0
pause
