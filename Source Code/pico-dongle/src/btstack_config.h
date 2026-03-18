/*
 * btstack_config.h - BTstack configuration for Pico W Guitar Dongle
 *
 * The dongle is a BLE Central that passively scans for controller
 * advertisements. No connections, no pairing, no peripheral role.
 */

#ifndef BTSTACK_CONFIG_H
#define BTSTACK_CONFIG_H

// ── Core BTstack features ──
#define ENABLE_LOG_ERROR
// #define ENABLE_LOG_INFO    // Uncomment for verbose debug logging

// Required by hci_dump_embedded_stdout (HCI logging to UART/stdout)
#define ENABLE_PRINTF_HEXDUMP

// ── BLE (Bluetooth Low Energy) ──
#ifndef ENABLE_BLE
#define ENABLE_BLE
#endif

#define ENABLE_LE_CENTRAL

// ── CYW43 HCI transport requirements ──
#define HCI_OUTGOING_PRE_BUFFER_SIZE          4
#define HCI_ACL_CHUNK_SIZE_ALIGNMENT          4

// ── HCI Controller-to-Host flow control ──
#define ENABLE_HCI_CONTROLLER_TO_HOST_FLOW_CONTROL
#define HCI_HOST_ACL_PACKET_LEN               256
#define HCI_HOST_ACL_PACKET_NUM               3
#define HCI_HOST_SCO_PACKET_LEN               120
#define HCI_HOST_SCO_PACKET_NUM               3

#define MAX_NR_CONTROLLER_ACL_BUFFERS         3
#define MAX_NR_CONTROLLER_SCO_PACKETS         3

// ── BLE Device Database (minimal — we don't store pairings) ──
// BTstack requires NVM_NUM_DEVICE_DB_ENTRIES >= 1 even if pairing is unused
#define NVM_NUM_DEVICE_DB_ENTRIES             1
#define NVM_NUM_LINK_KEYS                     0
#define MAX_NR_LE_DEVICE_DB_ENTRIES           1
#define MAX_NR_WHITELIST_ENTRIES              0

// ── ATT (minimal — required by BTstack internals) ──
#define MAX_ATT_DB_SIZE                       64

// ── Memory Configuration ──
#define HCI_ACL_PAYLOAD_SIZE                  256
#define HCI_INCOMING_PRE_BUFFER_SIZE          14

#define MAX_NR_HCI_CONNECTIONS                1
#define MAX_NR_L2CAP_SERVICES                 1
#define MAX_NR_L2CAP_CHANNELS                 1
#define MAX_NR_SERVICE_RECORD_ITEMS           0
#define MAX_NR_BTSTACK_LINK_KEY_DB_MEMORY_ENTRIES  0
#define MAX_NR_GATT_CLIENTS                   0
#define MAX_NR_HIDS_CLIENTS                   0
#define MAX_NR_SM_LOOKUP_ENTRIES              0

// ── Unused profiles ──
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
