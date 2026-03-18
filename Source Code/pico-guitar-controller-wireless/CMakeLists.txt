cmake_minimum_required(VERSION 3.13)

# ── Pico W board selection (must be before pico_sdk_init) ──
set(PICO_BOARD pico_w)

# Pull in Pico SDK (must be before project())
include(pico_sdk_import.cmake)

project(pico_guitar_controller_bt C CXX ASM)

set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)

# Initialize the Pico SDK
pico_sdk_init()

add_executable(pico_guitar_controller_bt
    src/main.c
    src/usb_descriptors.c
    src/xinput_driver.c
    src/guitar_config.c
    src/config_serial.c
    src/apa102_leds.c
    src/adxl345.c
    src/lis3dh.c
    src/bt_hid_gamepad.c
    src/controller_bt.c
)

# Include directories
target_include_directories(pico_guitar_controller_bt PRIVATE
    ${CMAKE_CURRENT_LIST_DIR}/src
)

# Compile definitions
target_compile_definitions(pico_guitar_controller_bt PRIVATE
    CYW43_LWIP=0
    PICO_W_BT=1
)

# Link required libraries
target_link_libraries(pico_guitar_controller_bt
    pico_stdlib
    pico_unique_id
    tinyusb_device
    tinyusb_board
    hardware_flash
    hardware_sync
    hardware_adc
    hardware_gpio
    hardware_spi
    hardware_dma
    hardware_watchdog
    hardware_i2c
    pico_bootrom
    pico_cyw43_arch_poll
    pico_btstack_ble
    pico_btstack_cyw43
    pico_btstack_flash_bank
)

# ── Build date: embedded in firmware and written to a sidecar .date file ──
string(TIMESTAMP BUILD_MONTH "%b")
string(TIMESTAMP BUILD_DAY   "%d")
string(TIMESTAMP BUILD_YEAR  "%Y")
set(BUILD_DATE_STR "${BUILD_MONTH} ${BUILD_DAY} ${BUILD_YEAR}")
target_compile_definitions(pico_guitar_controller_bt PRIVATE
    BUILD_DATE_STR="${BUILD_DATE_STR}"
)

# Disable default USB and UART stdio (we use USB for XInput/CDC)
pico_enable_stdio_usb(pico_guitar_controller_bt 0)
pico_enable_stdio_uart(pico_guitar_controller_bt 0)

# Create UF2 output
pico_add_extra_outputs(pico_guitar_controller_bt)

# Write a .uf2.date sidecar so the configurator build script can read it
add_custom_command(TARGET pico_guitar_controller_bt POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E echo "${BUILD_DATE_STR}"
        > "$<TARGET_FILE_DIR:pico_guitar_controller_bt>/pico_guitar_controller_bt.uf2.date"
    COMMENT "Writing firmware build date sidecar: ${BUILD_DATE_STR}"
)