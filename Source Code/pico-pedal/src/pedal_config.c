/*
 * pedal_config.c - Flash-backed configuration storage for pedal controller
 */

#include "pedal_config.h"
#include "hardware/flash.h"
#include "hardware/sync.h"
#include <stddef.h>
#include <string.h>

#define FLASH_CONFIG_OFFSET  (PICO_FLASH_SIZE_BYTES - FLASH_SECTOR_SIZE)
#define FLASH_CONFIG_ADDR    ((const pedal_config_t *)(XIP_BASE + FLASH_CONFIG_OFFSET))

typedef struct __attribute__((packed)) {
    uint32_t magic;
    uint16_t version;
    int8_t   pin_buttons[PEDAL_BUTTON_COUNT];
    uint8_t  button_mapping[PEDAL_BUTTON_COUNT];
    uint8_t  debounce_ms;
    char     device_name[DEVICE_NAME_MAX + 1];
    int8_t   adc_pin[PEDAL_ADC_COUNT];
    uint8_t  adc_axis[PEDAL_ADC_COUNT];
    uint8_t  adc_invert[PEDAL_ADC_COUNT];
    uint16_t adc_min[PEDAL_ADC_COUNT];
    uint16_t adc_max[PEDAL_ADC_COUNT];
    uint32_t checksum;
} pedal_config_v2_t;

typedef struct __attribute__((packed)) {
    uint32_t magic;
    uint16_t version;
    int8_t   pin_buttons[PEDAL_BUTTON_COUNT];
    uint8_t  button_mapping[PEDAL_BUTTON_COUNT];
    uint8_t  debounce_ms;
    char     device_name[DEVICE_NAME_MAX + 1];
    int8_t   adc_pin[PEDAL_ADC_COUNT];
    uint8_t  adc_axis[PEDAL_ADC_COUNT];
    uint8_t  adc_invert[PEDAL_ADC_COUNT];
    uint16_t adc_min[PEDAL_ADC_COUNT];
    uint16_t adc_max[PEDAL_ADC_COUNT];
    int8_t   usb_host_pin;
    uint8_t  usb_host_dm_first;
    uint32_t checksum;
} pedal_config_v3_t;

static uint32_t _calc_checksum(const pedal_config_t *config) {
    const uint8_t *data = (const uint8_t *)config;
    size_t len = offsetof(pedal_config_t, checksum);
    uint32_t sum = 0;
    for (size_t i = 0; i < len; i++) {
        sum += data[i];
        sum = (sum << 3) | (sum >> 29);
    }
    return sum ^ 0xDEADBEEF;
}

static uint32_t _calc_checksum_v2(const pedal_config_v2_t *config) {
    const uint8_t *data = (const uint8_t *)config;
    size_t len = offsetof(pedal_config_v2_t, checksum);
    uint32_t sum = 0;
    for (size_t i = 0; i < len; i++) {
        sum += data[i];
        sum = (sum << 3) | (sum >> 29);
    }
    return sum ^ 0xDEADBEEF;
}

static uint32_t _calc_checksum_v3(const pedal_config_v3_t *config) {
    const uint8_t *data = (const uint8_t *)config;
    size_t len = offsetof(pedal_config_v3_t, checksum);
    uint32_t sum = 0;
    for (size_t i = 0; i < len; i++) {
        sum += data[i];
        sum = (sum << 3) | (sum >> 29);
    }
    return sum ^ 0xDEADBEEF;
}

bool config_usb_host_pin_valid(int pin) {
    return pin >= 0 && pin <= 27;
}

bool config_pin_is_usb_host_reserved(const pedal_config_t *config, int pin) {
    if (pin < 0 || pin > 28 || !config_usb_host_pin_valid(config->usb_host_pin)) {
        return false;
    }
    return pin == config->usb_host_pin || pin == (config->usb_host_pin + 1);
}

