# Pico-Pedal USB Host Troubleshooting Log

## Device Being Tested

**GameSir-G7 SE Controller for Xbox**
- VID: 0x3537 / PID: 0x1010
- Protocol: GIP (Gaming Input Protocol) — Xbox One/Series X controller stack
- Driver on Windows: `dc1-controller.sys` + upper filter `xboxgip`
- `bDeviceClass: 0xFF`, `bDeviceSubClass: 0xFF`, `bDeviceProtocol: 0xFF`
- `bMaxPacketSize0: 64` (EP0 is 64-byte, standard USB full-speed)
- Interface 0 class info: `Class=0xFF, SubClass=0x47, Protocol=0xD0`

**Important**: This device uses GIP, NOT XInput. Our driver looks for
`subclass=0x5D, protocol=0x01` (XInput). Even if enumeration succeeds,
this device would not be claimed by the current XInput driver. A separate
GIP driver would be needed — or a different guitar should be tested first.

---

## Debug Infrastructure Built

Added a debug output mode (`PEDAL_HOST_DEBUG=1`) that prints a row every 500ms
over CDC serial. Columns:

| col | meaning |
|-----|---------|
| c1 | Core 1 status (4=task loop running) |
| any | tuh_mount_cb fired (any device mounted) |
| mnt | XInput mount count |
| umt | unmount count |
| oat | xinputh_open() called (interface seen) |
| ocl | xinputh_open() claimed (XInput match) |
| cls/sub/pro | most recent interface class/subclass/protocol seen |
| se0 | SE0 recovery runs (tuh_umount_cb side effect) |
| ok | valid XInput reports received |
| fail | failed IN transfers on XInput endpoint |
| pfird | times probe fired (anti-phantom check ran) |
| preal | times probe confirmed a real device (D+ pull-up detected) |
| rcon | root->connected at time of read |
| rsus | root->suspended at time of read |
| brst | port_reset_start() call count (bus reset started) |
| setup | usb_setup_transaction() call count (SETUP packet sent) |

Also added a **3-second watchdog** in `main.c` (PEDAL_HOST_DEBUG section): if
`preal > 0` but `mnt == 0` after 3s since last preal change, calls
`xinput_host_force_reconnect()` to retry detection.

---

## Phantom Device Problem (Solved)

**Symptom:** Probe fires on boot but no real device present.
PIO-USB TX SM idles in J-state (D+=HIGH). RX init sets `GPIO_OVERRIDE_INVERT`,
so `get_line_state()` reads J-state as `PORT_PIN_FS_IDLE` and triggers a phantom
CONNECT. After phantom enum fails, `root->connected` stays true and the detection
loop never runs again.

**Fix applied in `pio_usb_host.c`:** Anti-phantom probe — before accepting a
CONNECT event, drive DP low via output override and check with `gpio_get()`.
With INVERT active, `gpio_get()==0` means physical HIGH = real D+ pull-up.
Phantom J-state reads 1 (low after invert) → skipped.

**Also fixed:** `tuh_umount_cb` now pulses SE0 for 3ms to reset
`root->connected=false` after a phantom enum unwind, re-enabling the detection
loop for real devices.

**Result:** `pfird`/`preal` now only increment when a real device is physically
plugged in. ✓

---

## Stuck root->connected After Failed Enum (Partially Addressed)

**Problem identified:** After the probe fires and `enum_new_device()` runs:
1. Bus reset (50ms) + debounce (450ms) + GET_DESCRIPTOR sent → `setup=1`
2. Device doesn't respond to DATA IN → enum fails
3. `enum_full_complete()` only clears `_dev0.enumerating`. `root->connected`
   stays true. Detection loop never runs again.

**Fixes applied:**

- Added `_xinput_root_connected`, `_xinput_root_suspended`, `_xinput_bus_reset_count`,
  `_xinput_setup_sent_count` counters, exposed in `rcon`, `rsus`, `brst`, `setup`
  debug columns, to observe enumeration progression.

