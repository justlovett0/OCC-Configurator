cmake_minimum_required(VERSION 3.13)

# Pull in Pico SDK (must be before project())
include(pico_sdk_import.cmake)

project(pico_pedal_controller C CXX ASM)

set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)

# Initialize the Pico SDK
pico_sdk_init()

set(PICO_PIO_USB_LOCAL "${CMAKE_CURRENT_LIST_DIR}/lib/Pico-PIO-USB")
if(NOT EXISTS ${PICO_PIO_USB_LOCAL}/CMakeLists.txt)
    message(FATAL_ERROR
        "Pico-PIO-USB not found at ${PICO_PIO_USB_LOCAL}\n"
        "Download https://github.com/sekigon-gonnoc/Pico-PIO-USB/archive/refs/tags/0.7.2.zip "
        "and extract it to lib/Pico-PIO-USB/")
endif()
add_subdirectory(${PICO_PIO_USB_LOCAL} pico_pio_usb)

# ── Pico-PIO-USB: provides USB host capability via PIO ──
# Using local copy to avoid FetchContent re-configure loop.
# Download 0.7.2 from https://github.com/sekigon-gonnoc/Pico-PIO-USB/releases
# and place it at lib/Pico-PIO-USB/ in this project root.
add_executable(pico_pedal_controller
    src/main.c
    src/usb_descriptors.c
    src/xinput_driver.c
    src/xinput_host.c
    src/hcd_pio_usb_debug.c
    src/apa102_leds.c
    src/pedal_config.c
    src/pedal_config_serial.c
)

# Include directories
target_include_directories(pico_pedal_controller PRIVATE
    ${CMAKE_CURRENT_LIST_DIR}/src
)

# Link required libraries
target_link_libraries(pico_pedal_controller
    pico_stdlib
    pico_unique_id
    pico_multicore
    tinyusb_device
    tinyusb_host
    tinyusb_board
    pico_pio_usb
    hardware_flash
    hardware_sync
    hardware_gpio
    hardware_adc
    hardware_watchdog
    hardware_spi
    hardware_dma
    pico_bootrom
)

# ── Build date: embedded in firmware and written to a sidecar .date file ──
string(TIMESTAMP BUILD_MONTH "%b")
string(TIMESTAMP BUILD_DAY   "%d")
string(TIMESTAMP BUILD_YEAR  "%Y")
set(BUILD_DATE_STR "${BUILD_MONTH} ${BUILD_DAY} ${BUILD_YEAR}")
target_compile_definitions(pico_pedal_controller PRIVATE
    BUILD_DATE_STR="${BUILD_DATE_STR}"
    PIO_USB_USE_TINYUSB=1
)

set(PEDAL_HOST_DEBUG OFF CACHE BOOL "Enable pedal USB host CDC debug output" FORCE)
if(PEDAL_HOST_DEBUG)
    target_compile_definitions(pico_pedal_controller PRIVATE PEDAL_HOST_DEBUG=1)
endif()

# ── Debug LED support (troubleshooting only) ──
# Displays USB host connection status on the APA102 LEDs (GP6=SCK, GP7=MOSI).
# Change ON → OFF (or remove block) to revert. Zero APA102 code compiled when OFF.
set(PEDAL_LED_DEBUG OFF CACHE BOOL "Show USB host status on APA102 LEDs" FORCE)
if(PEDAL_LED_DEBUG)
    target_compile_definitions(pico_pedal_controller PRIVATE PEDAL_LED_DEBUG=1)
endif()

# Disable default USB and UART stdio (we use USB for XInput/CDC)
pico_enable_stdio_usb(pico_pedal_controller 0)
pico_enable_stdio_uart(pico_pedal_controller 0)

# Create UF2 output
pico_add_extra_outputs(pico_pedal_controller)

# Write a .uf2.date sidecar so the configurator build script can read it
add_custom_command(TARGET pico_pedal_controller POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E echo "${BUILD_DATE_STR}"
        > "$<TARGET_FILE_DIR:pico_pedal_controller>/pico_pedal_controller.uf2.date"
    COMMENT "Writing firmware build date sidecar: ${BUILD_DATE_STR}"
)
