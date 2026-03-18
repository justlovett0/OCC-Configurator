/*
 * tusb_config.h - TinyUSB configuration for Pedal Controller
 *
 * Dual-mode USB:
 *   RHPORT0 (native USB) -> XInput device to host PC
 *   RHPORT1 (PIO USB)    -> USB host reading guitar controller
 *
 * CDC enabled for config mode serial interface.
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

//--------------------------------------------------------------------
// Device mode on RHPORT0 (native USB -> host PC)
//--------------------------------------------------------------------

#define CFG_TUSB_RHPORT0_MODE     (OPT_MODE_DEVICE | OPT_MODE_FULL_SPEED)
#define CFG_TUD_ENABLED           1
#define CFG_TUD_ENDPOINT0_SIZE    64

// CDC enabled for config mode serial interface
#define CFG_TUD_CDC               1
#define CFG_TUD_CDC_RX_BUFSIZE    256
#define CFG_TUD_CDC_TX_BUFSIZE    256

// All other device classes disabled
#define CFG_TUD_HID               0
#define CFG_TUD_MSC               0
#define CFG_TUD_MIDI              0
#define CFG_TUD_VENDOR            0
#define CFG_TUD_ECM_RNDIS         0
#define CFG_TUD_NCM               0
#define CFG_TUD_DFU               0
#define CFG_TUD_DFU_RUNTIME       0

//--------------------------------------------------------------------
// Host mode on RHPORT1 (PIO USB -> guitar controller)
//--------------------------------------------------------------------

#define CFG_TUSB_RHPORT1_MODE     (OPT_MODE_HOST | OPT_MODE_FULL_SPEED)
#define CFG_TUH_ENABLED           1
#define CFG_TUH_RPI_PIO_USB      1
#define BOARD_TUH_RHPORT         1
#define CFG_TUH_API_EDPT_XFER    1
#define CFG_TUH_MAX_SPEED        OPT_MODE_FULL_SPEED

// Host stack configuration
#define CFG_TUH_ENUMERATION_BUFSIZE 256
#define CFG_TUH_DEVICE_MAX       1   // Only one guitar controller at a time
#define CFG_TUH_ENDPOINT_MAX     4

// Host class drivers — all disabled, we use a custom XInput host driver
#define CFG_TUH_HID              0
#define CFG_TUH_CDC              0
#define CFG_TUH_MSC              0
#define CFG_TUH_VENDOR           0

#ifdef __cplusplus
}
#endif

#endif /* _TUSB_CONFIG_H_ */