- Added `xinput_host_force_reconnect()`: sets `_xinput_force_reconnect` flag.
  In `pio_usb_host_frame()` SOF callback, when flag is set: clears
  `root->connected`, sets `root->suspended`, fires `DISCONNECT_BITS`. Probe
  re-fires on next frame → `root->connected=true` → CONNECT event queued →
  `enum_new_device()` runs again.

- 3-second watchdog in `main.c`: calls `force_reconnect()` when device is
  detected but never mounts.

---

## Test Results: Enumeration Fails at DATA IN

### Observation

Every test run (with and without the EP0 stall fix) shows:

```
c1  any mnt umt oat ocl  cls   sub   pro   se0 ok  fail pfird preal rcon rsus brst setup
4    0   0   0   0   0   0x00 0x00 0x00  0    0    0    1     1     1    0    1    1   no-device
watchdog: no mount after 3s, forcing reconnect
4    0   0   0   0   0   0x00 0x00 0x00  0    0    0    2     2     1    0    2    1   no-device
watchdog: no mount after 3s, forcing reconnect
...
```

### What each value tells us

- `c1=4` → Core 1 task loop is running ✓
- `rcon=1` → `root->connected=true` (device physically present) ✓
- `pfird=N, preal=N` → probe fires and confirms real device every cycle ✓
- `brst=N` → bus reset starts every cycle (`port_reset_start()` called) ✓
- `setup=1` → **exactly one SETUP packet has ever been sent, across all cycles**
- `any=0, mnt=0` → no device has ever mounted
- `oat=0` → our XInput driver's `open()` was never called
- `ok=0, fail=0` → no XInput IN transfers ever ran

### Root cause analysis

`setup=1` across all retry cycles means:
1. The first SETUP (GET_DEVICE_DESC) was sent and ACKed by the device ✓
2. DATA IN phase started (`_ctrl_xfer.stage = CONTROL_STAGE_DATA`)
3. The device either:
   - Sends NAK indefinitely on DATA IN (device not ready / requires GIP handshake first)
   - Sends DATA with wrong toggle (DATA0 vs DATA1 mismatch)
4. PIO-USB does not timeout on NAK — `failed_count` resets to 0 on each NAK (line in
   `usb_in_transaction`: `if (res == 0) ep->failed_count = 0;`). Transfer never completes.
5. `_ctrl_xfer.stage` stays in `CONTROL_STAGE_DATA` permanently.
6. Force_reconnect fires → DISCONNECT+CONNECT queued → new `enum_new_device()`.
7. In the new enum: `tuh_control_xfer()` checks `_ctrl_xfer.stage == CONTROL_STAGE_IDLE`
   → FAILS (stage is still DATA) → returns false → no new SETUP sent → `setup` stays at 1.
8. Infinite loop.

### EP0 stall fix attempted (did not resolve)

Added a `_ep0_in_stall` counter to `usb_in_transaction` in `pio_usb_host.c`:
after 200 consecutive frames of EP0 IN with no data (NAK or toggle mismatch),
fires `pio_usb_ll_transfer_complete(ep, ENDPOINT_ERROR_BITS)` to force an error
event. This should have reset `_ctrl_xfer.stage` to IDLE and allowed retry SETUP
packets, incrementing `setup` to 2, 3, etc.

**Result: `setup` still stuck at 1.** The fix either:
- Fires the error but `tuh_control_xfer()` still fails for another reason
- Is not being reached (DATA IN phase may not actually be running if there is a
  deeper issue in how the enum flows for this device type)

This remains unresolved.

---

## Key Finding: Wrong Protocol

The device is a **GameSir-G7 SE** which uses **GIP (Gaming Input Protocol)**,
not XInput. GIP is used by Xbox One / Xbox Series X controllers and requires:

1. A security handshake sequence before standard USB responses work
2. The `xboxgip` driver on Windows sends vendor-specific USB commands
3. The device likely refuses to send GET_DESCRIPTOR data until this handshake occurs
   (or at minimum behaves differently than an XInput device during enumeration)

Interface class values: `SubClass=0x47, Protocol=0xD0` (GIP), vs expected XInput
`SubClass=0x5D, Protocol=0x01`.

