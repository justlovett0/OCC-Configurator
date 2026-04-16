@echo off
setlocal enabledelayedexpansion

set BASH="C:\Program Files\Git\bin\bash.exe"
set SRC=%~dp0
set CONFIGURATOR=%SRC%configurator

echo ============================================================
echo  OCC Firmware Build All
echo ============================================================
echo.

:: ------------------------------------------------------------
:: 1. Wired Guitar Controller
:: ------------------------------------------------------------
echo [1/11] Building pico-guitar-controller-wired...
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
echo [2/11] Building pico-guitar-controller-wired-6fret...
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
echo [3/11] Building pico-drums-wired...
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
echo [4/11] Building pico-drums-wireless...
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
echo [5/11] Building pico-retro...
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
echo [6/11] Building pico-guitar-controller-wireless...
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
::echo [6/9] Building pico-dongle...
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
echo [8/11] Building pico-dongle-4channel...
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
echo [9/11] Building pico-pedal...
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
echo [10/11] Building pico-keyboard-macro...
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
echo [11/11] Building pico-arcadestick...
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
:: Done
:: ------------------------------------------------------------
echo ============================================================
echo  All firmware projects processed and copied to configurator folder.
echo ============================================================
goto :end

:error
echo.
echo ============================================================
echo  Build FAILED. See error above.
echo ============================================================

:end
if /i "%~1"=="NOPAUSE" exit /b 0
pause