uint8_t config_usb_host_dp_pin(const pedal_config_t *config) {
    return (uint8_t)(config->usb_host_dm_first ? (config->usb_host_pin + 1)
                                               : config->usb_host_pin);
}

uint8_t config_usb_host_dm_pin(const pedal_config_t *config) {
    return (uint8_t)(config->usb_host_dm_first ? config->usb_host_pin
                                               : (config->usb_host_pin + 1));
}

void config_set_defaults(pedal_config_t *config) {
    memset(config, 0, sizeof(pedal_config_t));
    config->magic   = CONFIG_MAGIC;
    config->version = CONFIG_VERSION;

    // Default pedal button pins: GP4–GP7
    // (GP2/GP3 reserved for PIO-USB D+/D-)
    config->pin_buttons[0] = 4;
    config->pin_buttons[1] = 5;
    config->pin_buttons[2] = 6;
    config->pin_buttons[3] = 7;

    // Default mappings: Green, Red, Yellow, Blue frets
    config->button_mapping[0] = BTN_IDX_GREEN;
    config->button_mapping[1] = BTN_IDX_RED;
    config->button_mapping[2] = BTN_IDX_YELLOW;
    config->button_mapping[3] = BTN_IDX_BLUE;

    config->debounce_ms = 5;

    strncpy(config->device_name, "Pedal Controller", DEVICE_NAME_MAX);
    config->device_name[DEVICE_NAME_MAX] = '\0';

    // Analog inputs disabled by default
    for (int i = 0; i < PEDAL_ADC_COUNT; i++) {
        config->adc_pin[i]    = -1;
        config->adc_axis[i]   = ADC_AXIS_WHAMMY;
        config->adc_invert[i] = 0;
        config->adc_min[i]    = 0;
        config->adc_max[i]    = 4095;
    }

    config->usb_host_pin      = 2;
    config->usb_host_dm_first = 0;

    config->leds.enabled = 0;
    config->leds.count = 0;
    config->leds.base_brightness = 5;

    for (int i = 0; i < 4 && i < MAX_LEDS; i++) {
        config->leds.colors[i].r = 255;
        config->leds.colors[i].g = 255;
        config->leds.colors[i].b = 255;
    }
    for (int i = 4; i < MAX_LEDS; i++) {
        config->leds.colors[i].r = 255;
        config->leds.colors[i].g = 255;
        config->leds.colors[i].b = 255;
    }

    for (int i = 0; i < LED_INPUT_COUNT; i++) {
        config->leds.led_map[i] = 0;
        config->leds.active_brightness[i] = 25;
    }
    for (int i = 0; i < 4 && i < MAX_LEDS; i++) {
        config->leds.led_map[i] = (uint16_t)(1u << i);
    }
    config->leds.loop_enabled = 0;
    config->leds.loop_start = 0;
    config->leds.loop_end = 0;
    config->leds.breathe_enabled = 0;
    config->leds.breathe_start = 0;
    config->leds.breathe_end = 0;
    config->leds.breathe_min_bright = 1;
    config->leds.breathe_max_bright = 9;
    config->leds.wave_enabled = 0;
    config->leds.wave_origin = 0;
    config->leds.loop_speed_ms = 3000;
    config->leds.breathe_speed_ms = 3000;
    config->leds.wave_speed_ms = 800;

    config->checksum = _calc_checksum(config);
}

bool config_is_valid(const pedal_config_t *config) {
    if (config->magic != CONFIG_MAGIC) return false;
    if (config->version != CONFIG_VERSION) return false;
    if (config->checksum != _calc_checksum(config)) return false;
    if (!config_usb_host_pin_valid(config->usb_host_pin)) return false;
    if (config->usb_host_dm_first > 1) return false;
    return true;
}

static bool config_is_valid_v2(const pedal_config_v2_t *config) {
    if (config->magic != CONFIG_MAGIC) return false;
    if (config->version != 2) return false;
    if (config->checksum != _calc_checksum_v2(config)) return false;
    return true;
}