Even if enumeration succeeded, the current XInput driver would not claim the
GIP interface (`oat` would increment but `ocl` would stay 0).

---

## Recommended Next Steps

### 1. Test with a known XInput guitar first

Before debugging the GIP/stall issue further, plug in a standard wired Xbox 360
guitar (Xplorer, Les Paul, etc.) or a Clone Hero wired controller that advertises
standard XInput (subclass=0x5D, protocol=0x01). The current codebase is built
for XInput. If a standard XInput guitar enumerates and works, the core host
infrastructure is sound and only GIP support is missing.

### 2. If only a GIP device is available

GIP devices need vendor-specific initialization. To support the GameSir-G7 SE:
- Research the GIP handshake sequence (check GP2040-CE's `gamepad_usb_host.cpp`
  and Santroller's `xinput_wireless_gamepad_host.cpp` — both have GIP support)
- The interface to claim would be `Class=0xFF, SubClass=0x47, Protocol=0xD0`
- The host likely needs to send a vendor-specific "wakeup" packet over EP0 before
  the device will respond to regular transfers

### 3. Investigate `_ctrl_xfer.stage` stuck state

If a standard XInput guitar also fails at `setup=1`, the stuck `_ctrl_xfer.stage`
issue is real and needs fixing. Options:
- Add `CFG_TUSB_DEBUG=2` to enable TinyUSB internal logging over CDC and see
  exactly where enumeration stalls
- Add a counter for how many times `usb_in_transaction` is called for EP0 to
  confirm the DATA IN loop is actually running
- Check if the EP0 stall counter is actually reaching 200 (add a debug export)

---

## Files Modified

| File | Change |
|------|--------|
| `lib/Pico-PIO-USB/src/pio_usb_host.c` | Anti-phantom probe; SE0 recovery in umount; bus state externs; force_reconnect hook; `_xinput_bus_reset_count`/`_xinput_setup_sent_count` counters; EP0 stall timeout (200 frames) |
| `src/xinput_host.c` | New globals: `_xinput_root_connected`, `_xinput_root_suspended`, `_xinput_force_reconnect`, `_xinput_bus_reset_count`, `_xinput_setup_sent_count`; `xinput_host_force_reconnect()` |
| `src/xinput_host.h` | Added `root_connected`, `root_suspended`, `bus_reset_count`, `setup_sent_count` to `xinput_debug_t`; declared `xinput_host_force_reconnect()` |
| `src/main.c` | Full debug output with all columns; 3-second mount watchdog |
| `src/apa102_leds.c` | LED status indicators for host connection state |
| `CMakeLists.txt` | `PEDAL_HOST_DEBUG=1` define; `PEDAL_LED_DEBUG` option |

---

## USB Descriptor Reference (Windows USBView output)

```
Vendor ID    : 0x3537  (Guangzhou Chicken Run Network Technology Co., Ltd.)
Product ID   : 0x1010
Product      : GameSir-G7 SE Controller for Xbox
USB Version  : 2.0 (Full-Speed only)
bMaxPacketSize0 : 64
Driver       : dc1-controller.sys (Microsoft GIP driver)
Upper Filter : xboxgip

Interface 0: Class=0xFF SubClass=0x47 Protocol=0xD0 (GIP main)
  EP 0x02 OUT Interrupt  64 bytes  4ms
  EP 0x82 IN  Interrupt  64 bytes  4ms

Interface 1 alt 0: Class=0xFF SubClass=0x47 Protocol=0xD0 (GIP audio base)
Interface 1 alt 1: Class=0xFF SubClass=0x47 Protocol=0xD0 (GIP audio active)
  EP 0x03 OUT Isochronous  228 bytes  1ms
  EP 0x83 IN  Isochronous  228 bytes  1ms

Interface 2 alt 0/1: Class=0xFF SubClass=0x47 Protocol=0xD0 (GIP bulk)
  EP 0x01 OUT Bulk  64 bytes
  EP 0x81 IN  Bulk  64 bytes
```
