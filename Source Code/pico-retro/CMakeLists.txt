cmake_minimum_required(VERSION 3.13)

# ── Wireless/Pico W option (must be set before pico_sdk_init) ──
option(PICO_RETRO_WIRELESS "Build for Pico W with wireless scaffold" OFF)
if(PICO_RETRO_WIRELESS)
    set(PICO_BOARD pico_w)
endif()

# Pull in Pico SDK (must be before project())
include(pico_sdk_import.cmake)

project(pico_retro_controller C CXX ASM)

set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)

# Initialize the Pico SDK
pico_sdk_init()

add_executable(pico_retro_controller
    src/main.c
    src/usb_descriptors.c
    src/xinput_driver.c
    src/retro_config.c
    src/retro_config_serial.c
)

# Include directories
target_include_directories(pico_retro_controller PRIVATE
    ${CMAKE_CURRENT_LIST_DIR}/src
)

# ── Build date: embedded in firmware and written to a sidecar .date file ──
string(TIMESTAMP BUILD_MONTH "%b")
string(TIMESTAMP BUILD_DAY   "%d")
string(TIMESTAMP BUILD_YEAR  "%Y")
set(BUILD_DATE_STR "${BUILD_MONTH} ${BUILD_DAY} ${BUILD_YEAR}")

# Compile definitions (base)
target_compile_definitions(pico_retro_controller PRIVATE
    BUILD_DATE_STR="${BUILD_DATE_STR}"
)

# Link required libraries (base — both Pico and Pico W)
target_link_libraries(pico_retro_controller
    pico_stdlib
    pico_unique_id
    tinyusb_device
    tinyusb_board
    hardware_flash
    hardware_sync
    hardware_adc
    hardware_gpio
    hardware_watchdog
    pico_bootrom
)

# ── Pico W specific additions ──
if(PICO_RETRO_WIRELESS)
    target_compile_definitions(pico_retro_controller PRIVATE
        CYW43_LWIP=0
        PICO_W_BT=1
    )
    target_link_libraries(pico_retro_controller
        pico_cyw43_arch_poll
    )
    set_target_properties(pico_retro_controller PROPERTIES OUTPUT_NAME "Retro_Controller_W")
else()
    set_target_properties(pico_retro_controller PROPERTIES OUTPUT_NAME "Retro_Controller")
endif()

# Disable default USB and UART stdio (we use USB for XInput/CDC)
pico_enable_stdio_usb(pico_retro_controller 0)
pico_enable_stdio_uart(pico_retro_controller 0)

# Create UF2 output
pico_add_extra_outputs(pico_retro_controller)

# Write a .uf2.date sidecar so the configurator build script can read it
add_custom_command(TARGET pico_retro_controller POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E echo "${BUILD_DATE_STR}"
        > "$<TARGET_FILE_DIR:pico_retro_controller>/$<TARGET_PROPERTY:pico_retro_controller,OUTPUT_NAME>.uf2.date"
    COMMENT "Writing firmware build date sidecar: ${BUILD_DATE_STR}"
)
