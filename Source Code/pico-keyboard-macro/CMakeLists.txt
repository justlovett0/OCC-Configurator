cmake_minimum_required(VERSION 3.13)

include(pico_sdk_import.cmake)

project(pico_keyboard_macro C CXX ASM)

set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)

pico_sdk_init()

add_executable(pico_keyboard_macro
    src/main.c
    src/usb_descriptors.c
    src/macro_config.c
    src/macro_config_serial.c
)

target_include_directories(pico_keyboard_macro PRIVATE
    ${CMAKE_CURRENT_LIST_DIR}/src
)

target_link_libraries(pico_keyboard_macro
    pico_stdlib
    pico_unique_id
    tinyusb_device
    tinyusb_board
    hardware_flash
    hardware_sync
    hardware_gpio
    hardware_watchdog
    pico_bootrom
)

string(TIMESTAMP BUILD_MONTH "%b")
string(TIMESTAMP BUILD_DAY   "%d")
string(TIMESTAMP BUILD_YEAR  "%Y")
set(BUILD_DATE_STR "${BUILD_MONTH} ${BUILD_DAY} ${BUILD_YEAR}")
target_compile_definitions(pico_keyboard_macro PRIVATE
    BUILD_DATE_STR="${BUILD_DATE_STR}"
)

pico_enable_stdio_usb(pico_keyboard_macro 0)
pico_enable_stdio_uart(pico_keyboard_macro 0)

pico_add_extra_outputs(pico_keyboard_macro)

add_custom_command(TARGET pico_keyboard_macro POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E echo "${BUILD_DATE_STR}"
        > "$<TARGET_FILE_DIR:pico_keyboard_macro>/pico_keyboard_macro.uf2.date"
    COMMENT "Writing firmware build date sidecar: ${BUILD_DATE_STR}"
)