static bool config_is_valid_v3(const pedal_config_v3_t *config) {
    if (config->magic != CONFIG_MAGIC) return false;
    if (config->version != 3) return false;
    if (config->checksum != _calc_checksum_v3(config)) return false;
    if (!config_usb_host_pin_valid(config->usb_host_pin)) return false;
    if (config->usb_host_dm_first > 1) return false;
    return true;
}

void config_load(pedal_config_t *config) {
    const pedal_config_t *flash_config = FLASH_CONFIG_ADDR;
    if (config_is_valid(flash_config)) {
        memcpy(config, flash_config, sizeof(pedal_config_t));
        return;
    }

    const pedal_config_v2_t *flash_config_v2 = (const pedal_config_v2_t *)FLASH_CONFIG_ADDR;
    if (config_is_valid_v2(flash_config_v2)) {
        config_set_defaults(config);
        memcpy(config->pin_buttons, flash_config_v2->pin_buttons, sizeof(config->pin_buttons));
        memcpy(config->button_mapping, flash_config_v2->button_mapping, sizeof(config->button_mapping));
        config->debounce_ms = flash_config_v2->debounce_ms;
        memcpy(config->device_name, flash_config_v2->device_name, sizeof(config->device_name));
        memcpy(config->adc_pin, flash_config_v2->adc_pin, sizeof(config->adc_pin));
        memcpy(config->adc_axis, flash_config_v2->adc_axis, sizeof(config->adc_axis));
        memcpy(config->adc_invert, flash_config_v2->adc_invert, sizeof(config->adc_invert));
        memcpy(config->adc_min, flash_config_v2->adc_min, sizeof(config->adc_min));
        memcpy(config->adc_max, flash_config_v2->adc_max, sizeof(config->adc_max));
        config->usb_host_pin      = 2;
        config->usb_host_dm_first = 0;
        config_update_checksum(config);
        return;
    }

    const pedal_config_v3_t *flash_config_v3 = (const pedal_config_v3_t *)FLASH_CONFIG_ADDR;
    if (config_is_valid_v3(flash_config_v3)) {
        config_set_defaults(config);
        memcpy(config->pin_buttons, flash_config_v3->pin_buttons, sizeof(config->pin_buttons));
        memcpy(config->button_mapping, flash_config_v3->button_mapping, sizeof(config->button_mapping));
        config->debounce_ms = flash_config_v3->debounce_ms;
        memcpy(config->device_name, flash_config_v3->device_name, sizeof(config->device_name));
        memcpy(config->adc_pin, flash_config_v3->adc_pin, sizeof(config->adc_pin));
        memcpy(config->adc_axis, flash_config_v3->adc_axis, sizeof(config->adc_axis));
        memcpy(config->adc_invert, flash_config_v3->adc_invert, sizeof(config->adc_invert));
        memcpy(config->adc_min, flash_config_v3->adc_min, sizeof(config->adc_min));
        memcpy(config->adc_max, flash_config_v3->adc_max, sizeof(config->adc_max));
        config->usb_host_pin = flash_config_v3->usb_host_pin;
        config->usb_host_dm_first = flash_config_v3->usb_host_dm_first;
        config_update_checksum(config);
        return;
    }

    config_set_defaults(config);
}

void config_save(const pedal_config_t *config) {
    uint8_t buf[FLASH_PAGE_SIZE];
    memset(buf, 0xFF, sizeof(buf));
    memcpy(buf, config, sizeof(pedal_config_t));

    uint32_t ints = save_and_disable_interrupts();
    flash_range_erase(FLASH_CONFIG_OFFSET, FLASH_SECTOR_SIZE);
    flash_range_program(FLASH_CONFIG_OFFSET, buf, FLASH_PAGE_SIZE);
    restore_interrupts(ints);
}

void config_update_checksum(pedal_config_t *config) {
    config->magic    = CONFIG_MAGIC;
    config->version  = CONFIG_VERSION;
    config->checksum = _calc_checksum(config);
}
