/*
 * drum_config_serial.h - CDC serial config mode for drum kit
 */

#ifndef _DRUM_CONFIG_SERIAL_H_
#define _DRUM_CONFIG_SERIAL_H_

#include "drum_config.h"

// Run the config-mode main loop. Reboots via watchdog on REBOOT command
// or if the serial connection is idle for too long.
void drum_config_mode_main(drum_config_t *config);

#endif /* _DRUM_CONFIG_SERIAL_H_ */
