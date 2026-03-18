/*
 * btstack_config.h - BTstack configuration for Pico W Bluetooth LE HID Gamepad
 *
 * Switched from Bluetooth Classic to BLE (Bluetooth Low Energy) HIDS profile.
 *
 * Why BLE:
 *   Bluetooth Classic HID on Windows uses a legacy classification path that
 *   misidentifies guitar/instrument controller subtypes regardless of SDP
 *   subclass settings. BLE HID (HIDS over GATT) bypasses this entirely —
 *   Windows reads the HID Service (0x1812) and report descriptor directly,
 *   classifying the device exactly as described in the descriptor.
 *
 *   This matches how Santroller, Switch Pro Controller, DualSense, and all
 *   modern wireless controllers work on Windows 10/11.
 */

#ifndef BTSTACK_CONFIG_H
#define BTSTACK_CONFIG_H

// ── Core BTstack features ──
#define ENABLE_LOG_ERROR
// #define ENABLE_LOG_INFO    // Uncomment for verbose debug logging
#define ENABLE_PRINTF_HEXDUMP

// ── BLE (Bluetooth Low Energy) ──
// Guard against redefinition — pico_btstack_ble sets this via -D flag
#ifndef ENABLE_BLE
#define ENABLE_BLE
#endif

#define ENABLE_L2CAP_LE_CREDIT_BASED_FLOW_CONTROL_MODE
#define ENABLE_LE_PERIPHERAL
#define ENABLE_LE_CENTRAL

// ── Security Manager (BLE pairing/bonding) ──
#define ENABLE_SOFTWARE_AES128
#define ENABLE_MICRO_ECC_FOR_LE_SECURE_CONNECTIONS

// ── CYW43 HCI transport requirements ──
#define HCI_OUTGOING_PRE_BUFFER_SIZE          4
#define HCI_ACL_CHUNK_SIZE_ALIGNMENT          4

// ── HCI Controller-to-Host flow control ──
// Prevents CYW43 shared bus overrun (same as Santroller's btstack_config.h)
#define ENABLE_HCI_CONTROLLER_TO_HOST_FLOW_CONTROL
#define HCI_HOST_ACL_PACKET_LEN               1024
#define HCI_HOST_ACL_PACKET_NUM               3
#define HCI_HOST_SCO_PACKET_LEN               120
#define HCI_HOST_SCO_PACKET_NUM               3

// Limit controller-side buffers to avoid CYW43 shared bus overrun
#define MAX_NR_CONTROLLER_ACL_BUFFERS         3
#define MAX_NR_CONTROLLER_SCO_PACKETS         3

// ── BLE Device Database (stores bonding keys) ──
#define NVM_NUM_DEVICE_DB_ENTRIES             16
#define NVM_NUM_LINK_KEYS                     16
#define MAX_NR_LE_DEVICE_DB_ENTRIES           16
#define MAX_NR_WHITELIST_ENTRIES              16

// ── ATT (GATT attribute database) ──
#define MAX_ATT_DB_SIZE                       512

// ── Memory Configuration ──
#define HCI_ACL_PAYLOAD_SIZE                  (1691 + 4)
#define HCI_INCOMING_PRE_BUFFER_SIZE          14

#define MAX_NR_HCI_CONNECTIONS                2
#define MAX_NR_L2CAP_SERVICES                 3
#define MAX_NR_L2CAP_CHANNELS                 4
#define MAX_NR_SERVICE_RECORD_ITEMS           4
#define MAX_NR_BTSTACK_LINK_KEY_DB_MEMORY_ENTRIES  2
#define MAX_NR_GATT_CLIENTS                   1
#define MAX_NR_HIDS_CLIENTS                   1
#define MAX_NR_SM_LOOKUP_ENTRIES              3

// ── Unused profiles — keep at zero ──
#define MAX_NR_RFCOMM_MULTIPLEXERS            0
#define MAX_NR_RFCOMM_SERVICES                0
#define MAX_NR_RFCOMM_CHANNELS                0
#define MAX_NR_BNEP_SERVICES                  0
#define MAX_NR_BNEP_CHANNELS                  0
#define MAX_NR_HFP_CONNECTIONS                0
#define MAX_NR_AVDTP_STREAM_ENDPOINTS         0
#define MAX_NR_AVDTP_CONNECTIONS              0
#define MAX_NR_AVRCP_CONNECTIONS              0
#define MAX_NR_HID_HOST_CONNECTIONS           0

// ── BTstack HAL configuration ──
#define HAVE_EMBEDDED_TIME_MS
#define HAVE_ASSERT
#define HCI_RESET_RESEND_TIMEOUT_MS           1000

#endif /* BTSTACK_CONFIG_H */
