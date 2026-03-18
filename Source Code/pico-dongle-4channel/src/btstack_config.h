/*
 * btstack_config.h - BTstack configuration for Pico W Guitar Dongle
 *
 * The dongle is a pure BLE Central at runtime — it only passively scans for
 * controller advertisements and never advertises or accepts connections.
 *
 * ENABLE_LE_PERIPHERAL must still be defined here. Some BTstack versions
 * (including the one bundled with the Pico SDK) only compile the
 * le_advertisements_state field into hci_stack_t when this flag is present.
 * Without it the build fails:
 *   error: 'hci_stack_t' has no member named 'le_advertisements_state'
 *
 * Defining this flag does NOT cause the dongle to advertise or behave as a
 * peripheral — that requires an explicit gap_advertisements_enable() call,
 * which is never made. att_server_init() has also been removed from
 * dongle_bt_init() so the GATT server is never started either.
 */

#ifndef BTSTACK_CONFIG_H
#define BTSTACK_CONFIG_H

// ── Core BTstack features ──────────────────────────────────────────
#define ENABLE_LOG_ERROR
// #define ENABLE_LOG_INFO    /* Uncomment for verbose debug logging */
#define ENABLE_PRINTF_HEXDUMP

// ── BLE (Bluetooth Low Energy) ────────────────────────────────────
#ifndef ENABLE_BLE
#define ENABLE_BLE
#endif

// Central (scanner) role — what the dongle actually uses at runtime.
#define ENABLE_LE_CENTRAL

// Required by some Pico SDK BTstack versions to compile hci_stack_t fully.
// Does not activate advertising or peripheral behaviour without explicit API
// calls (gap_advertisements_enable etc.), none of which are made here.
#define ENABLE_LE_PERIPHERAL

// ── Security Manager ──────────────────────────────────────────────
#define ENABLE_SOFTWARE_AES128
#define ENABLE_MICRO_ECC_FOR_LE_SECURE_CONNECTIONS

// ── CYW43 HCI transport requirements ─────────────────────────────
#define HCI_OUTGOING_PRE_BUFFER_SIZE          4
#define HCI_ACL_CHUNK_SIZE_ALIGNMENT          4

// ── HCI Controller-to-Host flow control ──────────────────────────
#define ENABLE_HCI_CONTROLLER_TO_HOST_FLOW_CONTROL
#define HCI_HOST_ACL_PACKET_LEN               1024
#define HCI_HOST_ACL_PACKET_NUM               3
#define HCI_HOST_SCO_PACKET_LEN               120
#define HCI_HOST_SCO_PACKET_NUM               3

#define MAX_NR_CONTROLLER_ACL_BUFFERS         3
#define MAX_NR_CONTROLLER_SCO_PACKETS         3

// ── BLE Device Database ───────────────────────────────────────────
#define NVM_NUM_DEVICE_DB_ENTRIES             4
#define NVM_NUM_LINK_KEYS                     4
#define MAX_NR_LE_DEVICE_DB_ENTRIES           4
#define MAX_NR_WHITELIST_ENTRIES              4

// ── ATT (GATT attribute database) ────────────────────────────────
// att_server_init() is NOT called in dongle_bt_init(), so the GATT server
// is never started. This size is kept at minimum to conserve RAM.
#define MAX_ATT_DB_SIZE                       128

// ── Memory configuration ──────────────────────────────────────────
#define HCI_ACL_PAYLOAD_SIZE                  (1691 + 4)
#define HCI_INCOMING_PRE_BUFFER_SIZE          14

#define MAX_NR_HCI_CONNECTIONS                1
#define MAX_NR_L2CAP_SERVICES                 1
#define MAX_NR_L2CAP_CHANNELS                 2
#define MAX_NR_SERVICE_RECORD_ITEMS           1
#define MAX_NR_BTSTACK_LINK_KEY_DB_MEMORY_ENTRIES  1
#define MAX_NR_GATT_CLIENTS                   1
#define MAX_NR_HIDS_CLIENTS                   0
#define MAX_NR_SM_LOOKUP_ENTRIES              2

// ── Unused profiles ───────────────────────────────────────────────
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

// ── BTstack HAL ───────────────────────────────────────────────────
#define HAVE_EMBEDDED_TIME_MS
#define HAVE_ASSERT
#define HCI_RESET_RESEND_TIMEOUT_MS           1000

#endif /* BTSTACK_CONFIG_H */
