cmake_minimum_required(VERSION 3.13)

# ── Pico W board selection (must be before pico_sdk_init) ──
set(PICO_BOARD pico_w)

# Pull in Pico SDK (must be before project())
include(pico_sdk_import.cmake)

project(pico_guitar_dongle_4channel C CXX ASM)

set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)

# Initialize the Pico SDK
pico_sdk_init()

add_executable(pico_guitar_dongle_4channel
    src/main.c
    src/usb_descriptors.c
    src/xinput_driver.c
    src/dongle_bt.c
    src/apa102_leds.c
)

# Include directories
target_include_directories(pico_guitar_dongle_4channel PRIVATE
    ${CMAKE_CURRENT_LIST_DIR}/src
)

# Compile definitions
target_compile_definitions(pico_guitar_dongle_4channel PRIVATE
    CYW43_LWIP=0
    PICO_W_BT=1
)

# Link required libraries
target_link_libraries(pico_guitar_dongle_4channel
    pico_stdlib
    pico_unique_id
    tinyusb_device
    tinyusb_board
    hardware_gpio
    hardware_spi
    hardware_dma
    pico_cyw43_arch_poll
    pico_btstack_ble
    pico_btstack_cyw43
)

# Disable default USB and UART stdio (we use USB for XInput)
pico_enable_stdio_usb(pico_guitar_dongle_4channel 0)
pico_enable_stdio_uart(pico_guitar_dongle_4channel 0)

# Create UF2 output
pico_add_extra_outputs(pico_guitar_dongle_4channel)
