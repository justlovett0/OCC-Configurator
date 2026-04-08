/*
 * tusb_config.h - TinyUSB configuration for Bluetooth Guitar Controller
 *
 * CDC is enabled for config mode. USB is only used in config mode;
 * play mode uses Bluetooth Classic HID instead of USB XInput.
 */

#ifndef _TUSB_CONFIG_H_
#define _TUSB_CONFIG_H_

#ifdef __cplusplus
extern "C" {
#endif

#define CFG_TUSB_MCU              OPT_MCU_RP2040
#define CFG_TUSB_OS               OPT_OS_PICO
#define CFG_TUSB_DEBUG            0

#ifndef CFG_TUSB_MEM_SECTION
#define CFG_TUSB_MEM_SECTION
#endif

#ifndef CFG_TUSB_MEM_ALIGN
#define CFG_TUSB_MEM_ALIGN        __attribute__((aligned(4)))
#endif

#define CFG_TUD_ENABLED           1
#define CFG_TUSB_RHPORT0_MODE     OPT_MODE_DEVICE
#define CFG_TUD_ENDPOINT0_SIZE    64

// CDC enabled for config mode serial interface
#define CFG_TUD_CDC               1
#define CFG_TUD_CDC_RX_BUFSIZE    256
#define CFG_TUD_CDC_TX_BUFSIZE    256

// HID enabled for USB PS3 and USB keyboard boot personalities
#define CFG_TUD_HID               1
#define CFG_TUD_MSC               0
#define CFG_TUD_MIDI              0
#define CFG_TUD_VENDOR            0
#define CFG_TUD_ECM_RNDIS         0
#define CFG_TUD_NCM               0
#define CFG_TUD_DFU               0
#define CFG_TUD_DFU_RUNTIME       0

#ifdef __cplusplus
}
#endif

#endif /* _TUSB_CONFIG_H_ */
