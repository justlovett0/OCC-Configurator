/*
 * tusb_config.h - TinyUSB configuration for Pico W Guitar Dongle
 *
 * Dual-mode: XInput in play mode, CDC serial in config mode.
 */

#ifndef _TUSB_CONFIG_H_
#define _TUSB_CONFIG_H_

#ifdef __cplusplus
extern "C" {
#endif

#define BOARD_DEVICE_RHPORT_NUM     0
#define BOARD_DEVICE_RHPORT_SPEED   OPT_MODE_FULL_SPEED
#define CFG_TUSB_RHPORT0_MODE      (OPT_MODE_DEVICE | OPT_MODE_FULL_SPEED)

#define CFG_TUSB_MEM_SECTION
#define CFG_TUSB_MEM_ALIGN          __attribute__((aligned(4)))
#define CFG_TUD_ENDPOINT0_SIZE      64

#define CFG_TUD_CDC                 1
#define CFG_TUD_CDC_RX_BUFSIZE      256
#define CFG_TUD_CDC_TX_BUFSIZE      256
#define CFG_TUD_MSC                 0
#define CFG_TUD_HID                 0
#define CFG_TUD_MIDI                0
#define CFG_TUD_VENDOR              0

#ifdef __cplusplus
}
#endif

#endif /* _TUSB_CONFIG_H_ */
