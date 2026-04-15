cmake_minimum_required(VERSION 3.13)

include(pico_sdk_import.cmake)

project(pico_arcadestick_controller C CXX ASM)

set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)

pico_sdk_init()

add_executable(pico_arcadestick_controller
    src/main.c
    src/usb_descriptors.c
    src/xinput_driver.c
    src/arcadestick_config.c
    src/arcadestick_config_serial.c
)

target_include_directories(pico_arcadestick_controller PRIVATE
    ${CMAKE_CURRENT_LIST_DIR}/src
)

string(TIMESTAMP BUILD_MONTH "%b")
string(TIMESTAMP BUILD_DAY "%d")
string(TIMESTAMP BUILD_YEAR "%Y")
set(BUILD_DATE_STR "${BUILD_MONTH} ${BUILD_DAY} ${BUILD_YEAR}")

target_compile_definitions(pico_arcadestick_controller PRIVATE
    BUILD_DATE_STR="${BUILD_DATE_STR}"
)

target_link_libraries(pico_arcadestick_controller
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

set_target_properties(pico_arcadestick_controller PROPERTIES OUTPUT_NAME "ArcadeStick_Controller")

pico_enable_stdio_usb(pico_arcadestick_controller 0)
pico_enable_stdio_uart(pico_arcadestick_controller 0)

pico_add_extra_outputs(pico_arcadestick_controller)

add_custom_command(TARGET pico_arcadestick_controller POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E echo "${BUILD_DATE_STR}"
        > "$<TARGET_FILE_DIR:pico_arcadestick_controller>/$<TARGET_PROPERTY:pico_arcadestick_controller,OUTPUT_NAME>.uf2.date"
    COMMENT "Writing firmware build date sidecar: ${BUILD_DATE_STR}"
)
